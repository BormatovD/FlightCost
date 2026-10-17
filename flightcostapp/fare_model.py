"""Цена по формуле там, где наблюдений нет (решение 212).

ЧТО ЭТО. Нижний ярус цены пары: степенная зависимость цена = A · км^β
(прямая в логарифмах; первая версия была прямой «база + ставка × км» и в
Европе давала отрицательный наклон — лоукостеры делают цену почти
плоской по расстоянию, а ошибку меряют в процентах, не в евро),
подогнанная по НАШИМ ЖЕ наблюдениям — медианам дневных минимумов
(`market_fare`, прямые, главная полоса по правилу сети, решение 209).
Отдельно по регионам: километр в Европе, в России и в Индии стоит по-разному.
Наблюдение всегда главнее формулы; формула закрывает только пустоту, чтобы
сеть не теряла пару из-за «нет цены».

ЧЕГО ЭТО НЕ ЕСТЬ. Не прогноз цены конкретной линии: формула не знает
конкуренции, лоукостеров на паре, сезона и туристического спроса. Поэтому
у каждой оценки — типичная ошибка формулы на парах, где цена известна
(медиана |ошибки| в процентах), и подпись «оценка по формуле».

Подгонка — по хранилищу при первом обращении и до первой записи в него
(тот же ключ кэша, что у `Store.current`): свёрнутые новые цены сразу
переподгоняют формулу.
"""

from __future__ import annotations

import math

# Регион пары — по первой букве (двум) кода ИКАО. Грубо, но без справочника
# стран: для формулы цены этого достаточно, а пары разных регионов идут
# в общую межрегиональную прямую.
_REGION2 = {"UA": "cis", "UB": "cis", "UC": "cis", "UD": "cis", "UG": "cis", "UK": "cis",
            "UM": "cis", "UT": "cis", "VA": "india", "VE": "india", "VI": "india",
            "VO": "india", "RJ": "east_asia", "RK": "east_asia", "RC": "east_asia",
            "VH": "east_asia", "VM": "east_asia"}
_REGION1 = {"E": "europe", "L": "europe", "U": "russia", "K": "namerica", "C": "namerica",
            "Z": "china", "R": "east_asia", "V": "se_asia", "W": "se_asia",
            "O": "middle_east", "H": "africa", "D": "africa", "F": "africa", "G": "africa",
            "S": "latam", "M": "latam", "T": "latam", "Y": "oceania", "N": "oceania"}
REGION_RU = {"europe": "Европа", "russia": "Россия", "cis": "СНГ", "india": "Индия",
             "china": "Китай", "east_asia": "Восточная Азия", "se_asia": "Юго-Восточная Азия",
             "middle_east": "Ближний Восток", "africa": "Африка", "namerica": "Северная Америка",
             "latam": "Латинская Америка", "oceania": "Океания", "inter": "межрегиональные",
             "all": "все пары"}

MIN_PAIRS = 12          # меньше — прямая региона не строится, берётся общая
FLOOR_EUR = 25.0        # нижняя граница оценки: короткое плечо не бывает бесплатным
_CACHE: dict = {}


def region(icao: str) -> str:
    c = (icao or "").upper()
    return _REGION2.get(c[:2]) or _REGION1.get(c[:1], "other")


def pair_region(a: str, b: str) -> str:
    ra, rb = region(a), region(b)
    if ra == rb:
        return ra
    # Россия и СНГ — один рынок перевозок по цене километра.
    if {ra, rb} <= {"russia", "cis"}:
        return "russia"
    return "inter"


def _km(p, q) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _coords(store) -> dict:
    out = {}
    for (txt,) in store.db.execute(
            "SELECT value_text FROM facts WHERE domain='airport' AND valid_to IS NULL"):
        try:
            latlon, icao, *_ = (txt or "").split("|")
            lat, lon = (float(x) for x in latlon.split(","))
        except ValueError:
            continue
        out[icao.upper()] = (lat, lon)
    return out


def _ols_log(pts):
    """ln цена = ln A + β · ln км: возвращает (A, β)."""
    lp = [(math.log(x), math.log(y)) for x, y in pts if x > 0 and y > 0]
    a, b = _ols(lp)
    return math.exp(a), b


def _ols(pts):
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx <= 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    return my - b * mx, b


def predict(m: dict, km: float) -> float:
    return max(FLOOR_EUR, m["A"] * km ** m["beta"])


def _mdape(pts, A, beta) -> float:
    m = {"A": A, "beta": beta}
    errs = sorted(abs(predict(m, x) - y) / y for x, y in pts if y > 0)
    return errs[len(errs) // 2] if errs else float("nan")


def fit(store, as_of=None) -> dict:
    """{регион: {a, b, n, mdape}} по главной прямой полосе каждой пары."""
    try:
        ver = store._version()
    except Exception:                                    # noqa: BLE001 — нет базы (тестовое хранилище)
        return {}
    key = (id(store), ver)
    if key in _CACHE:
        return _CACHE[key]
    from .network import FARE_BANDS
    rank = {b: i for i, b in enumerate(FARE_BANDS)}
    best: dict = {}
    for k, v, unit, cur in store.db.execute(
            "SELECT key, value, unit, currency FROM facts WHERE domain='market_fare' "
            "AND valid_to IS NULL"):
        parts = (k or "").split("/")
        if len(parts) != 3 or parts[2] != "direct" or parts[1] not in rank or v is None:
            continue
        if ((cur or unit) or "").upper() != "EUR":
            continue
        pr = parts[0]
        if pr not in best or rank[parts[1]] < best[pr][0]:
            best[pr] = (rank[parts[1]], float(v))
    xy = _coords(store) if best else {}
    groups: dict = {}
    for pr, (_, fare) in best.items():
        a, _, b = pr.partition("-")
        if a.upper() not in xy or b.upper() not in xy:
            continue
        km = _km(xy[a.upper()], xy[b.upper()])
        if km < 50:
            continue
        groups.setdefault(pair_region(a, b), []).append((km, fare))
        groups.setdefault("all", []).append((km, fare))
    model = {}
    for g, pts in groups.items():
        if len(pts) < MIN_PAIRS:
            continue
        A, beta = _ols_log(pts)
        beta = max(0.0, beta)                            # цена, падающая с расстоянием, — не модель
        model[g] = {"A": A, "beta": beta, "n": len(pts), "mdape": _mdape(pts, A, beta),
                    "at1000": predict({"A": A, "beta": beta}, 1000.0)}
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = model
    return model


def estimate(store, o_icao: str, d_icao: str, dist_km: float, as_of=None):
    """(EUR, подпись) по формуле региона пары, иначе общей; (None, причина)."""
    model = fit(store, as_of)
    if not model or not dist_km:
        return None, "формулы цены нет: в хранилище мало свёрнутых цен (fca fare --aggregate)"
    g = pair_region(o_icao, d_icao)
    m = model.get(g) or model.get("all")
    if not m:
        return None, "формулы цены нет"
    used = g if g in model else "all"
    fare = predict(m, dist_km)
    b = f"{m['beta']:.2f}".replace(".", ",")
    return fare, (f"оценка по формуле ({REGION_RU.get(used, used)}): {m['at1000']:.0f} EUR за "
                  f"1000 км, цена растёт как км^{b}; по {m['n']} парам с ценой, "
                  f"типичная ошибка ±{m['mdape'] * 100:.0f}%")
