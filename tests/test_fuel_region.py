"""Решение 235: цена топлива «в крыло» = спот USGC × множитель региона аэропорта вылета."""
from __future__ import annotations

import pathlib
import unittest

import yaml

from flightcostapp import econ

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FuelRegion(unittest.TestCase):
    def setUp(self):
        # Без локального ряда Platts (его нет в репозитории): статические множители статьи.
        self._p = econ.PLATTS_LOCAL_PATH
        econ.PLATTS_LOCAL_PATH = ROOT / "data/fuel/_нет_такого.local.json"
        econ._FUEL_REG_CACHE.pop("platts", None)

    def tearDown(self):
        econ.PLATTS_LOCAL_PATH = self._p
        econ._FUEL_REG_CACHE.pop("platts", None)

    def test_spot_shift_with_local_ratios(self):
        """Решение 236: со свежим соотношением спота k = addon × r(сейчас); без addon — статический k."""
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"as_of": "2026-10-23", "ratio_to_north_america": {"europe": 1.05, "asia": 0.9}}, fh)
        econ.PLATTS_LOCAL_PATH = pathlib.Path(fh.name)
        econ._FUEL_REG_CACHE.pop("platts", None)
        doc = yaml.safe_load((ROOT / "data/fuel/_regional.yaml").read_text(encoding="utf-8"))
        k, code, r = econ.fuel_region_k("EDDF")
        self.assertAlmostEqual(k, doc["regions"]["europe"]["addon"] * 1.05)
        self.assertEqual(r["spot_as_of"], "2026-10-23")
        self.assertEqual(econ.fuel_region_k("KJFK")[0], doc["regions"]["north_america"]["k"])
        self.assertEqual(econ.fuel_region_k("UUEE")[0], doc["regions"]["russia_centre"]["k"])

    def test_india_domestic_vat_by_state_and_date(self):
        """Решение 236: цена IOCL Дели без VAT Дели × (1 + VAT штата вылета на дату)."""
        dl = econ.india_domestic_atf("VIDP", "2026-10-30")
        base = dl["delhi"] / 1.07
        self.assertAlmostEqual(dl["inr_kl"], base * 1.07)
        self.assertEqual(econ.india_domestic_atf("VIDP", "2026-12-01")["vat_pct"], 25)   # снижение кончилось
        self.assertEqual(econ.india_domestic_atf("VOMM", "2026-10-30")["vat_pct"], 29)
        self.assertEqual(econ.india_domestic_atf("VOMM", "2026-11-01")["vat_pct"], 16)
        x = econ.india_domestic_atf("VAXX", "2026-10-30")
        self.assertFalse(x["known"])
        self.assertAlmostEqual(x["inr_kl"], base * 1.18)

    def test_ru_damper(self):
        """Демпфер последнего опубликованного месяца не позже даты расчёта + возврат акциза 3 024 руб/т."""
        total, month, d = econ.ru_fuel_compensation("2026-10-30")
        self.assertEqual(month, "2026-09")
        self.assertAlmostEqual(total - d, 3024)
        self.assertEqual(econ.ru_fuel_compensation("2026-02-15")[1:], ("2026-02", 1779.7))
        self.assertIsNone(econ.ru_fuel_compensation("2020-01-01"))
    def test_regions_by_prefix(self):
        for icao, reg in (("EDDF", "europe"), ("GCLP", "europe"), ("LLBG", "europe"), ("KJFK", "north_america"),
                          ("OMDB", "middle_east"), ("VIDP", "india"), ("VTBS", "asia_oceania"), ("ZBAA", "asia_oceania"),
                          ("UAAA", "kz_cis"), ("UUEE", "russia_centre"), ("UNNT", "russia_siberia"),
                          ("UHWW", "russia_far_east"), ("FAOR", "africa"), ("SBGR", "latam"), ("MMMX", "latam")):
            self.assertEqual(econ.fuel_region_k(icao)[1], reg, icao)

    def test_file_matches_article(self):
        """Множители в данных = таблица статьи (файл собирает её сборщик, руками не правится)."""
        doc = yaml.safe_load((ROOT / "data/fuel/_regional.yaml").read_text(encoding="utf-8"))
        for r in doc["regions"].values():
            self.assertTrue(r["range"][0] <= r["k"] <= r["range"][1], r["name"])
            self.assertIn(r["confidence"], ("средняя", "низкая", "заглушка"))
        self.assertEqual(econ.fuel_region_k("EDDF")[0], doc["regions"]["europe"]["k"])

    def test_unknown_airport_has_no_correction(self):
        self.assertEqual(econ.fuel_region_k("XXXX")[:2], (1.0, "unknown"))


if __name__ == "__main__":
    unittest.main()
