"""Модель потока по населению (решение 214)."""

import io
import json
import math
import pathlib
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import traffic_model as TM  # noqa: E402
from flightcostapp.fare_model import _km       # noqa: E402
from flightcostapp.store import Fact, Store    # noqa: E402

# Аэропорт = город одного размера в его точке. Поток задан законом
# 300 · (Pa·Pb/10¹²)^0,8 · (км/1000)^−0,9 в месяц с шумом ±25 %.
AP = {"EDDF": (50.03, 8.54, 5.0e6), "LEBL": (41.30, 2.08, 5.5e6), "LIRF": (41.80, 12.24, 4.3e6),
      "LPPT": (38.78, -9.14, 2.9e6), "LEMD": (40.47, -3.56, 6.6e6), "EGLL": (51.47, -0.45, 14e6),
      "EHAM": (52.31, 4.76, 2.5e6), "LFPG": (49.01, 2.55, 12e6), "LOWW": (48.11, 16.57, 2.9e6),
      "EPWA": (52.17, 20.97, 3.1e6), "LGAV": (37.94, 23.94, 3.7e6), "EKCH": (55.62, 12.65, 2.1e6),
      "ESSA": (59.65, 17.92, 2.4e6), "LHBP": (47.44, 19.26, 3.0e6)}


def law(pa, pb, km):
    return 300 * (pa * pb / 1e12) ** 0.8 * (km / 1000) ** -0.9


def store_with(n_pairs=60, cities=True):
    s = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
    f = [Fact(domain="airport", key=k, valid_from="2026-01-01",
              value_text=f"{la},{lo}|{k}|XX|{k}", source_id="t", extracted_by="t")
         for k, (la, lo, _) in AP.items()]
    if cities:
        f += [Fact(domain="city", key=str(i), valid_from="2026-01-01", value=p, unit="жителей",
                   value_text=f"{la},{lo}|XX|{k}", source_id="t", extracted_by="t")
              for i, (k, (la, lo, p)) in enumerate(AP.items())]
    keys = sorted(AP)
    pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]][:n_pairs]
    for i, (a, b) in enumerate(pairs):
        km = _km(AP[a][:2], AP[b][:2])
        pax = law(AP[a][2], AP[b][2], km) * (1.25 if i % 2 else 0.8)
        f.append(Fact(domain="traffic", key=f"eurostat_par/{a}-{b}/2025", valid_from="2026-01-01",
                      value=pax * 12, unit="пасс/год",
                      value_text=json.dumps({f"{m:02d}": [round(pax), None, None] for m in range(1, 13)}),
                      source_id="eurostat_par", extracted_by="t"))
    s.commit_facts(f)
    return s, pairs


class Model(unittest.TestCase):

    def test_law_recovered(self):
        s, _ = store_with()
        m = TM.fit(s, "2026-10-01")
        self.assertGreaterEqual(m["n"], 30)
        P = m["P"]
        self.assertAlmostEqual(P["coef"][1], 0.8, delta=0.15)      # масса — жители
        self.assertLess(P["factor_cv"], 1.5)
        self.assertIn("T", m)                                       # массы по статистике тоже есть
        self.assertGreater(m["T"]["r2"], 0.5)

    def test_estimate_is_labelled_and_close(self):
        s, pairs = store_with(n_pairs=60)
        a, b = "LHBP", "LPPT"                       # пара вне выборки подгонки
        self.assertNotIn((a, b), pairs)
        km = _km(AP[a][:2], AP[b][:2])
        pax, why = TM.estimate(s, a, b, km, "2026-10-01")
        truth = law(AP[a][2], AP[b][2], km)
        self.assertLess(abs(math.log(pax / truth)), math.log(2.0))
        self.assertTrue(why.startswith("модель:"))
        self.assertIn("по статистике", why)                          # оба аэропорта есть в статистике
        self.assertIn("не знает туризма", why)

    def test_airport_without_statistics_uses_residents(self):
        s, _ = store_with(n_pairs=60)
        km = _km(AP["LHBP"][:2], (48.86, 2.35))
        s.commit_facts([Fact(domain="airport", key="LFPO", valid_from="2026-01-01",
                             value_text="48.72,2.38|LFPO|FR|Orly", source_id="t", extracted_by="t")])
        pax, why = TM.estimate(s, "LHBP", "LFPO", km, "2026-10-01")
        self.assertIsNotNone(pax)
        self.assertIn("LFPO — по жителям", why)

    def test_no_cities_no_model(self):
        s, _ = store_with(cities=False)
        pax, why = TM.estimate(s, "EDDF", "LEBL", 1100, "2026-10-01")
        self.assertIsNone(pax)
        self.assertIn("geonames_cities", why)

    def test_few_pairs_no_model(self):
        s, _ = store_with(n_pairs=10)
        pax, why = TM.estimate(s, "EDDF", "LEBL", 1100, "2026-10-01")
        self.assertIsNone(pax)
        self.assertIn("нужно 30", why)

    def test_city_without_split_is_one_node(self):
        """Сводка по РФ даёт Москву городом (@MOW): её поток — масса Шереметьева,
        а оценка пары с Москвой — поток всего города, с подписью."""
        s, _ = store_with()
        mos = (55.97, 37.41, 17e6)
        f = [Fact(domain="airport", key="UUEE", valid_from="2026-01-01",
                  value_text=f"{mos[0]},{mos[1]}|UUEE|RU|SVO", source_id="t", extracted_by="t"),
             Fact(domain="city", key="mos", valid_from="2026-01-01", value=mos[2], unit="жителей",
                  value_text=f"{mos[0]},{mos[1]}|RU|Moscow", source_id="t", extracted_by="t")]
        for k in ("EDDF", "LFPG", "EGLL"):
            pax = law(mos[2], AP[k][2], _km(mos[:2], AP[k][:2]))
            a, b = sorted(("@MOW", k))
            f.append(Fact(domain="traffic", key=f"ru_pairs/{a}-{b}/2025", valid_from="2026-01-01",
                          value=pax * 12, unit="пасс/год",
                          value_text=json.dumps({"A": [round(pax * 12), None, None]}),
                          source_id="ru_pairs", extracted_by="t"))
        s.commit_facts(f)
        _, thr = TM._flows(s, "2026-10-01")
        self.assertIn("@MOW", thr)
        self.assertNotIn("UUEE", thr)
        pax, why = TM.estimate(s, "UUEE", "LOWW", 1650, "2026-10-01")
        self.assertIsNotNone(pax)
        self.assertIn("весь город", why)

    def test_catchment_decays_with_distance(self):
        s, _ = store_with()
        near = TM.catchment(s, 50.03, 8.54)             # во Франкфурте
        far = TM.catchment(s, 50.03, 8.54 + 1.4)        # ≈ 100 км восточнее
        self.assertGreater(near, far)
        self.assertGreaterEqual(far, TM.MIN_CATCH)


class AirportEffects(unittest.TestCase):

    def test_hidden_hub_factor_is_learned(self):
        """Решение 217: у аэропортов скрытый «характер» (хаб, курорт) —
        поправка по их собственным парам снимает его почти до шума."""
        import random
        random.seed(1)
        aps = {f"E{chr(65 + i // 26)}{chr(65 + i % 26)}X":
               (40 + random.random() * 15, -5 + random.random() * 25,
                random.choice([0.5e6, 1e6, 2e6, 5e6]), math.exp(random.gauss(0, 0.8)))
               for i in range(30)}
        s = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        f = [Fact(domain="airport", key=k, valid_from="2026-01-01",
                  value_text=f"{la},{lo}|{k}|XX|{k}", source_id="t", extracted_by="t")
             for k, (la, lo, _, _) in aps.items()]
        f += [Fact(domain="city", key=str(i), valid_from="2026-01-01", value=p, unit="ж",
                   value_text=f"{la},{lo}|XX|c", source_id="t", extracted_by="t")
              for i, (la, lo, p, _) in enumerate(aps.values())]
        keys = sorted(aps)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                km = _km(aps[a][:2], aps[b][:2])
                if random.random() > 0.6 or km < 100:
                    continue
                pax = (law(aps[a][2], aps[b][2], km) * aps[a][3] * aps[b][3]
                       * math.exp(random.gauss(0, 0.3)))
                f.append(Fact(domain="traffic", key=f"eurostat_par/{a}-{b}/2025",
                              valid_from="2026-01-01", value=pax * 12, unit="п",
                              value_text=json.dumps({f"{m:02d}": [round(pax), None, None]
                                                     for m in range(1, 13)}),
                              source_id="eurostat_par", extracted_by="t"))
        s.commit_facts(f)
        m = TM.fit(s, "2026-10-01")
        self.assertLess(m["F"]["factor_cv"], m["T"]["factor_cv"])
        self.assertLess(m["F"]["factor_cv"], 1.4)


class Parser(unittest.TestCase):

    def test_geonames_rows(self):
        from flightcostapp.parsers.geonames_cities import parse
        rows = ["2925533\tFrankfurt am Main\tFrankfurt\t\t50.11552\t8.68417\tP\tPPLA2\tDE\t\t05\t06\t06412\t"
                "06412000\t763380\t\t112\tEurope/Berlin\t2024-01-01",
                "1\tTiny\tTiny\t\t1\t1\tP\tPPL\tXX\t\t\t\t\t\t900\t\t\t\t",
                "2\tLake\tLake\t\t1\t1\tH\tLK\tXX\t\t\t\t\t\t0\t\t\t\t"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("cities15000.txt", "\n".join(rows))
        facts = parse(buf.getvalue(), {"source_id": "geonames_cities", "today": "2026-10-17"})
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, 763380.0)
        self.assertEqual(facts[0].value_text, "50.1155,8.6842|DE|Frankfurt am Main")


if __name__ == "__main__":
    unittest.main(verbosity=2)
