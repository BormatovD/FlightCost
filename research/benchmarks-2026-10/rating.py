"""Рейтинг эффективности авиакомпаний FlightCostApp — индекс из четырёх опор.

Данные: out/b2.json (вне Северной Америки), out/b3.json (Северная Америка), out/b4.json (Form 41 T-2 2025,
налёт основных рейсов США), out/b5.json (группа «Аэрофлот», Databook), out/b6.json (средние курсы 2025),
data/benchmarks/FR-2025.yaml и S7-2025.yaml (полосы бенчмарков калькулятора).

Опоры (каждая метрика — процентиль внутри выборки, 100 — лучший):
1. Затраты — CASK без топлива, евроценты, приведённый к единой длине: × (L / L_ref)^k, L — средний путь
   пассажира (RPK ÷ пассажиры), L_ref — медиана выборки, k = 0,5 (MIT ADP, McKinsey); чувствительность — k = 1/3.
2. Отдача парка — блок-часы на самолёт в сутки.
3. Коммерция — загрузка (RPK ÷ ASK) и операционная маржа ((выручка − расходы) ÷ выручка).
4. Топливо — граммы топлива на пассажиро-км.
Индекс — среднее доступных опор; в рейтинг попадают перевозчики с тремя и более опорами.

    python3 research/benchmarks-2026-10/rating.py      → out/rating.json
"""
from __future__ import annotations

import json
import pathlib
import statistics

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
FX = J("out/b6.json")["eur_per"]
GAL_T = 3.785 * 0.8 / 1000          # тонн в галлоне США (плотность 0,8 кг/л)
BBL_T = 158.987 * 0.8 / 1000        # тонн в баррель
GJ_T = 1 / 43.15
CO2_T = 3.16                        # т CO₂ на тонну керосина                    # тонн на ГДж (низшая теплота сгорания керосина 43,15 МДж/кг)


def val(v, k):
    x = v.get(k)
    if isinstance(x, dict):
        return x.get("value"), x.get("ids") or [], x.get("unit")
    return x, [], None


def tonnes(q, unit):
    if q is None:
        return None
    u = (unit or "t").lower()
    return q * {"t": 1, "us gal": GAL_T, "gal": GAL_T, "l": 0.8 / 1000, "bbl": BBL_T}.get(u, 1)


def carriers():
    out = {}
    for f in ("out/b2.json", "out/b3.json", "out/b5.json"):
        for c in J(f)["carriers"]:
            out[c["code"]] = c                                  # b5 (Databook) заменяет SU из b2
    f41 = {x["code"]: x for x in J("out/b4.json")["form41_t2_2025"]}
    return out, f41


def yaml_carrier(code):
    d = yaml.safe_load((ROOT / "data" / "benchmarks" / f"{code}-2025.yaml").read_text(encoding="utf-8"))
    v = {k: x.get("value") for k, x in d["values"].items()}
    return d, v


EXCLUDE = {"NK": "два банкротства в 2025 году, год разбит на два отчётных периода",
           "WS": "нет открытой финансовой отчётности (только вторичные источники)"}
FUEL_ESTIMATE = {"W6": "объём топлива — оценка 2,2 т на блок-час, не из отчёта"}
UTIL_REPORTED = {"U2": "U2", "DY": "NO"}
SOFT_UTIL = {"CM": "средний парк — оценка", "AD": "средний парк — оценка, без Cessna и грузовых", "BT": "средний парк — оценка", "FR": "лётные часы, FY2025", "G3": "на эксплуатируемый парк", "6E": "средний парк — оценка; только регулярные рейсы", "BT": "свои рейсы без сдачи в ACMI", "PC": "чтение отчёта не подтверждено", "Y4": "средний парк — полусумма; треть парка стоит (GTF)",
             "DL": "Form 41, только основные рейсы", "AA": "Form 41, только основные рейсы",
             "UA": "Form 41, только основные рейсы", "WN": "Form 41", "AS": "Form 41, только основные рейсы",
             "B6": "Form 41", "F9": "Form 41", "G4": "Form 41", "SY": "Form 41", "U2": "как опубликовано",
             "DY": "как опубликовано", "SU": "налёт часов ÷ парк на балансе"}


def metrics():
    cs, f41 = carriers()
    rows = []
    for code, c in cs.items():
        if code in EXCLUDE:
            rows.append({"code": code, "name": c["name"], "excluded": EXCLUDE[code]})
            continue
        v = c["values"]
        g = lambda k: val(v, k)[0]  # noqa: E731
        cur = c.get("currency") or "EUR"
        rate = FX.get(cur)
        r = {"code": code, "name": c["name"], "region": c.get("region"), "model": c.get("model"),
             "period": c.get("period"), "currency": cur, "notes": c.get("notes") or "", "ids": {}}
        for k in ("revenue", "opex", "fuel_cost", "ask_km", "rpk_km", "pax", "fuel_volume", "block_hours", "fleet_avg"):
            r["ids"][k] = val(v, k)[1]
        rev, opex, fuel, ask, rpk, pax = (g(k) for k in ("revenue", "opex", "fuel_cost", "ask_km", "rpk_km", "pax"))
        if code == "G4" and g("opex_airline"):
            opex = g("opex_airline")
        exf = None
        if code == "6E" and g("opex_ex_fuel_reported"):                 # без курсовой переоценки лизинга
            exf = g("opex_ex_fuel_reported")
            opex = exf + (fuel or 0)
        if exf is None and opex and fuel:
            exf = opex - fuel
        fv, _, unit = val(v, "fuel_volume")
        ft = None if code in FUEL_ESTIMATE else tonnes(fv, unit)
        bh, fleet = g("block_hours"), g("fleet_avg")
        if isinstance(fleet, dict):
            fleet = None
        util = bh / fleet / 365 if bh and fleet else None
        if code in UTIL_REPORTED:                                   # опубликованный налёт важнее расчёта
            util = yaml_carrier(UTIL_REPORTED[code])[1]["utilisation_bh_day"]
        if code in f41:
            util = f41[code]["util"]
            r["ids"]["util"] = f41[code]["ids"]
        r.update(rev=rev, opex=opex, exf=exf, fuel=fuel, ask=ask, rpk=rpk, pax=pax, fuel_t=ft, util=util)
        rows.append(r)
    # Ryanair и S7 — из полос бенчмарков калькулятора (у b2 по Ryanair нет ASK за FY2026)
    for code in ("FR", "S7"):
        d, v = yaml_carrier(code)
        r = next((x for x in rows if x["code"] == code), None)
        if r is None:
            r = {"code": code, "ids": {}}
            rows.append(r)
        cur = "EUR" if code == "FR" else "RUB"
        r.update(name=d["name"], region="Europe" if code == "FR" else "Russia",
                 model="ULCC" if code == "FR" else "hybrid", currency=cur,
                 period="FY2025 (апрель 2024 — март 2025)" if code == "FR" else "2025",
                 rev=v.get("revenue_eur"), opex=v.get("opex_eur"), fuel=v.get("fuel_cost_eur"),
                 ask=v.get("ask_km"), rpk=v.get("rpk_km"), pax=v.get("pax"),
                 fuel_t=(v["fuel_gj"] * GJ_T) if v.get("fuel_gj") else None,
                 util=9.57 if code == "FR" else None, source_url=d.get("source_url"),
                 notes=("ASK и RPK — кресла × средний сектор из глоссария" if code == "FR"
                        else "РСБУ юрлица «Сибирь»; операционные показатели — отчёт об устойчивом развитии"))
        r["exf"] = (r["opex"] - r["fuel"]) if r.get("opex") and r.get("fuel") else None
    # дозаполнение (out/b7.json): топливо или интенсивность CO₂ и опубликованный налёт
    B7 = {c["code"]: c for c in J("out/b7.json")["carriers"]}
    for r in rows:
        b = B7.get(r["code"])
        if not b or r.get("excluded"):
            continue
        f = b.get("fuel")
        if f and r.get("fuel_t") is None:
            if f["unit"] == "gCO2_per_RPK":
                r["g_rpk_direct"] = f["value"] / CO2_T            # г топлива на RPK
            else:
                r["fuel_t"] = tonnes(f["value"], f["unit"])
            r["ids"]["fuel_b7"] = f.get("ids") or []
            r["fuel_note"] = f.get("scope", "")
        u = b.get("util")
        if u and u.get("value_bh_day") and r.get("util") is None:
            r["util"] = u["value_bh_day"]
            r["ids"]["util"] = u.get("ids") or []
        if r["code"] == "BT":                     # свои рейсы без сдачи в ACMI — как остальные показатели BT (b7-038)
            r["util"], r["ids"]["util"] = 7.67, ["b7-038"]
    for r in rows:
        if r.get("excluded"):
            continue
        rate = FX.get(r["currency"], 1)
        e = lambda x: x / rate if x is not None else None  # noqa: E731
        r["L"] = r["rpk"] / r["pax"] if r.get("rpk") and r.get("pax") else None
        r["casx"] = e(r["exf"]) / r["ask"] * 100 if r.get("exf") and r.get("ask") else None   # евроценты
        r["cask"] = e(r["opex"]) / r["ask"] * 100 if r.get("opex") and r.get("ask") else None
        r["rask"] = e(r["rev"]) / r["ask"] * 100 if r.get("rev") and r.get("ask") else None
        r["lf"] = r["rpk"] / r["ask"] if r.get("rpk") and r.get("ask") else None
        if r["code"] == "SY":
            r["lf"] = None                                    # RPK — только регулярные рейсы, ASK — все
        r["margin"] = (r["rev"] - r["opex"]) / r["rev"] if r.get("rev") and r.get("opex") else None
        r["g_rpk"] = (r["fuel_t"] * 1e6 / r["rpk"] if r.get("fuel_t") and r.get("rpk")
                      else r.get("g_rpk_direct"))
    return [r for r in rows]


def pct(vals, x, higher_better):
    """Процентиль 0–100 (100 — лучший) по рангу среди доступных значений."""
    s = sorted(vals)
    if len(s) < 2:
        return None
    below = sum(1 for v in s if (v < x if higher_better else v > x))
    eq = sum(1 for v in s if v == x) - 1
    return round((below + eq / 2) / (len(s) - 1) * 100, 1)


def rate(rows, k=0.5):
    act = [r for r in rows if not r.get("excluded")]
    Lref = statistics.median([r["L"] for r in act if r.get("L")])
    for r in act:
        r["casx_adj"] = r["casx"] * (r["L"] / Lref) ** k if r.get("casx") and r.get("L") else None
    M = {"casx_adj": False, "util": True, "lf": True, "margin": True, "g_rpk": False}
    P = {m: [r[m] for r in act if r.get(m) is not None] for m in M}
    for r in act:
        p = {m: (pct(P[m], r[m], hb) if r.get(m) is not None else None) for m, hb in M.items()}
        com = [x for x in (p["lf"], p["margin"]) if x is not None]
        pil = {"cost": p["casx_adj"], "asset": p["util"], "commercial": statistics.mean(com) if com else None,
               "fuel": p["g_rpk"]}
        have = [x for x in pil.values() if x is not None]
        r["pct"], r["pillars"] = p, pil
        r["n_pillars"] = len(have)
        r["index"] = round(statistics.mean(have), 1) if len(have) >= 3 else None
    ranked = sorted([r for r in act if r["index"] is not None], key=lambda r: -r["index"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return Lref, ranked


def main():
    rows = metrics()
    Lref, ranked = rate(rows, 0.5)
    base = {r["code"]: (r["rank"], r["index"]) for r in ranked}
    rows3 = metrics()
    _, ranked3 = rate(rows3, 1 / 3)
    alt = {r["code"]: r["rank"] for r in ranked3}
    for r in rows:
        if r["code"] in alt:
            r["rank_k13"] = alt[r["code"]]
    keep = ("code", "name", "region", "model", "period", "currency", "notes", "ids", "excluded", "L", "casx", "casx_adj",
            "cask", "rask", "lf", "margin", "util", "g_rpk", "pct", "pillars", "n_pillars", "index", "rank", "rank_k13",
            "source_url")
    out = {"L_ref_km": Lref, "k": 0.5, "fx_eur_per": FX,
           "carriers": sorted([{k: r.get(k) for k in keep if k in r} for r in rows],
                              key=lambda r: (r.get("rank") or 999, r["code"]))}
    (HERE / "out" / "rating.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in out["carriers"]:
        f = lambda x, d=1: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
        print(f"{str(r.get('rank') or '-'):>3} {r['code']:3} {f(r.get('index'))} | casx {f(r.get('casx'),2)} adj "
              f"{f(r.get('casx_adj'),2)} L {f(r.get('L'),0)} | util {f(r.get('util'))} | lf {f(r.get('lf'),3)} "
              f"m {f(r.get('margin'),3)} | g/rpk {f(r.get('g_rpk'))} | k1/3 {r.get('rank_k13')} {r.get('excluded') or ''}")
    print("L_ref", round(Lref))


if __name__ == "__main__":
    main()
