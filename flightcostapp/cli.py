"""CLI. Это же — интерфейс для агента: OpenClaw дёргает `fca refresh --due
--json` по расписанию и разбирает вывод. Никакого отдельного «агентского API»
нет и не нужно — агент пользуется тем же, чем ты."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from .econ import route_economics
from .overrides import parse_set
from .refresh import load_registry, plan_due, refresh_all
from .store import Store
from .validate import freshness_report


# Эталонные маршруты для сверки карты с моделью. Набор, а не один
# маршрут: обратная сверка на одном прогоне ложна — `d_fx` законно
# молчит там, где все ставки в евро, `d_limits` не сработает там, где
# полосы хватает с запасом. Подбор по режимам регулирования (решение 28)
# и по механике расчёта, а не по трафику.
# Эталонные маршруты для сверки карты с моделью. Набор, а не один
# маршрут: обратная сверка на одном прогоне ложна — `d_fx` законно
# молчит там, где все ставки в евро, `d_limits` не сработает там, где
# полосы хватает с запасом. Подбор по режимам регулирования (решение 28)
# и по механике расчёта, а не по трафику.
#
# `needs` — машинная запись того, что маршрут ОБЯЗАН задействовать
# (решение 89). Без неё маршрут, у которого данных меньше всего,
# отчитывается лучше всех: называть нечего, и сверка говорит «сошлась».
# Проверено на живом прогоне оркестратора: PMO–BGY прошёл чисто ровно
# потому, что тарифов Палермо и Бергамо в хранилище не было и сборы
# ушли в параметрику яруса 3 — то есть перестал проверять то, ради чего
# взят.
#
#   node:<id>  — шаг с этим узлом должен быть в трассировке
#   code:<код> — статья должна быть НАЧИСЛЕНА хотя бы на одном конце
#   infeasible — рейс должен оказаться невыполнимым
REF_ROUTES = [
    ("FRA", "BCN", "A320", "эталон: две зоны транзита, оба конца с тарифом",
     # `node:d_charge` выполнялся только шагом «Полнота начисления», а он
     # есть, лишь когда статьи ТЕРЯЮТСЯ: обязательство держалось на
     # дефекте и пало, когда Франкфурт стал считаться целиком. То, что
     # тариф прочитан и начислен, доказывает `code:passenger`.
     ("node:v_cross", "code:passenger")),
    # Месяц задаётся ЯВНО: маршрут взят ради сезонной строки, а без
    # `--month` она не срабатывает по построению, и узел `i_month` не
    # появляется в трассировке. Регрессия обязана подавать вход, ради
    # которого она заведена, иначе она вечно жалуется на себя.
    ("PMO", "BGY", "A320", "надбавка государства на обоих концах, сезонность",
     ("code:municipal_tax", "node:i_month"), {"month": 7}),
    ("FRA", "SIN", "A320", "невыполнимый рейс, межконтинентальная ступень",
     ("infeasible", "node:v_cross")),
    # Алматы — регрессия на связность, но НЕ проверка величин: ставка
    # расходится с решением регулятора в 2,2 раза и помечена disputed.
    ("ALA", "FRA", "B738", "чужая валюта, формула вне EUROCONTROL",
     ("node:d_fx", "node:v_rate")),
    # Три валюты лежали в хранилище и не касались ни одного эталонного
    # маршрута: фунт у Гатвика, злотый у Познани, риал у Дохи. Проверка
    # покрытия валют их называла, а закрыть было нечем — маршрута нет.
    # Гатвик отдельно ценен тем, что у него НЕТ весового посадочного
    # сбора: там Demand Charge, и это законный `not_applicable`, который
    # регрессия обязана переживать.
    ("LGW", "BCN", "A320", "фунт; у Гатвика нет весового посадочного сбора",
     # Та же ошибка, что у FRA–BCN: тариф доказывается начисленной
     # статьёй, и у Гатвика это именно Demand Charge — ради него маршрут
     # и взят.
     ("cur:GBP", "code:demand")),
    ("POZ", "FRA", "E195", "злотый; малый аэропорт, короткое плечо",
     ("cur:PLN", "node:v_cross")),
    ("DOH", "FRA", "B738", "риал; ставки редакции 2020, помечены stale_edition",
     ("cur:QAR", "caveat")),
]


def _unmet(res, needs) -> list[str]:
    """Что эталонный маршрут обязался задействовать и не задействовал."""
    nodes = {getattr(s, "node", None) for s in getattr(res, "trace", ())}
    priced = set()
    for rep in (getattr(res, "charge_gaps", None) or {}).values():
        priced |= set(rep.get("priced_codes") or [])
    out = []
    for need in needs:
        if need == "infeasible":
            if getattr(res, "feasible", True):
                out.append("рейс оказался выполнимым")
        elif need.startswith("node:"):
            if need[5:] not in nodes:
                out.append(f"узел {need[5:]} не задействован")
        elif need.startswith("code:"):
            if need[5:] not in priced:
                out.append(f"статья {need[5:]} не начислена")
        elif need.startswith("cur:"):
            # Валюта названа маршрутом ЯВНО, а не выведена из того, что
            # он случайно задел: маршрут берут ради неё, и если она не
            # участвовала, брать его было незачем.
            if need[4:] not in (getattr(res, "currencies_seen", None) or ()):
                out.append(f"валюта {need[4:]} не участвовала в расчёте")
        elif need == "caveat":
            if not (getattr(res, "caveats", None) or {}):
                out.append("оговорок прочтения не оказалось")
    return out


def _uncovered_currencies(store, results) -> list[str]:
    """Валюты в хранилище, которых эталонный набор не касается.

    Обратная сторона решения 89: маршрут говорит, чего не задействовал
    он, а это — чего не задействовал НАБОР. Когда B заведёт аэропорт в
    новой валюте, набор не сузится молча.

    Перечисление берётся у хранилища (`inventory`), а не своим запросом:
    второй сырой SELECT в `cli.py` был бы тем же долгом, который только
    что закрыли в `heatmap.py`.
    """
    inv = getattr(store, "inventory", None)
    if inv is None:
        return ["  покрытие валют не проверено: у хранилища нет inventory()"]
    have = set(inv("airport_charge").get("currencies") or {})
    if not have:
        return []
    seen = {c for r in results
            for c in (getattr(r, "currencies_seen", None) or ())}
    if not seen:
        # Result пока не несёт перечня задействованных валют. Молчать
        # нельзя: непроверенное покрытие и полное покрытие выглядели бы
        # одинаково.
        return [f"  покрытие валют не проверено: в хранилище "
                f"{', '.join(sorted(have))}, расчёт их не называет"]
    miss = sorted(have - seen)
    return [f"  валюты без эталонного маршрута: {', '.join(miss)}"] if miss else []


def _composition(store, results) -> list[str]:
    """Состав модели — машинно, а не от руки (решение 81).

    Отпечаток ОДИН и считает его хранилище (решение 87). Своих счётчиков
    отсюда достаточно, своего хеша — нет: механизм, написанный против
    расхождения редакций, был реализован дважды и разошёлся сам. Два
    числа под подписью «состав» хуже, чем ни одного.

    Счётчики берутся по составу, а не по подписям: подписи меняются
    свободно (ветка B переименовала «Сбор:» в «Сбор EDDF:»), а пара
    «раздел + узел» — это и есть устройство модели.
    """
    from .graph import N

    steps = [s for r in results for s in getattr(r, "trace", ())]
    shape = sorted({(getattr(s, "group", ""), getattr(s, "node", None) or "—")
                    for s in steps})
    mine = {"trace_steps": len(steps), "trace_shapes": len(shape),
            "map_nodes": len(N)}

    comp = getattr(store, "composition", None)
    if comp is None:
        # Своего хеша здесь нет намеренно. Считать запасной — значит
        # вернуть второй отпечаток, против которого написано решение 87.
        return [f"  шагов {len(steps)}, видов {len(shape)}, "
                f"узлов карты {len(N)}",
                "  отпечаток не получен: у хранилища нет composition()"]
    got = comp(extra=mine)
    stamp = got.get("fingerprint") if isinstance(got, dict) else got
    return [f"  шагов {len(steps)}, видов {len(shape)}, узлов карты {len(N)}",
            f"  состав: {stamp}"]


def _map_check(store, a) -> None:
    """Сверка карты с моделью на живом расчёте, а не на фикстурах.

    До этого `check_against_trace` вызывался только в тестах на
    фикстурах, где узлы проставлены и проверка всегда зелёная. Проверка,
    которая никогда не срабатывает на реальных данных, считается
    неработающей (решение 16), и попала она в этот разряд ровно потому,
    что её не на чем было запустить.

    Расхождение не останавливает работу: оно законно, пока ветки
    добавляют домены. Но названо вслух.
    """
    from .econ import route_economics
    from .graph import check_against_trace, unrealised_nodes

    said, results = [], []
    for row in REF_ROUTES:
        org, dst, ac, why, needs = row[:5]
        extra = row[5] if len(row) > 5 else {}
        try:
            r = route_economics(store, org, dst, aircraft=ac,
                                load_factor=0.80, fare_eur=100.0, **extra)
        except Exception as exc:                       # noqa: BLE001
            # Непосчитанный эталон — сам по себе результат сверки:
            # молча пропустить его значило бы объявить карту сошедшейся
            # на маршрутах, которые не считались.
            said.append(f"  {org}–{dst}: не посчитан ({type(exc).__name__}) "
                        f"— {why}")
            continue
        results.append(r)
        for line in check_against_trace(r):
            said.append(f"  {org}–{dst}: {line}")
        # Регрессия, которая может ничего не проверить, обязана об этом
        # сказать — решение 37 применительно к самой регрессии.
        for line in _unmet(r, needs):
            said.append(f"  {org}–{dst}: {line} — маршрут взят ради «{why}»")
    for line in unrealised_nodes(results):
        said.append(f"  {line}")
    said += _uncovered_currencies(store, results)

    if a.json:
        return
    print("\nсостав модели:")
    print("\n".join(_composition(store, results)))
    print("\nкарта против модели:")
    print("\n".join(said) if said
          else f"  сошлась на {len(results)} эталонных маршрутах")


def _lease_terms(overrides) -> dict:
    """Допущения пересчёта лизинга из слоя сценария.

    Отдельный разбор, а не общий `--set`: это не факт хранилища и не
    условие начисления, а параметр справочной прикидки. Класть его в
    домен значило бы обещать факт, которого нет.
    """
    out = {}
    for raw in overrides or []:
        if not raw.startswith("lease_terms."):
            continue
        key, _, val = raw.partition("=")
        name = key.split(".", 1)[1]
        try:
            out[name] = float(val)
        except ValueError:
            raise SystemExit(f"{raw}: значение должно быть числом")
    return out


def _fact_label(f: dict) -> str:
    """Короткая подпись факта: что это, а не как хранится.

    В `value_text` у тарифного правила лежит JSON на несколько строк.
    Показывать его целиком — то же, что показывать «256 фактов»: буквы
    есть, прочитать нельзя.
    """
    key = f.get("key", "")
    try:
        d = json.loads(f.get("value_text") or "{}")
    except (ValueError, TypeError):
        d = {}
    bits = [b for b in (d.get("code"), d.get("base")) if b]
    when = d.get("when") or {}
    if when:
        bits.append(" ".join(f"{k}={v}" for k, v in sorted(when.items()))[:40])
    return f"{key}" + (f"  [{' · '.join(bits)}]" if bits else "")


def _fmt(v, unit: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:,.4g}".replace(",", " ") + (f" {unit}" if unit else "")


def _proposal_diff(store, row) -> dict:
    """Чем предложение отличается от того, что уже лежит в хранилище.

    Это единственное, ради чего человек смотрит на приёмку: 256 фактов, из
    которых 203 не меняют ничего, — не предмет решения. Предмет — те
    двенадцать, что меняют значение, и те сорок один, которых не было.
    """
    payload = json.loads(row["payload"])
    facts = payload.get("facts", [])
    new = changed = same = 0
    sample: list[str] = []
    for f in facts:
        prev = store.get(f["domain"], f["key"], f.get("valid_from"))
        if prev is None:
            new += 1
            continue
        old, cur = prev["value"], f.get("value")
        if old is None or cur is None or abs((old or 0) - (cur or 0)) < 1e-9:
            same += 1
            continue
        changed += 1
        pct = f" ({(cur - old) / abs(old) * 100:+.1f}%)" if old else ""
        sample.append(f"{_fact_label(f)}: {_fmt(old, f.get('unit') or '')} → "
                      f"{_fmt(cur)}{pct}")

    # Находки схлопываются ПО ПРИЧИНЕ, а не по факту (решение 84): шесть
    # строк «нет курса GBP» — это одна причина и шесть адресов, и читать
    # надо адреса, а не повтор сообщения.
    by_cause: dict[str, dict] = {}
    share = ""
    for fd in payload.get("findings", []):
        if fd.get("level") != "info":
            continue
        if fd["code"].endswith("share"):
            # Это не повод, а показатель: доля выделенных строк. Смешивать
            # его с поводами значит печатать «выделено 0» там, где стоит
            # цифра, ради которой всё считалось.
            share = fd["message"]
            continue
        slot = by_cause.setdefault(fd["code"], {"message": fd["message"], "keys": []})
        if fd.get("key"):
            slot["keys"].append(fd["key"])
    blob = json.dumps([[f.get("domain"), f.get("key"), f.get("value"),
                        f.get("value_text")] for f in facts],
                      ensure_ascii=False, sort_keys=True)
    return {"total": len(facts), "new": new, "changed": changed, "same": same,
            "by_cause": by_cause, "sample_changed": sample, "facts": facts,
            "share": share,
            "findings": payload.get("findings", []),
            "hash": hashlib.sha256(blob.encode()).hexdigest()[:12]}


def _review_detail(store, pid: int, *, show_all: bool = False) -> int:
    """Подробный вид одного предложения: что именно меняется."""
    row = next((r for r in store.pending_proposals() if r["id"] == pid), None)
    if row is None:
        print(f"предложения #{pid} нет среди ждущих приёмки.")
        print("  список: fca review")
        return 2
    d = _proposal_diff(store, row)
    cap = 10**9 if show_all else 25
    print(f"#{pid}  {row['source_id']}  {row['created_at'][:16]}")
    print(f"  всего {d['total']} · новых {d['new']} · меняют значение "
          f"{d['changed']} · без изменений {d['same']}")

    if d["changed"]:
        print(f"\nМЕНЯЮТ ЗНАЧЕНИЕ — {d['changed']}. Здесь нужен глаз: "
              f"ошибка извлечения выглядит именно так.")
        for line in d["sample_changed"][:cap]:
            print("  " + line)
        if d["changed"] > cap:
            print(f"  …и ещё {d['changed'] - cap} — fca review {pid} --all")

    if d["new"]:
        print(f"\nНОВЫЕ — {d['new']}, по документам:")
        groups: dict[str, list] = {}
        for f in d["facts"]:
            if store.get(f["domain"], f["key"], f.get("valid_from")) is None:
                groups.setdefault(f["key"].split("/")[0], []).append(f)
        for pref, items in sorted(groups.items()):
            print(f"  {pref}: {len(items)}")
            for f in items[:3 if not show_all else 10**9]:
                print(f"    {_fact_label(f)} = "
                      f"{_fmt(f.get('value'), f.get('unit') or '')}")
            if len(items) > 3 and not show_all:
                print(f"    …и ещё {len(items) - 3}")

    if d["share"]:
        print(f"  {d['share']}")
    if d["by_cause"]:
        print("\nВЫДЕЛЕНО ГЕЙТОМ — по причинам:")
        for code, item in d["by_cause"].items():
            print(f"  {code}: {item['message']}")
            for k in (item["keys"] if show_all else item["keys"][:8]):
                print(f"    {k}")
            if len(item["keys"]) > 8 and not show_all:
                print(f"    …и ещё {len(item['keys']) - 8}")

    print(f"\n  принять:   fca review --accept {pid}")
    print(f"  отклонить: fca review --reject {pid}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fca")
    p.add_argument("--db", default="data/flightcost.db")
    p.add_argument("--registry", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="обновить справочники")
    r.add_argument("--reparse", action="store_true",
                   help="разобрать заново, даже если артефакт тот же: нужно, "
                        "когда изменился парсер, а не документ")
    r.add_argument("--due", action="store_true", help="только те, у кого подошёл срок")
    r.add_argument("--all", action="store_true")
    r.add_argument("--only", nargs="*")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--json", action="store_true")

    pb = sub.add_parser("publish", help="снимок справочника на сервер витрины")
    pb.add_argument("--host", default=None, metavar="deploy@адрес",
                    help="сервер; по умолчанию из переменной FCA_DEPLOY_HOST")
    pb.add_argument("--dry-run", action="store_true",
                    help="только собрать снимок и показать, что в нём; на сервер не слать")
    tp = sub.add_parser("tkp-pack",
                        help="упаковать выгрузку сообщества в JSON для репозитория")
    tp.add_argument("--src", default="data/raw/tkp",
                    help="где лежит сырая выгрузка *.xlsx (берётся самая новая)")
    tp.add_argument("--out", default="data/tkp/tkp_charges.json")
    tp.add_argument("--codes", default="data/codes/tkp_codes.yaml",
                    help="таблица соответствия кодов сообщества → ИКАО")
    s = sub.add_parser("status", help="свежесть источников")
    s.add_argument("--json", action="store_true")

    v = sub.add_parser("review", help="предложения, ждущие человека")
    v.add_argument("id", nargs="?", type=int, metavar="N",
                   help="показать предложение подробно: что меняется")
    v.add_argument("--accept", type=int)
    v.add_argument("--reject", type=int)
    v.add_argument("--all", action="store_true",
                   help="в подробном виде показать все строки, а не выборку")

    # Общие аргументы маршрута. Вынесены в родительский парсер, чтобы
    # `econ` и `explain` не разъехались: добавишь ключ здесь — он появится
    # в обеих командах сразу.
    route = argparse.ArgumentParser(add_help=False)
    route.add_argument("origin"); route.add_argument("destination")
    route.add_argument("--ac", default="A320", help="тип ВС из словаря FLEET")
    route.add_argument("--lf", type=float, default=0.80, help="загрузка, доля")
    route.add_argument("--fare", type=float, default=None, help="тариф, EUR/пасс")
    route.add_argument("--as-of", default=None,
                       help="дата справочников, YYYY-MM-DD")
    # Месяц рейса, а не дата справочника: as_of отвечает на вопрос «по
    # каким данным считаем», month — «когда летим». Умолчания нет
    # сознательно: незаданный месяц не превращается в июль, сезонные
    # правила просто не срабатывают, и разбор их называет.
    route.add_argument("--month", type=int, default=None, metavar="1-12",
                       choices=range(1, 13),
                       help="месяц вылета для сезонных ставок; без него "
                            "сезонные правила не срабатывают")
    # Ключ, которого не было, а предупреждение его звало: «запасной
    # аэродром не задан (--alternate-nm)». Ровно тот же случай, что был с
    # `--month`: величина принимается ядром, названа в предупреждении и
    # недостижима из командной строки.
    route.add_argument("--alternate-nm", type=float, default=None, metavar="NM",
                       help="расстояние до запасного аэродрома; без него в "
                            "запасе топлива нет ухода и предельная "
                            "коммерческая нагрузка завышена")
    route.add_argument("--freq", type=float, default=None, metavar="N",
                       help="рейсов в неделю в одну сторону")
    route.add_argument("--util", default="fleet_average",
                       choices=["fleet_average", "dedicated", "marginal"],
                       help="как относить лизинг: типовой налёт перевозчика, "
                            "выделенный под маршрут борт, или борт уже оплачен")
    route.add_argument("--set", dest="overrides", action="append", metavar="КЛЮЧ=ЧИСЛО",
                       help="переопределить значение на этот расчёт, например "
                            "fleet_economics.A320.lease_eur_month=280000 "
                            "или enroute_rate.ED=95; в справочник не пишется")
    route.add_argument("--operator", default="*",
                       help="код перевозчика для его ставок эксплуатации")

    src = sub.add_parser("sources",
                         help="где опубликованы тарифы и когда сверялись")
    src.add_argument("--json", action="store_true")

    hm = sub.add_parser("heatmap", help="карта сборов за аэронавигацию по зонам")
    hm.add_argument("--out", default="docs/zones.html")
    hm.add_argument("--as-of", dest="hm_asof", default=None)
    hm.add_argument("--no-open", action="store_true")
    hm.add_argument("--world", action="store_true",
                    help="весь мир вместо Европы")

    rg = sub.add_parser("range", help="диаграмма «нагрузка — дальность»")
    rg.add_argument("aircraft")
    rg.add_argument("--operator", default="*")
    rg.add_argument("--points", type=int, default=9)

    bn = sub.add_parser("bench", help="полоса флотской экономики: Form 41 США и IATA ACMG "
                                      "против заготовки")
    bn.add_argument("aircraft", nargs="?", default=None,
                    help="тип ИКАО; без него — сводка по всем типам выборки")
    bn.add_argument("--year", type=int, default=None,
                    help="год отчётности; по умолчанию последний полный")
    bn.add_argument("--operator", default="*")
    bn.add_argument("--carriers", action="store_true",
                    help="строки перевозчиков, из которых сложена полоса")

    ob = sub.add_parser("observe",
                        help="забрать наблюдения эксплуатации за сутки")
    ob.add_argument("--day", default=None, metavar="ГГГГ-ММ-ДД",
                    help="сутки забора; по умолчанию вчерашние — сегодняшние "
                         "ещё не закончились")
    ob.add_argument("--airports", default=None, metavar="ИКАО,ИКАО",
                    help="список через запятую; по умолчанию встроенный")
    ob.add_argument("--back", type=int, default=7, metavar="N",
                    help="на сколько суток назад искать пробелы; забор "
                         "идемпотентен, поэтому догонять безопасно")
    ob.add_argument("--pause", type=float, default=1.2,
                    help="пауза между запросами, секунд")
    ob.add_argument("--aggregate", action="store_true",
                    help="свернуть накопленное в факты домена observed")
    ob.add_argument("--gaps", action="store_true",
                    help="какие борта наблюдались, но типа у них нет, "
                         "с разбивкой по перевозчикам")
    ob.add_argument("--since", default=None, metavar="ГГГГ-ММ-ДД",
                    help="для --gaps: считать только с этой даты")
    ob.add_argument("--check", action="store_true",
                    help="один пробный запрос: показать ключи, токен и ответ "
                         "целиком, ничего не записывая")

    fl = sub.add_parser("flow", help="модель потока по населению (решение 214): "
                                     "коэффициенты, ошибка, оценка пары")
    fl.add_argument("--pair", default=None, metavar="A-B",
                    help="оценка пары (ИКАО) и, если есть, опубликованный поток рядом")

    bu = sub.add_parser("burn", help="сверка расхода openap с опубликованной эксплуатацией "
                                     "(решение 225)")
    bu.add_argument("--calib", action="store_true",
                    help="таблица: опубликовано ÷ модель по Aircraft Commerce и Form 41")

    fr = sub.add_parser("fare", help="наблюдения рыночной цены из выгрузок")
    fr.add_argument("--dir", default="data/raw/market_fare",
                    help="где лежат выгрузки агрегатора")
    fr.add_argument("--list", action="store_true", dest="listing",
                    help="что уже накоплено: пары, полосы глубины, число дат")
    fr.add_argument("--state", default=None, action="append",
                    choices=["в справочнике", "наберётся", "только с пересадкой", "мало дат",
                             "ready", "pending", "via", "thin"],
                    help="с --list: только пары в этом состоянии; можно несколько раз")
    fr.add_argument("--routes-out", default=None, metavar="ФАЙЛ.xlsx",
                    help="с --list: записать отобранные пары списком маршрутов "
                         "для tools/collect_prices.py (коды ИАТА)")
    fr.add_argument("--model", action="store_true",
                    help="формула цены по регионам (решение 212): постоянная часть, "
                         "ставка за 100 км, число пар и типичная ошибка")
    fr.add_argument("--aggregate", action="store_true",
                    help="свернуть накопленное в факты домена market_fare")
    fr.add_argument("--min-obs", type=int, default=5,
                    help="дат на полосу; меньше — не полоса, а несколько случаев")
    fr.add_argument("--why", default=None, metavar="ПАРА",
                    help="почему по паре есть или нет полоса, по всем полосам "
                         "глубины: DME-OVB или UUDD-UNNT, направление как хранится")

    sv = sub.add_parser("serve", help="локальная витрина: ядро за JSON")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--no-warm", action="store_true",
                    help="не прогревать ядро при запуске")
    sv.add_argument("--public", action="store_true",
                    help="публичный режим: запись в справочник закрыта, гости "
                         "работают в своих местах по секретной ссылке")
    sv.add_argument("--guests", action="store_true",
                    help="включить рабочие места гостей и локально (data/user.db)")

    inv = sub.add_parser("data", help="витрина хранилища: что в нём лежит")
    inv.add_argument("--out", default="docs/data.html")
    inv.add_argument("--as-of", default=None)
    inv.add_argument("--no-open", action="store_true")

    m = sub.add_parser("map", help="карта данных: откуда что берётся")
    m.add_argument("--out", default="docs/architecture.html")
    m.add_argument("--no-open", action="store_true")

    e = sub.add_parser("econ", parents=[route], help="экономика маршрута")
    e.add_argument("--explain", metavar="PATH", nargs="?", const="auto",
                   default=None, help="заодно выгрузить разбор в HTML")

    sv = sub.add_parser("solve", parents=[route],
                        help="обратный расчёт: при каком значении параметра "
                             "маршрут выходит в ноль")
    sv.add_argument("--for", dest="param", required=True, metavar="ПАРАМЕТР",
                    help="что искать: lf, fare, freq или ключ вида "
                         "fleet_economics.A320.lease_eur_month")

    x = sub.add_parser("explain", parents=[route],
                       help="подробный разбор расчёта в HTML")
    x.add_argument("--out", metavar="PATH", default="auto",
                   help="куда положить файл (по умолчанию docs/<марш>-<дата>.html)")
    x.add_argument("--no-open", action="store_true",
                   help="не открывать в браузере")
    x.add_argument("--no-margins", action="store_true",
                   help="не считать запас прочности (быстрее)")

    nw = sub.add_parser("network",
                        help="симулятор авиакомпании: сеть из аэропортов, "
                             "N бортов одного типа, нужная доля рынка")
    nw.add_argument("airports", nargs="+", metavar="АЭРОПОРТ",
                    help="коды аэропортов; пары сложатся сами")
    nw.add_argument("--base", required=True,
                    help="база — её страна задаёт национальность перевозчика")
    nw.add_argument("--ac", default="A320", help="тип ВС")
    nw.add_argument("--fleet", type=int, required=True, metavar="N", help="бортов")
    nw.add_argument("--freq", action="append", metavar="ПАРА=N",
                    help="рейсов в неделю туда-обратно, напр. ALA-FRA=4; "
                         "без ключа частоты раскладываются поровну")
    nw.add_argument("--fare", action="append", metavar="ПАРА=EUR",
                    help="цена вместо рыночной медианы; ALA-FRA — оба "
                         "направления, если обратное не задано отдельно")
    nw.add_argument("--market-pax", action="append", metavar="ПАРА=ПАСС",
                    help="поток на паре в месяц, оба направления")
    nw.add_argument("--fare-mult", type=float, default=1.0,
                    help="наша цена к рыночной медиане, 0.9 = на 10%% ниже")
    nw.add_argument("--fare-conv", type=float, default=None,
                    help="переход от медианы дневных минимумов к среднему чеку; "
                         "не задан — по потоку пары: 1,2, на загруженных 2,0 (решение 210)")
    nw.add_argument("--lf", type=float, default=0.80,
                    help="загрузка, при которой считаются пороги")
    nw.add_argument("--alpha", type=float, default=None,
                    help="показатель S-кривой (допущение, по умолчанию 1.3)")
    nw.add_argument("--util", type=float, default=None, metavar="Ч/МЕС",
                    help="налёт борта; по умолчанию — типовой из справочника")
    nw.add_argument("--lease", type=float, default=None, metavar="EUR/МЕС",
                    help="ставка лизинга борта")
    nw.add_argument("--month", type=int, default=None, metavar="1-12")
    nw.add_argument("--as-of", default=None)
    nw.add_argument("--operator", default="*")
    nw.add_argument("--set", dest="overrides", action="append", metavar="КЛЮЧ=ЧИСЛО")
    nw.add_argument("--json", action="store_true")

    a = p.parse_args(argv)
    # У `serve` поток на запрос, поэтому соединение открывается снятым с
    # привязки к потоку. ВТОРОГО соединения не заводим: две ручки к одному
    # файлу — лишний источник блокировок там, где хватает одной.
    store = Store(a.db, shared=(a.cmd == "serve"))
    registry = load_registry(a.registry) if a.registry else load_registry()

    if a.cmd == "refresh":
        reports = refresh_all(registry, store, force=a.all,
                              reparse=getattr(a, "reparse", False),
                              dry_run=a.dry_run, only=a.only)
        if not reports and not a.json:
            # Молчание неотличимо от успеха. Если обновлять нечего, это
            # надо сказать вслух и показать, когда будет что.
            from .refresh import next_due
            print("нечего обновлять: у всех источников срок ещё не подошёл")
            for row in next_due(registry, store)[:8]:
                print(f"  {row['source']:<24} через {row['days_left']:>4} дн."
                      f"   {row['message']}")
            print("\n  форсировать:  fca refresh --all")
            return 0
        if a.json:
            print(json.dumps(reports, ensure_ascii=False, indent=2))
        else:
            EXPLAIN = {
                "committed": "записано",
                "unchanged": "не изменилось",
                "proposal": "ждёт приёмки: fca review",
                "rejected": "отвергнуто гейтом",
                "skipped:not-implemented": "парсер не написан",
                "skipped:empty-directory": "папка пуста",
                "skipped:no-url": "нет адреса в реестре",
                "error:fetch": "не скачалось",
                "error:parse": "не разобралось",
                "error:package": "пакет не установлен",
                "external": "наполняется своим контуром",
                "committed:partial": "записано (часть документов отвергнута)",
            }
            for rep in reports:
                n = rep["stats"].get("added")
                tail = f"  {n} фактов" if n else ""
                print(f"{rep['source']:<24} {rep['outcome']:<26} "
                      f"{EXPLAIN.get(rep['outcome'], '')}{tail}")
                if rep.get("note"):
                    print(f"    {rep['note']}")
                for line in rep.get("summary", [])[:6]:
                    print(f"    · {line[:160]}")
                # Пять первых — по тяжести, не по порядку появления: иначе
                # пять info «нет курса GBP» вытесняют единственный error об
                # отвергнутом документе, и он не печатается вовсе.
                rank = {"error": 0, "warn": 1, "info": 2}
                fs = sorted(rep.get("findings", []),
                            key=lambda f: rank.get(f["level"], 3))
                for f in fs[:5]:
                    print(f"    [{f['level']}] {f['code']}: {f['message']}")
                if len(fs) > 5:
                    print(f"    … ещё {len(fs) - 5}, подробнее: fca review")
                if rep.get("error"):
                    print(f"    {rep['error'][:110]}")
                # Причина отказа разбора: при `error:parse` гейт не
                # запускался, находок нет, и печаталось одно «не
                # разобралось» — механизм, который не сработал, обязан
                # сказать почему (решение 37).
                if rep.get("rejected") and not fs:
                    for m in rep["rejected"][:5]:
                        print(f"    отвергнут: {m[:160]}")
        pend = len(store.pending_proposals())
        if pend and not a.json:
            print(f"\n{pend} предложений ждут ревью: fca review")
        return 0

    if a.cmd == "publish":
        return _publish(store, a)

    if a.cmd == "tkp-pack":
        # Сырая выгрузка сообщества остаётся у владельца; в репозиторий идёт её
        # упаковка: шесть аэронавигационных услуг, аэропорты с кодом ИКАО.
        import hashlib
        import json as _json
        from pathlib import Path as _P
        from .parsers import tkp_charges as _tkp
        src = _P(a.src)
        files = sorted(src.glob("*.xlsx"), key=lambda f: f.stat().st_mtime)
        if not files:
            print(f"в {src} нет выгрузки *.xlsx")
            return 2
        blob = files[-1].read_bytes()
        packed = _tkp.pack(blob, _tkp._codes({"codes_path": a.codes}),
                           hashlib.sha256(blob).hexdigest())
        out = _P(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(packed, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{files[-1].name} → {out}: {packed['airports']} аэропортов, "
              f"{len(packed['records'])} записей, {out.stat().st_size // 1024} КБ")
        if packed["unmapped_codes"]:
            print(f"  без кода сообщества→ИКАО и потому не упаковано: {packed['unmapped_codes']} "
                  f"аэропортов — дополнить {a.codes}, если нужны")
        print("  дальше: fca refresh --only tkp_charges")
        return 0

    if a.cmd == "status":
        rows = freshness_report(store, registry)
        _map_check(store, a)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(f"{'состояние':<9} {'возраст':>8} {'SLA':>6}  {'источник':<24} последнее")
            for row in rows:
                age = "—" if row["age_days"] is None else f"{row['age_days']}d"
                st = store.source_state(row["source"])
                # Свежесть и исправность — разные вещи. Источник может быть
                # «never» и потому, что его не запускали, и потому, что он
                # падает третий раз подряд. Без этой колонки не различить.
                last = f"{st['status']}: {st['message']}" if st else "не запускался"
                print(f"{row['state']:<9} {age:>8} {str(row['sla'])+'d':>6}  "
                      f"{row['source']:<24} {last[:52]}")
            # Ждущие приёмки — единственное в этом выводе, что требует
            # действия ПРЯМО СЕЙЧАС, и его тут не было вовсе: столбец
            # «последнее» описывает событие, а не состояние очереди, и
            # «proposal #9» оставалось там после того, как предложение
            # приняли. Спрашиваем очередь, а не память о ней.
            pend = store.pending_proposals()
            if pend:
                print(f"\nждут приёмки: "
                      + ", ".join(f"#{r['id']} {r['source_id']}" for r in pend))
                print(f"  посмотреть: fca review {pend[0]['id']}")
        return 0

    if a.cmd == "review":
        if a.accept or a.reject:
            pid = a.accept or a.reject
            try:
                store.resolve_proposal(pid, bool(a.accept), "via cli")
            except KeyError:
                # Голая трассировка на несуществующий номер — отказ того же
                # класса, что и всё остальное здесь: сообщение обязано
                # называть, что не так и что делать.
                left = [r["id"] for r in store.pending_proposals()]
                print(f"предложения #{pid} нет.")
                print("  ждут приёмки: " + (", ".join(f"#{i}" for i in left)
                                            if left else "ни одного"))
                return 2
            print(f"{'принято' if a.accept else 'отклонено'} #{pid}"); return 0
        if a.id:
            return _review_detail(store, a.id, show_all=a.all)
        pending = store.pending_proposals()
        if not pending:
            print("предложений на приёмке нет")
            print("  проверить состояние источников:  fca status")
            return 0
        # Список отвечает на «что изменится», а не «сколько строк приехало».
        # Прежний вид печатал число фактов и одну и ту же находку шесть раз
        # подряд: принять такое можно только вслепую, а приёмка вслепую —
        # это решение 4, выполненное формально и пустое по существу.
        by_hash: dict[str, list[int]] = {}
        for row in pending:
            d = _proposal_diff(store, row)
            by_hash.setdefault(d["hash"], []).append(row["id"])
            print(f"#{row['id']}  {row['source_id']}  {row['created_at'][:16]}"
                  f"  ·  {d['total']} фактов")
            print("    " + " · ".join(
                f"{n} {w}" for n, w in (
                    (d["new"], "новых"), (d["changed"], "меняют значение"),
                    (d["same"], "без изменений"))
                if n) or "    нечего менять")
            if d["share"]:
                pct = re.search(r"\(([\d.,]+)%\)", d["share"])
                loud = pct and float(pct.group(1).replace(",", ".")) > 10
                print(f"    {d['share']}"
                      + ("  ← это уже распределение, а не исключения "
                         "(решение 96)" if loud else ""))
            for code, items in d["by_cause"].items():
                keys = ", ".join(items["keys"][:3])
                more = f", +{len(items['keys']) - 3}" if len(items["keys"]) > 3 else ""
                print(f"    выделено {len(items['keys'])}: {items['message']}"
                      + (f" — {keys}{more}" if keys else ""))
            if d["changed"]:
                for line in d["sample_changed"][:2]:
                    print(f"      {line}")
        for h, ids in by_hash.items():
            if len(ids) > 1:
                print("\n  ! одинаковое содержимое: "
                      + ", ".join(f"#{i}" for i in ids)
                      + " — повтор прогона. Принять стоит один, "
                        "остальные отклонить.")
        first = pending[0]["id"]
        print(f"\n  подробнее: fca review {first}")
        print(f"  принять:   fca review --accept {first}")
        print(f"  отклонить: fca review --reject {first}")
        return 0

    if a.cmd == "observe":
        from . import observe as _obs, observe_run
        from datetime import date as _date, timedelta as _td
        if a.check:
            print(observe_run.probe(
                _date.fromisoformat(a.day) if a.day else None))
            return 0
        if a.gaps:
            print(observe_run.gaps(store, since=a.since))
            return 0
        if a.aggregate:
            total = 0
            for kind in _obs.OBSERVED_QUANTITY:
                facts, thin = _obs.aggregate(store, kind)
                if facts:
                    st = store.commit_facts(facts)
                    total += st.get("added", 0)
                    print(f"{kind:14} агрегатов {len(facts)}, записано "
                          f"{st.get('added', 0)}")
                for t in thin[:5]:
                    print(f"{'':14} мало: {t}")
            # Кресла по типам наблюдённых бортов — для оценки потока
            # там, где статистики по парам нет (RU, KZ; решение 198).
            facts, thin = _obs.aggregate_seats(store)
            if facts:
                st = store.commit_facts(facts)
                total += st.get("added", 0)
                print(f"{'seats':14} агрегатов {len(facts)}, записано {st.get('added', 0)}")
            for t in thin[:5]:
                print(f"{'':14} мало: {t}")
            print(f"\nвсего записано {total}")
            return 0

        airports = ([x.strip().upper() for x in a.airports.split(",") if x.strip()]
                    if a.airports else observe_run.DEFAULT_AIRPORTS)
        # По умолчанию ДОГОНЯЕМ пропущенное, а не берём только вчера.
        # Забор идемпотентен — дедупликация по четвёрке отсекает повторы,
        # — поэтому переспросить безопасно, а не переспросить нельзя:
        # живой поток отдаёт настоящее, и пропущенные сутки не
        # восстанавливаются. Закрытый на ночь ноутбук, исчерпанный лимит,
        # упавший cron — все три лечатся одним и тем же.
        if a.day:
            days = [_date.fromisoformat(a.day)]
        else:
            gaps = store.unfetched_days(airports, back=a.back)
            days = [_date.fromisoformat(d) for d in gaps] or []
            if not days:
                print("пробелов за последние "
                      f"{a.back} суток нет — забирать нечего")
                return 0
            if len(days) > 1:
                print(f"незабранных суток: {len(days)} — "
                      + ", ".join(str(d) for d in days))
        cid, _sec = observe_run.credentials()
        if not cid:
            # Эндпоинт рейсов за интервал анонимно не отдаётся: параметр
            # времени игнорируется, и приходит отказ. Двадцать восемь
            # одинаковых отказов подряд — не отчёт, а шум, поэтому
            # останавливаемся здесь и называем причину один раз.
            print("ключей нет, а эндпоинт рейсов анонимно не отдаётся.")
            print("  ключи: страница учётной записи OpenSky -> API client")
            print("  export OPENSKY_CLIENT_ID=... OPENSKY_CLIENT_SECRET=...")
            print("  либо export OPENSKY_CREDENTIALS=~/…/credentials.json")
            print("  проверить: fca observe --check")
            return 2
        total = {"flights": 0, "added": 0, "duplicate": 0, "without_type": 0}
        for day in days:
            print(f"забор за {day}, аэропортов {len(airports)}")
            st = observe_run.run(store, day=day, airports=airports, pause=a.pause)
            for k in total:
                total[k] += st.get(k, 0)
            if st.get("halted"):
                # Лимит исчерпан: остальные сутки сегодня всё равно не
                # заберутся. Останавливаемся и говорим, что осталось, —
                # метки уже проставлены, завтрашний прогон продолжит с
                # того же места.
                print(f"\nостановлено: {st['halted']}")
                print("  незабранное сохранено: следующий прогон продолжит")
                break
        st = total
        left = observe_run.budget_left()
        print(f"\nрейсов {st['flights']}, строк {st['added']}, "
              f"дублей {st['duplicate']}, без известного типа "
              f"{st['without_type']}"
              + (f", бюджет {left}" if left is not None else ""))
        if left is not None and left < 400:
            # Считать надо кредиты, а не запросы: у эндпоинта рейсов цена
            # обращения зависит от длины окна, а нам нужны ровно сутки.
            print(f"  бюджет на исходе ({left}). Аэропортов в списке "
                  f"{len(airports)}, на сутки нужно вдвое больше обращений: "
                  f"сократите список ключом --airports или разнесите "
                  f"забор на несколько запусков — метки не дадут "
                  f"забрать одно дважды")
        if st["flights"] and st["without_type"] == st["flights"]:
            # Все борта без типа — значит реестр не загружен или пуст, и
            # главная строка (блок-время по типу) не собирается вовсе.
            # Молчать нельзя: накопление идёт, а половина смысла нет.
            # Сказать не только «плохо», но и где смотреть: у реестра
            # две разные беды — его нет вовсе и он есть, но не отвечает.
            n = store.count_keys("aircraft_registry")
            print(f"  ! ни у одного борта не определён тип. В реестре "
                  f"{n:,} бортов".replace(",", " "))
            print("    "
                  + ("реестр пуст: fca refresh --only aircraft_registry"
                     if not n else
                     "реестр не пуст — значит адреса не совпадают: проверьте "
                     "регистр (ожидается нижний) и дату начала действия"))
        return 0

    if a.cmd == "burn":
        from .burn_calib import report
        print("Сверка расхода openap (решение 225). Опубликовано ÷ модель: 1,00 — совпадение,\n"
              "больше 1 — модель занижает. Form 41 — выданное топливо с ВСУ и задержками,\n"
              "поэтому выше модели на 5–15 % и сравнивается ПОРЯДКОМ типов (столбцы /A320).\n")
        for line in report(store):
            print(line)
        cur = store.db.execute("SELECT key, value FROM facts WHERE domain='aircraft' "
                               "AND key LIKE '%/burn_calib' AND valid_to IS NULL").fetchall()
        print("\nдействующие поправки: " + (", ".join(f"{k.split('/')[0]} ×{v:.2f}" for k, v in cur)
                                          or "нет (fca refresh --only burn_calib)"))
        return 0

    if a.cmd == "flow":
        import math
        from . import traffic_model as _tmod
        from .fare_model import REGION_RU, _coords, _km
        sp = lambda v: f"{v:,.0f}".replace(",", " ")              # noqa: E731
        m = _tmod.fit(store)
        if not m.get("P"):
            print(_tmod.estimate(store, "", "", 0)[1])
            return 0
        names = {"T": "по потоку аэропортов (обе массы — статистика)",
                 "P": "по жителям (массы — население в 150 км)"}
        for k in ("T", "P"):
            if k not in m:
                continue
            mm, c = m[k], m[k]["coef"]
            print(f"модель {names[k]}: пар {mm['n']}, R² {mm['r2']:.2f}, ошибка в "
                  f"{mm['factor']:.1f} раза на своих парах, в {mm['factor_cv']:.1f} — на отложенных")
            print(f"  ln(поток/мес) = {c[0]:.2f} + {c[1]:.2f}·ln(масса A × B) "
                  f"{c[2]:+.2f}·ln(км/1000) {c[3]:+.2f}·ln²(км/1000)"
                  f"   [база: {REGION_RU.get(m['base'], m['base'])}]")
            ns = len(m["shifts"])
            sl = dict(zip(m.get("slopes", []), c[4 + ns:]))
            for g, s_ in zip(m["shifts"], c[4:4 + ns]):
                print(f"    {REGION_RU.get(g, g):22} сдвиг {s_:+.2f}"
                      + (f", степень по массе {c[1] + sl[g]:.2f}" if g in sl else ""))
        F = m.get("F") or {}
        if F.get("factor_cv"):
            print(f"модель по потоку аэропортов с поправкой на сам аэропорт: ошибка на отложенных "
                  f"парах в {F['factor_cv']:.1f} раза (проверено на {F['n_eval']} парах, где у "
                  f"обоих аэропортов от {_tmod.MIN_AP_PAIRS} пар в статистике)")
        print("  пар по регионам: " + ", ".join(f"{REGION_RU.get(g, g)} {n}"
                                              for g, n in sorted(m["counts"].items(), key=lambda x: -x[1])))
        if a.pair:
            x, _, y = a.pair.upper().partition("-")
            xy = _coords(store)
            if x not in xy or y not in xy:
                print(f"{a.pair}: аэропорта нет в справочнике")
                return 2
            pax, why, c = _tmod.estimate_detail(store, x, y, _km(xy[x], xy[y]))
            if pax is None:
                print(f"\n{a.pair}: {why}")
                return 0
            print(f"\n{a.pair}: модель ≈ {sp(pax)} пасс./мес — {why}")
            print("  как посчитано (логарифмы):")
            for e in c["ends"]:
                how = ("поток по статистике" if e["how"] == "stat" else
                       f"{sp(e['pop'])} жителей × {e['ratio']:.2f}")
                print(f"    масса {e['code']}: {sp(e['mass'])} пасс./мес ({how})")
            print(f"    уровень региона ({c['region']}): {c['c']:+.2f} {c['shift']:+.2f}")
            print(f"    размер: {c['alpha']:.2f} × {c['mass_term'] / c['alpha']:.2f} = {c['mass_term']:+.2f}")
            print(f"    расстояние: {c['b1']:+.2f} × {c['ld']:.2f} {c['b2']:+.2f} × {c['ld'] ** 2:.2f} "
                  f"= {c['dist_term']:+.2f}")
            if c["mu"]:
                print(f"    поправки аэропортов: {c['mu']['a']:+.2f} (по {c['mu']['na']} парам) "
                      f"{c['mu']['b']:+.2f} (по {c['mu']['nb']})")
            print(f"    сумма {c['ln']:.2f} → e^{c['ln']:.2f} ≈ {sp(c['pax'])} пасс./мес")
            from .traffic import published
            pub = published(store, x, y)
            if pub:
                print(f"  опубликовано {sp(pub['pax_month'])} пасс./мес — модель "
                      f"× {pax / pub['pax_month']:.2f} к факту")
        return 0

    if a.cmd == "fare":
        from . import market_fare as _mf
        if a.why:
            # Одна пара целиком вместо «…и ещё 2066»: механизм, который
            # чего-то не сделал, обязан дать спросить, чего именно.
            print("\n".join(_mf.explain(store, a.why, min_obs=a.min_obs)))
            return 0
        if a.model:
            from . import fare_model as _fm
            m = _fm.fit(store)
            if not m:
                print("формулы нет: свёрнутых прямых цен в EUR меньше "
                      f"{_fm.MIN_PAIRS} на регион — fca fare --aggregate")
                return 0
            print(f"{'регион':22} {'пар':>5} {'500 км':>8} {'1000 км':>8} {'3000 км':>8} "
                  f"{'степень':>8} {'ошибка':>7}")
            for g, v in sorted(m.items(), key=lambda kv: -kv[1]["n"]):
                p_ = lambda km: _fm.predict(v, km)                  # noqa: E731
                print(f"{_fm.REGION_RU.get(g, g):22} {v['n']:>5} {p_(500):>8.0f} {p_(1000):>8.0f} "
                      f"{p_(3000):>8.0f} {v['beta']:>8.2f} {v['mdape'] * 100:>6.0f}%")
            print("\nцена в EUR по формуле цена = A · км^степень; степень 1 — пропорционально "
                  "расстоянию, 0 — не зависит от него")
            print("\nошибка — медиана |оценка − наблюдение| / наблюдение по парам региона")
            return 0
        if a.listing:
            # Вопрос «что подтянулось» задавался, потому что ответить на
            # него было нечем: `fca fare` печатал число дублей и молчал о
            # содержимом. Счётчик — не отчёт.
            rows = store.db.execute(
                """SELECT key, COUNT(*) n, MIN(observed_at), MAX(observed_at)
                   FROM observations WHERE kind = ? GROUP BY key
                   ORDER BY key""", (_mf.KIND,)).fetchall()
            if not rows:
                print("наблюдений цены нет: fca fare")
                return 0
            # Отметка считается по наблюдениям, а не по справочнику: раньше
            # «нет, дат мало» печаталось у всего, что ещё не свёрнуто, и
            # свежий сбор на сотне дат читался как пустой. Главная полоса —
            # по правилу сети (решение 209): прямые, порядок FARE_BANDS.
            from .network import FARE_BANDS
            pairs: dict[str, dict] = {}
            for key, n, lo, hi in rows:
                pair, _, rest = key.partition("/")
                pairs.setdefault(pair, {})[rest] = n
            # В справочнике — именно эта полоса прямых, а не любая полоса
            # пары: свёрнутая когда-то полоса «с пересадкой» не делает
            # новую прямую посчитанной.
            live = {r[0] for r in store.db.execute(
                "SELECT key FROM facts WHERE domain='market_fare' "
                "AND valid_to IS NULL")}
            print(f"{'пара':14} {'дат':>5}  {'главная полоса (прямые)':<26} состояние")
            cnt = {"в справочнике": 0, "наберётся": 0, "только с пересадкой": 0, "мало дат": 0}
            alias = {"ready": "в справочнике", "pending": "наберётся", "via": "только с пересадкой",
                     "thin": "мало дат"}
            want = {alias.get(s, s) for s in a.state or []}
            picked = []
            for pair, items in sorted(pairs.items()):
                total = sum(items.values())
                main = next(((b, items[f"{b}/direct"]) for b in FARE_BANDS
                             if items.get(f"{b}/direct", 0) >= a.min_obs), None)
                via = any(k.endswith("/via") and v >= a.min_obs for k, v in items.items())
                if main and f"{pair}/{main[0]}/direct" in live:
                    state = "в справочнике"
                elif main:
                    state = "наберётся"
                elif via:
                    state = "только с пересадкой"
                else:
                    state = "мало дат"
                cnt[state] += 1
                if want and state not in want:
                    continue
                picked.append(pair)
                band = f"{main[0]}: {main[1]} дат" if main else "—"
                print(f"{pair:14} {total:>5}  {band:<26} {state}")
            if a.routes_out:
                # Сборщик говорит на ИАТА, хранилище — на ИКАО (решение 103):
                # обратный перевод по тому же указателю, что и при загрузке.
                back = {}
                for iata, icao in store.icao_of_iata().items():
                    back.setdefault(icao, iata)
                rows, lost = [], []
                for pr in picked:
                    o, _, d = pr.partition("-")
                    if o in back and d in back:
                        rows.append(f"{back[o]}-{back[d]}")
                    else:
                        lost.append(pr)
                import pandas as pd
                pd.DataFrame({"Направление": rows, "Кол-во рейсов": None,
                              "Дистанция, км": None}).to_excel(a.routes_out, index=False)
                print(f"\nсписок маршрутов: {a.routes_out}, направлений {len(rows)}"
                      + (f"; без кода ИАТА {len(lost)}: {', '.join(lost[:5])}" if lost else ""))
            print(f"\nпар {len(pairs)}: " + ", ".join(f"{k} {v}" for k, v in cnt.items() if v)
                  + f". Порог — {a.min_obs} дат на полосу; «наберётся» станет ценой после "
                  f"fca fare --aggregate")
            return 0
        if a.aggregate:
            rep: dict = {}
            facts, thin = _mf.aggregate(store, min_obs=a.min_obs, report=rep)
            thin = [t for t in thin if "цена неправдоподобна" not in t]
            st = store.commit_facts(facts) if facts else {}
            # Полоса с неправдоподобной ценой не публикуется, а прежняя её
            # запись аннулируется на всём интервале: в мире такой цены не
            # было, она была у нас (решение 222).
            for x in rep.get("suspect", []):
                store.db.execute("""UPDATE facts SET valid_to = valid_from
                                    WHERE domain = 'market_fare' AND key = ?
                                      AND valid_to IS NULL""", (x["key"],))
            store.db.commit()
            add, same = st.get("added", 0), st.get("unchanged", 0)
            # «Записано 0» читается как отказ, а означало «всё уже лежит».
            # Различать обязательно: это разные состояния (решение 67).
            print(f"полос {len(facts)}: записано {add}"
                  + (f", уже было {same}" if same else "")
                  + (", новых нет" if facts and not add else ""))
            sus = rep.get("suspect", [])
            if sus:
                print(f"  ! цена неправдоподобна для расстояния, не опубликовано: {len(sus)} — "
                      f"чужая подпись валюты или выброс агрегатора. Посмотреть пару: "
                      f"fca fare --why <пара>")
                for x in sus:
                    print(f"    {x['key']}: {x['value']:,.0f} {x['unit']} — {x['why']}".replace(",", " "))
            for t in thin[:8]:
                print(f"  мало наблюдений: {t}")
            if len(thin) > 8:
                print(f"  …и ещё {len(thin) - 8}")
            return 0
        d = Path(a.dir)
        files = sorted(d.glob("*.csv"))
        if not files:
            print(f"в {d} нет выгрузок. Положите туда raw_*.csv из "
                  f"tools/collect_prices.py")
            return 2
        # Перевод в ИКАО — здесь, а не в скрипте сбора: агрегатор говорит
        # на ИАТА, продукт на ИКАО (решение 103), и делать перевод должен
        # тот, кто знает указатель.
        to_icao = store.icao_of_iata()
        if not to_icao:
            print("указателя кодов нет: fca refresh --only airport_codes --all")
            return 2
        total = {"added": 0, "duplicate": 0}
        for f in files:
            dump = _mf.read_dump(f.read_bytes(), to_icao=to_icao)
            st = _mf.collect(store, dump)
            for k in total:
                total[k] += st.get(k, 0)
            note = (f", не переведено {len(st['untranslated'])}"
                    if st.get("untranslated") else "")
            if st.get("no_currency_column"):
                note += (f", валюта из ссылки у {st['currency_from_link']}"
                         if st.get("currency_from_link")
                         else ", БЕЗ ВАЛЮТЫ — строки пропущены")
            print(f"{f.name:28} минимумов {st['added']:>5}, "
                  f"дублей {st['duplicate']:>5}, пар {st['pairs']}{note}")
            for u in (st.get("untranslated") or [])[:5]:
                print(f"    без кода ИКАО: {u}")
        print(f"\nвсего: добавлено {total['added']}, дублей {total['duplicate']}")
        print("  свернуть в факты: fca fare --aggregate")
        return 0

    if a.cmd == "serve":
        from . import serve as _serve
        _serve.serve(store, registry, host=a.host, port=a.port,
                     warm=not a.no_warm, public=a.public,
                     guests=True if a.guests else None)
        return 0

    if a.cmd == "data":
        from . import inventory
        # Реестр нужен, чтобы показать ОБЪЯВЛЕННЫЕ, но пустые домены:
        # без них витрина показывала бы только успехи, а цена пустоты —
        # главное, что о таком домене можно сказать.
        store.registry = registry
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(inventory.build(store, a.as_of), encoding="utf-8")
        print(f"витрина хранилища: {out}")
        if not a.no_open:
            import webbrowser
            webbrowser.open(out.resolve().as_uri())
        return 0

    if a.cmd == "sources":
        import json as _j
        rows = []
        for f in sorted(Path("data/charges").glob("*.json")):
            try:
                d = _j.loads(f.read_text(encoding="utf-8"))
            except Exception:                          # noqa: BLE001
                continue
            rows.append({"icao": d.get("icao", f.stem),
                         "valid_from": d.get("valid_from", ""),
                         "checked_at": d.get("checked_at", ""),
                         "publisher": d.get("publisher", ""),
                         "url": d.get("source_url", ""),
                         "rules": len(d.get("rules", []))})
        if a.json:
            print(_j.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("тарифов нет: положи файлы в data/charges/")
            return 0
        print(f"{'аэропорт':<9} {'правил':>7} {'действует с':>13} "
              f"{'сверено':>11}  издатель")
        for r in rows:
            print(f"{r['icao']:<9} {r['rules']:>7} {r['valid_from']:>13} "
                  f"{r['checked_at'] or '—':>11}  {r['publisher'][:44]}")
            if r["url"]:
                print(f"          {r['url']}")
            else:
                print("          АДРЕС НЕ УКАЗАН — обновить будет нечем")
        return 0

    if a.cmd == "heatmap":
        from .heatmap import build, DEFAULT_BBOX
        as_of = a.hm_asof or date.today().isoformat()
        bbox = (-170.0, -55.0, 190.0, 78.0) if a.world else DEFAULT_BBOX
        html = build(store, as_of, "data/airspace/fir_zones.json", bbox=bbox)
        path = Path(a.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        print(f"карта: {path}  ({path.stat().st_size/1024:.0f} КБ)")
        if not a.no_open:
            import webbrowser
            webbrowser.open(path.resolve().as_uri())
        return 0

    if a.cmd == "bench":
        return _bench(store, a)

    if a.cmd == "range":
        from .econ import load_aircraft
        from .fuel import payload_range
        as_of = date.today().isoformat()
        try:
            ac = load_aircraft(store, a.aircraft, as_of, a.operator)
        except KeyError as exc:
            print(exc); return 1
        # Планер и аналог — из хранилища, тем же путём, что у расчёта
        # маршрута. Прежде сюда шёл только код, и `payload_range` брал
        # планер из библиотеки: свой тип получал «домик» библиотечного,
        # тип с другими массами — чужой конверт, а тип без физики не
        # считался вовсе. Молча.
        d = payload_range(ac.icao, ac.seats, points=a.points,
                          frame=ac.frame, ref=ac.burn_ref,
                          calib=ac.burn_calib[0] if ac.burn_calib else None)
        if d.get("error"):
            print("не считается:", d["error"]); return 1
        print(f"{ac.icao}: {ac.seats} кресел, {d['pax_mass_kg']:.0f} кг на "
              f"пассажира ({d['pax_mass_source']})")
        print(f"  планер: {ac.frame_source}; расход: "
              + (f"аналог {ac.burn_ref.analog}"
                 + (", тот же двигатель" if ac.burn_ref.same_engine else
                    f", якорь {ac.burn_ref.anchor_kg_per_h:,.0f} кг/ч")
                 if ac.burn_ref else "физика openap"))
        print(f"  снаряжённая {d['oew_t']:.1f} т, предельная взлётная "
              f"{d['mtow_t']:.1f} т\n")
        print(f"  {'пассажиров':>11} {'нагрузка':>10} {'дальность':>11} "
              f"{'миль за тонну':>15}")
        for c in d["curve"]:
            g = c.get("nm_per_tonne")
            mark = "  ← баки полны" if d.get("corner") is c else ""
            print(f"  {c['pax']:>11.0f} {c['payload_kg']/1000:>9.1f}т "
                  f"{c['range_nm']:>10.0f} nm {(f'{g:,.0f}' if g else '—'):>15}"
                  f"{mark}")
        if d.get("corner"):
            print(f"\n  До {d['corner']['pax']:.0f} пассажиров снятие нагрузки "
                  f"покупает дальность выгодно, дальше почти нет:")
            print(f"  борт уже не упирается в предельную массу, только в "
                  f"ёмкость баков.")
        return 0

    if a.cmd == "map":
        from .graph import to_html as map_html
        path = Path(a.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(map_html(registry), encoding="utf-8")
        print(f"карта: {path}")
        if not a.no_open:
            import webbrowser
            webbrowser.open(path.resolve().as_uri())
        return 0

    if a.cmd == "solve":
        from .solve import solve
        # `--month` и `--alternate-nm` живут в родительском парсере и до
        # `solve` не доезжали: ключ принимался и молча игнорировался.
        # Родительский парсер заведён ровно затем, чтобы команды не
        # разъезжались, и они разъезжались — не на разборе аргументов, а
        # на месте вызова.
        base = dict(aircraft=a.ac, load_factor=a.lf, fare_eur=a.fare,
                    as_of=a.as_of, freq_week=a.freq, util_mode=a.util,
                    month=a.month, alternate_nm=a.alternate_nm,
                    operator=a.operator, overrides=parse_set(a.overrides))
        sol = solve(store, a.origin, a.destination, param=a.param,
                    base_kwargs=base)
        if not sol.ok:
            print(f"не решается: {sol.note}")
            return 1
        def num(v):
            if v is None:
                return "—"
            return f"{v:,.3f}" if abs(v) < 10 else f"{v:,.0f}"
        was = num(sol.baseline)
        print(f"{a.origin}-{a.destination}, {a.ac}, загрузка {a.lf*100:.0f}%, "
              f"тариф {a.fare:,.0f} EUR")
        print(f"\n  {sol.param}")
        print(f"    сейчас        {was}")
        print(f"    безубыточно   {num(sol.value)}")
        if sol.baseline:
            d = (sol.value - sol.baseline) / sol.baseline * 100
            print(f"    запас         {d:+.1f}%")
        from .solve import implied_aircraft_value
        if "lease_eur_month" in sol.param and sol.value:
            # Число, которое пользователь проверит в Excel, обязано нести
            # свою формулу, подстановку и допущения. Иначе расхождение
            # закрывается перепиской, а не чтением.
            d = implied_aircraft_value(
                sol.value, terms=_lease_terms(getattr(a, "overrides", None)))
            print(f"    справочно     борт примерно за "
                  f"{d['value'] / 1e6:,.1f} млн EUR")
            print(f"      формула     {d['formula']}")
            print(f"      подстановка {d['subst']}")
            print("      допущения   " + ", ".join(
                f"{k} {v}" for k, v in d["terms"].items()))
            print("      если считать иначе:")
            for k, v in d["variants"].items():
                print(f"        {k:<38} {v / 1e6:>8,.1f} млн")
            print("      изменить:   --set lease_terms.annual_rate=0.09 "
                  "(months, balloon_share, in_advance)")
        if sol.curve:
            print(f"\n  {'значение':>14} {'прибыль рейса':>16}")
            for v, pr in sol.curve:
                mark = "  ← порог" if abs(v - sol.value) < 1e-9 else ""
                print(f"  {num(v):>14} {pr:>16,.0f}{mark}")
        print()
        print(f"\n  итераций: {sol.iterations}")
        return 0

    if a.cmd == "network":
        return _cmd_network(a, store)

    if a.cmd in ("econ", "explain"):
        res = route_economics(store, a.origin, a.destination, aircraft=a.ac,
                              load_factor=a.lf, fare_eur=a.fare, as_of=a.as_of,
                              freq_week=a.freq, util_mode=a.util,
                              operator=a.operator,
                              month=a.month, alternate_nm=a.alternate_nm,
                              overrides=parse_set(a.overrides),
                              freshness=freshness_report(store, registry))
        want = a.out if a.cmd == "explain" else a.explain
        if a.cmd == "econ":
            print(res.report())
        if want:
            mg = None
            if a.cmd == "explain" and not getattr(a, "no_margins", False) and a.fare:
                from .solve import margins
                mg = margins(store, a.origin, a.destination,
                             dict(aircraft=a.ac, load_factor=a.lf,
                                  fare_eur=a.fare, as_of=a.as_of,
                                  freq_week=a.freq, util_mode=a.util,
                                  operator=a.operator,
                                  overrides=parse_set(a.overrides)), a.ac)
            path = _write_explain(res, want, mg)
            print(f"\n  разбор: {path}")
            if a.cmd == "explain":
                print(f"  на выдуманных константах: "
                      f"{res.default_share()*100:.0f}% суммы")
                if not a.no_open:
                    import webbrowser
                    webbrowser.open(path.resolve().as_uri())
        return 2 if res.degraded else 0

    return 1


def _pairs_arg(items, cast=float) -> dict:
    """`ALA-FRA=4` → {"ALA-FRA": 4}. Ошибка формата — отказ, а не пропуск:
    молча потерянная частота дала бы сеть без пары и правдоподобный итог."""
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or "-" not in k:
            raise SystemExit(f"не понял «{it}»: нужно ПАРА=ЗНАЧЕНИЕ, напр. ALA-FRA=4")
        out[k.strip().upper()] = cast(v)
    return out


def _cmd_network(a, store) -> int:
    from dataclasses import asdict
    from .network import ALPHA, fleet_from_core, form_network, report, simulate

    ov = parse_set(a.overrides)
    pairs = form_network(store, a.airports, base=a.base, aircraft=a.ac,
                         as_of=a.as_of, month=a.month, overrides=ov,
                         operator=a.operator, user_fares=_pairs_arg(a.fare),
                         user_market=_pairs_arg(a.market_pax))
    ok = [p for p in pairs if p.status == "ok"]
    if not ok:
        print("сеть пуста — ни одной пары не осталось:")
        for p in pairs:
            print(f"  {p.key:<10}" + "; ".join(r["text"] for r in p.reasons))
        return 1
    fleet = fleet_from_core(route_economics, store, ok[0].a, ok[0].b,
                            aircraft=a.ac, as_of=a.as_of, month=a.month,
                            overrides=ov, operator=a.operator)
    try:
        net = simulate(pairs, fleet=fleet, fleet_n=a.fleet,
                       freq=_pairs_arg(a.freq, int) or None,
                       util_h_month=a.util, lease_eur_month=a.lease,
                       fare_mult=a.fare_mult, fare_conv=a.fare_conv,
                       lf_ref=a.lf, alpha=a.alpha if a.alpha is not None else ALPHA)
    except ValueError as exc:
        print(f"не посчитать: {exc}")
        for p in pairs:
            if p.status != "ok" or not p.priced:
                print(f"  {p.key:<10}" + "; ".join(r["text"] for r in p.reasons))
        return 1
    if a.json:
        print(json.dumps({"network": asdict(net),
                          "pairs": [asdict(p) for p in pairs]},
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(report(net, pairs, base=a.base.upper()))
    return 0


def _write_explain(res, want: str, margins=None) -> Path:
    """Пишет HTML-разбор. 'auto' даёт предсказуемое имя в docs/ — так
    накапливается история расчётов, а не один затираемый файл."""
    from .explain import to_html

    if want == "auto":
        path = Path("docs") / f"{res.origin}-{res.destination}-{date.today()}.html"
    else:
        path = Path(want)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_html(res, margins), encoding="utf-8")
    return path


if __name__ == "__main__":
    sys.exit(main())


# ── публикация справочника ────────────────────────────────────────────────
# Что из базы НЕ уходит на сервер (решения 147, 148).
PUBLISH_EXCLUDE_SOURCES = {
    "aircraft_user": "свои типы владельца — его сценарий, а не справочник",
    "aircraft_registry": "реестр бортов — нужен только свёртке наблюдений у владельца; "
                         "витрина его не читает, а это бо́льшая часть веса снимка",
}
# Медианы цен агрегатора (`market_fare`) публикуются: Data API Travelpayouts
# предназначен для информирования пользователей на сайте партнёра. Уходят
# только агрегаты; сырые предложения вычищаются вместе с таблицей
# observations ниже.
PUBLISH_CLEAR_TABLES = {
    "observations": "сырые наблюдения ADS-B и цен — в справочнике только агрегаты",
    "proposals": "очередь приёмки владельца",
    "artifacts": "ссылки на скачанные документы, включая подписную выгрузку сообщества",
    "review_ack": "отметки приёмки владельца",
}
SERVER_ROOT = "/srv/fca"


def _bench_model(store, icao: str, operator: str):
    """Ставки модели тем же путём, что у расчёта маршрута, или None."""
    from .econ import load_aircraft
    from .fleet import load as load_fleet
    from .overrides import Resolver
    today = date.today().isoformat()
    try:
        ac = load_aircraft(store, icao, today, operator)
    except KeyError:
        return None
    return load_fleet(Resolver(store=store, as_of=today, overrides={}), ac.icao,
                      operator=operator, mtow_t=ac.mtow_t, seats=ac.seats)


def _bench_reports(store, fe=None, leg=None) -> None:
    """Ставки по отчётности перевозчиков — рядом с полосой Form 41."""
    from . import bench
    rows = bench.reports(store)
    if not rows:
        return
    print("\n  Отчётность перевозчиков, EUR на блок-час (весь перевозчик, не тип; курс — сегодняшний):")
    print(f"  {'':5} {'год':>4} {'блок-ч':>10} {'плечо':>6} {'экипаж':>7} {'персонал':>9} "
          f"{'ТОиР':>6} {'ТОиР+влад.':>11}")
    f = lambda x: f"{x:,.0f}" if x else "—"
    for r in rows:
        bh = f"{r['block_h']:,.0f}" + ("*" if r["bh_estimated"] else " ")
        leg_ = f"{r['block_per_dep']:.1f}ч" if r["block_per_dep"] else "—"
        mark = "  ?" if r["unconfirmed"] else ""
        print(f"  {r['carrier']:5} {r['year']:>4} {bh:>10} {leg_:>6} {f(r['crew_per_bh']):>7} "
              f"{f(r['staff_per_bh']):>9} {f(r['maint_per_bh']):>6} {f(r['maint_own_per_bh']):>11}{mark}")
    print("  * блок-часы — оценка: налёт в сутки × средний парк × 365.  ? — есть величины "
          "с certainty=reading_unconfirmed, сверить по data/benchmarks/\n"
          "  экипаж — лётный и кабинный (easyJet — строкой, airBaltic — из ц/ASK); персонал — весь штат.\n"
          "  ТОиР по МСФО без тяжёлых форм (они в амортизации) — сравнивать сумму ТОиР + владение.")
    if fe is not None and leg:
        print(f"  заготовка на плече {leg:.1f} ч: экипаж {fe.effective_crew_per_h(leg):,.0f}, "
              f"ТОиР {fe.effective_maint_per_h(leg):,.0f} EUR на блок-час")


def _bench(store, a) -> int:
    """Полоса бенчмарка против заготовки (M11)."""
    from . import bench
    rows, meta = bench.carrier_rows(store, a.year)
    if not rows and not bench._load(store)["acmg"] and not bench.reports(store):
        print("бенчмарка нет: fca refresh --only form41 acmg_cost acmg_structure\n"
              "  файлы Form 41 — в data/raw/form41/, как скачать — в шпаргалке")
        return 1
    if meta["year"]:
        print(f"Form 41 США, {meta['year']} год (есть: {', '.join(map(str, meta['years']))})")
        for w in meta["scales"]["why"]:
            print(f"  масштаб: {w}")
    for code, why in (meta.get("overrides") or {}).items():
        print(f"  код {code}: {why}")
    if meta.get("dropped"):
        print(f"  кварталов перевозчик×тип без расходов (часы поданы, ТОиР или пилоты — ноль): "
              f"{meta['dropped']}, в полосу не входят")
    if meta["unmapped"]:
        print(f"  кодов типа без нашего ИКАО: {len(meta['unmapped'])} — "
              + "; ".join(f"{k} {v}" for k, v in list(meta["unmapped"].items())[:6]))

    if not a.aircraft:
        rate, why = bench.usd_per_eur(store, meta["year"])
        if not rate:
            print(f"  {why} — суммы в USD")
        k = (1 / rate) if rate else 1.0
        cur = "EUR" if rate else "USD"
        print(f"  {why}\n")
        print(f"  {'тип':5} {'перев.':>6} {'плечо':>6} {'налёт':>6}   {'ТОиР ' + cur + '/ч':>17}   "
              f"{'модель':>7}   {'лётный экипаж':>14}   {'владение ' + cur + '/мес':>17}")
        for icao in sorted({r["icao"] for r in rows}):
            b = bench.type_bench(store, icao, meta["year"])
            bd = b["bands"]
            fe = _bench_model(store, icao, a.operator)
            leg = bd["block_per_dep"].p50
            mm = f"{fe.effective_maint_per_h(leg):7,.0f}" if fe else "      —"
            print(f"  {icao:5} {bd['maint_per_bh'].n:6d} {leg:5.1f}ч {bd['util_h_month'].p50:6.0f}   "
                  f"{bd['maint_per_bh'].p50 * k:6,.0f} ({bd['maint_per_bh'].p25 * k:,.0f}–"
                  f"{bd['maint_per_bh'].p75 * k:,.0f})   {mm}   "
                  f"{bd['cockpit_per_bh'].p50 * k:14,.0f}   {bd['own_per_ac_month'].p50 * k:17,.0f}")
        print("\n  ТОиР — счёт 52990 на блок-час; «модель» — заготовка на плече выборки.\n"
              "  Один-два перевозчика — точка, а не полоса.\n"
              "  Подробно по типу: fca bench A320")
        _bench_reports(store)
        return 0

    icao = a.aircraft.upper()
    fe = _bench_model(store, icao, a.operator)
    b = bench.compare(store, icao, fe, a.year) if fe else bench.type_bench(store, icao, a.year)
    if not b:
        print(f"{icao}: в выборке нет ни Form 41, ни семейства ACMG")
        return 1
    print(f"\n{icao}" + (f" — {fe.note}" if fe else " — типа нет в справочнике, модели нет"))
    if b.get("fx"):
        print(f"  {b['fx']}")
    rate = b.get("usd_per_eur")
    if b["bands"]:
        leg = b["bands"]["block_per_dep"].p50
        print(f"  перевозчиков {b['bands']['maint_per_bh'].n}, среднее плечо выборки {leg:.2f} ч — "
              f"модель сравнивается на нём\n")
        print(f"  {'величина':46} {'p25':>9} {'медиана':>9} {'p75':>9}   {'модель':>9}")
        for m, (unit, label) in bench.METRICS.items():
            bd = b["bands"].get(m)
            if not bd:
                continue
            mod = (b.get("model") or {}).get(m)
            ms = f"{mod['usd']:9,.0f}  {mod['where']}" if mod else ""
            fmt = ",.1f" if bd.p50 < 20 else ",.0f"
            print(f"  {(label + ', ' + unit)[:46]:46} {bd.p25:9{fmt}} {bd.p50:9{fmt}} "
                  f"{bd.p75:9{fmt}}   {ms}")
        if rate:
            print(f"\n  суммы в USD; модель переведена по {rate:.4f} USD за EUR")
        if b.get("cabin_ratio"):
            print(f"  экипаж модели приведён к лётному: ÷ (1 + {b['cabin_ratio']:.2f}) — "
                  f"кабинный к лётному по структуре ACMG 2019")
        print("  владение — по балансу (аренда + амортизация): старый парк самортизирован,\n"
              "  для нового борта это нижняя оценка, а не ставка лизинга")
        for what, label in (("maint", "ТОиР"), ("cockpit", "лётный экипаж")):
            s = b["split"].get(what)
            if s is None:
                print(f"\n  {label}: структура «час + цикл» не измерена — меньше трёх "
                      f"перевозчиков или плечи слишком близки")
                continue
            if s.structure == "inconsistent":
                legs = [r["block_per_dep"] for r in b["carriers"]]
                lvl = [r[f"{what}_per_bh"] for r in b["carriers"]]
                print(f"\n  {label}: структура «час + цикл» по перевозчикам не выделяется — "
                      f"плечи {min(legs):.1f}–{max(legs):.1f} ч, а уровни на блок-час "
                      f"{min(lvl):,.0f}–{max(lvl):,.0f} USD: разница между перевозчиками\n"
                      f"  {'':{len(label)}}  больше влияния плеча (подбор дал отрицательную "
                      f"часть, остаток {s.residual:,.0f} USD/рейс). Структура заготовки остаётся допущением")
                continue
            print(f"\n  {label}: {s.per_h:,.0f} USD/ч + {s.per_cycle:,.0f} USD/рейс "
                  f"({s.note}"
                  + (f"; среднее отклонение {s.residual:,.0f} USD/рейс" if s.residual else "") + ")")
            if what == "maint" and fe and rate:
                print(f"  {'':{len(label)}}  модель: {fe.maint_eur_per_fh * rate:,.0f} USD/ч + "
                      f"{fe.maint_eur_per_fc * rate:,.0f} USD/рейс")
        if a.carriers:
            print(f"\n  {'перевозчик':28} {'бортов':>6} {'плечо':>6} {'налёт':>6} {'ТОиР/ч':>8} "
                  f"{'экипаж/ч':>9} {'владение/мес':>13}")
            for r in sorted(b["carriers"], key=lambda r: -r["block_h"]):
                print(f"  {(r['carrier'] + ' ' + r['name'])[:28]:28} {r['aircraft']:6.0f} "
                      f"{r['block_per_dep']:5.2f}ч {r['util_h_month']:6.0f} {r['maint_per_bh']:8,.0f} "
                      f"{r['cockpit_per_bh']:9,.0f} {r['own_per_ac_month']:13,.0f}")
    _bench_reports(store, fe, b["bands"]["block_per_dep"].p50 if b.get("bands") else 2.5)
    ac_ = b.get("acmg")
    if ac_:
        k = (1 / rate) if rate else None
        print(f"\n  IATA ACMG, семейство {ac_['family']} (FY2019 в ценах 2025): "
              f"{ac_['per_fh_usd']:,.0f} USD на лётный час ВСЕГО, с топливом и сборами"
              + (f" ≈ {ac_['per_fh_usd'] * k:,.0f} EUR" if k else ""))
        if ac_.get("leg_h"):
            print(f"  плечо выборки {ac_['leg_h']:.2f} ч (на цикл / на час) — сравнивать с "
                  f"итогом модели на блок-час на таком плече")
        if ac_["new_gen_note"]:
            print("  в сборе 2019 года почти только ceo/NG: для neo и MAX — верхняя оценка по топливу")
    return 0


def _publish(store, a) -> int:
    """Снимок справочника -> сервер витрины, подмена целиком.

    Снимок — резервной копией SQLite, а не копированием файла: копия файла
    во время `refresh` бывает рваной, резервная копия согласована всегда.
    Из снимка вычищается то, чему наружу нельзя, и это печатается — молча
    вырезанное выглядело бы как пропавшие данные. На сервере файл кладётся
    рядом и подменяется переименованием: гость не увидит половину базы.
    """
    import datetime as _dt
    import json as _json
    import os
    import shlex
    import sqlite3
    import subprocess
    import tempfile
    from pathlib import Path as _P

    tmp = _P(tempfile.mkdtemp(prefix="fca-publish-")) / "flightcost.db"
    dst = sqlite3.connect(tmp)
    store.db.backup(dst)
    cur = dst.cursor()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    gone = {}
    for sid, why in PUBLISH_EXCLUDE_SOURCES.items():
        n = cur.execute("SELECT COUNT(*) FROM facts WHERE source_id = ?", (sid,)).fetchone()[0]
        cur.execute("DELETE FROM facts WHERE source_id = ?", (sid,))
        gone[f"источник {sid}"] = (n, why)
    # История потока витрине не нужна: она считает на сегодня, а каждая
    # новая выгрузка закрывает прежние ряды — они остались бы в снимке
    # мёртвым весом (решение 197).
    n = cur.execute("SELECT COUNT(*) FROM facts WHERE domain = 'traffic' "
                    "AND valid_to IS NOT NULL").fetchone()[0]
    cur.execute("DELETE FROM facts WHERE domain = 'traffic' AND valid_to IS NOT NULL")
    gone["закрытые ряды потока"] = (n, "история выгрузок — витрине нужен только действующий ряд")
    for tbl, why in PUBLISH_CLEAR_TABLES.items():
        if tbl in tables:
            n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            cur.execute(f"DELETE FROM {tbl}")
            gone[f"таблица {tbl}"] = (n, why)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except Exception:                                        # noqa: BLE001
        commit = "?"
    facts = cur.execute("SELECT COUNT(*) FROM facts WHERE valid_to IS NULL").fetchone()[0]
    meta = {"published_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "code_commit": commit, "facts": str(facts),
            "excluded": _json.dumps({k: v[0] for k, v in gone.items()}, ensure_ascii=False)}
    cur.execute("CREATE TABLE IF NOT EXISTS publish_meta (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("DELETE FROM publish_meta")
    cur.executemany("INSERT INTO publish_meta VALUES (?, ?)", meta.items())
    dst.commit()
    cur.execute("VACUUM")
    ok = cur.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    if ok != "ok":
        print(f"снимок повреждён: {ok}")
        return 2

    print(f"снимок: {tmp} — {tmp.stat().st_size / 1e6:.1f} МБ, действующих фактов {facts}")
    for k, (n, why) in gone.items():
        if n:
            print(f"  убрано {k}: {n} — {why}")
    if a.dry_run:
        print("  --dry-run: на сервер не отправлено")
        return 0

    host = a.host or os.environ.get("FCA_DEPLOY_HOST")
    if not host:
        print("не задан сервер: --host deploy@адрес или переменная FCA_DEPLOY_HOST")
        return 2

    def run(cmd):
        print("  $", " ".join(shlex.quote(c) for c in cmd))
        return subprocess.run(cmd).returncode

    root = SERVER_ROOT
    if run(["rsync", "-az", "--partial", str(tmp), f"{host}:{root}/incoming/flightcost.db.new"]):
        print("не отправилось: проверьте ssh до сервера")
        return 2
    # Геометрия — тоже данные витрины: без data/geo нет глобуса, без
    # data/airspace нет зон аэронавигации, и расчёт на сервере молча
    # уходил в «по вылету и прилёту пополам». Второй каталог уезжал бы
    # не раньше, чем кто-то заметил бы предупреждение на домене.
    for sub in ("data/geo", "data/airspace"):
        d = _P(sub)
        if d.is_dir():
            run(["rsync", "-az", "--delete", f"{d}/", f"{host}:{root}/site/{sub}/"])
        else:
            print(f"  нет каталога {sub} — на сервер не уедет")
    remote = (f"set -e; mv -f {root}/incoming/flightcost.db.new {root}/site/data/flightcost.db; "
              f"chgrp fca {root}/site/data/flightcost.db; chmod 664 {root}/site/data/flightcost.db; "
              f"sudo /usr/bin/systemctl restart fca; "
              f"for i in $(seq 1 20); do sleep 1; "
              f"curl -fsS http://127.0.0.1:8000/healthz && exit 0; done; "
              f"echo 'витрина не ответила'; exit 1")
    if run(["ssh", host, remote]):
        print("подмена прошла, но витрина не ответила: ssh на сервер и journalctl -u fca -n 50")
        return 2
    print("\nопубликовано")
    return 0
