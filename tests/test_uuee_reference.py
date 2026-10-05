"""Эталон Шереметьево: разбор UUEE-2025 воспроизводит счёт, сведённый руками.

Второй эталон после Франкфурта, и первый вне евро и вне ЕС. Проверяет не
только числа, но и три вещи, которых у Франкфурта не было:

  * два прейскуранта на один аэропорт по признаку ЭКСПЛУАТАНТА
    (условие `operator`), в двух валютах;
  * аэровокзальный сбор с прибывающих И убывающих — оборот платит за
    пассажира дважды (`per_pax_per_movement`);
  * стоянка долей от посадочного ЗА ЕДИНИЦУ ВРЕМЕНИ: у российских
    пользователей за час сверх трёх, у иностранных за сутки после трёх
    часов (`pct_of` × база времени).

Счёт сведён по прейскурантам № 01/25 и 01/25-И АО «МАШ» от 29.01.2025
(в силе с 01.03.2025) на эталонном обороте: A320, 78 т МВМ, 148
пассажиров, тот же оборот, что у Франкфурта.

Курс здесь 1:1 намеренно: сравнивается сумма в валюте прейскуранта, а не
её пересчёт — курс проверяется отдельно и не должен маскировать ошибку
в правиле.

Запуск: python3 tests/test_uuee_reference.py
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.charges import Rule, evaluate  # noqa: E402
from flightcostapp.parsers import airport_charges  # noqa: E402

DOC = ROOT / "data" / "charges" / "UUEE-2025.json"
MTOW, PAX = 78.0, 148.0


def rules():
    facts = airport_charges.parse(DOC.read_bytes(), {
        "source_id": "test", "sha": "test", "extracted_by": "test",
        "as_of": "2026-09-16", "corpus": {}, "icao_seen": []})
    # `from_fact` читает строку хранилища; факт парсера — тот же набор
    # полей, только объектом. Через dataclasses.asdict, чтобы не заводить
    # второе прочтение правила из факта.
    from dataclasses import asdict
    return [Rule.from_fact(asdict(f)) for f in facts if f.domain == "airport_charge"]


def ctx(operator, flight, terminal, park_h):
    # Один оборот: одна посадка, один вылет, два движения.
    return {"mtow_t": MTOW, "pax": PAX, "cargo_kg": 0.0,
            "movements": 2, "landings": 1, "turnarounds": 1, "departures": 1,
            "flight": flight, "pax_type": "local", "dest": "intercontinental",
            "month": 7, "night": False, "noise_cat": None, "cargo": False,
            "stand": "apron", "stand_group": None, "ac_group": None,
            "ac_class": None, "pax_per_mtow": PAX / MTOW, "park_h": park_h,
            "park_h_over_free": park_h > 0, "return_technical": False,
            "operator": operator, "terminal": terminal}


def total(operator, flight, terminal, park_h):
    out = evaluate(rules(), ctx(operator, flight, terminal, park_h),
                   fx=lambda cur: 1.0)
    return {k: round(v, 2) for k, v in out.items() if not k.startswith("_")}


class Sheremetyevo(unittest.TestCase):

    def test_russian_user_domestic_terminal_b_two_hours(self):
        got = total("national", "domestic", "B", 2.0)
        # п.1.1 768,50 = 394,70 + 373,80; п.2 38,36; п.3.1.1 296,76 × 148 × 2
        self.assertAlmostEqual(got["landing"], 394.70 * MTOW, 2)          # 30 786,60
        self.assertAlmostEqual(got["landing_invest"], 373.80 * MTOW, 2)   # 29 156,40
        self.assertAlmostEqual(got["security"], 38.36 * MTOW, 2)          #  2 992,08
        self.assertAlmostEqual(got["passenger"], 296.76 * PAX * 2, 2)     # 87 840,96
        self.assertNotIn("parking", got)                                   # до трёх часов
        self.assertAlmostEqual(sum(got.values()), 150_776.04, 2)

    def test_russian_user_parking_is_per_hour_above_three(self):
        got = total("national", "domestic", "B", 5.0)
        # 5% от 30 786,60 за каждый час сверх трёх: два часа
        self.assertAlmostEqual(got["parking"], 0.05 * 394.70 * MTOW * 2, 2)  # 3 078,66
        self.assertAlmostEqual(sum(got.values()), 153_854.70, 2)

    def test_russian_user_international_terminal_c(self):
        got = total("national", "INTL", "C", 2.0)
        self.assertAlmostEqual(got["passenger"], 810.16 * PAX * 2, 2)     # 239 807,36
        # тот же документ читается и для рейса в Шенген: для России это
        # международный, а не «EEA»
        self.assertEqual(total("national", "EEA", "C", 2.0)["passenger"], got["passenger"])

    def test_foreign_user_terminal_c_two_hours_usd(self):
        got = total("foreign", "INTL", "C", 2.0)
        self.assertAlmostEqual(got["landing"], 11.01 * MTOW, 2)           #   858,78
        self.assertAlmostEqual(got["landing_invest"], 5.95 * MTOW, 2)     #   464,10
        self.assertAlmostEqual(got["security"], 1.40 * MTOW, 2)           #   109,20
        self.assertAlmostEqual(got["passenger"], 20.32 * PAX * 2, 2)      # 6 014,72
        self.assertNotIn("parking", got)
        self.assertAlmostEqual(sum(got.values()), 7_446.80, 2)

    def test_foreign_user_parking_is_per_day_after_three_hours(self):
        got = total("foreign", "INTL", "C", 30.0)
        # 5% от 858,78 за каждые начатые сутки: 30 ч — двое суток
        self.assertAlmostEqual(got["parking"], 0.05 * 11.01 * MTOW * 2, 2)  # 85,88
        self.assertAlmostEqual(sum(got.values()), 7_532.68, 2)

    def test_price_lists_do_not_bleed_into_each_other(self):
        # Российский пользователь не платит долларовых статей и наоборот:
        # обе суммы состоят только из своей валюты.
        rs = rules()
        for op in ("national", "foreign"):
            active = [r for r in rs if r.matches(ctx(op, "INTL", "C", 5.0))]
            self.assertEqual({r.currency for r in active},
                             {"RUB" if op == "national" else "USD"})

    def test_terminal_unset_is_a_reported_gap_not_zero(self):
        report = {}
        evaluate(rules(), ctx("national", "domestic", None, 2.0),
                 fx=lambda cur: 1.0, report=report)
        self.assertIn("terminal", report.get("missing_input", []),
                      "терминал не задан — вопрос к пользователю, а не ноль")


if __name__ == "__main__":
    unittest.main(verbosity=2)
