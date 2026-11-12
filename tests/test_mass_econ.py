"""MLW must be passed end-to-end from aircraft data into airport-charge context."""
import unittest
from types import SimpleNamespace

from flightcostapp import charges, econ


class MLWEconomicsTest(unittest.TestCase):
    def test_charge_context_keeps_mlw_distinct_from_mtow(self):
        ac = SimpleNamespace(icao="A320", mtow_t=78.0, mlw_t=66.0, seats=170)
        ap = {"icao": "KLAX", "country": "US"}
        other = {"icao": "KDEN", "country": "US"}
        ctx = econ.charge_context(ap, other, ac, pax=148, month=7,
                                  events=econ.rotation_events("KLAX", [("KDEN", "KLAX"),
                                                                           ("KLAX", "KDEN")]))
        self.assertEqual(ctx["mtow_t"], 78.0)
        self.assertEqual(ctx["mlw_t"], 66.0)
        charges.check_context(ctx)

    def test_missing_mlw_does_not_use_mtow(self):
        # An aircraft known only by MTOW must not get a made-up landing weight.
        ac = SimpleNamespace(icao="A320", mtow_t=78.0, seats=170)
        ap = {"icao": "KLAX", "country": "US"}
        other = {"icao": "KDEN", "country": "US"}
        ctx = econ.charge_context(ap, other, ac, pax=148, month=7,
                                  events=charges.EVENT_COUNTS)
        self.assertIsNone(ctx["mlw_t"])
        report = {}
        rule = charges.Rule(code="landing", base="per_mass",
                            rate=8.65, currency="USD", events="landing",
                            mass_basis="mlw", rate_unit="1000lb")
        out = charges.evaluate([rule], ctx, fx=lambda _: 1.0, report=report)
        self.assertNotIn("landing", out)
        self.assertIn("mlw_t", report["missing_data"])


if __name__ == "__main__":
    unittest.main()
