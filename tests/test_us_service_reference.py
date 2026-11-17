"""Published service fees: independent amounts and exclusions for FY2027."""
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from flightcostapp import categories, charges, econ
from flightcostapp.parsers import airport_charges

ROOT = Path(__file__).resolve().parents[1]


def document(icao):
    return json.loads((ROOT / "data" / "charges" / f"{icao}-2026.json").read_text())


def evaluate(icao, ctx, code=None):
    doc = document(icao)
    facts = airport_charges.parse(json.dumps(doc).encode(), {
        "source_id": "test", "node": "src_airport_tariff"})
    rules = [charges.Rule.from_fact(asdict(f)) for f in facts
             if f.value_text and not f.key.split("/")[1].startswith("_")]
    if code:
        rules = [r for r in rules if r.code == code]
    gaps = [e for e in doc.get("unpriced", []) if not code or e["code"] == code]
    report = {}
    out = charges.evaluate(rules, ctx, fx=lambda _: 1, report=report, unpriced=gaps)
    return out, report


def context(**given):
    ac = SimpleNamespace(mtow_t=78, mlw_t=68.5, seats=170)
    return econ.charge_context({"icao": "KLAX", "country": "US"},
        {"icao": "KLAS", "country": "US"}, ac, pax=148, month=7,
        events=charges.EVENT_COUNTS, **given)


class USServiceReference(unittest.TestCase):
    def test_klas_common_use_domestic_turn(self):
        c = context(fee_status="signatory", body_class="narrow", ferry=False,
            west_side_use=False, gate_turn_billable=True, common_use_counter=True,
            common_use_bso=True, fis_use=False, arrival_type="domestic",
            cargo_apron_use=False, pfc_pax=148, fuel_flowage_separate=False,
            joint_use=False, parking_area="none", parking_chargeable=False,
            off_hours_use=False, unauthorized_gate_uses=0,
            unauthorized_counter_positions=0, unauthorized_parking_uses=0)
        out, report = evaluate("KLAS", c)
        self.assertAlmostEqual(out["landing"], 270.56)
        self.assertEqual(out["gate_turn"], 328)
        self.assertAlmostEqual(out["ticket_counter"], 211.64)
        self.assertAlmostEqual(out["bso"], 16.28)
        self.assertEqual(out["pfc"], 666)
        self.assertAlmostEqual(sum(out.values()), 1492.48)
        self.assertEqual(report["lost_codes"], [])
        self.assertEqual(report["missing_input"], [])

    def test_klas_ferry_and_west_side_do_not_charge_gate_turn(self):
        c = context(fee_status="signatory", body_class="narrow", ferry=True,
                    west_side_use=False, gate_turn_billable=True)
        self.assertNotIn("gate_turn", evaluate("KLAS", c, "gate_turn")[0])
        c.update(ferry=False, west_side_use=True)
        self.assertNotIn("gate_turn", evaluate("KLAS", c, "gate_turn")[0])

    def test_klas_west_side_counts_crew_and_offhours_surcharge(self):
        c = context(west_side_use=True, souls_on_board=20, off_hours_use=True)
        self.assertEqual(evaluate("KLAS", c, "west_side")[0]["west_side"], 250)
        self.assertEqual(evaluate("KLAS", c, "off_hours")[0]["off_hours"], 800)
        c.update(souls_on_board=21, west_side_use=False, fis_use=True)
        self.assertNotIn("west_side", evaluate("KLAS", c, "west_side")[0])
        self.assertEqual(evaluate("KLAS", c, "off_hours")[0]["off_hours"], 1600)

    def test_klas_parking_is_missing_instead_of_invented_zero(self):
        out, report = evaluate("KLAS", context(parking_area="tier1",
            parking_chargeable=True, fee_status="signatory", park_h=10), "parking")
        self.assertNotIn("parking", out)
        self.assertEqual(report["lost_codes"], ["parking"])
        self.assertTrue(report["unpriced"])

    def test_klax_arra_services_do_not_double_charge_bridge(self):
        c = context(carrier_type="passenger", terminal_agreement="arra_2023",
            terminal_facility="TBIT", ac_class=5, common_use_holdroom=True,
            high_volume_gate=False, gate_turn_billable=True, common_use_counter=True,
            common_use_baggage_outbound=True, common_use_baggage_claim=False,
            common_use_bmu=False, fis_use=True, arrival_type="international",
            separate_bridge=True)
        for code, expected in (("holdroom", 1445.27), ("ticket_counter", 99.16),
                ("baggage_outbound", 2086.80), ("fis", 2976.28), ("custodial", 100.64)):
            with self.subTest(code=code):
                out, report = evaluate("KLAX", c, code)
                self.assertAlmostEqual(out[code], expected)
                self.assertFalse(report["lost_codes"])
        self.assertNotIn("boarding_bridge", evaluate("KLAX", c, "boarding_bridge")[0])
        c.update(common_use_holdroom=False)
        self.assertAlmostEqual(evaluate("KLAX", c, "boarding_bridge")[0]["boarding_bridge"], 134.20)

    def test_disputed_farra_class4_and_tariff_are_visible_gaps(self):
        c = context(carrier_type="passenger", terminal_agreement="farra",
            terminal_facility="TBIT", common_use_holdroom=True,
            gate_turn_billable=True, high_volume_gate=False, ac_class=4)
        out, report = evaluate("KLAX", c, "holdroom")
        self.assertNotIn("holdroom", out)
        self.assertEqual(report["lost_codes"], ["holdroom"])
        self.assertIn("1827.27", report["unpriced"][0]["reason"])
        c.update(terminal_agreement="tariff")
        self.assertNotIn("holdroom", evaluate("KLAX", c, "holdroom")[0])

    def test_precleared_arrivals_use_domestic_baggage_and_no_fis(self):
        c = context(carrier_type="passenger", terminal_agreement="arra_2023",
            arrival_type="precleared", common_use_baggage_claim=True, fis_use=True)
        self.assertAlmostEqual(evaluate("KLAX", c, "baggage_claim")[0]["baggage_claim"], 708.92)
        self.assertNotIn("fis", evaluate("KLAX", c, "fis")[0])

    def test_parking_document_examples_and_fourth_day(self):
        for area, at72, fourth in (("remote", 6750, 5000), ("contact", 8437.50, 6250)):
            c = context(carrier_type="passenger", parking_area=area,
                        parking_chargeable=True, parking_credit=False, park_h=72)
            self.assertEqual(evaluate("KLAX", c, "parking")[0]["parking"], at72)
            c["park_h"] = 72.01
            self.assertEqual(evaluate("KLAX", c, "parking")[0]["parking"], at72 + fourth)
            c.update(park_h=72, parking_credit=True)
            if area == "contact":
                out, report = evaluate("KLAX", c, "parking")
                self.assertEqual(out["parking"], 7500)
                self.assertEqual(report["partial_codes"], ["parking"])

    def test_document_aircraft_classes_do_not_guess_unknown_large_type(self):
        spec = document("KLAX")["categories"]["ac_class"]
        for icao, seats, expected in (("A320", 170, 5), ("BCS1", 90, 5),
                ("B752", 200, 5), ("B753", 230, 4), ("E170", 80, 6),
                ("TEST", 150, None)):
            with self.subTest(icao=icao):
                got = categories.resolve("ac_class", spec, {"icao": icao, "seats_max": seats})
                self.assertEqual(got.value, expected)

    def test_boolean_typo_cannot_silently_disable_a_service(self):
        for key in ("common_use_counter", "parking_credit", "revenue_landing"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "true/false"):
                    charges.parse_context_value(key, "treu")
                self.assertIs(charges.parse_context_value(key, "false"), False)
                self.assertIs(charges.parse_context_value(key, "true"), True)


if __name__ == "__main__":
    unittest.main()
