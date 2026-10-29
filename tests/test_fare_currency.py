"""Выгрузка цен в другой валюте под чужой подписью не записывается (сбор 14.09.2026: рубли как EUR)."""
import pathlib, sys, tempfile, unittest
from datetime import date, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from flightcostapp import market_fare as MF   # noqa: E402
from flightcostapp.store import Store         # noqa: E402

PAIRS = ["EDDF-LSZH", "EDDM-EDDH", "EFHK-ESSA", "EDDF-LEBL", "EGLL-LEMD", "LOWW-EDDF"]


def dump(scale: float, seen: date, start: int = 0):
    out = []
    for i, p in enumerate(PAIRS):
        for k in range(4):
            out.append({"pair": p, "band": "d31_60", "direct": True, "price": (80 + 5 * i + k) * scale,
                        "currency": "EUR", "dep_date": seen + timedelta(days=40 + start + k),
                        "observed_at": seen, "carrier": "XX"})
    return out


class FareCurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Store(pathlib.Path(self.tmp.name) / "t.db")
        self.first = MF.collect(self.st, dump(1.0, date(2026, 9, 17)))

    def tearDown(self):
        self.st.db.close(); self.tmp.cleanup()

    def test_first_dump_has_nothing_to_compare(self):
        self.assertEqual(self.first["added"], 24)
        self.assertNotIn("refused", self.first)

    def test_rubles_under_eur_refused(self):
        st = MF.collect(self.st, dump(95.0, date(2026, 9, 14), start=10))
        self.assertIn("refused", st)
        self.assertEqual(st["added"], 0)
        n = self.st.db.execute("SELECT COUNT(*) FROM observations WHERE note = '2026-09-14'").fetchone()[0]
        self.assertEqual(n, 0, "отвергнутая выгрузка не пишется")

    def test_normal_price_movement_passes(self):
        st = MF.collect(self.st, dump(1.6, date(2026, 10, 13), start=20))   # сезон, распродажа
        self.assertNotIn("refused", st)
        self.assertEqual(st["added"], 24)

    def test_reparse_same_dump_not_compared_with_itself(self):
        st = MF.collect(self.st, dump(1.0, date(2026, 9, 17)))
        self.assertNotIn("refused", st)
        self.assertEqual(st["duplicate"], 24)


if __name__ == "__main__":
    unittest.main()
