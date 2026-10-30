"""Итог (сектор приведён к типичному для класса: региональные 1,5 ч, узкофюзеляжные 2,5 ч, широкофюзеляжные 8 ч): форма кривой — из модели fe.py (по классам), ставка типа — медиана приведённых точек.
Приведённая точка = наблюдение / f(возраст) / (сектор/сектор класса)^e  →  «зрелый борт, типичный сектор класса, USD 2025».
Вес строки — её доля в блок-часах своего перевозчика по типу: каждый перевозчик весит одинаково
(иначе ставка типа = ставка крупнейшего: у B737 на Southwest 86% блок-часов)."""
import json, pathlib, sys, collections
HERE = pathlib.Path(__file__).resolve().parent
INDEX = sys.argv[1] if len(sys.argv) > 1 else "ppi"
FE = json.load(open(HERE / f"fe_{INDEX}_direct.json")); FB = json.load(open(HERE / f"fe_{INDEX}_burden.json"))
C = json.load(open(HERE / f"curves_{INDEX}.json"))
sys.path.insert(0, str(HERE)); from common import CLASS, CHARTER as CH
BINS = list(range(0, 26, 2)) + [26]
def binof(a): return max(lo for lo in BINS if a >= lo)
sh_all = FE["by_class"]["shape"]; nobs = FE["by_class"]["nobs"]; E = FE["by_class"]["sector_elasticity"]
shape = {}
for g, sh in sh_all.items():   # пустые ступени — значение последней наблюдаемой
    last = None; s = {}
    for lo in BINS:
        if nobs.get(f"{g}|{lo}", 0) >= 5: last = sh[str(lo)] if str(lo) in sh else sh[lo]
        s[lo] = last
    first = next(v for v in s.values() if v is not None); shape[g] = {lo: (v if v is not None else first) for lo, v in s.items()}
LIFE = {g: sum(shape[g][binof(a + 0.5)] for a in range(25)) / 25 for g in shape}
SEC = {"региональные": 1.5, "узкофюзеляжные": 2.5, "широкофюзеляжные": 8.0}
def wq(xs, q):
    xs = sorted(xs); t = sum(w for _, w in xs); c = 0
    for v, w in xs:
        c += w
        if c >= q * t: return v
types = {}
for ic, T in C["types"].items():
    g = CLASS.get(ic)
    if not g: continue
    ps = [p for p in T["points"] if p["carrier"] not in CH and p["sector"] and p["direct"] > 0]
    if len(ps) < 3: continue
    norm = []
    for p in ps:
        k = shape[g][binof(p["age"])] * (p["sector"] / SEC[g]) ** E
        norm.append({**p, "f": shape[g][binof(p["age"])], "sec_k": (p["sector"] / SEC[g]) ** E, "mature": p["direct"] / k, "burden_share": p["burden"] / p["direct"]})
    cb = collections.Counter(); [cb.update({p["carrier"]: p["bh"]}) for p in norm]
    for p in norm: p["w"] = p["bh"] / cb[p["carrier"]]
    ages = [p["age"] for p in ps]
    young_only = max(ages) < 6
    m = wq([(p["mature"], p["w"]) for p in norm], .5)
    m_bh = wq([(p["mature"], p["bh"]) for p in norm], .5)
    types[ic] = dict(icao=ic, cls=g, n=len(ps), carriers=sorted({p["carrier"] for p in ps}), age_lo=min(ages), age_hi=max(ages),
                     years=[min(p["year"] for p in ps), max(p["year"] for p in ps)], young_only=young_only,
                     mature=m, lo=wq([(p["mature"], p["w"]) for p in norm], .2), hi=wq([(p["mature"], p["w"]) for p in norm], .8), mature_bh=m_bh,
                     burden_share=wq([(p["burden_share"], p["w"]) for p in norm if p["burden_share"] > 0.02], .5) if any(p["burden_share"] > 0.02 for p in norm) else None,
                     burden_reporting=f'{sum(1 for p in norm if p["burden_share"] > 0.02)} из {len(norm)}', life=m * LIFE[g],
                     points=sorted(norm, key=lambda p: (p["carrier"], p["year"])))
PAIRS = [("B38M", "B738"), ("B39M", "B739"), ("A20N", "A320"), ("A21N", "A321"), ("A19N", "A319"),
         ("B788", "B763"), ("B789", "B764"), ("B789", "A332"), ("A359", "B772"), ("A339", "A333"),
         ("BCS3", "E190"), ("BCS1", "E190"), ("E75L", "CRJ9"), ("B39M", "B753")]
pairs = []
for a, b in PAIRS:
    if a in types and b in types:
        A, Bt = types[a], types[b]
        # тот же возраст: предшественник — только точки в диапазоне возраста нового типа (+2 года)
        same = [p for p in Bt["points"] if p["age"] <= A["age_hi"] + 2]
        same_m = wq([(p["mature"], p["w"]) for p in same], .5) if len(same) >= 3 else None
        pairs.append(dict(new=a, old=b, ratio=A["mature"] / Bt["mature"], ratio_same_age=(A["mature"] / same_m) if same_m else None,
                          new_n=A["n"], new_carriers=A["carriers"], old_same_n=len(same), age_hi=A["age_hi"]))
out = dict(nobs=nobs, sector_ref=SEC, index=INDEX, sector_elasticity=E, shape=shape, life=LIFE, boot_shape=FE["boot"]["shape"], types=types, pairs=pairs,
           excluded=C["excluded"], burden_life_note="накладные не приводятся по возрасту: это отнесённые расходы службы ТО")
json.dump(out, open(HERE / f"final_{INDEX}.json", "w"), ensure_ascii=False)
print("жизненный цикл 0–25 лет к зрелому:", {g: round(v, 3) for g, v in LIFE.items()}, "эласт. сектора", round(E, 3))
for t in sorted(types.values(), key=lambda t: (t["cls"], -t["n"])):
    print(f"{t['icao']:5} {t['cls'][:5]} n{t['n']:3} перев{len(t['carriers']):2} возр {t['age_lo']:4.1f}-{t['age_hi']:4.1f}  зрелый {t['mature']:6.0f} [{t['lo']:.0f}–{t['hi']:.0f}]  цикл {t['life']:6.0f}  накл {(t['burden_share'] or 0):.0%} ({t['burden_reporting']})" + ("  ТОЛЬКО МОЛОДОЙ" if t["young_only"] else ""))
for p in pairs: print(p["new"], "/", p["old"], round(p["ratio"], 2), "в том же возрасте:", p["ratio_same_age"] and round(p["ratio_same_age"], 2), "точек предш.", p["old_same_n"])
