"""Budgeted IATI pilot: no key, server or HTTP call is made in these tests."""
from datetime import datetime, timedelta, timezone
import io
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import iati_fetch as f
import usage_budget as budget

HERE = Path(__file__).resolve().parent
PAYLOAD = json.loads((HERE / 'fixtures/iati_synthetic_page.json').read_text())


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, n=-1):
        return self.raw if n is None or n < 0 else self.raw[:n]


class LiveBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.ledger = self.dir / 'quota.sqlite'
        self.now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
        self.env = patch.dict(os.environ, {'FCA_IATI_API_KEY': 'NOT-A-REAL-KEY'}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def args(self, *parts):
        return ['--budget-db', str(self.ledger), *parts]

    def test_no_quota_db_disallows_a_live_call_before_network(self):
        calls = []
        with self.assertRaises(SystemExit):
            f.run(['--probe', '--countries', 'KE'], opener=lambda *a: calls.append(1))
        self.assertEqual(calls, [])

    def test_same_ledger_blocks_extra_request_across_runs(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse(json.dumps(PAYLOAD).encode())
        with patch('builtins.print'):
            f.run(self.args('--probe', '--countries', 'KE', '--minute-limit', '1'),
                  opener=opener, clock=lambda: self.now)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            f.run(self.args('--probe', '--countries', 'MA', '--minute-limit', '1'),
                  opener=opener, clock=lambda: self.now)
        self.assertEqual(len(calls), 1)
        with closing(budget.open_private(self.ledger)) as db:
            status = budget.snapshot(db, now=self.now)
        self.assertEqual(status['minute_used'], 1)
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o600)

    def test_failure_still_consumes_budget_and_secret_never_logged(self):
        def failing(req, timeout):
            raise HTTPError(req.full_url, 429, 'Too Many Requests',
                            {'Retry-After': '180'}, io.BytesIO(b'Rate limited'))
        with self.assertRaises(f.IatiRequestError) as caught:
            f.run(self.args('--probe', '--countries', 'KE'),
                  opener=failing, clock=lambda: self.now)
        self.assertNotIn('NOT-A-REAL-KEY', str(caught.exception))
        with closing(budget.open_private(self.ledger)) as db:
            snap = budget.snapshot(db, now=self.now+timedelta(seconds=61))
            row = db.execute('SELECT state,http_status FROM request_attempt').fetchone()
        self.assertEqual(row, ('rate_limited', 429))
        self.assertFalse(snap['allowed'])
        self.assertEqual(snap['blocked_until'],
                         (self.now+timedelta(seconds=180)).isoformat(timespec='microseconds'))

    def test_network_error_is_recorded_and_second_request_not_attempted(self):
        calls = []
        def failing(req, timeout):
            calls.append(1)
            raise OSError('synthetic network failure')
        for _ in range(2):
            with self.assertRaises((OSError, RuntimeError)):
                f.run(self.args('--probe', '--countries', 'KE', '--minute-limit', '1'),
                      opener=failing, clock=lambda: self.now)
        self.assertEqual(len(calls), 1)
        with closing(budget.open_private(self.ledger)) as db:
            self.assertEqual(db.execute('SELECT state FROM request_attempt').fetchone()[0], 'failed')

    def test_no_unstable_multi_page_snapshot(self):
        calls = []
        with self.assertRaises(SystemExit):
            f.run(self.args('--countries', 'KE', '--max-pages', '2'),
                  opener=lambda *a: calls.append(1))
        self.assertEqual(calls, [])

    def test_probe_does_not_create_data_directory(self):
        output = self.dir / 'no-data'
        def opener(req, timeout):
            return FakeResponse(json.dumps(PAYLOAD).encode())
        with patch('builtins.print'):
            f.run(self.args('--probe', '--countries', 'KE', '--out', str(output)),
                  opener=opener)
        self.assertFalse(output.exists())
        self.assertTrue(self.ledger.is_file())

    def test_reject_insecure_existing_budget_file(self):
        self.ledger.write_text('insecure')
        self.ledger.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'private'):
            budget.open_private(self.ledger)

    def test_http_date_retry_after_parsed(self):
        value = 'Thu, 12 Nov 2026 12:05:00 GMT'
        self.assertEqual(f.retry_after_seconds(value, now=self.now), 300)
        self.assertIsNone(f.retry_after_seconds('not-a-date', now=self.now))


if __name__ == '__main__':
    unittest.main()
