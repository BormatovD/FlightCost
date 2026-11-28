"""Render the annual outlook and the dated quarterly forecast comparison."""
from __future__ import annotations

from datetime import date
from html import escape
import json
import math
from pathlib import Path


ACCURACY_LABEL = {
    "ru": "Проверка прогноза",
    "en": "Forecast tracking",
    "de": "Prognosevergleich",
}

TEXT = {
    "ru": {
        "annual": "Мировой пассажиропоток",
        "annual_unit": "Млн пассажирских сегментов",
        "annual_note": "Белая линия объединяет годовые отчёты ИКАО до 2020 года включительно и Safety Report с 2021 года. Охват источников различается. Ориентиры Airbus и Boeing переведены в сегменты по принятой в расчёте средней дальности. Покрытие парком — расчётный объём перевозок, доступный при заданных поставках.",
        "quarterly": "Мировой пассажирооборот по кварталам",
        "quarterly_unit": "Млрд платных пассажиро-километров (RPK)",
        "quarterly_note": "Пустые кружки обозначают предварительные оценки. Ошибка = 100% × (прогноз − факт) / факт. Считаем её после публикации квартального итога IATA по оценкам, зафиксированным до выхода первой статистики за этот квартал.",
        "period": "Период",
        "status": "Статус",
        "details": "Таблица данных",
        "issued": "Пересчёт от",
        "locked": "Зафиксировано",
        "scored": "Ошибка рассчитана",
        "pending": "Ожидаем итог IATA",
        "preview": "Предварительная оценка",
        "no_frozen_forecast": "Факт IATA",
        "awaiting_data": "Ожидаем данные",
        "icao": "ИКАО · факт",
        "iata": "IATA · факт",
        "prior": "FlightCost · прежний",
        "updated": "FlightCost · обновлённый",
        "fleet": "Покрытие парком",
        "trend": "Десятилетний тренд",
    },
    "en": {
        "annual": "Global passenger traffic",
        "annual_unit": "Millions of passenger segments",
        "annual_note": "The white line combines ICAO Annual Reports through 2020 and the Safety Report from 2021. Their coverage differs. The Airbus and Boeing reference forecasts are converted to segments using the model’s assumed average segment distance. Fleet coverage is the volume the fleet could carry under the delivery assumptions.",
        "quarterly": "Global passenger traffic by quarter",
        "quarterly_unit": "Billions of revenue passenger-kilometres (RPK)",
        "quarterly_note": "Open circles mark preliminary forecasts. Error = 100% × (forecast − observed) / observed. We score forecasts locked before the first data for the quarter once IATA publishes the quarterly total.",
        "period": "Period",
        "status": "Status",
        "details": "Data table",
        "issued": "Update dated",
        "locked": "Locked",
        "scored": "Error measured",
        "pending": "Awaiting IATA total",
        "preview": "Preliminary outlook",
        "no_frozen_forecast": "IATA observation",
        "awaiting_data": "Awaiting data",
        "icao": "ICAO · observed",
        "iata": "IATA · observed",
        "prior": "FlightCost · previous",
        "updated": "FlightCost · updated",
        "fleet": "Fleet coverage",
        "trend": "Ten-year trend",
    },
    "de": {
        "annual": "Weltweites Passagieraufkommen",
        "annual_unit": "Millionen Passagiersegmente",
        "annual_note": "Die weiße Linie verbindet die ICAO-Jahresberichte bis einschließlich 2020 mit dem Safety Report ab 2021. Der Erfassungsumfang unterscheidet sich. Für die Umrechnung der Referenzprognosen von Airbus und Boeing in Segmente verwenden wir die im Modell angenommene mittlere Segmentdistanz. Die Flottenabdeckung gibt an, welches Aufkommen die Flotte bei den angenommenen Auslieferungen bewältigen könnte.",
        "quarterly": "Weltweite Verkehrsleistung je Quartal",
        "quarterly_unit": "Milliarden verkaufte Passagierkilometer (RPK)",
        "quarterly_note": "Offene Kreise markieren vorläufige Prognosen. Fehler = 100 % × (Prognose − Istwert) / Istwert. Sobald IATA den Quartalswert veröffentlicht, prüfen wir die Prognosen, die vor den ersten Daten für das Quartal festgeschrieben wurden.",
        "period": "Zeitraum",
        "status": "Status",
        "details": "Datentabelle",
        "issued": "Aktualisierung vom",
        "locked": "Festgeschrieben",
        "scored": "Fehler berechnet",
        "pending": "IATA-Quartalswert ausstehend",
        "preview": "Vorläufige Prognose",
        "no_frozen_forecast": "IATA-Istwert",
        "awaiting_data": "Daten ausstehend",
        "icao": "ICAO · Istwert",
        "iata": "IATA · Istwert",
        "prior": "FlightCost · bisher",
        "updated": "FlightCost · aktualisiert",
        "fleet": "Flottenabdeckung",
        "trend": "Zehnjahrestrend",
    },
}

STYLE = """
<style>
#forecast-accuracy { border-top: 1px solid var(--line); margin-top: 22px; padding-top: 22px; scroll-margin-top: 12px; }
#forecast-accuracy :is(h2,h3) { margin: 0; }
#forecast-accuracy .fa-panel { margin-top: 18px; padding: clamp(12px, 2vw, 22px); background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
#forecast-accuracy .fa-note { color: var(--dim); font-size: .875rem; margin: 6px 0 0; }
#forecast-accuracy .fa-figure { margin: 14px 0; }
#forecast-accuracy canvas { display: block; width: 100%; height: clamp(200px, 32vw, 320px); }
#forecast-accuracy .fa-legend { display: flex; flex-wrap: wrap; gap: 5px 18px; list-style: none; padding: 0; margin: 7px 0 0; font-size: .8rem; }
#forecast-accuracy .fa-legend li { display: inline-flex; align-items: center; gap: 7px; }
#forecast-accuracy .fa-swatch { width: 19px; border-top-width: 2px; border-top-style: var(--fa-pattern, solid); border-top-color: var(--fa-color); }
#forecast-accuracy .fa-scroll { overflow-x: auto; }
#forecast-accuracy table { min-width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: .85rem; }
#forecast-accuracy :is(th,td) { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line); }
#forecast-accuracy :is(th,td):first-child, #forecast-accuracy .fa-status { text-align: left; }
#forecast-accuracy :is(td,th[scope=row]) { white-space: nowrap; }
#forecast-accuracy .fa-error { display: block; color: var(--dim); font-size: .76rem; }
#forecast-accuracy details { margin-top: 10px; }
#forecast-accuracy details > summary { width: fit-content; }
</style>
"""


def _num(value, scale=1):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value / scale
    return None


def _fmt(value, lang, *, signed=False):
    if value is None:
        return "—"
    if abs(value) < 0.05:
        value = 0
    number = format(value, "+,.1f" if signed and value else ",.1f").removesuffix(".0")
    if lang == "ru":
        return number.replace(",", "\u00a0").replace(".", ",")
    if lang == "de":
        return number.translate(str.maketrans(",.", ".,"))
    return number


def _date(value, lang):
    if not isinstance(value, str):
        return ""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return ""
    if lang == "en":
        month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        return f"{parsed.day} {month[parsed.month - 1]} {parsed.year}"
    return parsed.strftime("%d.%m.%Y")


def _series(text, specs):
    return [
        {"key": key, "label": text.get(label, label), "color": color, "dash": dash}
        for key, label, color, dash in specs
    ]


def _figure(title, unit, rows, series, lang, *, quarterly=False):
    if not rows:
        return ""
    visible = [item for item in series if any(row.get(item["key"]) is not None for row in rows)]
    if not visible:
        return ""
    legend = []
    for item in visible:
        style = "dotted" if item["dash"] == [2, 3] else "dashed" if item["dash"] else "solid"
        legend.append(
            f'<li><span class="fa-swatch" aria-hidden="true" style="--fa-color:'
            f'{item["color"]};--fa-pattern:{style}"></span>{escape(item["label"])}</li>'
        )
    observed_key = "actual" if quarterly else "icao"
    payload = json.dumps({"lang": lang, "quarterly": quarterly, "observedKey": observed_key,
                          "rows": rows, "series": visible},
                         ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    return (
        f'<figure class="fa-figure" data-fa-chart hidden>'
        f'<canvas role="img" aria-label="{escape(title)} · {escape(unit)}"></canvas>'
        f'<ul class="fa-legend" aria-label="{escape(unit)}">{"".join(legend)}</ul>'
        f'<script type="application/json">{payload}</script></figure>'
    )


def _table(text, unit, rows, series, lang, *, statuses=False):
    if not rows:
        return ""
    headers = [f'<th scope="col">{text["period"]}</th>']
    headers.extend(f'<th scope="col">{escape(item["label"])}</th>' for item in series)
    if statuses:
        headers.append(f'<th scope="col" class="fa-status">{text["status"]}</th>')
    body = []
    for row in rows:
        cells = [f'<th scope="row">{escape(row["label"])}</th>']
        for item in series:
            key = item["key"]
            cell = _fmt(row.get(key), lang)
            error = row.get("errors", {}).get(key)
            if error is not None and row.get(key) is not None:
                gap = "\u00a0" if lang == "de" else ""
                cell += f'<span class="fa-error">{_fmt(error, lang, signed=True)}{gap}%</span>'
            cells.append(f"<td>{cell}</td>")
        if statuses:
            status = text.get(row.get("status"), "—")
            locked = _date(row.get("locked"), lang)
            if locked and row.get("status") in ("pending", "scored"):
                status += f'<br><small>{text["locked"]} {locked}</small>'
            cells.append(f'<td class="fa-status">{status}</td>')
        body.append(f'<tr>{"".join(cells)}</tr>')
    return (
        f'<div class="fa-scroll" tabindex="0" role="region" aria-label="{escape(unit)}">'
        f'<table aria-label="{escape(unit)}"><thead><tr>{"".join(headers)}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _yearly(edition, text, lang):
    series = _series(text, (
        ("icao", "icao", "var(--ink)", []),
        ("prior", "prior", "var(--calc)", [6, 5]),
        ("updated", "updated", "var(--calc)", []),
        ("airbus", "Airbus", "var(--doc)", [7, 4]),
        ("boeing", "Boeing", "var(--doc)", [2, 3]),
        ("fleet", "fleet", "var(--dim)", [6, 3, 2, 3]),
    ))
    rows = []
    for item in edition.get("annual") or ():
        year = item.get("year")
        if not isinstance(year, int) or isinstance(year, bool):
            continue
        rows.append({
            "label": str(year),
            "icao": _num(item.get("icao_observed_segments"), 1_000_000),
            "prior": _num(item.get("joint_segments"), 1_000_000),
            "updated": _num(item.get("updated_joint_segments"), 1_000_000),
            "airbus": _num(item.get("airbus_equivalent_segments"), 1_000_000),
            "boeing": _num(item.get("boeing_equivalent_segments"), 1_000_000),
            "fleet": _num(item.get("updated_fleet_covered_segments"), 1_000_000),
        })
    rows.sort(key=lambda row: row["label"])
    title, unit = text["annual"], text["annual_unit"]
    return (
        f'<div class="fa-panel"><h3>{title}</h3><p class="fa-note">{unit}</p>'
        f'{_figure(title, unit, rows, series, lang)}<p class="fa-note">{text["annual_note"]}</p>'
        f'<details><summary>{text["details"]}</summary>{_table(text, unit, rows, series, lang)}</details></div>'
    ) if rows else ""


def _quarterly(edition, text, lang):
    series = _series(text, (
        ("actual", "iata", "var(--ink)", []),
        ("current", "prior", "var(--calc)", [6, 5]),
        ("updated", "updated", "var(--calc)", []),
        ("airbus", "Airbus", "var(--doc)", [7, 4]),
        ("boeing", "Boeing", "var(--doc)", [2, 3]),
        ("trend", "trend", "var(--dim)", [6, 3, 2, 3]),
    ))
    rows = []
    for item in edition.get("quarterly") or ():
        period = item.get("quarter")
        if not isinstance(period, str):
            continue
        status = item.get("scoring")
        row = {"label": period, "status": status, "locked": item.get("forecast_frozen_on")}
        row.update({entry["key"]: _num(item.get(f'{entry["key"]}_rpk_billion')) for entry in series})
        if status == "scored" and row["actual"] is not None and row["actual"] > 0:
            row["errors"] = {entry["key"]: _num(item.get(f'{entry["key"]}_error_pct')) for entry in series[1:]}
        rows.append(row)
    rows.sort(key=lambda row: row["label"])
    title, unit = text["quarterly"], text["quarterly_unit"]
    return (
        f'<div class="fa-panel"><h3>{title}</h3><p class="fa-note">{unit}</p>'
        f'{_figure(title, unit, rows, series, lang, quarterly=True)}'
        f'{_table(text, unit, rows, series, lang, statuses=True)}'
        f'<p class="fa-note">{text["quarterly_note"]}</p></div>'
    ) if rows else ""


def render_accuracy(edition: dict, lang: str) -> bytes:
    """Build a report section with localized tables and charts for a dated edition."""
    lang = lang if lang in TEXT else "ru"
    text = TEXT[lang]
    annual = _yearly(edition, text, lang)
    quarterly = _quarterly(edition, text, lang)
    if not (annual or quarterly):
        return b""
    issued = _date(edition.get("issued_on"), lang)
    credit = f'<p class="fa-note">{text["issued"]} {issued}</p>' if issued else ""
    script = Path(__file__).with_name("web").joinpath("forecast-accuracy.js").read_text(encoding="utf-8")
    return (
        f'{STYLE}<section id="forecast-accuracy" class="brief-world" aria-labelledby="fa-heading" lang="{lang}">'
        f'<h2 id="fa-heading">{ACCURACY_LABEL[lang]}</h2>{credit}{annual}{quarterly}</section><script>{script}</script>'
    ).encode()
