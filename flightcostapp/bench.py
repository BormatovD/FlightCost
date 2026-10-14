"""Полоса бенчмарка флотской экономики: Form 41 по типам и IATA ACMG.

Заготовка `fleet.parametric` даёт связные, но выдуманные ставки — 41%
себестоимости рейса держится на ней и на двух константах рядом. Этот
модуль не заменяет заготовку, а ставит рядом с ней ИЗМЕРЕНИЕ с
погрешностью: что платят за ТОиР, пилотов, владение и сколько летает борт
у двух десятков перевозчиков США на том же типе. Модель в полосу либо
попадает, либо объяснимо не попадает — это и есть условие готовности M11.

ЧТО ИЗМЕРЕНО, А ЧТО НЕТ.

* ТОиР — `maint_total` (счёт 52990: прямой ТОиР бортов плюс отнесённые
  накладные ТОиР) на блок-час T-2. Полная ставка, как её называют в
  отрасли; прямую часть — рядом.
* Экипаж — ТОЛЬКО ЛЁТНЫЙ: пилоты, стажёры, прочий лётный персонал, их
  соцпакет и налоги на фонд оплаты. Бортпроводники в P-5.2 не по типам, а
  в общих расходах перевозчика. Полный экипаж оценивается отношением
  кабинного к лётному из структуры ACMG — и подписывается как оценка.
* Владение — аренда, амортизация бортов и амортизация финансового лизинга
  на борт в месяц ПО БАЛАНСУ. Не рыночная ставка лизинга: старый
  собственный парк самортизирован и тянет полосу вниз. Читать как нижнюю
  оценку для нового борта.
* Налёт — блок-часы T-2 на день в парке, в часах на месяц. Измерение без
  оговорок, кроме одной: «дни в парке» включают стоящие борта.
* Расход — галлоны T-2 на блок-час, в кг (0,8 кг/л). Проверка вычислителя
  расхода, а не статья.

СТРУКТУРА «ЧАС ПЛЮС ЦИКЛ». Перевозчики летают один тип на разных средних
плечах: региональный A320 — 1,5 часа, трансконтинентальный — 4. Стоимость
на вылет против плеча по перевозчикам — те самые «две точки на разных
плечах», которых не хватало заготовке (fleet.py, «известная привязка»).
Подбор — `cycles.fit`, с остатком; при отрицательной части структура
названа несогласованной, а не подогнана.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

DAYS_PER_MONTH = 30.4375
KG_PER_GAL = 3.785411784 * 0.8        # US галлон, плотность керосина 0,8 кг/л

# Расшифровка BTS -> наш код ИКАО. Порядок важен: neo и MAX раньше базовых.
# Не узнанный тип не выбрасывается молча — он печатается в отчёте.
TYPE_PATTERNS = [
    (r"A-?319.*NEO|A319N|A-?319-\d{3}N\b", "A19N"),
    (r"A-?320.*NEO|A320N|A-?320-\d{3}N\b", "A20N"),
    (r"A-?321.*NEO|A321N|A-?321-\d{3}N\b|A321 ?X?LR", "A21N"),
    (r"A-?318", "A318"),
    (r"A-?319", "A319"),
    (r"A-?320", "A320"),
    (r"A-?321", "A321"),
    (r"A220-100|A200-100|CS-?100|BD-?500-1A10", "BCS1"),
    (r"A220-300|CS-?300|BD-?500-1A11", "BCS3"),
    (r"A-?330-?900|A-?330.*NEO", "A339"),
    (r"A-?330-?200|A-?330-2\d\d\b", "A332"),
    (r"A-?330-?300|A-?330-3\d\d\b", "A333"),
    (r"A-?350-?900", "A359"),
    (r"A-?350-?1000|AIRBUS 350-1000", "A35K"),
    (r"A-?380", "A388"),
    (r"737 ?MAX ?10|737-?MAX ?10", "B3XM"),
    (r"737 ?MAX ?8|737 ?MAX ?800|737 ?MAX ?200|737-8\b", "B38M"),
    (r"737 ?MAX ?9|737 ?MAX ?900|737-9\b", "B39M"),
    (r"737 MAX 7\b|737-7\b", "B37M"),
    (r"737-?900", "B739"),
    (r"737-?800", "B738"),
    (r"737-?700", "B737"),
    (r"737-?300", "B733"),
    (r"717-?200", "B712"),
    (r"757-?300", "B753"),
    (r"757-?200", "B752"),
    (r"767-?400", "B764"),
    (r"767-?300", "B763"),
    (r"767-?200", "B762"),
    (r"777-?300", "B77W"),
    (r"777-?200", "B772"),
    (r"747-?8|B747-8", "B748"),
    (r"747-?400\b", "B744"),
    (r"787-?10", "B78X"),
    (r"787-?900|787-?9\b", "B789"),
    (r"787-?800|787-?8\b", "B788"),
    (r"E-?175|ERJ-?175|EMB-?175|EMBRAER 175|ERJ-170-200", "E75L"),
    (r"E-?170|ERJ-?170|EMB-?170", "E170"),
    (r"E-?190|ERJ-?190|EMB-?190|EMBRAER 190", "E190"),
    (r"E-?195|ERJ-?195|EMB-?195", "E195"),
    (r"ERJ-?145|EMB-?145|EMBRAER-?145", "E145"),
    (r"ERJ-?135|EMBRAER-?135", "E135"),
    (r"CRJ[- ]?900|CL-?600-2D24", "CRJ9"),
    (r"CRJ[- ]?700|CRJ[- ]?705|\bRJ-?700|CL-?600-2C10", "CRJ7"),
    (r"CRJ[- ]?550|CRJ[- ]?200|\bRJ-?200|CL-?600-2B19", "CRJ2"),
    (r"DHC-?8-?400|DASH ?8-?400|Q400", "DH8D"),
    (r"ATR-?72", "AT76"),
    (r"ATR-?42", "AT45"),
]

# Семейства ACMG. Сбор 2019 года: в «A320 Family» и «B737 NG» почти нет neo
# и MAX — отнесение нового поколения к семейству подписывается в ответе.
ACMG_FAMILY = {
    **dict.fromkeys(["A318", "A319", "A320", "A321"], "A320_FAMILY"),
    **dict.fromkeys(["A19N", "A20N", "A21N"], "A320_FAMILY"),
    **dict.fromkeys(["B737", "B738", "B739"], "B737_NG"),
    **dict.fromkeys(["B37M", "B38M", "B39M"], "B737_NG"),
    **dict.fromkeys(["B733", "B734", "B735"], "B737_CLASSIC"),
    **dict.fromkeys(["B772", "B773", "B77W", "B77L"], "B777"),
    **dict.fromkeys(["A332", "A333", "A338", "A339"], "A330"),
    **dict.fromkeys(["B752", "B753"], "B757"),
    **dict.fromkeys(["B762", "B763", "B764"], "B767"),
    **dict.fromkeys(["B788", "B789", "B78X"], "B787"),
    **dict.fromkeys(["E190", "E195", "E290", "E295"], "EMB_190"),
    **dict.fromkeys(["DH8A", "DH8B", "DH8C", "DH8D"], "DASH_8"),
}
NEW_GEN = {"A19N", "A20N", "A21N", "B37M", "B38M", "B39M"}


def icao_of(desc: str) -> str | None:
    d = (desc or "").upper()
    for pat, icao in TYPE_PATTERNS:
        if re.search(pat, d):
            return icao
    return None


# ---------------------------------------------------------------- чтение

def _rows(store, prefix: str):
    return store.db.execute(
        "SELECT key, value, value_text, unit FROM facts WHERE domain = 'fleet_benchmark' "
        "AND valid_to IS NULL AND key LIKE ?", (prefix + "%",)).fetchall()


def _stamp(store):
    r = store.db.execute("SELECT COUNT(*), MAX(id) FROM facts WHERE domain = 'fleet_benchmark'"
                         ).fetchone()
    return (id(store.db), r[0], r[1])          # гостевая обёртка — та же база


_CACHE: dict = {}


def _load(store):
    """Квартальные строки P-5.2 и T-2, расшифровка кодов; с кэшем на состояние домена."""
    st = _stamp(store)
    if _CACHE.get("stamp") == st:
        return _CACHE["data"]
    p52 = defaultdict(dict)
    t2 = defaultdict(dict)
    names = {}
    for r in _rows(store, "F41/P52/"):
        _, _, yq, car, typ, f = r["key"].split("/")
        p52[(yq, car, typ)][f] = r["value"] or 0.0
        if r["value_text"]:
            try:
                names[car] = json.loads(r["value_text"]).get("carrier_name") or names.get(car, "")
            except ValueError:
                pass
    for r in _rows(store, "F41/T2/"):
        _, _, yq, car, typ, f = r["key"].split("/")
        t2[(yq, car, typ)][f] = r["value"] or 0.0
    types = {r["key"].split("/")[2]: r["value_text"] for r in _rows(store, "F41/TYPES/")}
    acmg = defaultdict(dict)
    for r in _rows(store, "ACMG/"):
        _, fam, f = r["key"].split("/")
        acmg[fam][f] = r["value"]
    data = {"p52": p52, "t2": t2, "types": types, "names": names, "acmg": acmg}
    _CACHE.update(stamp=st, data=data)
    return data


# ---------------------------------------------------------------- масштаб

def scales(data) -> dict:
    """Масштаб «(000)» P-5.2: часы — сверкой с T-2, деньги — правдоподобием.

    Пометка «(000)» в описании полей BTS стоит у всех величин, включая
    часы, — значит она шаблонная. Решается по данным и печатается.
    """
    ratios = []
    for k, v in data["p52"].items():
        t = data["t2"].get(k)
        if t and v.get("air_hours") and t.get("air_hours"):
            ratios.append(v["air_hours"] / t["air_hours"])
    hours_mult, why_h = 1.0, "часы P-5.2 не с чем сверить (нет T-2 с часами в воздухе)"
    if ratios:
        ratios.sort()
        med = ratios[len(ratios) // 2]
        hours_mult = 1000.0 if med < 0.03 else 1.0
        why_h = (f"часы P-5.2 к часам T-2: медиана {med:.3g} по {len(ratios)} строкам → "
                 + ("в тысячах" if hours_mult == 1000.0 else "в часах"))
    per_h = []
    for v in data["p52"].values():
        h = (v.get("air_hours") or 0.0) * hours_mult
        if h > 0 and v.get("maint_total"):
            per_h.append(v["maint_total"] / h)
    money_mult, why_m = 1000.0, "расходы в тысячах USD, как в описании полей"
    if per_h:
        per_h.sort()
        med = per_h[len(per_h) // 2]
        money_mult = 1000.0 if med < 30 else 1.0
        why_m = (f"ТОиР на час в воздухе без пересчёта: медиана {med:.3g} → расходы "
                 + ("в тысячах USD" if money_mult == 1000.0 else "в долларах"))
    return {"hours": hours_mult, "money": money_mult, "why": [why_h, why_m]}


# ---------------------------------------------------------------- строки перевозчиков

COCKPIT = ("pilots", "oth_flight", "trainees", "pers_exp", "benefits", "payroll_tax")
DEP_PARTS = ("dep_airframe", "dep_engine", "dep_af_parts", "dep_eng_parts", "dep_other")


def _quarter_values(v: dict) -> dict:
    """Итоги квартала: поданный итог, а без него — сумма слагаемых.

    Итог амортизации (70756) в выгрузке 2025 года пуст в 1 523 строках из
    1 547; где подан, равен сумме слагаемых до цента. С ТОиР наоборот:
    итог 52990 подан почти везде, а без него — прямой плюс накладные.
    """
    dep = v.get("depreciation") or sum(v.get(f, 0.0) for f in DEP_PARTS)
    maint = v.get("maint_total") or (v.get("maint_direct", 0.0) + v.get("maint_burden", 0.0))
    return {"maint_total": maint, "maint_direct": v.get("maint_direct", 0.0),
            "cockpit": sum(v.get(f, 0.0) for f in COCKPIT),
            "ownership": v.get("rentals", 0.0) + dep + v.get("amort_leases", 0.0),
            "doc_total": v.get("doc_total", 0.0)}


# Код BTS, расшифровка которого противоречит данным. Не правка справочника,
# а исключение с доводом: справочник остаётся, как опубликован.
CODE_OVERRIDES = {
    # «A321Neoxlr» в L_AIRCRAFT_TYPE 2025 года. Под кодом 699 отчитываются
    # 218 бортов AA, 125 DL, 63 B6 при 181–190 креслах и плече 2,8–3 ч —
    # это парк A321ceo (у AA их около 218), а neo идёт отдельным кодом 721
    # (A321-200n). XLR в США к 2025 году — единицы. Расшифровка, по всей
    # видимости, перезаписана при заведении XLR; данные под кодом — ceo.
    "699": ("A321", "расшифровка BTS «A321Neoxlr» противоречит данным: под кодом "
                    "парк A321ceo (AA 218, DL 125 бортов), neo — код 721"),
}


def carrier_rows(store, year: int | None = None) -> tuple[list[dict], dict]:
    """Перевозчик × наш тип за год: кварталы, где есть и P-5.2, и T-2.

    Квартал без пары не берётся: расходы без блок-часов дали бы ставку из
    половины знаменателя.
    """
    data = _load(store)
    sc = scales(data)
    years = sorted({int(k[0][:4]) for k in data["p52"] if k in data["t2"]})
    meta = {"years": years, "scales": sc, "unmapped": {}, "year": None}
    if not years:
        return [], meta
    if year is None:
        full = [y for y in years
                if len({k[0] for k in data["p52"] if k[0].startswith(str(y)) and k in data["t2"]}) == 4]
        year = (full or years)[-1]
    meta["year"] = year
    acc = defaultdict(lambda: defaultdict(float))
    quarters = defaultdict(set)
    for k, v in data["p52"].items():
        yq, car, typ = k
        if not yq.startswith(str(year)) or k not in data["t2"]:
            continue
        desc = data["types"].get(typ, "")
        icao = CODE_OVERRIDES[typ][0] if typ in CODE_OVERRIDES else icao_of(desc)
        if typ in CODE_OVERRIDES:
            meta.setdefault("overrides", {})[typ] = CODE_OVERRIDES[typ][1]
        if icao is None:
            meta["unmapped"][typ] = desc or "нет расшифровки (L_AIRCRAFT_TYPE не загружен?)"
            continue
        t = data["t2"][k]
        qv = _quarter_values(v)
        if qv["maint_total"] <= 0 or qv["cockpit"] <= 0:
            # Часы поданы, расходы — нет (так у трети строк 2025 года: малые
            # перевозчики, сводные коды). Ноль ТОиР — не ставка, а пропуск:
            # с ним в полосе медиана уехала бы вниз.
            meta["dropped"] = meta.get("dropped", 0) + 1
            continue
        a = acc[(car, icao)]
        for f, x in qv.items():
            a[f] += x * sc["money"]
        for f, x in t.items():
            a[f"t2_{f}"] += x
        quarters[(car, icao)].add(yq)
    rows = []
    for (car, icao), a in acc.items():
        bh, dep, days = a["t2_ramp_hours"], a["t2_departures"], a["t2_days_assigned"]
        if bh <= 0 or dep <= 0 or days <= 0:
            continue
        cockpit, own = a["cockpit"], a["ownership"]
        r = {
            "carrier": car, "name": data["names"].get(car, ""), "icao": icao,
            "quarters": len(quarters[(car, icao)]),
            "block_h": bh, "departures": dep, "aircraft": days / (91.3125 * len(quarters[(car, icao)])),
            "block_per_dep": bh / dep,
            "util_h_month": bh / days * DAYS_PER_MONTH,
            "maint_per_bh": a["maint_total"] / bh,
            "maint_direct_per_bh": a["maint_direct"] / bh,
            "maint_per_dep": a["maint_total"] / dep,
            "cockpit_per_bh": cockpit / bh,
            "cockpit_per_dep": cockpit / dep,
            "own_per_ac_month": own / days * DAYS_PER_MONTH,
            "fuel_kg_per_bh": (a["t2_fuel_gal"] * KG_PER_GAL / bh) if a["t2_fuel_gal"] else None,
            "seats": (a["t2_asm"] / a["t2_air_miles"]) if a["t2_air_miles"] else None,
            "doc_per_bh": a["doc_total"] / bh if a["doc_total"] else None,
        }
        rows.append(r)
    return rows, meta


# ---------------------------------------------------------------- полосы

@dataclass
class Band:
    metric: str
    unit: str
    p25: float
    p50: float
    p75: float
    lo: float
    hi: float
    n: int
    carriers: list = field(default_factory=list)

    def where(self, x: float) -> str:
        if self.p25 <= x <= self.p75:
            return "в полосе p25–p75"
        if self.lo <= x <= self.hi:
            return "в размахе, вне p25–p75"
        return "ниже всех перевозчиков" if x < self.lo else "выше всех перевозчиков"


def _wq(pairs, q):
    """Квантиль, взвешенный блок-часами: крупный парк весит больше мелкого."""
    pairs = sorted(pairs)
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for x, w in pairs:
        acc += w
        if acc >= q * tot:
            return x
    return pairs[-1][0]


METRICS = {
    "maint_per_bh": ("USD/блок-ч", "ТОиР полный (52990) на блок-час"),
    "maint_direct_per_bh": ("USD/блок-ч", "ТОиР прямой (52780) на блок-час"),
    "cockpit_per_bh": ("USD/блок-ч", "лётный экипаж (с соцпакетом) на блок-ч"),
    "own_per_ac_month": ("USD/борт·мес", "аренда + амортизация по балансу"),
    "util_h_month": ("блок-ч/мес", "налёт борта"),
    "block_per_dep": ("ч", "среднее плечо в блок-часах"),
    "fuel_kg_per_bh": ("кг/блок-ч", "расход по выданному топливу"),
    "seats": ("кресел", "кресло-мили / мили"),
}


def type_bench(store, icao: str, year: int | None = None) -> dict | None:
    """Полосы по типу и разложение «час + цикл» для ТОиР и лётного экипажа.

    Кэш на состояние домена: разбор зовёт это на каждом плече сети.
    """
    key = (_stamp(store), icao.upper(), year)
    hit = _TB.get(key)
    if hit is not None:
        return hit[0]
    out = _type_bench(store, icao, year)
    if len(_TB) > 256:
        _TB.clear()
    _TB[key] = (out,)
    return out


_TB: dict = {}


def _type_bench(store, icao: str, year: int | None) -> dict | None:
    from .cycles import fit

    rows, meta = carrier_rows(store, year)
    mine = [r for r in rows if r["icao"] == icao.upper()]
    out = {"icao": icao.upper(), "year": meta["year"], "scales": meta["scales"],
           "unmapped": meta["unmapped"], "bands": {}, "split": {}, "carriers": mine}
    if mine:
        for m, (unit, _) in METRICS.items():
            pts = [(r[m], r["block_h"]) for r in mine if r.get(m) is not None]
            if not pts:
                continue
            xs = [x for x, _ in pts]
            out["bands"][m] = Band(m, unit, _wq(pts, .25), _wq(pts, .5), _wq(pts, .75),
                                   min(xs), max(xs), len(pts),
                                   [r["carrier"] for r in mine if r.get(m) is not None])
        for what in ("maint", "cockpit"):
            pts = [(r["block_per_dep"], r[f"{what}_per_dep"]) for r in mine]
            spread = max(p[0] for p in pts) - min(p[0] for p in pts)
            if len(pts) >= 3 and spread >= 0.4:
                s = fit(pts, source=f"Form 41 {meta['year']}, {len(pts)} перевозчиков")
                out["split"][what] = s
            else:
                out["split"][what] = None
    fam = ACMG_FAMILY.get(icao.upper())
    acmg = _load(store)["acmg"].get(fam) if fam else None
    if acmg and acmg.get("per_flight_hour"):
        leg = (acmg["per_flight_cycle"] / acmg["per_flight_hour"]
               if acmg.get("per_flight_cycle") else None)
        out["acmg"] = {"family": fam, "per_fh_usd": acmg["per_flight_hour"],
                       "per_cycle_usd": acmg.get("per_flight_cycle"),
                       "per_ac_year_musd": acmg.get("per_aircraft_year"),
                       "leg_h": leg, "new_gen_note": icao.upper() in NEW_GEN}
    if not mine and "acmg" not in out:
        return None
    return out


def cabin_to_cockpit(store) -> float | None:
    """Отношение кабинного экипажа к лётному по структуре ACMG 2019."""
    a = _load(store)["acmg"].get("STRUCTURE", {})
    cab, ck = a.get("CABIN_CREW"), a.get("FLIGHT_DECK_CREW")
    return cab / ck if cab and ck else None


def usd_per_eur(store, year: int | None) -> tuple[float | None, str]:
    """Курс для пересчёта годовых величин: на середину года отчёта."""
    from . import fx
    day = f"{year}-07-01" if year else None
    rate, prov = fx.resolve(store, "USD", day)
    if rate:
        return rate, f"USD/EUR {rate:.4f} на {day or 'сегодня'} ({prov})"
    # Истории курса в хранилище может не быть: ЕЦБ отдаёт день, и ряд
    # копится с первого `refresh`. Тогда — последний известный курс, и это
    # сказано: за год доллар к евро ходит на 5–10%, полоса от этого не
    # меняет вывод «в полосе / вне», но число — меняет.
    rate, prov = fx.resolve(store, "USD", None)
    if rate:
        return rate, (f"USD/EUR {rate:.4f} — последний известный курс, не на середину "
                      f"{year} года: истории курса в хранилище нет ({prov})")
    return None, "нет курса USD: fca refresh --only fx_rates"


# ---------------------------------------------------------------- сравнение с моделью

def compare(store, icao: str, fe, year: int | None = None) -> dict | None:
    """Ставки модели против полосы — на СРЕДНЕМ ПЛЕЧЕ ВЫБОРКИ, в евро.

    Сравнивать на своём плече нельзя: на коротком секторе цикловые статьи
    делятся на меньшее число часов, и ставка на час выше при той же
    эффективности.
    """
    b = type_bench(store, icao, year)
    if not b or not b["bands"]:
        return b
    b = dict(b)                      # из кэша: дописывать в общий объект нельзя
    rate, why_fx = usd_per_eur(store, b["year"])
    b["fx"] = why_fx
    if not rate:
        return b
    leg = b["bands"]["block_per_dep"].p50
    model = {
        "maint_per_bh": fe.effective_maint_per_h(leg) * rate,
        "util_h_month": fe.monthly_hours,
        "own_per_ac_month": fe.lease_eur_month * rate,
    }
    ratio = cabin_to_cockpit(store)
    crew_eur = fe.effective_crew_per_h(leg)
    if ratio:
        # Модель считает экипаж целиком; полоса — только лётный. Модель
        # приводится к лётному тем же отношением, которым полоса дала бы
        # полный: сравнение одного с одним.
        model["cockpit_per_bh"] = crew_eur / (1 + ratio) * rate
    b["model"] = {k: {"usd": v, "where": b["bands"][k].where(v)}
                  for k, v in model.items() if k in b["bands"]}
    b["leg_h"] = leg
    b["usd_per_eur"] = rate
    b["cabin_ratio"] = ratio
    return b


def note_for(store, icao: str, metric: str, as_of=None) -> str:
    """Одна строка для разбора: полоса в евро и плечо выборки, или ''."""
    try:
        b = type_bench(store, icao)
    except Exception:                                   # noqa: BLE001
        return ""
    if not b or metric not in b.get("bands", {}):
        return ""
    band = b["bands"][metric]
    rate, _ = usd_per_eur(store, b["year"])
    if not rate:
        return ""
    unit = {"maint_per_bh": "EUR/блок-ч", "cockpit_per_bh": "EUR/блок-ч",
            "own_per_ac_month": "EUR/борт·мес", "util_h_month": "ч/мес"}[metric]
    k = 1.0 if metric == "util_h_month" else 1.0 / rate
    leg = b["bands"]["block_per_dep"].p50
    return (f"полоса США, Form 41 {b['year']}: медиана {band.p50 * k:,.0f} {unit}, "
            f"p25–p75 {band.p25 * k:,.0f}–{band.p75 * k:,.0f}, перевозчиков {band.n}, "
            f"среднее плечо выборки {leg:.1f} ч")


# ---------------------------------------------------------------- отчётность перевозчиков

def reports(store) -> list[dict]:
    """Ставки на блок-час по годовой отчётности перевозчиков (решение 183).

    Не по типу, а по перевозчику целиком — парк у большинства однотипный
    или одного семейства, и это сказано в строке. Блок-часы — числом из
    отчёта; если его нет, — налёт в сутки × средний парк × 365 с пометкой
    «оценка». Деньги переводятся в евро курсом хранилища на сегодня: у
    годовой величины курс должен быть средним за год, но ряда в хранилище
    нет, и это написано в выводе.
    """
    from . import fx
    rows = store.db.execute(
        "SELECT key, value, currency, certainty FROM facts WHERE domain = 'carrier_benchmark' "
        "AND valid_to IS NULL").fetchall()
    by = defaultdict(dict)
    for r in rows:
        car, year, name = r["key"].split("/", 2)
        by[(car, int(year))][name] = (r["value"], (r["currency"] or "").upper(), r["certainty"])
    latest = {}
    for car, year in by:
        if year >= latest.get(car, 0):
            latest[car] = year
    out = []
    for car, year in sorted(latest.items()):
        v = by[(car, year)]
        g = lambda k: v[k][0] if k in v else None
        bh, est = g("block_hours"), False
        if not bh and g("utilisation_bh_day"):
            fleet = g("fleet_avg") or (
                (g("fleet_year_end") + g("fleet_year_end_prev")) / 2
                if g("fleet_year_end") and g("fleet_year_end_prev") else None)
            if fleet:
                bh, est = g("utilisation_bh_day") * fleet * 365, True
        if not bh:
            continue

        def eur(k):
            if k not in v:
                return None
            val, cur, _ = v[k]
            if cur in ("", "EUR"):
                return val
            rate, _p = fx.resolve(store, cur, None)
            return val / rate if rate else None

        crew = eur("crew_cost_eur")
        crew_basis = "экипаж" if crew else None
        if crew is None and g("pilot_cost_c_per_ask") and g("ask_km"):
            crew = (g("pilot_cost_c_per_ask") + (g("cabin_cost_c_per_ask") or 0)) / 100 * g("ask_km")
            crew_basis = "пилоты и бортпроводники, ц/ASK × ASK"
        unconfirmed = sorted(k for k, x in v.items() if x[2] != "exact")
        out.append({
            "carrier": car, "year": year, "block_h": bh, "bh_estimated": est,
            "block_per_dep": bh / g("flights") if g("flights") else None,
            "crew_per_bh": crew / bh if crew else None, "crew_basis": crew_basis,
            "staff_per_bh": (eur("staff_cost_eur") / bh) if eur("staff_cost_eur") else None,
            "maint_per_bh": (eur("maintenance_cost_eur") / bh) if eur("maintenance_cost_eur") else None,
            # ТОиР и владение вместе: по МСФО тяжёлые формы капитализируются
            # и уходят в амортизацию, поэтому строка maintenance у
            # европейских перевозчиков — не полный ТОиР. Сумма сравнима
            # лучше, чем каждое слагаемое (решение 183).
            "maint_own_per_bh": ((eur("maintenance_cost_eur") +
                                  (eur("aircraft_ownership_eur") or eur("depreciation_eur"))) / bh)
            if eur("maintenance_cost_eur") and (eur("aircraft_ownership_eur") or eur("depreciation_eur"))
            else None,
            "unconfirmed": unconfirmed,
        })
    return out
