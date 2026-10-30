"""Модель с фиксированными эффектами: ln(ставка) = тип + перевозчик + f(возраст).
Взвешено блок-часами. f — ступени по 2 года, опорная ступень 12–13 лет («зрелый борт»)."""
import json, pathlib, sys, collections, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import CLASS, CHARTER
HERE = pathlib.Path(__file__).resolve().parent
INDEX = sys.argv[1] if len(sys.argv) > 1 else "ppi"
WHAT = sys.argv[2] if len(sys.argv) > 2 else "direct"
C = json.load(open(HERE / f"curves_{INDEX}.json"))
pts = [p for t in C["types"].values() for p in t["points"] if p[WHAT] > 0 and p["carrier"] not in CHARTER and p["sector"]]
cnt = collections.Counter(p["icao"] for p in pts)
pts = [p for p in pts if cnt[p["icao"]] >= 3 and CLASS.get(p["icao"])]
BINS = list(range(0, 26, 2)) + [26]
def b(age):
    for i, lo in enumerate(BINS[::-1]):
        if age >= lo: return BINS[::-1][i]
REF = 12
def fit(pts, by_class=False):
    types = sorted({p["icao"] for p in pts}); cars = sorted({p["carrier"] for p in pts})
    groups = sorted({CLASS.get(p["icao"], "прочие") for p in pts}) if by_class else ["все"]
    cols = [("T", t) for t in types] + [("C", c) for c in cars[1:]] + [("S",)] + \
           [("A", g, lo) for g in groups for lo in BINS if lo != REF]
    ix = {c: i for i, c in enumerate(cols)}
    X = np.zeros((len(pts), len(cols))); y = np.zeros(len(pts)); w = np.zeros(len(pts))
    for i, p in enumerate(pts):
        X[i, ix[("T", p["icao"])]] = 1
        if p["carrier"] != cars[0]: X[i, ix[("C", p["carrier"])]] = 1
        g = CLASS.get(p["icao"], "прочие") if by_class else "все"; lo = b(p["age"])
        if lo != REF: X[i, ix[("A", g, lo)]] = 1
        X[i, ix[("S",)]] = np.log(p["sector"] / 2.0)     # длина сектора относительно 2 ч
        y[i] = np.log(p[WHAT]); w[i] = p["bh"]
    sw = np.sqrt(w / w.mean())
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    res = y - X @ beta
    s2 = np.sum(w * res ** 2) / np.sum(w)
    car_fx = {c: (beta[ix[("C", c)]] if ("C", c) in ix else 0.0) for c in cars}
    # средний эффект перевозчика по блок-часам — уровень «типичного перевозчика»
    bh_c = collections.Counter(); [bh_c.update({p["carrier"]: p["bh"]}) for p in pts]
    cbar = sum(car_fx[c] * bh_c[c] for c in cars) / sum(bh_c.values())
    shape = {g: {lo: (float(np.exp(beta[ix[("A", g, lo)]])) if lo != REF else 1.0) for lo in BINS} for g in groups}
    nobs = collections.Counter(); [nobs.update({(CLASS.get(p["icao"], "прочие") if by_class else "все", b(p["age"])): 1}) for p in pts]
    lvl = {t: float(np.exp(beta[ix[("T", t)]] + cbar)) for t in types}
    return dict(sector_elasticity=float(beta[ix[("S",)]]), level=lvl, shape=shape, sigma=float(np.sqrt(s2)), n=len(pts), carriers=car_fx, cbar=float(cbar),
                nobs={f"{g}|{lo}": n for (g, lo), n in nobs.items()})
out = {"pooled": fit(pts), "by_class": fit(pts, True)}
# Бутстрэп по перевозчикам: перевозчик выпадает или повторяется целиком (его учёт — один источник ошибки)
rng = np.random.default_rng(2025); cars = sorted({p["carrier"] for p in pts}); B = []
byc = collections.defaultdict(list); [byc[p["carrier"]].append(p) for p in pts]
for _ in range(200):
    pick = rng.choice(cars, len(cars)); sample = []
    for j, c in enumerate(pick): sample += [{**p, "carrier": f"{c}#{j}"} for p in byc[c]]
    try: B.append(fit(sample, True))
    except Exception: pass
def q(xs, a): xs = sorted(x for x in xs if x is not None); return xs[int(a * (len(xs) - 1))] if xs else None
out["boot"] = {"n": len(B),
  "level": {t: [q([b["level"].get(t) for b in B], .1), q([b["level"].get(t) for b in B], .9)] for t in out["by_class"]["level"]},
  "shape": {g: {lo: [q([b["shape"].get(g, {}).get(lo) for b in B], .1), q([b["shape"].get(g, {}).get(lo) for b in B], .9)] for lo in BINS}
            for g in out["by_class"]["shape"]}}
json.dump(out, open(HERE / f"fe_{INDEX}_{WHAT}.json", "w"), ensure_ascii=False, indent=1)
for k, f in [(k, out[k]) for k in ("pooled", "by_class")]:
    print("==", k, "σ =", round(f["sigma"], 3), "n =", f["n"], "эластичность по сектору", round(f["sector_elasticity"], 3))
    for g, sh in f["shape"].items():
        lc = np.mean([sh[b(a + 0.5)] for a in range(0, 25)])
        print(f"  {g:16}", " ".join(f"{lo}:{v:.2f}" for lo, v in sh.items()), f"| среднее 0–25 лет: {lc:.3f}")
