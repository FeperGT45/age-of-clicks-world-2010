#!/usr/bin/env python3
"""Reduce pinned UN voting and COW alliance sources; optional import only."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pyreadr

ROOT = Path(__file__).resolve().parents[1]
UN_COMMIT = "7eb7034314ff79c49c9e0785fcd9d216fa04cf14"
COW_URL = "https://correlatesofwar.org/wp-content/uploads/version4.1_csv.zip"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cow_date(row, prefix):
    if not row[prefix + "year"]:
        return None
    return dt.date(int(row[prefix + "year"]), int(row[prefix + "month"] or 1),
                   int(row[prefix + "day"] or 1))


def import_sources(votes_path, calls_path, cow_path, output):
    output.mkdir(parents=True, exist_ok=True)
    votes = pyreadr.read_r(str(votes_path))["un_votes"]
    calls = pyreadr.read_r(str(calls_path))["un_roll_calls"]
    calls = calls[calls["date"].map(lambda d: d.year == 2009)]
    dates = {int(r.rcid): r.date.isoformat() for r in calls.itertuples()}
    votes = votes[votes.rcid.isin(calls.rcid)]
    with (output / "un_votes_2009.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["rcid", "date", "country_code", "country_name", "vote"])
        for r in votes.sort_values(["rcid", "country_code"]).itertuples():
            writer.writerow([int(r.rcid), dates[int(r.rcid)], r.country_code, r.country, str(r.vote)])
    with zipfile.ZipFile(cow_path) as z:
        raw = z.read("version4.1_csv/alliance_v4.1_by_dyad.csv").decode("cp1252")
    reader = csv.DictReader(io.StringIO(raw))
    fields = reader.fieldnames
    snapshot = dt.date(2010, 1, 1)
    active = [r for r in reader if cow_date(r, "dyad_st_") <= snapshot and
              (cow_date(r, "dyad_end_") is None or cow_date(r, "dyad_end_") >= snapshot)]
    with (output / "cow_alliances_2010.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(active)
    metadata = {
        "as_of": snapshot.isoformat(), "vote_calendar_year": 2009,
        "unvotes_commit": UN_COMMIT,
        "votes_source_url": f"https://raw.githubusercontent.com/dgrtwo/unvotes/{UN_COMMIT}/data/un_votes.rda",
        "roll_calls_source_url": f"https://raw.githubusercontent.com/dgrtwo/unvotes/{UN_COMMIT}/data/un_roll_calls.rda",
        "un_original_source": "https://doi.org/10.7910/DVN/LEJUQZ",
        "un_credit": "Voeten, Strezhnev and Bailey; unvotes distribution by David Robinson (MIT)",
        "cow_source_url": COW_URL,
        "cow_credit": "Correlates of War Formal Alliances v4.1; Douglas M. Gibler",
        "upstream_sha256": {"un_votes.rda": sha(votes_path), "un_roll_calls.rda": sha(calls_path),
                            "version4.1_csv.zip": sha(cow_path)},
        "sha256": {name: sha(output / name) for name in ["un_votes_2009.csv", "cow_alliances_2010.csv"]},
        "vote_rows": len(votes), "roll_calls": len(calls), "cow_rows": len(active),
        "changes": "UN: only observed yes/abstain/no votes in calendar year 2009; COW: date-filtered dyadic records active on 2010-01-01, end date inclusive. No copied treaty descriptions.",
        "cautions": ["UN voting alignment is not a bilateral diplomatic relationship rating",
                     "COW categories describe formal commitments, not automatic military support",
                     "COW predecessor state names and treaty succession require review"]}
    (output / "diplomacy.provenance.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(votes)} votes / {len(calls)} roll calls and {len(active)} formal treaty dyads")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("votes", type=Path)
    parser.add_argument("roll_calls", type=Path)
    parser.add_argument("cow_zip", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data/vendor")
    args = parser.parse_args()
    import_sources(args.votes, args.roll_calls, args.cow_zip, args.output)
