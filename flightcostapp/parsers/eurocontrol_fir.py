"""Границы тарифных зон: шейпфайл Network Manager EUROCONTROL -> GeoJSON.

Источник — репозиторий подразделения EUROCONTROL по анализу эффективности,
лицензия MIT, правообладатель сама организация. То есть границы приходят
оттуда же, откуда счета по этим границам.

Ключом служит поле AV_ICAO_ST — двухбуквенный префикс ИКАО, тот самый,
которым уже ключуются ставки en-route. Совпадение не случайное: и зоны
взимания, и коды аэродромов строятся по одной схеме.

Геометрия не кладётся в факты. Хранилище рассчитано на скалярные
значения с интервалами действия; полигон на сотню тысяч точек там
неуместен, и проверки гейта к нему неприменимы. Файл ложится в data/
рядом с тарифами.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

OUT = Path("data/airspace/fir_zones.json")
SIMPLIFY_DEG = 0.02          # ~1 морская миля на экваторе


def parse(blob: bytes, ctx: dict) -> list:
    import shapefile
    from shapely.geometry import mapping, shape

    z = zipfile.ZipFile(io.BytesIO(blob))
    base = next(n[:-4] for n in z.namelist() if n.lower().endswith(".shp"))
    sf = shapefile.Reader(**{ext: io.BytesIO(z.read(f"{base}.{ext}"))
                             for ext in ("shp", "dbf", "shx")})
    flds = [f[0] for f in sf.fields[1:]]
    i_st, i_id = flds.index("AV_ICAO_ST"), flds.index("AV_AIRSPAC")
    i_lo, i_hi = flds.index("MIN_FLIGHT"), flds.index("MAX_FLIGHT")
    i_nm = flds.index("AV_NAME")

    zones = []
    for sr in sf.shapeRecords():
        r = sr.record
        st = str(r[i_st]).strip().upper()
        if len(st) != 2:
            continue
        g = shape(sr.shape.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        # Упрощение обязательно: полный контур весит мегабайты, а на
        # шаге выборки в десять миль лишняя точность не влияет ни на что.
        g = g.simplify(SIMPLIFY_DEG, preserve_topology=True)
        if g.is_empty:
            continue
        zones.append({
            "zone": st,
            "airspace": str(r[i_id]).strip(),
            "name": str(r[i_nm]).strip(),
            "fl_min": int(r[i_lo]), "fl_max": int(r[i_hi]),
            "geometry": mapping(g),
        })
    if len(zones) < 80:
        raise ValueError(f"разобрано {len(zones)} зон, ожидалось не менее 80")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"source": "EUROCONTROL Network Manager FirUir_NM, лицензия MIT, "
                   "данные 2015 года",
         "zones": zones}, ensure_ascii=False), encoding="utf-8")
    # Фактов не возвращаем: геометрия живёт файлом, а не значением.
    return []
