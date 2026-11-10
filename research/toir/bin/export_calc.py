"""Ставки ТОиР статьи — в калькулятор: data/maintenance/_toir.yaml (план toir-calc, 10.11.2026).

Берёт итог модели final_ppi_main.json (панель Form 41 1991–2025, прямые затраты,
USD 2025 за блок-час, индекс PPI): ставку зрелого борта (12 лет) и среднюю за срок
службы по типу, кривую возраста по классу, эластичность по длине сектора. Типы
меньше чем с MIN_N точками (5 бортов × кварталы) не берутся — у них полоса шире
самой ставки. Новым типам без истории в США назначается предшественник: его
ставка и кривая возраста, с пометкой.

    python3 research/toir/bin/export_calc.py
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "maintenance" / "_toir.yaml"
MIN_N = 8
CLS = {"узкофюзеляжные": "narrow", "широкофюзеляжные": "wide", "региональные": "regional"}
# Новые типы без истории в Form 41 → ближайший предшественник того же семейства.
SUCCESSOR = {
    "A20N": "A320", "A19N": "A319", "B37M": "B737", "B3XM": "B739", "A339": "A333", "A338": "A332",
    "B78X": "B788", "B779": "B77W", "B748": "B744", "B77L": "B772", "E290": "E190", "E295": "E190",
    "E195": "E190", "E275": "E75L", "AT72": "AT76", "CRJX": "CRJ9", "A35K": "A332",
}
GROWTH = 0.03
# Новый тип против предшественника в одном возрасте — пары панели (pairs: B38M/B738 0,69, B39M/B739 0,64,
# A21N/A321 1,11). Медиана — к ставке предшественника; у типов с другими двигателями того же
# поколения (LEAP, GTF) — та же поправка, у «старых» наследников (AT72, B748, B77L, E195…) — без неё.          # индекс ТОиР, в год (статья: +3 %, а не каталог 6–9 %)


def main() -> int:
    m = json.loads((HERE / "final_ppi_main.json").read_text("utf-8"))
    types = {}
    for icao, t in sorted(m["types"].items()):
        if t["n"] < MIN_N:
            continue
        types[icao] = {"cls": CLS[t["cls"]], "mature_usd_bh": round(t["mature"]), "life_usd_bh": round(t["life"]),
                       "lo": round(t["lo"]), "hi": round(t["hi"]), "n": t["n"], "carriers": t["carriers"],
                       "ages": [round(t["age_lo"], 1), round(t["age_hi"], 1)], "years": t["years"],
                       "young_only": bool(t["young_only"])}
    import statistics
    ratios = [p["ratio_same_age"] for p in m.get("pairs", []) if p.get("ratio_same_age")]
    r_new = round(statistics.median(ratios), 2) if ratios else 1.0
    NEW_GEN = {"A20N", "A19N", "B37M", "B3XM", "A339", "A338", "B78X", "B779", "E290", "E295", "E275", "A35K", "CRJX"}
    succ = {k: {"base": v, "ratio": r_new if k in NEW_GEN else 1.0}
            for k, v in SUCCESSOR.items() if v in types and k not in types}
    doc = {
        "method": ("Прямые затраты на ТОиР перевозчиков США (Form 41), USD 2025 за блок-час, без накладных; модель "
                   "тип + перевозчик + возраст + длина сектора по панели 1991–2025 (research/toir). mature — борт 12 "
                   "лет; life — средняя за срок службы; shape — множитель возраста к зрелой ставке по классу; "
                   "cycle_share — доля цикловой части на опорном секторе класса, из эластичности ставки по длине "
                   "сектора; growth — индекс ТОиР в год. Типы меньше чем с 8 точками не взяты."),
        "source": "/ru/research/toir",
        "usd_year": 2025, "growth": GROWTH,
        "cycle_share": round(-m["sector_elasticity"], 3),
        "sector_ref": {CLS[k]: v for k, v in m["sector_ref"].items()},
        "life": {CLS[k]: round(v, 3) for k, v in m["life"].items()},
        "shape": {CLS[k]: {int(a): round(x, 3) for a, x in v.items()} for k, v in m["shape"].items()},
        "types": types,
        "successors": succ,
        "successor_pairs": [{"new": p["new"], "old": p["old"], "ratio_same_age": round(p["ratio_same_age"], 2)}
                            for p in m.get("pairs", []) if p.get("ratio_same_age")],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("# Сгенерировано research/toir/bin/export_calc.py — руками не править.\n"
                   + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), "utf-8")
    print(f"{OUT.relative_to(ROOT)}: типов {len(types)}, наследников {len(succ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
