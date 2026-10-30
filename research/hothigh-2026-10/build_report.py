#!/usr/bin/env python3
"""Статья «Жара и высота: сколько пассажиров самолёт не довезёт» — HTML в оформлении сайта, на трёх языках.

Структура — research/STYLE.md; ориентир — как жара и высота меняют расчёт рейса.

Читает итоги (out/hothigh.json) и проверку цитат (verify/h1.json), пишет report.html.
Числа Coffel & Horton (2014, табл. 2) — дословно сверены проверяющим; наклоны и
пороги — производные исследователя, это сказано в отчёте.
Тексты — T(ru, en, de); строки из данных — i18n.yaml (Tr).

    python3 research/hothigh-2026-10/build_report.py      # из корня репозитория → report.html, report.en.html, report.de.html
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, Tr, article_title, calc_badge, chain, e,  # noqa: E402
                     line_chart, mark, n, page, whisker, write_all)

D = json.loads((HERE / "out" / "hothigh.json").read_text(encoding="utf-8"))
V = {k: v for f in sorted((HERE / "verify").glob("h*.json"))
     for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")}
TR = Tr(HERE)
MTOW_KG, LB = 79_016, 0.4536
# Сомнения исследователя, снятые документами владельца (trace/h2.jsonl): таблица Coffel & Horton
# сверена по журнальной версии, MTOW 737-800 и градиент ISA — с цитатами.
CLOSED = ("пересказ", "MTOW 737-800", "Traficom")


def tr(s):
    """Строка из данных: переводится, если в ней русский текст или десятичная запятая; остальное
    (типы, «ATR factsheet», «AC A320 06/2024 §3-3») — как есть."""
    return TR(s) if s and re.search(r"[А-Яа-яЁё]|\d,\d", s) else s


# Coffel & Horton (2014), табл. 2: температура, °C, при которой ограничение взлётной
# массы 737-800 достигает 1 000 / 10 000 / 15 000 фунтов. None — «N/A»: ограничение
# не меньше 1 000 фунтов при любой температуре.
CH = [(("Финикс (346 м, ВПП 3,5 км)", "Phoenix (346 m, runway 3.5 km)", "Phoenix (346 m, Piste 3,5 km)"), (38, 47, 53)),
      (("Денвер (1 656 м, ВПП 4,9 км)", "Denver (1,656 m, runway 4.9 km)", "Denver (1.656 m, Piste 4,9 km)"),
       (None, 30, 37)),
      (("Нью-Йорк, Ла-Гуардия (6 м, ВПП 2,1 км)", "New York LaGuardia (6 m, runway 2.1 km)",
        "New York-LaGuardia (6 m, Piste 2,1 km)"), (None, 31, 33))]


def pct(lb):
    return lb * LB / MTOW_KG * 100


def chart():
    cols = ["var(--sky)", "var(--green)", "var(--aqua)"]
    ser = []
    for (name, (t1, t10, t15)), c in zip(CH, cols):
        pts = {}
        if t1 is not None:
            pts[t1] = pct(1000)
        pts[t10], pts[t15] = pct(10_000), pct(15_000)
        ser.append((T(*name).split(" (")[0], c, pts, False))
    return line_chart(ser, ylab=T("снижение взлётной массы, % MTOW", "take-off weight reduction, % MTOW",
                                  "Verringerung der Startmasse, % MTOW"),
                      yfmt=lambda v: n(max(v, 0), 0) + " %", x_every=1)


S = Sources(HERE)
# Пример расчёта: A320, MTOW 78 т, 180 кресел, пассажир с багажом — 100 кг. Сейчас калькулятор
# нагрузку из-за жары не снимает; поправка ниже — то, что предлагается добавить.
SEATS = 180


def isa_dev(t, elev_m):
    return t - (15 - 1.98 * elev_m / 304.8)


def loss_pct(dev, d0, k):
    return k * max(0.0, dev - d0)


def pax(p):
    return p / 100 * MTOW_KG / 100


# Сценарии для точечной диаграммы: (подпись ru/en/de, T, высота м, порог, k — оценка, (k от, k до), шаги журнала)
SCEN = [(("Дели, май — 40,7 °C", "Delhi, May — 40.7 °C", "Delhi, Mai — 40,7 °C"),
         40.7, 240, 25, 0.5, (0.48, 0.57), ("h1-075",)),
        (("Ахмадабад, май — 42,2 °C", "Ahmedabad, May — 42.2 °C", "Ahmedabad, Mai — 42,2 °C"),
         42.2, 55, 25, 0.5, (0.48, 0.57), ("h1-082",)),
        (("Дели, жара 45 °C", "Delhi, heatwave 45 °C", "Delhi, Hitzewelle 45 °C"),
         45.0, 240, 25, 0.5, (0.48, 0.57), ("h1-014",)),
        (("Денвер, июль — 32,2 °C", "Denver, July — 32.2 °C", "Denver, Juli — 32,2 °C"),
         32.2, 1656, 12, 0.4, (0.4, 0.6), ("h1-086",)),
        (("Короткая полоса у моря, 35 °C", "Short runway at sea level, 35 °C", "Kurze Piste auf Meereshöhe, 35 °C"),
         35.0, 6, 12, 1.4, (1.2, 1.43), ("h1-061",))]


def build() -> str:
    st = Counter(x["status"] for k, x in V.items() if not k.startswith("_"))
    steps = sum(1 for f in (HERE / "trace").glob("h*.jsonl") for _ in f.open(encoding="utf-8"))
    dl = loss_pct(isa_dev(40.7, 240), 25, 0.5)
    dl45 = loss_pct(isa_dev(45, 240), 25, 0.5)
    lost = round(pax(dl))
    cost_up = n(lost / (SEATS - lost) * 100, 1)

    hook = f"""<h1>{T("Жара и высота: сколько пассажиров самолёт не довезёт",
                    "Heat and altitude: how many passengers an aircraft cannot carry",
                    "Hitze und Höhe: wie viele Passagiere ein Flugzeug nicht mitnehmen kann")}</h1>
<p class="meta">{T('''Исследование FlightCostApp, октябрь 2026 · черновик · как температура и высота аэродрома меняют расчёт
рейса''', "FlightCostApp research, October 2026 · draft · how airfield temperature and elevation change the cost of a flight",
                   "FlightCostApp-Recherche, Oktober 2026 · Entwurf · wie Temperatur und Höhe des Flugplatzes die Flugkosten "
                   "verändern")}</p>
{calc_badge("hothigh-2026-10")}
<div class="verdict">
<div><b>{T("До порога — ничего", "Below the threshold — nothing", "Unterhalb der Schwelle — nichts")}</b><span>{T(
        '''двигатель держит тягу до «точки излома»; у A320 на длинной полосе у моря масса
ограничивается примерно с 40 °C''',
        "the engine holds its thrust up to the “kink point”; for an A320 on a long sea-level runway the weight becomes "
        "limited from about 40 °C",
        "das Triebwerk hält seinen Schub bis zum „Knickpunkt“; beim A320 auf einer langen Piste auf Meereshöhe wird die "
        "Masse ab etwa 40 °C begrenzt")}{S.cite('h1-114', 'h1-133')}</span></div>
<div><b>{T("Дальше 0,4–0,6 % массы на градус", "Beyond it, 0.4–0.6 % of weight per degree",
           "Darüber 0,4–0,6 % der Masse je Grad")}</b><span>{T(
        '''около 4 пассажиров A320 на каждый градус; на короткой полосе — до
1,4 %''',
        "about 4 A320 passengers for every degree; on a short runway — up to 1.4 %",
        "etwa 4 Passagiere eines A320 je Grad; auf einer kurzen Piste — bis zu 1,4 %")}{S.cite('h2-003', 'h2-005')}</span></div>
<div><b>{T(f"Дели в мае: −{lost} пассажиров", f"Delhi in May: −{lost} passengers",
           f"Delhi im Mai: −{lost} Passagiere")}</b><span>{T(
        f'''себестоимость на пассажира +{cost_up} % — но только
на рейсе, загруженном до предельной массы''',
        f"cost per passenger +{cost_up} % — but only on a flight loaded up to the weight limit",
        f"Kosten je Passagier +{cost_up} % — aber nur auf einem Flug, der bis zur Grenzmasse beladen ist")
        }{S.cite('h1-075')}</span></div>
<div><b>{T("Опора узкая", "A narrow basis", "Schmale Grundlage")}</b><span>{T(
        '''один тип (737-800) и три аэропорта; для турбовинтовых и высокогорья выше 2 100 м чисел
нет''',
        "one type (737-800) and three airports; there are no figures for turboprops or for high airfields above 2,100 m",
        "ein Typ (737-800) und drei Flughäfen; für Turboprops und Hochlagen über 2.100 m gibt es keine Zahlen")
        }</span></div></div>
<p class="lede">{T('''Сейчас калькулятор считает, что самолёт в любой день может взлететь с полной загрузкой. В жару и на
высоте это не так: допустимая взлётная масса падает, и на длинном секторе с полным салоном часть пассажиров или груза
приходится снять. Тогда те же затраты на рейс делятся на меньшее число пассажиров. Ниже — когда это происходит и на
сколько.''',
        "Today the calculator assumes that an aircraft can take off fully loaded on any day. In heat and at altitude this is "
        "not so: the allowable (performance-limited) take-off weight drops, and on a long sector with a full cabin some "
        "passengers or cargo have to be offloaded. The same flight costs are then split over fewer passengers. Below: when "
        "this happens and by how much.",
        "Derzeit nimmt der Rechner an, dass ein Flugzeug an jedem Tag voll beladen starten kann. Bei Hitze und in der Höhe "
        "stimmt das nicht: Die zulässige Startmasse sinkt, und auf einer langen Strecke mit voller Kabine müssen einige "
        "Passagiere oder Fracht ausgeladen werden. Dann verteilen sich dieselben Flugkosten auf weniger Passagiere. Unten: "
        "wann das passiert und wie stark.")}</p>"""

    theory = f"""<section><h2>{T("Почему жара и высота отнимают пассажиров", "Why heat and altitude cost passengers",
                                  "Warum Hitze und Höhe Passagiere kosten")}</h2>
{chain([(T("Жарко или высоко", "Hot or high", "Heiß oder hoch"),
         T("воздух менее плотный: самолёт ведёт себя как на большей высоте",
           "the air is less dense: the aircraft behaves as if it were higher up",
           "die Luft ist weniger dicht: Das Flugzeug verhält sich wie in größerer Höhe")),
        (T("Больше скорость отрыва", "Higher lift-off speed", "Höhere Abhebegeschwindigkeit"),
         T("та же приборная скорость, но истинная выше — длиннее разбег",
           "the same indicated airspeed, but a higher true airspeed — a longer take-off run",
           "dieselbe angezeigte Fahrt, aber höhere wahre Geschwindigkeit — längerer Startlauf")),
        (T("Меньше тяги", "Less thrust", "Weniger Schub"),
         T("двигатель «вдыхает» меньше воздуха — медленнее разгон",
           "the engine “breathes in” less air — slower acceleration",
           "das Triebwerk „atmet“ weniger Luft ein — langsamere Beschleunigung")),
        (T("Ниже допустимая масса", "Lower allowable weight", "Niedrigere zulässige Masse"),
         T("полосы и набора не хватает — снимают груз, потом пассажиров",
           "runway or climb performance runs short — cargo is offloaded first, then passengers",
           "Piste oder Steigleistung reichen nicht — erst wird Fracht ausgeladen, dann Passagiere"))])}
<p>{T(f'''<b>Плотность решает всё.</b> Подъёмная сила крыла и сопротивление прямо пропорциональны плотности воздуха, а
плотность зависит от давления, температуры и влажности{S.cite('h2-019', 'h2-020')}. Поэтому лётчики считают не
по высоте аэродрома, а по «высоте по плотности» — высоте, на которой в стандартной атмосфере был бы такой же
воздух{S.cite('h2-011')}. Жаркий день у моря для самолёта — то же, что прохладный в горах: он ведёт себя так, как
будто взлетает с высоты по плотности{S.cite('h2-013')}.''',
      f"<b>Density decides everything.</b> Wing lift and drag are directly proportional to air density, and density depends "
      f"on pressure, temperature and humidity{S.cite('h2-019', 'h2-020')}. That is why pilots work not from the airfield "
      f"elevation but from “density altitude” — the altitude at which the standard atmosphere would have the same "
      f"air{S.cite('h2-011')}. To an aircraft, a hot day at sea level is the same as a cool one in the mountains: it behaves "
      f"as if it were taking off from its density altitude{S.cite('h2-013')}.",
      f"<b>Die Dichte entscheidet alles.</b> Auftrieb und Widerstand des Flügels sind direkt proportional zur Luftdichte, und "
      f"die Dichte hängt von Druck, Temperatur und Feuchte ab{S.cite('h2-019', 'h2-020')}. Deshalb rechnen Piloten nicht mit "
      f"der Flugplatzhöhe, sondern mit der „Dichtehöhe“ — der Höhe, in der die Standardatmosphäre dieselbe Luft "
      f"hätte{S.cite('h2-011')}. Ein heißer Tag auf Meereshöhe ist für das Flugzeug dasselbe wie ein kühler in den Bergen: Es "
      f"verhält sich, als starte es aus seiner Dichtehöhe{S.cite('h2-013')}.")}</p>
<p>{T(f'''<b>Два удара по взлёту.</b> Разреженный воздух даёт сразу два эффекта: нужна большая скорость отрыва и меньше
тяга, а значит, слабее разгон{S.cite('h2-014')}. Самолёт отрывается на той же приборной скорости, но истинная
скорость больше — разбег длиннее{S.cite('h2-015')}. Обратный рычаг — масса: +10 % массы удлиняет взлёт не меньше чем
на 21 %{S.cite('h2-016')}. Поэтому, когда полосы не хватает, снимают массу.''',
      f"<b>Two blows to the take-off.</b> Thin air has two effects at once: a higher lift-off speed is needed and thrust is "
      f"lower, so acceleration is weaker{S.cite('h2-014')}. The aircraft lifts off at the same indicated airspeed, but its "
      f"true airspeed is higher — the take-off run is longer{S.cite('h2-015')}. The opposite lever is weight: +10 % weight "
      f"lengthens the take-off by at least 21 %{S.cite('h2-016')}. So when the runway is not long enough, weight comes off.",
      f"<b>Zwei Schläge gegen den Start.</b> Dünne Luft wirkt doppelt: Es braucht eine höhere Abhebegeschwindigkeit, und der "
      f"Schub ist geringer, die Beschleunigung also schwächer{S.cite('h2-014')}. Das Flugzeug hebt bei derselben angezeigten "
      f"Fahrt ab, aber die wahre Geschwindigkeit ist höher — der Startlauf wird länger{S.cite('h2-015')}. Der Gegenhebel ist "
      f"die Masse: +10 % Masse verlängern den Start um mindestens 21 %{S.cite('h2-016')}. Reicht die Piste nicht, wird "
      f"deshalb Masse reduziert.")}</p>
<p>{T(f'''<b>Плоское ограничение тяги.</b> Реактивный двигатель настроен держать взлётную тягу постоянной до определённой
температуры — «точки излома»: обычно 30 °C у моря{S.cite('h1-114')}, у двигателей A320 — до 45 °C, у A321 — до
30 °C{S.cite('h1-116', 'h1-117')}, у Dash 8-400 — до 37,4 °C{S.cite('h1-100')}. До излома жара почти не мешает,
выше — тяга падает вместе с допустимой массой. Отсюда порог в расчёте.''',
      f"<b>Flat rating.</b> A jet engine is set up to hold take-off thrust constant up to a certain temperature — the "
      f"“kink” (corner) point: usually 30 °C at sea level{S.cite('h1-114')}, up to 45 °C for A320 engines, up to 30 °C for "
      f"the A321{S.cite('h1-116', 'h1-117')}, up to 37.4 °C for the Dash 8-400{S.cite('h1-100')}. Below the kink, heat "
      f"hardly matters; above it, thrust falls together with the allowable weight. Hence the threshold in the calculation.",
      f"<b>Flat Rating.</b> Ein Strahltriebwerk ist so eingestellt, dass es den Startschub bis zu einer bestimmten "
      f"Temperatur konstant hält — dem „Knickpunkt“: meist 30 °C auf Meereshöhe{S.cite('h1-114')}, bei den Triebwerken des "
      f"A320 bis 45 °C, beim A321 bis 30 °C{S.cite('h1-116', 'h1-117')}, bei der Dash 8-400 bis 37,4 °C"
      f"{S.cite('h1-100')}. Unterhalb des Knickpunkts stört die Hitze kaum, darüber sinkt der Schub zusammen mit der "
      f"zulässigen Masse. Daher die Schwelle in der Berechnung.")}</p>
<p>{T(f'''<b>Ограничение — не только полоса.</b> Правила сертификации требуют определить взлётные характеристики для каждой
массы, высоты и температуры{S.cite('h2-022')}. Взлёт должен уложиться в полосу даже с отказом двигателя
{S.cite('h2-023')}, а после отрыва двухдвигательный самолёт на одном двигателе обязан набирать высоту с градиентом не
меньше 2,4 %{S.cite('h2-024')}. Допустимая масса — минимум из всех пределов: полоса, набор, препятствия, скорость
шин, тормоза{S.cite('h1-005')}. В Денвере полоса 4,9 км, но 737-800 упирается в предельную скорость шин
{S.cite('h2-006')}.''',
      f"<b>The limit is not just the runway.</b> Certification rules require take-off performance to be determined for every "
      f"weight, altitude and temperature{S.cite('h2-022')}. The take-off must fit on the runway even with an engine failure"
      f"{S.cite('h2-023')}, and after lift-off a twin-engine aircraft on one engine must still climb at a gradient of at "
      f"least 2.4 %{S.cite('h2-024')}. The allowable weight is the lowest of all limits: runway, climb, obstacles, tyre "
      f"speed, brakes{S.cite('h1-005')}. Denver's runway is 4.9 km long, yet the 737-800 runs into its tyre speed limit"
      f"{S.cite('h2-006')}.",
      f"<b>Die Grenze ist nicht nur die Piste.</b> Die Zulassungsvorschriften verlangen, die Startleistung für jede Masse, "
      f"Höhe und Temperatur zu bestimmen{S.cite('h2-022')}. Der Start muss auch bei Triebwerksausfall auf die Piste passen"
      f"{S.cite('h2-023')}, und nach dem Abheben muss ein zweimotoriges Flugzeug mit einem Triebwerk noch mit einem "
      f"Gradienten von mindestens 2,4 % steigen{S.cite('h2-024')}. Die zulässige Masse ist das Minimum aller Grenzen: Piste, "
      f"Steigflug, Hindernisse, Reifengeschwindigkeit, Bremsen{S.cite('h1-005')}. In Denver ist die Piste 4,9 km lang, "
      f"doch die 737-800 stößt an die Grenzgeschwindigkeit ihrer Reifen{S.cite('h2-006')}.")}</p>
<p>{T(f'''<b>Какую температуру брать.</b> Аэропорты в США проектируют по среднему дневному максимуму самого жаркого месяца
{S.cite('h1-004')} — эту же температуру берём для расчёта рейса.''',
      f"<b>Which temperature to use.</b> US airports are designed for the mean daily maximum of the hottest month"
      f"{S.cite('h1-004')} — we take the same temperature for the flight calculation.",
      f"<b>Welche Temperatur.</b> Flughäfen in den USA werden auf das mittlere Tagesmaximum des heißesten Monats ausgelegt"
      f"{S.cite('h1-004')} — dieselbe Temperatur nehmen wir für die Flugberechnung.")}</p></section>"""

    rows = []
    for name, t, h, d0, k, (k1, k2), ev in SCEN:
        dev = isa_dev(t, h)
        rows.append((T(*name), pax(loss_pct(dev, d0, k)), (pax(loss_pct(dev, d0, k1)), pax(loss_pct(dev, d0, k2))),
                     "var(--orange)" if h > 1000 or k > 1 else "var(--sky)"))
    dots = whisker(rows, lo=0, hi=110, ticks=(0, 25, 50, 75, 100), fmt=lambda v: n(v), label_w=230)
    analytics = f"""<section><h2>{T("Сколько пассажиров снимается", "How many passengers are offloaded",
                                     "Wie viele Passagiere ausgeladen werden")}</h2>
<p>{T('''A320 на полной взлётной массе, сколько пассажиров (по 100 кг с багажом) пришлось бы снять. Точка — оценка
поправки, линия — разброс наклона; оранжевым — где опора слабее (высокогорье, короткая полоса).''',
      "An A320 at maximum take-off weight: how many passengers (100 kg each with baggage) would have to be offloaded. Dot — "
      "estimated correction, line — spread of the slope; orange — where the basis is weaker (high altitude, short runway).",
      "Ein A320 mit maximaler Startmasse: wie viele Passagiere (je 100 kg mit Gepäck) ausgeladen werden müssten. Punkt — "
      "geschätzte Korrektur, Linie — Streuung der Steigung; orange — wo die Grundlage schwächer ist (Hochlage, kurze "
      "Piste).")}</p>
{dots}
<p class="small">{T('''Денвер — с учётом порога ISA+12 для высокогорья; на деле там ограничение есть и в прохладный день
(скорость шин), так что оценка скорее занижена.''',
                    "Denver — with the ISA+12 threshold for high airfields; in reality the weight is limited there even on "
                    "a cool day (tyre speed), so the estimate is, if anything, too low.",
                    "Denver — mit der Schwelle ISA+12 für Hochlagen; tatsächlich ist die Masse dort auch an kühlen Tagen "
                    "begrenzt (Reifengeschwindigkeit), die Schätzung ist also eher zu niedrig.")}</p>
<h3>{T("Как ограничение растёт с температурой", "How the limit grows with temperature",
       "Wie die Begrenzung mit der Temperatur wächst")}</h3>
{chart()}<p class="small">{T(f'''Снижение допустимой взлётной массы 737-800, % от максимальной (79 т).
Точки — Coffel &amp; Horton (2015), табл. 2{S.cite('h2-003', 'h2-004', 'h2-005')}, по графикам Boeing; между точками —
прямые.''',
        f"Reduction of the 737-800 allowable take-off weight, % of maximum (79 t). Dots — Coffel &amp; Horton (2015), "
        f"table 2{S.cite('h2-003', 'h2-004', 'h2-005')}, from Boeing charts; straight lines between the dots.",
        f"Verringerung der zulässigen Startmasse der 737-800, % der höchstzulässigen (79 t). Punkte — Coffel &amp; Horton "
        f"(2015), Tab. 2{S.cite('h2-003', 'h2-004', 'h2-005')}, nach Boeing-Diagrammen; zwischen den Punkten Geraden.")}</p>
<p>{T(f'''Каждая линия начинается с порога и дальше растёт почти прямо. Чем короче полоса, тем круче: в Ла-Гуардии
(2,1 км) от 31 до 33 °C ограничение вырастает с 4,5 до 6,8 т. Наклоны и пороги посчитал исследователь по трём точкам
статьи — в самой статье их нет{S.cite('h1-133')}. Авторы переводят те же 4,5 т в 52 пассажира — у них 86 кг на
пассажира с ручной кладью{S.cite('h2-008')}; калькулятор берёт 100 кг с багажом, поэтому у нас пассажиров меньше. На
деле первым снимают груз{S.cite('h2-009')}.''',
      f"Each line starts at the threshold and then rises almost linearly. The shorter the runway, the steeper: at LaGuardia "
      f"(2.1 km) the limit grows from 4.5 to 6.8 t between 31 and 33 °C. The slopes and thresholds were derived by the "
      f"researcher from the paper's three points — the paper itself does not give them{S.cite('h1-133')}. The authors "
      f"convert the same 4.5 t into 52 passengers — they assume 86 kg per passenger with carry-on{S.cite('h2-008')}; the "
      f"calculator uses 100 kg with checked baggage, so we get fewer passengers. In practice cargo is offloaded "
      f"first{S.cite('h2-009')}.",
      f"Jede Linie beginnt an der Schwelle und steigt dann fast gerade an. Je kürzer die Piste, desto steiler: In LaGuardia "
      f"(2,1 km) wächst die Begrenzung zwischen 31 und 33 °C von 4,5 auf 6,8 t. Steigungen und Schwellen hat der "
      f"Rechercheur aus den drei Punkten des Artikels abgeleitet — im Artikel selbst stehen sie nicht{S.cite('h1-133')}. Die "
      f"Autoren rechnen dieselben 4,5 t in 52 Passagiere um — sie setzen 86 kg je Passagier mit Handgepäck an"
      f"{S.cite('h2-008')}; der Rechner nimmt 100 kg mit Gepäck, deshalb kommen bei uns weniger Passagiere heraus. In der "
      f"Praxis wird zuerst Fracht ausgeladen{S.cite('h2-009')}.")}</p></section>"""

    m = D["model"]
    trs = "".join(f"<tr><td>{e(tr(r['case']))}</td><td class=r>{'—' if r['D0'] is None else 'ISA+' + str(r['D0'])}</td>"
                  f"<td class=r>{'—' if r['k_pct_per_C'] is None else n(r['k_pct_per_C'], 1) + ' %'}</td>"
                  f"<td class=r>{'—' if r['k_pct_per_C'] is None else n(pax(r['k_pct_per_C']), 1)}</td>"
                  f"<td class=s>{e(tr(r['range']))}</td></tr>" for r in m["table"])
    ot = "".join(f"<tr><td><b>{e(t['type'])}</b></td><td>{e(tr(t['effect']))}</td><td>{e(tr(t.get('per_unit')) or '—')}"
                 f"{S.cite(*t.get('evidence', []))}</td><td class=s>{e(tr(t.get('conditions')) or '')}</td></tr>"
                 for t in D["by_type"] if t["type"] != "737-800")
    # Описания случаев длинные (в en/de особенно) — переносятся, иначе колонка «Числа» уходит за край.
    cases = "".join(f"<tr><td style=\"white-space:normal\">{e(tr(c['what']))}{S.cite(*c.get('evidence', []))}</td>"
                    f"<td class=s>{e(tr(c.get('numbers')) or '')}</td></tr>" for c in D["cases"])
    facts = f"""<section><h2>{T("Таблица для расчёта", "Table for the calculation", "Tabelle für die Berechnung")}</h2>
<div class="tw"><table><tr><th>{T("Случай", "Case", "Fall")}</th><th class=r>{T("Порог", "Threshold", "Schwelle")}</th>
<th class=r>{T("Потеря массы на °C", "Weight loss per °C", "Massenverlust je °C")}</th>
<th class=r>{T("A320, пасс. на °C", "A320, pax per °C", "A320, Passagiere je °C")}</th>
<th>{T("Опора и разброс", "Basis and spread", "Grundlage und Streuung")}</th></tr>{trs}</table></div>
<p class="small">{T('''Порог — на сколько градусов жаркий месяц теплее стандартной атмосферы (ISA: 15 °C у моря, на 2 °C
меньше на каждые 300 м высоты), прежде чем начнётся ограничение.''',
                    "Threshold — how many degrees the hot month is warmer than the standard atmosphere (ISA: 15 °C at sea "
                    "level, 2 °C less for every 300 m of elevation) before the limit starts.",
                    "Schwelle — um wie viele Grad der heiße Monat wärmer ist als die Standardatmosphäre (ISA: 15 °C auf "
                    "Meereshöhe, 2 °C weniger je 300 m Höhe), bevor die Begrenzung einsetzt.")}</p>
<details><summary>{T("Другие типы — что известно", "Other types — what is known", "Andere Typen — was bekannt ist")}</summary>
<div class="tw"><table><tr><th>{T("Тип", "Type", "Typ")}</th><th>{T("Что известно", "What is known", "Was bekannt ist")}</th>
<th>{T("Число", "Figure", "Zahl")}</th><th>{T("Условия", "Conditions", "Bedingungen")}</th></tr>{ot}</table></div></details>
<details><summary>{T("Что происходило на деле", "What happened in practice", "Was in der Praxis geschah")}</summary>
<div class="tw"><table><tr><th>{T("Случай", "Case", "Fall")}</th><th>{T("Числа", "Figures", "Zahlen")}</th></tr>{cases}</table></div>
<p class="small">{T("Авиакомпании пишут об ограничениях словами — сколько мест сняли, не публикует никто.",
                    "Airlines describe the restrictions in words — nobody publishes how many seats were blocked.",
                    "Airlines beschreiben die Beschränkungen in Worten — wie viele Plätze gesperrt wurden, veröffentlicht "
                    "niemand.")}</p></details></section>"""

    pax45 = round(pax(dl45))
    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator", "Was wir im Rechner ändern")}</h2>
<p class="formula">{T('''ΔISA = T<sub>жаркого месяца</sub> − (15 − 1,98 · h<sub>тыс. футов</sub>)<br>
потеря взлётной массы, % = k · max(0, ΔISA − порог)<br>
снять нагрузку = max(0, плановая взлётная масса − допустимая), в пассажирах — по 100 кг''',
                      '''ΔISA = T<sub>hot month</sub> − (15 − 1.98 · h<sub>thousand ft</sub>)<br>
take-off weight loss, % = k · max(0, ΔISA − threshold)<br>
payload to offload = max(0, planned take-off weight − allowable), in passengers — 100 kg each''',
                      '''ΔISA = T<sub>heißer Monat</sub> − (15 − 1,98 · h<sub>Tsd. ft</sub>)<br>
Verlust an Startmasse, % = k · max(0, ΔISA − Schwelle)<br>
auszuladende Zuladung = max(0, geplante Startmasse − zulässige), in Passagieren — je 100 kg''')}</p>
<ol><li>{mark('planned')}{T('''<b>Только когда рейс упирается в массу.</b> Калькулятор уже знает плановую взлётную массу; если она ниже
допустимой с поправкой — ничего не меняется. Так что короткие рейсы жара не трогает.''',
        "<b>Only when the flight is weight-limited.</b> The calculator already knows the planned take-off weight; if it is "
        "below the corrected allowable weight, nothing changes. So heat does not touch short flights.",
        "<b>Nur wenn der Flug an die Massengrenze stößt.</b> Der Rechner kennt die geplante Startmasse bereits; liegt sie "
        "unter der korrigierten zulässigen Masse, ändert sich nichts. Kurze Flüge berührt die Hitze also nicht.")}</li>
<li>{mark('planned')}{T('''<b>Строка таблицы — по полосе и высоте</b> аэродрома (они в справочнике), температура — средний максимум месяца
рейса.''',
        "<b>The table row is chosen by the runway and elevation</b> of the airfield (both are in the reference data); the "
        "temperature is the mean maximum of the flight's month.",
        "<b>Die Tabellenzeile richtet sich nach Piste und Höhe</b> des Flugplatzes (beide stehen im Verzeichnis); die "
        "Temperatur ist das mittlere Maximum des Flugmonats.")}</li>
<li>{mark('planned')}{T(f'''<b>Снятые пассажиры</b> уменьшают выручку; затраты на рейс те же — себестоимость на пассажира растёт. Дели в мае:
−{lost} пасс., при 45 °C — около {pax45}.''',
        f"<b>Offloaded passengers</b> reduce revenue; the flight costs stay the same — cost per passenger rises. Delhi in "
        f"May: −{lost} passengers, at 45 °C — about {pax45}.",
        f"<b>Ausgeladene Passagiere</b> senken den Erlös; die Flugkosten bleiben gleich — die Kosten je Passagier steigen. "
        f"Delhi im Mai: −{lost} Passagiere, bei 45 °C — etwa {pax45}.")}</li>
<li>{mark('planned')}{T('''<b>Всё — с оранжевой пометкой «оценка».</b> Для турбовинтовых, E-Jet и аэродромов выше 2 100 м поправку не
считаем, а предупреждаем.''',
        "<b>Everything carries the orange “estimate” flag.</b> For turboprops, E-Jets and airfields above 2,100 m we do not "
        "compute a correction but show a warning.",
        "<b>Alles mit der orangen Kennzeichnung „Schätzung“.</b> Für Turboprops, E-Jets und Flugplätze über 2.100 m "
        "berechnen wir keine Korrektur, sondern geben eine Warnung aus.")}</li>
<li>{mark('on_input')}{T('''<b>Пока поправки нет</b> — на жарком или высоком аэродроме и длинном секторе снижайте загрузку вручную по таблице
выше.''',
        "<b>Until the correction is in</b> — at a hot or high airfield on a long sector, reduce the load by hand using the "
        "table above.",
        "<b>Solange die Korrektur fehlt</b> — auf einem heißen oder hoch gelegenen Flugplatz und einer langen Strecke die "
        "Beladung von Hand nach der Tabelle oben senken.")}</li></ol></section>"""

    doubts = [x for x in D["doubts"] if not any(w in x for w in CLOSED)]   # фильтр — по русскому оригиналу
    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T(f'''Журнал — {steps} шагов: поиск исследователя (<code>trace/h1.jsonl</code>) и теория по документам владельца
(<code>trace/h2.jsonl</code>). Цитаты сверены (<code>verify/</code>): найдено дословно {st['found']}, частично
{st.get('partial', 0)}, не найдено {st.get('not_found', 0)}. Отдельный агент воспроизвёл расчёт порогов, наклонов и
примера Дели; таблица 2 журнальной версии Coffel &amp; Horton совпала с версией конференции по всем числам.''',
      f"The log has {steps} steps: the researcher's search (<code>trace/h1.jsonl</code>) and the theory from the owner's "
      f"documents (<code>trace/h2.jsonl</code>). Quotes were checked (<code>verify/</code>): found verbatim {st['found']}, "
      f"partly {st.get('partial', 0)}, not found {st.get('not_found', 0)}. A separate agent reproduced the calculation of "
      f"the thresholds, the slopes and the Delhi example; table 2 of the journal version of Coffel &amp; Horton matched the "
      f"conference version in every figure.",
      f"Das Protokoll hat {steps} Schritte: die Suche des Rechercheurs (<code>trace/h1.jsonl</code>) und die Theorie aus den "
      f"Dokumenten des Eigentümers (<code>trace/h2.jsonl</code>). Die Zitate wurden geprüft (<code>verify/</code>): wörtlich "
      f"gefunden {st['found']}, teilweise {st.get('partial', 0)}, nicht gefunden {st.get('not_found', 0)}. Ein separater "
      f"Agent hat die Berechnung der Schwellen, der Steigungen und des Delhi-Beispiels nachvollzogen; Tabelle 2 der "
      f"Zeitschriftenfassung von Coffel &amp; Horton stimmte in allen Zahlen mit der Konferenzfassung überein.")}</p>
<details><summary>{T("Чего нет и в чём сомнения", "What is missing and what is in doubt",
                     "Was fehlt und was zweifelhaft ist")}</summary><ul>{''.join(f'<li>{e(TR(x))}</li>' for x in D['gaps'])}
{''.join(f'<li>{e(TR(x))}</li>' for x in doubts)}
{''.join(f'<li>{e(TR(x))}</li>' for x in m['limits'])}</ul></details>
<details><summary>{T("Что осталось до публикации", "What is left before publication",
                     "Was bis zur Veröffentlichung noch fehlt")}</summary><ul>
<li>{T('''Числа по типам: графики «взлётная масса — длина полосы — температура — высота» из документов Airbus (AC, раздел
3-3) и Boeing (D6-58325-6) — ручной съём для A320, A321, 737-800.''',
       "Figures by type: the “take-off weight — runway length — temperature — elevation” charts from the Airbus (AC, "
       "section 3-3) and Boeing (D6-58325-6) documents — to be read off by hand for the A320, A321 and 737-800.",
       "Zahlen nach Typ: die Diagramme „Startmasse — Pistenlänge — Temperatur — Höhe“ aus den Dokumenten von Airbus (AC, "
       "Abschnitt 3-3) und Boeing (D6-58325-6) — von Hand ablesen für A320, A321 und 737-800.")}</li>
<li>{T('''Теория закрыта (FAA PHAK гл. 5 и 11, CS-25 Subpart B, журнальная версия Coffel &amp; Horton — переданы
30.10.2026, журнал <code>trace/h2.jsonl</code>).''',
       "The theory is closed (FAA PHAK ch. 5 and 11, CS-25 Subpart B, the journal version of Coffel &amp; Horton — provided "
       "on 2026-10-30, log <code>trace/h2.jsonl</code>).",
       "Die Theorie ist abgeschlossen (FAA PHAK Kap. 5 und 11, CS-25 Subpart B, Zeitschriftenfassung von Coffel &amp; "
       "Horton — übergeben am 30.10.2026, Protokoll <code>trace/h2.jsonl</code>).")}</li></ul></details>
{S.html()}</section>"""
    return page(article_title("hothigh-2026-10"), ARTICLE_CSS + hook + theory + analytics + facts + concl + report)


if __name__ == "__main__":
    write_all(HERE, "hothigh-2026-10", build, TR)
