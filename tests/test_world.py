import hashlib
import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build import build, make_world, polygon_parts


def inside_ring(point, ring):
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def owns(feature, point):
    return any(inside_ring(point, p[0]) and not any(inside_ring(point, hole) for hole in p[1:])
               for p in polygon_parts(feature["geometry"]))


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings, cls.world = make_world()
        cls.features = {f["properties"]["tag"]: f for f in cls.world["features"]}

    def test_2010_ownership_at_reference_locations(self):
        for tag, point in [("UKR", (34.1, 44.95)), ("SDN", (31.6, 4.85)),
                           ("DNK", (-42, 72)), ("USA", (-66.1, 18.2)),
                           ("SOM", (45, 9.6))]:
            with self.subTest(tag=tag):
                self.assertTrue(owns(self.features[tag], point))
        self.assertFalse(owns(self.features["RUS"], (34.1, 44.95)))
        self.assertNotIn("SDS", self.features)
        self.assertNotIn("ATA", self.features)

    def test_2010_blocs(self):
        blocs = self.settings["blocs"]
        self.assertEqual(len(blocs["NATO"]), 28)
        self.assertEqual(len(blocs["EU"]), 27)
        self.assertIn("GBR", blocs["EU"])
        self.assertNotIn("HRV", blocs["EU"])
        for tag in ["FIN", "SWE", "MNE", "MKD"]:
            self.assertNotIn(tag, blocs["NATO"])
        self.assertIn("UZB", blocs["CSTO"])

    def test_geometry_and_small_states_are_explicit(self):
        for feature in self.world["features"]:
            geometry = feature["geometry"]
            if geometry["type"] == "Point":
                self.assertEqual(feature["properties"]["geometry_status"], "reference_point_only")
                continue
            for polygon in polygon_parts(geometry):
                for ring in polygon:
                    self.assertEqual(ring[0], ring[-1])
                    self.assertGreaterEqual(len(ring), 4)
                    for lon, lat in ring:
                        self.assertTrue(math.isfinite(lon) and -180 <= lon <= 180)
                        self.assertTrue(math.isfinite(lat) and -90 <= lat <= 90)
        self.assertEqual(self.features["SGP"]["geometry"]["type"], "Point")
        self.assertEqual(self.features["SWZ"]["properties"]["name_en"], "Swaziland")

    def test_build_is_reproducible_and_honest_about_native_status(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            aa, bb = Path(a), Path(b)
            build(aa)
            build(bb)
            self.assertEqual({p.name: p.read_bytes() for p in aa.iterdir()},
                             {p.name: p.read_bytes() for p in bb.iterdir()})
            manifest = json.loads((aa / "manifest.json").read_text())
            self.assertFalse(manifest["native_import_ready"])
            for name, sha in manifest["sha256"].items():
                self.assertEqual(hashlib.sha256((aa / name).read_bytes()).hexdigest(), sha)
            ET.parse(aa / "world_2010.svg")


if __name__ == "__main__":
    unittest.main()
