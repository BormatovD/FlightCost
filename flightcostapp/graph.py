"""Карта архитектуры данных.

Отвечает на вопрос «откуда взялось это число» кликом, а не чтением кода.

Связи именованные: ребро несёт не просто «зависит от», а конкретное поле
с единицей измерения. Разница существенная — ТОиР зависит от типа ВС, но
берёт оттуда ровно одну ставку из семи, и без этого узел «Тип ВС»
выглядит чёрным ящиком, из которого что-то приходит.

Заодно это проект будущего фронта. Роль узла определяет элемент
интерфейса, а список полей узла — схему формы:
  input   — поле ввода или ползунок
  fleet   — выпадающий список типов ВС
  store   — таблица справочника, редактируется через ревью, не напрямую
  derived — только чтение, пересчитывается

Граф описан декларативно, но `check_against_trace` сверяет его с
трассировкой живого расчёта: добавишь шаг в econ.py, забудешь про карту —
проверка это покажет.
"""

from __future__ import annotations

import html
import json
from datetime import date


def n(id, layer, label, unit, role, formula="", inputs=(), fields=(),
      emits="", note=""):
    """inputs: (id_источника, что_берётся, единица)
       fields: (имя_поля, единица, пояснение)"""
    return {"id": id, "layer": layer, "label": label, "unit": unit,
            "role": role, "formula": formula,
            "inputs": [{"id": a, "take": b, "unit": c} for a, b, c in inputs],
            "fields": [{"name": a, "unit": b, "note": c} for a, b, c in fields],
            "emits": emits or label, "note": note}


N = [
    # ---------- слой 0: внешние источники ----------
    n("src_oa", 0, "OurAirports", "CSV", "source",
      fields=[("airports.csv", "~48 тыс. строк", "фильтруются три типа аэропортов")],
      emits="координаты и коды",
      note="Машиночитаемый фид, детерминированный парсер, авто-приём. "
           "Проверка раз в 30 дней, SLA 180 дней."),
    n("src_crco", 0, "CRCO en-route", "PDF", "source",
      fields=[("ставка государства", "EUR/SU", "две цифры после запятой"),
              ("дата вступления", "дата", "обычно 1 января"),
              ("валюта", "код", "не-евро страны пересчитываются ежемесячно")],
      emits="ставки по государствам",
      note="Циркуляры по шаблону <префикс ИКАО>-<год>-<месяц>.pdf. "
           "Агентный контур: извлекает LLM, принимает человек."),
    n("src_term", 0, "Терминальные ставки", "PDF", "source",
      fields=[("ставка зоны TCZ", "нац. валюта / SU", "26 зон, годовая публикация"),
              ("число аэродромов", "шт", "всего 189 в схеме SES RP4")],
      emits="ставки терминальных зон",
      note="Текст PDF извлекается чисто, строк 26 — парсер детерминированный. "
           "А вот распределение аэродромов по зонам ведётся вручную: в "
           "приложении порядок строк при извлечении разъезжается."),
    n("src_aip", 0, "AIP GEN 4.1", "PDF", "source",
      fields=[("адреса тарифных страниц", "URL", "Италия 35, Германия 28"),
              ("общегосударственные статьи", "EUR/пасс", "надбавки, "
               "установленные законом, а не оператором"),
              ("перечень отмен", "интервал", "региональные, точечные по "
               "аэропортам")],
      emits="указатель источников и государственные статьи",
      note="Не источник операторских тарифов, а указатель на них — и "
           "единственное место, где публикуется перечень региональных "
           "отмен надбавки. Издатель государство, ритм годовой, правки "
           "приходят бюджетным законом в декабре."),

    n("src_airport_tariff", 0, "Тарифы операторов", "PDF/XLS", "source",
      fields=[("посадочный тариф", "EUR/т", ""),
              ("пассажирский сбор", "EUR/пасс", ""),
              ("стоянка, шум, эмиссия, security", "EUR", "разобраны частично")],
      emits="аэропортовые тарифы",
      note="Формат у каждого оператора свой, скидки и incentive-схемы не "
           "публикуются вовсе. Ярус 1 — ручная курация, около 40 аэропортов. "
           "Доставка бывает ручной (.xls Тираны) — это свойство экземпляра, "
           "а не отдельный вид источника."),

    n("src_fir", 0, "Границы FIR/UIR", "SHP", "source",
      fields=[("AV_ICAO_ST", "код", "префикс государства"),
              ("MIN/MAX_FLIGHT", "эшелон", "вертикальные границы")],
      emits="151 полигон",
      note="Шейпфайл Network Manager EUROCONTROL, лицензия MIT: границы "
           "приходят оттуда же, откуда счета по ним. Данные 2015 года — "
           "для устоявшихся европейских границ приемлемо."),
    n("src_fuel", 0, "Цена керосина", "HTML", "source",
      fields=[("котировка", "USD/барр", "недельный монитор IATA")],
      emits="цена топлива",
      note="Одно число, жёсткие валидаторы, авто-приём. SLA 45 дней."),

    # ---------- слой 1: домены справочника ----------
    n("d_airport", 1, "airport", "запись", "store",
      inputs=[("src_oa", "координаты, коды", "—")],
      fields=[("lat", "°", "широта WGS84"), ("lon", "°", "долгота WGS84"),
              ("icao", "код", "четырёхбуквенный"),
              ("iso_country", "код", "определяет ставку en-route"),
              ("name", "текст", "")],
      emits="запись аэропорта",
      note="Ключ — код ИАТА. Значения действуют интервалами: запрос всегда "
           "на дату, поэтому прошлый расчёт воспроизводится."),
    n("d_rate", 1, "enroute_rate", "EUR/SU", "store",
      inputs=[("src_crco", "ставка государства", "EUR/SU")],
      fields=[("value", "EUR/SU", "средняя по системе около 33, разброс троекратный"),
              ("valid_from", "дата", ""), ("currency", "код", "")],
      emits="ставка государства",
      note="Ключ — код государства ISO."),
    n("d_charge", 1, "airport_charge", "EUR", "store",
      inputs=[("src_airport_tariff", "тарифы оператора", "EUR"),
              ("src_aip", "государственные статьи", "EUR/пасс")],
      fields=[("<icao>/landing_per_t", "EUR/т", "посадка, умножается на MTOW"),
              ("<icao>/pax", "EUR/пасс", "пассажирский сбор"),
              ("<icao>/parking", "EUR/ч", "ещё не заведён"),
              ("<icao>/noise", "EUR", "ещё не заведён")],
      emits="тарифы аэропорта",
      note="Пусто — включается параметрика яруса 3 с пометкой «оценка»."),
    n("d_terminal", 1, "terminal_rate", "нац. валюта", "store",
      inputs=[("src_term", "ставка зоны", "нац. валюта/SU")],
      fields=[("value", "нац. валюта/SU", "Испания 25.78, Германия 365.18 — разница в 14 раз"),
              ("currency", "код", "пересчёт через домен fx при расчёте")],
      emits="ставка зоны",
      note="Ключ — название зоны TCZ. Связь аэродрома с зоной живёт в "
           "config/tcz.yaml, ярус 1."),
    n("d_fx", 1, "fx", "за EUR", "store",
      inputs=[("src_crco", "курсы, применённые CRCO", "нац. валюта/EUR")],
      fields=[("<код валюты>", "за 1 EUR", "тот же курс, что в счёте CRCO")],
      emits="курс валюты",
      note="Приезжает попутно с en-route ставками: те же курсы, которыми "
           "CRCO пересчитывает свои счета. Для сборов точнее биржевых."),
    n("d_airspace", 1, "Границы зон", "GeoJSON", "store",
      inputs=[("src_fir", "полигоны FIR и UIR", "—")],
      fields=[("zone", "код", "двухбуквенный префикс ИКАО, тот же ключ что у ставок"),
              ("fl_min, fl_max", "эшелон", "разделение FIR и UIR по высоте"),
              ("geometry", "полигон", "упрощён до 0.02°, около мили")],
      emits="полигоны зон",
      note="Геометрия не кладётся в факты: хранилище рассчитано на скаляры "
           "с интервалами действия, проверки гейта к полигону неприменимы."),
    n("d_fuelp", 1, "fuel_price", "USD/барр", "store",
      inputs=[("src_fuel", "котировка", "USD/барр")],
      fields=[("jet_global", "USD/барр", "одно значение на весь мир")],
      emits="котировка",
      note="Региональная разбивка — задел на будущее."),

    # ---------- слой 2: ввод пользователя ----------
    n("i_route", 2, "Маршрут", "два кода", "input",
      formula="--origin / --destination",
      fields=[("origin", "код ИАТА", ""), ("destination", "код ИАТА", "")],
      emits="пара кодов",
      note="Во фронте — два поля с автодополнением по справочнику airport."),
    n("d_fleet", 1, "fleet_economics", "EUR", "store",
      fields=[("lease_eur_month", "EUR/мес", "ставка лизинга, самая закрытая величина"),
              ("monthly_hours", "ч/мес", "месячный налёт борта; в режиме dedicated из частоты"),
              ("maint_eur_per_fh", "EUR/ч", "восстановление двигателей, тяжёлые формы"),
              ("maint_eur_per_fc", "EUR/рейс", "шасси, ВСУ, ресурсные детали, линейное"),
              ("crew_eur_per_fh", "EUR/ч", "оплата по блок-времени"),
              ("crew_eur_per_fc", "EUR/рейс", "брифинг, пред- и послеполётная работа")],
      emits="ставки эксплуатации",
      note="Ключ «перевозчик/тип» с запасным «*/тип». Публичных данных нет: "
           "по умолчанию параметрическая заготовка от массы и кресел, "
           "пользователь подставляет свои."),
    n("v_util", 3, "Налёт", "ч/мес", "input",
      formula="типовой по флоту, из частоты рейсов, или борт уже оплачен",
      inputs=[("d_fleet", "monthly_hours", "ч/мес")], emits="месячный налёт",
      note="Владение платится за месяц, а не за час. Доля месячного платежа, "
           "приходящаяся на рейс, определяется налётом борта — вот почему "
           "единицей расчёта стал маршрут с частотой. По-русски именно "
           "«налёт»: «утилизация» означает списание техники."),
    n("v_maint_rate", 3, "Ставки ТОиР", "EUR", "derived",
      formula="почасовая и поцикловая части",
      inputs=[("d_fleet", "maint_eur_per_fh и per_fc", "EUR/ч, EUR/рейс")],
      emits="две ставки",
      note="Цикловые статьи не зависят от длительности рейса: часовой и "
           "шестичасовой изнашивают шасси одинаково. Плоская ставка за час "
           "занижает короткие плечи на 90%."),
    n("d_limits", 1, "airport_limits", "м", "store",
      inputs=[("src_oa", "runways.csv", "—")],
      fields=[("<icao>/runway_length_m", "м", "самая длинная действующая полоса"),
              ("<icao>/runway_width_m", "м", ""),
              ("<icao>/runway_surface", "текст", "покрытие")],
      emits="ограничения аэродрома",
      note="Источник тот же, что для координат, и уже качался. До этого "
           "модель считала экономику A388 в аэропорт с полосой в полтора "
           "километра и ничего не замечала."),
    n("v_rwy", 3, "Потребная полоса", "м", "default",
      formula="привязка к массе по опорным точкам",
      inputs=[("v_mtow", "mtow_t", "т"), ("d_limits", "длина полосы", "м")],
      emits="запас по полосе",
      note="ОЦЕНКА, не расчёт характеристик: он требует тяги, площади "
           "крыла, температуры и превышения. Задача — отсеять невозможное, "
           "а не заменить лётный расчёт."),
    n("d_layout", 1, "aircraft_layout", "кресел", "store",
      fields=[("<перевозчик>/<тип>", "шт", "публикуемая компоновка салона"),
              ("типовая из openap", "шт", "когда перевозчик не указан")],
      emits="число кресел",
      note="Кресла — не свойство типа, а решение перевозчика: у A320 бывает "
           "от 150 до 186, и разница в четверть входит прямо в себестоимость "
           "кресла. Ведётся в config/layouts.yaml."),
    n("v_feas", 3, "Выполнимость", "да/нет", "derived",
      formula="OEW + нагрузка + топливо + резерв ≤ MTOW; топливо ≤ ёмкость",
      inputs=[("v_fuel", "масса топлива", "кг"), ("i_ac", "mtow_t, oew_t", "т")],
      emits="признак и предельная нагрузка",
      note="До этой проверки расчёт FRA–SIN на A320 давал уверенную "
           "себестоимость при перегрузе в двадцать тонн: усечение массы "
           "происходило молча. Теперь модель отвечает «нельзя» и говорит, "
           "сколько пассажиров поднимет на это плечо."),
    n("i_ac", 2, "Тип ВС", "код ИКАО", "fleet",
      formula="--ac, справочник aircraft",
      fields=[("mtow_t", "т", "максимальная взлётная масса"),
              ("cruise_kt", "kt", "крейсерская истинная скорость"),
              ("fuel_kg_per_h", "кг/ч", "запасная ставка, если openap недоступен")],
      emits="запись флота (только физика)",
      note="Экономика эксплуатации здесь НЕ живёт: ставки лизинга, ТОиР и "
           "экипажа лежат в fleet_economics и ключуются парой «перевозчик "
           "плюс тип». Масса у A320 одна на всех, а стоимость обслуживания "
           "у каждого своя — держать их в одном месте значит смешивать то, "
           "что никто не выбирает, с тем, что выбирают все."),
    n("i_lf", 2, "Загрузка", "доля", "input", formula="--lf",
      fields=[("load_factor", "доля 0…1", "")], emits="загрузка",
      note="Ползунок. Не моделируется, задаётся всегда."),
    n("i_charge_ctx", 2, "Условия начисления", "ключ=значение", "input",
      formula="--set charge_context.<ИКАО>.<ключ>",
      fields=[("noise_cat", "категория", "акустический класс борта"),
              ("stand", "apron/pier", "место стоянки"),
              ("dest", "ступень шкалы", "schengen … intercontinental")],
      emits="контекст начисления по аэропортам",
      note="Условие, а не факт: в слой сценария не попадает и у резолвера "
           "не спрашивается. Поэтому и в unused() его нет — предупреждение "
           "о неиспользованном ключе было бы ложным. Словарь ключей "
           "закрытый (решение 21): ключ вне словаря не срабатывает никогда "
           "и должен отвергаться на входе."),

    n("i_month", 2, "Месяц вылета", "1-12", "input", formula="--month",
      fields=[("month", "целое", "сезонное условие тарифа")],
      emits="месяц рейса",
      note="Умолчания нет сознательно: незаданный месяц не превращается в "
           "июль, сезонные правила просто не срабатывают, и разбор их "
           "называет. Не путать с as_of — та дата справочника, а не рейса."),

    n("i_fare", 2, "Тариф", "EUR/пасс", "input", formula="--fare",
      fields=[("fare_eur", "EUR/пасс", "средний чек, не цена конкретного билета")],
      emits="средний чек",
      note="Вместе с загрузкой — те две догадки, вокруг которых сосредоточена "
           "вся неопределённость модели."),

    # ---------- слой 3: промежуточные величины ----------
    n("v_dist", 3, "Ортодромия", "nm", "derived",
      formula="2R·asin(√(sin²(Δφ/2) + cosφ₁cosφ₂sin²(Δλ/2)))",
      inputs=[("d_airport", "lat, lon обеих точек", "°"),
              ("i_route", "какие именно аэропорты", "коды")],
      emits="расстояние",
      note="Дуга большого круга. Реальный трек длиннее на 3–7% из-за "
           "структуры воздушного пространства — надбавки пока нет, и это "
           "занижает сразу топливо, блок-время и число SU."),
    n("v_seats", 3, "Кресла", "шт", "store", formula="компоновка или типовая",
      inputs=[("i_ac", "тип", "код"),
              ("d_layout", "кресел по перевозчику", "шт")], emits="кресел"),
    n("src_openap", 0, "openap", "библиотека", "source",
      fields=[("профиль расхода", "кг/ч", "по фазам полёта"),
              ("геометрия и массы", "разные", "37 типов")],
      emits="физика типов ВС",
      note="Открытая замена BADA: та лицензируется и переизданию не "
           "подлежит. Обновляется версией пакета, а не загрузкой."),

    n("src_aircraft_user", 0, "свои типы ВС", "каталог", "source",
      fields=[("паспортные величины", "разные", "массы, баки, размах, кресла, крейсер"),
              ("аналог и якорь", "кг/ч", "расход от аналога с опубликованным якорем")],
      emits="паспорт типа и якорь расхода",
      note="Каталог data/aircraft/user/*.json, гейт review. Расход числом не "
           "заводится: аналог по поколению двигателя плюс якорь, без якоря "
           "тип отвечает «нельзя» (решения 94, 105, 106)."),

    n("src_easa_noise", 0, "EASA: шум типов", "xlsx", "source",
      fields=[("уровни шума", "EPNdB", "боковая, заход, пролёт"),
              ("масса и глава", "т, №", "при которых сертифицирован уровень")],
      emits="сертифицированный шум типа",
      note="Одна строка на тип: двигатель из домена, масса ближайшая к MTOW. "
           "Запас к главе 3 выводится; категории аэропортов, считающих по "
           "сертификату, строятся на нём правилами документа."),

    n("d_aircraft", 1, "aircraft", "запись", "store",
      inputs=[("src_openap", "физика типа", "разные"),
              ("src_aircraft_user", "паспорт и якорь", "разные"),
              ("src_easa_noise", "шум типа", "EPNdB")],
      fields=[("mtow_t", "т", "максимальная взлётная масса"),
              ("профиль расхода", "кг/ч", "по фазам полёта"),
              ("масса пассажира", "кг", "параметр типа, не константа")],
      emits="физика типа ВС",
      note="37 типов. Вынесен из кода в хранилище на M6; до этого "
           "словарь FLEET жил в исходниках четырьмя типами."),

    n("v_mtow", 3, "MTOW", "т", "store", formula="справочник aircraft",
      inputs=[("d_aircraft", "mtow_t", "т")], emits="взлётная масса",
      note="Входит и в аэронавигационный сбор, и в посадочный."),
    n("v_pax", 3, "Пассажиров", "чел", "derived", formula="кресла · загрузка",
      inputs=[("v_seats", "кресел", "шт"), ("i_lf", "load_factor", "доля")],
      emits="пассажиров"),
    n("v_prof", 3, "Профиль полёта", "фазы", "derived",
      formula="эшелон = min(крейсерский, дистанция · 0.9 / расход пути)",
      inputs=[("v_dist", "расстояние", "nm"),
              ("i_ac", "cruise_kt, модель openap", "kt")],
      fields=[("Руление", "кг, ч", "12 мин при 600 кг/ч"),
              ("Набор", "кг, ч", "2000 фт/мин, 300 kt"),
              ("Крейсер", "кг, ч", "на выбранном эшелоне"),
              ("Снижение", "кг, ч", "1500 фт/мин, 280 kt")],
      emits="топливо и время по четырём фазам",
      note="На коротком плече эшелон срезается: иначе набор и снижение не "
           "помещаются в дистанцию. Отсюда FL192 на 120 nm."),
    n("v_fuel", 3, "Рейсовое топливо", "кг", "derived", formula="Σ по фазам",
      inputs=[("v_prof", "масса по четырём фазам", "кг"),
              ("v_pax", "полезная нагрузка, 100 кг на пассажира", "чел")],
      emits="масса топлива",
      note="Масса считается итеративно: топливо зависит от взлётной массы, "
           "масса зависит от топлива. Сходится за 3–4 шага."),
    # Шаги завела ветка A по решению 82: величина, на которую опирается
    # ответ, обязана быть шагом. Узлы на карте за ними не появились, и
    # сверка четыре круга подряд рапортовала об этом на всех эталонных
    # маршрутах. Соответствием шага и узла никто не владел — теперь ветка
    # одна, и владелец есть.
    n("v_tier", 3, "Ярус расхода", "1-4", "derived",
      formula="openap / точка эксплуатанта / CO₂ / аналог",
      inputs=[("i_ac", "тип ВС", "код"), ("d_aircraft", "охват openap", "да/нет")],
      emits="ярус",
      note="Причина ярусности — лицензия и закрытая эксплуатационная "
           "документация, а не отсутствие данных в мире (решение 105). "
           "Ярус ниже первого допустим только объявленным: молчаливая "
           "подмена «посчитаем по похожему» запрещена."),
    n("v_reserve", 3, "Запас топлива", "кг", "derived",
      formula="непредвиденный 5% + ожидание 30 мин + уход на запасной",
      inputs=[("v_fuel", "рейсовое топливо", "кг"), ("i_ac", "расход в ожидании", "кг/ч")],
      emits="масса запаса",
      note="Запас не сжигается и в стоимость топлива не входит: он возится "
           "и возвращается, а лишний расход от его перевозки уже сидит в "
           "рейсовом топливе через взлётную массу. В выполнимость входит."),
    n("v_block", 3, "Блок-время", "ч", "derived",
      formula="набор + крейсер + снижение + руление",
      inputs=[("v_prof", "время четырёх фаз", "ч")], emits="блок-время",
      note="Держит на себе владение, ТОиР и экипаж — около 39% "
           "себестоимости. Уточнение профиля на M2 уточнило и их."),
    n("v_crew_rate", 3, "Ставки экипажа", "EUR", "derived",
      formula="почасовая и поцикловая части",
      inputs=[("d_fleet", "crew_eur_per_fh и per_fc", "EUR/ч, EUR/рейс")],
      emits="две ставки",
      note="Устроена так же, как ставка ТОиР: часть висит на времени, часть "
           "на самом рейсе — предполётная подготовка и разбор от "
           "длительности плеча не зависят. Узел заведён по симметрии, "
           "замеченной веткой A: обе ставки приводятся к блок-часу "
           "одинаково, и держать их на разных уровнях карты нечестно."),

    n("v_cross", 3, "Пересекаемые зоны", "nm по зонам", "derived",
      formula="выборка точек вдоль ортодромии с шагом 10 nm",
      inputs=[("v_dist", "расстояние", "nm"),
              ("d_airspace", "полигоны зон", "GeoJSON")],
      emits="доли маршрута по зонам",
      note="На FRA–BCN Франция составляет 74% пути. До этого считались "
           "только государства вылета и прилёта, и она в счёт не попадала."),
    n("v_su", 3, "Единицы обслуживания", "SU", "derived",
      formula="Σ по зонам (D_км в зоне / 100) · √(MTOW / 50)",
      inputs=[("v_cross", "мили в каждой зоне", "nm"), ("v_mtow", "mtow_t", "т")],
      emits="число SU по зонам",
      note="Формула EUROCONTROL. У терминальных сборов показатель другой — "
           "0.70 вместо 0.5, и дистанция в него не входит."),
    n("v_rate", 3, "Ставки зон", "EUR/SU", "derived",
      formula="ставка каждой пересекаемой зоны",
      inputs=[("d_rate", "value по коду зоны", "EUR/SU"),
              ("d_navform", "способ расчёта зоны", "код"),
              ("v_cross", "какие зоны пересечены", "коды")],
      emits="ставки",
      note="Зоны без ставки достраиваются средней по маршруту с явным "
           "предупреждением: пропуск занижал бы сбор молча."),
    n("d_navform", 1, "Способ расчёта зоны", "код", "store",
      fields=[("eurocontrol", "формула", "(D_км/100) · √(MTOW/50), 41 государство"),
              ("distance_only", "формула", "за 100 км без учёта массы, Казахстан и СНГ"),
              ("per_100nm", "формула", "за 100 миль, пролётный сбор США и Канады"),
              ("tonne_km", "формула", "за тонно-километр"),
              ("flat", "формула", "плоская плата за пролёт"),
              ("none", "формула", "сбора нет: внутренние рейсы США")],
      emits="способ расчёта",
      note="Формула EUROCONTROL — правило одной организации, а не устройство "
           "мира. Поэтому способ расчёта хранится как данные: добавление "
           "государства становится строкой в справочнике, а не правкой кода. "
           "Отсутствие записи означает eurocontrol."),
    n("v_fprice", 3, "Цена топлива", "EUR/кг", "derived",
      formula="барр / 159 л / 0.8 кг·л⁻¹",
      inputs=[("d_fuelp", "jet_global", "USD/барр")], emits="цена",
      note="Плотность 0.8 кг/л принята константой. Курс USD/EUR пока не "
           "применяется — дыра, закроется вместе с источником fx."),

    # ---------- слой 4: статьи затрат ----------
    n("c_fuel", 4, "Топливо", "EUR", "derived", formula="масса · цена",
      inputs=[("v_fuel", "масса топлива", "кг"),
              ("v_fprice", "цена", "EUR/кг")], emits="затраты"),
    n("c_nav", 4, "Аэронавигация", "EUR", "derived", formula="SU · ставка",
      inputs=[("v_su", "число SU", "SU"), ("v_rate", "ставка", "EUR/SU")],
      emits="затраты"),
    n("c_apt", 4, "Аэропортовые сборы", "EUR", "derived",
      formula="landing_per_t · MTOW + pax · пассажиры",
      inputs=[("d_charge", "landing_per_t и pax", "EUR/т, EUR/пасс"),
              ("v_mtow", "mtow_t", "т"), ("v_pax", "пассажиров", "чел")],
      emits="затраты",
      note="Сейчас две статьи. В реальности их восемь: стоянка, шум, "
           "эмиссия, security, PRM, антиобледенение."),
    n("v_tsu", 3, "Терминальные единицы", "SU", "derived",
      formula="(MTOW / 50) ^ 0.70",
      inputs=[("v_mtow", "mtow_t", "т")], emits="терминальные SU",
      note="Показатель 0.70, а не 0.5 как у en-route, и дистанция в формулу "
           "не входит вовсе: платится за обслуживание в районе аэродрома."),
    n("c_term", 4, "Терминальный сбор", "EUR", "derived",
      formula="терминальные SU · ставка зоны / курс",
      inputs=[("v_tsu", "терминальные SU", "SU"),
              ("d_terminal", "ставка зоны назначения", "нац. валюта/SU"),
              ("d_fx", "курс валюты зоны", "за EUR")],
      emits="затраты",
      note="Плата EUROCONTROL за диспетчерское обслуживание захода, не "
           "аэропорту. Для аэродрома вне config/tcz.yaml не начисляется."),
    n("c_own", 4, "Владение ВС", "EUR", "default",
      formula="месячный платёж · блок-время / налёт борта",
      inputs=[("d_fleet", "lease_eur_month", "EUR/мес"),
              ("v_util", "месячный налёт", "ч/мес"),
              ("v_block", "блок-время", "ч")],
      emits="затраты",
      note="Не ставка за час, а доля месячного платежа. Оба множителя "
           "добываемы по отдельности, непрозрачный EUR/ч — нет."),
    n("c_mnt", 4, "ТОиР", "EUR", "default",
      formula="почасовая · блок-время + поцикловая",
      inputs=[("v_maint_rate", "две ставки", "EUR/ч, EUR/рейс"),
              ("v_block", "блок-время", "ч")],
      emits="затраты",
      note="Поцикловая часть добавляется целиком независимо от плеча: "
           "часовой и шестичасовой рейс изнашивают шасси одинаково."),
    n("c_crew", 4, "Экипаж", "EUR", "default",
      formula="почасовая · блок-время + поцикловая",
      inputs=[("d_fleet", "crew_eur_per_fh и per_fc", "EUR/ч, EUR/рейс"),
              ("v_block", "блок-время", "ч")], emits="затраты"),
    n("c_grnd", 4, "Наземное обслуживание", "EUR", "default",
      formula="900 + 2.2 · пассажиры",
      inputs=[("v_pax", "пассажиров", "чел")], emits="затраты",
      note="Обе константы выдуманы: 900 EUR постоянной части и 2.2 EUR на "
           "пассажира. Кандидат номер один на замену договорными ставками."),
    n("c_dist", 4, "Дистрибуция", "EUR", "default", formula="выручка · 7%",
      inputs=[("v_pax", "пассажиров", "чел")], emits="затраты",
      note="7% — типичная величина для лоукостера, не проверена."),

    # ---------- слой 5: итог ----------
    n("t_base", 5, "Себестоимость рейса", "EUR", "derived",
      formula="Σ девяти статей",
      inputs=[(k, "затраты", "EUR") for k in
              ("c_fuel", "c_nav", "c_term", "c_apt", "c_own", "c_mnt",
               "c_crew", "c_grnd", "c_dist")],
      emits="полная себестоимость"),
    n("t_fare", 5, "Безубыточный тариф", "EUR/пасс", "derived",
      formula="база / пассажиры / (1 − 0.07)",
      inputs=[("t_base", "себестоимость", "EUR"),
              ("v_pax", "пассажиров", "чел")],
      emits="тариф безубыточности",
      note="Деление на (1 − 0.07), потому что комиссия берётся с выручки, "
           "а не с затрат."),
    n("t_lf", 5, "Безубыточная загрузка", "доля", "derived",
      formula="база / (тариф · 0.93 · кресла)",
      inputs=[("t_base", "себестоимость", "EUR"),
              ("i_fare", "fare_eur", "EUR/пасс"),
              ("v_seats", "кресел", "шт")],
      emits="загрузка безубыточности",
      note="Тот же ответ с другой стороны. Вместе с заданными значениями "
           "даёт вердикт прибыль или убыток."),
]

LAYERS = ["Источники", "Справочники", "Задаётся пользователем",
          "Промежуточные величины", "Статьи затрат", "Итог"]

from .ui import PROV_VAR, style_tag

# Подписи ролей здесь, цвета — в ui.css через PROV_VAR (второго списка
# цветов нет). `source` и `store` разного тона одного семейства: внешний
# источник до разбора и справочник после.
ROLE = {
    "source":   ("Внешний источник", PROV_VAR["source"]),
    "store":    ("Справочник",       PROV_VAR["store"]),
    "input":    ("Ввод пользователя", PROV_VAR["input"]),
    "fleet":    ("Параметр флота",   PROV_VAR["fleet"]),
    "derived":  ("Вычисляется",      PROV_VAR["derived"]),
    "default":  ("Выдумано",         PROV_VAR["default"]),
    "override": ("Задано вручную",   PROV_VAR["override"]),
}

UI = {
    "source":  "нет элемента — только индикатор свежести",
    "store":   "таблица только для чтения; правка через ревью предложений",
    "input":   "поле ввода или ползунок",
    "fleet":   "выпадающий список типов ВС",
    "derived": "только вывод, пересчитывается при любом изменении входов",
    "default": "поле ввода с пометкой «оценка» — пока нет источника",
}


def check_against_trace(res) -> list[str]:
    """Шаги расчёта, которым на карте не соответствует узел.

    Ключ — идентификатор узла, а не подпись шага. Подписи меняются:
    ветка B переименовала «Сбор: passenger» в «Сбор EDDF: passenger», и
    сверка по строке этого не пережила бы. Идентификаторы не меняются.

    Единица расхождения — узел, а не строка трассировки. Новый код
    статьи в уже заведённом домене карту не меняет; новый домен или
    новый источник меняет. Иначе на пятидесяти аэропортах проверка
    выдавала бы сотни строк, а проверку, которая шумит пропорционально
    объёму данных, выключают — и она умирает так же, как та, что
    молчит.

    Отсутствие шага расхождением не считается никогда: у Гатвика нет
    весового посадочного сбора, и это устройство тарифа, а не пропуск.
    """
    ids = {x["id"] for x in N}
    out: list[str] = []

    named = [s for s in res.trace if getattr(s, "node", None)]
    unnamed = [s for s in res.trace if not getattr(s, "node", None)]

    seen = set()
    for s in named:
        if s.node not in ids and s.node not in seen:
            seen.add(s.node)
            out.append(f"{s.node} — шаг «{s.label}» ссылается на узел, "
                       f"которого нет на карте")

    # Пустой список должен означать «сверено и сошлось», а не «сверять
    # было нечем». Решение 37.
    if unnamed:
        kinds = ", ".join(sorted({s.group for s in unnamed})) or "без группы"
        out.append(f"не сверено: {len(unnamed)} шагов без поля node "
                   f"({kinds}) — эта часть расчёта картой не проверяется")
    if not res.trace:
        out.append("не сверено: трассировка пуста")
    return out


def unrealised_nodes(results) -> list[str]:
    """Обратная сверка: узел, который не реализует ни один шаг.

    Второй вид того же расхождения, что и прямая сверка. Прямая ловит
    «модель считает то, чего нет на карте», обратная — «карта обещает
    то, чего модель не считает».

    Область применения сужена намеренно. Источники слоя 0 и домены
    хранилища слоя 1 шагами не реализуются НИКОГДА: шаг стоит на
    производной величине, а не на источнике позади неё. Проверять их
    здесь значило бы вечно показывать семнадцать мёртвых узлов, которые
    живы, — то есть шум пропорционально размеру карты (решение 57).
    Их присутствие в модели проверяется провенансом факта, а не
    трассировкой.

    Работает по ОБЪЕДИНЕНИЮ прогонов, а не по одному: `d_fx` законно
    молчит на маршруте, где все ставки в евро, а `d_limits` — там, где
    полосы хватает с запасом.
    """
    if not results:
        return ["обратная сверка не выполнялась: ни один эталонный "
                "маршрут не посчитан"]
    used = {getattr(s, "node", None)
            for r in results for s in getattr(r, "trace", ())}
    used.discard(None)
    dead = sorted(x["id"] for x in N
                  if x["layer"] >= 3 and x["id"] not in used)
    if not dead:
        return []
    return [f"{i} — узел есть на карте, но его не реализует ни один шаг "
            f"ни на одном из {len(results)} эталонных маршрутов"
            for i in dead]


def to_html(registry: dict | None = None) -> str:
    nodes = [dict(x) for x in N]
    for nd in nodes:
        nd["outputs"] = [
            {"id": m["id"],
             "take": next(i["take"] for i in m["inputs"] if i["id"] == nd["id"]),
             "unit": next(i["unit"] for i in m["inputs"] if i["id"] == nd["id"])}
            for m in nodes if any(i["id"] == nd["id"] for i in m["inputs"])]
        nd["roleLabel"], nd["color"] = ROLE[nd["role"]]
        nd["ui"] = UI[nd["role"]]

    legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{html.escape(l)}</span>'
        for l, c in ROLE.values())

    return (_TPL.replace("__UI__", style_tag(inline_fonts=True))
                .replace("__DATA__", json.dumps(nodes, ensure_ascii=False))
                .replace("__LAYERS__", json.dumps(LAYERS, ensure_ascii=False))
                .replace("__LEGEND__", legend)
                .replace("__DATE__", date.today().isoformat()))


_TPL = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FlightCostApp — карта данных</title>
__UI__<style>
body{font-size:14px}
header{padding:26px 30px 18px;border-bottom:1px solid var(--line)}
h1{margin:0 0 4px;font:600 20px/1.2 var(--sans);color:var(--ink2)}
.sub{color:var(--dim);font-size:13px;max-width:76ch}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--dim)}
.lg{display:flex;align-items:center;gap:6px}
.lg i{width:9px;height:9px;border-radius:2px;display:block}
main{display:flex;align-items:flex-start}
#board{flex:1;overflow-x:auto;padding:22px 26px 60px;position:relative}
#svg{position:absolute;inset:0;pointer-events:none;z-index:0}
.cols{display:flex;gap:34px;position:relative;z-index:1;min-width:max-content}
.col{width:186px;flex:none}
.colh{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--dim);font-weight:600;margin-bottom:11px;height:26px}
.node{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--c);
 border-radius:6px;padding:9px 11px;margin-bottom:9px;cursor:pointer;
 transition:background .12s,border-color .12s,opacity .12s}
.node:hover{background:var(--raise);border-color:var(--faint)}
.node.sel{background:var(--select);border-color:var(--c)}
.node.dim{opacity:.22}
.node .t{font-weight:600;color:var(--ink2);font-size:13.5px;line-height:1.3}
.node .u{font:11px var(--mono);color:var(--dim);margin-top:3px}
aside{width:398px;flex:none;border-left:1px solid var(--line);padding:22px 24px 60px;
 position:sticky;top:0;max-height:100vh;overflow-y:auto}
aside h2{margin:0 0 3px;font-size:19px;color:var(--ink2)}
.role{display:inline-block;font-size:10px;letter-spacing:.09em;
 text-transform:uppercase;font-weight:600;padding:3px 7px;border-radius:3px;
 margin-bottom:15px}
.sec{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;
 color:var(--dim);font-weight:600;margin:19px 0 7px}
.f{font:12.5px/1.6 var(--mono);color:var(--ink);
 background:var(--panel);border:1px solid var(--line);border-radius:5px;padding:9px 11px;
 word-break:break-word}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td{padding:6px 0;border-bottom:1px solid var(--line2);vertical-align:top}
td.k{width:42%;padding-right:10px}
td.u{width:28%;font:11.5px var(--mono);color:var(--dim);text-align:right;
 white-space:nowrap}
.link{color:var(--ink);cursor:pointer;border-bottom:1px dotted var(--faint)}
.link:hover{color:var(--ink2)}
.take{color:var(--dim);font:11.5px/1.5 var(--mono)}
.fname{font:12px var(--mono);color:var(--ink)}
.fnote{color:var(--dim);font-size:11.5px;display:block;margin-top:2px;line-height:1.45}
.note{border:0;background:none;padding:0;border-radius:0;color:var(--dim);font-size:13px;line-height:1.6}
.empty{color:var(--faint);font-size:12.5px;font-style:italic}
.hint{color:var(--dim);font-size:12.5px;line-height:1.6;margin-top:8px}
@media(max-width:900px){main{flex-direction:column}aside{width:100%;
 border-left:0;border-top:1px solid var(--line);position:static;max-height:none}}
</style></head><body>
<header>
<h1>FlightCostApp · карта данных</h1>
<div class="sub">Каждый узел — величина в расчёте. Клик показывает формулу,
собственные поля, а также что именно узел получает от каждого входа и что
отдаёт дальше, с единицами измерения. Ветка подсвечивается, остальное гаснет.</div>
<div class="legend">__LEGEND__</div>
</header>
<main>
<div id="board"><svg id="svg"></svg><div class="cols" id="cols"></div></div>
<aside id="panel"></aside>
</main>
<script>
const NODES = __DATA__, LAYERS = __LAYERS__;
const byId = Object.fromEntries(NODES.map(n => [n.id, n]));
const cols = document.getElementById('cols'), svg = document.getElementById('svg');

LAYERS.forEach((name, i) => {
  const c = document.createElement('div'); c.className = 'col';
  c.innerHTML = '<div class="colh">' + name + '</div>';
  NODES.filter(n => n.layer === i).forEach(n => {
    const d = document.createElement('div');
    d.className = 'node'; d.id = 'n_' + n.id;
    d.style.setProperty('--c', n.color);
    d.innerHTML = '<div class="t">' + n.label + '</div><div class="u">' + n.unit + '</div>';
    d.onclick = ev => { ev.stopPropagation(); select(n.id); };
    c.appendChild(d);
  });
  cols.appendChild(c);
});

const up = (id, a = new Set()) => (byId[id].inputs.forEach(p =>
  { if (!a.has(p.id)) { a.add(p.id); up(p.id, a); } }), a);
const down = (id, a = new Set()) => (byId[id].outputs.forEach(p =>
  { if (!a.has(p.id)) { a.add(p.id); down(p.id, a); } }), a);

function select(id) {
  const u = up(id), d = down(id), live = new Set([id, ...u, ...d]);
  NODES.forEach(n => {
    const el = document.getElementById('n_' + n.id);
    el.classList.toggle('sel', n.id === id);
    el.classList.toggle('dim', !live.has(n.id));
  });
  drawEdges(live); panel(byId[id], u, d);
}

function drawEdges(live) {
  const box = document.getElementById('board').getBoundingClientRect();
  svg.setAttribute('width', cols.scrollWidth);
  svg.setAttribute('height', cols.scrollHeight + 60);
  let out = '';
  NODES.forEach(n => n.inputs.forEach(p => {
    const on = !live || (live.has(n.id) && live.has(p.id));
    const a = document.getElementById('n_' + p.id).getBoundingClientRect();
    const b = document.getElementById('n_' + n.id).getBoundingClientRect();
    const x1 = a.right - box.left, y1 = a.top - box.top + a.height / 2;
    const x2 = b.left - box.left,  y2 = b.top - box.top + b.height / 2;
    const m = (x1 + x2) / 2;
    out += '<path d="M' + x1 + ' ' + y1 + ' C' + m + ' ' + y1 + ' ' + m + ' '
        + y2 + ' ' + x2 + ' ' + y2 + '" fill="none" stroke="'
        + (on ? byId[p.id].color : 'var(--line)') + '" stroke-width="' + (on ? 1.6 : 1)
        + '" opacity="' + (on ? .85 : .3) + '"/>';
  }));
  svg.innerHTML = out;
}

function rows(list) {
  if (!list.length) return '<div class="empty">нет</div>';
  return '<table>' + list.map(p =>
    '<tr><td class="k"><span class="link" onclick="select(\'' + p.id + '\')">'
    + byId[p.id].label + '</span></td>'
    + '<td><span class="take">' + p.take + '</span></td>'
    + '<td class="u">' + p.unit + '</td></tr>').join('') + '</table>';
}

function fields(f) {
  if (!f.length) return '';
  return '<div class="sec">Собственные поля</div><table>' + f.map(x =>
    '<tr><td class="k"><span class="fname">' + x.name + '</span>'
    + (x.note ? '<span class="fnote">' + x.note + '</span>' : '') + '</td>'
    + '<td></td><td class="u">' + x.unit + '</td></tr>').join('') + '</table>';
}

function panel(n, u, d) {
  document.getElementById('panel').innerHTML =
    '<h2>' + n.label + '</h2>'
    + '<span class="role" style="background:' + n.color + '22;color:' + n.color
      + '">' + n.roleLabel + ' · ' + n.unit + '</span>'
    + (n.formula ? '<div class="sec">Формула</div><div class="f">' + n.formula + '</div>' : '')
    + fields(n.fields)
    + '<div class="sec">Получает</div>' + rows(n.inputs)
    + '<div class="sec">Отдаёт «' + n.emits + '» в</div>' + rows(n.outputs)
    + (n.note ? '<div class="sec">Что важно знать</div><div class="note">' + n.note + '</div>' : '')
    + '<div class="sec">Во фронте</div><div class="note">' + n.ui + '</div>'
    + '<div class="hint">' + u.size + ' узлов выше по потоку, ' + d.size + ' ниже.</div>';
}

document.getElementById('board').onclick = () => {
  NODES.forEach(n => document.getElementById('n_' + n.id)
    .classList.remove('sel', 'dim'));
  drawEdges(null); intro();
};
function intro() {
  document.getElementById('panel').innerHTML =
    '<h2>Как читать</h2>'
    + '<div class="note">Поток слева направо: внешний источник → справочник '
    + '→ промежуточная величина → статья затрат → итог. Ребро несёт '
    + 'конкретное поле, а не просто зависимость: в панели у каждой связи '
    + 'указано, что именно берётся и в каких единицах.</div>'
    + '<div class="sec">Зачем это</div>'
    + '<div class="note">Оранжевые узлы — числа, взятые из воздуха. Чем их '
    + 'меньше, тем ближе модель к пригодности. Зелёные приходят из '
    + 'справочников и обновляются сами.</div>'
    + '<div class="sec">Для фронта</div>'
    + '<div class="note">Синие узлы становятся полями ввода, фиолетовые — '
    + 'выбором типа ВС, зелёные — таблицами только для чтения, серые — '
    + 'выводом. Список собственных полей узла — это и есть схема формы.</div>'
    + '<div class="hint">Сгенерировано __DATE__ командой <code>fca map</code>.</div>';
}
window.addEventListener('resize', () => drawEdges(null));
setTimeout(() => { drawEdges(null); intro(); }, 60);
</script></body></html>"""
