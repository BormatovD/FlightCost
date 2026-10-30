"""Раздел «Как не стоять на земле»: планирование ТО, простои, контракты, станции, запчасти (out/n4.json,
trace/n4.jsonl; резерв и запасные двигатели — n3). Связный текст, схемы — svg.year и svg.layers.
Тексты — T(ru, en, de)."""

from _report import T


def section(N4, cite, n, e, svg):
    checks = [(T("Ежедневная (daily)", "Daily check", "Daily Check"),
               T("действует до 48 часов", "valid for up to 48 hours", "gilt bis zu 48 Stunden"),
               T("на стоянке между рейсами или ночью", "on the ground between flights or overnight",
                 "am Boden zwischen Flügen oder nachts"), ["n4-016"]),
              (T("Еженедельная (weekly)", "Weekly check", "Weekly Check"), T("раз в неделю", "once a week", "einmal pro Woche"),
               T("ночью, обычно на базе", "overnight, usually at base", "nachts, meist an der Basis"), ["n4-286"]),
              (T("Форма A (A-check), A320", "A-check, A320", "A-Check, A320"),
               T("750 → до 1 000 лётных часов или 4–6 месяцев", "750 → up to 1,000 flight hours or 4–6 months",
                 "750 → bis 1.000 Flugstunden oder 4–6 Monate"),
               T("одна ночь в ангаре, около 150 человеко-часов", "one night in the hangar, about 150 man-hours",
                 "eine Nacht im Hangar, etwa 150 Arbeitsstunden"), ["n4-007", "n4-220", "n4-280"]),
              (T("Форма C (C-check), A320", "C-check, A320", "C-Check, A320"),
               T("задачи с 24 переводятся на 36 месяцев", "tasks moving from 24 to 36 months",
                 "Aufgaben wandern von 24 auf 36 Monate"),
               T("от 3 суток до 3 недель, находки — ещё неделя", "3 days to 3 weeks, findings add another week",
                 "3 Tage bis 3 Wochen, Befunde noch eine Woche dazu"), ["n4-006", "n4-223", "n4-225", "n4-224"]),
              (T("Базовая форма 737-8 MAX (SmartLynx)", "737-8 MAX base check (SmartLynx)", "737-8 MAX Base Check (SmartLynx)"),
               T("3 года, 7 500 лётных часов или 5 000 циклов", "3 years, 7,500 flight hours or 5,000 cycles",
                 "3 Jahre, 7.500 Flugstunden oder 5.000 Zyklen"),
               T("стоянка в ангаре, как у формы C", "hangar downtime, like a C-check", "Hangarstandzeit wie beim C-Check"),
               ["n4-291"]),
              (T("Тяжёлая форма (D-check)", "Heavy check (D-check)", "Schwerer Check (D-Check)"),
               T("самая редкая", "the rarest", "der seltenste"), T("около двух месяцев", "about two months", "etwa zwei Monate"),
               ["n4-203"])]
    t_chk = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}{cite(*ev)}</td></tr>" for a, b, c, ev in checks)
    year = svg.year([9, 9, 10, 11, 12, 13, 13.5, 13.5, 12.5, 11, 9.5, 9], a_fh=750, c_months=(0,))

    contracts = [
        (T("Двигатель «за лётный час» (PBH: TotalCare, RPFH, EngineWise)",
           "Engine “by the flight hour” (PBH: TotalCare, RPFH, EngineWise)",
           "Triebwerk „pro Flugstunde“ (PBH: TotalCare, RPFH, EngineWise)"),
         T("ремонты двигателя, плановые и внеплановые", "engine repairs, scheduled and unscheduled",
           "Triebwerksreparaturen, geplant und ungeplant"),
         T("производитель", "manufacturer", "Hersteller"),
         T("ставка за час работы двигателя, 10–12 лет, ежегодная индексация",
           "rate per engine flight hour, 10–12 years, annual escalation",
           "Satz je Triebwerksstunde, 10–12 Jahre, jährliche Indexierung"),
         T("новый тип, малый и средний парк", "new type, small and mid-size fleets", "neuer Typ, kleine und mittlere Flotten"),
         ["n4-044", "n4-065", "n4-194", "n4-212", "n4-211"]),
        (T("Полная поддержка компонентов (TCS)", "Total component support (TCS)", "Total Component Support (TCS)"),
         T("пул агрегатов, ремонт, логистика, комплект на базе", "component pool, repair, logistics, kit at base",
           "Komponentenpool, Reparatur, Logistik, Kit an der Basis"),
         T("поставщик", "provider", "Anbieter"),
         T("ставка за лётный час, 5–11 лет", "rate per flight hour, 5–11 years", "Satz je Flugstunde, 5–11 Jahre"),
         T("малый и средний парк без своего пула", "small and mid-size fleets without their own pool",
           "kleine und mittlere Flotten ohne eigenen Pool"), ["n4-049", "n4-050", "n4-184"]),
        (T("Обмен агрегата (exchange)", "Unit exchange", "Tausch (Exchange)"),
         T("исправный агрегат сразу, снятый уходит в ремонт", "a serviceable unit at once, the removed one goes for repair",
           "sofort ein funktionsfähiges Teil, das ausgebaute geht in Reparatur"),
         T("поровну, по договору", "shared, per contract", "geteilt, laut Vertrag"),
         T("около 10 % цены агрегата плюс ремонт снятого", "about 10 % of the unit price plus repair of the removed one",
           "etwa 10 % des Teilepreises plus Reparatur des ausgebauten"),
         T("разовые отказы", "one-off failures", "einzelne Ausfälle"), ["n4-186", "n4-187"]),
        (T("Консигнационный склад", "Consignment stock", "Konsignationslager"),
         T("детали поставщика лежат у авиакомпании", "the supplier's parts sit at the airline",
           "Teile des Lieferanten lagern bei der Airline"),
         T("поставщик — за запас", "supplier — for the stock", "Lieferant — für den Bestand"),
         T("по факту использования", "on use", "bei Verbrauch"),
         T("база с частыми заменами", "a base with frequent replacements", "Basis mit häufigem Austausch"),
         ["n4-313", "n4-314"]),
        (T("Тяжёлая форма у сторонней организации", "Heavy check at a third-party MRO", "Schwerer Check bei einem Fremd-MRO"),
         T("проверка в ангаре по пакету задач", "a hangar check by work package", "Hangar-Check nach Arbeitspaket"),
         T("авиакомпания — за находки", "airline — for findings", "Airline — für Befunde"),
         T("фиксированная цена за рутину плюс находки по факту", "fixed price for routine work plus findings at cost",
           "Festpreis für Routine plus Befunde nach Aufwand"),
         T("все, кто не держит ангар", "everyone without their own hangar", "alle ohne eigenen Hangar"),
         ["n4-202", "n4-264"]),
        (T("Линейное ТО у подрядчика", "Line maintenance by a contractor", "Linienwartung durch einen Dienstleister"),
         T("проверки на выездной станции, вызов техника", "checks at an outstation, technician call-out",
           "Checks an einer Außenstation, Technikereinsatz auf Abruf"),
         T("авиакомпания", "airline", "Airline"),
         T("за событие или человеко-час", "per event or per man-hour", "pro Ereignis oder Arbeitsstunde"),
         T("аэропорты с редкими рейсами", "airports with few flights", "Flughäfen mit wenigen Flügen"),
         ["n4-159", "n4-308", "n4-309"]),
    ]
    t_con = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td><td>{e(d)}</td><td>{e(f)}{cite(*ev)}</td></tr>"
                    for a, b, c, d, f, ev in contracts)
    layers = svg.layers([
        (T("Поставщик и общий пул", "Supplier and shared pool", "Lieferant und gemeinsamer Pool"),
         T("производитель, компонентный пул, межавиакомпанейский пул IATP: 6 600 позиций на 350 станциях",
           "manufacturer, component pool, the inter-airline IATP pool: 6,600 items at 350 stations",
           "Hersteller, Komponentenpool, airlineübergreifender IATP-Pool: 6.600 Positionen an 350 Stationen"),
         T("обмен или доставка", "exchange or delivery", "Tausch oder Lieferung"), "var(--t3)"),
        (T("Центральный склад авиакомпании или поставщика", "Central store of the airline or supplier",
           "Zentrallager der Airline oder des Lieferanten"),
         T("основной запас агрегатов, расчёт под уровень сервиса 95–99 %",
           "main stock of components, sized for a 95–99 % service level",
           "Hauptbestand an Komponenten, ausgelegt auf 95–99 % Servicegrad"),
         T("критичная деталь — за 3 часа", "critical part — within 3 hours", "kritisches Teil — in 3 Stunden"), "var(--t1)"),
        (T("Комплект на главной базе", "Kit at the main base", "Kit an der Hauptbasis"),
         T("критичные агрегаты поставщика прямо в ангаре базы (main base kit)",
           "the supplier's critical components right in the base hangar (main base kit)",
           "kritische Komponenten des Lieferanten direkt im Basishangar (Main Base Kit)"),
         T("на месте", "on site", "vor Ort"), "var(--sky)"),
        (T("Линейная станция", "Line station", "Linienstation"),
         T("расходники и частые замены; дефекты по MEL ждут ночёвки на базе",
           "consumables and frequent replacements; MEL defects wait for a night at base",
           "Verbrauchsmaterial und häufige Tauschteile; MEL-Mängel warten auf die Nacht an der Basis"),
         T("на месте или следующим рейсом", "on site or on the next flight", "vor Ort oder mit dem nächsten Flug"),
         "var(--t2)"),
        (T("Fly-away kit на борту", "Fly-away kit on board", "Fly-away-Kit an Bord"),
         T("детали и инструмент для удалённых аэропортов без своей станции",
           "parts and tools for remote airports without one's own station",
           "Teile und Werkzeug für entlegene Flughäfen ohne eigene Station"),
         T("с самолётом", "with the aircraft", "mit dem Flugzeug"), "var(--green)")])

    intro = T(f"""<p>Самолёт зарабатывает только в воздухе, а техническое обслуживание — главный законный повод держать его на земле.
Поэтому авиакомпании, которые летают по 12–13 часов в сутки, не выбирают между налётом и ТО: они встраивают
обслуживание в паузы, которые сеть и так оставляет, — ночи на базе и зимний низкий сезон, — а неплановые поломки
превращают с помощью контрактов, резерва и запчастей в предсказуемые расходы. Ниже — как это устроено по шагам.</p>""",
              f"""<p>An aircraft earns money only in the air, and maintenance is the main legitimate reason to keep it on the
ground. That is why airlines flying 12–13 hours a day do not choose between utilisation and maintenance: they fit
maintenance into the gaps the network leaves anyway — nights at base and the winter low season — and use contracts,
reserves and spare parts to turn unscheduled failures into predictable costs. Here is how it works, step by step.</p>""",
              f"""<p>Ein Flugzeug verdient nur in der Luft Geld, und die Wartung ist der wichtigste legitime Grund, es am Boden zu
halten. Deshalb wählen Airlines, die 12–13 Stunden am Tag fliegen, nicht zwischen Auslastung und Wartung: Sie legen die
Wartung in die Pausen, die das Netz ohnehin lässt — Nächte an der Basis und die winterliche Nebensaison —, und machen
ungeplante Ausfälle mit Verträgen, Reserven und Ersatzteilen zu planbaren Kosten. So funktioniert das Schritt für
Schritt.</p>""")

    program = T(f"""<h3>Программа ТО: формы, интервалы и что наступит раньше</h3>
<p>Производитель самолёта выпускает документ планирования обслуживания (MPD), авиакомпания делает из него собственную
программу ТО, утверждённую авиационными властями. Задачи программы сгруппированы в формы — пакеты работ с порогами по
лётным часам, циклам (взлёт-посадка) и календарю; форму выполняют, когда наступает первый из порогов. Лёгкие формы
частые и короткие, тяжёлые — редкие и долгие:</p>
<div class="tw"><table><tr><th>Форма</th><th>Как часто</th><th>Сколько стоит на земле</th></tr>{t_chk}</table></div>
<p>Для сети из этой таблицы следуют две вещи. Ежедневная и еженедельная проверки и форма A делаются ночью — значит,
самолёт должен регулярно ночевать там, где есть механики, ангар и запчасти, и это одно из главных требований к выбору
баз. На выездных станциях делают минимум, остальное копят до еженедельной проверки на базе{cite('n4-286', 'n4-288')}.
Второе: при высоком налёте раньше наступают часы и циклы, а не календарь. В спецификации одного 737-8 MAX авиакомпании
SmartLynx (2024) предел базовой формы — 7 500 часов: при 10 блок-часах в сутки он наступает примерно через 2,4 года, при
16 — через полтора; при шести рейсах в сутки 5 000 циклов набираются за 2,3 года{cite('n4-293')}. Каждая лишняя тысяча
часов налёта приближает следующую стоянку.</p>""",
                f"""<h3>The maintenance programme: checks, intervals and whichever comes first</h3>
<p>The aircraft manufacturer issues a maintenance planning document (MPD); the airline turns it into its own maintenance
programme, approved by the aviation authority. The programme's tasks are grouped into checks — work packages with
thresholds in flight hours, cycles (one take-off and landing) and calendar time; a check is due when the first threshold
is reached. Light checks are frequent and short, heavy checks rare and long:</p>
<div class="tw"><table><tr><th>Check</th><th>How often</th><th>Time on the ground</th></tr>{t_chk}</table></div>
<p>Two things follow from this table for the network. Daily and weekly checks and the A-check are done overnight — so
the aircraft must regularly spend the night where there are mechanics, a hangar and spare parts, and this is one of
the main requirements when choosing bases. Outstations do the minimum; the rest is saved up for the weekly check at base
{cite('n4-286', 'n4-288')}. Second: at high utilisation, hours and cycles run out before the calendar does. In the
specification of one 737-8 MAX operated by SmartLynx (2024), the base-check limit is 7,500 hours: at 10 block hours a
day it is reached after about 2.4 years, at 16 after a year and a half; at six flights a day, 5,000 cycles are reached
in 2.3 years{cite('n4-293')}. Every extra thousand flight hours brings the next downtime closer.</p>""",
                f"""<h3>Das Wartungsprogramm: Checks, Intervalle und was zuerst eintritt</h3>
<p>Der Flugzeughersteller gibt ein Wartungsplanungsdokument (MPD) heraus; die Airline macht daraus ihr eigenes, von der
Luftfahrtbehörde genehmigtes Wartungsprogramm. Die Aufgaben sind zu Checks gebündelt — Arbeitspaketen mit Schwellen in
Flugstunden, Zyklen (ein Start und eine Landung) und Kalenderzeit; der Check ist fällig, sobald die erste Schwelle
erreicht ist. Leichte Checks sind häufig und kurz, schwere selten und lang:</p>
<div class="tw"><table><tr><th>Check</th><th>Wie oft</th><th>Zeit am Boden</th></tr>{t_chk}</table></div>
<p>Für das Netz folgen daraus zwei Dinge. Daily und Weekly Check sowie der A-Check werden nachts gemacht — das Flugzeug
muss also regelmäßig dort übernachten, wo es Mechaniker, einen Hangar und Ersatzteile gibt; das ist eine der wichtigsten
Anforderungen bei der Wahl der Basen. Außenstationen machen nur das Nötigste, der Rest wird bis zum Weekly Check an der
Basis gesammelt{cite('n4-286', 'n4-288')}. Zweitens: Bei hoher Auslastung laufen Stunden und Zyklen vor dem Kalender ab.
In der Spezifikation einer 737-8 MAX von SmartLynx (2024) liegt die Grenze des Base Checks bei 7.500 Stunden: Bei 10
Blockstunden am Tag ist sie nach etwa 2,4 Jahren erreicht, bei 16 nach anderthalb; bei sechs Flügen am Tag sind 5.000
Zyklen nach 2,3 Jahren voll{cite('n4-293')}. Jede zusätzliche tausend Flugstunden rückt die nächste Standzeit näher.</p>""")

    after_year = T(f"""<p class="small">Схема: налёт по месяцам условный, плечо 2 часа, руление 20 минут на рейс; форма A — каждые 750 лётных
часов (в оптимизированных программах — до 1 000). Форма C поставлена на январь.</p>
<p>Длинные стоянки сокращают двумя способами. Первый — равномерно распределённая программа (equalized): задачи формы C
раскладывают по ночным визитам, и многонедельной стоянки нет вовсе. easyJet работает по такой схеме с 2004 года,
JetBlue разбил пакет формы A на 32 ночные сегментированные проверки{cite('n4-013', 'n4-015', 'n4-221')}. Плата —
ангар и бригада на базе каждую ночь, а по мере старения парка находок становится больше, и схема работает хуже: easyJet
в 2019 году её пересматривал{cite('n4-362', 'n4-363')}. Второй способ — перенести тяжёлые формы на зиму, когда самолёты
всё равно нужны меньше, а места в ангарах сторонних организаций дешевле{cite('n4-200')}. Ryanair покупает под зимние
сезоны «линии» тяжёлого ТО у сторонних организаций — в 2024 году, например, десять линий в Аммане на десять лет
{cite('n4-264', 'n4-266')}. Так зимний провал налёта частично заполняется обслуживанием, а летом летают все самолёты.</p>""",
                   f"""<p class="small">Schematic: monthly utilisation is illustrative, 2-hour sectors, 20 minutes of taxi per
flight; A-check every 750 flight hours (up to 1,000 in optimised programmes). The C-check is placed in January.</p>
<p>Long downtimes are shortened in two ways. The first is an equalized programme: C-check tasks are spread over
overnight visits, so there is no multi-week downtime at all. easyJet has worked this way since 2004; JetBlue split its
A-check package into 32 segmented overnight checks{cite('n4-013', 'n4-015', 'n4-221')}. The price is a hangar and a
crew at base every night, and as the fleet ages there are more findings and the scheme works less well: easyJet reviewed
it in 2019{cite('n4-362', 'n4-363')}. The second is to move heavy checks to winter, when fewer aircraft are needed
anyway and third-party hangar slots are cheaper{cite('n4-200')}. Ryanair buys heavy-maintenance “lines” at third-party
MROs for the winter seasons — in 2024, for instance, ten lines in Amman for ten years{cite('n4-264', 'n4-266')}. So the
winter dip in utilisation is partly filled with maintenance, and in summer every aircraft flies.</p>""",
                   f"""<p class="small">Schema: Monatsauslastung beispielhaft, 2-Stunden-Strecken, 20 Minuten Rollen je Flug;
A-Check alle 750 Flugstunden (in optimierten Programmen bis 1.000). Der C-Check liegt im Januar.</p>
<p>Lange Standzeiten werden auf zwei Wegen verkürzt. Der erste ist ein gleichmäßig verteiltes Programm (equalized): Die
Aufgaben des C-Checks werden auf nächtliche Besuche verteilt, eine mehrwöchige Standzeit gibt es gar nicht. easyJet
arbeitet seit 2004 so, JetBlue hat sein A-Check-Paket in 32 segmentierte Nacht-Checks aufgeteilt
{cite('n4-013', 'n4-015', 'n4-221')}. Der Preis: jede Nacht ein Hangar und ein Team an der Basis, und mit dem Altern der
Flotte gibt es mehr Befunde und das Schema funktioniert schlechter — easyJet hat es 2019 überprüft
{cite('n4-362', 'n4-363')}. Der zweite Weg: schwere Checks in den Winter legen, wenn ohnehin weniger Flugzeuge gebraucht
werden und Hangarplätze bei Fremd-MROs billiger sind{cite('n4-200')}. Ryanair kauft für die Wintersaisons „Linien“ für
schwere Wartung bei Fremd-MROs — 2024 zum Beispiel zehn Linien in Amman für zehn Jahre{cite('n4-264', 'n4-266')}. So wird
die Winterdelle der Auslastung teilweise mit Wartung gefüllt, und im Sommer fliegen alle Flugzeuge.</p>""")

    downtime = T(f"""<h3>Как избегают простоев</h3>
<p>Неплановый простой — самолёт не может вылететь из-за неисправности, на жаргоне AOG (aircraft on ground) — случается
редко, но обходится дорого. Нормальная техническая регулярность узкофюзеляжного парка — 99,4–99,8 % вылетов без
технической задержки больше 15 минут или отмены: в среднем по миру у A320neo — 99,59 %, у easyJet — 99,57 %
{cite('n4-022', 'n4-229', 'n4-328', 'n4-331', 'n4-332')}. Это 2–6 технических срывов на тысячу вылетов; при парке в сто
самолётов и шести рейсах в сутки — от одного до четырёх в день.</p>
<p>Первый инструмент против простоя — перечень минимального оборудования (MEL): он разрешает вылет с некоторыми
неисправностями при условии, что дефект устранят в срок — для категории B за 3 дня, C — за 10, D — за 120
{cite('n4-150', 'n4-151', 'n4-152')}. Для сети это ключевая вещь: дефект, найденный на выездной станции, переносят до
ночёвки на базе, где есть и деталь, и механик.</p>
<p>Второй — надёжность и прогноз отказов. Это уже не реклама, а подтверждённые цифры: Delta сократила число отмен по
техническим причинам с 5 647 в 2010 году до 55 в 2018-м{cite('n4-032', 'n4-029')}; easyJet с января 2019 по сентябрь
2025 года предотвратил прогнозными моделями 1 343 отмены — около двухсот в год на парк примерно из 350 самолётов, — а
78 % отказов таких компонентов на крыле означали бы простой больше трёх часов{cite('n4-231', 'n4-236')}. British Airways,
заменяя стартерные клапаны до отказа по признаку затянутого запуска двигателя, сократила простой парка A320neo примерно на
4 %{cite('n4-024', 'n4-025')}. У малой авиакомпании своей науки о данных обычно нет, но часть эффекта она получает через
контракты: производитель двигателя и поставщик компонентов сами следят за состоянием агрегатов{cite('n4-044', 'n4-049')}.
</p>
<p>Третий — резерв. easyJet летом 2024 года держал 14 резервных самолётов, около 4 % парка, Ryanair — около восьми,
1,3 %{cite('n3-083', 'n3-084', 'n3-092')}. Запасные двигатели — 14–15 % от установленных у CFM56 и V2500 и около 21 % у
Wizz Air с проблемными GTF{cite('n3-105', 'n3-106', 'n3-114')}. Если своего резерва нет или поломка затянулась, берут
самолёт с экипажем в мокрый лизинг (ACMI) — от нескольких рейсов до месяцев{cite('n4-274', 'n4-275')}. Резерв — это
лизинговые платежи без налёта, поэтому он прямо снижает средний налёт парка.</p>""",
                 f"""<h3>How downtime is avoided</h3>
<p>Unscheduled downtime — the aircraft cannot depart because of a defect, AOG (aircraft on ground) in the jargon — is
rare but expensive. Normal technical dispatch reliability for a narrowbody fleet is 99.4–99.8 % of departures without a
technical delay of more than 15 minutes or a cancellation: the world average for the A320neo is 99.59 %, easyJet's is
99.57 %{cite('n4-022', 'n4-229', 'n4-328', 'n4-331', 'n4-332')}. That is 2–6 technical disruptions per thousand
departures; for a fleet of a hundred aircraft with six flights a day, one to four a day.</p>
<p>The first tool against downtime is the minimum equipment list (MEL): it allows departure with certain defects
provided they are fixed in time — 3 days for category B, 10 for C, 120 for D{cite('n4-150', 'n4-151', 'n4-152')}. For
the network this is key: a defect found at an outstation is deferred until the night at base, where both the part and
the mechanic are.</p>
<p>The second is reliability and failure prediction. These are no longer marketing claims but confirmed figures: Delta
cut maintenance cancellations from 5,647 in 2010 to 55 in 2018{cite('n4-032', 'n4-029')}; between January 2019 and
September 2025 easyJet's predictive models prevented 1,343 cancellations — about two hundred a year for a fleet of
roughly 350 aircraft — and 78 % of on-wing failures of such components would have meant more than three hours of
downtime{cite('n4-231', 'n4-236')}. By replacing starter valves before failure, flagged by slow engine starts, British
Airways cut A320neo fleet downtime by about 4 %{cite('n4-024', 'n4-025')}. A small airline usually has no data science
of its own, but it gets part of the effect through its contracts: the engine maker and the component provider monitor the
units themselves{cite('n4-044', 'n4-049')}.</p>
<p>The third is reserves. In summer 2024 easyJet held 14 spare aircraft, about 4 % of the fleet, Ryanair about eight,
1.3 %{cite('n3-083', 'n3-084', 'n3-092')}. Spare engines are 14–15 % of installed engines for the CFM56 and V2500 and about
21 % at Wizz Air with its troubled GTFs{cite('n3-105', 'n3-106', 'n3-114')}. If there is no reserve of one's own or a
repair drags on, airlines wet-lease an aircraft with crew (ACMI) — from a few flights to months{cite('n4-274', 'n4-275')}.
A reserve means lease payments without flying, so it directly lowers the fleet's average utilisation.</p>""",
                 f"""<h3>Wie Stillstand vermieden wird</h3>
<p>Ungeplanter Stillstand — das Flugzeug kann wegen eines Defekts nicht starten, im Jargon AOG (aircraft on ground) — ist
selten, aber teuer. Die normale technische Abflugzuverlässigkeit einer Schmalrumpfflotte liegt bei 99,4–99,8 % der
Abflüge ohne technische Verspätung über 15 Minuten oder Annullierung: weltweit im Schnitt 99,59 % beim A320neo, 99,57 %
bei easyJet{cite('n4-022', 'n4-229', 'n4-328', 'n4-331', 'n4-332')}. Das sind 2–6 technische Störungen je tausend Abflüge;
bei einer Flotte von hundert Flugzeugen mit sechs Flügen am Tag eine bis vier pro Tag.</p>
<p>Das erste Werkzeug gegen Stillstand ist die Mindestausrüstungsliste (MEL): Sie erlaubt den Abflug mit bestimmten
Mängeln, sofern sie fristgerecht behoben werden — Kategorie B in 3 Tagen, C in 10, D in 120
{cite('n4-150', 'n4-151', 'n4-152')}. Für das Netz ist das zentral: Ein an einer Außenstation gefundener Mangel wird bis
zur Nacht an der Basis zurückgestellt, wo Teil und Mechaniker vorhanden sind.</p>
<p>Das zweite ist Zuverlässigkeit und Ausfallprognose. Das ist keine Werbung mehr, sondern belegt: Delta senkte die
technisch bedingten Annullierungen von 5.647 im Jahr 2010 auf 55 im Jahr 2018{cite('n4-032', 'n4-029')}; easyJet verhinderte
von Januar 2019 bis September 2025 mit Prognosemodellen 1.343 Annullierungen — rund zweihundert pro Jahr bei einer Flotte
von etwa 350 Flugzeugen —, und 78 % der Ausfälle solcher Komponenten am Flügel hätten mehr als drei Stunden Stillstand
bedeutet{cite('n4-231', 'n4-236')}. British Airways tauschte Anlasserventile vor dem Ausfall, erkannt an verzögerten
Triebwerksstarts, und senkte so den Stillstand der A320neo-Flotte um etwa 4 %{cite('n4-024', 'n4-025')}. Eine kleine
Airline hat meist keine eigene Datenanalyse, bekommt aber einen Teil des Effekts über ihre Verträge: Triebwerkshersteller
und Komponentenanbieter überwachen den Zustand der Teile selbst{cite('n4-044', 'n4-049')}.</p>
<p>Das dritte ist die Reserve. easyJet hielt im Sommer 2024 14 Reserveflugzeuge, etwa 4 % der Flotte, Ryanair rund acht,
1,3 %{cite('n3-083', 'n3-084', 'n3-092')}. Ersatztriebwerke machen 14–15 % der eingebauten bei CFM56 und V2500 aus und etwa
21 % bei Wizz Air mit den problematischen GTF{cite('n3-105', 'n3-106', 'n3-114')}. Fehlt eine eigene Reserve oder zieht sich
eine Reparatur hin, wird ein Flugzeug mit Besatzung im Wet Lease (ACMI) genommen — von einigen Flügen bis zu Monaten
{cite('n4-274', 'n4-275')}. Reserve heißt Leasingzahlungen ohne Flugstunden; sie senkt also direkt die durchschnittliche
Auslastung der Flotte.</p>""")

    contracts_txt = T(f"""<h3>Контракты: кто несёт риск</h3>
<p>ТОиР в среднем по выборке IATA стоит 1 522 доллара за лётный час, около 11,5 % операционных расходов; половина этих
денег — двигатели, 18 % — компоненты{cite('n4-061', 'n4-059', 'n4-058')}. Две трети затрат на двигатель — его заходы в цех
{cite('n4-213')}: редкие, огромные и плохо предсказуемые платежи. Поэтому главный вопрос любого контракта на ТО — кто
несёт риск отказа.</p>
<p>По контракту «за лётный час» (power by the hour, PBH) на двигатель производитель берёт на себя риск отказов и
стоимость всех ремонтов, а авиакомпания платит ставку за каждый час работы двигателя{cite('n4-044', 'n4-065', 'n4-194')}.
Такие контракты заключают лет на 10–12, и они доступны не только гигантам: китайская Colorful Guizhou с парком около
пятнадцати A320neo подписала с CFM соглашение о двенадцатилетнем контракте примерно на 500 миллионов долларов по прайсу
{cite('n4-212', 'n4-066')}. Особенно выгоден PBH на новом типе двигателя — производитель делит риск надёжности новой
техники{cite('n4-206')}. Плата за предсказуемость — премия за риск в ставке и ежегодная индексация на высокие однозначные и
низкие двузначные проценты, а ещё зависимость от одного поставщика, который знает о двигателе больше авиакомпании
{cite('n4-216', 'n4-211', 'n4-218')}.</p>
<p>Для агрегатов — насосов, клапанов, блоков электроники — аналог PBH называется полной поддержкой компонентов (total
component support): поставщик даёт доступ к своему пулу, ремонтирует снятое, возит детали и кладёт комплект критичных
агрегатов прямо на главную базу клиента, на срок от 5 до 11 лет{cite('n4-049', 'n4-050', 'n4-184')}. Всё остальное
покупают точечно — обменом, консигнацией, разовым заказом:</p>
<div class="tw"><table><tr><th>Контракт</th><th>Что покрывает</th><th>Кто несёт риск</th><th>Как платят</th>
<th>Кому подходит</th></tr>{t_con}</table></div>
<p>Малой и крупной авиакомпании выгодно разное, и причина — эффект масштаба. Запас агрегатов растёт медленнее парка: в
общем пуле один запасной агрегат страхует сразу много самолётов, и на сотню бортов его нужно тем меньше, чем больше
парк в пуле{cite('n4-144', 'n4-172')}. Малая авиакомпания этот эффект сама не получит, поэтому ей выгодны PBH на
двигатели и полная поддержка компонентов: она покупает чужой масштаб пула. Крупные строят своё, но и Ryanair при
шестистах самолётах сочетает собственное и покупное ТО{cite('n4-269')}.</p>""",
                      f"""<h3>Contracts: who carries the risk</h3>
<p>Across the IATA sample, maintenance averages 1,522 dollars per flight hour, about 11.5 % of operating costs; half of
that money goes on engines, 18 % on components{cite('n4-061', 'n4-059', 'n4-058')}. Two thirds of engine costs are shop
visits{cite('n4-213')}: rare, huge and hard-to-predict payments. So the key question of any maintenance contract is who
carries the risk of failure.</p>
<p>Under a “by the hour” engine contract (power by the hour, PBH) the manufacturer takes on the failure risk and the cost
of all repairs, and the airline pays a rate for every engine flight hour{cite('n4-044', 'n4-065', 'n4-194')}. These
contracts run for 10–12 years and are not only for giants: China's Colorful Guizhou, with a fleet of about fifteen
A320neo, signed an agreement with CFM for a twelve-year contract worth about 500 million dollars at list price
{cite('n4-212', 'n4-066')}. PBH is particularly attractive on a new engine type — the manufacturer shares the reliability
risk of new technology{cite('n4-206')}. The price of predictability is a risk premium in the rate and annual escalation
in the high single to low double digits, plus dependence on a single supplier who knows more about the engine than the
airline{cite('n4-216', 'n4-211', 'n4-218')}.</p>
<p>For components — pumps, valves, avionics boxes — the PBH equivalent is total component support: the provider gives
access to its pool, repairs removed units, ships parts and places a kit of critical components right at the customer's
main base, for 5 to 11 years{cite('n4-049', 'n4-050', 'n4-184')}. Everything else is bought case by case — by exchange,
consignment or one-off order:</p>
<div class="tw"><table><tr><th>Contract</th><th>What it covers</th><th>Who carries the risk</th><th>How it is paid</th>
<th>Who it suits</th></tr>{t_con}</table></div>
<p>Small and large airlines benefit from different things, and the reason is scale. Component stock grows more slowly
than the fleet: in a shared pool one spare unit covers many aircraft at once, and the larger the fleet in the pool, the
fewer spares are needed per hundred aircraft{cite('n4-144', 'n4-172')}. A small airline cannot get this effect on its
own, so PBH for engines and total component support pay off for it: it buys someone else's pool scale. Large airlines
build their own, but even Ryanair, with six hundred aircraft, mixes in-house and bought-in maintenance
{cite('n4-269')}.</p>""",
                      f"""<h3>Verträge: wer das Risiko trägt</h3>
<p>Instandhaltung kostet im IATA-Durchschnitt 1.522 Dollar je Flugstunde, etwa 11,5 % der Betriebskosten; die Hälfte davon
entfällt auf Triebwerke, 18 % auf Komponenten{cite('n4-061', 'n4-059', 'n4-058')}. Zwei Drittel der Triebwerkskosten sind
Werkstattbesuche{cite('n4-213')}: seltene, riesige und schwer vorhersehbare Zahlungen. Die Kernfrage jedes
Wartungsvertrags lautet daher: Wer trägt das Ausfallrisiko?</p>
<p>Bei einem Triebwerksvertrag „pro Flugstunde“ (Power by the Hour, PBH) übernimmt der Hersteller das Ausfallrisiko und
die Kosten aller Reparaturen, die Airline zahlt einen Satz je Triebwerksstunde{cite('n4-044', 'n4-065', 'n4-194')}. Solche
Verträge laufen 10–12 Jahre und sind nicht nur etwas für Riesen: Die chinesische Colorful Guizhou mit einer Flotte von
etwa fünfzehn A320neo unterzeichnete mit CFM eine Vereinbarung über einen Zwölfjahresvertrag im Listenwert von rund 500
Millionen Dollar{cite('n4-212', 'n4-066')}. Besonders lohnt sich PBH bei einem neuen Triebwerkstyp — der Hersteller teilt das
Zuverlässigkeitsrisiko der neuen Technik{cite('n4-206')}. Der Preis der Planbarkeit: ein Risikoaufschlag im Satz und eine
jährliche Indexierung im hohen einstelligen bis niedrigen zweistelligen Prozentbereich, dazu die Abhängigkeit von einem
Lieferanten, der mehr über das Triebwerk weiß als die Airline{cite('n4-216', 'n4-211', 'n4-218')}.</p>
<p>Für Komponenten — Pumpen, Ventile, Avionikgeräte — heißt das PBH-Gegenstück Total Component Support: Der Anbieter gibt
Zugang zu seinem Pool, repariert ausgebaute Teile, liefert und legt ein Kit kritischer Komponenten direkt an die
Hauptbasis des Kunden, für 5 bis 11 Jahre{cite('n4-049', 'n4-050', 'n4-184')}. Alles andere wird punktuell gekauft —
als Tausch, Konsignation oder Einzelauftrag:</p>
<div class="tw"><table><tr><th>Vertrag</th><th>Was er abdeckt</th><th>Wer das Risiko trägt</th><th>Wie bezahlt wird</th>
<th>Für wen</th></tr>{t_con}</table></div>
<p>Kleinen und großen Airlines nützt Unterschiedliches, und der Grund ist die Größe. Der Komponentenbestand wächst
langsamer als die Flotte: In einem gemeinsamen Pool sichert ein Ersatzteil viele Flugzeuge zugleich ab, und je größer die
Flotte im Pool, desto weniger Ersatzteile braucht man je hundert Flugzeuge{cite('n4-144', 'n4-172')}. Eine kleine Airline
erreicht diesen Effekt allein nicht, daher lohnen sich für sie PBH für Triebwerke und Total Component Support: Sie kauft
die Poolgröße anderer ein. Große bauen Eigenes auf, doch selbst Ryanair mit sechshundert Flugzeugen kombiniert eigene und
eingekaufte Wartung{cite('n4-269')}.</p>""")

    stations = T(f"""<h3>Линейные станции: где держать своих механиков</h3>
<p>Линейное ТО — проверки перед вылетом, на стоянке и ночью — всегда делают там, где стоит самолёт, а тяжёлое можно
«возить»: сторонние организации обслуживают клиентов в радиусе примерно трёх часов полёта{cite('n4-155', 'n4-157')}.
Поэтому для каждого аэропорта сети решают, держать ли там свою линейную станцию технического обслуживания (ЛСТО) или
покупать услугу у подрядчика. Публичного числового порога мы не нашли; решает объём работы, и прежде всего число
ночующих самолётов. American Airlines в 2019 году открыла свою станцию в Хьюстоне, где у неё было около 38 вылетов в
сутки и до 10 самолётов ночевали, со штатом около 46 человек — чтобы к утренней волне было больше исправных самолётов
{cite('n4-318', 'n4-319', 'n4-320', 'n4-321')}. Там, где рейсов мало, станцию отдают подрядчику{cite('n4-141')}; сторонние
организации держат станции «по вызову» и выездные бригады{cite('n4-159')}. Для ориентира по цене — публичный прайс
S7 Technics на линейное ТО для иностранных перевозчиков на 2025 год: 88 долларов за человеко-час, вызов техника с
устранением дефекта до часа работы — 450 долларов{cite('n4-308', 'n4-309')}.</p>
<p>В России требования к организациям по ТО с 1 марта 2024 года задаёт ФАП-109, заменивший ФАП-285
{cite('n4-134', 'n4-135')}. Линейная станция — подразделение сертифицированной организации по ТО, а не отдельный
сертификат{cite('n4-080')}. Чтобы открыть её, нужны квалифицированный персонал с правом подписывать допуск самолёта к
вылету (привлечённых со стороны — не больше половины), поверенный инструмент и оборудование и склад с раздельным
хранением исправных и неисправных деталей{cite('n4-083', 'n4-136')}. У «Аэрофлот Техникс» в конце 2024 года было 20
линейных станций в России, пять из них — на Дальнем Востоке; они выполняют оперативное ТО A320 и Boeing 737
{cite('n4-121', 'n4-124', 'n4-122')}.</p>""",
                 f"""<h3>Line stations: where to keep your own mechanics</h3>
<p>Line maintenance — checks before departure, during turnarounds and overnight — is always done where the aircraft is,
whereas heavy maintenance can be “flown in”: third-party MROs serve customers within roughly three hours' flying
{cite('n4-155', 'n4-157')}. So for each airport in the network the airline decides whether to keep its own line maintenance
station there or to buy the service from a contractor. We found no public numerical threshold; the deciding factor is
the workload, above all the number of aircraft staying overnight. In 2019 American Airlines opened its own station in
Houston, where it had about 38 departures a day and up to 10 aircraft overnight, with a staff of about 46 — to have more
serviceable aircraft for the morning bank{cite('n4-318', 'n4-319', 'n4-320', 'n4-321')}. Where flights are few, the station
is handed to a contractor{cite('n4-141')}; third-party providers run on-call stations and mobile teams{cite('n4-159')}. As a
price benchmark, S7 Technics' public 2025 price list for line maintenance for foreign carriers: 88 dollars per man-hour, a
technician call-out with defect rectification of up to one hour — 450 dollars{cite('n4-308', 'n4-309')}.</p>
<p>In Russia, requirements for maintenance organisations have been set since 1 March 2024 by FAP-109 (Russian aviation
rules), which replaced FAP-285{cite('n4-134', 'n4-135')}. A line station is a unit of a certified maintenance organisation,
not a separate certificate{cite('n4-080')}. To open one you need qualified staff entitled to sign the aircraft's release to
service (no more than half of them contracted from outside), calibrated tools and equipment, and a store keeping
serviceable and unserviceable parts separately{cite('n4-083', 'n4-136')}. At the end of 2024 Aeroflot Technics had 20 line
maintenance stations in Russia, five of them in the Far East; they carry out line maintenance on the A320 and Boeing 737
{cite('n4-121', 'n4-124', 'n4-122')}.</p>""",
                 f"""<h3>Linienstationen: wo die eigenen Mechaniker sitzen</h3>
<p>Linienwartung — Checks vor dem Abflug, während des Turnarounds und nachts — findet immer dort statt, wo das Flugzeug
steht; schwere Wartung kann man „hinfliegen“: Fremd-MROs bedienen Kunden im Umkreis von etwa drei Flugstunden
{cite('n4-155', 'n4-157')}. Daher wird für jeden Flughafen im Netz entschieden, ob man dort eine eigene
Linienwartungsstation unterhält oder die Leistung bei einem Dienstleister einkauft. Eine öffentliche Zahlenschwelle haben
wir nicht gefunden; entscheidend ist das Arbeitsvolumen, vor allem die Zahl der übernachtenden Flugzeuge. American
Airlines eröffnete 2019 eine eigene Station in Houston, wo sie rund 38 Abflüge am Tag und bis zu 10 übernachtende
Flugzeuge hatte, mit etwa 46 Beschäftigten — damit zur Morgenwelle mehr einsatzbereite Flugzeuge da sind
{cite('n4-318', 'n4-319', 'n4-320', 'n4-321')}. Wo es wenige Flüge gibt, geht die Station an einen Dienstleister
{cite('n4-141')}; Fremdanbieter halten Stationen auf Abruf und mobile Teams vor{cite('n4-159')}. Als Preisorientierung die
öffentliche Preisliste von S7 Technics für Linienwartung ausländischer Airlines 2025: 88 Dollar je Arbeitsstunde, ein
Technikereinsatz mit Mängelbehebung bis zu einer Stunde — 450 Dollar{cite('n4-308', 'n4-309')}.</p>
<p>In Russland legt seit dem 1. März 2024 die FAP-109 (russische Luftfahrtvorschriften) die Anforderungen an
Wartungsbetriebe fest; sie ersetzte die FAP-285{cite('n4-134', 'n4-135')}. Eine Linienstation ist eine Einheit eines
zertifizierten Wartungsbetriebs, kein eigenes Zertifikat{cite('n4-080')}. Für die Eröffnung braucht man qualifiziertes
Personal mit Freigabeberechtigung (höchstens die Hälfte extern), kalibrierte Werkzeuge und Ausrüstung sowie ein Lager mit
getrennter Aufbewahrung funktionsfähiger und defekter Teile{cite('n4-083', 'n4-136')}. Aeroflot Technics hatte Ende 2024
20 Linienwartungsstationen in Russland, fünf davon im Fernen Osten; sie übernehmen die Linienwartung von A320 und Boeing
737{cite('n4-121', 'n4-124', 'n4-122')}.</p>""")

    spares = T(f"""<h3>Где лежат запчасти</h3>
<p>Держать все детали на каждой станции слишком дорого{cite('n4-144')}, поэтому запас раскладывают слоями: чем ближе к
самолёту, тем быстрее, но тем больше денег заморожено на полке.</p>
{layers}
<p class="small">Схема по исследованию склада KLM Component Services и контрактам AFI KLM E&M, IATP, производителей
fly-away kit{cite('n4-169', 'n4-173', 'n4-181', 'n4-296', 'n4-163')}.</p>
<p>Запас считают под заданный уровень сервиса — долю случаев, когда деталь есть в нужный момент: у KLM Component Services
договорной уровень — 95 %, расчёт — под 99 %, а фактически по Boeing 737 получалось 82 %{cite('n4-169', 'n4-170', 'n4-171')}.
Сейчас главный риск — двигатели: сроки их ремонта в цехах выросли на 35 % и больше у старых моделей и более чем на 150 %
у новых{cite('n4-256', 'n4-257')}. В 2025 году это обходится авиакомпаниям в 2,6 миллиарда долларов на аренду
дополнительных двигателей и 1,4 миллиарда на лишние запасы{cite('n4-252', 'n4-251')}: чем дольше ремонт, тем больше
деталей должно быть в обороте.</p>""",
               f"""<h3>Where the spare parts are</h3>
<p>Keeping every part at every station is too expensive{cite('n4-144')}, so stock is laid out in layers: the closer to
the aircraft, the faster, but the more money is tied up on the shelf.</p>
{layers}
<p class="small">Schematic based on the KLM Component Services stock study and the AFI KLM E&M, IATP and fly-away kit
providers' contracts{cite('n4-169', 'n4-173', 'n4-181', 'n4-296', 'n4-163')}.</p>
<p>Stock is sized for a target service level — the share of cases in which the part is there when needed: KLM Component
Services' contractual level is 95 %, its calculation targets 99 %, yet for the Boeing 737 it actually achieved 82 %
{cite('n4-169', 'n4-170', 'n4-171')}. Today the main risk is engines: shop repair times have grown by 35 % or more for older
models and by more than 150 % for new ones{cite('n4-256', 'n4-257')}. In 2025 this costs airlines 2.6 billion dollars in
extra engine leases and 1.4 billion in excess inventory{cite('n4-252', 'n4-251')}: the longer the repair, the more parts
must be in circulation.</p>""",
               f"""<h3>Wo die Ersatzteile liegen</h3>
<p>Alle Teile an jeder Station vorzuhalten ist zu teuer{cite('n4-144')}, daher wird der Bestand in Schichten verteilt: Je
näher am Flugzeug, desto schneller — aber desto mehr Geld liegt im Regal.</p>
{layers}
<p class="small">Schema nach der Lagerstudie von KLM Component Services und den Verträgen von AFI KLM E&M, IATP und
Fly-away-Kit-Anbietern{cite('n4-169', 'n4-173', 'n4-181', 'n4-296', 'n4-163')}.</p>
<p>Der Bestand wird auf einen Ziel-Servicegrad ausgelegt — den Anteil der Fälle, in denen das Teil im richtigen Moment da
ist: Bei KLM Component Services liegt der vertragliche Wert bei 95 %, gerechnet wird auf 99 %, tatsächlich erreicht wurden
bei der Boeing 737 82 %{cite('n4-169', 'n4-170', 'n4-171')}. Das Hauptrisiko sind heute die Triebwerke: Ihre
Werkstattdurchlaufzeiten sind bei älteren Modellen um 35 % und mehr, bei neuen um über 150 % gestiegen
{cite('n4-256', 'n4-257')}. 2025 kostet das die Airlines 2,6 Milliarden Dollar für zusätzliche Leasingtriebwerke und 1,4
Milliarden für überschüssige Lagerbestände{cite('n4-252', 'n4-251')}: Je länger die Reparatur, desto mehr Teile müssen im
Umlauf sein.</p>""")

    russia = T(f"""<h3>Россия после 2022 года</h3>
<p>Российские авиакомпании потеряли доступ к зарубежным цехам и запчастям двигателей CFM и Pratt & Whitney
{cite('n4-131')}. «Аэрофлот Техникс» обслуживает больше 300 самолётов группы и с 2023 года выполняет больше тысячи форм
A и C в год{cite('n4-126', 'n4-127')}; выполнен первый собственный ремонт трёх двигателей CFM56-5B, а завод по ремонту
двигателей планируется к концу 2027 года{cite('n4-130', 'n4-132')}. Расходы группы на ТО по МСФО выросли с 23,4
миллиарда рублей в 2023 году до 57,1 миллиарда в 2024-м — в 2,4 раза, тогда как ёмкость выросла на 18 %
{cite('n4-345', 'n4-346')}; рост операционных расходов в целом компания объясняет расширением программы, отдельно
рост ТО в открытых источниках не разобран. По данным СМИ, в конце 2022 года правительство
разрешило снимать компоненты с одних самолётов для ремонта других, но текст решения не опубликован{cite('n4-246')}.</p>""",
               f"""<h3>Russia after 2022</h3>
<p>Russian airlines lost access to foreign shops and to CFM and Pratt & Whitney engine parts{cite('n4-131')}. Aeroflot
Technics maintains more than 300 group aircraft and since 2023 has performed more than a thousand A- and C-checks a year
{cite('n4-126', 'n4-127')}; the first in-house repair of three CFM56-5B engines has been completed, and an engine repair
plant is planned for the end of 2027{cite('n4-130', 'n4-132')}. The group's maintenance costs under IFRS rose from 23.4
billion roubles in 2023 to 57.1 billion in 2024 — 2.4 times — while capacity grew by 18 %{cite('n4-345', 'n4-346')}; the
company explains the growth of operating costs as a whole by the expanded programme, and public sources do not break down
the maintenance increase separately. According to media reports, at the end of 2022 the government allowed components to
be taken from some aircraft to repair others, but the text of the decision has not been published{cite('n4-246')}.</p>""",
               f"""<h3>Russland nach 2022</h3>
<p>Russische Airlines haben den Zugang zu ausländischen Werkstätten und zu Triebwerksteilen von CFM und Pratt & Whitney
verloren{cite('n4-131')}. Aeroflot Technics betreut mehr als 300 Flugzeuge der Gruppe und führt seit 2023 mehr als tausend
A- und C-Checks im Jahr durch{cite('n4-126', 'n4-127')}; die erste eigene Reparatur von drei CFM56-5B-Triebwerken ist
abgeschlossen, ein Triebwerksreparaturwerk ist für Ende 2027 geplant{cite('n4-130', 'n4-132')}. Die Wartungskosten der
Gruppe nach IFRS stiegen von 23,4 Milliarden Rubel 2023 auf 57,1 Milliarden 2024 — das 2,4-Fache —, während die Kapazität
um 18 % wuchs{cite('n4-345', 'n4-346')}; den Anstieg der Betriebskosten insgesamt erklärt das Unternehmen mit dem
ausgeweiteten Programm, den Wartungsanstieg schlüsseln öffentliche Quellen nicht gesondert auf. Medienberichten zufolge
erlaubte die Regierung Ende 2022, Komponenten aus einigen Flugzeugen zur Reparatur anderer auszubauen; der Text der
Entscheidung ist nicht veröffentlicht{cite('n4-246')}.</p>""")

    concl = T("""<h3>Что это значит для сети</h3>
<p>Высокий налёт держится на четырёх опорах. Каждый самолёт регулярно ночует на базе со своей станцией, ангаром и
запасом — там делают ежедневные, еженедельные проверки, форму A и устраняют отложенные дефекты. Тяжёлые формы стоят на
зиму или разложены по ночам. Резерв в 2–4 % парка или договорённость об ACMI закрывает поломки. Контракты «за час» и
пулы превращают редкие дорогие отказы в ставку за лётный час — и именно в такой форме ТОиР и считает калькулятор.</p>""",
              """<h3>What this means for the network</h3>
<p>High utilisation rests on four pillars. Every aircraft regularly spends the night at a base with its own station,
hangar and stock — that is where daily and weekly checks and the A-check are done and deferred defects are fixed. Heavy
checks are scheduled for winter or spread across nights. A reserve of 2–4 % of the fleet or an ACMI arrangement covers
breakdowns. “By the hour” contracts and pools turn rare, expensive failures into a rate per flight hour — which is
exactly how the calculator counts maintenance.</p>""",
              """<h3>Was das für das Netz bedeutet</h3>
<p>Hohe Auslastung ruht auf vier Säulen. Jedes Flugzeug übernachtet regelmäßig an einer Basis mit eigener Station, Hangar
und Bestand — dort werden Daily und Weekly Checks und der A-Check gemacht und zurückgestellte Mängel behoben. Schwere Checks
liegen im Winter oder sind auf Nächte verteilt. Eine Reserve von 2–4 % der Flotte oder eine ACMI-Vereinbarung deckt
Ausfälle ab. Verträge „pro Stunde“ und Pools machen seltene, teure Ausfälle zu einem Satz je Flugstunde — und genau so
rechnet der Rechner die Instandhaltung.</p>""")

    h2 = T("Как не стоять на земле: ТО, контракты, станции и запчасти",
           "How not to sit on the ground: maintenance, contracts, stations and spare parts",
           "Wie man nicht am Boden steht: Wartung, Verträge, Stationen und Ersatzteile")
    return (f"<section><h2>{h2}</h2>\n{intro}\n{program}\n{year}\n{after_year}\n{downtime}\n{contracts_txt}\n"
            f"{stations}\n{spares}\n{russia}\n{concl}\n</section>")
