"""Указатель кодов аэропорта: ИАТА и прочие -> ИКАО.

ЗАЧЕМ ОТДЕЛЬНЫЙ ДОМЕН, А НЕ ПОЛЕ ЗАПИСИ (решение 104).

У кода своя история действия: коды ИАТА переиспользуются, и тот же три
знака через десять лет может означать другой аэродром. Кодов бывает
НЕСКОЛЬКО на один аэропорт — у Базель-Мюлуза их три при одном ИКАО.
И наконец, городской код обязан отвечать вопросом, а не одним из шести
аэродромов: `MOW` это Шереметьево, Домодедово, Внуково и Жуковский
сразу, и подставить любой из них наугад значит соврать молча.

ЧТО ЭТО РАЗБЛОКИРУЕТ. Ссылочная проверка в гейте сейчас ищет ИКАО
перебором `value_text` всего домена `airport` — сорок восемь тысяч строк
на каждый ключ. Пассажиропоток приходит и в ИКАО (Eurostat), и в ИАТА
(американские выборки). Парсер билетов работает в ИАТА, наблюдения
ADS-B — в ИКАО. Без указателя каждая склейка делается руками и молча.

ЧЕГО ЗДЕСЬ НЕТ. Городских кодов. Их нет и в источнике — это не пробел, а
свойство: `MOW`, `LON`, `NYC` не аэропорты, и заводить их сюда нельзя.
Когда понадобятся, им нужен свой домен со списком аэродромов и явным
ответом «уточните, какой».
"""

from __future__ import annotations

import csv
import collections
import io

from ..store import Fact


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "icao" not in rows[0]:
        raise ValueError(
            "в справочнике нет колонки icao; заголовок: "
            + ", ".join(list(rows[0])[:6] if rows else []))

    valid_from = str(ctx.get("valid_from") or ctx.get("today") or "")
    by_iata: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        iata = (r.get("iata") or "").strip().upper()
        icao = (r.get("icao") or "").strip().upper()
        if len(iata) == 3 and len(icao) == 4:
            by_iata[iata].append(r)

    facts, ambiguous = [], []
    for iata, items in sorted(by_iata.items()):
        icaos = {(x.get("icao") or "").strip().upper() for x in items}
        if len(icaos) > 1:
            # Один код ИАТА на два разных ИКАО — это НЕ дубликат, а
            # неоднозначность: подставив любой, мы соврём. Такие строки
            # не заводятся и уходят человеку списком.
            ambiguous.append(f"{iata} -> {', '.join(sorted(icaos))}")
            continue
        r = items[0]
        facts.append(Fact(
            domain="airport_code", key=f"IATA/{iata}", value=None,
            value_text=r["icao"].strip().upper(), unit="icao",
            currency="", valid_from=valid_from, source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:airport_code@1"),
            confidence="exact", certainty="exact", node="src_codes",
            source_note="", note=""))

    ctx.setdefault("summary", []).append(
        f"кодов ИАТА {len(facts)} из {len(rows)} строк; "
        f"неоднозначных {len(ambiguous)}"
        + (f": {', '.join(ambiguous[:5])}" if ambiguous else ""))
    if ambiguous:
        ctx.setdefault("coverage", []).extend(ambiguous)
    return facts
