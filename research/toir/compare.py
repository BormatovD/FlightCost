"""Этап 2: факт по отчётам авиакомпаний против прогноза модели 2 (Form 41) для того же парка, возраста и сектора.
Сравнение в USD 2025 на блок-час. Прогноз — прямой ТОиР Form 41 (с собственным трудом); рядом — без труда (×(1−0,182))."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); from common import CLASS
M = json.load(open(HERE / "model2_ppi.json")); FX = json.load(open(HERE / "fx.json")); IX = json.load(open(HERE / "index.json"))
LAB = 0.182
BINS = list(range(0, 26, 2)) + [26]; binof = lambda a: max(lo for lo in BINS if a >= lo)
def ppi(y):
    w = IX["wps5541_jun"].get(str(y)) or 100.0 * IX["pcu488190_jun"][str(y)] / IX["pcu488190_jun"]["2009"]
    return IX["wps5541_jun"]["2025"] / w
def fx(cur, fy, fye):
    if cur == "USD": return 1.0
    end_m = int(fye[:2]); months = [((fy if m <= end_m else fy - 1), m) for m in list(range(end_m + 1, 13)) + list(range(1, end_m + 1))]
    if cur == "EUR":
        v = [FX["eur_m"].get(f"{y}-{m:02d}") for y, m in months]
        return sum(v) / len(v) if all(v) else None
    if cur == "GBP":   # годовые средние, взвешенные по месяцам финансового года
        w = {}; [w.__setitem__(y, w.get(y, 0) + 1) for y, m in months]
        return sum(FX["gbp_y"][str(y)] * k for y, k in w.items()) / 12 if all(str(y) in FX["gbp_y"] for y in w) else None
    return None
MAP = {"A21N_XLR": "A21N"}
def predict(fleet, age, sector):
    tot = sum(v for k, v in fleet.items() if isinstance(v, (int, float)) and MAP.get(k, k) in M["types"])
    if not tot or age is None or sector is None: return None, "нет парка по типам, возраста или сектора"
    s = 0
    for k, n in fleet.items():
        t = MAP.get(k, k)
        if t not in M["types"] or not isinstance(n, (int, float)): continue
        T = M["types"][t]; g = T["cls"]
        s += n / tot * T["mature"] * M["shape"][g][str(binof(age))] * (sector / M["sector_ref"][g]) ** M["e"]
    return s, ""
COVID = {2020, 2021, 2022}
out = []
for f in sorted((HERE / "stage2").glob("*.json")):
    d = json.load(open(f)); cur = d.get("currency"); fye = d.get("fiscal_year_end") or "12-31"
    mult = {"млн": 1e6, "тыс.": 1e3, "тыс": 1e3}.get(d.get("unit"), 1)
    for y, v in sorted(d["years"].items()):
        if not y.isdigit(): continue
        fy = int(y); r = {"airline": d["code"], "fy": fy}
        if not v.get("maint") or not v.get("block_h"): r["why"] = "нет суммы ТОиР или налёта"; out.append(r); continue
        rate = fx(cur, fy, fye)
        if not rate: r["why"] = f"нет курса {cur} за ФГ{fy}"; out.append(r); continue
        cal = fy if fye >= "07" else fy - 1      # календарный год, на который приходится бóльшая часть ФГ
        act = v["maint"] * mult * rate / v["block_h"] * ppi(min(cal, 2025))
        pred, why = predict(v.get("fleet") or {}, v.get("avg_age"), v.get("sector_h"))
        r.update(actual=round(act), pred=round(pred) if pred else None, pred_nolab=round(pred * (1 - LAB)) if pred else None,
                 ratio=round(act / (pred * (1 - LAB)), 2) if pred else None, why=why + ("; пандемия — налёт обвалился, постоянные расходы ТО на час завышены" if fy in COVID or (fye < "07" and fy == 2023 and False) else ""),
                 covid=cal in COVID or fy in COVID, age=v.get("avg_age"), sector=v.get("sector_h"), hours=v.get("hours_kind"), fx=round(rate, 4), cur=cur)
        out.append(r)
json.dump(out, open(HERE / "stage2_compare.json", "w"), ensure_ascii=False, indent=0)
for r in out:
    if "actual" in r: print(f"{r['airline']} ФГ{r['fy']} факт {r['actual']:5} USD25/БЧ | модель {r['pred'] or '—':>5} (без труда {r['pred_nolab'] or '—':>5}) | факт/модель без труда {r['ratio'] or '—'} | возраст {r['age']} сектор {r['sector']}{' | ПАНДЕМИЯ' if r['covid'] else ''} {r['why'][:50]}")
    else: print(f"{r['airline']} ФГ{r['fy']} — {r['why']}")
