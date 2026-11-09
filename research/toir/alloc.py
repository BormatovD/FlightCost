"""Распределение ТОиР по типам формулой: поквартально ищем общую базу (блок-час, ASM, вылет, миля),
на которую у ≥75% типов перевозчика приходится одна и та же ставка (±3%). Год помечается, если так в ≥2 кварталах."""
import csv, json, pathlib, collections
HERE = pathlib.Path(__file__).resolve().parent; RAW = HERE / "raw20"
num = lambda v: float(v) if v and v.strip() else 0.0
M = collections.defaultdict(lambda: collections.defaultdict(float)); code = {}
for r in csv.DictReader(open(RAW / "p52.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if not (2006 <= y <= 2025) or r["AIRCRAFT_CONFIG"].strip() != "1": continue
    M[(r["AIRLINE_ID"], y, r["QUARTER"], r["AIRCRAFT_TYPE"].lstrip("0"))]["d"] += num(r["TOT_DIR_MAINT"]); code[r["AIRLINE_ID"]] = r["UNIQUE_CARRIER"]
for r in csv.DictReader(open(RAW / "t2.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if not (2006 <= y <= 2025) or r["AIRCRAFT_CONFIG"].strip() != "1" or r["SERVICE_CLASS"] != "Z": continue
    k = (r["AIRLINE_ID"], y, r["QUARTER"], r["AIRCRAFT_TYPE"].lstrip("0"))
    if k in M:
        for f, c in (("bh", "ACRFT_HRS_RAMPTORAMP_630"), ("asm", "AVL_SEAT_MILES_320"), ("dep", "REV_ACRFT_DEP_PERF_510"), ("mi", "REV_ACRFT_MILES_FLOWN_410")):
            M[k][f] += num(r[c])
byq = collections.defaultdict(list)
for (aid, y, q, t), v in M.items():
    if v["d"] > 0 and v["bh"] > 500: byq[(aid, y, q)].append(v)
qflag = collections.defaultdict(list)
for (aid, y, q), vs in byq.items():
    if len(vs) < 3: continue
    for f in ("bh", "asm", "dep", "mi"):
        r = sorted(v["d"] / v[f] for v in vs if v[f] > 0)
        if len(r) < 3: continue
        med = r[len(r) // 2]
        if sum(1 for x in r if abs(x / med - 1) < 0.03) / len(r) >= 0.75:
            qflag[(aid, y)].append(f); break
out = {}
for (aid, y), fl in qflag.items():
    if len(fl) >= 2:
        out[f"{aid}|{y}"] = {"carrier": code[aid], "basis": collections.Counter(fl).most_common(1)[0][0], "quarters": len(fl)}
json.dump(out, open(HERE / "alloc_q.json", "w"), ensure_ascii=False, indent=0)
NAME = {"bh": "блок-час", "asm": "кресло-милю", "dep": "вылет", "mi": "милю"}
byc = collections.defaultdict(list)
for k, v in out.items(): byc[v["carrier"]].append((int(k.split("|")[1]), v["basis"]))
for c, ys in sorted(byc.items()): print(f"{c:8}", " ".join(f"{y}:{NAME[b]}" for y, b in sorted(ys)))
