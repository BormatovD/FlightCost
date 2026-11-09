"""Модель 2: все строки остаются. Распределённые формулой перевозчико-годы входят суммой по парку.

ln(прямой ТОиР на блок-час, USD 2025) = тип + перевозчик + f(возраст; класс) + e·ln(сектор/2)
                                       + ρ_с·доживание·(1−доля аренды) + ρ_а·доживание·доля аренды
Наблюдения двух видов:
  * строка «перевозчик × тип × год» — где разбивка по типам настоящая;
  * сумма «перевозчик × год» — где разбивка сделана формулой (по блок-часам, кресло-милям…):
    ln(Σ затрат) = ln Σ_типов БЧ·exp(η).  Ставка типа у такого перевозчика не используется,
    его общая сумма — используется.
Отложены до восстановления по 10-K (не выброшены): метод отсрочки, двигатели вне ТОиР.
"""
import json, pathlib, sys, collections, os
import numpy as np
from scipy.optimize import least_squares
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); from common import CLASS
INDEX = sys.argv[1] if len(sys.argv) > 1 else "ppi"
BOOT = int(os.environ.get("BOOT", "100"))
P = json.load(open(HERE / "panel.json"))["rows"]; A = json.load(open(HERE / "ages.json"))["ages"]
IX = json.load(open(HERE / "index.json")); POL = json.load(open(HERE / "policy.json"))
VER = json.load(open(HERE / "mmr_verified.json")) if (HERE / "mmr_verified.json").exists() else {}
RECON = json.load(open(HERE / "recon.json")) if (HERE / "recon.json").exists() else {}
AQ = json.load(open(HERE / "alloc_q.json")); CV = json.load(open(HERE / f"curves_{INDEX}.json"))
RO = json.load(open(HERE / "runout.json")); EX = RO["exits"]; LEASE = RO["lease"]
def idx(y):
    if INDEX == "cpi": return IX["cpiu_annual"][str(y)] / IX["cpiu_annual"]["2025"]
    w = IX["wps5541_jun"].get(str(y)) or 100.0 * IX["pcu488190_jun"][str(y)] / IX["pcu488190_jun"]["2009"]
    return w / IX["wps5541_jun"]["2025"]
BASIS = {"bh": "блок-часам", "asm": "кресло-милям", "dep": "вылетам", "mi": "милям"}
# ---------- статус каждой строки
rows = []
for r in P:
    if r["year"] < 2006: continue
    a = A.get(f"{r['year']}|{r['aid']}|{r['icao']}")
    key = f"{r['aid']}|{r['year']}"
    st, why = "row", ""
    if r["direct"] <= 0: st, why = "unusable", "прямой ТОиР не подан"
    elif not a: st, why = "unusable", "нет возраста в B-43"
    elif not CLASS.get(r["icao"]): st, why = "unusable", "тип вне классов модели"
    elif not r["sector_h"]: st, why = "unusable", "нет сектора"
    # 1) учётная политика — раньше распределения: у отсрочки занижен и итог по парку, сумма тоже не годится
    if st == "row":
        for per in POL.get(r["carrier"], []):
            if per["from"] <= r["year"] <= per["to"]: st, why = "pending", per["why"] + " — ждёт восстановления по 10-K"; break
    if st == "row":
        if key in AQ: st, why = "agg", f"распределено пропорционально {BASIS[AQ[key]['basis']]}"
        elif CV["alloc"].get(key) == "total": st, why = "agg", "распределено формулой (доли и итог ровные)"
    # 2) двигатели почти ничего не стоят у молодого парка — первый капремонт через 5–8 лет; это норма.
    #    Подозрительна низкая доля только у парка старше 6 лет: там двигатели должны идти в ремонт.
    if st == "row" and a and a["age"] >= 6 and r["engine"] / r["direct"] < 0.15 and CV["alloc"].get(key) != "split" \
            and f"{r['carrier']}|{r['year']}" not in VER:
        st, why = "pending", "парк старше 6 лет, а двигатели < 15% прямых: платежи, видимо, учтены вне ТОиР — ждёт восстановления по 10-K"
    rc = RECON.get(r["carrier"], {}).get(str(r["year"]))
    if rc and st in ("row", "agg", "pending"):
        st, why = "agg", f"восстановлено по 10-K: + амортизация отложенного ТО {rc['add_kusd']/1000:.1f} млн USD за год, весь год — суммой по парку"
    e = EX.get(f"{r['aid']}|{r['icao']}")
    ro = bool(e and e["exit"] - 2 <= r["year"] <= e["exit"])
    rows.append(dict(r, status=st, why=why, age=a["age"] if a else None, n=a["n"] if a else None,
                     cost=r["direct"] / idx(r["year"]), runout=ro, leased=LEASE.get(f"{r['aid']}|{r['icao']}|{r['year']}", 0.0)))
# суммы по распределённым перевозчико-годам: только если у всех типов есть возраст (иначе сумму нечем объяснить)
grp = collections.defaultdict(list)
for x in rows:
    if x["status"] == "agg": grp[(x["aid"], x["year"])].append(x)
allrows_by = collections.defaultdict(list)
for x in rows: allrows_by[(x["aid"], x["year"])].append(x)
aggs = []
for k, xs in grp.items():
    others = [x for x in allrows_by[k] if x["status"] == "unusable" and x["direct"] > 0]
    miss = sum(x["block_h"] for x in others) / sum(x["block_h"] for x in allrows_by[k])
    if miss > 0.10:
        for x in xs: x["status"], x["why"] = "unusable", x["why"] + f"; сумму не объяснить: у {miss:.0%} блок-часов нет возраста"
        continue
    rc = RECON.get(xs[0]["carrier"], {}).get(str(xs[0]["year"]))
    if rc: xs[0]["recon_add"] = rc["add_kusd"] * 1000 / idx(xs[0]["year"])
    aggs.append(xs)
use = [x for x in rows if x["status"] == "row"]
if os.environ.get("NO_CHARTER"):
    from common import CHARTER
    use = [x for x in use if x["carrier"] not in CHARTER]; aggs = [g for g in aggs if g[0]["carrier"] not in CHARTER]
BINS = list(range(0, 26, 2)) + [26]; REF = 12
binof = lambda a: max(lo for lo in BINS if a >= lo)
def design(use, aggs):
    allx = use + [x for g in aggs for x in g]
    types = sorted({x["icao"] for x in allx}); cars = sorted({x["carrier"] for x in allx}); groups = sorted({CLASS[x["icao"]] for x in allx})
    cols = [("T", t) for t in types] + [("C", c) for c in cars[1:]] + [("S",), ("RO",), ("RL",)] + \
           [("A", g, lo) for g in groups for lo in BINS if lo != REF]
    ix = {c: i for i, c in enumerate(cols)}
    def vec(x):
        v = np.zeros(len(cols)); v[ix[("T", x["icao"])]] = 1
        if x["carrier"] != cars[0]: v[ix[("C", x["carrier"])]] = 1
        v[ix[("S",)]] = np.log(x["sector_h"] / 2.0)
        v[ix[("RO",)]] = x["runout"] * (1 - x["leased"]); v[ix[("RL",)]] = x["runout"] * x["leased"]
        lo = binof(x["age"])
        if lo != REF: v[ix[("A", CLASS[x["icao"]], lo)]] = 1
        return v
    Xr = np.array([vec(x) for x in use]) if use else np.zeros((0, len(cols)))
    yr = np.array([np.log(x["cost"] / x["block_h"]) for x in use]); wr = np.array([x["block_h"] for x in use], float)
    G = [(np.array([vec(x) for x in g]), np.array([x["block_h"] for x in g], float), np.log(sum(x["cost"] for x in g) + g[0].get("recon_add", 0.0))) for g in aggs]
    wg = np.array([g[1].sum() for g in G], float)
    W = np.concatenate([wr, wg]); W = W / W.mean()
    return cols, ix, types, cars, Xr, yr, G, np.sqrt(W[:len(wr)]), np.sqrt(W[len(wr):])
def fit(use, aggs, x0=None):
    cols, ix, types, cars, Xr, yr, G, sr, sg = design(use, aggs)
    def res(b):
        r1 = sr * (yr - Xr @ b)
        r2 = np.array([sg[j] * (lnD - np.log(np.sum(bh * np.exp(X @ b)))) for j, (X, bh, lnD) in enumerate(G)])
        return np.concatenate([r1, r2])
    def jac(b):
        J1 = -sr[:, None] * Xr
        J2 = []
        for j, (X, bh, lnD) in enumerate(G):
            e = bh * np.exp(X @ b); J2.append(-sg[j] * (e @ X) / e.sum())
        return np.vstack([J1, np.array(J2).reshape(-1, len(cols))])
    b0 = x0 if x0 is not None and len(x0) == len(cols) else np.zeros(len(cols))
    if x0 is None:
        b0[[ix[("T", t)] for t in types]] = np.log(1000)
    sol = least_squares(res, b0, jac=jac, method="trf", x_scale="jac", max_nfev=200)
    b = sol.x
    gam = {c: (b[ix[("C", c)]] if ("C", c) in ix else 0.0) for c in cars}
    allx = use + [x for g in aggs for x in g]
    ops = collections.defaultdict(set); [ops[x["icao"]].add(x["carrier"]) for x in allx]
    # уровень типа «типичного эксплуатанта»: среднее эффектов перевозчиков, летающих на типе (каждый весит одинаково)
    # чартерные участвуют в оценке (свой уровень у каждого), но «типичный эксплуатант» — регулярный перевозчик
    from common import CHARTER
    base = lambda c: c.split("#")[0]
    sched = {t: [c for c in ops[t] if base(c) not in CHARTER] or list(ops[t]) for t in types}
    lvl = {t: float(np.exp(b[ix[("T", t)]] + np.mean([gam[c] for c in sched[t]]))) for t in types}
    shape = {g: {lo: (float(np.exp(b[ix[("A", g, lo)]])) if lo != REF else 1.0) for lo in BINS} for g in sorted({CLASS[t] for t in types})}
    nobs = collections.Counter((CLASS[x["icao"]], binof(x["age"])) for x in allx)
    rr = res(b); n = len(rr)
    return dict(level=lvl, shape=shape, nobs={f"{g}|{lo}": v for (g, lo), v in nobs.items()}, e=float(b[ix[("S",)]]),
                runout_owned=float(np.exp(b[ix[("RO",)]])), runout_leased=float(np.exp(b[ix[("RL",)]])),
                sigma=float(np.sqrt(np.mean(rr ** 2))), n_rows=len(use), n_aggs=len(aggs), cost=float(sol.cost), status=sol.status,
                ops={t: sorted(v) for t, v in ops.items()}, gamma={c: float(v) for c, v in gam.items()}, beta=b, cols=cols)
F = fit(use, aggs)
# ---------- бутстрэп по перевозчикам
rng = np.random.default_rng(2026); cars = sorted({x["carrier"] for x in use} | {g[0]["carrier"] for g in aggs})
B = []
for it in range(BOOT):
    pick = rng.choice(cars, len(cars)); u2 = []; a2 = []
    for j, c in enumerate(pick):
        tag = f"{c}#{j}"
        u2 += [dict(x, carrier=tag) for x in use if x["carrier"] == c]
        a2 += [[dict(x, carrier=tag) for x in g] for g in aggs if g[0]["carrier"] == c]
    try: B.append(fit(u2, a2))
    except Exception as ex: pass
q = lambda xs, a: float(np.quantile([x for x in xs if x is not None], a)) if any(x is not None for x in xs) else None
SEC = {"региональные": 1.5, "узкофюзеляжные": 2.5, "широкофюзеляжные": 8.0}
def fill(sh, g, nobs):
    last = None; out = {}
    for lo in BINS:
        if nobs.get(f"{g}|{lo}", 0) >= 5: last = sh[lo]
        out[lo] = last
    first = next(v for v in out.values() if v is not None)
    return {lo: (v if v is not None else first) for lo, v in out.items()}
shape = {g: fill(F["shape"][g], g, F["nobs"]) for g in F["shape"]}
LIFE = {g: sum(shape[g][binof(a + 0.5)] for a in range(25)) / 25 for g in shape}
life_b = {g: [] for g in shape}
for bb in B:
    for g in shape:
        if g in bb["shape"]:
            s2 = fill(bb["shape"][g], g, F["nobs"]); life_b[g].append(sum(s2[binof(a + 0.5)] for a in range(25)) / 25)
types = {}
for t, L in F["level"].items():
    g = CLASS[t]; secf = (SEC[g] / 2.0) ** F["e"]
    xs = [x for x in rows if x["icao"] == t]
    tb = [bb["level"].get(t) for bb in B]
    # бутстрэп: тип мог выпасть вместе со своими перевозчиками — берём, где он есть
    tb = [v * (SEC[g] / 2.0) ** bb["e"] for v, bb in zip(tb, B) if v]
    ages = [x["age"] for x in xs if x["status"] in ("row", "agg") and x["age"] is not None]
    types[t] = dict(icao=t, cls=g, mature=L * secf, life=L * secf * LIFE[g], lo=q(tb, .1), hi=q(tb, .9),
                    operators=F["ops"][t], age_lo=min(ages) if ages else None, age_hi=max(ages) if ages else None,
                    young_only=bool(ages) and max(ages) < 6,
                    # уровень держится на строках самого типа; если их меньше трёх, он выведен только из сумм по парку
                    # (тип — доля в общей сумме перевозчика) и не определён надёжно
                    weak=sum(1 for x in xs if x["status"] == "row") < 3,
                    n_row=sum(1 for x in xs if x["status"] == "row"), n_agg=sum(1 for x in xs if x["status"] == "agg"),
                    n_pending=sum(1 for x in xs if x["status"] == "pending"), n_unusable=sum(1 for x in xs if x["status"] == "unusable"),
                    rows=[{k: x[k] for k in ("carrier", "year", "age", "n", "sector_h", "block_h", "status", "why", "runout", "leased")}
                          | {"rate": x["cost"] / x["block_h"]} for x in sorted(xs, key=lambda x: (x["carrier"], x["year"]))])
out = dict(index=INDEX, method=__doc__, e=F["e"], runout_owned=F["runout_owned"], runout_leased=F["runout_leased"],
           runout_ci=[[q([b["runout_owned"] for b in B], .1), q([b["runout_owned"] for b in B], .9)],
                      [q([b["runout_leased"] for b in B], .1), q([b["runout_leased"] for b in B], .9)]],
           sigma=F["sigma"], n_rows=F["n_rows"], n_aggs=F["n_aggs"], boot=len(B), shape=shape, nobs=F["nobs"], life=LIFE,
           life_ci={g: [q(v, .1), q(v, .9)] for g, v in life_b.items()},
           boot_shape={g: {lo: [q([bb["shape"].get(g, {}).get(lo) for bb in B], .1), q([bb["shape"].get(g, {}).get(lo) for bb in B], .9)] for lo in BINS} for g in shape},
           sector_ref=SEC, types=types,
           status=collections.Counter(x["status"] for x in rows), why=collections.Counter(x["why"] for x in rows if x["status"] != "row"),
           gamma=F["gamma"])
json.dump(out, open(HERE / (f"model2_{INDEX}_nocharter.json" if os.environ.get("NO_CHARTER") else f"model2_{INDEX}.json"), "w"), ensure_ascii=False, default=float)
print(f"{INDEX}: строк {F['n_rows']}, сумм по перевозчико-годам {F['n_aggs']}, σ {F['sigma']:.3f}, сектор e {F['e']:.3f}, бутстрэп {len(B)}")
print("статусы:", dict(out["status"]))
print("доживание: собств ×%.2f [%s], аренда ×%.2f [%s]" % (F["runout_owned"], out["runout_ci"][0], F["runout_leased"], out["runout_ci"][1]))
for g in shape: print(f"  {g:16} цикл {LIFE[g]:.3f} {out['life_ci'][g]} ", " ".join(f"{lo}:{v:.2f}" for lo, v in shape[g].items()))
for t in sorted(types.values(), key=lambda t: (t["cls"], -(t["n_row"] + t["n_agg"]))):
    if t["n_row"] + t["n_agg"] < 5: continue
    print(f"{t['icao']:5} строк {t['n_row']:3} в суммах {t['n_agg']:3} отлож {t['n_pending']:3}  зрелый {t['mature']:6.0f} [{(t['lo'] or 0):.0f}–{(t['hi'] or 0):.0f}] цикл {t['life']:6.0f}  эксплуатантов {len(t['operators'])}" + ("  молодой" if t["young_only"] else "") + ("  СЛАБО ОПРЕДЕЛЁН" if t["weak"] else ""))
