"""Цена по формуле (решение 212): прямая по нашим же наблюдениям, по регионам."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import fare_model as FM   # noqa: E402
from flightcostapp.store import Fact, Store  # noqa: E402

# Европейские аэропорты с координатами — сетка, на которой «рынок» платит
# 12 · км^0,6 EUR; одна пара — прямая с пересадкой, она не в счёт.
EU = {"EDDF": (50.03, 8.54), "LEBL": (41.30, 2.08), "LIRF": (41.80, 12.24),
      "LPPT": (38.78, -9.14), "LEMD": (40.47, -3.56), "EGLL": (51.47, -0.45),
      "EHAM": (52.31, 4.76), "LFPG": (49.01, 2.55), "LOWW": (48.11, 16.57),
      "EPWA": (52.17, 20.97), "LGAV": (37.94, 23.94), "EKCH": (55.62, 12.65)}


def store_with(n_pairs: int) -> Store:
    d = pathlib.Path(tempfile.mkdtemp())
    s = Store(d / "t.db")
    facts = [Fact(domain="airport", key=k, valid_from="2026-01-01",
                  value_text=f"{la},{lo}|{k}|XX|{k}", source_id="t", extracted_by="t")
             for k, (la, lo) in EU.items()]
    keys = list(EU)
    pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]][:n_pairs]
    for i, (a, b) in enumerate(pairs):
        km = FM._km(EU[a], EU[b])
        noise = 1 + (0.06 if i % 2 else -0.06)
        facts.append(Fact(domain="market_fare", key=f"{a}-{b}/d15_30/direct",
                          valid_from="2026-10-01", value=12 * km ** 0.6 * noise,
                          unit="EUR", currency="EUR", source_id="t", extracted_by="t"))
        facts.append(Fact(domain="market_fare", key=f"{a}-{b}/d15_30/via",
                          valid_from="2026-10-01", value=9999.0, unit="EUR", currency="EUR",
                          source_id="t", extracted_by="t"))
    s.commit_facts(facts)
    return s


class FareModel(unittest.TestCase):

    def test_regions(self):
        self.assertEqual(FM.pair_region("EDDF", "LEBL"), "europe")
        self.assertEqual(FM.pair_region("UUEE", "UATT"), "russia")      # Россия + СНГ
        self.assertEqual(FM.pair_region("VIDP", "VABB"), "india")
        self.assertEqual(FM.pair_region("EDDF", "VIDP"), "inter")

    def test_line_recovered_from_direct_fares_only(self):
        s = store_with(40)
        m = FM.fit(s)["europe"]
        self.assertAlmostEqual(m["beta"], 0.6, delta=0.08)
        self.assertLess(m["mdape"], 0.10)
        fare, src = FM.estimate(s, "EDDF", "LGAV", 1800.0)
        self.assertAlmostEqual(fare, 12 * 1800 ** 0.6, delta=0.1 * 12 * 1800 ** 0.6)
        self.assertIn("оценка по формуле", src)
        self.assertIn("Европа", src)

    def test_too_few_pairs_no_formula(self):
        s = store_with(5)
        self.assertEqual(FM.fit(s), {})
        fare, why = FM.estimate(s, "EDDF", "LGAV", 1800.0)
        self.assertIsNone(fare)
        self.assertIn("мало", why)

    def test_other_region_falls_back_to_all_pairs(self):
        s = store_with(40)
        fare, src = FM.estimate(s, "VIDP", "VABB", 1150.0)
        self.assertIsNotNone(fare)
        self.assertIn("все пары", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class CurrencyLabel(unittest.TestCase):
    """Решение 222: неправдоподобная цена (чужая подпись валюты, выброс) не публикуется."""

    def test_thresholds(self):
        from flightcostapp.market_fare import implausible
        self.assertEqual(implausible(85.0, 1100), "")            # FRA–BCN
        self.assertEqual(implausible(700.0, 9000), "")           # дальний, дорогой, но рынок
        self.assertEqual(implausible(629.0, 599), "")            # пересадка ULLI–UUEE: дорого, но живое
        self.assertIn("EUR/км", implausible(4259.0, 286))        # выброс EDDF–LSZH
        self.assertIn("EUR/км", implausible(7976.0, 2800))       # рубли под евро
        self.assertIn("дешевле", implausible(99 / 95, 1000))     # евро под рублями
        self.assertEqual(implausible(500.0, None), "")           # без расстояния не судим

    def test_aggregate_names_and_skips_suspect(self):
        from flightcostapp import market_fare as MF
        d = pathlib.Path(tempfile.mkdtemp())
        s = Store(d / "t.db")
        ap = {"EDDF": (50.03, 8.54), "LEBL": (41.30, 2.08),
              "UUEE": (55.97, 37.41), "UNNT": (55.01, 82.65)}
        s.commit_facts([Fact(domain="airport", key=k, valid_from="2026-01-01",
                             value_text=f"{la},{lo}|{k}|XX|{k}", source_id="t", extracted_by="t")
                        for k, (la, lo) in ap.items()]
                       + [Fact(domain="fx", key="RUB", valid_from="2026-01-01", value=95.0,
                               unit="per_EUR", currency="RUB", source_id="fx_rates",
                               extracted_by="t")])
        rows = []
        for i in range(6):
            day = f"2026-11-{i + 1:02d}"
            rows += [dict(kind=MF.KIND, key="EDDF-LEBL/d15_30/direct", value=80.0 + i,
                          unit="EUR", observed_at=day, source_id="market_fare"),
                     dict(kind=MF.KIND, key="UUEE-UNNT/d15_30/direct", value=7900.0 + i,
                          unit="EUR", observed_at=day, source_id="market_fare"),
                     dict(kind=MF.KIND, key="UNNT-UUEE/d15_30/direct", value=8100.0 + i,
                          unit="RUB", observed_at=day, source_id="market_fare")]
        s.add_observations(rows)
        rep = {}
        facts, notes = MF.aggregate(s, as_of="2026-10-17", report=rep)
        keys = {f.key for f in facts}
        self.assertIn("EDDF-LEBL/d15_30/direct", keys)
        self.assertIn("UNNT-UUEE/d15_30/direct", keys)          # честные рубли проходят
        self.assertNotIn("UUEE-UNNT/d15_30/direct", keys)
        self.assertEqual([x["key"] for x in rep["suspect"]], ["UUEE-UNNT/d15_30/direct"])
        self.assertTrue(any("цена неправдоподобна" in n for n in notes))
