"""Страница «План и показатели»: план из data/plan.yaml, ряды из базы.

Проверяется то, что обещает страница: план читается и битый план ловится;
индекс ставок считается от базового месяца и не показывает строк закрытого
источника; страница отдаётся на трёх языках, есть в sitemap и в шапке.
"""

from __future__ import annotations

import http.client
import pathlib
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp import monitor as M                     # noqa: E402
from flightcostapp import serve as S                       # noqa: E402
from flightcostapp.store import Fact, Store                # noqa: E402

CYR = re.compile(r"[А-Яа-яЁё]{3,}")


def f(domain, key, vf, value, src):
    return Fact(domain=domain, key=key, valid_from=vf, value=value, unit="", source_id=src, extracted_by="t")


class Plan(unittest.TestCase):
    def test_repo_plan_is_valid_and_translated(self):
        items = M.load_plan()
        self.assertTrue(items)
        for it in items:
            for lg in ("en", "de"):
                self.assertTrue(it["title"].get(lg), f"{it['id']}: нет title.{lg}")

    def test_bad_status_is_an_error(self):
        p = pathlib.Path(tempfile.mkdtemp()) / "plan.yaml"
        p.write_text("items:\n  - {id: x, status: soon, area: calc, title: {ru: т}}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            M.load_plan(p)

    def test_author_credit_shown_as_given(self):
        items = [{"id": "a", "status": "next", "area": "data", "title": {"ru": "Тарифы Казани"},
                  "by": "Иван П.", "via": "bot #12", "added": "2026-11-06"}]
        h = M.plan_html("ru", items)
        self.assertIn("Иван П.", h)
        self.assertIn("Дальше", h)


class Order(unittest.TestCase):
    def test_timeline_done_then_now_then_plan(self):
        items = [{"id": "n", "status": "next", "area": "calc", "title": {"ru": "Следующее"}, "added": "2026-11-01"},
                 {"id": "w", "status": "now", "area": "calc", "title": {"ru": "Текущее"}, "added": "2026-11-02"},
                 {"id": "d2", "status": "done", "area": "calc", "title": {"ru": "Позднее"}, "added": "2026-10-01",
                  "done": "2026-11-04"},
                 {"id": "d1", "status": "done", "area": "calc", "title": {"ru": "Раннее"}, "added": "2026-10-01",
                  "done": "2026-11-01"}]
        h = M.plan_html("ru", items)
        pos = [h.index(f'id="p-{i}"') for i in ("d1", "d2", "w", "n")]
        self.assertEqual(pos, sorted(pos), "сверху вниз: сделанное по дате, в работе, дальше")


class Priority(unittest.TestCase):
    def test_order_before_date(self):
        items = [{"id": "a", "status": "next", "area": "calc", "title": {"ru": "Старое"}, "added": "2026-10-01"},
                 {"id": "b", "status": "next", "area": "calc", "title": {"ru": "Важное"}, "added": "2026-11-09", "order": 1}]
        h = M.plan_html("ru", items)
        self.assertLess(h.index('id="p-b"'), h.index('id="p-a"'), "пронумерованное — первым")


class Record(unittest.TestCase):
    def test_writes_only_changes(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "x.db")
        shares = {"default_share/EDDF-LEBL/A320": ("FRA–BCN A320", 0.40)}
        old = M._ref_shares
        M._ref_shares = lambda store: shares
        try:
            n1 = M.record(st, "2026-11-06")
            n2 = M.record(st, "2026-11-07")              # ничего не сдвинулось
            shares["default_share/EDDF-LEBL/A320"] = ("FRA–BCN A320", 0.38)
            n3 = M.record(st, "2026-11-08")
        finally:
            M._ref_shares = old
        self.assertGreaterEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(n3, 1)
        pts = M._history(st, "monitor", key="default_share/EDDF-LEBL/A320")["default_share/EDDF-LEBL/A320"]
        self.assertEqual(pts, [("2026-11-06", 0.40), ("2026-11-08", 0.38)])


class RefRoutes(unittest.TestCase):
    def test_iata_codes_and_seed_survives_failure(self):
        from flightcostapp import econ
        calls = []

        class R:
            def default_share(self):
                return 0.39

        def fake(store, o, d, **kw):
            calls.append((o, d))
            if o == "FRA":
                return R()
            raise KeyError(o)
        old = econ.route_economics
        econ.route_economics = fake
        try:
            st = Store(pathlib.Path(tempfile.mkdtemp()) / "x.db")
            dl = dict(M._default_share(st)["lines"])
        finally:
            econ.route_economics = old
        self.assertIn(("FRA", "BCN"), calls, "расчёт ключует аэропорты ИАТА")
        pts = dl["FRA–BCN A320"]
        self.assertEqual(pts[0], ("2026-11-01", 42.0))
        self.assertEqual(pts[-1][1], 39.0)
        self.assertNotIn("SVO–LED A320", dl, "без расчёта и истории линии нет")


class Index(unittest.TestCase):
    def test_index_from_base_month(self):
        s = {"Z1": [("2026-01-01", 10.0), ("2026-03-01", 11.0)],
             "Z2": [("2026-01-01", 20.0), ("2026-02-01", 24.0)]}
        idx = dict(M.rate_index(s))
        self.assertEqual(idx["2026-01"], 100.0)
        self.assertEqual(idx["2026-02"], 110.0)            # медиана (100, 120)
        self.assertEqual(idx["2026-03"], 115.0)            # медиана (110, 120)

    def test_ans_per_100km_by_continent(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "x.db")
        st.commit_facts([f("enroute_rate", "EDZZ", "2026-01-01", 60.0, "crco_enroute_rates"),
                         f("enroute_rate", "LFZZ", "2026-01-01", 80.0, "crco_enroute_rates")])
        a = M._ans(st)
        v = dict(a["lines"]["europe_ec"])["2026-01"]
        self.assertAlmostEqual(v, 70 * (78 / 50) ** 0.5, delta=0.1)    # среднее ставок × √(MTOW/50)
        self.assertEqual(a["n"]["europe_ec"], 2)

    def test_russia_one_line_after_damper(self):
        st = Store(pathlib.Path(tempfile.mkdtemp()) / "x.db")
        st.commit_facts([f("fx", "RUB", "2026-01-01", 100.0, "cbr_fx"), f("fx", "USD", "2026-01-01", 1.0, "fx_rates")])
        regs = [{"code": "russia_centre", "k": 1.2, "conf": "", "line": [("2026-09", 1200)]},
                {"code": "russia_siberia", "k": 1.0, "conf": "", "line": [("2026-09", 1000)]},
                {"code": "europe", "k": 1.1, "conf": "", "line": [("2026-09", 1100)]}]
        out = M._russia_net(st, regs, [("2026-08", 47000.0)], 3000.0)
        ru = [r for r in out if r["code"] == "russia"]
        self.assertEqual(len(ru), 1)
        self.assertEqual(len(out), 2)
        # (47 000 + 3 000) руб/т ÷ 100 руб/USD = 500 USD/т вычета; демпфер прошлого месяца действует
        self.assertEqual(ru[0]["line"], [("2026-09", 700)])
        self.assertEqual(ru[0]["band"], [("2026-09", 500, 700)])

    def test_correction_overrides_same_date(self):
        d = tempfile.mkdtemp()
        st = Store(pathlib.Path(d) / "x.db")
        st.commit_facts([f("jet_fuel_price", "spot/USGC", "2026-01-05", 2.0, "jet_fuel_price")])
        st.commit_facts([f("jet_fuel_price", "spot/USGC", "2026-01-05", 2.5, "jet_fuel_price")])
        self.assertEqual(M._history(st, "jet_fuel_price", key="spot/USGC")["spot/USGC"], [("2026-01-05", 2.5)])


class Http(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        st = Store(pathlib.Path(cls.tmp.name) / "flightcost.db", shared=True)
        facts = []
        for m in range(1, 13):
            facts.append(f("jet_fuel_price", "spot/USGC", f"2025-{m:02d}-03", 2.0 + m / 20, "jet_fuel_price"))
            facts.append(f("enroute_rate", "EDZZ", f"2025-{m:02d}-01", 60 + m, "crco_enroute_rates"))
            facts.append(f("enroute_rate", "LFZZ", f"2025-{m:02d}-01", 55 + m / 2, "crco_enroute_rates"))
        st.commit_facts(facts)
        cls.ctx = S.Context(st, {"sources": {}}, public=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), S._Handler)
        cls.httpd.ctx = cls.ctx
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")

    def test_plan_tab_three_languages(self):
        for lg in ("ru", "en", "de"):
            code, body = self.get(f"/{lg}/monitor")
            self.assertEqual(code, 200, lg)
            self.assertIn(f'<html lang="{lg}"', body)
            self.assertIn('href="/%s/monitor"' % lg, body)
            if lg != "ru":
                main = body.split("<main>")[1].split("</main>")[0]
                words = [w for w in CYR.findall(re.sub(r"<[^>]+>", " ", main))]
                self.assertLessEqual(len(words), 3, f"{lg}: {words[:8]}")

    def test_series_tab_draws_and_hides_closed_rows(self):
        code, body = self.get("/ru/monitor?tab=series")
        self.assertEqual(code, 200)
        self.assertIn("<svg", body)
        self.assertIn("Европа (EUROCONTROL)", body)
        self.assertIn("Доля заготовки", body)
        # Ставки CRCO закрыты лицензией: на странице — индекс, а не ставка зоны.
        self.assertNotIn("EDZZ", body)

    def test_sitemap_and_nav(self):
        _, sm = self.get("/sitemap.xml")
        self.assertIn("/ru/monitor", sm)
        _, body = self.get("/en/about")
        self.assertIn('href="/en/monitor"', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
