"""Экономика маршрута.

Сознательно построено вокруг ТОЧКИ БЕЗУБЫТОЧНОСТИ, а не прибыли.
Затраты считаются детерминированно с точностью порядка ±10%. Спрос,
загрузка и yield — не считаются вообще, они задаются рукой. Модель,
которая выдаёт "маржа 8.4%", маскирует три догадки сорока параметрами.
Модель, которая выдаёт "выходит в ноль при LF 74% и среднем чеке 142 EUR",
говорит ровно то, что знает.

Каждый результат несёт с собой список источников, из которых он собран,
и их свежесть. Если хоть один пробил SLA — result.degraded = True.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date
from pathlib import Path

from .airspace import billing_zones, crossing
from .charges import (CODE_RU, evaluate, load_rules, rule_nodes, parse_context_sets,
                      charge_caveats)
from .navcharge import FORMULA_RU, charge as nav_charge
from .fleet import load as load_fleet
from . import categories as _cat
from .overrides import Resolver, split_context
from .fuel import (Airframe, BurnRef, ReserveSpec, airframe_from_openap, fit_burn,
                   required_runway_m, trip_fuel)
from .store import Store

R_EARTH_NM = 3440.065
TCZ_PATH = Path(__file__).resolve().parents[1] / "config" / "tcz.yaml"


def _tcz_map() -> dict:
    """Аэродром -> терминальная зона. Ярус 1: список ведётся вручную."""
    try:
        import yaml
        with open(TCZ_PATH, encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("tcz", {}) or {}
    except Exception:                                   # noqa: BLE001
        return {}


@dataclass
class Aircraft:
    """Физика и лётные данные типа. Приходят из справочника, не из кода.

    Экономика эксплуатации живёт отдельно, в `fleet.FleetEconomics`, и
    ключуется парой «перевозчик плюс тип»: A320 у сетевого и у лоукостера
    стоят по-разному, а масса у них одинаковая.

    Кресла — особый случай. Это не свойство типа, а решение перевозчика:
    у A320 бывает от 150 до 186. Берутся из компоновки, если перевозчик
    известен, и типовое значение справочника иначе.
    """

    icao: str
    seats: int
    mtow_t: float
    cruise_kt: float = 450.0
    fuel_kg_per_h: float = 2400.0
    seats_source: str = "справочник"
    # Планер: справочные величины, из которых выводится выполнимость.
    # `openap` их тоже знает, и до разделения расчёт брал их оттуда —
    # два источника для одних чисел, расходящиеся молча. Теперь
    # библиотека остаётся вычислителем расхода и справочником не является.
    frame: "Airframe | None" = None
    frame_source: str = "store"
    # Четвёртый ярус расхода: аналог и якорь из тех же фактов типа.
    # `None` — у типа свой вычислитель (или его нет, и тогда «нельзя»).
    burn_ref: "BurnRef | None" = None
    # Имя из справочника — для витрины и разбора, не для ключа.
    name: str = ""


def load_aircraft(store, icao: str, as_of, operator: str = "*") -> Aircraft:
    """Тип из домена `aircraft`. Словаря в коде больше нет.

    Он держался три этапа, потому что каждый раз казался мелочью, и всё
    это время нарушал первое решение проекта: справочник строится
    локально, а не хранится в исходниках. Побочно ограничивал расчёт
    четырьмя типами при тридцати семи доступных и давал расхождения —
    180 кресел против 170, 51.8 тонны против 50.3.
    """
    icao = icao.upper()
    g = lambda k: store.value("aircraft", f"{icao}/{k}", as_of)
    mtow = g("mtow_t")
    if mtow is None:
        have = sorted({k.split("/")[0] for k in store.current("aircraft", as_of)})
        raise KeyError(
            f"типа {icao} нет в справочнике. Доступны: {', '.join(have[:12])}"
            + (f" и ещё {len(have) - 12}" if len(have) > 12 else "")
            + ". Обновить: fca refresh --only aircraft_openap")

    # Порядок: компоновка перевозчика, общая компоновка, типовая из
    # справочника типов. Всё из хранилища — config/ больше не читается.
    seats = store.value("aircraft_layout", f"{operator}/{icao}", as_of)
    src = f"компоновка {operator}"
    if seats is None:
        seats, src = (store.value("aircraft_layout", f"*/{icao}", as_of),
                      "компоновка по умолчанию")
    if seats is None:
        seats, src = (g("seats_typical") or g("seats_max")), "типовая из справочника"

    from openap import aero
    mach = g("cruise_mach") or 0.78
    alt_m = g("cruise_alt_m") or 11000.0
    kt = aero.mach2tas(mach, alt_m) / aero.kts

    # Планер из домена. Чего в домене нет — берётся из библиотеки, но
    # источник называется: два источника для одних чисел допустимы ровно
    # до тех пор, пока видно, из какого взято.
    #
    # Ёмкость баков в домене лежит как `fuel_capacity_t` (парсер openap),
    # а читалось `mfc_kg` — поле без читателя (решение 101): планер из
    # хранилища получал ёмкость 0, и проверка «топливо не влезает» для
    # него не срабатывала никогда. Старое имя остаётся запасным.
    oew = g("oew_t")
    mfc_t = g("fuel_capacity_t")
    mfc_kg = float(mfc_t) * 1000.0 if mfc_t is not None else g("mfc_kg")
    if oew is not None:
        frame = Airframe(icao=icao, oew_kg=float(oew) * 1000.0,
                         mtow_kg=float(mtow) * 1000.0,
                         mfc_kg=float(mfc_kg or 0.0),
                         cruise_alt_ft=float(alt_m) / 0.3048,
                         cruise_tas_kt=float(kt), source="store")
        fsrc = "хранилище" + ("" if mfc_kg else "; ёмкость баков не задана")
    else:
        try:
            frame = airframe_from_openap(icao)
            frame.mtow_kg = float(mtow) * 1000.0   # масса из домена главнее
            fsrc = f"библиотека: в домене aircraft нет ключа {icao}/oew_t"
        except Exception:                          # noqa: BLE001
            frame, fsrc = None, "нет ни в домене, ни в библиотеке"

    # Аналог и якорь — факты того же типа. Заводятся человеком через
    # каталог `aircraft_user`; у типов openap их нет и не нужно.
    # `store.value` отдаёт числовую колонку; аналог и примечание лежат в
    # `value_text`. Первый прогон читал их через value, получал None и
    # честно писал «аналог не назван» на типе, у которого он назван.
    def gt(k):
        row = store.get("aircraft", f"{icao}/{k}", as_of)
        return (row["value_text"] or "") if row is not None else ""
    analog = gt("burn_analog")
    ref = None
    if analog:
        a_mass = g("burn_anchor_mass_t")
        ref = BurnRef(analog=str(analog).upper(),
                      anchor_kg_per_h=g("burn_anchor_kg_per_h"),
                      anchor_mass_kg=float(a_mass) * 1000.0 if a_mass else None,
                      same_engine=bool(g("burn_same_engine")),
                      note=gt("burn_anchor_note"))
    row = store.get("aircraft", f"{icao}/mtow_t", as_of)
    name = str(row["note"] or "") if row is not None and row["note"] else ""
    return Aircraft(icao=icao, seats=int(seats), mtow_t=float(mtow),
                    cruise_kt=float(kt), seats_source=src,
                    frame=frame, frame_source=fsrc, burn_ref=ref, name=name)


@dataclass
class Step:
    """Один шаг вывода. Хранит не только результат, но и формулу с
    подстановкой и происхождение входных данных — из этого потом
    собирается человекочитаемый разбор."""

    n: int
    group: str
    label: str
    formula: str
    subst: str
    value: float
    unit: str
    prov: str            # input | store | fleet | default | derived
    node: str            # идентификатор узла карты данных
    src: str = ""
    # АДРЕС факта, на котором стоит шаг: "домен/ключ". Не то же, что `src`
    # и не то же, что `node`. `src` — подпись для человека («справочник
    # airport, источник ourairports»), `node` — узел карты данных, а
    # `ref` — то, по чему можно открыть саму запись: значение, интервал,
    # достоверность, цена ошибки, история редакций.
    #
    # Без него «прокликать до справочника» упиралось в прозу: шаг называл
    # источник словами, а адреса не нёс — хотя резолвер его знает, в его
    # журнале на каждое чтение лежит `домен.ключ`.
    #
    # `None` означает «шаг не стоит на факте»: вычислен из других шагов
    # или задан входом. Это ответ, а не пробел, и отличать его от «адрес
    # есть, но не заполнен» обязательно.
    ref: str | None = None


# Подписи статей затрат. Ключ и подпись разделены (решение 27): ключ
# уезжает в схему формы и в идентификаторы полей, где кириллица
# неуместна, подпись остаётся здесь и переводится каталогами по спросу.
COST_RU = {
    "fuel":            "Топливо",
    "enroute":         "Аэронавигация",
    "terminal":        "Терминальный сбор",
    "airport_charges": "Аэропортовые сборы",
    "ownership":       "Владение ВС",
    "maintenance":     "ТОиР",
    "crew":            "Экипаж",
    "ground_handling": "Наземное обслуживание",
    "distribution":    "Дистрибуция и продажи",
}


@dataclass
class Result:
    origin: str
    destination: str
    aircraft: str
    distance_nm: float
    block_h: float
    fuel_kg: float
    cost: dict = field(default_factory=dict)
    breakeven_fare_eur: float = 0.0
    breakeven_lf: float | None = None
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    feasible: bool = True
    max_pax: int = 0            # сколько поднимет на это плечо
    trade: dict = field(default_factory=dict)   # чем платим за выполнимость
    trace: list = field(default_factory=list)
    overrides: list = field(default_factory=list)
    # Полнота начисления по каждому аэропорту: сколько статей тарифа
    # осталось без цены из-за неизвестных значений условий. Доля СУММЫ
    # здесь невозможна по построению — величина пропущенной статьи
    # неизвестна, иначе она не была бы пропущена.
    # `None`, а не `{}`. Пустой словарь у поля, которое означает «отчёт о
    # полноте», неотличим от «проверено, пропусков нет» — а означал бы
    # «не присваивалось». Механизм, написанный против тихого недосчёта,
    # отказал бы по своей же схеме (решение 67).
    charge_gaps: dict | None = None
    # Строки сборов по обоим концам, ключ `ИКАО/код`. Нужны отдельно от
    # трассировки: сверяться с подписью шага — та же связка ключа с
    # подписью, из-за которой ломалась карта.
    charge_lines: dict | None = None
    # Выполнимость структурой, а не прозой: во что упёрлись машинным
    # ключом. `None` означает «не считалось» — тот же класс, что
    # `charge_gaps` (решения 67 и 85).
    feasibility: dict | None = None
    # Оговорки прочтения по аэропортам. `None` — не считалось; пустой
    # список у аэропорта — считалось, оговорок нет. Пустая панель
    # «принято на прочтении» читается как «мы проверили», а означала бы
    # «нечего сказать» (решения 67 и 85).
    caveats: dict | None = None
    # Валюты, реально задействованные расчётом. Без этого эталонный набор
    # маршрутов не проверяем: Алматы берут в него ради тенге, а убедиться,
    # что тенге действительно участвовал, нечем. Решение 89 требует, чтобы
    # маршрут объявлял, что обязан задействовать; это — проверяемое.
    currencies_seen: set | None = None
    inputs: dict = field(default_factory=dict)
    cost_prov: dict = field(default_factory=dict)

    def charges_checked(self) -> bool:
        """Считалось ли начисление вообще.

        Три состояния вместо двух: не считалось (`None`), считалось и
        пропусков нет (пустой отчёт у каждого аэропорта), считалось и
        пропуски есть. Первое и второе обязаны различаться — иначе поле
        отвечает «всё в порядке» на вопрос, который ему не задавали.
        """
        return self.charge_gaps is not None

    def override_share(self) -> float:
        """Доля суммы, стоящая на ручных значениях. Это не «выдумано» и не
        «из источника», а допущение пользователя — третья категория."""
        if not self.cost_total:
            return 0.0
        return sum(v for k, v in self.cost.items()
                   if self.cost_prov.get(k) == "override") / self.cost_total

    def default_share(self) -> float:
        """Доля итоговой суммы, опирающаяся на выдуманные константы.
        Главный диагностический показатель: он говорит, насколько
        результату вообще можно верить."""
        if not self.cost_total:
            return 0.0
        risky = sum(v for k, v in self.cost.items()
                    if self.cost_prov.get(k) == "default")
        return risky / self.cost_total

    @property
    def cost_total(self) -> float:
        return sum(self.cost.values())

    def report(self) -> str:
        lines = [
            f"{self.origin}-{self.destination}  {self.aircraft}  "
            f"{self.distance_nm:.0f} nm  block {self.block_h:.2f} h  "
            f"fuel {self.fuel_kg:.0f} kg",
            "-" * 62,
        ]
        for k, v in sorted(self.cost.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {COST_RU.get(k, k):<24} {v:>12,.0f} EUR   "
                         f"{v/self.cost_total*100:>5.1f}%")
        lines.append("-" * 62)
        lines.append(f"  {'ИТОГО за рейс':<24} {self.cost_total:>12,.0f} EUR")
        lf = self.inputs.get("load_factor")
        fare = self.inputs.get("fare_eur")
        seats = self.inputs.get("seats", 0)
        lines.append("")
        lines.append("  ЗАДАНО ТОБОЙ:")
        lines.append(f"    загрузка   {lf*100:.0f}%  =  {seats*lf:.0f} из {seats} кресел")
        lines.append(f"    тариф      {fare:,.0f} EUR/пасс" if fare
                     else "    тариф      не задан (--fare)")
        lines.append("")
        lines.append("  БЕЗУБЫТОЧНОСТЬ:")
        lines.append(f"    при загрузке {lf*100:.0f}% нужен тариф "
                     f"{self.breakeven_fare_eur:,.0f} EUR")
        if self.breakeven_lf is not None:
            lines.append(f"    при тарифе {fare:,.0f} EUR нужна загрузка "
                         f"{self.breakeven_lf*100:.1f}%")
            gap = (fare - self.breakeven_fare_eur) * seats * lf
            verdict = "прибыль" if gap >= 0 else "УБЫТОК"
            lines.append("")
            lines.append(f"    ИТОГ при твоих {lf*100:.0f}% и {fare:,.0f} EUR: "
                         f"{verdict} {abs(gap):,.0f} EUR за рейс")
        lines.append("")
        if not self.feasible:
            lines.append("")
            lines.append("  РЕЙС НЕВЫПОЛНИМ на этом типе — числа выше "
                         "справочные, не планируйте по ним")
            t = self.trade
            if t:
                lines.append("")
                lines.append("  ЧЕМ ПЛАТИТЬ ЗА ВЫПОЛНИМОСТЬ:")
                lines.append(f"    снять {t['pax_drop']} пассажиров — "
                             f"останется {t['pax_ok']} "
                             f"(загрузка {t['lf_ok']*100:.0f}%)")
                if t["revenue_loss"]:
                    lines.append(f"    выручка падает на "
                                 f"{t['revenue_loss']:,.0f} EUR за рейс")
                lines.append(f"    безубыточный тариф: "
                             f"{t['breakeven_before']:,.0f} → "
                             f"{t['breakeven_after']:,.0f} EUR")
            else:
                lines.append("    компромисса нет: тип не долетит и пустым")
        elif self.max_pax:
            # Запас считается по массе, а ограничивает кресло: взять
            # больше, чем помещается в салон, некуда. Показываем меньшее
            # из двух, иначе получается «ещё 114 пассажиров» в самолёт,
            # где их некуда посадить.
            seats = int(self.inputs.get("seats") or 0)
            now = int(round(self.inputs.get("pax", 0)))
            head = min(self.max_pax, seats) - now
            lines.append("")
            if head > 0:
                limit = ("кресла" if self.max_pax >= seats else "масса")
                lines.append(f"  Запас: ещё {head} пассажиров до полной "
                             f"загрузки, ограничивает {limit}")
                if self.max_pax > seats:
                    spare = (self.max_pax - seats) * 0.1
                    lines.append(f"    по массе борт поднял бы ещё "
                                 f"{self.max_pax - seats} человек — около "
                                 f"{spare:.1f} т свободной нагрузки, которую "
                                 f"мог бы занять груз")
            elif head == 0:
                lines.append("  Загрузка предельная: свободных кресел нет")
        lines.append(f"  На выдуманных константах держится "
                     f"{self.default_share()*100:.0f}% суммы")
        if self.warnings:
            lines.append("")
            lines.append("  ВНИМАНИЕ:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)


def great_circle_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


@lru_cache(maxsize=1)
def _nav_formulas() -> dict:
    """Способ расчёта сбора по зонам. Отсутствие записи означает правило
    EUROCONTROL — оно верно для сорока одного государства его зоны и
    разумно для соседей, но ставка всё равно нужна отдельно, так что
    пробел не спрячется."""
    try:
        import yaml
        path = Path(__file__).resolve().parents[1] / "config" / "nav_zones.yaml"
        with open(path, encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("zones", {}) or {}
    except Exception:                                  # noqa: BLE001
        return {}


class _Cross:
    """Пересечение зон по ломаной: суммы по плечам в той же форме, что
    отдаёт `crossing` для прямой."""

    def __init__(self, legs, prefer):
        acc: dict[str, float] = {}
        self.unassigned_nm = 0.0
        self.by_layer: dict[str, float] = {}
        for p, q in zip(legs, legs[1:]):
            nm = great_circle_nm(*p, *q)
            c = crossing(p[0], p[1], q[0], q[1], nm, prefer=prefer)
            for z, v in dict(c.zones).items():
                acc[z] = acc.get(z, 0.0) + v
            for k, v in c.by_layer.items():
                self.by_layer[k] = self.by_layer.get(k, 0.0) + v
            self.unassigned_nm += c.unassigned_nm
        self.zones = list(acc.items())


def _crossing_along(legs, prefer):
    if len(legs) == 2:
        p, q = legs
        return crossing(p[0], p[1], q[0], q[1], great_circle_nm(*p, *q), prefer=prefer)
    return _Cross(legs, prefer)


def _airport(store: Store, code: str, as_of):
    row = store.get("airport", code.upper(), as_of)
    if row is None:
        raise KeyError(f"аэропорт {code} отсутствует в справочнике — "
                       f"запусти `fca refresh --only ourairports`")
    latlon, icao, iso, name = row["value_text"].split("|", 3)
    lat, lon = (float(x) for x in latlon.split(","))
    return {"lat": lat, "lon": lon, "icao": icao, "country": iso, "name": name}


# Домен локальных категорий ВС: «в этом аэропорту борт этого типа
# относится к такой-то категории». Заводит ветка B (решение 68); имя
# домена предварительное и меняется одной строкой.
#
# Ключ включает и аэропорт, и тип, потому что величина принадлежит паре:
# тройка означает у Франкфурта категорию 3, у Дублина QC 0,5, у Гатвика
# Chapter 14, у Познани букву кода ИКАО. Сквозной шкалы не существует.
CTX_DOMAIN = "airport_ac_category"
# Только то, что определяет ТИП (решение 78). `stand_group`, `stand` и
# `park_h` сюда не входят намеренно: на этапе планирования никто не
# знает, к какому перрону встанет борт, справочного значения не
# существует, и заводить под него домен значило бы обещать факт,
# которого нет. Они остаются входом и задаются через `--set`.
CTX_FROM_STORE = ("noise_cat", "ac_class", "ac_group")


# Ступени шкалы направлений по коду страны. Ярус ниже — дешевле.
#
# ВЫДУМАННАЯ КОНСТАНТА в смысле решения 1: состав клубов — справочные
# данные, которым место в хранилище, а не в исходниках. Лежит здесь
# временно и помечается провенансом `default`, как цена топлива до
# появления своего домена.
#
# Шкала одномерна, а членство нет, поэтому она врёт на странах, которые
# входят в один клуб против порядка ступеней: Швейцария в Шенгене, но не
# в ЕЭП, и из Испании по документу дороже, чем окажется по шкале.
# Расхождение в пределах одной ступени пассажирского сбора, принято.
_SCHENGEN = {
    "AT", "BE", "BG", "CH", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL",
    "PT", "RO", "SE", "SI", "SK",
}
_EU = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
}
# Европа в географическом смысле: всё, что не Европа, — межконтинентальное.
_EUROPE = _EU | _SCHENGEN | {
    "AL", "AD", "AM", "AZ", "BA", "BY", "GB", "GE", "GI", "MC", "MD", "ME",
    "MK", "RS", "RU", "SM", "TR", "UA", "VA", "XK", "FO", "GL",
}


def dest_step(iso: str) -> str:
    """Ступень шкалы направлений для страны назначения вылета."""
    iso = (iso or "").upper()
    if iso in _SCHENGEN:
        return "schengen"
    if iso in _EU:
        return "eu_non_schengen"
    if iso in _EUROPE:
        return "europe_non_eu"
    return "intercontinental"


# Рейсов в обороте, по которому считаются сборы концов маршрута. Сборы
# начисляются за оборот, статьи затрат и выручка — за рейс.
LEGS_PER_ROTATION = 2


def rotation_events(icao: str, legs: list[tuple[str, str]]) -> dict:
    """Сколько раз каждое событие случается в ЭТОМ аэропорту за расчётную
    единицу.

    Выводится из плеч, а не задаётся числом. Пока движений было жёстко
    одно, признак начисления не различал ничего: `movement`, `landing` и
    `turnaround` давали одинаковый множитель, и защита от самой частой
    ошибки разбора лежала без применения.

    За оборот каждый конец маршрута видит один прилёт и один вылет, то
    есть два движения, одну посадку и одно обслуживание. Симметрия здесь
    не совпадение: закрытый оборот касается обоих аэропортов поровну.
    Ставки при этом разные, и оборот не равен удвоенному сектору.
    """
    arrivals = sum(1 for _, d in legs if d == icao)
    departures = sum(1 for o, _ in legs if o == icao)
    return {"movements": arrivals + departures,
            "landings": arrivals,
            "turnarounds": min(arrivals, departures) or max(arrivals, departures),
            "departures": departures}


def charge_context(ap: dict, other: dict, ac: Aircraft, *, pax: float,
                   month: int, events: dict,
                   park_h: float = 0.0, cargo_kg: float = 0.0,
                   pax_type: str = "local", stand: str = "apron",
                   noise_cat: int | None = None, noise_cat_dep: int | None = None,
                   ac_class: int | None = None,
                   ac_group: int | None = None, stand_group: int | None = None,
                   return_technical: bool = False,
                   operator: str | None = None,
                   terminal: str | None = None,
                   seats: float | None = None) -> dict:
    """Контекст начисления сборов ОДНОГО аэропорта.

    Был литералом внутри расчёта с зашитыми `flight="EEA"` и
    `noise_cat=3`, подавал семь ключей из пятнадцати. Восемь не приходили
    никогда, и правило с таким условием проходило проверку достижимости,
    а срабатывало ноль раз: во Франкфурте так умирали 90 правил из 99 и
    85% суммы.

    По аэропорту, а не на расчёт: `noise_cat`, `stand_group`, `ac_class`
    — порядковые номера ВНУТРИ аэропорта. Тройка означает у Франкфурта
    категорию 3, у Дублина QC 0,5, у Гатвика Chapter 14, у Познани букву
    кода ИКАО. Одно значение на весь расчёт неверно, как только у
    маршрута два конца.

    Категории оставлены незаполненными намеренно. Значения нет в
    хранилище, а зашитая тройка была выдуманной константой без пометки;
    `evaluate` теперь называет статьи, потерянные из-за неизвестного
    значения, вместо того чтобы молча их ронять.
    """
    dest = dest_step(other["country"])
    return {
        # величины
        "mtow_t": ac.mtow_t, "pax": pax, "cargo_kg": cargo_kg,
        **events,
        # условия
        "flight": "domestic" if ap["country"] == other["country"] else (
            "EEA" if dest in ("schengen", "eu_non_schengen") else "INTL"),
        "pax_type": pax_type,
        "dest": dest,
        "month": month,
        "night": False,
        "noise_cat": noise_cat,
        "noise_cat_dep": noise_cat_dep,
        "cargo": cargo_kg > 0,
        "stand": stand,
        "stand_group": stand_group,
        "ac_group": ac_group,
        "ac_class": ac_class,
        "pax_per_mtow": pax / ac.mtow_t if ac.mtow_t else None,
        "park_h": park_h,
        "park_h_over_free": park_h > 0,
        "return_technical": return_technical,
        # Без значения по умолчанию: свой или иностранный — свойство рейса,
        # и подставить «иностранный» значило бы посчитать Аэрофлоту сбор
        # в долларах и выдать это за ответ. Пропуск доезжает до отчёта как
        # вопрос к пользователю.
        "operator": operator,
        "terminal": terminal,
        # Другой конец плеча — свойство рейса, выводится, не спрашивается.
        "other": other["icao"],
        # Кресла — из компоновки (решение 44), а не из типа.
        "seats": float(seats if seats is not None else ac.seats),
    }


GALLON_L = 3.785411784      # международный галлон США, определение точное


def route_economics(store: Store, origin: str, destination: str, *,
                    aircraft: str = "A320", as_of: str | date | None = None,
                    load_factor: float = 0.80, fare_eur: float | None = None,
                    fuel_eur_per_kg: float | None = None,
                    operator: str = "*",
                    month: int | None = None,
                    alternate_nm: float | None = None,
                    freq_week: float | None = None,
                    util_mode: str = "fleet_average",
                    seats: int | None = None,
                    overrides: dict | None = None,
                    charge_ctx: dict | None = None,
                    via: list | None = None,
                    _trade: bool = True,
                    freshness: list[dict] | None = None) -> Result:
    as_of = as_of or date.today().isoformat()
    # Один ключ `--set` на входе, два механизма внутри: переопределения
    # фактов идут в слой сценария, условия начисления — в контекст.
    _facts, from_set = split_context(overrides)
    res_ = Resolver(store=store, as_of=as_of, overrides=_facts)
    ac = load_aircraft(store, aircraft, as_of, operator)
    # Кресла, заданные рейсом, старше компоновки: это тот же слой сценария,
    # что `--set`, только для величины, которая через резолвер не идёт —
    # `load_aircraft` читает компоновку напрямую. Число снаружи заменяет
    # кресла ЯВНО, с провенансом `input` в трассировке, а не подменой в
    # хранилище (решение 10). Отсюда же положения витрины «по
    # сертификату» и «своя»: первое шлёт `seats_max` типа, второе — число.
    seats_over_max, seats_given = None, seats   # ниже `seats` затеняется шагом
    if seats is not None:
        if int(seats) < 1:
            raise ValueError(f"кресел задано {seats}: меньше одного нельзя")
        smax = store.value("aircraft", f"{ac.icao}/seats_max", as_of)
        if smax and int(seats) > int(smax):
            seats_over_max = int(smax)
        ac.seats, ac.seats_source = int(seats), "задано"
    a, b = _airport(store, origin, as_of), _airport(store, destination, as_of)
    # Условия начисления по аэропортам нужны раньше сборов: маршрутный и
    # терминальный сбор аэронавигации в России зависят от того, свой ли
    # эксплуатант, а это то же условие `operator`.
    cctx = (charge_ctx if isinstance(charge_ctx, dict)
            and all(isinstance(v, dict) for v in charge_ctx.values())
            else parse_context_sets(charge_ctx or {}))
    warnings: list[str] = []
    trace: list[Step] = []
    n = [0]

    # Узел карты данных, к которому относится шаг. Умолчания нет
    # намеренно (решение 24): шаг без узла попадает в отчёт сверки
    # отдельной строкой, а необязательное поле молча заполнялось бы
    # пустотой, и пустой результат сверки перестал бы что-либо значить.
    #
    # Узел — это ОТКУДА берутся числа, а не что делает шаг. Ортодромия
    # считается здесь, но стоит на координатах аэропорта, поэтому её узел
    # `d_airport`. Иначе узел пришлось бы заводить на каждое вычисление,
    # и единицей снова стала бы строка, а не узел.
    def rec(group, label, formula, subst, value, unit, prov, src="", *,
            node, ref=None):
        n[0] += 1
        trace.append(Step(n[0], group, label, formula, subst, value, unit,
                          prov, node, src, ref))
        return value

    G1, G2, G3, G4, G5, G6 = ("Вход", "География и время", "Топливо",
                              "Аэронавигация", "Аэропорт", "Экономика флота")

    # ---------- вход ----------
    rec(G1, "Загрузка", "задана ключом --lf", f"{load_factor}",
        load_factor, "доля", "input", node="i_lf")
    if fare_eur:
        rec(G1, "Тариф", "задан ключом --fare", f"{fare_eur}",
            fare_eur, "EUR/пасс", "input", node="i_fare")
    # Компоновка перевозчика и типовая — факты хранилища, а не ввод: с
    # переезда из `config/` они лежат в `aircraft_layout` с провенансом.
    # `input` — только число, заданное рейсом.
    seats = rec(G1, "Кресел", ac.seats_source, f"{ac.seats}",
                ac.seats, "шт",
                "input" if ac.seats_source == "задано" else "store",
                "число кресел — решение перевозчика, а не свойство типа: "
                "у A320 бывает от 150 до 186", node="v_seats")
    if seats_over_max:
        # Больше сертифицированного максимума — не запрет (максимум в
        # справочнике может быть по одной из редакций сертификата), но и
        # не молча: масса пассажиров растёт, а выполнимость считается по
        # ней. Решение 37.
        warnings.append(f"кресел задано {ac.seats} при сертифицированном "
                        f"максимуме {seats_over_max} для {ac.icao}")
    rec(G1, "MTOW", "справочник aircraft, источник openap", f"{ac.mtow_t}",
        ac.mtow_t, "т", "store", node="v_mtow")
    rec(G1, "MTOW", f"FLEET['{ac.icao}'].mtow_t", f"{ac.mtow_t}",
        ac.mtow_t, "т", "fleet", "econ.py: словарь FLEET", node="v_mtow")

    # Месяц ВЫЛЕТА, не дата справочника. Сезонная дифференциация есть у
    # пяти аэропортов из девяти разобранных, на Дублине она удваивает
    # посадочный сбор. Подставить сюда `as_of` было бы тем самым тихим
    # сбоем: расчёт по мартовской редакции тарифа стал бы расчётом
    # мартовского рейса.
    #
    # Умолчания нет намеренно (решение 24). Незаданный месяц не
    # превращается в июль, а оставляет сезонные правила несработавшими —
    # и `evaluate` об этом скажет.
    if month is not None:
        if not 1 <= int(month) <= 12:
            raise ValueError(f"месяц вылета вне 1-12: {month}")
        month = int(month)
        rec(G1, "Месяц вылета", "задан ключом --month", f"{month}",
            month, "мес", "input",
            "сезонная дифференциация ставок у пяти аэропортов из девяти", node="i_month")
    else:
        warnings.append("месяц вылета не задан (--month): сезонные ставки "
                        "аэропортов не сработают, будут названы в разборе")

    # ---------- география и время ----------
    # Путь — ортодромия либо ломаная через точки обхода закрытого неба
    # (решение 158): тогда шаг называет лишние мили и то, что обойдено.
    # Поправка ИКАО к ортодромии (решение 47) ниже прибавляется к сумме
    # плеч так же, как к прямой: она про схемы и ожидание, не про обход.
    legs = [(a["lat"], a["lon"])] + [tuple(map(float, w)) for w in (via or [])] \
        + [(b["lat"], b["lon"])]
    gc_direct = great_circle_nm(a["lat"], a["lon"], b["lat"], b["lon"])
    dist = sum(great_circle_nm(*p, *q) for p, q in zip(legs, legs[1:]))
    if via:
        rec(G2, "Путь с обходом", "Σ ортодромий по точкам обхода",
            f"{a['icao']} → {len(via)} т. → {b['icao']}; прямая {gc_direct:.0f} nm",
            dist, "nm", "derived",
            f"обход закрытого неба: +{dist - gc_direct:.0f} nm "
            f"(+{(dist / gc_direct - 1) * 100:.1f}%)", node="v_dist")
    else:
        rec(G2, "Ортодромия", "2R·asin(√(sin²(Δφ/2)+cosφ₁cosφ₂sin²(Δλ/2)))",
            f"{a['icao']} ({a['lat']:.3f}, {a['lon']:.3f}) → "
            f"{b['icao']} ({b['lat']:.3f}, {b['lon']:.3f})",
            dist, "nm", "store", "справочник airport, источник ourairports", node="v_dist")

    # ---------- топливо и блок-время ----------
    # Считаются вместе: и то и другое выпадает из одного профиля полёта.
    pax_pre = ac.seats * load_factor
    # Запас: два слагаемых из правил, третье из операции дня (решение 78).
    # Домена `fuel_reserve` пока нет, поэтому регуляторные величины идут с
    # умолчанием и провенансом `default`; расстояние до запасного — вход и
    # умолчания не имеет: «не задан» это не «не нужен».
    _cont = res_.value("fuel_reserve", "contingency_frac")
    _final = res_.value("fuel_reserve", "final_reserve_min")
    spec = ReserveSpec(
        contingency_frac=_cont if _cont is not None else ReserveSpec.contingency_frac,
        final_reserve_min=_final if _final is not None else ReserveSpec.final_reserve_min,
        alternate_nm=alternate_nm,
        provenance="store" if _cont is not None else "default")
    if ac.frame_source != "хранилище":
        warnings.append(f"планер {ac.icao}: {ac.frame_source} — расчёт "
                        f"выполнимости опирается не на справочник")
    # Ярус 2: точки эксплуатанта из домена `fuel_burn`, ключ
    # `<перевозчик>/<тип>/<блок-часы>` → блок-топливо в кг. Читаются
    # раньше физики: измерение на своём борту точнее расчёта по обобщённой
    # поляре, и порядок обязан это отражать.
    burn = None
    pts = [(float(k.rsplit("/", 1)[1]), float(v["value"]))
           for k, v in (store.current("fuel_burn", as_of) or {}).items()
           if k.split("/")[:2] in ([operator, ac.icao], ["*", ac.icao])]
    if pts:
        burn = fit_burn(pts, source=f"{operator}/{ac.icao}")
        rec(G3, "Расход: точки эксплуатанта",
            "подбор почасовой и поцикловой частей по названным плечам",
            f"{burn.per_h:,.0f} кг/ч + {burn.per_cycle:,.0f} кг/цикл",
            float(burn.points), "точек", "stated", burn.note, node="d_fuel_burn")
        if burn.structure != "measured":
            warnings.append(f"расход {ac.icao}: {burn.note}")
    fr = trip_fuel(ac.icao, dist, pax_pre, spec=spec, frame=ac.frame, burn=burn,
                   ref=ac.burn_ref,
                   fallback_kg_per_h=ac.fuel_kg_per_h, cruise_kt=ac.cruise_kt)
    # ТОЛЬКО рейсовое. Запас возится и возвращается, в стоимость топлива
    # не входит; его вес уже удорожил рейсовое через взлётную массу.
    fuel_kg, block_h = fr.trip_kg, fr.block_h
    prov_fuel = "derived" if fr.method == "openap" else "default"
    if fr.method != "openap":
        warnings.append(fr.note)
    # Выполнимость решает, будет ли ответ вообще, и до сих пор жила вне
    # трассировки: узел `v_feas` на карте есть, шага не было ни одного.
    # Решение 45 требует, чтобы «нельзя» было ОТВЕТОМ модели, а не
    # отсутствием ответа плюс строкой в списке из девяти предупреждений.
    #
    # Шаг ставится всегда, а не только при отказе: запас до предела —
    # такая же величина, как сам предел, и на выполнимом рейсе он
    # единственное, что говорит, насколько близко мы к границе.
    rec(G3, "Ярус расхода", "чем получен расход",
        {0: "плоская ставка, параметрика", 1: "физика openap",
         2: "точки эксплуатанта", 3: "по сертифицированному CO2",
         4: "от аналога с якорем"}[fr.tier]
        + (f" — {fr.tier_note}" if fr.tier_note else ""),
        float(fr.tier), "ярус", "derived" if fr.tier == 1 else "stated",
        "ярус ниже первого допустим только объявленным (решение 94)",
        node="v_tier")
    rec(G3, "Запас топлива",
        "непредвиденный расход + конечный остаток + уход на запасной",
        " + ".join(f"{k.lower()} {v:,.0f}" for k, v in fr.reserve_parts.items()
                   if v) or "не посчитан",
        fr.reserve_kg, "кг", spec.provenance,
        ("возится, не сжигается: в статью топлива не входит, во взлётную "
         "массу входит" + ("" if alternate_nm else
          "; ЗАПАСНОЙ НЕ НАЗВАН — уход не посчитан, предельная нагрузка "
          "завышена примерно на тонну")),
        node="v_reserve")
    if not alternate_nm:
        warnings.append(
            "запасной аэродром не задан (--alternate-nm): в запасе нет "
            "ухода, предельная коммерческая нагрузка завышена")

    _pax_now = ac.seats * load_factor
    feasibility = {"ok": fr.feasible.ok, "max_pax": fr.feasible.max_pax,
                   "pax": _pax_now, "limits": list(fr.feasible.limits)}
    rec(G3, "Выполнимость", "предельная коммерческая загрузка на это плечо",
        (f"{fr.feasible.max_pax} пасс при {_pax_now:.0f} на борту, запас "
         f"{fr.feasible.max_pax - _pax_now:+.0f}") if fr.feasible.ok else
        "; ".join(f"{l['key']}: {l['text']}" for l in fr.feasible.limits),
        float(fr.feasible.max_pax), "пасс", "derived",
        ("предел не достигнут" if fr.feasible.ok else
         "упёрлись в: " + ", ".join(l["key"] for l in fr.feasible.limits)),
        node="v_feas")
    if not fr.feasible.ok:
        for why in fr.feasible.reasons:
            warnings.append("РЕЙС НЕВЫПОЛНИМ: " + why)

    for ph, kg in fr.phases.items():
        t = fr.times[ph]
        rec(G3, f"Топливо: {ph}", "расход фазы · время фазы",
            (f"{kg/t:.0f} кг/ч · {t*60:.0f} мин" if t > 1e-6 else "фаза отсутствует"),
            kg, "кг", prov_fuel, node="v_prof")
    rec(G3, "Рейсовое топливо", "Σ по фазам" if fr.phases else "q · T_block",
        fr.note, fuel_kg, "кг", prov_fuel,
        f"метод: {fr.method}" + (f", взлётная масса {fr.takeoff_mass_kg/1000:.1f} т"
                                 if fr.takeoff_mass_kg else ""), node="v_fuel")
    rec(G2, "Блок-время", "набор + крейсер + снижение + руление"
        if fr.method == "openap" else "0.33 + D / V · 1.06",
        " + ".join(f"{v*60:.0f}" for v in fr.times.values()) + " мин"
        if fr.times else f"0.33 + {dist:.0f} / {ac.cruise_kt} · 1.06",
        block_h, "ч", prov_fuel,
        "из профиля полёта, а не из плоской ставки" if fr.method == "openap"
        else "плоская оценка", node="v_block")

    fuel_prov, fuel_src = "input", "задана ключом --fuel"
    if fuel_eur_per_kg is None:
        # Цена собирается из трёх величин, и ни одна не константа в коде.
        # Прежний вариант делил на литры в БАРРЕЛЕ и на плотность 0,8, а
        # курс не применял вовсе: при котировке EIA в долларах за ГАЛЛОН
        # это ошибка примерно в сорок два раза плюс отсутствующий перевод
        # в евро — и всё это молча (решение 22: ставка хранится как
        # опубликована, пересчёт делает расчёт).
        usd_gal = res_.value("jet_fuel_price", "spot/USGC")
        rho = res_.value("fuel_spec", "density/jet_a1")        # кг/л
        usd_eur = store.value("fx", "USD", as_of)              # долларов за евро
        if usd_gal is None or rho is None or not usd_eur:
            fuel_eur_per_kg, fuel_prov = 0.78, "default"
            missing = [n for n, v in (("котировка", usd_gal), ("плотность", rho),
                                      ("курс USD", usd_eur)) if not v]
            fuel_src = "заглушка в econ.py: нет " + ", ".join(missing)
            warnings.append(
                "нет актуальной цены топлива — взято 0.78 EUR/kg (нет: "
                + ", ".join(missing) + ")")
        else:
            fuel_eur_per_kg = usd_gal / GALLON_L / rho / usd_eur
            fuel_prov = "store"
            fuel_src = (f"EIA spot/USGC {usd_gal:.3f} USD/gal, плотность "
                        f"{rho:.3f} кг/л, курс {usd_eur:.4f} USD/EUR")
            # Спот Мексиканского залива — НЕ цена европейского маршрута и
            # не цена в крыло. Разница к Северо-Западной Европе публикуется
            # по подписке, стоимость заправки — договор перевозчика.
            # 19,1% себестоимости стоят теперь на одном измеренном и одном
            # недостающем слагаемом, и молчать об этом нельзя.
            warnings.append(
                "цена топлива — спот Мексиканского залива без европейского "
                "дифференциала и без стоимости заправки в крыло: занижена "
                "на неизвестную величину")
    rec(G3, "Цена топлива", "из справочника или заглушка",
        f"{fuel_eur_per_kg:.3f}", fuel_eur_per_kg, "EUR/кг", fuel_prov, fuel_src,
        node="v_fprice",
        # Цена стоит на ТРЁХ фактах — котировке, плотности и курсе, — а
        # адрес у шага один. Называем котировку: она меняется ежедневно и
        # спорят обычно о ней. Остальные два видны в подстановке.
        ref="jet_fuel_price/spot/USGC" if fuel_prov == "store" else None)

    # ---------- аэронавигация ----------
    # Сбор берётся за пролёт каждой зоны отдельно, по её собственной
    # ставке и её доле маршрута. До этого считались только государства
    # вылета и прилёта, а транзитные не учитывались вовсе: на FRA-BCN
    # Франция составляет три четверти пути и в счёт не попадала.
    # Полигон EUROCONTROL главнее там, где EUROCONTROL и выставляет счёт;
    # остальной мир — границы сообщества VATSIM (решение 162).
    cross = _crossing_along(legs, billing_zones(store, as_of))
    zones = dict(cross.zones)
    community_nm = (getattr(cross, "by_layer", None) or {}).get("community", 0.0)
    if community_nm > dist * 0.02:
        warnings.append(f"границы зон на {community_nm / dist * 100:.0f}% пути — данные "
                        f"сообщества VATSIM, не официальные: сбор там оценка")
    zones_prov = "store"
    if not zones:
        zones = {a["icao"][:2]: dist / 2, b["icao"][:2]: dist / 2}
        zones_prov = "default"
        warnings.append("границы зон недоступны — сбор посчитан по вылету и "
                        "прилёту пополам, транзитные государства пропущены")

    # Пересечение зон — место, где целое государство пропадает молча: до
    # M6 на FRA-BCN не считалась Франция, а это три четверти пути. Числа
    # были и раньше, но лежали внутри подстановки зонных строк, то есть
    # увидеть их можно было только сложив глазами.
    #
    # Доля важнее миль. Она сразу показывает грубость полигонов вне
    # Европы: на FRA-JNB зона FA покрывает 63% пути, потому что Африка
    # южнее Сахары слита в один полигон. Для сравнения типов это годится,
    # для счёта нет, и человек должен видеть это в разборе, а не в
    # примечании к этапу.
    _share = sorted(zones.items(), key=lambda kv: -kv[1])
    rec(G4, "Пересечённые зоны", "отрезки по 10 миль, середина каждого "
        "относится к зоне",
        ", ".join(f"{z} {nm:.0f} nm ({nm / dist * 100:.0f}%)"
                  for z, nm in _share) or "—",
        float(len(zones)), "зон", zones_prov,
        "доля выше половины на одну зону вне Европы означает грубость "
        "полигона, а не длинный пролёт: границы 2015 года, южнее Сахары "
        "слиты", node="v_cross")

    nav_forms = _nav_formulas()
    nav_cost = 0.0
    su_total = 0.0
    missing: list[str] = []
    # Государства, где ставка зависит от того, КТО летит и КУДА: Россия
    # держит три маршрутных тарифа — внутренний, международный и для
    # иностранных без договоров. Ключ факта <зона>/<operator>/<flight>;
    # эксплуатант — по стране аэропорта вылета (то же умолчание, что у
    # сборов), вид полёта — по паре стран. Зона без вариантов читается
    # по прежнему ключу.
    _home = (cctx.get(a["icao"], {}) or {}).get("operator")
    nav_operator = "national" if _home in (None, "national") else "foreign"
    nav_flight = "domestic" if a["country"] == b["country"] else "international"
    nav_variant = None
    for z, nm in sorted(zones.items(), key=lambda kv: -kv[1]):
        cfg = dict(nav_forms.get(z, {}))
        form = cfg.get("formula", "eurocontrol")
        su_z = (nm * 1.852 / 100.0) * math.sqrt(ac.mtow_t / 50.0)
        su_total += su_z
        if form == "none":
            rec(G4, f"Зона {z}", FORMULA_RU.get(form, cfg.get("note", form)), f"{nm:.0f} nm",
                0.0, "EUR", "store", cfg.get("note", ""), node="v_rate")
            continue
        rate, age = None, None
        rate_cur = "EUR"
        for key in (f"{z}/{nav_operator}/{nav_flight}", z):
            row = store.get("enroute_rate", key, as_of) or \
                store.latest_before("enroute_rate", key, as_of)
            if row is None:
                continue
            rate, age = row["value"], None
            rate_cur = (row["currency"] or "EUR").upper()
            # Форма сбора — в факте, если источник её положил (решение 43):
            # полосы массы и делители приказа ФАС переопределяют config.
            try:
                extra = json.loads(row["value_text"] or "{}")
            except ValueError:
                extra = {}
            if isinstance(extra, dict) and extra.get("bands"):
                cfg.update({k: v for k, v in extra.items()
                            if k in ("d_div", "d_unit", "d_exp", "m_div",
                                     "m_exp", "bands")})
                form = "custom"
            if key != z:
                nav_variant = f"{nav_operator}/{nav_flight}"
            break
        if rate is None:
            missing.append(z)
            continue
        if age:
            warnings.append(f"ставка зоны {z} из истёкшего документа ({age} дн.)")
        amount = nav_charge(nm, ac.mtow_t, rate, form, cfg)
        # Ставка хранится как опубликована (решение 22): рубль здесь, курс —
        # слоями. Без курса статья не молчит, а зовётся пропущенной.
        if rate_cur != "EUR":
            fx_r = store.value("fx", rate_cur, as_of)
            if fx_r is None:
                warnings.append(f"нет курса {rate_cur} для ставки зоны {z} — "
                                f"маршрутный сбор по зоне не начислен")
                missing.append(z)
                continue
            amount = amount / fx_r
        nav_cost += amount
        rec(G4, f"Зона {z}", FORMULA_RU.get(form, cfg.get("note", form)),
            f"{nm:.0f} nm · {rate:,.2f} {rate_cur}"
            + (f" [{nav_variant}]" if nav_variant else ""), amount, "EUR", "store",
            (f"{nm / dist * 100:.0f}% маршрута"
             + (f"; {cfg['note']}" if cfg.get("note") else "")), node="v_rate",
            ref=f"enroute_rate/{z}")
    if cross.unassigned_nm > dist * 0.02:
        warnings.append(f"{cross.unassigned_nm:.0f} nm маршрута вне известных "
                        f"зон — сбор за этот участок не начислен")
    if missing:
        # Пропуск ставки занижает сбор молча. Достраиваем средней по
        # известным зонам этого же маршрута — грубо, но видно.
        # value_with_age, а не value: на стыке месяцев действующего
        # значения нет, и средняя схлопнулась бы к заглушке при том,
        # что настоящие ставки известны.
        known = [store.value_with_age("enroute_rate", z, as_of)[0]
                 for z in zones if z not in missing]
        known = [k for k in known if k]
        avg = sum(known) / len(known) if known else 35.0
        for z in missing:
            c = nav_forms.get(z, {})
            nav_cost += nav_charge(zones[z], ac.mtow_t, avg,
                                   c.get("formula", "eurocontrol"), c)
        warnings.append(f"нет ставок для зон {', '.join(missing)} — взята "
                        f"средняя по маршруту {avg:,.2f} EUR/SU")

    rec(G4, "Единицы обслуживания", "Σ по зонам: (D_км / 100) · √(MTOW / 50)",
        f"{len(zones)} зон, {dist:.0f} nm", su_total, "SU", "derived",
        "формула EUROCONTROL, дистанция считается в каждой зоне отдельно", node="v_su")
    nav_prov = "default" if missing and len(missing) == len(zones) else "derived"

    # Полоса. Оценка потребной длины грубая и помечена как таковая, но
    # грубого хватает: задача — не пустить A388 на полосу в полтора
    # километра, а не заменить расчёт лётных характеристик.
    need_m = required_runway_m(ac.mtow_t)
    for who, ap in (("вылета", a), ("прилёта", b)):
        have = store.value("airport_limits", f"{ap['icao']}/runway_length_m", as_of)
        if have is None:
            continue
        rec(G5, f"Полоса {ap['icao']}", "самая длинная действующая",
            f"нужно около {need_m:,.0f} м", have, "м", "store",
            f"аэродром {who}; запас {have - need_m:+,.0f} м", node="v_rwy")
        if have < need_m:
            # Полоса — третий предел рядом с массой и баками. Раньше он
            # жил только предупреждением, и структура выполнимости о нём
            # не знала.
            feasibility["limits"].append({
                "key": "runway", "airport": ap["icao"],
                "text": (f"полоса {ap['icao']} {have:,.0f} м при "
                         f"ориентировочно потребных {need_m:,.0f} м"),
                "short_m": need_m - have})
            warnings.append(
                f"полоса аэродрома {who} {ap['icao']}: {have:,.0f} м при "
                f"ориентировочно потребных {need_m:,.0f} м для {ac.icao} "
                f"(оценка по массе, не расчёт характеристик)")

    # ---------- аэропорт ----------
    pax = seats * load_factor
    rec(G5, "Пассажиров", "кресла · загрузка",
        f"{seats} · {load_factor}", pax, "чел", "derived", node="v_pax")

    # Сборы аэропорта считаются построчно по правилам из хранилища. Нет
    # правил — ярус 3, грубая параметрика с явной пометкой «оценка».
    #
    # Считаются ОБА конца. Раньше начислялся только аэропорт прилёта, и
    # пассажирский сбор — почти везде он берётся с вылетающего — падал на
    # прилетающих, а тариф аэропорта вылета не участвовал вовсе.
    legs = [(a["icao"], b["icao"]), (b["icao"], a["icao"])]
    apt_lines: dict[str, float] = {}
    charge_gaps: dict[str, dict] = {}
    caveats: dict[str, list] = {}
    currencies_seen: set = {"EUR"}
    # Условия начисления приходят двумя путями: явным аргументом или тем
    # же `--set`, что и переопределения фактов. Разводятся они на входе,
    # чтобы `Resolver` не увидел нечислового значения, а условие не попало
    # в отчёт о неиспользованных ключах: оно не факт, его никто не
    # спрашивает, и предупреждение было бы ложным.
    for icao, vals in parse_context_sets(from_set).items():
        cctx.setdefault(icao, {}).update(vals)
    apt_any = False
    for ap, other in ((a, b), (b, a)):
        load_report: dict = {}
        rules_ = load_rules(store, ap["icao"], as_of, report=load_report)
        for line in load_report.get("broken", []):
            warnings.append(f"{ap['icao']}: факт не стал правилом — {line}")
        if load_report.get("duplicates"):
            # Удвоение суммы — не тот отказ, который можно оставить на
            # добросовестность слоя записи. Чинится закрытием интервалов
            # при записи, но обнаруживается здесь.
            warnings.append(
                f"{ap['icao']}: {len(load_report['duplicates'])} правил "
                f"задвоены — вероятно, старые ключи остались с открытым "
                f"интервалом; статьи начислятся дважды: "
                + "; ".join(load_report["duplicates"][:3])
                + ". Предупреждение до установки retire_missing; после неё "
                  "близнецы могут означать только дефект, и расчёт будет "
                  "отказывать (решения 45 и 80)")
        if not rules_:
            warnings.append(
                f"нет тарифа для {ap['icao']} — сборы по параметрике "
                f"(ярус 3; разброс между режимами регулирования до 20 раз)")
            continue
        apt_any = True
        # Узел карты для каждой статьи берётся у ФАКТА, а не ставится
        # литералом: в день, когда общегосударственные статьи переедут на
        # AIP GEN 4.1, провенанс сменится и узел сменится вместе с ним.
        # Литерал пережил бы перенос и продолжил показывать старый
        # источник — расхождение, которое сверка обязана ловить, а не
        # воспроизводить.
        nodes = rule_nodes(rules_)
        if rules_ and not any(nodes.values()):
            # Колонки узла в схеме `facts` пока нет. Сверка карты назовёт
            # все строки сборов несверенными, и это верно — но без этой
            # строки выглядит как её собственная поломка.
            # Сообщение называло причиной отсутствие КОЛОНКИ, а колонка
            # давно есть: пусто поле `map_node` в самих файлах разбора.
            # Обвинять схему в пробеле данных — учить не верить
            # диагностике.
            warnings.append(
                f"{ap['icao']}: узел карты пуст у всех фактов — источник "
                f"не объявил `node`, а документ не задал `map_node`; "
                f"строки сборов останутся несверенными")
        # Значения условий, заданные слоем сценария по этому аэропорту.
        # Категория шума, класс ВС и группа стоянки — порядковые номера
        # ВНУТРИ аэропорта, в хранилище их нет, и до появления домена
        # пары «аэропорт × тип» их задаёт пользователь. В разборе они
        # видны как «задано пользователем», а не как справочные.
        # Два слоя, порядок неизменен: справочник снизу, сценарий сверху.
        # Пока домена нет, нижний слой пуст и всё приходит из `--set`;
        # когда ветка B его заведёт, записанные сценарии продолжат
        # перебивать справочное значение, а не сломаются (решение 41 —
        # исходное показывается рядом с заданным).
        ref = {}
        for cond in CTX_FROM_STORE:
            v = res_.value(CTX_DOMAIN, f"{ap['icao']}/{ac.icao}/{cond}")
            if v is not None:
                ref[cond] = int(v)
        scenario = dict(cctx.get(ap["icao"], {}))
        given = {**ref, **scenario}
        # Категории типа по правилам документа аэропорта (categories.py):
        # поимённо названный тип, затем правило над свойствами типа, затем
        # умолчание документа. Ниже сценария и ниже прежнего поимённого
        # ключа — те остаются перебивающими слоями.
        from_rules: set = set()
        specs = _cat.load_specs(store, ap["icao"], as_of)
        if specs:
            props = _cat.aircraft_props(store, ac.icao, as_of)
            for cond, spec in sorted(specs.items()):
                if cond in given:
                    continue
                rz = _cat.resolve(cond, spec, props)
                if rz.value is None:
                    warnings.append(
                        f"{ap['icao']}: категория {cond} для {ac.icao} не "
                        f"определена — {rz.note or 'ни одно правило не подошло'}")
                    continue
                given[cond] = rz.value
                from_rules.add(cond)
                prov = {"named": "store", "rule": "derived",
                        "default": "default"}[rz.how]
                basis = {"named": "названа документом",
                         "rule": "правило документа по свойствам типа",
                         "default": "умолчание документа"}[rz.how]
                used = ", ".join(sorted(k for k in props.get("_derived", [])
                                        if any(k in (r.get("when") or {})
                                               for r in spec.get("rules") or [])))
                rec(G5, f"Условие {ap['icao']}: {cond}",
                    f"категории типов {ap['icao']}: {basis}",
                    f"{rz.value} — {rz.note}"
                    + (f" (выведено: {used})" if used else ""),
                    0.0, "", prov,
                    "порядковый номер внутри этого аэропорта, не сквозная шкала",
                    node="i_charge_ctx")
                if rz.disagree:
                    warnings.append(f"{ap['icao']}: {cond} {ac.icao}: {rz.disagree}")
        # --- умолчания входов, названные вслух (не тихие) -------------
        # `operator`: свой или иностранный эксплуатант — свойство рейса,
        # и его знает пользователь, а не справочник. Но без него у
        # Шереметьево не начислялась НИ ОДНА статья, включая посадочную,
        # которая от терминала не зависит. Умолчание: эксплуатант из
        # страны аэропорта ВЫЛЕТА — маршрут чаще всего моделируется от
        # базы. Показывается как `default`, задаётся
        # --set charge_context.<ИКАО>.operator=national|foreign.
        uses = {k for r in rules_ for k in r.when}
        if "operator" in uses and "operator" not in given:
            given["operator"] = ("national" if ap["country"] == a["country"]
                                 else "foreign")
            rec(G5, f"Условие {ap['icao']}: operator",
                "не задано → по стране аэропорта вылета",
                f"{given['operator']} (страна эксплуатанта = {a['country']})",
                0.0, "", "default",
                "свойство рейса; задать --set charge_context."
                f"{ap['icao']}.operator=national|foreign",
                node="i_charge_ctx")
        # `terminal`: к какому терминалу встанет борт, на этапе
        # планирования неизвестно. Умолчание — САМЫЙ ДОРОГОЙ из терминалов,
        # названных в тарифе: оценка сверху, а не снизу, и она названа.
        if "terminal" in uses and "terminal" not in given:
            cands = sorted({v for r in rules_ if "terminal" in r.when
                            for v in (r.when["terminal"] if isinstance(
                                r.when["terminal"], list) else [r.when["terminal"]])})
            best, best_sum = None, -1.0
            for t in cands:
                probe = charge_context(ap, other, ac, pax=pax_pre, month=month,
                                       events=rotation_events(ap["icao"], legs),
                                       **{**given, "terminal": t})
                tot = sum(v for k, v in evaluate(
                    rules_, probe, fx=lambda cur: store.value("fx", cur, as_of)
                    ).items() if not k.startswith("_"))
                if tot > best_sum:
                    best, best_sum = t, tot
            if best is not None:
                given["terminal"] = best
                rec(G5, f"Условие {ap['icao']}: terminal",
                    "не задано → самый дорогой из тарифа",
                    f"{best} (из {', '.join(cands)})", 0.0, "", "default",
                    "оценка сверху; задать --set charge_context."
                    f"{ap['icao']}.terminal=<буква>", node="i_charge_ctx")
        ctx = charge_context(ap, other, ac, pax=pax_pre, month=month,
                             events=rotation_events(ap["icao"], legs),
                             **given)
        for k, v in sorted(given.items()):
            if k in ("operator", "terminal") and k not in scenario \
                    and k not in ref:
                continue                      # уже записано как умолчание
            if k in from_rules:
                continue                      # уже записано с правилом
            from_set = k in scenario
            was = ref.get(k)
            rec(G5, f"Условие {ap['icao']}: {k}",
                "задано ключом --set" if from_set else
                f"{CTX_DOMAIN}/{ap['icao']}/{ac.icao}/{k}",
                f"{was} → {v}" if from_set and was is not None else f"{v}",
                0.0, "", "input" if from_set else "store",
                "порядковый номер внутри этого аэропорта, не сквозная шкала",
                node="i_charge_ctx")
        report: dict = {}
        lines = evaluate(rules_, ctx, report=report,
                         fx=lambda cur: store.value("fx", cur, as_of))
        charge_gaps[ap["icao"]] = report
        # По сработавшим правилам и по тому же контексту, что и начисление:
        # оговорка о правиле, которое не применилось, — шум, растущий с
        # объёмом хранилища.
        caveats[ap["icao"]] = charge_caveats(rules_, ctx)
        currencies_seen.update(report.get("currencies", []))
        # Курс, по которому строки тарифа в чужой валюте стали евро, —
        # величина, на которую опирается ответ, значит шаг (решение 82).
        # Пересчёт шёл внутри `evaluate` молча: пока курса не было, это
        # давало предупреждение; когда курс появился, пропало и оно, и
        # спорные ставки Алматы пересчитывались по числу, которого нет
        # в разборе.
        for cur in sorted(set(report.get("currencies", [])) - {"EUR"}):
            row = store.get("fx", cur, as_of)
            if row is None or not row["value"]:
                continue
            rec(G5, f"Курс {cur} для {ap['icao']}",
                f"домен fx, котировка на {row['valid_from']}",
                f"{row['value']:,.4f} {cur} за 1 EUR",
                float(row["value"]), f"{cur}/EUR", "store",
                f"источник {row['source_id']}; берётся последняя котировка "
                f"на дату расчёта (решение 23)",
                node="d_fx")
        if report.get("lost_codes"):
            rec(G5, f"Полнота начисления {ap['icao']}",
                "статей с ценой из статей тарифа",
                f"{len(report['priced_codes'])} из {report['total_codes']}, "
                f"без цены: {', '.join(report['lost_codes'])}",
                float(len(report["lost_codes"])), "статей", "derived",
                # Кому адресован пропуск. Свалить в одну строку значило бы
                # предложить пользователю ввести класс ВС, которого он не
                # знает, или винить справочник в незаданном перроне.
                "; ".join(filter(None, [
                    (f"нет справочных значений: "
                     f"{', '.join(report['missing_data'])} — вопрос к полноте "
                     f"домена {CTX_DOMAIN}, до его появления задаётся через "
                     f"--set charge_context.{ap['icao']}.<условие>")
                    if report.get("missing_data") else "",
                    (f"не задано: {', '.join(report['missing_input'])} — "
                     f"свойство рейса, справочного значения не существует: "
                     f"--set charge_context.{ap['icao']}.<условие>=<значение>")
                    if report.get("missing_input") else "",
                    (f"ДЕФЕКТ РАСЧЁТА: {', '.join(report['missing_derived'])} "
                     f"выводится моделью и не должно отсутствовать")
                    if report.get("missing_derived") else "",
                ])),
                node="d_charge")
        for code, amount in sorted(lines.items(), key=lambda kv: -kv[1]):
            if code.startswith("_"):
                warnings.append(f"{ap['icao']}: {code[1:]}")
                continue
            apt_lines[f"{ap['icao']}/{code}"] = amount
            rec(G5, f"Сбор {ap['icao']}: {CODE_RU.get(code, code)}",
                f"правило airport_charge/{ap['icao']}/{code}", "",
                amount, "EUR", "store", "ярус 1, разобранный тариф",
                # Пусто, если правила одного кода приехали из разных
                # источников: сверка назовёт шаг несверенным, а выбор
                # одного из двух наугад промолчал бы.
                node=nodes.get(code) or "",
                # Одна статья складывается из НЕСКОЛЬКИХ правил: у
                # Франкфурта пассажирский сбор это четыре строки по
                # направлениям. Поэтому адрес указывает на код, а не на
                # конкретный факт: `airport_charge/EDDF/passenger`. Панель
                # раскроет его в перечень правил — по-другому и не надо,
                # спорят обычно не с одной строкой, а с трактовкой статьи.
                ref=f"airport_charge/{ap['icao']}/{code}")

    # ---------- статьи затрат ----------
    cost, prov = {}, {}

    def item(name, value, p, formula, subst, src="", *, node, ref=None):
        # Ключ и ПОДПИСЬ — разные вещи (решение 27). `name` английский:
        # он идентификатор статьи, годится в поле формы и не переводится.
        # В трассировку идёт подпись из `COST_RU`, иначе в русском разборе
        # посреди строк появляются `ownership` и `ground_handling`.
        cost[name] = value
        prov[name] = p
        rec("Статьи затрат", COST_RU.get(name, name), formula, subst, value,
            "EUR", p, src, node=node, ref=ref)

    item("fuel", fuel_kg * fuel_eur_per_kg,
         "default" if fuel_prov == "default" else "derived",
         "масса · цена", f"{fuel_kg:.0f} · {fuel_eur_per_kg:.3f}", node="c_fuel")
    item("enroute", nav_cost, nav_prov, "Σ по зонам маршрута",
         "  ".join(f"{z} {nm:.0f}nm" for z, nm in
                   sorted(zones.items(), key=lambda kv: -kv[1])), node="c_nav")
    # ОБОРОТ = ДВА РЕЙСА. Сборы считаются по обороту: `legs` — туда и
    # обратно, и каждый конец видит прилёт и вылет. Это верно — так и
    # выставляют счёт аэропорты, и минимумы со ступенями стоянки иначе не
    # посчитать. Но всё остальное здесь — на РЕЙС: топливо, аэронавигация,
    # блок-время, и выручка — пассажиры этого рейса на чек. Оборот целиком
    # в статье «за рейс» удваивал сборы: пассажирский сбор Барселоны брался
    # с вылетающих оттуда, то есть с пассажиров обратного рейса, а платили
    # за него пассажиры прямого. На FRA–BCN это было +4,7 тыс. EUR и
    # +34 EUR к безубыточному чеку. Строки по аэропортам остаются за
    # оборот — они сверяются с калькулятором аэропорта (эталон Франкфурта);
    # делится только сумма, и делится явно. Допущение: обратный рейс с той
    # же загрузкой — то же, что и у топлива.
    if apt_any:
        rot = sum(apt_lines.values())
        item("airport_charges",
             rot / LEGS_PER_ROTATION,
             "derived", "Σ строк тарифа обоих аэропортов за оборот ÷ 2 рейса",
             f"{len(apt_lines)} статей; оборот {rot:,.0f} EUR ÷ {LEGS_PER_ROTATION}",
             node="c_apt")
    else:
        item("airport_charges", 9.5 * ac.mtow_t + 11.0 * pax, "default",
             "тариф · MTOW + сбор · пассажиры",
             f"9.5 · {ac.mtow_t} + 11.0 · {pax:.0f}",
             "обе константы выдуманы, см. предупреждение выше", node="c_apt")
    # Терминальный сбор аэронавигации. Отдельно от аэропортовых сборов:
    # это плата за диспетчерское обслуживание захода и в районе аэродрома,
    # взимает провайдер аэронавигации, а не оператор аэропорта. Начисляется
    # НА ОБОИХ КОНЦАХ оборота — прежде считался только аэропорт прилёта, и
    # Франкфурт на FRA–BCN не платил вовсе. Форма — из факта: у EUROCONTROL
    # (MTOW/50)^0,7 за вылет, у России — за тонну МВМ по аэродрому, ставка
    # своя у российских и иностранных эксплуатантов.
    term_cost, term_prov, term_parts = 0.0, "derived", []
    _tcz = _tcz_map()
    for ap_t in (a, b):
        icao_t = ap_t["icao"]
        op_t = (cctx.get(icao_t, {}) or {}).get("operator") or (
            "national" if ap_t["country"] == a["country"] else "foreign")
        zone_t = _tcz.get(icao_t)
        row = None
        for key in (f"{icao_t}/{op_t}", icao_t, zone_t):
            if not key:
                continue
            row = store.get("terminal_rate", key, as_of) or \
                store.latest_before("terminal_rate", key, as_of)
            if row is not None:
                zone_t = key
                break
        if row is None:
            term_prov = "default"
            warnings.append(
                f"{icao_t}: терминальный сбор не начислен — "
                + (f"зона {zone_t} известна, ставки в справочнике нет"
                   if zone_t else "аэродром не отнесён ни к зоне TCZ, ни к "
                   "справочнику терминальных ставок (config/tcz.yaml, "
                   "источник fas_ans_rates)"))
            continue
        try:
            prm = json.loads(row["value_text"] or "{}")
        except ValueError:
            prm = {}
        if not isinstance(prm, dict):
            prm = {}
        m_div, m_exp = float(prm.get("m_div", 50.0)), float(prm.get("m_exp", 0.70))
        units = (ac.mtow_t / m_div) ** m_exp if m_exp else 1.0
        rate, cur = row["value"], (row["currency"] or "EUR").upper()
        fx = 1.0 if cur == "EUR" else store.value("fx", cur, as_of)
        if fx is None:
            term_prov = "default"
            warnings.append(f"нет курса {cur} для терминальной ставки {zone_t} — "
                            f"сбор в {icao_t} не начислен")
            continue
        amount = rate * units / fx
        term_cost += amount
        term_parts.append(f"{icao_t} {amount:,.0f}")
        rec(G4, f"Терминальные единицы {icao_t}",
            f"(MTOW / {m_div:g}) ^ {m_exp:g}", f"({ac.mtow_t} / {m_div:g}) ^ {m_exp:g}",
            units, "SU" if m_exp != 1 else "т", "derived",
            "показатель 0,7 у EUROCONTROL; за тонну — у России" if m_exp == 1
            else "дистанция не участвует", node="v_tsu")
        rec(G4, f"Терминальная ставка ({zone_t})", "справочник terminal_rate",
            f"{rate:,.2f} {cur}" + ("" if cur == "EUR" else f" / {fx}"),
            rate, cur, "store", "публикация регулятора или EUROCONTROL",
            node="d_terminal", ref=f"terminal_rate/{zone_t}")
    term_su = (ac.mtow_t / 50.0) ** 0.70
    tcz = ", ".join(term_parts) if term_parts else None
    # Терминальный сбор берётся за ВЫЛЕТ: у Франкфурта — с этого рейса, у
    # Барселоны — с обратного. Сумма двух концов — оборот; на рейс половина,
    # по той же причине и с тем же допущением, что у аэропортовых сборов.
    item("terminal", term_cost / LEGS_PER_ROTATION, term_prov,
         "Σ по концам оборота ÷ 2 рейса: единицы · ставка аэродрома или зоны",
         (f"{tcz}; оборот {term_cost:,.0f} EUR ÷ {LEGS_PER_ROTATION}" if tcz
          else "не начислен ни на одном конце"), node="c_term")

    # Экономика эксплуатации: раскладка на почасовую и поцикловую части,
    # владение через месячный налёт борта. Прежние плоские ставки были неверны
    # не только величиной, но и формой — цикловые статьи не зависят от
    # длительности рейса, и плоская ставка занижала короткие плечи.
    fe = load_fleet(res_, ac.icao, operator=operator,
                    mtow_t=ac.mtow_t, seats=seats)
    fe_prov = {"store": "store", "mixed": "override"}.get(fe.provenance, "default")
    if fe_prov == "default":
        warnings.append("ставки владения, ТОиР и экипажа — параметрическая "
                        "заготовка, а не данные: подставь свои через --set")
    RU_MODE = {"fleet_average": "типовой по флоту",
               "dedicated": "из частоты рейсов",
               "marginal": "борт уже оплачен"}
    hours, why = fe.monthly_hours_for(block_h, freq_week, util_mode)
    rec(G6, f"Налёт ({RU_MODE[util_mode]})", "часов в месяц на борт", why,
        hours, "ч/мес", "input" if util_mode == "dedicated" else fe_prov,
        "типовой по флоту — борт летает и на других линиях; из частоты — "
        "маршруту нужен свой борт; борт уже оплачен — владение не начисляется", node="v_util")
    rec(G6, "Ставка лизинга", "за месяц", f"{fe.lease_eur_month:,.0f}",
        fe.lease_eur_month, "EUR/мес", fe_prov, node="d_fleet",
        # Адрес есть, ТОЛЬКО если значение пришло из хранилища. У
        # заготовки его нет и быть не может: в `facts` она не лежит,
        # и подставить сюда правдоподобный ключ значило бы обещать
        # запись, которой нет, — панель открылась бы с «ключа нет».
        ref=(f"fleet_economics/{operator}/{ac.icao}/lease_eur_month"
             if fe_prov == "store" else None))
    eff_m = fe.effective_maint_per_h(block_h)
    eff_c = fe.effective_crew_per_h(block_h)
    rec(G6, "Ставка ТОиР", "полная, на блок-час при этом плече",
        f"(почасовая {fe.maint_eur_per_fh:,.0f} EUR/ч · {block_h:.2f} ч + "
        f"поцикловая {fe.maint_eur_per_fc:,.0f} EUR/рейс) / {block_h:.2f} ч",
        eff_m, "EUR/ч", fe_prov,
        f"складывается из {fe.maint_eur_per_fh:,.0f} EUR за час налёта "
        f"(двигатели, тяжёлые формы, пул компонентов) и "
        f"{fe.maint_eur_per_fc:,.0f} EUR за рейс (шасси, ВСУ, ресурсные "
        f"детали, линейное обслуживание). Вторая часть от длительности "
        f"рейса не зависит, поэтому ставка на час падает с ростом плеча",
        node="v_maint_rate",
        ref=(f"fleet_economics/{operator}/{ac.icao}/maint_eur_per_fh"
             if fe_prov == "store" else None))
    rec(G6, "Ставка экипажа", "полная, на блок-час при этом плече",
        f"(почасовая {fe.crew_eur_per_fh:,.0f} EUR/ч · {block_h:.2f} ч + "
        f"поцикловая {fe.crew_eur_per_fc:,.0f} EUR/рейс) / {block_h:.2f} ч",
        eff_c, "EUR/ч", fe_prov,
        f"{fe.crew_eur_per_fh:,.0f} EUR за час плюс {fe.crew_eur_per_fc:,.0f} "
        f"за вылет: брифинг, пред- и послеполётная работа", node="v_crew_rate")

    parts = fe.per_flight(block_h, freq_week, util_mode)
    item("ownership", parts["ownership"], fe_prov,
         "месячный платёж · блок-время / налёт"
         if util_mode != "marginal" else "не начисляется: борт уже оплачен",
         f"{fe.lease_eur_month:,.0f} · {block_h:.2f} / {hours:.0f}"
         if util_mode != "marginal" else "", node="c_own")
    item("maintenance", parts["maintenance"], fe_prov,
         "за час · блок-время + за цикл",
         f"{fe.maint_eur_per_fh:,.0f} · {block_h:.2f} + {fe.maint_eur_per_fc:,.0f}", node="c_mnt")
    item("crew", parts["crew"], fe_prov,
         "за час · блок-время + за цикл",
         f"{fe.crew_eur_per_fh:,.0f} · {block_h:.2f} + {fe.crew_eur_per_fc:,.0f}", node="c_crew")
    item("ground_handling", 900.0 + 2.2 * pax, "default",
         "постоянная + переменная на пассажира",
         f"900 + 2.2 · {pax:.0f}", "обе константы выдуманы, кандидат №1 на замену", node="c_grnd")

    base = sum(cost.values())
    dist_rate = 0.07
    be_fare = base / max(pax, 1e-9) / (1 - dist_rate)
    item("distribution", be_fare * pax * dist_rate, "default",
         "выручка · 7%", f"{be_fare:.0f} · {pax:.0f} · 0.07",
         "7% — типичная величина для LCC, не проверена", node="c_dist")

    rec("Безубыточность", "Сумма без дистрибуции", "Σ статей", "", base, "EUR", "derived", node="t_base")
    rec("Безубыточность", "Безубыточный тариф", "База / пасс / (1 − 0.07)",
        f"{base:.0f} / {pax:.0f} / 0.93", be_fare, "EUR/пасс", "derived",
        "деление на (1−0.07) потому, что комиссия берётся с выручки, а не с затрат", node="t_fare")

    be_lf = None
    if fare_eur:
        net = fare_eur * (1 - dist_rate)
        be_lf = base / (net * seats)
        rec("Безубыточность", "Безубыточная загрузка", "База / (тариф · 0.93 · кресла)",
            f"{base:.0f} / ({fare_eur} · 0.93 · {seats})", be_lf, "доля", "derived", node="t_lf")

    res = Result(origin.upper(), destination.upper(), ac.icao, dist, block_h,
                 fuel_kg, cost, be_fare, be_lf, warnings=warnings,
                 trace=trace, cost_prov=prov,
                 inputs={"load_factor": load_factor, "fare_eur": fare_eur,
                         "seats": seats, "as_of": as_of, "pax": pax,
                         "origin_name": a["name"], "dest_name": b["name"],
                         "origin_icao": a["icao"], "dest_icao": b["icao"],
                         "month": month, "charge_ctx": cctx,
                         "via": [list(w) for w in (via or [])]},
                 charge_gaps=charge_gaps, charge_lines=apt_lines,
                 feasibility=feasibility, caveats=caveats,
                 currencies_seen=currencies_seen)

    # Слой сценария: что подменили и что задали впустую
    for x in res_.applied():
        was = f"{x['was']:,.2f}" if x["was"] is not None else "не было"
        res.warnings.append(f"задано вручную {x['path']}: {was} → {x['now']:,.2f}")
    for k in res_.unused():
        res.warnings.append(f"ключ {k} задан, но в расчёте не используется — "
                            f"проверь написание")
    res.overrides = res_.applied()

    res.feasible = fr.feasible.ok
    res.max_pax = fr.feasible.max_pax

    # Отказ без цены — половина ответа. Если рейс не выполним, считаем
    # его же с той загрузкой, которая выполнима, и показываем, во что
    # обходится компромисс: сколько пассажиров снять, сколько выручки
    # потерять и какой тариф после этого нужен для безубыточности.
    if _trade and not fr.feasible.ok and fr.feasible.max_pax > 0:
        lf_ok = fr.feasible.max_pax / seats
        alt = route_economics(
            store, origin, destination, aircraft=aircraft, as_of=as_of,
            load_factor=lf_ok, fare_eur=fare_eur, fuel_eur_per_kg=fuel_eur_per_kg,
            operator=operator, freq_week=freq_week, util_mode=util_mode,
            month=month, charge_ctx=cctx, overrides=overrides, seats=seats_given,
            via=via, _trade=False)
        if alt.feasible:
            lost = int(round(pax)) - fr.feasible.max_pax
            res.trade = {
                "pax_drop": lost,
                "pax_ok": fr.feasible.max_pax,
                "lf_ok": lf_ok,
                "revenue_loss": lost * (fare_eur or 0.0),
                "breakeven_before": res.breakeven_fare_eur,
                "breakeven_after": alt.breakeven_fare_eur,
                "cost_after": alt.cost_total,
            }
    if freshness:
        # Три состояния, а не два (решение 67). «Протух» — данные были и
        # устарели: ответ опирается на старое, это деградация. «Не
        # подключён» — источник не собирался ни разу: у новой копии это
        # наблюдения OpenSky, цены агрегатора, свои типы — то, что требует
        # своих ключей или файлов. Прежде оба шли одной строкой «протухшие»
        # и делали ответ деградированным: свежая копия навсегда получала
        # код возврата 2 из-за ключа, которого у человека может и не быть.
        stale = [f["source"] for f in freshness if f["state"] == "stale"]
        never = [f["source"] for f in freshness if f["state"] == "never"]
        if stale:
            res.degraded = True
            res.warnings.append("протухшие источники: " + ", ".join(stale))
        if never:
            res.warnings.append(
                "не подключены (ни разу не собирались): " + ", ".join(never)
                + " — им нужны свои ключи или файлы; что даёт каждый, покажет fca status")
    return res
