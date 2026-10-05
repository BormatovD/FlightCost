"""Вычислитель аэропортовых сборов.

Правила НЕ живут в коде. Здесь только механика: восемь баз начисления и
четыре типа модификаторов, которых хватило на шесть аэропортов из трёх
режимов регулирования — Испания, Австрия, Германия, Казахстан, Катар.

Сами ставки приезжают из домена `airport_charge` хранилища, где каждая
строка тарифа лежит отдельным фактом: числовая ставка в поле value (её
проверяют валидаторы гейта), остальное описание правила — в value_text.
Так ставка остаётся под контролем гейта, а условия применения едут вместе
с ней и не требуют отдельной таблицы.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, asdict

# ---------- базы начисления ----------
# Русские подписи баз для разбора. Коды остаются английскими по решению 27.
#
# Отдельно про turnaround: это ОДНО обслуживание борта в аэропорту —
# прилёт плюс вылет, — а не рейс туда-обратно. Русское «оборот» в
# разговоре чаще означает второе, поэтому здесь оно не используется.
BASE_RU = {
    "per_turnaround":    "за обслуживание (прилёт + вылет)",
    "per_movement":      "за движение (отдельно посадка и взлёт)",
    "per_tonne_mtow":    "за тонну максимальной взлётной массы",
    "per_tonne_above":   "за тонну массы сверх порога полосы",
    "per_departing_pax": "за вылетающего пассажира",
    "per_100kg":         "за 100 кг груза и почты",
    "per_hour":          "за час стоянки",
    "per_15min":         "за 15 минут стоянки",
    "per_hour_above":    "за час стоянки сверх порога",
    "per_tonne_hour_above": "за тонну массы за час стоянки сверх порога",
    "per_day":           "за сутки стоянки",
    "per_day_above":     "за сутки стоянки сверх порога",
    "per_pax_per_movement": "за пассажира при посадке и при взлёте",
    "per_service_unit":  "за единицу обслуживания",
}
# Подписи кодов статей. Код остаётся английским и идентификатором
# (решение 27), а в разборе стоит подпись: строка «Сбор EDDF: gh_infra_pax»
# посреди русского текста требует знания нашего же словаря.
#
# Словарь НЕПОЛОН намеренно и полным не станет: коды приходят из тарифных
# документов, и новый аэропорт может завести свой. Незнакомый код
# показывается как есть — это честнее выдуманного перевода, и заодно
# видно, что статью стоит подписать.
CODE_RU = {
    "landing":        "посадка",
    "landing_pax":    "посадка, пассажирская часть",
    "landing_invest": "посадка, инвестиционная составляющая",
    "landing_night":  "посадка, ночная надбавка",
    "pbb":            "телетрап",
    "bhs":            "багажная система",
    "passenger":      "пассажирский сбор",
    "security":       "авиационная безопасность",
    "prm":            "маломобильные пассажиры",
    "noise":          "шум",
    "noise_program":  "программа снижения шума",
    "parking":        "стоянка",
    "parking_pier":   "стоянка у телетрапа",
    "gh_infra":       "инфраструктура наземного обслуживания",
    "gh_infra_pax":   "инфраструктура, пассажирская часть",
    "gh_infra_dg":    "инфраструктура, опасные грузы",
    "aerodrome":      "аэродромное обеспечение",
    "meteo":          "метеообеспечение",
    "border":         "пограничный контроль",
    "demand":         "сбор за спрос",
    "municipal_tax":  "муниципальная надбавка",
    "terminal":       "терминальный сбор",
    "emission":       "выбросы",
    "lighting":       "светотехническое обеспечение",
    "boarding_bridge": "телетрап",
    "de_icing":       "противообледенительная обработка",
    "fuel_infra":     "инфраструктура заправки",
    "cargo":          "грузовой сбор",
    "transfer":       "трансферные пассажиры",
}

EVENT_RU = {
    "movement":   "отдельно за посадку и за взлёт",
    "landing":    "один раз за посадку",
    "takeoff":    "один раз за взлёт",
    "turnaround": "один раз за обслуживание борта",
}

# Счётчики событий в ОДНОМ аэропорту за одну единицу расчёта. Раньше
# движений было жёстко одно, и при n = 1 признак начисления не различал
# ничего: `movement`, `landing` и `turnaround` давали один и тот же
# множитель. Защита от самой частой ошибки разбора лежала без применения
# и проявилась бы разом на всех аэропортах в день, когда число изменится.
#
# За оборот каждый конец маршрута видит один прилёт и один вылет: два
# движения, одну посадку, одно обслуживание, один вылет с пассажирами.
# Значения здесь — умолчания; расчёт подаёт свои, выведенные из плеч.
EVENT_COUNTS = {"movements": 2, "landings": 1, "turnarounds": 1,
                "departures": 1}

BASES = {
    "per_turnaround":    lambda c, r: 1.0,
    "per_movement":      lambda c, r: c["n"],
    "per_tonne_mtow":    lambda c, r: c["mtow_t"] * c["n"],
    # Накопительная полоса: платится за тонны СВЕРХ её нижней границы, а
    # предыдущие полосы оплачены своими строками. Симметрична
    # `per_hour_above` и пользуется тем же полем `threshold`.
    #
    # Обходилось разложением на ставку за тонну плюс постоянный член со
    # знаком: на Порту 8,93 × 78 − 136,00. Арифметика верна, но её
    # повторяет агент, и ошибка в знаке даёт правдоподобный результат.
    "per_tonne_above":   lambda c, r: max(0.0, c["mtow_t"] - r.threshold) * c["n"],
    "per_departing_pax": lambda c, r: c["pax"] * c["departures"],
    "per_100kg":         lambda c, r: math.ceil(c["cargo_kg"] / 100) * c["n"],
    "per_hour":          lambda c, r: math.ceil(c["park_h"]),
    "per_15min":         lambda c, r: math.ceil(c["park_h"] * 4),
    # показатель степени задаётся строкой правила: 0.5 у en-route,
    # 0.70 у терминальных сборов в схеме SES. Дефолта тут быть не должно.
    "per_service_unit":  lambda c, r: (c["mtow_t"] / 50.0) ** r.exponent,
    # Ступенчатая стоянка: базовый сбор покрывает первые threshold часов,
    # эта база считает только часы сверх порога. Встретилась во Франкфурте
    # (43.33 за первые 3 часа, дальше 63.63 за каждый начатый час).
    "per_hour_above":    lambda c, r: max(0, math.ceil(c["park_h"] - r.threshold)),
    # Шереметьево: стоянка иностранных пользователей — «за 1 сутки», а
    # российских — «за 1 час». Одна статья, две единицы времени.
    "per_day":           lambda c, r: math.ceil(c["park_h"] / 24.0),
    # Аэровокзальный сбор в России берётся с прибывающих, убывающих и
    # транзитных: оборот платит за пассажира дважды. `per_departing_pax`
    # дал бы половину и выглядел бы обеспеченным документом.
    "per_pax_per_movement": lambda c, r: c["pax"] * c["n"],
    # Нарита: стоянка «за каждые 24 часа сверх первых шести, неполные —
    # как полные». Сутки считаются от порога, а не от посадки.
    "per_day_above":     lambda c, r: max(0, math.ceil(
                             max(0.0, c["park_h"] - r.threshold) / 24.0)),
    # Индия (ордера AERA): стоянка «в рупиях за тонну МВМ за час», первые
    # два часа бесплатно, начатый час — как полный. Обходилось бы
    # разложением «ставка × масса» в само число ставки, но тогда правило
    # держит массу эталонного типа и врёт на любом другом. Масса
    # округляется полем `round_mtow`, как у посадки.
    "per_tonne_hour_above": lambda c, r: c["mtow_t"] * max(
                             0, math.ceil(c["park_h"] - r.threshold)),
}
# Базы, зависящие от времени стоянки. Для долевого правила (`pct_of`)
# только они умножают долю: «5% от посадочного за каждый час» — это доля
# раз в час, а «5% от посадочного» с базой per_movement — доля один раз,
# как заведено в Барселоне и Дохе до появления этого списка.
TIME_BASES = {"per_hour", "per_15min", "per_hour_above", "per_day", "per_day_above",
              "per_tonne_hour_above"}
# `nearest_tonne` — Бангалор: «based on the nearest MT». Не `round()`:
# банковское округление даёт 78,5 → 78, а документ имеет в виду
# арифметическое.
ROUND = {None: lambda x: x, "ceil_tonne": math.ceil, "ceil_hour": math.ceil,
         "nearest_tonne": lambda x: math.floor(x + 0.5)}
# `takeoff` — отдельно от `landing`, потому что аэропорт вправе тарифицировать
# их по РАЗНЫМ категориям: у Франкфурта шум при посадке и при взлёте
# отнесён к разным шкалам (§1.2.6 и §1.2.7), и B738 стоит в категории 3 на
# посадке и 6 на взлёте. «Движение» с одной категорией на оба события
# занижало взлёт почти у всех типов.
EVENTS = ("movement", "landing", "takeoff", "turnaround")

# Сколько раз срабатывает правило с этим признаком начисления.
EVENT_COUNT_KEY = {"movement": "movements", "landing": "landings",
                   "takeoff": "departures",
                   "turnaround": "turnarounds"}

# Закрытый словарь условий применения.
#
# Без него правило с выдуманным ключом — скажем, {"season": "summer"} —
# спокойно проходит гейт, ложится в базу и НИКОГДА не срабатывает: в
# контексте расчёта такого ключа нет, сравнение всегда ложно. Ни ошибки,
# ни предупреждения, просто статья тихо отсутствует в сумме. Тот же класс
# отказа, что и валидатор, который ни разу не срабатывал.
CONDITION_KEYS = {
    "flight",        # EEA | INTL | domestic
    "pax_type",      # local | transfer | transit
    "dest",          # ступень шкалы направлений, см. DOMAINS
    "month",         # 1-12, месяц ВЫЛЕТА, не дата справочника
    "night",         # bool
    "noise_cat",     # int; у аэропортов с раздельными шкалами — при посадке
    "noise_cat_dep", # int, категория шума при взлёте (Франкфурт §1.2.7)
    "cargo",         # bool
    "stand",         # apron | pier
    "stand_group",   # int, группа стоянки
    "ac_group",      # int, группа ВС у оператора
    "ac_class",      # int, класс ВС у оператора
    "mtow_t",        # интервал (lo, hi]
    "pax_per_mtow",  # интервал
    "park_h",        # интервал
    "park_h_over_free",
    "return_technical",
    "operator",      # national | foreign — свой или иностранный эксплуатант
                     # (Россия: два прейскуранта на один аэропорт)
    "terminal",      # буква или цифра терминала: у Шереметьево ставка
                     # аэровокзального сбора своя у B/C/D и у E/F
    "other",         # ИКАО другого конца плеча: Пулково держит отдельный
                     # прейскурант на внутренние линии в Москву и обратно
    "seats",         # число кресел борта: Нарита берёт за багажную систему
                     # по полосам кресел, а не по массе
}

# Кому адресован пропуск значения (решение 78).
#
#   data     величину определяет ТИП: класс ВС, категория шума. Их не
#            знает пользователь и не должен знать — отсутствие есть
#            вопрос к нам, к полноте справочника.
#   input    величину определяет операция дня: перрон, группа стоянки,
#            часы стоянки, месяц, ночь, вид пассажира, груз. Справочного
#            значения не существует: на этапе планирования никто не
#            знает, к какому перрону встанет борт. Отсутствие есть
#            вопрос к пользователю.
#   derived  величину считает сама модель из маршрута и типа. Пропуск
#            здесь не вопрос ни к кому, а дефект расчёта.
#
# Слияние трёх в одно заставило бы разбор винить данные в том, чего не
# ввёл человек, — и наоборот.
KEY_ORIGIN = {
    "ac_class": "data", "noise_cat": "data", "noise_cat_dep": "data",
    "ac_group": "data",

    "stand": "input", "stand_group": "input", "park_h": "input",
    "operator": "input", "terminal": "input",
    "other": "derived", "seats": "derived",
    "park_h_over_free": "input", "month": "input", "night": "input",
    "pax_type": "input", "cargo": "input", "return_technical": "input",

    "dest": "derived", "flight": "derived", "mtow_t": "derived",
    "pax_per_mtow": "derived",
}

# Условие без адресата — тот же тихий отказ, что условие без источника:
# оно попадёт в отчёт о полноте и не будет знать, кому адресовано.
# Проверяется при загрузке модуля, а не при первом промахе.
assert set(KEY_ORIGIN) == CONDITION_KEYS, (
    "у условий нет адресата пропуска: "
    f"{sorted(CONDITION_KEYS - set(KEY_ORIGIN))}; лишние: "
    f"{sorted(set(KEY_ORIGIN) - CONDITION_KEYS)}")


# Величины, которые контекст подаёт помимо условий: они входят в базы
# начисления, а не в отбор правил. `mtow_t` и `park_h` числятся в обоих
# списках намеренно — по ним и отбирают, и считают.
CONTEXT_VALUES = {"pax", "cargo_kg"} | set(EVENT_COUNTS)


def check_context(ctx: dict) -> None:
    """Контекст обязан подавать РОВНО те ключи, что перечислены в словаре.

    Настоящий контракт задаёт не `CONDITION_KEYS`, а тот `dict`, который
    собирает расчёт. Пока эти два списка никем не сверялись, восемь ключей
    из пятнадцати не приходили никогда — правило с таким условием проходило
    `self_check` (ключ в словаре есть, область непуста) и не срабатывало ни
    разу, потому что `ctx.get(k)` возвращал `None`. Во Франкфурте так
    умирали 90 правил из 99 и 85% суммы.

    Это тот же класс отказа, что решение 21, только с другой стороны: там
    выдуманный ключ проходил гейт и не срабатывал, здесь настоящий.

    Падение, а не предупреждение. Иначе ключ можно завести, не научив
    расчёт его подавать, и повторение — вопрос времени.
    """
    keys = set(ctx)
    missing = CONDITION_KEYS - keys
    extra = keys - CONDITION_KEYS - CONTEXT_VALUES - {"n"}
    if missing or extra:
        raise KeyError(
            "контекст расчёта разошёлся с CONDITION_KEYS"
            + (f"; не подаётся: {sorted(missing)}" if missing else "")
            + (f"; лишнее: {sorted(extra)}" if extra else "")
            + ". Условие, которого нет в контексте, не срабатывает молча — "
              "заведи источник значения или убери ключ из словаря")


CONTEXT_PREFIX = "charge_context"


def parse_context_value(key: str, raw):
    """Значение условия из строки, с проверкой по области.

    Тип берётся из `DOMAINS`, отдельной таблицы типов нет: множество
    строк даёт строку, множество целых — целое, интервал — дробное. Это
    не экономия, а то же требование, что к правилам: значение проверяется
    против той же области, по которой проверяется достижимость. Иначе
    появятся два списка допустимого, и они разойдутся.
    """
    if key not in CONDITION_KEYS:
        raise KeyError(f"{key} не является условием применения; "
                       f"допустимы: {sorted(CONDITION_KEYS)}")
    dom = DOMAINS.get(key)
    if dom == "icao":                                # открытая область
        v = str(raw).strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4}", v):
            raise ValueError(f"{key}={raw!r} не похоже на код ИКАО")
        return v
    if isinstance(dom, tuple):                       # непрерывная величина
        v = float(raw)
        if not dom[0] <= v <= dom[1]:
            raise ValueError(f"{key}={v} вне области {list(dom)}")
        return v
    sample = next(iter(dom))
    kinds = {type(x) for x in dom}
    if isinstance(sample, bool):
        v = str(raw).strip().lower() in ("1", "true", "да", "yes")
    elif kinds == {int}:
        v = int(raw)
    elif kinds == {int, str}:                        # смешанная область: 1–16 или A–F
        t = str(raw).strip().upper()
        v = int(t) if t.isdigit() else t
    else:
        v = str(raw).strip()
    if v not in dom:
        raise ValueError(f"{key}={raw!r} вне области "
                         f"{sorted(dom, key=str) if len(dom) < 20 else '...'}")
    return v


def parse_context_sets(pairs) -> dict[str, dict]:
    """`charge_context.EDDF.noise_cat=3` → `{"EDDF": {"noise_cat": 3}}`.

    Аэропорт в ключе обязателен, а не подразумевается на весь расчёт.
    `noise_cat`, `stand_group` и `ac_class` — порядковые номера ВНУТРИ
    аэропорта: тройка означает у Франкфурта категорию 3, у Дублина QC 0,5,
    у Гатвика Chapter 14. Одно значение на оба конца маршрута неверно с
    того момента, как концов стало два.

    Строки сюда пускаются, а в слой переопределения фактов — нет.
    Основание: это не переопределение факта, а ВХОД расчёта, такой же как
    загрузка или месяц. Ставка в хранилище лежит и проверяется гейтом,
    поэтому там число обязательно; категории шума в хранилище нет вовсе,
    и требовать от неё числовой формы не за чем. Числовая проверка
    `parse_set` остаётся нетронутой — расходятся не типы значений, а
    пространства имён.
    """
    out: dict[str, dict] = {}
    for item in (pairs.items() if isinstance(pairs, dict) else
                 (p.split("=", 1) for p in (pairs or []))):
        key, raw = item
        parts = str(key).split(".")
        if len(parts) != 3 or parts[0] != CONTEXT_PREFIX:
            raise ValueError(
                f"{key}: ожидается {CONTEXT_PREFIX}.<ИКАО>.<условие>, "
                f"например {CONTEXT_PREFIX}.EDDF.noise_cat=3")
        _, icao, cond = parts
        out.setdefault(icao.upper(), {})[cond] = parse_context_value(cond, raw)
    return out


@dataclass
class Rule:
    code: str                        # статья: landing, passenger, noise, ...
    base: str                        # одна из BASES
    rate: float
    currency: str = "EUR"
    events: str = "movement"         # movement | landing | turnaround
    when: dict = field(default_factory=dict)
    minimum: float | None = None
    pct_of: str | None = None        # доля от другой статьи; "*" — от суммы
    round_mtow: str | None = None
    exponent: float = 0.5           # для per_service_unit: 0.5 en-route, 0.70 терминальный
    threshold: float = 0.0          # для per_hour_above: порог в часах
    source_note: str = ""
    # Достоверность ПРОЧТЕНИЯ — ось, независимая от происхождения
    # (решение 73). Ярус 3 с параметрикой — `estimated` по происхождению и
    # точный по прочтению: мы знаем ровно, что посчитали сами. Доха
    # наоборот: происхождение безупречное, документ настоящий, а прочтение
    # под вопросом, потому что редакция 2015 года. Одна ось не выражает
    # обоих утверждений, и слияние сделало бы «посчитано по параметрике»
    # неотличимым от «списано из негодного документа».
    #
    # Все четыре читаются в `from_fact` из КОЛОНОК и в `value_text` не
    # сериализуются: колонки уже есть, дублирование дало бы два источника
    # правды.
    key: str | None = field(default=None, compare=False)
    certainty: str | None = field(default=None, compare=False)
    error_cost: float | None = field(default=None, compare=False)
    confirm_by: str | None = field(default=None, compare=False)
    # Узел карты данных. Заполняется в `load_rules` из провенанса факта, а
    # не приезжает из файла разбора: файл описывает правило, а карта — то,
    # откуда правило взялось, и второе меняется без первого.
    node: str | None = field(default=None, compare=False)

    def matches(self, ctx: dict) -> bool:
        for k, want in self.when.items():
            got = ctx.get(k)
            if isinstance(want, (list, tuple)) and len(want) == 2 \
                    and all(isinstance(x, (int, float)) for x in want):
                if got is None or not (want[0] < got <= want[1]):
                    return False
            elif isinstance(want, dict) and set(want) == {"not"}:
                # Отрицание: {"not": [...]} — значение НЕ из списка. Нужно
                # там, где тариф делит «на Москву» и «на всё остальное»:
                # перечислить «всё остальное» нельзя, а два правила без
                # отрицания сработали бы оба.
                if got is None or got in want["not"]:
                    return False
            elif isinstance(want, (set, frozenset, list, tuple)):
                # Список строк — принадлежность. `self_check` читал его так
                # с самого начала, а здесь список сравнивался со значением
                # целиком и не совпадал никогда: правило с
                # {"flight": ["EEA", "INTL"]} проходило достижимость и не
                # срабатывало. Второе прочтение того же поля разошлось с
                # первым молча (решение 102).
                if got not in want:
                    return False
            elif got != want:
                return False
        return True

    def unknown_keys(self, ctx: dict) -> list[str]:
        """Условия, значение которых неизвестно.

        Отличать от несовпадения обязательно. «Правило не подошло, потому
        что борт другой категории» и «правило не подошло, потому что
        категория борта неизвестна» выглядят в сумме одинаково, а значат
        разное: первое верно, второе — потерянная статья.
        """
        return sorted(k for k in self.when if ctx.get(k) is None)

    def to_json(self) -> str:
        d = asdict(self)
        d.pop("rate")                 # ставка живёт в числовом поле факта
        d.pop("node")                 # узел — свойство факта, не правила
        for f in ("key", "certainty", "error_cost", "confirm_by"):
            d.pop(f)                  # колонки факта, не описание правила
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_fact(cls, row) -> "Rule":
        d = json.loads(row["value_text"])
        d["rate"] = row["value"]
        r = cls(**d)
        r.certainty = _row_field(row, "certainty")
        r.confirm_by = _row_field(row, "confirm_by")
        cost = _row_field(row, "error_cost")
        r.error_cost = float(cost) if cost is not None else None
        return r


def _row_field(row, *names):
    """Поле строки хранилища по имени.

    `store.current` возвращает то `dict`, то `sqlite3.Row`; у второго нет
    `.get`, отсюда обёртка.

    Раньше здесь стояла цепочка из четырёх имён — колонки узла в схеме
    ещё не было, и я не знал, как её назовут. Ветка B завела `node`,
    причина цепочки исчерпана, имя прибито. Цепочка была безопасна ровно
    пока не подходило ни одно имя: при переименовании подошло бы
    следующее, и подмена прошла бы бесшумно.
    """
    for n in names:
        try:
            v = row[n]
        except (KeyError, IndexError, TypeError):
            continue
        if v:
            return v
    return None


def _state_covers(store, state: str, icao: str, as_of) -> bool:
    """Действует ли общегосударственная статья на этом аэродроме.

    Область задана ВЫЧИТАНИЕМ: включено государство целиком, исключения
    перечислены поимённо и датированы — Фриули с 2024, Абруццо на
    2025-2027, Сицилия с 2026 кроме четырёх аэродромов. Поэтому проверять
    надо на дату расчёта, а не на дату разбора.

    Факт `_scope` лежит с пустым `value_text` (правилом он не становится),
    а сама область — в `note` строкой JSON.
    """
    row = store.get("airport_charge", f"{state}/_scope", as_of)
    if row is None:
        return False
    try:
        scope = json.loads(row["note"] or "{}")
    except ValueError:
        return False
    at = str(as_of)
    for ex in scope.get("exclude") or []:
        if icao not in (ex.get("icao") or []):
            continue
        since, until = ex.get("since"), ex.get("until")
        if (since is None or since <= at) and (until is None or at < until):
            return False        # исключён на эту дату
    return True


def load_rules(store, icao: str, as_of, report: dict | None = None) -> list[Rule]:
    """Строки тарифа аэропорта из хранилища, действующие на дату.

    `report` — необязательный словарь, куда складывается всё, что не
    доехало до правил. Раньше здесь стоял голый `except: continue`, и
    факт, из которого не удалось собрать правило, исчезал бесшумно: сумма
    получалась меньше, а причина не существовала нигде. Тот же класс, что
    мёртвый валидатор, только на входе.
    """
    out = []
    broken: list[str] = []
    empty: list[str] = []
    # Префиксы, которые относятся к этому аэропорту. Кроме собственного
    # тарифа это ОБЩЕГОСУДАРСТВЕННАЯ статья: муниципальная надбавка
    # Италии установлена законом, ключуется государством и действует на
    # аэропортах, перечисленных областью действия.
    #
    # Область раскрывается ЗДЕСЬ, на расчёте, а не при разборе: список
    # аэродромов государства меняется, исключения датированы, и
    # раскрытие на разборе зафиксировало бы состав на дату разбора вместо
    # даты рейса. Без этого шага надбавка не начислялась вовсе — эталонный
    # набор называл это каждым прогоном, а причина была не в данных.
    prefixes = [f"{icao}/"]
    state = icao[:2].upper()
    if _state_covers(store, state, icao, as_of):
        prefixes += [f"{state}/", f"{state}:{icao}/"]
    for key, row in store.current("airport_charge", as_of).items():
        if not any(key.startswith(p) for p in prefixes):
            continue
        if "/_cat/" in key:
            # Раздел категорий типов — не строка тарифа: его читает
            # categories.py, а здесь он собрался бы в сломанное правило.
            continue
        if not row["value_text"]:
            # Факт с пустым описанием — не мусор: так лежат области
            # действия и датированные исключения (`LI/_scope`). Правилом
            # он не становится, но и потерей не является.
            empty.append(key)
            continue
        try:
            r = Rule.from_fact(row)
        except Exception as e:                     # noqa: BLE001
            broken.append(f"{key}: {type(e).__name__}: {e}")
            continue
        # Узел карты берётся у ФАКТА, а не ставится литералом в месте
        # вызова. Разница проявится в день, когда общегосударственные
        # статьи переедут на AIP GEN 4.1: провенанс факта сменится, и узел
        # сменится вместе с ним, без правки кода и без таблицы
        # соответствий. Литерал пережил бы перенос и продолжил показывать
        # старый источник — то самое расхождение, которое сверка обязана
        # ловить, а не воспроизводить.
        r.node = _row_field(row, "node")
        out.append(r)

    # Одинаковые правила из разных фактов. Появляются, когда одна и та же
    # строка тарифа заведена дважды под разными ключами — например, после
    # смены схемы ключа, когда старые записи остались с открытым
    # интервалом. `evaluate` сложит обе и удвоит статью, не сказав ни
    # слова: на LOWW это дало 11 296,42 вместо 5 648,21.
    #
    # Чинить это должно закрытие интервалов при записи, а здесь только
    # обнаружение. Но обнаружение обязано быть: удвоение суммы — не тот
    # отказ, который можно оставить на добросовестность другого слоя.
    seen: dict = {}
    twins: list[str] = []
    for r in out:
        sig = (r.code, r.base, r.rate, r.events, r.currency,
               repr(sorted((r.when or {}).items())), r.minimum, r.threshold)
        if sig in seen:
            twins.append(f"{r.code} ({BASE_RU.get(r.base, r.base)}, "
                         f"ставка {r.rate})")
        seen[sig] = True
    if report is not None:
        report.update(broken=broken, empty_text=empty, duplicates=twins)
    return out


def rule_nodes(rules: list[Rule]) -> dict[str, str | None]:
    """Узел карты для каждого кода статьи.

    `evaluate` складывает правила по коду, поэтому в трассировку идёт одно
    число на код — и узел нужен один. Если правила одного кода приехали из
    разных источников, узел неопределён: возвращается `None`, и шаг
    честно попадёт в отчёт сверки как несверенный. Подставлять сюда
    любой из двух значило бы выбрать наугад и промолчать об этом.
    """
    seen: dict[str, set] = {}
    for r in rules:
        seen.setdefault(r.code, set()).add(r.node)
    return {code: (nodes.pop() if len(nodes) == 1 else None)
            for code, nodes in seen.items()}


@dataclass
class Caveat:
    """Оговорка прочтения: что принято на веру и чего это стоит.

    `error_cost` НЕ делится на сумму рейса и не складывается с ней. Она
    измерена на эталонном обороте, а стоит рядом со сборами конкретного
    рейса: отношение «3 905 из 10 713» прочлось бы как «36% расчёта под
    вопросом», а этой доли никто не мерил. Отсюда `basis` — единица, с
    которой величину нельзя перепутать (решение 83).
    """

    certainty: str
    error_cost: float | None
    currency: str
    confirm_by: str | None
    codes: list
    rules: int
    basis: str = "на эталонном обороте"


def charge_caveats(rules: list[Rule], ctx: dict) -> list[Caveat]:
    """Оговорки по СРАБОТАВШИМ правилам, схлопнутые по причине.

    Два свойства обязательны, и оба выведены замером, а не рассуждением.

    **Только сработавшие.** Без фильтра по `matches` тариф Дохи вылезает
    на маршруте Франкфурт-Барселона. Проверка, шумящая пропорционально
    объёму хранилища, выключается — и умирает так же надёжно, как
    молчащая.

    **Схлопывание по причине, а не по факту.** У Дохи пометка стоит на
    ДОКУМЕНТЕ и приезжает на одиннадцати строках с одной и той же ценой.
    Сложение по фактам дало бы 38 665 EUR вместо 3 515, то есть
    одиннадцатикратно завышенную тревогу об одной оговорке. Цена берётся
    один раз на причину.
    """
    groups: dict[tuple, dict] = {}
    for r in rules:
        if not r.certainty or r.certainty == "exact":
            continue
        if not r.matches(ctx):
            continue
        k = (r.certainty, r.error_cost, r.currency, r.confirm_by)
        g = groups.setdefault(k, {"codes": set(), "rules": 0})
        g["codes"].add(r.code)
        g["rules"] += 1
    return [Caveat(certainty=c, error_cost=cost, currency=cur, confirm_by=by,
                   codes=sorted(g["codes"]), rules=g["rules"])
            for (c, cost, cur, by), g in sorted(groups.items(), key=str)]


def evaluate(rules: list[Rule], ctx: dict, fx=None,
             report: dict | None = None,
             expected_codes=None) -> dict[str, float]:
    """Сумма по каждой статье, в евро.

    fx(currency, ...) -> курс к евро; нужен, потому что тарифы вне зоны
    евро публикуются в национальной валюте. Без него правило в чужой
    валюте пропускается, а не пересчитывается по выдуманному курсу.
    """
    ctx = {**EVENT_COUNTS, **{"cargo_kg": 0.0, "park_h": 0.0}, **ctx}
    check_context(ctx)
    out: dict[str, float] = {}
    mins: dict[str, float] = {}
    skipped: list[str] = []

    def to_eur(v, cur):
        if cur == "EUR":
            return v
        rate = fx(cur) if fx else None
        if not rate:
            skipped.append(cur)
            return None
        return v / rate

    active = [r for r in rules if r.matches(ctx)]

    # Правила, не сработавшие из-за неизвестного значения условия. Молча
    # их терять нельзя: статья исчезает из суммы, а сумма выглядит целой.
    unknown: dict[str, set] = {}
    for r in rules:
        if r in active:
            continue
        for k in r.unknown_keys(ctx):
            unknown.setdefault(k, set()).add(r.code)

    for r in active:
        if r.pct_of is not None:
            continue
        n = ctx[EVENT_COUNT_KEY[r.events]]
        c = {**ctx, "n": n}
        if r.round_mtow:
            c["mtow_t"] = ROUND[r.round_mtow](c["mtow_t"])
        amount = to_eur(r.rate, r.currency)
        if amount is not None:
            out[r.code] = out.get(r.code, 0.0) + amount * BASES[r.base](c, r)
        # Минимум — пол над статьёй, а не отдельный сбор, и применяется на
        # ЛЮБОЙ базе. Раньше поле читалось только при `per_movement`, а на
        # прочих игнорировалось молча: в первых разборах Пальмы и Дублина
        # минимумы стояли на `per_tonne_mtow` и не работали.
        #
        # Пол обязан жить под кодом основной статьи. Отдельным кодом он
        # превращается из пола в добавку — на Гатвике это давало +454 EUR
        # на пустом месте.
        if r.minimum is not None:
            m = to_eur(r.minimum, r.currency)
            if m is not None:
                mins[r.code] = max(mins.get(r.code, 0.0), m * n)

    for code, m in mins.items():
        out[code] = max(out.get(code, 0.0), m)

    for r in active:                                # доли от других статей
        if r.pct_of is None:
            continue
        src = sum(out.values()) if r.pct_of == "*" else out.get(r.pct_of, 0.0)
        times = 1.0
        if r.base in TIME_BASES:
            n = ctx[EVENT_COUNT_KEY[r.events]]
            times = BASES[r.base]({**ctx, "n": n}, r)
        out[r.code] = out.get(r.code, 0.0) + r.rate * src * times

    if skipped:
        out["_нет курса"] = 0.0
    for k, codes in sorted(unknown.items()):
        out[f"_нет значения {k}: пропущены {', '.join(sorted(codes))}"] = 0.0

    # Счёт пропущенного, а не строка о нём. В предупреждениях рейса эта
    # информация растворяется среди восьми других, а вопрос «насколько
    # неполон ответ» требует числа.
    #
    # Долю СУММЫ посчитать нельзя по построению: величина пропущенной
    # статьи неизвестна, иначе она не была бы пропущена. Считается доля
    # статей, и это единственное, что здесь можно утверждать честно.
    if report is not None:
        priced = {c for c, v in out.items()
                  if not c.startswith("_") and abs(v) > 1e-9}
        touched = {c for codes in unknown.values() for c in codes}
        by_origin: dict[str, list] = {}
        for k in sorted(unknown):
            by_origin.setdefault(KEY_ORIGIN[k], []).append(k)
        report.update(
            total_codes=len({r.code for r in rules}),
            priced_codes=sorted(priced),
            lost_codes=sorted(touched - priced),
            partial_codes=sorted(touched & priced),
            # Решение 78: пропуск справочного значения и пропуск ввода —
            # разные утверждения, и адресованы разным людям. Объединения
            # трёх списков здесь нет намеренно: имя `unknown_keys` не
            # говорило бы, что внутри, и первый, кто возьмёт поле по
            # названию, получил бы не то, что думает. Складывается на
            # месте — вычисленное объединение разойтись не может.
            missing_data=by_origin.get("data", []),
            missing_input=by_origin.get("input", []),
            missing_derived=by_origin.get("derived", []),
            # Валюты СРАБОТАВШИХ правил. Не всех: валюта в неприменившемся
            # правиле не задействована, и объявлять её покрытой значило бы
            # то же, что показывать оговорку по несработавшему правилу.
            currencies=sorted({r.currency for r in active}),
        )
        # Статья, которой в документе НЕТ ЦЕЛИКОМ.
        #
        # Своими силами это не обнаруживается: знаменатель `total_codes`
        # считается по кодам, встреченным в правилах, и уменьшается
        # вместе с числителем. Документ без пассажирского сбора отчитается
        # «начислено всё» — та же слепота, что у `coverage_check`, только
        # на стороне рейса. У Дохи разбор показал бы полное начисление.
        #
        # Видит это только корпус (решение 88): статья, присутствующая
        # почти у всех и отсутствующая у одного. Вердикт приезжает
        # снаружи, здесь он лишь доносится до разбора — иначе находка на
        # 3 195 EUR останется в отчёте проверки и не дойдёт до того, кто
        # смотрит на сумму рейса.
        if expected_codes is not None:
            report["absent_codes"] = sorted(set(expected_codes)
                                            - {r.code for r in rules})
    return {k: v for k, v in out.items() if abs(v) > 1e-9 or k.startswith("_")}


# Область допустимых значений каждого условия. Достижимость проверяется
# по областям, а не перебором придуманных контекстов: условия независимы,
# поэтому правило достижимо тогда и только тогда, когда каждое его условие
# выполнимо по отдельности. Перебор образцов я пробовал дважды и дважды
# объявлял живые правила мёртвыми, потому что образцы подбирались руками.
DOMAINS = {
    "flight":           {"EEA", "INTL", "domestic"},
    "pax_type":         {"local", "transfer", "transit"},
    # Направление — порядковая шкала, а не ярлык. Документы режут её в
    # разных местах: ANA по Шенгену, ANAC по ЕС, Aena по ЕЭП. Одно
    # значение на каждое деление не годится — Ирландия одновременно ЕС,
    # не Шенген и ЕЭП. Ступени упорядочены по дороговизне, и каждый
    # документ ставит границу там, где ему надо.
    #
    # Врёт на странах, входящих в один клуб против порядка шкалы:
    # Швейцария в Шенгене, но не в ЕЭП. Расхождение в пределах одной
    # ступени пассажирского сбора, принято сознательно.
    "dest":             {"schengen", "eu_non_schengen",
                         "europe_non_eu", "intercontinental"},
    "stand":            {"apron", "pier"},
    "operator":         {"national", "foreign"},
    "terminal":         set("ABCDEFGHJKLMNPRSTUVWXYZ") | set("123456789"),
    # Открытая область: любой код ИКАО. Строка-метка, а не множество —
    # проверка достижимости сверяет форму значения, не принадлежность.
    "other":            "icao",
    "seats":            (0.0, 1000.0),
    "night":            {True, False},
    "cargo":            {True, False},
    "park_h_over_free": {True, False},
    "return_technical": {True, False},
    # Категория шума — местная: у Франкфурта 1–16, у Нариты A–F по индексу
    # к главе 3 Приложения 16. Одна область на оба вида, потому что
    # значение принадлежит аэропорту, а не типу (решение 68).
    "noise_cat":        set(range(1, 17)) | set("ABCDEFGH"),
    "noise_cat_dep":    set(range(1, 17)) | set("ABCDEFGH"),
    "stand_group":      set(range(1, 10)),
    "ac_group":         set(range(1, 7)),
    "ac_class":         set(range(0, 7)),
    # непрерывные: интервал правила должен пересекаться с областью
    "mtow_t":           (0.4, 650.0),
    "pax_per_mtow":     (0.0, 5.0),
    "park_h":           (0.0, 240.0),
    # Месяц интервальный намеренно, хотя значений всего двенадцать: так
    # `coverage_check` его не трогает и не порождает шум на каждом
    # сезонном тарифе. Полноту года проверяет `season_check`.
    "month":            (0, 12),
}


def coverage_check(rules: list[Rule], scales: dict | None = None) -> list[str]:
    """Неполнота: статья различает значения условия, но покрыты не все.

    Отдельная проверка от достижимости. Достижимость ловит правило,
    которое НИКОГДА не сработает; полнота — набор правил, который
    сработает только для части флота. Второе опаснее: расчёт для A320
    выглядит верным, а для A388 молча теряет статью.

    `scales` — сколько ступеней у этого аэропорта на самом деле, из
    заголовка файла разбора: `{"noise_cat": 8, "ac_class": 6}`. Без него
    полнота мерилась размером словарной области, а она вмещает самую
    подробную шкалу из встреченных: у Дублина восемь ступеней QC, у
    Гатвика шесть категорий, а область `noise_cat` — шестнадцать
    значений, и проверка честно сообщала «заведено 8 из 16» о полных
    данных. При сотне аэропортов человек перестаёт читать такие
    предупреждения и пропускает настоящее.

    Не отказ, а предупреждение: неполнота бывает законной. У Вены нет
    ставки телетрапа для шестой группы ВС, потому что такие борта к
    телетрапу не ставят, и в документе прямо стоит «не применяется».
    Такие случаи человек подтверждает при сверке.
    """
    scales = scales or {}
    ENUMS = {k: v for k, v in DOMAINS.items() if isinstance(v, set)
             and k not in ("night", "cargo", "park_h_over_free",
                           "return_technical")}
    used: dict[tuple, set] = {}
    for r in rules:
        for k, want in r.when.items():
            if k not in ENUMS or isinstance(want, (list, tuple, dict)):
                continue
            used.setdefault((r.code, k), set()).add(want)

    # Одно заведённое значение — не «различения нет», а самый частый вид
    # неполноты: строка вводится для того борта, на котором проверяли,
    # а остальные восемь групп остаются пустыми. Первая версия этой
    # проверки требовала минимум двух значений и ровно этот случай
    # пропускала.
    out = []
    for (code, key), covered in sorted(used.items()):
        declared = scales.get(key)
        if declared is not None:
            if len(covered) >= declared:
                continue
            out.append((declared - len(covered),
                        f"{code}: по условию {key} заведено {len(covered)} "
                        f"ступеней из {declared} объявленных в файле"))
            continue
        dom = ENUMS[key]
        # noise_cat — смешанная область (1–16 и A–H): числовая и буквенная
        # шкалы принадлежат разным аэропортам, и «непокрытые» считаются
        # только внутри той шкалы, которой пользуется файл.
        if key == "noise_cat":
            kinds = {type(v) for v in covered}
            dom = {v for v in dom if type(v) in kinds} if kinds else dom
        missing = sorted(dom - covered, key=str)
        if not missing:
            continue
        shown = missing if len(missing) < 9 else str(missing[:8]) + "..."
        out.append((len(missing),
                    f"{code}: по условию {key} заведено {len(covered)} значений "
                    f"из {len(dom)}, нет {shown}"
                    + ("" if key in scales else
                       " — если у аэропорта столько ступеней и нет, объяви "
                       "их число в заголовке файла")))
    return [msg for _, msg in sorted(out, key=lambda t: -t[0])]


MONTHS = frozenset(range(1, 13))


def _months_of(want) -> set[int]:
    """Месяцы, которые покрывает условие правила.

    Интервал читается как `(lo, hi]` — так же, как его читает `matches`.
    Апрель-октябрь записывается `[3, 10]`.
    """
    if isinstance(want, (list, tuple)) and len(want) == 2:
        return set(range(int(want[0]) + 1, int(want[1]) + 1)) & MONTHS
    if isinstance(want, (set, frozenset)):
        return {int(x) for x in want} & MONTHS
    return {int(want)} & MONTHS


def _rest_key(when: dict) -> tuple:
    """Условия правила без месяца — то, что делает строки сравнимыми."""
    return tuple(sorted((k, repr(list(v) if isinstance(v, (list, tuple, set,
                                                           frozenset)) else v))
                        for k, v in when.items() if k != "month"))


def season_check(rules: list[Rule]) -> list[str]:
    """Год покрыт не целиком: заведён высокий сезон, низкий потерян.

    Нужна отдельно, потому что область `month` намеренно интервальная и
    `coverage_check` её не трогает — иначе каждый сезонный тариф порождал
    бы шум про недостающие месяцы. Но без этой проверки ключ `month`
    закрывает задачу наполовину: незаведённый низкий сезон — самая частая
    неполнота после отсутствия самого ключа. На Дублине разница по посадке
    двукратная, на Палермо 24%.

    Сравниваются строки с ОДИНАКОВЫМИ прочими условиями. Группировать по
    одному коду нельзя: у статьи обычно несколько полос по массе, и полоса
    с одним лишь летним правилом спряталась бы за соседней, где заведены
    оба сезона.

    Зимний сезон через новый год интервалом `(lo, hi]` не выражается:
    ноябрь-март — это `[10, 12]` и `[0, 3]` двумя строками. Пропуск одной
    из них проверка и ловит.
    """
    seasonal: dict[tuple, set] = {}
    year_round: dict[tuple, set] = {}
    for r in rules:
        key = (r.code, _rest_key(r.when))
        if "month" in r.when:
            seasonal.setdefault(key, set()).update(_months_of(r.when["month"]))
        else:
            year_round.setdefault(key, set()).add(r.base)

    out = []
    for (code, rest), covered in sorted(seasonal.items()):
        where = (" при " + ", ".join(f"{k}={v}" for k, v in rest)) if rest else ""
        missing = sorted(MONTHS - covered)
        if missing:
            out.append(f"{code}{where}: заведено {len(covered)} месяцев из 12, "
                       f"нет {missing}")
        if (code, rest) in year_round:
            # Строка без условия на месяц срабатывает и в сезонные месяцы
            # тоже — то есть в них статья начисляется дважды. Молча это
            # выглядит как завышенная ставка высокого сезона.
            out.append(f"{code}{where}: рядом с сезонными строками есть "
                       f"всесезонная — в покрытые месяцы статья начислится "
                       f"дважды")
    return out


def self_check(rules: list[Rule]) -> list[str]:
    """Правила, не сработавшие ни в одном эталонном контексте.

    Пустой список — все строки достижимы. Непустой почти всегда означает
    опечатку в условии, а не экзотический тариф: настоящее условие обычно
    выполняется хотя бы для одного из четырёх типовых рейсов.
    """
    dead = []
    for r in rules:
        for k, want in r.when.items():
            dom = DOMAINS.get(k)
            if dom is None:
                dead.append(f"{r.code}: условие {k} вне словаря")
            elif isinstance(want, dict) and set(want) == {"not"}:
                continue                    # отрицание достижимо всегда
            elif dom == "icao":
                vals = want if isinstance(want, (list, tuple, set)) else [want]
                bad = [v for v in vals if not re.fullmatch(r"[A-Z0-9]{4}", str(v))]
                if bad:
                    dead.append(f"{r.code}: {k}={bad} не похоже на код ИКАО")
            elif isinstance(dom, tuple):
                lo, hi = want if isinstance(want, (list, tuple)) else (want, want)
                if hi <= dom[0] or lo >= dom[1]:
                    dead.append(f"{r.code}: интервал {k}={list(want)} не пересекается "
                                f"с областью {list(dom)}")
            elif isinstance(want, (set, frozenset, list, tuple)):
                if not (set(want) & dom):
                    dead.append(f"{r.code}: ни одно из {sorted(want)} не входит в "
                                f"область {k}")
            elif want not in dom:
                dead.append(f"{r.code}: {k}={want!r} вне области "
                            f"{sorted(dom) if len(dom) < 20 else '...'}")
    return dead
