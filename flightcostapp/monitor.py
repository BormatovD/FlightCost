"""Страница «План и показатели» (/{lang}/monitor): открытый план работ и ряды
изменений ключевых показателей (О6, 06.11.2026).

ПЛАН — `data/plan.yaml`, правится коммитом. Предложение из бота после
приёмки приходит владельцу готовой записью; автор подписан так, как сам
указал в боте (имя и ник из Телеграма бот не хранит).

РЯДЫ — из той же базы, что расчёт, и только из того, что разрешено
показывать (решение 219):

  * топливо — спот USGC (EIA, открыт) помесячно, USD/т; демпфер России —
    `data/fuel/_ru_damper.yaml`, руб./т;
  * сборы аэропортов — медиана контрольного оборота A320 по регионам
    (`data/charges/_regional.yaml`, решение 234): снимок, а не ряд — ряд
    растёт с новыми редакциями тарифов;
  * аэронавигация — индекс ставок en-route: EUROCONTROL (CRCO, строки
    закрыты лицензией — только медиана по зонам, индексом) и ФАС России;
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
        "fuel_note": "Цена в крыло в расчёте = спот × множитель региона (решение 235); множители пока по одной "
                     "точке на регион, поэтому отдельного ряда по регионам нет — это пункт плана.",
        "ch_h": "Сборы аэропортов по регионам",
        "ch_cap": "Контрольный оборот A320 (78 т, 148 пасс., июль): медиана по тарифам с документом и разброс, EUR",
        "ch_note": "Снимок на дату сборки, а не ряд: тарифы обновляются раз в год, и ряд растёт с каждой новой "
                   "редакцией. Неофициальные данные сообщества сюда не входят.",
        "ch_n": "аэропортов",
        "ans_h": "Аэронавигация",
        "ans_cap": "Ставки en-route, индекс: медиана по зонам, первый общий месяц = 100",
        "ans_eu": "EUROCONTROL (зоны ЕКАО)", "ans_ru": "Россия (ФАС)",
        "ans_note": "Ставки EUROCONTROL по лицензии не показываются строками — только медианой по зонам. "
                    "В расчёте участвует ставка каждой зоны.",
        "mro_h": "ТОиР по классам ВС",
        "mro_cap": "Полный ТОиР на блок-час, перевозчики США (Form 41), медиана, взвешенная блок-часами, "
                   "номинальные USD",
        "mro_u": "USD/блок-ч",
        "c_narrow": "узкофюзеляжные", "c_wide": "широкофюзеляжные", "c_regional": "региональные",
        "own_h": "Владение по типам ВС",
        "own_cap": "Аренда + амортизация на борт в месяц, перевозчики США (Form 41), медиана, номинальные USD",
        "own_u": "USD/борт·мес",
        "own_note": "Это не ставка лизинга одного договора: в сумме и собственные, и арендованные борта, по "
                    "балансовой стоимости. Открытого ряда ставок лизинга по типам нет — ищем.",
        "missing": "В базе нет ряда: {what}.",
        "src": "Источник", "last": "последнее", "upd": "Обновлено",
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
        "fuel_note": "Into-plane price in the calculation = spot × regional multiplier (decision 235); the "
                     "multipliers rest on one point per region, so there is no regional series yet — it is on the plan.",
        "ch_h": "Airport charges by region",
        "ch_cap": "Reference A320 turnaround (78 t, 148 pax, July): median over documented tariffs and range, EUR",
        "ch_note": "A snapshot at build date, not a series: tariffs change once a year, and the series grows with "
                   "each new edition. Unofficial community data is not included.",
        "ch_n": "airports",
        "ans_h": "Air navigation",
        "ans_cap": "En-route rates, index: median across zones, first common month = 100",
        "ans_eu": "EUROCONTROL (ECAC zones)", "ans_ru": "Russia (FAS)",
        "ans_note": "EUROCONTROL rates are not shown row by row under their licence — only as a median across "
                    "zones. The calculation uses each zone's own rate.",
        "mro_h": "Maintenance by aircraft class",
        "mro_cap": "Total maintenance per block hour, US carriers (Form 41), block-hour-weighted median, nominal USD",
        "mro_u": "USD/block h",
        "c_narrow": "narrowbody", "c_wide": "widebody", "c_regional": "regional",
        "own_h": "Ownership by aircraft type",
        "own_cap": "Rent + depreciation per aircraft per month, US carriers (Form 41), median, nominal USD",
        "own_u": "USD/aircraft·month",
        "own_note": "Not a single lease rate: owned and leased aircraft at book value together. There is no open "
                    "series of lease rates by type — we are looking.",
        "missing": "No series in the database: {what}.",
        "src": "Source", "last": "latest", "upd": "Updated",
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
        "fuel_note": "Preis ins Flugzeug in der Berechnung = Spot × Regionsfaktor (Entscheidung 235); die Faktoren "
                     "beruhen auf einem Punkt je Region, daher gibt es noch keine regionale Reihe — sie steht im Plan.",
        "ch_h": "Flughafenentgelte nach Region",
        "ch_cap": "Referenz-Umlauf A320 (78 t, 148 Pax, Juli): Median der belegten Tarife und Spanne, EUR",
        "ch_note": "Momentaufnahme zum Erstellungsdatum, keine Reihe: Tarife ändern sich einmal im Jahr, die Reihe "
                   "wächst mit jeder neuen Ausgabe. Inoffizielle Community-Daten sind nicht enthalten.",
        "ch_n": "Flughäfen",
        "ans_h": "Flugsicherung",
        "ans_cap": "Streckengebühren, Index: Median über Zonen, erster gemeinsamer Monat = 100",
        "ans_eu": "EUROCONTROL (ECAC-Zonen)", "ans_ru": "Russland (FAS)",
        "ans_note": "EUROCONTROL-Sätze werden laut Lizenz nicht zeilenweise gezeigt — nur als Median über Zonen. "
                    "Die Berechnung nutzt den Satz jeder Zone.",
        "mro_h": "Instandhaltung nach Flugzeugklasse",
        "mro_cap": "Instandhaltung gesamt je Blockstunde, US-Airlines (Form 41), nach Blockstunden gewichteter "
                   "Median, nominale USD",
        "mro_u": "USD/Blockstd.",
        "c_narrow": "Schmalrumpf", "c_wide": "Großraum", "c_regional": "Regional",
        "own_h": "Besitz nach Flugzeugtyp",
        "own_cap": "Miete + Abschreibung je Flugzeug und Monat, US-Airlines (Form 41), Median, nominale USD",
        "own_u": "USD/Flugzeug·Monat",
        "own_note": "Kein einzelner Leasingsatz: eigene und geleaste Flugzeuge zusammen, zum Buchwert. Eine offene "
                    "Reihe von Leasingsätzen nach Typ gibt es nicht — wir suchen.",
        "missing": "Keine Reihe in der Datenbank: {what}.",
        "src": "Quelle", "last": "zuletzt", "upd": "Aktualisiert",
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
    t = T[lang]
    parts = [f'<p class="dim">{esc(t["plan_honest"])}</p>']
    for st in STATUSES:
        rows = [x for x in items if x["status"] == st]
        if not rows:
            continue
        if st == "done":
            rows.sort(key=lambda x: str(x.get("done")), reverse=True)
        parts.append(f'<h2>{esc(t["st_" + st])} <span class="tag">{len(rows)}</span></h2><ul class="plan">')
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
    return {"spot": monthly, "damper": damper}


def _charges() -> dict:
    if not REGIONAL.exists():
        return {}
    doc = yaml.safe_load(REGIONAL.read_text(encoding="utf-8")) or {}
    rows = []
    for code, r in (doc.get("regions") or {}).items():
        rng = r.get("range_eur") or [None, None]
        rows.append({"code": code, "name": r.get("name") or code, "median": r.get("median_eur"),
                     "lo": rng[0], "hi": rng[1], "n": r.get("n")})
    rows.sort(key=lambda r: -(r["median"] or 0))
    return {"built": str(doc.get("built") or ""), "rows": rows}


REGION_NAMES = {
    "europe": {"en": "Europe", "de": "Europa"}, "russia_cis": {"en": "Russia and CIS", "de": "Russland und GUS"},
    "india": {"en": "India", "de": "Indien"}, "asia_gulf": {"en": "Asia and the Gulf", "de": "Asien und Golf"},
    "africa": {"en": "Africa", "de": "Afrika"}, "world": {"en": "Rest of world", "de": "Übrige Welt"},
}


def _ans(store) -> dict:
    eu = _history(store, "enroute_rate")
    crco = {k: v for k, v in eu.items() if "/" not in k}               # CRCO: ключ — зона
    fas = {k: v for k, v in eu.items() if "/" in k}                    # ФАС: зона/эксплуатант/рейс
    src = dict(store.db.execute(
        "SELECT key, source_id FROM facts WHERE domain = 'enroute_rate' GROUP BY key"))
    crco = {k: v for k, v in crco.items() if src.get(k) == "crco_enroute_rates"}
    fas = {k: v for k, v in fas.items() if src.get(k) == "fas_ans_rates"}
    return {"eu": rate_index(crco), "ru": rate_index(fas), "n_eu": len(crco), "n_ru": len(fas)}


def _form41(store) -> dict:
    from .bench import _wq, carrier_rows
    try:
        _, meta = carrier_rows(store, None)
    except Exception:                                      # noqa: BLE001 — нет Form 41 в базе
        return {}
    mro: dict = defaultdict(list)
    own: dict = defaultdict(list)
    bh_type: dict = defaultdict(float)
    for y in meta.get("years") or []:
        rows, _ = carrier_rows(store, y)
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
            mro[c].append((str(y), round(_wq(pairs, 0.5))))
        for ic, pairs in by_type.items():
            own[ic].append((str(y), round(_wq(pairs, 0.5))))
    top = sorted((ic for ic in own if len(own[ic]) >= 2), key=lambda ic: -bh_type[ic])[:OWN_TYPES_MAX]
    return {"mro": dict(mro), "own": {ic: own[ic] for ic in top}}


def build(store) -> dict:
    """Все ряды страницы. Медленная часть — Form 41 за все годы; витрина
    кэширует результат до смены базы."""
    out = {"fuel": _fuel(store), "charges": _charges(), "ans": _ans(store), "built": date.today().isoformat()}
    out.update(_form41(store))
    return out


# ── рисование ─────────────────────────────────────────────────────────────

def _fmt(v: float, lang: str) -> str:
    if v is None:
        return "—"
    s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"
    return s.replace(",", " ").replace(".", "," if lang != "en" else ".")


def line_chart(lines: list[tuple[str, list]], lang: str, unit: str = "", w: int = 720, h: int = 240) -> str:
    """SVG-линии по категориям времени (месяц «2026-05» или год «2024»).
    Подпись каждой линии — текстом справа и в легенде: цвет не единственный
    признак. Без скрипта: страница читается и роботом, и при печати."""
    lines = [(n, pts) for n, pts in lines if pts]
    if not lines:
        return ""
    xs = sorted({p[0] for _, pts in lines for p in pts})
    ys = [p[1] for _, pts in lines for p in pts]
    lo, hi = min(ys), max(ys)
    if lo == hi:
        lo, hi = lo * 0.9, hi * 1.1 or 1
    pad = (hi - lo) * 0.08
    lo, hi = max(0, lo - pad) if lo >= 0 else lo - pad, hi + pad
    L, R, Tp, B = 6, 10, 22, 26                     # подписи оси Y — внутри поля, над линейкой
    pw, ph = w - L - R, h - Tp - B

    # Ось времени настоящая, а не по порядку: месяцы демпфера идут с
    # пропусками, и равные шаги между точками исказили бы скорость роста.
    def tnum(x):
        return int(x[:4]) + ((int(x[5:7]) - 1) / 12 if len(x) >= 7 else 0)
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
    g = []
    v = math.ceil(lo / step) * step
    while v <= hi:
        y = Y(v)
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{y:.1f}" y2="{y:.1f}" class="gl"/>'
                 f'<text x="{L + 2}" y="{y - 4:.1f}" class="ax">'
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
        odd = " odd" if n % 2 and i not in (0, len(xs) - 1) else ""
        g.append(f'<text x="{X(xs[i]):.1f}" y="{h - 6}" class="ax{odd}" text-anchor="{anc}">{esc(xs[i])}</text>')
    paths, legend = [], []
    for i, (name, pts) in enumerate(lines):
        c = COLORS[i % len(COLORS)]
        d = " ".join(f'{"M" if j == 0 else "L"}{X(x):.1f},{Y(y):.1f}' for j, (x, y) in enumerate(pts))
        paths.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2"/>')
        if len(pts) <= 24:
            paths.extend(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="{c}"><title>{esc(name)} · '
                         f'{esc(x)}: {esc(_fmt(y, lang))} {esc(unit)}</title></circle>' for x, y in pts)
        lx, ly = pts[-1]
        legend.append(f'<span><i style="background:{c}"></i>{esc(name)}: <b>{esc(_fmt(ly, lang))}</b>'
                      f' <em>({esc(lx)})</em></span>')
    svg = (f'<svg viewBox="0 0 {w} {h}" class="ch" role="img" preserveAspectRatio="none">'
           + "".join(g) + "".join(paths) + "</svg>")
    return f'<div class="lg2">{"".join(legend)}</div>{svg}'


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
    out = []
    f = d.get("fuel") or {}
    body = (line_chart([(t["fuel_spot_u"], f.get("spot") or [])], lang, t["fuel_spot_u"])
            or miss("jet_fuel_price spot/USGC"))
    body2 = line_chart([(t["fuel_dmp_u"], f.get("damper") or [])], lang, t["fuel_dmp_u"])
    out.append(_panel(t["fuel_h"], t["fuel_spot"], body
                      + (f'<p class="cap">{esc(t["fuel_dmp"])}</p>{body2}' if body2 else ""),
                      t["fuel_note"],
                      f'{esc(t["src"])}: <a href="https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm">EIA</a> · '
                      f'{"Рейтер через СМИ" if lang == "ru" else "Reuters via media"} '
                      f'(<a href="https://github.com/BormatovD/FlightCost/blob/main/data/fuel/_ru_damper.yaml">'
                      f'_ru_damper.yaml</a>)'))
    ch = d.get("charges") or {}
    out.append(_panel(t["ch_h"], t["ch_cap"] + (f" · {ch['built']}" if ch.get("built") else ""),
                      range_chart(ch.get("rows") or [], lang) or miss("data/charges/_regional.yaml"),
                      t["ch_note"], f'{esc(t["src"])}: <a href="/{lang}/research/charges-2026-10">'
                      f'{"исследование сборов" if lang == "ru" else "charges research" if lang == "en" else "Entgelt-Recherche"}</a>'))
    a = d.get("ans") or {}
    lines = [(f'{t["ans_eu"]}, {a.get("n_eu", 0)}', a.get("eu") or []),
             (f'{t["ans_ru"]}, {a.get("n_ru", 0)}', a.get("ru") or [])]
    out.append(_panel(t["ans_h"], t["ans_cap"], line_chart(lines, lang, "") or miss("enroute_rate"),
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
svg.ch .vl{fill:var(--ink2);font:12px var(--sans)}
.lg2{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;margin:4px 0}
.lg2 i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:6px}
.lg2 em{color:var(--dim);font-style:normal}
.botl{display:inline-block;margin:6px 0}
@media(max-width:640px){svg.ch .ax{font-size:22px}svg.ch .vl{font-size:23px}svg.ch .ax.odd{display:none}
  .pn{padding:2px 10px 8px}}
</style>"""


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
    body.append(series_html(lang, data or {}) if tab == "series" else plan_html(lang, plan))
    canon = f"{seo.site()}/{lang}/monitor" + ("?tab=series" if tab == "series" else "")
    alts = [(lg, f"{seo.site()}/{lg}/monitor" + ("?tab=series" if tab == "series" else "")) for lg in seo.LANGS]
    alts.append(("x-default", f"{seo.site()}/en/monitor" + ("?tab=series" if tab == "series" else "")))
    h = seo.head(lang, t["title"], t["desc"], canon, alts) + STYLE
    return seo.shell(lang, "/monitor" + ("?tab=series" if tab == "series" else ""), h, "\n".join(body), on="monitor")


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
