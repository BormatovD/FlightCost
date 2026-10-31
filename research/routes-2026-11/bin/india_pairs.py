"""Пары городов Индии, внутренние рейсы, из сборки DGCA (github.com/Vonter/india-aviation-traffic, ODbL) →
out/pairs_in.json: пассажиры за 2024 и 2025 годы и за последние 12 месяцев, оба направления.

    python3 research/routes-2026-11/bin/india_pairs.py <city.csv>
"""
import csv, json, pathlib, sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parents[1]
MONTHS = [f"{i:02d}" for i in range(1, 13)]
ALLMON = set()
# С 2026 года DGCA пишет город с аэропортом в скобках (MUMBAI (NAVI MUMBAI), GOA (MOPA, NORTH GOA)): пара городов —
# по городу, оба аэропорта вместе; у Раджкота новый аэропорт назван по месту (HIRASAR (RAJKOT)).
SPECIAL = {"HIRASAR (RAJKOT)": "RAJKOT"}
# Переименования в рядах DGCA: город — одним именем за все годы (иначе рост пары — артефакт смены названия).
ALIAS = {"TRIVANDRUM": "THIRUVANANTHAPURAM", "VISAKHAPATNAM": "VISHAKHAPATNAM", "VIJAYAWADA": "VIJAYWADA",
         "TIRUCHIRAPALLY": "TIRUCHIRAPPALLI", "NASIK": "NASHIK", "SHOLAPUR": "SOLAPUR", "SIMLA": "SHIMLA",
         "HISSAR": "HISAR", "BHATINDA": "BATHINDA", "KALABURAGI": "GULBARGA", "DABOLIM": "GOA", "MOPA, GOA": "GOA",
         "MOPA": "GOA", "PRAYAGRAJ": "ALLAHABAD", "HIRASAR": "RAJKOT"}


def city(x):
    x = x.strip().upper()
    x = SPECIAL.get(x, x.split(" (")[0])
    for suf in (" INTERNATIONAL AIRPORT", " AIRPORT"):
        if x.endswith(suf):
            x = x[: -len(suf)]
    return ALIAS.get(x, x).title()


def main(path):
    m = defaultdict(lambda: defaultdict(float))       # (A, B) -> "ГГГГ-ММ" -> пасс.
    seen = defaultdict(set)
    for r in csv.DictReader(open(path, encoding="utf-8")):
        a, b = city(r["City1"]), city(r["City2"])
        key, mon = tuple(sorted((a, b))), f"{r['Year']}-{r['Month']}"
        pax = float(r["PaxToCity2"] or 0) + float(r["PaxFromCity2"] or 0)
        # строка (A, B) и (B, A) — одни и те же рейсы, увиденные с двух концов: берём одну
        src = (r["City1"], r["City2"], mon)
        if src in seen[key] or (r["City2"], r["City1"], mon) in seen[key]:
            continue
        seen[key].add(src)
        m[key][mon] += pax
    last = max(mon for v in m.values() for mon in v)
    global ALLMON
    ALLMON = {mon for v in m.values() for mon in v}
    y, mm = int(last[:4]), int(last[5:])
    l12 = {f"{y - (mm - k <= 0)}-{(mm - k - 1) % 12 + 1:02d}" for k in range(12)}
    p12 = {f"{int(x[:4]) - 1}{x[4:]}" for x in l12}
    out = {}
    for (a, b), v in m.items():
        row = {yy: round(sum(x for mon, x in v.items() if mon.startswith(yy))) for yy in ("2023", "2024", "2025")}
        # в ряду DGCA нет мая 2024: рост 2025 к 2024 — по месяцам, которые есть в обоих годах
        common = [mm for mm in MONTHS if f"2024-{mm}" in ALLMON and f"2025-{mm}" in ALLMON]
        row["g25"] = [round(sum(v.get(f"2024-{mm}", 0) for mm in common)), round(sum(v.get(f"2025-{mm}", 0) for mm in common))]
        row["l12"] = round(sum(v.get(x, 0) for x in l12))
        row["p12"] = round(sum(v.get(x, 0) for x in p12))
        if max(row["l12"], row["2025"]) >= 1000:
            out[f"{a}-{b}"] = row
    doc = {"source": "DGCA, внутренние рейсы по парам городов, помесячно; сборка github.com/Vonter/india-aviation-"
                     "traffic (ODbL 1.0)", "last_month": last, "pairs": out}
    (HERE / "out" / "pairs_in.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    top = sorted(out.items(), key=lambda kv: -kv[1]["l12"])[:10]
    print(len(out), "пар; последний месяц", last)
    for k, v in top:
        print(k, v)


if __name__ == "__main__":
    main(sys.argv[1])
