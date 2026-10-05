"""Цена топлива: четыре величины, а не одна.

Плоское число здесь было бы той же ошибкой, что плоская ставка ТОиР до
M5: неверна форма, а не величина. Четыре слагаемых имеют разную природу,
разный ритм и разную добываемость, и слитые в одно они это скрывают.

    spot/<регион>          биржевая котировка       ежедневно   ЕСТЬ
    differential/<регион>  разница к эталону        месяц       НЕТ ИСТОЧНИКА
    into_plane/<ИКАО>      заправка в крыло         договор     закрыто
    ets/<год>, saf/<год>   регулирование            год         публично

Заведён первый.

ПЛОТНОСТЬ ЛЕЖИТ В ДРУГОМ ДОМЕНЕ — `fuel_spec`, и это не мелочь. Домен —
единица однородности правил: у гейта одна ожидаемая единица измерения на
домен, и он справедливо отверг поставку, где рядом с долларом за галлон
приехали килограммы на литр. Плотность и цена — разной природы, разного
ритма и разного издателя: одна из спецификации топлива и не меняется
десятилетиями, другая котируется ежедневно. Класть их вместе было
удобством, а не свойством величин.

Отсюда честная формулировка результата: 19,1%
себестоимости перешли из «одного выдуманного числа» в «одно измеренное
плюс одно выдуманное».

РАЗБИРАЕТСЯ HTML, А НЕ ЕГО ПРЕДСТАВЛЕНИЕ. Прежняя редакция искала строки
с вертикальными чертами — то есть markdown-вид страницы, который отдаёт
инструмент чтения. Контур качает исходный HTML, черт в нём нет ни одной,
и разбор падал на «не найдено ни одной котировки». Величина настоящая,
источник настоящий, КЛАСС АРТЕФАКТА другой — та же ошибка, что со строкой
ТОиР у Ryanair и с блок-временем в наблюдениях, только про сам документ.

Отсюда правило: новый источник проверяется прогоном через `fca refresh`,
а не вызовом парсера на куске текста из блокнота.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta

from ..store import Fact

SERIES = "EER_EPJK_PF4_RGC_DPG"

MONTH = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

# Плотность — ФАКТ С ПРОВЕНАНСОМ, а не константа в коде. Иначе через год
# никто не вспомнит, откуда взялось 0,8, и число станет неотличимо от
# выдуманного. Полоса задана спецификацией топлива, а не нами.
DENSITY = {
    "key": "density/jet_a1",
    "value": 0.804,
    "unit": "kg/l",
    "note": ("Плотность Jet A-1 при 15 °C. DEF STAN 91-091 и ASTM D1655 "
             "задают полосу 0,775-0,840 кг/л; 0,804 — принятое отраслевое "
             "значение для пересчёта объёма в массу. ВНУТРИ ПОЛОСЫ РАЗБРОС "
             "±4%, и он целиком переходит в цену за килограмм"),
    "error_cost": 0.086,          # EUR/кг между краями полосы
    "confirm_by": "паспорт топлива поставщика на конкретной заправке",
}


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    """Дневной ряд EIA -> факты `spot/USGC` в долларах за галлон.

    Ставка сохраняется КАК ОПУБЛИКОВАНА (решение 22): доллар за галлон.
    Пересчёт в евро за килограмм делает расчёт, беря курс из домена `fx` и
    плотность отсюда же. Пересчитывать здесь значило бы зашить курс дня
    загрузки в историческую котировку, и расчёт «на прошлый март»
    воспроизводил бы сегодняшний курс.
    """
    rows = _rows(blob.decode("utf-8", "replace"))
    if not rows:
        raise ValueError(
            "в документе EIA не найдено ни одной котировки: ожидалась "
            f"таблица «неделя x пять дней» в HTML со страницы ряда {SERIES}")

    src = str(ctx.get("url") or "")
    common = dict(
        source_id=ctx["source_id"],
        artifact_sha=ctx.get("sha"),
        extracted_by=ctx.get("extracted_by", "parser:jet_fuel_price@2"),
        confidence="exact")

    facts = [Fact(
        domain="jet_fuel_price", key="spot/USGC", valid_from=d.isoformat(), value=v,
        unit="USD_per_gallon", currency="USD", value_text="",
        certainty="exact", node="src_eia",
        source_note=("спот FOB Мексиканский залив; НЕ европейская цена и "
                     "НЕ цена в крыло"),
        note=f"{SERIES} | {src}", **common) for d, v in rows]

    facts.append(Fact(
        domain="fuel_spec", key=DENSITY["key"], valid_from="1990-01-01", value=DENSITY["value"],
        unit=DENSITY["unit"], currency="", value_text="",
        certainty="reading_unconfirmed", node="src_fuel_spec",
        error_cost=DENSITY["error_cost"], confirm_by=DENSITY["confirm_by"],
        source_note=DENSITY["note"], note="DEF STAN 91-091 / ASTM D1655",
        **common))

    ctx.setdefault("summary", []).append(
        f"котировок {len(rows)}, с {rows[0][0]} по {rows[-1][0]}")
    return facts


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
# Заголовок строки: «1990 Apr- 2 to Apr- 6». Число пробелов после дефиса
# переменное — EIA выравнивает столбец по правому краю.
_HEAD = re.compile(r"^(\d{4})\s+([A-Z][a-z]{2})-\s*(\d{1,2})\s+to\s+"
                   r"([A-Z][a-z]{2})-\s*(\d{1,2})$")


def _text(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell)).replace("\xa0", " ").strip()


def _rows(doc: str) -> list[tuple[date, float]]:
    """Таблица «неделя x пять дней» разворачивается в дневной ряд.

    Заголовок строки — «1990 Apr- 2 to Apr- 6», дальше пять ячеек с
    понедельника по пятницу. Пустая ячейка означает НЕРАБОЧИЙ ДЕНЬ, а не
    ноль: подставить туда ноль значило бы завести котировку, которой не
    было.

    Неделя, переходящая через Новый год («2018 Dec-31 to Jan- 4»), второй
    половиной принадлежит следующему году. Год не подменяется — дата
    считается сложением дней от понедельника, поэтому переход выходит сам.
    """
    out: list[tuple[date, float]] = []
    for row in _ROW.findall(doc):
        cells = [_text(c) for c in _CELL.findall(row)]
        if not cells:
            continue
        m = _HEAD.match(cells[0])
        if not m:
            continue
        year, mon, day, _m2, _d2 = m.groups()
        try:
            monday = date(int(year), MONTH[mon], int(day))
        except (KeyError, ValueError):
            continue
        for i, cell in enumerate(cells[1:6]):
            if not cell:
                continue
            try:
                v = float(cell)
            except ValueError:
                continue
            out.append((monday + timedelta(days=i), v))
    out.sort()
    return out
