"""Compile dated diplomatic evidence and explicit game estimates, offline."""
import csv
import datetime as dt
import hashlib
import json
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pair(a, b):
    if a == b:
        raise ValueError(f"Self relation: {a}")
    return tuple(sorted((a, b)))


def agreement_pairs(agreement):
    scope = agreement["pair_scope"]
    if scope == "all_pairs":
        return {pair(a, b) for a, b in combinations(agreement["members"], 2)}
    if scope == "explicit":
        return {pair(a, b) for a, b in agreement["active_pairs"]}
    if scope == "between_sides":
        left, right = agreement["sides"]
        return {pair(a, b) for a, b in product(left, right)}
    raise ValueError(f"Invalid pair scope: {scope}")


def vote_alignment(first, second, minimum):
    """Observed votes only. Yes=1, abstain=0, no=-1; no imputed absences."""
    common = first.keys() & second.keys()
    if len(common) < minimum:
        return None, len(common)
    return 1 - sum(abs(first[k] - second[k]) for k in common) / len(common), len(common)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_diplomacy(settings, world):
    config = read_json(ROOT / "data/diplomacy.json")
    provenance = read_json(ROOT / "data/vendor/diplomacy.provenance.json")
    if config["as_of"] != settings["start_date"] or config["as_of"] != provenance["as_of"]:
        raise ValueError("Diplomacy snapshot does not match scenario start")
    if settings.get("diplomacy_file") != "diplomacy_2010.json":
        raise ValueError("Scenario diplomacy asset link does not match the compiled filename")
    for name, checksum in provenance["sha256"].items():
        if hashlib.sha256((ROOT / "data/vendor" / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Diplomacy source checksum mismatch: {name}")
    tags = {f["properties"]["tag"] for f in world["features"]}
    if len(tags) != len(world["features"]):
        raise ValueError("Duplicate country tags")
    sources = config["sources"]

    def check_sources(ids):
        if not ids or not set(ids) <= sources.keys():
            raise ValueError(f"Invalid diplomacy citations: {ids}")

    agreements = config["agreements"]
    agreement_ids = [a["id"] for a in agreements]
    if len(agreement_ids) != len(set(agreement_ids)):
        raise ValueError("Duplicate agreement ID")
    defense, trade, cooperation = defaultdict(list), defaultdict(list), defaultdict(list)
    snapshot = dt.date.fromisoformat(config["as_of"])
    for agreement in agreements:
        members = agreement["members"]
        if len(members) < 2 or len(members) != len(set(members)) or not set(members) <= tags:
            raise ValueError(f"Invalid agreement membership: {agreement['id']}")
        check_sources(agreement["source_ids"])
        if agreement["status"] != "in_force":
            raise ValueError("Only active agreements belong in this snapshot")
        if "in_force_from" in agreement and dt.date.fromisoformat(agreement["in_force_from"]) > snapshot:
            raise ValueError(f"Future agreement: {agreement['id']}")
        for pending in agreement.get("pending_members", []):
            if pending["tag"] in members or pending["tag"] not in tags or dt.date.fromisoformat(pending["in_force_from"]) <= snapshot:
                raise ValueError(f"Incorrect pending membership: {agreement['id']}")
        pairs = agreement_pairs(agreement)
        if any(a not in members or b not in members for a, b in pairs):
            raise ValueError("Agreement pair outside its membership")
        if agreement["pair_scope"] == "between_sides":
            sides = agreement["sides"]
            if set(sides[0]) & set(sides[1]) or set(sides[0] + sides[1]) != set(members):
                raise ValueError("Invalid agreement sides")
        for a, b in agreement.get("suspended_pairs", []):
            if pair(a, b) in pairs:
                raise ValueError("Suspended alliance pair is active")
        if agreement["id"] in settings["blocs"] and set(members) != set(settings["blocs"][agreement["id"]]):
            raise ValueError("Legacy bloc membership differs from diplomacy source")
        target = defense if agreement["mutual_defense"] else trade if agreement["trade_preference"] else cooperation
        for key in pairs:
            target[key].append(agreement["id"])

    raw_countries = read_json(ROOT / "data/vendor/ne_110m_admin_0_countries.geojson")["features"]
    iso2, country_names = {}, {}
    for feature in raw_countries:
        p = feature["properties"]
        owner = settings["merge_into"].get(p["ADM0_A3"], p["ADM0_A3"])
        country_names[p["NAME_EN"]] = owner
        for column in ["ISO_A2", "ISO_A2_EH"]:
            value = p.get(column)
            if isinstance(value, str) and len(value) == 2:
                iso2[value] = owner
    iso2.update(config["iso2_overrides"])
    country_names.update({f["properties"]["name_en"]: f["properties"]["tag"] for f in world["features"]})
    country_names.update(config["cow_name_aliases"])

    votes = defaultdict(dict)
    roll_dates, vote_rows = {}, 0
    mapping_notes = []
    with (ROOT / "data/vendor/un_votes_2009.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            date = dt.date.fromisoformat(row["date"])
            if date.year != 2009 or date >= snapshot:
                raise ValueError("Vote outside the pre-start calendar year")
            code = row["country_code"]
            tag = iso2.get(code)
            if tag not in tags:
                raise ValueError(f"Unmapped UN voting country: {code}")
            rcid = int(row["rcid"])
            if rcid in votes[tag]:
                raise ValueError(f"Duplicate UN vote: {tag}, {rcid}")
            if rcid in roll_dates and roll_dates[rcid] != row["date"]:
                raise ValueError("Conflicting UN roll call dates")
            value = {"yes": 1, "abstain": 0, "no": -1}.get(row["vote"])
            if value is None:
                raise ValueError("Unknown/absent votes must not be treated as abstentions")
            votes[tag][rcid] = value
            roll_dates[rcid] = row["date"]
            vote_rows += 1
    if vote_rows != provenance["vote_rows"] or len(roll_dates) != provenance["roll_calls"]:
        raise ValueError("UN source count mismatch")
    if "YU" in config["iso2_overrides"]:
        mapping_notes.append("unvotes labels COW code 345 as Yugoslavia/YU even in 2009; mapped to Serbia/SRB, not to a fictitious Yugoslavia")

    formal = []
    cow_by_pair = defaultdict(list)
    with (ROOT / "data/vendor/cow_alliances_2010.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            def observed_date(prefix):
                if not row[prefix + "year"]:
                    return None
                return dt.date(int(row[prefix + "year"]), int(row[prefix + "month"] or 1),
                               int(row[prefix + "day"] or 1))
            start, end = observed_date("dyad_st_"), observed_date("dyad_end_")
            if start is None or start > snapshot or (end is not None and end < snapshot):
                raise ValueError("Inactive formal treaty in snapshot source")
            names = [row["state_name1"], row["state_name2"]]
            mapped = [country_names.get(n) for n in names]
            if any(t not in tags for t in mapped):
                raise ValueError(f"Unmapped COW countries: {names}")
            key = pair(*mapped)
            flags = {field: row[field] == "1" for field in ["defense", "neutrality", "nonaggression", "entente"]}
            record = dict(treaty_id=row["version4id"], country_a=key[0], country_b=key[1],
                          source_state_1=names[0], source_state_2=names[1], **flags,
                          asymmetric=row["asymmetric"] == "1", source_id="COW",
                          observed_start_date=start.isoformat(),
                          observed_end_date=end.isoformat() if end else None,
                          left_censored=row["left_censor"] == "1",
                          right_censored=row["right_censor"] == "1",
                          legal_scope_individually_reviewed=False,
                          predecessor_name_present=any(n in {"Yugoslavia", "German Federal Republic"} for n in names))
            formal.append(record)
            cow_by_pair[key].append(record)
    if len(formal) != provenance["cow_rows"]:
        raise ValueError("COW source count mismatch")

    overrides = {}
    for override in config["bilateral_overrides"]:
        key = pair(*override["countries"])
        if not set(key) <= tags or key in overrides:
            raise ValueError("Invalid or duplicate bilateral override")
        if not -100 <= override["game_score"] <= 100:
            raise ValueError("Relation score outside scale")
        check_sources(override["source_ids"])
        overrides[key] = override

    model = config["relation_model"]
    relations = []
    for key in combinations(sorted(tags), 2):
        a, b = key
        alignment, common = vote_alignment(votes[a], votes[b], model["min_common_votes"])
        base = round(model["alignment_scale"] * alignment) if alignment is not None else None
        score = base
        basis = ["un_votes_2009_proxy"] if base is not None else []
        citations = {"UNVOTES"} if base is not None else set()
        if defense[key]:
            score = max(score if score is not None else 0, model["defense_floor"])
            basis.append("reviewed_defense_floor_game_rule")
        if trade[key]:
            score = (score if score is not None else 0) + model["trade_bonus"]
            basis.append("trade_bonus_game_rule")
        for agreement in agreements:
            if agreement["id"] in defense[key] or agreement["id"] in trade[key]:
                citations.update(agreement["source_ids"])
        override = overrides.get(key)
        status, diplomatic, war = "not_individually_reviewed", "not_reviewed", None
        reason = ""
        if override:
            score = override["game_score"]
            status = override["political_status"]
            diplomatic = override["diplomatic_relations"]
            war = override["active_interstate_war"]
            reason = override["reason_ru"]
            basis.append("historical_context_game_override")
            citations.update(override["source_ids"])
        score = max(-100, min(100, score)) if score is not None else None
        relations.append(dict(country_a=a, country_b=b, relation_score=score,
            score_status="game_estimate" if score is not None else "unknown",
            political_status=status, diplomatic_relations=diplomatic,
            active_interstate_war=war, vote_alignment=round(alignment, 6) if alignment is not None else None,
            common_votes_2009=common, base_vote_score=base,
            defense_agreements=sorted(defense[key]), trade_agreements=sorted(trade[key]),
            cooperation_forums=sorted(cooperation[key]),
            cow_treaty_ids=sorted({r["treaty_id"] for r in cow_by_pair[key]}),
            cow_formal_defense_indicator=any(r["defense"] for r in cow_by_pair[key]),
            basis=basis, source_ids=sorted(citations), reason_ru=reason))
    report = dict(as_of=config["as_of"], native_import_ready=False, countries=len(tags),
                  pairs=len(relations), named_agreements=len(agreements),
                  mutual_defense_arrangements=sum(a["mutual_defense"] for a in agreements),
                  trade_arrangements=sum(a["trade_preference"] for a in agreements),
                  votes_2009=vote_rows, roll_calls_2009=len(roll_dates), un_countries=len([t for t in tags if votes[t]]),
                  cow_dyadic_records=len(formal), cow_treaties=len({r["treaty_id"] for r in formal}),
                  historical_bilateral_overrides=len(overrides),
                  estimated_pairs=sum(r["relation_score"] is not None for r in relations),
                  unknown_score_pairs=sum(r["relation_score"] is None for r in relations),
                  diplomatic_status_not_reviewed=sum(r["diplomatic_relations"] == "not_reviewed" for r in relations),
                  objective_bilateral_ratings=False, exhaustive_trade_treaty_register=False,
                  un_date_min=min(roll_dates.values()), un_date_max=max(roll_dates.values()),
                  mapping_notes=mapping_notes, coverage_note_ru=config["coverage_note_ru"])
    return config, relations, formal, report


def write_diplomacy_assets(output, config, relations, formal, report):
    def write_json(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_json("diplomacy_2010.json", {**config, "relations_file": "relations_2010.csv",
        "formal_treaties_file": "formal_treaties_2010.csv",
        "note": "COW reference commitments do not automatically activate game alliances"})
    write_json("diplomacy_2010.report.json", report)
    for name, rows in [("relations_2010.csv", relations), ("formal_treaties_2010.csv", formal)]:
        with (output / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ";".join(v) if isinstance(v, list) else
                    "unknown" if v is None and k == "active_interstate_war" else
                    str(v).lower() if isinstance(v, bool) else v for k, v in row.items()})
    summary = ["# Дипломатия — 1 января 2010 года", "",
        f"{report['pairs']} пар стран; {report['named_agreements']} именованных соглашений; "
        f"{report['cow_treaties']} формальных договоров COW в справочнике.", "",
        "Числовые отношения — игровые оценки. Составы, правовые типы и примечания см. в источниках. "
        "Полнота реестра всех торговых договоров не заявляется. Нативный импорт ещё не реализован.", "",
        "| Объединение / соглашение | Тип | Участники сценария |", "| --- | --- | --- |"]
    for a in config["agreements"]:
        summary.append(f"| {a['name_ru']} | {a['kind']} | {', '.join(a['members'])} |")
    summary.extend(["", "Источники, ограничения и правила оценок: `docs/DIPLOMACY.md`.", ""])
    (output / "diplomacy_2010.summary.md").write_text("\n".join(summary), encoding="utf-8")
