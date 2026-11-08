"""Оплаченные тарифы США: DOT Consumer Airfare Report и свёртка DB1C.

Проверяется: разбор Table 1a по именам колонок, пара без направления, окно
с 2024 года; свёртка DB1C — только действительная доходность (VYield=1),
прямые рынки отдельно от всех, квантили и группы глубины продажи, порог
пассажиров; файл без заголовка читается по порядку полей из описания; оба
источника заведены в реестре, DB1C — только дома.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Инструмент из tools/ — по пути файла, не через sys.path: в tools/ лежат
# свои test_*.py, и с ним в пути обход тестов брал бы их вместо tests/.
import importlib.util                                        # noqa: E402
_spec = importlib.util.spec_from_file_location("db1c_fetch", ROOT / "tools" / "db1c_fetch.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

from flightcostapp import master                             # noqa: E402
from flightcostapp.parsers import db1c_agg, dot_car          # noqa: E402
from flightcostapp.refresh import load_registry              # noqa: E402

CAR = """Year,quarter,citymarketid_1,citymarketid_2,city1,city2,airportid_1,airportid_2,airport_1,airport_2,nsmiles,passengers,fare,carrier_lg,large_ms,fare_lg,carrier_low,lf_ms,fare_low
2025,3,30397,32575,"Atlanta, GA","Los Angeles, CA",10397,12892,LAX,ATL,1946,2210,"$312.45",DL,0.61,330.1,NK,0.12,180.2
2023,1,30397,32575,"Atlanta, GA","Los Angeles, CA",10397,12892,ATL,LAX,1946,2000,280.0,DL,0.6,300,NK,0.1,170
"""


def db1c_csv(header=True) -> bytes:
    cols = ["ITINID", "MKTID", "MKTCOUPONS", "ORIGIN", "DEST", "PASSENGERS", "MKTAMOUNT", "VYIELD",
            "PURCHASEWINDOWGROUP"]
    rows = []
    for i in range(400):                                   # ATL->LAX прямые: 100..499
        g = "21AP" if i < 100 else "2290" if i < 300 else "91UP"
        rows.append([i, i, 1, "ATL", "LAX", 1, 100 + i, 1, g])
    rows.append([999, 999, 1, "LAX", "ATL", 1, 0, 1, "2290"])        # нулевой тариф — мимо
    rows.append([998, 998, 1, "LAX", "ATL", 1, 5000, 0, "2290"])     # недействительная доходность — мимо
    rows.append([997, 997, 2, "LAX", "ATL", 1, 50, 1, "2290"])       # с пересадкой — только в «все»
    rows += [[i, i, 1, "BOS", "MIA", 1, 150, 1, "2290"] for i in range(10)]   # мелкая пара — ниже порога
    out = io.StringIO()
    import csv
    w = csv.writer(out)
    if header:
        w.writerow(cols)
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode()


class Car(unittest.TestCase):
    def test_table_1a(self):
        facts = dot_car.parse(CAR.encode(), {"source_id": "dot_car"})
        by = {f.key: f for f in facts}
        self.assertEqual(by["ATL-LAX/2025Q3/mean"].value, 312.45)
        self.assertEqual(by["ATL-LAX/2025Q3/mean"].valid_from, "2025-07-01")
        self.assertEqual(by["ATL-LAX/2025Q3/mean_low_carrier"].value, 180.2)
        self.assertFalse([k for k in by if "2023" in k], "до 2024 года не берётся")

    def test_missing_column_is_named(self):
        with self.assertRaises(ValueError) as e:
            dot_car.parse(b"Year,quarter,airport_1\n2025,1,ATL\n", {"source_id": "dot_car"})
        self.assertIn("fare", str(e.exception))


class Db1c(unittest.TestCase):
    def test_aggregate(self):
        doc = D.aggregate(io.BytesIO(db1c_csv()), "2025-07")
        self.assertEqual(set(doc["pairs"]), {"ATL-LAX"})
        d = doc["pairs"]["ATL-LAX"]["direct"]
        self.assertEqual(d["pax"], 400)
        self.assertAlmostEqual(d["mean"], 299.5)
        self.assertAlmostEqual(d["p50"], 299.5)
        self.assertAlmostEqual(d["share_21AP"], 0.25)
        self.assertAlmostEqual(d["mean_21AP"], 149.5)
        self.assertAlmostEqual(d["mean_91UP"], 449.5)
        self.assertEqual(doc["pairs"]["ATL-LAX"]["all"]["pax"], 401)
        self.assertEqual(doc["skipped"], 2)

    def test_headerless_file(self):
        cols = ["ITINID", "MKTID", "MKTCOUPONS", "ORIGIN", "DEST", "PASSENGERS", "MKTAMOUNT", "VYIELD",
                "PURCHASEWINDOWGROUP"]
        full = [c.upper() for c in [
            "ITINID", "MKTID", "GATEID", "MKTCOUPONS", "RPYEAR", "RPQUARTER", "RPMONTH", "SCHFLYR", "SCHFLQUARTER",
            "SCHFLMO", "ORIGINAIRPORTID", "ORIGINAIRPORTSEQID", "ORIGINCITYMARKETID", "ORIGIN", "ORIGINCOUNTRY",
            "ORIGINSTATEFIPS", "ORIGINSTATE", "ORIGINSTATENAME", "ORIGINWAC", "DESTAIRPORTID", "DESTAIRPORTSEQID",
            "DESTCITYMARKETID", "DEST", "DESTCOUNTRY", "DESTSTATE", "DESTSTATENAME", "DESTWAC", "AIRPORTGROUP",
            "WACGROUP", "DWELLTIMEGROUP", "SEGMENTVIAGROUP", "RPCARRIERAIRLINEID", "RPCARRIER",
            "ISSUINGCARRIERAIRLINEID", "ISSUINGCARRIER", "MARKETINGCARRIERAIRLINEID", "MKTCARRIER",
            "MKTCARRIERGROUP", "MKTCARRIERCHANGE", "OPERATINGCARRIERAIRLINEID", "OPCARRIER", "OPCARRIERGROUP",
            "OPCARRIERCHANGE", "PASSENGERS", "MKTAMOUNT", "MKTTAX", "VYIELD", "PURCHASEWINDOWGROUP",
            "TOTALDISTANCE", "MILESTRAVELED", "NONSTOPMILES", "MKTGEOTYPE", "ITINGEOTYPE", "BREAK_LEGACYLOGIC"]]
        import csv
        src = list(csv.reader(io.StringIO(db1c_csv(header=False).decode())))
        out = io.StringIO()
        w = csv.writer(out)
        for r in src:
            row = [""] * len(full)
            for c, v in zip(cols, r):
                row[full.index(c)] = v
            w.writerow(row)
        doc = D.aggregate(io.BytesIO(out.getvalue().encode()), "2025-07")
        self.assertEqual(doc["pairs"]["ATL-LAX"]["direct"]["pax"], 400)

    def test_parser_facts(self):
        doc = D.aggregate(io.BytesIO(db1c_csv()), "2025-07")
        facts = db1c_agg.parse(json.dumps(doc).encode(), {"source_id": "db1c_market"})
        by = {f.key: f for f in facts}
        self.assertEqual(by["ATL-LAX/2025-07/direct/mean"].value, 299.5)
        self.assertEqual(by["ATL-LAX/2025-07/direct/mean"].valid_from, "2025-07-01")
        self.assertEqual(by["ATL-LAX/2025-07/direct/share_91UP"].unit, "share")


class Zip(unittest.TestCase):
    def test_odd_inner_name_and_pipes(self):
        import tempfile
        import zipfile
        body = db1c_csv().decode().replace(",", "|").encode()
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "DB1C.202507.zip"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("readme.pdf", b"x")
            z.writestr("DB1C.202507/DB1C.MARKET.202507.parquet", b"PAR1" + b"\0" * 5000)
            z.writestr("__MACOSX/DB1C.202507/._DB1C.MARKET.202507.csv.zip", b"junk")
            z.writestr("T_DB1C_MARKET_202507.asc", body)
        old = D.AGG
        D.AGG = d / "agg"
        try:
            out = D.fold_zip(f, "2025-07")
        finally:
            D.AGG = old
        doc = json.loads(out.read_text())
        self.assertEqual(doc["pairs"]["ATL-LAX"]["direct"]["pax"], 400)

    def test_empty_fold_is_not_written(self):
        import tempfile
        import zipfile
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "DB1C.202508.zip"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("m.csv", "ORIGIN,DEST,MKTCOUPONS,PASSENGERS,MKTAMOUNT,VYIELD,PURCHASEWINDOWGROUP\n"
                                "ATL,LAX,1,1,100,0,2290\n")
        old = D.AGG
        D.AGG = d / "agg"
        try:
            with self.assertRaises(ValueError):
                D.fold_zip(f, "2025-08")
        finally:
            D.AGG = old
        self.assertFalse((d / "agg" / "DB1C-2025-08.json").exists())


class Links(unittest.TestCase):
    def test_closed_page_falls_back_to_known(self):
        import urllib.request
        old = urllib.request.urlopen

        def deny(*a, **k):
            raise urllib.error.HTTPError(D.INDEX, 403, "Forbidden", {}, None)
        import urllib.error
        urllib.request.urlopen = deny
        try:
            got = D.links()
        finally:
            urllib.request.urlopen = old
        self.assertIn("2025-07", got)
        self.assertTrue(got["2026-07"].endswith("DB1C.MARKET.202607.15OCT2026.zip"))

    def test_saved_page_adds_new_month(self):
        import tempfile
        f = pathlib.Path(tempfile.mkdtemp()) / "p.html"
        f.write_text('<a href="https://x.blob.core.windows.net/p/DB1C.MARKET.202608.12NOV2026.zip">Aug</a>')
        got = D.links(str(f))
        self.assertIn("2026-08", got)
        self.assertIn("2025-07", got)


class Registry(unittest.TestCase):
    def test_sources_and_home_only(self):
        reg = load_registry()["sources"]
        self.assertEqual(reg["dot_car"]["parser"], "dot_car")
        self.assertEqual(reg["db1c_market"]["path"], "data/raw/db1c/agg")
        self.assertIn("db1c_market", master.HOME_ONLY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
