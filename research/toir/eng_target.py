"""Двигательная часть ТОиР по Form 41 — цель для сверки модели «снизу».
Берутся строки, где разбивка планер/двигатели настоящая: строка типа, год не распределён формулой (ни итог, ни доли),
доля двигателей ≥ 15% прямых, возраст парка 8–20 лет (за первым капремонтом, до доживания). USD 2025 на блок-час."""
import json, pathlib, collections, statistics as st
HERE = pathlib.Path(__file__).resolve().parent
P = json.load(open(HERE / "panel.json"))["rows"]; AG = json.load(open(HERE / "ages.json"))["ages"]
CV = json.load(open(HERE / "curves_ppi.json")); AQ = json.load(open(HERE / "alloc_q.json")); IX = json.load(open(HERE / "index.json"))
POL = json.load(open(HERE / "policy.json"))
def ppi(y):
    w = IX["wps5541_jun"].get(str(y)) or 100.0 * IX["pcu488190_jun"][str(y)] / IX["pcu488190_jun"]["2009"]
    return IX["wps5541_jun"]["2025"] / w
pts = collections.defaultdict(list)
for r in P:
    if r["year"] < 2006 or r["direct"] <= 0: continue
    k = f"{r['aid']}|{r['year']}"; a = AG.get(f"{r['year']}|{r['aid']}|{r['icao']}")
    if not a or not (8 <= a["age"] <= 20) or k in AQ or CV["alloc"].get(k) or r["quarters"] < 3: continue
    if any(p["from"] <= r["year"] <= p["to"] for p in POL.get(r["carrier"], [])): continue
    if r["engine"] / r["direct"] < 0.15: continue
    pts[r["icao"]].append(dict(c=r["carrier"], y=r["year"], age=a["age"], eng=r["engine"] / r["block_h"] * ppi(r["year"]),
                               af=r["airframe"] / r["block_h"] * ppi(r["year"]), share=r["engine"] / r["direct"], sector=r["sector_h"], bh=r["block_h"]))
out = {}
for t, ps in pts.items():
    cars = sorted({p["c"] for p in ps})
    # медиана по перевозчикам (сначала медиана внутри перевозчика) — каждый весит одинаково
    pc = [st.median([p["eng"] for p in ps if p["c"] == c]) for c in cars]
    out[t] = dict(eng_bh=st.median(pc), share=st.median([p["share"] for p in ps]), carriers=cars, n=len(ps),
                  sector=st.median([p["sector"] for p in ps]), lo=min(pc), hi=max(pc), points=ps)
json.dump(out, open(HERE / "bottomup" / "eng_target.json", "w"), ensure_ascii=False)
for t in sorted(out, key=lambda t: -out[t]["n"]):
    o = out[t]
    if o["n"] >= 3: print(f"{t:5} двигатели {o['eng_bh']:5.0f} USD25/БЧ (по перевозчикам {o['lo']:.0f}–{o['hi']:.0f}), доля {o['share']:.0%}, сектор {o['sector']:.1f} ч, строк {o['n']}, {', '.join(o['carriers'])}")
