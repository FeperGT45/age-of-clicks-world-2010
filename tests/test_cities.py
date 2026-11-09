import csv
import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build import make_world, svg_map
from cities import make_cities, write_city_assets


class CityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings, cls.world = make_world()
        cls.cities, cls.report = make_cities(cls.settings, cls.world)
        cls.by_id = {f["properties"]["source_id"]: f for f in cls.cities["features"]}

    def test_complete_selection_of_source_2010_centres(self):
        with (ROOT / "data/vendor/ghsl_mtuc_2010.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        expected = {r["source_id"] for r in rows if r["population_2010"]}
        self.assertEqual(set(self.by_id), expected)
        self.assertEqual(len(self.by_id), len(self.cities["features"]))
        self.assertEqual(len(expected), 9793)
        self.assertNotIn("1", self.by_id)  # Apia crosses the dataset's urban threshold later.
        self.assertEqual(self.report["source_records"],
                         self.report["included_urban_centres"] + self.report["excluded_without_2010_population"])

    def test_historical_country_ownership_and_names(self):
        for ident, tag in [("986", "SDN"), ("3669", "UKR"), ("3856", "UKR"), ("2576", "RUS")]:
            self.assertEqual(self.by_id[ident]["properties"]["country_tag"], tag)
        for ident, name in [("3618", "Dnipropetrovsk"), ("3461", "Dniprodzerzhynsk"),
                            ("2953", "Kirovohrad"), ("2045", "Port Elizabeth"), ("9558", "Bangalore")]:
            self.assertEqual(self.by_id[ident]["properties"]["name"], name)
        moscow = self.by_id["2576"]
        self.assertEqual(moscow["properties"]["population_2010"], 12727784)
        lon, lat = moscow["geometry"]["coordinates"]
        self.assertTrue(37 < lon < 38 and 55 < lat < 56)

    def test_coordinates_population_and_unresolved_data(self):
        counts = Counter()
        damaged = 0
        for feature in self.cities["features"]:
            p = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"]
            self.assertTrue(math.isfinite(lon) and -180 <= lon <= 180)
            self.assertTrue(math.isfinite(lat) and -90 <= lat <= 90)
            self.assertGreater(p["population_2010"], 0)
            self.assertEqual(p["geometry_epoch"], 2010)
            self.assertLessEqual(p["urban_first_epoch"], 2010)
            self.assertGreaterEqual(p["urban_last_epoch"], 2010)
            if p["country_tag"] is None:
                self.assertEqual(p["country_assignment"], "unresolved")
            if p["name_status"] == "missing_or_damaged_source_name":
                damaged += 1
                self.assertTrue(p["name"].startswith("GHSL urban centre "))
            counts[p["country_tag"]] += 1
        self.assertEqual(counts[None], self.report["unresolved_country_count"])
        self.assertEqual(damaged, self.report["missing_or_damaged_name_count"])
        for tag, count in self.report["by_country"].items():
            self.assertEqual(counts[tag], count)
        self.assertFalse(self.report["complete_world_city_census"])

    def test_csv_geojson_and_map_contain_the_same_set(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_city_assets(output, self.cities, self.report)
            with (output / "cities_2010.csv").open(encoding="utf-8", newline="") as handle:
                csv_ids = {r["id"] for r in csv.DictReader(handle)}
            geojson = json.loads((output / "cities_2010.geojson").read_text(encoding="utf-8"))
            geojson_ids = {f["properties"]["id"] for f in geojson["features"]}
            self.assertEqual(csv_ids, geojson_ids)
            svg = ET.fromstring(svg_map(self.settings, self.world, self.cities))
            ns = {"s": "http://www.w3.org/2000/svg"}
            city_group = svg.find("s:g[@id='cities']", ns)
            self.assertEqual({node.attrib["id"] for node in city_group}, geojson_ids)


if __name__ == "__main__":
    unittest.main()
