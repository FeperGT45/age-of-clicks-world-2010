"""Build a city reference layer with explicit historical and coverage limits."""
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inside_ring(point, ring):
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def country_at(point, world):
    """Only fill missing source countries, never snap across a coast or border."""
    candidates = set()
    for feature in world["features"]:
        geom = feature["geometry"]
        if geom["type"] != "MultiPolygon":
            continue
        for polygon in geom["coordinates"]:
            ring = polygon[0]
            if not (min(p[0] for p in ring) <= point[0] <= max(p[0] for p in ring)
                    and min(p[1] for p in ring) <= point[1] <= max(p[1] for p in ring)):
                continue
            if inside_ring(point, ring) and not any(inside_ring(point, h) for h in polygon[1:]):
                candidates.add(feature["properties"]["tag"])
    return next(iter(candidates)) if len(candidates) == 1 else None


def make_cities(settings, world):
    config = json.loads((ROOT / "data/cities.json").read_text(encoding="utf-8"))
    provenance = json.loads((ROOT / "data/vendor/ghsl_mtuc_2010.provenance.json").read_text(encoding="utf-8"))
    csv_path = ROOT / "data/vendor/ghsl_mtuc_2010.csv"
    if hashlib.sha256(csv_path.read_bytes()).hexdigest() != provenance["csv_sha256"]:
        raise ValueError("City source checksum mismatch; re-import or review provenance")
    source_countries = json.loads((ROOT / "data/vendor/ne_110m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    country_names = {f["properties"]["NAME_EN"]: f["properties"]["ADM0_A3"]
                     for f in source_countries["features"]}
    country_names.update({f["properties"]["name_en"]: f["properties"]["tag"]
                          for f in world["features"]})
    country_names.update(config["country_aliases"])
    valid_tags = {f["properties"]["tag"] for f in world["features"]}
    features, source_ids, overrides_used = [], set(), set()
    excluded = 0
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            source_id = row["source_id"]
            if source_id in source_ids:
                raise ValueError(f"Duplicate city source ID: {source_id}")
            source_ids.add(source_id)
            # Empty means not identified as an urban centre in 2010, NOT zero population.
            if not row["population_2010"]:
                excluded += 1
                continue
            population = int(row["population_2010"])
            birth, death = int(row["urban_first_epoch"]), int(row["urban_last_epoch"])
            lon, lat = float(row["longitude_2010"]), float(row["latitude_2010"])
            if not (population > 0 and birth <= 2010 <= death and math.isfinite(lon)
                    and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"Invalid city record: {source_id}")
            source_country = row["country_source_2025"]
            if source_country:
                if source_country not in country_names:
                    raise ValueError(f"Missing country alias: {source_country}")
                tag = country_names[source_country]
                tag = settings["merge_into"].get(tag, tag)
                assignment = "source_country_remapped_for_scenario"
            else:
                tag = country_at((lon, lat), world)
                assignment = "scenario_polygon" if tag else "unresolved"
            if tag is not None and tag not in valid_tags:
                raise ValueError(f"Invalid scenario country: {tag}")
            source_name = row["name_source_2025"]
            name = source_name
            name_ru = None
            name_status = "source_2025_needs_historical_review"
            if not source_name.strip() or "?" in source_name:
                name = f"GHSL urban centre {source_id}"
                name_status = "missing_or_damaged_source_name"
            if source_id in config["name_overrides"]:
                override = config["name_overrides"][source_id]
                if override["expected_source_name"] != source_name:
                    raise ValueError(f"Historical city name patch mismatch: {source_id}")
                name, name_ru = override["name"], override["name_ru"]
                name_status = "historical_override"
                overrides_used.add(source_id)
            features.append({"type": "Feature", "properties": {
                "id": "ghsl-mtuc-" + source_id, "name": name, "name_ru": name_ru,
                "source_name_2025": source_name or None, "name_status": name_status,
                "country_tag": tag, "country_assignment": assignment,
                "source_country_2025": source_country or None,
                "population_2010": population, "population_scope": "urban_centre",
                "area_km2_2010": float(row["area_km2_2010"]),
                "urban_first_epoch": birth, "urban_last_epoch": death,
                "geometry_epoch": 2010, "point_method": "urban_area_point_on_surface",
                "source_id": source_id},
                "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    if overrides_used != set(config["name_overrides"]):
        raise ValueError("Unused city name overrides")
    features.sort(key=lambda f: int(f["properties"]["source_id"]))
    if len(source_ids) != provenance["source_records"]:
        raise ValueError("City source row count mismatch")
    counts = Counter(f["properties"]["country_tag"] for f in features)
    report = {
        "reference_year": 2010, "source": config["source"],
        "source_records": len(source_ids), "included_urban_centres": len(features),
        "excluded_without_2010_population": excluded, "native_import_ready": False,
        "complete_world_city_census": False,
        "countries_with_records": len([k for k in counts if k is not None]),
        "unresolved_country_count": counts[None],
        "historical_name_overrides": len(overrides_used),
        "missing_or_damaged_name_count": sum(f["properties"]["name_status"] == "missing_or_damaged_source_name" for f in features),
        "by_country": {tag: counts[tag] for tag in sorted(valid_tags)},
        "source_url": provenance["source_url"], "license": "CC-BY-4.0",
        "credit": "European Union / JRC, GHSL UCDB R2024A V1_2; reduced and adapted for this scenario",
        "limits": ["Urban centres, not all municipal cities or villages",
                   "Names and source country labels are from 2025; only explicit overrides are historically reviewed",
                   "Urban detection epoch is not a city foundation date",
                   "Coordinates represent 2010 urban geometry, not exact city halls or historical capitals",
                   "A 2010 population estimate is not necessarily a census or a value for 1 January"]}
    return {"type": "FeatureCollection", "attribution": {
        "credit": report["credit"], "source_url": provenance["source_url"],
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "changes": "Selected 2010 records; derived points; remapped countries and explicit historical names",
        "name_epoch_without_override": 2025, "population_epoch": 2010,
        "complete_world_city_census": False}, "features": features}, report


def write_city_assets(output, cities, report):
    (output / "cities_2010.geojson").write_text(
        json.dumps(cities, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "cities_2010.report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["id", "name", "name_ru", "country_tag", "longitude", "latitude",
              "population_2010", "area_km2_2010", "name_status", "country_assignment",
              "source_name_2025", "source_country_2025", "geometry_epoch", "point_method"]
    with (output / "cities_2010.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for feature in cities["features"]:
            props = feature["properties"]
            row = {key: props[key] for key in fields if key in props}
            row["longitude"], row["latitude"] = feature["geometry"]["coordinates"]
            writer.writerow(row)
