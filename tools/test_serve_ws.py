"""Рабочее место через HTTP: cookie, вход по ссылке, свой тип, экспорт.

Поднимается настоящий `serve._Handler` на свободном порту с крошечным
справочником и слоем гостя во временном каталоге; ядро не трогается —
проверяется только плёнка между браузером и слоем.
"""

from __future__ import annotations

import http.client
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import serve as S                      # noqa: E402
from flightcostapp.guest import GuestDB                   # noqa: E402
from flightcostapp.store import Fact, Store               # noqa: E402

DOC = {"icao": "user:a21n-my", "name": "A321neo моя", "valid_from": "2026-10-01",
       "source": "тест", "source_url": "https://example.test", "publisher": "я",
       "checked_at": "2026-10-01", "certainty": "exact",
       "fields": {"mtow_t": 97.0, "oew_t": 50.1, "fuel_capacity_t": 23.7, "seats_max": 244,
                  "span_m": 35.8, "cruise_mach": 0.78, "cruise_alt_m": 11000}}


class WsHttp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(cls.tmp.name)
        cls.store = Store(d / "flightcost.db", shared=True)
        cls.store.commit_facts([Fact(domain="aircraft", key="A320/mtow_t", valid_from="2026-01-01",
                                     value=78.0, unit="т", source_id="aircraft_openap",
                                     extracted_by="t")])
        cls.gdb = GuestDB(d / "user.db")
        cls.ctx = S.Context(cls.store, {"sources": {}}, public=True, gdb=cls.gdb)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), S._Handler)
        cls.httpd.ctx = cls.ctx
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        cls.store.db.close(); cls.gdb.db.close(); cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = {"Content-Type": "application/json"}
        if cookie:
            hdr["Cookie"] = f"fca_ws={cookie}"
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                  headers=hdr)
        r = c.getresponse()
        raw = r.read()
        set_cookie = r.getheader("Set-Cookie")
        loc = r.getheader("Location")
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = raw.decode("utf-8", "replace")
        c.close()
        return r.status, data, set_cookie, loc

    def test_full_cycle(self):
        st, d, ck, _ = self.call("GET", "/api/ws")
        self.assertEqual((st, d["enabled"], d["exists"]), (200, True, False))

        st, d, ck, _ = self.call("POST", "/api/ws/new", {})
        self.assertEqual(st, 200)
        key = d["key"]
        self.assertIn(f"fca_ws={key}", ck)
        self.assertNotIn("HttpOnly", ck, "страница показывает ссылку из cookie")
        self.assertIn("Secure", ck, "на публичной витрине cookie только по https")

        # без cookie — сохранение требует место
        st, d, _, _ = self.call("POST", "/api/aircraft/save", DOC)
        self.assertTrue(d.get("need_workspace"))

        # с cookie — тип ложится в слой гостя, не в справочник
        st, d, _, _ = self.call("POST", "/api/aircraft/save", DOC, cookie=key)
        self.assertTrue(d.get("ok"), d)
        self.assertEqual(d["icao"], "USER:A21N-MY")
        self.assertIsNone(self.store.get("aircraft", "USER:A21N-MY/mtow_t"))

        st, d, _, _ = self.call("GET", "/api/aircraft/type?icao=USER:A21N-MY", cookie=key)
        self.assertTrue(d["workspace"]); self.assertTrue(d["editable"])
        self.assertEqual({f["field"] for f in d["fields"]} >= {"mtow_t", "seats_max"}, True)
        st, d, _, _ = self.call("GET", "/api/aircraft/type?icao=USER:A21N-MY")
        self.assertIn("error", d, "без cookie своего типа не видно")

        # справочный код под своим ключом не переопределить
        st, d, _, _ = self.call("POST", "/api/aircraft/save", {**DOC, "icao": "A320"}, cookie=key)
        self.assertIn("USER:", d.get("error", ""))

        # настройки и сети — документами
        st, d, _, _ = self.call("POST", "/api/ws/doc", {"kind": "settings", "name": "default",
                                "body": {"overrides": {"fleet_economics.A320.lease_eur_month": 380000}}},
                                cookie=key)
        self.assertTrue(d["ok"])
        ctx = self.ctx.for_request(key)
        self.assertEqual(ctx._settings_overrides(), ["fleet_economics.A320.lease_eur_month=380000"])
        self.assertIs(self.ctx.for_request(None), self.ctx)
        self.assertIs(self.ctx.for_request("0" * 32), self.ctx, "неизвестный ключ — общий контекст")

        # экспорт, новая ссылка, старая закрыта
        st, d, _, _ = self.call("GET", "/api/ws/export", cookie=key)
        self.assertEqual(d["schema"], "fca.workspace/1")
        self.assertEqual(len(d["docs"]), 2)          # aircraft + settings
        st, d, ck, _ = self.call("POST", "/api/ws/rotate", {}, cookie=key)
        new = d["key"]
        st, d, _, _ = self.call("POST", "/api/ws/open", {"key": key})
        self.assertEqual((st, d.get("code")), (404, "missing"))
        st, d, ck, _ = self.call("POST", "/api/ws/open", {"key": new.upper()})
        self.assertEqual(st, 200)
        self.assertIn(f"fca_ws={new}", ck, "вход по ссылке ставит cookie")

        # Ссылка — /w#<ключ>: сервер видит только /w и отдаёт витрину; ключ
        # в адресе пути не принимается и в журнал не попадает.
        st, d, _, _ = self.call("GET", "/w")
        self.assertEqual(st, 200)
        self.assertIn("<html", str(d)[:200].lower())
        st, d, ck, _ = self.call("GET", f"/w/{new}")
        self.assertEqual(st, 200)
        self.assertIsNone(ck, "ключ в пути — не вход")

        # удаление места: cookie гасится, данные уходят
        st, d, ck, _ = self.call("POST", "/api/ws/delete", {}, cookie=new)
        self.assertIn("Max-Age=0", ck)
        st, d, _, _ = self.call("GET", "/api/ws", cookie=new)
        self.assertFalse(d["exists"])

    def test_health_counts_workspaces(self):
        st, d, _, _ = self.call("GET", "/healthz")
        self.assertIn("workspaces", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
