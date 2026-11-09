"""Доживание парка: строки за 3 года до ухода типа от перевозчика. Сначала измеряем эффект, потом решаем."""
import csv, json, pathlib, sys, collections, numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); from common import CLASS, CHARTER
exec(open(HERE / "ages.py").read().split("ages = defaultdict(list)")[0])   # icao(), from_model()
fleet = collections.defaultdict(lambda: collections.Counter())   # (aid, icao) -> year -> n
lease = collections.defaultdict(lambda: collections.Counter())   # (aid, icao, year) -> статус
tails = collections.defaultdict(set)                              # (aid, icao, year) -> хвосты
where = collections.defaultdict(dict)                             # tail -> year -> aid
for r in csv.DictReader(open(RAW / "b43.csv", encoding="utf-8-sig")):
    if r["OPERATING_STATUS"].strip().upper() != "Y": continue
    try: y, my = int(r["YEAR"]), int(float(r["MANUFACTURE_YEAR"]))
    except ValueError: continue
    code = r["AIRCRAFT_TYPE"].strip(); code = (code[:3] if len(code) == 4 else code).lstrip("0")
    ic = (icao(code) if code else None) or from_model(r["MODEL"], my, r["MANUFACTURER"])
    if not ic: continue
    k = (r["AIRLINE_ID"], ic); fleet[k][y] += 1
    lease[(r["AIRLINE_ID"], ic, y)][r["AIRCRAFT_STATUS"].strip().upper()] += 1
    t = r["TAIL_NUMBER"].strip().upper()
    if t: tails[(r["AIRLINE_ID"], ic, y)].add(t); where[t][y] = r["AIRLINE_ID"]
# Перевозчик, который сам перестал отчитываться (слияние: Continental → United, Northwest → Delta, US Airways → American),
# не «доживает» тип — парк просто переходит под другой код. Такие уходы не считаются.
last_rep = collections.Counter()
for (aid, ic), ser in fleet.items(): last_rep[aid] = max(last_rep[aid], max(ser))
exits = {}; merged = 0
for k, ser in fleet.items():
    yrs = sorted(y for y, n in ser.items() if n > 0)
    E = yrs[-1]
    if E >= 2025 or max(ser.values()) < 5: continue
    if last_rep[k[0]] <= E: merged += 1; continue
    gone = set().union(*(tails[(k[0], k[1], y)] for y in range(E - 2, E + 1)))
    later_us = sum(1 for t in gone if any(yy > E and a != k[0] for yy, a in where[t].items()))
    exits[k] = dict(exit=E, peak=max(ser.values()), tails=len(gone), later_other_us=later_us)
pan = json.load(open(HERE / "panel.json"))["rows"]
aid_of = {}
for r in pan: aid_of[(r["carrier"], r["year"])] = r["aid"]
C = json.load(open(HERE / "curves_ppi_all.json"))   # без исключения доживания — иначе нечего мерить
pts = [p for t in C["types"].values() for p in t["points"] if p["direct"] > 0 and p["carrier"] not in CHARTER and p["sector"] and CLASS.get(p["icao"])]
for p in pts:
    aid = aid_of.get((p["carrier"], p["year"])); e = exits.get((aid, p["icao"]))
    p["runout"] = bool(e and e["exit"] - 2 <= p["year"] <= e["exit"])
    L = lease.get((aid, p["icao"], p["year"]), {}); n = sum(L.values()) or 1
    p["leased"] = (L.get("B", 0) + L.get("A", 0)) / n
    p["yrs_to_exit"] = (e["exit"] - p["year"]) if e else None
BINS = list(range(0, 26, 2)) + [26]; REF = 12
b = lambda a: max(lo for lo in BINS if a >= lo)
def fit(pts, extra):
    types = sorted({p["icao"] for p in pts}); cars = sorted({p["carrier"] for p in pts}); groups = sorted({CLASS[p["icao"]] for p in pts})
    cols = [("T", t) for t in types] + [("C", c) for c in cars[1:]] + [("S",)] + [("A", g, lo) for g in groups for lo in BINS if lo != REF] + [("X", n) for n in extra]
    ix = {c: i for i, c in enumerate(cols)}; X = np.zeros((len(pts), len(cols))); y = np.zeros(len(pts)); w = np.zeros(len(pts))
    for i, p in enumerate(pts):
        X[i, ix[("T", p["icao"])]] = 1
        if p["carrier"] != cars[0]: X[i, ix[("C", p["carrier"])]] = 1
        X[i, ix[("S",)]] = np.log(p["sector"] / 2)
        lo = b(p["age"])
        if lo != REF: X[i, ix[("A", CLASS[p["icao"]], lo)]] = 1
        for n, f in extra.items(): X[i, ix[("X", n)]] = f(p)
        y[i] = np.log(p["direct"]); w[i] = p["bh"]
    sw = np.sqrt(w / w.mean()); beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return {n: float(beta[ix[("X", n)]]) for n in extra}
EX = {"доживание, собственные": lambda p: p["runout"] * (1 - p["leased"]), "доживание, в аренде": lambda p: p["runout"] * p["leased"]}
EX2 = {f"за {k} г. до ухода": (lambda k: lambda p: float(p["yrs_to_exit"] == k))(k) for k in range(0, 5)}
est = fit(pts, EX); est2 = fit(pts, EX2)
rng = np.random.default_rng(7); cars = sorted({p["carrier"] for p in pts}); byc = collections.defaultdict(list); [byc[p["carrier"]].append(p) for p in pts]
B = []
for _ in range(200):
    s = []
    for j, c in enumerate(rng.choice(cars, len(cars))): s += [{**p, "carrier": f"{c}#{j}"} for p in byc[c]]
    B.append(fit(s, EX2))
ci = {n: (float(np.percentile([x[n] for x in B], 10)), float(np.percentile([x[n] for x in B], 90))) for n in EX2}
nrun = sum(p["runout"] for p in pts)
out = dict(merged_skipped=merged, exits={f"{k[0]}|{k[1]}": v for k, v in exits.items()}, n_points=len(pts), n_runout=nrun,
           effect={n: float(np.exp(v)) for n, v in est.items()}, by_year={n: float(np.exp(v)) for n, v in est2.items()},
           by_year_ci={n: [float(np.exp(a)), float(np.exp(b_))] for n, (a, b_) in ci.items()},
           tails_total=sum(e["tails"] for e in exits.values()), tails_later_other_us=sum(e["later_other_us"] for e in exits.values()))
out["lease"] = {f"{a}|{i}|{y}": round((L.get("B", 0) + L.get("A", 0)) / max(sum(L.values()), 1), 3) for (a, i, y), L in lease.items()}
json.dump(out, open(HERE / "runout.json", "w"), ensure_ascii=False, indent=1)
print("уходов из-за прекращения отчётности перевозчика (слияния) не считаются:", merged)
print("уходов типа от продолжающего работу перевозчика:", len(exits), "строк в окне доживания:", nrun, "из", len(pts))
print("бортов, ушедших в окне:", out["tails_total"], "из них потом у другого перевозчика США:", out["tails_later_other_us"])
for n, v in out["effect"].items(): print(f"  {n}: ×{v:.2f}")
for n, v in out["by_year"].items(): print(f"  {n}: ×{v:.2f}  [{out['by_year_ci'][n][0]:.2f}–{out['by_year_ci'][n][1]:.2f}]")
