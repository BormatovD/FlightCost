"""SDR по возрасту парка: три группы глав (конструкция 51–57, системы 21–49, силовая установка 71–80),
Пуассон: перевозчик×год + тип + ступень возраста (по классу), экспозиция — блок-часы."""
import json, csv, collections, pathlib, sys, numpy as np, pandas as pd
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); from common import CLASS
exec(open(HERE / "panel.py").read().split("AF = ")[0]); R = HERE / "raw20"
A = json.load(open(HERE / "sdr" / "sdr_agg.json")); AG = json.load(open(HERE / "ages.json"))["ages"]
num = lambda v: float(v) if v and v.strip() else 0.0
bh = collections.Counter()
for r in csv.DictReader(open(R / "t2.csv", encoding="utf-8-sig")):
    y = int(r["YEAR"])
    if 2018 <= y <= 2025 and r["SERVICE_CLASS"] == "Z":
        ic = icao(r["AIRCRAFT_TYPE"].lstrip("0"))
        if ic: bh[(y, r["AIRLINE_ID"], ic)] += num(r["ACRFT_HRS_RAMPTORAMP_630"])
cnt = collections.Counter()
GRP = lambda ch: "конструкция" if "51" <= ch <= "57" else "системы" if "21" <= ch <= "49" else "силовая установка" if "71" <= ch <= "80" else None
for k, v in A["cnt"].items():
    y, aid, ic, ch = k.split("|"); g = GRP(ch)
    if g: cnt[(int(y), aid, ic, g)] += v
BINS = list(range(0, 26, 2)) + [26]; binof = lambda a: max(lo for lo in BINS if a >= lo)
out = {}
for g in ("конструкция", "системы", "силовая установка"):
    rows = []
    for (y, aid, ic), h in bh.items():
        a = AG.get(f"{y}|{aid}|{ic}"); cl = CLASS.get(ic)
        if h < 2000 or not a or not cl: continue
        tot = sum(cnt.get((y, aid, ic, gg), 0) for gg in ("конструкция", "системы", "силовая установка"))
        if tot == 0: continue
        rows.append(dict(cy=f"{aid}|{y}", t=ic, ab=f"{cl}|{binof(a['age'])}", n=cnt.get((y, aid, ic, g), 0), e=h / 1000))
    df = pd.DataFrame(rows)
    f = {c: pd.Series(1.0, index=df[c].unique()) for c in ("cy", "t", "ab")}
    for it in range(500):
        old = f["ab"].copy()
        for c in ("t", "ab", "cy"):
            others = np.ones(len(df))
            for o in ("cy", "t", "ab"):
                if o != c: others = others * df[o].map(f[o]).values
            f[c] = df.groupby(c).n.sum() / pd.Series(df.e.values * others, index=df.index).groupby(df[c]).sum()
        if np.nanmax(np.abs(np.log(f["ab"] / old).replace([np.inf, -np.inf], np.nan))) < 1e-9: break
    res = {}
    for cl in ("узкофюзеляжные", "широкофюзеляжные", "региональные"):
        ref = f["ab"].get(f"{cl}|12")
        if not ref: continue
        res[cl] = {lo: (round(float(f["ab"][f"{cl}|{lo}"] / ref), 2), int(df[df.ab == f"{cl}|{lo}"].n.sum())) for lo in BINS if f"{cl}|{lo}" in f["ab"]}
    out[g] = res
json.dump(out, open(HERE / "sdr" / "sdr_age.json", "w"), ensure_ascii=False)
F2 = json.load(open(HERE / "model2_ppi.json"))["shape"]
for g, res in out.items():
    print("==", g, "(отношение к 12–13 годам; в скобках — сообщений)")
    for cl, s in res.items():
        print(f"  {cl:16}", " ".join(f"{lo}:{v[0]}({v[1]})" for lo, v in s.items()))
print("== для сравнения: ТОиР Form 41 (модель 2)")
for cl, s in F2.items(): print(f"  {cl:16}", " ".join(f"{lo}:{v:.2f}" for lo, v in s.items()))
