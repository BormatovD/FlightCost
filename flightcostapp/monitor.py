"""Страница «План и показатели» (/{lang}/monitor): открытый план работ и ряды
изменений ключевых показателей (О6, 06.11.2026).

ПЛАН — `data/plan.yaml`, правится коммитом. Предложение из бота после
приёмки приходит владельцу готовой записью; автор подписан так, как сам
указал в боте (имя и ник из Телеграма бот не хранит).

РЯДЫ — из той же базы, что расчёт, и только из того, что разрешено
показывать (решение 219):

  * топливо — спот USGC (EIA, открыт) помесячно, USD/т, и цена по регионам
    так, как её берёт расчёт: спот × множитель региона с полосой множителя
    (`data/fuel/_regional.yaml`, решение 235); демпфер России, руб./т;
  * сборы аэропортов — медиана контрольного оборота A320 по регионам
    (`data/charges/_regional.yaml`, решение 234): снимок с разбросом и ряд
    медиан — его пишет `record()` при каждом обновлении главной базы;
  * аэронавигация — маршрутный сбор на 100 км для A320 (78 т), EUR, среднее
    по зонам континента; EUROCONTROL — только средним (строки закрыты
    лицензией), Россия — по приказу ФАС;
  * доля заготовки — какая часть себестоимости эталонных рейсов стоит на
    заготовках, а не на документах; ряд пишет `record()`, текущее значение
    считается при показе;
  * ТОиР по классам ВС и владение по типам — отчётность США (Form 41),
    медиана, взвешенная блок-часами перевозчиков; номинальные USD.

Ряд, которого в базе нет, не рисуется пустым графиком: панель говорит,
чего не хватает. Чисел здесь не выдумывается.
"""

from __future__ import annotations

import html
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "data" / "plan.yaml"
DAMPER = ROOT / "data" / "fuel" / "_ru_damper.yaml"
REGIONAL = ROOT / "data" / "charges" / "_regional.yaml"

STATUSES = ("now", "next", "later", "done")
AREAS = ("calc", "data", "research", "site", "community")

# Классы ВС для ТОиР — те же, что в исследовании ТОиР (research/toir/common.py).
CLASS = {**dict.fromkeys("A19N A20N A21N A318 A319 A320 A321 B712 B733 B734 B735 B737 B738 B739 B38M B39M "
                         "B752 B753 MD80 MD90 BCS1 BCS3".split(), "narrow"),
         **dict.fromkeys("A306 A332 A333 A339 A359 B744 B748 B762 B763 B764 B772 B77W B788 B789 B78X "
                         "MD11 DC10".split(), "wide"),
         **dict.fromkeys("CRJ1 CRJ2 CRJ7 CRJ9 E135 E145 E170 E75L E190 E195 DH8D AT76 AT45 SF34 E120 "
                         "DH8A DH8B DH8C".split(), "regional")}
OWN_TYPES_MAX = 6

T = {
    "ru": {
        "title": "План и показатели — FlightCost",
        "desc": "Открытый план работ FlightCost с авторами предложений и ряды изменений: топливо, сборы, "
                "аэронавигация, ТОиР, владение.",
        "h1": "План и показатели",
        "lead": "Что делается в проекте и что дальше — и как меняются показатели, на которых стоит расчёт. "
                "Предложить работу в план можно через Телеграм-бота проекта; принятые предложения появляются "
                "здесь с подписью автора, если он её оставил.",
        "nav": "План",
        "tab_plan": "План работ", "tab_series": "Показатели",
        "st_now": "В работе", "st_next": "Дальше", "st_later": "Когда-нибудь", "st_done": "Сделано",
        "a_calc": "расчёт", "a_data": "данные", "a_research": "исследование", "a_site": "сайт",
        "a_community": "сообщество",
        "by": "предложил", "owner": "автор проекта", "added": "в плане с", "done_on": "сделано",
        "plan_honest": "Проект делает один человек в свободное время: сроки — ориентир, а не обещание.",
        "empty": "пусто",
        "fuel_h": "Топливо",
        "fuel_spot": "Спот авиакеросина, побережье Мексиканского залива США (EIA), среднее за месяц",
        "fuel_spot_u": "USD/т",
        "fuel_dmp": "Демпфер России: компенсация эксплуатанту за тонну, по месяцам",
        "fuel_dmp_u": "руб./т",
        "fuel_spot_l": "спот USGC (основа)",
        "fuel_dmp_note": "Россия: цена после компенсации российскому эксплуатанту — демпфер месяца плюс возврат акциза, по курсу (решение 236), как её берёт расчёт. Линия — Центр, полоса — от Сибири до Дальнего Востока. Последний опубликованный демпфер — {v} руб./т за {month}, возврат акциза — {ex} руб./т; до публикации следующего месяца действует последний.",
        "fuel_gross": "без вычета: нет курса рубля",
        "fuel_net": "после демпфера",
        "fuel_reg": "Цена топлива «в крыло» по регионам так, как её берёт расчёт: спот × множитель региона, USD/т",
        "fuel_note": "Множители стоят на одной точке или допущении на регион (решение 235): форма кривых одна — спот, различается уровень. Свой ряд по регионам — пункт плана.",
        "conf": "уверенность",
        "ch_h": "Сборы аэропортов по регионам",
        "ch_cap": "Контрольный оборот A320 (78 т, 148 пасс., июль): медиана по тарифам с документом и разброс, EUR",
        "ch_note": "Снимок на дату сборки, а не ряд: тарифы обновляются раз в год, и ряд растёт с каждой новой "
                   "редакцией. Неофициальные данные сообщества сюда не входят.",
        "ch_n": "аэропортов",
        "ans_h": "Аэронавигация",
        "ans_cap": "Маршрутный сбор на 100 км для A320 (78 т), EUR: среднее по зонам континента; в подписи — "
                   "число зон",
        "ans_note": "Ставки EUROCONTROL по лицензии не показываются по зонам — только средним. В расчёте участвует "
                    "ставка каждой зоны. Россия — внутренние рейсы российского эксплуатанта.",
        "dflt_h": "Доля заготовки",
        "dflt_cap": "Какая часть себестоимости эталонных рейсов стоит на заготовках, а не на документах, %",
        "dflt_note": "Чем ниже, тем больше расчёта опирается на документы. Ряд ведётся с ноября 2026 года; "
                     "сегодняшняя точка считается при открытии страницы.",
        "ch_hist": "Медиана по регионам со временем, EUR",
        "mro_h": "ТОиР по классам ВС",
        "mro_cap": "Полный ТОиР на блок-час, перевозчики США (Form 41), по кварталам, медиана, взвешенная блок-часами, "
                   "номинальные USD",
        "mro_u": "USD/блок-ч",
        "c_narrow": "узкофюзеляжные", "c_wide": "широкофюзеляжные", "c_regional": "региональные",
        "own_h": "Владение по типам ВС",
        "own_cap": "Аренда + амортизация на борт в месяц, перевозчики США (Form 41), по кварталам, медиана, номинальные USD",
        "own_u": "USD/борт·мес",
        "own_note": "Это не ставка лизинга одного договора: в сумме и собственные, и арендованные борта, по "
                    "балансовой стоимости. Открытого ряда ставок лизинга по типам нет — ищем.",
        "missing": "В базе нет ряда: {what}.",
        "src": "Источник", "pick": "нажмите на регион в легенде, чтобы показать или скрыть", "last": "последнее", "upd": "Обновлено",
        "window": "Все ряды — с января 2025 года: расчёт стоит на данных по итогам 2025-го, и ряды начинаются с "
                  "одной даты, чтобы их можно было сравнивать. Более длинная история — в исследованиях.",
        "bot": "Предложить в план — Телеграм-бот проекта",
    },
    "en": {
        "title": "Plan and indicators — FlightCost",
        "desc": "FlightCost's open work plan crediting who proposed what, and change series: fuel, charges, "
                "air navigation, maintenance, ownership.",
        "h1": "Plan and indicators",
        "lead": "What the project is working on and what comes next — and how the indicators behind the "
                "calculation change. Suggest work through the project's Telegram bot; accepted suggestions "
                "appear here credited to their author, if they chose to be credited.",
        "nav": "Plan",
        "tab_plan": "Work plan", "tab_series": "Indicators",
        "st_now": "In progress", "st_next": "Next", "st_later": "Later", "st_done": "Done",
        "a_calc": "calculation", "a_data": "data", "a_research": "research", "a_site": "site",
        "a_community": "community",
        "by": "proposed by", "owner": "project author", "added": "in plan since", "done_on": "done",
        "plan_honest": "One person builds this project in their spare time: dates are a guide, not a promise.",
        "empty": "empty",
        "fuel_h": "Jet fuel",
        "fuel_spot": "Jet fuel spot, US Gulf Coast (EIA), monthly average",
        "fuel_spot_u": "USD/t",
        "fuel_dmp": "Russia's fuel damper: payment to the operator per tonne, by month",
        "fuel_dmp_u": "RUB/t",
        "fuel_spot_l": "USGC spot (base)",
        "fuel_dmp_note": "Russia: price after compensation to a Russian operator — the month's fuel damper plus the excise refund, at the exchange rate (decision 236), as the calculation takes it. The line is the Centre, the band spans Siberia to the Far East. The latest published damper is {v} RUB/t for {month}, the excise refund {ex} RUB/t; until the next month is published the latest one applies.",
        "fuel_gross": "no deduction: no rouble rate",
        "fuel_net": "after damper",
        "fuel_reg": "Into-plane jet fuel price by region as the calculation takes it: spot × regional multiplier, USD/t",
        "fuel_note": "The multipliers rest on one point or an assumption per region (decision 235): every curve has the spot's shape, only the level differs. A regional series of its own is on the plan.",
        "conf": "confidence",
        "ch_h": "Airport charges by region",
        "ch_cap": "Reference A320 turnaround (78 t, 148 pax, July): median over documented tariffs and range, EUR",
        "ch_note": "A snapshot at build date, not a series: tariffs change once a year, and the series grows with "
                   "each new edition. Unofficial community data is not included.",
        "ch_n": "airports",
        "ans_h": "Air navigation",
        "ans_cap": "En-route charge per 100 km for an A320 (78 t), EUR: mean over the continent's zones; the label "
                   "shows the number of zones",
        "ans_note": "EUROCONTROL rates are not shown zone by zone under their licence — only as a mean. The "
                    "calculation uses each zone's own rate. Russia — domestic flights of a Russian operator.",
        "dflt_h": "Share on placeholders",
        "dflt_cap": "Share of the reference flights' cost that rests on placeholders rather than documents, %",
        "dflt_note": "Lower means more of the calculation stands on documents. The series starts in November 2026; "
                     "today's point is calculated when the page opens.",
        "ch_hist": "Regional median over time, EUR",
        "mro_h": "Maintenance by aircraft class",
        "mro_cap": "Total maintenance per block hour, US carriers (Form 41), quarterly, block-hour-weighted median, nominal USD",
        "mro_u": "USD/block h",
        "c_narrow": "narrowbody", "c_wide": "widebody", "c_regional": "regional",
        "own_h": "Ownership by aircraft type",
        "own_cap": "Rent + depreciation per aircraft per month, US carriers (Form 41), quarterly, median, nominal USD",
        "own_u": "USD/aircraft·month",
        "own_note": "Not a single lease rate: owned and leased aircraft at book value together. There is no open "
                    "series of lease rates by type — we are looking.",
        "missing": "No series in the database: {what}.",
        "src": "Source", "pick": "click a region in the legend to show or hide it", "last": "latest", "upd": "Updated",
        "window": "All series start in January 2025: the calculation rests on full-year 2025 data, and the series "
                  "share one start date so they can be compared. Longer history is in the research articles.",
        "bot": "Suggest work — the project's Telegram bot",
    },
    "de": {
        "title": "Plan und Kennzahlen — FlightCost",
        "desc": "Offener Arbeitsplan von FlightCost mit Namen der Vorschlagenden und Zeitreihen: Treibstoff, "
                "Entgelte, Flugsicherung, Instandhaltung, Besitz.",
        "h1": "Plan und Kennzahlen",
        "lead": "Woran das Projekt arbeitet und was als Nächstes kommt — und wie sich die Kennzahlen hinter der "
                "Berechnung verändern. Vorschläge nimmt der Telegram-Bot des Projekts entgegen; angenommene "
                "Vorschläge erscheinen hier mit dem Namen der Person, wenn sie genannt werden möchte.",
        "nav": "Plan",
        "tab_plan": "Arbeitsplan", "tab_series": "Kennzahlen",
        "st_now": "In Arbeit", "st_next": "Als Nächstes", "st_later": "Später", "st_done": "Erledigt",
        "a_calc": "Berechnung", "a_data": "Daten", "a_research": "Recherche", "a_site": "Website",
        "a_community": "Community",
        "by": "vorgeschlagen von", "owner": "Projektautor", "added": "im Plan seit", "done_on": "erledigt",
        "plan_honest": "Eine Person entwickelt das Projekt in der Freizeit: Termine sind Richtwerte, keine Zusagen.",
        "empty": "leer",
        "fuel_h": "Kerosin",
        "fuel_spot": "Kerosin-Spot, US-Golfküste (EIA), Monatsmittel",
        "fuel_spot_u": "USD/t",
        "fuel_dmp": "Russischer Kraftstoff-Dämpfer: Ausgleich an den Betreiber je Tonne, monatlich",
        "fuel_dmp_u": "RUB/t",
        "fuel_spot_l": "USGC-Spot (Basis)",
        "fuel_dmp_note": "Russland: Preis nach dem Ausgleich an einen russischen Betreiber — Dämpfer des Monats plus Rückerstattung der Verbrauchsteuer, zum Wechselkurs (Entscheidung 236), wie die Berechnung ihn nimmt. Die Linie ist das Zentrum, das Band reicht von Sibirien bis Fernost. Letzter veröffentlichter Dämpfer: {v} RUB/t für {month}, Rückerstattung {ex} RUB/t; bis zur nächsten Veröffentlichung gilt der letzte.",
        "fuel_gross": "ohne Abzug: kein Rubelkurs",
        "fuel_net": "nach Dämpfer",
        "fuel_reg": "Kerosinpreis ins Flugzeug nach Region, wie die Berechnung ihn nimmt: Spot × Regionsfaktor, USD/t",
        "fuel_note": "Die Faktoren beruhen auf einem Punkt oder einer Annahme je Region (Entscheidung 235): alle Kurven folgen dem Spot, nur das Niveau unterscheidet sich. Eine eigene Regionalreihe steht im Plan.",
        "conf": "Sicherheit",
        "ch_h": "Flughafenentgelte nach Region",
        "ch_cap": "Referenz-Umlauf A320 (78 t, 148 Pax, Juli): Median der belegten Tarife und Spanne, EUR",
        "ch_note": "Momentaufnahme zum Erstellungsdatum, keine Reihe: Tarife ändern sich einmal im Jahr, die Reihe "
                   "wächst mit jeder neuen Ausgabe. Inoffizielle Community-Daten sind nicht enthalten.",
        "ch_n": "Flughäfen",
        "ans_h": "Flugsicherung",
        "ans_cap": "Streckengebühr je 100 km für einen A320 (78 t), EUR: Mittel über die Zonen eines Kontinents; "
                   "in der Legende die Zahl der Zonen",
        "ans_note": "EUROCONTROL-Sätze werden laut Lizenz nicht je Zone gezeigt — nur als Mittel. Die Berechnung "
                    "nutzt den Satz jeder Zone. Russland — Inlandsflüge eines russischen Betreibers.",
        "dflt_h": "Anteil Platzhalter",
        "dflt_cap": "Anteil der Kosten der Referenzflüge, der auf Platzhaltern statt Dokumenten beruht, %",
        "dflt_note": "Je niedriger, desto mehr der Berechnung beruht auf Dokumenten. Die Reihe beginnt im November "
                     "2026; der heutige Punkt wird beim Öffnen der Seite berechnet.",
        "ch_hist": "Regionalmedian im Zeitverlauf, EUR",
        "mro_h": "Instandhaltung nach Flugzeugklasse",
        "mro_cap": "Instandhaltung gesamt je Blockstunde, US-Airlines (Form 41), quartalsweise, nach "
                   "Blockstunden gewichteter Median, nominale USD",
        "mro_u": "USD/Blockstd.",
        "c_narrow": "Schmalrumpf", "c_wide": "Großraum", "c_regional": "Regional",
        "own_h": "Besitz nach Flugzeugtyp",
        "own_cap": "Miete + Abschreibung je Flugzeug und Monat, US-Airlines (Form 41), quartalsweise, Median, nominale USD",
        "own_u": "USD/Flugzeug·Monat",
        "own_note": "Kein einzelner Leasingsatz: eigene und geleaste Flugzeuge zusammen, zum Buchwert. Eine offene "
                    "Reihe von Leasingsätzen nach Typ gibt es nicht — wir suchen.",
        "missing": "Keine Reihe in der Datenbank: {what}.",
        "src": "Quelle", "pick": "Region in der Legende anklicken, um sie ein- oder auszublenden", "last": "zuletzt", "upd": "Aktualisiert",
        "window": "Alle Reihen beginnen im Januar 2025: die Berechnung beruht auf Daten des Gesamtjahres 2025, und "
                  "die Reihen haben ein gemeinsames Startdatum, damit sie vergleichbar sind. Längere Historie in den Recherchen.",
        "bot": "Vorschlag einreichen — Telegram-Bot des Projekts",
    },
}

COLORS = ("#3987e5", "#199e70", "#9085e9", "#c98500", "#d55181", "#1E9EDB")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


# ── план ──────────────────────────────────────────────────────────────────

def load_plan(path: Path = PLAN) -> list[dict]:
    """Записи плана, проверенные по форме. Неверная запись — ошибка, а не
    молчаливый пропуск: план правится руками, и опечатка в статусе иначе
    увела бы пункт со страницы незаметно."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out, seen = [], set()
    for it in doc.get("items") or []:
        iid = str(it.get("id") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", iid) or iid in seen:
            raise ValueError(f"plan.yaml: плохой или повторный id «{iid}»")
        seen.add(iid)
        if it.get("status") not in STATUSES:
            raise ValueError(f"plan.yaml {iid}: status {it.get('status')!r} не из {STATUSES}")
        if it.get("area") not in AREAS:
            raise ValueError(f"plan.yaml {iid}: area {it.get('area')!r} не из {AREAS}")
        title = it.get("title") or {}
        if not isinstance(title, dict) or not title.get("ru"):
            raise ValueError(f"plan.yaml {iid}: нет title.ru")
        if it["status"] == "done" and not it.get("done"):
            raise ValueError(f"plan.yaml {iid}: сделано без даты done")
        out.append(it)
    return out


def _tr(field, lang: str) -> str:
    if isinstance(field, dict):
        return str(field.get(lang) or field.get("ru") or "")
    return str(field or "")


def plan_html(lang: str, items: list[dict]) -> str:
    """Лента сверху вниз по времени: сделанное (зелёное, от старого к
    новому), в работе (синее), дальше и когда-нибудь (серое). Точка на
    линии слева — статус: цвет не единственный признак, рядом заголовок
    раздела."""
    t = T[lang]
    parts = [f'<p class="dim">{esc(t["plan_honest"])}</p>']
    for st in ("done", "now", "next", "later"):
        rows = [x for x in items if x["status"] == st]
        if not rows:
            continue
        if st == "done":
            rows.sort(key=lambda x: (str(x.get("done")), str(x.get("added"))))
        else:
            # `order` — очерёдность владельца (1 — первым); без неё — по дате в плане.
            rows.sort(key=lambda x: (int(x.get("order") or 999), str(x.get("added"))))
        parts.append(f'<h2 class="tl-h {st}">{esc(t["st_" + st])} <span class="tag">{len(rows)}</span></h2>'
                     f'<ul class="plan tl {st}">')
        for x in rows:
            by = x.get("by") or "owner"
            who = t["owner"] if by == "owner" else by
            meta = [f'<span class="area">{esc(t["a_" + x["area"]])}</span>',
                    f'{esc(t["by"])}: {esc(who)}',
                    f'{esc(t["added"])} {esc(x.get("added") or "")}']
            if st == "done":
                meta.append(f'{esc(t["done_on"])} {esc(x.get("done"))}')
            title = esc(_tr(x["title"], lang))
            if x.get("link"):
                title = f'<a href="{esc(x["link"])}">{title}</a>'
            note = _tr(x.get("note"), lang)
            parts.append(f'<li id="p-{esc(x["id"])}"><b>{title}</b>'
                         + (f'<p>{esc(note)}</p>' if note else "")
                         + f'<div class="meta">{" · ".join(meta)}</div></li>')
        parts.append("</ul>")
    return "\n".join(parts)


# ── ряды ──────────────────────────────────────────────────────────────────

def _history(store, domain: str, prefix: str | None = None, key: str | None = None) -> dict[str, list]:
    """{ключ: [(valid_from, value)]} — по каждой дате начала одна строка,
    последняя по созданию (исправление перекрывает прежнюю)."""
    sql = "SELECT key, valid_from, value FROM facts WHERE domain = ? AND value IS NOT NULL"
    args: list = [domain]
    if key is not None:
        sql += " AND key = ?"
        args.append(key)
    elif prefix:
        sql += " AND key >= ? AND key < ?"
        args += [prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)]
    sql += " ORDER BY key, valid_from, created_at"
    by: dict = defaultdict(dict)
    for k, vf, v in store.db.execute(sql, args):
        by[k][str(vf)[:10]] = float(v)                    # позднее создание перекрывает
    return {k: sorted(d.items()) for k, d in by.items()}


def _monthly_mean(points: list) -> list:
    acc = defaultdict(list)
    for d, v in points:
        acc[d[:7]].append(v)
    return [(m, sum(xs) / len(xs)) for m, xs in sorted(acc.items())]


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _months(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def rate_index(series: dict[str, list], share: float = 0.8) -> list:
    """Индекс ставок по зонам: на каждый месяц — действующая ставка каждой
    зоны (последняя с началом не позже конца месяца), делённая на её
    ставку в базовом месяце; медиана по зонам × 100. Базовый месяц —
    первый, где ставка есть у `share` зон. Зона без ставки в базе — вне
    индекса (её рост мерить не от чего)."""
    series = {k: v for k, v in series.items() if v}
    if not series:
        return []
    first = min(v[0][0] for v in series.values())[:7]
    last = max(max(v[-1][0] for v in series.values())[:7], date.today().isoformat()[:7])
    months = _months(first, last)

    def at(pts, month):
        val = None
        for d, v in pts:
            if d[:7] <= month:
                val = v
            else:
                break
        return val

    base = None
    for m in months:
        if sum(1 for p in series.values() if at(p, m) is not None) >= share * len(series):
            base = m
            break
    if base is None:
        return []
    b = {k: at(p, base) for k, p in series.items()}
    b = {k: v for k, v in b.items() if v}
    out = []
    for m in months[months.index(base):]:
        r = [at(series[k], m) / b[k] for k in b if at(series[k], m) is not None]
        if r:
            out.append((m, round(100 * _median(r), 1)))
    return out


FUEL_NAMES = {
    "north_america": {"en": "North America", "de": "Nordamerika"}, "europe": {"en": "Europe", "de": "Europa"},
    "middle_east": {"en": "Middle East", "de": "Naher Osten"},
    "asia_oceania": {"en": "Asia and Oceania", "de": "Asien und Ozeanien"},
    "africa": {"en": "Africa", "de": "Afrika"}, "latam": {"en": "Latin America", "de": "Lateinamerika"},
    "kz_cis": {"en": "Kazakhstan and CIS", "de": "Kasachstan und GUS"}, "india": {"en": "India", "de": "Indien"},
    "russia_centre": {"en": "Russia — Centre", "de": "Russland — Zentrum"},
    "russia_siberia": {"en": "Russia — Siberia", "de": "Russland — Sibirien"},
    "russia_far_east": {"en": "Russia — Far East", "de": "Russland — Ferner Osten"},
    "russia": {"en": "Russia", "de": "Russland"},
}
CONF = {"высокая": {"en": "high", "de": "hoch"}, "средняя": {"en": "medium", "de": "mittel"},
        "низкая": {"en": "low", "de": "niedrig"}, "заглушка": {"en": "placeholder", "de": "Platzhalter"}}
FUEL_FILE = ROOT / "data" / "fuel" / "_regional.yaml"
# Регионы на графике топлива по умолчанию; остальные включаются в легенде.
FUEL_DEFAULT = {"north_america", "europe", "india", "russia", "africa", "spot"}
# Цвет и штрих региона на общем графике: Россия — один цвет и три штриха,
# остальные — свои цвета. 11 линий цветом не различить, штрих помогает.
FUEL_STYLE = {
    "north_america": ("#3987e5", None, 2), "europe": ("#199e70", None, 2), "middle_east": ("#9085e9", None, 2),
    "asia_oceania": ("#e69f00", None, 2), "africa": ("#a1887f", None, 2), "latam": ("#56b4e9", None, 2),
    "kz_cis": ("#cc79a7", None, 2), "india": ("#f0e442", None, 2),
    "russia": ("#ef5a5a", None, 2.5),
}


def _fuel(store) -> dict:
    spot = _history(store, "jet_fuel_price", key="spot/USGC").get("spot/USGC", [])
    from .bench import KG_PER_GAL
    monthly = [(m, round(v * 1000 / KG_PER_GAL)) for m, v in _monthly_mean(spot)]
    damper = []
    if DAMPER.exists():
        doc = yaml.safe_load(DAMPER.read_text(encoding="utf-8")) or {}
        for m, r in sorted((doc.get("months") or {}).items()):
            if isinstance(r, dict) and r.get("damper_rub_t") is not None:
                damper.append((str(m)[:7], float(r["damper_rub_t"])))
    # Регионы — так, как цену берёт расчёт (econ, решение 235): спот ×
    # множитель региона аэропорта вылета; полоса — разброс множителя.
    # С начала окна страницы (SINCE): старше множитель не мерили, и тянуть
    # его на прошлые годы значило бы выдумывать.
    regions = []
    if FUEL_FILE.exists() and monthly:
        doc = yaml.safe_load(FUEL_FILE.read_text(encoding="utf-8")) or {}
        tail = [x for x in monthly if x[0] >= SINCE]
        for code, r in (doc.get("regions") or {}).items():
            k = r.get("k")
            if not k:
                continue
            lo, hi = (r.get("range") or [k, k])[:2]
            regions.append({"code": code, "name": r.get("name") or code, "k": k,
                            "conf": r.get("confidence") or "",
                            "line": [(m, round(v * k)) for m, v in tail],
                            "band": [(m, round(v * lo), round(v * hi)) for m, v in tail]})
    exc = 0.0
    if DAMPER.exists():
        exc = float((yaml.safe_load(DAMPER.read_text(encoding="utf-8")) or {}).get("excise_refund_rub_t") or 0)
    regions = _russia_net(store, regions, damper, exc)
    return {"spot": monthly, "damper": damper, "regions": regions, "excise": exc}


def _russia_net(store, regions: list, damper: list, excise: float) -> list:
    """Три региона России — одной линией, сразу после компенсации, как её
    берёт расчёт для российского эксплуатанта (econ, решение 236): цена −
    (демпфер последнего опубликованного месяца + возврат акциза) по курсу,
    не ниже нуля. Линия — Центр, полоса — от меньшего множителя регионов до
    большего. Месяц без курса рубля пропускается, а не рисуется без вычета."""
    ru = [r for r in regions if r["code"].startswith("russia")]
    if not ru:
        return regions
    rest = [r for r in regions if not r["code"].startswith("russia")]
    centre = next((r for r in ru if r["code"] == "russia_centre"), ru[0])
    ks = sorted(r["k"] for r in ru)
    dm = sorted(damper)

    def comp(month):
        known = [v for m, v in dm if m <= month]
        return (known[-1] + excise) if known else None

    line, band = [], []
    for m, gross_c in centre["line"]:
        c = comp(m)
        rub_eur = store.value("fx", "RUB", f"{m}-28")
        usd_eur = store.value("fx", "USD", f"{m}-28")
        if c is None or not rub_eur or not usd_eur:
            continue
        cut = c / (rub_eur / usd_eur)                     # руб/т → USD/т
        spot = gross_c / centre["k"]
        line.append((m, round(max(gross_c - cut, 0))))
        band.append((m, round(max(spot * ks[0] - cut, 0)), round(max(spot * ks[-1] - cut, 0))))
    if not line:
        # Нет курса рубля — вычесть нечем, как и в расчёте: линия без вычета, и это сказано.
        spot = [(m, v / centre["k"]) for m, v in centre["line"]]
        return rest + [{"code": "russia", "name": "Россия", "k": centre["k"], "k_range": (ks[0], ks[-1]),
                        "conf": centre["conf"], "line": centre["line"], "net": False,
                        "band": [(m, round(v * ks[0]), round(v * ks[-1])) for m, v in spot]}]
    return rest + [{"code": "russia", "name": "Россия", "k": centre["k"], "k_range": (ks[0], ks[-1]),
                    "conf": centre["conf"], "line": line, "band": band, "net": True}]


def _charges(store=None) -> dict:
    if not REGIONAL.exists():
        return {}
    doc = yaml.safe_load(REGIONAL.read_text(encoding="utf-8")) or {}
    rows = []
    for code, r in (doc.get("regions") or {}).items():
        rng = r.get("range_eur") or [None, None]
        rows.append({"code": code, "name": r.get("name") or code, "median": r.get("median_eur"),
                     "lo": rng[0], "hi": rng[1], "n": r.get("n")})
    rows.sort(key=lambda r: -(r["median"] or 0))
    hist = {}
    if store is not None:
        for key, pts in _history(store, "monitor", prefix="charges_median/").items():
            hist[key.split("/", 1)[1]] = pts
    return {"built": str(doc.get("built") or ""), "rows": rows, "history": hist}


REGION_NAMES = {
    "europe": {"en": "Europe", "de": "Europa"}, "russia_cis": {"en": "Russia and CIS", "de": "Russland und GUS"},
    "india": {"en": "India", "de": "Indien"}, "asia_gulf": {"en": "Asia and the Gulf", "de": "Asien und Golf"},
    "africa": {"en": "Africa", "de": "Afrika"}, "world": {"en": "Rest of world", "de": "Übrige Welt"},
}

# Континент зоны — по первой букве кода ИКАО; EUROCONTROL и ФАС — по
# источнику: CRCO выставляет счета и за Турцию, Кавказ и Канары.
CONTINENT = {"crco": "europe_ec", "fas": "russia", "U": "cis", "Z": "china", "V": "asia", "W": "asia",
             "R": "asia", "O": "middle_east", "K": "north_america", "C": "north_america", "P": "north_america",
             "M": "latam", "S": "latam", "T": "latam", "D": "africa", "F": "africa", "G": "africa",
             "H": "africa", "Y": "oceania", "N": "oceania", "E": "europe", "L": "europe", "B": "europe"}
CONTINENT_NAMES = {
    "europe_ec": {"ru": "Европа (EUROCONTROL)", "en": "Europe (EUROCONTROL)", "de": "Europa (EUROCONTROL)"},
    "russia": {"ru": "Россия (ФАС)", "en": "Russia (FAS)", "de": "Russland (FAS)"},
    "cis": {"ru": "СНГ", "en": "CIS", "de": "GUS"}, "china": {"ru": "Китай", "en": "China", "de": "China"},
    "asia": {"ru": "Азия", "en": "Asia", "de": "Asien"},
    "middle_east": {"ru": "Ближний Восток", "en": "Middle East", "de": "Naher Osten"},
    "north_america": {"ru": "Северная Америка", "en": "North America", "de": "Nordamerika"},
    "latam": {"ru": "Латинская Америка", "en": "Latin America", "de": "Lateinamerika"},
    "africa": {"ru": "Африка", "en": "Africa", "de": "Afrika"},
    "oceania": {"ru": "Океания", "en": "Oceania", "de": "Ozeanien"},
    "europe": {"ru": "Европа (вне EUROCONTROL)", "en": "Europe (outside EUROCONTROL)",
               "de": "Europa (außerhalb EUROCONTROL)"},
}
REF_MTOW_T = 78.0
KM100_NM = 100 / 1.852


def _zone_per_100km(z: str, rate: float, value_text: str | None, forms: dict) -> float:
    """Маршрутный сбор зоны за 100 км для A320 (78 т) в валюте ставки — той
    же формулой, что в расчёте (econ, navcharge): полосы массы ФАС из
    факта, способ зоны из config/nav_zones.yaml."""
    from .navcharge import charge
    cfg = dict(forms.get(z, {}))
    form = cfg.get("formula", "eurocontrol")
    try:
        extra = json.loads(value_text or "{}")
    except ValueError:
        extra = {}
    if isinstance(extra, dict) and extra.get("bands"):
        cfg.update({k: v for k, v in extra.items() if k in ("d_div", "d_unit", "d_exp", "m_div", "m_exp", "bands")})
        form = "custom"
    return charge(KM100_NM, REF_MTOW_T, rate, form, cfg)


def _ans(store) -> dict:
    """Среднее по зонам континента, EUR на 100 км, помесячно. Зона входит в
    месяц, если ставка в нём действует и есть курс её валюты."""
    from .econ import _nav_formulas
    forms = _nav_formulas()
    rows = store.db.execute(
        "SELECT key, valid_from, value, currency, value_text, source_id FROM facts "
        "WHERE domain = 'enroute_rate' AND value IS NOT NULL ORDER BY key, valid_from, created_at").fetchall()
    zones: dict = defaultdict(dict)
    meta: dict = {}
    for key, vf, val, cur, vt, src in rows:
        if "/" in key and not key.endswith("/national/domestic"):
            continue                                  # Россия — один вариант: свой эксплуатант, внутренний рейс
        z = key.split("/")[0]
        if src == "crco_enroute_rates":
            cont = "europe_ec"
        elif src == "fas_ans_rates":
            cont = "russia"
        else:
            cont = CONTINENT.get(z[:1])
        if not cont:
            continue
        zones[key][str(vf)[:10]] = (float(val), (cur or "EUR").upper(), vt)
        meta[key] = (z, cont)
    if not zones:
        return {"lines": {}, "n": {}}
    first = min(min(v) for v in zones.values())[:7]
    months = _months(first, date.today().isoformat()[:7])
    fx_cache: dict = {}

    def fx(cur, month):
        if cur == "EUR":
            return 1.0
        k = (cur, month)
        if k not in fx_cache:
            fx_cache[k] = store.value("fx", cur, f"{month}-28")
        return fx_cache[k]

    acc: dict = defaultdict(lambda: defaultdict(list))
    for key, pts in zones.items():
        z, cont = meta[key]
        dates = sorted(pts)
        for m in months:
            cur_d = None
            for d in dates:
                if d[:7] <= m:
                    cur_d = d
                else:
                    break
            if cur_d is None:
                continue
            val, cur, vt = pts[cur_d]
            r = fx(cur, m)
            if not r:
                continue
            acc[cont][m].append(_zone_per_100km(z, val, vt, forms) / r)
    lines = {c: [(m, round(sum(v) / len(v), 1)) for m, v in sorted(ms.items())] for c, ms in acc.items()}
    n = {c: len({meta[k][0] for k in zones if meta[k][1] == c}) for c in acc}
    return {"lines": lines, "n": n}


# ── доля заготовки на эталонных рейсах ────────────────────────────────────

# Эталоны: по одному на регион, где расчёт опирается на разные документы.
# FRA–BCN — тот же, что в проверке сайта (tools/site_check.py).
# Расчёт ключует аэропорты кодом ИАТА (домен airport, serve.resolve), ряд
# в базе — кодом ИКАО: (ИАТА, ИАТА, тип, ключ ряда, подпись).
REF_ROUTES = (("FRA", "BCN", "A320", "EDDF-LEBL", "FRA–BCN A320"),
              ("SVO", "LED", "A320", "UUEE-ULLI", "SVO–LED A320"),
              ("DEL", "BOM", "A20N", "VIDP-VABB", "DEL–BOM A20N"),
              ("JFK", "LAX", "A321", "KJFK-KLAX", "JFK–LAX A321"))
# Замеры до начала ряда (проверка сайта, эталон FRA–BCN, июль, загрузка 0,82).
SEED = {"default_share/EDDF-LEBL/A320": [("2026-11-01", 0.42), ("2026-11-05", 0.40)]}


def _ref_shares(store) -> dict:
    from .econ import route_economics
    import sys
    out = {}
    for o, d, ac, key, label in REF_ROUTES:
        try:
            res = route_economics(store, o, d, aircraft=ac, load_factor=0.82, month=7)
            out[f"default_share/{key}/{ac}"] = (label, round(res.default_share(), 4))
        except Exception as exc:                       # noqa: BLE001 — нет аэропорта или типа в базе
            # Не молча: 06.11.2026 все четыре эталона падали на кодах ИКАО,
            # а страница писала «в базе нет ряда» без причины.
            print(f"monitor: эталон {label} не посчитан: {type(exc).__name__}: {exc}", file=sys.stderr)
    return out


def _default_share(store) -> dict:
    now = _ref_shares(store)
    hist = _history(store, "monitor", prefix="default_share/")
    lines = []
    today = date.today().isoformat()
    # Ряд показывается и тогда, когда сегодняшний расчёт не удался: замеры и
    # записанная история от этого не исчезают.
    for o, d, ac, key, label in REF_ROUTES:
        k = f"default_share/{key}/{ac}"
        pts = dict(SEED.get(k, []))
        pts.update(dict(hist.get(k, [])))
        if k in now:
            pts[today] = now[k][1]
        if pts:
            lines.append((label, [(dd, round(x * 100, 1)) for dd, x in sorted(pts.items())]))
    return {"lines": lines}


def record(store, today: str | None = None) -> int:
    """Записать в главную базу то, у чего нет своей истории: долю заготовки
    эталонов и медианы сборов по регионам. Пишется только изменившееся —
    ряд не пухнет от одинаковых дней. Это производные от уже принятых
    данных, а не новые данные извне, поэтому мимо очереди приёмки.
    Возвращает число записанных фактов."""
    from .store import Fact
    today = today or date.today().isoformat()
    vals = {k: v for k, (_, v) in _ref_shares(store).items()}
    ch = _charges()
    for r in ch.get("rows") or []:
        if r.get("median"):
            vals[f"charges_median/{r['code']}"] = float(r["median"])
    last = {k: (pts[-1][1] if pts else None)
            for k, pts in _history(store, "monitor").items()}
    facts = []
    for k, v in vals.items():
        prev = last.get(k)
        tol = 0.005 if k.startswith("default_share/") else 1.0
        if prev is not None and abs(prev - v) < tol:
            continue
        facts.append(Fact(domain="monitor", key=k, valid_from=today, value=v,
                          unit="share" if k.startswith("default_share/") else "EUR",
                          source_id="monitor", extracted_by="monitor@1"))
    if facts:
        store.commit_facts(facts)
    return len(facts)


def _form41(store) -> dict:
    """ТОиР по классам и владение по типам — поквартально с начала окна
    (SINCE): по годам с 2025-го была бы одна точка. Квартал подписан
    месяцем своего начала, чтобы стоять на общей оси времени."""
    from .bench import _load, _wq, carrier_rows
    try:
        data = _load(store)
    except Exception:                                      # noqa: BLE001 — нет Form 41 в базе
        return {}
    periods = sorted({k[0] for k in data.get("p52", {}) if k in data.get("t2", {}) and k[0] >= SINCE})
    mro: dict = defaultdict(list)
    own: dict = defaultdict(list)
    bh_type: dict = defaultdict(float)
    for yq in periods:
        m = re.fullmatch(r"(\d{4})Q([1-4])", yq)
        if not m:
            continue
        label = f"{m.group(1)}-{(int(m.group(2)) - 1) * 3 + 1:02d}"
        rows, _ = carrier_rows(store, yq)                  # отбор по началу ключа — квартал целиком
        by_cls = defaultdict(list)
        by_type = defaultdict(list)
        for r in rows:
            c = CLASS.get(r["icao"])
            if c:
                by_cls[c].append((r["maint_per_bh"], r["block_h"]))
            if r.get("own_per_ac_month") and r["own_per_ac_month"] > 0:
                by_type[r["icao"]].append((r["own_per_ac_month"], r["block_h"]))
                bh_type[r["icao"]] += r["block_h"]
        for c, pairs in by_cls.items():
            mro[c].append((label, round(_wq(pairs, 0.5))))
        for ic, pairs in by_type.items():
            own[ic].append((label, round(_wq(pairs, 0.5))))
    top = sorted(own, key=lambda ic: -bh_type[ic])[:OWN_TYPES_MAX]
    return {"mro": dict(mro), "own": {ic: own[ic] for ic in top}}


# Общее окно всех рядов: с 2025 года — база расчёта стоит на данных по
# итогам 2025-го, и ряды должны начинаться с одной даты, чтобы их можно
# было класть рядом. Более длинная история остаётся в базе и в исследованиях.
SINCE = "2025"


def _since(pts: list) -> list:
    return [x for x in pts if str(x[0]) >= SINCE]


def build(store) -> dict:
    """Все ряды страницы, обрезанные по SINCE. Медленная часть — Form 41 и
    четыре эталонных расчёта; витрина кэширует результат до смены базы."""
    out = {"fuel": _fuel(store), "charges": _charges(store), "ans": _ans(store),
           "dflt": _default_share(store), "built": date.today().isoformat()}
    out.update(_form41(store))
    f = out["fuel"]
    f["spot"], f["damper"] = _since(f["spot"]), _since(f["damper"])
    out["ans"]["lines"] = {c: _since(v) for c, v in (out["ans"].get("lines") or {}).items()}
    out["ans"]["lines"] = {c: v for c, v in out["ans"]["lines"].items() if v}
    for k in ("mro", "own"):
        if k in out:
            out[k] = {c: _since(v) for c, v in out[k].items() if _since(v)}
    ch = out["charges"]
    if ch.get("history"):
        ch["history"] = {c: _since(v) for c, v in ch["history"].items()}
    out["dflt"]["lines"] = [(n, _since(v)) for n, v in out["dflt"]["lines"]]
    out["since"] = SINCE
    return out


# ── рисование ─────────────────────────────────────────────────────────────

def _fmt(v: float, lang: str) -> str:
    if v is None:
        return "—"
    s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"
    return s.replace(",", " ").replace(".", "," if lang != "en" else ".")


def line_chart(lines: list[tuple[str, list]], lang: str, unit: str = "", w: int = 720, h: int = 240,
               band: list | None = None, y_range: tuple | None = None, cls: str = "",
               styles: list | None = None, legend_below: bool = False, bands: dict | None = None,
               ids: list | None = None, shown: set | None = None) -> str:
    """SVG-линии по категориям времени (месяц «2026-05» или год «2024»).
    Подпись каждой линии — в легенде с последним значением: цвет не
    единственный признак. Без скрипта: страница читается и роботом, и при
    печати. `band` — полоса [(x, низ, верх)] под первой линией; `y_range` —
    общая шкала для ряда маленьких графиков, чтобы их можно было сравнить."""
    lines = [(n, pts) for n, pts in lines if pts]
    if not lines:
        return ""
    band = band or []
    bands = bands or {}
    allb = band + [b for bb in bands.values() for b in bb]
    xs = sorted({p[0] for _, pts in lines for p in pts} | {b[0] for b in allb})
    ys = [p[1] for _, pts in lines for p in pts] + [v for b in allb for v in b[1:]]
    lo, hi = y_range if y_range else (min(ys), max(ys))
    if lo == hi:
        lo, hi = lo * 0.9, hi * 1.1 or 1
    pad = (hi - lo) * 0.08
    lo, hi = max(0, lo - pad) if lo >= 0 else lo - pad, hi + pad
    L, R, Tp, B = 6, 10, 22, 26                     # подписи оси Y — внутри поля, над линейкой
    pw, ph = w - L - R, h - Tp - B

    # Ось времени настоящая, а не по порядку: месяцы демпфера идут с
    # пропусками, и равные шаги между точками исказили бы скорость роста.
    def tnum(x):
        t = int(x[:4]) + ((int(x[5:7]) - 1) / 12 if len(x) >= 7 else 0)
        return t + ((int(x[8:10]) - 1) / 365 if len(x) >= 10 else 0)    # дни — для коротких рядов
    t0, t1 = tnum(xs[0]), tnum(xs[-1])

    def X(x):
        return L + (pw * (tnum(x) - t0) / (t1 - t0) if t1 > t0 else pw / 2)

    def Y(y):
        return Tp + ph * (1 - (y - lo) / (hi - lo))

    step = 10 ** math.floor(math.log10((hi - lo) / 4 or 1))
    for k in (1, 2, 2.5, 5, 10):
        if (hi - lo) / (step * k) <= 5:
            step *= k
            break
    g, ylab = [], []                                       # подписи оси Y — поверх линий
    v = math.ceil(lo / step) * step
    while v <= hi:
        y = Y(v)
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{y:.1f}" y2="{y:.1f}" class="gl"/>')
        ylab.append(f'<text x="{L + 2}" y="{y - 4:.1f}" class="ax yl">'
                 f'{esc(_fmt(round(v) if step >= 1 else v, lang))}</text>')
        v += step
    nlab = min(len(xs), 7)
    idx, last_x = [], -1e9
    for i in range(nlab):                                  # подписи — равномерно по времени
        want = t0 + (t1 - t0) * i / max(1, nlab - 1)
        j = min(range(len(xs)), key=lambda k: abs(tnum(xs[k]) - want))
        if X(xs[j]) - last_x > 60 or j == len(xs) - 1:
            idx.append(j)
            last_x = X(xs[j])
    for n, i in enumerate(dict.fromkeys(idx)):
        anc = "end" if i == len(xs) - 1 and len(xs) > 1 else "start" if i == 0 else "middle"
        # На телефоне подписи крупнее — каждая вторая прячется (кроме крайних).
        odd = (" odd" if n % 2 else "") + " mid" if i not in (0, len(xs) - 1) else ""
        g.append(f'<text x="{X(xs[i]):.1f}" y="{h - 6}" class="ax{odd}" text-anchor="{anc}">{esc(xs[i])}</text>')
    paths, legend = [], []
    if band:
        up = " ".join(f"{X(x):.1f},{Y(b):.1f}" for x, _, b in band)
        dn = " ".join(f"{X(x):.1f},{Y(a):.1f}" for x, a, _ in reversed(band))
        paths.append(f'<polygon points="{up} {dn}" fill="{COLORS[0]}" fill-opacity=".18"/>')
    # ids/shown — выбор линий: каждая линия со своей полосой — группа
    # <g data-s>, легенда — кнопки; скрипт страницы (TOGGLE_JS) прячет и
    # показывает. Без скрипта видны линии по умолчанию.
    def grp_open(i):
        if not ids:
            return ""
        hid = "" if shown is None or ids[i] in shown else ' style="display:none"'
        return f'<g data-s="{esc(ids[i])}"{hid}>'

    grp_close = "</g>" if ids else ""
    for i, (name, pts) in enumerate(lines):
        paths.append(grp_open(i))
        if i in bands:                                     # полоса линии — её цветом, под ней
            c = styles[i][0] if styles and i < len(styles) else COLORS[i % len(COLORS)]
            up = " ".join(f"{X(x):.1f},{Y(b):.1f}" for x, _, b in bands[i])
            dn = " ".join(f"{X(x):.1f},{Y(a):.1f}" for x, a, _ in reversed(bands[i]))
            paths.append(f'<polygon points="{up} {dn}" fill="{c}" fill-opacity=".16"/>')
        # styles[i] = (цвет, штрих или None, толщина): много линий на одном
        # графике различаются не только цветом, но и штрихом.
        c, dash, sw = (styles[i] if styles and i < len(styles) else (COLORS[i % len(COLORS)], None, 2))
        d = " ".join(f'{"M" if j == 0 else "L"}{X(x):.1f},{Y(y):.1f}' for j, (x, y) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        paths.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{sw}"{da}/>')
        if len(pts) <= 24:
            paths.extend(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="{c}"><title>{esc(name)} · '
                         f'{esc(x)}: {esc(_fmt(y, lang))} {esc(unit)}</title></circle>' for x, y in pts)
        lx, ly = pts[-1]
        sw_i = (f'<svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke="{c}" stroke-width="2.5"{da}/></svg>'
                if dash else f'<i style="background:{c}"></i>')
        paths.append(grp_close)
        when = "" if legend_below else f' <em>({esc(lx)})</em>'
        inner = f'{sw_i}{esc(name)}: <b>{esc(_fmt(ly, lang))}</b>{when}'
        if ids:
            on = shown is None or ids[i] in shown
            legend.append((ly, f'<button type="button" class="lgb{"" if on else " off"}" data-s="{esc(ids[i])}" '
                               f'aria-pressed="{"true" if on else "false"}">{inner}</button>'))
        else:
            legend.append((ly, f'<span>{inner}</span>'))
    svg = (f'<svg viewBox="0 0 {w} {h}" class="ch {cls}" role="img" preserveAspectRatio="none">'
           + "".join(g) + "".join(paths) + "".join(ylab) + "</svg>")
    if legend_below:
        # Под графиком — по последнему значению сверху вниз, как линии стоят на графике.
        items = "".join(x for _, x in sorted(legend, key=lambda z: -z[0]))
        last = max(p[-1][0] for _, p in lines)
        hint = f' · {esc(T[lang]["pick"])}' if ids else ""
        return (f'<div class="pick" data-key="{esc(cls or "chart")}">{svg}<div class="lg2 below">{items}</div></div>'
                f'<p class="cap">{esc(T[lang]["last"])}: {esc(last)}{hint}</p>')
    return f'<div class="lg2">{"".join(x for _, x in legend)}</div>{svg}'


def range_chart(rows: list[dict], lang: str, w: int = 720) -> str:
    rows = [r for r in rows if r.get("median")]
    if not rows:
        return ""
    hi = max((r.get("hi") or r["median"]) for r in rows) * 1.05
    # Подпись региона — над полосой, а не слева: на телефоне левой колонке
    # не хватает места, а так ширина одна на всех экранах.
    L, R, rh = 8, 70, 60
    h = rh * len(rows) + 8
    out = []
    for i, r in enumerate(rows):
        y = 4 + i * rh + rh * 0.72

        def X(v):
            return L + (w - L - R) * v / hi
        name = r["name"] if lang == "ru" else REGION_NAMES.get(r["code"], {}).get(lang, r["name"])
        out.append(f'<text x="{L}" y="{y - 17:.1f}" class="ax">{esc(name)} · {r.get("n") or "—"} '
                   f'{esc(T[lang]["ch_n"])}</text>')
        if r.get("lo") and r.get("hi"):
            out.append(f'<line x1="{X(r["lo"]):.1f}" x2="{X(r["hi"]):.1f}" y1="{y:.1f}" y2="{y:.1f}" '
                       f'stroke="{COLORS[0]}" stroke-opacity=".45" stroke-width="6" stroke-linecap="round"/>')
        out.append(f'<circle cx="{X(r["median"]):.1f}" cy="{y:.1f}" r="5" fill="{COLORS[0]}"/>'
                   f'<text x="{X(r.get("hi") or r["median"]) + 8:.1f}" y="{y + 4:.1f}" class="vl">'
                   f'{esc(_fmt(r["median"], lang))}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="ch" role="img">{"".join(out)}</svg>'


def _panel(h: str, cap: str, body: str, note: str = "", src: str = "") -> str:
    return (f'<section class="pn"><h2>{esc(h)}</h2><p class="cap">{esc(cap)}</p>{body}'
            + (f'<p class="dim">{esc(note)}</p>' if note else "")
            + (f'<p class="src">{src}</p>' if src else "") + "</section>")


def series_html(lang: str, d: dict) -> str:
    t = T[lang]
    miss = lambda what: f'<div class="note quiet">{esc(t["missing"].format(what=what))}</div>'  # noqa: E731
    nm = lambda names, code, fallback: (names.get(code, {}).get(lang) or fallback)  # noqa: E731
    out = [f'<p class="dim">{esc(t["window"])}</p>']
    # Доля заготовки — первой: это главный ответ «насколько можно верить расчёту».
    dl = (d.get("dflt") or {}).get("lines") or []
    out.append(_panel(t["dflt_h"], t["dflt_cap"], line_chart(dl, lang, "%") or miss("default_share"),
                      t["dflt_note"]))
    f = d.get("fuel") or {}
    regs = sorted(f.get("regions") or [], key=lambda r: -r["k"])
    lines, styles, bands, ids = [], [], {}, []
    kf = lambda v: str(v) if lang == "en" else str(v).replace(".", ",")  # noqa: E731
    for r in regs:
        name = r["name"] if lang == "ru" else nm(FUEL_NAMES, r["code"], r["name"])
        if "net" in r:
            lo, hi = r["k_range"]
            tag = t["fuel_net"] if r["net"] else t["fuel_gross"]
            lines.append((f"{name}* ×{kf(lo)}–{kf(hi)}, {tag}", r["line"]))
            bands[len(lines) - 1] = r["band"]
        else:
            lines.append((f"{name} ×{kf(r['k'])}", r["line"]))
        styles.append(FUEL_STYLE.get(r["code"], (COLORS[len(styles) % len(COLORS)], None, 2)))
        ids.append(r["code"])
    if f.get("spot"):
        lines.append((t["fuel_spot_l"], f["spot"]))
        styles.append(("#8a8a8a", "2 4", 1.5))
        ids.append("spot")
    body = line_chart(lines, lang, t["fuel_spot_u"], h=300, styles=styles, legend_below=True, bands=bands,
                      ids=ids, shown=FUEL_DEFAULT, cls="fuel") \
        or miss("jet_fuel_price spot/USGC")
    dm = f.get("damper") or []
    if dm:
        m, v = dm[-1]
        body += (f'<p class="foot">* {esc(t["fuel_dmp_note"].format(month=m, v=_fmt(v, lang), ex=_fmt(f.get("excise") or 0, lang)))}</p>')
    out.append(_panel(t["fuel_h"], t["fuel_reg"], body, t["fuel_note"],
                      f'{esc(t["src"])}: <a href="https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm">EIA</a> · '
                      f'<a href="/{lang}/research/fuel-2026-10">{"исследование топлива" if lang == "ru" else "fuel research" if lang == "en" else "Treibstoff-Recherche"}</a> · '
                      f'<a href="https://github.com/BormatovD/FlightCost/blob/main/data/fuel/_ru_damper.yaml">'
                      f'_ru_damper.yaml</a>'))
    ch = d.get("charges") or {}
    body = range_chart(ch.get("rows") or [], lang) or miss("data/charges/_regional.yaml")
    hist = ch.get("history") or {}
    if any(len(v) >= 2 for v in hist.values()):
        names = {r["code"]: r["name"] for r in ch.get("rows") or []}
        hl = [(names.get(c, c) if lang == "ru" else nm(REGION_NAMES, c, c), pts) for c, pts in hist.items()]
        body += f'<p class="cap">{esc(t["ch_hist"])}</p>' + line_chart(hl, lang, "EUR")
    out.append(_panel(t["ch_h"], t["ch_cap"] + (f" · {ch['built']}" if ch.get("built") else ""), body,
                      t["ch_note"], f'{esc(t["src"])}: <a href="/{lang}/research/charges-2026-10">'
                      f'{"исследование сборов" if lang == "ru" else "charges research" if lang == "en" else "Entgelt-Recherche"}</a>'))
    a = d.get("ans") or {}
    al = a.get("lines") or {}
    order = sorted(al, key=lambda c: -(al[c][-1][1] if al[c] else 0))
    lines = [(f'{CONTINENT_NAMES.get(c, {}).get(lang, c)}, {a.get("n", {}).get(c, 0)}', al[c]) for c in order]
    out.append(_panel(t["ans_h"], t["ans_cap"], line_chart(lines, lang, "EUR") or miss("enroute_rate"),
                      t["ans_note"], f'{esc(t["src"])}: EUROCONTROL CRCO · ФАС России'))
    mro = d.get("mro") or {}
    lines = [(t["c_" + c], mro[c]) for c in ("narrow", "regional", "wide") if mro.get(c)]
    out.append(_panel(t["mro_h"], t["mro_cap"], line_chart(lines, lang, t["mro_u"]) or miss("Form 41"),
                      "", f'{esc(t["src"])}: <a href="https://www.transtats.bts.gov/">BTS Form 41</a> · '
                      f'<a href="/{lang}/research/toir">{"исследование ТОиР" if lang == "ru" else "maintenance research" if lang == "en" else "Instandhaltungs-Recherche"}</a>'))
    own = d.get("own") or {}
    out.append(_panel(t["own_h"], t["own_cap"],
                      line_chart(list(own.items()), lang, t["own_u"]) or miss("Form 41"),
                      t["own_note"], f'{esc(t["src"])}: <a href="https://www.transtats.bts.gov/">BTS Form 41</a>'))
    out.append(f'<p class="dim">{esc(t["upd"])}: {esc(d.get("built") or "")}</p>')
    return "\n".join(out)


STYLE = """<style>
.tabs{display:flex;gap:6px;margin:14px 0 4px;border-bottom:1px solid var(--line)}
.tabs a{padding:8px 14px;text-decoration:none;color:var(--dim);border-bottom:2px solid transparent;margin-bottom:-1px}
.tabs a.on{color:var(--ink2);border-bottom-color:var(--accent)}
ul.plan{list-style:none;padding:0;margin:0}
ul.tl{position:relative;padding-left:26px;margin-left:6px}
ul.tl::before{content:"";position:absolute;left:6px;top:0;bottom:-26px;width:2px;background:var(--line)}
ul.tl li{position:relative}
ul.tl li::before{content:"";position:absolute;left:-26px;top:14px;width:12px;height:12px;border-radius:50%;
  background:#6b6b6b;border:2px solid var(--bg)}
ul.tl.done li::before{background:#199e70}ul.tl.now li::before{background:#3987e5}
ul.tl.done li{border-left:3px solid #199e70}ul.tl.now li{border-left:3px solid #3987e5}
ul.tl.next li,ul.tl.later li{opacity:.82}
h2.tl-h.done{color:#3fbf8f}h2.tl-h.now{color:#6aa8f0}h2.tl-h.next,h2.tl-h.later{color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px 14px}
.grid .ct{font-size:12.5px;color:var(--ink2);margin-top:6px}.grid .ct em{color:var(--dim);font-style:normal}
svg.ch.sm .ax{font-size:13px}svg.ch.sm .ax.mid{display:none}
ul.plan li{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0;background:var(--panel);max-width:none}
ul.plan li p{margin:4px 0;color:var(--ink)}
ul.plan .meta{font-size:12.5px;color:var(--dim)}
ul.plan .area{display:inline-block;padding:0 7px;border:1px solid var(--line);border-radius:3px}
.pn{border:1px solid var(--line);border-radius:8px;padding:4px 14px 10px;margin:14px 0;background:var(--panel)}
.pn h2{margin:12px 0 2px}.pn .cap{font-size:13px;color:var(--dim);margin:2px 0 6px}
.pn .src{font-size:12px;color:var(--dim)}.pn .src a{color:var(--dim)}
svg.ch{width:100%;height:auto;display:block}
svg.ch .gl{stroke:var(--line);stroke-width:1}
svg.ch .ax{fill:var(--dim);font:11px var(--sans)}
svg.ch .yl{paint-order:stroke;stroke:var(--panel);stroke-width:3px}
svg.ch .vl{fill:var(--ink2);font:12px var(--sans)}
.lg2{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;margin:4px 0}
.lg2 i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:6px}
.lg2 em{color:var(--dim);font-style:normal}
.lg2.below{margin:8px 0 2px;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:3px 14px}
.lg2 svg{vertical-align:middle;margin-right:6px}
.lgb{all:unset;cursor:pointer;padding:2px 4px;border-radius:4px;font-size:12.5px;color:var(--ink)}
.lgb:hover{background:var(--line)}.lgb:focus-visible{outline:2px solid var(--accent)}
.lgb.off{opacity:.45}.lgb.off b{font-weight:normal}
.pn .foot{font-size:12.5px;color:var(--ink);margin:8px 0 2px}
.botl{display:inline-block;margin:6px 0}
@media(max-width:640px){svg.ch .ax{font-size:22px}svg.ch .vl{font-size:23px}svg.ch .ax.odd{display:none}
  svg.ch.sm .ax{font-size:26px}svg.ch.sm .ax.mid{display:none}
  .pn{padding:2px 10px 8px}}
</style>"""


TOGGLE_JS = """<script>
(function(){
  // Выбор линий в легенде. Выбор помнится в этом браузере (localStorage —
  // удобство, не данные: нет хранилища — работает умолчание).
  document.querySelectorAll('.pick').forEach(function(box){
    var key = 'fca.monitor.' + box.dataset.key, saved = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) {}
    function apply(id, on){
      box.querySelectorAll('g[data-s="' + id + '"]').forEach(function(g){ g.style.display = on ? '' : 'none'; });
      box.querySelectorAll('.lgb[data-s="' + id + '"]').forEach(function(b){
        b.classList.toggle('off', !on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); });
    }
    if (Array.isArray(saved)) box.querySelectorAll('.lgb').forEach(function(b){ apply(b.dataset.s, saved.indexOf(b.dataset.s) >= 0); });
    box.querySelectorAll('.lgb').forEach(function(b){
      b.addEventListener('click', function(){
        apply(b.dataset.s, b.classList.contains('off'));
        var on = []; box.querySelectorAll('.lgb:not(.off)').forEach(function(x){ on.push(x.dataset.s); });
        try { localStorage.setItem(key, JSON.stringify(on)); } catch (e) {}
      });
    });
  });
})();
</script>"""


def page(lang: str, plan: list[dict], data: dict | None, tab: str = "plan", bot_url: str = "") -> str:
    from . import seo
    t = T[lang]
    tabs = (f'<nav class="tabs"><a href="/{lang}/monitor"{" class=on" if tab == "plan" else ""}>{esc(t["tab_plan"])}</a>'
            f'<a href="/{lang}/monitor?tab=series"{" class=on" if tab == "series" else ""}>{esc(t["tab_series"])}</a></nav>')
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › {esc(t["h1"])}</div>',
            f'<h1>{esc(t["h1"])}</h1>', f'<p class="lead">{esc(t["lead"])}</p>']
    if bot_url:
        body.append(f'<a class="cta botl" href="{esc(bot_url)}">{esc(t["bot"])} →</a>')
    body.append(tabs)
    body.append(series_html(lang, data or {}) + TOGGLE_JS if tab == "series" else plan_html(lang, plan))
    canon = f"{seo.site()}/{lang}/monitor" + ("?tab=series" if tab == "series" else "")
    alts = [(lg, f"{seo.site()}/{lg}/monitor" + ("?tab=series" if tab == "series" else "")) for lg in seo.LANGS]
    alts.append(("x-default", f"{seo.site()}/en/monitor" + ("?tab=series" if tab == "series" else "")))
    h = seo.head(lang, t["title"], t["desc"], canon, alts) + STYLE
    return seo.shell(lang, "/monitor" + ("?tab=series" if tab == "series" else ""), h, "\n".join(body), on="monitor")


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
