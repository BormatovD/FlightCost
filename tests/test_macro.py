"""Макрофакторы спроса: разбор Всемирного банка, Eurostat (JSON-stat), GISCO, виз и мигрантов ООН."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from flightcostapp.parsers import eurostat_json, gisco_nuts, lessor_xbrl, migrant_stock, visa_index, wb_wdi
from flightcostapp.refresh import load_registry, refresh_source
from flightcostapp.store import Fact, Store


def ctx(**kw):
    return {"source_id": "t", "sha": "x", "today": "2026-11-10", "node": "src_macro", **kw}


class Parsers(unittest.TestCase):

    def test_world_bank(self):
        blob = json.dumps([{"page": 1, "pages": 1}, [
            {"indicator": {"id": "NY.GDP.PCAP.PP.KD"}, "country": {"id": "DE"}, "date": "2024", "value": 61000.5},
            {"indicator": {"id": "SP.POP.TOTL"}, "country": {"id": "DE"}, "date": "2024", "value": 84e6},
            {"indicator": {"id": "ST.INT.ARVL"}, "country": {"id": "DE"}, "date": "2024", "value": None}]]).encode()
        f = wb_wdi.parse(blob, ctx())
        self.assertEqual(sorted(x.key for x in f), ["country/DE/gdp_pc_ppp/2024", "country/DE/pop/2024"])

    def test_world_bank_rejects_partial_response(self):
        row = {"indicator": {"id": "SP.POP.TOTL"}, "country": {"id": "DE"},
               "date": "2024", "value": 84e6}
        for meta in ({"pages": 2}, {"pages": 1, "total": 2},
                     {"pages": 1, "total": "2"}):
            with self.subTest(meta=meta):
                with self.assertRaisesRegex(ValueError, "неполный ответ API"):
                    wb_wdi.parse(json.dumps([meta, [row]]).encode(), ctx())

    def test_world_bank_total_counts_null_rows(self):
        row = {"indicator": {"id": "SP.POP.TOTL"}, "country": {"id": "DE"},
               "date": "2024", "value": 84e6}
        rows = [row, {**row, "date": "2025", "value": None}]
        for total in (2, "2"):
            with self.subTest(total=total):
                facts = wb_wdi.parse(
                    json.dumps([{"pages": 1, "total": total}, rows]).encode(), ctx())
                self.assertEqual(len(facts), 1)
                self.assertEqual(facts[0].key, "country/DE/pop/2024")

    def test_eurostat_json_stat(self):
        # 2 региона × 2 вида резидентов × 2 месяца; один пропуск
        d = {"id": ["freq", "c_resid", "unit", "geo", "time"], "size": [1, 2, 1, 2, 2],
             "dimension": {"freq": {"category": {"index": {"M": 0}}},
                           "c_resid": {"category": {"index": {"TOTAL": 0, "FOR": 1}}},
                           "unit": {"category": {"index": {"NR": 0}}},
                           "geo": {"category": {"index": {"DE21": 0, "ES53": 1}}},
                           "time": {"category": {"index": {"2025-07": 0, "2025-08": 1}}}},
             "value": {"0": 100, "1": 110, "2": 900, "3": 950, "4": 40, "5": 45, "6": 700}, "label": "nights"}
        f = eurostat_json.parse(json.dumps(d).encode(), ctx(indicator="nights", dims={"c_resid": ["TOTAL", "FOR"]}))
        k = {x.key: x.value for x in f}
        self.assertEqual(k["nuts/DE21/nights.TOTAL/2025-07"], 100)
        self.assertEqual(k["nuts/ES53/nights.FOR/2025-07"], 700)
        self.assertNotIn("nuts/ES53/nights.FOR/2025-08", k)
        self.assertEqual(len(f), 7)
        with self.assertRaises(ValueError):          # измерение без фильтра не угадывается
            eurostat_json.parse(json.dumps(d).encode(), ctx(indicator="nights"))

    def test_eurostat_separate_month_dimension(self):
        # Срез настоящего tour_occ_nin2m (ответ 10.11.2026): freq=A,
        # time=год, month=TOTAL/M01…M12. Прежний тест с freq=M этого не ловил.
        d = {"id": ["freq", "c_resid", "nace_r2", "month", "unit", "geo", "time"],
             "size": [1, 2, 1, 13, 1, 2, 1],
             "dimension": {
                 "freq": {"category": {"index": {"A": 0}}},
                 "c_resid": {"category": {"index": {"FOR": 0, "TOTAL": 1}}},
                 "nace_r2": {"category": {"index": {"I551-I553": 0}}},
                 "month": {"category": {"index": {
                     "TOTAL": 0, **{f"M{m:02}": m for m in range(1, 13)}}}},
                 "unit": {"category": {"index": {"NR": 0}}},
                 "geo": {"category": {"index": {"DE21": 0, "ES53": 1}}},
                 "time": {"category": {"index": {"2025": 0}}}},
             "value": {"0": 13136211, "1": 66695399, "2": 742374, "3": 207496,
                       "14": 1507795, "15": 11816186, "24": 1165927, "25": 303903,
                       "26": 43515689, "27": 73409037, "28": 2558633, "29": 289094,
                       "40": 5015392, "41": 12910531, "50": 3191560, "51": 383111}}
        settings = ctx(indicator="nights", dims={"c_resid": ["TOTAL", "FOR"]})
        facts = eurostat_json.parse(json.dumps(d).encode(), settings)
        self.assertEqual({f.key: f.value for f in facts}, {
            "nuts/DE21/nights.FOR/2025-01": 742374,
            "nuts/ES53/nights.FOR/2025-01": 207496,
            "nuts/DE21/nights.FOR/2025-07": 1507795,
            "nuts/ES53/nights.FOR/2025-07": 11816186,
            "nuts/DE21/nights.FOR/2025-12": 1165927,
            "nuts/ES53/nights.FOR/2025-12": 303903,
            "nuts/DE21/nights.TOTAL/2025-01": 2558633,
            "nuts/ES53/nights.TOTAL/2025-01": 289094,
            "nuts/DE21/nights.TOTAL/2025-07": 5015392,
            "nuts/ES53/nights.TOTAL/2025-07": 12910531,
            "nuts/DE21/nights.TOTAL/2025-12": 3191560,
            "nuts/ES53/nights.TOTAL/2025-12": 383111,
        })
        for fact in facts:
            self.assertEqual(fact.valid_from, fact.key.rsplit("/", 1)[1] + "-01")
        # Некалендарные коды не превращаются ни в месяцы 00/13, ни в годовой ряд.
        month = d["dimension"]["month"]["category"]["index"]
        month["M00"], month["M13"] = month.pop("M01"), month.pop("M12")
        valid = eurostat_json.parse(json.dumps(d).encode(), settings)
        self.assertEqual(len(valid), 4)
        self.assertTrue(all(f.key.endswith("/2025-07") for f in valid))

    def test_eurostat_annual_without_month_dimension(self):
        d = {"id": ["freq", "unit", "geo", "time"], "size": [1, 1, 1, 2],
             "dimension": {"freq": {"category": {"index": {"A": 0}}},
                           "unit": {"category": {"index": {"NR": 0}}},
                           "geo": {"category": {"index": {"DE21": 0}}},
                           "time": {"category": {"index": {"2024": 0, "2025": 1}}}},
             "value": {"0": 100, "1": 110}}
        facts = eurostat_json.parse(json.dumps(d).encode(), ctx(indicator="pop"))
        self.assertEqual([(f.key, f.valid_from, f.value) for f in facts], [
            ("nuts/DE21/pop/2024", "2024-01-01", 100),
            ("nuts/DE21/pop/2025", "2025-01-01", 110)])

    def test_gisco_and_visa(self):
        g = {"features": [{"properties": {"NUTS_ID": "DE212", "LEVL_CODE": 3, "CNTR_CODE": "DE",
                                          "NAME_LATN": "München"}, "geometry": {"coordinates": [11.57, 48.14]}}]}
        f = gisco_nuts.parse(json.dumps(g).encode(), ctx())
        self.assertEqual(f[0].key, "nuts_lb/DE212")
        self.assertTrue(f[0].value_text.startswith("48.1400,11.5700|3|DE"))
        rows = "Passport,Destination,Requirement\n" + "\n".join(
            f"A{i % 9},B{i % 7},{r}" for i, r in enumerate(["90", "visa required", "e-visa", "-1", "no admission"] * 250))
        f = visa_index.parse(rows.encode(), ctx())
        lv = {x.value_text: x.value for x in f}
        self.assertEqual((lv["90"], lv["e-visa"], lv["visa required"], lv["no admission"], lv["-1"]), (0, 1, 2, 3, 0))

    def test_migrant_stock(self):
        import openpyxl
        d = Path(tempfile.mkdtemp())
        (d / "m49.csv").write_text("Country or Area;M49 Code;ISO-alpha2 Code\nGermany;276;DE\nTürkiye;792;TR\n"
                                   "Poland;616;PL\n", "utf-8")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Table 1"
        ws.append(["International migrant stock"])
        ws.append(["Index", "Region of destination", "Location code of destination", "Region of origin",
                   "Location code of origin", 2015, 2020, 2024, 2015, 2020, 2024])
        ws.append([1, "Germany", 276, "Türkiye", 792, 1500000, 1480000, 1500000, 800000, 790000, 780000])
        ws.append([2, "Germany", 276, "Poland", 616, 1900000, 2000000, 2100000, 1, 1, 1])
        ws.append([3, "WORLD", 900, "Poland", 616, 9, 9, 9, 1, 1, 1])
        buf = io.BytesIO()
        wb.save(buf)
        (d / "ims.xlsx").write_bytes(buf.getvalue())
        f = migrant_stock.parse(buf.getvalue(), ctx(url=f"file:{d / 'ims.xlsx'}"))
        k = {x.key: x.value for x in f}
        self.assertEqual(k["migrants/DE-TR/2024"], 1500000)
        self.assertEqual(len(k), 6)                   # только оба пола, без строки WORLD


    def test_lessor_xbrl(self):
        d = {"cik": 1487712, "entityName": "AIR LEASE CORP", "facts": {"us-gaap": {
            "OperatingLeaseLeaseIncome": {"units": {"USD": [
                {"val": 2000e6, "frame": "CY2023"}, {"val": 2300e6, "frame": "CY2024"}, {"val": 2500e6, "frame": "CY2025"},
                {"val": 600e6, "frame": "CY2025Q3"}]}},
            "PropertySubjectToOrAvailableForOperatingLeaseNet": {"units": {"USD": [
                {"val": 22e9, "frame": "CY2022Q4I"}, {"val": 24e9, "frame": "CY2023Q4I"},
                {"val": 26e9, "frame": "CY2024Q4I"}, {"val": 28e9, "frame": "CY2025Q4I"}]}}}}}
        f = {x.key: x.value for x in lessor_xbrl.parse(json.dumps(d).encode(), ctx(ticker="AL"))}
        self.assertAlmostEqual(f["lessor/AL/lease_yield/2024"], 2300e6 / 25e9)
        self.assertNotIn("lessor/AL/lease_revenue/2025Q3", f)
        with self.assertRaises(ValueError):
            lessor_xbrl.parse(json.dumps({"facts": {"us-gaap": {}}}).encode(), ctx())


class Refresh(unittest.TestCase):

    def test_world_bank_completeness_uses_own_source(self):
        # Сохраняем настоящие пороги реестра: минимум 3000 строк, спад не
        # более 20%. Большой ряд Eurostat не является прежней поставкой WB.
        registry = load_registry()
        rows = [{"indicator": {"id": "SP.POP.TOTL"},
                 "country": {"id": chr(65 + c // 26) + chr(65 + c % 26)},
                 "date": str(y), "value": 100000 + c * 100 + y}
                for c in range(200) for y in range(2005, 2025)]

        def fetch_for(items):
            blob = json.dumps([{"page": 1, "pages": 1, "total": len(items)}, items]).encode()
            return lambda url: (blob, "application/json")

        # Артефакты тоже временные: put_artifact пишет data/raw от cwd.
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            st = Store(Path(tmp) / "macro.db")
            try:
                st.commit_facts([
                    Fact(domain="macro", key=f"nuts/TEST{i}/nights.TOTAL/2024-01",
                         valid_from="2024-01-01", value=1000,
                         source_id="eurostat_nights_nuts2")
                    for i in range(6000)
                ])
                full = refresh_source("wb_wdi", registry, st, fetch=fetch_for(rows))
                self.assertEqual(full["outcome"], "committed", full)
                self.assertEqual(st.count_keys("macro"), 10000)
                self.assertEqual(st.count_keys("macro", source_id="wb_wdi"), 4000)
                self.assertEqual(st.count_keys("macro", source_id="eurostat_nights_nuts2"), 6000)

                # 3000 строк проходят абсолютный минимум, но потеря четверти
                # собственной поставки должна по-прежнему остановить запись.
                reduced = refresh_source("wb_wdi", registry, st, fetch=fetch_for(rows[:3000]))
                self.assertEqual(reduced["outcome"], "rejected", reduced)
                errors = [f for f in reduced["findings"] if f["level"] == "error"]
                self.assertEqual([f["code"] for f in errors], ["count.drop"])
                self.assertIn("4000 -> 3000", errors[0]["message"])
                self.assertEqual(st.count_keys("macro", source_id="wb_wdi"), 4000)
            finally:
                st.db.close()


if __name__ == "__main__":
    unittest.main()
