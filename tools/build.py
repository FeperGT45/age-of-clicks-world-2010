#!/usr/bin/env python3
"""Build reference assets, never pretend to export an undocumented game format."""
import argparse
import copy
import csv
import hashlib
import html
import io
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/vendor/ne_110m_admin_0_countries.geojson"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_parts(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError(f"Unsupported geometry: {geometry['type']}")


def ring_bounds(ring):
    return [min(p[0] for p in ring), min(p[1] for p in ring),
            max(p[0] for p in ring), max(p[1] for p in ring)]


def country_color(tag):
    # Fixed per tag: adding a country never recolors other countries.
    digest = hashlib.sha256(tag.encode("ascii")).digest()
    return "#" + "".join(f"{64 + x % 160:02x}" for x in digest[:3])


def make_world():
    settings = read_json(ROOT / "data/scenario.json")
    raw = read_json(SOURCE)
    raw = {f["properties"]["ADM0_A3"]: copy.deepcopy(f) for f in raw["features"]}
    parts = {tag: polygon_parts(f["geometry"]) for tag, f in raw.items()}
    for patch in settings["geometry_patches"]:
        matches = [p for p in parts[patch["from"]]
                   if all(abs(a - b) < 0.00001 for a, b in
                          zip(ring_bounds(p[0]), patch["outer_ring_bounds"]))]
        if len(matches) != patch["expected_polygons"]:
            raise ValueError(f"Patch {patch['id']}: expected polygon not found")
        for poly in matches:
            parts[patch["from"]].remove(poly)
            parts[patch["to"]].append(poly)
    owners = defaultdict(list)
    source_tags = defaultdict(list)
    for tag, geometry in parts.items():
        if tag in settings["exclude"]:
            continue
        owner = settings["merge_into"].get(tag, tag)
        owners[owner].extend(geometry)
        source_tags[owner].append(tag)
    features = []
    for tag in sorted(owners):
        properties = raw[tag]["properties"]
        names = settings["names"].get(tag, {})
        features.append({"type": "Feature", "properties": {
            "tag": tag, "name_ru": names.get("ru", properties["NAME_RU"]),
            "name_en": names.get("en", properties["NAME_EN"]),
            "color": country_color(tag), "geometry_status": "generalized_polygon",
            "source_tags": sorted(source_tags[tag])},
            "geometry": {"type": "MultiPolygon", "coordinates": owners[tag]}})
    with (ROOT / "data/small_states.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["tag"] in owners:
                raise ValueError(f"Duplicate small state: {row['tag']}")
            features.append({"type": "Feature", "properties": {
                "tag": row["tag"], "name_ru": row["name_ru"], "name_en": row["name_en"],
                "color": country_color(row["tag"]), "geometry_status": "reference_point_only",
                "source_tags": []}, "geometry": {"type": "Point", "coordinates":
                    [float(row["longitude"]), float(row["latitude"])]}})
    features.sort(key=lambda f: f["properties"]["tag"])
    tags = {f["properties"]["tag"] for f in features}
    colors = [f["properties"]["color"] for f in features]
    if len(colors) != len(set(colors)) or settings["map"]["ocean"] in colors:
        raise ValueError("Ownership palette collision")
    for bloc, members in settings["blocs"].items():
        if len(members) != len(set(members)) or not set(members) <= tags:
            raise ValueError(f"Invalid bloc: {bloc}")
    for event in read_json(ROOT / "data/events.json")["events"]:
        if not set(event["countries"]) <= tags:
            raise ValueError(f"Unknown event country: {event['id']}")
    return settings, {"type": "FeatureCollection", "features": features}


def project(point, width, height):
    return ((point[0] + 180) * width / 360, (90 - point[1]) * height / 180)


def svg_map(settings, world):
    width, height = settings["map"]["width"], settings["map"]["height"]
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
              '<title id="title">Мир — 1 января 2010</title>',
              '<desc id="desc">Черновая карта. Малые государства показаны точками. Границы обобщены.</desc>',
              f'<rect width="{width}" height="{height}" fill="{settings["map"]["ocean"]}"/>']
    edges = defaultdict(set)
    markers = []
    for feature in world["features"]:
        props, geom = feature["properties"], feature["geometry"]
        label = html.escape(f'{props["name_ru"]} ({props["tag"]})')
        if geom["type"] == "Point":
            x, y = project(geom["coordinates"], width, height)
            markers.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{props["color"]}" stroke="#fff" stroke-width="0.8"><title>{label} — только точка, полигон ещё не готов</title></circle>')
            continue
        path = []
        for polygon in polygon_parts(geom):
            for ring in polygon:
                points = [project(point, width, height) for point in ring]
                path.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in points) + " Z")
                for a, b in zip(ring, ring[1:]):
                    key = tuple(sorted((tuple(a), tuple(b))))
                    edges[key].add(props["tag"])
        result.append(f'<path id="{props["tag"]}" d="{" ".join(path)}" fill="{props["color"]}" fill-rule="evenodd"><title>{label}</title></path>')
    # Only strokes between different owners. Merged Sudan has no internal border.
    border = []
    for (a, b), owners in edges.items():
        if len(owners) > 1:
            x, y = project(a, width, height)
            xx, yy = project(b, width, height)
            border.append(f"M{x:.2f},{y:.2f}L{xx:.2f},{yy:.2f}")
    result.append(f'<path d="{" ".join(border)}" fill="none" stroke="#172638" stroke-width="0.8"/>')
    result.extend(markers)
    result.append('</svg>')
    return "\n".join(result) + "\n"


def build(output):
    settings, world = make_world()
    output.mkdir(parents=True, exist_ok=True)
    def write_json(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_json("world_2010.geojson", world)
    write_json("scenario.source.json", settings)
    write_json("events.design.json", read_json(ROOT / "data/events.json"))
    (output / "world_2010.svg").write_text(svg_map(settings, world), encoding="utf-8")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["tag", "name_ru", "name_en", "color", "geometry_status", "blocs"])
    for feature in world["features"]:
        p = feature["properties"]
        writer.writerow([p["tag"], p["name_ru"], p["name_en"], p["color"], p["geometry_status"],
                         ";".join(b for b, m in settings["blocs"].items() if p["tag"] in m)])
    (output / "countries.csv").write_text(buffer.getvalue(), encoding="utf-8")
    files = ["world_2010.geojson", "scenario.source.json", "events.design.json", "world_2010.svg", "countries.csv"]
    write_json("manifest.json", {
        "format": settings["format"], "start_date": settings["start_date"],
        "native_import_ready": False, "polygon_entities": sum(f["geometry"]["type"] != "Point" for f in world["features"]),
        "point_only_entities": sum(f["geometry"]["type"] == "Point" for f in world["features"]),
        "sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in files}})
    print(f"Built {len(world['features'])} entities in {output}; native game import: pending")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    build(parser.parse_args().output)
