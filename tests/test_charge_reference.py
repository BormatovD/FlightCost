"""Эталон аэропортовых сборов через НАСТОЯЩИЙ путь расчёта.

Причина, по которой пропажа 60% сборов Франкфурта прожила незамеченной:
эталон проверялся вызовом `evaluate` напрямую, а продукт ходит через
`route_economics`. Оба дефекта — неподанные значения условий и
домиграционный словарь `dest` в хранилище — сидели ровно в разрыве между
этими двумя путями. Проверка, обходящая обвязку, не проверяет продукт.

Контекст записан ЗДЕСЬ, рядом с числом, а не в комментарии к нему.
Эталон есть свойство пары «файл тарифа + контекст начисления», и 5 971,40
без контекста — не эталон, а число. Тот же набор при `stand=apron` даёт
5 941,40, при одном движении вместо оборота — 5 623,41.
"""

from __future__ import annotations

import os
import unittest

from flightcostapp.econ import route_economics
from flightcostapp.store import Store

DB = os.environ.get("FCA_DB", "data/flightcost.db")

# --- эталон и его контекст, неразделимо ------------------------------
REFERENCE_EUR = 5971.40
REFERENCE = {
    "origin": "FRA",
    "destination": "BCN",
    "aircraft": "A320",
    "as_of": "2026-09-07",
    "month": 7,
    "pax": 148,
    "charge_ctx": {
        "EDDF": {
            # Порядковые номера ВНУТРИ Франкфурта. Тройка здесь означает
            # категорию 3 по его собственной шкале и ничего не означает
            # для любого другого аэропорта.
            "noise_cat": 3,        # при посадке, §1.2.6
            "noise_cat_dep": 3,    # при взлёте, §1.2.7
            "ac_class": 1,
            "stand_group": 1,
            "stand": "pier",
            "park_h": 1.5,
        },
    },
}


class ChargeReference(unittest.TestCase):
    """Красный до того, как контекст доедет до начисления. Это и есть
    признак, что тест проверяет нужное."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(DB):
            raise unittest.SkipTest(f"нет базы {DB}")
        cls.store = Store(DB)

    def _run(self, load_factor, aircraft=None, **kw):
        return route_economics(
            self.store, REFERENCE["origin"], REFERENCE["destination"],
            aircraft=aircraft or REFERENCE["aircraft"], as_of=REFERENCE["as_of"],
            month=REFERENCE["month"], load_factor=load_factor, **kw)

    def _lf_for_reference_pax(self):
        """Загрузка, дающая ровно 148 пассажиров при кресле из справочника.

        Не константа: число кресел A320 — решение перевозчика, и если оно
        в справочнике изменится, тест должен сравнивать те же 148
        пассажиров, а не ту же долю.
        """
        seats = self._run(0.8).inputs["seats"]
        self.assertTrue(seats, "в справочнике нет числа кресел для A320")
        return REFERENCE["pax"] / seats

    def test_eddf_total_matches_reference(self):
        res = self._run(self._lf_for_reference_pax(),
                        charge_ctx=REFERENCE["charge_ctx"])
        self.assertEqual(round(res.inputs["pax"]), REFERENCE["pax"])
        total = sum(v for k, v in res.charge_lines.items()
                    if k.startswith("EDDF/"))
        self.assertAlmostEqual(
            total, REFERENCE_EUR, places=2,
            msg=(f"сборы EDDF {total:,.2f} против эталона {REFERENCE_EUR:,.2f}. "
                 f"Без цены остались: "
                 f"{res.charge_gaps.get('EDDF', {}).get('lost_codes')}"))

    def test_passenger_charge_is_not_lost(self):
        """Отдельно, потому что пассажирский сбор — 60% суммы аэропорта.

        Общая проверка скажет «не сошлось», эта — «пропала именно та
        статья, из-за которой всё и затевалось».
        """
        res = self._run(self._lf_for_reference_pax(),
                        charge_ctx=REFERENCE["charge_ctx"])
        self.assertIn("EDDF/passenger", res.charge_lines,
                      "пассажирский сбор EDDF не начислен — проверь словарь "
                      "dest в хранилище: ступени schengen / eu_non_schengen / "
                      "europe_non_eu / intercontinental")

    # Тип, которого Fraport не называет ни в одной таблице (§1.2.6, §1.2.7,
    # §2.2.1) и который тяжелее 34 т, — значит, ни поимённо, ни правилом
    # категории 1 его категории не определяются. На A320 эта проверка
    # больше не годится: его категории теперь приходят из документа, и
    # пропуска просто нет.
    UNLISTED = "A19N"

    def test_missing_context_is_reported_not_hidden(self):
        """Без контекста расчёт обязан не молчать, а перечислить потери.

        Это вторая половина требования: подача контекста чинит сумму,
        отсутствие подачи не должно давать правдоподобное число.
        """
        res = self._run(0.8, aircraft=self.UNLISTED)
        gaps = res.charge_gaps.get("EDDF", {})
        self.assertTrue(gaps.get("lost_codes"),
                        f"{self.UNLISTED} не назван Fraport: без значений условий "
                        f"статьи теряются, и расчёт обязан их назвать")
        # `charges.py` отдаёт три списка вместо одного: решение 78 делит
        # пропуски по адресату — «не знаем» к нам, «не задан вход» к
        # пользователю. Поле `unknown_keys` исчезло, и `.get()` возвращал
        # пустой список: проверка падала, но по неверной причине.
        missing = gaps.get("missing_data", [])
        for cond in ("noise_cat", "noise_cat_dep", "ac_class"):
            self.assertIn(cond, missing)

    def test_categories_come_from_the_document(self):
        """Вторая сторона того же требования: там, где документ тип
        называет, категории доезжают до начисления сами, без `--set`.

        Если этот тест начнёт падать при зелёном предыдущем, значит
        раздел `categories` файла тарифа перестал читаться — и Франкфурт
        снова считается без шума, обслуживания и стоянки.
        """
        res = self._run(self._lf_for_reference_pax())
        gaps = res.charge_gaps.get("EDDF", {})
        self.assertFalse(gaps.get("lost_codes"),
                         f"A320 назван Fraport во всех трёх таблицах, а статьи "
                         f"потеряны: {gaps.get('lost_codes')}")
        for code in ("EDDF/noise", "EDDF/gh_infra", "EDDF/parking"):
            self.assertIn(code, res.charge_lines)

    def test_airport_cost_is_half_the_rotation(self):
        """Решение 137: строки по аэропортам — за оборот, статья — за рейс.

        Сборы оборота целиком на одном рейсе удваивали статью: пассажирский
        сбор Барселоны брался с пассажиров обратного рейса. Строки при этом
        обязаны остаться за оборот — по ним сходится эталон Франкфурта.
        """
        res = self._run(self._lf_for_reference_pax(),
                        charge_ctx=REFERENCE["charge_ctx"])
        rotation = sum(res.charge_lines.values())
        self.assertAlmostEqual(res.cost["airport_charges"], rotation / 2, places=2,
                               msg="статья аэропортовых сборов не равна половине оборота")

    def test_foreign_currency_rate_is_a_step(self):
        """Решение 142: курс пересчёта виден в разборе, а не только в сумме.

        Гатвик считает в фунтах — значит в трассировке обязан стоять шаг
        «Курс GBP» с узлом `d_fx`. Без него пересчёт шёл внутри начисления
        молча, и ставки в чужой валюте пересчитывались по числу, которого
        нет в разборе.
        """
        res = route_economics(self.store, "LGW", "BCN", aircraft="A320",
                              as_of=REFERENCE["as_of"], month=REFERENCE["month"],
                              load_factor=0.8)
        steps = [st for st in res.trace if st.label.startswith("Курс GBP")]
        self.assertTrue(steps, "пересчёт фунта в разборе не виден")
        self.assertEqual(steps[0].node, "d_fx")
        self.assertGreater(steps[0].value, 0)


    def test_reference_depends_on_its_context(self):
        """Страховка от того, что эталон снова станет просто числом.

        Если этот тест начнёт падать, значит контекст перестал влиять на
        сумму — то есть либо он не доходит, либо правила его не читают.
        """
        apron = dict(REFERENCE["charge_ctx"]["EDDF"], stand="apron")
        res = self._run(self._lf_for_reference_pax(),
                        charge_ctx={"EDDF": apron})
        total = sum(v for k, v in res.charge_lines.items()
                    if k.startswith("EDDF/"))
        self.assertNotAlmostEqual(total, REFERENCE_EUR, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
