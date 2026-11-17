"""Synthetic service quantities and unresolved tariff articles, without live calls."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from flightcostapp import charges
from flightcostapp.parsers import airport_charges
from flightcostapp.store import Store


class ServiceChargeTests(unittest.TestCase):
    def context(self, **changes):
        return {**{k: None for k in charges.CONDITION_KEYS}, **charges.EVENT_COUNTS,
                "mtow_t": 78.0, "pax": 148.0, "cargo_kg": 0.0, "park_h": 2.0,
                **changes}

    def rule(self, **changes):
        args = dict(code="flowage", base="per_quantity", rate=0.1, currency="USD",
                    events="turnaround", quantity_key="fuel_us_gal", quantity_unit=1.0)
        args.update(changes)
        return charges.Rule(**args)

    def document(self):
        return {"icao": "KLAX", "valid_from": "2026-07-01",
                "source": "Synthetic tariff", "source_url": "https://example.com/tariff",
                "map_node": "src_airport_tariff", "rules": [
                    {"code": "landing", "base": "per_turnaround", "rate": 50.0}],
                "unpriced": [{"code": "terminal", "reason": "Requires billed area",
                              "when": {"common_use_counter": True,
                                       "terminal_facility": "TBIT"}}]}

    def parse(self, doc):
        return airport_charges.parse(json.dumps(doc).encode(), {
            "source_id": "test", "node": "src_airport_tariff"})

    def test_quantity_fractional_units_event_count_and_fx(self):
        # 12.5 gallons, $0.10 per gallon, two movements, USD 2 per EUR.
        rule = self.rule(events="movement")
        result = charges.evaluate([rule], self.context(fuel_us_gal=12.5), fx=lambda _: 2.0)
        self.assertAlmostEqual(result["flowage"], 1.25)
        self.assertFalse(charges.self_check([rule]))

    def test_missing_quantity_is_reported_while_known_zero_is_not_missing(self):
        report = {}
        result = charges.evaluate([self.rule()], self.context(), fx=lambda _: 1, report=report)
        self.assertNotIn("flowage", result)
        self.assertEqual(report["lost_codes"], ["flowage"])
        self.assertEqual(report["missing_input"], ["fuel_us_gal"])
        self.assertFalse(report["missing_data"])
        result = charges.evaluate([self.rule()], self.context(fuel_us_gal=0),
                                  fx=lambda _: 1, report=report)
        self.assertEqual(result.get("flowage", 0), 0)
        self.assertFalse(report["lost_codes"])
        self.assertFalse(report["missing_input"])
        self.assertFalse(any(k.startswith("_") for k in result))

    def test_no_departure_does_not_require_pfc_passenger_quantity(self):
        rule = self.rule(code="pfc", events="takeoff", quantity_key="pfc_pax",
                         when={"carrier_type": "passenger"})
        for carrier in (None, "passenger"):
            report = {}
            result = charges.evaluate([rule], self.context(departures=0,
                movements=1, carrier_type=carrier), fx=lambda _: 1, report=report)
            self.assertNotIn("pfc", result)
            self.assertFalse(report["lost_codes"])
            self.assertFalse(report["missing_input"])

    def test_quantity_grace_and_started_quarter_hours(self):
        rule = self.rule(code="cleanup", rate=20, quantity_key="spill_cleanup_min",
                         quantity_unit=15, threshold=15, round_quantity="ceil_unit")
        for minutes, expected in ((0, 0), (14.9, 0), (15, 0), (15.01, 20),
                                  (30, 20), (30.01, 40), (45, 40)):
            with self.subTest(minutes=minutes):
                result = charges.evaluate([rule], self.context(spill_cleanup_min=minutes),
                                          fx=lambda _: 1)
                self.assertEqual(result.get("cleanup", 0), expected)

    def test_quantity_rounding_is_applied_to_units(self):
        for rounding, quantity, expected in ((None, 2.5, 25), ("nearest_unit", 2.5, 30),
                                              ("floor_unit", 2.9, 20), ("ceil_unit", 2.1, 30)):
            with self.subTest(rounding=rounding):
                result = charges.evaluate([self.rule(rate=10, quantity_unit=10,
                                                       round_quantity=rounding)],
                                          self.context(fuel_us_gal=quantity * 10), fx=lambda _: 1)
                self.assertEqual(result["flowage"], expected)

    def test_invalid_quantity_input_and_rule_parameters_are_rejected(self):
        for value in (-1, True, "10", float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    charges.evaluate([self.rule()], self.context(fuel_us_gal=value), fx=lambda _: 1)
        for changes in ({"quantity_key": "mtow_t"}, {"quantity_unit": 0},
                        {"quantity_unit": True}, {"quantity_unit": float("inf")},
                        {"quantity_unit": None}, {"round_quantity": "ceil_hour"},
                        {"pct_of": "landing"}, {"round_mtow": "ceil_tonne"},
                        {"base": "per_turnaround"}):
            with self.subTest(changes=changes):
                self.assertTrue(charges.self_check([self.rule(**changes)]))

    def test_known_condition_mismatch_excludes_missing_quantity(self):
        rule = self.rule(when={"fuel_flowage_separate": True})
        report = {}
        result = charges.evaluate([rule], self.context(fuel_flowage_separate=False),
                                  fx=lambda _: 1, report=report)
        self.assertFalse(result)
        self.assertFalse(report["lost_codes"])
        self.assertFalse(report["missing_input"])

    def test_arriving_pax_uses_landings_and_departing_pax_uses_departures(self):
        rules = [charges.Rule(code="arrival", base="per_arriving_pax", rate=3),
                 charges.Rule(code="departure", base="per_departing_pax", rate=3)]
        result = charges.evaluate(rules, self.context(pax=10, landings=2, departures=0))
        self.assertEqual(result["arrival"], 60)
        self.assertEqual(result.get("departure", 0), 0)

    def test_gate_turn_full_published_fee_and_half_turn(self):
        rule = charges.Rule(code="gate", base="per_gate_turn", rate=120,
                            events="movement")
        self.assertFalse(charges.self_check([rule]))
        for movements, expected in ((2, 120), (1, 60), (0, 0)):
            with self.subTest(movements=movements):
                result = charges.evaluate([rule], self.context(movements=movements))
                self.assertEqual(result.get("gate", 0), expected)
        self.assertTrue(charges.self_check([replace(rule, events="turnaround")]))

    def test_quantity_parser_round_trip_and_distinct_identity(self):
        doc = self.document()
        raw = asdict(self.rule())
        raw = {k: v for k, v in raw.items() if v is not None}
        for field in ("key", "certainty", "error_cost", "confirm_by", "node"):
            raw.pop(field, None)
        doc["rules"] = [dict(raw, source="Fuel contract", source_url="https://example.com/fuel")]
        fact = self.parse(doc)[0]
        rule = charges.Rule.from_fact(asdict(fact))
        self.assertEqual((rule.quantity_key, rule.quantity_unit, rule.round_quantity),
                         ("fuel_us_gal", 1.0, None))
        self.assertEqual(fact.note, " | Fuel contract | https://example.com/fuel")
        self.assertNotEqual(fact.key, airport_charges._rule_key(
            "KLAX", replace(rule, quantity_key="pfc_pax")))
        self.assertNotEqual(fact.key, airport_charges._rule_key(
            "KLAX", replace(rule, quantity_unit=100)))
        self.assertNotEqual(fact.key, airport_charges._rule_key(
            "KLAX", replace(rule, round_quantity="ceil_unit")))
        doc["rules"][0]["source"] = "Corrected source title"
        self.assertEqual(self.parse(doc)[0].key, fact.key)

    def test_existing_rule_hash_and_serialization_do_not_gain_quantity_fields(self):
        rule = charges.Rule(code="landing", base="per_tonne_mtow", rate=6)
        original = {"base": rule.base, "events": rule.events, "when": rule.when,
                    "currency": rule.currency, "threshold": rule.threshold,
                    "exponent": rule.exponent, "pct_of": rule.pct_of,
                    "round_mtow": rule.round_mtow, "variant": ""}
        digest = hashlib.sha256(json.dumps(original, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()[:8]
        self.assertEqual(airport_charges._rule_key("KLAX", rule), f"KLAX/landing/{digest}")
        self.assertTrue({"quantity_key", "quantity_unit", "round_quantity"}.isdisjoint(
            json.loads(rule.to_json())))

    def test_unpriced_store_load_evaluate_and_known_mismatch(self):
        doc = self.document()
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "facts.db")
            try:
                store.commit_facts(self.parse(doc))
                loading = {}
                rules = charges.load_rules(store, "KLAX", "2026-07-01", report=loading)
                self.assertEqual([r.code for r in rules], ["landing"])
                self.assertFalse(loading["broken"])
                self.assertEqual(loading["unpriced"][0]["reason"], "Requires billed area")
                for terminal, used, missing, lost in (
                        ("TBIT", None, ["common_use_counter"], ["terminal"]),
                        ("TBIT", True, [], ["terminal"]),
                        ("T5", None, [], []), ("TBIT", False, [], [])):
                    with self.subTest(terminal=terminal, used=used):
                        report = {}
                        result = charges.evaluate(
                            rules, self.context(terminal_facility=terminal, common_use_counter=used),
                            report=report, unpriced=loading["unpriced"])
                        self.assertEqual(result["landing"], 50)
                        self.assertNotIn("terminal", result)
                        self.assertEqual(report["missing_input"], missing)
                        self.assertEqual(report["lost_codes"], lost)
                        self.assertEqual([e["code"] for e in report["unpriced"]], lost)
            finally:
                store.db.close()

    def test_unpriced_same_article_as_priced_rule_reports_partial(self):
        report = {}
        rules = [charges.Rule(code="terminal", base="per_turnaround", rate=40)]
        entry = {"code": "terminal", "when": {}, "reason": "Additional leased area"}
        result = charges.evaluate(rules, self.context(), unpriced=[entry], report=report)
        self.assertEqual(result["terminal"], 40)
        self.assertEqual(report["partial_codes"], ["terminal"])
        self.assertFalse(report["lost_codes"])

    def test_browse_shows_unpriced_reason_without_zero_price(self):
        from flightcostapp import browse

        doc = self.document()
        registry = {"sources": {"test": {"public": "full", "title": "Test source"}}}
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "facts.db")
            try:
                store.commit_facts(self.parse(doc))
                rows = browse.rows(store, registry, "airport_charge", as_of="2026-07-01")["rows"]
                row = next(r for r in rows if r["unit"] == "unpriced_charge")
                self.assertIsNone(row["value"])
                self.assertIn("Requires billed area", row["text"])
                self.assertIn("Synthetic tariff", row["text"])
                self.assertIn("https://example.com/tariff", row["text"])
                self.assertEqual(next(r for r in rows if r["unit"] == "per_turnaround")["value"], 50)
            finally:
                store.db.close()

    def test_type_comparison_drops_body_class_and_preserves_service_settings(self):
        from flightcostapp.serve import Context

        context = object.__new__(Context)
        overrides = {"charge_context.KLAX.body_class": "wide",
                     "charge_context.KLAX.noise_cat": 2,
                     "charge_context.KLAX.fee_status": "signatory"}
        context._kwargs = lambda _: {"overrides": overrides}
        context._legs = lambda _q, pax: [{"o": "LAX", "d": "LAS", "pax": pax}]
        seen = []

        def compare_type(aircraft, legs, kwargs):
            seen.append(dict(kwargs["overrides"]))
            return {"icao": aircraft, "status": "ok", "cost_per_pax": 10}

        context._compare_type = compare_type
        result = context.compare({"types": "A320,B788", "pax": 100,
                                  "set": "~".join(f"{key}={value}" for key, value in overrides.items())})
        self.assertEqual(result["dropped_ctx"], ["body_class", "noise_cat"])
        self.assertEqual(seen, [{"charge_context.KLAX.fee_status": "signatory"}] * 2)


if __name__ == "__main__":
    unittest.main()
