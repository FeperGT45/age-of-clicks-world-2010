#!/usr/bin/env python3
"""Reduce the official GHSL MTUC archive to reproducible city source columns.

Optional import dependencies are in requirements-import.txt. Normal builds use
only the resulting CSV and Python's standard library.
"""
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from pyproj import Transformer
from shapely import from_wkb, make_valid

ROOT = Path(__file__).resolve().parents[1]
URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
       "GHS_UCDB_GLOBE_R2024A/GHS_UCDB_MTUC_GLOBE_R2024A/V1-2/"
       "GHS_UCDB_MTUC_GLOBE_R2024A_V1_2.zip")
GPKG = "GHS_UCDB_MTUC_GLOBE_R2024A.gpkg"
FIELDS = ["source_id", "name_source_2025", "country_source_2025",
          "urban_first_epoch", "urban_last_epoch", "population_2010",
          "area_km2_2010", "longitude_2010", "latitude_2010"]


def read_geometry(blob):
    if blob[:2] != b"GP":
        raise ValueError("Expected a GeoPackage geometry")
    envelope = (blob[3] >> 1) & 7
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    return from_wkb(blob[8 + envelope_bytes[envelope]:])


def import_archive(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory() as temporary:
        # Extract exactly this known file, never arbitrary archive paths.
        gpkg_path = Path(temporary) / GPKG
        gpkg_path.write_bytes(z.read(GPKG))
        with sqlite3.connect(gpkg_path) as connection:
            connection.row_factory = sqlite3.Row
            wkt = connection.execute(
                "SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id=54009"
            ).fetchone()[0]
            transformer = Transformer.from_crs(wkt, "EPSG:4326", always_xy=True)
            geometries = dict(connection.execute(
                "SELECT ID_UC_G0, geom FROM GHSL_UCDB_MTUC_2010_GLOBE_R2024"))
            records = connection.execute(
                'SELECT ID_MTUC_G0, GC_UCN_MAI_2025, GC_CNT_GAD_2025, '
                '"GC_UCB_YOB _2025", "GC_UCB_YOD _2025", '
                'MT_POP_TOT_2010, MT_UCA_KM2_2010 '
                'FROM GHSL_UCDB_MTUC_GLOBE_R2024 ORDER BY ID_MTUC_G0').fetchall()
        csv_path = output / "ghsl_mtuc_2010.csv"
        repaired_ids = []
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for record in records:
                source_id, name, country, birth, death, population, area = record
                lon, lat = "", ""
                if population is not None and population > 0:
                    if source_id not in geometries:
                        raise ValueError(f"Missing 2010 geometry: {source_id}")
                    geometry = read_geometry(geometries[source_id])
                    if not geometry.is_valid:
                        geometry = make_valid(geometry)
                        repaired_ids.append(source_id)
                    if geometry.is_empty:
                        raise ValueError(f"Empty 2010 geometry: {source_id}")
                    point = geometry.representative_point()
                    lon_value, lat_value = transformer.transform(point.x, point.y)
                    if not (math.isfinite(lon_value) and math.isfinite(lat_value)):
                        raise ValueError(f"Invalid projection: {source_id}")
                    lon, lat = f"{lon_value:.6f}", f"{lat_value:.6f}"
                writer.writerow(dict(zip(FIELDS, [source_id, name or "", country or "",
                    birth, death, "" if population is None else round(population),
                    "" if area is None else area, lon, lat])))
        # The CSV is a column subset and uses derived representative points.
        metadata = {
            "dataset": "GHS_UCDB_MTUC_GLOBE_R2024A", "version": "V1_2",
            "source_url": URL, "archive_sha256": archive_sha,
            "gpkg_sha256": hashlib.sha256(gpkg_path.read_bytes()).hexdigest(),
            "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "source_records": len(records), "license": "CC-BY-4.0",
            "geometry_repaired_with_make_valid": repaired_ids,
            "copyright": "European Union, 1995-2026",
            "population_epoch": 2010, "geometry_epoch": 2010, "name_epoch": 2025,
            "point_method": "point on surface of 2010 urban geometry, inverse ESRI:54009 to EPSG:4326",
            "coverage": "urban centres defined by GHSL; not a census of all municipal cities and towns",
            "changes": "Selected columns; population rounded to persons; derived WGS84 representative points; all source rows retained."
        }
        (output / "ghsl_mtuc_2010.provenance.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(records)} source records into {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Official MTUC V1_2 ZIP (see URL in this script)")
    parser.add_argument("--output", type=Path, default=ROOT / "data/vendor")
    args = parser.parse_args()
    import_archive(args.archive, args.output)
