"""Оценка сборов по региону для аэропортов без тарифа → data/charges/_regional.yaml.

Берёт контрольные обороты A320 (turnaround.json, bin/turnaround.py) по всем
тарифам с документом и считает медиану по региону. Калькулятор умножает на
отношение «медиана региона / прежняя оценка» ту же формулу 9,5·MTOW + 11·пасс.:
форма остаётся, уровень — по региону (решение 234).

Из медиан исключены обороты, где не начислена посадка или пассажирский сбор
(тариф заведён не целиком): они занижены не на шум, а на главную статью.

    python3 research/charges-2026-10/bin/regional.py
"""
import json
import pathlib
import statistics
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TURN = json.loads((HERE.parent / "turnaround.json").read_text(encoding="utf-8"))["airports"]
MTOW, PAX = 78, 148
BASE = 9.5 * MTOW + 11.0 * PAX            # прежняя оценка за оборот одного аэропорта, EUR

# Регион — по префиксу ИКАО (две буквы, затем одна): так покрывается и аэропорт,
# которого нет среди тарифов. Порядок важен: сначала двухбуквенные.
REGIONS = {
    "europe": {"name": "Европа", "prefixes": ["GC", "B", "E", "L"]},
    "russia_cis": {"name": "Россия и СНГ", "prefixes": ["U"]},
    "india": {"name": "Индия", "prefixes": ["VA", "VE", "VI", "VO"]},
    "asia_gulf": {"name": "Азия и Ближний Восток", "prefixes": ["O", "R", "Z", "VH", "VM", "VT", "VV", "VD", "VL",
                                                                   "VY", "VG", "VN", "VR", "VC", "W"]},
    "africa": {"name": "Африка", "prefixes": ["D", "F", "G", "H"]},
}
PARTIAL = {"DAAG", "DGAA"}                 # найдена только посадка, пассажирского сбора нет


def region(icao: str) -> str | None:
    for two in (True, False):
        for code, r in REGIONS.items():
            for p in r["prefixes"]:
                if (len(p) == 2) == two and icao.startswith(p):
                    return code
    return None


def main():
    by = {}
    for icao, t in TURN.items():
        if not t.get("eur") or icao in PARTIAL or "landing" in (t.get("not_charged") or []):
            continue
        r = region(icao)
        if r:
            by.setdefault(r, []).append((icao, t["eur"]))
    allv = [v for xs in by.values() for _, v in xs]
    out = {"method": ("Медиана контрольного оборота A320 (78 т, 148 пасс., июль; из Франкфурта, для российских "
                      "прейскурантов — внутренний рейс из Шереметьева) по тарифам с документом, research/charges-"
                      "2026-10. k = медиана / (9,5·78 + 11·148); оценка оборота аэропорта без тарифа = "
                      "k · (9,5·MTOW + 11·пасс.). Курсы — приблизительные. Решение 234."),
           "built": str(date.today()), "base_eur": BASE,
           "world": {"name": "Мир (вне регионов)", "k": round(statistics.median(allv) / BASE, 3),
                     "median_eur": round(statistics.median(allv)), "n": len(allv)},
           "regions": {}}
    for code, r in REGIONS.items():
        xs = sorted(by.get(code, []), key=lambda x: x[1])
        if not xs:
            continue
        med = statistics.median(v for _, v in xs)
        out["regions"][code] = {"name": r["name"], "prefixes": r["prefixes"], "k": round(med / BASE, 3),
                                "median_eur": round(med), "n": len(xs),
                                "range_eur": [xs[0][1], xs[-1][1]], "airports": [i for i, _ in xs]}
    import yaml
    dst = ROOT / "data" / "charges" / "_regional.yaml"
    dst.write_text("# Сгенерировано research/charges-2026-10/bin/regional.py — руками не править.\n"
                   + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    for code, r in out["regions"].items():
        print(f"{code:11s} k={r['k']:.3f} медиана {r['median_eur']} EUR, n={r['n']}")
    print("world", out["world"])


if __name__ == "__main__":
    main()
