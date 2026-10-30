# Bottom-up ТОиР: открытые источники (разведка r1, 2026-10-20)

Журнал: `trace/r1.jsonl` (r1-001…r1-143). Машиночитаемо: `sources.json`.

## Покрытие по блокам

| Блок | Покрытие открытыми данными | Лучшие источники | Главная оговорка |
|---|---|---|---|
| Таксономия ATA/JASC | **полное** | FAA JASC Code Table (2008, ~488 кодов) | iSpec 2200 платный; JASC хватает |
| Надёжность по главам ATA | **только относительная** | FAA SDR CSV 1995–2026 + BTS T-2 AirHours | SDR = только safety-relevant отказы (14 CFR 121.703), не все съёмы → занижение абсолютной интенсивности |
| MTBUR конкретных компонентов | **точечно** | вузовские статьи (Индонезия: Batik Air A320 pitot), исторические PR (APS3200 MTBUR >7700 ч, 1999) | нет каталога; в статьях бывают арифметические ошибки |
| Двигатель: shop visit, LLP | **частично** | открытые PDF Aircraft Commerce (LLP list prices, SV budget), SR Technics fixed-price catalogue CFM56-5B 2026, LARA 2025 (интервалы) | цены AC с лагом 5–15 лет; SRT — только труд, без частоты |
| Шасси | **порядок величины** | AC No.79 (2011): ~10 лет + FC-лимит; 737NG $0.50–0.525 млн/комплект | цены 2011 |
| ВСУ | **порядок величины** | тендер Uzbekistan Airways 131-9A (~$10 млн/5 лет), FlightGlobal 1999 | нет числа SV |
| Формы планера | **слабо** | MRBR A320 Rev 25 (копия) — интервалы задач; AC — MH форм | MPD с трудоёмкостью закрыт |
| Ротируемые/PBH | **нет ставок** | суммы контрактов: Аэрофлот SSJ100 PBH (НМЦ $136,2 млн, 49 ВС, до 2030), AAR C-40 CLS $148 млн | $/FH только с допущениями |
| Цены деталей / MH | **частично** | FAA AD «Costs of Compliance» (Federal Register, work-hours × $85 + parts) | это AD-работы, не ротация |
| Калибровка сверху | **да** | IATA MCX public FY2024; Oliver Wyman/ARSA ExecSum 2026 (двигатели ~50%, планер ~20%, компоненты ~17%, линейное ~13%) | не по типам ВС |
| Военные аналоги | **нет** | VAMOSC — только DoD | — |

## Примеры записей (дословно)

- SDR 2024: `AALA202401026428,01/01/2024,"2024-01-02T14:33:12.733-05:00",AALA,AALA,A,SW,23,A,3260,J,,,O,,,,CL,V,184US,AIRBUS,"A320*",`
- JASC: `4920 APU CORE ENGINE`
- AC No.128: «There are now three LLPs in the fan and LPC with certified life limits of 30,000EFC, and a list price of $543,200.»
- FAA AD 2025-18-03: «2 work-hours x $85 per hour = $170»
- Batik Air: «P/N 0851MC has an MTBUR of 12,132.71 FH, nearly twice as high as P/N 0851HL, which stands at 5,661.93 FH.»

## Технические ограничения разведки

- Прокси сессии блокирует `sdrs.faa.gov` и `external.apic4e.faa.gov` для curl; WebFetch отдаёт только начало CSV. Для полной выгрузки SDR нужно разрешить домен.
- zakupki.gov.ru и USASpending по конкретным лотам ремонта агрегатов не подняты.

## Пробелы

Абсолютные MTBUR по P/N; MPD; ставки PBH; статистика надёжности Росавиации/EASA/TC; актуальные LLP-каталоги (только платно); VAMOSC.
