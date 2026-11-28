import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flightcostapp.admin_app import AdminServer, ORIGIN
from flightcostapp.agent_run import Runner
from flightcostapp.airport_queue import add_airport, pending_airports
from flightcostapp.probe import probe_url


class AdminHTTP(unittest.TestCase):
    token = "test-token"
    owner = 1000001

    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        queue = self.queue = Path(temp)
        snapshot = queue / "status.json"
        snapshot.write_text('{"as_of":"2026-11-23T20:00:00Z"}', encoding="utf-8")
        self.server = AdminServer(("127.0.0.1", 0), token=self.token, owner=self.owner,
                                  snapshot=snapshot, queue=queue, ticket_control=queue / "ticket-overrides.json")
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def signed(self, user=None, seconds=0):
        fields = {"auth_date": str(int(time.time()) - seconds), "query_id": "TEST",
                  "user": json.dumps({"id": self.owner if user is None else user}),
                  "signature": "telegram-test-signature"}
        data = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", self.token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
        return urlencode(fields)

    def call(self, endpoint, data=None, signed=None, origin=ORIGIN):
        headers = {"Origin": origin}
        body = None
        if signed is not None:
            headers["Authorization"] = f"tma {signed}"
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        req = Request(probe_url(f"http://127.0.0.1:{self.server.server_port}/bot-admin/api/{endpoint}"),
                      data=body, headers=headers)
        try:
            stream = urlopen(req, timeout=3)
        except HTTPError as exc:
            stream = exc
        with stream:
            return stream.code, json.load(stream)

    def test_journalist_pause_is_owner_only_and_idempotent(self):
        self.server.editorial_control = self.queue
        auth = self.signed()
        pause = {"paused": True}
        self.assertEqual(self.call("journalist", pause, self.signed(user=8))[0], 403)
        self.assertEqual(self.call("journalist", pause, auth, origin="https://example.org")[0], 403)
        self.assertEqual(self.call("journalist", {"paused": "false"}, auth)[0], 400)
        self.assertFalse(self.call("status", signed=auth)[1]["journalist"]["paused"])
        for _ in range(2):
            self.assertEqual(self.call("journalist", pause, auth), (200, pause))
        self.assertTrue((self.queue / "paused").is_file())
        self.assertTrue(self.call("status", signed=auth)[1]["journalist"]["paused"])
        self.assertEqual(self.call("journalist", {"paused": False}, auth)[1], {"paused": False})
        self.assertFalse((self.queue / "paused").exists())

    def test_owner_only_fresh_signed_snapshot(self):
        self.assertEqual(self.call("status", signed=self.signed())[0], 200)
        for bad in (None, self.signed(user=2), self.signed(seconds=3700),
                    self.signed() + "&auth_date=1", self.signed().replace("TEST", "TAMPERED")):
            self.assertEqual(self.call("status", signed=bad)[0], 403)

    def test_airport_dedup_and_run_coalescing(self):
        auth = self.signed()
        data = {"icao": "rjaa", "city": "Токио Нарита"}
        self.assertEqual(self.call("airports", data, auth, origin="https://other.example")[0], 403)
        self.assertEqual(self.call("airports", {"icao": "../x"}, auth)[0], 400)
        self.assertEqual(self.call("airports", {**data, "url": "https://example.com"}, auth)[0], 400)
        self.assertEqual(self.call("airports", data, auth)[1]["already_queued"], False)
        self.assertEqual(self.call("airports", data, auth)[1]["already_queued"], True)
        self.assertEqual(pending_airports(self.queue)[0]["icao"], "RJAA")
        self.assertEqual(self.call("run", {}, auth)[0], 202)
        self.assertTrue((self.queue / ".run").is_file())
        self.assertTrue(self.call("run", {}, auth)[1]["already_queued"])

    def test_airport_edit_requires_owner_origin_and_returns_current_queue(self):
        auth = self.signed()
        endpoint = "airports/edit"
        data = {"icao": "egll", "action": "defer"}
        self.assertEqual(self.call(endpoint, data)[0], 403)
        self.assertEqual(self.call(endpoint, data, auth, origin="https://example.org")[0], 403)
        self.assertEqual(self.call(endpoint, {**data, "action": "unknown"}, auth)[0], 400)
        self.assertEqual(self.call(endpoint, {**data, "city": "London"}, auth)[0], 400)
        status, result = self.call(endpoint, data, auth)
        self.assertEqual(status, 200)
        self.assertTrue(result["changed"])
        self.assertEqual(result["deferred"], ["EGLL"])
        self.assertEqual(result["manual"], [])
        self.assertFalse(self.call(endpoint, data, auth)[1]["changed"])
        result = self.call(endpoint, {**data, "action": "restore"}, auth)[1]
        self.assertEqual(result["deferred"], [])
        self.assertTrue(result["changed"])
        result = self.call(endpoint, {**data, "action": "prioritize"}, auth)[1]
        self.assertEqual([row["icao"] for row in result["manual"]], ["EGLL"])
        result = self.call(endpoint, {**data, "action": "remove"}, auth)[1]
        self.assertEqual(result["manual"], [])

    def test_ticket_edit_requires_owner_and_writes_only_overrides(self):
        self.server.snapshot.write_text('{"tickets":{"planned":[{"route":"JFK-LHR"}]}}')
        auth = self.signed()
        endpoint = "tickets/edit"
        body = {"route": "JFK-LHR", "action": "prioritize"}
        self.assertEqual(self.call(endpoint, body)[0], 403)
        self.assertEqual(self.call(endpoint, body, auth, origin="https://example.org")[0], 403)
        self.assertEqual(self.call(endpoint, {**body, "route": "JFK-LGA"}, auth)[0], 400)
        self.assertEqual(self.call(endpoint, body, auth)[1]["prioritized"], ["JFK-LHR"])
        self.assertEqual(self.call(endpoint, {**body, "action": "defer"}, auth)[1]["deferred"], ["JFK-LHR"])
        self.assertEqual(self.call(endpoint, {**body, "action": "restore"}, auth)[1]["deferred"], [])
        self.assertEqual(json.loads(self.server.snapshot.read_text())["tickets"]["planned"], [{"route": "JFK-LHR"}])


class ManualAgent(unittest.TestCase):
    def test_manual_request_reopens_failed_airport_without_erasing_attempt_limit(self):
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        queue = home / "queue" / "airport-admin"
        queue.mkdir(parents=True)
        add_airport(queue, "UTTT", "Ташкент")
        runner = Runner(home=home, spool=home / "spool")
        runner.save_charges_state({"UTTT": {"status": "not_found", "tries": 2}})
        with (patch.object(runner, "say"), patch.object(runner, "budget_ok", return_value=False),
              patch.object(runner, "exec") as execute):
            self.assertIsNone(runner.charges_one())
            execute.assert_not_called()
            self.assertTrue((queue / "UTTT.json").exists())
        with (patch.object(runner, "say"), patch.object(runner, "budget_ok", return_value=True),
              patch.object(runner, "exec", return_value={"status": "ok"}) as execute):
            self.assertEqual(runner.charges_one(), 0)
            self.assertEqual(runner.charges_state()["UTTT"]["tries"], 1)
            self.assertEqual(runner.charges_one(), 0)
            self.assertEqual(runner.charges_state()["UTTT"]["status"], "not_found")
            self.assertFalse((queue / "UTTT.json").exists())
            self.assertIn("UTTT", execute.call_args.args[2])
