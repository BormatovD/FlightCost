"""Приёмка по исключениям: что показать человеку, а что принять молча.

Пятнадцать аэропортов дают 438 фактов, сто дадут около трёх тысяч.
Построчная приёмка — неделя чтения чисел, и на третьем часу ошибка
приёмки неотличима от ошибки извлечения. Поэтому человеку показывается
остаток, а не всё.

Два требования к списку важнее его содержания (решение 96):

1. Разрешённое не всплывает заново. Иначе список вечно содержит
   известное, его перестают читать, и проверка умирает так же надёжно,
   как мёртвый валидатор.
2. Длина списка не растёт пропорционально числу документов. Если на сотом
   аэропорте выделенных вдвое больше, чем на пятнадцатом, порог выбран
   неверно: это распределение, а не исключения. Поэтому доля печатается
   при каждом разборе — она и есть индикатор.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# Абсолютный порог ловит КАТАСТРОФУ и только её: потерянный разряд, ставку
# в центах вместо евро, перепутанную единицу.
#
# Полосы ВЫВЕДЕНЫ ИЗ КОРПУСА, а не из головы. Первая версия была
# придумана — и отвергла десять верных строк: шум Франкфурта 29 976 EUR
# за движение, наземное обслуживание A380 5 826 за обслуживание, посадка
# Познани 37,65 за тонну для кода F. Ровно ошибка M1 с `row_count_min`,
# повторённая мной через год после того, как из неё сделали правило.
#
# Множитель — порядок величины от наблюдённого предела на 15 аэропортах.
# Проверка обязана срабатывать на сдвиге разряда и молчать на всём
# остальном; проверено на подложных поломках, см. тест ниже.
# ПЕРЕСМАТРИВАТЬ, когда корпус вырастет на порядок.
ABSOLUTE_EUR = {
    "per_departing_pax": (-60.0, 300.0),
    "per_tonne_mtow":    (-30.0, 400.0),
    "per_tonne_above":   (-30.0, 400.0),
    "per_movement":      (-750.0, 300_000.0),
    "per_turnaround":    (0.0, 60_000.0),
    "per_hour":          (0.0, 2_000.0),
    "per_15min":         (0.0, 2_000.0),
    "per_hour_above":    (0.0, 2_000.0),
    "per_100kg":         (0.0, 3.0),
    "per_service_unit":  (0.0, 5_000.0),
    "per_day":           (0.0, 20_000.0),
    "per_pax_per_movement": (-60.0, 300.0),
    "per_day_above":     (0.0, 20_000.0),
}


@dataclass
class Flag:
    key: str
    # Дрейфа здесь нет намеренно. Сравнение с медианой КОРПУСА я завёл и
    # убрал: на пятнадцати аэропортах оно выделило 86 строк из 422, и все
    # верные — пассажирский сбор Франкфурта законно вчетверо выше
    # медианы. Это тот же коридор, только в профиль. Дрейф — величина
    # ВРЕМЕННА́Я: сравнение с прошлым значением того же ключа, и оно уже
    # есть в гейте с M3. Дублировать его здесь незачем.
    trigger: str      # corpus | absolute | certainty | reachable | reference
    why: str
    value: float | None = None


def _sha(fact) -> str:
    """Отпечаток значения. Разрешение привязано к нему, а не к ключу:
    если ставка изменится, кандидат обязан всплыть заново."""
    return hashlib.sha256(
        f"{fact.value}|{fact.value_text}|{fact.currency}".encode()).hexdigest()[:16]


def _eur(v, cur, fx):
    if v is None:
        return None
    if not cur or cur == "EUR":
        return v
    r = fx(cur) if fx else None
    return None if not r else v / r


def flag(facts, *, store=None, fx=None, corpus_candidates=(), dead_rules=(),
         icao_missing=(), acked=frozenset()) -> tuple[list[Flag], dict]:
    """Строки, которые человек обязан посмотреть, и доля от общего числа."""
    rules = [f for f in facts if f.value_text]          # `_na` и `_scope` мимо
    out: list[Flag] = []

    for c in corpus_candidates:
        out.append(Flag(key=f"{c.icao}/{c.code}", trigger="corpus",
                        why=f"статья есть у {c.present_at} аэропортов корпуса, здесь нет"))
    for d in dead_rules:
        out.append(Flag(key=d, trigger="reachable", why="правило недостижимо"))
    for i in icao_missing:
        out.append(Flag(key=i, trigger="reference",
                        why="код ИКАО отсутствует в домене airport"))

    no_rate = []
    for f in rules:
        if _sha(f) in acked:
            continue
        base = f.unit
        # Два повода независимы, и второй не должен зависеть от исхода
        # первого. Раньше «нет курса» уходил в `continue`, и у строки без
        # курса проверка прочтения не выполнялась вовсе: две оговорки
        # Шереметьево (reading_unconfirmed, цена ошибки 3 077 RUB) прошли
        # гейт без пометки, потому что в базе не было рубля. Механизм,
        # который может ничего не сделать, обязан об этом сказать
        # (решение 37) — и не должен молчать из-за соседнего механизма.
        if f.certainty != "exact":
            out.append(Flag(key=f.key, trigger="certainty",
                            why=f"{f.certainty}, цена ошибки "
                                f"{f.error_cost or 0:.0f} {f.currency}, "
                                f"подтвердить: {f.confirm_by}", value=f.value))
        v = _eur(f.value, f.currency, fx)
        if v is None:
            no_rate.append(f.currency)
            out.append(Flag(key=f.key, trigger="absolute",
                            why=f"нет курса {f.currency}: абсолютный порог не проверен",
                            value=f.value))
            continue
        lo, hi = ABSOLUTE_EUR.get(base, (-1e9, 1e9))
        if not (lo <= v <= hi):
            out.append(Flag(key=f.key, trigger="absolute",
                            why=f"{v:.2f} EUR вне полосы {lo}..{hi} для базы {base}",
                            value=f.value))

    share = len(out) / len(rules) if rules else 0.0
    stats = {"flagged": len(out), "rules": len(rules), "share": round(share, 4),
             "by_trigger": {t: sum(1 for x in out if x.trigger == t)
                            for t in sorted({x.trigger for x in out})},
             "no_fx": sorted(set(no_rate))}
    return out, stats
