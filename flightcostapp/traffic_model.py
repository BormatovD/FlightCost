"""Поток пары по модели, когда нет ни статистики, ни наблюдённых рейсов (решение 214).

ЧТО ЭТО. Гравитационная модель, нижний ярус потока:

    ln(поток) = c_региона + α · ln(масса A × масса B) + β₁ · ln(км) + β₂ · ln²(км)

МАССА АЭРОПОРТА. Первая версия брала массой население вокруг аэропорта и
на 12 тыс. пар объяснила четверть разброса (R² 0,25, ошибка в 2,3 раза):
у Франкфурта 6 млн жителей вокруг и 5 млн пассажиров в месяц, у города
того же размера без хаба — в десять раз меньше. Поэтому масса — поток
самого аэропорта по нашей же статистике (сумма опубликованных пар; при
подгонке — без самой пары, иначе модель подглядывает ответ). Нет у
аэропорта статистики — масса по жителям в 150 км (GeoNames, полностью до
50 км и с убыванием дальше), переведённая в «пассажиры» медианным
отношением своего региона. Ошибка у двух случаев разная, и подпись
называет ту, что относится к оценке.

Квадрат логарифма расстояния — потому что поток не убывает с расстоянием
монотонно: короткие пары отнимают поезд и машина. Коэффициенты
подгоняются по НАШЕМУ опубликованному потоку (домен `traffic`: Eurostat,
T-100, DGCA, сводка по РФ) — та же идея, что у цены по формуле (решение
212): модель учится на парах, где поток известен, и сама говорит, во
сколько раз она обычно ошибается.

ЧЕГО ОНА НЕ ЗНАЕТ — и это пишется в подписи оценки:
* туризма: у Анталии мало жителей и огромный поток — курорт модель занизит;
* поездов: FRA–CGN, MAD–BCN модель завысит, о железной дороге она не знает;
* хабов, у которых нет статистики: пересадочный поток через них в
  население не укладывается;
* городов с несколькими аэропортами: у LHR и LGW одна зона охвата, поток
  Лондона каждому из них модель отдаст целиком.

Порядок ярусов не меняется: заданное человеком → статистика → оценка по
наблюдённым рейсам → эта модель. Модель только закрывает пустоту.
"""

from __future__ import annotations

import math

import numpy as np

R_FULL, R_ZERO = 50.0, 150.0     # км: жители полностью до 50, ноль после 150
MIN_CATCH = 15000.0              # зона без городов GeoNames — не ноль, а малый город
MIN_PAIRS = 30                   # меньше — модели нет
MIN_REGION = 25                  # своя постоянная региона — от стольких пар
SHORT_KM = 300.0                 # короче — пара, которую обычно отнимает поезд и автобус
_CACHE: dict = {}


def _ver(store):
    try:
        return (id(store.db), store._version())
    except Exception:                                    # noqa: BLE001
        return None


def _cities(store):
    key = ("cities", _ver(store))
    if key in _CACHE:
        return _CACHE[key]
    lat, lon, pop = [], [], []
    for v, txt in store.db.execute(
            "SELECT value, value_text FROM facts WHERE domain='city' AND valid_to IS NULL"):
        try:
            la, lo = (float(x) for x in (txt or "").split("|", 1)[0].split(","))
        except ValueError:
            continue
        lat.append(la), lon.append(lo), pop.append(float(v or 0))
    arr = (np.radians(lat), np.radians(lon), np.array(pop)) if pop else None
    _CACHE[key] = arr
    return arr


def catchment(store, lat: float, lon: float) -> float | None:
    """Жители зоны охвата точки; None — городов в хранилище нет."""
    cs = _cities(store)
    if cs is None:
        return None
    la, lo, pop = cs
    p1, l1 = math.radians(lat), math.radians(lon)
    h = (np.sin((la - p1) / 2) ** 2 + math.cos(p1) * np.cos(la) * np.sin((lo - l1) / 2) ** 2)
    d = 2 * 6371.0 * np.arcsin(np.minimum(1.0, np.sqrt(h)))
    w = np.clip((R_ZERO - d) / (R_ZERO - R_FULL), 0.0, 1.0)
    return max(MIN_CATCH, float((w * pop).sum()))


MIN_SLOPE = 200                  # своя степень по массе у региона — от стольких пар


def _xrow(xa, xb, km, region, shifts, slopes=()):
    """Признаки пары. `slopes` — регионы со своей степенью по массе: у
    звёздной сети России поток растёт с размером концов круче, чем у
    плотной сети США, и одна общая степень занижала Москву в десятки раз."""
    ld = math.log(km / 1000.0)
    x = xa + xb
    return ([1.0, x, ld, ld * ld] + [1.0 if region == g else 0.0 for g in shifts]
            + [x if region == g else 0.0 for g in slopes])


def _node(code: str) -> str:
    """Узел модели: аэропорт, а аэропорт города, который источник не делит
    (Москва в сводке по РФ, решение 201), — сам город."""
    from .traffic import CITY_OF
    c = (code or "").upper()
    return CITY_OF.get(c, c)


def _node_xy(xy: dict, node: str):
    from .traffic import CITY_GROUPS
    if node in CITY_GROUPS:
        return next((xy[a] for a in CITY_GROUPS[node] if a in xy), None)
    return xy.get(node)


def _node_region(node: str) -> str:
    from .fare_model import region
    from .traffic import CITY_GROUPS
    return region(CITY_GROUPS[node][0] if node in CITY_GROUPS else node)


def _ols(rows, y, folds=5):
    """Коэффициенты, R² и ошибка «во сколько раз» на отложенных парах."""
    X, y = np.array(rows), np.array(y)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    r2 = 1 - float((res ** 2).sum()) / float(((y - y.mean()) ** 2).sum() or 1)
    out = np.empty_like(y)
    idx = np.arange(len(y)) % folds
    for k in range(folds):
        tr, te = idx != k, idx == k
        c, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        out[te] = y[te] - X[te] @ c
    return {"coef": coef.tolist(), "r2": r2,
            "factor": math.exp(float(np.median(np.abs(res)))),
            "factor_cv": math.exp(float(np.median(np.abs(out))))}


def _flows(store, as_of):
    """{(A, B): пасс./мес} опубликованных пар и поток каждого аэропорта."""
    key = ("flows", _ver(store), as_of)
    if key in _CACHE:
        return _CACHE[key]
    from .traffic import _pair_index, _published
    # Узлы, а не коды: поток сводки по РФ лежит под «@MOW», и без этого у
    # Шереметьева была только международная статистика — 271 тыс. в месяц
    # вместо миллионов, а Москва–Новосибирск выпадал из подгонки вовсе.
    # Один и тот же поток узлов под разными ключами берётся максимумом, а
    # не суммой: разные издатели описывают одних и тех же пассажиров.
    flows, thr = {}, {}
    for pair in _pair_index(store, as_of):
        a, _, b = pair.partition("-")
        got = _published(store, a, b, as_of) if (a and b) else None
        if not got or not got.get("pax_month"):
            continue
        na, nb = sorted((_node(a), _node(b)))
        if na == nb:
            continue
        # DGCA относит поток города к главному аэропорту (Лондон → LHR,
        # Париж → CDG, решение 201): это поток города под кодом аэропорта.
        # Узлом такой город не заведён — пара пропускается, чтобы не
        # раздувать массу LHR потоком Гатвика и Станстеда.
        if "город, а не аэропорт" in (got.get("src") or "") and not (
                na.startswith("@") or nb.startswith("@")):
            continue
        flows[(na, nb)] = max(flows.get((na, nb), 0.0), float(got["pax_month"]))
    for (na, nb), f in flows.items():
        thr[na] = thr.get(na, 0.0) + f
        thr[nb] = thr.get(nb, 0.0) + f
    _CACHE[key] = (flows, thr)
    return flows, thr


MIN_THR = 1000.0                 # пасс./мес: меньше — у аэропорта статистики, считай, нет
SHRINK = 2.0                     # поправка аэропорта по n парам весит n / (n + 2)
MIN_AP_PAIRS = 3                 # меньше пар — поправки аэропорта нет


def _effects(pairs, resid, iters=20):
    """Поправка каждого аэропорта: насколько его пары в среднем больше или
    меньше формулы (в логарифмах), со сжатием к нулю у малых выборок.
    Чередующиеся средние, а не общая система: аэропортов тысячи, пары —
    разреженная матрица."""
    mu: dict = {}
    nb: dict = {}
    for a, b in pairs:
        nb[a] = nb.get(a, 0) + 1
        nb[b] = nb.get(b, 0) + 1
    for _ in range(iters):
        acc: dict = {}
        for (a, b), r in zip(pairs, resid):
            acc[a] = acc.get(a, 0.0) + r - mu.get(b, 0.0)
            acc[b] = acc.get(b, 0.0) + r - mu.get(a, 0.0)
        mu = {k: acc[k] / (nb[k] + SHRINK) for k in acc}
    return mu, nb


def _fit_effects(X, y, pairs, folds=5):
    """Формула по массам плюс поправки аэропортов; ошибка — на отложенных
    парах, у которых оба аэропорта есть в обучающей части не менее чем
    MIN_AP_PAIRS раз (это и есть случай, где поправка применяется)."""
    X, y = np.array(X), np.array(y)
    idx = np.arange(len(y)) % folds
    errs = []
    for k in range(folds):
        tr, te = idx != k, idx == k
        c, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        ptr = [pairs[i] for i in np.where(tr)[0]]
        mu, nb = _effects(ptr, (y[tr] - X[tr] @ c).tolist())
        for i in np.where(te)[0]:
            a, b = pairs[i]
            if nb.get(a, 0) >= MIN_AP_PAIRS and nb.get(b, 0) >= MIN_AP_PAIRS:
                errs.append(abs(y[i] - X[i] @ c - mu[a] - mu[b]))
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    mu, nb = _effects(pairs, (y - X @ c).tolist())
    return {"mu": mu, "nb": nb, "n_eval": len(errs),
            "factor_cv": math.exp(float(np.median(errs))) if errs else None}


def fit(store, as_of=None) -> dict:
    """Две модели: по потоку аэропортов (T) и по жителям (P)."""
    v = _ver(store)
    if v is None:
        return {}
    from datetime import date
    as_of = str(as_of or date.today())
    key = ("fit4", v, as_of)
    if key in _CACHE:
        return _CACHE[key]
    from .fare_model import _coords, _km, pair_region
    if _cities(store) is None:
        _CACHE[key] = {}
        return {}
    xy = _coords(store)
    flows, thr = _flows(store, as_of)
    pos = {}
    for k in thr:
        q = _node_xy(xy, k)
        if q:
            pos[k] = q
    catch = {}

    def cat(k):
        if k not in catch:
            catch[k] = catchment(store, *pos[k])
        return catch[k]

    region = _node_region
    # Перевод жителей в «пассажиры»: медиана ln(поток / жители) по региону.
    ratios: dict = {}
    for k, T in thr.items():
        if k in pos and T >= MIN_THR:
            ratios.setdefault(region(k), []).append(math.log(T) - math.log(cat(k)))
    allr = sorted(x for v_ in ratios.values() for x in v_)
    c0 = {g: sorted(v_)[len(v_) // 2] for g, v_ in ratios.items() if len(v_) >= 10}
    c0["all"] = allr[len(allr) // 2] if allr else 0.0
    obs = []
    for (a, b), f in flows.items():
        if a not in pos or b not in pos:
            continue
        km = _km(pos[a], pos[b])
        if km < 100:
            continue
        ta, tb = thr.get(a, 0) - f, thr.get(b, 0) - f
        ra, rb = region(a), region(b)
        g = ra if ra == rb else ("russia" if {ra, rb} <= {"russia", "cis"} else "inter")
        obs.append((a, b, km, g, f, ta, tb))
    if len(obs) < MIN_PAIRS:
        _CACHE[key] = {"n": len(obs)}
        return _CACHE[key]
    counts: dict = {}
    for o in obs:
        counts[o[3]] = counts.get(o[3], 0) + 1
    regions = sorted(g for g, n in counts.items() if n >= MIN_REGION)
    base = max(regions, key=lambda g: counts[g]) if regions else None
    shifts = [g for g in regions if g != base]
    slopes = [g for g in shifts if counts[g] >= MIN_SLOPE]
    px = lambda k: math.log(cat(k)) + c0.get(region(k), c0["all"])     # noqa: E731
    # T — обе массы по статистике (без самой пары); P — обе по жителям.
    rt, yt, rp, yp, pt = [], [], [], [], []
    for a, b, km, g, f, ta, tb in obs:
        if ta >= MIN_THR and tb >= MIN_THR:
            rt.append(_xrow(math.log(ta), math.log(tb), km, g, shifts, slopes))
            yt.append(math.log(f))
            pt.append((a, b))
        rp.append(_xrow(px(a), px(b), km, g, shifts, slopes))
        yp.append(math.log(f))
    model = {"n": len(obs), "counts": counts, "shifts": shifts, "slopes": slopes,
             "base": base, "c0": c0,
             "P": _ols(rp, yp)}
    if len(rt) >= MIN_PAIRS:
        model["T"] = _ols(rt, yt)
        model["T"]["n"] = len(rt)
        # Поправки аэропортов (решение 217): формула знает размер узлов, но
        # не их характер — у звёздной сети Москвы пары крупнее, чем
        # предсказывает размер. Поправка учится на собственных парах
        # аэропорта и растёт в точности с каждой новой строкой статистики.
        model["F"] = _fit_effects(rt, yt, pt)
    model["P"]["n"] = len(rp)
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[key] = model
    return model


def estimate(store, a_icao: str, b_icao: str, dist_km: float, as_of=None):
    """(пасс./мес в обе стороны, подпись) или (None, причина)."""
    pax, note, _ = estimate_detail(store, a_icao, b_icao, dist_km, as_of)
    return pax, note


def estimate_detail(store, a_icao: str, b_icao: str, dist_km: float, as_of=None):
    """То же и шаги расчёта (решение 218): каждое слагаемое формулы числом —
    витрина показывает их по нажатию, чтобы оценку можно было проверить
    руками, а не принять на веру."""
    from datetime import date

    from .fare_model import REGION_RU, _coords
    from .traffic import CITY_GROUPS
    as_of = str(as_of or date.today())
    m = fit(store, as_of)
    if not m.get("P"):
        n = m.get("n", 0)
        return None, (f"модели потока нет: пар с опубликованным потоком {n}, нужно {MIN_PAIRS}"
                      if m else "модели потока нет: в хранилище нет городов (fca refresh "
                      "--only geonames_cities) или опубликованного потока"), {}
    xy = _coords(store)
    a, b = _node(a_icao), _node(b_icao)
    pa_, pb_ = _node_xy(xy, a), _node_xy(xy, b)
    if not pa_ or not pb_ or not dist_km or a == b:
        return None, "модели потока нет: аэропорт без координат", {}
    region = _node_region
    _, thr = _flows(store, as_of)
    c0 = m["c0"]
    r1 = lambda x: f"{x:.1f}".replace(".", ",")                     # noqa: E731
    xs, parts, known, ends = [], [], 0, []
    for k, q in ((a, pa_), (b, pb_)):
        T = thr.get(k, 0.0)
        name = (f"{k[1:]} (весь город: {', '.join(CITY_GROUPS[k])})" if k in CITY_GROUPS else k)
        if T >= MIN_THR:
            xs.append(math.log(T))
            amt = f"{r1(T / 1e6)} млн" if T >= 1e6 else f"{T / 1e3:.0f} тыс."
            parts.append(f"{name} — {amt} пасс./мес по статистике")
            known += 1
            ends.append({"code": name, "mass": T, "how": "stat"})
        else:
            pop = catchment(store, *q)
            xs.append(math.log(pop) + c0.get(region(k), c0["all"]))
            parts.append(f"{name} — по жителям ({r1(pop / 1e6)} млн в 150 км)")
            ends.append({"code": name, "mass": math.exp(xs[-1]), "how": "pop", "pop": pop,
                         "ratio": math.exp(c0.get(region(k), c0["all"]))})
    use = "T" if (known == 2 and m.get("T")) else "P"
    if known == 1 and m.get("T"):
        use = "T"                         # одна масса — статистика, вторая — переведённые жители
    mm = m[use]
    F = m.get("F") or {}
    nb = F.get("nb", {})
    eff = (use == "T" and known == 2 and F.get("factor_cv")
           and nb.get(a, 0) >= MIN_AP_PAIRS and nb.get(b, 0) >= MIN_AP_PAIRS)
    ra, rb = region(a), region(b)
    g = ra if ra == rb else ("russia" if {ra, rb} <= {"russia", "cis"} else "inter")
    row = _xrow(xs[0], xs[1], max(dist_km, 100.0), g, m["shifts"], m.get("slopes", ()))
    lp = float(np.dot(row, mm["coef"]))
    co = mm["coef"]
    ns = len(m["shifts"])
    shift = sum(co[4 + i] for i, s in enumerate(m["shifts"]) if s == g)
    alpha = co[1] + sum(co[4 + ns + i] for i, s in enumerate(m.get("slopes", ())) if s == g)
    ld = math.log(max(dist_km, 100.0) / 1000.0)
    steps = {"model": use, "region": REGION_RU.get(g, g), "c": co[0], "shift": shift,
             "alpha": alpha, "b1": co[2], "b2": co[3], "km": dist_km, "ld": ld,
             "ends": ends, "mass_term": alpha * (xs[0] + xs[1]),
             "dist_term": co[2] * ld + co[3] * ld * ld, "mu": None}
    err = mm["factor_cv"] if known == 2 else m["P"]["factor_cv"]
    if eff:
        lp += F["mu"][a] + F["mu"][b]
        err = F["factor_cv"]
        steps["mu"] = {"a": F["mu"][a], "b": F["mu"][b], "na": nb[a], "nb": nb[b]}
        parts.append(f"с поправкой на сами аэропорты по их {nb[a]} и {nb[b]} парам")
    pax = math.exp(lp)
    steps.update(ln=lp, pax=pax, err=err, n=mm["n"])
    used = g if (g in m["shifts"] or g == m["base"]) else "все регионы"
    note = (f"модель: {'; '.join(parts)}; {f'{dist_km:,.0f}'.replace(',', ' ')} км; "
            f"подогнана по {mm['n']} парам с опубликованным потоком "
            f"({REGION_RU.get(used, used)}), на отложенных парах ошибается обычно в "
            f"{r1(err)} раза; не знает туризма и поездов")
    if a in CITY_GROUPS or b in CITY_GROUPS:
        note += "; поток всего города, как в сводке, а не одного аэропорта"
    if dist_km < SHORT_KM:
        note += "; пара короткая — часть потока, вероятно, уходит на поезд и автобус"
    return pax, note, steps
