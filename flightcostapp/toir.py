"""Заготовка ТОиР по типу, возрасту и году — из статьи «ТОиР» (план toir-calc, 10.11.2026).

Данные — `data/maintenance/_toir.yaml` (research/toir/bin/export_calc.py): прямые затраты
перевозчиков США по Form 41, USD 2025 за блок-час, модель по панели 1991–2025.

Ставка на блок-час:
  возраст не задан — средняя за срок службы типа (life);
  возраст задан    — зрелая ставка (борт 12 лет) × множитель возраста класса,
                     линейно между узлами кривой, за краем — крайний узел;
  × (1 + 3 %)^(год расчёта − 2025) — индекс ТОиР, а не каталог 6–9 %;
  ÷ курс USD/EUR на дату расчёта.
Раскладка на час и цикл — доля цикловой части 39 % на опорном секторе класса
(из эластичности ставки по длине сектора −0,39): на коротком плече час дороже.

Чего здесь нет. Накладных службы ТО (в Form 41 — ещё ~50 % сверху у части
перевозчиков): ставка прямая, как в статье. Поправки на страну: это затраты США,
в Европе и Азии работа дешевле, материалы те же. Новые типы без истории в США —
по предшественнику; расчёт «снизу» по каталогу двигателя — следующий шаг.
Типов меньше чем с 8 точками в таблице нет — им остаётся параметрика.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .cycles import from_share

PATH = Path(__file__).resolve().parents[1] / "data" / "maintenance" / "_toir.yaml"
USD_PER_EUR_FALLBACK = 1.13
_CACHE: dict = {}


def doc() -> dict:
    try:
        mt = PATH.stat().st_mtime
    except OSError:
        return {}
    if _CACHE.get("mt") != mt:
        _CACHE.update(mt=mt, doc=yaml.safe_load(PATH.read_text("utf-8")) or {})
    return _CACHE["doc"]


def age_factor(shape: dict, age: float) -> float:
    pts = sorted((int(k), float(v)) for k, v in shape.items())
    if age <= pts[0][0]:
        return pts[0][1]
    for (a0, v0), (a1, v1) in zip(pts, pts[1:]):
        if age <= a1:
            return v0 + (v1 - v0) * (age - a0) / (a1 - a0)
    return pts[-1][1]


def rate(icao: str, *, age: float | None = None, year: int | None = None,
         usd_per_eur: float | None = None, d: dict | None = None) -> dict | None:
    """Ставка ТОиР типа: {"per_bh_eur", "per_fh", "per_fc", "note", …} или None."""
    d = doc() if d is None else d
    types = d.get("types") or {}
    base, via, ratio = icao.upper(), None, 1.0
    if base not in types:
        sc = (d.get("successors") or {}).get(base)
        if not sc:
            return None
        via, ratio = sc["base"], float(sc.get("ratio", 1.0))
        base = via
    t = types[base]
    cls = t["cls"]
    if age is None:
        usd, how = float(t["life_usd_bh"]), "средняя за срок службы"
    else:
        k = age_factor(d["shape"][cls], float(age))
        usd, how = float(t["mature_usd_bh"]) * k, f"борт {age:g} лет: зрелая × {k:.2f}"
    y0 = int(d.get("usd_year", 2025))
    g = (1 + float(d.get("growth", 0.03))) ** ((year or y0) - y0)
    fx = usd_per_eur or USD_PER_EUR_FALLBACK
    usd *= ratio
    eur = usd * g / fx
    sp = from_share(eur, float(d["cycle_share"]), float(d["sector_ref"][cls]), source="Form 41")
    note = (f"ТОиР по Form 41 (перевозчики США, прямые затраты): {base} {usd:,.0f} USD 2025/блок-ч, {how}"
            + (f", тип {icao} — по предшественнику {base}" + (f" × {ratio:.2f} (новое поколение против старого в "
               f"одном возрасте — медиана пар B38M/B738, B39M/B739, A21N/A321)" if ratio != 1 else "")
               + ": своей истории в США нет" if via else "")
            + (", только молодые борта — ставка зрелого продлена кривой" if t.get("young_only") else "")
            + (f"; индекс +{float(d.get('growth', 0.03)):.0%} в год × {g:.3f}" if g != 1 else "")
            + f"; ÷ {fx:.3f} USD/EUR; без накладных и без поправки на страну")
    return {"icao": icao, "base": base, "via": via, "ratio": ratio, "cls": cls, "usd_bh": usd, "growth": g, "fx": fx,
            "per_bh_eur": eur, "per_fh": sp.per_h, "per_fc": sp.per_cycle, "note": note,
            "band_usd": (t["lo"], t["hi"]), "n": t["n"], "age": age}


def apply(fe, icao: str, *, age=None, year=None, usd_per_eur=None) -> dict | None:
    """Заменить параметрическую заготовку ТОиР ставкой статьи, если тип в таблице."""
    r = rate(icao, age=age, year=year, usd_per_eur=usd_per_eur)
    if not r:
        return None
    fe.maint_eur_per_fh, fe.maint_eur_per_fc = r["per_fh"], r["per_fc"]
    if getattr(fe, "field_prov", None) is not None:
        for f in ("maint_eur_per_fh", "maint_eur_per_fc"):
            fe.field_prov[f] = "derived"
    return r
