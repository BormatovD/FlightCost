"""Перечень аэропортов, которые мы ведём. Файл владельца, не мой.

ЗАЧЕМ ДОМЕН, А НЕ ФАЙЛ РЯДОМ. Список лежал в скачанном CSV, который я
сделал разовым скриптом на своей стороне. Через месяц никто не вспомнит,
откуда он взялся и соответствует ли текущему списку — то же самое, что
хранить курс валюты в комментарии. Став источником, список получает
историю, происхождение и дату, а инструменты берут его из хранилища, а не
из файла, который кто-то когда-то положил рядом.

ФОРМАТ — ВАШ. Первая колонка с кодами, заголовок любой. Коды принимаются
и в ИАТА, и в ИКАО: в одном списке они мешаются, и требовать единообразия
значит перекладывать на человека работу указателя. Прочие колонки
необязательны и переносятся как есть — приписка, приоритет, что угодно.

ГОРОДСКИЕ КОДЫ НЕ ЗАВОДЯТСЯ (решение 104). `MOW` — это Шереметьево,
Домодедово, Внуково и Жуковский сразу; подставить любой значит соврать
молча. Такая строка уходит в список к человеку с вопросом, какой именно.
"""

from __future__ import annotations

import io

from ..store import Fact

# Колонки, которые узнаём по имени. Остальные переносятся в примечание.
CODE_HINTS = ("аэропорт", "код", "iata", "icao", "airport", "code")
NOTE_HINTS = ("примечание", "зачем", "почему", "note", "комментарий")
PRIO_HINTS = ("приоритет", "очередь", "priority")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    try:
        import openpyxl
    except ImportError:                                   # noqa: BLE001
        raise ValueError(
            "для разбора перечня нужен openpyxl: pip install -e '.[tools]'")

    wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True)
    ws = wb.worksheets[0]
    head = [str(c or "").strip() for c in
            next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    low = [h.lower() for h in head]

    def find(hints, default=None):
        for i, h in enumerate(low):
            if any(x in h for x in hints):
                return i
        return default

    i_code = find(CODE_HINTS, 0)
    i_note, i_prio = find(NOTE_HINTS), find(PRIO_HINTS)

    # Указатель кодов: без него ИАТА не перевести, а перечень в двух
    # системах — это перечень, который ни с чем не стыкуется.
    store = ctx.get("store")
    to_icao = store.icao_of_iata() if store is not None else {}
    if not to_icao:
        raise ValueError(
            "указатель кодов пуст: сначала fca refresh --only airport_codes")
    known_icao = set(to_icao.values())

    valid_from = str(ctx.get("valid_from") or ctx.get("today") or "")
    facts, cities, unknown, seen = [], [], [], set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw = str(row[i_code] or "").strip().upper()
        if not raw:
            continue
        icao = raw if raw in known_icao else to_icao.get(raw)
        if icao is None:
            # Городской код или опечатка — различить по длине нельзя, и
            # гадать не надо: три знака без перевода это почти всегда
            # город, четыре — опечатка или аэродром вне справочника.
            (cities if len(raw) == 3 else unknown).append(raw)
            continue
        if icao in seen:
            continue
        seen.add(icao)
        note = str(row[i_note] or "").strip() if i_note is not None else ""
        prio = row[i_prio] if i_prio is not None else None
        facts.append(Fact(
            domain="airport_watch", key=icao,
            value=float(prio) if isinstance(prio, (int, float)) else None,
            value_text=raw, unit="", currency="", valid_from=valid_from,
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:airport_watch@1"),
            confidence="exact", certainty="exact", node="src_watchlist",
            source_note=note, note=""))

    ctx.setdefault("summary", []).append(
        f"аэропортов {len(facts)}"
        + (f", городских кодов {len(cities)}: {', '.join(cities)}" if cities else "")
        + (f", не опознано {len(unknown)}: {', '.join(unknown[:6])}" if unknown else ""))
    if cities:
        # Не отказ: список полезен и без них. Но вопрос обязан дойти до
        # человека — иначе через месяц Москва просто не посчитается, и
        # причины будет не найти.
        ctx.setdefault("coverage", []).append(
            "городские коды требуют уточнения, какой именно аэродром: "
            + ", ".join(cities))
    if unknown:
        ctx.setdefault("coverage", []).append(
            "коды не найдены в указателе: " + ", ".join(unknown))
    return facts
