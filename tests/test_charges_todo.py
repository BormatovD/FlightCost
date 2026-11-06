"""Список тарифов для агента: не меньше двух аэропортов с документом на регион.

Проверяется порядок выбора: первый регион, где не хватает; в нём первый
кандидат без файла; «не найден» дважды — следующий кандидат; черновик на
приёмке занимает место в регионе, но не дольше срока приёмки; явный список
FCA_AGENT_CHARGES_ONLY главнее регионов. И сам файл: у каждого кандидата
регион по префиксу совпадает с тем, где он записан.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from datetime import date, timedelta

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp import agent_run as A                     # noqa: E402

DOC = {
    "regions": {
        "na": {"name": "Северная Америка", "prefixes": ["K", "C"],
               "candidates": [{"icao": "KATL"}, {"icao": "KDFW"}, {"icao": "KLAX"}]},
        "me": {"name": "Ближний Восток", "prefixes": ["OM", "OT", "OE"],
               "candidates": [{"icao": "OMDB"}, {"icao": "OERK"}]},
    },
    "airports": {"KDFW": {"url": "https://example.org/dfw.pdf", "publisher": "DFW"}},
    "not_found_x": {"KLAX": "нет документа"},
}


class Pick(unittest.TestCase):
    def test_first_short_region_first_candidate(self):
        icao, a, rid = A.pick_charges(DOC, set(), {})
        self.assertEqual((icao, rid), ("KATL", "na"))

    def test_merges_details_and_skips_not_found(self):
        st = {"KATL": {"status": "not_found"}}
        icao, a, _ = A.pick_charges(DOC, set(), st)
        self.assertEqual(icao, "KDFW")
        self.assertEqual(a["url"], "https://example.org/dfw.pdf")
        st["KDFW"] = {"status": "not_found"}
        # KLAX в not_found_x — регион без кандидатов, переход к следующему
        icao, _, rid = A.pick_charges(DOC, set(), st)
        self.assertEqual((icao, rid), ("OMDB", "me"))

    def test_region_with_two_covered_is_skipped(self):
        icao, _, rid = A.pick_charges(DOC, {"KJFK", "CYYZ", "OTHH"}, {})
        self.assertEqual((icao, rid), ("OMDB", "me"))

    def test_draft_holds_place_until_it_expires(self):
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=A.DRAFT_DAYS + 1)).isoformat()
        st = {"KATL": {"status": "draft", "at": today}}
        icao, _, _ = A.pick_charges(DOC, {"KJFK"}, st)            # KJFK + черновик KATL = 2
        self.assertEqual(icao, "OMDB")
        st["KATL"]["at"] = old                                     # не принят за срок
        icao, _, _ = A.pick_charges(DOC, {"KJFK"}, st)
        self.assertEqual(icao, "KDFW")

    def test_explicit_list_wins(self):
        icao, _, rid = A.pick_charges(DOC, set(), {}, ["OERK"])
        self.assertEqual((icao, rid), ("OERK", "me"))


class File(unittest.TestCase):
    def test_candidates_sit_in_their_region(self):
        doc = yaml.safe_load((ROOT / "data" / "charges" / "_todo.yaml").read_text("utf-8"))
        regions = doc["regions"]
        seen = set()
        for rid, r in regions.items():
            for c in r["candidates"]:
                self.assertRegex(c["icao"], r"^[A-Z]{4}$")
                self.assertNotIn(c["icao"], seen, f"{c['icao']} дважды")
                seen.add(c["icao"])
                self.assertEqual(A.region_of(c["icao"], regions), rid, f"{c['icao']} не в своём регионе")


if __name__ == "__main__":
    unittest.main(verbosity=2)
