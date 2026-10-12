"""Валюта на витрине — пересчёт на экране по курсу с провенансом.

Что проверяется: разбор XML Банка России в единицы за евро; порядок
источников — ЕЦБ главнее ЦБ РФ там, где есть оба, ЦБ РФ главнее
объявленного файла; `/api/fx` отдаёт пять валют витрины, у каждой — курс
с датой и провенансом либо честное «курса нет»; страница не содержит
ни одного места, где число в евро печаталось бы мимо пересчёта.
"""

from __future__ import annotations

import http.client
import json
import pathlib
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import fx as FX                        # noqa: E402
from flightcostapp import serve as S                      # noqa: E402
from flightcostapp.parsers import cbr_fx                  # noqa: E402
from flightcostapp.store import Fact, Store               # noqa: E402

WEB = pathlib.Path(__file__).resolve().parents[1] / "flightcostapp" / "web"

CBR_XML = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="10.10.2026" name="Foreign Currency Market">
<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Доллар США</Name><Value>81,5000</Value><VunitRate>81,5</VunitRate></Valute>
<Valute ID="R01239"><NumCode>978</NumCode><CharCode>EUR</CharCode><Nominal>1</Nominal><Name>Евро</Name><Value>95,0000</Value><VunitRate>95</VunitRate></Valute>
<Valute ID="R01335"><NumCode>398</NumCode><CharCode>KZT</CharCode><Nominal>100</Nominal><Name>Тенге</Name><Value>15,8333</Value><VunitRate>0,158333</VunitRate></Valute>
<Valute ID="R01270"><NumCode>356</NumCode><CharCode>INR</CharCode><Nominal>10</Nominal><Name>Индийских рупий</Name><Value>9,2000</Value><VunitRate>0,92</VunitRate></Valute>
<Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal><Name>Юань</Name><Value>11,4000</Value><VunitRate>11,4</VunitRate></Valute>
<Valute ID="R01240"><NumCode>364</NumCode><CharCode>IRR</CharCode><Nominal>100000</Nominal><Name>Иранских риалов</Name><Value>4,8000</Value><VunitRate>0,000048</VunitRate></Valute>
""" + "".join(
    f'<Valute ID="X{i}"><NumCode>{i}</NumCode><CharCode>{c}</CharCode><Nominal>1</Nominal>'
    f'<Name>x</Name><Value>{10 + i},0</Value></Valute>\n'
    for i, c in enumerate(("GBP", "CHF", "JPY", "AUD", "CAD", "SGD", "HKD", "NOK", "SEK", "DKK",
                           "PLN", "CZK", "HUF", "TRY", "BRL", "ZAR", "AMD", "AZN", "BYN", "UZS"))
) + "</ValCurs>"


class Parser(unittest.TestCase):

    def test_units_per_eur_and_cross(self):
        facts = cbr_fx.parse(CBR_XML.encode("windows-1251"), {"source_id": "cbr_fx"})
        by = {f.key: f for f in facts}
        self.assertEqual(by["RUB"].value, 95.0)
        self.assertEqual(by["RUB"].valid_from, "2026-10-10")
        self.assertEqual(by["RUB"].unit, "per_EUR")
        # Тенге: 100 KZT = 15.8333 RUB → 1 EUR = 95 / 0.158333 = 600 KZT
        self.assertAlmostEqual(by["KZT"].value, 600.0, places=2)
        self.assertIn("кросс", by["KZT"].note)
        self.assertNotIn("EUR", by, "евро за евро не факт")
        self.assertAlmostEqual(by["USD"].value, 95 / 81.5, places=4)

    def test_refuses_without_euro_or_date(self):
        with self.assertRaises(ValueError):
            cbr_fx.parse(CBR_XML.replace("<CharCode>EUR</CharCode>", "<CharCode>XXX</CharCode>")
                         .encode("windows-1251"), {"source_id": "cbr_fx"})
        with self.assertRaises(ValueError):
            cbr_fx.parse(CBR_XML.replace('Date="10.10.2026"', "").encode("windows-1251"),
                         {"source_id": "cbr_fx"})


class Registry(unittest.TestCase):
    """Источник заведён целиком: реестр → загрузка → парсер → гейт → домен fx."""

    def test_refresh_through_registry(self):
        from flightcostapp.refresh import load_registry, refresh_source
        tmp = tempfile.TemporaryDirectory()
        store = Store(pathlib.Path(tmp.name) / "f.db", shared=True)
        try:
            reg = load_registry()
            self.assertEqual(reg["sources"]["cbr_fx"]["domain"], "fx")
            r = refresh_source("cbr_fx", reg, store,
                               fetch=lambda url, timeout=60: (CBR_XML.encode("windows-1251"), "text/xml"))
            self.assertIn(r["outcome"], ("committed", "ok", "auto-committed", "proposal"), r)
            if r["outcome"] == "proposal":
                store.resolve_proposal(r["proposal_id"], True, "тест")
            self.assertEqual(store.value("fx", "RUB", "2026-10-12"), 95.0)
            self.assertAlmostEqual(store.value("fx", "KZT", "2026-10-12"), 600.0, places=2)
            # Риал — около двух миллионов за евро: гейт обязан это пропустить,
            # граница ловит сдвиг точки, а не экзотику (2026-10-12 отверг всё).
            self.assertAlmostEqual(store.value("fx", "IRR", "2026-10-12"), 95 / 0.000048, delta=1)
            q = FX.quote(store, "RUB", "2026-10-12")
            self.assertEqual((q["kind"], q["date"]), ("cbr", "2026-10-10"))
        finally:
            store.db.close(); tmp.cleanup()


class Priority(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(pathlib.Path(self.tmp.name) / "f.db", shared=True)

        def f(key, value, src, day, note=""):
            return Fact(domain="fx", key=key, valid_from=day, value=value, unit="per_EUR",
                        currency=key, source_id=src, extracted_by="t", note=note)
        self.store.commit_facts([
            f("USD", 1.16, "fx_rates", "2026-10-09"),
            f("USD", 1.1656, "cbr_fx", "2026-10-10"),                  # свежее, но ниже рангом
            f("RUB", 92.09, "fx_declared", "2025-12-31"),
            f("RUB", 95.0, "cbr_fx", "2026-10-10", "официальный курс Банка России"),
            f("KZT", 600.0, "cbr_fx", "2026-10-10", "кросс через рубль по курсам Банка России"),
        ])

    def tearDown(self):
        self.store.db.close(); self.tmp.cleanup()

    def test_ecb_over_cbr_over_declared(self):
        q = FX.quote(self.store, "USD", "2026-10-12")
        self.assertEqual((q["rate"], q["source"]), (1.16, "fx_rates"))
        self.assertIn("ЕЦБ", q["provenance"])
        q = FX.quote(self.store, "RUB", "2026-10-12")
        self.assertEqual((q["rate"], q["source"], q["date"]), (95.0, "cbr_fx", "2026-10-10"))
        self.assertIn("Банка России", q["provenance"])
        q = FX.quote(self.store, "KZT", "2026-10-12")
        self.assertIn("кросс", q["provenance"])
        self.assertEqual(FX.quote(self.store, "EUR", "2026-10-12")["rate"], 1.0)
        q = FX.quote(self.store, "INR", "2026-10-12")
        self.assertIsNone(q["rate"]); self.assertEqual(q["provenance"], "курса нет")

    def test_api_fx_lists_display_currencies(self):
        ctx = S.Context(self.store, {"sources": {}}, public=True)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), S._Handler); httpd.ctx = ctx
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
            c.request("GET", "/api/fx?as_of=2026-10-12")
            d = json.loads(c.getresponse().read())
        finally:
            httpd.shutdown(); httpd.server_close()
        self.assertEqual(d["base"], "EUR")
        self.assertEqual(set(d["rates"]), {"EUR", "USD", "RUB", "INR", "CNY"})
        self.assertEqual(d["rates"]["RUB"]["rate"], 95.0)
        self.assertIsNone(d["rates"]["CNY"]["rate"], "нет курса — null, а не выдумка")


class Page(unittest.TestCase):
    """Деньги на экране печатаются только через пересчёт.

    Прямое `f0(x)` у величины в евро — число, которое при выборе долларов
    останется в евро и будет выглядеть долларами. Ловится по именам полей
    ядра: всё, что называется *_eur*, cost_* и c.eur, идёт через m0/m2."""

    def test_no_euro_field_printed_raw(self):
        html = (WEB / "serve.html").read_text(encoding="utf-8")
        js = html[html.index('<script type="module">'):]
        raw = re.findall(r"\bf[02]\((?:a|t|c|cur|b\.yield|m|r\.answer)\.(?:breakeven_fare_eur|cost_total|cost_per_pax|"
                         r"yield_eur_pax|cost_per_block_h|eur|lo|hi|now|edge|limit)\b", js)
        self.assertEqual(raw, [], f"евро мимо пересчёта: {raw}")
        self.assertIn('id="cur"', html, "переключателя валюты нет в шапке")
        self.assertIn("/api/fx", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
