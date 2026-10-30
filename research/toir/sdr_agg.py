"""SDR 2018–2025: каждое сообщение → перевозчик (по бортовому номеру через B-43 того же года), тип ИКАО, глава/код JASC.
Знаменатель — блок-часы T-2 перевозчика по типу за год (все компоновки)."""
import csv, json, re, collections, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent; R = HERE / "raw20"; S = HERE / "sdr"
csv.field_size_limit(10**8)
def icao_sdr(make, model):
    m = re.sub(r"[^A-Z0-9]", "", (model or "").upper()); mk = (make or "").upper()
    if mk.startswith("BOEING"):
        if m in ("7378", "737MAX8"): return "B38M"
        if m in ("7379", "737MAX9"): return "B39M"
        for p, ic in (("7377", "B737"), ("7378", "B738"), ("7379", "B739"), ("7373", "B733"), ("7374", "B734"), ("7375", "B735"),
                      ("7172", "B712"), ("7572", "B752"), ("7573", "B753"), ("7672", "B762"), ("7673", "B763"), ("7674", "B764"),
                      ("7773", "B77W"), ("7772", "B772"), ("777F", "B772"), ("78710", "B78X"), ("7878", "B788"), ("7879", "B789"), ("7474", "B744"), ("7478", "B748")):
            if m.startswith(p): return ic
    if mk.startswith("AIRBUS"):
        if m.startswith("BD5001A10"): return "BCS1"
        if m.startswith("BD5001A11"): return "BCS3"
        for p, n, o in (("A319", "A19N", "A319"), ("A320", "A20N", "A320"), ("A321", "A21N", "A321")):
            if m.startswith(p): return n if re.search(r"N(X|Y)?$", m) else o
        for p, ic in (("A3302", "A332"), ("A3303", "A333"), ("A3309", "A339"), ("A3509", "A359"), ("A300", "A306")):
            if m.startswith(p): return ic
    if mk.startswith(("CNDAIR", "BOMBDR", "MITSUB")):
        if "2B19" in m: return "CRJ2"
        if "2C10" in m or "2C11" in m: return "CRJ7"
        if "2D24" in m or "2D15" in m: return "CRJ9"
    if mk.startswith("EMB"):
        if m.startswith(("EMB145", "ERJ145")): return "E145"
        if m.startswith(("EMB135", "ERJ135", "EMB140")): return "E135"
        if m.startswith(("ERJ170200", "EMB175")): return "E75L"
        if m.startswith("ERJ170"): return "E170"
        if m.startswith("ERJ190"): return "E190" if "400" not in m[:10] else "E195"
    if mk.startswith(("DOUG", "MCDONN", "BOEING")) and m.startswith(("DC983", "DC982", "MD8")): return "MD80"
    if mk.startswith(("DEHAV", "DHC", "BOMBDR")) and "DHC8400" in m: return "DH8D"
    if mk.startswith("ATR") or m.startswith("ATR72"): return "AT76"
    return None
# бортовой номер → перевозчик по B-43 (год отчёта)
tail = {}
for r in csv.DictReader(open(R / "b43.csv", encoding="utf-8-sig")):
    t = r["TAIL_NUMBER"].strip().upper().lstrip("N")
    if t: tail[(int(r["YEAR"]), t)] = r["AIRLINE_ID"]
code = {}
for r in csv.DictReader(open(R / "t2.csv", encoding="utf-8-sig")):
    code[r["AIRLINE_ID"]] = r["UNIQUE_CARRIER"]
cnt = collections.Counter(); cnt4 = collections.Counter(); ptime = collections.defaultdict(list); stat = collections.Counter()
for f in sorted(S.glob("SDR-20*.csv")):
    for r in csv.DictReader(open(f, encoding="utf-8-sig", errors="replace")):
        if r["SubmitterTypeCode"] != "A": stat["не авиаперевозчик (тип подателя ≠ A)"] += 1; continue
        try: y = int(r["DifficultyDate"][-4:])
        except ValueError: stat["нет даты"] += 1; continue
        ic = icao_sdr(r["AircraftMake"], r["AircraftModel"])
        if not ic: stat["тип вне списка"] += 1; continue
        n = r["RegistryNNumber"].strip().upper().lstrip("N")
        aid = tail.get((y, n)) or tail.get((y - 1, n)) or tail.get((y + 1, n))
        if not aid: stat["борт не найден в B-43"] += 1; continue
        j = re.sub(r"\D", "", r["JASCCode"])[:4]
        if len(j) != 4: stat["нет кода JASC"] += 1; continue
        stat["учтено"] += 1
        cnt[(y, aid, ic, j[:2])] += 1; cnt4[(ic, j)] += 1
        try:
            pt = float(r["PartTotalTime"] or 0)
            if pt > 0: ptime[(ic, j)].append(pt)
        except ValueError: pass
json.dump({"stat": dict(stat), "cnt": {"|".join(map(str, k)): v for k, v in cnt.items()}, "cnt4": {"|".join(k): v for k, v in cnt4.items()},
           "ptime": {"|".join(k): sorted(v) for k, v in ptime.items() if len(v) >= 5}, "code": code}, open(S / "sdr_agg.json", "w"))
print(dict(stat))
