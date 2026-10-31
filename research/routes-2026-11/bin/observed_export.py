"""Кто летает на парах рейтинга: свёртка наблюдений ADS-B из своей базы.

Запуск из корня проекта, на любой машине, где копились наблюдения:

    python3 research/routes-2026-11/bin/observed_export.py data/flightcost.db
    python3 research/routes-2026-11/bin/observed_export.py --airports   # список для забора

Пишет `~/observed_pairs.csv` — уже СВЁРНУТОЕ: пара, перевозчик (три буквы
позывного), тип, рейсов, сутки наблюдения. Ни адресов бортов, ни
позывных целиком — только счёт. Сырая база никуда не уезжает.

Сутки считаются по меткам забора: пара видна в те сутки, когда хотя бы
один её конец был забран целиком (вылеты и прилёты). Рейс, увиденный с
обоих концов, в базе один — дедупликация по (вид, ключ, борт, момент).
"""

from __future__ import annotations

import csv
import json
import pathlib
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent.parent
TOP = {"europe": 20, "long_haul": 10, "india": 20}


def pairs() -> list[tuple[str, str, str]]:
    r = json.loads((HERE / "out" / "rating.json").read_text("utf-8"))
    out = []
    for reg, rows in (("europe", r["europe"]["pairs"]),
                      ("long_haul", r["europe"]["long_haul"]),
                      ("india", r["india"]["pairs"])):
        for p in sorted(rows, key=lambda p: p["rank"])[:TOP[reg]]:
            a, b = p["icao"] if reg == "india" else (p["a"], p["b"])
            out.append((reg, *sorted((a, b))))
    return out


def cover(ps) -> list[str]:
    """Наименьший (жадно) список аэропортов, чей забор покрывает все пары."""
    left, chosen = [set(p[1:]) for p in ps], []
    while left:
        a = Counter(x for p in left for x in p).most_common(1)[0][0]
        chosen.append(a)
        left = [p for p in left if a not in p]
    return chosen


def main(argv):
    ps = pairs()
    if argv[:1] == ["--airports"]:
        for reg in ("europe", "india"):
            sub = [p for p in ps if (p[0] == "india") == (reg == "india")]
            print(f"{reg}: " + ",".join(cover(sub)))
        return 0
    db = sqlite3.connect(argv[0] if argv else "data/flightcost.db")

    # сутки, когда аэропорт забран целиком
    full = defaultdict(set)
    kinds = defaultdict(set)
    for key, day in db.execute(
            "SELECT key, observed_at FROM observations WHERE kind = '_fetched'"):
        a, _, k = (key or "").partition("/")
        kinds[(a, day[:10])].add(k)
    for (a, day), ks in kinds.items():
        if {"departure", "arrival"} <= ks:
            full[a].add(day)

    # тип борта — из строки времени того же рейса (тот же борт и момент)
    typ = {}
    for key, ref, at in db.execute(
            "SELECT key, ref, observed_at FROM observations "
            "WHERE kind IN ('contact_time', 'airborne_time')"):
        typ[(ref, at)] = key.split("/", 1)[0]

    want = {(a, b): reg for reg, a, b in ps}
    cnt = Counter()
    for key, ref, at, note in db.execute(
            "SELECT key, ref, observed_at, note FROM observations "
            "WHERE kind = 'frequency'"):
        pair = key.split("/", 1)[0]
        a, _, b = pair.partition("-")
        k = tuple(sorted((a, b)))
        if k not in want:
            continue
        airline = (note or "")[:3].upper() if (note or "")[:3].isalpha() else "?"
        cnt[(k, airline, typ.get((ref, at), "?"))] += 1

    out = pathlib.Path.home() / "observed_pairs.csv"
    seen = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "a", "b", "days", "airline", "type", "flights"])
        for (reg, a, b) in ps:
            days = len(full[a] | full[b])
            rows = [(al, t, n) for (k, al, t), n in cnt.items() if k == (a, b)]
            seen += bool(rows)
            if not rows:
                w.writerow([reg, a, b, days, "", "", 0])
            for al, t, n in sorted(rows, key=lambda x: -x[2]):
                w.writerow([reg, a, b, days, al, t, n])
            print(f"{reg:9} {a}-{b}  суток {days:3}  рейсов "
                  f"{sum(r[2] for r in rows):5}  перевозчиков "
                  f"{len({r[0] for r in rows})}")
    print(f"\nпар с наблюдениями: {seen} из {len(ps)}; файл {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
