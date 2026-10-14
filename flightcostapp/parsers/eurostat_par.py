"""Eurostat: пассажиры между аэропортами-парами — домен `traffic` (M10).

Таблицы `avia_par_<страна>` («Air passenger transport between the main
airports of <страна> and their main partner airports»): по паре
аэропортов, по месяцам, сколько пассажиров ПЕРЕВЕЗЕНО (`PAS_CRD`, оба
направления вместе). Публикует Eurostat по Регламенту 437/2003, повторное
использование — CC BY 4.0 (решение Комиссии 2011/833/EU). Задержка —
квартал-полгода после отчётного периода.

Почему «перевезено», а не «на борту» (`PAS_BRD`). На борту считаются и
транзитные пассажиры многоплечевого рейса, а пара FRA–BCN спрашивает,
сколько людей летит между этими городами. Перевезено — ровно это.

Форматы. Data Browser отдаёт два вида выгрузки, и разбираются оба:

* старый TSV: `freq,unit,tra_meas,airp_pr\\TIME_PERIOD<TAB>2024-01 <TAB>…`,
  значения со знаками качества (`12345 p`, `:` — нет значения);
* SDMX-CSV: колонки `freq, unit, tra_meas, airp_pr, TIME_PERIOD,
  OBS_VALUE, OBS_FLAG` (подписи колонок бывают с расшифровкой после `:`).

Файл может быть сжат gzip — как отдаёт массовая выгрузка.

Ключ: `<ИКАО отчитавшегося>/<ИКАО-ИКАО по алфавиту>/<ГГГГ-ММ>`. Отчитавшийся
стоит первым, потому что одну и ту же пару публикуют обе страны (Германия —
FRA–BCN, Испания — BCN–FRA), а файл каждой страны снимается с учёта своим
префиксом. Читатель (`traffic.py`) сводит отчёты сторон.
"""

from __future__ import annotations

import csv
import gzip
import io
import re

from ..store import Fact

WHO = "parser:eurostat_par@2"
MEASURE = "PAS_CRD"           # пассажиры перевезённые, оба направления
# Рядом с пассажирами — кресла и рейсы той же пары (проверено на выгрузке
# avia_par_de: август 2024 FRA–BCN — 481 рейс, 80 411 пассажиров, сумма
# месяцев 2024 = годовой строке 804 747). Из них — средний борт рынка и
# его загрузка: величины, с которыми сравнивается свой рейс.
EXTRA = {"ST_PAS": ("seats", "кресел/мес"), "CAF_PAS": ("flights", "рейсов/мес")}
KEEP_MONTHS = 36              # месяцев от последнего в файле — глубже не нужно
_AP = re.compile(r"^([A-Z]{2})_([A-Z0-9]{4})_([A-Z]{2})_([A-Z0-9]{4})$")
_MONTH = re.compile(r"^(\d{4})-?M?(\d{2})$")


def _text(blob: bytes) -> str:
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return blob.decode("utf-8-sig", errors="replace")


def _month(s: str) -> str | None:
    m = _MONTH.match(s.strip())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s.startswith(":"):
        return None
    s = s.split()[0]                       # «12345 p» -> 12345
    try:
        return float(s)
    except ValueError:
        return None


def _rows(text: str):
    """(freq, unit, tra_meas, airp_pr, период, значение) из любого формата."""
    first = text.split("\n", 1)[0]
    if "\t" in first and "\\" in first:                       # старый TSV
        rd = csv.reader(io.StringIO(text), delimiter="\t")
        head = next(rd)
        dims = head[0].split("\\")[0].split(",")
        periods = [h.strip() for h in head[1:]]
        for row in rd:
            if not row:
                continue
            d = dict(zip(dims, row[0].split(",")))
            for per, cell in zip(periods, row[1:]):
                yield (d.get("freq"), d.get("unit"), d.get("tra_meas"),
                       d.get("airp_pr"), per, _num(cell))
        return
    rd = csv.DictReader(io.StringIO(text))
    # «airp_pr: Airport pair» и «airp_pr» — одна колонка.
    norm = {k: (k or "").split(":")[0].strip() for k in (rd.fieldnames or [])}
    need = {"freq", "unit", "tra_meas", "airp_pr", "TIME_PERIOD", "OBS_VALUE"}
    if not need <= set(norm.values()):
        raise ValueError(f"не похоже на выгрузку avia_par: нет колонок "
                         f"{sorted(need - set(norm.values()))}")
    for raw in rd:
        r = {norm[k]: (v or "").split(":")[0].strip() for k, v in raw.items() if k}
        yield (r["freq"], r["unit"], r["tra_meas"], r["airp_pr"], r["TIME_PERIOD"],
               _num(r["OBS_VALUE"]))


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    day = ctx.get("today") or ""
    name = str(ctx.get("url") or "").removeprefix("file:").replace("\\", "/").rsplit("/", 1)[-1] \
        or ctx.get("source_id", "")
    keep = []
    for freq, unit, meas, pair, per, val in _rows(_text(blob)):
        if freq != "M" or val is None or (meas != MEASURE and meas not in EXTRA):
            continue
        m, mon = _AP.match(pair or ""), _month(per or "")
        if not m or not mon:
            continue
        keep.append((m.group(2), m.group(4), mon, val, meas))
    if not any(k[4] == MEASURE for k in keep):
        raise ValueError("в файле нет месячных строк PAS_CRD (пассажиры перевезённые): "
                         "выгружена не та мера или не та частота")
    last = max(k[2] for k in keep)
    y, mo = int(last[:4]), int(last[5:])
    total = y * 12 + mo - 1 - (KEEP_MONTHS - 1)
    since = f"{total // 12:04d}-{total % 12 + 1:02d}"
    agg: dict[tuple, list] = {}
    idx = {MEASURE: 0, "ST_PAS": 1, "CAF_PAS": 2}
    for rep, partner, mon, val, meas in keep:
        if mon < since:
            continue
        a, b = sorted((rep, partner))
        agg.setdefault((rep, a, b, mon), [None, None, None])[idx[meas]] = val
    agg = {k: v for k, v in agg.items() if v[0] is not None}
    reporters = {k[0] for k in agg}
    from ..traffic import pack
    facts = pack(agg, ctx=ctx, who=WHO,
                 note=f"Eurostat {name}: пассажиры перевезённые, оба направления")
    # Снимается с учёта только то, что этот файл разобрал целиком: свои
    # отчитавшиеся аэропорты (решение 63).
    ctx.setdefault("parsed_prefixes", []).extend(sorted(reporters))   # store добавит «/»
    ctx["summary"] = [x for x in ctx.get("summary", [])]
    ctx["summary"].insert(0,
        f"пар {len({f.key.split('/')[1] for f in facts})}, месяцев с {since} по {last}, "
        f"аэропортов-отчётчиков {len(reporters)}")
    return facts
