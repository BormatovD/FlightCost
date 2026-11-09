"""Открытые ряды цены топлива (план fuel-regions): расчёт k, местная цена, агент и приёмка."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from flightcostapp import agent_run as A
from flightcostapp import econ
from flightcostapp import fuel_series as FS

ROOT = Path(__file__).resolve().parents[1]

SERIES = {"series": {
    "us": {"name": "США", "mode": "ratio", "unit": "USD_per_gallon", "spot_window": 2, "smooth": 3,
           "max_age_months": 4, "regions": {"north_america": {}}, "home": "https://bts", "find": "релиз",
           "points": {"2026-07": {"value": 3.40}, "2026-08": {"value": 3.72}, "2026-09": {"value": 3.86}}},
    "ru": {"name": "Россия", "mode": "direct", "unit": "RUB_per_t", "currency": "RUB", "max_age_months": 3,
           "vat": {2026: 0.22}, "regions": {"russia_centre": {"markup": 0.285, "fee_t": 2210}},
           "home": "https://mt", "find": "заметка", "points": {"2026-09": {"value": 126263}}}}}


class FakeStore:
    """USGC по рабочим дням месяца и курс — как в главной базе."""

    def __init__(self, months: dict, fx: dict | None = None):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE facts (domain, key, valid_from, value, created_at)")
        for m, v in months.items():
            for day in range(1, 21):
                self.db.execute("INSERT INTO facts VALUES ('jet_fuel_price', 'spot/USGC', ?, ?, '1')",
                                (f"{m}-{day:02d}", v))
        self.fx = fx or {"RUB": 92.09, "USD": 1.12}

    def value(self, domain, key, as_of=None, default=None):
        return self.fx.get(key, default) if domain == "fx" else default


class Series(unittest.TestCase):

    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.path = d / "_series.yaml"
        self.path.write_text(yaml.safe_dump(SERIES, allow_unicode=True), "utf-8")
        self.p = mock.patch.object(econ, "FUEL_SERIES_PATH", self.path)
        self.p.start()
        econ._FUEL_REG_CACHE.pop("series", None)
        self.st = FakeStore({"2026-06": 3.042, "2026-07": 3.403, "2026-08": 3.724, "2026-09": 4.388})

    def tearDown(self):
        self.p.stop()
        econ._FUEL_REG_CACHE.pop("series", None)

    def test_ratio_uses_lagged_spot_and_median(self):
        r = econ.fuel_series("north_america", "2026-10-06", self.st)
        # 09: 3.86 / ((4.388+3.724)/2) = 0.952; 08: 1.044; 07: 1.055 → медиана 1.044
        self.assertEqual(r["points"], {"2026-09": 0.952, "2026-08": 1.044, "2026-07": 1.055})
        self.assertAlmostEqual(r["k"], 1.044, places=3)

    def test_stale_series_falls_back(self):
        self.assertIsNone(econ.fuel_series("north_america", "2027-03-01", self.st))
        self.assertIsNone(econ.fuel_series("europe", "2026-10-06", self.st))

    def test_direct_price_bypasses_spot(self):
        r = econ.fuel_series("russia_centre", "2026-10-06", self.st)
        want = (126263 / 1.22 * 1.285 + 2210) / 92.09 / 1000
        self.assertAlmostEqual(r["eur_kg"], want, places=6)
        self.assertEqual(r["month"], "2026-09")

    def test_repo_series_file_is_valid(self):
        doc = yaml.safe_load((ROOT / "data" / "fuel" / "_series.yaml").read_text("utf-8"))
        regs = yaml.safe_load((ROOT / "data" / "fuel" / "_regional.yaml").read_text("utf-8"))["regions"]
        for sid, ser in doc["series"].items():
            self.assertIn(ser["mode"], ("ratio", "direct"), sid)
            for reg in ser["regions"]:
                self.assertIn(reg, regs, f"{sid}: регион {reg} не заведён в _regional.yaml")
            for m, p in ser["points"].items():
                self.assertRegex(str(m), r"^\d{4}-\d{2}$")
                self.assertTrue(str(p["source"]).startswith("https://"), f"{sid} {m}: нет источника")


class Drafts(unittest.TestCase):

    def test_numbers_in_quotes(self):
        self.assertTrue(FS.number_in(126263, "до 126.263 рублей за тонну"))
        self.assertTrue(FS.number_in(27639.95, "в размере 27.639,95 рубля"))
        self.assertTrue(FS.number_in(3.86, "The cost per gallon of fuel in September 2026 ($3.86) was up"))
        self.assertFalse(FS.number_in(3.72, "The cost per gallon of fuel in September 2026 ($3.86)"))

    def test_due_months(self):
        dd = {"months": {"2026-09": {"damper_rub_t": 1}}}
        w = FS.due(SERIES, dd, today=__import__("datetime").date(2026, 12, 8))
        self.assertEqual(w["points"], [("us", "2026-10"), ("us", "2026-11"), ("ru", "2026-10"), ("ru", "2026-11")])
        self.assertEqual(w["damper"], ["2026-10", "2026-11"])

    def test_check_and_merge(self):
        st = FakeStore({"2026-09": 4.388, "2026-10": 4.338})
        blob = json.dumps({"points": [
            {"series": "us", "month": "2026-10", "value": 4.05, "quote": "in October 2026 ($4.05) was up",
             "where": "https://bts/x"},
            {"series": "ru", "month": "2026-10", "value": 131000, "quote": "составила 130.900 рублей",
             "where": "https://mt/x"},
            {"series": "ru", "month": "2026-11", "value": None},
            {"series": "nope", "month": "2026-10", "value": 1}],
            "damper": [{"month": "2026-10", "value": 61000.5, "quote": "в размере 61.000,5 рубля",
                        "where": "https://mt/x"}]}).encode()
        r = FS.check(blob, st, SERIES, {"months": {}})
        v = {(x["series"], x["month"]): x for x in r["rows"]}
        self.assertEqual(v[("us", "2026-10")]["verdict"], "clean")
        self.assertAlmostEqual(v[("us", "2026-10")]["k"], 4.05 / ((4.338 + 4.388) / 2))
        self.assertEqual(v[("ru", "2026-10")]["verdict"], "look")
        self.assertIn("числа нет в цитате", v[("ru", "2026-10")]["reasons"])
        self.assertEqual(v[("ru", "2026-11")]["verdict"], "skip")
        self.assertEqual(v[("nope", "2026-10")]["verdict"], "reject")
        self.assertEqual(v[("ru_damper", "2026-10")]["verdict"], "clean")

        d = Path(tempfile.mkdtemp())
        sp, dp = d / "s.yaml", d / "d.yaml"
        sp.write_text("# шапка\n" + yaml.safe_dump(SERIES, allow_unicode=True), "utf-8")
        dp.write_text("# шапка\n" + yaml.safe_dump({"months": {}}), "utf-8")
        take = [x for x in r["rows"] if x["verdict"] in ("clean", "look")]
        FS.merge(take, sp, dp)
        s2, d2 = yaml.safe_load(sp.read_text("utf-8")), yaml.safe_load(dp.read_text("utf-8"))
        self.assertEqual(s2["series"]["us"]["points"]["2026-10"], {"value": 4.05, "source": "https://bts/x"})
        self.assertEqual(list(s2["series"]["ru"]["points"]), ["2026-09", "2026-10"])
        self.assertEqual(d2["months"]["2026-10"]["damper_rub_t"], 61000.5)
        self.assertTrue(sp.read_text("utf-8").startswith("# шапка"))


class Agent(unittest.TestCase):

    def test_fuel_job_makes_draft(self):
        tmp = Path(tempfile.mkdtemp())
        out = {"points": [{"series": "us_p12a", "month": "2026-10", "value": 4.05, "quote": "($4.05)",
                           "where": "https://www.bts.gov/newsroom/x"}], "damper": [], "doubts": []}
        oc = tmp / "openclaw"
        oc.write_text(f"""#!{sys.executable}
import json, sys, pathlib
cwd = pathlib.Path(sys.argv[sys.argv.index('--cwd') + 1])
(cwd / 'out' / 'fuel.json').write_text({json.dumps(out)!r})
print(json.dumps({{"ok": True, "status": "ok", "final": "готово", "costUsd": 0.02}}))
""")
        oc.chmod(oc.stat().st_mode | stat.S_IEXEC)
        key = tmp / "key"
        key.write_text("sk-test")
        with mock.patch.dict(os.environ, {"FCA_ANTHROPIC_KEY_FILE": str(key)}):
            r = A.Runner(tmp / "agent", openclaw=str(oc), config=str(ROOT / "deploy" / "agent" / "openclaw.json5"),
                         spool=tmp / "spool")
            n = r.fuel(today=__import__("datetime").date(2026, 12, 8))
        self.assertEqual(n, 1)
        drafts = list((tmp / "agent" / "out").glob("fuel-*.json"))
        self.assertEqual(len(drafts), 1)
        self.assertEqual(oct(drafts[0].stat().st_mode & 0o777), "0o640")
        msgs = [json.loads(p.read_text())["text"] for p in (tmp / "spool").glob("*.json")]
        self.assertTrue(any("us_p12a 2026-10: 4.05" in t for t in msgs))
        from flightcostapp import bot as B
        self.assertTrue(B.stash_draft(drafts[0].name, b"{}", tmp / "drafts"))

    def test_task_lists_due_series(self):
        w = FS.due(SERIES, {}, today=__import__("datetime").date(2026, 11, 8))
        self.assertEqual(w["points"], [("us", "2026-10"), ("ru", "2026-10")])


if __name__ == "__main__":
    unittest.main()
