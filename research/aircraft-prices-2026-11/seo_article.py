#!/usr/bin/env python3
"""Small, idempotent SEO and reader-first additions to the existing price report.

The source report is still generated from researched inputs. This module only
adds page-specific meta tags, an attributed quick answer, and internal links.
It never changes calculations or creates any additional URLs.
"""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ORIGIN = "https://flightcost.app"
SLUG = "aircraft-prices-2026-11"
LANGS = {"ru": "report.html", "en": "report.en.html", "de": "report.de.html"}

COPY = {
    "ru": {
        "title": "Сколько стоит самолёт: цена, лизинг и стоимость рейса | FlightCost",
        "description": "Сколько стоит самолёт и его лизинг: оценки Airbus A320neo, A321neo, исторические графики, пример стоимости одного рейса и расчёт ставки по источникам.",
        "heading": "Сколько стоит самолёт — краткий ответ",
        "subtitle": "Ориентиры I квартала 2026 года, не цены конкретных сделок. Валюты и периоды не смешиваются.",
        "appraisal": "A320neo, рыночная оценка нового ВС",
        "a320": "A320neo, лизинг нового ВС в месяц",
        "a321": "A321neo, лизинг нового ВС в месяц",
        "flight": "A320neo, часть стоимости условного рейса за счёт лизинга",
        "units_m": "≈ 56,3 млн USD",
        "units_a320": "395–424 тыс. USD",
        "units_a321": "456–488 тыс. USD",
        "units_flight": "2 508–2 692 EUR",
        "context": "Пример: Франкфурт — Барселона, 2,12 ч, 300 ч налёта в месяц. Это только владение, а не полная себестоимость рейса.",
        "source": "Опубликованные оценки IBA, I квартал 2026",
        "to_types": "Характеристики A320neo и A321neo",
        "to_calc": "Посчитать стоимость своего рейса в калькуляторе",
        "about": "Как цена самолёта связана со стоимостью перелёта",
        "about_text": "Цена покупки не списывается целиком на один рейс. В сценарии аренды стоимость владения на рейс = месячный лизинг ÷ налёт борта в месяц × блок-время рейса. Топливо, сборы, экипаж и ТОиР считаются отдельно; билет пассажиру не равен себестоимости рейса.",
        "faq_title": "Частые вопросы о стоимости самолёта",
        "q1": "Сколько стоит новый Airbus A320neo?",
        "a1": "Оценка рыночной стоимости нового A320neo в рассмотренном источнике IBA за I квартал 2026 года составляет около 56,3 млн USD. Это не объявленная цена сделки и не каталожная цена производителя.",
        "q2": "Сколько стоит лизинг Airbus A321neo?",
        "a2": "Для нового A321neo (A321-200NX) оценка IBA за I квартал 2026 года составляет 456–488 тыс. USD в месяц. Реальный договор зависит от возраста, комплектации, арендатора и условий обслуживания.",
        "q3": "Сколько стоит рейс самолёта или перелёт пассажира?",
        "a3": "Единой цены нет: маршрут, топливо, сборы, экипаж, обслуживание, аренда, налёт и загрузка меняют результат. В этой статье 2 508–2 692 EUR — лишь лизинговая часть одного условного рейса A320neo. Полную стоимость и безубыточный тариф рассчитывает калькулятор.",
        "date": "11 ноября 2026",
    },
    "en": {
        "title": "Aircraft cost: price, leasing and cost per flight | FlightCost",
        "description": "How much an aircraft costs: A320neo and A321neo market appraisals, historical lease charts and a sourced example of leasing cost per flight.",
        "heading": "How much does an aircraft cost? The short answer",
        "subtitle": "Q1 2026 appraisals, not disclosed transaction prices. Periods and currencies remain explicit.",
        "appraisal": "New A320neo, appraised market value",
        "a320": "New A320neo, monthly lease estimate",
        "a321": "New A321neo, monthly lease estimate",
        "flight": "A320neo, lease component of one illustrative flight",
        "units_m": "≈ USD 56.3 million",
        "units_a320": "USD 395–424 thousand",
        "units_a321": "USD 456–488 thousand",
        "units_flight": "EUR 2,508–2,692",
        "context": "Illustration: Frankfurt–Barcelona, 2.12 block hours, 300 monthly flight hours. Ownership component only, not total flight cost.",
        "source": "IBA published appraisals, Q1 2026",
        "to_types": "A320neo and A321neo aircraft details",
        "to_calc": "Calculate the total cost of a flight",
        "about": "From aircraft price to the cost of a flight",
        "about_text": "The purchase price is not charged in full to a flight. Under a leasing scenario, ownership per flight = monthly rent ÷ monthly aircraft utilisation × flight block hours. Fuel, airport fees, crew and maintenance are separate; a passenger fare is not the same as flight cost.",
        "faq_title": "Questions about aircraft prices and leasing",
        "q1": "How much does a new Airbus A320neo cost?",
        "a1": "The cited IBA appraisal for a new A320neo in Q1 2026 is approximately USD 56.3 million. This is neither a disclosed transaction price nor a manufacturer list price.",
        "q2": "How much does an Airbus A321neo cost to lease?",
        "a2": "For a new A321neo (A321-200NX), IBA appraised monthly lease rates at USD 456–488 thousand in Q1 2026. Actual contracts vary by age, configuration, customer and maintenance terms.",
        "q3": "What does one flight or a passenger trip cost?",
        "a3": "There is no universal price: route, fuel, airport charges, crew, maintenance, rent, utilisation and occupancy all matter. The EUR 2,508–2,692 here is only the lease component of an illustrative A320neo flight. Use the calculator for total cost and break-even fare.",
        "date": "11 November 2026",
    },
    "de": {
        "title": "Was kostet ein Flugzeug? Kaufpreis, Leasing und Flugkosten | FlightCost",
        "description": "Flugzeugpreise und Leasingraten: Marktwert A320neo, A321neo, historische Kurven und ein nachvollziehbares Beispiel für Leasingkosten je Flug.",
        "heading": "Was kostet ein Flugzeug? Die kurze Antwort",
        "subtitle": "Schätzungen des ersten Quartals 2026, keine veröffentlichten Einzeltransaktionspreise. Währungen und Zeiträume sind ausgewiesen.",
        "appraisal": "Neuer A320neo, geschätzter Marktwert",
        "a320": "Neuer A320neo, Leasing pro Monat",
        "a321": "Neuer A321neo, Leasing pro Monat",
        "flight": "A320neo, Leasinganteil eines Beispielflugs",
        "units_m": "≈ 56,3 Mio. USD",
        "units_a320": "395–424 Tsd. USD",
        "units_a321": "456–488 Tsd. USD",
        "units_flight": "2.508–2.692 EUR",
        "context": "Beispiel Frankfurt–Barcelona: 2,12 Blockstunden, 300 Flugstunden pro Monat. Nur Besitzkosten, nicht die gesamten Flugkosten.",
        "source": "Veröffentlichte IBA-Schätzungen, Q1 2026",
        "to_types": "Details zu A320neo und A321neo",
        "to_calc": "Gesamte Flugkosten berechnen",
        "about": "Vom Flugzeugpreis zu den Kosten eines Flugs",
        "about_text": "Der Kaufpreis wird nicht vollständig einem Flug zugerechnet. Bei Leasing gilt: Besitzkosten je Flug = Monatsrate ÷ monatliche Flugstunden × Blockzeit. Kraftstoff, Gebühren, Besatzung und Wartung werden getrennt berechnet; Flugpreis und Flugkosten sind nicht dasselbe.",
        "faq_title": "Häufige Fragen zu Flugzeugpreisen und Leasing",
        "q1": "Was kostet ein neuer Airbus A320neo?",
        "a1": "Die zitierte IBA-Marktbewertung für einen neuen A320neo beträgt im ersten Quartal 2026 ungefähr 56,3 Mio. USD. Dies ist weder ein offengelegter Kaufpreis noch ein Listenpreis.",
        "q2": "Was kostet das Leasing eines Airbus A321neo?",
        "a2": "IBA nennt für einen neuen A321neo (A321-200NX) im ersten Quartal 2026 monatlich 456–488 Tsd. USD. Die tatsächlichen Konditionen hängen von Alter, Ausstattung, Kunde und Wartungsvereinbarung ab.",
        "q3": "Was kostet ein Flug oder eine Reise pro Passagier?",
        "a3": "Einen Einheitspreis gibt es nicht. Strecke, Treibstoff, Gebühren, Personal, Wartung, Leasing, Auslastung und Nutzung zählen. Die 2.508–2.692 EUR hier sind nur der Leasinganteil eines beispielhaften A320neo-Flugs. Den Gesamtbetrag und den Break-even-Tarif zeigt der Rechner.",
        "date": "11. November 2026",
    },
}

IBA_SOURCE = ("https://iclg.com/practice-areas/aviation-finance-and-leasing/"
              "02-the-aviation-finance-market-robust-demand-entrenched-supply-chain-challenges-and-strong-market-performance/")

CSS = """<style id="fca-seo-price-style">
.seo-quick{margin:20px 0 24px;padding:16px 18px;border:1px solid var(--line, #484848);border-radius:12px;background:var(--panel,transparent)}
.seo-quick h2{margin:0 0 6px}.seo-quick .note{font-size:.91em;color:var(--dim,#999)}
.seo-quick-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:10px;margin:14px 0}
.seo-quick-item{border:1px solid var(--line,#444);border-radius:8px;padding:12px}
.seo-quick-item strong{display:block;font-size:1.12em;margin:4px 0;font-weight:600}
.seo-quick-item span{font-size:.85em;color:var(--dim,#aaa)}
.seo-links{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}.seo-links a{overflow-wrap:anywhere}
.seo-note{border-left:3px solid var(--blue,#6699cc);padding:4px 0 4px 14px;margin:18px 0}
.seo-faq h3{font-size:1.05em;margin:14px 0 4px}.seo-faq p{margin:0 0 9px}
</style>"""


def seo_url(lang: str) -> str:
    return f"{ORIGIN}/{lang}/research/{SLUG}"


def link(lang: str, suffix: str) -> str:
    return f"{ORIGIN}/{lang}{suffix}"


def quick_answer(lang: str) -> str:
    t = COPY[lang]
    cards = "".join(
        f'<div class="seo-quick-item"><span>{escape(t[label])}</span><strong>{escape(t[value])}</strong></div>'
        for label, value in (("appraisal", "units_m"), ("a320", "units_a320"),
                             ("a321", "units_a321"), ("flight", "units_flight")))
    return (
        f'<section id="fca-seo-answer" class="seo-quick" aria-labelledby="fca-seo-heading">'
        f'<h2 id="fca-seo-heading">{escape(t["heading"])}</h2>'
        f'<p>{escape(t["subtitle"])}</p>'
        f'<div class="seo-quick-grid">{cards}</div>'
        f'<p class="note">{escape(t["context"])}</p>'
        f'<p class="note"><a href="{escape(IBA_SOURCE,quote=True)}">{escape(t["source"])}</a></p>'
        f'<div class="seo-links"><a href="{link(lang,"/type/A20N")}">A320neo</a>'
        f'<a href="{link(lang,"/type/A21N")}">A321neo</a>'
        f'<a href="{link(lang,"/calc")}">{escape(t["to_calc"])}</a></div>'
        '</section>'
    )


def extra_section(lang: str) -> str:
    t = COPY[lang]
    faqs = ''.join(f'<h3>{escape(t["q"+str(i)])}</h3><p>{escape(t["a"+str(i)])}</p>' for i in (1, 2, 3))
    return (
        f'<section id="fca-seo-flight" class="seo-note"><h2>{escape(t["about"])}</h2>'
        f'<p>{escape(t["about_text"])}</p>'
        f'<p><a href="{link(lang,"/calc")}">{escape(t["to_calc"])}</a></p></section>'
        f'<section id="fca-seo-faq" class="seo-faq"><h2>{escape(t["faq_title"])}</h2>{faqs}</section>'
    )


def seo_head(lang: str) -> str:
    t = COPY[lang]
    canonical = seo_url(lang)
    structured = [
        {"@context":"https://schema.org", "@type":"Article", "headline":{
            "ru":"Сколько стоит самолёт: история цен и экономика лизинга",
            "en":"What an aircraft costs: price history and lease economics",
            "de":"Was ein Flugzeug kostet: Preisentwicklung und Leasingwirtschaft",
         }[lang],
         "description":t["description"], "inLanguage":lang,
         "datePublished":"2026-11-11", "dateModified":"2026-11-11",
         "author":{"@type":"Organization","name":"FlightCost"},
         "publisher":{"@type":"Organization","name":"FlightCost"},
         "mainEntityOfPage":{"@type":"WebPage","@id":canonical}},
        {"@context":"https://schema.org", "@type":"BreadcrumbList",
         "itemListElement":[
             {"@type":"ListItem","position":1,"name":"FlightCost","item":link(lang,"/calc")},
             {"@type":"ListItem","position":2,"name":{"ru":"Исследования","en":"Research","de":"Forschung"}[lang],"item":link(lang,"/research")},
             {"@type":"ListItem","position":3,"name":t["heading"],"item":canonical}]},
    ]
    return (
        f'<meta name="description" content="{escape(t["description"],quote=True)}">'
        f'<meta name="robots" content="index,follow">'
        f'<link rel="canonical" href="{canonical}">'
        + ''.join(f'<link rel="alternate" hreflang="{l}" href="{seo_url(l)}">' for l in LANGS)
        + f'<meta property="og:type" content="article"><meta property="og:url" content="{canonical}">'
        + f'<meta property="og:title" content="{escape(t["title"],quote=True)}">'
        + f'<meta property="og:description" content="{escape(t["description"],quote=True)}">'
        + '<meta name="twitter:card" content="summary">'
        + ''.join('<script type="application/ld+json">'+json.dumps(obj, ensure_ascii=False).replace('<','\\u003c')+'</script>' for obj in structured)
        + CSS
    )


def apply_to_html(html: str, lang: str) -> str:
    """Transform the already-built report; a repeated call is a no-op."""
    if lang not in LANGS:
        raise ValueError(f"Unknown language: {lang}")
    if 'id="fca-seo-answer"' in html:
        return html
    if html.count('</head>') != 1 or html.count('</body>') != 1:
        raise ValueError("Report does not contain one head and one body")
    if 'class="verdict"' not in html:
        raise ValueError("Expected price report summary missing")
    title, count = re.subn(r"<title>[^<]*</title>",
                           '<title>'+escape(COPY[lang]['title'])+'</title>', html, count=1)
    if count != 1:
        raise ValueError("Page title missing")
    html = title.replace('</head>', seo_head(lang)+'</head>', 1)
    draft_text = {
        "ru": "Черновик исследования · 11 ноября 2026 · перед публикацией требуется моделирование владельцем",
        "en": "Research draft · 11 November 2026 · owner modelling required before publication",
        "de": "Forschungsentwurf · 11. November 2026 · Modellprüfung durch den Eigentümer vor Veröffentlichung",
    }[lang]
    published = {"ru":"Исследование · 11 ноября 2026", "en":"Research · 11 November 2026",
                 "de":"Recherche · 11. November 2026"}[lang]
    if draft_text not in html and published not in html:
        raise ValueError("Expected research publication line missing")
    html = html.replace(draft_text, published, 1)
    # The summary block is near the start of the article and is already styled.
    html = html.replace('<div class="verdict">', quick_answer(lang)+'<div class="verdict">',1)
    # Keep the sources and methodology section in its original position.
    marker = '<details><summary>'
    idx = html.rfind(marker)
    if idx < 0:
        idx = html.rfind('</body>')
    html = html[:idx] + extra_section(lang) + html[idx:]
    return html


def validate_numbers(directory: Path) -> None:
    summary = json.loads((directory / "out/summary.json").read_text(encoding="utf-8"))
    observations = summary["recent_observations"]
    def find(kind: str, code: str):
        return next(x for x in observations if x["source_id"] == "iba-iclg-2026"
                    and x["icao"] == code and x["kind"] == kind
                    and x["period"] == "2026-Q1" and x["age"] == "new")
    value = find("value", "A20N")
    a320 = find("lease", "A20N")
    a321 = find("lease", "A21N")
    example = summary["example"]
    expected = (round(value["amount_low_usd"]),
                round(a320["amount_low_usd"]), round(a320["amount_high_usd"]),
                round(a321["amount_low_usd"]), round(a321["amount_high_usd"]))
    if expected != (56300000, 395000, 424000, 456000, 488000):
        raise ValueError("SEO quick answer requires revision: source values changed")
    if (round(example["research_ownership_eur_flight_low"]),
        round(example["research_ownership_eur_flight_high"])) != (2508, 2692):
        raise ValueError("SEO quick answer requires revision: example assumptions changed")


def process_three(directory: Path = HERE) -> None:
    validate_numbers(directory)
    for lang, filename in LANGS.items():
        p = directory / filename
        old = p.read_text(encoding='utf-8')
        new = apply_to_html(old,lang)
        if new != old:
            p.write_text(new, encoding='utf-8')


if __name__ == '__main__':
    process_three()
