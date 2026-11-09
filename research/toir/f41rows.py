"""Этап 1а: ТОиР по Form 41 2025, перевозчик × тип, с разбивкой планер/двигатель."""
import csv, json, sys, pathlib
from collections import defaultdict
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "gh"))
from flightcostapp.bench import icao_of, CODE_OVERRIDES
RAW = pathlib.Path(__file__).resolve().parents[1] / "e2r/data/raw/form41"
types = {r["Code"].lstrip("0") if "Code" in r else r["CODE"].lstrip("0"): r.get("Description") or r.get("DESCRIPTION")
         for r in csv.DictReader(open(RAW/"types.csv", encoding="utf-8-sig"))}
AF = ["AIRFRAME_LABOR","AIRFRAME_REPAIR","AIRFRAME_MATERIALS","AIRFRAME_ALLOW","AIRFRAME_OVERHAULS"]
EN = ["ENGINE_LABOR","ENGINE_REPAIRS","ENGINE_MATERIALS","ENGINE_ALLOW","ENGINE_OVERHAULS"]
num = lambda v: float(v) if v and v.strip() else 0.0
p = defaultdict(lambda: defaultdict(float)); names = {}
for r in csv.DictReader(open(RAW/"p52.csv", encoding="utf-8-sig")):
    if r["AIRCRAFT_CONFIG"].strip() not in ("1", "01"): continue
    k = (r["YEAR"]+"Q"+r["QUARTER"], r["UNIQUE_CARRIER"], r["AIRCRAFT_TYPE"].lstrip("0"))
    names[r["UNIQUE_CARRIER"]] = r["UNIQUE_CARRIER_NAME"]
    for f in AF+EN+["INTERCHG_CHARG","TOT_DIR_MAINT","AP_MT_BURDEN","TOT_FLT_MAINT_MEMO"]:
        p[k][f] += num(r[f])
# T-2: класс Z = K + V, K = F + G, V = L+N+P+R (как в parsers/form41.py).
# Берётся самый сводный уровень, поданный в регионе; только пассажирская компоновка.
RANK = {"Z": 0, "K": 1, "V": 1}
lvl = {}; reg = defaultdict(lambda: defaultdict(float))
for r in csv.DictReader(open(RAW/"t2.csv", encoding="utf-8-sig")):
    if r["AIRCRAFT_CONFIG"].strip() not in ("1", "01"): continue
    kr = (r["YEAR"]+"Q"+r["QUARTER"], r["UNIQUE_CARRIER"], r["AIRCRAFT_TYPE"].lstrip("0"), r["CARRIER_REGION"])
    L = RANK.get(r["SERVICE_CLASS"].strip(), 2); b = lvl.get(kr)
    if b is not None and L > b: continue
    if b is not None and L < b: reg[kr] = defaultdict(float)
    lvl[kr] = L
    reg[kr]["bh"] += num(r["ACRFT_HRS_RAMPTORAMP_630"]); reg[kr]["dep"] += num(r["REV_ACRFT_DEP_PERF_510"])
    reg[kr]["days"] += num(r["AIR_DAYS_EQUIP_810"])
t = defaultdict(lambda: defaultdict(float))
for kr, v in reg.items():
    for f, x in v.items(): t[kr[:3]][f] += x
acc = defaultdict(lambda: defaultdict(float)); qs = defaultdict(set); drop=[]
for k, v in p.items():
    yq, car, typ = k
    if k not in t: continue
    icao = CODE_OVERRIDES[typ][0] if typ in CODE_OVERRIDES else icao_of(types.get(typ, ""))
    tot = v["TOT_FLT_MAINT_MEMO"] or (v["TOT_DIR_MAINT"] + v["AP_MT_BURDEN"])
    if not icao or tot <= 0 or t[k]["bh"] <= 0:
        drop.append((yq, car, typ, types.get(typ), tot)); continue
    a = acc[(car, icao)]
    for f, x in v.items(): a[f] += x * 1000.0   # P-5.2 в тысячах USD (bench.scales)
    for f, x in t[k].items(): a["t_"+f] += x
    qs[(car, icao)].add(yq)
rows = []
for (car, icao), a in sorted(acc.items(), key=lambda x: (x[0][1], x[0][0])):
    bh, dep = a["t_bh"], a["t_dep"]
    af = sum(a[f] for f in AF); en = sum(a[f] for f in EN)
    rows.append(dict(carrier=car, name=names[car], icao=icao, quarters=len(qs[(car,icao)]),
        block_h=round(bh), departures=round(dep), aircraft=round(a["t_days"]/365.25*4/len(qs[(car,icao)]),1),
        sector_h=round(bh/dep,2) if dep else None,
        direct_bh=round(a["TOT_DIR_MAINT"]/bh), burden_bh=round(a["AP_MT_BURDEN"]/bh),
        total_bh=round((a["TOT_FLT_MAINT_MEMO"] or a["TOT_DIR_MAINT"]+a["AP_MT_BURDEN"])/bh),
        airframe_bh=round(af/bh), engine_bh=round(en/bh), interchange_bh=round(a["INTERCHG_CHARG"]/bh),
        check_sum=round((af+en+a["INTERCHG_CHARG"]-a["TOT_DIR_MAINT"])/max(a["TOT_DIR_MAINT"],1),4)))
json.dump(rows, open("f41_rows.json","w"), ensure_ascii=False, indent=1)
print(len(rows), "rows; dropped", len(drop))
for r in rows: print(f'{r["icao"]:5} {r["carrier"]:3} {r["name"][:26]:26} q{r["quarters"]} ac{r["aircraft"]:6} sec{r["sector_h"]} tot{r["total_bh"]:5} dir{r["direct_bh"]:5} bur{r["burden_bh"]:4} af{r["airframe_bh"]:5} en{r["engine_bh"]:5} chk{r["check_sum"]}')
