"""Парсер реестра сообщества: редакции, старшинство первоисточника, форма правил.

Работает на фикстуре из трёх аэропортов, выкроенной из настоящей
выгрузки: Шереметьево (есть ручной разбор → только сверка),
Владивосток (заводится), неизвестный код (пропускается и считается).
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import tempfile
import unittest
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.parsers import tkp_charges  # noqa: E402

HDR = ["АП", "Услуга", "Орг-ция", "Ставка", "Ед.изм.", "Терминал", "Код Т/С", "В/С",
       "Дата с", "Дата по", "Марка топлива", "Код обработки", "Приб./убыв.", "Вид груза",
       "Наименование Орг", "Операции", "Индекс", "Примечание"]


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Перечень услуг"
    ws.append(HDR)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def row(ap, svc, rate, unit, d_from, d_to, org, idx="0", note="", terminal=" "):
    return [ap, svc, "0001", rate, unit, terminal, " ", "   ",
            dt.datetime.fromisoformat(d_from), dt.datetime.fromisoformat(d_to) if d_to else None,
            " ", " ", " ", "", org, " ", idx, note]


class Tkp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        (base / "codes.yaml").write_text(
            "codes:\n  ШРМ: {icao: UUEE, iata: SVO}\n  ВВО: {icao: UHWW, iata: VVO}\n",
            encoding="utf-8")
        (base / "charges").mkdir()
        (base / "charges" / "UUEE-2025.json").write_text("{}", encoding="utf-8")
        (base / "raw").mkdir()
        self.ctx = {"source_id": "t", "sha": "x", "extracted_by": "t",
                    "codes_path": str(base / "codes.yaml"),
                    "charges_path": str(base / "charges"),
                    "raw_dir": str(base / "raw")}
        self.blob = _xlsx([
            row("ШРМ", "ВЗЛЕТ-ПОСАДКА", "768.50", "РУБ-Т", "2025-01-01", "2027-12-31", "АО МАШ", "2",
                "В Т.Ч.ИНВЕСТИЦИОННАЯ СОСТАВЛЯЮЩАЯ 373.80\\РУБ-Т"),
            row("ШРМ", "ВЗЛЕТ-ПОСАДКА", "845.36", "РУБ-Т", "2026-01-01", "2028-12-30", "АО МАШ", "3",
                "В Т.Ч.ИНВЕСТИЦИОННАЯ СОСТАВЛЯЮЩАЯ 411.18\\РУБ-Т"),
            row("ВВО", "ВЗЛЕТ-ПОСАДКА", "514.00", "РУБ-Т", "2024-01-01", "2026-12-31", "АО МАВ"),
            row("ВВО", "ВЗЛЕТ-ПОСАДКА", "600.00", "РУБ-Т", "2026-07-01", "2029-06-30", "АО МАВ", "1"),
            row("ВВО", "СТОЯНКА", "5.00", "ПРОЦ-ЧАС", "2024-01-01", None, "АО МАВ"),
            row("ВВО", "АЭРОВОКЗАЛ(М)", "500.00", "РУБ-ПАСС", "2024-01-01", None, "АО МАВ", terminal="A"),
            row("ВВО", "АНО АД", "252.00", "РУБ-Т", "2026-04-08", "2029-04-06", "ОРВД"),
            row("XXX", "ВЗЛЕТ-ПОСАДКА", "1.00", "РУБ-Т", "2024-01-01", None, "неизвестно"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_airport_is_checked_not_entered(self):
        facts = tkp_charges.parse(self.blob, self.ctx)
        self.assertFalse(any(f.key.startswith("UUEE/") for f in facts))
        self.assertTrue(any("UUEE ВЗЛЕТ-ПОСАДКА: реестр 845.36" in c for c in self.ctx["checks"]))

    def test_later_edition_closes_the_earlier(self):
        facts = tkp_charges.parse(self.blob, self.ctx)
        landing = sorted((f for f in facts if f.key.startswith("UHWW/landing/")),
                         key=lambda f: f.valid_from)
        self.assertEqual([(f.value, f.valid_from, f.valid_to) for f in landing],
                         [(514.0, "2024-01-01", "2026-06-30"), (600.0, "2026-07-01", "2029-06-30")])

    def test_rule_shapes(self):
        facts = {f.key.split("/")[1] if f.domain == "airport_charge" else f.domain: f
                 for f in tkp_charges.parse(self.blob, self.ctx)}
        park = json.loads(facts["parking"].value_text)
        self.assertEqual((park["pct_of"], park["base"], park["threshold"]), ("landing", "per_hour_above", 3.0))
        self.assertEqual(facts["parking"].value, 0.05)
        pax = json.loads(facts["passenger"].value_text)
        self.assertEqual(pax["when"], {"operator": "national", "flight": ["EEA", "INTL"], "terminal": "A"})
        self.assertEqual(pax["base"], "per_pax_per_movement")
        self.assertEqual((facts["terminal_rate"].key, facts["terminal_rate"].value), ("UHWW/national", 252.0))

    def test_unknown_code_is_counted_not_silent(self):
        tkp_charges.parse(self.blob, self.ctx)
        self.assertTrue(any("без кода сообщества→ИКАО: 1" in s for s in self.ctx["summary"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
