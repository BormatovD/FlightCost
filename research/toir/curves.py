"""Кривые «ставка ТОиР от возраста парка» по типам, USD 2025, и ставка за жизненный цикл."""
import json, pathlib, collections, sys
HERE = pathlib.Path(__file__).resolve().parent
P = json.load(open(HERE / "panel.json"))["rows"]; A = json.load(open(HERE / "ages.json"))["ages"]
IX = json.load(open(HERE / "index.json"))
INDEX = sys.argv[1] if len(sys.argv) > 1 else "ppi"
def idx(y):
    if INDEX == "cpi": return IX["cpiu_annual"][str(y)] / IX["cpiu_annual"]["2025"]
    w = IX["wps5541_jun"].get(str(y))
    if w is None: w = 100.0 * IX["pcu488190_jun"][str(y)] / IX["pcu488190_jun"]["2009"]
    return w / IX["wps5541_jun"]["2025"]
import os
AQ = json.load(open(HERE / "alloc_q.json")) if (HERE / "alloc_q.json").exists() else {}
BASIS = {"bh": "блок-часам", "asm": "кресло-милям", "dep": "вылетам", "mi": "милям"}
RUN = json.load(open(HERE / "runout.json"))["exits"] if (HERE / "runout.json").exists() else {}
POL = json.load(open(HERE / os.environ.get("POLICY", "policy.json")))      # решения об исключении по перевозчикам и годам
# --- распределение формулой: по данным, год за годом
by = collections.defaultdict(list)
for r in P:
    if r["year"] >= 2006 and r["block_h"] > 5000 and r["direct"] > 0: by[(r["aid"], r["year"])].append(r)
alloc = {}
for k, rs in by.items():
    if len(rs) < 3: continue
    sh = [x["airframe"] / max(x["airframe"] + x["engine"], 1) for x in rs]; bu = [x["burden"] / x["direct"] for x in rs]
    rt = [x["total"] / x["block_h"] for x in rs]
    split = max(sh) - min(sh) < 0.03 and max(bu) - min(bu) < 0.03
    alloc[k] = "total" if split and max(rt) / min(rt) < 1.35 else "split" if split else None
pts = []; excl = collections.Counter(); exlist = []
for r in P:
    if r["year"] < 2006: continue
    a = A.get(f"{r['year']}|{r['aid']}|{r['icao']}")
    why = None
    if not a: why = "нет возраста в B-43"
    elif r["quarters"] < 3: why = "меньше 3 кварталов"
    elif a["n"] < 5: why = "меньше 5 бортов"
    elif r["direct"] <= 0: why = "прямой ТОиР не подан"
    elif alloc.get((r["aid"], r["year"])) == "total": why = "распределено формулой (доли и итог ровные)"
    elif f"{r['aid']}|{r['year']}" in AQ: why = f"распределено по типам пропорционально {BASIS[AQ[r['aid'] + '|' + str(r['year'])]['basis']]}"
    else:
        p = POL.get(r["carrier"]) or POL.get(r["aid"])
        if p:
            for per in p:
                if per["from"] <= r["year"] <= per["to"] and per["use"] is False: why = per["why"]; break
        e = RUN.get(f"{r['aid']}|{r['icao']}")
        if not why and e and e["exit"] - 2 <= r["year"] <= e["exit"] and not os.environ.get("NO_RUNOUT"):
            why = f"доживание: тип уходит из парка перевозчика в {e['exit']}"
        if not why and r["engine"] / r["direct"] < 0.15 and alloc.get((r["aid"], r["year"])) != "split":
            why = "двигатели < 15% прямых — учтены вне ТОиР"
    if why: excl[why] += 1; exlist.append({**{k: r[k] for k in ("year","carrier","icao")}, "why": why}); continue
    k = 1 / idx(r["year"])
    pts.append(dict(icao=r["icao"], year=r["year"], carrier=r["carrier"], age=a["age"], n=a["n"], bh=r["block_h"],
                    direct=r["direct"] / r["block_h"] * k, burden=r["burden"] / r["block_h"] * k,
                    split_ok=alloc.get((r["aid"], r["year"])) != "split", sector=r["sector_h"]))
def wmed(xs):
    xs = sorted(xs); t = sum(w for _, w in xs); c = 0
    for v, w in xs:
        c += w
        if c >= t / 2: return v
types = collections.defaultdict(list)
for p in pts: types[p["icao"]].append(p)
out = {}
for ic, ps in types.items():
    bins = {}
    for b in range(0, 36, 2):
        s = [p for p in ps if b <= p["age"] < b + 2]
        if sum(p["bh"] for p in s) < 30000: continue      # меньше ~30 тыс. блок-часов в корзине — шум
        bins[b + 1] = dict(direct=wmed([(p["direct"], p["bh"]) for p in s]), burden=wmed([(p["burden"], p["bh"]) for p in s]),
                           rows=len(s), carriers=sorted({p["carrier"] for p in s}), bh=sum(p["bh"] for p in s))
    out[ic] = {"bins": bins, "points": ps}
json.dump({"index": INDEX, "types": out, "excluded": dict(excl), "excluded_rows": exlist, "alloc": {f"{k[0]}|{k[1]}": v for k, v in alloc.items() if v}},
          open(HERE / (f"curves_{INDEX}_all.json" if os.environ.get("NO_RUNOUT") else f"curves_{INDEX}.json"), "w"), ensure_ascii=False)
print(INDEX, "точек", len(pts), dict(excl))
for ic in sorted(out, key=lambda i: -sum(p["bh"] for p in out[i]["points"])):
    b = out[ic]["bins"]
    if not b: continue
    print(f"{ic:5}", " ".join(f"{a}:{v['direct']:.0f}({len(v['carriers'])})" for a, v in sorted(b.items())))
