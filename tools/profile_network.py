#!/usr/bin/env python3
"""Где уходит время сборки сети — на ВАШЕМ хранилище, без сервера.

Демо-хранилище в тестах не похоже на настоящее: в нём нет тарифов,
полигонов зон и закрытий, и узкое место там может быть не тем, что у вас.
Скрипт собирает ту же сеть, что витрина, два раза подряд (холодный и
тёплый прогон — второй показывает, что кэши работают), и печатает:

  * время на тип и на пару, число вызовов ядра;
  * двадцать пять функций, где ушло больше всего времени (cumulative);
  * двадцать пять функций с наибольшим собственным временем (tottime).

Запуск из корня репозитория:

    python3 tools/profile_network.py --airports FRA,BCN,LIS,MAD,FCO,ALA,DME,OVB \\
        --base FRA --types A320,A20N,B738 --month 7 > profile.txt

Пришлите profile.txt — по нему видно, что ускорять.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pathlib
import pstats
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import econ as E          # noqa: E402
from flightcostapp.network import fleet_from_core, form_network  # noqa: E402
from flightcostapp.store import Store       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/flightcost.db")
    ap.add_argument("--airports", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--types", default="A320")
    ap.add_argument("--month", type=int, default=7)
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args()
    store = Store(a.db)
    airports = [x.strip().upper() for x in a.airports.split(",") if x.strip()]
    calls = [0]
    detours: dict = {}          # как у сервера: обходы общие для типов
    real = E.route_economics

    def counted(*args, **kw):
        calls[0] += 1
        return real(*args, **kw)

    def one(ac):
        pairs = form_network(store, airports, base=a.base, aircraft=ac, as_of=a.as_of,
                             month=a.month, econ=counted, detour_cache=detours)
        ok = [p for p in pairs if p.status == "ok"]
        if ok:
            fleet_from_core(counted, store, ok[0].a, ok[0].b, aircraft=ac, as_of=a.as_of,
                            month=a.month, overrides=None, operator="*")
        return pairs

    print(f"аэропортов {len(airports)}, типов {len(a.types.split(','))}, месяц {a.month}")
    for run in ("холодный", "тёплый"):
        pr = cProfile.Profile()
        t0 = time.perf_counter()
        pr.enable()
        for ac in [x.strip().upper() for x in a.types.split(",") if x.strip()]:
            c0, t1 = calls[0], time.perf_counter()
            pairs = one(ac)
            n_ok = sum(1 for p in pairs if p.status == "ok")
            dt = time.perf_counter() - t1
            print(f"  {run:9} {ac:6} {dt:7.2f} с · пар {len(pairs)} (летает {n_ok}) · "
                  f"вызовов ядра {calls[0] - c0} · {dt / max(1, calls[0] - c0) * 1000:.0f} мс на вызов")
        pr.disable()
        print(f"  {run}: всего {time.perf_counter() - t0:.2f} с\n")
        if run == "холодный":
            continue
        for key in ("cumulative", "tottime"):
            s = io.StringIO()
            pstats.Stats(pr, stream=s).strip_dirs().sort_stats(key).print_stats(25)
            print(f"===== {key} =====")
            print("\n".join(s.getvalue().splitlines()[4:]))


if __name__ == "__main__":
    main()
