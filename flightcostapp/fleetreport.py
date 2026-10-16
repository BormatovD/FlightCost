"""Отчёт по парку (Ф5): какой тип брать под этот объём перевозок.

Вопрос — не «N бортов каждого типа, кто больше заработает», а обратный:
**мы планируем перевезти такую долю пассажиров на этих парах — сколько
рейсов, бортов и денег это стоит на каждом типе** (решение 204). Объём —
вход, частоты и парк — выход:

1. Поток пары (опубликованный, оценка или заданный) × наша доля = объём.
2. Доля зависит от цены: `доля × (цена к рынку)^(−эластичность)`.
   Эластичность — объявленное допущение, а не измерение: открытых
   данных об отклике доли на цену по парам нет. Показывается с пометкой
   и меняется.
3. Рейсов в неделю — сколько нужно, чтобы вывезти объём при плановой
   загрузке, но не реже `min_freq` (раз в день): реже — не регулярная
   линия. Нижняя граница частоты — то, что не даёт большому борту
   выиграть «тремя рейсами в неделю»: на тонком рынке он летает
   полупустым.
4. Бортов — налёт расписания на налёт борта, вверх до целого, плюс
   резерв (доля, не меньше одного борта).
5. Экономика рейса — прямые плеча ядра (решение 38): статьи на рейс и на
   пассажира (`Leg.parts`). Ядро здесь не зовётся.

Ниже — развороты того же расчёта: как итог зависит от цены (через долю)
и от доли (кто выгоднее на тонком и на толстом рынке), и CASK/RASK по
длине плеча. Плюсы и минусы — кодами с числами, фразу собирает
страница на языке читателя. Доступность и ЛТХ из обзоров — рядом, в
расчёт не входят.
"""

from __future__ import annotations

import math
import pathlib
from datetime import date

import yaml

from .network import CONV_BASE, CONV_THICK, DIST_RATE, THICK_PAX_MONTH, WEEKS_PER_MONTH, pair_conv

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "types"
AVAIL = DATA / "availability.yaml"
SPECS = DATA / "specs.yaml"

ARTICLES = ("fuel", "maintenance", "crew", "airport_charges", "terminal", "enroute",
            "ground_handling", "other", "distribution", "ownership")

# Допущения плана по умолчанию. Каждое — вход отчёта и строка в Excel.
DEFAULTS = {
    "share": 0.10,          # наша доля нынешнего потока пары при рыночной цене
    "price": 1.00,          # наша цена к рыночной
    "elasticity": 1.5,      # −dДоля/Доля на dЦена/Цена; ДОПУЩЕНИЕ
    "lf_target": 0.80,      # плановая загрузка, под которую подбираются частоты
    "min_freq": 7,          # рейсов туда-обратно в неделю, не меньше
    "reserve": 0.10,        # резерв парка, доля от эксплуатационного, не меньше борта
    "share_cap": 0.60,      # больше этой доли рынка — уже не «отжать», а монополия
    # Средний чек к медиане дневных минимумов (решение 191). Рыночная цена
    # плеча — минимум, а не чек; переход — этот множитель, у нас и у
    # рынка один и тот же. Пусто — как у сети на витрине.
    "fare_conv": None,
}
PRICE_GRID = (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20)
SHARE_GRID = tuple(x / 100 for x in (2, 4, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 50, 60))


# ── справочные сведения ─────────────────────────────────────────────────

def _yaml(path) -> dict:
    p = pathlib.Path(path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def load_availability(path=AVAIL) -> dict:
    return _yaml(path) or {"types": {}, "reviews": {}}


def load_specs(path=SPECS) -> dict:
    return _yaml(path) or {"types": {}}


def _match(icao: str, name: str | None, types: dict):
    key = (icao or "").upper()
    hit = next(((k, t) for k, t in types.items()
                if key in {str(m).upper() for m in [k] + list(t.get("match") or [])}), None)
    if hit is None and key.startswith("USER:"):
        # Свой тип узнаётся по названию: «USER:RW214», «Ту-214 Red Wings».
        hay = f"{key} {(name or '').upper()}"
        hit = next(((k, t) for k, t in types.items()
                    if any(str(n).upper() in hay for n in t.get("names") or [])), None)
    return hit


def availability_for(icao: str, name: str | None, av: dict) -> dict | None:
    """Сведения о поставках: западный тип — по точному ключу, свой — по названию."""
    hit = _match(icao, name, av.get("types") or {})
    if not hit:
        return None
    k, t = hit
    rv = (av.get("reviews") or {}).get(t.get("review"), {})
    stale = bool(av.get("review_by") and str(date.today()) > str(av["review_by"]))
    return {"key": k, "name": t.get("name"), "full_name": t.get("full_name") or t.get("name"),
            "tagline": t.get("tagline"), "status": t.get("status"), "kind": t.get("kind"),
            "points": t.get("points") or [], "price": t.get("price"),
            "price_note": t.get("price_note"), "as_of": av.get("as_of"), "stale": stale,
            "review": t.get("review"), "review_title": rv.get("title"),
            "basis": rv.get("basis"), "sources": rv.get("sources") or []}


# ── плечи из ответа сети ────────────────────────────────────────────────

def leg_cost(leg: dict, pax: float, fuel_px: float | None = None) -> dict:
    """Статьи рейса при `pax` пассажирах, EUR, без дистрибуции и владения."""
    out = {}
    parts = leg.get("parts") or {"other": [leg["fixed_eur"], leg["per_pax_eur"]]}
    for a, (c0, c1) in parts.items():
        a = a if a in ARTICLES else "other"
        if a == "fuel" and fuel_px is not None:
            kg = float(leg.get("fuel_kg0") or 0) + float(leg.get("fuel_kg_per_pax") or 0) * pax
            out["fuel"] = out.get("fuel", 0.0) + kg * fuel_px
            continue
        out[a] = out.get(a, 0.0) + c0 + c1 * pax
    return out


class TypePlan:
    """Тип на сети: пары, которые он может летать, и его ставки."""

    def __init__(self, icao: str, res: dict):
        self.icao = icao
        self.res = res
        self.net = res.get("network") or {}
        fl = res.get("fleet") or {}
        self.lease = float(self.net.get("lease_eur_month") or fl.get("lease_eur_month") or 0.0)
        self.util = float(self.net.get("util_h_month") or fl.get("util_h_month") or 0.0)
        # Заданный в сети средний чек к минимуму; None — по потоку пары (решение 210).
        c = self.net.get("fare_conv")
        self.conv = float(c) if c not in (None, "") else None
        self.rates = {"maint_fh": self.net.get("maint_fh", fl.get("maint_fh")),
                      "maint_fc": self.net.get("maint_fc", fl.get("maint_fc")),
                      "crew_fh": fl.get("crew_fh"), "crew_fc": fl.get("crew_fc")}
        self.prov = {"lease": self.net.get("lease_prov") or fl.get("lease_prov"),
                     "util": self.net.get("util_prov") or fl.get("util_prov"),
                     "maint": self.net.get("maint_prov") or fl.get("maint_prov"),
                     "crew": fl.get("crew_prov")}
        self.pairs = []          # пары, которые тип летает: с правом, дальностью и ценой
        self.cut = {}            # не летает: статус → сколько
        for p in res.get("pairs") or []:
            key = f"{p['a']}-{p['b']}"
            legs = p.get("legs") or []
            if p.get("status") != "ok":
                self.cut[p.get("status") or "?"] = self.cut.get(p.get("status") or "?", 0) + 1
                continue
            if not legs or not all(l.get("fare_eur") for l in legs):
                self.cut["no_fare"] = self.cut.get("no_fare", 0) + 1
                continue
            self.pairs.append({"key": key, "dist": float(p.get("dist_km") or 0), "legs": legs,
                               "market": p.get("market_pax_month"),
                               "market_src": p.get("market_src") or ""})
        self.seats = next((int(l["seats"]) for p in self.pairs for l in p["legs"]
                           if l.get("seats")), None)
        self.has_parts = all(l.get("parts") for p in self.pairs for l in p["legs"])

    def plan(self, a: dict, *, volume: dict | None = None, fuel_px=None) -> dict:
        """План при допущениях `a`. `volume` — {пара: пасс./мес} вместо доли."""
        share = min(a["share"] * a["price"] ** (-a["elasticity"]), a["share_cap"])
        conv = a.get("fare_conv") if a.get("fare_conv") is not None else self.conv
        cost = {x: 0.0 for x in ARTICLES}
        rows, skipped = [], []
        rev = pax_m = seats_m = ask = hours = flights = fuel_kg = 0.0
        for p in self.pairs:
            V = (volume or {}).get(p["key"])
            if V is None:
                if not p["market"]:
                    skipped.append(p["key"])
                    continue
                V = share * float(p["market"])
            legs = p["legs"]
            D = V / len(legs)                          # спрос на направление в месяц
            need = max(D / (WEEKS_PER_MONTH * min(a["lf_target"] * l["seats"], l["max_pax"]))
                       for l in legs)
            f_need = math.ceil(need - 1e-9)
            f = max(int(a["min_freq"]), f_need)
            m = f * WEEKS_PER_MONTH
            cp = pair_conv(p["market"], conv)
            prow = {"key": p["key"], "dist": p["dist"], "volume": V, "freq": f, "conv": cp,
                    "freq_need": f_need, "min_binds": f > f_need, "market": p["market"],
                    "market_src": p["market_src"], "legs": []}
            for l in legs:
                pax = min(D / m, float(l["max_pax"]))
                c = leg_cost(l, pax, fuel_px)
                r = pax * float(l["fare_eur"]) * a["price"] * cp
                for x, v in c.items():
                    cost[x] += v * m
                cost["distribution"] += r * DIST_RATE * m
                rev += r * m
                pax_m += pax * m
                seats_m += l["seats"] * m
                ask += l["seats"] * p["dist"] * m
                hours += float(l["block_h"]) * m
                flights += m
                fuel_kg += (float(l.get("fuel_kg0") or 0) + float(l.get("fuel_kg_per_pax") or 0) * pax) * m
                # Дальность: на этом плече борт поднимает меньше плановой
                # загрузки — рейсы подобраны по этому пределу, а не по ней.
                cap = float(l["max_pax"]) / l["seats"]
                prow["legs"].append({"o": l["origin"], "d": l["destination"], "pax": pax,
                                     "lf": pax / l["seats"], "block_h": l["block_h"],
                                     "cap_lf": cap, "range_limited": cap < a["lf_target"] - 1e-9})
            prow["lf"] = sum(x["lf"] for x in prow["legs"]) / len(prow["legs"])
            lim = [x["cap_lf"] for x in prow["legs"] if x["range_limited"]]
            prow["range_cap"] = min(lim) if lim else None
            rows.append(prow)
        n_op = math.ceil(hours / self.util - 1e-9) if self.util and hours else 0
        spare = max(1, math.ceil(n_op * a["reserve"] - 1e-9)) if (a["reserve"] > 0 and n_op) else 0
        n = n_op + spare
        cost["ownership"] = n * self.lease
        total = sum(cost.values())
        return {"share": share, "conv": conv, "pairs": rows, "skipped": skipped, "revenue": rev, "cost": cost,
                "cost_total": total, "result": rev - total, "pax": pax_m, "seats": seats_m,
                "ask": ask, "hours": hours, "flights": flights, "fuel_kg": fuel_kg,
                "n_op": n_op, "spare": spare, "fleet": n,
                "util_used": hours / n_op if n_op else None,
                "lf": pax_m / seats_m if seats_m else None,
                "cask_ct": total / ask * 100 if ask else None,
                "rask_ct": rev / ask * 100 if ask else None,
                "cost_per_pax": total / pax_m if pax_m else None,
                "rev_per_pax": rev / pax_m if pax_m else None,
                "fuel_share": cost["fuel"] / total if total else None,
                "kg_per_seat_100km": fuel_kg / ask * 100 if ask else None,
                "freq_week": sum(r["freq"] for r in rows)}

    def leg_curve(self, a: dict) -> list:
        """CASK и RASK каждого плеча при плановой загрузке, по длине плеча.

        Владение — через налёт: ставка ÷ налёт × блок, как у борта, который
        летает весь месяц. Это и есть «CASK на длине плеча»."""
        out = []
        for p in self.pairs:
            for l in p["legs"]:
                pax = min(a["lf_target"] * l["seats"], float(l["max_pax"]))
                c = sum(leg_cost(l, pax).values())
                r = pax * float(l["fare_eur"]) * a["price"] * pair_conv(
                    p["market"], a.get("fare_conv") if a.get("fare_conv") is not None else self.conv)
                own = self.lease / self.util * float(l["block_h"]) if self.util else 0.0
                sk = l["seats"] * p["dist"]
                out.append({"o": l["origin"], "d": l["destination"], "dist": p["dist"],
                            "cask_ct": (c + r * DIST_RATE + own) / sk * 100 if sk else None,
                            "rask_ct": r / sk * 100 if sk else None,
                            "full": pax >= l["max_pax"] and pax < a["lf_target"] * l["seats"]})
        return sorted(out, key=lambda x: x["dist"])


# ── сборка отчёта ───────────────────────────────────────────────────────

def assumptions(q: dict | None = None) -> dict:
    """Допущения плана из запроса: пусто — по умолчанию."""
    a = dict(DEFAULTS)
    for k in a:
        v = (q or {}).get(k)
        if k == "fare_conv" and v in (None, ""):
            continue
        if v not in (None, ""):
            try:
                a[k] = float(v)
            except (TypeError, ValueError):
                pass
    a["min_freq"] = int(round(a["min_freq"]))
    for k in ("share", "lf_target", "reserve", "share_cap"):
        if a[k] > 1.5:                 # пришло в процентах
            a[k] /= 100
    return a


def build(results: dict, *, assume: dict | None = None, chosen: str = "",
          names: dict | None = None, geom: dict | None = None,
          availability: dict | None = None, specs: dict | None = None,
          context: dict | None = None) -> dict:
    """`results` — {тип: ответ `network` витрины}. Отчёт словарём."""
    a = assumptions(assume)
    names, geom = names or {}, geom or {}
    av = load_availability() if availability is None else availability
    sp = load_specs() if specs is None else specs
    plans: dict[str, TypePlan] = {}
    rows = []
    for icao, res in results.items():
        name = names.get(icao) or icao
        avl = availability_for(icao, name, av)
        hit = _match(icao, name, av.get("types") or {})
        row = {"icao": icao, "name": name, "own_rates": icao == chosen, "availability": avl,
               "geom": geom.get(icao),
               "specs": (sp.get("types") or {}).get(hit[0]) if hit else None}
        if not res or not res.get("network"):
            row.update(status="failed", why=(res or {}).get("error") or "сеть не посчитана")
        else:
            plans[icao] = TypePlan(icao, res)
            row["status"] = "ok"
        rows.append(row)
    ok = [r for r in rows if r["status"] == "ok"]
    if not ok:
        return {"error": "ни один тип не посчитан", "types": rows, "assume": a}
    if a.get("fare_conv") is None:
        a["fare_conv"] = plans[ok[0]["icao"]].conv          # None — по потоку пары

    for r in ok:
        tp = plans[r["icao"]]
        pl = tp.plan(a)
        r.update(plan=pl, seats=tp.seats, lease_eur_month=tp.lease, util_h_month=tp.util,
                 rates=tp.rates, prov=tp.prov, cut=tp.cut, parts_ok=tp.has_parts,
                 pairs_ok=len(tp.pairs), curve=tp.leg_curve(a))
        if pl["pax"] == 0:
            r.update(status="failed",
                     why="нет потока ни на одной паре, которую тип может летать — задайте "
                         "поток на вкладке «Рынок»")
    ok = [r for r in ok if r["status"] == "ok"]
    if not ok:
        return {"error": rows[0].get("why") or "нет потока", "types": rows, "assume": a}

    # Сравнимость: все типы должны возить одно и то же. Пара, которую
    # летает не каждый тип, в сравнении нечестна — она называется.
    common = set.intersection(*({p["key"] for p in r["plan"]["pairs"]} for r in ok))
    partial = sorted({p["key"] for r in ok for p in r["plan"]["pairs"]} - common)

    by = sorted(ok, key=lambda r: -r["plan"]["result"])
    for i, r in enumerate(by):
        r["rank"] = i + 1
    leader = by[0]

    # Цена → доля → объём → парк и итог: таблица по сетке цен.
    price_sweep = []
    for k in PRICE_GRID:
        b = dict(a, price=k)
        row = {"price": k, "share": min(a["share"] * k ** -a["elasticity"], a["share_cap"]),
               "types": {}}
        for r in ok:
            pl = plans[r["icao"]].plan(b)
            row["types"][r["icao"]] = {"result": pl["result"], "fleet": pl["fleet"],
                                       "pax": pl["pax"], "lf": pl["lf"]}
        price_sweep.append(row)
    for r in ok:
        best = max(price_sweep, key=lambda x: x["types"][r["icao"]]["result"])
        r["best_price"] = best["price"]

    # Доля → кто выгоднее: тонкий рынок любит маленький борт (нижняя
    # граница частоты), толстый — большой.
    share_sweep = []
    for s in SHARE_GRID:
        b = dict(a, share=s, price=1.0)
        row = {"share": s, "types": {}}
        for r in ok:
            pl = plans[r["icao"]].plan(b)
            row["types"][r["icao"]] = {"result": pl["result"], "fleet": pl["fleet"],
                                       "cost_per_pax": pl["cost_per_pax"]}
        row["leader"] = max(row["types"], key=lambda t: row["types"][t]["result"])
        share_sweep.append(row)
    bands, cur = [], None
    for row in share_sweep:
        if cur is None or cur["type"] != row["leader"]:
            cur = {"type": row["leader"], "from": row["share"], "to": row["share"]}
            bands.append(cur)
        else:
            cur["to"] = row["share"]

    for r in ok:
        r["pros"], r["cons"] = _pros_cons(r, ok, a)

    av_of = av.get("as_of")
    ctx = dict(context or {})
    return {
        "as_of": ctx.get("as_of") or str(date.today()), "context": ctx, "assume": a,
        "leader": leader["icao"],
        "leader_margin": (leader["plan"]["result"] - by[1]["plan"]["result"]) if len(by) > 1 else None,
        "fewest_aircraft": min(ok, key=lambda r: (r["plan"]["fleet"], -r["plan"]["result"]))["icao"],
        "cheapest_pax": min(ok, key=lambda r: r["plan"]["cost_per_pax"] or 1e18)["icao"],
        "price_sweep": price_sweep, "share_sweep": share_sweep, "share_bands": bands,
        "common_pairs": sorted(common), "partial_pairs": partial,
        "types": rows, "availability_as_of": av_of, "specs_as_of": sp.get("as_of"),
        "notes": _notes(ok, a, partial),
    }


def _pros_cons(r: dict, ok: list, a: dict) -> tuple[list, list]:
    """Плюсы и минусы — кодами с числами, только из плана."""
    pros, cons = [], []
    pl = r["plan"]
    many = len(ok) > 1

    def ext(get, low=True):
        vals = [(get(x), x) for x in ok if get(x) is not None]
        if len(vals) < 2:
            return None
        return (min if low else max)(vals, key=lambda v: v[0])[1]

    if many:
        others = [x for x in ok if x is not r]
        best_other = max(x["plan"]["result"] for x in others)
        if r["rank"] == 1:
            pros.append({"code": "best_result", "v": pl["result"], "gap": pl["result"] - best_other})
        elif r["rank"] == len(ok):
            cons.append({"code": "worst_result", "gap": best_other - pl["result"]})
        if ext(lambda x: x["plan"]["cost_per_pax"]) is r:
            pros.append({"code": "cheapest_pax", "v": pl["cost_per_pax"]})
        elif ext(lambda x: x["plan"]["cost_per_pax"], low=False) is r:
            cons.append({"code": "dearest_pax", "v": pl["cost_per_pax"]})
        if ext(lambda x: x["plan"]["cask_ct"]) is r:
            pros.append({"code": "lowest_cask", "v": pl["cask_ct"]})
        fl = [x["plan"]["fleet"] for x in ok]
        if pl["fleet"] == min(fl) and len(set(fl)) > 1:
            pros.append({"code": "fewest_aircraft", "v": pl["fleet"]})
        elif pl["fleet"] == max(fl) and len(set(fl)) > 1:
            cons.append({"code": "most_aircraft", "v": pl["fleet"]})
        if ext(lambda x: x["plan"]["kg_per_seat_100km"]) is r:
            pros.append({"code": "fuel_lean", "v": pl["kg_per_seat_100km"]})
        elif ext(lambda x: x["plan"]["kg_per_seat_100km"], low=False) is r:
            cons.append({"code": "fuel_heavy", "v": pl["kg_per_seat_100km"]})
    binds = [p for p in pl["pairs"] if p["min_binds"]]
    if binds:
        cons.append({"code": "min_freq_binds", "n": len(binds), "of": len(pl["pairs"]),
                     "lf": min(p["lf"] for p in binds), "freq": a["min_freq"]})
    if pl["util_used"] and r["util_h_month"] and pl["util_used"] < 0.85 * r["util_h_month"]:
        cons.append({"code": "idle_hours", "v": pl["util_used"], "max": r["util_h_month"]})
    rl = [p for p in pl["pairs"] if p.get("range_cap") is not None]
    if rl:
        cons.append({"code": "range_limited", "n": len(rl), "of": len(pl["pairs"]),
                     "cap": min(p["range_cap"] for p in rl),
                     "pairs": [p["key"] for p in sorted(rl, key=lambda p: p["range_cap"])][:4]})
    if (r.get("cut") or {}).get("range"):
        cons.append({"code": "range_cut", "n": r["cut"]["range"]})
    dflt = [k for k, v in (r.get("prov") or {}).items() if v == "default"]
    if dflt:
        cons.append({"code": "rates_default", "fields": dflt})
    av = r.get("availability")
    if av:
        (pros if av.get("kind") == "production" else cons).append(
            {"code": "avail_" + (av.get("kind") or "unknown"), "status": av.get("status")})
    return pros, cons


def _notes(ok: list, a: dict, partial: list) -> list:
    out = [{"code": "elasticity", "v": a["elasticity"]}]
    if a.get("fare_conv") is not None and abs(a["fare_conv"] - 1.0) < 1e-9:
        out.append({"code": "conv_one"})
    if partial:
        out.append({"code": "partial_pairs", "pairs": partial})
    sk = sorted({k for r in ok for k in r["plan"]["skipped"]})
    if sk:
        out.append({"code": "no_market", "pairs": sk})
    est = sorted({p["key"] for r in ok for p in r["plan"]["pairs"]
                  if (p["market_src"] or "").startswith("оценка")})
    if est:
        out.append({"code": "market_estimated", "pairs": est})
    if any(not r["parts_ok"] for r in ok):
        out.append({"code": "no_parts", "types": [r["icao"] for r in ok if not r["parts_ok"]]})
    if any(r["plan"]["share"] >= a["share_cap"] - 1e-9 for r in ok):
        out.append({"code": "share_cap", "v": a["share_cap"]})
    return out
