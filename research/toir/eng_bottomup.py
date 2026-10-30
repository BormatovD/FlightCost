"""Двигатели снизу: стоимость на блок-час самолёта = двигателей × (капремонт/интервал + LLP/ресурс) × (лётные часы / блок-часы).
Цены приводятся к 2025: капремонт — индексом цен на ТО ВС (WPS5541), LLP — ростом каталога (по двум точкам двигателя, иначе 7%/год).
Каждое допущение записано в поле how."""
import json, pathlib
HERE = pathlib.Path(__file__).resolve().parent; E = HERE / "bottomup" / "engines"
IX = json.load(open(HERE / "index.json")); TG = json.load(open(HERE / "bottomup" / "eng_target.json"))
def ppi(y):
    w = IX["wps5541_jun"].get(str(y)) or 100.0 * IX["pcu488190_jun"][str(y)] / IX["pcu488190_jun"]["2009"]
    return IX["wps5541_jun"]["2025"] / w
DEFAULT_ESC = 0.07
# Расчётные случаи: тип ВС ← двигатель и выбранные из файла значения (с указанием, какие именно)
CASES = [
 dict(t="A320", eng="CFM56-5B", llp=(4200000, 2020), llp_esc=(2550000, 2014), llp_life=20000, ratio=1.9,
      sv=[(4300000, 2020, 19000)], how="первый ремонт A320 после 19 тыс. циклов, $4,3 млн (2020); LLP $4,2 млн (2020), лимит HPC/HPT 20 тыс. циклов"),
 dict(t="A320", eng="V2500-A5", llp=(3000000, 2013), llp_esc=None, llp_life=20000, ratio=1.9,
      sv=[(2400000, 2013, 10500)], how="первый ремонт V2527 после 10,5 тыс. циклов, $2,4 млн (2013); LLP $3,0 млн (2013), все LLP 20 тыс. циклов"),
 dict(t="B738", eng="CFM56-7B", llp=(4000000, 2019), llp_esc=(2520000, 2013), llp_life=20000, ratio=1.9,
      sv=[(1725000, 2013, 16000), (3300000, 2013, 13000)], how="первый ремонт -7B24 $1,73 млн через 16 тыс. циклов; следующий — полный $3,3 млн, интервал принят 13 тыс. (по -7B26) (2013); LLP $4,0 млн (2019)"),
 dict(t="B752", eng="PW2000", llp=(4950000, 2013), llp_esc=None, llp_life=15000, ratio=2.7,
      sv=[(2550000, 2013, 6500)], how="PW2037: ремонт через 18 тыс. ч / 6,5 тыс. циклов, $2,55 млн (2013); LLP $4,95 млн (2013), лимит дисков ТВД 15 тыс. циклов"),
 dict(t="B763", eng="CF6-80C2", llp=(3385000, 2006), llp_esc=None, llp_life=20000, ratio=6.0,
      sv=[(2100000, 2006, 2500)], how="-80C2B6F: ремонт через 15 тыс. ч / 2,5 тыс. циклов, $2,1 млн (2006); LLP $3,39 млн (2006), целевой ресурс 20 тыс. циклов"),
 dict(t="B763", eng="PW4000-94", llp=(3600000, 2007), llp_esc=None, llp_life=15000, ratio=6.0,
      sv=[(2400000, 2007, 17000 / 6.0)], how="PW4000-94 дальнемагистральный: ремонт через 17 тыс. ч, $2,4 млн (2007); LLP $3,6 млн (2007), ресурс 15 тыс. циклов (по -100)"),
 dict(t="CRJ9", eng="CF34-8C", llp=(1900000, 2009), llp_esc=None, llp_life=13200, ratio=1.4,
      sv=[(900000, 2009, 11500), (1250000, 2009, 11500)], how="-8C5: первый $0,9 млн, второй $1,25 млн через 11,5 тыс. циклов (2009); LLP $1,9 млн, лимит ТВД 13,2 тыс."),
 dict(t="E75L", eng="CF34-8E", llp=(1800000, 2010), llp_esc=None, llp_life=13000, ratio=1.3,
      sv=[(950000, 2010, 12000), (1500000, 2010, 12000)], how="-8E5: первый $0,95 млн через 12 тыс. циклов, второй $1,5 млн (2010); LLP $1,8 млн, лимит ТВД 13 тыс."),
 dict(t="B77W", eng="GE90-115B", llp=(6500000, 2012), llp_esc=None, llp_life=15000, ratio=8.5,
      sv=[(6250000, 2012, 3000), (7250000, 2012, 2100)], how="первый $6,25 млн через 25 тыс. ч / 3 тыс. циклов, следующие $7,25 млн через 2,1 тыс. циклов (2012); LLP $6,5 млн, ресурс 15 тыс."),
]
out = []
for c in CASES:
    y0 = c["llp"][1]
    esc = ((c["llp"][0] / c["llp_esc"][0]) ** (1 / (y0 - c["llp_esc"][1])) - 1) if c["llp_esc"] else DEFAULT_ESC
    llp25 = c["llp"][0] * (1 + esc) ** (2025 - y0)
    sv_efh = sum(cost * ppi(y) for cost, y, efc in c["sv"]) / sum(efc * c["ratio"] for cost, y, efc in c["sv"])
    llp_efh = llp25 / c["llp_life"] / c["ratio"]
    tg = TG.get(c["t"], {}); sector = tg.get("sector") or 2.0
    fh_bh = max(0.5, 1 - 0.3 / sector)          # лётные часы на блок-час: руление ~18 мин на рейс
    per_bh = 2 * (sv_efh + llp_efh) * fh_bh
    out.append(dict(type=c["t"], engine=c["eng"], sv_per_efh=round(sv_efh), llp_per_efh=round(llp_efh), llp_2025=round(llp25),
                    llp_esc=round(esc, 3), fh_bh=round(fh_bh, 2), per_bh=round(per_bh), target=round(tg.get("eng_bh", 0)) or None,
                    target_range=[round(tg["lo"]), round(tg["hi"])] if tg else None, ratio=round(per_bh / tg["eng_bh"], 2) if tg else None, how=c["how"]))
json.dump(out, open(HERE / "bottomup" / "eng_compare.json", "w"), ensure_ascii=False, indent=1)
for o in out:
    print(f"{o['type']:5} {o['engine']:10} капремонт {o['sv_per_efh']:4}/EFH + LLP {o['llp_per_efh']:4}/EFH (комплект 2025 ${o['llp_2025']/1e6:.1f} млн, рост {o['llp_esc']:.1%}) × 2 × {o['fh_bh']} = {o['per_bh']:5} USD25/БЧ | Form 41 {o['target']} {o['target_range']} → {o['ratio']}")
