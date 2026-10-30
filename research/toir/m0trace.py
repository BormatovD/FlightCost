"""Журнал моих шагов (m0) по Form 41 — в том же формате, что у исследователей."""
import json, hashlib, pathlib, statistics as st
from collections import defaultdict
RAW = pathlib.Path(__file__).resolve().parents[1] / "e2r/data/raw/form41"
R = json.load(open("f41_rows.json"))
T = []; n = [0]
def add(kind, parents=(), **kw):
    n[0] += 1; i = f"m0-{n[0]:03d}"
    T.append({"id": i, "kind": kind, "parents": list(parents), **kw}); return i
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
src = {}
for f, what in [("p52.csv", "Schedule P-5.2, 2025 Q1–Q4 — расходы по типу"),
                ("t2.csv", "Schedule T-2, 2025 — блок-часы, вылеты, дни в парке"),
                ("types.csv", "L_AIRCRAFT_TYPE — расшифровка кодов типа")]:
    src[f] = add("open", url="https://www.transtats.bts.gov/", title=f"BTS TranStats: {what}",
                 locator=f"локальная выгрузка data/raw/form41/{f}, sha256 {sha(RAW/f)}",
                 note="Выгрузка скачана вручную с TranStats (форма ASP.NET), та же, что в бенчмарке сайта")
d1 = add("infer", [src["t2.csv"]], note="T-2 подаёт строки по классам обслуживания: Z = K + V, K = F + G. "
         "У Southwest 2025Q1 тип 612 строки F и K совпадают до единицы (288 262 блок-ч) — сложить всё = удвоить. "
         "Решение: брать самый сводный класс, поданный в регионе (как parsers/form41.py)", value="класс Z")
d2 = add("infer", [src["p52.csv"], src["t2.csv"]], note="Только пассажирская компоновка (AIRCRAFT_CONFIG = 1): "
         "грузовые и комби имеют другой профиль ТОиР и другой налёт", value="config 1")
d3 = add("infer", [src["p52.csv"]], note="P-5.2 в тысячах USD: без пересчёта медиана ТОиР ~1 USD/ч (как и решает bench.scales)",
         value="×1000")
d4 = add("infer", [src["types.csv"]], note="Код 699 «A321Neoxlr» по данным — парк A321ceo (AA 218, DL 125 бортов); "
         "neo — код 721. Исключение из bench.CODE_OVERRIDES", value="699 → A321")
d5 = add("infer", [d1, d2, d3, d4], note="ТОиР на блок-час = Σ кварталов (52990 «итого ТОиР», без него 52780+52796) / Σ блок-часов T-2 "
         "по кварталам, где есть и P-5.2, и T-2. Планер = труд+подряд+материалы+резервы+капремонт планера, двигатели — то же; "
         "сумма планер+двигатели+interchange сверена с 52780 (расхождение ≤0,1% во всех строках)")
by = defaultdict(list)
for r in R:
    i = add("extract", [d5], carrier=r["carrier"], locator=f"{r['carrier']} × {r['icao']}, кварталов {r['quarters']}",
            value=f"{r['total_bh']} USD/блок-ч (прямой {r['direct_bh']}, накладные {r['burden_bh']}; планер {r['airframe_bh']}, двигатели {r['engine_bh']})",
            note=f"бортов ≈{r['aircraft']}, сектор {r['sector_h']} ч, блок-часов {r['block_h']}")
    r["_id"] = i
    if r["aircraft"] >= 5: by[r["carrier"]].append(r)
for c, rs in by.items():
    if len(rs) < 3: continue
    sh = [x["airframe_bh"] / max(x["airframe_bh"] + x["engine_bh"], 1) for x in rs]
    bu = [x["burden_bh"] / max(x["direct_bh"], 1) for x in rs]
    tot = [x["total_bh"] for x in rs]
    flat_split = max(sh) - min(sh) < 0.03 and max(bu) - min(bu) < 0.03
    flat_tot = max(tot) / min(tot) < 1.35
    if flat_split:
        add("infer", [x["_id"] for x in rs], carrier=c,
            value="распределено формулой" + (" (и итог тоже)" if flat_tot else " (доли; итог различается)"),
            note=f"У {len(rs)} типов доля планера {min(sh):.2f}–{max(sh):.2f} и накладные/прямой {min(bu):.2f}–{max(bu):.2f}: "
                 "так не бывает при учёте по факту — разные типы, двигатели и возраст. "
                 + ("Итог тоже почти одинаков (" + f"{min(tot)}–{max(tot)}" + " USD/ч): ставка по типу не измерена, а разнесена. "
                    if flat_tot else "Итог различается — разбивка планер/двигатели условна, итог может быть по факту. ")
                 + "Нужна учётная политика перевозчика (исследователь)")
add("infer", [src["t2.csv"]], carrier="MQ", value="«бортов» по T-2 — только ориентир",
    note="Число бортов считается как дни в парке (поле 810) / дни квартала. У Envoy E175 выходит ≈399 бортов при парке около 170 "
         "(исследователь a3), у SkyWest E175 ≈266 при большем фактическом парке. Поле 810 подаётся неоднородно, поэтому "
         "веса при сведении по типу — блок-часы, а не борта")
pathlib.Path("trace").mkdir(exist_ok=True)
with open("trace/m0.jsonl", "w") as f:
    for t in T: f.write(json.dumps(t, ensure_ascii=False) + "\n")
print(len(T), "steps")
