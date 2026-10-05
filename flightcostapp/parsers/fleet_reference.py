"""Компоновки салонов и масса пассажира -> факты хранилища.

Раньше эти два справочника лежали в config/ и читались напрямую. Из-за
этого у них не было ни провенанса, ни истории, ни авторства — то есть
слой сообщества, ради которого затевались три уровня данных, к ним был
неприменим. Тарифы аэропортов лежали правильно, а эти два выпали.

Теперь они проходят тот же путь, что и всё остальное: файл в data/,
парсер, гейт, факты с датой и источником. Пользователь может прислать
свою компоновку, и она будет отличима от нашей.

Формат — тот же YAML, что был в config/, чтобы правка оставалась
человекочитаемой.
"""

from __future__ import annotations

from ..store import Fact


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import yaml

    d = yaml.safe_load(blob.decode("utf-8")) or {}
    day = ctx.get("today") or ""
    who = ctx.get("extracted_by", "parser:fleet_reference@1")
    facts: list[Fact] = []

    for key, seats in (d.get("layouts") or {}).items():
        op, _, icao = key.partition("/")
        if not icao:
            raise ValueError(f"ключ компоновки {key!r}: ожидалось "
                             f"«перевозчик/тип», например LH/A320")
        facts.append(Fact(
            domain="aircraft_layout", key=f"{op}/{icao.upper()}",
            valid_from=day, value=float(seats), unit="seats",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=who, confidence="exact",
            note=d.get("source") or "компоновка перевозчика"))

    for icao, kg in ((d.get("pax_mass") or {}).get("by_type") or {}).items():
        facts.append(Fact(
            domain="pax_mass", key=icao.upper(), valid_from=day,
            value=float(kg), unit="kg_per_pax",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=who, confidence="exact",
            note="масса пассажира с багажом, по типу"))

    for row in ((d.get("pax_mass") or {}).get("by_class") or []):
        facts.append(Fact(
            domain="pax_mass", key=f"class/{row['max_mtow_t']:g}",
            valid_from=day, value=float(row["kg"]), unit="kg_per_pax",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=who,
            confidence="estimated" if "ДОПУЩЕНИЕ" in str(row.get("note", ""))
            else "exact",
            note=row.get("note", "")))

    if not facts:
        raise ValueError("файл не содержит ни компоновок, ни масс пассажира")
    return facts
