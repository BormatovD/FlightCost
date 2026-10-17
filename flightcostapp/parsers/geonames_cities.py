"""GeoNames cities15000: города мира от 15 тыс. жителей (решение 214).

Нужны модели потока (`traffic_model`): население вокруг аэропорта — главная
переменная гравитационной модели. Факт — город: ключ — geonameid, значение
— население, текст — «широта,долгота|страна|название». Аэропорт к городу
здесь не привязывается: зона охвата считается при чтении, по расстоянию,
потому что у Лондона пять аэропортов, а у Рейн-Майна один.

Лицензия GeoNames — CC BY 4.0: атрибуция в NOTICE и в подписи оценки.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

from ..store import Fact

# Колонки дампа GeoNames (readme.txt выгрузки): 0 geonameid, 1 name,
# 4 latitude, 5 longitude, 6 feature class, 8 country code, 14 population.
MIN_POP = 15000


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    today = ctx.get("today") or date.today().isoformat()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        text = z.read(name).decode("utf-8", errors="replace")
    out, skipped = [], 0
    for line in text.splitlines():
        c = line.split("\t")
        if len(c) < 15 or c[6] != "P":
            skipped += 1
            continue
        try:
            pop = int(c[14] or 0)
            lat, lon = float(c[4]), float(c[5])
        except ValueError:
            skipped += 1
            continue
        if pop < MIN_POP:
            continue
        out.append(Fact(
            domain="city", key=c[0], valid_from=today, value=float(pop), unit="жителей",
            value_text=f"{lat:.4f},{lon:.4f}|{c[8]}|{c[1]}",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by="geonames_cities", confidence="exact", certainty="exact",
            node=ctx.get("node")))
    if skipped:
        ctx.setdefault("summary", []).append(f"пропущено строк не-городов или битых: {skipped}")
    return out
