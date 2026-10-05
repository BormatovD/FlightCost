"""Реестр бортов: адрес транспондера -> тип ВС.

Зачем. Борт вещает 24-битный адрес транспондера, а не тип. Без этого
сопоставления наблюдения эксплуатации привязываются только к паре
аэропортов: частота и фактическая длина пути копятся, а главная строка —
блок-время ПО ТИПУ, на котором висят 39% себестоимости, — не собирается
вовсе.

Зависимость односторонняя: типы нужны наблюдениям, наблюдениям типы нет.

Что кладём и чего не кладём. Из тридцати с лишним колонок снимка берём
одну величину — код типа ИКАО. Регистрация, владелец, серийный номер и
дата постройки к расчёту отношения не имеют, а весят на порядок больше:
снимок это сотни тысяч бортов. Заводить их «на будущее» значило бы
раздуть справочник ради того, чего никто не спрашивает.

Строки без кода типа пропускаются молча — это норма, а не поломка:
снимок агрегирует официальные и неофициальные источники, и у части
бортов типа просто нет. Доля таких печатается в отчёт: если она вырастет,
это признак смены формата, а не мира.
"""

from __future__ import annotations

import csv
import io

from ..store import Fact

# Колонки снимка, которые нас касаются. Имена берём из заголовка, а не по
# номеру: порядок колонок у снимка менялся, и позиционное чтение однажды
# тихо подставит серийный номер вместо типа.
COL_ICAO24 = "icao24"
COL_TYPE = "typecode"


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or COL_ICAO24 not in reader.fieldnames:
        raise ValueError(
            f"в снимке нет колонки {COL_ICAO24!r}; заголовок: "
            + ", ".join((reader.fieldnames or [])[:8]))
    if COL_TYPE not in reader.fieldnames:
        raise ValueError(
            f"в снимке нет колонки {COL_TYPE!r} — без кода типа реестр "
            f"бесполезен: наблюдения не привязать к типу")

    valid_from = str(ctx.get("valid_from") or ctx.get("today") or "")
    facts, total, no_type, seen = [], 0, 0, set()
    for row in reader:
        total += 1
        icao24 = (row.get(COL_ICAO24) or "").strip().lower()
        typ = (row.get(COL_TYPE) or "").strip().upper()
        if not icao24:
            continue
        if not typ:
            no_type += 1
            continue
        if icao24 in seen:          # снимок содержит повторы адресов
            continue
        seen.add(icao24)
        facts.append(Fact(
            domain="aircraft_registry", key=icao24, value=None,
            value_text=typ, unit="icao_type", currency="",
            valid_from=valid_from, source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:aircraft_registry@1"),
            confidence="exact", certainty="exact", node="src_ac_registry",
            # Ни примечания, ни адреса на строку: это свойства ИСТОЧНИКА,
            # а не борта, и они одинаковы у всех. Полмиллиона повторов
            # одной и той же прозы дали 68 МБ из 283 — четверть базы,
            # которая ничего не сообщает. Адрес лежит в реестре, оговорка
            # про полноту снимка — там же.
            source_note="", note=""))

    ctx.setdefault("summary", []).append(
        f"бортов с типом {len(facts)} из {total}, без типа {no_type} "
        f"({no_type / total:.1%})" if total else "снимок пуст")
    if total and len(facts) < total * 0.2:
        # Не отказ: доля бортов без типа законно велика. Но падение ниже
        # пятой части — признак смены формата, и сказать об этом надо
        # раньше, чем расчёт начнёт молча терять типы.
        ctx.setdefault("coverage", []).append(
            f"тип известен лишь у {len(facts) / total:.1%} бортов снимка — "
            f"проверьте, не сменился ли заголовок")
    return facts
