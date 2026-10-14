"""Файлы выкладки согласованы между собой.

Ловит поломку, которая на сервере выглядит тишиной: юнит лежит в
репозитории, но bootstrap.sh его не ставит — таймер копий или забора
просто не существует, и никто об этом не узнаёт, пока не понадобится
копия или пропущенные сутки.
"""

from __future__ import annotations

import pathlib
import re
import unittest

DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy"


class Deploy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.boot = (DEPLOY / "bootstrap.sh").read_text(encoding="utf-8")

    def test_every_unit_is_installed(self):
        for unit in sorted(DEPLOY.glob("*.service")) + sorted(DEPLOY.glob("*.timer")):
            self.assertIn(unit.name, self.boot, f"{unit.name} есть, а bootstrap его не ставит")

    def test_every_timer_is_enabled(self):
        for timer in sorted(DEPLOY.glob("*.timer")):
            self.assertRegex(self.boot, rf"systemctl enable[^\n]*{re.escape(timer.name)}",
                             f"{timer.name} ставится, но не включается")

    def test_observer_never_writes_into_published_snapshot(self):
        """`fca publish` подменяет site/data/flightcost.db и вычищает наблюдения."""
        unit = (DEPLOY / "fca-observe.service").read_text(encoding="utf-8")
        exec_line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
        self.assertIn("--db /srv/fca/observe/", exec_line)
        self.assertNotIn("/srv/fca/site", re.sub(r"(?m)^#.*$", "", unit))

    def test_scripts_referenced_by_units_exist(self):
        for unit in DEPLOY.glob("*.service"):
            for m in re.finditer(r"/srv/fca/app/deploy/([\w.-]+)", unit.read_text(encoding="utf-8")):
                self.assertTrue((DEPLOY / m.group(1)).exists(), f"{unit.name}: нет {m.group(1)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
