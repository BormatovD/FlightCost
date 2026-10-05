# Обзор режимов вне Европы и России: где лежат первоисточники

Составлен 2026-09-18 по 148 аэропортам перечня владельца. Цель — чтобы
поиск не давал «лабуду»: у каждого режима свой издатель, свой тип
документа и свои слова, по которым он ищется. Правило то же, что везде
(решение 108): заводится число с издателем и редакцией; сводки IATA,
ACIC, портала airportal.go.kr и т. п. — вторичные, ими проверяют, не
заводят.

Заведён пилот региона **Япония — Нарита (RJAA)** с первоисточника NAA,
сходится с собственным примером NAA до иены.

## Япония (10 аэропортов: NRT, HND, KIX, NGO, FUK, CTS, OKA, HIJ, KMJ, TAK)

| | издатель | документ | искать по |
|---|---|---|---|
| NRT | NAA (частный оператор) | «Charges for Airport Facilities», страница + PDF | `narita-airport.jp company business flights-charge` |
| HND | MLIT (государственный) + Tokyo International Air Terminal (T3 частный) | посадочные — постановление MLIT о сборах за использование аэропортов (空港使用料); PSFC — TIAT | `羽田 着陸料 国土交通省`, `Tokyo International Air Terminal PSFC` |
| KIX, ITM | Kansai Airports (концессия Vinci/Orix) | «Airport Charges» PDF | `Kansai Airports landing charge international` |
| NGO | Central Japan International Airport Co. | «Airport Charges» | `Chubu Centrair airport charges landing` |
| FUK, CTS, HIJ, KMJ, TAK, OKA | концессионеры (Fukuoka International Airport Co., Hokkaido Airports, Hiroshima, Kumamoto, Takamatsu) либо MLIT для государственных | у концессий свои PDF; у государственных — единый тариф MLIT | `<airport> airport charges landing PSFC` |

**Схема.** Посадочный по индексу шума A–F × MTOW с округлением тонн
вверх и минимумом — уже поддержано (`noise_cat` теперь принимает буквы).
Стоянка «за 24 часа сверх первых шести» — база `per_day_above`. Багажная
система по полосам кресел — условие `seats`. Что нужно из данных:
**категория шума по типу** — домен `airport_ac_category` (решение 68);
пока его нет, `noise_cat` задаётся в условиях начисления, и без него
посадочный не начисляется (пропуск виден в отчёте).

## Китай (11: PEK, PKX, PVG, SHA, CAN, SZX, TFU, XMN, WUH, CGO + HKG)

| | издатель | документ |
|---|---|---|
| материк | CAAC + NDRC: «民用机场收费标准» — единый государственный тариф по классам аэропортов (一类1级/2级, 二类…) и по ВС (внутренние/иностранные перевозчики) | приказ 民航发〔2017〕18号 с последующими корректировками; ставки за взлёт-посадку по полосам MTOW, стоянка, пассажирский сбор (旅客服务费), безопасность (安检费) |
| HKG | Airport Authority Hong Kong, ставки гласят в Gazette (G.N. 3341 от 17.06.2016, с тех пор не менялись) | посадка HKD 3 150 до 20 т + 74/т сверх; стоянка за 15 мин; TBC 23 HKD и security 50 HKD с вылетающего; Airport Construction Fee — сбор с пассажира по перечню направлений |

**Схема.** Материк: один документ на 10 аэропортов, ставки по классу
аэропорта и по эксплуатанту (китайский / иностранный) — ложится на
`operator` и `mtow_t`-полосы. HKG: посадочный «фикс + за тонну сверх 20»
— `per_movement` + `per_tonne_above` (есть). ACF по перечню государств
назначения — в модели нет такого деления; либо условие по стране
другого конца (`other`), либо не заводить.

## Юго-Восточная и Южная Азия

| страна | аэропорты | издатель | документ |
|---|---|---|---|
| Таиланд | BKK, HKT, CNX, UTP | AOT (гос. компания, 6 аэропортов) | «Airport Charges» на aot-th, единый тариф; стоянка и посадка по MTOW |
| Тайвань | TPE, TSA, KHH, RMQ | CAA Taiwan / Taoyuan International Airport Corp. | «民用航空局 場站降落費», TIAC «Airport charges» PDF |
| Корея | ICN, GMP, PUS | IIAC (Incheon) и KAC (остальные) | «Airport charges» на airport.kr / airport.co.kr; посадка по MTOW с ночными скидками |
| Сингапур | SIN | CAAS + Changi Airport Group | «Aeronautical charges» PDF на changiairport.com/corporate |
| Малайзия | KUL, PEN | Malaysia Airports + MAVCOM (регулятор) | Aeronautical Charges Framework MAVCOM |
| Индонезия | CGK, DPS, SUB | AP II / AP I (InJourney) | «Tarif PJP2U / PJP4U» — отдельно пассажирский (PJP2U) и посадка (PJP4U) |
| Вьетнам | HAN, SGN, DAD | ACV + Минтранс (регулируемые) | «Thông tư» Минтранса о ценах аэропортовых услуг |
| Филиппины | MNL, CEB | MIAA / GMR-Megawide | «Schedule of Fees» |
| Индия | DEL, BOM, BLR | AERA (регулятор) | «Tariff Order» на aera.gov.in по каждому аэропорту, на контрольный период; UDF с пассажира |
| Камбоджа | PNH | Cambodia Airports (Vinci) | «Airport charges» |
| ОАЭ, Саудовская Аравия | DXB, JED, RUH | Dubai Airports / GACA | DXB — «Airport charges» на dubaiairports.ae; GACA — «Economic regulations, airport charges» |
| Израиль, Турция, Египет | TLV, IST, AYT, CAI | IAA / DHMİ / ECAA | TLV — тариф IAA; IST — тариф İGA + DHMİ; CAI — ECAA |

**Схема.** Индия: UDF (User Development Fee) с пассажира по направлению —
`per_departing_pax` с `flight`. Индонезия: PJP2U отдельно на внутренние
и международные — то же. Корея: ночные скидки к посадочному — `night`.
Новых баз не видно; проверять на первом аэропорте каждой страны.

## США (14: ATL, BOS, DEN, EWR, HNL, IAD, IAH, JFK, LAX, MIA, ONT, ORD, SEA, SFO)

| | издатель | документ | искать по |
|---|---|---|---|
| все | оператор аэропорта (city/authority) | «Schedule of Rates and Charges» / «Rates and Charges» на финансовый год | `<airport> rates and charges FY2026 landing fee signatory` |
| JFK, EWR | Port Authority NY&NJ | «Schedule of Charges for Air Terminals» | `panynj schedule of charges air terminals` |
| LAX, ONT | LAWA | «Rates and Charges» | `LAWA rates and charges landing fee` |
| SFO, SEA, DEN, MIA, IAH, IAD, BOS, ATL, ORD, HNL | городские/портовые власти | то же; у ORD — City of Chicago, у ATL — City of Atlanta, у IAD — MWAA, у HNL — HDOT | |

**Схема — здесь новые сущности, и это единственный регион, где они
нужны:**
- посадочный **по MLW за 1 000 фунтов**, не по MTOW — нужны `mlw_t` в
  контексте (данные типа) и база `per_1000lb_mlw` (или `per_tonne_mlw` с
  переводом единицы фактом);
- **signatory / non-signatory** — ставка зависит от договора с аэропортом
  (подписанты платят ниже); новое условие, вход пользователя;
- пассажирского сбора у аэропорта нет: PFC до 4,50 USD с пассажира —
  федеральный сбор с билета, не сбор аэропорта; терминал платится
  арендой площадей (не на рейс);
- терминальная аэронавигация не взимается; маршрутная — FAA overflight
  fee только с пролётных.

## Африка (JNB, CPT, CAI, LOS)

| | издатель | документ |
|---|---|---|
| JNB, CPT | ACSA, ставки утверждаются Regulating Committee и публикуются в Government Gazette | уведомление в Gazette «Airport charges … effective 1 April 2026»: посадка по MTOW с делением по происхождению рейса (внутренний / из Ботсваны, Лесото, Намибии, Эсватини / международный), стоянка сверх 4 часов, PSC с вылетающего по трём категориям |
| CAI | Egyptian Airports Company / ECAA | тариф ECAA; ставки в USD |
| LOS | FAAN (Federal Airports Authority of Nigeria) | «Aeronautical charges»; в USD для международных |

**Схема.** ЮАР: «региональный» — третье значение между внутренним и
международным по перечню государств — снова условие по другому концу
(`other`) или по стране; стоянка сверх 4 часов — `per_hour_above` с
порогом 4.

## Порядок, если делать по методу «один — пять — все»

1. Япония — NRT заведён; следующие: KIX, HND (два издателя в одном
   аэропорту), NGO.
2. Китай — один документ на десять; начать с PEK и проверить на PVG.
3. ЮАР — Gazette 2026, два аэропорта из одного документа.
4. США — только после схемы (MLW, signatory); LAX первым: у LAWA
   документ самый чистый.
