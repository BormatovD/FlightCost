"""Симулятор авиакомпании на одном типе: сеть, парк, нужная доля рынка.

Пользователь выбирает аэропорты, базу, тип и число бортов. Сеть
складывается сама (решение 156): все пары выбранных аэропортов, затем
права, затем пролёт, затем дальность. Ответ — обращением (решение 154):
не «сколько пассажиров мы заберём», а «сколько нужно забрать и по какой
цене, чтобы N бортов окупились», рядом — доля частот и S-кривая как
объявленное допущение (решение 155).

Почему не сумма маршрутов (решение 38). Владение платится за борт в
месяц, и при заданном числе бортов это постоянная сумма парка. Поэтому
каждое плечо считается ядром в режиме «борт уже оплачен», а лизинг
прибавляется один раз — N · ставка. Налёт перестаёт быть допущением и
становится следствием частот.

Экономика плеча линейна по пассажирам, и это используется явно: ядро
зовётся дважды на разной загрузке, из двух точек берутся постоянная часть
рейса и добавка на пассажира. Дальше сеть считается без ядра — сотни
вариантов частот и цен за миллисекунды. Линейность — не допущение, а
свойство статей: пассажирские сборы, обслуживание и топливо от массы
растут с числом пассажиров линейно в рабочем диапазоне. Проверяется
третьей точкой на каждом плече: расхождение больше процента — оговорка
у плеча, а не тихая неточность.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

from .rights import closed_zones, load_closures, pair_rights
from .zones import closed_polygons, load_world

WEEKS_PER_MONTH = 365.25 / 12 / 7

# Доля дистрибуции от выручки — та же величина, что в безубыточности
# ядра. Вторая запись объявлена (решение 102) и сверяется тестом с
# разбором: если ядро её поменяет, сеть не должна разойтись молча.
DIST_RATE = 0.07

# Оценка потока на паре по наблюдённым рейсам: кресел у рейса и загрузка.
# Это не данные, а объявленное допущение — показывается с пометкой и
# заменяется `--market-pax`. Своего источника по рынку Казахстана нет.
MARKET_SEATS = 180
MARKET_LF = 0.80

# Показатель S-кривой «доля частот → доля пассажиров». Отраслевое
# эмпирическое правило, а не измерение (решение 155): значение условное,
# меняется `--alpha`, при 1,0 кривая вырождается в пропорцию.
ALPHA = 1.3

# Порядок полос глубины бронирования при поиске рыночной цены. Средняя
# глубина — ближе к среднему чеку, чем «за неделю» и «за полгода».
FARE_BANDS = ("d15_30", "d31_60", "d08_14", "d61_120", "d00_07", "d121_")

# Если борт на плече поднимает меньше этой доли кресел, пара считается
# недоступной по дальности: такой рейс — не рейс сети, а перегон.
MIN_CAP_SHARE = 0.5


@dataclass
class Leg:
    origin: str                  # ИКАО
    destination: str
    block_h: float
    seats: int
    max_pax: int                 # сколько поднимет на этом плече, ≤ seats
    fixed_eur: float             # на рейс без владения и дистрибуции, при 0 пасс.
    per_pax_eur: float           # добавка на пассажира
    fuel_kg0: float
    fuel_kg_per_pax: float
    fuel_price: float | None     # EUR/кг, взята ядром
    fare_eur: float | None = None
    fare_src: str = ""
    comp_week: float | None = None   # наблюдённых рейсов конкурентов в неделю
    warnings: list = field(default_factory=list)


@dataclass
class Pair:
    a: str                        # коды, как задал пользователь
    b: str
    a_icao: str = ""
    b_icao: str = ""
    ca: str = ""
    cb: str = ""
    dist_km: float = 0.0
    status: str = "ok"            # ok | rights | airspace | range | error
    reasons: list = field(default_factory=list)
    legs: list = field(default_factory=list)
    via: list = field(default_factory=list)     # точки обхода a→b, (lat, lon)
    detour_km: float = 0.0                       # лишние километры обхода
    market_pax_month: float | None = None
    market_src: str = ""

    @property
    def key(self) -> str:
        return f"{self.a}-{self.b}"

    @property
    def priced(self) -> bool:
        return bool(self.legs) and all(l.fare_eur for l in self.legs)


@dataclass
class Fleet:
    """Свойства парка, прочитанные из разбора ядра, а не из кода."""
    aircraft: str
    lease_eur_month: float
    lease_prov: str
    util_h_month: float
    util_prov: str


# ── вспомогательное ─────────────────────────────────────────────────────

def _step(res, node: str):
    for s in getattr(res, "trace", None) or []:
        if getattr(s, "node", None) == node:
            return s
    return None


def _base_cost(res) -> float:
    """Сумма статей без дистрибуции: дистрибуция — доля выручки, и в сети
    она считается от фактического тарифа, а не от безубыточного."""
    return res.cost_total - res.cost.get("distribution", 0.0)


def _lookup(d: dict | None, a: str, b: str, *, directional: bool):
    if not d:
        return None
    for k in ((f"{a}-{b}",) if directional else (f"{a}-{b}", f"{b}-{a}")):
        if k in d:
            return d[k]
    return None


def _row(row, name, default=None):
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def market_fare(store, o_icao: str, d_icao: str, as_of, bands=FARE_BANDS):
    """Медиана дневных минимумов, прямые рейсы. Только евро: пересчёт
    валюты здесь не делается, и чужая валюта — пропуск с причиной, а не
    число под евровой подписью (решение 144)."""
    skipped = []
    for band in bands:
        row = store.get("market_fare", f"{o_icao}-{d_icao}/{band}/direct", as_of)
        if row is None:
            continue
        cur = (_row(row, "currency") or _row(row, "unit") or "").upper()
        if cur != "EUR":
            skipped.append(f"{band}: {cur or 'валюта не указана'}")
            continue
        n = ""
        try:
            import json
            n = json.loads(_row(row, "value_text") or "{}").get("n_days", "")
        except ValueError:
            pass
        return float(row["value"]), f"медиана дневных минимумов {band}, дат {n}"
    if skipped:
        return None, "есть только в другой валюте: " + "; ".join(skipped)
    return None, "наблюдений цены нет"


def observed_frequency(store, as_of) -> tuple[dict, int]:
    """Наблюдённые рейсы по направлениям в неделю и окно наблюдения, сут.

    Домен `observed`, ключи `frequency/<ИКАО>-<ИКАО>/<дата>` со счётом за
    сутки. Окно — от первой до последней даты по всем парам: дни без
    рейса на паре не имеют ключа, и делить на число ключей пары значило
    бы считать частоту только по дням, когда летали.
    """
    rows = store.current("observed", as_of) if hasattr(store, "current") else {}
    counts: dict[str, float] = {}
    dates = set()
    for key, row in rows.items():
        if not key.startswith("frequency/"):
            continue
        _, pair, day = key.split("/", 2)
        counts[pair] = counts.get(pair, 0.0) + float(row["value"] or 0)
        dates.add(day[:10])
    if not dates:
        return {}, 0
    d0, d1 = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
    window = (d1 - d0).days + 1
    return {k: v / window * 7 for k, v in counts.items()}, window


# ── формирование сети ───────────────────────────────────────────────────

def _leg(econ, store, o, d, *, aircraft, as_of, month, overrides, operator, via=None):
    kw = dict(aircraft=aircraft, as_of=as_of, month=month, overrides=overrides,
              operator=operator, util_mode="marginal", _trade=False, via=via)
    r_full = econ(store, o, d, load_factor=1.0, **kw)
    seats = int(r_full.inputs["seats"])
    cap = int(r_full.max_pax) if r_full.max_pax else seats
    p_hi = max(0, min(seats, cap))
    if p_hi == 0:
        return Leg(o, d, r_full.block_h, seats, 0, 0, 0, r_full.fuel_kg, 0,
                   None, warnings=list(r_full.warnings)), r_full
    r1 = r_full if p_hi == seats else econ(store, o, d, load_factor=p_hi / seats, **kw)
    r2 = econ(store, o, d, load_factor=p_hi / seats / 2, **kw)
    p1, p2 = float(r1.inputs["pax"]), float(r2.inputs["pax"])
    b1, b2 = _base_cost(r1), _base_cost(r2)
    v = (b1 - b2) / (p1 - p2)
    fpp = (r1.fuel_kg - r2.fuel_kg) / (p1 - p2)
    price = (r1.cost.get("fuel", 0.0) / r1.fuel_kg) if r1.fuel_kg else None
    warn = list(dict.fromkeys(r1.warnings))
    # Третья точка: линейность — свойство статей, но ступени тарифов (полосы
    # массы, минимумы) могут её сломать. Расхождение — оговорка у плеча.
    r3 = econ(store, o, d, load_factor=p_hi / seats * 0.75, **kw)
    p3 = float(r3.inputs["pax"])
    pred = b1 - v * (p1 - p3)
    if b1 and abs(_base_cost(r3) - pred) > 0.01 * abs(_base_cost(r3)):
        warn.append(f"{o}→{d}: стоимость рейса нелинейна по пассажирам "
                    f"({_base_cost(r3):,.0f} против {pred:,.0f} по прямой) — "
                    f"ступень тарифа; сеть считает по прямой")
    return Leg(o, d, r1.block_h, seats, p_hi, b1 - v * p1, v,
               r1.fuel_kg - fpp * p1, fpp, price, warnings=warn), r1


def fleet_from_core(econ, store, o, d, *, aircraft, as_of, month, overrides,
                    operator) -> Fleet:
    """Ставка лизинга и типовой налёт — из разбора ядра в режиме «типовой
    по флоту», с их происхождением. Сеть не заводит своих констант."""
    r = econ(store, o, d, aircraft=aircraft, as_of=as_of, month=month,
             overrides=overrides, operator=operator, load_factor=0.8,
             util_mode="fleet_average", _trade=False)
    lease, util = _step(r, "d_fleet"), _step(r, "v_util")
    if lease is None or util is None:
        raise RuntimeError("в разборе ядра нет шагов d_fleet / v_util — "
                           "сеть не может прочесть ставку и налёт")
    return Fleet(r.aircraft, float(lease.value), lease.prov,
                 float(util.value), util.prov)


def form_network(store, airports, *, base: str, aircraft: str, as_of=None,
                 month=None, overrides=None, operator="*",
                 user_fares=None, user_market=None, fare_bands=FARE_BANDS,
                 closures=None, econ=None, crossing_fn=None, airport_fn=None,
                 gc_nm=None, world_zones=None, detour_fn=None) -> list[Pair]:
    """Все пары выбранных аэропортов с причиной, почему пара в сети или нет."""
    if econ is None or airport_fn is None or gc_nm is None:
        from . import econ as _e
        econ = econ or _e.route_economics
        airport_fn = airport_fn or _e._airport
        gc_nm = gc_nm or _e.great_circle_nm
    if crossing_fn is None:
        from .airspace import crossing as crossing_fn
    if closures is None:
        closures = load_closures()
    if detour_fn is None:
        from .detour import detour as detour_fn
    as_of = str(as_of or date.today())
    if world_zones is None:
        world_zones = load_world()
    no_world = not world_zones

    codes = [c.strip().upper() for c in airports if c.strip()]
    base = base.strip().upper()
    if base not in codes:
        codes.insert(0, base)
    codes = list(dict.fromkeys(codes))
    info = {c: airport_fn(store, c, as_of) for c in codes}
    carrier = info[base]["country"]
    comp, _window = observed_frequency(store, as_of)

    pairs = []
    for x, y in combinations(codes, 2):
        ax, ay = info[x], info[y]
        nm = gc_nm(ax["lat"], ax["lon"], ay["lat"], ay["lon"])
        p = Pair(x, y, ax["icao"], ay["icao"], ax["country"], ay["country"],
                 dist_km=nm * 1.852)
        v = pair_rights(carrier, p.ca, p.cb, as_of, closures)
        if not v.ok:
            p.status, p.reasons = "rights", v.reasons
            pairs.append(p)
            continue
        zones = dict(crossing_fn(ax["lat"], ax["lon"], ay["lat"], ay["lon"], nm).zones)
        shut = closed_zones(carrier, zones, as_of, closures)
        if shut:
            # Прямая идёт через закрытое небо — строится обход (решение 158).
            # Без мировых границ обход не построить: пара уходит с причиной,
            # а не считается по прямой.
            if no_world:
                p.status = "airspace"
                p.reasons = shut + [{"kind": "no_detour", "text":
                                     "нет файла границ data/geo/zones_world.json — "
                                     "fca refresh --only fir_world"}]
                pairs.append(p)
                continue
            dt = detour_fn((ax["lat"], ax["lon"]), (ay["lat"], ay["lon"]),
                           closed_polygons(carrier, as_of, closures, world_zones))
            if not dt.found:
                p.status = "airspace"
                p.reasons = shut + [{"kind": "no_detour", "text": w} for w in dt.warnings]
                pairs.append(p)
                continue
            p.via = [tuple(w) for w in dt.waypoints[1:-1]]
            p.detour_km = dt.extra_km
            p.reasons = [{"kind": "detour", "text":
                          f"обход {', '.join(dt.avoided)}: +{dt.extra_km:,.0f} км "
                          f"(+{dt.extra_share * 100:.1f}%) через {len(p.via)} т."}]
            p.reasons += [{"kind": "detour_warning", "text": w} for w in dt.warnings]
        try:
            for o, d in ((x, y), (y, x)):
                via = p.via if (o, d) == (x, y) else list(reversed(p.via))
                leg, _r = _leg(econ, store, o, d, aircraft=aircraft, as_of=as_of,
                               month=month, overrides=overrides, operator=operator,
                               via=via or None)
                oi, di = info[o]["icao"], info[d]["icao"]
                given = _lookup(user_fares, o, d, directional=True)
                if given is None:
                    given = _lookup(user_fares, o, d, directional=False)
                if given is not None:
                    leg.fare_eur, leg.fare_src = float(given), "задано"
                else:
                    leg.fare_eur, leg.fare_src = market_fare(store, oi, di, as_of, fare_bands)
                leg.comp_week = comp.get(f"{oi}-{di}") if comp else None
                p.legs.append(leg)
        except (KeyError, ValueError, RuntimeError) as exc:
            p.status, p.reasons = "error", [{"kind": "error", "text": str(exc)}]
            pairs.append(p)
            continue
        worst = min(p.legs, key=lambda l: l.max_pax / l.seats if l.seats else 0)
        if worst.max_pax < MIN_CAP_SHARE * worst.seats:
            p.status = "range"
            p.reasons = p.reasons + [{"kind": "range", "text":
                          f"{worst.origin}→{worst.destination}: поднимет {worst.max_pax} "
                          f"из {worst.seats} кресел — меньше половины"}]
        elif worst.max_pax < worst.seats:
            p.reasons = p.reasons + [{"kind": "range_partial", "text":
                          f"{worst.origin}→{worst.destination}: не больше "
                          f"{worst.max_pax} пассажиров из {worst.seats}"}]
        given = _lookup(user_market, x, y, directional=False)
        if given is not None:
            p.market_pax_month, p.market_src = float(given), "задано"
        elif comp:
            c = sum((l.comp_week or 0.0) for l in p.legs)
            p.market_pax_month = c * WEEKS_PER_MONTH * MARKET_SEATS * MARKET_LF
            p.market_src = (f"оценка: наблюдённые рейсы × {MARKET_SEATS} кресел × "
                            f"{MARKET_LF:.2f}")
        else:
            p.market_src = "нет: ни наблюдений рейсов, ни заданного потока"
        pairs.append(p)
    return pairs


# ── симуляция ───────────────────────────────────────────────────────────

@dataclass
class PairResult:
    key: str
    freq_week: int
    seats_month: float
    pax_month: float
    revenue_month: float
    contribution_month: float      # вклад в парк: выручка минус свои рейсы, при lf_ref
    lf_own: float | None           # загрузка, при которой пара окупает свои рейсы (без парка)
    market_pax_month: float | None
    need_share: float | None
    freq_share: float | None
    s_share: float | None
    comp_week: float | None


@dataclass
class NetResult:
    fleet: int
    aircraft: str
    lease_eur_month: float
    lease_prov: str
    util_h_month: float
    util_prov: str
    hours_used: float
    lf_ref: float
    fare_mult: float
    fare_conv: float
    alpha: float
    breakeven_lf: float | None
    profit_at_ref: float
    fare_mult_breakeven: float | None
    lease_breakeven: float | None
    fuel_price_now: float | None
    fuel_price_breakeven: float | None
    pairs: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # Оговорки ядра по плечам: тарифов нет, сборы по параметрике, ступени.
    # Отдельно от оговорок сети — у них разный адресат (решение 76).
    core_warnings: list = field(default_factory=list)


def _pax(leg: Leg, lf: float) -> float:
    return min(lf * leg.seats, leg.max_pax)


def _net_rev(leg: Leg, k: float) -> float:
    return leg.fare_eur * k * (1 - DIST_RATE)


def _profit(flown, fleet_n, lease, lf, k, dfuel=0.0) -> float:
    total = -fleet_n * lease
    for p, f in flown:
        m = f * WEEKS_PER_MONTH
        for l in p.legs:
            pax = _pax(l, lf)
            fuel = l.fuel_kg0 + l.fuel_kg_per_pax * pax
            total += m * (pax * (_net_rev(l, k) - l.per_pax_eur) - l.fixed_eur - dfuel * fuel)
    return total


def _bisect(fn, lo, hi, it=80):
    flo, fhi = fn(lo), fn(hi)
    if flo * fhi > 0:
        return None
    for _ in range(it):
        mid = (lo + hi) / 2
        fm = fn(mid)
        if (fm > 0) == (fhi > 0):
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def simulate(pairs: list[Pair], *, fleet: Fleet, fleet_n: int, freq=None,
             util_h_month=None, lease_eur_month=None, fare_mult=1.0,
             fare_conv=1.0, lf_ref=0.80, alpha=ALPHA) -> NetResult:
    if fleet_n < 1:
        raise ValueError("бортов меньше одного")
    warnings = []
    lease = float(lease_eur_month if lease_eur_month is not None else fleet.lease_eur_month)
    lease_prov = "input" if lease_eur_month is not None else fleet.lease_prov
    util = float(util_h_month if util_h_month is not None else fleet.util_h_month)
    util_prov = "input" if util_h_month is not None else fleet.util_prov

    excluded = [p for p in pairs if p.status != "ok"]
    ok = [p for p in pairs if p.status == "ok"]
    for p in ok:
        if not p.priced:
            excluded.append(p)
            p.reasons = p.reasons + [{"kind": "no_fare", "text": "нет цены: " + "; ".join(
                f"{l.origin}→{l.destination} — {l.fare_src}" for l in p.legs if not l.fare_eur)
                + " — задайте --fare"}]
    live = [p for p in ok if p.priced]
    if not live:
        raise ValueError("в сети не осталось ни одной пары с ценой и правом летать")

    rt_h = {p.key: sum(l.block_h for l in p.legs) for p in live}
    if freq:
        f_of = {}
        for p in live:
            f = _lookup(freq, p.a, p.b, directional=False)
            f_of[p.key] = int(f or 0)
        idle = [k for k, f in f_of.items() if f == 0]
        if idle:
            warnings.append("частота не задана — пары не летаются: " + ", ".join(idle))
    else:
        H = fleet_n * util
        f_eq = int(H // (WEEKS_PER_MONTH * sum(rt_h.values())))
        if f_eq < 1:
            raise ValueError(
                f"{fleet_n} бортов при налёте {util:.0f} ч/мес не хватает даже на "
                f"рейс в неделю на каждой из {len(live)} пар — задайте частоты "
                f"вручную (--freq) или увеличьте парк")
        f_of = {p.key: f_eq for p in live}
        warnings.append(f"частоты не заданы — разложено поровну: {f_eq} рейсов в "
                        f"неделю туда-обратно на каждой паре, сколько вывозит парк")
    flown = [(p, f_of[p.key]) for p in live if f_of[p.key] > 0]
    hours = sum(f * WEEKS_PER_MONTH * rt_h[p.key] for p, f in flown)
    if hours > fleet_n * util * 1.0001:
        warnings.append(f"налёт {hours / fleet_n:,.0f} ч/мес на борт выше принятого "
                        f"{util:,.0f}: расписание с такими частотами {fleet_n} бортами "
                        f"не выполнить — либо больше бортов, либо меньше рейсов")

    be_lf = _bisect(lambda x: _profit(flown, fleet_n, lease, x, fare_mult * fare_conv), 0.0, 1.0)
    pr_ref = _profit(flown, fleet_n, lease, lf_ref, fare_mult * fare_conv)
    be_k = _bisect(lambda k: _profit(flown, fleet_n, lease, lf_ref, k * fare_conv), 0.0, 20.0)
    be_lease = lease + pr_ref / fleet_n
    fuel_kg = sum(f * WEEKS_PER_MONTH * (l.fuel_kg0 + l.fuel_kg_per_pax * _pax(l, lf_ref))
                  for p, f in flown for l in p.legs)
    cost_fuel = sum(f * WEEKS_PER_MONTH * (l.fuel_kg0 + l.fuel_kg_per_pax * _pax(l, lf_ref))
                    * (l.fuel_price or 0.0) for p, f in flown for l in p.legs)
    p_now = cost_fuel / fuel_kg if fuel_kg else None
    p_be = (p_now + pr_ref / fuel_kg) if (p_now is not None and fuel_kg) else None

    lf_need = be_lf if be_lf is not None else None
    out_pairs = []
    for p, f in flown:
        m = f * WEEKS_PER_MONTH
        lf_use = lf_need if lf_need is not None else lf_ref
        pax = sum(_pax(l, lf_use) * m for l in p.legs)
        rev = sum(_pax(l, lf_ref) * m * _net_rev(l, fare_mult * fare_conv) for l in p.legs)
        contrib = sum(m * (_pax(l, lf_ref) * (_net_rev(l, fare_mult * fare_conv) - l.per_pax_eur)
                           - l.fixed_eur) for l in p.legs)
        cw = None
        if all(l.comp_week is not None for l in p.legs):
            cw = sum(l.comp_week for l in p.legs) / len(p.legs)
        fs = ss = None
        if cw is not None:
            fs = f / (f + cw) if (f + cw) else None
            ss = f ** alpha / (f ** alpha + cw ** alpha) if (f + cw) else None
        need = (pax / p.market_pax_month) if (p.market_pax_month and lf_need is not None) else None
        # Экономика пары без раскладки лизинга (решение 159): при какой
        # загрузке пара окупает свои рейсы и сколько при расчётной
        # загрузке приносит в парк. Сеть в нуле там, где сумма вкладов
        # равна лизингу парка; делить лизинг по парам нечем и незачем.
        lf_p = _bisect(lambda x: _profit([(p, f)], 0, 0.0, x, fare_mult * fare_conv),
                       0.0, 1.0)
        out_pairs.append(PairResult(p.key, f, sum(l.seats for l in p.legs) * m, pax, rev,
                                    contrib, lf_p, p.market_pax_month, need, fs, ss, cw))

    if fare_conv == 1.0:
        warnings.append("медиана дневных минимумов принята за средний чек (--fare-conv 1): "
                        "минимум ниже среднего, выручка занижена на неизвестную величину")
    if any(r.s_share is not None for r in out_pairs):
        warnings.append(f"S-кривая — отраслевое допущение, не измерение: показатель "
                        f"{alpha} условный, конкуренты сложены в одного (это занижает "
                        f"нашу долю при показателе больше 1)")
    if any(p.market_src.startswith("оценка") for p, _ in flown):
        warnings.append("поток на паре — оценка по наблюдённым рейсам; спрос, который "
                        "создаёт новый перевозчик, не учтён — доля считается от "
                        "нынешнего потока")
    warnings.append("третья и четвёртая свободы считаются доступными: двусторонние "
                    "соглашения о воздушном сообщении не проверяются")
    warnings.append("расписание проверено только суммой часов: развороты, ночёвки "
                    "и окна аэропортов — этап ротации (M15)")
    if any(p.via for p, _ in flown):
        warnings.append("обход закрытого неба — кратчайший по границам зон с зазором "
                        f"{25} км, без структуры трасс и высотных ограничений; "
                        "границы вне Европы — данные сообщества VATSIM, не официальные")
    core = list(dict.fromkeys(w for p, _ in flown for l in p.legs for w in l.warnings))
    unconf = {r["id"]: r for p in pairs for r in p.reasons
              if r.get("certainty") == "reading_unconfirmed"}
    for r in unconf.values():
        warnings.append(f"закрытие {r['id']} записано без сверки с документом — "
                        f"подтвердить: {r.get('confirm_by') or r.get('source')}")

    return NetResult(fleet_n, fleet.aircraft, lease, lease_prov, util, util_prov, hours,
                     lf_ref, fare_mult, fare_conv, alpha, be_lf, pr_ref, be_k,
                     be_lease, p_now, p_be, out_pairs, excluded, warnings, core)


# ── отчёт ───────────────────────────────────────────────────────────────

STATUS_RU = {"rights": "права", "airspace": "небо", "range": "дальность",
             "error": "ошибка", "ok": "нет цены"}


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def report(net: NetResult, pairs: list[Pair], *, base: str) -> str:
    L = []
    L.append(f"СЕТЬ  база {base} · {net.aircraft} × {net.fleet}")
    L.append("=" * 78)
    pax_h = "нужно пасс." if net.breakeven_lf is not None else f"пасс.@{net.lf_ref:.0%}"
    L.append(f"{'пара':<10}{'км':>7}{'рейс/нед':>9}{'кресел/мес':>11}{'рейсы в 0':>10}"
             f"{'вклад':>8}{pax_h:>12}{'поток/мес':>11}{'нужно':>7}{'частоты':>8}{'S':>6}")
    for r in net.pairs:
        p = next(x for x in pairs if x.key == r.key)
        L.append(f"{r.key:<10}{p.dist_km:>7,.0f}{r.freq_week:>9}{r.seats_month:>11,.0f}"
                 f"{_pct(r.lf_own) if r.lf_own is not None else '>100%':>10}"
                 f"{r.contribution_month / 1000:>8,.0f}"
                 f"{r.pax_month:>12,.0f}"
                 f"{(f'{r.market_pax_month:,.0f}' if r.market_pax_month else '—'):>11}"
                 f"{_pct(r.need_share):>7}{_pct(r.freq_share):>8}{_pct(r.s_share):>6}")
    L.append("")
    L.append(f"  рейсы в 0 — загрузка, при которой пара окупает свои рейсы, без парка;")
    L.append(f"  вклад — тыс. EUR/мес в лизинг парка при загрузке {net.lf_ref:.0%}; сеть в нуле,")
    L.append(f"  когда сумма вкладов равна лизингу парка ({net.fleet * net.lease_eur_month / 1000:,.0f} тыс.);")
    L.append("  нужно — доля нынешнего потока при безубыточной загрузке сети;")
    L.append("  частоты — наша доля рейсов; S — что даёт S-кривая (допущение)")
    over = [r.key for r in net.pairs if r.need_share is not None and r.need_share > 1]
    if over:
        L.append(f"  больше всего нынешнего потока нужно на: {', '.join(over)} — "
                 f"частоты выше, чем рынок способен заполнить")
    if net.excluded:
        L.append("\nНЕ В СЕТИ")
        for p in net.excluded:
            why = "; ".join(r["text"] for r in p.reasons) or "—"
            L.append(f"  {p.key:<10}{STATUS_RU.get(p.status, p.status):<10}{why}")
    det = [(p, r) for p in pairs if p.status == "ok"
           for r in p.reasons if r["kind"] == "detour"]
    if det:
        L.append("\nС ОБХОДОМ ЗАКРЫТОГО НЕБА")
        for p, r in det:
            L.append(f"  {p.key:<10}{r['text']}")
    partial = [(p, r) for p in pairs if p.status == "ok"
               for r in p.reasons if r["kind"] == "range_partial"]
    if partial:
        L.append("\nОГРАНИЧЕНО ДАЛЬНОСТЬЮ")
        for p, r in partial:
            L.append(f"  {p.key:<10}{r['text']}")

    L.append("\nПАРК")
    L.append(f"  лизинг        {net.lease_eur_month:>12,.0f} EUR/мес на борт   [{net.lease_prov}]")
    L.append(f"  налёт         {net.hours_used / net.fleet:>12,.0f} ч/мес на борт      "
             f"из принятых {net.util_h_month:,.0f} [{net.util_prov}]")
    L.append("\nУСЛОВИЯ")
    L.append(f"  цена          медиана рынка × {net.fare_mult:.2f}"
             + (f" × {net.fare_conv:.2f} (минимум → средний чек)" if net.fare_conv != 1 else ""))
    if net.breakeven_lf is not None:
        L.append(f"  безубыточная загрузка сети          {net.breakeven_lf * 100:5.1f}%")
    else:
        L.append("  безубыточной загрузки нет: сеть не окупается даже полными бортами")
    L.append(f"  при загрузке {net.lf_ref * 100:.0f}%: результат "
             f"{net.profit_at_ref:,.0f} EUR в месяц")
    if net.fare_mult_breakeven is not None:
        L.append(f"  цена в ноль при {net.lf_ref * 100:.0f}%      медиана × "
                 f"{net.fare_mult_breakeven:.2f}")
    if net.lease_breakeven is not None:
        L.append(f"  лизинг в ноль                      {net.lease_breakeven:,.0f} EUR/мес")
    if net.fuel_price_breakeven is not None:
        L.append(f"  топливо в ноль                     {net.fuel_price_breakeven:.3f} EUR/кг "
                 f"(сейчас {net.fuel_price_now:.3f})")
    L.append("\nОГОВОРКИ СЕТИ")
    for w in net.warnings:
        L.append(f"  - {w}")
    if net.core_warnings:
        L.append("\nОГОВОРКИ ЯДРА ПО ПЛЕЧАМ")
        for w in net.core_warnings[:20]:
            L.append(f"  - {w}")
        if len(net.core_warnings) > 20:
            L.append(f"  …и ещё {len(net.core_warnings) - 20} — fca econ по паре")
    return "\n".join(L)
