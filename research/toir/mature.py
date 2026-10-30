"""Этап 1, промежуточный итог: отбор строк Form 41 по учётной политике и сведение по типу.
Поправка на возраст НЕ применена — нет возраста по типам (ждём Schedule B-43)."""
import json
R = json.load(open("f41_rows.json"))
EXCL = {
 "DL": "распределено по типам формулой: у 17 типов одинаковые доли и итог (m0)",
 "NK": "метод отсрочки: тяжёлые формы и капремонт капитализируются (a2)",
 "F9": "метод отсрочки: тяжёлые формы и капремонт капитализируются (a2)",
 "G4": "метод отсрочки для капремонта планеров и двигателей (a2)",
 "SY": "капремонт части двигателей капитализируется (built-in overhaul) (a2)",
 "YV": "отсрочка по ранее собственным E175, остаток списан в 2025 (a3)",
 "ZW": "капремонт двигателей капитализируется; договор с United закончился в 2025 (a3)",
 "3M": "полёты прекращены 11.06.2025, политика неизвестна (a3)",
 "G7": "под кодом CRJ200 по всей видимости CRJ550; политика неизвестна (a3)",
 "MX": "учётная политика не найдена; ровное деление планер/двигатели (a2)",
 "XP": "учётная политика не найдена (a2)",
 "C5": "учётная политика не найдена (a3)",
}
FLAG = {"AA": "доли планер/двигатели у American одинаковы по всем типам — разбивка условна, итог по типу различается",
        "OO": "под кодом CRJ200 у SkyWest могут быть и CRJ550"}
RESEARCHED = set(EXCL) | {"AA","UA","WN","AS","QX","HA","B6","OO","MQ","PT","OH","YX","9E"}
def m_age(a):  # RAND: доля от зрелой ставки
    return 1.0 if a >= 12 else 1.035 ** (a - 12) if a >= 6 else 0.8135 * 1.176 ** (a - 6)
types = {}
for r in R:
    t = types.setdefault(r["icao"], {"icao": r["icao"], "used": [], "excluded": []})
    base = dict(carrier=r["carrier"], raw=r["total_bh"], direct=r["direct_bh"], burden=r["burden_bh"], bh=r["block_h"])
    why = None
    if r["carrier"] not in RESEARCHED: why = "перевозчик не исследован (грузовой, чартерный или малый)"
    elif r["carrier"] in EXCL: why = EXCL[r["carrier"]]
    elif r["quarters"] < 3: why = f"данных только за {r['quarters']} кв."
    elif r["direct_bh"] > 0 and r["engine_bh"] / r["direct_bh"] < 0.15:
        why = f"двигатели {r['engine_bh']} USD/ч — {r['engine_bh']/r['direct_bh']:.0%} прямых: учтены вне ТОиР Form 41 (договор по налёту или обслуживание у материнской)"
    if why: t["excluded"].append({**base, "why": why}); continue
    t["used"].append({**base, "age": None, "k": None, "mature": None, "why": FLAG.get(r["carrier"], "")})
def wmed(xs):
    xs = sorted(xs); tot = sum(w for _, w in xs); c = 0
    for v, w in xs:
        c += w
        if c >= tot / 2: return v
out = []
for icao, t in sorted(types.items()):
    if t["used"]:
        d = wmed([(u["direct"], u["bh"]) for u in t["used"]]); b = wmed([(u["burden"], u["bh"]) for u in t["used"]])
        t.update(mature=None, raw_direct=d, burden=b, lo=min(u["raw"] for u in t["used"]), hi=max(u["raw"] for u in t["used"]),
                 note=f"как отчитано: прямой {d} + накладные {b} USD/блок-ч (медиана по блок-часам); поправка на возраст не применена")
    else:
        t.update(mature=None, burden=None, lo=None, hi=None, note="нет пригодных строк")
    out.append(t)
M = {"method": "Промежуточный итог. Из 134 строк Form 41 2025 оставлены перевозчики, у которых ТОиР списывается по факту "
     "(учётная политика подтверждена в 10-K), с данными за 3–4 квартала и двигателями, учтёнными внутри ТОиР. Значение — медиана по "
     "блок-часам, прямые и накладные отдельно. Приведение к зрелой ставке (борт ~12 лет, кривая RAND) ждёт возраста парка по типам: "
     "в открытом тексте 10-K он недоступен, нужна выгрузка Schedule B-43.", "types": out}
json.dump(M, open("mature.json", "w"), ensure_ascii=False, indent=1)
for t in out:
    if t["used"]: print(f"{t['icao']:5} n{len(t['used'])} excl{len(t['excluded'])} direct {t['raw_direct']} burden {t['burden']} range {t['lo']}-{t['hi']}  ", [u['carrier'] for u in t['used']])
print("types w/o usable:", [t['icao'] for t in out if not t['used']])
