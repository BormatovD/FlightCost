"""Расход топлива по фазам полёта.

Почему не плоская ставка кг/ч. Набор высоты стоит примерно вдвое дороже
крейсера в пересчёте на час, а его длительность от дистанции почти не
зависит. На коротком плече набор занимает треть топлива, на длинном —
десятую часть. Плоская ставка, откалиброванная на 600 nm, ошибается на
четверть на 300 nm и на десятую часть на 2000 nm — в разные стороны.

Почему масса считается итеративно. Топливо зависит от взлётной массы,
взлётная масса зависит от количества топлива. Уравнение неявное,
решается парой итераций неподвижной точки: сходится за три-четыре шага
с точностью до килограммов.

Профиль сознательно грубый: постоянные скороподъёмность и скорость на
участках вместо интегрирования настоящей траектории. Точность этого
достаточна, потому что основная неопределённость модели давно не здесь,
а в ставках сборов и наземном обслуживании.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .cycles import Split, fit as fit_split
from pathlib import Path

# Параметры профиля. Вынесены сюда, чтобы их было видно и можно было
# оспорить, а не искать по коду.
CLIMB_VS_FPM = 2000.0        # средняя скороподъёмность
CLIMB_TAS_KT = 300.0
DESCENT_VS_FPM = 1500.0
DESCENT_TAS_KT = 280.0
# Руление по стандартному циклу ИКАО (LTO): 19 минут на выруливание и
# 7 на заруливание. Наши прежние 12 были взяты на глаз и вдвое коротки
# для загруженных европейских аэропортов.
TAXI_MIN = 26.0
TAXI_KG_PER_H = 600.0
PAX_MASS_KG = 100.0          # запасное значение, если справочник недоступен

# Поправка к ортодромии по методике углеродного калькулятора ИКАО.
# Прибавляется, а не умножается: обход по структуре воздушного
# пространства, ожидание в зоне и выход на схему — накрутка примерно
# постоянная, а не пропорциональная. Поэтому на плече в 250 миль она
# даёт десять процентов, а на четырёх тысячах — полтора.
#
# Полосы в километрах, как в исходной методике.
ICAO_DC_KM = [(550.0, 50.0), (5500.0, 100.0), (float("inf"), 125.0)]

# Калибровочного множителя расхода здесь БОЛЬШЕ НЕТ, и это решение, а не
# упущение.
#
# Он существовал три захода со значением 1.0 и выведенным, но не
# применённым 1.12. Второй точки не появилось: калибровка по отчётам
# перевозчиков упирается в границу учёта, а не в нашу арифметику. Число,
# лежащее готовым к включению, — соблазн, хранимый в коде: по одной точке
# выводится уровень, но не структура (решение 48), а через полгода
# останется только уровень и уверенность, что он проверен.
#
# Само измерение никуда не делось и не перестало быть верным: 1.12 по
# Ryanair FY25 после поправки ИКАО и стандартного руления записано в карте,
# раздел M7, вместе со способом получения. Если вторая точка появится,
# восстановить множитель — три строки; восстановить измерение из воздуха
# нельзя, поэтому в карте лежит оно, а не он.


def icao_distance_nm(gcd_nm: float) -> tuple[float, str]:
    """Расчётная дальность с поправкой ИКАО и пояснение."""
    km = gcd_nm * 1.852
    dc = next(v for lim, v in ICAO_DC_KM if km < lim)
    return (km + dc) / 1.852, f"ортодромия {km:,.0f} км + поправка ИКАО {dc:.0f} км"


# ---------------------------------------------------------------------
# Запас топлива.
#
# Был двумя константами: 5% от рейсового плюс 1 200 кг «на запасной и
# ожидание». Пять процентов на месте — это непредвиденный расход. Тысяча
# двести килограммов покрывали примерно только получасовое ожидание для
# A320, а ухода на запасной в модели не было вовсе.
#
# Цена ошибки не в топливе, а в выполнимости: заниженный запас завышает
# предельную коммерческую нагрузку примерно на тонну, то есть на десяток
# пассажиров. Модель не занижала возможности, а завышала — решение 45 с
# обратной стороны. На E195 та же константа была завышена вдвое, на
# широкофюзеляжных занижена кратно.
#
# ЗАПАС НЕ СЖИГАЕТСЯ и в стоимость топлива не входит. Он возится и
# возвращается; лишний расход от его перевозки уже сидит в рейсовом
# топливе через взлётную массу. Складывать запас с рейсовым в статью
# затрат — двойной счёт. Здесь модель права, и это написано затем, чтобы
# следующий читатель не «исправил».
# ---------------------------------------------------------------------

# Умолчания. Первые два — регуляторные и следуют из правил, а не из типа:
# непредвиденный расход 5% от рейсового, конечный остаток на 30 минут
# ожидания. Провенанс у них `default` до заведения домена `fuel_reserve`.
CONTINGENCY_FRAC = 0.05
FINAL_RESERVE_MIN = 30.0
HOLDING_TAS_KT = 220.0       # скорость ожидания
HOLDING_ALT_FT = 1500.0      # высота ожидания


@dataclass
class ReserveSpec:
    """Из чего складывается запас. Три слагаемых, три природы.

    `contingency_frac` и `final_reserve_min` следуют из правил и от рейса
    не зависят — это данные (решение 78).

    `alternate_nm` следует из операции дня: у каждого аэропорта свой
    запасной, и выбирает его рейс, а не тип. Значит вход, а не
    справочник. `None` означает, что запасной не назван, и это отдельное
    состояние: не «ухода нет», а «не задан».
    """

    contingency_frac: float = CONTINGENCY_FRAC
    final_reserve_min: float = FINAL_RESERVE_MIN
    alternate_nm: float | None = None
    provenance: str = "default"


@dataclass
class Feasibility:
    """Выполним ли рейс физически.

    Модель обязана отвечать «нельзя», а не выдавать число. До этой
    проверки расчёт FRA-SIN на A320 давал уверенную себестоимость при
    перегрузе в пятнадцать тонн и топливе, которое в баки не влезает
    на одиннадцать: `min(масса, MTOW)` усекал молча.
    """

    ok: bool = True
    # Предел, в который упёрлись: машинный ключ, проза и запас. Раньше
    # причина существовала только прозой, и в разборе не было видно, во
    # что именно упёрлись — в MTOW, в ёмкость баков или в полосу. Решение
    # 45 требует, чтобы «нельзя» было ОТВЕТОМ модели; ответ, который
    # нельзя прочитать машинно, к оси состояний не привязывается.
    limits: list = field(default_factory=list)
    max_payload_t: float = 0.0     # сколько груза поднимет на это плечо
    max_pax: int = 0
    overload_t: float = 0.0
    fuel_over_t: float = 0.0

    @property
    def reasons(self) -> list:
        """Прозаический вид пределов. Считается, а не хранится: два
        представления одного и того же расходятся молча."""
        return [l["text"] for l in self.limits]

    def limit(self, key: str, text: str, **margin) -> None:
        self.ok = False
        self.limits.append({"key": key, "text": text, **margin})


@dataclass
class FuelResult:
    trip_kg: float
    block_h: float
    airborne_h: float
    takeoff_mass_kg: float
    phases: dict = field(default_factory=dict)      # кг по фазам
    times: dict = field(default_factory=dict)       # ч по фазам
    method: str = "openap"
    note: str = ""
    feasible: Feasibility = field(default_factory=Feasibility)
    # Запас и его разложение. Возится, не сжигается: в стоимость топлива
    # не входит, во взлётную массу входит.
    reserve_kg: float = 0.0
    reserve_parts: dict = field(default_factory=dict)
    # Каким ярусом получен расход и на чём этот ярус стоит. Молчаливая
    # подмена запрещена, объявленная — нет; вся разница между ними в том,
    # видит ли пользователь, что произошло (решение 94).
    tier: int = 1
    tier_note: str = ""

    @property
    def kg_per_h(self) -> float:
        return self.trip_kg / self.block_h if self.block_h else 0.0


@lru_cache(maxsize=1)
def _pax_mass_table() -> dict:
    try:
        import yaml
        path = Path(__file__).resolve().parents[1] / "data" / "fleet" / "reference.yaml"
        with open(path, encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("pax_mass", {}) or {}
    except Exception:                                  # noqa: BLE001
        return {}


def pax_mass(icao: str, mtow_t: float | None = None,
             store=None, as_of=None) -> tuple[float, str]:
    """Масса пассажира с багажом и откуда она взята.

    На регионалах норма провоза жёстче, на дальних плечах багажа больше.
    Разница в десять килограммов при полутора сотнях кресел — полторы
    тонны полезной нагрузки, то есть сотни миль дальности.
    """
    if store is not None:
        v = store.latest_any("pax_mass", icao.upper())
        if v:
            return float(v), f"справочник, тип {icao.upper()}"
        if mtow_t:
            bands = sorted(
                ((float(k.split("/")[1]), k) for k in
                 store.current("pax_mass", as_of) if k.startswith("class/")),
                key=lambda x: x[0])
            for lim, key in bands:
                if mtow_t <= lim:
                    row = store.get("pax_mass", key, as_of)
                    return float(row["value"]), f"класс: {row['note'] or ''}"
    # Запасной путь: файл, если хранилище недоступно (например, в расчёте
    # диаграммы вне контекста маршрута).
    t = _pax_mass_table()
    v = (t.get("by_type") or {}).get(icao.upper())
    if v:
        return float(v), f"файл, тип {icao.upper()}"
    if mtow_t:
        for row in t.get("by_class") or []:
            if mtow_t <= row["max_mtow_t"]:
                return float(row["kg"]), f"файл, класс: {row.get('note', '')}"
    return PAX_MASS_KG, "запасное значение"


# Доля цикловой части расхода у узкофюзеляжного борта на типичном плече.
# Набор высоты и цикл ВПП не зависят от длины плеча вовсе; на двухчасовом
# рейсе это примерно четверть блок-топлива. Нужна ТОЛЬКО для случая одной
# точки: она задаёт уровень и не задаёт структуру.
BURN_CYCLE_SHARE = 0.25
BURN_REF_BLOCK_H = 2.0


def fit_burn(points, source: str = "точки эксплуатанта") -> Split:
    """Расход по точкам «плечо в блок-часах → блок-топливо, кг».

    Второй ярус — основной путь, а не запасной. Там, где публичных данных
    хуже всего — старые и незападные типы, — у эксплуатанта данные лучше
    всего: он знает блок-топливо своего борта на своих плечах точно, и
    точнее любой модели.

    Механика та же, что у ТОиР (решение 11), и это буквально тот же код:
    одна точка задаёт уровень, две на разных плечах раскладывают на
    почасовую и поцикловую части однозначно.
    """
    return fit_split(points, prior_cycle_share=BURN_CYCLE_SHARE, source=source)


@dataclass
class BurnRef:
    """Четвёртый ярус: расход от аналога с якорем (решения 94, 105, 106).

    Поляры типа нет — не потому, что её нет в мире, а потому, что BADA и
    FCOM закрыты (решение 105). Берётся вычислитель АНАЛОГА того же
    поколения силовой установки, а планер — свой, из хранилища. Аналог по
    массе и креслам недостаточен: Ту-214 и A321 формально соседи, а по
    расходу разделены поколением двигателя на десятки процентов, которых
    ни масса, ни кресла не покажут. Поэтому аналог называет человек, а не
    выбирает код.

    Якорь — опубликованный крейсерский расход типа, кг/ч, при названной
    массе. Множитель = якорь / расход аналога на нашем планере при той же
    массе, и он применяется ко всем фазам. Без якоря тип отвечает
    «нельзя», а не выдаёт число: расход аналога без привязки — это
    выдуманная константа с чужим именем.
    """

    analog: str
    anchor_kg_per_h: float | None = None
    anchor_mass_kg: float | None = None
    note: str = ""
    # Вариант с тем же двигателем (свой A320 с другими массами и креслами):
    # вычислитель аналога и есть вычислитель этого типа, якорь не нужен.
    # Требование якоря — про ДРУГОЙ тип с тем же поколением двигателя.
    same_engine: bool = False


@dataclass
class Airframe:
    """Справочные величины планера. Приходят из хранилища, не из библиотеки.

    `openap` — вычислитель, а не справочник, и это разделение
    принципиальное. Масса пустого, максимальная взлётная, ёмкость баков,
    эшелон и крейсерское число публикуются и собираются; коэффициенты
    расхода не публикуются, их считает библиотека.

    Пока это не было разделено, тридцать восьмой тип, заведённый ветвью B
    руками, падал на `openap.prop.aircraft` и молча уходил на плоскую
    параметрику: характеристики собраны, а расчёт их не видит. Сбор типов
    до этой правки был бессмыслен.
    """

    icao: str
    oew_kg: float
    mtow_kg: float
    mfc_kg: float = 0.0
    cruise_alt_ft: float = 36000.0
    cruise_tas_kt: float = 450.0
    source: str = "store"


@lru_cache(maxsize=16)
def _known_to_openap(icao: str) -> bool:
    try:
        from openap import prop
        return icao.lower() in {a.lower() for a in prop.available_aircraft()}
    except Exception:                                  # noqa: BLE001
        return False


def _flow(icao: str):
    """Вычислитель расхода. ТОЛЬКО он — справочных величин здесь больше нет.

    Дорого создавать, поэтому кэшируется по типу.
    """
    import openap
    return openap.FuelFlow(icao)


class _Scaled:
    """Вычислитель аналога, умноженный на якорный множитель."""

    def __init__(self, ff, k: float):
        self._ff, self._k = ff, k

    def enroute(self, *a, **kw):
        return self._ff.enroute(*a, **kw) * self._k


@lru_cache(maxsize=16)
def airframe_from_openap(icao: str) -> Airframe:
    """Планер из библиотеки — запасной путь, когда домена не хватает.

    Существует затем, чтобы расчёт не встал, пока ветка B не заполнит
    `aircraft`. Помечает себя источником: два источника для одних чисел
    допустимы ровно до тех пор, пока видно, из какого взято.
    """
    import openap
    from openap import aero
    ac = openap.prop.aircraft(icao)
    crz_ft = ac["cruise"]["height"] / aero.ft
    try:
        mfc = float(ac["limits"]["MFC"])
    except Exception:                                  # noqa: BLE001
        mfc = 0.0
    return Airframe(
        icao=icao.upper(),
        oew_kg=float(ac["limits"]["OEW"]), mtow_kg=float(ac["limits"]["MTOW"]),
        mfc_kg=mfc, cruise_alt_ft=crz_ft,
        cruise_tas_kt=aero.mach2tas(ac["cruise"]["mach"],
                                    crz_ft * aero.ft) / aero.kts,
        source="openap")


def trip_fuel(icao: str, dist_nm: float, pax: float,
              fallback_kg_per_h: float = 2400.0,
              cruise_kt: float = 447.0, apply_icao_dc: bool = True,
              spec: "ReserveSpec | None" = None,
              frame: "Airframe | None" = None,
              burn: "Split | None" = None,
              ref: "BurnRef | None" = None) -> FuelResult:
    """Рейсовое топливо и блок-время. При отсутствии openap — параметрика.

    По умолчанию к ортодромии применяется поправка ИКАО: без неё модель
    занижала блок-время на 16%, что подтвердилось сверкой с Ryanair.
    """
    # Ярус 2 идёт ПЕРЕД физикой, а не после её отказа. Точка эксплуатанта
    # — измерение на его борту; физика — расчёт по обобщённой поляре.
    # Измерение точнее, и порядок обязан это отражать, иначе второй ярус
    # включается только там, где первый сломался, то есть работает как
    # запасной путь при том, что он основной.
    if burn is not None:
        dist_eff, note = (icao_distance_nm(dist_nm) if apply_icao_dc
                          else (dist_nm, ""))
        block = dist_eff / cruise_kt + TAXI_MIN / 60.0
        sp = spec or ReserveSpec()
        trip = burn.at(block)
        f_cont = sp.contingency_frac * trip
        return FuelResult(
            trip_kg=trip, block_h=block, airborne_h=block - TAXI_MIN / 60.0,
            takeoff_mass_kg=0.0, method="empirical", tier=2,
            reserve_kg=f_cont,
            reserve_parts={"Непредвиденный расход": f_cont},
            tier_note=(f"точки эксплуатанта: {burn.per_h:,.0f} кг/ч + "
                       f"{burn.per_cycle:,.0f} кг/цикл, {burn.note}"),
            note=note + ("; структура взята из заготовки, не измерена"
                         if burn.structure == "assumed" else ""))

    note_dc = ""
    if apply_icao_dc:
        dist_nm, note_dc = icao_distance_nm(dist_nm)

    # Ярус 4: своего вычислителя нет, назван аналог. Планер обязан быть
    # из хранилища — иначе считался бы аналог целиком, а не наш тип.
    if ref is not None:
        if frame is None:
            raise ValueError(f"{icao}: для расчёта от аналога нужен планер из "
                             f"хранилища (mtow_t, oew_t, fuel_capacity_t)")
        scale, how = _anchor_scale(ref, frame)
        r = _openap_profile(icao, dist_nm, pax, spec=spec, frame=frame,
                            flow_of=ref.analog, scale=scale)
        r.tier = 4
        r.tier_note = f"аналог {ref.analog}, {how}" + (f"; {ref.note}" if ref.note else "")
        if ref.anchor_kg_per_h is None and not ref.same_engine:
            # Решение 106: без якоря — «нельзя». Числа остаются в ответе,
            # чтобы было видно, что именно не привязано, но рейс невыполним.
            r.feasible.limit(
                "no_anchor",
                f"расход {icao} не привязан: назван аналог {ref.analog}, но нет "
                f"якоря — опубликованного крейсерского расхода кг/ч при названной "
                f"массе. Без якоря тип отвечает «нельзя» (решение 106)")
        if note_dc:
            r.note = note_dc + "; " + r.note
        return r

    try:
        r = _openap_profile(icao, dist_nm, pax, spec=spec, frame=frame)
        if note_dc:
            r.note = note_dc + "; " + r.note
        return r
    except ImportError as exc:
        # Библиотеки нет вовсе — плоская ставка, ОБЪЯВЛЕННАЯ как ярус 0.
        # Прежде откат оставлял `tier=1`, и шаг «Ярус расхода» писал
        # «физика openap» на параметрике (решение 94: подмена допустима
        # только объявленной).
        no_model = f"openap недоступен ({type(exc).__name__})"
        not_ok = None
    except Exception as exc:                        # noqa: BLE001
        if _known_to_openap(icao):
            # Тип библиотеке известен, упала сама физика — это дефект, а не
            # отсутствие модели: параметрика с объявленным ярусом 0.
            no_model = f"openap упал на {icao} ({type(exc).__name__}: {exc})"
            not_ok = None
        else:
            # Библиотека есть, типа в ней нет и аналог не назван. Числа
            # параметрики остаются в ответе, но рейс невыполним: расход
            # неизвестен, а не приблизителен (решение 106).
            no_model = f"типа {icao} нет в openap"
            not_ok = (f"расход {icao} не посчитать: типа нет в openap, аналог с "
                      f"якорем не назван (burn_analog, burn_anchor_kg_per_h)")

    block_h = 0.33 + dist_nm / cruise_kt * 1.06
    # Запас считается и здесь. Ярус хуже, но отсутствие запаса — не
    # «менее точно», а другая ошибка: предельная нагрузка окажется
    # завышенной на весь его вес.
    sp = spec or ReserveSpec()
    trip_p = fallback_kg_per_h * block_h
    f_cont = sp.contingency_frac * trip_p
    f_final = fallback_kg_per_h * 0.6 * sp.final_reserve_min / 60.0
    f_alt = (fallback_kg_per_h * (sp.alternate_nm / cruise_kt * 1.06 + 0.2)
             if sp.alternate_nm else 0.0)
    # Выполнимость считается и здесь, если планер известен: предельная
    # нагрузка выводится из МАСС, а не из физики расхода. Иначе тип,
    # заведённый ветвью B без поддержки openap, доходил бы до выбора
    # яруса формально — с числом расхода и без ответа «нельзя».
    feas = Feasibility()
    m0 = 0.0
    if frame:
        reserve_p = f_cont + f_final + f_alt
        pm_p, _ = pax_mass(icao, frame.mtow_kg / 1000.0)
        m0 = frame.oew_kg + pax * pm_p + trip_p + reserve_p
        feas.max_payload_t = max(
            0.0, (frame.mtow_kg - frame.oew_kg - trip_p - reserve_p) / 1000.0)
        feas.max_pax = int(feas.max_payload_t * 1000 / pm_p)
        if m0 > frame.mtow_kg:
            feas.limit("mtow",
                       f"перегруз {(m0 - frame.mtow_kg)/1000:.1f} т на "
                       f"параметрике расхода: поднимет {feas.max_pax} "
                       f"пассажиров вместо {pax:.0f}",
                       over_t=(m0 - frame.mtow_kg) / 1000.0,
                       limit_t=frame.mtow_kg / 1000.0)
        if frame.mfc_kg and trip_p + reserve_p > frame.mfc_kg:
            feas.limit("fuel_capacity",
                       f"топливо не влезает: нужно "
                       f"{(trip_p + reserve_p)/1000:.1f} т, ёмкость "
                       f"{frame.mfc_kg/1000:.1f} т",
                       over_t=(trip_p + reserve_p - frame.mfc_kg) / 1000.0,
                       limit_t=frame.mfc_kg / 1000.0)
    if not_ok:
        feas.limit("no_model", not_ok)
    return FuelResult(
        trip_kg=trip_p,
        block_h=block_h,
        airborne_h=block_h - TAXI_MIN / 60,
        takeoff_mass_kg=m0,
        feasible=feas,
        reserve_kg=f_cont + f_final + f_alt,
        reserve_parts={"Непредвиденный расход": f_cont,
                       "Конечный остаток": f_final,
                       "Уход на запасной": f_alt},
        method="parametric", tier=0,
        tier_note=f"плоская ставка {fallback_kg_per_h:.0f} кг/ч",
        note=f"{no_model} — плоская ставка "
             f"{fallback_kg_per_h:.0f} кг/ч, ошибка до 25% на коротких плечах",
    )


def _anchor_scale(ref: "BurnRef", frame: "Airframe") -> tuple[float, str]:
    """Множитель к расходу аналога по якорю; 1,0 и пометка, если якоря нет."""
    if ref.anchor_kg_per_h is None:
        if ref.same_engine:
            return 1.0, "вариант с тем же двигателем — множитель 1,0"
        return 1.0, "без якоря — множитель 1,0, рейс невыполним"
    ff = _flow(ref.analog)
    m = ref.anchor_mass_kg or 0.85 * frame.mtow_kg
    model = ff.enroute(mass=m, tas=frame.cruise_tas_kt, alt=frame.cruise_alt_ft) * 3600
    k = ref.anchor_kg_per_h / model if model else 1.0
    return k, (f"якорь {ref.anchor_kg_per_h:,.0f} кг/ч при {m/1000:.1f} т"
               + ("" if ref.anchor_mass_kg else " (масса принята 0,85 MTOW)")
               + f", аналог даёт {model:,.0f} — множитель {k:.3f}")


def _openap_profile(icao: str, dist_nm: float, pax: float,
                    iters: int = 6, tol_kg: float = 5.0,
                    spec: "ReserveSpec | None" = None,
                    with_reserve: bool = True,
                    frame: "Airframe | None" = None,
                    flow_of: str | None = None,
                    scale: float = 1.0) -> FuelResult:
    """Профиль полёта. `with_reserve=False` — для плеча до запасного.

    Плечо до запасного считается тем же механизмом, что основной рейс, а
    не отдельной формулой: вторая реализация той же физики разойдётся с
    первой так же молча, как расходятся два списка допустимого. Своего
    запаса у этого плеча нет — иначе получился бы запас к запасу.

    Масса при этом берётся текущая, а не посадочная на назначении. Уход
    выполняется на выжженном борте и стоит дешевле; считать его на полной
    массе — сознательный запас в сторону осторожности, а не недосмотр.
    """
    spec = spec or ReserveSpec()
    frame = frame or airframe_from_openap(icao)
    # Вычислитель — свой или аналога (`flow_of`), множитель — от якоря.
    # Обёртка, а не умножение в каждой строке: одно место, одна ошибка.
    raw = _flow(flow_of or icao)
    ff = raw if scale == 1.0 else _Scaled(raw, scale)
    oew, mtow, crz_ft = frame.oew_kg, frame.mtow_kg, frame.cruise_alt_ft
    tas_crz = frame.cruise_tas_kt

    pm, _ = pax_mass(icao, mtow / 1000.0)
    payload = pax * pm
    trip = 5.0 * dist_nm                    # затравка порядка величины
    t_taxi = TAXI_MIN / 60.0
    f_taxi = TAXI_KG_PER_H * t_taxi

    # Потолок по дистанции. На коротком плече самолёт до крейсерского
    # эшелона просто не успевает подняться: набор и снижение вместе
    # требуют больше пути, чем есть. Реальный рейс в такой ситуации идёт
    # ниже — ограничиваем эшелон так, чтобы профиль поместился, оставив
    # 10% дистанции на крейсер.
    nm_per_ft = (CLIMB_TAS_KT / CLIMB_VS_FPM + DESCENT_TAS_KT / DESCENT_VS_FPM) / 60.0
    ft_max = dist_nm * 0.90 / nm_per_ft
    crz_used = min(crz_ft, ft_max)
    truncated = crz_used < crz_ft - 1

    t_cl = crz_used / CLIMB_VS_FPM / 60.0
    t_de = crz_used / DESCENT_VS_FPM / 60.0
    d_cl = CLIMB_TAS_KT * t_cl
    d_de = DESCENT_TAS_KT * t_de

    # на пониженном эшелоне истинная скорость меньше
    tas_cr_used = tas_crz * (0.80 + 0.20 * crz_used / crz_ft)

    mfc = frame.mfc_kg

    # Слагаемые запаса, не зависящие от рейсового топлива, считаются один
    # раз до итерации.
    if with_reserve:
        # Конечный остаток: время ожидания на этом типе, а не константа в
        # килограммах. У E195 получасовое ожидание около 550 кг, у A320
        # вдвое больше, у широкофюзеляжного кратно — одно число на все
        # типы неверно во все стороны сразу.
        q_hold = ff.enroute(mass=oew + pax * pm, tas=HOLDING_TAS_KT,
                            alt=HOLDING_ALT_FT) * 3600
        f_final = q_hold * spec.final_reserve_min / 60.0
        # Уход на запасной: расстояние — вход, топливо считается тем же
        # профилем. Если запасной не назван, слагаемого нет, и разбор об
        # этом говорит: «не задан» — не то же самое, что «не нужен».
        f_alt = 0.0
        if spec.alternate_nm:
            f_alt = _openap_profile(icao, spec.alternate_nm, pax,
                                    with_reserve=False, frame=frame,
                                    flow_of=flow_of, scale=scale).trip_kg
    else:
        f_final = f_alt = 0.0

    for _ in range(iters):
        reserve = spec.contingency_frac * trip + f_final + f_alt
        # Без усечения: если масса выше предела, это надо показать, а не
        # спрятать. Ограничение проверяется после сходимости.
        m0 = oew + payload + trip + reserve

        # набор: расход считается на взлётной массе
        q_cl = ff.enroute(mass=m0, tas=CLIMB_TAS_KT, alt=crz_used / 2,
                          vs=CLIMB_VS_FPM) * 3600
        f_cl = q_cl * t_cl

        # крейсер: масса на середине участка
        d_cr = max(0.0, dist_nm - d_cl - d_de)
        t_cr = d_cr / tas_cr_used
        m_cr = m0 - f_cl - 0.5 * max(0.0, trip - f_cl - f_taxi)
        q_cr = ff.enroute(mass=m_cr, tas=tas_cr_used, alt=crz_used) * 3600
        f_cr = q_cr * t_cr

        # снижение: почти малый газ
        q_de = ff.enroute(mass=m_cr - f_cr, tas=DESCENT_TAS_KT, alt=crz_used / 2,
                          vs=-DESCENT_VS_FPM) * 3600
        f_de = q_de * t_de

        new = f_cl + f_cr + f_de + f_taxi
        converged = abs(new - trip) < tol_kg
        trip = new
        if converged:
            break

    airborne = t_cl + t_cr + t_de
    f_cont = spec.contingency_frac * trip
    reserve = f_cont + f_final + f_alt
    reserve_parts = {"Непредвиденный расход": f_cont,
                     "Конечный остаток": f_final,
                     "Уход на запасной": f_alt}
    feas = Feasibility(max_payload_t=max(0.0, (mtow - oew - trip - reserve) / 1000.0))
    feas.max_pax = int(feas.max_payload_t * 1000 / pm)
    if m0 > mtow:
        feas.overload_t = (m0 - mtow) / 1000.0
        feas.limit("mtow",
                   f"перегруз {feas.overload_t:.1f} т: взлётная {m0/1000:.1f} т "
                   f"при пределе {mtow/1000:.1f} т. На это плечо поднимет "
                   f"{feas.max_pax} пассажиров вместо {pax:.0f}",
                   over_t=feas.overload_t, limit_t=mtow / 1000.0)
    if mfc and trip + reserve > mfc:
        feas.fuel_over_t = (trip + reserve - mfc) / 1000.0
        feas.limit("fuel_capacity",
                   f"топливо не влезает: нужно {(trip+reserve)/1000:.1f} т, "
                   f"ёмкость баков {mfc/1000:.1f} т",
                   over_t=feas.fuel_over_t, limit_t=mfc / 1000.0)

    return FuelResult(
        trip_kg=trip,
        block_h=airborne + t_taxi,
        airborne_h=airborne,
        takeoff_mass_kg=m0,
        phases={"Руление": f_taxi, "Набор": f_cl, "Крейсер": f_cr,
                "Снижение": f_de},
        times={"Руление": t_taxi, "Набор": t_cl, "Крейсер": t_cr,
               "Снижение": t_de},
        method="openap",
        feasible=feas,
        reserve_kg=reserve,
        reserve_parts=reserve_parts,
        note=f"профиль: набор {CLIMB_VS_FPM:.0f} фт/мин, крейсер "
             f"FL{crz_used/100:.0f} на {tas_cr_used:.0f} kt, снижение "
             f"{DESCENT_VS_FPM:.0f} фт/мин"
             + (" — эшелон срезан: плечо короткое" if truncated else ""),
    )


# ---------------------------------------------------------------------
# Диаграмма «полезная нагрузка — дальность», она же «домик».
#
# Три участка, и у каждого своё ограничение:
#
#   1. Полка. Нагрузка максимальна, дальность растёт за счёт топлива,
#      пока взлётная масса не упрётся в предел. Верх «крыши».
#   2. Скат. Взлётная масса уже на пределе, поэтому каждый килограмм
#      топлива берётся взамен килограмма нагрузки. Дальность растёт,
#      нагрузка падает — один к одному.
#   3. Обрыв. Баки полны, добавить топлива нельзя. Дальше дальность
#      растёт только за счёт облегчения борта, и падает нагрузка круче.
#
# Мы считаем прямую задачу — расстояние даёт топливо, — поэтому обратная
# решается делением пополам, как и всё остальное в этом проекте.
# ---------------------------------------------------------------------


def max_range_nm(icao: str, payload_kg: float, lo: float = 50.0,
                 hi: float = 12000.0, tol: float = 5.0,
                 frame: "Airframe | None" = None,
                 ref: "BurnRef | None" = None) -> float:
    """Наибольшее плечо, выполнимое с такой нагрузкой."""
    pm, _ = pax_mass(icao, frame.mtow_kg / 1000.0 if frame else None)
    pax_equiv = payload_kg / pm
    fx = lambda d: trip_fuel(icao, d, pax_equiv, frame=frame, ref=ref)   # noqa: E731
    if fx(lo).feasible.ok is False:
        return 0.0
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if fx(mid).feasible.ok:
            lo = mid
        else:
            hi = mid
    return lo


def payload_range(icao: str, seats: int | None = None, points: int = 9,
                  frame: "Airframe | None" = None,
                  ref: "BurnRef | None" = None) -> dict:
    """Точки диаграммы и её характерные углы.

    Планер — из хранилища, когда он передан; библиотека — только запасной
    путь. Иначе своему типу диаграмма не строилась вовсе, а тип с
    массами, отличными от библиотечных, получал чужой «домик».
    """
    # Тип без своей физики и без якоря отвечает «нельзя» (решение 106):
    # каждая точка кривой была бы невыполнимой, и диаграмма вышла бы из
    # нулей — правдоподобная картинка вместо отказа.
    if ref is not None and ref.anchor_kg_per_h is None and not ref.same_engine:
        return {"error": (f"расход {icao} не привязан: назван аналог {ref.analog}, "
                          f"но нет якоря — диаграмма не строится (решение 106)")}
    if frame is not None:
        oew, mtow = frame.oew_kg, frame.mtow_kg
    else:
        # Запасной путь — та же функция, что даёт планер расчёту маршрута.
        # Прежде здесь стоял вызов `_openap`, которой после переезда
        # планера в хранилище не существует: диаграмма отказывала на любом
        # типе с NameError, а не с причиной.
        try:
            frame = airframe_from_openap(icao)
            oew, mtow = frame.oew_kg, frame.mtow_kg
        except Exception as exc:                           # noqa: BLE001
            return {"error": f"нет планера {icao}: ни в хранилище, ни в openap ({exc})"}
    pm, pm_src = pax_mass(icao, mtow / 1000.0)
    full = (seats or 0) * pm or (mtow - oew) * 0.5

    curve = []
    for i in range(points):
        pl = full * (1 - i / (points - 1))
        curve.append({"payload_kg": pl,
                      "pax": pl / pm,
                      "range_nm": max_range_nm(icao, pl, frame=frame, ref=ref)})
    # Угол «домика»: там, где баки становятся полными и снятие нагрузки
    # перестаёт покупать дальность. Это самая содержательная точка
    # диаграммы: до неё обмен пассажиров на мили выгоден, после — почти
    # бесполезен.
    corner = None
    best = 0.0
    for a, b in zip(curve, curve[1:]):
        d_pl = a["payload_kg"] - b["payload_kg"]
        if d_pl <= 0:
            continue
        gain = (b["range_nm"] - a["range_nm"]) / (d_pl / 1000.0)   # миль за тонну
        b["nm_per_tonne"] = gain
        if best and gain < best * 0.5 and corner is None:
            corner = a
        best = max(best, gain)

    return {"icao": icao, "pax_mass_kg": pm, "pax_mass_source": pm_src,
            "oew_t": oew / 1000, "mtow_t": mtow / 1000,
            "full_payload_kg": full, "curve": curve, "corner": corner}


# Ориентировочная потребная длина полосы. НЕ расчёт характеристик: он
# требует тяги, площади крыла, температуры, превышения и уклона, и без
# этих данных любая формула будет выдумкой. Здесь грубая привязка к
# массе, откалиброванная по нескольким известным типам, с явной пометкой
# «оценка». Задача — отсеять невозможное (A388 на полосу в 1500 м), а не
# заменить расчёт лётных характеристик.
RUNWAY_REF = [(25.0, 1300), (50.0, 1800), (80.0, 2200),
              (150.0, 2700), (250.0, 3000), (600.0, 3300)]


def required_runway_m(mtow_t: float) -> float:
    """Оценка потребной длины полосы, метры."""
    prev_m, prev_l = 5.0, 900
    for m, l in RUNWAY_REF:
        if mtow_t <= m:
            k = (mtow_t - prev_m) / (m - prev_m) if m > prev_m else 0
            return prev_l + k * (l - prev_l)
        prev_m, prev_l = m, l
    return RUNWAY_REF[-1][1]
