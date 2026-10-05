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

MTOW, PAX = 78.0, 148.0


def rules(icao="UUEE-2025"):
    doc = ROOT / "data" / "charges" / f"{icao}.json"
    facts = airport_charges.parse(doc.read_bytes(), {
        "source_id": "test", "sha": "test", "extracted_by": "test",
        "as_of": "2026-09-16", "corpus": {}, "icao_seen": []})
    # `from_fact` читает строку хранилища; факт парсера — тот же набор
    # полей, только объектом. Через dataclasses.asdict, чтобы не заводить
    # второе прочтение правила из факта.
    from dataclasses import asdict
    return [Rule.from_fact(asdict(f)) for f in facts if f.domain == "airport_charge"]


def ctx(operator, flight, terminal, park_h, other="EDDF"):
    # Один оборот: одна посадка, один вылет, два движения.
    return {"mtow_t": MTOW, "pax": PAX, "cargo_kg": 0.0,
            "movements": 2, "landings": 1, "turnarounds": 1, "departures": 1,
            "flight": flight, "pax_type": "local", "dest": "intercontinental",
            "month": 7, "night": False, "noise_cat": None, "cargo": False,
            "stand": "apron", "stand_group": None, "ac_group": None,
            "ac_class": None, "pax_per_mtow": PAX / MTOW, "park_h": park_h,
            "park_h_over_free": park_h > 0, "return_technical": False,
            "operator": operator, "terminal": terminal, "other": other}


def total(operator, flight, terminal, park_h, icao="UUEE-2025", other="EDDF"):
    out = evaluate(rules(icao), ctx(operator, flight, terminal, park_h, other),
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


class Domodedovo(unittest.TestCase):
    """UUDD-2025: те же правила прочтения, другие числа и другая база
    безопасности у иностранных — за убывающего пассажира, не за тонну."""

    def test_russian_user_domestic_two_hours(self):
        got = total("national", "domestic", None, 2.0, "UUDD-2025")
        self.assertAlmostEqual(got["landing"], 560.00 * MTOW, 2)        # 43 680
        self.assertAlmostEqual(got["security"], 440.00 * MTOW, 2)       # 34 320
        self.assertAlmostEqual(got["passenger"], 335.00 * PAX * 2, 2)   # 99 160
        self.assertNotIn("parking", got)
        self.assertAlmostEqual(sum(got.values()), 177_160.00, 2)

    def test_russian_user_parking_five_hours(self):
        got = total("national", "domestic", None, 5.0, "UUDD-2025")
        self.assertAlmostEqual(got["parking"], 0.05 * 560.00 * MTOW * 2, 2)  # 4 368
        self.assertAlmostEqual(sum(got.values()), 181_528.00, 2)

    def test_foreign_user_security_is_per_departing_pax(self):
        got = total("foreign", "INTL", None, 2.0, "UUDD-2025")
        self.assertAlmostEqual(got["landing"], 13.80 * MTOW, 2)          # 1 076,40
        self.assertAlmostEqual(got["passenger"], 22.50 * PAX * 2, 2)     # 6 660,00
        self.assertAlmostEqual(got["security"], 10.10 * PAX, 2)          # 1 494,80
        self.assertAlmostEqual(sum(got.values()), 9_231.20, 2)

    def test_foreign_user_parking_ten_percent_per_day(self):
        got = total("foreign", "INTL", None, 30.0, "UUDD-2025")
        self.assertAlmostEqual(got["parking"], 0.10 * 13.80 * MTOW * 2, 2)   # 215,28
        self.assertAlmostEqual(sum(got.values()), 9_446.48, 2)

    def test_terminal_is_not_a_condition_here(self):
        # Одна ставка на все терминалы: без `terminal` пропуска нет.
        report = {}
        evaluate(rules("UUDD-2025"), ctx("national", "domestic", None, 2.0),
                 fx=lambda cur: 1.0, report=report)
        self.assertNotIn("terminal", report.get("missing_input", []))


class Pulkovo(unittest.TestCase):
    """ULLI-2026: четыре прейскуранта. Внутренние линии делятся по
    направлению: на Москву — одни ставки, на всё остальное — другие
    (условие other с отрицанием)."""

    def test_russian_user_international_two_hours(self):
        got = total("national", "INTL", None, 2.0, "ULLI-2026")
        self.assertAlmostEqual(got["landing"], 686.50 * MTOW, 2)        # 53 547,00
        self.assertAlmostEqual(got["security"], 656.00 * MTOW, 2)       # 51 168,00
        self.assertAlmostEqual(got["passenger"], 335.90 * PAX * 2, 2)   # 99 426,40
        self.assertNotIn("parking", got)
        self.assertAlmostEqual(sum(got.values()), 204_141.40, 2)

    def test_russian_user_parking_five_hours(self):
        got = total("national", "INTL", None, 5.0, "ULLI-2026")
        self.assertAlmostEqual(got["parking"], 0.05 * 686.50 * MTOW * 2, 2)  # 5 354,70
        self.assertAlmostEqual(sum(got.values()), 209_496.10, 2)

    def test_domestic_to_moscow_uses_the_moscow_list(self):
        got = total("national", "domestic", None, 2.0, "ULLI-2026", other="UUEE")
        self.assertAlmostEqual(got["landing"], 686.50 * MTOW, 2)
        self.assertAlmostEqual(got["passenger"], 255.30 * PAX * 2, 2)   # 75 568,80
        self.assertAlmostEqual(got["security"], 656.00 * MTOW, 2)
        self.assertAlmostEqual(sum(got.values()), 180_283.80, 2)

    def test_domestic_elsewhere_uses_the_cheaper_list(self):
        got = total("national", "domestic", None, 2.0, "ULLI-2026", other="USSS")
        self.assertAlmostEqual(got["landing"], 482.00 * MTOW, 2)        # 37 596,00
        self.assertAlmostEqual(got["passenger"], 115.00 * PAX * 2, 2)   # 34 040,00
        self.assertAlmostEqual(got["security"], 498.00 * MTOW, 2)       # 38 844,00
        self.assertAlmostEqual(sum(got.values()), 110_480.00, 2)

    def test_moscow_lists_do_not_double_count(self):
        # Ровно один посадочный, одна стоянка, одна безопасность, один
        # пассажирский —
        # правило «на Москву» и правило «кроме Москвы» не срабатывают вместе.
        rs = rules("ULLI-2026")
        for other in ("UUEE", "USSS"):
            active = [r for r in rs if r.matches(ctx("national", "domestic", None, 2.0, other))]
            self.assertEqual(sorted(r.code for r in active),
                             ["landing", "parking", "passenger", "security"], other)

    def test_foreign_user_in_euro(self):
        got = total("foreign", "INTL", None, 2.0, "ULLI-2026")
        self.assertAlmostEqual(got["landing"], 10.75 * MTOW, 2)         #   838,50
        self.assertAlmostEqual(got["passenger"], 14.50 * PAX * 2, 2)    # 4 292,00
        self.assertAlmostEqual(got["security"], 8.24 * PAX, 2)          # 1 219,52
        self.assertNotIn("landing_night", got)
        self.assertAlmostEqual(sum(got.values()), 6_350.02, 2)

    def test_foreign_user_night_surcharge_and_parking(self):
        c = ctx("foreign", "INTL", None, 30.0)
        c["night"] = True
        out = {k: v for k, v in evaluate(rules("ULLI-2026"), c, fx=lambda cur: 1.0).items()
               if not k.startswith("_")}
        self.assertAlmostEqual(out["landing_night"], 0.20 * 10.75 * MTOW, 2)   # 167,70
        self.assertAlmostEqual(out["parking"], 0.15 * 10.75 * MTOW * 2, 2)     # 251,55


class Koltsovo(unittest.TestCase):
    """USSS-2026: регулируемый аэропорт, ставки из приказа ФАС 500/26."""

    def test_russian_user_domestic_two_hours(self):
        got = total("national", "domestic", None, 2.0, "USSS-2026")
        self.assertAlmostEqual(got["landing"], 610.00 * MTOW, 2)        # 47 580
        self.assertAlmostEqual(got["security"], 370.00 * MTOW, 2)       # 28 860
        self.assertAlmostEqual(got["passenger"], 84.00 * PAX * 2, 2)    # 24 864
        self.assertNotIn("parking", got)
        self.assertAlmostEqual(sum(got.values()), 101_304.00, 2)

    def test_russian_user_international(self):
        got = total("national", "EEA", None, 5.0, "USSS-2026")
        self.assertAlmostEqual(got["passenger"], 388.00 * PAX * 2, 2)   # 114 848
        self.assertAlmostEqual(got["parking"], 0.05 * 610.00 * MTOW * 2, 2)  # 4 758
        self.assertAlmostEqual(sum(got.values()), 196_046.00, 2)

    def test_foreign_user(self):
        got = total("foreign", "INTL", None, 30.0, "USSS-2026")
        self.assertAlmostEqual(got["landing"], 16.10 * MTOW, 2)         # 1 255,80
        self.assertAlmostEqual(got["security"], 9.40 * MTOW, 2)         #   733,20
        self.assertAlmostEqual(got["passenger"], 11.00 * PAX * 2, 2)    # 3 256,00
        self.assertAlmostEqual(got["parking"], 0.15 * 16.10 * MTOW * 2, 2)  # 376,74
        self.assertAlmostEqual(sum(got.values()), 5_621.74, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
