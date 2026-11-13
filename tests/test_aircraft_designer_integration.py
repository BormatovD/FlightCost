"""Stage 2 is isolated from the legacy form and public reference database."""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from flightcostapp import aircraft_designer as A
from flightcostapp import serve as S
from flightcostapp.guest import GuestDB
from flightcostapp.store import Fact, Store


def design(icao="B752", *, seats=225, engine="RB211-535E4", model="b757-200-rb", layout="b752-225"):
    rows, last = divmod(seats, 6)
    if last:
        rows += 1
    zones = [{"class": "economy", "rows": rows, "seatsPerRow": 6, "pitchM": .75}]
    if last:
        zones[0]["lastRowSeats"] = last
    return {"protocol": A.PROTOCOL, "version": 1,
            "aircraft": {"icao": icao, "aircraftId": model, "engine": engine,
                         "weightProfile": "standard", "layoutId": layout,
                         "cabin": zones, "seats": seats},
            "weights": {"oew_kg": 58000, "mtow_kg": 110000, "mzfw_kg": 85000,
                        "mlw_kg": 90000, "fuel_capacity_kg": 35000},
            "geometry": {"length_m": 47.3, "span_m": 38.1},
            "model": {"mode": "fixed", "provisional": True, "controls": {}}}


def fact(key, value=None, text=None):
    return Fact(domain="aircraft", key=key, valid_from="2026-01-01",
                source_id="aircraft_catalog", extracted_by="stage2-test",
                note="Boeing 757 / A320neo", value=value, value_text=text, unit="")


class Contract(unittest.TestCase):
    def test_catalog_matches_both_real_model_variants(self):
        self.assertEqual([(c["engine"], c["seats"]) for c in A.choices("B752")],
                         [("RB211-535E4", n) for n in (186, 225, 239)]
                         + [("PW2037", n) for n in (186, 225, 239)])
        self.assertEqual({c["weightProfile"] for c in A.choices("T204")}, {"operational", "factory"})
        self.assertEqual(A.choices("A20N")[1]["seats"], 194)
        self.assertFalse(A.engine_matches("LEAP-1A", "PW1127G-JM"))
        self.assertTrue(A.engine_matches("ПС-90А", "PS-90A"))
        self.assertFalse(A.engine_matches("CFM56-5B", "CFM56-5B4"))

    def test_valid_seats_are_physical_zones_not_public_max(self):
        d = A.validate_design(design())
        self.assertEqual(d["aircraft"]["seats"], 225)
        self.assertEqual(A.new_user_key("B752", "12345678-abcd"), A.new_user_key("B752", "12345678-abcd"))
        self.assertNotEqual(A.new_user_key("B752", "12345678-abcd"), A.new_user_key("B752", "87654321-abcd"))

    def test_rejects_forgery_and_invalid_inputs(self):
        good = design()
        for change in (
            lambda d: d.update(version=True),
            lambda d: d["aircraft"].update(engine="PW2037"),
            lambda d: d["aircraft"].update(aircraftId="b757-200-pw"),
            lambda d: d["aircraft"].update(seats=239),
            lambda d: d["aircraft"].update(layoutId="b752-194"),
            lambda d: d["aircraft"].update(weightProfile="factory"),
            lambda d: d["aircraft"]["cabin"][0].update(lastRowSeats=7),
            lambda d: d["aircraft"]["cabin"][0].update(rows=True),
            lambda d: d["weights"].update(mzfw_kg=56000),
            lambda d: d["weights"].update(oew_kg=float("nan")),
            lambda d: d["geometry"].update(span_m=float("inf")),
            lambda d: d["model"].update(provisional=False),
        ):
            d = json.loads(json.dumps(good))
            change(d)
            with self.subTest(d=d), self.assertRaises(ValueError):
                A.validate_design(d)

    def test_preserve_mzfw_and_do_not_fake_engine_equivalence(self):
        base = {"icao": "USER:B752-MY", "name": "B757", "engine": "RB211-535E4",
                "fields": {"seats_max": 239, "seats_typical": 239, "cruise_alt_m": 11000},
                "burn": {"analog": "B752", "same_engine": True}}
        doc, same = A.make_workspace_doc(base, design(), user_icao="USER:B752-3D-ABC",
                                             reference_engine="RB211-535E4")
        self.assertTrue(same)
        self.assertEqual((doc["fields"]["seats_typical"], doc["fields"]["seats_max"]), (225, 239))
        self.assertEqual(doc["aircraft_designer"]["mzfw_t"], 85.)
        self.assertEqual(doc["fields"]["oew_t"], 58.)
        doc, same = A.make_workspace_doc(base, design(), user_icao="USER:B752-3D-ABC",
                                             reference_engine="PW2037")
        self.assertFalse(same)
        self.assertNotIn("burn", doc)
        self.assertEqual(doc["aircraft_designer"]["original_passport_seats_max"], 239)
        self.assertFalse(doc["aircraft_designer"]["selected_seats_exceed_passport"])
        design_ = design(seats=239)
        baseline = dict(base, fields={**base["fields"], "seats_max": 225})
        stretched, _ = A.make_workspace_doc(baseline, design_, user_icao="USER:B752-3D-ABC",
                                             reference_engine="RB211-535E4")
        self.assertEqual(stretched["fields"]["seats_max"], 239)
        self.assertEqual(stretched["aircraft_designer"]["original_passport_seats_max"], 225)
        self.assertTrue(stretched["aircraft_designer"]["selected_seats_exceed_passport"])
        self.assertIn("NOT a new certification", stretched["source"])


class ApiHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(cls.tmp.name)
        cls.store = Store(d / "reference.db", shared=True)
        f = []
        for key, eng, seats in (("B752", "RB211-535E4", 225), ("A20N", "PW1127G-JM", 180)):
            for field, val in {"mtow_t": 110., "oew_t": 58., "mlw_t": 90.,
                               "fuel_capacity_t": 35., "span_m": 38.1, "length_m": 47.3,
                               "cruise_mach": .8, "cruise_alt_m": 11000,
                               "seats_max": 239, "seats_typical": seats}.items():
                f.append(fact(key + "/" + field, val))
            f.append(fact(key + "/engine", text=eng))
            f.append(fact(key + "/burn_analog", text=key))
            f.append(fact(key + "/burn_same_engine", value=1))
        cls.store.commit_facts(f)
        cls.gdb = GuestDB(d / "user.db")
        cls.ctx = S.Context(cls.store, {"sources": {}}, public=True, gdb=cls.gdb)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), S._Handler)
        cls.httpd.ctx = cls.ctx
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        cls.store.db.close(); cls.gdb.db.close(); cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=None, origin=None, ctype="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=7)
        headers = {"Content-Type": ctype}
        if cookie: headers["Cookie"] = "fca_ws=" + cookie
        if origin is not None: headers["Origin"] = origin
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        r = conn.getresponse(); raw = r.read(); code = r.status
        try: out = json.loads(raw)
        except (ValueError, TypeError): out = raw.decode(errors="replace")
        conn.close()
        return code, out

    def test_feature_switch_and_static_assets(self):
        with patch.dict(os.environ, {"FCA_AIRCRAFT_DESIGNER": "0"}):
            st, html = self.call("GET", "/ru/type/B752")
            self.assertEqual(st, 200)
            self.assertNotIn('id="fc3d"', html)
            st, data = self.call("POST", "/api/aircraft/designer-save",
                                 {"requestId": "12345678-abc", "design": design()},
                                 origin="https://flightcost.app")
            self.assertEqual(st, 404)
        st, js = self.call("GET", "/flightcost-embed.nomodule.js")
        self.assertEqual(st, 200)
        self.assertIn("DESIGN_EXPORT", js)
        st, js = self.call("GET", "/flightcost-aircraft-designer.js")
        self.assertEqual(st, 200)
        self.assertIn("/api/aircraft/designer-save", js)

    def test_opt_in_page_and_guest_isolation(self):
        with patch.dict(os.environ, {"FCA_AIRCRAFT_DESIGNER": "1"}):
            st, html = self.call("GET", "/ru/type/B752")
            self.assertEqual(st, 200)
            self.assertIn('id="fc3d"', html)
            self.assertIn('id="edopen"', html)
            self.assertIn('"layoutId": "b752-225"', html)
            for lang, headline in (("en", "Explore and modify"),
                                   ("de", "Flugzeug in 3D")):
                st, translated = self.call("GET", "/" + lang + "/type/B752")
                self.assertEqual(st, 200)
                self.assertIn('id="fc3d"', translated)
                self.assertIn(headline, translated)
            body = {"requestId": "request001-abc", "design": design()}
            st, result = self.call("POST", "/api/aircraft/designer-save", body)
            self.assertEqual(st, 403)
            st, result = self.call("POST", "/api/aircraft/designer-save", body,
                                   origin="https://evil.example")
            self.assertEqual(st, 403)
            st, result = self.call("POST", "/api/aircraft/designer-save", body,
                                   origin="https://flightcost.app", ctype="text/plain")
            self.assertEqual(st, 415)
            st, result = self.call("POST", "/api/aircraft/designer-save", body,
                                   origin="https://flightcost.app")
            self.assertEqual(st, 400)
            self.assertTrue(result.get("need_workspace"))
            key = self.gdb.create("203.0.113.17")
            st, result = self.call("POST", "/api/aircraft/designer-save", body,
                                   cookie=key, origin="https://flightcost.app")
            self.assertEqual(st, 200, result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["seats"], 225)
            self.assertTrue(result["burn_inherited"])
            icao = result["icao"]
            self.assertTrue(icao.startswith("USER:B752-3D-"))
            ctx = self.ctx.for_request(key)
            self.assertEqual(ctx.store.value("aircraft", f"{icao}/seats_typical"), 225)
            self.assertEqual(ctx.store.value("aircraft", f"{icao}/seats_max"), 239)
            self.assertEqual(ctx.store.value("aircraft", f"{icao}/oew_t"), 58)
            self.assertEqual(ctx.store.value("aircraft", f"{icao}/mtow_t"), 110)
            self.assertEqual(ctx.store.value("aircraft", f"{icao}/mlw_t"), 90)
            self.assertIsNone(self.store.value("aircraft", f"{icao}/seats_typical"))
            doc = self.gdb.get_doc(ctx.ws, "aircraft", icao)
            self.assertEqual(doc["aircraft_designer"]["design"], design())
            self.assertEqual(doc["aircraft_designer"]["mzfw_t"], 85.)
            other = self.gdb.create("198.51.100.3")
            self.assertIsNone(self.ctx.for_request(other).store.value("aircraft", f"{icao}/mtow_t"))
            # Idempotent event delivery must not create a second type.
            st, again = self.call("POST", "/api/aircraft/designer-save", body,
                                  cookie=key, origin="https://flightcost.app")
            self.assertEqual(st, 200)
            self.assertTrue(again["replayed"])
            self.assertEqual(again["icao"], icao)
            tampered = json.loads(json.dumps(body)); tampered["design"]["aircraft"]["seats"] = 239
            st, bad = self.call("POST", "/api/aircraft/designer-save", tampered,
                                cookie=key, origin="https://flightcost.app")
            self.assertEqual(st, 400)

    def test_engine_mismatch_disables_burn(self):
        with patch.dict(os.environ, {"FCA_AIRCRAFT_DESIGNER": "1"}):
            key = self.gdb.create("198.51.100.55")
            d = design(icao="A20N", seats=194, engine="LEAP-1A", model="a320neo", layout="a320-194")
            st, saved = self.call("POST", "/api/aircraft/designer-save",
                                   {"requestId": "engine-mismatch1", "design": d},
                                   cookie=key, origin="https://flightcost.app")
            self.assertEqual(st, 200, saved)
            self.assertFalse(saved["engine_match"])
            self.assertFalse(saved["burn_inherited"])
            ctx = self.ctx.for_request(key)
            self.assertIsNone(ctx.store.value("aircraft", f"{saved['icao']}/burn_same_engine"))
            self.assertIsNotNone(self.store.value("aircraft", "A20N/mtow_t"))

if __name__ == "__main__":
    unittest.main()
