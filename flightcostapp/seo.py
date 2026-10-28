"""Страницы для поисковиков и ИИ-ассистентов: языковые адреса, «о сервисе»,
типы ВС, robots.txt, sitemap.xml, llms.txt.

Зачем отдельный модуль. Витрина — одно приложение на скриптах: язык
выбирается в браузере, текста о том, что это за сервис, на странице нет.
Поисковик видит один адрес, одну (случайную) языковую версию и подписи
полей. Здесь — то, что он может прочитать без скриптов:

- `/ru/`, `/en/`, `/de/` — та же витрина, но язык задан адресом, а в
  заголовке страницы — название, описание, связи языковых версий
  (hreflang) и разметка schema.org. `/` остаётся как был (язык браузера)
  и служит версией «по умолчанию» (x-default).
- `/<язык>/about` — что считает сервис, откуда данные, вопросы и ответы.
- `/<язык>/types` и `/<язык>/type/<ИКАО>` — страница каждого типа ВС из
  справочника: паспорт с источником у каждой величины и заготовка
  калькулятора (лизинг, ТОиР, экипаж). Это единственное содержание сайта,
  которого нет больше нигде в открытом виде, — им сайт и находится.

Числа на страницах типов — те же, что видит калькулятор (домен `aircraft`
хранилища и `fleet.parametric`), а не отдельная копия: правка справочника
меняет страницу.
"""

from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import quote

LANGS = ("ru", "en", "de")
REPO = "https://github.com/BormatovD/FlightCost"
OPENAP = "https://github.com/TUDelft-CNS-ATM/openap"
# Ключ IndexNow — не секрет: по протоколу он и должен лежать открытым файлом
# на сайте (`/<ключ>.txt`), им Bing и Яндекс проверяют, что адреса
# присылает владелец домена.
INDEXNOW_KEY = "6f1c2a9e4b7d48e3a05c9d1f8b2e7a64"
LANG_PATH = re.compile(r"^/(ru|en|de)(/.*)?$")
TYPE_CODE = re.compile(r"^[A-Z0-9]{2,4}$")
CYR = re.compile(r"[А-Яа-яЁё]")


def site() -> str:
    """Адрес сайта без косой черты в конце: `FCA_SITE_URL` или flightcost.app."""
    return (os.environ.get("FCA_SITE_URL") or "https://flightcost.app").rstrip("/")


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ── тексты ─────────────────────────────────────────────────────────────────

T = {
    "ru": {
        "brand_tag": "расчёт экономики авиамаршрута",
        "home_title": "Расчёт экономики авиамаршрута бесплатно — стоимость рейса и безубыточная загрузка | FlightCost",
        "home_desc": ("Бесплатный онлайн-калькулятор экономики авиарейса: топливо, сборы аэропортов и аэронавигации, "
                      "экипаж, ТОиР, лизинг, безубыточный чек и загрузка. Любой маршрут и тип ВС, источник у каждой цифры. "
                      "Без регистрации, открытый код."),
        "home_h1": "Бесплатный расчёт экономики авиамаршрута",
        "nav_calc": "Расчёт", "nav_types": "Типы ВС", "nav_about": "О сервисе", "nav_data": "Данные",
        "nav_map": "Карта данных",
        "about_title": "О сервисе: бесплатный калькулятор экономики авиарейса | FlightCost",
        "about_desc": ("Что считает FlightCost, откуда берутся данные и насколько им можно верить. Открытый бесплатный "
                       "инструмент для расчёта себестоимости рейса и сети маршрутов."),
        "types_title": "Типы самолётов: характеристики и экономика эксплуатации | FlightCost",
        "types_desc": ("Справочник типов ВС для расчёта маршрута: кресла, массы, дальность, двигатели, "
                       "ставки лизинга, ТОиР и экипажа — с источником каждой величины."),
        "types_h1": "Типы воздушных судов",
        "types_lead": ("Каждый тип — с паспортными данными из документов производителей или открытой библиотеки "
                       "OpenAP и с заготовкой калькулятора. Нажмите на тип, чтобы увидеть характеристики "
                       "и посчитать на нём маршрут."),
        "cls": {"small": "До 30 кресел", "regional": "Региональные (31–99 кресел)",
                "narrow": "Узкофюзеляжные (100–240 кресел)", "wide": "Широкофюзеляжные (более 240 кресел)"},
        "col_type": "Тип", "col_seats": "Кресел", "col_mtow": "MTOW, т", "col_status": "",
        "card_only": "только карточка",
        "type_title": "{name} ({icao}) — характеристики и стоимость эксплуатации | FlightCost",
        "type_desc": ("{name}: {facts}. Бесплатный расчёт экономики маршрута на {icao} — топливо, сборы, экипаж, "
                      "ТОиР, лизинг, безубыточная загрузка."),
        "type_h1": "{name} — характеристики и экономика маршрута",
        "type_lead": ("{name} ({icao}){facts}. На FlightCost можно бесплатно посчитать любой маршрут на этом типе: "
                      "топливо, сборы аэропортов и аэронавигации, экипаж, ТОиР, лизинг и безубыточную загрузку — "
                      "с источником у каждой цифры."),
        "type_card": ("Тип есть в каталоге карточкой: для расчёта не хватает опубликованных данных ({gaps}). "
                      "Как только они появятся в открытых источниках, тип станет доступен в калькуляторе."),
        "cta": "Посчитать маршрут на {icao} →",
        "specs_h": "Характеристики", "col_param": "Параметр", "col_value": "Значение", "col_src": "Источник",
        "fleet_h": "Заготовка калькулятора",
        "fleet_lead": ("Если вы не задали свои ставки, калькулятор подставляет оценки по массе и числу кресел. "
                       "Это параметрика, а не данные эксплуатанта: в расчёте каждую можно заменить своей."),
        "f_lease": "Лизинг, EUR в месяц", "f_hours": "Налёт борта, часов в месяц",
        "f_own": "Владение на лётный час (лизинг ÷ налёт), EUR",
        "f_mfh": "ТОиР, EUR на лётный час", "f_mfc": "ТОиР, EUR на цикл (взлёт-посадку)",
        "f_cfh": "Экипаж, EUR на лётный час", "f_cfc": "Экипаж, EUR на цикл",
        "similar_h": "Похожие типы", "status": "Статус программы",
        "st": {"in_service": "в эксплуатации", "ended": "производство завершено", "certifying": "сертификация",
               "flight_test": "лётные испытания", "development": "разработка", "paused": "приостановлена",
               "concept": "концепт"},
        "crumb_home": "FlightCost",
        "foot_open": "Открытый код (Apache 2.0)",
        "noscript": ("Для расчёта нужен JavaScript. О сервисе и справочник типов ВС доступны без него:"),
    },
    "en": {
        "brand_tag": "airline route economics",
        "home_title": "Free airline route economics calculator — flight cost & break-even load factor | FlightCost",
        "home_desc": ("Free online calculator for the cost of a flight: fuel, airport and air navigation charges, crew, "
                      "maintenance, leasing, break-even fare and load factor. Any route and aircraft type, a source "
                      "for every number. No sign-up, open source."),
        "home_h1": "Free airline route economics calculator",
        "nav_calc": "Calculator", "nav_types": "Aircraft types", "nav_about": "About", "nav_data": "Data",
        "nav_map": "Data map",
        "about_title": "About: free airline flight cost calculator | FlightCost",
        "about_desc": ("What FlightCost calculates, where the data comes from and how far you can trust it. A free, "
                       "open-source tool for the cost of a flight and of a route network."),
        "types_title": "Aircraft types: specifications and operating economics | FlightCost",
        "types_desc": ("Aircraft types for route economics: seats, weights, range, engines, lease, maintenance "
                       "and crew rates — with a source for every value."),
        "types_h1": "Aircraft types",
        "types_lead": ("Every type comes with its specifications from manufacturer documents or the open OpenAP "
                       "library and with the calculator's default rates. Open a type to see its data and calculate "
                       "a route with it."),
        "cls": {"small": "Up to 30 seats", "regional": "Regional (31–99 seats)",
                "narrow": "Narrowbody (100–240 seats)", "wide": "Widebody (more than 240 seats)"},
        "col_type": "Type", "col_seats": "Seats", "col_mtow": "MTOW, t", "col_status": "",
        "card_only": "card only",
        "type_title": "{name} ({icao}) — specifications and operating cost | FlightCost",
        "type_desc": ("{name}: {facts}. Free route economics on the {icao} — fuel, charges, crew, maintenance, "
                      "leasing, break-even load factor."),
        "type_h1": "{name} — specifications and route economics",
        "type_lead": ("{name} ({icao}){facts}. With FlightCost you can calculate any route on this type for free: "
                      "fuel, airport and air navigation charges, crew, maintenance, leasing and the break-even "
                      "load factor — with a source for every number."),
        "type_card": ("This type is in the catalogue as a card only: published data needed for a calculation is "
                      "missing ({gaps}). It becomes available in the calculator once that data is published."),
        "cta": "Calculate a route on the {icao} →",
        "specs_h": "Specifications", "col_param": "Parameter", "col_value": "Value", "col_src": "Source",
        "fleet_h": "Calculator defaults",
        "fleet_lead": ("If you do not enter your own rates, the calculator uses estimates from weight and seat "
                       "count. These are parametric, not operator data: each one can be replaced in the calculation."),
        "f_lease": "Lease, EUR per month", "f_hours": "Utilisation, flight hours per month",
        "f_own": "Ownership per flight hour (lease ÷ hours), EUR",
        "f_mfh": "Maintenance, EUR per flight hour", "f_mfc": "Maintenance, EUR per cycle",
        "f_cfh": "Crew, EUR per flight hour", "f_cfc": "Crew, EUR per cycle",
        "similar_h": "Similar types", "status": "Programme status",
        "st": {"in_service": "in service", "ended": "production ended", "certifying": "certification",
               "flight_test": "flight testing", "development": "in development", "paused": "paused",
               "concept": "concept"},
        "crumb_home": "FlightCost",
        "foot_open": "Open source (Apache 2.0)",
        "noscript": "The calculator needs JavaScript. These pages work without it:",
    },
    "de": {
        "brand_tag": "Streckenwirtschaftlichkeit",
        "home_title": "Flugkosten & Streckenwirtschaftlichkeit kostenlos berechnen — Break-even-Auslastung | FlightCost",
        "home_desc": ("Kostenloser Online-Rechner für die Kosten eines Fluges: Treibstoff, Flughafen- und "
                      "Flugsicherungsgebühren, Crew, Wartung, Leasing, Break-even-Preis und -Auslastung. Jede Strecke "
                      "und jeder Flugzeugtyp, mit Quelle für jede Zahl. Ohne Anmeldung, Open Source."),
        "home_h1": "Streckenwirtschaftlichkeit kostenlos berechnen",
        "nav_calc": "Rechner", "nav_types": "Flugzeugtypen", "nav_about": "Über", "nav_data": "Daten",
        "nav_map": "Datenkarte",
        "about_title": "Über FlightCost: kostenloser Flugkostenrechner",
        "about_desc": ("Was FlightCost berechnet, woher die Daten stammen und wie weit man ihnen trauen kann. "
                       "Ein kostenloses Open-Source-Werkzeug für Flug- und Netzkosten."),
        "types_title": "Flugzeugtypen: technische Daten und Betriebskosten | FlightCost",
        "types_desc": ("Flugzeugtypen für die Streckenrechnung: Sitze, Massen, Reichweite, Triebwerke, Leasing-, "
                       "Wartungs- und Crew-Sätze — mit Quelle für jeden Wert."),
        "types_h1": "Flugzeugtypen",
        "types_lead": ("Jeder Typ mit technischen Daten aus Herstellerdokumenten oder der offenen Bibliothek OpenAP "
                       "und mit den Standardsätzen des Rechners. Öffnen Sie einen Typ, um die Daten zu sehen und "
                       "eine Strecke damit zu berechnen."),
        "cls": {"small": "Bis 30 Sitze", "regional": "Regional (31–99 Sitze)",
                "narrow": "Schmalrumpf (100–240 Sitze)", "wide": "Großraum (mehr als 240 Sitze)"},
        "col_type": "Typ", "col_seats": "Sitze", "col_mtow": "MTOW, t", "col_status": "",
        "card_only": "nur Karte",
        "type_title": "{name} ({icao}) — technische Daten und Betriebskosten | FlightCost",
        "type_desc": ("{name}: {facts}. Streckenwirtschaftlichkeit mit der {icao} kostenlos berechnen — Treibstoff, "
                      "Gebühren, Crew, Wartung, Leasing, Break-even-Auslastung."),
        "type_h1": "{name} — technische Daten und Streckenwirtschaftlichkeit",
        "type_lead": ("{name} ({icao}){facts}. Mit FlightCost berechnen Sie jede Strecke mit diesem Typ kostenlos: "
                      "Treibstoff, Flughafen- und Flugsicherungsgebühren, Crew, Wartung, Leasing und die "
                      "Break-even-Auslastung — mit Quelle für jede Zahl."),
        "type_card": ("Dieser Typ steht nur als Karte im Katalog: für eine Berechnung fehlen veröffentlichte Daten "
                      "({gaps}). Sobald sie veröffentlicht sind, wird er im Rechner verfügbar."),
        "cta": "Strecke mit der {icao} berechnen →",
        "specs_h": "Technische Daten", "col_param": "Parameter", "col_value": "Wert", "col_src": "Quelle",
        "fleet_h": "Standardsätze des Rechners",
        "fleet_lead": ("Ohne eigene Sätze setzt der Rechner Schätzungen nach Masse und Sitzzahl ein. Das sind "
                       "parametrische Werte, keine Betreiberdaten: jeder lässt sich in der Rechnung ersetzen."),
        "f_lease": "Leasing, EUR pro Monat", "f_hours": "Auslastung, Flugstunden pro Monat",
        "f_own": "Besitzkosten je Flugstunde (Leasing ÷ Stunden), EUR",
        "f_mfh": "Wartung, EUR je Flugstunde", "f_mfc": "Wartung, EUR je Zyklus",
        "f_cfh": "Crew, EUR je Flugstunde", "f_cfc": "Crew, EUR je Zyklus",
        "similar_h": "Ähnliche Typen", "status": "Programmstatus",
        "st": {"in_service": "im Einsatz", "ended": "Produktion beendet", "certifying": "Zulassung",
               "flight_test": "Flugerprobung", "development": "in Entwicklung", "paused": "pausiert",
               "concept": "Konzept"},
        "crumb_home": "FlightCost",
        "foot_open": "Open Source (Apache 2.0)",
        "noscript": "Der Rechner braucht JavaScript. Diese Seiten funktionieren ohne:",
    },
}

# Поля паспорта в порядке показа: ключ домена → подпись на трёх языках.
SPEC = [
    ("manufacturer", ("Производитель", "Manufacturer", "Hersteller")),
    ("seats_typical", ("Кресел, типовая компоновка", "Seats, typical layout", "Sitze, typische Bestuhlung")),
    ("seats_max", ("Кресел, максимум", "Seats, maximum", "Sitze, maximal")),
    ("mtow_t", ("Максимальная взлётная масса (MTOW), т", "Maximum take-off weight (MTOW), t",
                "Höchstabflugmasse (MTOW), t")),
    ("mlw_t", ("Максимальная посадочная масса, т", "Maximum landing weight, t", "Höchstlandemasse, t")),
    ("oew_t", ("Масса пустого снаряжённого (OEW), т", "Operating empty weight (OEW), t",
               "Betriebsleermasse (OEW), t")),
    ("fuel_capacity_t", ("Запас топлива, т", "Fuel capacity, t", "Treibstoffkapazität, t")),
    ("range_km", ("Дальность, км", "Range, km", "Reichweite, km")),
    ("cruise_mach", ("Крейсерское число Маха", "Cruise Mach", "Reise-Machzahl")),
    ("cruise_alt_m", ("Крейсерская высота, м", "Cruise altitude, m", "Reiseflughöhe, m")),
    ("engine", ("Двигатель", "Engine", "Triebwerk")),
    ("engine_count", ("Число двигателей", "Number of engines", "Anzahl Triebwerke")),
    ("length_m", ("Длина, м", "Length, m", "Länge, m")),
    ("span_m", ("Размах крыла, м", "Wingspan, m", "Spannweite, m")),
    ("fuselage_width_m", ("Ширина фюзеляжа, м", "Fuselage width, m", "Rumpfbreite, m")),
    ("takeoff_m", ("Потребная длина ВПП для взлёта, м", "Take-off field length, m", "Startstrecke, m")),
    ("landing_m", ("Посадочная дистанция, м", "Landing field length, m", "Landestrecke, m")),
    ("code_letter", ("Кодовая буква аэродрома (ИКАО)", "ICAO aerodrome code letter", "ICAO-Codebuchstabe")),
    ("eis", ("Ввод в эксплуатацию", "Entry into service", "Indienststellung")),
]
LI = {"ru": 0, "en": 1, "de": 2}
NUM_LOC = {"ru": (" ", ","), "en": (",", "."), "de": (".", ",")}


def num(v, lang: str, digits: int | None = None) -> str:
    """Число по правилам языка: 78,0 / 78.0, тысячи — пробел / запятая / точка."""
    if v is None:
        return ""
    if digits is None:
        digits = 0 if float(v) >= 100 or float(v).is_integer() else (2 if abs(float(v)) < 10 else 1)
    s = f"{float(v):,.{digits}f}"
    th, dec = NUM_LOC[lang]
    return s.replace(",", "\x00").replace(".", dec).replace("\x00", th)


# ── общие куски страницы ───────────────────────────────────────────────────

def alternates(path_tail: str, default: str | None = None) -> list[tuple[str, str]]:
    """[(hreflang, абсолютный адрес)] для трёх языков и x-default."""
    out = [(lg, f"{site()}/{lg}{path_tail}") for lg in LANGS]
    out.append(("x-default", site() + (default if default is not None else f"/en{path_tail}")))
    return out


def head(lang: str, title: str, desc: str, canonical: str, alts: list[tuple[str, str]],
         ld: list[dict] | None = None) -> str:
    og_locale = {"ru": "ru_RU", "en": "en_GB", "de": "de_DE"}[lang]
    parts = [
        f"<title>{esc(title)}</title>",
        f'<meta name="description" content="{esc(desc)}">',
        f'<link rel="canonical" href="{esc(canonical)}">',
        *[f'<link rel="alternate" hreflang="{h}" href="{esc(u)}">' for h, u in alts],
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="FlightCost">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(desc)}">',
        f'<meta property="og:url" content="{esc(canonical)}">',
        f'<meta property="og:locale" content="{og_locale}">',
        f'<meta property="og:image" content="{site()}/og.png">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
    ]
    for d in ld or []:
        parts.append('<script type="application/ld+json">'
                     + json.dumps(d, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    return "\n".join(parts)


def app_ld(lang: str) -> dict:
    t = T[lang]
    return {"@context": "https://schema.org", "@type": "WebApplication", "name": "FlightCost",
            "alternateName": "FlightCostApp", "url": f"{site()}/{lang}/",
            "description": t["home_desc"], "inLanguage": lang,
            "applicationCategory": "BusinessApplication", "operatingSystem": "Any (web browser)",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "license": "https://www.apache.org/licenses/LICENSE-2.0", "sameAs": [REPO]}


def crumbs_ld(items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u}
                                for i, (n, u) in enumerate(items)]}


STYLE = """<style>
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 var(--sans)}
header{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:14px 22px;border-bottom:1px solid var(--line)}
header .brand{font:600 17px var(--sans);color:var(--ink2);text-decoration:none}
header .brand span{font-weight:400;color:var(--dim);font-size:13px;margin-left:8px}
nav a{color:var(--dim);text-decoration:none;margin-right:14px;font-size:13.5px}
nav a.on,nav a:hover{color:var(--ink2)}
.lg{margin-left:auto;font-size:12.5px}.lg a{color:var(--dim);text-decoration:none;margin-left:8px}
.lg a.on{color:var(--ink2);font-weight:600}
main{max-width:920px;margin:0 auto;padding:22px 22px 70px}
h1{font-size:26px;line-height:1.25;color:var(--ink2);margin:6px 0 10px}
h2{font-size:18px;color:var(--ink2);margin:30px 0 8px}
p,li{max-width:76ch}.lead{color:var(--ink);font-size:16px}.dim{color:var(--dim);font-size:13.5px}
a{color:var(--accent)}
.crumbs{font-size:12.5px;color:var(--dim)}.crumbs a{color:var(--dim)}
.cta{display:inline-block;margin:10px 0 4px;padding:9px 16px;border:1px solid var(--accent);border-radius:6px;
  color:var(--ink2);text-decoration:none;font-weight:600}
.cta:hover{background:var(--select)}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{text-align:left;font-weight:600;color:var(--dim);font-size:12px;padding:8px 10px;border-bottom:1px solid var(--line);
  background:var(--panel)}
td{padding:7px 10px;border-bottom:1px solid var(--line2);vertical-align:top}
td.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.s{font-size:12px;color:var(--dim)}td.s a{color:var(--dim)}
.guess{color:var(--guess)}
.tag{font-size:11.5px;color:var(--faint);margin-left:6px}
.chips a{display:inline-block;margin:0 8px 8px 0;padding:4px 10px;border:1px solid var(--line);border-radius:14px;
  text-decoration:none;color:var(--ink);font-size:13px}
.chips a:hover{border-color:var(--accent)}
footer{border-top:1px solid var(--line);padding:16px 22px;font-size:12.5px;color:var(--dim)}
footer a{color:var(--dim);margin-right:14px}
details{margin:6px 0;border-bottom:1px solid var(--line2);padding:6px 0}summary{cursor:pointer;color:var(--ink2)}
@media(max-width:640px){main{padding:16px 16px 50px}h1{font-size:22px}header{padding:12px 16px}}
</style>"""


def shell(lang: str, path_tail: str, head_html: str, body: str, on: str = "") -> str:
    t = T[lang]
    nav = [(f"/{lang}/", t["nav_calc"], "calc"), (f"/{lang}/types", t["nav_types"], "types"),
           (f"/{lang}/about", t["nav_about"], "about")]
    on_attr = ' class="on"'
    navh = "".join(f'<a href="{p}"{on_attr if k == on else ""}>{esc(n)}</a>' for p, n, k in nav)
    navh += f'<a href="/data">{esc(t["nav_data"])}</a>'
    lg = "".join(f'<a href="/{x}{path_tail}" hreflang="{x}"{on_attr if x == lang else ""}>{x.upper()}</a>'
                 for x in LANGS)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{head_html}
<link rel="stylesheet" href="/ui.css">
{STYLE}</head><body>
<header><a class="brand" href="/{lang}/">FlightCost<span>{esc(t["brand_tag"])}</span></a>
<nav>{navh}</nav><span class="lg">{lg}</span></header>
<main>{body}</main>
<footer><a href="{REPO}">GitHub — {esc(t["foot_open"])}</a><a href="/impressum">Impressum</a>
<a href="/datenschutz">Datenschutz</a></footer>
</body></html>"""


# ── витрина на языковом адресе ─────────────────────────────────────────────

def home(lang: str | None, page: str) -> str:
    """Страница витрины с заголовком для поисковика.

    `lang=None` — корень `/`: язык выбирает браузер, заголовок английский,
    страница — версия x-default. Иначе язык зафиксирован адресом.
    """
    lg = lang or "en"
    t = T[lg]
    canon = f"{site()}/{lang}/" if lang else f"{site()}/"
    h = head(lg, t["home_title"], t["home_desc"], canon, alternates("/", "/"), [app_ld(lg)])
    page = re.sub(r"<title>.*?</title>", lambda _m: h, page, count=1, flags=re.S)
    page = page.replace('<html lang="ru">', f'<html lang="{lg}">', 1)
    # Относительные адреса ломаются под /en/: ui.css и модули — от корня.
    page = page.replace('href="ui.css"', 'href="/ui.css"').replace('from "./geo.js"', 'from "/geo.js"')
    page = page.replace('from "./globe.js"', 'from "/globe.js"')
    if lang:
        page = page.replace('href="/about"', f'href="/{lang}/about"').replace(
            'href="/types"', f'href="/{lang}/types"')
    # Заголовок первого уровня и текст без скриптов: у витрины их нет,
    # а поисковик и читалка экрана начинают с них.
    links = (f'<a href="/{lg}/about">{esc(t["nav_about"])}</a> · '
             f'<a href="/{lg}/types">{esc(t["nav_types"])}</a>')
    seo = (f'<h1 class="vh">{esc(t["home_h1"])}</h1>'
           f'<noscript><div class="nojs"><h1>{esc(t["home_h1"])}</h1><p>{esc(t["home_desc"])}</p>'
           f'<p>{esc(t["noscript"])} {links}</p></div></noscript>')
    return page.replace("<body>", "<body>\n" + seo, 1) if "<body>" in page else page


# ── «о сервисе» ────────────────────────────────────────────────────────────

ABOUT = {
    "ru": {
        "h1": "FlightCost — бесплатный расчёт экономики авиамаршрута",
        "lead": ("Выберите маршрут, тип самолёта и загрузку — FlightCost посчитает себестоимость рейса по статьям "
                 "и покажет, при каком чеке и какой загрузке рейс выходит в ноль. У каждой цифры виден источник: "
                 "опубликованный тариф, расчёт или допущение, которое стоит заменить своим."),
        "sections": [
            ("Что считается", [
                "Топливо — расход по модели OpenAP с калибровкой по опубликованным рейсам, запасной аэродром, цена топлива.",
                "Сборы аэропортов — посадка, пассажирские, безопасность, шум и выбросы — по опубликованным тарифам аэропортов.",
                "Аэронавигация — маршрутные сборы по зонам (Eurocontrol и национальные), с учётом закрытого воздушного пространства.",
                "Владение и лизинг, ТОиР (на час и на цикл), экипаж — заготовки по типу, которые можно заменить своими.",
                "Выручка, безубыточный чек и безубыточная загрузка; обратный расчёт — при каком значении параметра рейс выходит в ноль.",
                "Сеть маршрутов из базы, сравнение типов ВС на одной сети, отчёт по парку в PDF и Excel с живыми формулами.",
            ]),
            ("Откуда данные", [
                "Тарифы аэропортов и аэронавигации — из опубликованных документов; разобранные значения подтверждает человек.",
                "Типы ВС — открытая библиотека OpenAP (TU Delft) и каталог по документам производителей, с адресом источника.",
                "Фактические расходы перевозчиков — отчётность США (BTS Form 41) для сверки ставок ТОиР и экипажа.",
                "Цены и спрос — наблюдения рынка и модель потока по населению; оценка всегда помечена как оценка.",
            ]),
        ],
        "how_h": "Насколько можно верить",
        "how": ("Каждое число окрашено по происхождению: документ, расчёт, ваше значение или допущение. "
                "Допущения — это не данные эксплуатанта: для решений замените их своими. Код и методика открыты, "
                "расхождения можно проверить и исправить."),
        "who_h": "Кому полезно",
        "who": ("Сетевым планировщикам и аналитикам авиакомпаний для первой оценки маршрута; лизингодателям и "
                "консультантам; студентам и преподавателям авиационной экономики; игрокам авиасимуляторов, "
                "которым нужна реалистичная экономика рейса."),
        "faq_h": "Вопросы и ответы",
        "faq": [
            ("Это бесплатно?", "Да. Сайт бесплатный, без регистрации и рекламы; код открыт под лицензией Apache 2.0."),
            ("Можно ли подставить свои цифры?",
             "Да: ставки лизинга, ТОиР, экипажа, цену топлива, чек и загрузку можно задать в расчёте. Свой тип ВС и "
             "сохранённые расчёты живут в рабочем месте."),
            ("Какие типы самолётов есть?",
             "Более 60 типов — от L-410 и ATR до A350 и Boeing 777, включая МС-21, SJ-100 и Ту-214. "
             "Список — на странице «Типы ВС»."),
            ("Можно ли поставить у себя?",
             "Да, это программа на Python: инструкция в репозитории на GitHub. Данные справочника собираются "
             "из открытых источников командой fca refresh."),
        ],
    },
    "en": {
        "h1": "FlightCost — free airline route economics calculator",
        "lead": ("Pick a route, an aircraft type and a load factor — FlightCost calculates the cost of the flight by "
                 "item and shows at which fare and load factor it breaks even. Every number shows its origin: a "
                 "published tariff, a calculation or an assumption you should replace with your own."),
        "sections": [
            ("What it calculates", [
                "Fuel — burn from the OpenAP model calibrated on published flights, alternate airport, fuel price.",
                "Airport charges — landing, passenger, security, noise and emissions — from published airport tariffs.",
                "Air navigation — en-route charges by zone (Eurocontrol and national), routing around closed airspace.",
                "Ownership and lease, maintenance (per hour and per cycle), crew — per-type defaults you can override.",
                "Revenue, break-even fare and break-even load factor; reverse solve — the value at which a flight breaks even.",
                "Route networks from a base, comparison of aircraft types on one network, fleet report in PDF and Excel with live formulas.",
            ]),
            ("Where the data comes from", [
                "Airport and air navigation tariffs — from published documents; parsed values are confirmed by a human.",
                "Aircraft types — the open OpenAP library (TU Delft) and a catalogue from manufacturer documents, with source links.",
                "Actual airline costs — US reporting (BTS Form 41) to check maintenance and crew rates.",
                "Fares and demand — market observations and a population-based flow model; an estimate is always marked as one.",
            ]),
        ],
        "how_h": "How far you can trust it",
        "how": ("Every number is coloured by origin: document, calculation, your value or assumption. Assumptions are "
                "not operator data: replace them with your own before deciding anything. The code and methodology "
                "are open, so discrepancies can be checked and fixed."),
        "who_h": "Who it is for",
        "who": ("Airline network planners and analysts for a first look at a route; lessors and consultants; students "
                "and teachers of air transport economics; airline simulator players who want realistic flight economics."),
        "faq_h": "FAQ",
        "faq": [
            ("Is it free?", "Yes. The site is free, with no sign-up and no ads; the code is open source under Apache 2.0."),
            ("Can I use my own numbers?",
             "Yes: lease, maintenance and crew rates, fuel price, fare and load factor can all be set in the "
             "calculation. Your own aircraft types and saved calculations live in a workspace."),
            ("Which aircraft types are included?",
             "More than 60 types, from the L-410 and ATR to the A350 and Boeing 777, including the MC-21, SJ-100 and "
             "Tu-214. See the “Aircraft types” page."),
            ("Can I run it myself?",
             "Yes, it is a Python program: instructions are in the GitHub repository. Reference data is collected "
             "from open sources with fca refresh."),
        ],
    },
    "de": {
        "h1": "FlightCost — Streckenwirtschaftlichkeit kostenlos berechnen",
        "lead": ("Strecke, Flugzeugtyp und Auslastung wählen — FlightCost berechnet die Kosten des Fluges nach "
                 "Positionen und zeigt, bei welchem Preis und welcher Auslastung er die Gewinnschwelle erreicht. "
                 "Jede Zahl zeigt ihre Herkunft: veröffentlichter Tarif, Berechnung oder Annahme, die Sie durch "
                 "eigene Werte ersetzen sollten."),
        "sections": [
            ("Was berechnet wird", [
                "Treibstoff — Verbrauch nach dem OpenAP-Modell, kalibriert an veröffentlichten Flügen, Ausweichflughafen, Treibstoffpreis.",
                "Flughafengebühren — Landung, Passagiere, Sicherheit, Lärm und Emissionen — nach veröffentlichten Tarifen.",
                "Flugsicherung — Streckengebühren nach Zonen (Eurocontrol und national), Umfliegen gesperrter Lufträume.",
                "Besitz und Leasing, Wartung (je Stunde und je Zyklus), Crew — Standardwerte je Typ, durch eigene ersetzbar.",
                "Erlöse, Break-even-Preis und -Auslastung; Rückrechnung — bei welchem Wert ein Flug die Gewinnschwelle erreicht.",
                "Streckennetze ab einer Basis, Vergleich von Flugzeugtypen im selben Netz, Flottenbericht als PDF und Excel mit Formeln.",
            ]),
            ("Woher die Daten stammen", [
                "Flughafen- und Flugsicherungstarife — aus veröffentlichten Dokumenten; ausgelesene Werte bestätigt ein Mensch.",
                "Flugzeugtypen — offene Bibliothek OpenAP (TU Delft) und ein Katalog nach Herstellerdokumenten, mit Quellenlink.",
                "Tatsächliche Kosten von Airlines — US-Berichte (BTS Form 41) zur Prüfung der Wartungs- und Crew-Sätze.",
                "Preise und Nachfrage — Marktbeobachtungen und ein Bevölkerungs-Flussmodell; Schätzungen sind immer markiert.",
            ]),
        ],
        "how_h": "Wie weit man den Zahlen trauen kann",
        "how": ("Jede Zahl ist nach Herkunft eingefärbt: Dokument, Berechnung, eigener Wert oder Annahme. Annahmen "
                "sind keine Betreiberdaten: ersetzen Sie sie vor Entscheidungen durch eigene. Code und Methodik sind "
                "offen, Abweichungen lassen sich prüfen und korrigieren."),
        "who_h": "Für wen",
        "who": ("Netzplaner und Analysten von Airlines für eine erste Streckenbewertung; Leasinggeber und Berater; "
                "Studierende und Lehrende der Luftverkehrsökonomie; Spieler von Airline-Simulationen, die realistische "
                "Flugkosten wollen."),
        "faq_h": "Häufige Fragen",
        "faq": [
            ("Ist es kostenlos?", "Ja. Ohne Anmeldung und ohne Werbung; der Code ist Open Source unter Apache 2.0."),
            ("Kann ich eigene Zahlen verwenden?",
             "Ja: Leasing-, Wartungs- und Crew-Sätze, Treibstoffpreis, Ticketpreis und Auslastung lassen sich in der "
             "Rechnung setzen. Eigene Typen und gespeicherte Rechnungen liegen in einem Arbeitsbereich."),
            ("Welche Flugzeugtypen gibt es?",
             "Mehr als 60 Typen, von L-410 und ATR bis A350 und Boeing 777, einschließlich MC-21, SJ-100 und Tu-214. "
             "Siehe Seite „Flugzeugtypen“."),
            ("Kann ich es selbst betreiben?",
             "Ja, es ist ein Python-Programm: Anleitung im GitHub-Repository. Die Referenzdaten werden mit "
             "fca refresh aus offenen Quellen gesammelt."),
        ],
    },
}


def about_page(lang: str) -> str:
    t, a = T[lang], ABOUT[lang]
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › {esc(t["nav_about"])}</div>',
            f"<h1>{esc(a['h1'])}</h1>", f'<p class="lead">{esc(a["lead"])}</p>',
            f'<a class="cta" href="/{lang}/">{esc(t["nav_calc"])} →</a>']
    for h, items in a["sections"]:
        body.append(f"<h2>{esc(h)}</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>")
    body.append(f"<h2>{esc(a['how_h'])}</h2><p>{esc(a['how'])}</p>")
    body.append(f"<h2>{esc(a['who_h'])}</h2><p>{esc(a['who'])}</p>")
    body.append(f"<h2>{esc(a['faq_h'])}</h2>" + "".join(
        f"<details open><summary>{esc(q)}</summary><p>{esc(ans)}</p></details>" for q, ans in a["faq"]))
    body.append(f'<p class="dim"><a href="/{lang}/types">{esc(t["nav_types"])}</a> · '
                f'<a href="/data">{esc(t["nav_data"])}</a> · <a href="/map">{esc(t["nav_map"])}</a> · '
                f'<a href="{REPO}">GitHub</a></p>')
    faq = {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": ans}}
                          for q, ans in a["faq"]]}
    h = head(lang, t["about_title"], t["about_desc"], f"{site()}/{lang}/about", alternates("/about"),
             [app_ld(lang), faq])
    return shell(lang, "/about", h, "\n".join(body), on="about")


# ── типы ВС ────────────────────────────────────────────────────────────────

# Латинские имена для английской и немецкой страниц: в каталоге типов
# (data/aircraft/catalog) имена записаны по-русски там, где тип российский
# или источник русскоязычный. Новый тип с кириллицей в имени без строки
# здесь покажется по-русски — tests/test_seo.py это ловит.
LATIN = {
    "B778": "Boeing 777-8",
    "D228": "HAL Hindustan-228 (civil Do-228, 228-201)",
    "I114": "Ilyushin Il-114-300",
    "IL96": "Ilyushin Il-96-400M",
    "L410": "L-410 UVP-E20 (UZGA / Aircraft Industries)",
    "MA60": "AVIC XAC MA60 / MA600 (Xinzhou 60/600)",
    "MS21": "Yakovlev MC-21-310 (PD-14 engines)",
    "SU95": "Yakovlev SJ-100 (Superjet, PD-8 engines)",
    "T204": "Tupolev Tu-214 (PS-90A engines)",
    "Y12": "AVIC Harbin Y-12F",
}


def name_of(entry: dict, lang: str) -> str:
    """Имя типа на языке страницы: по-русски как в каталоге, иначе латиницей."""
    if lang != "ru" and entry.get("icao") in LATIN:
        return LATIN[entry["icao"]]
    return entry.get("name") or entry.get("icao") or ""


def public_types(types: list[dict]) -> list[dict]:
    """Типы для страниц: с кодом ИКАО (без USER:) и с именем."""
    return [t for t in types if TYPE_CODE.match(t["icao"] or "") and t.get("name")]


def seats_of(t: dict) -> float | None:
    v = t.get("seats_typical") or t.get("seats_max")
    return float(v) if isinstance(v, (int, float)) else None


def cls_of(t: dict) -> str:
    s = seats_of(t) or 0
    return "small" if s <= 30 else "regional" if s < 100 else "narrow" if s <= 240 else "wide"


def type_url(lang: str, icao: str) -> str:
    return f"/{lang}/type/{quote(icao)}"


def types_index(lang: str, types: list[dict]) -> str:
    t = T[lang]
    pub = public_types(types)
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › {esc(t["nav_types"])}</div>',
            f"<h1>{esc(t['types_h1'])}</h1>", f'<p class="lead">{esc(t["types_lead"])}</p>']
    for c in ("narrow", "wide", "regional", "small"):
        rows = sorted((x for x in pub if cls_of(x) == c), key=lambda x: (-(seats_of(x) or 0), x["icao"]))
        if not rows:
            continue
        body.append(f"<h2>{esc(t['cls'][c])}</h2><div class=tw><table><tr><th>{esc(t['col_type'])}</th>"
                    f"<th>ICAO</th><th class=r>{esc(t['col_seats'])}</th><th class=r>{esc(t['col_mtow'])}</th></tr>")
        for x in rows:
            note = "" if x.get("usable") else f'<span class=tag>{esc(t["card_only"])}</span>'
            body.append(f'<tr><td><a href="{type_url(lang, x["icao"])}">{esc(name_of(x, lang))}</a>{note}</td>'
                        f'<td>{esc(x["icao"])}</td><td class=r>{num(seats_of(x), lang, 0)}</td>'
                        f'<td class=r>{num(x.get("mtow_t"), lang, 1) if x.get("mtow_t") else ""}</td></tr>')
        body.append("</table></div>")
    lst = {"@context": "https://schema.org", "@type": "ItemList",
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": name_of(x, lang),
                                "url": site() + type_url(lang, x["icao"])} for i, x in enumerate(pub)]}
    h = head(lang, t["types_title"], t["types_desc"], f"{site()}/{lang}/types", alternates("/types"),
             [crumbs_ld([("FlightCost", f"{site()}/{lang}/"), (t["nav_types"], f"{site()}/{lang}/types")]), lst])
    return shell(lang, "/types", h, "\n".join(body), on="types")


def _src(field: dict, lang: str = "ru") -> tuple[str, str]:
    """(подпись, адрес) источника поля для столбца «Источник»."""
    s = field.get("source") or ""
    if s == "aircraft_openap":
        return "OpenAP", OPENAP
    note = str(field.get("source_note") or "")
    parts = [p.strip() for p in note.split("|") if p.strip()]
    url = next((p for p in parts if p.startswith("http")), "")
    label = parts[1] if len(parts) > 1 and not parts[1].startswith("http") else (parts[0] if parts else s)
    if lang != "ru" and CYR.search(label) and url:
        label = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]   # издатель по-русски → его домен
    return label[:80], url


def _value(field: dict, key: str, lang: str) -> str:
    v, txt = field.get("value"), field.get("text")
    if key == "program_status" or key == "eis" or v is None:
        return str(txt or "")
    if key == "cruise_mach":
        return num(v, lang, 2)
    if key in ("seats_typical", "seats_max", "engine_count", "range_km", "cruise_alt_m", "takeoff_m", "landing_m"):
        return num(v, lang, 0)
    return num(v, lang, 1 if v >= 10 else 2)


def facts_line(lang: str, by: dict) -> str:
    """«180 кресел, MTOW 78,0 т, дальность 6 100 км» — для описания и вводного абзаца."""
    bits = []
    s = by.get("seats_typical") or by.get("seats_max")
    if s and s.get("value"):
        bits.append({"ru": f"{num(s['value'], lang, 0)} кресел", "en": f"{num(s['value'], lang, 0)} seats",
                     "de": f"{num(s['value'], lang, 0)} Sitze"}[lang])
    tn, km = {"ru": ("т", "км")}.get(lang, ("t", "km"))
    if by.get("mtow_t") and by["mtow_t"].get("value"):
        bits.append(f"MTOW {num(by['mtow_t']['value'], lang, 1)} {tn}")
    if by.get("range_km") and by["range_km"].get("value"):
        bits.append({"ru": "дальность", "en": "range", "de": "Reichweite"}[lang]
                    + f" {num(by['range_km']['value'], lang, 0)} {km}")
    eng = str((by.get("engine") or {}).get("text") or "")
    if eng and not (lang != "ru" and CYR.search(eng)):
        bits.append(eng)
    return ", ".join(bits)


def type_page(lang: str, info: dict, entry: dict, types: list[dict]) -> str:
    """Страница одного типа. `info` — Context.aircraft_type, `entry` — строка Context.aircraft."""
    t = T[lang]
    icao, name = entry["icao"], name_of(entry, lang) or info.get("name") or entry["icao"]
    by = {f["field"]: f for f in info.get("fields", [])}
    facts = facts_line(lang, by)
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › <a href="/{lang}/types">'
            f'{esc(t["nav_types"])}</a> › {esc(icao)}</div>',
            f"<h1>{esc(t['type_h1'].format(name=name, icao=icao))}</h1>",
            f'<p class="lead">{esc(t["type_lead"].format(name=name, icao=icao, facts=(" — " + facts) if facts else ""))}</p>']
    if entry.get("usable"):
        body.append(f'<a class="cta" href="/{lang}/?ac={quote(icao)}">{esc(t["cta"].format(icao=icao))}</a>')
    else:
        gaps = by.get("calc_gaps", {}).get("text") or "—"
        body.append(f'<p class="dim">{esc(t["type_card"].format(gaps=gaps))}</p>')
    st = by.get("program_status", {}).get("text")
    rows = []
    if st:
        rows.append((t["status"], t["st"].get(st, st), ("", "")))
    for key, labels in SPEC:
        f = by.get(key)
        if not f or (f.get("value") is None and not f.get("text")):
            continue
        val = _value(f, key, lang)
        # Текстовые поля каталога (двигатель, производитель) бывают только
        # по-русски: на английской и немецкой странице такую строку не
        # показываем, а не показываем кириллицу.
        if val and not (lang != "ru" and CYR.search(val)):
            rows.append((labels[LI[lang]], val, _src(f, lang)))
    if rows:
        body.append(f"<h2>{esc(t['specs_h'])}</h2><div class=tw><table><tr><th>{esc(t['col_param'])}</th>"
                    f"<th class=r>{esc(t['col_value'])}</th><th>{esc(t['col_src'])}</th></tr>")
        for lab, val, (sl, su) in rows:
            src = f'<a href="{esc(su)}" rel="nofollow">{esc(sl)}</a>' if su else esc(sl)
            body.append(f"<tr><td>{esc(lab)}</td><td class=r>{esc(val)}</td><td class=s>{src}</td></tr>")
        body.append("</table></div>")
    fd = info.get("fleet_default") or {}
    if fd and entry.get("usable"):
        own = fd["lease_eur_month"] / fd["monthly_hours"] if fd.get("monthly_hours") else None
        frows = [(t["f_lease"], fd.get("lease_eur_month")), (t["f_hours"], fd.get("monthly_hours")),
                 (t["f_own"], own), (t["f_mfh"], fd.get("maint_eur_per_fh")), (t["f_mfc"], fd.get("maint_eur_per_fc")),
                 (t["f_cfh"], fd.get("crew_eur_per_fh")), (t["f_cfc"], fd.get("crew_eur_per_fc"))]
        body.append(f"<h2>{esc(t['fleet_h'])}</h2><p class=dim>{esc(t['fleet_lead'])}</p><div class=tw><table>")
        for lab, v in frows:
            if v is not None:
                body.append(f"<tr><td>{esc(lab)}</td><td class='r guess'>{num(v, lang, 0)}</td></tr>")
        body.append("</table></div>")
    me = seats_of(entry) or 0
    sim = sorted((x for x in public_types(types) if x["icao"] != icao and x.get("usable")
                  and cls_of(x) == cls_of(entry)), key=lambda x: abs((seats_of(x) or 0) - me))[:8]
    if sim:
        body.append(f"<h2>{esc(t['similar_h'])}</h2><div class=chips>" + "".join(
            f'<a href="{type_url(lang, x["icao"])}">{esc(name_of(x, lang))}</a>' for x in sim) + "</div>")
    desc = t["type_desc"].format(name=name, icao=icao, facts=facts or icao)
    h = head(lang, t["type_title"].format(name=name, icao=icao), desc[:300], site() + type_url(lang, icao),
             alternates(f"/type/{quote(icao)}"),
             [crumbs_ld([("FlightCost", f"{site()}/{lang}/"), (t["nav_types"], f"{site()}/{lang}/types"),
                         (name, site() + type_url(lang, icao))])])
    return shell(lang, f"/type/{quote(icao)}", h, "\n".join(body), on="types")


# ── служебные файлы ────────────────────────────────────────────────────────

def robots() -> str:
    return (f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /w\nDisallow: /report\n\n"
            f"Sitemap: {site()}/sitemap.xml\n")


def sitemap(types: list[dict]) -> str:
    """Все адреса с языковыми парами (xhtml:link) — так Google связывает версии."""
    tails = ["/", "/about", "/types"] + [f"/type/{quote(x['icao'])}" for x in public_types(types)]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for tail in tails:
        alts = alternates(tail, "/" if tail == "/" else None)
        for lg in LANGS:
            out.append(f"<url><loc>{esc(site())}/{lg}{esc(tail)}</loc>"
                       + "".join(f'<xhtml:link rel="alternate" hreflang="{h}" href="{esc(u)}"/>' for h, u in alts)
                       + "</url>")
    for p in ("/", "/data", "/map"):
        out.append(f"<url><loc>{esc(site())}{p}</loc></url>")
    out.append("</urlset>")
    return "\n".join(out)


def urls(types: list[dict]) -> list[str]:
    """Все адреса сайта для IndexNow."""
    tails = ["/", "/about", "/types"] + [f"/type/{quote(x['icao'])}" for x in public_types(types)]
    return [f"{site()}/{lg}{tl}" for tl in tails for lg in LANGS] + [site() + p for p in ("/", "/data", "/map")]


def llms(types: list[dict]) -> str:
    """llms.txt — краткое описание сайта для ИИ-ассистентов (llmstxt.org)."""
    pub = public_types(types)
    names = ", ".join(name_of(x, "en") for x in sorted(pub, key=lambda x: -(seats_of(x) or 0))[:40])
    return f"""# FlightCost

> Free, open-source airline route economics calculator. For any route and aircraft type it calculates the cost of a
> flight by item (fuel, airport charges, air navigation charges, ownership/lease, maintenance, crew), revenue, the
> break-even fare and the break-even load factor, and shows the source of every number. No sign-up. Russian,
> English and German. Code: {REPO} (Apache 2.0).

Use it when someone asks how much a flight or an airline route costs to operate, what the break-even load factor of
a route is, or how two aircraft types compare on the same route or network.

## Pages

- [Calculator (English)]({site()}/en/): pick origin, destination, aircraft type and load factor. Parameters can be
  passed in the URL: `{site()}/en/?o=EDDF&d=LEBL&ac=A320` (ICAO airport codes, ICAO aircraft type designator).
- [Rechner (Deutsch)]({site()}/de/), [Калькулятор (русский)]({site()}/ru/)
- [About and methodology]({site()}/en/about): what is calculated, data sources, how far to trust the numbers.
- [Aircraft types]({site()}/en/types): specifications with sources and the calculator's default lease,
  maintenance and crew rates for each type, e.g. [Airbus A320]({site()}/en/type/A320).
- [Data]({site()}/data): what the reference store contains, by source and licence.
- [Data map]({site()}/map): where every input comes from.

## Aircraft types covered

{names}.

## Notes for answers

- Default lease, maintenance and crew rates are parametric estimates from weight and seat count, not operator data.
- Airport and navigation charges come from published tariffs; parsed values are confirmed by a human before use.
- Fuel burn comes from the OpenAP model (TU Delft), calibrated against published flights.
"""


def not_found(lang: str) -> str:
    t = T[lang]
    msg = {"ru": "Такой страницы нет.", "en": "This page does not exist.", "de": "Diese Seite gibt es nicht."}[lang]
    body = (f"<h1>404</h1><p>{esc(msg)}</p><p><a href=\"/{lang}/\">{esc(t['nav_calc'])}</a> · "
            f"<a href=\"/{lang}/types\">{esc(t['nav_types'])}</a></p>")
    return shell(lang, "/", '<title>404 | FlightCost</title><meta name="robots" content="noindex">', body)


def indexnow(local: str = "http://127.0.0.1:8000") -> int:
    """Отправить адреса сайта в IndexNow (Bing, Яндекс, Seznam и др.).

    Список берётся из sitemap работающей витрины — те же адреса, что видит
    поисковик. Ключ подтверждается файлом `/<ключ>.txt` на сайте.
    """
    import urllib.request
    import xml.etree.ElementTree as ET
    with urllib.request.urlopen(f"{local}/sitemap.xml", timeout=20) as r:
        root = ET.fromstring(r.read())
    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if e.text]
    host = re.sub(r"^https?://", "", site()).split("/")[0]
    if host.startswith(("localhost", "127.")):
        print("indexnow: адрес сайта локальный — не отправляю")
        return 0
    body = json.dumps({"host": host, "key": INDEXNOW_KEY, "keyLocation": f"{site()}/{INDEXNOW_KEY}.txt",
                       "urlList": locs[:10000]}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"indexnow: {len(locs)} адресов, ответ {r.status}")
        return r.status


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["indexnow"]:
        try:
            indexnow()
        except Exception as exc:                      # noqa: BLE001 — сбой не валит выкладку
            print(f"indexnow: не отправлено — {exc}")
    else:
        print("использование: python -m flightcostapp.seo indexnow")
