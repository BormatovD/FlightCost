"""Средний возраст парка перевозчик (AIRLINE_ID) × ИКАО × год по Schedule B-43."""
import csv, json, re, pathlib, collections
from collections import defaultdict, Counter
HERE = pathlib.Path(__file__).resolve().parent
exec(open(HERE / "panel.py").read().split("AF = ")[0])     # types, icao()
RX = [  # (шаблон по модели без пробелов, ИКАО) — порядок важен
 (r"A?319.*N(EO|X)?\b|319-1\d\dN|A19N", "A19N"), (r"A?320-2\d\dN|320N|A20N|320NEO", "A20N"),
 (r"A?321-2\d\dN|321N|A21N|321NEO|NX", "A21N"),
 (r"BD-?500-1A10|A220-1|CS-?100", "BCS1"), (r"BD-?500-1A11|A220-3|CS-?300", "BCS3"),
 (r"A?318", "A318"), (r"A?319", "A319"), (r"A?320", "A320"), (r"A?321", "A321"),
 (r"A?330-?9|A339", "A339"), (r"A?330-?2", "A332"), (r"A?330-?3", "A333"), (r"A?350-?9|A359", "A359"),
 (r"A?300", "A306"),
 (r"^(B-?)?MAX-?8|737-?MAX-?8|B?38M|737-8200", "B38M"), (r"^(B-?)?MAX-?9", "B39M"), (r"737-?MAX-?9|B?39M", "B39M"), (r"737-?(MAX|7M|8M|9M)", "B7MX"),
 (r"737-?9", "B739"), (r"737-?8", "B738"), (r"737-?7", "B737"),
 (r"737-?3", "B733"), (r"737-?4", "B734"), (r"737-?5", "B735"),
 (r"717", "B712"), (r"757-?3", "B753"), (r"757", "B752"), (r"767-?4", "B764"), (r"767-?3", "B763"), (r"767-?2", "B762"),
 (r"777-?3\d\dER|777-?300ER|B77W", "B77W"), (r"777-?2|777-?F", "B772"), (r"787-?10|B78X", "B78X"),
 (r"787-?9", "B789"), (r"787-?8", "B788"), (r"747-?8", "B748"), (r"747-?4", "B744"),
 (r"CRJ-?9|CL-?600-?2D24|RJ-?900", "CRJ9"), (r"CRJ-?7|CL-?600-?2C10|RJ-?700|CRJ70", "CRJ7"),
 (r"CRJ-?(1|100)|RJ-?100", "CRJ1"), (r"CRJ|CL-?600-?2B19|RJ-?200|CL65", "CRJ2"),
 (r"(ERJ|EMB)-?17[05]-?(2|LR|175)|ERJ-?175|EMB-?175|E175", "E75L"), (r"(ERJ|EMB)-?170|E170", "E170"),
 (r"(ERJ|EMB)?-?190|E190", "E190"), (r"(ERJ|EMB)?-?195|E195", "E195"),
 (r"(ERJ|EMB)-?14[05]", "E145"), (r"(ERJ|EMB)-?135", "E135"),
 (r"MD-?90", "MD90"), (r"MD-?8|SUPER80|DC-?9-?8", "MD80"), (r"MD-?11", "MD11"),
 (r"DHC-?8-?4|Q400|DASH-?8-?Q?4", "DH8D"), (r"DHC-?8-?3|DASH-?8-?3", "DH8C"), (r"DHC-?8-?2|DASH-?8-?2", "DH8B"), (r"DHC-?8-?1|DASH-?8-?1|DHC-?8$", "DH8A"),
 (r"DC-?9-?5", "DC95"), (r"DC-?9-?4", "DC94"), (r"DC-?9-?3", "DC93"), (r"DC-?10", "DC10"),
 (r"EMB-?120|EMB120", "E120"), (r"SF-?340|SAAB-?340|340[AB]?$", "SF34"), (r"ATR-?72", "AT76"), (r"ATR-?42", "AT45"),
]
def from_model(m, my, maker=""):
    m = re.sub(r"\s+", "", (m or "").upper())
    airbus = "AIRBUS" in (maker or "").upper() or m.startswith("A")
    for pat, ic in RX:
        if ic[0] == "A" and ic[:2] != "AT" and not airbus: continue
        if re.search(pat, m):
            # 737-800/900 и MAX 8/9 в B-43 пишут одинаково («737-8», «B737-8»).
            # NG выпускались до 2019, MAX поставлялись с 2017 (9 — с 2018):
            # борт 2017 года и позже с этим обозначением считается MAX, а
            # сомнительный 2017–2019 — так же, с пометкой в журнале.
            if ic == "B738" and my >= 2017 and not re.search(r"737-?8[0-9A-Z]{2}", m): return "B38M"
            if ic == "B739" and my >= 2018 and not re.search(r"737-?9[0-9A-Z]{2}", m): return "B39M"
            if ic == "B7MX": return "B39M" if "9" in m.split("737")[-1][:3] else "B38M"
            return ic
    return None
ages = defaultdict(list); how = Counter(); miss = Counter()
for r in csv.DictReader(open(RAW / "b43.csv", encoding="utf-8-sig")):
    if r["OPERATING_STATUS"].strip().upper() != "Y": how["не в эксплуатации"] += 1; continue
    try: y, my = int(r["YEAR"]), int(float(r["MANUFACTURE_YEAR"]))
    except ValueError: how["нет года выпуска"] += 1; continue
    if not (1950 < my <= y): how["год выпуска вне диапазона"] += 1; continue
    # Код типа в B-43 — код L_AIRCRAFT_TYPE с четвёртой цифрой варианта
    # (6141 = 614 «737-800» + 1). Код надёжнее свободного текста модели.
    code = r["AIRCRAFT_TYPE"].strip()
    code = (code[:3] if len(code) == 4 else code).lstrip("0")
    ic = icao(code) if code else None
    src = "код"
    if not ic:
        ic = from_model(r["MODEL"], my, r["MANUFACTURER"]); src = "модель"
    if not ic: miss[r["MODEL"].strip().upper()] += 1; how["тип не опознан"] += 1; continue
    how["по " + src] += 1
    ages[(y, r["AIRLINE_ID"], ic)].append(y - my)
out = {f"{y}|{a}|{i}": {"n": len(v), "age": round(sum(v) / len(v), 2)} for (y, a, i), v in ages.items()}
# Пропущенный год подачи B-43 (перевозчик не подал инвентарь за год, а тип у него летал до и после):
# возраст переносится из ближайшего года в пределах двух лет со сдвигом на разницу лет. Помечается.
have = collections.defaultdict(dict)
for k, v in out.items():
    y, a, i = k.split("|"); have[(a, i)][int(y)] = v
filled = 0
for (a, i), ser in have.items():
    for y in range(min(ser) - 2, max(ser) + 3):
        if y in ser or not (2006 <= y <= 2025): continue
        near = sorted((abs(y0 - y), y0) for y0 in ser if abs(y0 - y) <= 2 and "from" not in ser[y0])
        if not near: continue
        y0 = near[0][1]; v = ser[y0]
        if v["age"] + (y - y0) < 0: continue
        out[f"{y}|{a}|{i}"] = {"n": v["n"], "age": round(v["age"] + (y - y0), 2), "from": y0}; filled += 1
how["возраст перенесён из соседнего года"] = filled
json.dump({"ages": out, "how": dict(how), "unrecognized_top": miss.most_common(30)}, open(HERE / "ages.json", "w"), ensure_ascii=False, indent=0)
print(dict(how)); print(miss.most_common(15))
