"""Панель ТОиР: перевозчик (AIRLINE_ID) × тип ИКАО × год, 1991–2025, из P-5.2 и T-2."""
import csv, json, sys, pathlib
from collections import defaultdict
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gh"))
from flightcostapp.bench import icao_of, CODE_OVERRIDES
RAW = HERE / "raw20"
types = {r["Code"].lstrip("0"): r["Description"] for r in csv.DictReader(open(RAW / "types.csv", encoding="utf-8-sig"))}
# Старые типы, которых нет в bench.TYPE_PATTERNS (там — только типы расчёта сайта)
OLD = {"655": "MD80", "656": "MD90", "676": "E135", "675": "E135", "617": "B734", "616": "B735", "620": "B732",
       "456": "SF34", "461": "E120", "483": "DH8A", "491": "DH8B", "484": "DH8C", "628": "CRJ1", "650": "DC95",
       "640": "DC93", "645": "DC94", "691": "A306", "740": "MD11", "732": "DC10", "632": "J328", "715": "B722",
       "405": "B190", "835": "RJ85", "432": "SB20", "469": "JS31"}
def icao(code):
    if code in CODE_OVERRIDES: return CODE_OVERRIDES[code][0]
    return icao_of(types.get(code, "")) or OLD.get(code)
AF = ["AIRFRAME_LABOR","AIRFRAME_REPAIR","AIRFRAME_MATERIALS","AIRFRAME_ALLOW","AIRFRAME_OVERHAULS"]
EN = ["ENGINE_LABOR","ENGINE_REPAIRS","ENGINE_MATERIALS","ENGINE_ALLOW","ENGINE_OVERHAULS"]
F = AF + EN + ["INTERCHG_CHARG","TOT_DIR_MAINT","AP_MT_BURDEN","TOT_FLT_MAINT_MEMO"]
num = lambda v: float(v) if v and v.strip() else 0.0
p = defaultdict(lambda: defaultdict(float)); names = {}; codes = {}
for r in csv.DictReader(open(RAW / "p52.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if y > 2025 or r["AIRCRAFT_CONFIG"].strip() not in ("1", "01"): continue
    k = (y, int(r["QUARTER"]), r["AIRLINE_ID"], r["AIRCRAFT_TYPE"].lstrip("0"))
    names[r["AIRLINE_ID"]] = r["UNIQUE_CARRIER_NAME"]; codes[r["AIRLINE_ID"]] = r["UNIQUE_CARRIER"]
    for f in F: p[k][f] += num(r[f]) * 1000.0          # тысячи USD
RANK = {"Z": 0, "K": 1, "V": 1}; lvl = {}; reg = defaultdict(lambda: defaultdict(float))
for r in csv.DictReader(open(RAW / "t2.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if y > 2025 or r["AIRCRAFT_CONFIG"].strip() not in ("1", "01"): continue
    kr = (y, int(r["QUARTER"]), r["AIRLINE_ID"], r["AIRCRAFT_TYPE"].lstrip("0"), r["CARRIER_REGION"])
    L = RANK.get(r["SERVICE_CLASS"].strip(), 2); b = lvl.get(kr)
    if b is not None and L > b: continue
    if b is not None and L < b: reg[kr] = defaultdict(float)
    lvl[kr] = L
    reg[kr]["bh"] += num(r["ACRFT_HRS_RAMPTORAMP_630"]); reg[kr]["dep"] += num(r["REV_ACRFT_DEP_PERF_510"])
    names.setdefault(r["AIRLINE_ID"], r["UNIQUE_CARRIER_NAME"]); codes.setdefault(r["AIRLINE_ID"], r["UNIQUE_CARRIER"])
t = defaultdict(lambda: defaultdict(float))
for kr, v in reg.items():
    for f, x in v.items(): t[kr[:4]][f] += x
acc = defaultdict(lambda: defaultdict(float)); qs = defaultdict(set); stat = defaultdict(int)
for k, v in p.items():
    y, q, aid, code = k
    if k not in t or t[k]["bh"] <= 0: stat["нет пары T-2 или блок-часов"] += 1; continue
    tot = v["TOT_FLT_MAINT_MEMO"] or (v["TOT_DIR_MAINT"] + v["AP_MT_BURDEN"])
    if tot <= 0: stat["ТОиР не подан (ноль)"] += 1; continue
    ic = icao(code)
    if not ic: stat["тип не расшифрован"] += 1; continue
    a = acc[(y, aid, ic)]
    for f, x in v.items(): a[f] += x
    a["TOT"] += tot
    for f, x in t[k].items(): a["t_" + f] += x
    qs[(y, aid, ic)].add(q)
rows = []
for (y, aid, ic), a in acc.items():
    bh = a["t_bh"]
    rows.append(dict(year=y, aid=aid, carrier=codes[aid], name=names[aid], icao=ic, quarters=len(qs[(y, aid, ic)]),
        block_h=round(bh), sector_h=round(bh / a["t_dep"], 2) if a["t_dep"] else None,
        total=a["TOT"], direct=a["TOT_DIR_MAINT"], burden=a["AP_MT_BURDEN"],
        airframe=sum(a[f] for f in AF), engine=sum(a[f] for f in EN)))
rows.sort(key=lambda r: (r["icao"], r["carrier"], r["year"]))
json.dump({"rows": rows, "skipped": dict(stat)}, open(HERE / "panel.json", "w"), ensure_ascii=False)
print(len(rows), "строк;", dict(stat))
