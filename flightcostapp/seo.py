"""Страницы для поисковиков и ИИ-ассистентов: языковые адреса, «о сервисе»,
типы ВС, robots.txt, sitemap.xml, llms.txt.

Зачем отдельный модуль. Витрина — одно приложение на скриптах: язык
выбирается в браузере, текста о том, что это за сервис, на странице нет.
Поисковик видит один адрес, одну (случайную) языковую версию и подписи
полей. Здесь — то, что он может прочитать без скриптов:

- `/ru/`, `/en/`, `/de/` — та же витрина, но язык задан адресом, а в
  заголовке страницы — название, описание, связи языковых версий
  (hreflang) и разметка schema.org. `/` отдаёт главную на языке браузера,
  но canonical у неё — языковая версия; x-default — `/en/`.
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
from pathlib import Path
from urllib.parse import quote, urlencode

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
        "calc_title": "Калькулятор экономики авиарейса: стоимость рейса и безубыточность | FlightCost",
        "calc_desc": ("Посчитайте рейс по статьям: топливо, сборы аэропортов и аэронавигации, экипаж, ТОиР, лизинг; "
                      "безубыточный чек и загрузка. Любой маршрут и тип ВС, бесплатно и без регистрации."),
        "calc_h1": "Калькулятор экономики авиарейса",
        "hero_h": "Экономика авиамаршрута — бесплатно",
        "hero_p": "Стоимость рейса по статьям, безубыточный чек и загрузка — с источником у каждой цифры.",
        "hero_tags": ["Бесплатно · открытый код", "Любой маршрут", "60+ типов ВС", "RU · EN · DE"],
        "go_calc": "Посчитать маршрут", "go_types": "Сравнить типы ВС",
        "doors_h": "С чего начать",
        "door_types": ("Типы ВС", "Характеристики, схема и экономика каждого типа на типовом маршруте из Франкфурта."),
        "door_calc": ("Расчёт маршрута", "Любая пара аэропортов и тип: стоимость рейса по статьям и безубыточность."),
        "door_net": ("Маршрутная сеть", "Для опытных: несколько направлений, частоты, парк и сравнение типов на сети."),
        "sample_h": "Пример расчёта",
        "sample_l": "{name} · {route} · загрузка 80%",
        "sample_open": "Открыть этот расчёт →",
        "what_h": "Что внутри",
        "more_about": "Подробнее о сервисе и данных →",
        "k_total": "рейс, EUR", "k_seat": "на кресло, EUR", "k_cask": "CASK, евроцент на кресло-км",
        "k_bh": "на блок-час, EUR", "k_be": "безубыточный чек при 80%, EUR",
        "econ_h": "Экономика на маршруте {route}",
        "econ_lead": ("{km} км по пути полёта, блок {bh} ч, загрузка 80% — {pax} из {seats} кресел (максимум по сертификату), июль. "
                      "Посчитано ядром FlightCost; ставки владения, ТОиР и экипажа — заготовка: на допущениях "
                      "держится {dflt}% суммы."),
        "econ_range": "Паспортная дальность — {range} км.",
        "econ_open": "Открыть этот расчёт и поменять параметры →",
        "col_item": "Статья", "col_eur": "EUR", "col_share": "Доля", "col_prov": "Происхождение",
        "prov": {"doc": "документ", "calc": "расчёт", "guess": "допущение"},
        "no_model": "Расход топлива этого типа пока не моделируется — расчёт на маршруте недоступен.",
        "infeasible": "На этом маршруте рейс невыполним с загрузкой 80%: {why}. Числа ниже — справочные.",
        "lim": {"mtow": "упирается во взлётную массу — поднимет {mp} пассажиров",
                "fuel_capacity": "не хватает ёмкости топливных баков", "range": "не хватает дальности"},
        "cmp_h": "Типы класса на этом маршруте",
        "cmp_lead": "Тот же маршрут, загрузка и допущения — отличается только тип.",
        "econ_wait": "Расчёт на типовом маршруте готовится — обновите страницу через минуту.",
        "sil_h": "Схема",
        "sil_lead": "Вид сверху в одном масштабе с соседями по классу.",
        "dev_burn": "Расход топлива — оценка разработчика FlightCost: {src}",
        "dev_field": "оценка разработчика",
        "nav_calc": "Расчёт", "nav_types": "Типы ВС", "nav_research": "Исследования", "nav_about": "О сервисе", "nav_data": "Данные",
        "nav_map": "Карта данных", "nav_monitor": "План",
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
        "cls": {"small": "До 30 кресел", "regional": "Региональные (31–99 кресел в типовой компоновке)",
                "narrow": "Узкофюзеляжные (100–240 кресел в типовой компоновке)", "wide": "Широкофюзеляжные (более 240 кресел в типовой компоновке)"},
        "col_type": "Тип", "col_seats": "Кресел, макс.", "col_mtow": "MTOW, т", "col_status": "",
        "card_only": "только карточка",
        "type_title": "{name} ({icao}) — характеристики, лизинг и стоимость эксплуатации | FlightCost",
        "type_desc": ("{name}: {facts}.{rates} Бесплатный расчёт экономики маршрута на {icao} — топливо, сборы, "
                      "экипаж, ТОиР, лизинг, безубыточная загрузка."),
        "type_rates": " Лизинг — около {lease} EUR в месяц, ТОиР — около {mfh} EUR на лётный час (оценка).",
        "type_h1": "{name} — характеристики и экономика маршрута",
        "type_lead": ("{name} ({icao}){facts}. На FlightCost можно бесплатно посчитать любой маршрут на этом типе: "
                      "топливо, сборы аэропортов и аэронавигации, экипаж, ТОиР, лизинг и безубыточную загрузку — "
                      "с источником у каждой цифры."),
        "type_card": ("Тип есть в каталоге карточкой: для расчёта не хватает опубликованных данных ({gaps}). "
                      "Как только они появятся в открытых источниках, тип станет доступен в калькуляторе."),
        "cta": "Посчитать маршрут на {icao} →",
        "ed_btn": "Изменить и сохранить свой вариант",
        "ed_h": "Свой вариант {icao}",
        "ed_lead": "Копия типа со всеми характеристиками и расходом. Поменяйте то, что у вас иначе — кресла, массы, ставки, — и сохраните: вариант появится в калькуляторе и в сравнении сети. Хранится в вашем рабочем месте, никому не виден.",
        "ed_key": "Код",
        "ed_name": "Название",
        "ed_engine": "Двигатель",
        "ed_seats_max": "Кресел по сертификату",
        "ed_seats_typical": "Кресел в типовой компоновке",
        "ed_mtow": "Взлётная масса, т",
        "ed_oew": "Масса пустого, т",
        "ed_mlw": "Посадочная масса, т",
        "ed_fuel": "Ёмкость баков, т",
        "ed_rates": "Ставки эксплуатации, EUR — пусто: заготовка (серым)",
        "ed_lease": "Лизинг в месяц",
        "ed_hours": "Налёт, ч в месяц",
        "ed_mfh": "ТОиР за час",
        "ed_mfc": "ТОиР за цикл",
        "ed_cfh": "Экипаж за час",
        "ed_cfc": "Экипаж за вылет",
        "ed_src": "Что изменено и почему (обязательно)",
        "ed_src_ph": "например: компоновка 186 кресел, лизинг по предложению лизингодателя",
        "ed_burn_same": "Расход — как у {analog} (тот же двигатель, множитель 1).",
        "ed_burn_anchor": "Расход — по аналогу {analog} с якорем {icao}.",
        "ed_save": "Сохранить вариант",
        "ed_cancel": "Отмена",
        "ed_need_ws": "Своё хранится в рабочем месте — оно ваше по секретной ссылке, без регистрации.",
        "ed_make_ws": "Создать рабочее место и сохранить",
        "ed_saved": "Сохранено: {key}.",
        "ed_link": "Ссылка на ваше рабочее место — сохраните её, по ней вариант откроется на любом устройстве:",
        "ed_calc": "Посчитать маршрут на нём →",
        "ed_net": "Сравнить с {icao} в сети →",
        "ed_fail": "Не сохранено:", "ed_seats_err": "Кресел в типовой компоновке больше, чем по сертификату — поправьте одно из двух.",
        "ed_suggest": "Предложить в общий каталог — скоро: с источником по каждому изменённому полю.",
        "specs_h": "Характеристики", "col_param": "Параметр", "col_value": "Значение", "col_src": "Источник",
        "ts_m_h": "ТОиР по годам — отчётность перевозчиков США (Form 41)",
        "ts_m_lead": ("Затраты на ТОиР на блок-час, как их отчитали перевозчики США с этим типом: прямые (работа, "
                      "материалы, подряд) и полные — с накладными службы ТО. Доллары каждого года, без пересчёта. "
                      "2020 год выше соседних: налёт упал, а постоянная часть затрат осталась."),
        "ts_direct": "прямые", "ts_total": "с накладными", "ts_unit": "USD за блок-час",
        "ts_last": "{y}: прямые {d} USD, с накладными {t} USD за блок-час, перевозчиков {n}",
        "ts_src": "Источник: BTS, Form 41 Schedule P-5.2; разбор — в исследовании «ТОиР».",
        "ts_p_h": "Цена и лизинг по публикациям",
        "ts_p_lead": ("Цены ВС из каталогов, сделок и рыночных оценок показаны отдельно от месячных ставок лизинга. "
                      "У каждого наблюдения есть дата и ссылка на источник."),
        "ts_kind": {"list": "Цена ВС (каталог)", "deal": "Цена ВС (сделка)",
                    "value": "Цена ВС (оценка рынка)", "lease": "Лизинг в месяц"},
        "ts_col": ("Период", "Вид", "Значение", "Возраст", "Источник"), "ts_new": "новый",
        "ts_m_usd": "млн USD", "ts_k_usd": "тыс. USD в месяц",
        "ts_range": "диапазон источника", "ts_midpoint": "вычисленная середина",
        "ts_range_note": ("Вертикальный интервал — опубликованный диапазон, точка и центральная линия — вычисленная середина. "
                          "Между датами заливка линейно соединяет диапазоны одного вида, возраста и источника."),
        "ts_age_unknown": "не указан", "ts_source_context": "Контекст и цитата",
        "ts_use_midpoint": "В калькулятор по середине",
        "ts_param": "оценка по массе ({age}), в долларах каждого года",
        "ts_param_note": ("За основу взяты {eur} EUR в месяц на октябрь 2026 года и курс {fx} USD/EUR. "
                          "Для прошлых лет применён индекс потребительских цен США CPI-U. "
                          "Оценка рассчитана {age_for}."),
        "ts_age_new": "новый борт", "ts_age_cur": "борт около 12 лет",
        "ts_for_new": "для нового борта", "ts_for_cur": "для борта около 12 лет",
        "ts_now": "Среднее по источникам за {y} год — {m} тыс. USD в месяц. Оценка по массе — {p} тыс. ({d}).",
        "ts_yield": ("Рынок лизинга восстанавливается после 2020 года: доходность парка AerCap (арендная плата ÷ средний "
                     "парк) — {y19} в 2019, дно {ymin} в {ymin_y}, {ylast} в {ylast_y}, до уровня 2019 ещё не дошла."),
        "ts_real": ("В долларах 2026 года оценка по массе составляет {p} тыс., а наблюдения 2018–2019 годов для того же возраста дают {r} тыс. "
                    "Если рынок вернётся к доковидному уровню, оценка по массе окажется {where}."),
        "ts_where": {"near": "рядом с ним", "above": "выше него", "below": "ниже него"},
        "fleet_h": "Лизинг и ТОиР: оценка стоимости владения и обслуживания",
        "fleet_lead": ("Лизинг учитывает принятые публикации за год для этого типа и возраста. "
                       "Если их нет, применяется оценка по массе. В калькуляторе можно ввести свои ставки."),
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
        "foot_game": "Устали считать? SkyBoss — симулятор авиакомпании", "foot_game_t": "Игра на тех же данных; её доход поддерживает открытый FlightCost",
        "noscript": ("Для расчёта нужен JavaScript. О сервисе и справочник типов ВС доступны без него:"),
    },
    "en": {
        "brand_tag": "airline route economics",
        "home_title": "Free airline route economics calculator — flight cost & break-even load factor | FlightCost",
        "home_desc": ("Free online calculator for the cost of a flight: fuel, airport and air navigation charges, crew, "
                      "maintenance, leasing, break-even fare and load factor. Any route and aircraft type, a source "
                      "for every number. No sign-up, open source."),
        "home_h1": "Free airline route economics calculator",
        "calc_title": "Flight cost calculator: cost per flight and break-even | FlightCost",
        "calc_desc": ("Calculate a flight by item: fuel, airport and air navigation charges, crew, maintenance, lease; "
                      "break-even fare and load factor. Any route and aircraft type, free and without sign-up."),
        "calc_h1": "Airline flight cost calculator",
        "hero_h": "Airline route economics, free",
        "hero_p": "Cost of a flight by item, break-even fare and load factor — with a source for every number.",
        "hero_tags": ["Free · open source", "Any route", "60+ aircraft types", "RU · EN · DE"],
        "go_calc": "Calculate a route", "go_types": "Compare aircraft types",
        "doors_h": "Where to start",
        "door_types": ("Aircraft types", "Specifications, a drawing and the economics of every type on a typical route from Frankfurt."),
        "door_calc": ("Route calculation", "Any airport pair and type: cost of the flight by item and break-even."),
        "door_net": ("Route network", "For experienced users: several routes, frequencies, fleet and type comparison on a network."),
        "sample_h": "Example",
        "sample_l": "{name} · {route} · 80% load factor",
        "sample_open": "Open this calculation →",
        "what_h": "What is inside",
        "more_about": "More about the service and the data →",
        "k_total": "flight, EUR", "k_seat": "per seat, EUR", "k_cask": "CASK, euro cents per seat-km",
        "k_bh": "per block hour, EUR", "k_be": "break-even fare at 80%, EUR",
        "econ_h": "Economics on {route}",
        "econ_lead": ("{km} km along the flight path, {bh} h block, 80% load factor — {pax} of {seats} seats (certified maximum), July. "
                      "Calculated by the FlightCost engine; ownership, maintenance and crew rates are defaults: "
                      "{dflt}% of the total rests on assumptions."),
        "econ_range": "Published range: {range} km.",
        "econ_open": "Open this calculation and change the inputs →",
        "col_item": "Item", "col_eur": "EUR", "col_share": "Share", "col_prov": "Origin",
        "prov": {"doc": "document", "calc": "calculation", "guess": "assumption"},
        "no_model": "Fuel burn for this type is not modelled yet — the route calculation is not available.",
        "infeasible": "The flight is not feasible on this route at 80% load factor: {why}. Figures below are for reference.",
        "lim": {"mtow": "limited by take-off weight — carries {mp} passengers",
                "fuel_capacity": "fuel tank capacity is insufficient", "range": "range is insufficient"},
        "cmp_h": "Types of this class on the same route",
        "cmp_lead": "Same route, load factor and assumptions — only the aircraft type differs.",
        "econ_wait": "The typical-route calculation is being prepared — reload the page in a minute.",
        "sil_h": "Drawing",
        "sil_lead": "Top view at the same scale as its class neighbours.",
        "dev_burn": "Fuel burn is a FlightCost developer estimate: {src}",
        "dev_field": "developer estimate",
        "nav_calc": "Calculator", "nav_types": "Aircraft types", "nav_research": "Research", "nav_about": "About", "nav_data": "Data",
        "nav_map": "Data map", "nav_monitor": "Plan",
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
        "cls": {"small": "Up to 30 seats", "regional": "Regional (31–99 seats in a typical layout)",
                "narrow": "Narrowbody (100–240 seats in a typical layout)", "wide": "Widebody (more than 240 seats in a typical layout)"},
        "col_type": "Type", "col_seats": "Seats, max", "col_mtow": "MTOW, t", "col_status": "",
        "card_only": "card only",
        "type_title": "{name} ({icao}) — specs, lease rate and operating cost | FlightCost",
        "type_desc": ("{name}: {facts}.{rates} Free route economics on the {icao} — fuel, charges, crew, "
                      "maintenance, leasing, break-even load factor."),
        "type_rates": " Lease rate about EUR {lease} a month, maintenance about EUR {mfh} per flight hour (estimate).",
        "type_h1": "{name} — specifications and route economics",
        "type_lead": ("{name} ({icao}){facts}. With FlightCost you can calculate any route on this type for free: "
                      "fuel, airport and air navigation charges, crew, maintenance, leasing and the break-even "
                      "load factor — with a source for every number."),
        "type_card": ("This type is in the catalogue as a card only: published data needed for a calculation is "
                      "missing ({gaps}). It becomes available in the calculator once that data is published."),
        "cta": "Calculate a route on the {icao} →",
        "ed_btn": "Edit and save your own variant",
        "ed_h": "Your variant of the {icao}",
        "ed_lead": "A copy of the type with all characteristics and fuel burn. Change what differs for you — seats, masses, rates — and save: the variant appears in the calculator and in network comparison. It is kept in your workspace and visible to no one else.",
        "ed_key": "Code",
        "ed_name": "Name",
        "ed_engine": "Engine",
        "ed_seats_max": "Certified seats",
        "ed_seats_typical": "Seats in typical layout",
        "ed_mtow": "Take-off mass, t",
        "ed_oew": "Empty mass, t",
        "ed_mlw": "Landing mass, t",
        "ed_fuel": "Fuel capacity, t",
        "ed_rates": "Operating rates, EUR — empty means the default estimate (grey)",
        "ed_lease": "Lease per month",
        "ed_hours": "Utilisation, h per month",
        "ed_mfh": "MRO per hour",
        "ed_mfc": "MRO per cycle",
        "ed_cfh": "Crew per hour",
        "ed_cfc": "Crew per departure",
        "ed_src": "What changed and why (required)",
        "ed_src_ph": "e.g. 186-seat layout, lease from a lessor's offer",
        "ed_burn_same": "Fuel burn as the {analog} (same engine, factor 1).",
        "ed_burn_anchor": "Fuel burn by the analogue {analog} with the {icao} anchor.",
        "ed_save": "Save variant",
        "ed_cancel": "Cancel",
        "ed_need_ws": "Your own data lives in a workspace — it is yours via a secret link, no sign-up.",
        "ed_make_ws": "Create a workspace and save",
        "ed_saved": "Saved: {key}.",
        "ed_link": "Link to your workspace — keep it, it opens your variant on any device:",
        "ed_calc": "Calculate a route on it →",
        "ed_net": "Compare with the {icao} in a network →",
        "ed_fail": "Not saved:", "ed_seats_err": "More seats in the typical layout than certified — correct one of the two.",
        "ed_suggest": "Suggesting it for the shared catalogue — coming soon, with a source for every changed field.",
        "specs_h": "Specifications", "col_param": "Parameter", "col_value": "Value", "col_src": "Source",
        "ts_m_h": "Maintenance by year — US carriers' reports (Form 41)",
        "ts_m_lead": ("Maintenance cost per block hour as reported by US carriers flying this type: direct (labour, "
                      "materials, outside services) and full — with the maintenance department's overheads. Dollars of "
                      "each year, not restated. 2020 stands above its neighbours: flying dropped, the fixed part of the "
                      "cost stayed."),
        "ts_direct": "direct", "ts_total": "with overheads", "ts_unit": "USD per block hour",
        "ts_last": "{y}: direct USD {d}, with overheads USD {t} per block hour, {n} carriers",
        "ts_src": "Source: BTS, Form 41 Schedule P-5.2; analysis in the “Maintenance” research.",
        "ts_p_h": "Price and lease rate from publications",
        "ts_p_lead": ("Aircraft list prices, transaction prices and market appraisals are shown separately from "
                      "monthly lease rates. Each observation includes a date and a source link."),
        "ts_kind": {"list": "Aircraft price (list)", "deal": "Aircraft price (deal)",
                    "value": "Aircraft price (market appraisal)", "lease": "Lease per month"},
        "ts_col": ("Period", "Kind", "Value", "Age", "Source"), "ts_new": "new",
        "ts_m_usd": "USD m", "ts_k_usd": "USD k per month",
        "ts_range": "published range", "ts_midpoint": "computed midpoint",
        "ts_range_note": ("The vertical interval shows the published range; the dot and centre line show computed midpoints. "
                          "Between dates, shading linearly joins ranges of the same kind, aircraft age and source."),
        "ts_age_unknown": "not stated", "ts_source_context": "Context and quote",
        "ts_use_midpoint": "Use midpoint in calculator",
        "ts_param": "weight-based estimate ({age}), in dollars of each year",
        "ts_param_note": ("The line shows the weight-based lease estimate: EUR {eur} a month as of "
                          "October 2026 at {fx} USD/EUR, restated in dollars of earlier years by the US CPI-U price index. "
                          "It is an estimate {age_for}; points of another age are not directly comparable."),
        "ts_age_new": "new aircraft", "ts_age_cur": "aircraft about 12 years old",
        "ts_for_new": "for a new aircraft", "ts_for_cur": "for an aircraft about 12 years old",
        "ts_now": "The {y} source average is USD {m}k per month. The weight-based estimate is USD {p}k ({d}).",
        "ts_yield": ("The lease market is recovering after 2020: AerCap's fleet yield (lease rents ÷ average lease "
                     "assets) was {y19} in 2019, bottomed at {ymin} in {ymin_y}, {ylast} in {ylast_y} — not yet back to 2019."),
        "ts_real": ("In 2026 dollars, the weight-based estimate is {p}k and observations for the same age in 2018–2019 give {r}k. "
                    "If the market returns to its pre-COVID level, the weight-based estimate will be {where}."),
        "ts_where": {"near": "close to it", "above": "above it", "below": "below it"},
        "fleet_h": "Lease rate and maintenance cost: estimates for ownership and upkeep",
        "fleet_lead": ("The lease uses accepted publications for the year, type and age. If none are available, "
                       "a weight-based estimate applies. You can enter your own rates in the calculator."),
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
        "foot_game": "Tired of spreadsheets? SkyBoss — an airline tycoon game", "foot_game_t": "A game on the same data; its revenue keeps the open-source FlightCost running",
        "noscript": "The calculator needs JavaScript. These pages work without it:",
    },
    "de": {
        "brand_tag": "Streckenwirtschaftlichkeit",
        "home_title": "Flugkosten-Rechner kostenlos — Kosten eines Fluges und Break-even-Auslastung | FlightCost",
        "home_desc": ("Kostenloser Online-Rechner für die Kosten eines Fluges: Treibstoff, Flughafen- und "
                      "Flugsicherungsgebühren, Crew, Wartung, Leasing, Break-even-Preis und -Auslastung. Jede Strecke "
                      "und jeder Flugzeugtyp, mit Quelle für jede Zahl. Ohne Anmeldung, Open Source."),
        "home_h1": "Flugkosten-Rechner: Streckenwirtschaftlichkeit kostenlos berechnen",
        "calc_title": "Flugkostenrechner: Kosten je Flug und Break-even | FlightCost",
        "calc_desc": ("Einen Flug nach Positionen berechnen: Treibstoff, Flughafen- und Flugsicherungsgebühren, Crew, "
                      "Wartung, Leasing; Break-even-Preis und -Auslastung. Jede Strecke, jeder Typ, kostenlos."),
        "calc_h1": "Flugkostenrechner",
        "hero_h": "Streckenwirtschaftlichkeit, kostenlos",
        "hero_p": "Flugkosten nach Positionen, Break-even-Preis und -Auslastung — mit Quelle für jede Zahl.",
        "hero_tags": ["Kostenlos · Open Source", "Jede Strecke", "60+ Flugzeugtypen", "RU · EN · DE"],
        "go_calc": "Strecke berechnen", "go_types": "Flugzeugtypen vergleichen",
        "doors_h": "Wo anfangen",
        "door_types": ("Flugzeugtypen", "Technische Daten, Zeichnung und Wirtschaftlichkeit jedes Typs auf einer typischen Strecke ab Frankfurt."),
        "door_calc": ("Streckenrechnung", "Jedes Flughafenpaar und jeder Typ: Flugkosten nach Positionen und Break-even."),
        "door_net": ("Streckennetz", "Für Erfahrene: mehrere Strecken, Frequenzen, Flotte und Typvergleich im Netz."),
        "sample_h": "Beispiel",
        "sample_l": "{name} · {route} · 80 % Auslastung",
        "sample_open": "Diese Rechnung öffnen →",
        "what_h": "Was drin ist",
        "more_about": "Mehr über den Dienst und die Daten →",
        "k_total": "Flug, EUR", "k_seat": "je Sitz, EUR", "k_cask": "CASK, Eurocent je Sitz-km",
        "k_bh": "je Blockstunde, EUR", "k_be": "Break-even-Preis bei 80 %, EUR",
        "econ_h": "Wirtschaftlichkeit auf {route}",
        "econ_lead": ("{km} km entlang der Flugroute, {bh} h Blockzeit, 80 % Auslastung — {pax} von {seats} Sitzen (zugelassenes Maximum), Juli. "
                      "Berechnet vom FlightCost-Kern; Besitz-, Wartungs- und Crew-Sätze sind Standardwerte: "
                      "{dflt} % der Summe beruhen auf Annahmen."),
        "econ_range": "Reichweite laut Hersteller: {range} km.",
        "econ_open": "Diese Rechnung öffnen und Eingaben ändern →",
        "col_item": "Position", "col_eur": "EUR", "col_share": "Anteil", "col_prov": "Herkunft",
        "prov": {"doc": "Dokument", "calc": "Berechnung", "guess": "Annahme"},
        "no_model": "Der Treibstoffverbrauch dieses Typs ist noch nicht modelliert — keine Streckenrechnung verfügbar.",
        "infeasible": "Auf dieser Strecke ist der Flug bei 80 % Auslastung nicht durchführbar: {why}. Die Zahlen unten dienen nur zur Orientierung.",
        "lim": {"mtow": "durch die Startmasse begrenzt — befördert {mp} Passagiere",
                "fuel_capacity": "Tankvolumen reicht nicht", "range": "Reichweite reicht nicht"},
        "cmp_h": "Typen dieser Klasse auf derselben Strecke",
        "cmp_lead": "Gleiche Strecke, Auslastung und Annahmen — nur der Typ unterscheidet sich.",
        "econ_wait": "Die Rechnung auf der typischen Strecke wird vorbereitet — Seite in einer Minute neu laden.",
        "sil_h": "Zeichnung",
        "sil_lead": "Draufsicht im gleichen Maßstab wie die Nachbarn der Klasse.",
        "dev_burn": "Treibstoffverbrauch ist eine Schätzung der FlightCost-Entwickler: {src}",
        "dev_field": "Schätzung der Entwickler",
        "nav_calc": "Rechner", "nav_types": "Flugzeugtypen", "nav_research": "Recherchen", "nav_about": "Über", "nav_data": "Daten",
        "nav_map": "Datenkarte", "nav_monitor": "Plan",
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
        "cls": {"small": "Bis 30 Sitze", "regional": "Regional (31–99 Sitze in typischer Bestuhlung)",
                "narrow": "Schmalrumpf (100–240 Sitze in typischer Bestuhlung)", "wide": "Großraum (mehr als 240 Sitze in typischer Bestuhlung)"},
        "col_type": "Typ", "col_seats": "Sitze, max.", "col_mtow": "MTOW, t", "col_status": "",
        "card_only": "nur Karte",
        "type_title": "{name} ({icao}) — technische Daten, Leasingrate und Betriebskosten | FlightCost",
        "type_desc": ("{name}: {facts}.{rates} Streckenwirtschaftlichkeit mit der {icao} kostenlos berechnen — "
                      "Treibstoff, Gebühren, Crew, Wartung, Leasing, Break-even-Auslastung."),
        "type_rates": " Leasingrate etwa {lease} EUR im Monat, Wartung etwa {mfh} EUR je Flugstunde (Schätzung).",
        "type_h1": "{name} — technische Daten und Streckenwirtschaftlichkeit",
        "type_lead": ("{name} ({icao}){facts}. Mit FlightCost berechnen Sie jede Strecke mit diesem Typ kostenlos: "
                      "Treibstoff, Flughafen- und Flugsicherungsgebühren, Crew, Wartung, Leasing und die "
                      "Break-even-Auslastung — mit Quelle für jede Zahl."),
        "type_card": ("Dieser Typ steht nur als Karte im Katalog: für eine Berechnung fehlen veröffentlichte Daten "
                      "({gaps}). Sobald sie veröffentlicht sind, wird er im Rechner verfügbar."),
        "cta": "Strecke mit der {icao} berechnen →",
        "ed_btn": "Ändern und eigene Variante speichern",
        "ed_h": "Ihre Variante der {icao}",
        "ed_lead": "Eine Kopie des Typs mit allen Kennwerten und dem Verbrauch. Ändern Sie, was bei Ihnen anders ist — Sitze, Massen, Sätze — und speichern Sie: die Variante erscheint im Rechner und im Netzvergleich. Sie liegt in Ihrem Arbeitsbereich und ist für niemanden sonst sichtbar.",
        "ed_key": "Code",
        "ed_name": "Name",
        "ed_engine": "Triebwerk",
        "ed_seats_max": "Zugelassene Sitze",
        "ed_seats_typical": "Sitze in typischer Bestuhlung",
        "ed_mtow": "Startmasse, t",
        "ed_oew": "Leermasse, t",
        "ed_mlw": "Landemasse, t",
        "ed_fuel": "Tankinhalt, t",
        "ed_rates": "Betriebssätze, EUR — leer heißt Schätzwert (grau)",
        "ed_lease": "Leasing pro Monat",
        "ed_hours": "Flugstunden pro Monat",
        "ed_mfh": "Wartung je Stunde",
        "ed_mfc": "Wartung je Zyklus",
        "ed_cfh": "Crew je Stunde",
        "ed_cfc": "Crew je Abflug",
        "ed_src": "Was geändert wurde und warum (Pflicht)",
        "ed_src_ph": "z. B. Bestuhlung 186 Sitze, Leasing laut Angebot",
        "ed_burn_same": "Verbrauch wie {analog} (gleiches Triebwerk, Faktor 1).",
        "ed_burn_anchor": "Verbrauch über Analogon {analog} mit dem Anker der {icao}.",
        "ed_save": "Variante speichern",
        "ed_cancel": "Abbrechen",
        "ed_need_ws": "Eigene Daten liegen in einem Arbeitsbereich — er gehört Ihnen per geheimem Link, ohne Anmeldung.",
        "ed_make_ws": "Arbeitsbereich anlegen und speichern",
        "ed_saved": "Gespeichert: {key}.",
        "ed_link": "Link zu Ihrem Arbeitsbereich — aufbewahren, damit öffnet sich die Variante auf jedem Gerät:",
        "ed_calc": "Strecke damit berechnen →",
        "ed_net": "Im Netz mit der {icao} vergleichen →",
        "ed_fail": "Nicht gespeichert:", "ed_seats_err": "Mehr Sitze in der typischen Bestuhlung als zugelassen — bitte eines von beiden korrigieren.",
        "ed_suggest": "Vorschlag für den gemeinsamen Katalog — bald, mit Quelle für jedes geänderte Feld.",
        "specs_h": "Technische Daten", "col_param": "Parameter", "col_value": "Wert", "col_src": "Quelle",
        "ts_m_h": "Instandhaltung nach Jahren — Berichte der US-Airlines (Form 41)",
        "ts_m_lead": ("Instandhaltungskosten je Blockstunde, wie sie die US-Airlines mit diesem Typ berichten: direkt "
                      "(Arbeit, Material, Fremdleistungen) und voll — mit Gemeinkosten der Technik. Dollar des jeweiligen "
                      "Jahres, nicht umgerechnet. 2020 liegt über den Nachbarjahren: Es wurde weniger geflogen, der feste "
                      "Kostenanteil blieb."),
        "ts_direct": "direkt", "ts_total": "mit Gemeinkosten", "ts_unit": "USD je Blockstunde",
        "ts_last": "{y}: direkt {d} USD, mit Gemeinkosten {t} USD je Blockstunde, {n} Airlines",
        "ts_src": "Quelle: BTS, Form 41 Schedule P-5.2; Auswertung in der Studie „Instandhaltung“.",
        "ts_p_h": "Preis und Leasingrate aus Veröffentlichungen",
        "ts_p_lead": ("Listenpreise, Kaufpreise und Marktwertschätzungen für Flugzeuge stehen getrennt von monatlichen "
                      "Leasingraten. Jede Beobachtung enthält ein Datum und einen Quellenlink."),
        "ts_kind": {"list": "Flugzeugpreis (Liste)", "deal": "Flugzeugpreis (Kauf)",
                    "value": "Flugzeugpreis (Marktwertschätzung)", "lease": "Leasing pro Monat"},
        "ts_col": ("Zeitraum", "Art", "Wert", "Alter", "Quelle"), "ts_new": "neu",
        "ts_m_usd": "Mio. USD", "ts_k_usd": "Tsd. USD pro Monat",
        "ts_range": "veröffentlichte Spanne", "ts_midpoint": "berechneter Mittelwert",
        "ts_range_note": ("Das vertikale Intervall zeigt die veröffentlichte Spanne, Punkt und Mittellinie die berechneten "
                          "Mittelwerte. Zwischen den Daten verbindet die Fläche Spannen gleicher Art, gleichen "
                          "Flugzeugalters und derselben Quelle linear."),
        "ts_age_unknown": "nicht angegeben", "ts_source_context": "Kontext und Zitat",
        "ts_use_midpoint": "Mittelwert im Rechner verwenden",
        "ts_param": "gewichtsbasierte Schätzung ({age}), in Dollar des jeweiligen Jahres",
        "ts_param_note": ("Die Linie zeigt die gewichtsbasierte Schätzung: {eur} EUR pro Monat, "
                          "Stand Oktober 2026, zu {fx} USD/EUR, mit dem US-Verbraucherpreisindex CPI-U in Dollar früherer "
                          "Jahre umgerechnet. Schätzung {age_for}; Punkte anderen Alters sind nicht direkt vergleichbar."),
        "ts_age_new": "neues Flugzeug", "ts_age_cur": "Flugzeug von etwa 12 Jahren",
        "ts_for_new": "für ein neues Flugzeug", "ts_for_cur": "für ein Flugzeug von etwa 12 Jahren",
        "ts_now": "Der Mittelwert der Quellen für {y} beträgt {m} Tsd. USD pro Monat. Die gewichtsbasierte Schätzung beträgt {p} Tsd. USD ({d}).",
        "ts_yield": ("Der Leasingmarkt erholt sich seit 2020: Die Flottenrendite von AerCap (Leasingerlöse ÷ "
                     "durchschnittliches Leasingvermögen) lag 2019 bei {y19}, im Tief {ymin} ({ymin_y}), {ylast} ({ylast_y}) — "
                     "das Niveau von 2019 ist noch nicht erreicht."),
        "ts_real": ("In Dollar von 2026 beträgt die gewichtsbasierte Schätzung {p} Tsd. und der Vergleichswert für das gleiche Alter aus "
                    "den Jahren 2018–2019 liegt bei {r} Tsd. Kehrt der Markt auf das Vor-Corona-Niveau zurück, liegt die Schätzung {where}."),
        "ts_where": {"near": "nahe daran", "above": "darüber", "below": "darunter"},
        "fleet_h": "Leasingrate und Wartungskosten: Schätzung für Besitz und Instandhaltung",
        "fleet_lead": ("Die Leasingrate berücksichtigt bestätigte Quellen für Jahr, Typ und Alter. Ohne passende Quelle "
                       "gilt die gewichtsbasierte Schätzung. Im Rechner können Sie eigene Sätze eingeben."),
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
        "foot_game": "Genug gerechnet? SkyBoss — eine Airline-Simulation", "foot_game_t": "Ein Spiel auf denselben Daten; seine Einnahmen finanzieren das quelloffene FlightCost",
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
        ICON_LINKS,
    ]
    for d in ld or []:
        parts.append('<script type="application/ld+json">'
                     + json.dumps(d, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    return "\n".join(parts)


# Значок — одной строкой на все страницы (сервер подставляет её и в те,
# что собраны не здесь: данные, карта, отчёт, Impressum). `?v=` — сброс
# кэша значков Safari: он запоминает и «значка нет» и не спрашивает снова,
# сколько ни чистить историю; новый адрес он запрашивает заново. SVG —
# первым, PNG и ICO — после: Safari берёт PNG, Chrome — SVG.
ICON_V = "3"
ICON_LINKS = (f'<link rel="icon" href="/favicon.svg?v={ICON_V}" type="image/svg+xml">'
              f'<link rel="icon" href="/favicon-32.png?v={ICON_V}" type="image/png" sizes="32x32">'
              f'<link rel="icon" href="/favicon.ico?v={ICON_V}" sizes="16x16 32x32 48x48">'
              f'<link rel="apple-touch-icon" href="/apple-touch-icon.png?v={ICON_V}">')


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
td.tx{white-space:normal;min-width:10ch;overflow-wrap:anywhere}
th{white-space:normal}td a{overflow-wrap:anywhere}
td.s{font-size:12px;color:var(--dim)}td.s a{color:var(--dim)}
.guess{color:var(--guess)}
.tag{font-size:11.5px;color:var(--faint);margin-left:6px}
.chips a{display:inline-block;margin:0 8px 8px 0;padding:4px 10px;border:1px solid var(--line);border-radius:14px;
  text-decoration:none;color:var(--ink);font-size:13px}
.chips a:hover{border-color:var(--accent)}
footer{border-top:1px solid var(--line);padding:16px 22px;font-size:12.5px;color:var(--dim)}
footer a{color:var(--dim);margin-right:14px}
footer a.game{float:right;margin-right:0}footer a.game:hover{color:var(--ink)}
@media(max-width:640px){footer a.game{float:none;display:block;margin-top:8px}}
details{margin:6px 0;border-bottom:1px solid var(--line2);padding:6px 0}summary{cursor:pointer;color:var(--ink2)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel)}
.kpi b{display:block;font-size:20px;color:var(--ink2);font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--dim)}
tr.me td{background:var(--select)}tr.me td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.p-doc{color:var(--doc)}.p-calc{color:var(--calc)}.p-guess{color:var(--guess)}
.warn{border:1px solid var(--warn);border-radius:8px;padding:10px 12px;color:var(--ink);margin:10px 0}
.sil{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin:8px 0 4px}
.sil-details{margin:14px 0}.sil-details summary{padding:4px 0}
.sil-details summary h2{display:inline;margin:0}.sil-details summary:focus-visible{outline:2px solid var(--accent)}
.ts svg{width:100%;max-width:680px;height:auto;display:block}.ts .ax{stroke:var(--line)}
.ts text{font:11px var(--sans);fill:var(--dim)}.ts .l1{stroke:var(--accent);fill:none;stroke-width:2}
.ts .l2{stroke:var(--dim);fill:none;stroke-width:1.5;stroke-dasharray:5 4}
.ts .l3{stroke:var(--price-lease);fill:none;stroke-width:2;stroke-dasharray:6 4;opacity:.8}.ts .p1{fill:var(--accent)}
.ts .k-list{fill:var(--price-list)}.ts .k-deal{fill:var(--price-deal)}
.ts .k-value{fill:var(--price-value)}.ts .k-lease{fill:var(--price-lease)}
.ts .k-list,.price-kind.k-list,.price-value.k-list{color:var(--price-list)}
.ts .k-deal,.price-kind.k-deal,.price-value.k-deal{color:var(--price-deal)}
.ts .k-value,.price-kind.k-value,.price-value.k-value{color:var(--price-value)}
.ts .k-lease,.price-kind.k-lease,.price-value.k-lease{color:var(--price-lease)}
.ts .range-band{fill-opacity:.18;stroke:none}.ts .range-bar{fill:none;stroke:currentColor;stroke-width:2;
  vector-effect:non-scaling-stroke}.ts .midpoint{stroke:var(--bg);stroke-width:1.5}
.ts .range-midline{fill:none;stroke:currentColor;stroke-width:1.5}
.ts .range-label{fill:var(--ink)}
.price-kind{display:inline-block;position:relative;padding-left:15px;line-height:1.45;font-weight:400;max-width:28ch}
.price-dot{position:absolute;left:0;top:.45em;width:8px;height:8px;border-radius:50%;background:currentColor}
.ts .lg.price-legend{display:flex;flex-wrap:wrap;gap:8px 18px}
.price-table .price-kind{min-width:18ch}
.price-value{font-weight:400}
.price-mid{display:block;font-size:12px;color:var(--dim);white-space:normal;max-width:25ch;margin-left:auto}
.price-use{display:block;font-size:12px;white-space:normal;max-width:25ch;margin-left:auto}
.price-source{font-size:12px;border:0;margin:4px 0 0;padding:0}.price-source p{margin:5px 0}
.price-source blockquote{margin:5px 0;padding-left:8px;border-left:2px solid var(--line);overflow-wrap:anywhere}
.ts .lg{font-size:12.5px;color:var(--dim);margin:4px 0 8px}.ts .lg i{display:inline-block;width:10px;height:10px;
  border-radius:50%;margin:0 5px 0 12px;vertical-align:-1px}
.sil svg{max-width:100%;height:auto}.sil .lgd{font-size:12.5px;color:var(--dim)}
.sil .lgd i{display:inline-block;width:18px;height:0;border-top:2px solid var(--accent);vertical-align:middle;margin-right:6px}
.sil .lgd i.o{border-top:2px dashed var(--dim)}
@media(max-width:640px){main{padding:16px 16px 50px}h1{font-size:22px}
  .sil{flex-direction:column;align-items:flex-start;gap:8px}
  .ts .range-label{font-size:16px}
  /* Паспорт на телефоне: строка — сетка «параметр | значение», источник под ними. */
  table.spec tr:first-child{display:none}
  table.spec tr{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;padding:7px 10px;
    border-bottom:1px solid var(--line2)}
  table.spec td{border:0;padding:0}table.spec td.tx{max-width:55vw}
  table.spec td.s{grid-column:1/-1;padding-top:2px}
  td,th{padding:7px 8px}}
</style>"""


NAV = (("calc", "/calc", "nav_calc"), ("types", "/types", "nav_types"), ("research", "/research", "nav_research"),
       ("data", "/data", "nav_data"),
       ("map", "/map", "nav_map"), ("monitor", "/monitor", "nav_monitor"), ("about", "/about", "nav_about"))
LANG_LOCAL = ("data", "map")          # страницы с одним адресом на все языки


def site_header(lang: str | None, on: str = "", path_tail: str = "/") -> str:
    """Шапка сайта. `lang` — язык страницы; None — язык выбирает браузер
    (данные, карта данных, Impressum): шапка приходит с подписями на трёх
    языках и маленьким скриптом, который выбирает их так же, как витрина
    (?lang → сохранённый выбор → язык браузера → английский)."""
    on_attr = ' class="on"'
    L = lang or "ru"

    def href(k, p):
        # Карта и данные — один адрес на все языки: язык передаём явно, иначе
        # страница выбирает его по браузеру и с русской статьи открывалась
        # по-английски (чекап 02.11.2026).
        if k in LANG_LOCAL:
            return f"{p}?lang={lang}" if lang else p
        return f"/{L}{p}"
    labels = lambda key: esc(json.dumps({x: T[x][key] for x in LANGS}, ensure_ascii=False))  # noqa: E731
    nav = "".join(f'<a href="{href(k, p)}" data-p="{p}" data-l="{labels(key)}"{on_attr if k == on else ""}>'
                  f'{esc(T[L][key])}</a>' for k, p, key in NAV)
    if lang:
        lg = "".join(f'<a href="/{x}{path_tail}" hreflang="{x}"{on_attr if x == lang else ""}>{x.upper()}</a>'
                     for x in LANGS)
    else:
        lg = "".join(f'<a href="?lang={x}" data-x="{x}">{x.upper()}</a>' for x in LANGS)
    out = (f'<header class="sh"><a class="brand" href="/{L}/" data-p="/">FlightCost'
           f'<span data-l="{labels("brand_tag")}">{esc(T[L]["brand_tag"])}</span></a>'
           f'<nav>{nav}</nav><span class="lg">{lg}</span></header>')
    if lang:
        # Выбор языка запоминается так же, как в витрине: страницы без языка
        # в адресе (карта, данные, Impressum) откроются на нём.
        out += ("<script>try{localStorage.setItem('fca.lang','%s')}catch(e){}</script>" % lang)
    if not lang:
        out += ("<script>(function(){var L=['ru','en','de'],q=new URLSearchParams(location.search).get('lang'),s=null;"
                "try{s=localStorage.getItem('fca.lang')}catch(e){}var g=L.indexOf(q)>=0?q:L.indexOf(s)>=0?s:null;"
                "if(!g){var n=navigator.languages||[navigator.language||''];for(var i=0;i<n.length&&!g;i++){"
                "var p=String(n[i]).slice(0,2).toLowerCase();if(L.indexOf(p)>=0)g=p}}g=g||'en';"
                "var h=document.currentScript.previousElementSibling;"
                "h.querySelectorAll('[data-l]').forEach(function(a){a.textContent=JSON.parse(a.dataset.l)[g]});"
                "h.querySelectorAll('a[data-p]').forEach(function(a){var p=a.dataset.p;"
                "if(p!=='/data'&&p!=='/map')a.href='/'+g+p});"
                "h.querySelectorAll('.lg a').forEach(function(a){if(a.dataset.x===g)a.className='on'})})();</script>")
    return out


# Игра SkyBoss — на поддомене; ссылка ненавязчивая, в подвале: доход игры
# оплачивает поддержку открытого приложения (решение 232).
GAME_URL = "https://play.flightcost.app/"


def shell(lang: str, path_tail: str, head_html: str, body: str, on: str = "") -> str:
    t = T[lang]
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{head_html}
<link rel="stylesheet" href="/ui.css">
{STYLE}</head><body>
{site_header(lang, on, path_tail)}
<main>{body}</main>
<footer><a href="{REPO}">GitHub — {esc(t["foot_open"])}</a><a href="/impressum">Impressum</a>
<a href="/datenschutz">Datenschutz</a><a class="game" href="{GAME_URL}" title="{esc(t["foot_game_t"])}">{esc(t["foot_game"])} ↗</a></footer>
</body></html>"""


# ── витрина на языковом адресе ─────────────────────────────────────────────

def calc_page(lang: str | None, page: str) -> str:
    """Калькулятор (витрина) с заголовком для поисковика.

    `lang=None` — калькулятор по старому адресу `/` с параметрами маршрута
    или по ссылке рабочего места: язык выбирает браузер. Иначе язык задан
    адресом `/<язык>/calc`.
    """
    lg = lang or "en"
    t = T[lg]
    canon = f"{site()}/{lg}/calc"
    h = head(lg, t["calc_title"], t["calc_desc"], canon, alternates("/calc"), [app_ld(lg)])
    page = re.sub(r"<title>.*?</title>", lambda _m: h, page, count=1, flags=re.S)
    page = page.replace('<html lang="ru">', f'<html lang="{lg}">', 1)
    # Относительные адреса ломаются под /en/: ui.css и модули — от корня.
    page = page.replace('href="ui.css"', 'href="/ui.css"').replace('from "./geo.js"', 'from "/geo.js"')
    page = page.replace('from "./globe.js"', 'from "/globe.js"')
    if lang:
        page = page.replace('href="/about"', f'href="/{lang}/about"').replace(
            'href="/types"', f'href="/{lang}/types"').replace('href="/" id="homelink"', f'href="/{lang}/" id="homelink"')
    # Заголовок первого уровня и текст без скриптов: у витрины их нет,
    # а поисковик и читалка экрана начинают с них.
    links = (f'<a href="/{lg}/about">{esc(t["nav_about"])}</a> · '
             f'<a href="/{lg}/types">{esc(t["nav_types"])}</a>')
    seo = (f'<h1 class="vh">{esc(t["calc_h1"])}</h1>'
           f'<noscript><div class="nojs"><h1>{esc(t["calc_h1"])}</h1><p>{esc(t["calc_desc"])}</p>'
           f'<p>{esc(t["noscript"])} {links}</p></div></noscript>')
    return page.replace("<body>", "<body>\n" + seo, 1) if "<body>" in page else page


# ── главная: обложка и три входа ──────────────────────────────────────────

LANDING_STYLE = """<style>
.hero{position:relative;overflow:hidden;border-bottom:1px solid var(--line)}
.hero .in{position:relative;max-width:1080px;margin:0 auto;padding:72px 22px 64px}
.hero .arcs{position:absolute;right:-140px;top:-170px;width:720px;height:720px;pointer-events:none}
.hero h1{font-size:54px;line-height:1.08;margin:0 0 18px;max-width:17ch;color:var(--ink2)}
.hero p{font-size:20px;color:var(--dim);max-width:46ch;margin:0 0 28px}
.btns{display:flex;gap:12px;flex-wrap:wrap}
.btn1,.btn2{display:inline-block;padding:12px 20px;border-radius:7px;font-weight:600;text-decoration:none;font-size:15.5px}
.btn1{background:var(--accent);color:var(--bg)}.btn1:hover{filter:brightness(1.1)}
.btn2{border:1px solid var(--line);color:var(--ink2)}.btn2:hover{border-color:var(--accent)}
.tags{display:flex;gap:10px;flex-wrap:wrap;margin-top:34px}
.tags span{font-size:13.5px;padding:5px 12px;border:1px solid var(--line);border-radius:16px;color:var(--ink)}
.tags span:first-child{border-color:var(--calc);color:var(--calc)}
.doors{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:14px 0 8px}
.door{display:block;border:1px solid var(--line);border-radius:10px;padding:18px;background:var(--panel);
  text-decoration:none;color:var(--ink)}
.door:hover{border-color:var(--accent)}.door b{display:block;color:var(--ink2);font-size:17px;margin-bottom:6px}
.door span{font-size:14px;color:var(--dim)}.door.adv b::after{content:" ·  pro";color:var(--faint);font-weight:400;font-size:13px}
.sample{border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:10px 0}
.sample .cap{font-size:13px;color:var(--dim)}
main.wide{max-width:1080px}
@media(max-width:640px){.hero .in{padding:44px 16px 40px}.hero h1{font-size:36px}.hero p{font-size:17px}
  .hero .arcs{width:420px;height:420px;right:-200px;top:-150px;opacity:.3}}
</style>"""

ARCS = ('<svg class="arcs" viewBox="0 0 720 720" aria-hidden="true">'
        '<circle cx="360" cy="360" r="330" fill="none" stroke="var(--line)" stroke-width="2"/>'
        '<circle cx="360" cy="360" r="200" fill="none" stroke="var(--accent)" stroke-width="2" '
        'stroke-dasharray="6 7" opacity=".5"/>'
        '<path d="M120 520 Q 330 250 610 300" fill="none" stroke="var(--ink2)" stroke-width="2.4" opacity=".7"/>'
        '<circle cx="120" cy="520" r="6" fill="var(--ink2)"/><circle cx="610" cy="300" r="6" fill="var(--accent)"/>'
        '</svg>')


def landing(lang: str, sample: dict | None) -> str:
    """Главная: обложка, три входа (типы · расчёт · сеть), пример расчёта, коротко о сервисе.

    Корень «/» отдаёт ту же страницу на языке браузера, но canonical у неё
    всегда языковой: «/» и «/en/» с одинаковым текстом и разными canonical
    Google считал копиями и выбирал сам (Search Console, ноябрь 2026)."""
    t, a = T[lang], ABOUT[lang]
    hero = (f'<section class="hero">{ARCS}<div class="in"><h1>{esc(t["hero_h"])}</h1><p>{esc(t["hero_p"])}</p>'
            f'<div class="btns"><a class="btn1" href="/{lang}/calc">{esc(t["go_calc"])}</a>'
            f'<a class="btn2" href="/{lang}/types">{esc(t["go_types"])}</a></div>'
            f'<div class="tags">' + "".join(f"<span>{esc(x)}</span>" for x in t["hero_tags"]) + "</div></div></section>")
    doors = [(f"/{lang}/types", *t["door_types"], ""), (f"/{lang}/calc", *t["door_calc"], ""),
             (f"/{lang}/calc?mode=net", *t["door_net"], " adv")]
    body = [f"<h2>{esc(t['doors_h'])}</h2><div class=doors>" + "".join(
        f'<a class="door{c}" href="{esc(u)}"><b>{esc(h)}</b><span>{esc(d)}</span></a>' for u, h, d, c in doors)
        + "</div>"]
    if sample and sample.get("e") and not sample["e"].get("no_model") and sample["e"].get("total"):
        cap = t["sample_l"].format(name=sample["name"], route=route_name(lang, sample["cls"]))
        body.append(f"<h2>{esc(t['sample_h'])}</h2><div class=sample><div class=cap>{esc(cap)}</div>"
                    + _kpis(lang, sample["e"])
                    + f'<a href="{esc(calc_link(lang, sample["cls"], sample["icao"]))}">{esc(t["sample_open"])}</a></div>')
    from .research import TXT as RTX, _tr, human_date, items as r_items
    last = r_items()[:1]
    if last:
        it = last[0]
        body.append(f'<h2>{esc(RTX[lang]["h"])}</h2><a class="door" style="display:block" href="/{lang}/research/{it["slug"]}">'
                    f'<span>{esc(human_date(it["date"], lang))}</span><b>{esc(_tr(it, "title", lang))}</b>'
                    f'<span>{esc(_tr(it, "lede", lang))}</span></a>'
                    f'<p><a href="/{lang}/research">{esc(RTX[lang]["h"])} →</a></p>')
    sec_h, items = a["sections"][0]
    body.append(f"<h2>{esc(t['what_h'])}</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in items[:5]) + "</ul>"
                f"<p class=dim>{esc(a['how'])}</p><p><a href=\"/{lang}/about\">{esc(t['more_about'])}</a></p>")
    h = head(lang, t["home_title"], t["home_desc"], f"{site()}/{lang}/", alternates("/"), [app_ld(lang)])
    page = shell(lang, "/", h + LANDING_STYLE, "\n".join(body))
    return page.replace("<main>", hero + '<main class="wide">', 1)


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
            f'<a class="cta" href="/{lang}/calc">{esc(t["nav_calc"])} →</a>']
    for h, items in a["sections"]:
        body.append(f"<h2>{esc(h)}</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>")
    body.append(f"<h2>{esc(a['how_h'])}</h2><p>{esc(a['how'])}</p>")
    body.append(f"<h2>{esc(a['who_h'])}</h2><p>{esc(a['who'])}</p>")
    body.append(f"<h2>{esc(a['faq_h'])}</h2>" + "".join(
        f"<details open><summary>{esc(q)}</summary><p>{esc(ans)}</p></details>" for q, ans in a["faq"]))
    body.append(f'<p class="dim"><a href="/{lang}/types">{esc(t["nav_types"])}</a> · '
                f'<a href="/data?lang={lang}">{esc(t["nav_data"])}</a> · <a href="/map?lang={lang}">{esc(t["nav_map"])}</a> · '
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


# Деловая авиация и типы до 10 кресел в справочнике есть (их тянет openap),
# но на страницах типов не нужны: сайт — про гражданские перевозки от 11 мест.
BIZJETS = {"C550", "GLF6", "GLF5", "GLEX", "CL60", "C56X", "C68A", "E55P", "PC12", "LJ45"}


def public_types(types: list[dict]) -> list[dict]:
    """Типы для страниц: код ИКАО (без USER:), имя, гражданский от 11 кресел."""
    def big(t):
        m = t.get("seats_max") or t.get("seats_typical")
        return not isinstance(m, (int, float)) or m >= 11
    return [t for t in types if TYPE_CODE.match(t["icao"] or "") and t.get("name")
            and t["icao"] not in BIZJETS and big(t)]


def seats_of(t: dict) -> float | None:
    v = t.get("seats_typical") or t.get("seats_max")
    return float(v) if isinstance(v, (int, float)) else None


def seats_max_of(t: dict) -> float | None:
    """Кресла для показа и расчёта — максимум по сертификату (решение владельца, 29.10.2026).
    Класс типа (`cls_of`) остаётся по типовой компоновке: по максимуму A321neo (244)
    ушёл бы в широкофюзеляжные."""
    v = t.get("seats_max") or t.get("seats_typical")
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
        rows = sorted((x for x in pub if cls_of(x) == c), key=lambda x: (-(seats_max_of(x) or 0), x["icao"]))
        if not rows:
            continue
        body.append(f"<h2>{esc(t['cls'][c])}</h2><div class=tw><table><tr><th>{esc(t['col_type'])}</th>"
                    f"<th>ICAO</th><th class=r>{esc(t['col_seats'])}</th><th class=r>{esc(t['col_mtow'])}</th></tr>")
        for x in rows:
            note = "" if x.get("usable") else f'<span class=tag>{esc(t["card_only"])}</span>'
            body.append(f'<tr><td><a href="{type_url(lang, x["icao"])}">{esc(name_of(x, lang))}</a>{note}</td>'
                        f'<td>{esc(x["icao"])}</td><td class=r>{num(seats_max_of(x), lang, 0)}</td>'
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
    s = by.get("seats_max") or by.get("seats_typical")
    if s and s.get("value"):
        n = num(s["value"], lang, 0)
        bits.append({"ru": f"до {n} кресел", "en": f"up to {n} seats", "de": f"bis zu {n} Sitze"}[lang])
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


# ── типовой маршрут ────────────────────────────────────────────────────────
# Все из Франкфурта — эталон проекта (решение владельца, 28.10.2026). Пара
# на класс, а не на тип: внутри класса типы сравниваются на одном рейсе.
# Второй конец выбран из аэропортов с разобранным тарифом: Вена, Барселона,
# Пекин — иначе половина суммы была бы параметрикой сборов.
ROUTES = {"small": ("EDDF", "LOWW"), "regional": ("EDDF", "LOWW"),
          "narrow": ("EDDF", "LEBL"), "wide": ("EDDF", "ZBAA")}
CITY = {"EDDF": ("Франкфурт", "Frankfurt", "Frankfurt"), "LOWW": ("Вена", "Vienna", "Wien"),
        "LEBL": ("Барселона", "Barcelona", "Barcelona"), "ZBAA": ("Пекин", "Beijing", "Peking")}
ECON_LF, ECON_MONTH = 0.80, 7
# Метка данных, собранных разработчиком, а не опубликованных издателем
# (tools/catalog_fill.py ставит её в начало источника якоря расхода и в
# meta.assumed поля паспорта). Страница типа показывает её словами.
DEV_PREFIX = "Оценка разработчика FlightCost"
PROV = {"default": "guess", "fleet": "guess", "estimated": "guess", "derived": "calc", "calc": "calc"}


def route_name(lang: str, cls: str) -> str:
    o, d = ROUTES[cls]
    return f"{CITY[o][LI[lang]]} — {CITY[d][LI[lang]]}"


def calc_link(lang: str, cls: str, icao: str) -> str:
    o, d = ROUTES[cls]
    return f"/{lang}/calc?o={o}&d={d}&ac={quote(icao)}"


def econ_summary(j: dict) -> dict:
    """Ответ ядра (`result_json`) → то, что показывает страница типа."""
    r, a = j["route"], j["answer"]
    seats, km = int(r.get("seats") or 0), float(r.get("distance_nm") or 0) * 1.852
    total, bh = float(a.get("cost_total") or 0), float(r.get("block_h") or 0)
    lim = ((a.get("feasibility") or {}).get("limits")) or []
    return {"km": km, "block_h": bh, "fuel_kg": r.get("fuel_kg"), "seats": seats, "pax": r.get("pax"),
            "total": total, "per_seat": total / seats if seats else None,
            "cask_ct": total / (seats * km) * 100 if seats and km else None,
            "per_bh": total / bh if bh else None, "be_fare": a.get("breakeven_fare_eur"),
            "feasible": bool(a.get("feasible")), "max_pax": a.get("max_pax"),
            "limits": [x.get("key") for x in lim],
            # Нет вычислителя расхода (типа нет в openap) или назван аналог без якоря.
            "no_model": any(x.get("key") in ("no_model", "no_anchor") for x in lim),
            "cost": [{"item": c["item"], "label": c["label"], "eur": c["eur"], "prov": c.get("prov")}
                     for c in j.get("cost", []) if c.get("eur", 0) > 0.5],
            "default_share": j.get("default_share")}


_CAT = None


def tr(lang: str, ru: str) -> str:
    """Подпись ядра (по-русски) → язык страницы, из каталога витрины."""
    global _CAT
    if lang == "ru":
        return ru
    if _CAT is None:
        try:
            from pathlib import Path
            _CAT = json.loads((Path(__file__).parent / "web" / "i18n.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CAT = {}
    return (_CAT.get(lang) or {}).get(ru, ru)


def silhouettes(entry: dict, others: list[dict]) -> str:
    """Вид сверху: тип заливкой, соседи по классу контуром, один масштаб, линейка 10 м."""
    from .fleetreport_doc import silhouette_parts
    items = [(entry, silhouette_parts(entry.get("geom")), True)] + [
        (o, silhouette_parts(o.get("geom")), False) for o in others]
    items = [x for x in items if x[1]]
    if not items or not items[0][2]:
        return ""
    span = max(p["span"] for _, p, _ in items)
    top = min(p["top"] for _, p, _ in items)
    length = max(p["length"] for _, p, _ in items)
    pad = 1.5
    sw = span * .006
    g = []
    for _t, p, me in sorted(items, key=lambda x: x[2]):            # свой — поверх
        body = "".join(f'<polygon points="{x}"/>' for x in p["polys"]) + f'<path d="{p["fus"]}"/>'
        if me:
            g.append(f'<g fill="var(--accent)" fill-opacity=".22" stroke="var(--accent)" '
                     f'stroke-width="{sw:.2f}" stroke-linejoin="round">{body}{p["eng"]}</g>')
        else:
            g.append(f'<g fill="none" stroke="var(--dim)" stroke-width="{sw:.2f}" stroke-linejoin="round" '
                     f'stroke-dasharray="{sw * 5:.2f} {sw * 4:.2f}">{body}{p["eng"]}</g>')
    # Поворачиваем контуры вместе, оставляя линейку и подпись горизонтальными.
    extent = length - top
    px = min(520, max(240, 9 * extent))
    return (f'<svg viewBox="{top - pad:.2f} {-span / 2 - pad:.2f} '
            f'{extent + 2 * pad:.2f} {span + 2 * pad + 3:.2f}" width="{px:.0f}" '
            f'role="img" aria-label="top view"><g transform="rotate(-90)">{"".join(g)}</g>'
            f'<g transform="translate({top:.2f} {span / 2 + pad + 1:.2f})" fill="var(--dim)">'
            f'<path d="M0,-0.6v1.2 M0,0h10 M10,-0.6v1.2" stroke="var(--dim)" '
            f'stroke-width="{span * .004:.2f}"/><text x="11" y=".6" '
            f'font-size="{span * .035:.2f}">10 m</text></g></svg>')


def _kpis(lang: str, e: dict) -> str:
    t = T[lang]
    tiles = [(e["total"], t["k_total"], 0), (e["per_seat"], t["k_seat"], 0), (e["cask_ct"], t["k_cask"], 1),
             (e["per_bh"], t["k_bh"], 0), (e["be_fare"], t["k_be"], 0)]
    return '<div class="kpis">' + "".join(f'<div class="kpi"><b>{num(v, lang, d)}</b><span>{esc(lab)}</span></div>'
                                          for v, lab, d in tiles if v) + "</div>"


def econ_sections(lang: str, entry: dict, by: dict, econ: dict | None, cls: str, types: list[dict]) -> tuple[str, str]:
    """Экономика на типовом маршруте и сравнение с классом."""
    t = T[lang]
    out = [f"<h2>{esc(t['econ_h'].format(route=route_name(lang, cls)))}</h2>"]
    if econ is None:
        return "".join(out) + f'<p class="dim">{esc(t["econ_wait"])}</p>', ""
    e = econ.get(entry["icao"])
    if not e or e.get("error"):
        return "", ""
    if e["no_model"]:
        return "".join(out) + f'<p class="dim">{esc(t["no_model"])}</p>', ""
    rng = (by.get("range_km") or {}).get("value")
    lead = t["econ_lead"].format(km=num(e["km"], lang, 0), bh=num(e["block_h"], lang, 1), pax=e["pax"],
                                 seats=e["seats"], dflt=num((e.get("default_share") or 0) * 100, lang, 0))
    if rng:
        lead += " " + t["econ_range"].format(range=num(rng, lang, 0))
    out.append(f'<p class="dim">{esc(lead)}</p>')
    bnote = str((by.get("burn_anchor_note") or {}).get("text") or "")
    if bnote.startswith(DEV_PREFIX):
        src = bnote[len(DEV_PREFIX):].lstrip(" :—-")
        if lang != "ru" and CYR.search(src):
            src = re.sub(r".*?(https?://\S+).*", r"\1", src) if "http" in src else ""
        out.append(f'<p class="dim p-guess">{esc(t["dev_burn"].format(src=src).rstrip(": "))}</p>')
    if not e["feasible"]:
        why = "; ".join(t["lim"].get(k, k).format(mp=e.get("max_pax")) for k in e["limits"] if k in t["lim"])
        out.append(f'<div class="warn">{esc(t["infeasible"].format(why=why or "—"))}</div>')
    out.append(_kpis(lang, e))
    out.append(f"<div class=tw><table><tr><th>{esc(t['col_item'])}</th><th class=r>{esc(t['col_eur'])}</th>"
               f"<th class=r>{esc(t['col_share'])}</th><th>{esc(t['col_prov'])}</th></tr>")
    for c in e["cost"]:
        pv = PROV.get(c.get("prov") or "", "doc")
        out.append(f"<tr><td>{esc(tr(lang, c['label']))}</td><td class=r>{num(c['eur'], lang, 0)}</td>"
                   f"<td class=r>{num(c['eur'] / e['total'] * 100 if e['total'] else 0, lang, 0)}%</td>"
                   f"<td class='s p-{pv}'>{esc(t['prov'][pv])}</td></tr>")
    out.append("</table></div>")
    out.append(f'<a class="cta" href="{esc(calc_link(lang, cls, entry["icao"]))}">{esc(t["econ_open"])}</a>')
    # Сравнение с классом: тот же рейс, те же допущения.
    rows = []
    names = {x["icao"]: x for x in public_types(types)}
    for icao, x in econ.items():
        if icao in names and not x.get("error") and not x.get("no_model") and x.get("feasible") and x.get("per_seat"):
            rows.append((icao, x))
    comparison = []
    if len(rows) > 1:
        rows.sort(key=lambda r: r[1]["per_seat"])
        comparison.append(f"<h2>{esc(t['cmp_h'])}</h2><p class=dim>{esc(t['cmp_lead'])}</p><div class=tw><table>"
                   f"<tr><th>{esc(t['col_type'])}</th><th class=r>{esc(t['col_seats'])}</th>"
                   f"<th class=r>{esc(t['k_total'])}</th><th class=r>{esc(t['k_seat'])}</th>"
                   f"<th class=r>CASK, ¢</th></tr>")
        for icao, x in rows:
            me = ' class="me"' if icao == entry["icao"] else ""
            comparison.append(f'<tr{me}><td><a href="{type_url(lang, icao)}">{esc(name_of(names[icao], lang))}</a></td>'
                       f"<td class=r>{x['seats']}</td><td class=r>{num(x['total'], lang, 0)}</td>"
                       f"<td class=r>{num(x['per_seat'], lang, 0)}</td><td class=r>{num(x['cask_ct'], lang, 1)}</td></tr>")
        comparison.append("</table></div>")
    return "\n".join(out), "\n".join(comparison)


def type_page(lang: str, info: dict, entry: dict, types: list[dict], econ: dict | None = None,
              *, designer_enabled: bool = False, designer_origin: str | None = None, lease_market=None) -> str:
    """Страница одного типа. `info` — Context.aircraft_type, `entry` — строка Context.aircraft,
    `econ` — расчёты класса на типовом маршруте (Context.seo_econ) или None, пока не готовы."""
    t = T[lang]
    icao, name = entry["icao"], name_of(entry, lang) or info.get("name") or entry["icao"]
    by = {f["field"]: f for f in info.get("fields", [])}
    facts = facts_line(lang, by)
    fd = info.get("fleet_default") or {}
    model_lease_eur = fd.get("lease_eur_month")
    if fd and (lease_market or {}).get("lease_eur_month") is not None:
        fd = {**fd, "lease_eur_month": lease_market["lease_eur_month"]}
    lease_eur = fd.get("lease_eur_month")
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › <a href="/{lang}/types">'
            f'{esc(t["nav_types"])}</a> › {esc(icao)}</div>',
            f"<h1>{esc(t['type_h1'].format(name=name, icao=icao))}</h1>",
            f'<p class="lead">{esc(t["type_lead"].format(name=name, icao=icao, facts=(" — " + facts) if facts else ""))}</p>']
    cls = cls_of(entry)
    widget = ""
    if entry.get("usable"):
        body.append(f'<a class="cta" href="{esc(calc_link(lang, cls, icao))}">{esc(t["cta"].format(icao=icao))}</a>')
        if not icao.upper().startswith("USER:"):
            body.append(type_editor(lang, icao, cls, fd))
            if designer_enabled:
                widget = designer_widget(lang, icao, info, cls, designer_origin)
                if widget:
                    body.append(widget)
    else:
        gaps = by.get("calc_gaps", {}).get("text") or "—"
        body.append(f'<p class="dim">{esc(t["type_card"].format(gaps=gaps))}</p>')
    me_seats = seats_of(entry) or 0
    near = sorted((x for x in public_types(types) if x["icao"] != icao and cls_of(x) == cls and x.get("geom")),
                  key=lambda x: abs((seats_of(x) or 0) - me_seats))[:2]
    svg = silhouettes(entry, near)
    if svg:
        lgd = (f'<div class="lgd"><div><i></i>{esc(name)}</div>'
               + "".join(f'<div><i class="o"></i>{esc(name_of(x, lang))}</div>' for x in near) + "</div>")
        initial_state = "" if widget else " open"
        body.append(f'<details class="sil-details" id="scheme"{initial_state}>'
                    f'<summary><h2>{esc(t["sil_h"])}</h2></summary>'
                    f'<p class=dim>{esc(t["sil_lead"])}</p><div class="sil">{svg}{lgd}</div></details>')
    comparison = ""
    if entry.get("usable"):
        economics, comparison = econ_sections(lang, entry, by, econ, cls, types)
        body.append(economics)
    st = by.get("program_status", {}).get("text")
    rows = []
    if st:
        rows.append((t["status"], t["st"].get(st, st), ("", "")))
    assumed = dict(x.split(": ", 1) for x in str((by.get("assumed") or {}).get("text") or "").split("; ")
                   if ": " in x)
    for key, labels in SPEC:
        f = by.get(key)
        if not f or (f.get("value") is None and not f.get("text")):
            continue
        val = _value(f, key, lang)
        # Текстовые поля каталога (двигатель, производитель) бывают только
        # по-русски: на английской и немецкой странице такую строку не
        # показываем, а не показываем кириллицу.
        if val and not (lang != "ru" and CYR.search(val)):
            # Поле, собранное разработчиком, а не опубликованное, — так и подписано.
            dev = assumed.get(key, "").startswith(DEV_PREFIX)
            rows.append((labels[LI[lang]], val, (t["dev_field"], "") if dev else _src(f, lang)))
    if rows:
        body.append(f"<h2>{esc(t['specs_h'])}</h2><div class=tw><table class=spec><tr><th>{esc(t['col_param'])}</th>"
                    f"<th class=r>{esc(t['col_value'])}</th><th>{esc(t['col_src'])}</th></tr>")
        for lab, val, (sl, su) in rows:
            src = f'<a href="{esc(su)}" rel="nofollow">{esc(sl)}</a>' if su else esc(sl)
            # Числа — в строку и по правому краю; текст (производитель, двигатель,
            # ввод в эксплуатацию) переносится, иначе длинная строка выдавливает таблицу вправо.
            vcls = "r" if re.fullmatch(r"[\d\s.,−\-]+", val) else "r tx"
            body.append(f"<tr><td>{esc(lab)}</td><td class='{vcls}'>{esc(val)}</td><td class=s>{src}</td></tr>")
        body.append("</table></div>")
    if fd and entry.get("usable"):
        own = lease_eur / fd["monthly_hours"] if lease_eur is not None and fd.get("monthly_hours") else None
        frows = [(t["f_lease"], lease_eur), (t["f_hours"], fd.get("monthly_hours")),
                 (t["f_own"], own), (t["f_mfh"], fd.get("maint_eur_per_fh")), (t["f_mfc"], fd.get("maint_eur_per_fc")),
                 (t["f_cfh"], fd.get("crew_eur_per_fh")), (t["f_cfc"], fd.get("crew_eur_per_fc"))]
        body.append(f"<h2>{esc(t['fleet_h'])}</h2><p class=dim>{esc(t['fleet_lead'])}</p><div class=tw><table>")
        for lab, v in frows:
            if v is not None:
                body.append(f"<tr><td>{esc(lab)}</td><td class='r guess'>{num(v, lang, 0)}</td></tr>")
        body.append("</table></div>")
    body.append(toir_block(lang, icao))
    from .fleet import generation
    body.append(prices_block(lang, icao, model_lease_eur,
                             generation(icao) == "new", lease_market=lease_market))
    me = seats_of(entry) or 0
    has_cmp = bool(econ) and entry.get("usable")      # таблица класса уже ведёт к соседям
    sim = [] if has_cmp else sorted((x for x in public_types(types) if x["icao"] != icao and x.get("usable")
                  and cls_of(x) == cls_of(entry)), key=lambda x: abs((seats_of(x) or 0) - me))[:8]
    if sim:
        body.append(f"<h2>{esc(t['similar_h'])}</h2><div class=chips>" + "".join(
            f'<a href="{type_url(lang, x["icao"])}">{esc(name_of(x, lang))}</a>' for x in sim) + "</div>")
    body.append(comparison)
    # Ставки — в описание для выдачи: по запросам «a321neo price», «maintenance rates»
    # человек видит цифру уже в сниппете (Search Console, ноябрь 2026).
    rates = ""
    if fd and entry.get("usable") and lease_eur is not None and fd.get("maint_eur_per_fh"):
        rates = t["type_rates"].format(lease=num(round(lease_eur, -3), lang, 0),
                                       mfh=num(round(fd["maint_eur_per_fh"], -1), lang, 0))
    desc = t["type_desc"].format(name=name, icao=icao, facts=facts or icao, rates=rates)
    h = head(lang, t["type_title"].format(name=name, icao=icao), desc[:300], site() + type_url(lang, icao),
             alternates(f"/type/{quote(icao)}"),
             [crumbs_ld([("FlightCost", f"{site()}/{lang}/"), (t["nav_types"], f"{site()}/{lang}/types"),
                         (name, site() + type_url(lang, icao))])])
    return shell(lang, f"/type/{quote(icao)}", h, "\n".join(body), on="types")


# ── ряды на странице типа: ТОиР по Form 41, цены и лизинг из публикаций ──

def _ts_svg(lines: list[tuple[str, list[tuple[float, float]]]], points: list[tuple[str, float, float]] | None = None,
            unit: str = "", lang: str = "ru", w: int = 680, h: int = 220,
            ranges: list[tuple[str, list[tuple[float, float, float, str]]]] | None = None) -> str:
    """Линии, точки и диапазоны [(css-класс, [(x, низ, верх, подпись)])].

    Каждая серия диапазонов уже сопоставима по виду, возрасту и источнику.
    Одна дата даёт только вертикальный интервал; полоса появляется между датами.
    """
    intervals = [(cls, x, lo, hi, label) for cls, ps in ranges or [] for x, lo, hi, label in ps]
    xs = [x for _, ps in lines for x, _ in ps] + [x for _, x, _ in points or []] + [p[1] for p in intervals]
    ys = [y for _, ps in lines for _, y in ps] + [y for _, _, y in points or []] + [y for p in intervals for y in p[2:4]]
    if not xs:
        return ""
    x0, x1 = min(xs), max(xs)
    if x1 == x0:
        x0, x1 = x0 - 1, x1 + 1
    if (points or intervals) and not lines:        # точки и засечки у края не срезаются
        x0, x1 = x0 - 0.3, x1 + 0.3
    y1 = max(ys) * 1.1 or 1
    L, R, Tp, B = 48, 20, 10, 26
    X = lambda x: L + (x - x0) / (x1 - x0) * (w - L - R)        # noqa: E731
    Y = lambda y: h - B - y / y1 * (h - Tp - B)                  # noqa: E731
    description = "; ".join([unit, *[p[4] for p in intervals]])
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(description)}">',
           f'<line class=ax x1="{L}" y1="{h - B}" x2="{w - R}" y2="{h - B}"/>']
    import math
    raw = y1 / 5
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(mag * k for k in (1, 2, 5, 10) if mag * k >= raw)
    y = step
    while y < y1:
        out.append(f'<line class=ax x1="{L}" y1="{Y(y):.1f}" x2="{w - R}" y2="{Y(y):.1f}" opacity=".5"/>'
                   f'<text x="{L - 6}" y="{Y(y) + 4:.1f}" text-anchor="end">{num(y, lang, 0)}</text>')
        y += step
    span = int(x1) - int(x0)
    ev = 1 if span <= 10 else 2 if span <= 20 else 5
    for yr in range(math.ceil(x0 / ev) * ev, math.floor(x1) + 1, ev):
        out.append(f'<text x="{X(yr):.1f}" y="{h - 8}" text-anchor="middle">{yr}</text>')
    for cls, ps in ranges or []:
        if len(ps) > 1:
            up = " ".join(f"{X(x):.1f},{Y(hi):.1f}" for x, _, hi, _ in ps)
            dn = " ".join(f"{X(x):.1f},{Y(lo):.1f}" for x, lo, _, _ in reversed(ps))
            out.append(f'<polygon class="range-band {esc(cls)}" points="{up} {dn}"/>')
            mid = " ".join(f"{X(x):.1f},{Y((lo + hi) / 2):.1f}" for x, lo, hi, _ in ps)
            out.append(f'<polyline class="range-midline {esc(cls)}" points="{mid}"/>')
    for cls, ps in lines:
        if len(ps) > 1:
            out.append(f'<polyline class={cls} points="' + " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in ps) + '"/>')
    for cls, x, lo, hi, label in intervals:
        px, yl, yh, ym = X(x), Y(lo), Y(hi), Y((lo + hi) / 2)
        out.append(f'<g class="price-interval" role="img" aria-label="{esc(label)}"><title>{esc(label)}</title>'
                   f'<path class="range-bar {esc(cls)}" d="M{px:.1f},{yh:.1f}V{yl:.1f}'
                   f'M{px - 5:.1f},{yh:.1f}H{px + 5:.1f}M{px - 5:.1f},{yl:.1f}H{px + 5:.1f}"/>'
                   f'<circle class="midpoint {esc(cls)}" cx="{px:.1f}" cy="{ym:.1f}" r="4">'
                   f'<title>{esc(label)}</title></circle></g>')
        if len(intervals) == 1:                    # одиночный диапазон читается без наведения
            mid = num((lo + hi) / 2, lang, 6).rstrip("0").rstrip(".,")
            left = px > w * 0.55
            out.append(f'<text class="range-label" x="{px + (-10 if left else 10):.1f}" y="{ym + 4:.1f}"'
                       f' text-anchor="{"end" if left else "start"}">{esc(mid)} · {esc(T[lang]["ts_midpoint"])}</text>')
    for cls, x, y in points or []:
        out.append(f'<circle class={cls} cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4"/>')
    return "".join(out) + "</svg>"


TOIR_SERIES = Path(__file__).resolve().parents[1] / "data" / "maintenance" / "_toir_series.yaml"
_TS_CACHE: dict = {}


def toir_series(icao: str) -> dict:
    try:
        mt = TOIR_SERIES.stat().st_mtime
    except OSError:
        return {}
    if _TS_CACHE.get("mt") != mt:
        import yaml
        _TS_CACHE.update(mt=mt, d=(yaml.safe_load(TOIR_SERIES.read_text("utf-8")) or {}).get("types") or {})
    return _TS_CACHE["d"].get(icao.upper()) or {}


def toir_block(lang: str, icao: str) -> str:
    t, ser = T[lang], toir_series(icao)
    if len(ser) < 3:
        return ""
    ys = sorted(ser)
    svg = _ts_svg([("l2", [(y, ser[y][1]) for y in ys]), ("l1", [(y, ser[y][0]) for y in ys])],
                  [("p1", y, ser[y][0]) for y in ys], t["ts_unit"], lang)
    last = ys[-1]
    d, tot, n, _ = ser[last]
    return (f'<h2>{esc(t["ts_m_h"])}</h2><p class=dim>{esc(t["ts_m_lead"])}</p><div class=ts>'
            f'<div class=lg><i style="background:var(--accent)"></i>{esc(t["ts_direct"])}'
            f'<i style="background:var(--dim)"></i>{esc(t["ts_total"])} · {esc(t["ts_unit"])}</div>{svg}</div>'
            f'<p>{esc(t["ts_last"].format(y=last, d=num(d, lang, 0), t=num(tot, lang, 0), n=n))}</p>'
            f'<p class=dim>{esc(t["ts_src"])} <a href="/{lang}/research/toir">→</a></p>')


US_CPI = Path(__file__).resolve().parents[1] / "data" / "macro" / "_us_cpi.yaml"
PARAM_USD_PER_EUR, PARAM_YEAR = 1.16, 2026      # опора заготовки лизинга: fleet.py, октябрь 2026


def us_cpi() -> dict[int, float]:
    try:
        mt = US_CPI.stat().st_mtime
    except OSError:
        return {}
    if _TS_CACHE.get("cpi_mt") != mt:
        import yaml
        _TS_CACHE.update(cpi_mt=mt, cpi={int(k): float(v) for k, v in
                                         ((yaml.safe_load(US_CPI.read_text("utf-8")) or {}).get("years") or {}).items()})
    return _TS_CACHE["cpi"]


def param_lease_usd(eur_month: float, years: range) -> list[tuple[float, float]]:
    """Заготовка лизинга (EUR, октябрь 2026) в долларах каждого года: × курс опоры × CPI(год)/CPI(2026).
    Года после последнего в ряду CPI — продлены его последним годовым ростом."""
    cpi = us_cpi()
    if not cpi:
        return []
    last = max(cpi)
    g = cpi[last] / cpi[last - 1] if last - 1 in cpi else 1.03
    ix = lambda y: cpi[y] if y in cpi else cpi[last] * g ** (y - last)       # noqa: E731
    usd = eur_month * PARAM_USD_PER_EUR
    return [(y + 0.5, usd * ix(y) / ix(PARAM_YEAR) / 1e3) for y in years if y >= min(cpi)]


def current_lease_block(lang: str, name: str, market: dict | None) -> str:
    if not market:
        return ""
    title, monthly, count = {
        "ru": ("Актуальная ставка", "/мес.", "Первоисточников"),
        "en": ("Current lease rate", "/month", "Original sources"),
        "de": ("Aktuelle Leasingrate", "/Monat", "Originalquellen"),
    }[lang]
    links = {o["source"]: o["publisher"] or o["source"] for o in market["sources"]}
    refs = " · ".join(f'<a href="{esc(url)}">{esc(label)}</a>' for url, label in links.items()
                      if url.startswith(("https://", "http://")))
    value = num(market["midpoint"], lang, 0)
    return (f'<section class="current-lease"><h3>{title} · {esc(name)}</h3>'
            f'<p><strong>{value} {esc(market["currency"])}{monthly}</strong> · {market["year"]}</p>'
            f'<p class="dim">{count}: {market["source_count"]} · {refs}</p></section>')


def prices_block(lang: str, icao: str, lease_eur: float | None = None, new_gen: bool | None = None,
                 *, lease_market=None) -> str:
    from decimal import Decimal
    from . import prices as PR
    t, obs = T[lang], PR.of(icao)
    if not obs:
        return ""

    def pnum(v, mid_bounds=None):
        # Сохраняем дробные опубликованные границы и половину шага у середины.
        digits = max(max(0, -Decimal(str(x)).normalize().as_tuple().exponent) for x in mid_bounds or (v,))
        digits += int(mid_bounds is not None)
        text = num(v, lang, digits)
        return text.rstrip("0").rstrip(".,") if digits else text

    def age_label(o):
        if str(o.get("age")) == "new":
            return t["ts_new"]
        if o.get("age") in (None, ""):
            return t["ts_age_unknown"] if PR.is_range(o) else ""
        return num(o["age"], lang, 0)

    def publisher(o):
        return o.get("publisher") or re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", str(o.get("source", "")))

    def yx(o):
        m = str(o["month"])
        first, last = PR.period_months(m)
        return int(m[:4]) + (first + last - 1) / 24

    def chart(want_lease, divisor, unit):
        points, ranges, groups = [], [], {}
        for o in sorted(obs, key=PR.period_order):
            if (o["kind"] == "lease") != want_lease:
                continue
            values = PR.usd_bounds(o)
            if values is None:
                continue
            # Разные оценки и возраста не превращаются в один рыночный коридор.
            key = (o["kind"], o.get("age"), o["source"])
            groups.setdefault(key, []).append((o, values))
        for (kind, _, _), entries in groups.items():
            cls, segment = f"k-{kind}", []
            for o, values in entries:
                x, (lo, hi) = yx(o), (v / divisor for v in values)
                if not PR.is_range(o):
                    points.append((cls, x, lo))
                    if segment:                   # скалярная публикация прерывает полосу
                        ranges.append((cls, segment))
                        segment = []
                    continue
                label = (f"{o['month']} · {t['ts_kind'][kind]} · {t['ts_col'][3]}: {age_label(o)} · "
                         f"{t['ts_range']}: {pnum(lo)}–{pnum(hi)} {unit}; "
                         f"{t['ts_midpoint']}: {pnum((lo + hi) / 2, (lo, hi))} {unit} · {publisher(o)}")
                if segment and x <= segment[-1][0]:
                    ranges.append((cls, segment))  # две оценки одного месяца — отдельные интервалы
                    segment = []
                segment.append((x, lo, hi, label))
            if segment:
                ranges.append((cls, segment))
        return points, ranges

    craft, craft_ranges = chart(False, 1e6, t["ts_m_usd"])
    lease, lease_ranges = chart(True, 1e3, t["ts_k_usd"])
    def kind_label(kind):
        return (f'<span class="price-kind k-{esc(kind)}"><span class=price-dot aria-hidden=true></span>'
                f'<span>{esc(t["ts_kind"][kind])}</span></span>')

    lg = "".join(kind_label(k) for k in PR.KINDS if any(o["kind"] == k for o in obs))
    body = [f'<h2>{esc(t["ts_p_h"])}</h2><p class=dim>{esc(t["ts_p_lead"])}</p><div class=ts>'
            f'<div class="lg price-legend">{lg}</div>']
    body.append(current_lease_block(lang, icao, lease_market))
    if craft or craft_ranges:
        body.append(f'<p class=dim>{esc(t["ts_m_usd"])}</p>'
                    + _ts_svg([], craft, t["ts_m_usd"], lang, ranges=craft_ranges))
    if lease or lease_ranges:
        lines, note = [], ""
        if lease_eur:
            y0 = int(min([x for _, x, _ in lease] + [x for _, ps in lease_ranges for x, _, _, _ in ps]))
            pl = param_lease_usd(lease_eur, range(y0, PARAM_YEAR + 1))
            if pl:
                age = t["ts_age_new"] if new_gen else t["ts_age_cur"]
                lines = [("l3", pl)]
                note = (f'<p class=dim><span style="color:var(--price-lease)">— —</span> {esc(t["ts_param"].format(age=age))}. '
                        f'{esc(t["ts_param_note"].format(eur=num(round(lease_eur, -3), lang, 0), fx=num(PARAM_USD_PER_EUR, lang, 2), age=age, age_for=t["ts_for_new"] if new_gen else t["ts_for_cur"]))}</p>')
                if lease_market and lease_market["currency"] == "USD":
                    mn = lease_market["year"], lease_market["midpoint"] / 1000
                    py = dict((int(x), v) for x, v in pl).get(mn[0])
                    if py:
                        dd = (py / mn[1] - 1) * 100
                        note += (f'<p>{esc(t["ts_now"].format(y=mn[0], m=pnum(round(mn[1], 3)), p=num(round(py), lang, 0), d=("+" if dd >= 0 else "−") + num(abs(round(dd)), lang, 0) + " %"))}</p>')
                ly = PR.lessor_yield()
                if ly and 2019 in ly:
                    after = {y: v for y, v in ly.items() if y >= 2020}
                    ymin_y = min(after, key=after.get)
                    pct = lambda v: num(v * 100, lang, 1) + " %"        # noqa: E731
                    note += (f'<p class=dim>{esc(t["ts_yield"].format(y19=pct(ly[2019]), ymin=pct(ly[ymin_y]), ymin_y=ymin_y, ylast=pct(ly[max(ly)]), ylast_y=max(ly)))}</p>')
                pre = PR.real_level(obs, bool(new_gen), (2018, 2019), PARAM_YEAR, us_cpi())
                p26 = dict((int(x), v) for x, v in pl).get(PARAM_YEAR)
                if pre and p26:
                    rel = p26 / pre - 1
                    w = "near" if abs(rel) <= 0.1 else ("above" if rel > 0 else "below")
                    note += (f'<p class=dim>{esc(t["ts_real"].format(p=num(round(p26), lang, 0), r=num(round(pre), lang, 0), where=t["ts_where"][w]))}</p>')
        body.append(f'<p class=dim>{esc(t["ts_k_usd"])}</p>'
                    + _ts_svg(lines, lease, t["ts_k_usd"], lang, h=190, ranges=lease_ranges) + note)
    if craft_ranges or lease_ranges:
        body.append(f'<p class=dim>{esc(t["ts_range_note"])}</p>')
    c = t["ts_col"]
    body.append(f"</div><div class=tw><table class=price-table><tr><th>{c[0]}</th><th>{c[1]}</th><th class=r>{c[2]}</th>"
                f"<th class=r>{c[3]}</th><th>{c[4]}</th></tr>")
    for o in sorted(obs, key=PR.period_order, reverse=True)[:12]:
        sc = {"m": " m", "mn": " m", "million": " m", "млн": " m", "k": " k", "thousand": " k", "тыс": " k",
              "bn": " bn", "billion": " bn", "млрд": " bn"}.get(str(o.get("scale") or "").lower(), "")
        lo, hi = PR.bounds(o)
        cur = str(o.get("currency") or "USD")
        value = f"{esc(cur)} {pnum(lo)}" + (f"–{pnum(hi)}" if PR.is_range(o) else "") + sc
        value = f'<span class="price-value k-{esc(o["kind"])}">{value}</span>'
        context = ""
        if PR.is_range(o):
            value += (f'<span class=price-mid>{esc(t["ts_midpoint"])}: '
                      f'{esc(cur)} {pnum(PR.midpoint(o), (lo, hi))}{sc}</span>')
            if o["kind"] == "lease":
                calc = f"/{lang}/calc?ac={quote(icao)}&lease_observation={quote(PR.observation_id(o))}"
                value += f'<a class=price-use href="{esc(calc)}">{esc(t["ts_use_midpoint"])}</a>'
            if o.get("note") or o.get("quote"):
                context = f'<details class=price-source><summary>{esc(t["ts_source_context"])}</summary>'
                if o.get("note"):
                    context += f'<p>{esc(o["note"])}</p>'
                if o.get("quote"):
                    context += f'<blockquote>{esc(o["quote"])}</blockquote>'
                context += "</details>"
        body.append(f"<tr><td>{esc(str(o['month']))}</td><td>{kind_label(o['kind'])}</td>"
                    f"<td class=r>{value}</td><td class=r>{esc(age_label(o))}</td>"
                    f'<td class=s><a href="{esc(o["source"])}" rel="nofollow">{esc(publisher(o))}</a>{context}</td></tr>')
    body.append("</table></div>")
    return "".join(body)


# 3D is opt-in and intentionally not part of the existing economics UI.
# This widget doesn't change the original edit form, canonical or JSON-LD.
FC3D_TEXT = {
    "ru": {"rotate": "Вращать в 3D", "close_preview": "Закрыть 3D", "seats": "мест", "loading": "Загрузка 3D…",
           "preview_failed": "Не удалось открыть 3D", "operational": "эксплуатационный", "factory": "заводской",
           "back": "Вернуться к карточке во FlightCost", "apply": "Выбрать", "switch_note": "При смене компоновки несохранённые изменения пропадут.", "need_js": "Для 3D-конструктора нужен JavaScript.", "heading": "Посмотреть и изменить самолёт в 3D",
           "lead": "Откройте Aircraft Designer и сохраните результат как отдельный свой тип. Данные модели предварительные, не сертификационные.",
           "layout": "Салон и двигатель 3D", "open": "Открыть в 3D · Aircraft Designer",
           "create": "Создать рабочее место для сохранения", "workspace": "Моё рабочее место",
           "created": "Рабочее место создано. Сохраните секретную ссылку:",
           "need": "Для сохранения сначала создайте рабочее место FlightCost.",
           "saving": "Сохраняем модель в FlightCost…", "saved": "Сохранено как",
           "calc": "Открыть расчёт маршрута", "caveat": "Без подтверждённой топливной модели расчёт может быть недоступен.",
           "different": "Важно: двигатель 3D ({designer}) отличается от двигателя в карточке FlightCost ({flightcost}). Топливная модель не переносится автоматически.",
           "error": "Ошибка: "},
    "en": {"rotate": "Rotate in 3D", "close_preview": "Close 3D", "seats": "seats", "loading": "Loading 3D…",
           "preview_failed": "Could not load 3D", "operational": "operational", "factory": "factory",
           "back": "Back to aircraft on FlightCost", "apply": "Apply", "switch_note": "Changing the configuration discards unsaved edits.", "need_js": "JavaScript is required for the 3D designer.", "heading": "Explore and modify the aircraft in 3D",
           "lead": "Open Aircraft Designer and save as a separate custom aircraft. Engineering values are provisional, not certified.",
           "layout": "3D cabin and engine", "open": "Open in 3D · Aircraft Designer",
           "create": "Create a workspace to save", "workspace": "My workspace",
           "created": "Workspace created. Keep this secret link:",
           "need": "Create a FlightCost workspace before saving.",
           "saving": "Saving the design to FlightCost…", "saved": "Saved as",
           "calc": "Open route calculation", "caveat": "Without a validated fuel model, a route calculation may be unavailable.",
           "different": "Important: 3D engine ({designer}) differs from the FlightCost card engine ({flightcost}). Fuel model is not copied automatically.",
           "error": "Error: "},
    "de": {"rotate": "In 3D drehen", "close_preview": "3D schließen", "seats": "Sitze", "loading": "3D wird geladen…",
           "preview_failed": "3D konnte nicht geladen werden", "operational": "Betriebsprofil", "factory": "Werksprofil",
           "back": "Zurück zum Flugzeug bei FlightCost", "apply": "Auswählen", "switch_note": "Beim Wechsel der Konfiguration gehen ungespeicherte Änderungen verloren.", "need_js": "Für den 3D-Konfigurator ist JavaScript erforderlich.", "heading": "Flugzeug in 3D ansehen und ändern",
           "lead": "Aircraft Designer öffnen und als eigenen Typ speichern. Die Konstruktionswerte sind vorläufig, nicht zertifiziert.",
           "layout": "3D-Kabine und Triebwerk", "open": "In 3D öffnen · Aircraft Designer",
           "create": "Arbeitsbereich zum Speichern erstellen", "workspace": "Mein Arbeitsbereich",
           "created": "Arbeitsbereich erstellt. Geheimen Link sichern:",
           "need": "Vor dem Speichern einen FlightCost-Arbeitsbereich erstellen.",
           "saving": "Entwurf in FlightCost speichern…", "saved": "Gespeichert als",
           "calc": "Streckenberechnung öffnen", "caveat": "Ohne bestätigtes Verbrauchsmodell ist eine Streckenberechnung möglicherweise nicht verfügbar.",
           "different": "Wichtig: Das 3D-Triebwerk ({designer}) unterscheidet sich vom FlightCost-Triebwerk ({flightcost}). Das Verbrauchsmodell wird nicht automatisch übernommen.",
           "error": "Fehler: "},
}


def designer_choices(icao: str, info: dict) -> tuple[list[dict], int, str]:
    """One deterministic selection rule for the type card and separate 3D page."""
    from . import aircraft_designer as ad
    options = ad.choices(icao)
    if not options:
        return [], 0, ""
    by = {f["field"]: f for f in info.get("fields", [])}
    ref_engine = (by.get("engine") or {}).get("text") or ""
    typical = (by.get("seats_typical") or {}).get("value") or (by.get("seats_max") or {}).get("value")

    def priority(c):
        return (0 if typical is not None and c["seats"] == typical else 1,
                0 if ad.engine_matches(c["engine"], ref_engine) else 1,
                0 if c["default"] else 1)
    chosen = min(range(len(options)), key=lambda i: priority(options[i]))
    return options, chosen, ref_engine


def _designer_label(c: dict) -> str:
    label = f'{c["seats"]} · {c["engine"]} · {c["aircraftId"]}'
    return label + (" · factory" if c["weightProfile"] == "factory" else "")


def _designer_options(choices: list[dict], selected: int) -> str:
    return "".join(f'<option value="{i}"{" selected" if i == selected else ""}>'
                   f'{esc(_designer_label(c))}</option>'
                   for i, c in enumerate(choices))


def designer_widget(lang: str, icao: str, info: dict, cls: str, designer_origin: str | None = None) -> str:
    """Type-card preview. The full editor remains a normal GET navigation."""
    choices, selected, _ = designer_choices(icao, info)
    if not choices:
        return ""
    t = FC3D_TEXT[lang]
    href = f"/{lang}/type/{quote(icao)}/3d"
    origin = designer_origin or "https://aircraft-designer.app"
    options = []
    for i, c in enumerate(choices):
        poster = f'/aircraft-previews/{c["aircraftId"]}--{c["layoutId"]}.webp'
        query = urlencode({"view": "aircraft-preview", "ac": icao, "aircraft": c["aircraftId"],
                           "engine": c["engine"], "layout": c["layoutId"], "profile": c["weightProfile"]})
        seats = c["seats"]
        unit = t["seats"]
        if lang == "ru" and not 11 <= seats % 100 <= 14:
            if seats % 10 == 1:
                unit = "место"
            elif 2 <= seats % 10 <= 4:
                unit = "места"
        caption = f'{seats} {unit} · {c["engine"]}'
        if c["weightProfile"] in ("operational", "factory"):
            caption += " · " + t[c["weightProfile"]]
        options.append(f'<option value="{i}"{" selected" if i == selected else ""} '
                       f'data-poster="{esc(poster)}" data-view="{esc(origin + "/?" + query)}" '
                       f'data-caption="{esc(caption)}">{esc(_designer_label(c))}</option>')
        if i == selected:
            initial_poster, initial_caption = poster, caption
    return (f'<section class="ed fc3d" id="fc3d"><div class="fc3d-copy"><h3>{esc(t["heading"])}</h3>'
            f'<p class="dim">{esc(t["lead"])}</p>'
            f'<form action="{esc(href)}" method="get">'
            f'<label for="fc3d-choice">{esc(t["layout"])}</label>'
            f'<select id="fc3d-choice" name="choice">{"".join(options)}</select>'
            f'<button class="fc3d-cta" type="submit">{esc(t["open"])}</button></form></div>'
            f'<figure class="fc3d-preview" data-rotate="{esc(t["rotate"])}" data-close="{esc(t["close_preview"])}" '
            f'data-loading="{esc(t["loading"])}" data-failed="{esc(t["preview_failed"])}">'
            f'<div class="fc3d-stage"><img src="{esc(initial_poster)}" width="840" height="412" '
            f'loading="lazy" decoding="async" alt=""></div>'
            f'<figcaption>{esc(initial_caption)}</figcaption>'
            f'<button class="fc3d-orbit" type="button" hidden>{esc(t["rotate"])}</button>'
            '<span role="status" class="fc3d-preview-status"></span></figure></section>'
            '<script src="/aircraft-preview.js" defer></script>')


def designer_page(lang: str, icao: str, info: dict, entry: dict, cls: str,
                  selected: int, route_nm: float | None = None, designer_origin: str | None = None) -> str:
    """Full-height, single-purpose FlightCost page for the external 3D designer.

    The FlightCost origin stays top-level so its guest-workspace cookie and
    server-side save remain first-party. The actual 3D engine is a cross-origin
    iframe with the existing origin/source-validated postMessage contract.
    """
    choices, _, ref_engine = designer_choices(icao, info)
    if not choices or not 0 <= selected < len(choices):
        raise ValueError("Unsupported 3D selection")
    c = choices[selected]
    t = FC3D_TEXT[lang]
    back = type_url(lang, icao)
    name = name_of(entry, lang) or icao
    cfg = json.dumps({"icao": icao, "lang": lang, "refEngine": ref_engine,
                      "backHref": back, "route": ROUTES[cls], "routeNm": route_nm, "choices": choices,
                      "selected": selected, "designerOrigin": designer_origin, "text": t},
                     ensure_ascii=True).replace("</", "<\\/")
    options = _designer_options(choices, selected)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{esc(name)} · 3D · FlightCost</title>
<link rel="stylesheet" href="/ui.css">
<style>
html,body{{margin:0;min-height:100%;background:var(--bg);color:var(--ink);font:14px/1.4 var(--sans)}}
.fc3d-full{{height:100vh;height:100dvh;min-height:420px;display:flex;flex-direction:column}}
.fc3d-top{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px 20px;
  border-bottom:1px solid var(--line);padding:10px 16px;background:var(--panel)}}
.fc3d-top a,.fc3d-foot a{{color:var(--accent)}}
.fc3d-title{{font-weight:600;font-size:17px;margin:0;color:var(--ink2)}}
.fc3d-sub{{color:var(--dim);font-size:12px;margin:2px 0 0}}
.fc3d-choose{{display:flex;align-items:end;flex-wrap:wrap;gap:8px}}
.fc3d-choose label{{display:flex;flex-direction:column;gap:4px;color:var(--dim);font-size:12px}}
.fc3d-choose select,.fc3d-choose button,.fc3d-foot button{{background:var(--raise);color:var(--ink);
  border:1px solid var(--line);border-radius:6px;padding:7px 10px;font:14px var(--sans)}}
.fc3d-choose select{{max-width:min(80vw,360px)}}
.fc3d-choose button,.fc3d-foot button{{cursor:pointer}}
.fc3d-choose :focus-visible,.fc3d-foot a:focus-visible{{outline:2px solid var(--accent);outline-offset:3px}}
.fc3d-view{{flex:1;min-height:220px;display:flex;flex-direction:column;background:var(--bg)}}
#fc3d-mount{{flex:1;min-height:220px;display:flex}}
#fc3d-mount iframe{{display:block;flex:1;width:100%;height:100%;border:0;background:var(--panel)}}
.fc3d-foot{{border-top:1px solid var(--line);padding:9px 16px;background:var(--panel);
  max-height:26vh;overflow:auto}}
.fc3d-foot p{{margin:4px 0}}.fc3d-foot .fc3d-help{{color:var(--dim);font-size:12px}}
.fc3d-foot #fc3d-engine-note{{color:var(--warn)}}
.fc3d-foot [hidden]{{display:none!important}}
.fc3d-foot a{{overflow-wrap:anywhere}}.fc3d-links{{display:flex;flex-wrap:wrap;gap:6px 16px}}
@media(max-width:640px){{.fc3d-top{{padding:8px 12px;align-items:flex-start}}
  .fc3d-title{{font-size:15px}}.fc3d-choose{{width:100%}}.fc3d-choose label{{flex:1;min-width:0}}
  .fc3d-choose select{{max-width:100%;width:100%;box-sizing:border-box}}.fc3d-foot{{padding:7px 12px}}}}
</style></head><body>
<div class="fc3d-full">
  <header class="fc3d-top">
    <div><a id="fc3d-back" href="{esc(back)}">← {esc(t['back'])}</a>
      <h1 class="fc3d-title">{esc(name)} · 3D</h1>
      <p class="fc3d-sub">FlightCost × Aircraft Designer · {esc(c['engine'])} · {esc(c['seats'])}</p></div>
    <form action="{esc(back)}/3d" method="get" class="fc3d-choose">
      <label for="fc3d-choice">{esc(t['layout'])}
        <select id="fc3d-choice" name="choice">{options}</select></label>
      <button type="submit">{esc(t['apply'])}</button>
    </form>
  </header>
  <main class="fc3d-view" id="fc3d-mount">
    <noscript>{esc(t['need_js'])}</noscript>
  </main>
  <aside class="fc3d-foot">
    <p id="fc3d-engine-note" class="fc3d-help"></p>
    <p class="fc3d-help">{esc(t['lead'])} {esc(t['switch_note'])}</p>
    <button id="fc3d-create" type="button" hidden>{esc(t['create'])}</button>
    <p id="fc3d-message" role="status" aria-live="polite"></p>
    <p class="fc3d-links" id="fc3d-workspace"></p>
    <p class="fc3d-links" id="fc3d-links"></p>
  </aside>
</div>
<script type="application/json" id="fc3d-data">{cfg}</script>
<script src="/flightcost-embed.nomodule.js" defer></script>
<script src="/flightcost-aircraft-designer.js" defer></script>
</body></html>"""


# ── свой вариант типа со страницы типа (решение 231) ─────────────────────
# Форма — над заготовкой `/api/aircraft/draft`: копия со всеми полями и
# расходом (тот же двигатель или аналог с якорем исходного типа). На
# странице правится то, что обычно у перевозчика иначе; остальное едет как
# есть. Сохранение — `/api/aircraft/save` в рабочее место; места нет —
# создаётся одной кнопкой и ссылка на него показывается.
ED_FIELDS = (("seats_max", "ed_seats_max", "1"), ("seats_typical", "ed_seats_typical", "1"),
             ("mtow_t", "ed_mtow", "0.1"), ("oew_t", "ed_oew", "0.1"), ("mlw_t", "ed_mlw", "0.1"),
             ("fuel_capacity_t", "ed_fuel", "0.1"))
ED_RATES = (("lease_eur_month", "ed_lease", "1000"), ("monthly_hours", "ed_hours", "10"),
            ("maint_eur_per_fh", "ed_mfh", "10"), ("maint_eur_per_fc", "ed_mfc", "10"),
            ("crew_eur_per_fh", "ed_cfh", "10"), ("crew_eur_per_fc", "ed_cfc", "10"))
ED_STYLE = """<style>
.ed{border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:14px 0;background:var(--panel)}
.ed[hidden]{display:none}.ed h3{margin:0 0 6px;font-size:16px;color:var(--ink2)}
.ed .g{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px 14px;margin:10px 0}
.ed label{display:flex;flex-direction:column;gap:3px;font-size:12.5px;color:var(--dim)}
.ed input{background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:5px;padding:7px 9px;
  font:14px var(--sans);font-variant-numeric:tabular-nums}
.ed input:focus{border-color:var(--accent);outline:0}.ed input::placeholder{color:var(--faint)}
.ed .sub{font-size:12.5px;color:var(--dim);margin:14px 0 0}
.ed .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.ed button{background:var(--raise);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:8px 14px;
  font:14px var(--sans);cursor:pointer}.ed button.pri{border-color:var(--accent);font-weight:600}
.ed .msg{margin-top:10px;font-size:13.5px}.ed .msg.bad{color:var(--warn)}
.ed .key{font:12.5px var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:5px 8px;
  word-break:break-all;user-select:all;display:block;margin:6px 0}
button.cta{background:none;cursor:pointer;font:inherit;font-weight:600;margin-left:8px}
</style>"""


def type_editor(lang: str, icao: str, cls: str, fd: dict) -> str:
    """Кнопка «Изменить и сохранить свой вариант» и форма под ней."""
    t = T[lang]

    def inp(k, lab, step, ph=""):
        return (f'<label>{esc(t[lab])}<input data-k="{k}" type="number" step="{step}" min="0"'
                f'{f" placeholder={chr(34)}{ph}{chr(34)}" if ph != "" else ""}></label>')
    fields = "".join(inp("f." + k, lab, st) for k, lab, st in ED_FIELDS)
    rates = "".join(inp("r." + k, lab, st, "" if fd.get(k) is None else round(fd[k]))
                    for k, lab, st in ED_RATES)
    o, d = ROUTES[cls]
    txt = {k: t[k] for k in ("ed_saved", "ed_link", "ed_calc", "ed_net", "ed_fail", "ed_need_ws", "ed_seats_err",
                             "ed_make_ws", "ed_burn_same", "ed_burn_anchor")}
    # Подписи источника своего типа — данные, а не интерфейс: они пишутся
    # в факты по-русски, как у файлов каталога. В странице — экранированными
    # (ensure_ascii), чтобы английская и немецкая страница не несли кириллицу.
    src = {"source": "копия {icao} со страницы типа: {why}", "url": "собственное допущение",
           "publisher": "автор рабочего места"}
    cfg = json.dumps({"icao": icao, "lang": lang, "o": o, "d": d, "t": txt, "src": src},
                     ensure_ascii=True).replace("</", "<\\/")
    return (ED_STYLE
            + f'<button class="cta" id="edopen" type="button">{esc(t["ed_btn"])}</button>'
            f'<form class="ed" id="ed" hidden onsubmit="return false">'
            f'<h3>{esc(t["ed_h"].format(icao=icao))}</h3><p class="dim">{esc(t["ed_lead"])}</p>'
            f'<div class="g"><label>{esc(t["ed_key"])}<input data-k="icao" type="text"></label>'
            f'<label>{esc(t["ed_name"])}<input data-k="name" type="text"></label>'
            f'<label>{esc(t["ed_engine"])}<input data-k="engine" type="text"></label></div>'
            f'<div class="g">{fields}</div><p class="sub">{esc(t["ed_rates"])}</p><div class="g">{rates}</div>'
            f'<p class="sub" id="edburn"></p>'
            f'<div class="g"><label style="grid-column:1/-1">{esc(t["ed_src"])}<input data-k="why" type="text" '
            f'placeholder="{esc(t["ed_src_ph"])}"></label></div>'
            f'<div class="btns"><button class="pri" id="edsave" type="button">{esc(t["ed_save"])}</button>'
            f'<button id="edcancel" type="button">{esc(t["ed_cancel"])}</button></div>'
            f'<p class="dim">{esc(t["ed_suggest"])}</p><div class="msg" id="edmsg"></div></form>'
            f'<script type="application/json" id="edcfg">{cfg}</script>'
            f'<script>{ED_JS}</script>')


ED_JS = r"""(function(){
var C=JSON.parse(document.getElementById('edcfg').textContent),T=C.t,F=document.getElementById('ed'),D=null;
function $(k){return F.querySelector('[data-k="'+k+'"]')}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function msg(h,bad){var m=document.getElementById('edmsg');m.className='msg'+(bad?' bad':'');m.innerHTML=h}
document.getElementById('edopen').onclick=async function(){
  if(!D){D=await (await fetch('/api/aircraft/draft?icao='+encodeURIComponent(C.icao))).json();
    if(D.error){F.hidden=false;msg(esc(T.ed_fail)+' '+esc(D.error),1);return}
    $('icao').value=D.icao;$('name').value=D.name||'';$('engine').value=D.engine||'';
    F.querySelectorAll('[data-k^="f."]').forEach(function(e){var v=(D.fields||{})[e.dataset.k.slice(2)];e.value=v==null?'':v});
    F.querySelectorAll('[data-k^="r."]').forEach(function(e){var v=(D.fleet||{})[e.dataset.k.slice(2)];e.value=v==null?'':Math.round(v)});
    var b=D.burn;document.getElementById('edburn').textContent=b?(b.same_engine?T.ed_burn_same:T.ed_burn_anchor)
      .replace('{analog}',b.analog||C.icao).replace('{icao}',C.icao):'';}
  F.hidden=false;this.hidden=true;$('why').focus()};
document.getElementById('edcancel').onclick=function(){F.hidden=true;document.getElementById('edopen').hidden=false};
async function save(){
  var doc=JSON.parse(JSON.stringify(D)),why=$('why').value.trim();
  if(!why){$('why').focus();msg(esc(T.ed_fail)+' '+esc($('why').closest('label').firstChild.textContent),1);return}
  var sm=+$('f.seats_max').value,st=+$('f.seats_typical').value;
  if(sm&&st&&st>sm){$('f.seats_typical').focus();msg(esc(T.ed_fail)+' '+esc(T.ed_seats_err),1);return}
  doc.icao=$('icao').value.trim().toUpperCase();if(doc.icao.indexOf('USER:')!==0)doc.icao='USER:'+doc.icao;
  doc.name=$('name').value.trim()||doc.name;doc.engine=$('engine').value.trim();
  doc.fields=doc.fields||{};F.querySelectorAll('[data-k^="f."]').forEach(function(e){var k=e.dataset.k.slice(2);
    if(e.value==='')delete doc.fields[k];else doc.fields[k]=+e.value});
  var fl={};F.querySelectorAll('[data-k^="r."]').forEach(function(e){if(e.value!=='')fl[e.dataset.k.slice(2)]=+e.value});
  if(Object.keys(fl).length){doc.fleet=fl;doc.fleet_source=why}else{delete doc.fleet;delete doc.fleet_source}
  doc.source=C.src.source.replace('{icao}',C.icao).replace('{why}',why);doc.source_url=C.src.url;
  doc.publisher=C.src.publisher;
  var r=await (await fetch('/api/aircraft/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(doc)})).json();
  if(r.need_workspace){msg(esc(T.ed_need_ws)+' <button type="button" id="edws" class="pri">'+esc(T.ed_make_ws)+'</button>',0);
    document.getElementById('edws').onclick=async function(){
      var w=await (await fetch('/api/ws/new',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
      if(w.error){msg(esc(T.ed_fail)+' '+esc(w.error),1);return}
      C.wskey=w.key;save()};return}
  if(r.error){msg(esc(T.ed_fail)+' '+esc(r.error),1);return}
  var q='/'+C.lang+'/calc?o='+C.o+'&d='+C.d+'&ac='+encodeURIComponent(r.icao);
  var n='/'+C.lang+'/calc?o='+C.o+'&d='+C.d+'&ac='+encodeURIComponent(C.icao)+'&net=1&cmp='+encodeURIComponent(r.icao);
  msg(esc(T.ed_saved.replace('{key}',r.icao))+(C.wskey?'<br>'+esc(T.ed_link)+'<span class="key">'+esc(location.origin+'/w/'+C.wskey)+'</span>':'')
    +'<br><a href="'+q+'">'+esc(T.ed_calc)+'</a> · <a href="'+n+'">'+esc(T.ed_net.replace('{icao}',C.icao))+'</a>',0)}
document.getElementById('edsave').onclick=save;
})();"""


# ── служебные файлы ────────────────────────────────────────────────────────

def robots() -> str:
    return (f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /w\nDisallow: /report\n\n"
            f"Sitemap: {site()}/sitemap.xml\n")


def _research_tails() -> list[str]:
    from .research import items
    return [f"/research/{x['slug']}" for x in items()]


def sitemap(types: list[dict]) -> str:
    """Все адреса с языковыми парами (xhtml:link) — так Google связывает версии."""
    tails = (["/", "/calc", "/about", "/types", "/research", "/monitor"] + _research_tails()
             + [f"/type/{quote(x['icao'])}" for x in public_types(types)])
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for tail in tails:
        alts = alternates(tail)
        for lg in LANGS:
            out.append(f"<url><loc>{esc(site())}/{lg}{esc(tail)}</loc>"
                       + "".join(f'<xhtml:link rel="alternate" hreflang="{h}" href="{esc(u)}"/>' for h, u in alts)
                       + "</url>")
    for p in ("/data", "/map"):  # «/» не нужен: его canonical — языковая главная
        out.append(f"<url><loc>{esc(site())}{p}</loc></url>")
    out.append("</urlset>")
    return "\n".join(out)


def urls(types: list[dict]) -> list[str]:
    """Все адреса сайта для IndexNow."""
    tails = (["/", "/calc", "/about", "/types", "/research", "/monitor"] + _research_tails()
             + [f"/type/{quote(x['icao'])}" for x in public_types(types)])
    return [f"{site()}/{lg}{tl}" for tl in tails for lg in LANGS] + [site() + p for p in ("/data", "/map")]


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

- [Calculator (English)]({site()}/en/calc): pick origin, destination, aircraft type and load factor. Parameters can be
  passed in the URL: `{site()}/en/calc?o=EDDF&d=LEBL&ac=A320` (ICAO airport codes, ICAO aircraft type designator).
- [Rechner (Deutsch)]({site()}/de/calc), [Калькулятор (русский)]({site()}/ru/calc)
- [Home]({site()}/en/): what the service is and where to start.
- [About and methodology]({site()}/en/about): what is calculated, data sources, how far to trust the numbers.
- [Aircraft types]({site()}/en/types): specifications with sources, a top-view drawing, the calculator's default
  lease, maintenance and crew rates, and the cost of a flight on a typical route from Frankfurt (Vienna, Barcelona
  or Beijing by class) for each type, e.g. [Airbus A320]({site()}/en/type/A320).
- [Research]({site()}/en/research): what we found while collecting the data — e.g. how fast aircraft maintenance
  costs grow against inflation, engine makers' aftermarket economics and maintenance rates by type; every number
  with a source and a verified quote (reports in Russian).
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
