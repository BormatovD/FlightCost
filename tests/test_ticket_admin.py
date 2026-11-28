from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from flightcostapp.ticket_admin import edit_ticket_queue
from flightcostapp.ticket_controls import read_ticket_controls, select_tickets, ticket_controls


class TicketDashboardQueue(unittest.TestCase):
    def test_worker_and_dashboard_share_priorities_and_respect_backoff(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE targets(target TEXT PRIMARY KEY, metadata TEXT, priority INTEGER, "
                       "seq INTEGER, due INTEGER, status TEXT)")
            db.executemany("INSERT INTO targets VALUES (?, 'region', 0, 0, ?, ?)", (
                ("ABC-DEF", 0, None),
                ("ABC-GHI", 0, None),
                ("ABC-JKL", 0, None),
                ("ABC-MNO", 200, "http_429"),
                ("ABC-PQR", 0, "unsupported_route"),
            ))
            controls = (["ABC-MNO", "ABC-PQR", "ABC-JKL"], ["ABC-GHI"])
            self.assertEqual([row[0] for row in select_tickets(db, 3, 100, controls)],
                             ["ABC-JKL", "ABC-DEF"])
            self.assertEqual([row[0] for row in select_tickets(db, 3, 100, controls, include_future=True)],
                             ["ABC-JKL", "ABC-DEF", "ABC-MNO"])
            self.assertEqual([row[0] for row in select_tickets(db, 3, 200, controls)],
                             ["ABC-MNO", "ABC-JKL", "ABC-DEF"])

    def test_edits_persist_and_limit_starting_routes_to_preview(self):
        with TemporaryDirectory() as temp:
            snapshot = Path(temp) / "status.json"
            snapshot.write_text(json.dumps({"tickets": {"planned": [{"route": "ABC-DEF"}]}}))
            path = Path(temp) / "overrides.json"

            def edit(action, route="abc-def"):
                return edit_ticket_queue(path=path, snapshot=snapshot, body={"route": route, "action": action})

            self.assertTrue(edit("prioritize")["changed"])
            self.assertEqual(read_ticket_controls(path), (["ABC-DEF"], []))
            self.assertFalse(edit("prioritize")["changed"])
            self.assertTrue(edit("defer")["changed"])
            self.assertEqual(read_ticket_controls(path), ([], ["ABC-DEF"]))
            snapshot.write_text(json.dumps({"tickets": {"planned": []}}))
            self.assertTrue(edit("restore")["changed"])
            self.assertEqual(read_ticket_controls(path), ([], []))
            with self.assertRaises(ValueError):
                edit("prioritize", "ABC-PQR")
            path.write_bytes(b" " * 3000)
            self.assertEqual(ticket_controls(path), ([], []))
            with self.assertRaises(ValueError):
                edit("defer")
