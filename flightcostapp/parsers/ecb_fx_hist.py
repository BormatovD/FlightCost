"""История справочных курсов ЕЦБ: eurofxref-hist.zip -> домен fx.

Ежедневный файл (`ecb_fx`) кладёт один день. Рядам страницы «План и
показатели» и расчёту на прошлую дату нужен курс на каждый месяц с начала
окна (с 2025 года, `monitor.SINCE`), а его в базе нет, пока ежедневный
сборщик не прожил этот срок. Здесь — тот же курс ЕЦБ задним числом.

Формат: zip с eurofxref-hist.csv, первая строка `Date,USD,JPY,…`, дальше
по строке на рабочий день, отсутствующее — `N/A`. Единиц валюты за один
евро, как у ежедневного файла и у CRCO.

Интервалы закрываются следующей датой ряда: иначе каждый день оставался
бы открытым, и добавленная задним числом история перекрывала бы сама себя.
"""

from __future__ import annotations

import csv
import io
import zipfile

from ..store import Fact

FROM = "2025-01-01"


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0].strip() != "Date":
        raise ValueError("в архиве ЕЦБ нет таблицы с заголовком Date")
    head = [h.strip() for h in rows[0]]
    days = sorted((r for r in rows[1:] if r and r[0].strip() >= FROM), key=lambda r: r[0])
    if not days:
        raise ValueError(f"в истории ЕЦБ нет дат с {FROM}")
    by_cur: dict[str, list[tuple[str, float]]] = {}
    for r in days:
        for cur, cell in zip(head[1:], r[1:]):
            cell = cell.strip()
            if cur and cell and cell != "N/A":
                by_cur.setdefault(cur, []).append((r[0].strip(), float(cell)))
    facts = []
    for cur, pts in by_cur.items():
        for i, (d, v) in enumerate(pts):
            facts.append(Fact(domain="fx", key=cur, valid_from=d,
                              valid_to=pts[i + 1][0] if i + 1 < len(pts) else None,
                              value=v, unit="per_EUR", currency=cur,
                              source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                              extracted_by="parser:ecb_fx_hist@1", confidence="exact",
                              note="справочный курс ЕЦБ, история"))
    if len(by_cur) < 20:
        raise ValueError(f"в истории ЕЦБ {len(by_cur)} валют, ожидалось не менее 20")
    ctx.setdefault("summary", []).append(
        f"ЕЦБ, история с {days[0][0]} по {days[-1][0]}: {len(days)} дней, {len(by_cur)} валют")
    return facts
