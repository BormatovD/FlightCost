"""OurAirports: координаты аэропортов. Детерминированный контур."""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from ..store import Fact

KINDS = {"large_airport", "medium_airport", "small_airport"}

# Код ИКАО: четыре латинские буквы. Идентификатор OurAirports бывает ИКАО
# (`EDDF`), а бывает собственным (`IN-0276`, `US-1234`) — для аэродромов,
# которым код присвоен позже заведения записи или не присвоен вовсе.
ICAO_RX = re.compile(r"^[A-Z]{4}$")


def _shaped(v) -> str:
    v = (v or "").strip().upper()
    return v if ICAO_RX.match(v) else ""


def assign_icao(rows: list[dict]) -> tuple[list[str], dict]:
    """Код ИКАО для каждой записи, без дублей по построению.

    Старшинство источников кода: `icao_code`, затем `gps_code`, затем
    `ident` — каждый, только если это четыре латинские буквы.

    Но код, который у какой-то записи является СОБСТВЕННЫМ `ident`,
    принадлежит ей и из чужого поля не берётся. Бразилия переназначает
    коды полос: закрылась одна фазенда — код получила другая, а OurAirports
    оставляет старый код в `gps_code` прежней записи. Первая версия этой
    правки взяла такие `gps_code`, и 96 кодов оказались у двух записей
    сразу: ставка одного аэродрома нашлась бы у другого, молча.

    Код, который ни за кем не закреплён, но который заявляют несколько
    записей, не получает никто — неоднозначность не разрешается угадыванием.
    Такие записи остаются с `ident`, как было до правки.
    """
    idents = [(r.get("ident") or "").strip().upper() for r in rows]
    owned = {i for i in idents if ICAO_RX.match(i)}
    first: list[str] = []
    for r, ident in zip(rows, idents):
        pick = ""
        for col in ("icao_code", "gps_code"):
            v = _shaped(r.get(col))
            if v and (v == ident or v not in owned):
                pick = v
                break
        first.append(pick or _shaped(ident) or ident)
    # Второй проход: код из чужого поля, заявленный несколькими записями.
    claims: dict[str, int] = {}
    for code, ident in zip(first, idents):
        if code != ident:
            claims[code] = claims.get(code, 0) + 1
    out, stats = [], {"from_code": 0, "ambiguous": 0}
    for code, ident in zip(first, idents):
        if code != ident and claims.get(code, 0) > 1:
            out.append(ident)
            stats["ambiguous"] += 1
        else:
            out.append(code)
            stats["from_code"] += code != ident
    return out, stats


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = blob.decode("utf-8-sig", errors="replace")
    rows = csv.DictReader(io.StringIO(text))
    # Дата прогона приходит снаружи: у справочника аэропортов нет
    # собственной даты вступления в силу, но брать её из системных часов
    # внутри парсера — значит сделать прогон невоспроизводимым.
    today = ctx.get("today") or date.today().isoformat()
    rows = [r for r in rows if r.get("type") in KINDS]
    codes, stats = assign_icao(rows)
    facts: list[Fact] = []
    for r, icao in zip(rows, codes):
        code = (r.get("iata_code") or "").strip().upper()
        # Ключ — прежний (ИАТА, иначе идентификатор OurAirports): смена
        # ключа у сорока тысяч записей — отдельное решение (103, 104), а не
        # побочный эффект этой правки. Меняется только поле ИКАО.
        key = code or (r.get("ident") or "").strip().upper()
        if not key:
            continue
        try:
            lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        facts.append(Fact(
            domain="airport", key=key, valid_from=today, unit="wgs84",
            value_text=f"{lat:.6f},{lon:.6f}|{icao}|{r.get('iso_country','')}|{r.get('name','')}",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by="parser:ourairports@3", confidence="exact",
        ))
    ctx.setdefault("summary", []).append(
        f"код ИКАО из icao_code/gps_code: {stats['from_code']}; "
        f"оставлены без кода из-за неоднозначности: {stats['ambiguous']}")
    return facts
