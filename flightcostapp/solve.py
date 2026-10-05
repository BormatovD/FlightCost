"""Обращение расчёта: задать результат и найти параметр.

Прямой расчёт отвечает на вопрос эксплуатанта: «сколько стоит этот рейс».
Но у продукта три роли, и две другие спрашивают наоборот.

    лизингодатель — при какой ставке эта линия сходится
    производитель — какую стоимость обслуживания можно закладывать
    эксплуатант   — какая загрузка нужна на этом типе

Это один и тот же расчёт, решаемый относительно разного. Механика уже
была: безубыточный тариф и безубыточная загрузка считаются именно так,
только аналитически. Здесь то же самое, но численно и для любого
параметра — потому что аналитически выразить, скажем, ставку лизинга
через прибыль мешает ступенчатая структура сборов.

Метод простой намеренно: расширение интервала до смены знака, затем
деление пополам. Целевая функция не гладкая — минимальные сборы,
полосы по массе и ступени стоянки дают изломы, — поэтому производные
брать нельзя, а деление пополам к изломам равнодушно.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .econ import route_economics
from .overrides import canonical

# Параметры, задаваемые не через слой сценария, а прямыми аргументами.
# Цена топлива здесь же: `route_economics` принимает её ключом
# `fuel_eur_per_kg`, а в хранилище она не лежит одним фактом — собирается
# из котировки, плотности и курса. Обращать по котировке значило бы
# искать порог в долларах за галлон при ответе в евро за килограмм.
DIRECT = {"lf": "load_factor", "fare": "fare_eur", "freq": "freq_week",
          "fuel": "fuel_eur_per_kg"}


@dataclass
class Solution:
    param: str
    value: float | None
    baseline: float | None
    target: str
    iterations: int = 0
    bracket: tuple | None = None
    note: str = ""
    curve: list = field(default_factory=list)   # (значение, прибыль за рейс)
    status: str = "ok"                          # ok | unreachable | failed

    @property
    def ok(self) -> bool:
        return self.value is not None


def _profit(res, fare: float | None) -> float:
    """Прибыль рейса при заданном тарифе. Ноль — точка безубыточности.

    Та же формула, что печатает `Result.report()`. Это не педантизм: если
    разбор показывает убыток 7 506 EUR, а строка запаса считает недобор от
    другой величины, обе цифры по отдельности верны, и расхождение
    невозможно объяснить.
    """
    if fare is None:
        raise ValueError("для обращения расчёта нужен тариф: --fare")
    return (fare - res.breakeven_fare_eur) * res.inputs["pax"]


def _runner(store, origin: str, destination: str, kw: dict, param: str):
    """Прогон расчёта при заданном значении одного параметра.

    Прямые аргументы и слой сценария подставляются по-разному, но снаружи
    это одна и та же функция от одного числа.
    """
    key = canonical(param) if param not in DIRECT else param

    def run(x: float):
        k = dict(kw)
        if param in DIRECT:
            k[DIRECT[param]] = x
        else:
            k["overrides"] = {**(k.get("overrides") or {}), key: x}
        return route_economics(store, origin, destination, **k)

    return run, key


def _bisect(f, a: float, fa: float, b: float, fb: float,
            tol: float = 1e-3, max_iter: int = 80) -> tuple[float, int, tuple]:
    """Деление пополам на интервале с заведомой сменой знака.

    Изломы от минимальных сборов и ступеней стоянки делают производные
    непригодными, а делению пополам они безразличны.
    """
    it = 0
    while it < max_iter and (b - a) > tol * max(1.0, abs(a)):
        m = 0.5 * (a + b)
        fm = f(m)
        if (fa <= 0) == (fm <= 0):
            a, fa = m, fm
        else:
            b, fb = m, fm
        it += 1
    return 0.5 * (a + b), it, (a, b)


def solve(store, origin: str, destination: str, *, param: str,
          target: str = "breakeven", base_kwargs: dict | None = None,
          lo: float | None = None, hi: float | None = None,
          tol: float = 1e-3, max_iter: int = 80,
          curve: bool = True) -> Solution:
    """Значение параметра, при котором достигается цель.

    `target` — пока только `breakeven`: прибыль рейса равна нулю. Другие
    цели (заданная маржа, заданный доход) добавляются той же функцией,
    меняется лишь то, что приравнивается к нулю.
    """
    kw = dict(base_kwargs or {})
    run, key = _runner(store, origin, destination, kw, param)

    # Опорное значение: то, что модель берёт сейчас.
    base_res = route_economics(store, origin, destination, **kw)
    baseline = _baseline_of(base_res, param, key, kw)

    f = lambda x: _profit(run(x), kw.get("fare_eur") if param != "fare" else x)

    if lo is not None and hi is not None:
        # Заданный интервал раньше делился пополам без проверки, есть ли
        # внутри вообще смена знака. Если её нет, деление сходится к концу
        # интервала и возвращает число, которое выглядит как порог, но им
        # не является. Решение 37: механизм, который может ничего не
        # найти, обязан об этом сказать.
        a, b = lo, hi
        fa, fb = f(a), f(b)
        if (fa <= 0) == (fb <= 0):
            return Solution(param, None, baseline, target, bracket=(a, b),
                            status="unreachable",
                            note="в заданной области знак прибыли не меняется")
    else:
        start = baseline if baseline not in (None, 0) else 1.0
        a, b = _bracket(f, start)
        if a is None:
            return Solution(param, None, baseline, target, status="unreachable",
                            note="не удалось охватить точку безубыточности: "
                                 "при любом значении параметра знак прибыли "
                                 "не меняется")
        fa, fb = f(a), f(b)

    x, it, bracket = _bisect(f, a, fa, b, fb, tol=tol, max_iter=max_iter)

    # Небольшая окрестность вокруг ответа: лизингодателю важен не только
    # порог, но и то, насколько круто линия его проходит.
    pts = []
    if curve:
        for k in (0.8, 0.9, 1.0, 1.1, 1.2):
            v = x * k
            try:
                pts.append((v, _profit(run(v),
                                       kw.get("fare_eur") if param != "fare" else v)))
            except Exception:                          # noqa: BLE001
                pass

    return Solution(param, x, baseline, target, iterations=it,
                    bracket=bracket, curve=pts)


def _split_note(store, origin, destination, base_kwargs, param) -> str:
    """Справочная раскладка полной ставки на составляющие.

    Полная ставка — то, с чем сравнивают; раскладка — то, что объясняет,
    почему она меняется с плечом. Нужны обе, но в разном весе.
    """
    if not param.endswith(("maint_eur_per_fh", "crew_eur_per_fh")):
        return ""
    res = route_economics(store, origin, destination, **base_kwargs)
    want = "Ставка ТОиР" if "maint" in param else "Ставка экипажа"
    for st in res.trace:
        if st.label.startswith(want):
            # Скобки не убирать: без них «495 · 1.77 + 729 / 1.77» читается
            # как 495·1.77 + (729/1.77), то есть математически неверно.
            return st.subst
    return ""


def _effective_edge(store, origin, destination, base_kwargs, param, x):
    """Полная ставка при пороговом значении составляющей."""
    from .overrides import canonical
    kw = dict(base_kwargs)
    kw["overrides"] = {**(kw.get("overrides") or {}), canonical(param): x}
    res = route_economics(store, origin, destination, **kw)
    want = "Ставка ТОиР" if "maint" in param else "Ставка экипажа"
    for st in res.trace:
        if st.label.startswith(want):
            return st.value
    return None


def _baseline_of(res, param: str, key: str, kw: dict):
    """Текущее значение параметра — то, от чего пляшет поиск."""
    if param in DIRECT:
        v = kw.get(DIRECT[param])
        if v is not None or param != "fuel":
            return v
        # Цена топлива не задана — значит модель взяла её сама, и опорное
        # значение стоит в трассировке: из справочника или заглушка. Без
        # этого порог по топливу отсчитывался бы от «ничего».
        for step in res.trace:
            if step.label.startswith("Цена топлива"):
                return step.value
        return None
    for step in res.trace:
        if step.label.startswith("Ставка лизинга") and "lease" in key:
            return step.value
        if step.label.startswith("Налёт") and "monthly_hours" in key:
            return step.value
        if step.label.startswith("Ставка ТОиР") and "maint_eur_per_fh" in key:
            return step.value
        if step.label.startswith("Ставка экипажа") and "crew_eur_per_fh" in key:
            return step.value
    return None


def _bracket(f, start: float, grow: float = 1.6, steps: int = 40):
    """Расширение интервала до смены знака прибыли.

    Направление заранее неизвестно: рост ставки лизинга прибыль снижает,
    а рост налёта — повышает. Поэтому раздвигаем в обе стороны сразу.
    """
    try:
        f0 = f(start)
    except Exception:                                  # noqa: BLE001
        return None, None
    lo = hi = start
    flo = fhi = f0
    for _ in range(steps):
        hi *= grow
        try:
            fhi = f(hi)
        except Exception:                              # noqa: BLE001
            break
        if (f0 <= 0) != (fhi <= 0):
            return (start, hi) if start < hi else (hi, start)
    for _ in range(steps):
        lo /= grow
        if lo < 1e-9:
            break
        try:
            flo = f(lo)
        except Exception:                              # noqa: BLE001
            break
        if (f0 <= 0) != (flo <= 0):
            return (lo, start) if lo < start else (start, lo)
    return None, None


# Параметры, по которым считается запас прочности в разборе. Отобраны не
# по важности статьи, а по тому, что пользователь реально может менять:
# спорить со ставкой лизинга осмысленно, со ставкой аэронавигации нет.
MARGIN_PARAMS = [
    ("lf", "Загрузка", "доля",
     "доля занятых кресел на вылете"),
    ("fare", "Средний чек", "EUR",
     "доход с одного вылетающего пассажира до вычета комиссии"),
    ("fleet_economics.{ac}.lease_eur_month", "Ставка лизинга", "EUR/мес",
     "месячный платёж за борт"),
    ("fleet_economics.{ac}.monthly_hours", "Налёт борта", "ч/мес",
     "часов в месяц на одну машину, по всем её маршрутам"),
    ("fleet_economics.{ac}.maint_eur_per_fh", "ТОиР, полная ставка", "EUR/ч",
     "стоимость обслуживания на блок-час при этом плече"),
    ("fleet_economics.{ac}.crew_eur_per_fh", "Экипаж, полная ставка", "EUR/ч",
     "лётный и кабинный экипаж на блок-час"),
    ("fuel", "Цена топлива", "EUR/кг",
     "цена в крыло за килограмм; сейчас спот без дифференциала и заправки"),
]

# ---------------------------------------------------------------------
# Допустимая область параметра.
#
# Порог за границей области — не ответ, а его отсутствие: загрузка 1.327
# означает 226 кресел из 170. Порог за другой границей вообще не
# возвращался, и вместе с ним пропадало самое сильное утверждение из
# возможных: даже при нулевой ставке ТОиР рейс не выходит в ноль.
#
# Границы берутся только настоящие. Где настоящей нет, стоит предел
# области поиска с пометкой `search_range` — правдоподобный потолок,
# выведенный из общих соображений, это выдуманная константа, и её место
# не здесь.
# ---------------------------------------------------------------------

SEARCH_SPAN = 10.0          # во сколько раз от текущего раздвигается предел
                            # поиска там, где настоящей границы нет
CALENDAR_HOURS_MONTH = 24 * 30.44   # часов в месяце: это календарь, а не
                                    # отраслевое допущение о налёте

LIMIT_ABOUT = {
    "physical": "физический предел величины",
    "seats": "все кресла заняты",
    "payload_range": "больше не поднимет на это плечо",
    "calendar": "столько часов в месяце",
    "search_range": "предел области поиска: настоящей границы у параметра нет",
}


def _payload_cap(store, origin, destination, kw: dict, seats: float) -> float:
    """Наибольшая выполнимая загрузка по нагрузке и дальности, в долях.

    Считается неподвижной точкой: каждый лишний пассажир добавляет массу,
    масса добавляет топливо, топливо съедает оставшуюся коммерческую
    загрузку. Без итерации предел оказался бы завышен.

    Нужно это затем, что на длинном плече настоящая граница ниже единицы,
    и прибыль на границе, посчитанная при полной загрузке, была бы взята
    в точке, где рейс не выполним. Строка получилась бы правдоподобной и
    неверной — худший исход из возможных.
    """
    if not seats:
        return 1.0
    lf = 1.0
    for _ in range(4):
        res = route_economics(store, origin, destination,
                              **{**kw, "load_factor": lf, "_trade": False})
        cap = min(1.0, res.max_pax / seats)
        if cap >= 1.0:
            return 1.0
        if abs(cap - lf) < 1e-3:
            return cap
        lf = cap
    return lf


def _bounds(param: str, baseline: float, base_res, store, origin, destination,
            kw: dict) -> dict:
    """Границы области и то, чем каждая из них задана.

    `better` — конец, в сторону которого прибыль растёт. Именно на нём
    считается недобор: «даже при самом выгодном допустимом значении».
    """
    seats = base_res.inputs.get("seats") or 0.0
    span = max(SEARCH_SPAN * abs(baseline), abs(baseline) + 1.0)

    if param == "lf":
        cap = _payload_cap(store, origin, destination, kw, seats)
        return {
            # Ноль кресел даёт нулевую выручку и деление на ноль в
            # безубыточном тарифе; настоящий минимум — один пассажир.
            "lo": 1.0 / seats if seats else 0.0, "lo_reason": "physical",
            "hi": cap,
            "hi_reason": "seats" if cap >= 1.0 else "payload_range",
            "better": "hi",
        }
    if param == "fare":
        return {"lo": 0.0, "lo_reason": "physical",
                "hi": span, "hi_reason": "search_range", "better": "hi"}
    if param.endswith("monthly_hours"):
        return {"lo": max(base_res.block_h, 1.0), "lo_reason": "physical",
                "hi": CALENDAR_HOURS_MONTH, "hi_reason": "calendar",
                "better": "hi"}
    # Остальные — затратные ставки: отрицательными не бывают, и чем
    # меньше, тем лучше.
    return {"lo": 0.0, "lo_reason": "physical",
            "hi": span, "hi_reason": "search_range", "better": "lo"}


def _scan(f, xs: list[float]) -> list[tuple]:
    """Значения прибыли в точках области. None там, где расчёт упал."""
    out = []
    for x in xs:
        try:
            out.append((x, f(x)))
        except Exception:                              # noqa: BLE001
            out.append((x, None))
    return out


# Допущения пересчёта лизинга в стоимость борта. Три числа, на которых
# висит вся прикидка, и до сих пор они были константами в коде — то есть
# ровно тем, против чего написаны решения 12 и 24. Первый же, кто сверил
# нашу цифру со своим Excel, получил другую и не смог узнать почему.
#
# Теперь это ИМЕНОВАННЫЕ ДОПУЩЕНИЯ: они печатаются рядом с ответом и
# переопределяются слоем сценария.
#
#   --set lease_terms.months=120
#   --set lease_terms.annual_rate=0.09
#   --set lease_terms.balloon_share=0.25
#   --set lease_terms.in_advance=0        # платёж в конце периода
LEASE_TERMS = {
    "months": 144,            # 12 лет
    "annual_rate": 0.075,
    "balloon_share": 0.40,    # остаточный платёж долей от стоимости
    # Лизинг воздушного судна платится АВАНСОМ, в начале периода. В Excel
    # это `тип = 1` у ПЛТ, и по умолчанию там стоит 0 — расхождение около
    # 0,6%, мелкое, но необъяснённое расхождение хуже крупного объяснённого.
    "in_advance": 1,
}


def implied_aircraft_value(monthly: float, terms: dict | None = None) -> dict:
    """Стоимость борта, при которой такой месячный платёж осмыслен.

    Возвращает НЕ число, а разбор: значение, формулу, подстановку и
    допущения. Пользователь проверит эту цифру в Excel — это не гипотеза,
    это уже случилось, — и разойтись он может четырьмя способами:

      1. посчитал ПС без будущей стоимости, то есть БЕЗ остаточного
         платежа. Тогда его число примерно на 20% меньше нашего;
      2. взял остаток долей от платежа, а не дисконтированной долей
         стоимости. Тогда его число примерно на 40% больше;
      3. оставил `тип = 0`, то есть платёж в конце периода. Расхождение
         около 0,6%;
      4. взял другой срок, ставку или остаток — и тогда расходиться и
         должно, а увидеть это можно только если наши допущения названы.

    Формула. Стоимость P складывается из приведённого потока платежей и
    приведённого остаточного платежа, а остаток выражен долей САМОЙ P:

        P = M · a(n,i) · (1+i)^adv  +  r · P · (1+i)^-n

    откуда

        P = M · a(n,i) · (1+i)^adv / (1 - r · (1+i)^-n),
        где a(n,i) = (1 - (1+i)^-n) / i,  i = годовая / 12.

    Это прикидка, а не оценка: настоящая сделка зависит от возраста,
    компоновки, кредитного качества эксплуатанта и рынка. Но порядок
    величины проверить полезно — он сразу показывает бессмысленную ставку.
    """
    t = {**LEASE_TERMS, **(terms or {})}
    n = int(t["months"])
    i = float(t["annual_rate"]) / 12.0
    r = float(t["balloon_share"])
    adv = 1 if t.get("in_advance") else 0
    disc = (1 + i) ** (-n)
    annuity = (1 - disc) / i
    value = monthly * annuity * (1 + i) ** adv / (1 - r * disc)
    return {
        "value": value,
        "formula": "P = M · a(n,i) · (1+i)^adv / (1 − r · (1+i)^−n)",
        "subst": (f"M = {monthly:,.0f} · a = {annuity:.4f} · "
                  f"(1+i)^{adv} / (1 − {r:g} · {disc:.4f})").replace(",", " "),
        "terms": {"срок, мес": n, "годовая ставка": t["annual_rate"],
                  "остаточный платёж, доля": r,
                  "платёж": "авансом" if adv else "в конце периода"},
        # Что получилось бы при других прочтениях: чтобы расхождение с
        # чужим Excel закрывалось на месте, а не перепиской.
        "variants": {
            "без остаточного платежа (ПС без БС)": monthly * annuity,
            "остаток долей без дисконта": monthly * annuity / (1 - r),
            "платёж в конце периода": monthly * annuity / (1 - r * disc),
        },
    }


def margins(store, origin: str, destination: str, base_kwargs: dict,
            aircraft: str) -> list[dict]:
    """Запас прочности: насколько каждый параметр может уйти до нуля.

    Смысл не в самих порогах, а в их сравнении. Параметр с запасом в 3%
    определяет судьбу маршрута, параметр с запасом в 200% можно не
    уточнять вовсе — и это видно только рядом.

    **Запись возвращается всегда.** Раньше параметр без порога молча
    выпадал из списка, и на убыточном маршруте из шести строк оставались
    две. Выпадало при этом самое ценное утверждение из возможных: даже при
    нулевой ставке ТОиР рейс не выходит в ноль, то есть маршрут не чинится
    затратами. Оно вычислялось и терялось.

    Поле `status` различает три вещи, которые нельзя смешивать:

        ok           порог найден внутри допустимой области
        unreachable  порога в допустимой области нет
        failed       расчёт не сошёлся

    `unreachable` — утверждение о маршруте, `failed` — дефект расчёта.
    Слить их значит показать несошедшийся поиск как вывод «даже при нуле
    не сходится»: модель соврёт, и соврёт уверенно.

    При `unreachable` заполнены `limit` (где граница), `limit_reason`
    (чем она задана) и `gap_at_limit` — прибыль рейса на границе. Именно
    последнее делает строку полезной: не «порога нет», а «даже при
    нулевой ставке не хватает 4 900 EUR».

    Каким словом и цветом это показать, решается не здесь. Режим блока —
    запас против дефицита — выводится из знака прибыли и принадлежит
    разбору. Отсюда только факты.

    ВНИМАНИЕ вызывающему: `margin_pct` теперь `None` у всех строк, кроме
    `ok`. Числа там нет, потому что порога нет, а правдоподобное число на
    его месте — ровно тот тихий отказ, против которого написана эта
    правка.
    """
    base_res = route_economics(store, origin, destination, **base_kwargs)
    block_h = base_res.block_h
    seats = base_res.inputs["seats"]
    pax = base_res.inputs["pax"]
    fuel_kg = base_res.fuel_kg

    def hint(param: str, v: float) -> str:
        """Справочный перевод числа в осязаемую величину."""
        # Разряды — пробелом, как везде в разборе и в витрине: «32 062»,
        # а не «32,062» рядом с «1 797».
        return _hint(param, v).replace(",", " ")

    def _hint(param: str, v: float) -> str:
        if param == "fare":
            return f"выручка рейса {v * pax:,.0f} EUR"
        if param == "lf":
            return f"{v * seats:,.0f} из {seats:,.0f} кресел"
        if param.endswith("monthly_hours"):
            return (f"{v / block_h:,.0f} таких рейсов в месяц · "
                    f"{v / 30.0:.1f} ч в сутки")
        if param.endswith("lease_eur_month"):
            # Допущения договора вынесены под таблицу: они одинаковы для
            # всех строк, и повторять их в каждой ячейке значит удвоить
            # высоту строки ради текста, который читают один раз.
            return f"борт ≈ {implied_aircraft_value(v)['value'] / 1e6:,.1f} млн EUR"
        if param.endswith(("maint_eur_per_fh", "crew_eur_per_fh")):
            return f"{v * block_h:,.0f} EUR за рейс"
        if param == "fuel":
            return f"{v * fuel_kg:,.0f} EUR за рейс"
        return ""

    fare = base_kwargs.get("fare_eur")
    if not fare:
        # Без тарифа не существует не отдельного порога, а самого вопроса
        # «сколько до нуля». Это не пропажа параметра, а отсутствие блока.
        return []
    p_base = _profit(base_res, fare)

    def to_full_rate(param: str, x: float, fallback: float) -> float:
        """Порог по составляющей — в те же единицы, что показаны в строке.

        Решается почасовая часть, а в трассировке стоит полная ставка. Без
        пересчёта «сейчас» и «порог» оказались бы из разных величин — худший
        вид расхождения, потому что обе цифры по отдельности верны.

        Отсюда же следует неочевидное: полная ставка при нулевой почасовой
        части не равна нулю. Остаётся цикловая — шасси, ВСУ, ресурсные
        детали, линейное обслуживание, — и это настоящий пол, ниже
        которого ставка не опускается ни при каком решении перевозчика.
        """
        if not param.endswith(("maint_eur_per_fh", "crew_eur_per_fh")):
            return x
        return _effective_edge(store, origin, destination, base_kwargs,
                               param, x) or fallback

    out = []
    for tpl, label, unit, about in MARGIN_PARAMS:
        param = tpl.format(ac=aircraft.upper())
        row = {"label": label, "unit": unit, "param": param, "about": about,
               "now": None, "status": "failed", "edge": None, "margin_pct": None,
               "limit": None, "limit_reason": None, "limit_about": "",
               "gap_at_limit": None, "hint_now": "", "hint_edge": "",
               "hint_limit": "", "split": "", "note": "", "inert": False}
        out.append(row)

        try:
            run, key = _runner(store, origin, destination, base_kwargs, param)
            f = (lambda x: _profit(run(x), fare)) if param != "fare" \
                else (lambda x: _profit(run(x), x))
            baseline = _baseline_of(base_res, param, key, base_kwargs)
            if baseline is None:
                row["note"] = ("текущее значение параметра не найдено в "
                               "трассировке — порог не от чего отсчитывать")
                continue
            row["now"] = baseline
            row["hint_now"] = hint(param, baseline)
            row["split"] = _split_note(store, origin, destination,
                                       base_kwargs, param)

            b = _bounds(param, baseline, base_res, store, origin, destination,
                        base_kwargs)
            # В какую сторону от текущего значения лежит ноль. На убыточном
            # маршруте — в выгодную: параметр надо улучшать, пока хватит.
            # На прибыльном — в невыгодную: вопрос в том, сколько можно
            # потерять. Одно и то же поле, направление противоположное.
            side = b["better"] if p_base <= 0 else \
                ("lo" if b["better"] == "hi" else "hi")
            x_lim, reason = b[side], b[side + "_reason"]
            lo, hi = (baseline, x_lim) if baseline <= x_lim else (x_lim, baseline)
            if hi - lo <= 1e-12:
                row.update(status="unreachable", limit=x_lim,
                           limit_reason=reason, limit_about=LIMIT_ABOUT[reason],
                           gap_at_limit=p_base,
                           note="параметр уже стоит на границе допустимого")
                continue

            # Сетка между текущим значением и границей. Одних концов мало:
            # по загрузке прибыль не обязана быть монотонной — пассажир
            # добавляет не только выручку, но и массу, топливо и
            # пассажирский сбор, — и корень может лежать между концами при
            # одинаковом знаке на них.
            xs = [lo] + [lo + (hi - lo) * i / 4.0 for i in (1, 2, 3)] + [hi]
            pts = _scan(f, sorted(set(xs)))

            root = None
            for (xa, fa), (xb, fb) in zip(pts, pts[1:]):
                if fa is None or fb is None or (fa <= 0) == (fb <= 0):
                    continue
                root = _bisect(f, xa, fa, xb, fb)[0]
                break

            if root is not None:
                edge = to_full_rate(param, root, root)
                row.update(
                    status="ok", edge=edge,
                    margin_pct=(edge - baseline) / abs(baseline) * 100.0,
                    hint_edge=hint(param, edge))
                continue

            # Корня нет. Смотрим значение на границе: если и там знак тот
            # же — это утверждение о маршруте, а не сбой поиска.
            gap = next((v for x, v in pts if x == x_lim), None)
            if gap is None:
                row["note"] = "расчёт на границе области не сошёлся"
                continue
            if (gap <= 0) != (p_base <= 0):
                # Знак на границе противоположен текущему, а смены знака
                # сетка не нашла. Это дефект поиска, и мешать его с
                # содержательным «даже на границе не хватает» нельзя:
                # иначе несошедшийся солвер будет показан как вывод о
                # маршруте, то есть модель соврёт уверенно.
                row["note"] = ("знак прибыли на границе противоположен "
                               "текущему, но смена знака не найдена")
                continue

            row.update(
                status="unreachable",
                limit=to_full_rate(param, x_lim, x_lim),
                limit_reason=reason, limit_about=LIMIT_ABOUT[reason],
                gap_at_limit=gap,
                hint_limit=hint(param, to_full_rate(param, x_lim, x_lim)))
            if abs(gap - p_base) < 1e-6:
                # Параметр не входит в расчёт вовсе — например, лизинг в
                # режиме «борт уже оплачен». Решение 40: заданное, но не
                # использованное значение обязано себя назвать.
                row["inert"] = True
                row["note"] = "параметр не влияет на результат при этих условиях"
        except Exception as e:                         # noqa: BLE001
            row["note"] = f"{type(e).__name__}: {e}"

    # Порядок: сперва то, где порог есть — по тесноте запаса. Затем
    # недостижимое — по величине недобора на границе, то есть самый
    # дешёвый путь к нулю первым. Сбои в конце: их разбирают, а не читают.
    rank = {"ok": 0, "unreachable": 1, "failed": 2}
    return sorted(out, key=lambda r: (
        rank[r["status"]],
        abs(r["margin_pct"]) if r["margin_pct"] is not None
        else abs(r["gap_at_limit"]) if r["gap_at_limit"] is not None else 0.0))
