"""Сводка калькулятора по обычным и ротированным журналам Caddy."""

import contextlib
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.calculator_stats import log_paths, print_report, read_report  # noqa: E402


SCRIPT = ROOT / "tools" / "calculator_stats.py"
START = datetime(2026, 11, 15, 14, 9, 26, 123456, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def entry(offset, uri, seconds, status=200, method="GET"):
    return json.dumps({
        "ts": START.timestamp() + offset,
        "request": {"method": method, "uri": uri, "remote_ip": "192.0.2.0"},
        "duration": seconds,
        "status": status,
    })


class CalculatorStatsTest(unittest.TestCase):
    def test_report_reads_caddy_logs_and_classifies_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp)
            rotated = logs / "fca-2026-11-18T00-00-00-size.log"
            rotated_body = "\n".join((
                entry(-0.01, "/api/route", 10),
                entry(0, "/api/route?probe=other&query=private", 3, 399),
                entry(1, "/api/route?probe=develop", 3.01, 404),
                entry(2, "/api/network?probe=dev", 1.2, 202, "POST"),
                "{broken line",
                "[]",
                "",
            ))
            rotated.write_text(rotated_body, encoding="utf-8")
            gzip_rotation = rotated.with_suffix(".log.gz")
            with gzip.open(gzip_rotation, "wt", encoding="utf-8") as compressed:
                compressed.write(rotated_body)
            (logs / "fca-2026-11-19T00-00-00.log").write_text(
                entry(3, "/api/network?job=private&probe=dev", 0.1, 200), encoding="utf-8",
            )
            (logs / "fca.log").write_text("\n".join((
                entry(4, "/api/route?x=probe%3Ddev", 0.25),
                entry(5, "/api/route?%70robe=d%65v", 1.5),
                entry(6, "/api/netcompare?probe=dev", 5, 503, "POST"),
                entry(7, "/api/network-hints?probe=dev", 100),
                entry(8, "/api/solve", None),
                entry(9, "/api/compare", 0, 429),
                entry((END - START).total_seconds(), "/api/route", 10),
            )), encoding="utf-8")
            (logs / "other.log").write_text(entry(10, "/api/route", 100), encoding="utf-8")

            paths = log_paths(logs)
            self.assertIn(gzip_rotation, paths)
            self.assertNotIn(rotated, paths)
            report = read_report(paths, START, END)

        self.assertEqual(report.skipped, 3)
        self.assertLess(report.first_timestamp, START.timestamp())
        self.assertEqual(report.endpoints["/api/route", False].durations, [3, 3.01, 0.25])
        self.assertEqual(report.endpoints["/api/route", False].errors, 1)
        self.assertEqual(report.endpoints["/api/route", True].durations, [1.5])
        self.assertEqual(sorted(report.endpoints["/api/network", True].durations), [0.1, 1.2])
        self.assertEqual(report.endpoints["/api/netcompare", True].errors, 1)
        self.assertEqual(report.endpoints["/api/compare", False].errors, 1)
        self.assertFalse(report.endpoints["/api/solve", False].durations)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_report(report, START, END)
        summary = output.getvalue()
        self.assertIn("[2026-11-15T14:09:26.123456Z, 2026-11-22T14:09:26.123456Z)", summary)
        self.assertRegex(summary, r"/api/route\s+без метки\s+3\s+3\.000\s+3\.010\s+1\s+1")
        self.assertRegex(summary, r"/api/solve\s+probe=dev\s+0\s+—\s+—\s+0\s+0")
        self.assertNotIn("private", summary)
        self.assertNotIn("192.0.2.0", summary)

    def test_cli_runs_from_other_directory_and_reports_log_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, "-I", str(SCRIPT), "--log-dir", tmp, "--days", "2"]
            no_logs = subprocess.run(command, cwd=tmp, capture_output=True, text=True)
            self.assertEqual(no_logs.returncode, 1)
            self.assertIn("отсутствуют", no_logs.stderr)

            current = Path(tmp) / "fca.log"
            offset = (datetime.now(timezone.utc) - timedelta(hours=1) - START).total_seconds()
            current.write_text(entry(offset, "/api/route?probe=dev", 0.5), encoding="utf-8")
            valid = subprocess.run(command, cwd=tmp, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn("Период UTC", valid.stdout)
            self.assertIn("Начало периода может быть не покрыто", valid.stdout)
            self.assertRegex(valid.stdout, r"/api/route\s+probe=dev\s+1\s+0\.500\s+0\.500\s+0\s+0")
            self.assertEqual(valid.stderr, "")

            corrupt = Path(tmp) / "fca-2026-11-17T00-00-00.log.gz"
            corrupt.write_bytes(b"invalid gzip")
            unreadable = subprocess.run(command, cwd=tmp, capture_output=True, text=True)
            self.assertEqual(unreadable.returncode, 1)
            self.assertIn(f"Не удалось прочитать {corrupt}", unreadable.stderr)
            self.assertEqual(unreadable.stdout, "")


if __name__ == "__main__":
    unittest.main()
