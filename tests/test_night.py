"""Ночные ограничения аэропортов: окно базы, агент и приёмка (план network-calc, шаг 4)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

from flightcostapp import night as NG

DOC = {"airports": {
    "EDDF": {"kind": "ban", "from": "23:00", "to": "05:00", "checked": "2026-11-10"},
    "LEBL": {"kind": "surcharge", "from": "23:00", "to": "07:00", "checked": "2026-11-10"},
    "EGLL": {"kind": "quota", "from": "23:30", "to": "06:00", "checked": "2026-11-10"},
    "EDDL": {"kind": "ban", "from": "22:00", "to": "06:00", "checked": "2026-11-10"}}}


class Window(unittest.TestCase):

    def test_only_long_ban_narrows(self):
        self.assertEqual(NG.closed_hours(DOC["airports"]["EDDF"]), 6)
        self.assertEqual(NG.base_window("EDDF", 18, DOC)[0], 18)        # 24 − 6 = 18: не уже калибровки
        w, note = NG.base_window("EDDL", 18, DOC)
        self.assertEqual(w, 16)
        self.assertIn("16", note)
        self.assertEqual(NG.base_window("LEBL", 18, DOC)[0], 18)        # надбавка окно не меняет
        self.assertEqual(NG.base_window("KDEN", 18, DOC), (18, None))
        self.assertEqual(NG.notes(["EGLL", "LEBL", "EDDF"], DOC), ["EGLL — квота 23:30–06:00",
                                                                  "EDDF — запрет 23:00–05:00"])


class Drafts(unittest.TestCase):

    def test_check_and_merge(self):
        blob = json.dumps({"airports": [
            {"icao": "LSZH", "kind": "ban", "from": "23:30", "to": "06:00",
             "quote": "Nachtflugsperre von 23.30 bis 06.00 Uhr", "where": "https://flughafen-zuerich.ch/x"},
            {"icao": "LIRF", "kind": "ban", "from": "23:00", "to": "06:00", "quote": "night restrictions apply",
             "where": "https://adr.it/x"},
            {"icao": "LEMD", "kind": None},
            {"icao": "XX", "kind": "ban", "from": "1", "to": "2"}]}).encode()
        r = {x["icao"]: x for x in NG.check(blob, DOC)["rows"]}
        self.assertEqual(r["LSZH"]["verdict"], "clean")
        self.assertEqual(r["LIRF"]["verdict"], "look")
        self.assertEqual(r["LEMD"]["verdict"], "skip")
        self.assertEqual(r["XX"]["verdict"], "reject")
        p = Path(tempfile.mkdtemp()) / "_night.yaml"
        p.write_text("# шапка\nairports: {}\n", "utf-8")
        NG.merge([r["LSZH"]], p, date(2026, 11, 10))
        d = yaml.safe_load(p.read_text("utf-8"))
        self.assertEqual(d["airports"]["LSZH"]["from"], "23:30")
        self.assertEqual(d["airports"]["LSZH"]["checked"], "2026-11-10")
        self.assertTrue(p.read_text("utf-8").startswith("# шапка"))

    def test_due_takes_new_first(self):
        d = Path(tempfile.mkdtemp())
        for icao in ("EDDF", "LSZH", "LEMD"):
            (d / f"{icao}-2026.json").write_text(json.dumps({"publisher": "p", "source_url": f"https://{icao}"}))
        old = {"airports": {"EDDF": {"kind": "ban", "checked": "2025-01-01"},
                            "LSZH": {"kind": "ban", "checked": "2026-10-01"}}}
        w = NG.due(d, old, date(2026, 11, 10))
        self.assertEqual([x["icao"] for x in w], ["LEMD", "EDDF"])

    def test_repo_file_is_valid(self):
        doc = yaml.safe_load(NG.NIGHT_PATH.read_text("utf-8"))
        for icao, r in (doc.get("airports") or {}).items():
            self.assertIn(r["kind"], NG.KINDS, icao)
            self.assertTrue(str(r.get("source", "")).startswith("http"), icao)


if __name__ == "__main__":
    unittest.main()
