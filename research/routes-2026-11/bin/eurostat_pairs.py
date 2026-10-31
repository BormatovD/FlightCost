"""Пары аэропортов Европы из выгрузок Eurostat avia_par_<страна> (TSV, сжатые или нет) → out/pairs_eu.json.

Пара публикуется обеими странами: берём среднее двух отчётов, если оба есть (как flightcostapp.traffic).
Годовые суммы по месяцам: пассажиры перевезённые (PAS_CRD), кресла (ST_PAS), рейсы (CAF_PAS); год берётся,
только если в нём 12 месяцев с пассажирами. Сами выгрузки в репозиторий не кладутся (папку передаёт владелец).

    python3 research/routes-2026-11/bin/eurostat_pairs.py <папка с avia_par_*.tsv[.gz]>
"""
import gzip, json, pathlib, re, sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parents[1]
MEAS = {"PAS_CRD": 0, "ST_PAS": 1, "CAF_PAS": 2}


def text(p):
    b = p.read_bytes()
    return (gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b).decode("utf-8-sig")


def num(s):
    s = s.strip().split(" ")[0]
    return None if s in (":", "") else float(s)


def main(src):
    rep = defaultdict(lambda: defaultdict(lambda: [None, None, None]))   # (reporter, A, B) -> month -> [pax, seats, fl]
    for p in sorted(pathlib.Path(src).glob("*avia_par_*")):
        lines = text(p).splitlines()
        head = [h.strip() for h in lines[0].split("\t")]
        months = [(i, h) for i, h in enumerate(head) if re.fullmatch(r"\d{4}-\d{2}", h)]
        for l in lines[1:]:
            cells = l.split("\t")
            freq, unit, meas, pair = cells[0].split(",")
            if freq != "M" or meas not in MEAS:
                continue
            m = re.fullmatch(r"([A-Z]{2})_([A-Z]{4})_([A-Z]{2})_([A-Z]{4})", pair)
            if not m:
                continue
            a, b = sorted((m.group(2), m.group(4)))
            for i, mon in months:
                v = num(cells[i]) if i < len(cells) else None
                if v is not None:
                    rep[(m.group(1), a, b)][mon][MEAS[meas]] = v
    pairs = defaultdict(lambda: defaultdict(list))    # (A, B) -> year -> [ [pax, seats, fl] по отчётчикам ]
    for (r, a, b), mons in rep.items():
        years = defaultdict(list)
        for mon, v in mons.items():
            years[mon[:4]].append(v)
        for y, vs in years.items():
            if sum(1 for v in vs if v[0]) == 12:
                pairs[(a, b)][y].append([sum(v[k] or 0 for v in vs) for k in range(3)])
    out = {}
    for (a, b), ys in pairs.items():
        row = {}
        for y, reps in ys.items():
            pax = sum(x[0] for x in reps) / len(reps)
            seats = sum(x[1] for x in reps) / len(reps)
            fl = sum(x[2] for x in reps) / len(reps)
            row[y] = {"pax": round(pax), "seats": round(seats) or None, "flights": round(fl) or None,
                      "reporters": len(reps), "spread": round(abs(reps[0][0] - reps[-1][0]) / pax, 3) if pax else None}
        out[f"{a}-{b}"] = row
    last = max(m for k in rep.values() for m in k)
    doc = {"source": "Eurostat avia_par_* (PAS_CRD, ST_PAS, CAF_PAS), месячные данные; пара — среднее отчётов обеих "
                     "стран", "last_month": last, "pairs": out}
    (HERE / "out" / "pairs_eu.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(len(out), "пар; последний месяц", last, "; с 2024:", sum(1 for v in out.values() if "2024" in v))


if __name__ == "__main__":
    main(sys.argv[1])
