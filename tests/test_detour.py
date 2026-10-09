"""Обход закрытого неба и разбор мировых границ FIR — без базы и без сети.

Полигоны синтетические и маленькие, чтобы каждое свойство проверялось
отдельно: прямая свободна — обход не строится; прямая через зону — путь
найден, зону не задевает, не короче прямой; отрезанный пункт назначения —
честный отказ; зазор выдержан.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import detour as D                      # noqa: E402
from flightcostapp.parsers import fir_world as FW          # noqa: E402

# Квадрат «закрытого неба» 45–50 с.ш., 20–30 в.д.
BOX = {"XXXX": [[(45, 20), (50, 20), (50, 30), (45, 30), (45, 20)]]}
W = (47.5, 5.0)
E = (47.5, 45.0)


def rings(closed):
    import numpy as np
    return [np.asarray(r + ([r[0]] if r[0] != r[-1] else []), dtype=float)
            for rs in closed.values() for r in rs]


class Geometry(unittest.TestCase):

    def test_direct_free_is_returned_as_is(self):
        r = D.detour((40, 5), (40, 45), BOX)
        self.assertTrue(r.found)
        self.assertEqual(len(r.waypoints), 2)
        self.assertAlmostEqual(r.path_km, r.direct_km)
        self.assertEqual(r.avoided, [])

    def test_blocked_direct_gets_a_detour_that_misses_the_zone(self):
        r = D.detour(W, E, BOX)
        self.assertTrue(r.found)
        self.assertEqual(r.avoided, ["XXXX"])
        self.assertGreater(len(r.waypoints), 2)
        self.assertGreater(r.path_km, r.direct_km)
        self.assertLess(r.extra_share, 0.25, "обход квадрата 10° не может стоить четверть пути")
        rr = rings(BOX)
        for a, b in zip(r.waypoints, r.waypoints[1:]):
            self.assertFalse(D._arc_blocked(a, b, rr), f"участок {a}–{b} входит в зону")

    def test_buffer_is_respected(self):
        r = D.detour(W, E, BOX, buffer_km=40)
        rr = rings(BOX)[0]
        for lat, lon in r.waypoints[1:-1]:
            # ближайшая точка границы дальше зазора (в км по сфере, с запасом на дискретность)
            near = min(D.gc_km((lat, lon), (float(y), float(x))) for y, x in rr)
            self.assertGreater(near, 40 * 0.8)

    def test_enclosed_destination_is_an_honest_refusal(self):
        inside = (47.5, 25.0)
        r = D.detour(W, inside, BOX)
        self.assertFalse(r.found)
        self.assertTrue(any("не найден" in w for w in r.warnings))

    def test_two_zones_on_one_line(self):
        two = {"A": [[(45, 15), (50, 15), (50, 22), (45, 22)]],
               "B": [[(45, 28), (50, 28), (50, 35), (45, 35)]]}
        r = D.detour(W, E, two)                        # прямая режет обе
        self.assertTrue(r.found)
        self.assertEqual(r.avoided, ["A", "B"])
        rr = rings(two)
        for a, b in zip(r.waypoints, r.waypoints[1:]):
            self.assertFalse(D._arc_blocked(a, b, rr))

    def test_antimeridian_zone_is_skipped_with_warning(self):
        far = {"ZZZZ": [[(50, 170), (60, 170), (60, -170), (50, -170)]]}
        r = D.detour((40, 5), (40, 45), far)
        self.assertTrue(any("антимеридиан" in w for w in r.warnings))

    def test_simplify_keeps_endpoints_and_corners(self):
        ring = [(0, 0), (0, 0.001), (0, 10), (10, 10), (10, 0), (0, 0)]
        s = D._simplify(ring, 0.05)
        self.assertIn((0, 10), [tuple(p) for p in s])
        self.assertIn((10, 10), [tuple(p) for p in s])
        self.assertLess(len(s), len(ring))


class WorldParser(unittest.TestCase):

    def geojson(self, feats):
        return json.dumps({"type": "FeatureCollection", "features": feats}).encode()

    def feat(self, fid, oceanic="0", coords=None):
        coords = coords or [[[[20, 45], [30, 45], [30, 50], [20, 50], [20, 45]]]]
        return {"type": "Feature", "properties": {"id": fid, "oceanic": oceanic,
                                                  "label_lat": "47", "label_lon": "25"},
                "geometry": {"type": "MultiPolygon", "coordinates": coords}}

    def test_sectors_groups_and_oceanic_are_dropped(self):
        feats = [self.feat(m) for m in FW.MUST_HAVE]
        import itertools, string
        names = ("Z" + "".join(t) for t in itertools.product(string.ascii_uppercase, repeat=3))
        feats += [self.feat(next(names)) for _ in range(FW.MIN_ZONES)]
        feats += [self.feat("UAAA-A3A"), self.feat("UKR"), self.feat("NZZO", "1")]
        out, summary = FW.convert(self.geojson(feats))
        ids = {z["id"] for z in out["zones"]}
        self.assertIn("UAAA", ids)
        self.assertNotIn("UAAA-A3A", ids)
        self.assertNotIn("UKR", ids)
        self.assertNotIn("NZZO", ids)
        self.assertEqual((summary["sector"], summary["group"], summary["oceanic"]), (1, 1, 1))
        self.assertEqual(out["license"], "CC-BY-SA-4.0")
        z = next(z for z in out["zones"] if z["id"] == "UAAA")
        self.assertEqual(z["prefix"], "UA")
        self.assertEqual(z["rings"][0][0], z["rings"][0][-1], "кольцо замкнуто")
        self.assertEqual(z["rings"][0][0], [45.0, 20.0], "порядок [широта, долгота]")

    def test_wrong_file_is_refused(self):
        with self.assertRaises(ValueError):
            FW.convert(self.geojson([self.feat("UAAA")]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
