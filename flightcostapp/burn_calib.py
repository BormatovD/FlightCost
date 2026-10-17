"""Сверка модели расхода openap с опубликованной эксплуатацией (решение 225).

openap — открытая замена BADA, и по отдельным типам она ошибается заметно:
у A320neo на треть в сторону экономии, у 777 в полтора раза в обратную.
Здесь два независимых способа это измерить:

  * таблицы Aircraft Commerce — рейсовое топливо на названном секторе с
    названной загрузкой, посчитанное планировщиком полётов по данным
    производителя (`data/aircraft/burn_ref/aircraft_commerce.json`);
  * BTS Form 41, схема T-2 — топливо, выданное в крыло, рейсы и мили
    перевозчиков США за год (домен `fleet_benchmark`, если он собран).

Первый — точная задача, но один издатель. Второй — реальная эксплуатация
(с ВСУ, задержками и танкеровкой, поэтому заведомо выше модели на 5–15 %),
но средний сектор вместо распределения. Поправка заводится, только где
первый надёжен; второй её подтверждает или опровергает по ПОРЯДКУ типов:
если в Form 41 A320neo так же выбивается из семейства, как у Aircraft
Commerce, это не ошибка одного журнала.

Сама поправка — файл `data/aircraft/burn_calib/calib.json`, источник
`burn_calib` реестра, факт `aircraft/<тип>/burn_calib`: множитель к расходу
openap с основанием в примечании. Применяется только к типам, которые
считает сама openap (ярус 1); у типов по аналогу с якорем уровень и так
задан якорем.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

KG_PER_USG = 3.039            # 6,7 фунта на галлон, как у Aircraft Commerce
NM_PER_MI = 0.868976
LF_F41 = 0.84                 # загрузка для Form 41: в T-2 нет пассажиров; средняя по США
REF = Path(__file__).resolve().parents[1] / "data" / "aircraft" / "burn_ref" / "aircraft_commerce.json"


def _model(icao: str, nm: float, pax: float) -> float | None:
    from .fuel import _openap_profile
    try:
        return _openap_profile(icao, float(nm), float(pax)).trip_kg
    except Exception:                                 # noqa: BLE001
        return None


def _has_model(icao: str) -> bool:
    from .fuel import _flow
    try:
        _flow(icao)
        return True
    except Exception:                                 # noqa: BLE001
        return False


def ac_ratios(path: Path = REF) -> dict:
    """{тип: {n, ratio, min, max, issues}} — опубликовано ÷ модель."""
    from .fuel import airframe_from_openap, pax_mass
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["rows"]
    acc = defaultdict(list)
    for r in rows:
        k = r["icao"]
        kg = r.get("fuel_kg") or (r["fuel_usg"] * KG_PER_USG if r.get("fuel_usg") else None)
        if not r.get("esad_nm") or not kg or not _has_model(k):
            continue
        pax = r.get("pax")
        if not pax:
            pl = r.get("payload_kg") or (r.get("payload_lb") or 0) * 0.45359
            if not pl:
                continue
            pax = pl / pax_mass(k, airframe_from_openap(k).mtow_kg / 1000)[0]
        m = _model(k, r["esad_nm"], pax)
        if m:
            issue = (r.get("document") or "").split("No.")[-1].split()[0] if "No." in (r.get("document") or "") else "?"
            acc[k].append((kg / m, issue))
    return {k: {"n": len(v), "ratio": statistics.median(x for x, _ in v),
                "min": min(x for x, _ in v), "max": max(x for x, _ in v),
                "issues": sorted({i for _, i in v})} for k, v in acc.items()}


def f41_ratios(store, year: int | None = None) -> dict:
    """{тип: {n_carriers, departures, ratio, stage_nm}} по T-2 за год.

    Ratio — выданное топливо ÷ модель на среднем секторе перевозчика с
    загрузкой LF_F41, медиана по перевозчикам с весом по рейсам."""
    from . import bench
    data = bench._load(store)
    years = sorted({int(k[0][:4]) for k in data["t2"]})
    if not years:
        return {}
    if year is None:
        full = [y for y in years if len({k[0] for k in data["t2"] if k[0].startswith(str(y))}) == 4]
        year = (full or years)[-1]
    acc = defaultdict(lambda: defaultdict(float))
    for (yq, car, typ), v in data["t2"].items():
        if not yq.startswith(str(year)):
            continue
        desc = data["types"].get(typ, "")
        icao = bench.CODE_OVERRIDES[typ][0] if typ in bench.CODE_OVERRIDES else bench.icao_of(desc)
        if not icao:
            continue
        for f in ("departures", "air_miles", "fuel_gal", "asm"):
            acc[(car, icao)][f] += v.get(f, 0.0)
    per = defaultdict(list)
    for (car, icao), a in acc.items():
        dep, mi, gal, asm = a["departures"], a["air_miles"], a["fuel_gal"], a["asm"]
        if dep < 500 or mi <= 0 or gal <= 0 or asm <= 0 or not _has_model(icao):
            continue
        stage = mi / dep * NM_PER_MI
        seats = asm / mi
        m = _model(icao, stage, seats * LF_F41)
        if m:
            per[icao].append((gal * KG_PER_USG / dep / m, dep, stage))
    out = {}
    for icao, v in per.items():
        v.sort()
        half, run = sum(d for _, d, _ in v) / 2, 0
        for r, d, _ in v:
            run += d
            if run >= half:
                med = r
                break
        out[icao] = {"year": year, "n_carriers": len(v), "departures": sum(d for _, d, _ in v),
                     "ratio": med, "stage_nm": statistics.median(s for _, _, s in v)}
    return out


def report(store=None) -> list[str]:
    ac = ac_ratios()
    f41 = f41_ratios(store) if store is not None else {}
    base = None
    if f41.get("A320") and ac.get("A320"):
        # Порядок типов, а не уровень: уровень Form 41 выше модели из-за ВСУ,
        # задержек, танкеровки. Делим на A320 в каждом источнике.
        base = (ac["A320"]["ratio"], f41["A320"]["ratio"])
    L = [f"{'тип':6} {'AC n':>5} {'AC опубл/модель':>16} {'разброс':>11}   {'F41 перев.':>10} {'F41 выдано/модель':>18}"
         + ("   AC/A320  F41/A320" if base else "")]
    for k in sorted(set(ac) | set(f41), key=lambda t: -(ac.get(t, {}).get("ratio") or 0)):
        a, f = ac.get(k), f41.get(k)
        spread = f"{a['min']:.2f}–{a['max']:.2f}" if a else ""
        line = (f"{k:6} {a['n'] if a else '':>5} {a['ratio'] if a else float('nan'):>16.2f} "
                f"{spread:>11}   "
                f"{f['n_carriers'] if f else '':>10} {f['ratio'] if f else float('nan'):>18.2f}")
        if base:
            line += (f"   {a['ratio'] / base[0] if a else float('nan'):7.2f}"
                     f"  {f['ratio'] / base[1] if f else float('nan'):8.2f}")
        L.append(line)
    if store is not None and not f41:
        L.append("Form 41 (T-2) в хранилище нет: fca refresh --only form41 — тогда будет вторая колонка")
    return L
