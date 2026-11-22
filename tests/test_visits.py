"""Счётчик посещений: уникальные по суткам, роботы не считаются, адресов на диске нет."""
import pathlib, sqlite3, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from flightcostapp.visits import Visits, ALL   # noqa: E402
from flightcostapp.probe import is_probe, probe_url  # noqa: E402

UA = "Mozilla/5.0 (Macintosh) Safari/605.1"


class ProbeTest(unittest.TestCase):
    def test_marker_preserves_original_query_and_fragment(self):
        url = "/ru/calc?origin=A%2FB&fare=&probe=old#network=x"
        marked = "/ru/calc?origin=A%2FB&fare=&probe=dev#network=x"
        self.assertEqual(probe_url(url), marked)
        self.assertEqual(probe_url(marked), marked)
        self.assertEqual(probe_url("/api/network"), "/api/network?probe=dev")

    def test_only_dev_is_a_test_marker(self):
        self.assertTrue(is_probe("x=1&probe=other&probe=dev"))
        self.assertFalse(is_probe("probe=other&name=probe%3Ddev"))


class VisitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.p = pathlib.Path(self.tmp.name) / "stats.db"
        self.v = Visits(self.p)

    def tearDown(self):
        self.v.db.close(); self.tmp.cleanup()

    def row(self, day, page):
        return self.v.db.execute("SELECT views, uniques FROM daily WHERE day=? AND page=?", (day, page)).fetchone()

    def test_unique_per_day(self):
        for _ in range(3): self.v.hit("/", "1.2.3.4", UA, day="2026-10-22")
        self.v.hit("/map", "1.2.3.4", UA, day="2026-10-22")
        self.v.hit("/", "5.6.7.8", UA, day="2026-10-22")
        self.assertEqual(self.row("2026-10-22", "/"), (4, 2))
        self.assertEqual(self.row("2026-10-22", ALL), (5, 2))
        self.v.hit("/", "1.2.3.4", UA, day="2026-10-23")      # новые сутки — снова уникальный
        self.assertEqual(self.row("2026-10-23", ALL), (1, 1))

    def test_bots_skipped(self):
        self.assertFalse(self.v.hit("/", "1.2.3.4", "Googlebot/2.1", day="2026-10-22"))
        self.assertFalse(self.v.hit("/", "1.2.3.4", "curl/8.0", day="2026-10-22"))
        self.assertFalse(self.v.hit("/", "1.2.3.4", "", day="2026-10-22"))
        self.assertIsNone(self.row("2026-10-22", "/"))

    def test_no_addresses_on_disk_and_old_hashes_wiped(self):
        self.v.hit("/", "203.0.113.77", UA, day="2026-10-22")
        self.v.hit("/", "198.51.100.9", UA, day="2026-10-23")
        raw = self.p.read_bytes()
        for s in (b"203.0.113.77", b"198.51.100.9", b"Safari"):
            self.assertNotIn(s, raw)
        days = {r[0] for r in self.v.db.execute("SELECT day FROM seen")} | {r[0] for r in self.v.db.execute("SELECT day FROM salt")}
        self.assertEqual(days, {"2026-10-23"})             # прошлые сутки стёрты

    def test_restart_keeps_uniques(self):
        self.v.hit("/", "1.2.3.4", UA, day="2026-10-22"); self.v.db.close()
        self.v = Visits(self.p); self.v.hit("/", "1.2.3.4", UA, day="2026-10-22")
        self.assertEqual(self.row("2026-10-22", "/"), (2, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
