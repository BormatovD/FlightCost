# Ряды по годам из XBRL-отчётности SEC — задание исследователю

Формат журнала — как в SPEC.md (раздел «Журнал источников»): `trace/<id>.jsonl`, шаги search/open/extract/reject/infer/conclude/gap,
в extract — дословная цитата или, для таблицы, строка таблицы как есть (заголовок строки и числа) и подписи столбцов.

## Что нужно

Для каждой компании из твоего списка — годовые значения за все доступные годы 2006–2025 (в млн USD, как в отчёте; если отчёт в тысячах — так и пиши, с единицей):

1. **MMR** — строка отчёта о прибылях «Maintenance, materials and repairs» (или «Maintenance materials and repairs», «Aircraft maintenance, materials and repairs»).
2. **Амортизация отложенного ТО** — только у компаний на методе отсрочки (deferral / built-in overhaul): строка отчёта о движении денег или примечания «Amortization of heavy maintenance», «Amortization of deferred heavy maintenance», «Depreciation and amortization — maintenance» и т. п. Отдельно: сумма капитализированного за год ТО («Capitalized heavy maintenance», «Deferred heavy maintenance» в инвестиционной части), если есть.
3. **Оплата по договорам за налёт** — если компания раскрывает («flight hour-based maintenance expense», «power-by-the-hour»).
4. **Компенсации от производителя двигателей**, уменьшившие ТОиР (Pratt & Whitney GTF и т. п.) — сумма и год, если раскрыто.

## Где брать (по порядку)

- **API XBRL SEC**: `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/AircraftMaintenanceMaterialsAndRepairs.json`
  (CIK — 10 цифр с ведущими нулями). Там все годы сразу; бери записи `form: 10-K`, `fp: FY`, период 12 месяцев. Для других показателей
  имя тега ищи в отчёте компании (страницы R*.htm) или в `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (он большой —
  читай кусками через offset). Если адрес не открывается напрямую, сначала найди его через WebSearch.
- **Страницы R*.htm отчёта** (по одной таблице на страницу): `https://www.sec.gov/Archives/edgar/data/<CIK>/<номер подачи без дефисов>/R4.htm` и т. п.;
  индекс подачи — `.../<номер>/` (FilingSummary.xml перечисляет все R-страницы с названиями).
- Годы до XBRL (до ~2009): 10-K целиком читается плохо; если нужного нет — `gap`, не выдумывай.

В одном 10-K три года — используй это: достаточно отчётов за каждый третий год, а перекрытия сверяй (одно и то же значение в двух
отчётах — хорошая проверка; расхождение — пересчёт, запиши оба и `doubts`).

## Итог

`xbrl/<КОД>.json`:
```json
{"carrier": "G4", "cik": "1362468", "unit": "млн USD",
 "mmr": {"2019": {"v": 177.0, "evidence": ["x1-012"]}},
 "deferred_amort": {"2019": {"v": 0.0, "evidence": []}},
 "capitalized": {}, "pbh": {}, "oem_credits": {},
 "tags": {"mmr": "us-gaap:AircraftMaintenanceMaterialsAndRepairs"},
 "gaps": [], "doubts": []}
```
Проверь JSON. В ответе — сводка до 200 слов.
