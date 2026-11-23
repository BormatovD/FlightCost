"""Comparison-only route market hints shown in Network mode."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flightcostapp.serve import Context, network_pair_hints
from flightcostapp.store import Fact, Store

ROOT = Path(__file__).resolve().parents[1]
RATING = json.loads((ROOT / "research/routes-2026-11/out/rating.json").read_text(encoding="utf-8"))
AIRPORT_SOURCE = json.loads((ROOT / "research/routes-2026-11/out/airports.json").read_text(encoding="utf-8"))
AIRPORTS = [
    {"icao": icao, "key": row[5], "iso": row[2], "lat": row[0], "lon": row[1]}
    for icao, row in AIRPORT_SOURCE.items() if len(row) > 5 and row[5]
]


class NetworkHints(unittest.TestCase):
    def test_forecast_can_find_an_airport_outside_map_selection(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.db")
            try:
                store.commit_facts([Fact(domain="airport", key="ASE", valid_from="2020-01-01",
                                         value_text="39.2,-106.9|KASE|US|Aspen",
                                         source_id="test", extracted_by="test")])
                context = Context(store, {})
                self.assertEqual(context.airports(), [])
                rows = context.airports_by_code(["KASE", "ASE", "ZZZZ"])
                self.assertEqual([(row["key"], row["icao"], row["tier"]) for row in rows],
                                 [("ASE", "KASE", 3)])
                self.assertEqual(context.airports(), [])
            finally:
                store.db.close()

    def test_hub_hints_keep_only_base_pairs(self):
        rows = network_pair_hints(RATING, AIRPORTS, ["LEBL", "VIDP", "FRA", "VABB"], base="EDDF")
        self.assertEqual([row["from"] for row in rows], ["EDDF"] * 3)
        self.assertEqual([row["to"] for row in rows], ["LEBL", "VIDP", "VABB"])

    def test_fra_barcelona_iata_and_icao_are_symmetric_and_use_fluko_flags(self):
        iata = network_pair_hints(RATING, AIRPORTS, ["FRA", "BCN"])[0]
        icao = network_pair_hints(RATING, AIRPORTS, ["LEBL", "EDDF"])[0]
        self.assertTrue(iata["found"])
        self.assertEqual(iata["key"], "EDDF-LEBL")
        self.assertEqual(iata["market"], "europe_short_haul")
        self.assertEqual(iata["period"], "2024-12")
        self.assertEqual(iata["rank_of"], len(RATING["europe"]["pairs"]))
        self.assertEqual(iata["slot3"], ["EDDF", "LEBL"])
        for field in ("market", "period", "rank", "rank_of", "pax", "growth", "load_factor", "slot3"):
            self.assertEqual(iata[field], icao[field])

    def test_delhi_mumbai_has_both_slots_and_no_inferred_load_factor(self):
        row = network_pair_hints(RATING, AIRPORTS, ["DEL", "BOM"])[0]
        self.assertEqual(row["market"], "india")
        self.assertEqual(row["period"], "2026-07")
        self.assertEqual(row["rank_of"], len(RATING["india"]["pairs"]))
        self.assertEqual(row["slot3"], ["VIDP", "VABB"])
        self.assertIsNone(row["load_factor"])

    def test_long_haul_uses_long_haul_market_denominator(self):
        source = RATING["europe"]["long_haul"][0]
        row = network_pair_hints(RATING, AIRPORTS, [source["a"], source["b"]])[0]
        self.assertEqual(row["market"], "europe_long_haul")
        self.assertEqual(row["rank"], source["rank"])
        self.assertEqual(row["rank_of"], len(RATING["europe"]["long_haul"]))

    def test_unknown_pair_is_informational_and_has_no_guessed_market(self):
        row = network_pair_hints(RATING, AIRPORTS, ["EDDF", "VILH"])[0]
        self.assertFalse(row["found"])
        self.assertIsNone(row["market"])
        self.assertIsNone(row["period"])
        self.assertIsNone(row["rank"])

    def test_rebuild_after_pair_selection_or_rating_update(self):
        self.assertEqual(len(network_pair_hints(RATING, AIRPORTS, ["EDDF", "LEBL", "VIDP", "VABB"])), 6)
        self.assertEqual(len(network_pair_hints(RATING, AIRPORTS, ["EDDF", "LEBL", "VIDP"])), 3)
        self.assertEqual(len(network_pair_hints(RATING, AIRPORTS, ["EDDF", "LEBL"])), 1)
        changed = copy.deepcopy(RATING)
        changed["europe"]["pairs"].append({"pair": "XXXX-YYYY", "rank": len(changed["europe"]["pairs"]) + 1})
        row = network_pair_hints(changed, AIRPORTS, ["FRA", "BCN"])[0]
        self.assertEqual(row["rank"], 599)
        self.assertEqual(row["rank_of"], len(RATING["europe"]["pairs"]) + 1)


if __name__ == "__main__":
    unittest.main()
