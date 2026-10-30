#!/usr/bin/env python3
"""Статья «Как построить сеть, чтобы самолёт летал больше» — большое практическое руководство.

Структура — research/STYLE.md (хук → теория → аналитика → факты → что меняем → отчёт), но шире
калькулятора: базы, плечи, обороты, ротации, экипажи, ТОиР и простои, цена плотного расписания.
Текст — связный (правка владельца 30.10.2026): сокращаем схемами (svg.py), а не обрывками.

Данные — out/n1.json (налёт по авиакомпаниям), out/n2.json (механика и построение сети),
out/n3.json (экипажи, ТО, задержки), out/n4.json (планирование ТО, простои, контракты, станции,
запчасти), trace/n5.jsonl (группа «Аэрофлот» по Databook и полосы бенчмарков 2025 года);
проверка — verify/.

Только свежие данные (2023–2025): старые ряды налёта (S7 2014–2018, «Победа» 2018, Pegasus
2017–2019, США 2019) сняты по решению владельца. Поправки проверяющих: формула налёта — в блок-часах
с оборотом без такси (n2-137), без выборочного сравнения ULCC и сетевых (n2-143), DUS — плановые
посадки до 23:00 (n2-138), без примера ZRH–MIA (n2-142), без «809 ч на пилота» (n3-054), без таблицы
смен приказа №381 до сверки (n3-028).

Три языка: тексты — T(ru, en, de), строки из данных — i18n.yaml (Tr); write_all пишет report.html, report.en.html, report.de.html.

    python3 research/network-2026-10/build_report.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from _report import (ARTICLE_CSS, Sources, T, Tr, article_title, calc_badge, e, line_chart, mark,  # noqa: E402
                     money, n, page, whisker, write_all)
import svg  # noqa: E402

S = Sources(HERE)
TR = Tr(HERE)
# Выводы (infer/conclude) своего адреса не имеют — ссылка ведёт на источники, из которых они выведены.
_PAR = {o["id"]: o.get("parents") or [] for f in sorted(HERE.glob("trace/n*.jsonl"))
        for o in map(json.loads, f.read_text(encoding="utf-8").splitlines())}


def _roots(i, seen=None):
    seen = seen or set()
    if i in S.step or i in seen:
        return [i] if i in S.step else []
    seen.add(i)
    return [r for p in _PAR.get(i, []) for r in _roots(p, seen)]


def cite(*ids):
    return S.cite(*[r for i in ids for r in _roots(i)])


def txt(x):
    return x if isinstance(x, str) else (x.get("what") or x.get("item") or x.get("claim")
                                         or json.dumps(x, ensure_ascii=False))


J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
N1, N2, N3 = J("out/n1.json"), J("out/n2.json"), J("out/n3.json")
N4 = J("out/n4.json") if (HERE / "out/n4.json").exists() else None
VER = {f: J(f"verify/{f}.json") for f in ("n1", "n2", "n3", "n4") if (HERE / f"verify/{f}.json").exists()}

# Пример для калькулятора: A320 текущего поколения, лизинг-заготовка 200 тыс. EUR в месяц
# (fleet.DEFAULTS, решение 186), рейс Франкфурт — Барселона 2,12 блок-часа.
LEASE, BLOCK = 200_000, 2.12


def own_per_flight(h_month):
    return LEASE / h_month * BLOCK


def util_day(window_h, tat_min, block_h, shuttle=True):
    """Пиковый день: сколько целых рейсов влезает в окно; для челнока от базы — чётное число
    (последний рейс возвращает борт на базу). Блок-время плеча включает руление, поэтому между
    рейсами — только оборот (поправка проверяющего к n2-137)."""
    tat = tat_min / 60
    k = int((window_h + tat) // (block_h + tat))
    if shuttle:
        k -= k % 2
    return k * block_h, k


# ── налёт по авиакомпаниям, только 2023–2025: (подпись, год, среднее ч/сут, (мин, макс), шаги, оговорка) ──
# Диапазон — сезон (худший и лучший месяц) или «весь парк / летающие борта», если так в источнике.
# Подписи и оговорки — кортежи (ru, en, de), выбор языка — L().
def L(x):
    return T(*x) if isinstance(x, tuple) else x


AFL = [(("Победа", "Pobeda", "Pobeda"), [10.78, 12.29, 12.63, 12.69]),
       (("Аэрофлот", "Aeroflot", "Aeroflot"), [6.26, 8.01, 9.41, 9.8]),
       (("Россия", "Rossiya", "Rossiya"), [4.41, 4.19, 4.82, 4.94]),
       (("Группа", "Group", "Gruppe"), [6.13, 7.05, 8.02, 8.27])]
BAL = ("налёт ÷ средний парк на балансе", "flight hours ÷ average fleet on the balance sheet",
       "Flugstunden ÷ durchschnittliche Bilanzflotte")
AIR = [
    (("«Россия» (группа «Аэрофлот»)", "Rossiya (Aeroflot group)", "Rossiya (Aeroflot-Gruppe)"), "2025", 4.94,
     (4.94, 4.94), ["n5-011"], BAL),
    ("Allegiant", "2024", 6.3, (6.3, 6.3), ["n1-020"],
     ("редкие рейсы на курорты", "infrequent flights to resorts", "seltene Flüge zu Urlaubszielen")),
    (("Группа «Аэрофлот»", "Aeroflot group", "Aeroflot-Gruppe"), "2025", 8.27, (8.27, 8.27), ["n5-009"], BAL),
    ("Ryanair", "FY2025", 9.57, (9.57, 12.9), ["n1-099", "n1-058"],
     ("лётные часы; пик — Ryanair UK, август 2024", "flight hours; peak — Ryanair UK, August 2024",
      "Flugstunden; Spitze — Ryanair UK, August 2024")),
    (("«Аэрофлот»", "Aeroflot", "Aeroflot"), "2025", 9.8, (9.8, 9.8), ["n5-010"], BAL),
    ("Wizz Air", "FY2025", 9.85, (9.85, 12.47), ["n1-009", "n1-012"],
     ("весь парк / летающие борта (часть стоит из-за двигателей GTF)",
      "whole fleet / flying aircraft (some grounded by GTF engines)",
      "ganze Flotte / fliegende Flugzeuge (einige wegen GTF-Triebwerken am Boden)")),
    ("easyJet", "FY2025", 10.2, (8.9, 11.9), ["n5-015", "n1-066", "n1-055"],
     ("диапазон — easyJet UK, январь и сентябрь 2024", "range — easyJet UK, January and September 2024",
      "Spanne — easyJet UK, Januar und September 2024")),
    ("Norwegian", "2025", 10.9, (10.9, 10.9), ["n5-016"], ""),
    (("Copa (хаб в Панаме)", "Copa (hub in Panama)", "Copa (Hub in Panama)"), "2025", 11.1, (11.1, 11.1), ["n5-021"],
     ("блок-часы ÷ парк на конец года", "block hours ÷ year-end fleet", "Blockstunden ÷ Flotte zum Jahresende")),
    ("Spirit", "2023", 11.1, (11.1, 11.2), ["n1-023"], ""),
    ("VietJet", ("1П2023", "H1 2023", "H1 2023"), 12.0, (12.0, 12.0), ["n1-089"],
     ("база не указана", "basis not stated", "Basis nicht angegeben")),
    (("«Победа» (группа «Аэрофлот»)", "Pobeda (Aeroflot group)", "Pobeda (Aeroflot-Gruppe)"), "2025", 12.69,
     (12.69, 12.69), ["n5-012"], BAL),
    ("Thai AirAsia", "2023", 12.7, (12.7, 12.7), ["n1-149"], ""),
    ("Volaris", "2024", 13.03, (13.03, 13.13), ["n1-082"], ""),
    ("Pegasus", "2025", 13.2, (13.2, 13.2), ["n5-017"],
     ("чтение отчёта не подтверждено", "reading of the report not confirmed", "Lesung des Berichts nicht bestätigt")),
    ("BA A350-1000, Virgin", "2024", 14.3, (14.0, 14.8), ["n1-063", "n1-052", "n1-062"],
     ("по месяцам", "by month", "nach Monaten")),
]
SOFT = {"Ryanair", "easyJet", "Pegasus", "VietJet", "BA A350-1000, Virgin", "Copa (хаб в Панаме)"}

CURFEW = [(("Франкфурт (FRA)", "Frankfurt (FRA)", "Frankfurt (FRA)"),
           ("запрет 23:00–05:00; с 22 до 06 — в среднем до 133 плановых движений за ночь",
            "ban 23:00–05:00; from 22 to 06 on average up to 133 scheduled movements a night",
            "Verbot 23:00–05:00; von 22 bis 06 Uhr im Schnitt bis zu 133 planmäßige Bewegungen pro Nacht"),
           ["n2-006", "n2-007"]),
          (("Лондон-Хитроу (LHR)", "London Heathrow (LHR)", "London-Heathrow (LHR)"),
           ("ночная квота 23:30–06:00, 5 800 ночных движений в год",
            "night quota 23:30–06:00, 5,800 night movements a year",
            "Nachtkontingent 23:30–06:00, 5.800 Nachtbewegungen im Jahr"), ["n2-024", "n2-025"]),
          (("Амстердам (AMS)", "Amsterdam (AMS)", "Amsterdam (AMS)"),
           ("ночь 23:00–07:00, лимит ночных движений снижается с 32 000 до 27 000 в год",
            "night 23:00–07:00, the night-movement cap is being cut from 32,000 to 27,000 a year",
            "Nacht 23:00–07:00, die Obergrenze für Nachtbewegungen sinkt von 32.000 auf 27.000 im Jahr"),
           ["n2-033", "n2-034"]),
          (("Цюрих (ZRH)", "Zurich (ZRH)", "Zürich (ZRH)"),
           ("регулярные полёты 06:00–23:30; плановые вылеты до 22:45",
            "scheduled operations 06:00–23:30; scheduled departures until 22:45",
            "Linienbetrieb 06:00–23:30; planmäßige Abflüge bis 22:45"), ["n2-029", "n2-030"]),
          (("Париж-Орли (ORY)", "Paris Orly (ORY)", "Paris-Orly (ORY)"),
           ("запрет 23:30–06:00; потолок 250 000 движений в год", "curfew 23:30–06:00; cap of 250,000 movements a year",
            "Nachtflugverbot 23:30–06:00; Obergrenze 250.000 Bewegungen im Jahr"), ["n2-037", "n2-038"]),
          (("Дюссельдорф (DUS)", "Düsseldorf (DUS)", "Düsseldorf (DUS)"),
           ("плановые вылеты 06–22, посадки 06–23; базирующимся — опоздавшие посадки до 24:00",
            "scheduled departures 06–22, landings 06–23; based carriers — delayed landings until 24:00",
            "planmäßige Abflüge 06–22, Landungen 06–23; stationierte Airlines — verspätete Landungen bis 24:00"),
           ["n2-042", "n2-043", "n2-044"]),
          (("Сидней (SYD)", "Sydney (SYD)", "Sydney (SYD)"), ("запрет 23:00–06:00", "curfew 23:00–06:00",
                                                              "Nachtflugverbot 23:00–06:00"), ["n2-010"])]


def mro_section() -> str:
    """ТОиР и простои — по out/n4.json (собирается отдельным исследователем)."""
    if not N4:
        return ""
    from mro import section
    return section(N4, cite, n, e, svg)


def build() -> str:
    o300, o400 = own_per_flight(300), own_per_flight(400)
    peak25, _ = util_day(18, 25, 2.5)
    peak30, _ = util_day(18, 25, 3.0)

    # ── 1. хук ────────────────────────────────────────────────────────────
    hook = T(f"""<h1>Как построить сеть, чтобы самолёт летал больше</h1>
<p class="meta">Исследование FlightCostApp, октябрь 2026 · черновик · базы, плечи, обороты, экипажи, техобслуживание,
запчасти и цена плотного расписания</p>
{calc_badge("network-2026-10")}
<div class="verdict">
<div><b>8–13 ч в сутки</b><span>столько в среднем за год летает борт у крупных перевозчиков по отчётности 2024–2025
годов{cite('n5-009', 'n1-082', 'n5-017')}</span></div>
<div><b>12,7 · 9,8 · 4,9 ч</b><span>«Победа», «Аэрофлот» и «Россия» в 2025 году: одна группа, одна страна, одна
отчётность — налёт задаёт устройство сети{cite('n5-012', 'n5-010', 'n5-011')}</span></div>
<div><b>Плечо 2,5 ч → {n(peak25)} ч, 3 ч → {n(peak30)} ч</b><span>в пиковый день при окне 18 ч и обороте 25 минут:
в окно должно влезать целое число пар «туда-обратно»{cite('n2-139')}</span></div>
<div><b>300 → 400 ч в месяц</b><span>минус четверть владения на каждом рейсе: {money(o300)} → {money(o400)} на рейсе
A320 Франкфурт — Барселона</span></div></div>
<p class="lede">Налёт — сколько часов в сутки самолёт проводит в рейсе — главный рычаг себестоимости, которого не видно
в цене билета. Лизинг, страховку и бо́льшую часть зарплаты экипажа авиакомпания платит за месяц, а не за час полёта.
Поэтому самолёт, который летает 13 часов в сутки, везёт на каждом рейсе почти вдвое меньшую долю этих расходов, чем
самолёт, который летает 7. Эта статья — о том, как устроен налёт: из чего он складывается за сутки и за год, сколько
летают авиакомпании на самом деле, как строят сеть, расписание и смены экипажей, как планируют техобслуживание и
держат запчасти, чтобы самолёт не стоял, — и чем приходится платить за плотное расписание. Калькулятор сейчас берёт
одну цифру для любого самолёта и любой сети — 300 часов в месяц, около 10 в сутки; в конце — что мы в нём меняем.</p>""",
             f"""<h1>How to build a network so the aircraft flies more</h1>
<p class="meta">FlightCostApp research, October 2026 · draft · bases, sectors, turnarounds, crews, maintenance, spare
parts and the price of a tight schedule</p>
{calc_badge("network-2026-10")}
<div class="verdict">
<div><b>8–13 h a day</b><span>is how much an aircraft flies on average over a year at major carriers, per their 2024–2025
reports{cite('n5-009', 'n1-082', 'n5-017')}</span></div>
<div><b>12.7 · 9.8 · 4.9 h</b><span>Pobeda, Aeroflot and Rossiya in 2025: one group, one country, one set of accounts —
utilisation is set by how the network is built{cite('n5-012', 'n5-010', 'n5-011')}</span></div>
<div><b>Sector 2.5 h → {n(peak25)} h, 3 h → {n(peak30)} h</b><span>on a peak day with an 18-hour window and 25-minute
turnarounds: a whole number of out-and-back pairs must fit into the window{cite('n2-139')}</span></div>
<div><b>300 → 400 h a month</b><span>a quarter less ownership cost on every flight: {money(o300)} → {money(o400)} on an A320
Frankfurt — Barcelona flight</span></div></div>
<p class="lede">Utilisation — how many hours a day an aircraft spends flying — is the main cost lever that the ticket
price does not show. An airline pays the lease, the insurance and most of the crew's salary by the month, not by the
flight hour. So an aircraft flying 13 hours a day carries almost half as much of these costs on each flight as one
flying 7. This article is about how utilisation works: what it is made of over a day and a year, how much airlines
really fly, how they build the network, the schedule and crew duties, how they plan maintenance and keep spare parts so
the aircraft is not grounded — and what a tight schedule costs. The calculator currently uses a single figure for any
aircraft and any network — 300 hours a month, about 10 a day; at the end, what we are changing.</p>""",
             f"""<h1>Wie man ein Netz baut, damit das Flugzeug mehr fliegt</h1>
<p class="meta">FlightCostApp-Studie, Oktober 2026 · Entwurf · Basen, Strecken, Turnarounds, Crews, Wartung, Ersatzteile
und der Preis eines dichten Flugplans</p>
{calc_badge("network-2026-10")}
<div class="verdict">
<div><b>8–13 h am Tag</b><span>fliegt ein Flugzeug bei großen Airlines im Jahresmittel, laut ihren Berichten 2024–2025
{cite('n5-009', 'n1-082', 'n5-017')}</span></div>
<div><b>12,7 · 9,8 · 4,9 h</b><span>Pobeda, Aeroflot und Rossiya 2025: eine Gruppe, ein Land, ein Bericht — die
Auslastung bestimmt der Aufbau des Netzes{cite('n5-012', 'n5-010', 'n5-011')}</span></div>
<div><b>Strecke 2,5 h → {n(peak25)} h, 3 h → {n(peak30)} h</b><span>an einem Spitzentag bei 18-Stunden-Fenster und
25 Minuten Turnaround: Es muss eine ganze Zahl von Hin- und Rückflügen ins Fenster passen{cite('n2-139')}</span></div>
<div><b>300 → 400 h im Monat</b><span>ein Viertel weniger Besitzkosten auf jedem Flug: {money(o300)} → {money(o400)} auf
einem A320-Flug Frankfurt — Barcelona</span></div></div>
<p class="lede">Die Auslastung — wie viele Stunden am Tag ein Flugzeug in der Luft verbringt — ist der wichtigste
Kostenhebel, den man dem Ticketpreis nicht ansieht. Leasing, Versicherung und den größten Teil der Crewgehälter zahlt eine
Airline pro Monat, nicht pro Flugstunde. Ein Flugzeug, das 13 Stunden am Tag fliegt, trägt auf jedem Flug daher fast nur
halb so viel dieser Kosten wie eines, das 7 Stunden fliegt. Dieser Artikel erklärt, wie Auslastung funktioniert: woraus
sie sich über einen Tag und ein Jahr zusammensetzt, wie viel Airlines wirklich fliegen, wie Netz, Flugplan und
Crew-Dienste gebaut werden, wie Wartung geplant und Ersatzteile gehalten werden, damit das Flugzeug nicht steht — und was
ein dichter Flugplan kostet. Der Rechner nimmt derzeit eine Zahl für jedes Flugzeug und jedes Netz — 300 Stunden im
Monat, etwa 10 am Tag; am Ende steht, was wir daran ändern.</p>""")

    # ── 2. теория ─────────────────────────────────────────────────────────
    funnel = svg.funnel([(T("Сутки", "Day", "Tag"), 24, ""),
                         (T("Окно работы базы", "Base operating window", "Betriebsfenster der Basis"), 18,
                          T("минус ночь, когда база закрыта или нет спроса", "minus the night, when the base is closed or there is no demand",
                            "minus Nacht, wenn die Basis zu ist oder Nachfrage fehlt")),
                         (T("Пиковый день", "Peak day", "Spitzentag"), peak25,
                          T("минус обороты и непарный остаток окна", "minus turnarounds and the unpaired rest of the window",
                            "minus Turnarounds und ungenutzter Rest des Fensters")),
                         (T("Среднее за год", "Annual average", "Jahresmittel"), round(peak25 * 0.8, 1),
                          T("минус зима, ТО, резерв, задержки", "minus winter, maintenance, reserve, delays",
                            "minus Winter, Wartung, Reserve, Verspätungen"))])
    theory = T(f"""<section><h2>Из чего складывается налёт</h2>
<p>Начнём с суток. Самолёт может летать, пока открыты аэропорты, в которых он садится и откуда вылетает. Во многих
крупных аэропортах Европы ночью действуют запреты или квоты, и там рабочее окно базы — примерно с шести утра до
полуночи, около 18 часов. Но это не закон природы: многие аэропорты работают круглосуточно — Стамбул, Доха
{cite('n5-022')} и другие крупные хабы Персидского залива и Азии, — и ночью там летают вовсю: ночной рейс прилетает
к утренней волне пересадок, поздние прилёты и ранние вылеты стыкуются через ночь. Глава Qatar Airways прямо называл
круглосуточный аэропорт преимуществом перед европейскими конкурентами{cite('n5-022')}. Даже там сутки почти никогда не
уходят в рейсы целиком, только ограничивает уже не аэропорт, а три другие вещи. Спрос: ночью пассажиров мало, и ночной
рейс продают дешевле, кроме дальних и курортных направлений. Экипажи: ночная смена короче дневной — по правилам EASA
при начале смены поздно вечером и ночью до 11 часов против 13 днём{cite('n3-006', 'n3-005')}. И техобслуживание:
ежедневные проверки и форма A делаются на земле, обычно ночью на базе, — об этом ниже. Поэтому окно в 18 часов в
расчётах ниже — типичный случай для базы с ночными ограничениями; у базы без них окно шире, на 20–22 часа, но платят
за это ночными сменами и тем, что ТО приходится искать другое время. Внутри окна самолёт не только летает: после каждой
посадки его нужно высадить, убрать, заправить и посадить новых пассажиров — это оборот, у узкофюзеляжных самолётов от
получаса до часа. Кроме того, базовый самолёт к ночи должен вернуться домой, поэтому в окно влезает только целое число
пар «туда-обратно», и кусок окна, в который пара не влезла, пропадает. Так из 24 часов получается пиковый день — то,
что самолёт налетает в хороший летний день без сбоев.</p>
<p>Средний налёт за год всегда ниже пикового дня. Зимой спрос падает, и часть самолётов ставят на стоянку или на
тяжёлое техобслуживание; несколько бортов держат в резерве на случай поломок; задержки съедают запас расписания.
Сколько именно теряется, зависит от авиакомпании; на схеме ниже взят коэффициент 0,8 — это наша калибровка для
иллюстрации, а не цитата из источника.</p>
{funnel}
<p class="small">Схема: окно 06:00–24:00, плечо 2,5 блок-часа, оборот 25 минут — шесть рейсов по формуле из раздела о
сети; годовой коэффициент 0,8 — допущение.</p>
<p>Говоря о налёте, легко сравнить несравнимое, поэтому три уточнения. Первое — <b>блок-часы и лётные часы</b>.
Блок-время считают от уборки колодок перед вылетом до их установки после посадки, вместе с рулением; лётное время —
только в воздухе. Руление туда и обратно занимает около 20 минут на рейс{cite('n2-130')}, так что на коротких плечах
лётных часов на 10–15 % меньше, чем блок-часов. Ryanair отчитывается в лётных часах, большинство перевозчиков и
калькулятор — в блок-часах.</p>
<p>Второе — <b>летающий борт и весь парк</b>. В 2025 финансовом году у Wizz Air самолёт, который летал, налётывал
12 часов 28 минут в сутки, а в среднем на весь парк выходило 9 часов 51 минута: в среднем 44 борта стояли на земле из-за
дефектов двигателей{cite('n1-009', 'n1-012')}. Для себестоимости рейса важен налёт на весь парк: за стоящий самолёт
лизинг платится так же.</p>
<p>Третье — <b>пиковый месяц и год</b>. Летом авиакомпания выжимает из самолёта максимум, зимой летает меньше: у
easyJet в Великобритании в сентябре 2024 года — 11,9 часа в сутки, в январе — 8,9{cite('n1-055', 'n1-066')}. Годовой
лизинг делится на среднее за год, а не на лучший месяц.</p></section>""",
               f"""<section><h2>What utilisation is made of</h2>
<p>Let us start with a day. An aircraft can fly while the airports it lands at and departs from are open. Many large
European airports have night bans or quotas, and there a base's operating window runs roughly from six in the morning to
midnight, about 18 hours. But this is not a law of nature: many airports operate around the clock — Istanbul, Doha
{cite('n5-022')} and other big hubs in the Gulf and Asia — and flying goes on all night there: a night flight arrives for the
morning connecting bank, late arrivals and early departures connect overnight. The head of Qatar Airways has explicitly
called a 24-hour airport an advantage over European competitors{cite('n5-022')}. Even there, the whole day almost never
goes into flying; it is just that the limit is no longer the airport but three other things. Demand: there are few
passengers at night, and a night flight sells for less, except on long-haul and leisure routes. Crews: a night duty is
shorter than a day one — under EASA rules, a duty starting late in the evening or at night is limited to 11 hours, against
13 by day{cite('n3-006', 'n3-005')}. And maintenance: daily checks and the A-check are done on the ground, usually overnight
at base — more on this below. So the 18-hour window in the calculations below is the typical case for a base with night
restrictions; a base without them has a wider window, 20–22 hours, but pays for it with night duties and with having to
find other time for maintenance. Within the window the aircraft does not only fly: after each landing it has to be
deplaned, cleaned, refuelled and boarded again — the turnaround, from half an hour to an hour for narrowbodies. On top of
that, a based aircraft has to be home by night, so only a whole number of out-and-back pairs fits into the window, and
the part of the window that a pair does not fit into is lost. That is how 24 hours become a peak day — what the aircraft
flies on a good summer day without disruptions.</p>
<p>Average annual utilisation is always below the peak day. In winter demand falls, and some aircraft are parked or sent
for heavy maintenance; a few are kept in reserve for breakdowns; delays eat into schedule buffers. How much is lost
depends on the airline; the chart below uses a factor of 0.8 — our calibration for illustration, not a quote from a
source.</p>
{funnel}
<p class="small">Schematic: window 06:00–24:00, 2.5-block-hour sector, 25-minute turnaround — six flights by the formula
from the network section; the annual factor of 0.8 is an assumption.</p>
<p>When talking about utilisation it is easy to compare apples and oranges, so three clarifications. First, <b>block
hours and flight hours</b>. Block time runs from chocks off before departure to chocks on after landing, including taxi;
flight time counts only the time in the air. Taxi out and in takes about 20 minutes per flight{cite('n2-130')}, so on short
sectors there are 10–15 % fewer flight hours than block hours. Ryanair reports in flight hours; most carriers and the
calculator use block hours.</p>
<p>Second, <b>flying aircraft versus the whole fleet</b>. In financial year 2025, a Wizz Air aircraft that was flying logged
12 hours 28 minutes a day, while the average over the whole fleet came to 9 hours 51 minutes: on average 44 aircraft were
grounded by engine defects{cite('n1-009', 'n1-012')}. What matters for the cost of a flight is utilisation across the whole
fleet: the lease is paid for a grounded aircraft just the same.</p>
<p>Third, <b>peak month versus the year</b>. In summer an airline gets the most out of an aircraft, in winter it flies less:
easyJet in the UK flew 11.9 hours a day in September 2024 and 8.9 in January{cite('n1-055', 'n1-066')}. The annual lease is
divided by the annual average, not by the best month.</p></section>""",
               f"""<section><h2>Woraus sich die Auslastung zusammensetzt</h2>
<p>Beginnen wir mit einem Tag. Ein Flugzeug kann fliegen, solange die Flughäfen offen sind, auf denen es landet und von
denen es startet. Viele große Flughäfen in Europa haben nachts Verbote oder Kontingente, dort reicht das Betriebsfenster
einer Basis etwa von sechs Uhr morgens bis Mitternacht, rund 18 Stunden. Ein Naturgesetz ist das aber nicht: Viele
Flughäfen arbeiten rund um die Uhr — Istanbul, Doha{cite('n5-022')} und andere große Drehkreuze am Golf und in Asien —, und
dort wird nachts voll geflogen: Ein Nachtflug landet zur morgendlichen Umsteigewelle, späte Ankünfte und frühe Abflüge
werden über Nacht verknüpft. Der Chef von Qatar Airways nannte einen Rund-um-die-Uhr-Flughafen ausdrücklich einen Vorteil
gegenüber europäischen Konkurrenten{cite('n5-022')}. Selbst dort geht der Tag fast nie vollständig in Flüge auf, nur
begrenzt dann nicht mehr der Flughafen, sondern drei andere Dinge. Die Nachfrage: Nachts gibt es wenige Passagiere, und ein
Nachtflug wird billiger verkauft, außer auf Langstrecken- und Urlaubsrouten. Die Crews: Ein Nachtdienst ist kürzer als ein
Tagdienst — nach EASA-Regeln bei Dienstbeginn spätabends oder nachts bis 11 Stunden gegenüber 13 am Tag
{cite('n3-006', 'n3-005')}. Und die Wartung: Daily Checks und der A-Check finden am Boden statt, meist nachts an der Basis —
mehr dazu unten. Das 18-Stunden-Fenster in den Rechnungen unten ist daher der typische Fall einer Basis mit
Nachtbeschränkungen; eine Basis ohne sie hat ein breiteres Fenster von 20–22 Stunden, bezahlt es aber mit Nachtdiensten und
damit, dass für die Wartung eine andere Zeit gefunden werden muss. Innerhalb des Fensters fliegt das Flugzeug nicht nur:
Nach jeder Landung müssen Passagiere aussteigen, die Kabine gereinigt, getankt und neu eingestiegen werden — das ist der
Turnaround, bei Schmalrumpfflugzeugen eine halbe bis ganze Stunde. Außerdem muss ein stationiertes Flugzeug nachts zu Hause
sein, daher passt nur eine ganze Zahl von Hin- und Rückflügen ins Fenster, und der Rest, in den kein Paar mehr passt, geht
verloren. So werden aus 24 Stunden ein Spitzentag — das, was das Flugzeug an einem guten Sommertag ohne Störungen fliegt.</p>
<p>Die durchschnittliche Jahresauslastung liegt immer unter dem Spitzentag. Im Winter sinkt die Nachfrage, ein Teil der
Flugzeuge wird abgestellt oder in die schwere Wartung geschickt; einige werden als Reserve für Ausfälle gehalten;
Verspätungen fressen die Puffer im Flugplan. Wie viel verloren geht, hängt von der Airline ab; die Grafik unten nimmt einen
Faktor von 0,8 an — unsere Kalibrierung zur Veranschaulichung, kein Quellenzitat.</p>
{funnel}
<p class="small">Schema: Fenster 06:00–24:00, Strecke 2,5 Blockstunden, Turnaround 25 Minuten — sechs Flüge nach der Formel
aus dem Netz-Abschnitt; der Jahresfaktor 0,8 ist eine Annahme.</p>
<p>Bei der Auslastung vergleicht man leicht Äpfel mit Birnen, daher drei Klarstellungen. Erstens: <b>Blockstunden und
Flugstunden</b>. Die Blockzeit läuft vom Entfernen der Bremsklötze vor dem Abflug bis zum Anlegen nach der Landung,
einschließlich Rollen; die Flugzeit zählt nur die Zeit in der Luft. Rollen hin und zurück dauert etwa 20 Minuten pro Flug
{cite('n2-130')}, auf kurzen Strecken gibt es daher 10–15 % weniger Flug- als Blockstunden. Ryanair berichtet in Flugstunden,
die meisten Airlines und der Rechner in Blockstunden.</p>
<p>Zweitens: <b>fliegendes Flugzeug und ganze Flotte</b>. Im Geschäftsjahr 2025 flog ein fliegendes Wizz-Air-Flugzeug 12
Stunden 28 Minuten am Tag, im Schnitt über die ganze Flotte waren es 9 Stunden 51 Minuten: Im Mittel standen 44 Flugzeuge
wegen Triebwerksmängeln am Boden{cite('n1-009', 'n1-012')}. Für die Kosten eines Fluges zählt die Auslastung der ganzen
Flotte: Für ein stehendes Flugzeug wird das Leasing genauso gezahlt.</p>
<p>Drittens: <b>Spitzenmonat und Jahr</b>. Im Sommer holt eine Airline das Maximum aus dem Flugzeug, im Winter fliegt sie
weniger: easyJet in Großbritannien flog im September 2024 11,9 Stunden am Tag, im Januar 8,9{cite('n1-055', 'n1-066')}. Das
Jahresleasing wird durch das Jahresmittel geteilt, nicht durch den besten Monat.</p></section>""")

    # ── 3. аналитика: сколько летают ──────────────────────────────────────
    rows = [(f"{L(a)} · {L(y)}", m, rng, "var(--orange)" if (a if isinstance(a, str) else a[0]) in SOFT else "var(--sky)")
            for a, y, m, rng, *_ in AIR]
    dots = whisker(rows, lo=0, hi=16, ticks=(0, 4, 8, 12, 16), fmt=lambda v: n(v, 1), label_w=260)
    t_air = "".join(f"<tr><td>{e(L(a))}</td><td>{e(L(y))}</td><td class=r>{n(m, 1)}</td>"
                    f"<td class=r>{n(rng[0], 1)}–{n(rng[1], 1)}</td><td class=s>{e(L(note))}{cite(*ev)}</td></tr>"
                    for a, y, m, rng, ev, note in AIR)
    afl = "".join(f"<tr><td>{e(L(k))}</td>" + "".join(f"<td class=r>{n(v, 1)}</td>" for v in vs) + "</tr>"
                  for k, vs in AFL)
    real = T(f"""<section><h2>Сколько летают на самом деле</h2>
<p>На графике — средний налёт за год по отчётности авиакомпаний за 2023–2025 годы, в блок-часах на самолёт в сутки
(у Ryanair — в лётных). Точка — среднее за год; линия, где она есть, — от худшего месяца до лучшего или от всего
парка до летающих бортов. Оранжевым отмечены цифры, где среднее оценено по месяцам, взято из презентации или чтение
отчёта ещё не подтверждено.</p>
{dots}
<details><summary>Таблица с источниками</summary><div class="tw"><table><tr><th>Перевозчик</th><th>Год</th>
<th class=r>Среднее, ч/сут</th><th class=r>Диапазон</th><th>Оговорки</th></tr>{t_air}</table></div></details>
<p>Самое наглядное сравнение — внутри одной группы. «Аэрофлот» публикует подробную отчётность по трём своим
авиакомпаниям: налёт часов за год и парк на конец года{cite('n5-001', 'n5-002')}. Если разделить налёт на средний парк
и на число дней, получится налёт на самолёт в сутки:</p>
<div class="tw" style="max-width:520px"><table><tr><th>ч/сут на борт</th><th class=r>2022</th><th class=r>2023</th>
<th class=r>2024</th><th class=r>2025</th></tr>{afl}</table></div>
<p class="small">Налёт часов по Databook «Аэрофлота» ÷ средний парк (полусумма на начало и конец года) ÷ дней в году
{cite('n5-009', 'n5-010', 'n5-011', 'n5-012')}. Парк — все самолёты на балансе, включая стоящие; поэтому это налёт на
весь парк, а не на летающий борт.</p>
<p>«Победа» — лоукостер с одним типом, Boeing 737-800, и плотным челноком от баз — летает 12,7 часа в сутки, на уровне
лучших лоукостеров мира. «Аэрофлот» с хабом в Шереметьеве, волнами стыковок и дальними рейсами — 9,8, и этот налёт
быстро рос после 2022 года, когда парк сократился, а перевозки восстановились. «Россия» налетала в 2025 году меньше
пяти часов на самолёт в сутки. Отчёт не раскладывает, почему: в парке на балансе — все борта, летающие и стоящие, а
налёт по типам не публикуется. Но разница в два с половиной раза между авиакомпаниями одной группы с общими закупками,
техникой и правилами хорошо показывает главное: налёт задаёт не бренд и не страна, а то, как устроены сеть, парк и
обслуживание.</p>
<p>Та же картина за рубежом. Лоукостер не значит больше налёта: Allegiant летает на курорты несколько раз в неделю и
налётывает 6,3 часа в сутки, Spirit с плотной сетью — 11,1{cite('n1-020', 'n1-023')}. Сетевой перевозчик не значит
меньше: Copa с хабом в Панаме — около 11 часов{cite('n5-021')}, на уровне easyJet и Norwegian
{cite('n5-015', 'n5-016')}. Широкофюзеляжные самолёты на дальних рейсах летают больше всех — 14–15 часов в сутки у
British Airways и Virgin Atlantic в 2024 году{cite('n1-063', 'n1-062')}: длинный рейс почти не тратит времени на
обороты.</p>
<p>И отдельно о разговорах про «16 часов в сутки и больше». Такой налёт бывает — у отдельного самолёта в летний день, в
пиковый месяц, в плане на новый тип. В среднем за год по всему парку его не показывает ни одна открытая отчётность: даже
лучшие лоукостеры держат 12–13 часов, а летний месяц отдельной дочерней компании — 13{cite('n1-058', 'n5-017')}. Пиковый
день и средний год — разные величины, и для себестоимости важна вторая.</p></section>""",
             f"""<section><h2>How much aircraft really fly</h2>
<p>The chart shows average annual utilisation from airline reports for 2023–2025, in block hours per aircraft per day
(flight hours for Ryanair). The dot is the annual average; the line, where present, runs from the worst month to the
best or from the whole fleet to flying aircraft. Orange marks figures where the average was estimated from monthly data,
taken from a presentation, or where the reading of the report is not yet confirmed.</p>
{dots}
<details><summary>Table with sources</summary><div class="tw"><table><tr><th>Carrier</th><th>Year</th>
<th class=r>Average, h/day</th><th class=r>Range</th><th>Caveats</th></tr>{t_air}</table></div></details>
<p>The most telling comparison is within one group. Aeroflot publishes detailed reporting for its three airlines: flight
hours for the year and the year-end fleet{cite('n5-001', 'n5-002')}. Divide the hours by the average fleet and by the
number of days, and you get utilisation per aircraft per day:</p>
<div class="tw" style="max-width:520px"><table><tr><th>h/day per aircraft</th><th class=r>2022</th><th class=r>2023</th>
<th class=r>2024</th><th class=r>2025</th></tr>{afl}</table></div>
<p class="small">Flight hours from Aeroflot's Databook ÷ average fleet (mean of start and end of year) ÷ days in the year
{cite('n5-009', 'n5-010', 'n5-011', 'n5-012')}. The fleet is every aircraft on the balance sheet, including grounded ones;
so this is utilisation across the whole fleet, not per flying aircraft.</p>
<p>Pobeda — a low-cost carrier with a single type, the Boeing 737-800, and a dense shuttle from its bases — flies 12.7
hours a day, on a par with the world's best low-cost carriers. Aeroflot, with its Sheremetyevo hub, connecting banks and
long-haul flights, flies 9.8, and this figure grew quickly after 2022, when the fleet shrank and traffic recovered.
Rossiya flew less than five hours per aircraft per day in 2025. The report does not say why: the fleet on the balance
sheet includes every aircraft, flying and grounded, and utilisation by type is not published. But a two-and-a-half-fold
gap between airlines of one group with shared procurement, engineering and rules shows the main point well: utilisation
is set not by the brand or the country but by how the network, the fleet and maintenance are organised.</p>
<p>The picture is the same abroad. Low-cost does not mean more flying: Allegiant flies to resorts a few times a week and
logs 6.3 hours a day, Spirit with its dense network 11.1{cite('n1-020', 'n1-023')}. Network carrier does not mean less:
Copa with its Panama hub flies about 11 hours{cite('n5-021')}, on a par with easyJet and Norwegian
{cite('n5-015', 'n5-016')}. Widebodies on long-haul routes fly the most — 14–15 hours a day at British Airways and Virgin
Atlantic in 2024{cite('n1-063', 'n1-062')}: a long flight wastes almost no time on turnarounds.</p>
<p>And a separate word on talk of “16 hours a day or more”. Such utilisation does happen — for a single aircraft on a
summer day, in a peak month, in a plan for a new type. No public report shows it as an annual average across a whole
fleet: even the best low-cost carriers hold 12–13 hours, and the summer month of a single subsidiary 13
{cite('n1-058', 'n5-017')}. A peak day and an average year are different quantities, and for costs it is the second that
matters.</p></section>""",
             f"""<section><h2>Wie viel Flugzeuge wirklich fliegen</h2>
<p>Die Grafik zeigt die durchschnittliche Jahresauslastung aus Airline-Berichten für 2023–2025, in Blockstunden je
Flugzeug und Tag (bei Ryanair in Flugstunden). Der Punkt ist das Jahresmittel; die Linie, wo vorhanden, reicht vom
schlechtesten zum besten Monat oder von der ganzen Flotte zu den fliegenden Flugzeugen. Orange markiert Werte, bei denen
das Mittel aus Monatsdaten geschätzt, einer Präsentation entnommen oder die Lesung des Berichts noch nicht bestätigt
ist.</p>
{dots}
<details><summary>Tabelle mit Quellen</summary><div class="tw"><table><tr><th>Airline</th><th>Jahr</th>
<th class=r>Mittel, h/Tag</th><th class=r>Spanne</th><th>Vorbehalte</th></tr>{t_air}</table></div></details>
<p>Am anschaulichsten ist der Vergleich innerhalb einer Gruppe. Aeroflot veröffentlicht detaillierte Zahlen für seine drei
Airlines: Flugstunden im Jahr und Flotte zum Jahresende{cite('n5-001', 'n5-002')}. Teilt man die Stunden durch die
durchschnittliche Flotte und die Zahl der Tage, ergibt sich die Auslastung je Flugzeug und Tag:</p>
<div class="tw" style="max-width:520px"><table><tr><th>h/Tag je Flugzeug</th><th class=r>2022</th><th class=r>2023</th>
<th class=r>2024</th><th class=r>2025</th></tr>{afl}</table></div>
<p class="small">Flugstunden laut Aeroflot-Databook ÷ durchschnittliche Flotte (Mittel aus Jahresanfang und -ende) ÷ Tage im
Jahr{cite('n5-009', 'n5-010', 'n5-011', 'n5-012')}. Die Flotte umfasst alle Flugzeuge in der Bilanz, auch stehende; es ist
also die Auslastung der ganzen Flotte, nicht je fliegendes Flugzeug.</p>
<p>Pobeda — ein Low-Cost-Carrier mit nur einem Typ, der Boeing 737-800, und dichtem Pendelverkehr ab den Basen — fliegt
12,7 Stunden am Tag, auf dem Niveau der besten Low-Cost-Airlines der Welt. Aeroflot mit dem Hub Scheremetjewo,
Umsteigewellen und Langstrecken kommt auf 9,8, und dieser Wert stieg nach 2022 schnell, als die Flotte schrumpfte und der
Verkehr sich erholte. Rossiya flog 2025 weniger als fünf Stunden je Flugzeug und Tag. Warum, sagt der Bericht nicht: In der
Bilanzflotte stehen alle Flugzeuge, fliegende und stehende, und die Auslastung nach Typen wird nicht veröffentlicht. Doch
der Unterschied um das Zweieinhalbfache zwischen Airlines einer Gruppe mit gemeinsamem Einkauf, gemeinsamer Technik und
gemeinsamen Regeln zeigt das Wesentliche: Die Auslastung bestimmen nicht Marke oder Land, sondern der Aufbau von Netz,
Flotte und Wartung.</p>
<p>Im Ausland dasselbe Bild. Low-Cost heißt nicht mehr Flugstunden: Allegiant fliegt einige Male pro Woche zu
Urlaubszielen und kommt auf 6,3 Stunden am Tag, Spirit mit dichtem Netz auf 11,1{cite('n1-020', 'n1-023')}. Netzwerk-Airline
heißt nicht weniger: Copa mit dem Hub in Panama fliegt rund 11 Stunden{cite('n5-021')}, so viel wie easyJet und Norwegian
{cite('n5-015', 'n5-016')}. Großraumflugzeuge auf der Langstrecke fliegen am meisten — 14–15 Stunden am Tag bei British
Airways und Virgin Atlantic 2024{cite('n1-063', 'n1-062')}: Ein langer Flug verliert kaum Zeit mit Turnarounds.</p>
<p>Und gesondert zum Gerede von „16 Stunden am Tag und mehr“. Solche Werte gibt es — für ein einzelnes Flugzeug an einem
Sommertag, in einem Spitzenmonat, im Plan für einen neuen Typ. Als Jahresmittel über eine ganze Flotte zeigt ihn kein
öffentlicher Bericht: Selbst die besten Low-Cost-Airlines halten 12–13 Stunden, der Sommermonat einer einzelnen Tochter
13{cite('n1-058', 'n5-017')}. Spitzentag und Jahresmittel sind verschiedene Größen, und für die Kosten zählt die
zweite.</p></section>""")

    # ── 4. как построить сеть ─────────────────────────────────────────────
    xs = list(range(45, 301, 15))

    def lab(w, t):
        return T(f"окно {w} ч, оборот {t} мин", f"window {w} h, turnaround {t} min", f"Fenster {w} h, Turnaround {t} min")
    ser = []
    for tat, col in ((25, "var(--sky)"), (45, "var(--orange)")):
        ser.append((lab(18, tat), col, {m: util_day(18, tat, m / 60)[0] for m in xs}, False))
    ser.append((lab(19, 25), "var(--green)", {m: util_day(19, 25, m / 60)[0] for m in xs}, True))
    ser.append((lab(21, 25), "var(--t3)", {m: util_day(21, 25, m / 60)[0] for m in xs}, True))
    chart = line_chart(ser, w=720, ylab=T("блок-часов в пиковый день", "block hours on a peak day",
                                          "Blockstunden am Spitzentag"), yfmt=lambda v: n(v), x_every=60)
    t_cur = "".join(f"<tr><td>{e(L(a))}</td><td>{e(L(r))}{cite(*ev)}</td></tr>" for a, r, ev in CURFEW)
    day = svg.day([(T("Плечо 1,5 часа, оборот 25 минут", "1.5-hour sector, 25-minute turnaround",
                      "1,5-Stunden-Strecke, 25 Minuten Turnaround"), 1.5, 25, 8,
                    [(T("утро", "morning", "Früh"), 1, 4), (T("вечер", "evening", "Spät"), 5, 8)]),
                   (T("Плечо 2,5 часа, оборот 25 минут", "2.5-hour sector, 25-minute turnaround",
                      "2,5-Stunden-Strecke, 25 Minuten Turnaround"), 2.5, 25, 6,
                    [(T("утро", "morning", "Früh"), 1, 2), (T("день", "midday", "Mittag"), 3, 4),
                     (T("вечер", "evening", "Spät"), 5, 6)])])
    pat = svg.patterns()
    howto = T(f"""<section><h2>Как построить сеть, чтобы летать больше</h2>
<h3>База — это первый утренний вылет</h3>
<p>Сеть лоукостера строится вокруг баз: самолёт ночует на базе, утром уходит первой волной, днём делает несколько рейсов
и вечером возвращается домой. В Дублине первая волна Ryanair уходит между 06:00 и 07:00{cite('n2-101')}. Ценность базы — в
этом утреннем слоте: если самолёт не может вылететь рано, он теряет целый рейс, и экономика базового самолёта не
сходится{cite('n2-123')}. Поэтому первое, что смотрят при выборе базы, — ночной режим аэропорта, и не только базы, но
и пунктов назначения: последний рейс дня должен успеть сесть дома до запрета.</p>
<div class="tw"><table><tr><th>Аэропорт</th><th>Ночные ограничения</th></tr>{t_cur}</table></div>
<p>Чем шире окно базы, тем больше пар в него влезает. Аэропорты с запретом с 23:00 до 05:00–06:00 режут окно с двух
сторон, а привилегии базирующимся перевозчикам, как в Дюссельдорфе, где опоздавшим базовым самолётам разрешают
садиться до полуночи{cite('n2-043')}, наоборот, удлиняют его. Круглосуточная база позволяет поставить поздний
прилёт и ранний вылет — тогда окно растягивается до 20–22 часов, а ограничивать начинают ночные смены экипажей и
время, которое нужно самолёту на земле для обслуживания.</p>
<h3>Длина плеча — под целое число пар</h3>
<p>Самолёт базы делает целое число пар «туда-обратно». Сколько их влезает в окно, считается так: рейсов =
⌊(окно + оборот) ÷ (блок-время + оборот)⌋, а для челнока — до ближайшего чётного, чтобы последний рейс вернул самолёт
домой. Из-за округления зависимость пилообразная{cite('n2-139')}: пока плечо растёт, налёт растёт вместе с ним, но как
только последняя пара перестаёт помещаться в окно, налёт падает ступенькой. Лишние 15 минут на плече могут стоить
целой пары рейсов.</p>
{chart}
<p class="small">По горизонтали — блок-время плеча в минутах, по вертикали — блок-часы самолёта в пиковый день при окне
18 часов (06:00–24:00), 19 и 21 час (база без ночного запрета). Блок-время уже включает руление, поэтому между рейсами
добавляется только оборот. Это потолок без задержек, ТО и ограничений экипажей, а не прогноз.</p>
<p>Отсюда правило планирования: длину плеча и оборот подбирают так, чтобы пары заполняли окно без остатка. При окне
18 часов и обороте 25 минут хорошо ложатся плечи около 1,5, 2–2,5 и 4 часов; плечо в 3 часа хуже двухчасового в
пересчёте на день. Если пункт назначения неудобный по длине, остаток окна добирают другими схемами — о них ниже.</p>
<h3>Короткий оборот — главный рычаг коротких плеч</h3>
<p>Чем короче плечо, тем больше в сутках оборотов и тем сильнее налёт зависит от их длины. По данным EUROCONTROL за
2015–2019 годы, средний плановый оборот узкофюзеляжного самолёта в Европе — 48–49 минут, фактический — 53–55; у
широкофюзеляжных — 80–92 и 86–97 минут{cite('n2-071', 'n2-072', 'n2-069', 'n2-070')}. Более свежей сводки в открытом
доступе мы не нашли. Лоукостеры укорачивают оборот за счёт посадки без телетрапа, одного класса, отказа от питания и
уборки силами экипажа; на графике видно, что при плече в час разница между 25 и 45 минутами — пара рейсов в день.</p>
<h3>Экипаж решает, сколько смен держит самолёт</h3>
<p>Схема ниже показывает пиковый день самолёта для двух длин плеча и смены экипажей, которые его обслуживают. При
плече в полтора часа самолёт делает восемь рейсов, и его закрывают два экипажа — утренний и вечерний — по четыре
сектора. При плече в 2,5 часа рейсов шесть, налёт больше, но четыре сектора уже не влезают в разрешённую смену: по
правилам EASA при начале смены утром это 12 часов при четырёх секторах{cite('n3-005')}, а четыре рейса по 2,5 часа с
тремя оборотами и явкой за час до вылета — больше 12. Значит, экипажей в сутки нужно три, каждый на одну пару. Налёт
самолёта растёт, а налёт на экипаж падает: это важно для расчёта, к этому вернёмся в разделе об экипажах.</p>
{day}
<p class="small">Схема: окно с 06:00, оборот 25 минут, явка экипажа за час до первого вылета (допущение). Смена считается
от явки до посадки последнего рейса.</p>
<h3>Ротации: челнок, W и волны хаба</h3>
<p>Простейшая схема — челнок от базы: пары «туда-обратно» в один и тот же или в разные пункты, ночёвка дома. Экипаж
каждый вечер возвращается на базу, гостиницы не нужны. Её недостаток — пропадает остаток окна, в который не влезает
пара. Чартерные перевозчики, которые возят туристов на курорты, строят экономику на двух полных ротациях в сутки, и
потеря раннего или позднего слота ломает схему ступенькой{cite('n2-124', 'n2-127')}.</p>
<p>Остаток окна добирают W-ротациями: самолёт летит с базы в A, возвращается, летит в B, оттуда в C и домой, — или
ночует вне базы. Так можно использовать неудобные по длине плечи, но приходится платить за гостиницу экипажа и ночную
стоянку не дома.</p>
{pat}
<p>Сетевой перевозчик устроен иначе: все рейсы идут через хаб — узловой аэропорт, где пассажиры пересаживаются, — а
самолёт летает между хабом и городами сети туда и обратно (в английском такую схему называют hub-and-spoke, «ступица и
спицы»). Чтобы пересадки были короткими, рейсы собирают в волны: самолёты из разных городов прилетают в хаб к одному
окну, пассажиры пересаживаются, и самолёты почти одновременно улетают. В Цюрихе у SWISS шесть волн с 06:10 до 22:45 при
минимальном времени стыковки 40 минут{cite('n2-087', 'n2-088', 'n2-089')}. Плата за удобные стыковки — налёт: между волнами
самолёт ждёт. American Airlines, отказавшись в начале 2000-х от жёстких волн в части хабов, подняла налёт ценой более
долгих стыковок — в среднем на шесть минут{cite('n2-053', 'n2-054')}.</p>
<p>Дальние рейсы ставят по часовым поясам: ночной рейс прилетает утром к первой волне хаба, днём самолёт летит обратно.
Ночное окно используют и узкофюзеляжные самолёты там, где аэропорты открыты: у Southwest в пиковый день больше 50 ночных
рейсов{cite('n2-021')}.</p></section>""",
              f"""<section><h2>How to build a network that flies more</h2>
<h3>A base is the first morning departure</h3>
<p>A low-cost network is built around bases: the aircraft spends the night at base, leaves with the first wave in the
morning, flies several sectors during the day and returns home in the evening. In Dublin Ryanair's first wave departs
between 06:00 and 07:00{cite('n2-101')}. The value of a base lies in that morning slot: if the aircraft cannot leave early,
it loses a whole flight, and the economics of a based aircraft do not add up{cite('n2-123')}. So the first thing checked
when choosing a base is the airport's night regime — not only at the base but at the destinations too: the last flight
of the day must land at home before the curfew.</p>
<div class="tw"><table><tr><th>Airport</th><th>Night restrictions</th></tr>{t_cur}</table></div>
<p>The wider a base's window, the more pairs fit into it. Airports with a ban from 23:00 to 05:00–06:00 cut the window
at both ends, while privileges for based carriers — as in Düsseldorf, where delayed based aircraft may land until
midnight{cite('n2-043')} — lengthen it. A 24-hour base allows a late arrival and an early departure — the window then
stretches to 20–22 hours, and the limits become crew night duties and the time the aircraft needs on the ground for
maintenance.</p>
<h3>Sector length — for a whole number of pairs</h3>
<p>A based aircraft flies a whole number of out-and-back pairs. How many fit into the window is calculated as: flights =
⌊(window + turnaround) ÷ (block time + turnaround)⌋, and for a shuttle rounded down to an even number, so that the last
flight brings the aircraft home. Because of the rounding the relationship is a sawtooth{cite('n2-139')}: as the sector
grows, utilisation grows with it, but as soon as the last pair no longer fits into the window, utilisation drops by a
step. An extra 15 minutes on the sector can cost a whole pair of flights.</p>
{chart}
<p class="small">Horizontal axis — sector block time in minutes; vertical — aircraft block hours on a peak day with an
18-hour window (06:00–24:00), 19 and 21 hours (a base without a night ban). Block time already includes taxi, so only the
turnaround is added between flights. This is a ceiling without delays, maintenance or crew limits, not a forecast.</p>
<p>Hence the planning rule: sector length and turnaround are chosen so that the pairs fill the window with nothing left
over. With an 18-hour window and 25-minute turnarounds, sectors of about 1.5, 2–2.5 and 4 hours fit well; a 3-hour sector
is worse than a 2-hour one per day. If a destination has an awkward length, the rest of the window is filled with other
patterns — see below.</p>
<h3>A short turnaround is the main lever on short sectors</h3>
<p>The shorter the sector, the more turnarounds per day and the more utilisation depends on their length. According to
EUROCONTROL data for 2015–2019, the average scheduled turnaround of a narrowbody in Europe is 48–49 minutes, the actual
53–55; for widebodies 80–92 and 86–97 minutes{cite('n2-071', 'n2-072', 'n2-069', 'n2-070')}. We found no more recent public
summary. Low-cost carriers shorten the turnaround by boarding without jet bridges, a single class, no catering and
cleaning by the cabin crew; the chart shows that on a one-hour sector the difference between 25 and 45 minutes is a pair
of flights a day.</p>
<h3>The crew decides how many duties the aircraft needs</h3>
<p>The diagram below shows an aircraft's peak day for two sector lengths and the crew duties covering it. With
one-and-a-half-hour sectors the aircraft flies eight flights, covered by two crews — morning and evening — of four
sectors each. With 2.5-hour sectors there are six flights and more utilisation, but four sectors no longer fit into an
allowed duty: under EASA rules, a duty starting in the morning is limited to 12 hours with four sectors
{cite('n3-005')}, while four 2.5-hour flights with three turnarounds and reporting an hour before departure take more than
12. So three crews a day are needed, each flying one pair. Aircraft utilisation goes up while hours per crew go down:
this matters for the calculation, and we come back to it in the crew section.</p>
{day}
<p class="small">Schematic: window from 06:00, 25-minute turnaround, crew reports an hour before the first departure
(assumption). The duty runs from report to the landing of the last flight.</p>
<h3>Rotations: shuttle, W and hub banks</h3>
<p>The simplest pattern is the base shuttle: out-and-back pairs to the same or different points, night at home. The crew
returns to base every evening, no hotels are needed. Its drawback is that the rest of the window that a pair does not fit
into is lost. Charter carriers flying tourists to resorts build their economics on two full rotations a day, and losing
an early or late slot breaks the pattern by a step{cite('n2-124', 'n2-127')}.</p>
<p>The rest of the window is filled with W rotations: the aircraft flies from base to A, comes back, flies to B, from
there to C and home — or spends the night away from base. This makes use of awkwardly long sectors, but costs a crew
hotel and an overnight stand away from home.</p>
{pat}
<p>A network carrier works differently: all flights go through a hub — a connecting airport where passengers change
planes — and aircraft fly back and forth between the hub and the cities of the network (the hub-and-spoke model). To keep
connections short, flights are grouped into banks: aircraft from different cities arrive at the hub within one window,
passengers transfer, and the aircraft leave almost at once. SWISS in Zurich has six banks between 06:10 and 22:45 with a
minimum connecting time of 40 minutes{cite('n2-087', 'n2-088', 'n2-089')}. Convenient connections are paid for with
utilisation: between banks the aircraft waits. American Airlines, abandoning rigid banks at some hubs in the early 2000s,
raised utilisation at the cost of longer connections — six minutes on average{cite('n2-053', 'n2-054')}.</p>
<p>Long-haul flights are scheduled around time zones: a night flight arrives in the morning for the hub's first bank, and
the aircraft flies back during the day. Narrowbodies also use the night window where airports are open: Southwest has
more than 50 overnight flights on a peak day{cite('n2-021')}.</p></section>""",
              f"""<section><h2>Wie man ein Netz baut, um mehr zu fliegen</h2>
<h3>Eine Basis ist der erste Morgenabflug</h3>
<p>Das Netz eines Low-Cost-Carriers ist um Basen gebaut: Das Flugzeug übernachtet an der Basis, startet morgens mit der
ersten Welle, fliegt tagsüber mehrere Strecken und kehrt abends heim. In Dublin startet die erste Ryanair-Welle zwischen
06:00 und 07:00{cite('n2-101')}. Der Wert einer Basis liegt in diesem Morgenslot: Kann das Flugzeug nicht früh starten,
verliert es einen ganzen Flug, und die Wirtschaftlichkeit des stationierten Flugzeugs geht nicht auf{cite('n2-123')}. Deshalb
prüft man bei der Wahl einer Basis zuerst die Nachtregelung des Flughafens — nicht nur der Basis, sondern auch der Ziele:
Der letzte Flug des Tages muss vor dem Verbot zu Hause landen.</p>
<div class="tw"><table><tr><th>Flughafen</th><th>Nachtbeschränkungen</th></tr>{t_cur}</table></div>
<p>Je breiter das Fenster der Basis, desto mehr Paare passen hinein. Flughäfen mit Verbot von 23:00 bis 05:00–06:00
beschneiden das Fenster an beiden Enden, Vorrechte für stationierte Airlines dagegen — wie in Düsseldorf, wo verspätete
Basisflugzeuge bis Mitternacht landen dürfen{cite('n2-043')} — verlängern es. Eine Rund-um-die-Uhr-Basis erlaubt eine späte
Ankunft und einen frühen Abflug — dann dehnt sich das Fenster auf 20–22 Stunden, und begrenzend wirken Nachtdienste der
Crews und die Zeit, die das Flugzeug am Boden für die Wartung braucht.</p>
<h3>Streckenlänge — für eine ganze Zahl von Paaren</h3>
<p>Ein stationiertes Flugzeug fliegt eine ganze Zahl von Hin- und Rückflügen. Wie viele ins Fenster passen, rechnet man so:
Flüge = ⌊(Fenster + Turnaround) ÷ (Blockzeit + Turnaround)⌋, beim Pendel abgerundet auf eine gerade Zahl, damit der letzte
Flug das Flugzeug nach Hause bringt. Wegen der Rundung verläuft der Zusammenhang sägezahnförmig{cite('n2-139')}: Solange
die Strecke wächst, wächst die Auslastung mit, doch sobald das letzte Paar nicht mehr ins Fenster passt, fällt sie
stufenweise. 15 Minuten mehr auf der Strecke können ein ganzes Flugpaar kosten.</p>
{chart}
<p class="small">Horizontal — Blockzeit der Strecke in Minuten, vertikal — Blockstunden des Flugzeugs am Spitzentag bei einem
Fenster von 18 Stunden (06:00–24:00), 19 und 21 Stunden (Basis ohne Nachtflugverbot). Die Blockzeit enthält das Rollen
bereits, zwischen den Flügen kommt nur der Turnaround hinzu. Das ist eine Obergrenze ohne Verspätungen, Wartung und
Crew-Grenzen, keine Prognose.</p>
<p>Daraus folgt die Planungsregel: Streckenlänge und Turnaround werden so gewählt, dass die Paare das Fenster ohne Rest
füllen. Bei 18-Stunden-Fenster und 25 Minuten Turnaround passen Strecken von etwa 1,5, 2–2,5 und 4 Stunden gut; eine
3-Stunden-Strecke ist pro Tag schlechter als eine 2-Stunden-Strecke. Ist ein Ziel ungünstig lang, wird der Rest des
Fensters mit anderen Mustern gefüllt — dazu unten mehr.</p>
<h3>Kurzer Turnaround — der wichtigste Hebel auf kurzen Strecken</h3>
<p>Je kürzer die Strecke, desto mehr Turnarounds am Tag und desto stärker hängt die Auslastung von ihrer Länge ab. Laut
EUROCONTROL-Daten für 2015–2019 beträgt der durchschnittliche geplante Turnaround eines Schmalrumpfflugzeugs in Europa
48–49 Minuten, der tatsächliche 53–55; bei Großraumflugzeugen 80–92 und 86–97 Minuten
{cite('n2-071', 'n2-072', 'n2-069', 'n2-070')}. Eine neuere öffentliche Übersicht haben wir nicht gefunden. Low-Cost-Airlines
verkürzen den Turnaround durch Einsteigen ohne Fluggastbrücke, eine Klasse, Verzicht auf Catering und Reinigung durch die
Crew; die Grafik zeigt, dass bei einer Einstundenstrecke der Unterschied zwischen 25 und 45 Minuten ein Flugpaar pro Tag
ausmacht.</p>
<h3>Die Crew entscheidet, wie viele Dienste das Flugzeug braucht</h3>
<p>Das Schema unten zeigt den Spitzentag eines Flugzeugs für zwei Streckenlängen und die Crew-Dienste dazu. Bei
anderthalbstündigen Strecken fliegt das Flugzeug acht Flüge, abgedeckt von zwei Crews — Früh und Spät — mit je vier
Sektoren. Bei 2,5-Stunden-Strecken sind es sechs Flüge und mehr Auslastung, doch vier Sektoren passen nicht mehr in einen
zulässigen Dienst: Nach EASA-Regeln sind bei Dienstbeginn am Morgen mit vier Sektoren 12 Stunden erlaubt
{cite('n3-005')}, vier Flüge à 2,5 Stunden mit drei Turnarounds und Meldezeit eine Stunde vor dem Abflug ergeben mehr als 12.
Also braucht man drei Crews am Tag, jede für ein Paar. Die Auslastung des Flugzeugs steigt, die Flugstunden je Crew sinken:
Das ist für die Rechnung wichtig, wir kommen im Crew-Abschnitt darauf zurück.</p>
{day}
<p class="small">Schema: Fenster ab 06:00, Turnaround 25 Minuten, Meldezeit der Crew eine Stunde vor dem ersten Abflug
(Annahme). Der Dienst zählt von der Meldung bis zur Landung des letzten Fluges.</p>
<h3>Rotationen: Pendel, W und Hub-Wellen</h3>
<p>Das einfachste Muster ist der Pendel ab der Basis: Hin- und Rückflüge zum selben oder zu verschiedenen Zielen, Nacht zu
Hause. Die Crew kehrt jeden Abend zur Basis zurück, Hotels sind nicht nötig. Der Nachteil: Der Rest des Fensters, in den kein
Paar passt, geht verloren. Charter-Airlines, die Touristen in Urlaubsorte fliegen, bauen ihre Wirtschaftlichkeit auf zwei
vollen Rotationen am Tag auf, und der Verlust eines frühen oder späten Slots bricht das Muster stufenweise
{cite('n2-124', 'n2-127')}.</p>
<p>Den Rest des Fensters füllen W-Rotationen: Das Flugzeug fliegt von der Basis nach A, zurück, nach B, von dort nach C und
heim — oder übernachtet außerhalb der Basis. So lassen sich ungünstig lange Strecken nutzen, kosten aber Crew-Hotel und
Nachtabstellung außerhalb.</p>
{pat}
<p>Eine Netzwerk-Airline funktioniert anders: Alle Flüge gehen über einen Hub — einen Umsteigeflughafen —, und die Flugzeuge
pendeln zwischen dem Hub und den Städten des Netzes (das Hub-and-Spoke-Modell). Damit die Umstiege kurz sind, werden die
Flüge zu Wellen gebündelt: Flugzeuge aus verschiedenen Städten landen in einem Zeitfenster am Hub, die Passagiere steigen um,
und die Flugzeuge starten fast gleichzeitig. SWISS hat in Zürich sechs Wellen von 06:10 bis 22:45 bei einer
Mindestumsteigezeit von 40 Minuten{cite('n2-087', 'n2-088', 'n2-089')}. Bequeme Anschlüsse bezahlt man mit Auslastung:
Zwischen den Wellen wartet das Flugzeug. American Airlines gab Anfang der 2000er-Jahre an einigen Hubs die starren Wellen
auf und steigerte die Auslastung auf Kosten längerer Umsteigezeiten — im Schnitt um sechs Minuten
{cite('n2-053', 'n2-054')}.</p>
<p>Langstreckenflüge werden nach Zeitzonen geplant: Ein Nachtflug landet morgens zur ersten Welle des Hubs, tagsüber fliegt
das Flugzeug zurück. Auch Schmalrumpfflugzeuge nutzen das Nachtfenster, wo Flughäfen offen sind: Southwest hat an einem
Spitzentag mehr als 50 Nachtflüge{cite('n2-021')}.</p></section>""")

    # ── 5. экипажи ────────────────────────────────────────────────────────
    crews = "".join(f"<tr><td class=r>{h}</td><td class=r>{n(h * 365)}</td>"
                    f"<td class=r>{n(h * 365 / 900, 1)}</td><td class=r>{n(h * 365 / 750, 1)}</td>"
                    f"<td class=r>{n(h * 365 / 600, 1)}</td></tr>" for h in (8, 10, 13))
    crew = T(f"""<section><h2>Экипажи: что на самом деле ограничивает</h2>
<p>Суточная смена экипажа редко ограничивает налёт самолёта: самолёт держат несколько смен, как на схеме выше. Правила
EASA при начале смены с 06:00 до 13:29 разрешают до 13 часов при одном-двух секторах и на полчаса меньше за каждый
следующий — 12 часов при четырёх{cite('n3-005')}. Схема лоукостера «два раза туда-обратно» на плечах до двух часов
укладывается в это с запасом; утренний и вечерний экипажи вместе дают самолёту 14–16 часов{cite('n3-059')}.</p>
<p>Сколько экипажей нужно на самолёт, решают месячные и годовые лимиты. EASA ограничивает налёт пилота 100 часами
за 28 дней и 900 часами за календарный год{cite('n3-007', 'n3-008')}; в России с 1 марта 2026 года по приказу
Минтранса №381 — 80 часов в месяц и 800 в год, а с согласия пилота — до 90 и 900{cite('n3-025', 'n3-027')}. Отдых между
сменами — не меньше удвоенной смены, на базе — не меньше 12 часов, еженедельный отдых — 42 часа
{cite('n3-029', 'n3-030')}. Значит, число экипажей на самолёт = годовые блок-часы самолёта ÷ годовой налёт пилота.</p>
<div class="tw" style="max-width:640px"><table><tr><th class=r>Налёт борта, ч/сут</th><th class=r>Часов в год</th>
<th class=r>Экипажей при 900 ч</th><th class=r>при 750 ч</th><th class=r>при 600 ч</th></tr>{crews}</table></div>
<p class="small">Без резерва на болезни, отпуска и обучение. 900 часов — потолок EASA; на практике пилот налётывает
меньше.</p>
<p>Реальные цифры заметно ниже потолка. У IndiGo в 2025 финансовом году — около 567 блок-часов на пилота и 6,3 экипажа
на самолёт{cite('n3-043')}. В группе «Аэрофлот» в 2025 году на 352 самолёта приходилось 4 319 пилотов — около 12 на
самолёт; если на каждом рейсе два пилота, это около 490 часов налёта на пилота в год{cite('n5-014')}. Это оценка сверху
по числу пилотов: на дальних рейсах в кабине больше двух человек, а в лётном составе — резерв, стажёры, отпуска.
Разница между 490 и 900 часами — запас, за который тоже платят.</p>
<p>Отсюда главный вывод для расчёта: налёт самолёта удешевляет час только по владению. Лизинг за месяц один и тот же
при 8 и 13 часах в сутки, а экипажей при 13 часах нужно больше, и на час полёта экипаж не дешевеет. Если же из-за
длины плеча экипаж закрывает только одну пару за смену, как на схеме с 2,5-часовым плечом, экипаж на час даже
дорожает.</p></section>""",
             f"""<section><h2>Crews: what really limits</h2>
<p>A crew's daily duty rarely limits aircraft utilisation: the aircraft is covered by several duties, as in the diagram
above. EASA rules allow up to 13 hours for a duty starting between 06:00 and 13:29 with one or two sectors, and half an
hour less for each additional one — 12 hours with four{cite('n3-005')}. The low-cost “two out-and-backs” pattern on
sectors of up to two hours fits within this with room to spare; morning and evening crews together give the aircraft
14–16 hours{cite('n3-059')}.</p>
<p>How many crews an aircraft needs is decided by monthly and annual limits. EASA caps a pilot's flight time at 100 hours
in 28 days and 900 hours in a calendar year{cite('n3-007', 'n3-008')}; in Russia, from 1 March 2026 under Ministry of
Transport Order No. 381, it is 80 hours a month and 800 a year, and with the pilot's consent up to 90 and 900
{cite('n3-025', 'n3-027')}. Rest between duties is at least twice the duty, at base at least 12 hours, weekly rest 42 hours
{cite('n3-029', 'n3-030')}. So crews per aircraft = aircraft annual block hours ÷ a pilot's annual flight hours.</p>
<div class="tw" style="max-width:640px"><table><tr><th class=r>Aircraft utilisation, h/day</th><th class=r>Hours a year</th>
<th class=r>Crews at 900 h</th><th class=r>at 750 h</th><th class=r>at 600 h</th></tr>{crews}</table></div>
<p class="small">Without reserve for sickness, leave and training. 900 hours is the EASA ceiling; in practice a pilot flies
less.</p>
<p>Real figures are well below the ceiling. At IndiGo in financial year 2025 — about 567 block hours per pilot and 6.3
crews per aircraft{cite('n3-043')}. In the Aeroflot group in 2025 there were 4,319 pilots for 352 aircraft — about 12 per
aircraft; with two pilots on each flight, that is about 490 flight hours per pilot a year{cite('n5-014')}. This is an
upper-bound estimate from pilot numbers: long-haul cockpits carry more than two people, and the flight crew headcount
includes reserves, trainees and people on leave. The gap between 490 and 900 hours is a buffer that also has to be paid
for.</p>
<p>Hence the main conclusion for the calculation: higher aircraft utilisation makes an hour cheaper only on ownership.
The monthly lease is the same at 8 and at 13 hours a day, but at 13 hours more crews are needed, and the crew cost per
flight hour does not fall. And if the sector length means a crew covers only one pair per duty, as in the diagram with
the 2.5-hour sector, crew cost per hour actually rises.</p></section>""",
             f"""<section><h2>Crews: was wirklich begrenzt</h2>
<p>Der Tagesdienst einer Crew begrenzt die Auslastung selten: Das Flugzeug wird von mehreren Diensten abgedeckt, wie im
Schema oben. Die EASA-Regeln erlauben bei Dienstbeginn zwischen 06:00 und 13:29 bis zu 13 Stunden mit ein oder zwei
Sektoren und eine halbe Stunde weniger für jeden weiteren — 12 Stunden bei vier{cite('n3-005')}. Das Low-Cost-Muster
„zweimal hin und zurück“ auf Strecken bis zwei Stunden passt mit Reserve hinein; Früh- und Spät-Crew zusammen geben dem
Flugzeug 14–16 Stunden{cite('n3-059')}.</p>
<p>Wie viele Crews ein Flugzeug braucht, bestimmen Monats- und Jahresgrenzen. Die EASA begrenzt die Flugzeit eines
Piloten auf 100 Stunden in 28 Tagen und 900 Stunden im Kalenderjahr{cite('n3-007', 'n3-008')}; in Russland gelten seit dem
1. März 2026 nach Verordnung Nr. 381 des Verkehrsministeriums 80 Stunden im Monat und 800 im Jahr, mit Zustimmung des
Piloten bis 90 und 900{cite('n3-025', 'n3-027')}. Die Ruhezeit zwischen Diensten beträgt mindestens das Doppelte des
Dienstes, an der Basis mindestens 12 Stunden, die Wochenruhe 42 Stunden{cite('n3-029', 'n3-030')}. Also gilt: Crews je
Flugzeug = Jahresblockstunden des Flugzeugs ÷ Jahresflugstunden eines Piloten.</p>
<div class="tw" style="max-width:640px"><table><tr><th class=r>Auslastung, h/Tag</th><th class=r>Stunden im Jahr</th>
<th class=r>Crews bei 900 h</th><th class=r>bei 750 h</th><th class=r>bei 600 h</th></tr>{crews}</table></div>
<p class="small">Ohne Reserve für Krankheit, Urlaub und Schulung. 900 Stunden sind die EASA-Obergrenze; in der Praxis fliegt
ein Pilot weniger.</p>
<p>Die realen Zahlen liegen deutlich darunter. Bei IndiGo im Geschäftsjahr 2025 — etwa 567 Blockstunden je Pilot und 6,3
Crews je Flugzeug{cite('n3-043')}. In der Aeroflot-Gruppe kamen 2025 auf 352 Flugzeuge 4.319 Piloten — etwa 12 je Flugzeug;
bei zwei Piloten pro Flug sind das rund 490 Flugstunden je Pilot und Jahr{cite('n5-014')}. Das ist eine Schätzung nach
oben aus der Pilotenzahl: Auf Langstrecken sitzen mehr als zwei Personen im Cockpit, und zum fliegenden Personal gehören
Reserve, Auszubildende und Urlauber. Der Abstand zwischen 490 und 900 Stunden ist ein Puffer, der ebenfalls bezahlt
wird.</p>
<p>Daraus folgt der wichtigste Schluss für die Rechnung: Mehr Auslastung verbilligt die Stunde nur beim Besitz. Die
Monatsleasingrate ist bei 8 und bei 13 Stunden am Tag dieselbe, bei 13 Stunden braucht man aber mehr Crews, und die Crew
wird je Flugstunde nicht billiger. Deckt eine Crew wegen der Streckenlänge nur ein Paar pro Dienst ab, wie im Schema mit
der 2,5-Stunden-Strecke, wird die Crew je Stunde sogar teurer.</p></section>""")

    # ── 6. ТОиР и простои ─────────────────────────────────────────────────
    mro = mro_section()

    # ── 7. цена плотного расписания ───────────────────────────────────────
    price = T(f"""<section><h2>Чем платят за плотное расписание</h2>
<p>Чем больше рейсов у самолёта в день, тем дальше от плана уходит последний. В Европе в 2024 году средняя задержка —
17,5 минуты на рейс, и 46 % этих минут — наведённые: задержка пришла с предыдущего рейса того же самолёта
{cite('n3-117', 'n3-118')}. Первая утренняя волна вылетает почти по плану — в 2025 году в среднем 6,6 минуты задержки,
— а к вечеру задержки копятся{cite('n3-129', 'n3-134')}. Летом всё хуже, чем зимой: в июле 2025 года — 21 минута на
вылет, в ноябре — 11,6{cite('n3-124', 'n3-126')}.</p>
<p>Против этого в расписание закладывают запас — и платят за него налётом. Минута, добавленная к блок-времени, снимает
от 0,24 до 0,57 минуты задержки прилёта; минута, добавленная к обороту, — около 0,17{cite('n3-149', 'n3-145', 'n3-146')}.
Десять минут запаса на каждом из шести оборотов — это час налёта в сутки{cite('n3-150')}. На графике пиловидной
зависимости это видно буквально: лишние минуты на обороте могут сбросить налёт на целую пару рейсов.</p>
<p>Лоукостер при этом не обязательно опаздывает больше: Iberia Express стала первой по пунктуальности в Европе в 2025
году с 88,9 % рейсов вовремя, а в Великобритании в 2023 году самая большая средняя задержка была у Wizz Air — 31,6
минуты, у Ryanair — 19,9, у Lufthansa — 18,5{cite('n3-137', 'n3-133')}. Пунктуальность — это вопрос запаса и резерва, а не
модели бизнеса.</p>
<p>Наконец, сезон. Зимой спрос падает, и у авиакомпании три пути: ставить часть самолётов на стоянку, отправлять их на
тяжёлое ТО или сдавать с экипажами туда, где сейчас высокий сезон. Европейские операторы ACMI (лизинга с экипажем)
зимой уводят самолёты в южное полушарие: зимой 2024/25 года шесть таких самолётов летали у аргентинской Flybondi
{cite('n3-155', 'n3-157')}. Сезонный размах хорошо виден у Wizz Air: с октября по декабрь 2023 года — 11 часов 35 минут
в сутки на весь парк{cite('n3-165')}, а с апреля по сентябрь 2025 года — 10 часов 9 минут, когда часть самолётов стояла
из-за двигателей{cite('n3-112')}.</p></section>""",
              f"""<section><h2>What a tight schedule costs</h2>
<p>The more flights an aircraft has in a day, the further the last one drifts from the plan. In Europe in 2024 the
average delay was 17.5 minutes per flight, and 46 % of those minutes were reactionary: the delay came from the same
aircraft's previous flight{cite('n3-117', 'n3-118')}. The first morning wave leaves almost on time — 6.6 minutes of delay
on average in 2025 — and delays build up towards the evening{cite('n3-129', 'n3-134')}. Summer is worse than winter: 21
minutes per departure in July 2025, 11.6 in November{cite('n3-124', 'n3-126')}.</p>
<p>To counter this, buffers are built into the schedule — and paid for with utilisation. A minute added to block time
removes between 0.24 and 0.57 minutes of arrival delay; a minute added to the turnaround, about 0.17
{cite('n3-149', 'n3-145', 'n3-146')}. Ten minutes of buffer on each of six turnarounds is an hour of flying a day
{cite('n3-150')}. The sawtooth chart shows this literally: extra minutes on the turnaround can knock utilisation down by a
whole pair of flights.</p>
<p>Low-cost does not necessarily mean later: Iberia Express was Europe's most punctual airline in 2025 with 88.9 % of
flights on time, while in the UK in 2023 the largest average delay was Wizz Air's — 31.6 minutes — against 19.9 for
Ryanair and 18.5 for Lufthansa{cite('n3-137', 'n3-133')}. Punctuality is a matter of buffers and reserves, not of the
business model.</p>
<p>Finally, the season. In winter demand drops, and an airline has three options: park some aircraft, send them for heavy
maintenance, or lease them out with crews to where it is high season. European ACMI operators (wet lease with crew) take
aircraft to the southern hemisphere in winter: in winter 2024/25 six such aircraft flew for Argentina's Flybondi
{cite('n3-155', 'n3-157')}. Wizz Air shows the seasonal swing well: 11 hours 35 minutes a day across the whole fleet from
October to December 2023{cite('n3-165')}, and 10 hours 9 minutes from April to September 2025, when some aircraft were
grounded by engine problems{cite('n3-112')}.</p></section>""",
              f"""<section><h2>Was ein dichter Flugplan kostet</h2>
<p>Je mehr Flüge ein Flugzeug am Tag hat, desto weiter weicht der letzte vom Plan ab. In Europa betrug die
durchschnittliche Verspätung 2024 17,5 Minuten pro Flug, und 46 % dieser Minuten waren Folgeverspätungen: Sie stammten
vom vorherigen Flug desselben Flugzeugs{cite('n3-117', 'n3-118')}. Die erste Morgenwelle startet fast pünktlich — 2025 im
Schnitt 6,6 Minuten Verspätung —, zum Abend hin summieren sich die Verspätungen{cite('n3-129', 'n3-134')}. Im Sommer ist es
schlimmer als im Winter: im Juli 2025 21 Minuten je Abflug, im November 11,6{cite('n3-124', 'n3-126')}.</p>
<p>Dagegen werden Puffer in den Flugplan eingebaut — und mit Auslastung bezahlt. Eine zur Blockzeit hinzugefügte Minute
nimmt 0,24 bis 0,57 Minuten Ankunftsverspätung weg; eine zum Turnaround hinzugefügte etwa 0,17
{cite('n3-149', 'n3-145', 'n3-146')}. Zehn Minuten Puffer bei jedem von sechs Turnarounds sind eine Flugstunde am Tag
{cite('n3-150')}. Die Sägezahngrafik zeigt das buchstäblich: Zusätzliche Minuten beim Turnaround können die Auslastung um
ein ganzes Flugpaar senken.</p>
<p>Low-Cost heißt dabei nicht unbedingt unpünktlicher: Iberia Express war 2025 die pünktlichste Airline Europas mit 88,9 %
pünktlichen Flügen, in Großbritannien hatte 2023 Wizz Air die größte durchschnittliche Verspätung — 31,6 Minuten —, Ryanair
19,9, Lufthansa 18,5{cite('n3-137', 'n3-133')}. Pünktlichkeit ist eine Frage von Puffern und Reserven, nicht des
Geschäftsmodells.</p>
<p>Schließlich die Saison. Im Winter sinkt die Nachfrage, und eine Airline hat drei Wege: einen Teil der Flugzeuge
abstellen, in die schwere Wartung schicken oder mit Crew dorthin vermieten, wo gerade Hochsaison ist. Europäische
ACMI-Anbieter (Wet Lease mit Besatzung) bringen ihre Flugzeuge im Winter auf die Südhalbkugel: Im Winter 2024/25 flogen
sechs solcher Flugzeuge für die argentinische Flybondi{cite('n3-155', 'n3-157')}. Bei Wizz Air sieht man die saisonale
Schwankung gut: von Oktober bis Dezember 2023 11 Stunden 35 Minuten am Tag über die ganze Flotte{cite('n3-165')}, von April
bis September 2025 10 Stunden 9 Minuten, als ein Teil der Flugzeuge wegen der Triebwerke stand{cite('n3-112')}.</p></section>""")

    # ── 8. таблица для расчёта ────────────────────────────────────────────
    MODEL = [(("Лоукостер, челнок от базы", "Low-cost, base shuttle", "Low-Cost, Pendel ab Basis"), (10, 13),
              ("Победа 12,7, Volaris 13,0, easyJet 10,2", "Pobeda 12.7, Volaris 13.0, easyJet 10.2",
               "Pobeda 12,7, Volaris 13,0, easyJet 10,2"), "14–16", "25–35",
              ("18–19 ч (база)", "18–19 h (base)", "18–19 h (Basis)"), ["n5-012", "n1-082", "n5-015", "n2-139"]),
             (("Сетевой, волны хаба (узкие и дальние)", "Network, hub banks (narrow- and widebody)",
               "Netzwerk, Hub-Wellen (Schmal- und Großraum)"), (9.5, 11),
              ("Аэрофлот 9,8, Copa 11,1", "Aeroflot 9.8, Copa 11.1", "Aeroflot 9,8, Copa 11,1"), "13–14", "45–55",
              ("06–23 (хаб)", "06–23 (hub)", "06–23 (Hub)"), ["n5-010", "n5-021", "n2-071"]),
             (("Чартер, курорты", "Charter, resorts", "Charter, Urlaubsziele"), (8, 11),
              ("по сезону 7–13 (Jet2, TUI, 2024)", "7–13 by season (Jet2, TUI, 2024)", "7–13 je nach Saison (Jet2, TUI, 2024)"),
              "13", "40–50", ("две ротации в сутки", "two rotations a day", "zwei Rotationen am Tag"),
              ["n1-054", "n1-065", "n1-056", "n2-124"]),
             (("Региональный турбовинтовой", "Regional turboprop", "Regionaler Turboprop"), (5, 5.5),
              ("1 800–2 000 лётных ч в год (руководство по ТО)", "1,800–2,000 flight hours a year (maintenance guide)",
               "1.800–2.000 Flugstunden im Jahr (Wartungsleitfaden)"), "—", "—",
              ("как у хаба", "as at the hub", "wie am Hub"), ["n2-110", "n2-114"]),
             (("Дальний широкофюзеляжный", "Long-haul widebody", "Langstrecke, Großraum"), (12, 14),
              ("BA A350-1000, Virgin 14–14,6 (2024)", "BA A350-1000, Virgin 14–14.6 (2024)",
               "BA A350-1000, Virgin 14–14,6 (2024)"), "14–15", "80–95",
              ("по часовым поясам", "by time zones", "nach Zeitzonen"), ["n1-063", "n1-062", "n2-069"])]

    t_model = "".join(f"<tr><td>{e(L(a))}</td><td class=r>{n(b[0], 1 if b[0] % 1 else 0)}–{n(b[1], 1 if b[1] % 1 else 0)}</td>"
                      f"<td class=r>{n(b[0] * 30.4)}–{n(b[1] * 30.4)}</td><td class=s>{e(L(c))}</td>"
                      f"<td class=r>{d}</td><td class=r>{t}</td><td class=s>{e(L(w))}{cite(*ev)}</td></tr>"
                      for a, b, c, d, t, w, ev in MODEL)
    own = "".join(f"<tr><td class=r>{h}</td><td class=r>{n(h / 30.4, 1)}</td><td class=r>{money(own_per_flight(h))}</td>"
                  f"<td class=r>{n((own_per_flight(h) / own_per_flight(300) - 1) * 100, sign=True)} %</td></tr>"
                  for h in (250, 300, 350, 400, 450))
    facts = T(f"""<section><h2>Таблица для расчёта</h2>
<p>Сводка ориентиров по типам сети — для ввода своего налёта в калькулятор. Средний за год налёт — то, что вводить;
летний пик — для проверки, что расписание вообще реально.</p>
<div class="tw"><table><tr><th>Тип сети</th><th class=r>Налёт за год, ч/сут</th><th class=r>ч/мес</th>
<th>Факт 2023–2025</th><th class=r>Летний пик, ч/сут</th><th class=r>Оборот, мин</th><th>Окно</th></tr>{t_model}</table></div>
<h3>Что налёт делает с владением на рейс</h3>
<div class="tw" style="max-width:560px"><table><tr><th class=r>ч/мес</th><th class=r>ч/сут</th><th class=r>Владение на рейс</th>
<th class=r>к 300 ч</th></tr>{own}</table></div>
<p class="small">A320 текущего поколения, заготовка лизинга калькулятора {money(LEASE)} в месяц, рейс Франкфурт — Барселона
{n(BLOCK, 2)} блок-часа.</p></section>""",
              f"""<section><h2>Table for the calculation</h2>
<p>Benchmarks by network type — for entering your own utilisation into the calculator. The annual average is what to
enter; the summer peak is for checking that the schedule is realistic at all.</p>
<div class="tw"><table><tr><th>Network type</th><th class=r>Annual utilisation, h/day</th><th class=r>h/month</th>
<th>Actual 2023–2025</th><th class=r>Summer peak, h/day</th><th class=r>Turnaround, min</th><th>Window</th></tr>{t_model}</table></div>
<h3>What utilisation does to ownership cost per flight</h3>
<div class="tw" style="max-width:560px"><table><tr><th class=r>h/month</th><th class=r>h/day</th><th class=r>Ownership per flight</th>
<th class=r>vs 300 h</th></tr>{own}</table></div>
<p class="small">Current-generation A320, the calculator's default lease of {money(LEASE)} a month, Frankfurt — Barcelona
flight of {n(BLOCK, 2)} block hours.</p></section>""",
              f"""<section><h2>Tabelle für die Rechnung</h2>
<p>Richtwerte nach Netztyp — zur Eingabe der eigenen Auslastung in den Rechner. Einzugeben ist das Jahresmittel; der
Sommerspitzenwert dient der Prüfung, ob der Flugplan überhaupt realistisch ist.</p>
<div class="tw"><table><tr><th>Netztyp</th><th class=r>Jahresauslastung, h/Tag</th><th class=r>h/Monat</th>
<th>Ist 2023–2025</th><th class=r>Sommerspitze, h/Tag</th><th class=r>Turnaround, min</th><th>Fenster</th></tr>{t_model}</table></div>
<h3>Was die Auslastung mit den Besitzkosten je Flug macht</h3>
<div class="tw" style="max-width:560px"><table><tr><th class=r>h/Monat</th><th class=r>h/Tag</th><th class=r>Besitz je Flug</th>
<th class=r>zu 300 h</th></tr>{own}</table></div>
<p class="small">A320 der aktuellen Generation, Standard-Leasingrate des Rechners {money(LEASE)} im Monat, Flug Frankfurt —
Barcelona mit {n(BLOCK, 2)} Blockstunden.</p></section>""")

    # ── 9. что меняем в калькуляторе ──────────────────────────────────────
    concl = T(f"""<section><h2>Что меняем в калькуляторе</h2>
<ol><li>{mark('on_input')}<b>Вводите налёт на весь парк в среднем за год</b>, а не летний пик и не налёт летающего
самолёта: лизинг платится и за зиму, и за самолёт в резерве или на ТО. Ориентир — таблица выше.</li>
<li>{mark('planned')}<b>Налёт по типу сети вместо одной цифры 300 часов.</b> Заготовка будет зависеть от схемы (челнок от
базы, хаб, чартер, региональный, дальний) и длины плеча: пиковый день по формуле окна, умноженный на годовой коэффициент
(зима, ТО, резерв, задержки) — около 0,8; это калибровка, а не цитата.</li>
<li>{mark('planned')}<b>Экипажи от годовых часов.</b> Число экипажей на самолёт = часы самолёта ÷ налёт пилота (по
умолчанию 750 часов, диапазон 500–900) с проверкой, сколько секторов влезает в смену при данной длине плеча.</li>
<li>{mark('planned')}<b>Окно базы из ночных ограничений аэропорта</b> — в справочник аэропортов; в режиме «Сеть» —
предупреждение, если пары не влезают в окно.</li>
<li>{mark('planned')}<b>Резерв и плановое ТО — явными долями</b>: резервные самолёты и запасные двигатели — к владению,
простой на тяжёлом ТО — к налёту, вместо скрытого запаса на всё.</li></ol></section>""",
              f"""<section><h2>What we are changing in the calculator</h2>
<ol><li>{mark('on_input')}<b>Enter utilisation across the whole fleet, averaged over the year</b>, not the summer peak and
not the utilisation of flying aircraft: the lease is paid for winter too, and for aircraft in reserve or in maintenance.
The table above is the benchmark.</li>
<li>{mark('planned')}<b>Utilisation by network type instead of a single 300-hour figure.</b> The default will depend on the
pattern (base shuttle, hub, charter, regional, long-haul) and sector length: the peak day from the window formula,
multiplied by an annual factor (winter, maintenance, reserve, delays) of about 0.8; this is a calibration, not a
quote.</li>
<li>{mark('planned')}<b>Crews from annual hours.</b> Crews per aircraft = aircraft hours ÷ pilot flight hours (750 hours by
default, range 500–900), with a check of how many sectors fit into a duty at the given sector length.</li>
<li>{mark('planned')}<b>Base window from the airport's night restrictions</b> — into the airport reference data; in the
“Network” mode, a warning if the pairs do not fit into the window.</li>
<li>{mark('planned')}<b>Reserve and scheduled maintenance as explicit shares</b>: reserve aircraft and spare engines go to
ownership, heavy-maintenance downtime to utilisation, instead of a hidden buffer for everything.</li></ol></section>""",
              f"""<section><h2>Was wir im Rechner ändern</h2>
<ol><li>{mark('on_input')}<b>Geben Sie die Auslastung der ganzen Flotte im Jahresmittel ein</b>, nicht die Sommerspitze und
nicht die Auslastung fliegender Flugzeuge: Das Leasing wird auch im Winter gezahlt und für Flugzeuge in Reserve oder in der
Wartung. Richtwert ist die Tabelle oben.</li>
<li>{mark('planned')}<b>Auslastung nach Netztyp statt einer einzigen Zahl von 300 Stunden.</b> Der Standardwert hängt dann
vom Muster ab (Pendel ab Basis, Hub, Charter, regional, Langstrecke) und von der Streckenlänge: der Spitzentag nach der
Fensterformel, multipliziert mit einem Jahresfaktor (Winter, Wartung, Reserve, Verspätungen) von etwa 0,8; das ist eine
Kalibrierung, kein Zitat.</li>
<li>{mark('planned')}<b>Crews aus Jahresstunden.</b> Crews je Flugzeug = Flugzeugstunden ÷ Flugstunden je Pilot (Standard
750 Stunden, Spanne 500–900), mit Prüfung, wie viele Sektoren bei der gegebenen Streckenlänge in einen Dienst passen.</li>
<li>{mark('planned')}<b>Basisfenster aus den Nachtbeschränkungen des Flughafens</b> — in die Flughafendaten; im Modus „Netz“
eine Warnung, wenn die Paare nicht ins Fenster passen.</li>
<li>{mark('planned')}<b>Reserve und planmäßige Wartung als ausdrückliche Anteile</b>: Reserveflugzeuge und
Ersatztriebwerke zum Besitz, Standzeit in schwerer Wartung zur Auslastung, statt eines versteckten Puffers für alles.</li>
</ol></section>""")

    # ── 10. отчёт ─────────────────────────────────────────────────────────
    cnt = {f: Counter(x["status"] for k, x in v.items() if not k.startswith("_")) for f, v in VER.items()}
    steps = sum(1 for f in (HERE / "trace").glob("n*.jsonl") for _ in f.open(encoding="utf-8"))
    gl = N1["gaps"] + N2["gaps"] + N3["gaps"] + ((N4 or {}).get("gaps") or [])
    gaps = "".join(f"<li>{e(TR(txt(x)))}</li>" for x in gl
                   if not any(w in txt(x) for w in ("Pegasus", "MIT", "у n3", "allowlist", "разрешённого списка",
                                                    "координатор", "TrueChoice")))
    c1, c2, c3, c4 = cnt["n1"], cnt["n2"], cnt["n3"], cnt["n4"]
    report = T(f"""<section><h2>Как проверялось</h2>
<p>Четыре исследователя вели журналы поиска — {n(steps)} шагов вместе с выписками из отчётности (<code>trace/n1–n5</code>):
налёт по авиакомпаниям, механика и построение сети, экипажи и задержки, техобслуживание, контракты и запчасти. Другие
агенты открыли каждый источник и сверили цитаты (<code>verify/</code>): налёт — найдено {c1['found']} из
{sum(c1.values())}; механика — {c2['found']}, из выводов верны {c2['infer_ok']}, два исправлены;
экипажи и задержки — {c3['found']} дословно и {c3.get('partial', 0)} частично; техобслуживание,
контракты и запчасти — {c4['found']} дословно и {c4.get('partial', 0)} частично, все {c4['infer']}
расчётов пересчитаны.</p>
<p>По проверке раздела о ТО: пример эффекта пула в исследовании KLM оказался условным — даём принцип без чисел;
интервал «3 года» у 737-8 MAX — из спецификации одного самолёта, а не из программы ТО; контракт Colorful Guizhou с CFM —
соглашение о намерениях; рост расходов «Аэрофлота» на ТО компания объясняет только в целом по операционным расходам.</p>
<p>Исправлено по проверке: формула налёта — в блок-часах с оборотом, без двойного учёта руления; сравнение «лоукостеры
летают больше сетевых» снято — данные этого не показывают; окно Дюссельдорфа — плановые посадки до 23:00; пример
дальней ротации снят (не доказано, что это один самолёт); число экипажей — от лимитов и отчётности, а не от старой
цифры налёта пилота; таблица смен по числу посадок из приказа №381 не приводится, пока не сверена с официальным текстом.
Налёт группы «Аэрофлот» посчитан по Databook (лист операционных показателей и парка); ряды налёта старше 2023 года
сняты.</p>
<details><summary>Чего не нашлось</summary><ul>{gaps}</ul></details>
{S.html()}</section>""",
               f"""<section><h2>How it was checked</h2>
<p>Four researchers kept search logs — {n(steps)} steps including extracts from reports (<code>trace/n1–n5</code>): airline
utilisation, network mechanics and design, crews and delays, maintenance, contracts and spare parts. Other agents opened
every source and checked the quotes (<code>verify/</code>): utilisation — {c1['found']} of {sum(c1.values())} found;
mechanics — {c2['found']}, of the inferences {c2['infer_ok']} correct, two corrected; crews and delays — {c3['found']}
verbatim and {c3.get('partial', 0)} partially; maintenance, contracts and spare parts — {c4['found']} verbatim and
{c4.get('partial', 0)} partially, all {c4['infer']} calculations recomputed.</p>
<p>From the check of the maintenance section: the pool-effect example in the KLM study turned out to be illustrative — we
give the principle without the numbers; the “3 years” interval for the 737-8 MAX comes from one aircraft's specification,
not from a maintenance programme; the Colorful Guizhou contract with CFM is a memorandum of understanding; Aeroflot
explains the rise in maintenance costs only as part of operating costs as a whole.</p>
<p>Corrected after checking: the utilisation formula is in block hours with turnaround, without double-counting taxi; the
comparison “low-cost carriers fly more than network carriers” was removed — the data do not show it; the Düsseldorf window
is scheduled landings until 23:00; the long-haul rotation example was removed (not proven to be one aircraft); crew numbers
are based on limits and reporting, not on an old pilot-hours figure; the duty table by number of landings from Order
No. 381 is not given until checked against the official text. Aeroflot group utilisation was calculated from the Databook
(operating and fleet sheets); utilisation series older than 2023 were removed.</p>
<details><summary>What was not found</summary><ul>{gaps}</ul></details>
{S.html()}</section>""",
               f"""<section><h2>Wie geprüft wurde</h2>
<p>Vier Rechercheure führten Suchprotokolle — {n(steps)} Schritte samt Auszügen aus Berichten (<code>trace/n1–n5</code>):
Auslastung der Airlines, Mechanik und Aufbau des Netzes, Crews und Verspätungen, Wartung, Verträge und Ersatzteile. Andere
Agenten öffneten jede Quelle und prüften die Zitate (<code>verify/</code>): Auslastung — {c1['found']} von {sum(c1.values())}
gefunden; Mechanik — {c2['found']}, von den Schlussfolgerungen {c2['infer_ok']} richtig, zwei korrigiert; Crews und
Verspätungen — {c3['found']} wörtlich und {c3.get('partial', 0)} teilweise; Wartung, Verträge und Ersatzteile — {c4['found']}
wörtlich und {c4.get('partial', 0)} teilweise, alle {c4['infer']} Rechnungen nachgerechnet.</p>
<p>Aus der Prüfung des Wartungsabschnitts: Das Beispiel zum Pool-Effekt in der KLM-Studie erwies sich als fiktiv — wir geben
das Prinzip ohne Zahlen; das Intervall „3 Jahre“ bei der 737-8 MAX stammt aus der Spezifikation eines einzelnen Flugzeugs,
nicht aus einem Wartungsprogramm; der Vertrag von Colorful Guizhou mit CFM ist eine Absichtserklärung; den Anstieg der
Wartungskosten erklärt Aeroflot nur im Rahmen der Betriebskosten insgesamt.</p>
<p>Nach der Prüfung korrigiert: Die Auslastungsformel rechnet in Blockstunden mit Turnaround, ohne das Rollen doppelt zu
zählen; der Vergleich „Low-Cost-Airlines fliegen mehr als Netzwerk-Airlines“ wurde gestrichen — die Daten zeigen das nicht;
das Düsseldorfer Fenster sind planmäßige Landungen bis 23:00; das Beispiel einer Langstreckenrotation wurde gestrichen
(nicht belegt, dass es ein Flugzeug ist); die Crewzahl stützt sich auf Grenzwerte und Berichte, nicht auf eine alte
Pilotenstundenzahl; die Diensttabelle nach Landungen aus Verordnung Nr. 381 wird erst nach Abgleich mit dem amtlichen Text
gezeigt. Die Auslastung der Aeroflot-Gruppe wurde nach dem Databook berechnet (Betriebs- und Flottenblatt); Auslastungsreihen
vor 2023 wurden gestrichen.</p>
<details><summary>Was nicht gefunden wurde</summary><ul>{gaps}</ul></details>
{S.html()}</section>""")

    style = "<style>.formula{font:13.5px var(--mono)}figure.fig{margin:14px 0 6px;max-width:780px}</style>"
    return page(article_title("network-2026-10"),
                ARTICLE_CSS + style + hook + theory + real + howto + crew + mro + price + facts + concl + report)


if __name__ == "__main__":
    write_all(HERE, "network-2026-10", build, TR)
    print(f"источников {len(S.num)}")
