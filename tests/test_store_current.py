"""`Store.current` одним запросом — то же, что `get()` по каждому ключу.

Сборка сети зовёт `current` тысячи раз (тарифы, наблюдения), и раньше он
делал запрос на каждый ключ. Новый — один запрос и кэш до записи (решение
206). Тест сверяет его со старым определением на версиях с перекрытием,
закрытыми интервалами и префиксами, и проверяет, что запись сбрасывает кэш.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp.store import Fact, Store  # noqa: E402


def F(key, value, vf, vt=None):
    return Fact(domain="airport_charge", key=key, valid_from=vf, valid_to=vt, value=value,
                source_id="t", extracted_by="t")


class Current(unittest.TestCase):

    def setUp(self):
        self.s = Store(pathlib.Path(tempfile.mkdtemp()) / "c.db")
        self.s.commit_facts([
            F("EDDF/land", 1.0, "2026-01-01", "2026-06-01"),
            F("EDDF/land", 2.0, "2026-06-01"),
            F("EDDF/pax", 10.0, "2026-01-01"),
            F("EDDF0/x", 5.0, "2026-01-01"),          # за границей префикса «EDDF/»
            F("LI/muni", 6.5, "2026-01-01"),
            F("LEBL/old", 3.0, "2025-01-01", "2025-12-31"),
        ])

    def old(self, as_of, prefixes=None):
        keys = [r["key"] for r in self.s.db.execute(
            "SELECT DISTINCT key FROM facts WHERE domain='airport_charge'")]
        out = {}
        for k in keys:
            if prefixes and not any(k.startswith(p) for p in prefixes):
                continue
            row = self.s.get("airport_charge", k, as_of)
            if row is not None:
                out[k] = row["value"]
        return out

    def test_same_as_get_per_key(self):
        for d in ("2025-06-01", "2026-03-01", "2026-07-01"):
            for pre in (None, ["EDDF/"], ["EDDF/", "LI/"]):
                got = {k: r["value"] for k, r in self.s.current("airport_charge", d, pre).items()}
                self.assertEqual(got, self.old(d, pre), (d, pre))

    def test_write_resets_cache_and_copy_is_returned(self):
        a = self.s.current("airport_charge", "2026-07-01")
        a["junk"] = None                                   # вызывающий дополняет копию
        self.assertNotIn("junk", self.s.current("airport_charge", "2026-07-01"))
        self.s.commit_facts([F("EDDF/new", 7.0, "2026-01-01")])
        self.assertIn("EDDF/new", self.s.current("airport_charge", "2026-07-01"))


if __name__ == "__main__":
    unittest.main()
