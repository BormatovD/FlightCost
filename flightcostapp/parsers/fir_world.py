"""Границы FIR всего мира — из данных проекта VATSpy сообщества VATSIM.

Зачем второй источник границ. Полигоны EUROCONTROL точны в Европе и
грубы вне её: на ALA–DEL прямая «проходила» через зоны Вьетнама и Омана.
На тех же полигонах стоит и проверка закрытого неба, то есть грубость
решала, существует ли пара. Файл VATSpy ключует FIR кодом ИКАО, покрывает
мир целиком и обновляется раз в цикл AIRAC.

Чьи это данные. Сообщества сети авиасимуляции, не официальные. Границы
следуют опубликованным в AIP, но ручаться за каждую не может никто;
поэтому зоны из этого файла несут пометку `community`, и сборы за
аэронавигацию вне Европы остаются оценкой. Лицензия CC BY-SA 4.0:
производный файл наследует её, в репозиторий не кладётся (решение 1),
строка атрибуции — в NOTICE.

Что берётся. Только FIR целиком — четырёхбуквенные идентификаторы.
Сектора («UAAA-A3A»), группы («UKR», «ADR») и океанические зоны
пропускаются: сектор — деление FIR для диспетчера, а не зона сбора.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..store import Fact

MIN_ZONES = 300
MUST_HAVE = ("UAAA", "VIDF", "ZWWW", "UKBV", "OPLR", "EDGG", "KZNY")
SIMPLIFY_DEG = 0.02          # ≈ 2 км; граница FIR точнее не публикуется


def _simplify(ring: list, tol: float) -> list:
    """Дуглас — Пекер без numpy: парсер не должен тянуть зависимость ради
    одного прохода раз в полгода."""
    if len(ring) <= 4:
        return ring

    def dist(p, a, b):
        (y, x), (ay, ax), (by, bx) = p, a, b
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            return ((x - ax) ** 2 + (y - ay) ** 2) ** .5
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return ((x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2) ** .5

    def rec(i, j, keep):
        if j <= i + 1:
            return
        k, best = -1, tol
        for m in range(i + 1, j):
            d = dist(ring[m], ring[i], ring[j])
            if d > best:
                k, best = m, d
        if k >= 0:
            keep.add(k); rec(i, k, keep); rec(k, j, keep)

    mid = len(ring) // 2
    keep = {0, mid, len(ring) - 1}
    rec(0, mid, keep); rec(mid, len(ring) - 1, keep)
    return [ring[i] for i in sorted(keep)]


def convert(blob: bytes, *, simplify: float = SIMPLIFY_DEG) -> tuple[dict, dict]:
    """GeoJSON VATSpy → наш файл зон. Возвращает (данные, сводка)."""
    data = json.loads(blob)
    zones, skipped, pts_in, pts_out = [], {"sector": 0, "group": 0, "oceanic": 0}, 0, 0
    for f in data.get("features", []):
        p = f.get("properties") or {}
        zid = str(p.get("id") or "")
        if "-" in zid:
            skipped["sector"] += 1; continue
        if len(zid) != 4 or not zid.isalpha():
            skipped["group"] += 1; continue
        if str(p.get("oceanic", "0")) == "1":
            skipped["oceanic"] += 1; continue
        g = f.get("geometry") or {}
        polys = g["coordinates"] if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
        rings = []
        for poly in polys:
            if not poly:
                continue
            outer = [(float(lat), float(lon)) for lon, lat in poly[0]]
            pts_in += len(outer)
            s = _simplify(outer, simplify)
            if s[0] != s[-1]:
                s.append(s[0])
            pts_out += len(s)
            rings.append([[round(a, 4), round(b, 4)] for a, b in s])
        if not rings:
            continue
        zones.append({"id": zid.upper(), "prefix": zid[:2].upper(),
                      "rings": rings,
                      "label": [float(p["label_lat"]), float(p["label_lon"])]
                      if p.get("label_lat") and p.get("label_lon") else None})
    ids = {z["id"] for z in zones}
    missing = [m for m in MUST_HAVE if m not in ids]
    if len(zones) < MIN_ZONES or missing:
        raise ValueError(f"файл не похож на границы FIR мира: зон {len(zones)} "
                         f"(нужно ≥ {MIN_ZONES}), нет {missing or '—'}")
    zones.sort(key=lambda z: z["id"])
    return ({"schema": "fca.zones/1", "source": "VATSpy data project (VATSIM)",
             "license": "CC-BY-SA-4.0", "certainty": "community", "zones": zones},
            {"zones": len(zones), "points_in": pts_in, "points_out": pts_out, **skipped})


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    out, summary = convert(blob)
    out["fetched"] = ctx.get("today", "")
    out["url"] = ctx.get("url", "")
    out["sha"] = ctx.get("sha", "")
    at = Path((ctx.get("holds") or {}).get("at") or "data/geo/zones_world.json")
    at.parent.mkdir(parents=True, exist_ok=True)
    at.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                  encoding="utf-8")
    ctx["summary"] = (f"зон {summary['zones']}, точек {summary['points_in']} → "
                      f"{summary['points_out']}; пропущено секторов {summary['sector']}, "
                      f"групп {summary['group']}, океанических {summary['oceanic']}; "
                      f"файл {at}")
    # Геометрия ложится файлом, фактов не создаёт — как у eurocontrol_fir.
    return []
