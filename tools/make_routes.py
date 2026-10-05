#!/usr/bin/env python3
"""Файл маршрутов для парсера билетов — из наблюдений, где они есть, и из
перебора тарифных аэропортов, где их нет.

Парсер ждёт пары в кодах ИАТА. Наблюдения ADS-B копятся в ИКАО. Перевод
делает указатель кодов (домен `airport_code`), и делает его ОДИН раз
здесь: разбросанный по вызывающим, он разойдётся.

Почему из наблюдений, а не из списка аэропортов. Список даёт узлы, а
нужны линии; сто сорок четыре аэропорта — это двадцать тысяч пар, из
которых летают сотни. Наблюдения знают, какие именно, и это знание
накапливается само.

ПОЧЕМУ НЕ ТОЛЬКО ИЗ НАБЛЮДЕНИЙ. Наблюдение было условием попадания в
файл, и это молча выкидывало Россию и Китай целиком: там сорок один
разобранный тариф и ни одного приёмника. Слепота приёмников — свойство
сети сбора, а не маршрутов, и список маршрутов не должен её наследовать.
Поэтому второй источник строк — перебор: аэропорты с разобранным тарифом,
по которым наблюдений НЕТ, попарно внутри государства и между узлами
разных государств. Такая строка помечена в файле как перебор, а не как
наблюдение: число рейсов у неё не ноль, а «неизвестно» (решение 67).

    python3 tools/make_routes.py --min-days 3 --top 40
    python3 tools/make_routes.py --hubs EDDF,UUEE,ULLI,ZBAA,ZSPD --blind-top 60

Файл строится заново при каждом запуске, прежний перезаписывается:
состояния между запусками нет, что не названо в этом запуске — в файл не
попадёт. Собранные цены при этом не пропадают, они в хранилище.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp.store import Store           # noqa: E402
from flightcostapp.econ import great_circle_nm  # noqa: E402  одна реализация, решение 102


def _geo(st) -> dict[str, dict]:
    """ИКАО -> координаты и государство, из домена `airport`.

    Та же раскладка `value_text`, что читает `serve.airports`:
    «lat,lon|ИКАО|iso|название».
    """
    out = {}
    for txt, in st.db.execute(
            "SELECT value_text FROM facts WHERE domain = 'airport' "
            "AND valid_to IS NULL"):
        p = (txt or "").split("|", 3)
        if len(p) < 4 or not p[1]:
            continue
        try:
            lat, lon = (float(x) for x in p[0].split(",", 1))
        except (ValueError, IndexError):
            continue
        out[p[1]] = {"lat": lat, "lon": lon, "iso": p[2], "name": p[3]}
    return out


def _tariffed(st) -> set[str]:
    """Аэропорты с разобранным тарифом — ключ факта начинается с ИКАО."""
    return {(k or "").split("/")[0] for k, in st.db.execute(
        "SELECT DISTINCT key FROM facts WHERE domain = 'airport_charge' "
        "AND valid_to IS NULL")} - {""}


def _blind_pairs(st, seen: set[str], hubs: set[str], keep: set[str] | None,
                 nm_min: float, nm_max: float,
                 pool: set[str]) -> list[tuple[str, str, float, str]]:
    """Линии перебора — для аэропортов, которых наблюдения не видят.

    `pool` — откуда берутся узлы перебора: перечень владельца, тарифные
    аэропорты или их объединение (`--blind-from`). Названный узел входит в
    перебор всегда, даже если он наблюдается: Франкфурт виден приёмникам,
    Пекин нет, и линия Франкфурт–Пекин без этого не появилась бы ни
    из наблюдений (прилёт за пределами приёма), ни из перебора (один
    конец «зрячий»).

    Правило ЯВНОЕ, а не «первые N по алфавиту»:
      внутри государства — слепой аэропорт с узлом; без узлов — все пары
      слепых аэропортов;
      между государствами — только узел с узлом.
    Плечо ограничено полосой в милях: ниже — не летают, выше — не
    среднемагистральная экономика.
    """
    geo = _geo(st)
    ok = lambda a: a in geo and (not keep or a in keep)     # noqa: E731
    hubs = {h for h in hubs if ok(h)}
    blind = sorted(a for a in pool if a not in seen and ok(a) and a not in hubs)
    by_iso: dict[str, list[str]] = {}
    for a in blind:
        by_iso.setdefault(geo[a]["iso"], []).append(a)
    hubs_by_iso: dict[str, list[str]] = {}
    for h in sorted(hubs):
        hubs_by_iso.setdefault(geo[h]["iso"], []).append(h)

    def dist(a, b):
        return great_circle_nm(geo[a]["lat"], geo[a]["lon"],
                               geo[b]["lat"], geo[b]["lon"])

    out = []
    for iso, aps in by_iso.items():
        if hubs:
            cands = [(a, h) for a in aps for h in hubs_by_iso.get(iso, [])]
        else:
            cands = [(a, b) for i, a in enumerate(aps) for b in aps[i + 1:]]
        for a, b in cands:
            d = dist(a, b)
            if nm_min <= d <= nm_max:
                out.append((a, b, d, f"перебор {iso}"))
    hl = sorted(hubs)
    for i, a in enumerate(hl):
        for b in hl[i + 1:]:
            if geo[a]["iso"] == geo[b]["iso"]:
                continue
            d = dist(a, b)
            if nm_min <= d <= nm_max:
                out.append((a, b, d, f"перебор {geo[a]['iso']}-{geo[b]['iso']}"))
    # Порядок: сперва внутри государств по плечу — короткие линии частотнее
    # и цены по ним чаще есть, — затем межгосударственные узел–узел.
    return sorted(out, key=lambda r: ("-" in r[3], r[2]))


def _watchlist(st, as_of=None) -> set[str] | None:
    """Перечень из домена `airport_watch`, в обеих системах кодов."""
    icao = {k for k, in st.db.execute(
        "SELECT DISTINCT key FROM facts WHERE domain = 'airport_watch' "
        "AND valid_to IS NULL")}
    if not icao:
        return None
    iata = st.iata_of(as_of)
    return icao | {iata[i] for i in icao if i in iata}


def _airport_filter(spec: str | None) -> set[str] | None:
    """Список аэропортов, которыми ограничиваемся.

    Без него берутся любые наблюдавшиеся линии, а наблюдения идут по
    списку сбора ADS-B — то есть по двадцати восьми европейским узлам, а
    не по тем ста сорока семи, ради которых всё затевалось. Совпадения
    будут, но случайные.
    """
    if not spec:
        return None
    path = pathlib.Path(spec)
    if path.exists():
        import csv
        out = set()
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                for col in ("icao", "iata"):
                    if r.get(col):
                        out.add(r[col].strip().upper())
        return out
    return {x.strip().upper() for x in spec.split(",") if x.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/flightcost.db")
    ap.add_argument("--out", default="routes.xlsx")
    ap.add_argument("--min-days", type=int, default=3,
                    help="сколько суток линия должна встречаться")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--airports", default=None, metavar="ФАЙЛ|КОДЫ",
                    help="перечень вместо того, что в хранилище: путь к csv "
                         "или коды через запятую. По умолчанию берётся домен "
                         "`airport_watch` — перечень, который вы ведёте")
    ap.add_argument("--any-airport", action="store_true",
                    help="снять отбор совсем: любые наблюдавшиеся линии")
    ap.add_argument("--both-directions", action="store_true",
                    help="брать оба направления. По умолчанию одно: цены "
                         "туда и обратно различаются, но вдвое сокращать "
                         "охват ради этого стоит осознанно")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--blind-top", type=int, default=40,
                    help="сколько строк перебора добавить к наблюдённым; "
                         "0 — не добавлять")
    ap.add_argument("--blind-from", default="watch",
                    choices=["watch", "tariffed", "both"],
                    help="откуда узлы перебора: перечень владельца "
                         "(airport_watch), аэропорты с разобранным тарифом "
                         "или и те и другие")
    ap.add_argument("--hubs", default=None, metavar="ИКАО,ИКАО",
                    help="узлы для перебора: внутри государства берутся "
                         "только пары с узлом, между государствами — узел "
                         "с узлом. Без узлов — все пары внутри государства, "
                         "и это быстро становится перебором ради перебора")
    ap.add_argument("--nm", default="150,4000", metavar="МИН,МАКС",
                    help="полоса плеча для перебора в морских милях")
    a = ap.parse_args()

    st = Store(a.db)
    iata = st.iata_of(a.as_of)
    if not iata:
        print("указателя кодов нет: fca refresh --only airport_codes --all")
        return 2

    # РЕЙСЫ, а не сутки. Считать сутки было ошибкой: при нескольких днях
    # наблюдений почти все линии имеют одинаковый счёт, и «первые двадцать»
    # выбираются порядком вставки, то есть случайно. Строка частоты — одна
    # на рейс, поэтому сумма значений и есть число рейсов.
    days, flights = collections.Counter(), collections.Counter()
    for key, value in st.db.execute(
            "SELECT key, value FROM observations WHERE kind = 'frequency'"):
        pair = (key or "").split("/")[0]
        if "-" in pair:
            days[pair] += 1
            flights[pair] += value or 1
    if not days and not a.blind_top:
        print("наблюдений нет и перебор выключен: сначала fca observe "
              "или --blind-top")
        return 2

    # Перечень БЕРЁТСЯ ИЗ ХРАНИЛИЩА. Раньше он приходил файлом, который
    # я сделал разовым скриптом, и через месяц было бы не установить, тот
    # ли это список. Теперь у него есть источник, история и дата.
    keep = None if a.any_airport else (
        _airport_filter(a.airports) or _watchlist(st, a.as_of))
    rows, skipped, off_list, mirrored = [], [], [], []
    done_pairs: set[frozenset] = set()
    for pair, n_flights in flights.most_common():
        if days[pair] < a.min_days or len(rows) >= a.top:
            continue
        o, d = pair.split("-", 1)
        if keep and not (o in keep and d in keep):
            off_list.append(pair)
            continue
        if not a.both_directions:
            # Зеркало — не вторая линия, а та же с другим знаком. Из
            # двадцати мест пять уходили на повторы, и охват был вдвое
            # меньше заявленного.
            if frozenset((o, d)) in done_pairs:
                mirrored.append(pair)
                continue
            done_pairs.add(frozenset((o, d)))
        io_, id_ = iata.get(o), iata.get(d)
        if not (io_ and id_):
            # Линия не теряется молча: без кода ИАТА её нельзя спросить у
            # агрегатора, и знать об этом надо до запуска, а не после.
            skipped.append(f"{pair} ({'нет ' + o if not io_ else ''}"
                           f"{' нет ' + d if not id_ else ''})".strip())
            continue
        rows.append((f"{io_}-{id_}", int(n_flights), pair, "наблюдения"))

    # Перебор — для аэропортов, которых наблюдения не видят. Строки
    # помечены источником, число рейсов у них пусто: «не наблюдалось» и
    # «0 рейсов» — разные утверждения.
    # «Слепой» — аэропорт, не попавший ни в одну ВЫДАННУЮ строку: пара
    # с двумя наблюдениями за месяц отсеяна порогом и ничем не лучше
    # ненаблюдавшейся. Перечень владельца перебор не ограничивает:
    # разобранный тариф — более сильное основание, чем строка в списке;
    # явный `--airports` — ограничивает.
    seen_ap = {s for r in rows for s in r[2].split("-")}
    blind_rows = []
    if a.blind_top:
        hubs = {x.strip().upper() for x in (a.hubs or "").split(",") if x.strip()}
        nm_min, nm_max = (float(x) for x in a.nm.split(","))
        have = {r[2] for r in rows} | {"-".join(reversed(r[2].split("-"))) for r in rows}
        explicit = None if a.any_airport else _airport_filter(a.airports)
        watch_icao = {k for k, in st.db.execute(
            "SELECT DISTINCT key FROM facts WHERE domain = 'airport_watch' "
            "AND valid_to IS NULL")}
        pool = {"watch": watch_icao, "tariffed": _tariffed(st),
                "both": watch_icao | _tariffed(st)}[a.blind_from]
        if not pool:
            print(f"  ! перебор: источник узлов «{a.blind_from}» пуст")
        for o, d, dist_nm, why in _blind_pairs(st, seen_ap, hubs, explicit,
                                               nm_min, nm_max, pool):
            if len(blind_rows) >= a.blind_top:
                break
            if f"{o}-{d}" in have or f"{d}-{o}" in have:
                continue
            io_, id_ = iata.get(o), iata.get(d)
            if not (io_ and id_):
                skipped.append(f"{o}-{d} (перебор, нет кода ИАТА)")
                continue
            blind_rows.append((f"{io_}-{id_}", None, f"{o}-{d}", why, dist_nm))

    geo = _geo(st)
    def km(pair):
        o, d = pair.split("-", 1)
        if o in geo and d in geo:
            return round(great_circle_nm(geo[o]["lat"], geo[o]["lon"],
                                         geo[d]["lat"], geo[d]["lon"]) * 1.852)
        return None

    try:
        import openpyxl
    except ImportError:
        print("нужен openpyxl: pip install openpyxl")
        return 2
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Направление", "Кол-во рейсов", "Дистанция, км", "ИКАО", "Откуда строка"])
    for r in rows:
        ws.append([r[0], r[1], km(r[2]), r[2], r[3]])
    for r in blind_rows:
        ws.append([r[0], None, round(r[4] * 1.852), r[2], r[3]])
    wb.save(a.out)

    n_all = len(rows) + len(blind_rows)
    print(f"линий в файле: {n_all} — наблюдённых {len(rows)} "
          f"(из {len(days)} наблюдавшихся), перебором {len(blind_rows)}")
    print(f"  {a.out}")
    if a.blind_top and not blind_rows:
        # Механизм, который может ничего не дать, обязан сказать почему.
        print("  ! перебор не добавил ни одной строки: либо все тарифные "
              "аэропорты наблюдаются, либо полоса плеча или узлы отсекли всё")
    if keep:
        print(f"отсеяно не из списка: {len(off_list)}")
    else:
        print("  ! отбор снят: линии взяты любые наблюдавшиеся, и это "
              "почти наверняка не те, что нужны")
    if mirrored:
        print(f"пропущено зеркал: {len(mirrored)} "
              f"({', '.join(mirrored[:5])}) — вернуть ключом --both-directions")
    if skipped:
        print(f"пропущено без кода ИАТА: {len(skipped)}")
        for s in skipped[:8]:
            print(f"  {s}")
    # Запросов к агрегатору = линии × месяцы. Сказать заранее дешевле,
    # чем упереться в лимит на середине.
    print(f"\nзапросов при --months 6: {n_all * 6}")
    print(f"           при --months 12: {n_all * 12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
