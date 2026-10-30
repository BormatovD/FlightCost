"""Интенсивность сообщений SDR по главам ATA на 1000 блок-часов: тип × глава, с поправкой на склонность перевозчика сообщать.
Пуассон: число ~ перевозчик×год + тип×глава, экспозиция — блок-часы T-2."""
import json, csv, collections, pathlib, sys, numpy as np, pandas as pd
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); exec(open(HERE / "sdr_agg.py").read().split("# бортовой номер")[0].split('csv.field_size_limit')[0])
A = json.load(open(HERE / "sdr" / "sdr_agg.json")); J = json.load(open(HERE / "sdr" / "jasc.json"))
exec(open(HERE / "panel.py").read().split("AF = ")[0])     # icao() для T-2
num = lambda v: float(v) if v and v.strip() else 0.0
bh = collections.Counter()
for r in csv.DictReader(open(R / "t2.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if not (2018 <= y <= 2025) or r["SERVICE_CLASS"] != "Z": continue
    ic = icao(r["AIRCRAFT_TYPE"].lstrip("0"))
    if ic: bh[(y, r["AIRLINE_ID"], ic)] += num(r["ACRFT_HRS_RAMPTORAMP_630"])
cnt = {tuple(k.split("|")): v for k, v in A["cnt"].items()}
types = sorted({k[2] for k in cnt}); chaps = sorted({k[3] for k in cnt if "21" <= k[3] <= "80"})
rows = []
for (y, aid, ic), h in bh.items():
    if h < 2000 or ic not in types: continue
    tot = sum(cnt.get((str(y), aid, ic, ch), 0) for ch in chaps)
    if tot == 0: continue        # перевозчик не подаёт SDR вовсе (или не нашёлся) — не «ноль отказов»
    for ch in chaps:
        rows.append(dict(cy=f"{aid}|{y}", t=ic, ch=ch, n=cnt.get((str(y), aid, ic, ch), 0), bh=h))
df = pd.DataFrame(rows)
# оставляем пары тип×глава, где есть хоть что-то
keep = df.groupby(["t", "ch"]).n.transform("sum") >= 10
df = df[keep].copy(); df["tc"] = df.t + "|" + df.ch
# Пуассон с двумя группами факторов — итерационное пропорциональное подгонка (то же МП-решение, без огромной матрицы)
df["e"] = df.bh / 1000.0
a = pd.Series(1.0, index=df.cy.unique()); bt = pd.Series(1.0, index=df.tc.unique())
for it in range(300):
    bt_new = df.groupby("tc").n.sum() / (df.e * df.cy.map(a)).groupby(df.tc).sum()
    a_new = df.groupby("cy").n.sum() / (df.e * df.tc.map(bt_new)).groupby(df.cy).sum()
    d = float(np.max(np.abs(np.log(bt_new / bt))))
    a, bt = a_new, bt_new
    if d < 1e-8: break
w = df.groupby("cy").e.sum(); cbar = float(np.exp(np.average(np.log(a.clip(lower=1e-9)), weights=w)))
mu = df.e * df.cy.map(a) * df.tc.map(bt)
dev = 2 * np.sum(np.where(df.n > 0, df.n * np.log(df.n / mu), 0) - (df.n - mu)); dfr = len(df) - len(a) - len(bt)
class M: pass
m = M(); m.deviance = dev; m.df_resid = dfr
rate = {k: float(v * cbar) for k, v in bt.items()}
ntc = df.groupby("tc").n.sum()
se = {k: float(1 / np.sqrt(max(ntc[k], 1))) for k in bt.index}     # пуассоновская ошибка ln-ставки ≈ 1/√n
cy = {k: float(np.log(v / cbar)) for k, v in a.items()}; cbar = 0.0
out = collections.defaultdict(dict)
for k, v in rate.items():
    t, ch = k.split("|"); out[t][ch] = {"rate": v, "se_log": se[k]}
tot = {t: sum(x["rate"] for x in d.values()) for t, d in out.items()}
expo = df.groupby("t").bh.sum() / len(chaps)
json.dump({"chapters": {c: J["chapters"].get(c, "") for c in chaps}, "rates": out, "total": tot, "exposure_bh": expo.to_dict(),
           "n_reports": int(df.n.sum()), "n_cells": len(df), "deviance_ratio": float(m.deviance / m.df_resid),
           "carrier_year": {k: float(np.exp(v)) for k, v in cy.items()}, "code": A["code"]},
          open(HERE / "sdr" / "sdr_model.json", "w"), ensure_ascii=False)
print("сообщений", int(df.n.sum()), "ячеек", len(df), "избыточная дисперсия", round(m.deviance / m.df_resid, 2))
for t in sorted(tot, key=lambda t: -expo.get(t, 0)):
    top = sorted(out[t].items(), key=lambda x: -x[1]["rate"])[:5]
    print(f"{t:5} всего {tot[t]:5.2f}/1000БЧ  налёт {expo.get(t,0)/1e6:5.1f} млн БЧ | " + ", ".join(f"{ch} {J['chapters'].get(ch,'')[:12]} {v['rate']:.2f}" for ch, v in top))
