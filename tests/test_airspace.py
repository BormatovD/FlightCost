"""Два слоя границ зон (решение 162) — без базы, на крошечных полигонах.

EUROCONTROL главнее там, где он выставляет счёт (`prefer`); вне этого —
границы сообщества; без мирового файла всё считается как прежде. Каждое
правило проверяется точкой, которую два слоя относят к разным зонам.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import airspace as A                   # noqa: E402

try:
    import shapely  # noqa: F401
    HAVE_SHAPELY = True
except ImportError:
    HAVE_SHAPELY = False


def box(lat0, lon0, lat1, lon1):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1],
                                                [lon0, lat1], [lon0, lat0]]]}


def ring(lat0, lon0, lat1, lon1):
    return [[lat0, lon0], [lat0, lon1], [lat1, lon1], [lat1, lon0], [lat0, lon0]]


@unittest.skipUnless(HAVE_SHAPELY, "нужен shapely")
class TwoLayers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(cls.tmp.name)
        # EUROCONTROL: настоящая зона ED (0..10 с.ш., 0..10 в.д.) и
        # заглушка VV «регион» 0..10 с.ш., 10..40 в.д.
        cls.euro = d / "fir_zones.json"
        cls.euro.write_text(json.dumps({"source": "euro-test", "zones": [
            {"zone": "ED", "airspace": "EDTEST", "name": "T", "fl_min": 0, "fl_max": 999,
             "geometry": box(0, 0, 10, 10)},
            {"zone": "VV", "airspace": "VVVVFIR", "name": "V REGION", "fl_min": 0,
             "fl_max": 999, "geometry": box(0, 10, 10, 40)},
        ]}), encoding="utf-8")
        # Мир: ED чуть иначе (0..10, 0..12 — спорная полоса 10..12),
        # VI 0..10 × 12..25, вложенный VIUX внутри VI, ZW 25..40.
        cls.world = d / "zones_world.json"
        cls.world.write_text(json.dumps({"schema": "fca.zones/1", "source": "world-test",
                                         "zones": [
            {"id": "EDGG", "prefix": "ED", "rings": [ring(0, 0, 10, 12)]},
            {"id": "VIDF", "prefix": "VI", "rings": [ring(0, 12, 10, 25)]},
            {"id": "VIUX", "prefix": "VU", "rings": [ring(3, 15, 6, 18)]},
            {"id": "ZWWW", "prefix": "ZW", "rings": [ring(0, 25, 10, 40)]},
        ]}), encoding="utf-8")
        cls.none = d / "nope.json"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cross(self, lon0, lon1, **kw):
        # Путь вдоль 5° с.ш. от lon0 до lon1, ~1 nm шаг
        nm = abs(lon1 - lon0) * 60 * 0.9962
        return A.crossing(5, lon0, 5, lon1, nm, path=self.euro, step_nm=1.0, **kw)

    def test_without_world_file_old_behaviour(self):
        c = self.cross(0, 40, world_path=self.none, prefer={"ED"})
        self.assertEqual(set(c.zones), {"ED", "VV"})
        self.assertEqual(set(c.by_layer), {"eurocontrol"})

    def test_prefer_keeps_eurocontrol_where_it_bills(self):
        c = self.cross(0, 40, world_path=self.world, prefer={"ED"})
        self.assertNotIn("VV", c.zones, "заглушка EUROCONTROL уступила мировому слою")
        self.assertIn("VI", c.zones)
        self.assertIn("ZW", c.zones)
        # спорная полоса 10..12: EUROCONTROL говорит VV (не в prefer) → мир → ED
        # Итого ED по EUROCONTROL 0..10 плюс по миру 10..12 ≈ 12/40 пути
        self.assertAlmostEqual(c.zones["ED"] / c.total_nm, 12 / 40, delta=0.02)
        self.assertGreater(c.by_layer["eurocontrol"], 0)
        self.assertGreater(c.by_layer["community"], 0)

    def test_without_prefer_world_wins_everywhere(self):
        c = self.cross(0, 40, world_path=self.world)
        self.assertEqual(set(c.by_layer), {"community"})
        self.assertAlmostEqual(c.zones["ED"] / c.total_nm, 12 / 40, delta=0.02)

    def test_nested_fir_smaller_wins(self):
        c = A.crossing(4.5, 14, 4.5, 20, 6 * 60, path=self.euro, world_path=self.world,
                       step_nm=1.0, prefer=set())
        self.assertIn("VU", c.zones, "вложенный FIR не победил внешний")
        self.assertAlmostEqual(c.zones["VU"] / c.total_nm, 3 / 6, delta=0.03)

    def test_outside_everything_is_unassigned(self):
        c = A.crossing(50, 0, 50, 10, 600, path=self.euro, world_path=self.world,
                       step_nm=5.0, prefer={"ED"})
        self.assertEqual(c.zones, {})
        self.assertAlmostEqual(c.unassigned_nm, 600)
        self.assertEqual(set(c.by_layer), {"none"})


class BillingZones(unittest.TestCase):

    def test_reads_crco_keys_and_survives_missing_table(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE facts (domain, key, source_id, valid_to)")
        db.executemany("INSERT INTO facts VALUES (?,?,?,NULL)", [
            ("enroute_rate", "ED", "crco_enroute_rates"),
            ("enroute_rate", "LE/national/domestic", "crco_enroute_rates"),
            ("enroute_rate", "UU", "fas_ans_rates"),
            ("airport", "EDDF", "ourairports")])

        class S:
            pass
        s = S(); s.db = db
        self.assertEqual(A.billing_zones(s), {"ED", "LE"})
        db.execute("DROP TABLE facts")
        self.assertEqual(A.billing_zones(s), set(), "без таблицы — пусто, не падение")
        db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
