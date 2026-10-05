"""Местные категории ВС: как аэропорт раскладывает типы по своим строкам тарифа.

ТРИ СОРТА ЗНАНИЯ, И ТОЛЬКО ОДИН ИЗ НИХ — СПРАВОЧНИК АЭРОПОРТА.

  1. Выводится из физики типа: буква кода ИКАО из размаха, группа стоянки
     из размаха и длины, полоса массы. Формула, ноль записей.
  2. Свойство типа, общее для всех аэропортов: сертифицированный шум
     (глава Приложения 16, уровни EPNdB в трёх точках). Один источник на
     мир — база шума EASA, — записи в домене `aircraft`.
  3. Решение конкретного аэропорта: «к категории 7 относятся такие-то
     типы». Единицы строк, в файле тарифа.

Прежний ключ `<ИКАО>/<тип>/<условие>` задавал перебор всех трёх сортов как
третьего: 44 аэропорта × 37 типов × 3 условия. Здесь у аэропорта короткий
упорядоченный список ПРАВИЛ над свойствами типа — то же, что решение 19
сделало со сборами: механика в данных, кода на аэропорт ноль.

ГДЕ ЛЕЖИТ. Раздел `categories` файла тарифа, факт `<ИКАО>/_cat/<условие>`
в домене `airport_charge` рядом с `_next` и `_na`. Категории приходят из
того же документа и меняются с его редакцией — значит и снимаются с учёта
вместе с ним (решение 63), а не живут отдельной жизнью.

ФОРМА:

    "categories": {
      "noise_cat": {
        "named":  {"B744": 12, "A388": 11},          # документ называет тип
        "rules":  [
          {"when": {"icao": ["A318","A319","A320","A321"]}, "value": 6,
           "note": "п. 3.1.3.4: немодифицированное семейство A320"},
          {"when": {"noise_margin_cum": {"ge": 23}, "noise_margin_min": {"ge": 1}},
           "value": 1, "note": "Chapter 14 Minus"},
          {"default": 5, "note": "Chapter 3 и ниже"}
        ]
      }
    }

Порядок разрешения: названный документом тип → первое сработавшее
правило → умолчание (помечено `estimated`) → нет значения. Названный тип
сверяется с правилами, и расхождение называется: правила могут промахнуться
там, где аэропорт раскладывает по своим измерениям, а не по сертификату
(Франкфурт, Мюнхен, Гамбург меряют сами).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

# ── свойства типа ───────────────────────────────────────────────────────

# Буква кода аэродрома по размаху, Приложение 14, табл. 1-1 (редакция с
# 2018 года определяет букву только размахом, без колеи шасси).
CODE_LETTER = [(15.0, "A"), (24.0, "B"), (36.0, "C"), (52.0, "D"),
               (65.0, "E"), (80.0, "F")]


def code_letter(span_m: float | None) -> str | None:
    """Наименьшая буква, в которую тип помещается по размаху."""
    if span_m is None:
        return None
    for lim, letter in CODE_LETTER:
        if span_m < lim:
            return letter
    return None                     # шире 80 м — вне таблицы, не угадываем


def chapter3_limits(mtom_t: float, engines: int) -> dict[str, float]:
    """Пределы главы 3 Приложения 16, том I, для дозвуковых реактивных.

    M — максимальная взлётная масса в тоннах. Три точки: боковая (полная
    мощность), заход на посадку, пролёт. Формулы стыкуются на границах
    с точностью до сотых — проверяется тестом.
    """
    lg = math.log10(max(mtom_t, 1e-6))
    lat = 94.0 if mtom_t < 35 else (103.0 if mtom_t >= 400 else 80.87 + 8.51 * lg)
    app = 98.0 if mtom_t < 35 else (105.0 if mtom_t >= 280 else 86.03 + 7.75 * lg)
    if engines <= 2:
        lo, k = 48.1, 66.65
        top = 101.0
    elif engines == 3:
        lo, k = 28.6, 69.65
        top = 104.0
    else:
        lo, k = 20.2, 71.65
        top = 106.0
    fly = 89.0 if mtom_t < lo else (top if mtom_t >= 385 else k + 13.29 * lg)
    return {"lateral": lat, "approach": app, "flyover": fly}


def noise_margins(levels: dict[str, float], mtom_t: float,
                  engines: int) -> dict[str, float]:
    """Запасы к пределам главы 3: по точкам, кумулятивный, наименьший,
    наименьшая сумма двух. Именно этими тремя числами пишутся критерии
    глав 4 и 14 и категории аэропортов, считающих по сертификату."""
    lim = chapter3_limits(mtom_t, engines)
    m = {p: lim[p] - levels[p] for p in ("lateral", "approach", "flyover")}
    vals = list(m.values())
    two = min(vals[0] + vals[1], vals[0] + vals[2], vals[1] + vals[2])
    return {**{f"margin_{p}": v for p, v in m.items()},
            "noise_margin_cum": sum(vals), "noise_margin_min": min(vals),
            "noise_margin_two": two}


# Поля домена `aircraft`, которые читаются в свойства типа.
_NUM_FIELDS = ("span_m", "length_m", "mtow_t", "seats_max", "engine_count",
               "noise_lateral_epndb", "noise_approach_epndb",
               "noise_flyover_epndb", "noise_chapter", "noise_mtom_t")


def aircraft_props(store, icao: str, as_of=None) -> dict:
    """Свойства типа, над которыми пишутся правила категорий.

    Выведенное (буква кода, запасы) считается здесь же и помечается в
    `_derived`, чтобы разбор мог сказать «буква C выведена из размаха»,
    а не выдавать её за справочную.
    """
    p: dict = {"icao": icao.upper(), "_derived": [], "_missing": []}
    for f in _NUM_FIELDS:
        v = store.value("aircraft", f"{icao}/{f}", as_of)
        if v is not None:
            p[f] = float(v)
    p["code_letter"] = code_letter(p.get("span_m"))
    if p["code_letter"]:
        p["_derived"].append("code_letter")
    lv = {k: p.get(f"noise_{k}_epndb") for k in ("lateral", "approach", "flyover")}
    if all(v is not None for v in lv.values()):
        # Запас считается при массе, на которой сертифицирован уровень, а
        # не при MTOW домена: у одного типа десяток сертифицированных масс.
        m = p.get("noise_mtom_t") or p.get("mtow_t")
        if m:
            p.update(noise_margins(lv, m, int(p.get("engine_count") or 2)))
            p["_derived"] += ["noise_margin_cum", "noise_margin_min",
                              "noise_margin_two"]
    return p


# ── правила ─────────────────────────────────────────────────────────────

# Закрытый словарь (решение 21). Правило с выдуманным ключом прошло бы
# гейт и не сработало бы никогда.
MEMBER_KEYS = {"icao", "code_letter", "noise_chapter", "engine_count"}
RANGE_KEYS = {"span_m", "length_m", "mtow_t", "seats_max",
              "noise_lateral_epndb", "noise_approach_epndb",
              "noise_flyover_epndb",
              "noise_margin_cum", "noise_margin_min", "noise_margin_two"}
PREDICATES = MEMBER_KEYS | RANGE_KEYS
# Сравнения ЯВНЫЕ. Интервал `(lo, hi]`, принятый в условиях сборов, здесь
# не годится: Гатвик пишет «не меньше 23», Франкфурт «не больше 24 м», и
# соглашение о границе в разных документах разное. Явный оператор
# убирает спор о границе из кода в документ, где ему место.
OPS = {"ge": float.__ge__, "gt": float.__gt__,
       "le": float.__le__, "lt": float.__lt__}

# Какие условия сборов категории вправе определять: только то, что задаёт
# ТИП в понимании документа (решение 78). `stand_group` здесь потому, что
# у Франкфурта группа стоянки — по габаритам типа (Anhang 3); у аэропорта,
# где группа — это место на перроне, раздел её просто не объявляет.
CATEGORY_CONDS = {"noise_cat", "noise_cat_dep", "ac_class", "ac_group", "stand_group"}


@dataclass
class Resolution:
    cond: str
    value: object = None
    how: str = "none"            # named | rule | default | none
    note: str = ""
    certainty: str = "exact"
    unchecked: list = field(default_factory=list)   # предикаты без данных
    disagree: str = ""           # названный документом тип против правил


def validate(icao: str, cond: str, spec: dict, domain: set | None) -> None:
    """Проверка раздела при разборе. Отказ словами, а не молча при расчёте."""
    if cond not in CATEGORY_CONDS:
        raise ValueError(f"{icao}: категории для {cond!r} не объявляются — "
                         f"допустимы {sorted(CATEGORY_CONDS)}")
    if not isinstance(spec, dict) or not (spec.get("rules") or spec.get("named")):
        raise ValueError(f"{icao}/{cond}: раздел пуст — нужны rules или named")
    vals = list((spec.get("named") or {}).values())
    for i, r in enumerate(spec.get("rules") or []):
        if "default" in r:
            if i != len(spec["rules"]) - 1:
                raise ValueError(f"{icao}/{cond}: умолчание не последним правилом — "
                                 f"всё после него недостижимо")
            vals.append(r["default"])
            continue
        if "value" not in r or not r.get("when"):
            raise ValueError(f"{icao}/{cond}: правило {i} без when или value")
        bad = set(r["when"]) - PREDICATES
        if bad:
            raise ValueError(f"{icao}/{cond}: предикат вне словаря {sorted(bad)}; "
                             f"допустимы {sorted(PREDICATES)}")
        for k, want in r["when"].items():
            if k in RANGE_KEYS:
                if not isinstance(want, dict) or not want or set(want) - set(OPS):
                    raise ValueError(f"{icao}/{cond}: {k} задаётся явным сравнением "
                                     f"{{ge|gt|le|lt: число}}, а не {want!r}")
            elif not isinstance(want, list) or not want:
                raise ValueError(f"{icao}/{cond}: {k} задаётся списком значений")
        vals.append(r["value"])
    if domain:
        out = [v for v in vals if v not in domain and str(v) not in {str(x) for x in domain}]
        if out:
            raise ValueError(f"{icao}/{cond}: значения {out} вне области условия")


def _match(when: dict, props: dict) -> tuple[bool | None, list[str]]:
    """True/False, либо None — если для проверки не хватает данных типа.

    Нехватка данных — не «не подошло». Иначе тип без записи в базе шума
    молча проваливался бы мимо всех правил в умолчание, и дешёвая
    категория досталась бы ему потому, что мы его не знаем.
    """
    missing = []
    for k, want in when.items():
        have = props.get(k)
        if have is None:
            missing.append(k)
            continue
        if k in MEMBER_KEYS:
            norm = (lambda x: str(x).upper()) if k in ("icao", "code_letter") else \
                   (lambda x: int(float(x)))
            if norm(have) not in {norm(w) for w in want}:
                return False, []
        else:
            if not all(OPS[op](float(have), float(v)) for op, v in want.items()):
                return False, []
    return (None, missing) if missing else (True, [])


def resolve(cond: str, spec: dict, props: dict) -> Resolution:
    res = Resolution(cond=cond)
    named = {str(k).upper(): v for k, v in (spec.get("named") or {}).items()}
    by_rule = None
    for i, r in enumerate(spec.get("rules") or []):
        if "default" in r:
            # Два разных умолчания. «Всё прочее — группа 9» у Франкфурта —
            # остаток таблицы документа, это точное утверждение. «Не знаем,
            # берём среднюю» — догадка. Первое объявляется `exact: true`,
            # второе остаётся оценкой и так и показывается.
            if by_rule is None and not res.unchecked:
                exact = bool(r.get("exact"))
                by_rule = Resolution(cond, r["default"], "rule" if exact else "default",
                                     r.get("note") or "умолчание документа",
                                     "exact" if exact else "estimated")
            break
        ok, missing = _match(r["when"], props)
        if ok is None:
            # Первое совпадение выигрывает, значит правило, которое нельзя
            # проверить, закрывает и все последующие: сработай оно — они
            # бы не понадобились. Дальше не идём.
            res.unchecked += missing
            break
        if ok:
            by_rule = Resolution(cond, r["value"], "rule",
                                 r.get("note") or f"правило {i + 1}")
            break
    icao = props.get("icao", "")
    if icao in named:
        res.value, res.how = named[icao], "named"
        res.note = "тип назван документом"
        if by_rule is not None and by_rule.how == "rule" and \
                str(by_rule.value) != str(named[icao]):
            res.disagree = (f"правила дают {by_rule.value} ({by_rule.note}), "
                            f"документ называет {named[icao]}")
        return res
    if by_rule is not None:
        by_rule.unchecked = res.unchecked
        return by_rule
    if not spec.get("rules"):
        res.note = ("тип не назван документом, а правил для неперечисленных "
                    "в разделе нет — значение не угадывается")
        return res
    if res.unchecked:
        res.note = ("не хватает данных типа: " + ", ".join(sorted(set(res.unchecked)))
                    + " — умолчание не применено, чтобы не отдать неизвестному "
                      "типу категорию по остаточному принципу")
    return res


def load_specs(store, icao: str, as_of=None) -> dict[str, dict]:
    """Разделы категорий аэропорта из хранилища."""
    out = {}
    for cond in CATEGORY_CONDS:
        row = store.get("airport_charge", f"{icao}/_cat/{cond}", as_of)
        if row is not None and row["value_text"]:
            try:
                out[cond] = json.loads(row["value_text"])
            except ValueError:
                continue
    return out
