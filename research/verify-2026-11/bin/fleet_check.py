"""Сверка модели на сети перевозчика: T-100 (сеть) -> калькулятор -> суммы по типам.

    python3 research/verify-2026-11/bin/fleet_check.py F9 2.47 \
        --t100 data/raw/t100/T_T100_SEGMENT_ALL_CARRIER.csv \
        --types data/raw/form41/L_AIRCRAFT_TYPE.csv --db data/flightcost.db --out out/

Каждая пара × тип ВС считается один раз с фактическими креслами и
загрузкой (T-100, класс F), цена топлива — из отчёта перевозчика (USD за
галлон), курс — среднегодовой ЕЦБ. Результат умножается на число рейсов.
Запускать из корня репозитория: пути к полигонам зон в коде относительные.
"""
import argparse, collections, csv, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, ROOT)
from flightcostapp import bench, econ          # noqa: E402
from flightcostapp.store import Store          # noqa: E402

USD_PER_EUR_2025 = 1.13      # ЕЦБ, среднее за 2025 год


def network(path, carrier, icao_of):
    g = collections.defaultdict(lambda: [0.0] * 5)    # рейсы, кресла, пассажиры, колодки, воздух (мин)
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["UNIQUE_CARRIER"] != carrier or r["CLASS"] != "F":
            continue
        d = float(r["DEPARTURES_PERFORMED"] or 0)
        if d <= 0:
            continue
        a = g[(r["ORIGIN"], r["DEST"], icao_of(r["AIRCRAFT_TYPE"]))]
        a[0] += d; a[1] += float(r["SEATS"]); a[2] += float(r["PASSENGERS"])
        a[3] += float(r["RAMP_TO_RAMP"]); a[4] += float(r["AIR_TIME"])
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carrier"); ap.add_argument("fuel_usd_gal", type=float)
    ap.add_argument("--t100", required=True); ap.add_argument("--types", required=True)
    ap.add_argument("--db", default="data/flightcost.db"); ap.add_argument("--out", default=".")
    a = ap.parse_args()
    os.chdir(ROOT)
    types = {r["Code"]: r["Description"] for r in csv.DictReader(open(a.types, encoding="utf-8-sig"))}
    icao_of = lambda c: bench.CODE_OVERRIDES[c][0] if c in bench.CODE_OVERRIDES else (bench.icao_of(types.get(c, "")) or "?" + c)
    st = Store(a.db)
    fuel = a.fuel_usd_gal / bench.KG_PER_GAL / USD_PER_EUR_2025
    by = collections.defaultdict(lambda: collections.defaultdict(float))
    fail = collections.Counter()
    for (o, d, t), (dep, seats, pax, ramp, air) in network(a.t100, a.carrier, icao_of).items():
        try:
            r = econ.route_economics(st, o, d, aircraft=t, seats=max(1, round(seats / dep)),
                                     load_factor=max(min(pax / seats, 1.0), 0.05) if seats else 0.8,
                                     fuel_eur_per_kg=fuel)
        except Exception as e:                       # noqa: BLE001
            fail[f"{t}: {type(e).__name__}: {str(e)[:60]}"] += dep
            continue
        b = by[t]
        for k, v in r.cost.items():
            b[k] += v * dep * USD_PER_EUR_2025
        taxi = next((x.value for x in r.trace if x.label == "Руление"), 26.0)
        b["fuel_kg"] += r.fuel_kg * dep; b["block_h"] += r.block_h * dep; b["taxi_h"] += taxi / 60 * dep
        b["act_block_h"] += ramp / 60; b["act_air_h"] += air / 60
        b["dep"] += dep; b["seats"] += seats; b["pax"] += pax
    os.makedirs(a.out, exist_ok=True)
    json.dump({"by_type": by, "fail": fail, "usd_per_eur": USD_PER_EUR_2025, "fuel_usd_gal": a.fuel_usd_gal},
              open(os.path.join(a.out, f"{a.carrier}.json"), "w"), ensure_ascii=False, indent=1)
    for t, v in sorted(by.items()):
        print(f"{t:5} рейсов {v['dep']:9,.0f}  блок-ч модель {v['block_h']:10,.0f}  факт {v['act_block_h']:10,.0f}")
    if fail:
        print("не посчитано:", dict(fail))


if __name__ == "__main__":
    main()
