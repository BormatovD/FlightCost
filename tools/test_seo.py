"""Страницы для поисковиков: языковые адреса, страницы типов, служебные файлы.

Поднимается настоящий `serve._Handler` с крошечным справочником (A320 из
openap и МС-21 из каталога с русским именем) и проверяется то, что видит
робот без скриптов: заголовок, canonical, hreflang, разметка, sitemap.
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
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp import seo                             # noqa: E402
from flightcostapp import serve as S                      # noqa: E402
from flightcostapp.store import Fact, Store               # noqa: E402

CYR = re.compile(r"[А-Яа-яЁё]")


def fact(key, value=None, text=None, src="aircraft_openap", note=None, source_note=None):
    return Fact(domain="aircraft", key=key, valid_from="2026-01-01", value=value, value_text=text,
                unit="", source_id=src, extracted_by="t", note=note, source_note=source_note)


class SeoHttp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(cls.tmp.name)
        cls.store = Store(d / "flightcost.db", shared=True)
        sn = "ПАО «Яковлев» | ПАО «Яковлев» (ОАК) | https://yakovlev.ru/products/mc-21/"
        cls.store.commit_facts([
            fact("A320/mtow_t", 78.0, note="Airbus A320"), fact("A320/seats_typical", 170.0),
            fact("A320/seats_max", 180.0), fact("A320/engine", text="CFM56-5B4"),
            fact("MS21/mtow_t", 85.0, src="aircraft_catalog", note="Яковлев МС-21-310 (импортозамещённый, ПД-14)",
                 source_note=sn),
            fact("MS21/seats_typical", 175.0, src="aircraft_catalog", source_note=sn),
            fact("MS21/engine", text="2× ПД-14", src="aircraft_catalog", source_note=sn),
            fact("USER:Z4/seats_max", 250.0, src="aircraft_catalog"),
        ])
        cls.ctx = S.Context(cls.store, {"sources": {}}, public=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), S._Handler)
        cls.httpd.ctx = cls.ctx
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        cls.store.db.close(); cls.tmp.cleanup()

    def get(self, path, lang=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Accept-Language": lang} if lang else {})
        r = c.getresponse()
        body = r.read().decode("utf-8", "replace")
        loc = r.getheader("Location")
        c.close()
        return r.status, body, loc

    def head_of(self, body):
        return body.split("</head>", 1)[0]

    def test_language_calc(self):
        for lg in seo.LANGS:
            st, body, _ = self.get(f"/{lg}/calc")
            self.assertEqual(st, 200)
            h = self.head_of(body)
            self.assertIn(f'<html lang="{lg}">', body)
            self.assertIn(f'<link rel="canonical" href="{seo.site()}/{lg}/calc">', h)
            for x in seo.LANGS:
                self.assertIn(f'hreflang="{x}" href="{seo.site()}/{x}/calc"', h)
            self.assertIn(f"<title>{seo.esc(seo.T[lg]['calc_title'])}</title>", h)
            # относительные адреса витрины не ломаются под /<язык>/calc
            self.assertIn('href="/ui.css"', body)
            self.assertIn('from "/geo.js"', body)
            self.assertNotIn('href="ui.css"', body)
            ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', h).group(1))
            self.assertEqual((ld["@type"], ld["offers"]["price"]), ("WebApplication", "0"))
            self.assertIn('<h1 class="vh">', body)
        st, _, loc = self.get("/en")
        self.assertEqual((st, loc), (301, "/en/"))
        self.assertEqual(self.get("/calc?ac=A320", "de")[2], "/de/calc?ac=A320")

    def test_landing(self):
        for lg in seo.LANGS:
            st, body, _ = self.get(f"/{lg}/")
            self.assertEqual(st, 200)
            self.assertIn(f"<title>{seo.esc(seo.T[lg]['home_title'])}</title>", body)
            self.assertIn(f'href="/{lg}/calc"', body)
            self.assertIn(f'href="/{lg}/types"', body)
            self.assertIn(f'href="/{lg}/calc?mode=net"', body)
            self.assertNotIn("I18N", body, "главная — не витрина")
        # старая ссылка с параметрами на языковой главной — в калькулятор
        self.assertEqual(self.get("/en/?ac=A320&o=EDDF")[2], "/en/calc?ac=A320&o=EDDF")

    def test_root(self):
        st, body, _ = self.get("/", "de-DE,de")
        self.assertEqual(st, 200)
        self.assertIn(f'<link rel="canonical" href="{seo.site()}/">', self.head_of(body))
        self.assertIn('<html lang="de">', body)
        self.assertNotIn("I18N", body)
        # ссылки промо и закладки с параметрами — сразу калькулятор
        st, body, _ = self.get("/?o=UUEE&d=EDDF&ac=A320")
        self.assertEqual(st, 200)
        self.assertIn("const I18N", body)

    def test_about_redirect_by_language(self):
        self.assertEqual(self.get("/about", "de-DE,de;q=0.9")[2], "/de/about")
        self.assertEqual(self.get("/types", "fr-FR")[2], "/en/types")
        st, body, _ = self.get("/ru/about")
        self.assertEqual(st, 200)
        faq = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', body)]
        self.assertIn("FAQPage", [x["@type"] for x in faq])

    def test_type_pages(self):
        st, body, _ = self.get("/en/type/A320")
        self.assertEqual(st, 200)
        self.assertIn("<h1>Airbus A320", body)
        self.assertIn('href="/en/calc?o=EDDF&amp;d=LEBL&amp;ac=A320"', body)
        self.assertIn("78.0", body)
        st, body, _ = self.get("/de/type/A320")
        self.assertIn("78,0", body)
        self.assertEqual(self.get("/en/type/a320")[2], "/en/type/A320")
        self.assertEqual(self.get("/en/type/ZZZZ")[0], 404)
        # тип без кода ИКАО (USER:) страницы не получает
        self.assertEqual(self.get("/en/type/Z4")[0], 404)

    def test_no_cyrillic_on_foreign_type_pages(self):
        for lg in ("en", "de"):
            st, body, _ = self.get(f"/{lg}/type/MS21")
            self.assertEqual(st, 200)
            main = body.split("<main>", 1)[1].split("</main>", 1)[0]
            self.assertFalse(CYR.search(main), CYR.findall(main)[:5])
            self.assertIn("Yakovlev MC-21", main)
            self.assertIn("yakovlev.ru", main)
        st, body, _ = self.get("/ru/type/MS21")
        self.assertIn("Яковлев МС-21", body)

    def test_types_index(self):
        st, body, _ = self.get("/en/types")
        self.assertEqual(st, 200)
        self.assertIn('href="/en/type/A320"', body)
        self.assertIn('href="/en/type/MS21"', body)
        self.assertNotIn("USER:", body)

    def test_service_files(self):
        st, body, _ = self.get("/robots.txt")
        self.assertIn(f"Sitemap: {seo.site()}/sitemap.xml", body)
        self.assertIn("Disallow: /api/", body)
        st, body, _ = self.get("/sitemap.xml")
        root = ET.fromstring(body)
        locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        for lg in seo.LANGS:
            self.assertIn(f"{seo.site()}/{lg}/type/A320", locs)
            self.assertIn(f"{seo.site()}/{lg}/about", locs)
        self.assertEqual(len(locs), len(set(locs)))
        st, body, _ = self.get("/llms.txt")
        self.assertIn("# FlightCost", body)
        self.assertEqual(self.get(f"/{seo.INDEXNOW_KEY}.txt")[1], seo.INDEXNOW_KEY)
        self.assertEqual(self.get("/og.png")[0], 200)
        self.assertEqual(self.get("/favicon.svg")[0], 200)


class CatalogNames(unittest.TestCase):

    def test_every_cyrillic_catalog_name_has_latin(self):
        """Новый тип каталога с русским именем без латинского — по-русски на английской странице."""
        for p in sorted((ROOT / "data" / "aircraft" / "catalog").glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            icao = str(d.get("icao") or "")
            if seo.TYPE_CODE.match(icao) and CYR.search(str(d.get("name") or "")):
                self.assertIn(icao, seo.LATIN, f"{p.name}: имя «{d['name']}» без латинского в seo.LATIN")

    def test_count_mapping(self):
        """Языковые страницы считаются по виду: страница типа — одна строка."""
        seen = []

        class V:
            def hit(self, page, ip, ua):
                seen.append(page)

        h = S._Handler.__new__(S._Handler)
        h.server = type("Srv", (), {"ctx": type("C", (), {"visits": V()})()})()
        h.headers = {}
        h.client_address = ("127.0.0.1", 0)
        for p in ("/en/", "/en/calc", "/de/about", "/ru/types", "/en/type/A320", "/en/type/B738", "/api/x"):
            h._count(p)
        self.assertEqual(seen, ["/en/", "/en/calc", "/de/about", "/ru/types", "/en/type", "/en/type"])


class TypeEconomics(unittest.TestCase):
    """Блок «экономика на типовом маршруте» из ответа ядра — без ядра."""

    J = {"route": {"distance_nm": 590, "block_h": 2.0, "fuel_kg": 4500, "seats": 170, "pax": 136},
         "answer": {"cost_total": 15000.0, "breakeven_fare_eur": 110.3, "feasible": True, "max_pax": 290,
                    "feasibility": {"ok": True, "limits": []}},
         "cost": [{"item": "fuel", "label": "Топливо", "eur": 9000.0, "prov": "default"},
                  {"item": "airport_charges", "label": "Аэропортовые сборы", "eur": 6000.0, "prov": "derived"}],
         "default_share": 0.6}

    def test_summary(self):
        e = seo.econ_summary(self.J)
        self.assertAlmostEqual(e["per_seat"], 15000 / 170)
        self.assertAlmostEqual(e["cask_ct"], 15000 / (170 * 590 * 1.852) * 100)
        self.assertAlmostEqual(e["per_bh"], 7500)
        self.assertFalse(e["no_model"])

    def test_block_translated_and_compared(self):
        e = seo.econ_summary(self.J)
        other = {**e, "seats": 180, "total": 16000.0, "per_seat": 16000 / 180, "cask_ct": 8.0}
        types = [{"icao": "A320", "name": "Airbus A320", "seats_typical": 170, "usable": True},
                 {"icao": "A20N", "name": "Airbus A320neo", "seats_typical": 180, "usable": True}]
        html = seo.econ_block("de", types[0], {}, {"A320": e, "A20N": other}, "narrow", types)
        self.assertIn("Frankfurt — Barcelona", html)
        self.assertIn("Treibstoff", html)
        self.assertNotRegex(html, CYR)
        self.assertIn('class="me"', html)
        self.assertIn("/de/type/A20N", html)

    def test_no_model_and_infeasible(self):
        nm = seo.econ_summary({**self.J, "answer": {**self.J["answer"], "feasible": False,
                               "feasibility": {"limits": [{"key": "no_model"}]}}})
        t = {"icao": "AT76", "name": "ATR 72-600", "seats_typical": 72, "usable": True}
        self.assertIn(seo.T["en"]["no_model"], seo.econ_block("en", t, {}, {"AT76": nm}, "regional", [t]))
        inf = seo.econ_summary({**self.J, "answer": {**self.J["answer"], "feasible": False, "max_pax": 90,
                                "feasibility": {"limits": [{"key": "mtow"}]}}})
        html = seo.econ_block("ru", t, {}, {"AT76": inf}, "regional", [t])
        self.assertIn("невыполним", html)
        self.assertIn("90 пассажиров", html)
        self.assertIn(seo.T["ru"]["econ_wait"], seo.econ_block("ru", t, {}, None, "regional", [t]))


if __name__ == "__main__":
    unittest.main()
