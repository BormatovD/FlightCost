"""Калибровка годового коэффициента налёта по Form 41 T-2 (план network-calc, 09.11.2026).

Факт: блок-часы ÷ дни в парке по перевозчику и типу за год (T-2, все классы
обслуживания). Модель: пиковый день по формуле окна при средней длине плеча
перевозчика на типе (flightcostapp.netutil.peak_day). Коэффициент = факт ÷ пиковый
день. Перевозчики разложены по типу сети; Frontier и Southwest в калибровку не
входят — на них проверка. Региональные (capacity purchase) не берутся: дни в парке
у них учитываются иначе, коэффициенты 0,2–0,7 — артефакт учёта.

    python3 research/network-2026-10/bin/util_calib.py --db data/flightcost.db [--year 2025]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from flightcostapp.netutil import CLASS_OF, LONG_H, peak_day  # noqa: E402

HELD_OUT = {"F9", "WN"}
MIN_DAYS = 20_000          # от ~55 бортов в среднем за год на типе


def rows(db: str, year: str):
    c = sqlite3.connect(db)
    agg = collections.defaultdict(lambda: collections.defaultdict(float))
    for k, v in c.execute("SELECT key, value FROM facts WHERE domain = 'fleet_benchmark' "
                          "AND key LIKE 'F41/T2/%' AND value IS NOT NULL"):
        p = k.split("/")
        if len(p) == 6 and p[2].startswith(year):
            agg[(p[3], p[4])][p[5]] += float(v)
    for (cc, ty), d in agg.items():
        if cc not in CLASS_OF or d["days_assigned"] < MIN_DAYS or d["departures"] <= 0:
            continue
        b = d["ramp_hours"] / d["departures"]
        daily = d["ramp_hours"] / d["days_assigned"]
        pk = peak_day(b)
        yield cc, ty, ("longhaul" if b >= LONG_H else CLASS_OF[cc]), b, daily, daily / pk if pk else None, d["days_assigned"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/flightcost.db")
    ap.add_argument("--year", default="2025")
    a = ap.parse_args(argv)
    rs = [r for r in rows(a.db, a.year) if r[5]]
    print(f"{'перев.':6} {'тип':4} {'класс':9} {'плечо':>6} {'ч/сут':>6} {'коэф':>5} {'бортов':>6}")
    for r in sorted(rs, key=lambda r: (r[2], -r[6])):
        print(f"{r[0]:6} {r[1]:4} {r[2]:9} {r[3]:6.2f} {r[4]:6.1f} {r[5]:5.2f} {r[6] / 365:6.0f}"
              + ("  ← проверка" if r[0] in HELD_OUT else ""))
    print("\nкласс     коэф (медиана по бортам, без F9/WN)   разброс")
    for cl in sorted({r[2] for r in rs}):
        xs = [(r[5], r[6]) for r in rs if r[2] == cl and r[0] not in HELD_OUT]
        if not xs:
            continue
        flat = sorted(x for x, w in xs for _ in range(int(w // 1000)))
        print(f"{cl:9} {statistics.median(flat):.2f}  ({len(xs)} типов)"
              f"                    {min(x for x, _ in xs):.2f}–{max(x for x, _ in xs):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
