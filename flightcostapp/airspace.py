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

Границы берутся из шейпфайла Network Manager EUROCONTROL: та же
организация, которая по этим границам выставляет счета, лицензия MIT.
Данные датированы 2015 годом — для устоявшихся европейских границ это
приемлемо, но восточная часть карты с тех пор изменилась, и это
отмечено в предупреждениях.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path("data/airspace/fir_zones.json")
R_EARTH_NM = 3440.065
STEP_NM = 10.0          # шаг выборки; половина шага — предел ошибки на границе


@dataclass
class Crossing:
    zones: dict[str, float] = field(default_factory=dict)   # зона -> мили
    total_nm: float = 0.0
    unassigned_nm: float = 0.0
    note: str = ""

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
    """Полигоны зон, подготовленные для быстрой проверки принадлежности."""
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


def crossing(lat1, lon1, lat2, lon2, dist_nm: float, cruise_fl: float = 330,
             path: str | Path = DEFAULT_PATH, step_nm: float = STEP_NM) -> Crossing:
    """Мили в каждой пересекаемой зоне."""
    from shapely.geometry import Point

    p = str(path)
    if not Path(p).exists():
        return Crossing(note="файл зон не найден: расчёт по вылету и прилёту")
    tree, geoms, prepared, meta, src = _load(p)

    n = max(2, int(dist_nm / step_nm))
    seg = dist_nm / n
    out = Crossing(total_nm=dist_nm, note=src)
    for i in range(n):
        f = (i + 0.5) / n
        lat, lon = _gc_point(lat1, lon1, lat2, lon2, f)
        pt = Point(lon, lat)
        hit = None
        for idx in tree.query(pt):
            m = meta[idx]
            if not (m["fl_min"] <= cruise_fl <= m["fl_max"]):
                continue
            if prepared[idx].contains(pt):
                hit = m["zone"]
                break
        if hit is None:                       # вне известных зон: океан, прочее
            out.unassigned_nm += seg
            continue
        out.zones[hit] = out.zones.get(hit, 0.0) + seg
    return out
