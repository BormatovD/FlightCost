#!/usr/bin/env python3
"""Статья «Аэропортовые сборы: сколько стоит прилететь» — HTML на трёх языках.

Структура — research/STYLE.md; ориентир — как тариф аэропорта меняет расчёт рейса.

Читает ВСЕ файлы тарифов с документом (data/charges), проверку октябрьской волны
(verify/), контрольный оборот A320 (turnaround.json — bin/turnaround.py) и перечень
ненайденного (data/charges/_todo.yaml), пишет report.html, report.en.html, report.de.html.
Неофициальные данные сообщества (решение 227) в статью не входят.
Тексты — T(ru, en, de); строки из данных — i18n.yaml (Tr); деньги — money().

    python3 research/charges-2026-10/build_report.py      # из корня репозитория
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, Tr, article_title, calc_badge, chain, curname, e, mark,  # noqa: E402
                     money, n, page, whisker, write_all)

CHARGES = ROOT / "data" / "charges"
TURN = json.loads((HERE / "turnaround.json").read_text(encoding="utf-8"))["airports"]
TODO = yaml.safe_load((CHARGES / "_todo.yaml").read_text(encoding="utf-8")).get("not_found_2026_10_29") or {}
TR = Tr(HERE)
CYR = re.compile("[А-Яа-яЁё]")


def trd(s):
    """Строка из данных: с кириллицей — через i18n.yaml, латиница (имена собственные) — как есть."""
    return TR(s) if s and CYR.search(s) else s


# Город (ru, en, de) и регион — для подписи; регион определяет цвет полосы.
PLACE = {
    "EBBR": ("Брюссель", "Brussels", "Brüssel", "eu"), "EDDB": ("Берлин", "Berlin", "Berlin", "eu"),
    "EDDH": ("Гамбург", "Hamburg", "Hamburg", "eu"), "EDDL": ("Дюссельдорф", "Düsseldorf", "Düsseldorf", "eu"),
    "EFHK": ("Хельсинки", "Helsinki", "Helsinki", "eu"),
    "EGLL": ("Лондон, Хитроу", "London Heathrow", "London-Heathrow", "eu"),
    "EHAM": ("Амстердам", "Amsterdam", "Amsterdam", "eu"), "EKCH": ("Копенгаген", "Copenhagen", "Kopenhagen", "eu"),
    "ENGM": ("Осло", "Oslo", "Oslo", "eu"), "ESSA": ("Стокгольм", "Stockholm", "Stockholm", "eu"),
    "GCLP": ("Гран-Канария", "Gran Canaria", "Gran Canaria", "eu"),
    "GCTS": ("Тенерифе-Юг", "Tenerife South", "Teneriffa-Süd", "eu"),
    "LEAL": ("Аликанте", "Alicante", "Alicante", "eu"), "LEMD": ("Мадрид", "Madrid", "Madrid", "eu"),
    "LEMG": ("Малага", "Málaga", "Málaga", "eu"), "LGAV": ("Афины", "Athens", "Athen", "eu"),
    "LHBP": ("Будапешт", "Budapest", "Budapest", "eu"),
    "LIMC": ("Милан, Мальпенса", "Milan Malpensa", "Mailand-Malpensa", "eu"),
    "LKPR": ("Прага", "Prague", "Prag", "eu"), "LPFR": ("Фару", "Faro", "Faro", "eu"),
    "LPPT": ("Лиссабон", "Lisbon", "Lissabon", "eu"), "LSZH": ("Цюрих", "Zurich", "Zürich", "eu"),
    "LTAI": ("Анталья", "Antalya", "Antalya", "eu"), "LTFM": ("Стамбул", "Istanbul", "Istanbul", "eu"),
    "VOMM": ("Ченнаи", "Chennai", "Chennai", "in"), "DAAG": ("Алжир", "Algiers", "Algier", "af"),
    "DGAA": ("Аккра", "Accra", "Accra", "af"), "DNAA": ("Абуджа", "Abuja", "Abuja", "af"),
    "DNMM": ("Лагос", "Lagos", "Lagos", "af"), "FACT": ("Кейптаун", "Cape Town", "Kapstadt", "af"),
    "FAOR": ("Йоханнесбург", "Johannesburg", "Johannesburg", "af"), "HKJK": ("Найроби", "Nairobi", "Nairobi", "af"),
    "EDDM": ("Мюнхен", "Munich", "München", "eu"),
    "LFPG": ("Париж, Шарль-де-Голль", "Paris Charles de Gaulle", "Paris-Charles-de-Gaulle", "eu"),
    "LIRF": ("Рим, Фьюмичино", "Rome Fiumicino", "Rom-Fiumicino", "eu"),
    "HECA": ("Каир", "Cairo", "Kairo", "af"), "HAAB": ("Аддис-Абеба", "Addis Ababa", "Addis Abeba", "af"),
    "GMMN": ("Касабланка", "Casablanca", "Casablanca", "af"), "DTTA": ("Тунис", "Tunis", "Tunis", "af"),
    "VABB": ("Мумбаи", "Mumbai", "Mumbai", "in"), "VOHS": ("Хайдарабад", "Hyderabad", "Hyderabad", "in"),
    "VECC": ("Калькутта", "Kolkata", "Kolkata", "in"), "VAAH": ("Ахмадабад", "Ahmedabad", "Ahmedabad", "in"),
    "VOCI": ("Кочин", "Kochi", "Kochi", "in"), "VAPO": ("Пуна", "Pune", "Pune", "in"),
    "VOGO": ("Гоа, Даболим", "Goa Dabolim", "Goa-Dabolim", "in"), "VEGT": ("Гувахати", "Guwahati", "Guwahati", "in"),
    "VIJP": ("Джайпур", "Jaipur", "Jaipur", "in"), "VILK": ("Лакхнау", "Lucknow", "Lucknow", "in"),
    "VOGA": ("Гоа, Мопа", "Goa Mopa", "Goa-Mopa", "in"),
    "EDDF": ("Франкфурт", "Frankfurt", "Frankfurt", "eu"),
    "EGKK": ("Лондон, Гатвик", "London Gatwick", "London-Gatwick", "eu"),
    "EIDW": ("Дублин", "Dublin", "Dublin", "eu"), "EPPO": ("Познань", "Poznań", "Posen", "eu"),
    "LATI": ("Тирана", "Tirana", "Tirana", "eu"), "LEBL": ("Барселона", "Barcelona", "Barcelona", "eu"),
    "LEPA": ("Пальма", "Palma", "Palma", "eu"), "LIBR": ("Бриндизи", "Brindisi", "Brindisi", "eu"),
    "LICJ": ("Палермо", "Palermo", "Palermo", "eu"), "LIME": ("Бергамо", "Bergamo", "Bergamo", "eu"),
    "LOWW": ("Вена", "Vienna", "Wien", "eu"), "LPPR": ("Порту", "Porto", "Porto", "eu"),
    "OTHH": ("Доха", "Doha", "Doha", "as"), "RJAA": ("Токио, Нарита", "Tokyo Narita", "Tokio-Narita", "as"),
    "UAAA": ("Алматы", "Almaty", "Almaty", "ru"), "UIAA": ("Чита", "Chita", "Tschita", "ru"),
    "UIUU": ("Улан-Удэ", "Ulan-Ude", "Ulan-Ude", "ru"),
    "ULLI": ("Санкт-Петербург", "St Petersburg", "Sankt Petersburg", "ru"),
    "UNNT": ("Новосибирск", "Novosibirsk", "Nowosibirsk", "ru"), "URSS": ("Сочи", "Sochi", "Sotschi", "ru"),
    "USSS": ("Екатеринбург", "Yekaterinburg", "Jekaterinburg", "ru"),
    "UUDD": ("Москва, Домодедово", "Moscow Domodedovo", "Moskau-Domodedowo", "ru"),
    "UUEE": ("Москва, Шереметьево", "Moscow Sheremetyevo", "Moskau-Scheremetjewo", "ru"),
    "VANM": ("Нави-Мумбаи", "Navi Mumbai", "Navi Mumbai", "in"), "VIDP": ("Дели", "Delhi", "Delhi", "in"),
    "VOBL": ("Бангалор", "Bengaluru", "Bengaluru", "in"),
    "ZBAA": ("Пекин, Шоуду", "Beijing Capital", "Peking-Capital", "as"),
    "ZBAD": ("Пекин, Дасин", "Beijing Daxing", "Peking-Daxing", "as"),
    "ZGGG": ("Гуанчжоу", "Guangzhou", "Guangzhou", "as"), "ZGSZ": ("Шэньчжэнь", "Shenzhen", "Shenzhen", "as"),
    "ZHCC": ("Чжэнчжоу", "Zhengzhou", "Zhengzhou", "as"), "ZHHH": ("Ухань", "Wuhan", "Wuhan", "as"),
    "ZSAM": ("Сямынь", "Xiamen", "Xiamen", "as"),
    "ZSPD": ("Шанхай, Пудун", "Shanghai Pudong", "Shanghai-Pudong", "as"),
    "ZSSS": ("Шанхай, Хунцяо", "Shanghai Hongqiao", "Shanghai-Hongqiao", "as"),
    "ZUTF": ("Чэнду, Тяньфу", "Chengdu Tianfu", "Chengdu-Tianfu", "as"),
}


def city(icao: str) -> str:
    p = PLACE.get(icao)
    return T(*p[:3]) if p else ""


REGION = {"eu": (("Европа", "Europe", "Europa"), "var(--sky)"),
          "ru": (("Россия и Казахстан", "Russia and Kazakhstan", "Russland und Kasachstan"), "var(--blue)"),
          "as": (("Азия и Залив", "Asia and the Gulf", "Asien und Golfregion"), "var(--ink2)"),
          "in": (("Индия", "India", "Indien"), "var(--aqua)"),
          "af": (("Африка", "Africa", "Afrika"), "var(--green)")}
# Где тариф заведён не целиком: найдена только часть статей.
PAX_NF = ("пассажирский сбор (не найден)", "passenger charge (not found)", "Passagierentgelt (nicht gefunden)")
PARTIAL = {"DAAG": [PAX_NF], "DGAA": [PAX_NF]}
WHAT = {"landing": ("посадка", "landing", "Landung"), "noise": ("шум", "noise", "Lärm"),
        "noise_cat": ("шумовая категория типа", "type noise category", "Lärmkategorie des Typs"),
        "noise_cat_dep": ("шумовая категория на взлёте", "noise category on take-off", "Lärmkategorie beim Start")}


def files() -> list[dict]:
    """Все файлы тарифов аэропортов с документом; проверка — у тех, что сверены в октябре."""
    out = []
    for f in sorted(CHARGES.glob("[A-Z]*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        icao = d.get("icao") or ""
        if len(icao) != 4:                 # общегосударственные статьи (LI — муниципальный сбор Италии)
            continue
        vf = HERE / "verify" / f.name
        v = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else None
        t = TURN.get(icao) or {}
        out.append({"icao": icao, "file": f.name, "city": city(icao), "reg": PLACE[icao][3],
                    "rules": len(d.get("rules") or []), "wave": v is not None,
                    "checked": v["rules_checked"] if v else 0, "ok": v["rules_ok"] if v else 0,
                    "errors": len(v["errors"]) if v else 0, "checked_at": d.get("checked_at"),
                    "domestic": t.get("scenario") == "domestic_ru",
                    "valid_from": d.get("valid_from"), "publisher": d.get("publisher"),
                    "url": d.get("source_url"), "stale": "stale" in json.dumps(d, ensure_ascii=False),
                    "eur": t.get("eur"),
                    # Коды без перевода (parking_pier, ramp_infra) — как в данных, на всех языках.
                    "gaps": [T(*WHAT[x]) if x in WHAT else x for x in t.get("not_charged") or []]
                    + [T(*g) for g in PARTIAL.get(icao, [])]})
    return out


def turn_bars(fs) -> str:
    rows = sorted((x for x in fs if x["eur"]), key=lambda x: -x["eur"])
    top = max(x["eur"] for x in rows)
    out = []
    for x in rows:
        col = REGION[x["reg"]][1]
        sub = "; ".join(z for z in ((f"{T('без', 'without', 'ohne')}: {', '.join(x['gaps'])}" if x["gaps"] else ""),
                                     (T("внутренний рейс РФ", "Russian domestic flight", "russischer Inlandsflug")
                                      if x["domestic"] else "")) if z)
        cls = " part" if x["gaps"] else ""
        out.append(f'<div class="bar"><span class="bn"><b>{e(x["icao"])}</b> {e(x["city"])}</span><div class="track">'
                   f'<div class="fill{cls}" style="width:{x["eur"] / top * 100:.1f}%;background:{col}"></div></div>'
                   f'<div class="val">{money(x["eur"], nc=True)}{f"<small>{e(sub)}</small>" if sub else ""}</div></div>')
    lg = "".join(f'<span><i style="background:{c}"></i>{e(T(*nm))}</span>' for nm, c in REGION.values())
    return (f'<div class="lg">{lg}<span><i class="part"></i>{T("не всё начислено", "not all charged", "nicht alles berechnet")}'
            f'</span></div><div class="bars tb">{"".join(out)}</div>')


S = Sources(HERE)
REG = yaml.safe_load((CHARGES / "_regional.yaml").read_text(encoding="utf-8"))   # решение 234
sys.path.insert(0, str(ROOT))
from flightcostapp.econ import regional_charge_k  # noqa: E402
# Пример расчёта. Без тарифа калькулятор ставит параметрику 9,5 EUR · MTOW + 11 EUR · пассажир
# за рейс (econ.py, «обе константы выдуманы») — для A320 78 т и 148 пассажиров это и есть
# «оборот среднего аэропорта»: рейс несёт половину оборота каждого из двух аэропортов.
MTOW, PAX = 78, 148
PARAM = 9.5 * MTOW + 11.0 * PAX
FLIGHT_TOTAL = 13_429          # полная стоимость рейса A320 FRA–BCN в калькуляторе, EUR (30.10.2026)


def build() -> str:
    fs = files()
    found, miss = len(fs), len(TODO)
    checked = sum(x["checked"] for x in fs)
    ok = sum(x["ok"] for x in fs)
    with_err = [x["icao"] for x in fs if x["errors"]]
    full = [x for x in fs if x["eur"] and not x["gaps"]]
    eu = sorted(x["eur"] for x in fs if x["reg"] == "eu" and x["eur"])
    wave = [x for x in fs if x["wave"]]
    lo = min((x for x in full if not x["domestic"]), key=lambda x: x["eur"])   # тот же рейс из Франкфурта
    nreg = len({x["reg"] for x in fs})
    rs = REG["regions"]
    rmin = min(rs.values(), key=lambda r: r["k"])
    rmax = max(rs.values(), key=lambda r: r["k"])
    for x in fs:
        x["est"] = regional_charge_k(x["icao"])[0] * PARAM
    # Подпись источника — на языке статьи; номер — по первому упоминанию (как в русской версии):
    # Sources общий для трёх сборок, поэтому подпись задаётся явно при первом упоминании адреса в этой сборке.
    seen = set()
    for x in fs:
        if x["url"] and x["url"] not in seen:
            seen.add(x["url"])
            S.url(x["url"])
            S.title[x["url"]] = f"{x['icao']} — {trd((x['publisher'] or '').split(';')[0])}"
    steps = extracts = 0
    for f in (HERE / "trace").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            steps += 1
            extracts += o.get("kind") == "extract"
    cite = lambda icao: S.cite(next((x["url"] for x in fs if x["icao"] == icao and x["url"]), ""))  # noqa: E731
    ams, lag = TURN["EHAM"]["eur"], TURN["DNMM"]["eur"]
    rn = lambda r: e(TR(r["name"]))  # noqa: E731
    under = money(round((ams - PARAM) / 2, -1))
    over = money(round((PARAM - lo["eur"]) / 2, -1))
    p_lo = n((lo["eur"] - PARAM) / 2 / FLIGHT_TOTAL * 100)
    p_hi = n((lag - PARAM) / 2 / FLIGHT_TOTAL * 100)
    lo_c = e(lo["city"])
    lo_dom = T(", внутренний рейс", ", domestic flight", ", Inlandsflug") if lo["domestic"] else ""

    hook = f"""<h1>{T("Аэропортовые сборы: сколько стоит прилететь", "Airport charges: what it costs to fly in",
                    "Flughafenentgelte: was ein Anflug kostet")}</h1>
<p class="meta">{T(
        f"Исследование FlightCostApp, октябрь 2026 · {found} тарифов аэропортов из опубликованных документов —\n"
        f"всё, что есть в данных калькулятора · как сборы аэропорта меняют расчёт рейса",
        f"FlightCostApp research, October 2026 · {found} airport tariffs from published documents — everything in "
        f"the calculator's data · how airport charges change the cost of a flight",
        f"FlightCostApp-Recherche, Oktober 2026 · {found} Flughafentarife aus veröffentlichten Dokumenten — alles, was "
        f"in den Daten des Rechners steht · wie Flughafenentgelte die Flugkosten verändern")}</p>
{calc_badge("charges-2026-10")}
<div class="verdict">
<div><b>{T("Оценка — по региону", "Estimate by region", "Schätzung nach Region")}</b><span>{T(
        f"для аэропорта без тарифа калькулятор берёт медиану тарифов его региона: от\n"
        f"{money(rmin['median_eur'])} за оборот A320 ({rn(rmin)}) до {money(rmax['median_eur'])} ({rn(rmax)}); раньше\n"
        f"была одна на всех — {money(PARAM)}",
        f"for an airport without a tariff the calculator takes the median of its region's tariffs: from "
        f"{money(rmin['median_eur'])} per A320 turnaround ({rn(rmin)}) to {money(rmax['median_eur'])} ({rn(rmax)}); "
        f"before, one figure applied to all — {money(PARAM)}",
        f"für einen Flughafen ohne Tarif nimmt der Rechner den Median der Tarife seiner Region: von "
        f"{money(rmin['median_eur'])} je A320-Umlauf ({rn(rmin)}) bis {money(rmax['median_eur'])} ({rn(rmax)}); "
        f"bisher galt ein Wert für alle — {money(PARAM)}")}</span></div>
<div><b>{T("Европа", "Europe", "Europa")}: {money(eu[0])}–{money(eu[-1])}</b><span>{T(
        f"фактический оборот A320 по опубликованным тарифам {len(eu)}\n"
        f"аэропортов — от Дублина и Берлина до Будапешта и Амстердама",
        f"actual A320 turnaround at the published tariffs of {len(eu)} airports — from Dublin and Berlin to "
        f"Budapest and Amsterdam",
        f"tatsächlicher A320-Umlauf nach den veröffentlichten Tarifen von {len(eu)} Flughäfen — von Dublin und "
        f"Berlin bis Budapest und Amsterdam")}</span></div>
<div><b>{T("Лагос", "Lagos", "Lagos")} — {money(lag)}</b><span>{T(
        "в шесть раз выше прежней оценки: 100 USD с каждого вылетающего международного\nпассажира",
        "six times the old estimate: 100 USD per departing international passenger",
        "sechsmal so hoch wie die alte Schätzung: 100 USD je abfliegendem internationalem Passagier")
        }{cite('DNMM')}</span></div>
<div><b>{T(f"{found} тарифов в расчёте", f"{found} tariffs in the calculation", f"{found} Tarife in der Berechnung")
        }</b><span>{T(
        f"{nreg} регионов, у каждой ставки — документ и раздел; закрытые данные\nсообщества в статью не входят",
        f"{nreg} regions; every rate has its document and section; closed community data is not in the article",
        f"{nreg} Regionen, jeder Satz mit Dokument und Abschnitt; geschlossene Community-Daten sind nicht im Artikel")
        }</span></div></div>
<p class="lede">{T(
        f"Сборы аэропорта — плата за посадку, стоянку, пассажиров и досмотр. Рейс A320 оплачивает половину оборота\n"
        f"аэропорта вылета и половину оборота аэропорта прилёта. До этого исследования калькулятор для аэропорта без тарифа\n"
        f"ставил одну оценку на любой аэропорт — {money(PARAM)}, а если тариф был только у одного конца, второй не считал "
        f"вовсе. На деле разброс от {money(lo['eur'])} ({lo_c}{lo_dom})\nдо {money(lag)} (Лагос): в Амстердаме прежняя "
        f"оценка занижала рейс на {under}, в\n{lo_c} завышала на {over}. Рядом с полной стоимостью рейса такого "
        f"масштаба\n(Франкфурт — Барселона, около {money(round(FLIGHT_TOTAL, -2))}) ошибка была от {p_lo} % до\n"
        f"+{p_hi} %.",
        f"Airport charges are what an airline pays for landing, parking, passengers and security screening. An A320 "
        f"flight pays half the turnaround at the departure airport and half the turnaround at the arrival airport. "
        f"Before this research the calculator put one estimate on any airport without a tariff — {money(PARAM)}, and "
        f"if only one end had a tariff, it did not count the other at all. In reality the range runs from "
        f"{money(lo['eur'])} ({lo_c}{lo_dom}) to {money(lag)} (Lagos): in Amsterdam the old estimate understated the "
        f"flight by {under}, in {lo_c} it overstated it by {over}. Against the full cost of such a flight "
        f"(Frankfurt — Barcelona, about {money(round(FLIGHT_TOTAL, -2))}) the error ranged from {p_lo} % to "
        f"+{p_hi} %.",
        f"Flughafenentgelte sind die Zahlungen für Landung, Abstellen, Passagiere und Sicherheitskontrolle. Ein "
        f"A320-Flug zahlt die Hälfte des Umlaufs am Abflughafen und die Hälfte des Umlaufs am Zielflughafen. Vor "
        f"dieser Recherche setzte der Rechner für jeden Flughafen ohne Tarif dieselbe Schätzung an — {money(PARAM)}, "
        f"und hatte nur ein Ende einen Tarif, rechnete er das andere gar nicht. Tatsächlich reicht die Spanne von "
        f"{money(lo['eur'])} ({lo_c}{lo_dom}) bis {money(lag)} (Lagos): In Amsterdam unterschätzte die alte Schätzung "
        f"den Flug um {under}, in {lo_c} überschätzte sie ihn um {over}. Gemessen an den Gesamtkosten eines solchen "
        f"Flugs (Frankfurt — Barcelona, etwa {money(round(FLIGHT_TOTAL, -2))}) lag der Fehler zwischen {p_lo} % und "
        f"+{p_hi} %.")}</p>"""

    theory = f"""<section><h2>{T("Из чего складывается оборот", "What a turnaround is made of",
                                  "Woraus sich ein Umlauf zusammensetzt")}</h2>
{chain([(T("Посадка", "Landing", "Landung"),
         T("за тонну взлётной массы, часто со шумовой категорией и временем суток",
           "per tonne of take-off weight, often with a noise category and time of day",
           "je Tonne Startgewicht, oft mit Lärmkategorie und Tageszeit")),
        (T("Стоянка", "Parking", "Abstellen"),
         T("за тонну и час (или 15 минут, сутки) сверх бесплатного окна",
           "per tonne and hour (or 15 minutes, or day) beyond a free window",
           "je Tonne und Stunde (oder 15 Minuten, Tag) über ein freies Zeitfenster hinaus")),
        (T("Пассажиры", "Passengers", "Passagiere"),
         T("с каждого вылетающего: терминал, развитие аэропорта, помощь маломобильным",
           "per departing passenger: terminal, airport development, assistance for passengers with reduced mobility",
           "je abfliegendem Passagier: Terminal, Flughafenausbau, Hilfe für Personen mit eingeschränkter Mobilität")),
        (T("Безопасность", "Security", "Sicherheit"),
         T("досмотр пассажиров и багажа, тоже с вылетающего",
           "screening of passengers and baggage, also per departing passenger",
           "Kontrolle von Passagieren und Gepäck, ebenfalls je abfliegendem Passagier"))])}
<p>{T("Почти везде основная часть оборота — <b>пассажирские сборы</b> и досмотр, а не посадка по массе. Поэтому сборы\n"
      "растут с загрузкой, а не только с размером самолёта: полный A320 в Амстердаме стоит заметно дороже полупустого.",
      "Almost everywhere the bulk of a turnaround is <b>passenger charges</b> and security, not the weight-based landing "
      "charge. So charges grow with the load factor, not just with aircraft size: a full A320 in Amsterdam costs "
      "noticeably more than a half-empty one.",
      "Fast überall machen <b>Passagierentgelte</b> und Sicherheitskontrolle den Großteil des Umlaufs aus, nicht das "
      "gewichtsabhängige Landeentgelt. Deshalb steigen die Entgelte mit der Auslastung, nicht nur mit der "
      "Flugzeuggröße: Ein voller A320 kostet in Amsterdam spürbar mehr als ein halb leerer.")}</p>
<p>{T("Тариф публикует оператор аэропорта или регулятор (в Европе — по директиве 2009/12/EC, с ежегодными "
      "консультациями с авиакомпаниями), часть\nгосударственных сборов — в сборнике аэронавигационной информации страны "
      "(AIP, раздел GEN 4.1). Одна страна может\nиметь один документ на все аэропорты (Aena в Испании, ANA в Португалии, "
      "ACSA в ЮАР, FAAN в Нигерии).",
      "The tariff is published by the airport operator or the regulator (in Europe under Directive 2009/12/EC, with "
      "annual consultations with airlines); some government charges are in the country's Aeronautical Information "
      "Publication (AIP, section GEN 4.1). A country may have one document for all its airports (Aena in Spain, ANA "
      "in Portugal, ACSA in South Africa, FAAN in Nigeria).",
      "Den Tarif veröffentlicht der Flughafenbetreiber oder der Regulierer (in Europa nach der Richtlinie 2009/12/EG, "
      "mit jährlichen Konsultationen der Airlines); ein Teil der staatlichen Entgelte steht im Luftfahrthandbuch des "
      "Landes (AIP, Abschnitt GEN 4.1). Ein Land kann ein Dokument für alle Flughäfen haben (Aena in Spanien, ANA in "
      "Portugal, ACSA in Südafrika, FAAN in Nigeria).")}</p>
<p>{T("<b>Россия</b> — свои прейскуранты у каждого аэропорта, часто раздельно для российских и иностранных перевозчиков и\n"
      "для внутренних и международных линий; ставки заведены без НДС (налог — не сбор), у регулируемых аэропортов это\n"
      "предельные ставки ФАС. <b>Китай</b> — одна государственная схема CAAC: на внутренних линиях ставка зависит от "
      "класса\nаэропорта, на международных — одна на всю страну, поэтому оборот из Франкфурта во всех десяти китайских "
      "аэропортах\nодинаковый.",
      "<b>Russia</b>: each airport has its own price list, often separate for Russian and foreign carriers and for "
      "domestic and international routes; rates are entered without VAT (a tax, not a charge); at regulated airports "
      "these are the maximum rates set by the FAS (Russia's competition authority). <b>China</b>: one state scheme "
      "from the CAAC — on domestic routes the rate depends on the airport class, on international routes it is the "
      "same for the whole country, so a turnaround from Frankfurt is identical at all ten Chinese airports.",
      "<b>Russland</b>: Jeder Flughafen hat eine eigene Preisliste, oft getrennt für russische und ausländische "
      "Airlines sowie für Inlands- und Auslandsstrecken; die Sätze sind ohne MwSt. erfasst (eine Steuer, kein "
      "Entgelt), bei regulierten Flughäfen sind es die Höchstsätze des FAS (russische Wettbewerbsbehörde). "
      "<b>China</b>: ein staatliches Schema der CAAC — auf Inlandsstrecken hängt der Satz von der Flughafenklasse ab, "
      "auf Auslandsstrecken gilt einer für das ganze Land, deshalb ist ein Umlauf aus Frankfurt an allen zehn "
      "chinesischen Flughäfen gleich.")}</p></section>"""

    # Те же медианы, что в data/charges/_regional.yaml, — то, что считает калькулятор.
    col = {"europe": "var(--sky)", "russia_cis": "var(--blue)", "asia_gulf": "var(--ink2)", "india": "var(--aqua)",
           "africa": "var(--green)"}
    reg = [(f"{TR(r['name'])} · {r['n']}", r["median_eur"], tuple(r["range_eur"]), col.get(c, "var(--ink2)"))
           for c, r in rs.items()]
    reg.append((T("Прежняя оценка", "Old estimate", "Alte Schätzung"), PARAM, (PARAM, PARAM), "var(--orange)"))
    dots = whisker(reg, lo=0, hi=15000, ticks=(0, 2500, 5000, 7500, 10000, 12500, 15000),
                   fmt=lambda v: n(v), label_w=215, cur="EUR")
    analytics = f"""<section><h2>{T("Насколько оценка калькулятора далека от факта",
                                     "How far the calculator's estimate is from reality",
                                     "Wie weit die Schätzung des Rechners von der Wirklichkeit entfernt ist")}</h2>
<p>{T(f"Оборот A320 (78 т, 148 пассажиров, рейс из Франкфурта, июль) по всем тарифам в данных, {curname()}. Точка — медиана\n"
      "региона (теперь это и есть оценка калькулятора для аэропорта региона без тарифа), линия — от самого дешёвого\n"
      "аэропорта до самого дорогого; оранжевым — прежняя оценка, одна на всех. В выборку\n"
      "не вошли обороты, где не начислена посадка или пассажирский сбор (тариф заведён не целиком). Для российских\n"
      "аэропортов, где заведён прейскурант для российских перевозчиков, контрольный рейс — внутренний, из Шереметьева.",
      f"A320 turnaround (78 t, 148 passengers, flight from Frankfurt, July) at every tariff in the data, {curname()}. "
      "Dot — the regional median (this is now the "
      "calculator's estimate for an airport in that region without a tariff), line — from the cheapest airport to "
      "the most expensive; orange — the old one-size-fits-all estimate. Turnarounds where the landing or passenger "
      "charge is not computed (tariff only partly entered) are excluded. For Russian airports where the price list "
      "for Russian carriers is entered, the reference flight is domestic, from Sheremetyevo.",
      f"A320-Umlauf (78 t, 148 Passagiere, Flug ab Frankfurt, Juli) nach allen Tarifen in den Daten, {curname()}. "
      "Punkt — Median der Region (das ist jetzt "
      "die Schätzung des Rechners für einen Flughafen der Region ohne Tarif), Linie — vom günstigsten bis zum "
      "teuersten Flughafen; orange — die alte Einheitsschätzung. Nicht enthalten sind Umläufe, bei denen Lande- oder "
      "Passagierentgelt nicht berechnet ist (Tarif nur teilweise erfasst). Für russische Flughäfen, bei denen die "
      "Preisliste für russische Airlines erfasst ist, ist der Referenzflug ein Inlandsflug ab Scheremetjewo.")}</p>
{dots}
<h3>{T("По аэропортам", "By airport", "Nach Flughafen")}</h3>
<p>{T(f"Тот же оборот, посчитанный расчётным ядром калькулятора по каждому тарифу, {curname()}. Штриховка — где часть сборов не\n"
      "начислена: для посадки или шумового сбора нужна шумовая категория A320 по правилам аэропорта, а в справочнике её\n"
      "пока нет.",
      f"The same turnaround, computed by the calculator's engine for each tariff, {curname()}. Hatching marks where some "
      "charges are not computed: the landing or noise charge needs the A320's noise category under the airport's "
      "rules, and the aircraft type reference does not have it yet.",
      f"Derselbe Umlauf, vom Rechenkern des Rechners für jeden Tarif berechnet, {curname()}. Schraffiert — wo ein Teil der "
      "Entgelte nicht berechnet ist: Für Lande- oder Lärmentgelt braucht es die Lärmkategorie des A320 nach den "
      "Regeln des Flughafens, und im Typenverzeichnis fehlt sie noch.")}</p>
{turn_bars(fs)}
<p class="small">{T(
        "Ставки — в валюте документа, перевод по приблизительному курсу (только для сравнения). Временного ряда\n"
        "нет: тарифы собраны на одну дату, в Европе тарифы пересматриваются ежегодно.",
        "Rates are in the document's currency, converted at an approximate rate (for comparison only). There is no "
        "time series: tariffs were collected as of one date; in Europe tariffs are revised annually.",
        "Sätze in der Währung des Dokuments, umgerechnet zu einem ungefähren Kurs (nur zum Vergleich). Eine Zeitreihe "
        "gibt es nicht: Die Tarife sind zu einem Stichtag erfasst, in Europa werden sie jährlich überarbeitet.")
        }</p></section>"""

    stale = T("устарел", "outdated", "veraltet")
    dom = T("внутр. рейс", "domestic", "Inland")
    rows = "".join(
        f"<tr><td><b>{e(x['icao'])}</b></td><td>{e(x['city'])}{cite(x['icao'])}</td><td>{e(T(*REGION[x['reg']][0]))}</td>"
        f"<td class=r>{e(str(x['valid_from'] or ''))}{f' · <span class=warnw>{stale}</span>' if x['stale'] else ''}</td>"
        f"<td class=r>{money(x['eur'])}</td><td class=r>{money((x['eur'] - PARAM) / 2, sign=True) if x['eur'] else ''}</td>"
        f"<td class=r>{money((x['eur'] - x['est']) / 2, sign=True) if x['eur'] else ''}</td>"
        f"<td class=s>{e('; '.join(z for z in (', '.join(x['gaps']), dom if x['domestic'] else '') if z))}</td></tr>"
        for x in sorted(fs, key=lambda x: (x['reg'], -(x['eur'] or 0))))
    facts = f"""<section><h2>{T("Таблица для расчёта", "Table for the calculation", "Tabelle für die Berechnung")}</h2>
<details open><summary>{T(f"{found} тарифов — оборот A320 и поправка к рейсу",
                          f"{found} tariffs — A320 turnaround and the adjustment per flight",
                          f"{found} Tarife — A320-Umlauf und Korrektur je Flug")}</summary>
<div class="tw"><table><tr><th>ICAO</th><th>{T("Город", "City", "Stadt")}</th><th>{T("Регион", "Region", "Region")}</th>
<th class=r>{T("Действует с", "Valid from", "Gültig ab")}</th>
<th class=r>{T("Оборот A320", "A320 turnaround", "A320-Umlauf")}</th>
<th class=r>{T("Рейс к прежней оценке", "Flight vs old estimate", "Flug ggü. alter Schätzung")}</th>
<th class=r>{T("Рейс к оценке региона", "Flight vs regional estimate", "Flug ggü. Regionsschätzung")}</th>
<th>{T("Оговорки", "Caveats", "Vorbehalte")}</th></tr>{rows}</table></div></details>
<p class="small">{T(
        f"«Рейс к оценке», EUR — на сколько рейс в этот аэропорт или из него дороже (+) или дешевле (−), чем с\n"
        f"оценкой: (оборот − оценка) ÷ 2. Прежняя — {money(PARAM)} на любой аэропорт; оценка региона — медиана его "
        f"тарифов\n(для аэропорта с тарифом это просто показатель, насколько он типичен для региона). Номера — ссылки на "
        f"документ\nтарифа.",
        f"“Flight vs estimate”, EUR — how much more (+) or less (−) a flight to or from this airport costs than with "
        f"the estimate: (turnaround − estimate) ÷ 2. The old one is {money(PARAM)} for any airport; the regional "
        f"estimate is the median of the region's tariffs (for an airport with a tariff it simply shows how typical it "
        f"is for its region). The superscript numbers link to the tariff document.",
        f"„Flug ggü. Schätzung“, EUR — um wie viel ein Flug zu oder von diesem Flughafen teurer (+) oder günstiger (−) "
        f"ist als mit der Schätzung: (Umlauf − Schätzung) ÷ 2. Die alte — {money(PARAM)} für jeden Flughafen; die "
        f"Regionsschätzung — der Median der Tarife der Region (für einen Flughafen mit Tarif zeigt sie nur, wie "
        f"typisch er für seine Region ist). Die hochgestellten Nummern verlinken auf das Tarifdokument.")}</p></section>"""

    gaps = "".join(f"<tr><td><b>{e(k)}</b></td><td>{e(city(k))}</td><td>{e(TR(v))}</td></tr>"
                   for k, v in TODO.items())
    ks = ", ".join(f"{rn(r)} ×{n(r['k'], 2)}" for r in rs.values())
    kw = n(REG['world']['k'], 2)
    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator", "Was wir im Rechner ändern")}</h2>
<ol><li>{mark('in_calc')}{T(
        f"<b>{found} тарифов уже в данных</b> (<code>data/charges/</code>) — для этих аэропортов расчёт идёт по "
        f"документу, со\nссылкой на раздел.",
        f"<b>{found} tariffs are already in the data</b> (<code>data/charges/</code>) — these airports are calculated "
        f"from the document, with a reference to the section.",
        f"<b>{found} Tarife sind bereits in den Daten</b> (<code>data/charges/</code>) — diese Flughäfen werden nach "
        f"dem Dokument berechnet, mit Verweis auf den Abschnitt.")}</li>
<li>{mark('in_calc')}{T(
        f"<b>Оценка по региону вместо одной на всех</b> (решение 234). Для аэропорта без тарифа — медиана\n"
        f"региона: прежняя формула 9,5·MTOW + 11·пасс. × k региона ({ks};\nвне регионов ×{kw}), с оранжевой пометкой "
        f"«оценка». Африка держится на пяти тарифах из трёх\nдокументов — её множитель самый шаткий.",
        f"<b>An estimate by region instead of one for all</b> (decision 234). For an airport without a tariff — the "
        f"regional median: the old formula {n(9.5, 1)}·MTOW + {n(11)}·pax × the region's k ({ks}; outside the regions "
        f"×{kw}), flagged orange as “estimate”. Africa rests on five tariffs from three documents — its multiplier is "
        f"the shakiest.",
        f"<b>Schätzung nach Region statt einer für alle</b> (Entscheidung 234). Für einen Flughafen ohne Tarif — der "
        f"Median der Region: die alte Formel {n(9.5, 1)}·MTOW + {n(11)}·Pax × k der Region ({ks}; außerhalb der "
        f"Regionen ×{kw}), orange als „Schätzung“ markiert. Afrika stützt sich auf fünf Tarife aus drei Dokumenten — "
        f"sein Faktor ist der wackeligste.")}</li>
<li>{mark('in_calc')}{T(
        "<b>Оценка для «второго конца»</b> (решение 234). Если тариф есть только у одного аэропорта, второй\n"
        "считается оценкой его региона, и эта часть идёт в долю «выдуманного».",
        "<b>An estimate for the “other end”</b> (decision 234). If only one airport has a tariff, the other is costed "
        "at its region's estimate, and that part counts towards the “made-up” share.",
        "<b>Schätzung für das „andere Ende“</b> (Entscheidung 234). Hat nur ein Flughafen einen Tarif, wird der "
        "andere mit der Schätzung seiner Region gerechnet, und dieser Teil zählt zum Anteil des „Ausgedachten“.")}</li>
<li>{mark('on_input')}{T(
        "<b>Шумовая категория типа.</b> Без неё в Амстердаме, Брюсселе и Мальпенсе не начисляется посадка — добавить\n"
        "категорию в справочник типов по правилам аэропорта.",
        "<b>Type noise category.</b> Without it no landing charge is computed in Amsterdam, Brussels and Malpensa — "
        "add the category to the aircraft type reference under each airport's rules.",
        "<b>Lärmkategorie des Typs.</b> Ohne sie wird in Amsterdam, Brüssel und Malpensa kein Landeentgelt berechnet "
        "— die Kategorie nach den Regeln des Flughafens ins Typenverzeichnis aufnehmen.")}</li>
<li>{mark('on_input')}{T(
        "<b>Не помещается в схему</b> (пока вне расчёта): ночные надбавки, сборы за NOx и CO₂, поминутная стоянка, "
        "скидки за\nобъём и новые линии.",
        "<b>Does not fit the schema</b> (outside the calculation for now): night surcharges, NOx and CO₂ charges, "
        "per-minute parking, volume and new-route discounts.",
        "<b>Passt nicht ins Schema</b> (vorerst außerhalb der Berechnung): Nachtzuschläge, NOx- und CO₂-Entgelte, "
        "minutengenaues Abstellen, Mengen- und Neustreckenrabatte.")}</li></ol></section>"""

    errl = e(", ".join(with_err))
    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T(f"В статье — все {found} тарифов аэропортов, заведённых в калькулятор по опубликованным документам. Неофициальные\n"
      f"данные сообщества (таблица по российским аэропортам) участвуют в расчёте, но здесь не показываются: как они\n"
      f"собраны, проверить нельзя.",
      f"The article covers all {found} airport tariffs entered into the calculator from published documents. "
      f"Unofficial community data (the Russian airport-charges table of the Transport Clearing House, TKP) is used in the calculation but not "
      f"shown here: there is no way to check how it was collected.",
      f"Der Artikel enthält alle {found} Flughafentarife, die nach veröffentlichten Dokumenten im Rechner erfasst "
      f"sind. Inoffizielle Community-Daten (die Tabelle russischer Flughafenentgelte der Transport-Clearingstelle TKP) gehen in die Berechnung "
      f"ein, werden hier aber nicht gezeigt: Wie sie erhoben wurden, lässt sich nicht prüfen.")}</p>
<ul><li>{T(
        f"<b>Октябрьская волна — {len(wave)} тарифов.</b> Девять агентов-исследователей по 51 аэропорту искали\n"
        f"действующий тариф (оператор, регулятор или AIP), раскладывали в схему калькулятора и проверяли контрольным "
        f"оборотом;\nжурналы — {n(steps)} шагов, {n(extracts)} дословных цитат (<code>trace/</code>). Пять других "
        f"агентов сверили каждый\nфайл с первоисточником (<code>verify/</code>): совпали {n(ok)} из {n(checked)} "
        f"ставок; расхождения в {len(with_err)}\nфайлах ({errl}) исправлены.",
        f"<b>October wave — {len(wave)} tariffs.</b> Nine research agents searched 51 airports for the current tariff "
        f"(operator, regulator or AIP), mapped it into the calculator's schema and checked it with a reference "
        f"turnaround; logs — {n(steps)} steps, {n(extracts)} verbatim quotes (<code>trace/</code>). Five other agents "
        f"checked every file against the primary source (<code>verify/</code>): {n(ok)} of {n(checked)} rates "
        f"matched; discrepancies in {len(with_err)} files ({errl}) were fixed.",
        f"<b>Oktober-Welle — {len(wave)} Tarife.</b> Neun Recherche-Agenten suchten für 51 Flughäfen den geltenden "
        f"Tarif (Betreiber, Regulierer oder AIP), übertrugen ihn ins Schema des Rechners und prüften ihn mit einem "
        f"Referenzumlauf; Protokolle — {n(steps)} Schritte, {n(extracts)} wörtliche Zitate (<code>trace/</code>). Fünf "
        f"weitere Agenten glichen jede Datei mit der Primärquelle ab (<code>verify/</code>): {n(ok)} von {n(checked)} "
        f"Sätzen stimmten überein; Abweichungen in {len(with_err)} Dateien ({errl}) wurden korrigiert.")}</li>
<li>{T(
        f"<b>Заведённые раньше — {found - len(wave)} тарифов</b> (сентябрь 2026): Франкфурт — эталон расчёта "
        f"(контрольный\nоборот сверен с калькулятором аэропорта), пилотные аэропорты Европы, Россия (контрольный — "
        f"Шереметьево), Китай\n(одна схема CAAC), Индия, Доха, Нарита, Алматы. Проверены контрольным оборотом и разбором "
        f"по правилам; дата проверки —\nв каждом файле.",
        f"<b>Entered earlier — {found - len(wave)} tariffs</b> (September 2026): Frankfurt — the calculation benchmark "
        f"(its reference turnaround matches the airport's own calculator), pilot airports in Europe, Russia (reference: "
        f"Sheremetyevo), China (one CAAC scheme), India, Doha, Narita, Almaty. Checked with a reference turnaround and "
        f"a rule-by-rule review; the check date is in each file.",
        f"<b>Früher erfasst — {found - len(wave)} Tarife</b> (September 2026): Frankfurt — die Referenz der Berechnung "
        f"(Referenzumlauf mit dem Rechner des Flughafens abgeglichen), europäische Pilotflughäfen, Russland (Referenz: "
        f"Scheremetjewo), China (ein CAAC-Schema), Indien, Doha, Narita, Almaty. Geprüft mit Referenzumlauf und "
        f"Durchsicht Regel für Regel; das Prüfdatum steht in jeder Datei.")}</li></ul>
<details><summary>{T(f"Чего не нашлось — {miss} аэропортов", f"Not found — {miss} airports",
                     f"Nicht gefunden — {miss} Flughäfen")}</summary>
<div class="tw"><table><tr><th>ICAO</th><th>{T("Город", "City", "Stadt")}</th>
<th>{T("Что мешает", "What is in the way", "Was fehlt")}</th></tr>{gaps}</table></div>
<p class="small">{T(
        "Нужен человек с документом: Мюнхен (PDF без текста), Рим (таблицы при извлечении перемешаны),\n"
        "индийские ордера AERA и AIC AAI — их можно загрузить вручную.",
        "These need a person with the document: Munich (PDF without text), Rome (tables scrambled on extraction), the "
        "Indian AERA orders and AAI AICs — they can be loaded by hand.",
        "Hier braucht es einen Menschen mit dem Dokument: München (PDF ohne Text), Rom (Tabellen beim Extrahieren "
        "durcheinander), die indischen AERA-Anordnungen und AAI-AICs — sie lassen sich manuell laden.")}</p></details>
{S.html()}</section>"""

    style = """<style>
.tb .bar{grid-template-columns:190px 1fr 150px}.tb .bn b{color:var(--ink2);margin-right:4px}
.fill.part{background-image:repeating-linear-gradient(135deg,transparent 0 5px,var(--orange) 5px 7px)!important}
.lg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--dim);margin:12px 0 4px}
.lg i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.lg i.part{background:repeating-linear-gradient(135deg,var(--raise) 0 3px,var(--orange) 3px 5px)}
.warnw{color:var(--orange)}.verdict b .mny{font-size:inherit;color:inherit}
@media(max-width:760px){.tb .bar{grid-template-columns:120px 1fr 96px}}
</style>"""
    return page(article_title("charges-2026-10"),
                ARTICLE_CSS + style + hook + theory + analytics + facts + concl + report)


if __name__ == "__main__":
    write_all(HERE, "charges-2026-10", build, TR)
    print(f"источников {len(S.num)}")
