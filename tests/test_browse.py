"""Просмотр хранилища и политика видимости (решение 219), карта данных на сайте.

Главное здесь — что закрытое не утекает: строки источника `public: none`
на публичной витрине не видны ни в /api/browse, ни в образцах /api/data,
а /api/fact отдаёт по нему только действующее значение без истории.
Локально (`public=False`) видно всё: данные свои, лицензия ограничивает
публикацию, а не просмотр.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import browse as B                     # noqa: E402
from flightcostapp import serve as S                      # noqa: E402
from flightcostapp.store import Fact, Store               # noqa: E402

REG = {"sources": {
    "ourairports": {"title": "OurAirports", "public": "full", "license": "public-domain"},
    "market_fare": {"title": "Агрегатор", "public": "none", "license": "check-terms"},
    "nameless": {"title": "Без поля"},
}}
DAY = "2026-01-01"


class Browse(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(pathlib.Path(self.tmp.name) / "f.db", shared=True)
        f = lambda dom, key, src, **kw: Fact(domain=dom, key=key, valid_from=DAY,  # noqa: E731
                                             source_id=src, extracted_by="t", **kw)
        self.store.commit_facts([
            f("airport", "FRA", "ourairports", unit="wgs84", value_text="50.0,8.5|EDDF|DE|Frankfurt"),
            f("airport", "BCN", "ourairports", unit="wgs84", value_text="41.3,2.1|LEBL|ES|Barcelona"),
            f("market_fare", "FRA-BCN/d15_30/direct", "market_fare", value=88.0, unit="EUR",
              note="выписка агрегатора"),
            f("market_fare", "FRA-MAD/d15_30/direct", "market_fare", value=99.0, unit="EUR"),
            f("airport", "XXX", "nameless", unit="wgs84", value_text="0,0|XXXX|ZZ|Secret"),
        ])
        self.store.commit_facts([
            Fact(domain="market_fare", key="FRA-BCN/d15_30/direct", valid_from="2026-02-01",
                 source_id="market_fare", extracted_by="t", value=91.0, unit="EUR")])

    def tearDown(self):
        self.store.db.close(); self.tmp.cleanup()

    def test_policy_defaults_to_closed(self):
        p = B.policy(REG)
        self.assertTrue(p["ourairports"]["public"])
        self.assertFalse(p["market_fare"]["public"])
        self.assertFalse(p["nameless"]["public"])          # без поля — закрыт

    def test_catalog_counts_open_and_closed(self):
        c = {d["domain"]: d for d in B.catalog(self.store, REG, as_of="2026-03-01")["domains"]}
        self.assertEqual((c["airport"]["open"], c["airport"]["closed"]), (2, 1))
        self.assertEqual((c["market_fare"]["open"], c["market_fare"]["closed"]), (0, 2))
        self.assertEqual(list(c)[:1], ["airport"])          # порядок — как в DOMAINS

    def test_rows_hide_closed_sources(self):
        r = B.rows(self.store, REG, "airport", as_of="2026-03-01")
        self.assertEqual([x["key"] for x in r["rows"]], ["BCN", "FRA"])
        self.assertEqual(r["closed"], 1)
        r = B.rows(self.store, REG, "market_fare", as_of="2026-03-01")
        self.assertEqual((r["rows"], r["closed"]), ([], 2))
        r = B.rows(self.store, REG, "airport", q="barc", as_of="2026-03-01")
        self.assertEqual([x["key"] for x in r["rows"]], ["BCN"])

    def test_local_sees_everything(self):
        r = B.rows(self.store, REG, "market_fare", as_of="2026-03-01", open_all=True)
        self.assertEqual(len(r["rows"]), 2)

    def test_public_context_filters_data_and_fact(self):
        ctx = S.Context(self.store, REG, public=True)
        d = {x["domain"]: x for x in ctx.data()["domains"]}
        srcs = {r["source"] for x in d.values() for r in x["shown"]}
        self.assertNotIn("market_fare", srcs)
        self.assertNotIn("nameless", srcs)
        fact = ctx.fact({"domain": "market_fare", "key": "FRA-BCN/d15_30/direct"})
        self.assertTrue(fact["restricted"])
        self.assertEqual(fact["history"], [])
        self.assertNotIn("note", fact["current"])
        open_fact = ctx.fact({"domain": "airport", "key": "FRA"})
        self.assertFalse(open_fact["restricted"])
        local = S.Context(self.store, REG, public=False)
        self.assertEqual(len(local.fact({"domain": "market_fare",
                                         "key": "FRA-BCN/d15_30/direct"})["history"]), 1)
        self.assertEqual(ctx.browse({"domain": "market_fare"})["rows"], [])
        self.assertEqual(len(local.browse({"domain": "market_fare"})["rows"]), 2)

    def test_pages_render(self):
        ctx = S.Context(self.store, REG, public=True)
        html = ctx.map_page().decode("utf-8")
        self.assertIn('id="rt"', html)                     # форма маршрута
        self.assertNotIn("/*I18N*/{}/*/I18N*/", html)      # каталог вшит
        self.assertNotIn("__WEB__", html)
        page = S._page("data.html").decode("utf-8")
        self.assertIn("/api/browse", page)
        self.assertNotIn("/*I18N*/{}/*/I18N*/", page)
        # `fca map` без сайта — без формы и без вызова API
        from flightcostapp.graph import to_html
        self.assertNotIn("/api/route", to_html(REG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
