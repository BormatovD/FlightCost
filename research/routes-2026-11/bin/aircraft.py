"""Лучший из доступных сегодня типов на каждую пару рейтинга — расчётом калькулятора FlightCostApp.

Кандидаты — типы «в серии» из data/types/availability.yaml: узкофюзеляжные A320neo, A321neo, 737 MAX 8/9, A220-300;
для пар дальше 4 500 км — A350-900 и 787-9. Пары с российским аэропортом — только типы, доступные российским
перевозчикам (Ту-214); если калькулятор тип не считает, так и пишем. Критерий — безубыточный тариф на пассажира
при загрузке 80 %, июль, среди типов, которые выполнимы (масса, дальность, полоса).

    python3 research/routes-2026-11/bin/aircraft.py <база калькулятора .db> [N на регион]
"""
import json, pathlib, sys
import yaml

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from flightcostapp.store import Store  # noqa: E402
from flightcostapp import serve as S  # noqa: E402
from flightcostapp.econ import route_economics  # noqa: E402

NB = ["A20N", "A21N", "B38M", "B39M", "BCS3"]
WB = ["A359", "B789", "A21N"]
RU = ["T204", "SU95", "MS21"]
IN_ICAO = None
IATA = {}


def iata_map(st):
    """Справочник аэропортов калькулятора держит ключ по коду ИАТА; ИКАО — внутри значения."""
    m = {}
    for k, vt in st.db.execute("SELECT key, value_text FROM facts WHERE domain='airport'"):
        p = (vt or "").split("|")
        if len(p) > 1 and len(p[1]) == 4:
            m.setdefault(p[1], k)
    return m


def best(st, c, a, b, types):
    res = []
    for ac in types:
        try:
            j = S.result_json(route_economics(st, IATA.get(a, a), IATA.get(b, b), aircraft=ac, load_factor=0.8,
                                              month=7))
        except Exception as exc:                      # noqa: BLE001
            res.append({"type": ac, "ok": False, "why": str(exc)[:160]})
            continue
        an = j["answer"]
        lim = [x.get("text", "") for x in (an.get("feasibility") or {}).get("limits", [])]
        res.append({"type": ac, "ok": bool(an.get("feasible")), "fare": an.get("breakeven_fare_eur"),
                    "cost": an.get("cost_total"), "pax": (an.get("feasibility") or {}).get("pax"), "why": "; ".join(lim)[:200]})
    ok = [r for r in res if r["ok"] and r.get("fare")]
    return (min(ok, key=lambda r: r["fare"]) if ok else None), res


def main(db, top=30):
    st = Store(db)
    global IATA
    IATA = iata_map(st)
    c = S.Context(st, yaml.safe_load(open(ROOT / "flightcostapp" / "registry.yaml")))
    rt = json.loads((HERE / "out" / "rating.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(HERE))
    from rating import IN_ICAO as ICAO
    out = {"method": "безубыточный тариф на пассажира, загрузка 80 %, июль; калькулятор FlightCostApp", "pairs": {}}
    for reg, rows in (("eu", rt["europe"]["pairs"][:top]), ("eul", rt["europe"]["long_haul"][:10]),
                      ("in", rt["india"]["pairs"][:top])):
        for r in rows:
            a, b = (r["a"], r["b"]) if reg != "in" else (ICAO.get(r["a"]), ICAO.get(r["b"]))
            if not a or not b:
                continue
            ru = any(x[:1] == "U" for x in (a, b))
            types = RU if ru else (WB if reg == "eul" else NB)
            bst, res = best(st, c, a, b, types)
            out["pairs"][r["pair"]] = {"region": reg, "russia": ru, "best": bst, "all": res}
            print(reg, r["pair"], bst and (bst["type"], round(bst["fare"])), "| " + ", ".join(
                f"{x['type']}:{round(x['fare']) if x.get('fare') and x['ok'] else 'нельзя'}" for x in res))
    (HERE / "out" / "aircraft.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30)
