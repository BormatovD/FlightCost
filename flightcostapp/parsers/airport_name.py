"""Названия аэропортов на разных языках.

ЗАЧЕМ. Поиск в витрине сейчас работает по коду и английскому названию.
Человек, который набирает «Франкфурт», не находит EDDF — и это не
придирка: продукт рассчитан на трёх пользователей, и двое из них думают
не по-английски.

Придумать перевод нельзя. Транслитерация даёт «Франкфурт Майн Эйрпорт», и
это будет та же выдуманная константа, что заглушка цены топлива: похоже
на данные, ничем не обеспечено. Название — публикуемая величина, и
источник у неё должен быть.

ЧТО В ИСТОЧНИКЕ И ЧЕГО ТАМ НЕТ. Файл отдаёт `name_translations` — словарь
локаль → название. Какие локали в нём есть, заранее не известно и меняется
со временем, поэтому берём ВСЕ, что пришли, и печатаем список: обещать
китайский до того, как он увиден, нельзя.

Файл содержит не только аэропорты: там железнодорожные и автобусные
станции, потому что поиск билетов их тоже показывает. Различаются полем
`iata_type`, и всё, что не `airport`, отбрасывается — иначе в справочник
аэропортов приедет вокзал.
"""

from __future__ import annotations

import collections
import json

from ..store import Fact

# Локали, которые держим. Не «все подряд»: каждая локаль — это строка на
# аэропорт, а аэропортов тысячи. Список расширяется по надобности, и
# расширение видно в истории домена.
KEEP = ("ru", "en", "de", "fr", "es", "it", "zh-CN", "zh", "pl", "tr", "ar")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    data = json.loads(blob.decode("utf-8", "replace"))
    if not isinstance(data, list) or not data:
        raise ValueError("ожидался список аэропортов")

    store = ctx.get("store")
    to_icao = store.icao_of_iata() if store is not None else {}
    if not to_icao:
        raise ValueError(
            "указатель кодов пуст: сначала fca refresh --only airport_codes")

    valid_from = str(ctx.get("valid_from") or ctx.get("today") or "")
    facts = []
    seen_loc: collections.Counter = collections.Counter()
    skipped_type: collections.Counter = collections.Counter()
    no_icao = 0

    for r in data:
        if not isinstance(r, dict):
            continue
        kind = (r.get("iata_type") or "").strip().lower()
        if kind and kind != "airport":
            # Вокзал в справочнике аэропортов — это не лишняя строка, а
            # ложный аэропорт: по нему посчитается маршрут.
            skipped_type[kind] += 1
            continue
        iata = (r.get("code") or "").strip().upper()
        icao = to_icao.get(iata)
        if not icao:
            no_icao += 1
            continue
        tr = r.get("name_translations") or {}
        if r.get("name") and "en" not in tr:
            tr = dict(tr, en=r["name"])
        for loc, name in tr.items():
            if loc not in KEEP or not str(name).strip():
                continue
            seen_loc[loc] += 1
            facts.append(Fact(
                domain="airport_name", key=f"{icao}/{loc}", value=None,
                value_text=str(name).strip(), unit="", currency="",
                valid_from=valid_from, source_id=ctx["source_id"],
                artifact_sha=ctx.get("sha"),
                extracted_by=ctx.get("extracted_by", "parser:airport_name@1"),
                confidence="exact", certainty="exact", node="src_names",
                source_note="", note=""))

    ctx.setdefault("summary", []).append(
        "локали: " + ", ".join(f"{k} {n}" for k, n in seen_loc.most_common())
        + f"; без кода ИКАО {no_icao}"
        + (f"; отброшено не аэропортов: "
           + ", ".join(f"{k} {n}" for k, n in skipped_type.most_common(4))
           if skipped_type else ""))
    missing = [k for k in ("ru", "zh-CN", "zh") if k not in seen_loc]
    if missing:
        # Не отказ: поиск работает и без части языков. Но сказать надо —
        # иначе «китайского нет» обнаружится при показе китайцу.
        ctx.setdefault("coverage", []).append(
            "локалей нет в источнике: " + ", ".join(missing))
    return facts
