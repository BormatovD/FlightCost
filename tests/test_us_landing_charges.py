"""Official FY2027 landing fees: applicability, mass and parser round trip."""
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flightcostapp import charges, drafts, econ
from flightcostapp.parsers import airport_charges


ROOT = Path(__file__).resolve().parents[1]


def document(icao):
    return (ROOT / "data" / "charges" / f"{icao}-2026.json").read_bytes()


def rules(icao):
    facts = airport_charges.parse(document(icao), {
        "source_id": "airport_charges_tier1", "node": "src_airport_tariff"})
    return [charges.Rule.from_fact(asdict(f)) for f in facts
            if f.value_text and "/landing/" in f.key]


def context(**given):
    ac = SimpleNamespace(mtow_t=78, mlw_t=68.5, seats=170)
    return econ.charge_context(
        {"icao": "KLAX", "country": "US"},
        {"icao": "KLAS", "country": "US"}, ac,
        pax=148, month=7, events=charges.EVENT_COUNTS, **given)


class USLandingFees(unittest.TestCase):
    def test_klas_rounds_up_by_ordinance_not_just_rate_sheet(self):
        rs = rules("KLAS")
        self.assertEqual(len(rs), 1)
        c = context()
        out = charges.evaluate(rs, c, fx=lambda _: 1)
        self.assertAlmostEqual(out["landing"], 152 * 1.78)
        self.assertEqual(rs[0].round_mass, "ceil_unit")

    def test_klax_all_permit_carrier_and_apron_combinations(self):
        rs = rules("KLAX")
        for permit, pax_rate, cargo_rate in (
            ("permitted", 8.65, 6.28), ("non_permitted", 10.81, 7.85)
        ):
            for carrier in ("passenger", "cargo"):
                for apron in (True, False):
                    with self.subTest(permit=permit, carrier=carrier, apron=apron):
                        c = context(landing_permit=permit, carrier_type=carrier,
                                    terminal_apron=apron, revenue_landing=True)
                        # Belly cargo does not change a passenger carrier's rate.
                        c.update(cargo=True, cargo_kg=1000)
                        report = {}
                        out = charges.evaluate(rs, c, fx=lambda _: 1, report=report)
                        rate = pax_rate if carrier == "passenger" and apron else cargo_rate
                        self.assertEqual(sum(r.matches(c) for r in rs), 1)
                        self.assertAlmostEqual(out["landing"], 151 * rate)
                        self.assertFalse(report["partial_codes"])
                        self.assertFalse(report["missing_input"])

    def test_cargo_does_not_require_irrelevant_passenger_apron(self):
        c = context(landing_permit="permitted", carrier_type="cargo",
                    revenue_landing=True)
        report = {}
        out = charges.evaluate(rules("KLAX"), c, fx=lambda _: 1, report=report)
        self.assertAlmostEqual(out["landing"], 151 * 6.28)
        self.assertEqual(report["missing_input"], [])

    def test_rounding_at_500_pounds_and_landing_event_count(self):
        c = context(landing_permit="permitted", carrier_type="passenger",
                    terminal_apron=True, revenue_landing=True)
        for pounds, units in ((150499, 150), (150500, 151), (151000, 151)):
            with self.subTest(pounds=pounds):
                c["mlw_t"] = pounds * .45359237 / 1000
                out = charges.evaluate(rules("KLAX"), c, fx=lambda _: 1)
                self.assertAlmostEqual(out["landing"], units * 8.65)
        c["landings"] = 0
        self.assertNotIn("landing", charges.evaluate(rules("KLAX"), c, fx=lambda _: 1))

    def test_missing_conditions_never_choose_cheaper_permitted_rate(self):
        c = context()
        report = {}
        out = charges.evaluate(rules("KLAX"), c, fx=lambda _: 1, report=report)
        self.assertNotIn("landing", out)
        self.assertEqual(report["lost_codes"], ["landing"])
        self.assertEqual(set(report["missing_input"]), {
            "landing_permit", "carrier_type", "terminal_apron", "revenue_landing"})

    def test_exempt_landing_needs_no_permit_or_carrier_inputs(self):
        report = {}
        c = context(revenue_landing=False)
        out = charges.evaluate(rules("KLAX"), c, fx=lambda _: 1, report=report)
        self.assertNotIn("landing", out)
        self.assertEqual(report["lost_codes"], [])
        self.assertEqual(report["missing_input"], [])

    def test_missing_mlw_does_not_substitute_mtow_for_either_airport(self):
        c = context(landing_permit="permitted", carrier_type="passenger",
                    terminal_apron=True, revenue_landing=True)
        c["mlw_t"] = None
        for icao in ("KLAX", "KLAS"):
            with self.subTest(icao=icao):
                report = {}
                out = charges.evaluate(rules(icao), c, fx=lambda _: 1, report=report)
                self.assertNotIn("landing", out)
                self.assertEqual(report["missing_data"], ["mlw_t"])

    def test_cli_context_values_and_invalid_categories(self):
        got = charges.parse_context_sets([
            "charge_context.KLAX.landing_permit=non_permitted",
            "charge_context.KLAX.carrier_type=passenger",
            "charge_context.KLAX.terminal_apron=true",
            "charge_context.KLAX.revenue_landing=false"])
        self.assertEqual(got["KLAX"], dict(landing_permit="non_permitted",
            carrier_type="passenger", terminal_apron=True, revenue_landing=False))
        with self.assertRaises(ValueError):
            charges.parse_context_value("carrier_type", "general_aviation")
        with self.assertRaises(ValueError):
            charges.parse_context_value("landing_permit", "foreign")

    def test_evidence_preserved_outside_executable_rules(self):
        for icao in ("KLAS", "KLAX"):
            with self.subTest(icao=icao):
                doc = json.loads(document(icao))
                self.assertTrue(doc["evidence"])
                self.assertTrue(any(e.get("quote") for e in doc["evidence"]))
                self.assertTrue(all(e.get("where") and (e.get("quote") or e.get("note") or
                    isinstance(e.get("rate"), (int, float))) for e in doc["evidence"]))
                for r in doc["rules"]:
                    self.assertTrue({"quote", "where", "confidence"}.isdisjoint(r))
                # An unsupported field must still fail rather than disappear silently.
                doc["rules"][0]["quote"] = "unsupported"
                with self.assertRaisesRegex(ValueError, "quote"):
                    airport_charges.parse(json.dumps(doc).encode(), {
                        "source_id": "test", "node": "src_airport_tariff"})

    def test_draft_check_names_unset_inputs_and_keeps_manual_review(self):
        res = SimpleNamespace(charge_lines={}, charge_gaps={"KLAX": {
            "missing_input": ["carrier_type", "landing_permit"], "missing_data": []}})
        with patch("flightcostapp.econ.route_economics", return_value=res):
            result = drafts.check(document("KLAX"), object())
        self.assertEqual(result["verdict"], "look")
        self.assertGreaterEqual(result["priced_rules"], 6)
        self.assertTrue(any("carrier_type, landing_permit" in r for r in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
