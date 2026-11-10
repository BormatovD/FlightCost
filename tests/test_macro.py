"""Макрофакторы спроса: разбор Всемирного банка, Eurostat (JSON-stat), GISCO, виз и мигрантов ООН."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from flightcostapp.parsers import eurostat_json, gisco_nuts, lessor_xbrl, migrant_stock, visa_index, wb_wdi


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


if __name__ == "__main__":
    unittest.main()
