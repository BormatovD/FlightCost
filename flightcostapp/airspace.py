"""Пересекаемые тарифные зоны аэронавигации.

До этого модуля сбор считался по двум государствам — вылета и прилёта, —
а всё, что между, не учитывалось вовсе. На FRA–BCN самолёт пролетает
Францию целиком, и она в счёт не попадала. Это не упрощение, а
пропущенное государство: ошибка в статье на 7% себестоимости, растущая
с дальностью.

Метод: маршрут разбивается на равные отрезки, середина каждого
относится к зоне, накопленные расстояния дают доли. Точечная выборка,
а не пересечение геометрий — потому что длину пересечения линии с
полигоном пришлось бы мерить в градусах и переводить в мили с поправкой
на широту, а счёт точек этого не требует и ошибается не больше, чем на
половину шага.

Два слоя границ (решение 162). Шейпфайл Network Manager EUROCONTROL —
точный там, где EUROCONTROL выставляет счета, и грубый вне своей зоны:
«FICTICIOUS FIR REST OF RUSSIA», «V W A REGION», «SOUTH AMERICA» — это
не границы, а заглушки его карты. Поэтому полигон EUROCONTROL главнее
только для зон, по которым есть ставка CRCO (`prefer`); для остального
мира берутся границы FIR из данных сообщества VATSIM
(`data/geo/zones_world.json`, парсер `fir_world`), с пометкой
`community`. Нет мирового файла — считается как прежде, и доля пути по
заглушкам видна в `Crossing.by_layer`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path("data/airspace/fir_zones.json")
WORLD_PATH = Path("data/geo/zones_world.json")
R_EARTH_NM = 3440.065
STEP_NM = 10.0          # шаг выборки; половина шага — предел ошибки на границе
CRCO_SOURCE = "crco_enroute_rates"


@dataclass
class Crossing:
    zones: dict[str, float] = field(default_factory=dict)   # зона -> мили
    total_nm: float = 0.0
    unassigned_nm: float = 0.0
    note: str = ""
    # Мили по слоям границ: eurocontrol | community | none. Доля
    # «community» — то, что стоит на неофициальных границах; доля «none»
    # — что не отнесено никуда.
    by_layer: dict[str, float] = field(default_factory=dict)

    def shares(self) -> dict[str, float]:
        t = self.total_nm or 1.0
        return {k: v / t for k, v in self.zones.items()}


def _gc_point(lat1, lon1, lat2, lon2, f: float):
    """Точка на дуге большого круга на доле f пути."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2))
    if d < 1e-12:
        return lat1, lon1
    a, b = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return (math.degrees(math.atan2(z, math.hypot(x, y))),
            math.degrees(math.atan2(y, x)))


@lru_cache(maxsize=4)
def _load(path: str):
    """Полигоны EUROCONTROL, подготовленные для быстрой проверки принадлежности."""
    from shapely.geometry import shape
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    geoms, meta = [], []
    for z in data["zones"]:
        g = shape(z["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        geoms.append(g)
        meta.append({"zone": z["zone"], "name": z.get("name", ""),
                     "fl_min": z.get("fl_min", 0), "fl_max": z.get("fl_max", 999)})
    return STRtree(geoms), geoms, [prep(g) for g in geoms], meta, data.get("source", "")


@lru_cache(maxsize=4)
def _load_world(path: str):
    """Полигоны FIR мира из файла парсера `fir_world` (кольца [lat, lon])."""
    from shapely.geometry import Polygon
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "fca.zones/1":
        raise ValueError(f"{path}: неизвестная схема {data.get('schema')!r}")
    geoms, meta = [], []
    for z in data["zones"]:
        for ring in z["rings"]:
            g = Polygon([(lon, lat) for lat, lon in ring])
            if not g.is_valid:
                g = g.buffer(0)
            if g.is_empty:
                continue
            geoms.append(g)
            meta.append({"zone": z["prefix"], "fir": z["id"], "area": g.area})
    return STRtree(geoms), geoms, [prep(g) for g in geoms], meta, data.get("source", "")


def billing_zones(store, as_of=None) -> set[str]:
    """Зоны, по которым есть ставка CRCO: там полигон EUROCONTROL — границы
    того, кто выставляет счёт, и он главнее данных сообщества."""
    try:
        rows = store.db.execute(
            "SELECT DISTINCT key FROM facts WHERE domain = 'enroute_rate' "
            "AND source_id = ? AND valid_to IS NULL", (CRCO_SOURCE,)).fetchall()
    except Exception:                                      # noqa: BLE001
        return set()
    return {str(r[0]).split("/")[0].upper() for r in rows}


def crossing(lat1, lon1, lat2, lon2, dist_nm: float, cruise_fl: float = 330,
             path: str | Path = DEFAULT_PATH, step_nm: float = STEP_NM,
             world_path: str | Path = WORLD_PATH,
             prefer: set[str] | None = None) -> Crossing:
    """Мили в каждой пересекаемой зоне.

    `prefer` — зоны, где полигон EUROCONTROL главнее мирового (обычно
    `billing_zones(store)`). `None` означает «неизвестно»: тогда при
    наличии мирового файла он главнее везде, а EUROCONTROL — запасной.
    """
    from shapely.geometry import Point

    p, w = str(path), str(world_path)
    have_euro, have_world = Path(p).exists(), Path(w).exists()
    if not have_euro and not have_world:
        return Crossing(note="файл зон не найден: расчёт по вылету и прилёту")
    euro = _load(p) if have_euro else None
    world = _load_world(w) if have_world else None

    n = max(2, int(dist_nm / step_nm))
    seg = dist_nm / n
    notes = [x[4] for x in (euro, world) if x]
    out = Crossing(total_nm=dist_nm, note="; ".join(notes))

    def hit_euro(pt):
        tree, _g, prepared, meta, _s = euro
        for idx in tree.query(pt):
            m = meta[idx]
            if not (m["fl_min"] <= cruise_fl <= m["fl_max"]):
                continue
            if prepared[idx].contains(pt):
                return m["zone"]
        return None

    def hit_world(pt):
        tree, _g, prepared, meta, _s = world
        best = None
        for idx in tree.query(pt):
            if prepared[idx].contains(pt):
                m = meta[idx]
                # Вложенные FIR (например, VIDF и VIUX): берётся меньший —
                # более конкретный. Префикс у них обычно общий.
                if best is None or m["area"] < best["area"]:
                    best = m
        return best["zone"] if best else None

    for i in range(n):
        f = (i + 0.5) / n
        lat, lon = _gc_point(lat1, lon1, lat2, lon2, f)
        pt = Point(lon, lat)
        ze = hit_euro(pt) if euro else None
        zw = hit_world(pt) if world else None
        if ze is not None and (prefer is not None and ze in prefer or zw is None):
            z, layer = ze, "eurocontrol"
        elif zw is not None:
            z, layer = zw, "community"
        else:
            z, layer = None, "none"
        out.by_layer[layer] = out.by_layer.get(layer, 0.0) + seg
        if z is None:                         # вне известных зон: океан, прочее
            out.unassigned_nm += seg
            continue
        out.zones[z] = out.zones.get(z, 0.0) + seg
    return out
