"""Каталог типов ВС (решение 223): data/aircraft/catalog/*.json.

Файлы собираются агентом и правятся руками — тест держит то, что иначе
ломается молча: файл не разбирается, ключ совпал с типом openap (тогда
паспорт каталога перезаписал бы физику библиотеки), тип в разработке без
статуса или вида данных, карточка без перечня пробелов.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.parsers.aircraft_user import (CATALOG, DATA_KINDS, REQUIRED,  # noqa: E402
                                                  STATUSES, _one)
from flightcostapp.store import Store                     # noqa: E402

CAT = ROOT / "data" / "aircraft" / "catalog"
FILES = sorted(CAT.glob("*.json"))


class Catalog(unittest.TestCase):

    def test_every_file_parses(self):
        self.assertTrue(FILES, "каталог пуст")
        for f in FILES:
            with self.subTest(f.name):
                d = json.loads(f.read_text(encoding="utf-8"))
                facts = _one(d, {"source_id": CATALOG})
                self.assertTrue(facts)
                self.assertEqual(f.stem, d["icao"].upper().replace(":", "_"))

    def test_status_and_kind_named(self):
        for f in FILES:
            m = json.loads(f.read_text(encoding="utf-8")).get("meta") or {}
            with self.subTest(f.name):
                self.assertIn(m.get("status"), STATUSES)
                self.assertIn(m.get("data_kind"), DATA_KINDS)
                self.assertTrue(m.get("field_sources"), "у чисел нет источников по полям")

    def test_no_overlap_with_openap(self):
        try:
            from openap import prop
        except ImportError:
            self.skipTest("openap не установлен")
        lib = {a.upper() for a in prop.available_aircraft()}
        keys = {json.loads(f.read_text(encoding="utf-8"))["icao"].upper() for f in FILES}
        self.assertEqual(sorted(keys & lib), [])

    def test_analog_has_fuel_model(self):
        """Аналог обязан считать расход: у A19N, A21N, B37M… в openap есть
        паспорт, но нет поляры — тип с таким аналогом падал в ядре."""
        try:
            from flightcostapp.fuel import _flow
            _flow("A320")
        except Exception:                                  # noqa: BLE001
            self.skipTest("openap не установлен")
        for f in FILES:
            b = json.loads(f.read_text(encoding="utf-8")).get("burn") or {}
            if b.get("analog"):
                with self.subTest(f.name):
                    _flow(b["analog"])

    def test_card_names_its_gaps(self):
        for f in FILES:
            d = json.loads(f.read_text(encoding="utf-8"))
            miss = [k for k in REQUIRED if (d.get("fields") or {}).get(k) is None]
            facts = {x.key.split("/", 1)[1]: x for x in _one(d, {"source_id": CATALOG})}
            with self.subTest(f.name):
                if miss:
                    self.assertEqual(facts["calc_gaps"].value_text, ", ".join(miss))
                else:
                    self.assertNotIn("calc_gaps", facts)

    def test_own_type_stays_strict(self):
        d = json.loads((CAT / "A35K.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            _one(d, {"source_id": "aircraft_user"})

    def test_card_refused_in_words(self):
        from flightcostapp.econ import load_aircraft
        s = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        d = json.loads((CAT / "A35K.json").read_text(encoding="utf-8"))
        s.commit_facts(_one(d, {"source_id": CATALOG}))
        with self.assertRaises(KeyError) as e:
            load_aircraft(s, "A35K", "2026-12-01")
        self.assertIn("только карточка", str(e.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
