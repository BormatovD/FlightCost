import os
import stat
import tempfile
from pathlib import Path
from threading import Barrier, Thread
from unittest import TestCase
from unittest.mock import patch

from flightcostapp.agent_run import manual_charge_candidate, pick_charges
from flightcostapp.airport_queue import add_airport, consume_airport, edit_airport, queue_airports, request_identity


class AirportQueue(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_priority_retains_retry_identity_and_add_keeps_fifo(self):
        add_airport(self.directory, "KLAX", "Los Angeles")
        add_airport(self.directory, "KJFK", "New York")
        original = queue_airports(self.directory)[0][1]
        self.assertTrue(edit_airport(self.directory, "KJFK", "prioritize"))
        self.assertFalse(edit_airport(self.directory, "KJFK", "prioritize"))
        self.assertTrue(edit_airport(self.directory, "KATL", "prioritize"))
        add_airport(self.directory, "KBOS", "Boston")
        self.assertEqual([row["icao"] for row in queue_airports(self.directory)[0]],
                         ["KATL", "KJFK", "KLAX", "KBOS"])
        self.assertEqual(request_identity(original), request_identity(queue_airports(self.directory)[0][1]))
        self.assertEqual(queue_airports(self.directory)[0][1]["city"], "New York")

    def test_defer_and_restore_exclude_automatic_refresh_and_candidates(self):
        doc = {"airports": {"EDDF": {"url": "https://example.org/eddf"}},
               "regions": {"us": {"prefixes": ["K"], "min": 2,
                                  "candidates": [{"icao": "KJFK"}, {"icao": "KATL"}]}}}
        state = {"KLAX": {"status": "refresh", "url": "https://example.org/klax"}}
        have = {"KLAX"}
        self.assertEqual(pick_charges(doc, have, state)[0], "KLAX")
        self.assertTrue(edit_airport(self.directory, "KLAX", "defer"))
        self.assertFalse(edit_airport(self.directory, "KLAX", "remove"))
        self.assertFalse(edit_airport(self.directory, "KLAX", "defer"))
        self.assertTrue(edit_airport(self.directory, "KJFK", "defer"))
        manual, deferred = queue_airports(self.directory)
        self.assertEqual((manual, deferred), ([], ["KJFK", "KLAX"]))
        self.assertEqual(pick_charges(doc, have, state, excluded=set(deferred))[0], "KATL")
        self.assertTrue(edit_airport(self.directory, "KLAX", "restore"))
        self.assertEqual(pick_charges(doc, have, state, excluded=set(queue_airports(self.directory)[1]))[0], "KLAX")

    def test_consume_cannot_delete_readded_request(self):
        add_airport(self.directory, "KJFK", "New York")
        old = queue_airports(self.directory)[0][0]
        self.assertTrue(edit_airport(self.directory, "KJFK", "remove"))
        self.assertTrue(add_airport(self.directory, "KJFK", "New York"))
        current = queue_airports(self.directory)[0][0]
        consume_airport(self.directory, old)
        self.assertEqual(queue_airports(self.directory)[0], [current])
        consume_airport(self.directory, current)
        self.assertEqual(queue_airports(self.directory)[0], [])

    def test_queue_lock_has_shared_permissions_with_restrictive_umask(self):
        previous = os.umask(0o077)
        try:
            add_airport(self.directory, "KJFK", "")
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE((self.directory / ".lock").stat().st_mode), 0o660)

    def test_concurrent_adds_respect_capacity(self):
        ready = Barrier(3)
        results = []

        def add(code):
            ready.wait(timeout=3)
            try:
                add_airport(self.directory, code, "")
            except ValueError:
                results.append(False)
            else:
                results.append(True)

        with patch("flightcostapp.airport_queue.MAX_ITEMS", 1):
            threads = [Thread(target=add, args=(code,)) for code in ("KATL", "KJFK")]
            for thread in threads:
                thread.start()
            ready.wait(timeout=3)
            for thread in threads:
                thread.join(timeout=3)
            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(len(queue_airports(self.directory)[0]), 1)

    def test_manual_refresh_keeps_its_source_with_existing_tariff(self):
        doc = {"airports": {"KJFK": {"url": "https://example.org/old"}},
               "regions": {"us": {"prefixes": ["K"], "candidates": [{"icao": "KJFK", "city": "New York"}]}}}
        state = {"KJFK": {"status": "refresh", "url": "https://example.org/new"}}
        edit_airport(self.directory, "KJFK", "prioritize")
        row = queue_airports(self.directory)[0][0]
        picked, refresh_url = manual_charge_candidate(doc, {"KJFK"}, state, row)
        self.assertEqual(picked, ("KJFK", {"icao": "KJFK", "city": "New York", "url": refresh_url}, "us"))
        self.assertEqual(refresh_url, "https://example.org/new")
