# `fca` — шпаргалка

Составлено по `cli.py` от 2026-09-28 и по скриптам в `tools/`. Заменяет
`fca-шпаргалка-2.md`. Всё запускается из корня проекта.

---

## Ритуал возвращения

```bash
source .venv/bin/activate                # без этого «command not found: fca»
fca status                               # протухшее, очередь приёмки, сверка карты
python3 tests/test_pipeline.py
python3 tests/test_charge_reference.py   # Франкфурт до цента (нужна база)
python3 tests/test_ru_reference.py       # 28 счетов по России
python3 tests/test_cn_reference.py       # Пекин, Сямынь
python3 tests/test_jp_reference.py       # Нарита
python3 tests/test_ui.py                 # цвет только из ui.css
python3 tests/test_deps.py               # объявленное = импортируемое
python3 tests/test_tkp_parser.py
fca serve                                # http://127.0.0.1:8000
```

Активация живёт в пределах вкладки терминала. В crontab — полный путь
`.venv/bin/fca` и обязательный `cd` в каталог проекта.

---

## Частые ловушки

| что | почему | как |
|---|---|---|
| `zsh: bad pattern` | zsh раскрывает скобки и `*` | весь SQL — в двойных кавычках, строки внутри — в одинарных |
| `--set …*…` | оболочка раскроет звёздочку | не ставить; `fleet_economics.A320.…` без `*` |
| другая, пустая база | путь `data/flightcost.db` относительный | запускать из корня проекта |
| `refresh` висит | `serve` держит базу открытой | остановить сервер на время обновления |
| правка `.py` не видна в витрине | сервер читает Python только при старте | перезапустить `fca serve`; HTML/CSS/JS читаются на каждый запрос |
| правка парсера не доехала | тот же sha — разбор пропускается | `fca refresh --reparse --only <источник>` |

---

## Глобальные ключи

Ставятся **до** имени команды.

| ключ | умолчание | что делает |
|---|---|---|
| `--db PATH` | `data/flightcost.db` | другое хранилище |
| `--registry PATH` | из пакета | другой реестр источников |

---

## Данные

### `fca status`

```bash
fca status
fca status --json
```

Колонка «последнее» — последнее **событие**, не состояние. Источник с
непринятым предложением стареет: `last_ok` не двигается до приёмки.

### `fca refresh`

```bash
fca refresh                               # у кого подошёл срок
fca refresh --all                         # сдвинуть РАСПИСАНИЕ всем
fca refresh --reparse --only airport_charges_tier1   # разобрать заново
fca refresh --only jet_fuel_price fx_rates
fca refresh --due / --dry-run / --json
```

`--all` двигает расписание, `--reparse` заставляет разобрать тот же файл
заново. Исходы: `committed`, `committed:partial`, `unchanged`,
`proposal` (ждёт `fca review`), `rejected`, `external`, `skipped:*`,
`error:fetch`, `error:parse`.

Источники, которые чаще всего трогаются руками:

| источник | что | когда запускать |
|---|---|---|
| `airport_charges_tier1` | `data/charges/*.json` — тарифы аэропортов | после нового или правленого файла, с `--reparse` |
| `aircraft_user` | `data/aircraft/user/*.json` — свои типы | чтобы восстановить базу из каталога |
| `easa_noise` | сертифицированный шум типов, EASA | раз в полгода, новый выпуск |
| `aircraft_openap` | физика 37 типов | после обновления openap |
| `market_fare` | не через refresh — см. «Цены» | — |

### `fca review`

```bash
fca review                 # список: что изменится
fca review 27              # подробно одно предложение
fca review 27 --all        # все строки, без выборки
fca review --accept 27
fca review --reject 27
```

Приёмка по исключениям: смотреть выделенные строки и поводы, а не число
фактов. «Все совпадают с хранилищем — принимать нечего» — нормальный исход.

### `fca data`, `fca sources`, `fca map`

```bash
fca data                                  # витрина хранилища
fca data --as-of 2026-08-01 --out docs/данные-август.html --no-open
fca sources                               # где опубликован каждый тариф
fca map                                   # карта: что откуда, поля, единицы
```

Домен без фактов по замыслу (`airspace`, `observed`) показывается
состоянием своего файла или таблицы: не считалось / пусто / истекло /
свежо.

---

## Цены билетов — цепочка целиком

```bash
# 0. ключ агрегатора — в окружении, в репозиторий не попадает
export TP_TOKEN=$(grep TP_TOKEN ~/.config/travelpayouts/env | cut -d= -f2)

# 1. файл маршрутов: наблюдённые линии + перебор по перечню и хабам
python3 tools/make_routes.py --blind-from watch \
  --hubs EDDF,EHAM,LFPG,EGLL,LEMD,LTFM,UUEE,ULLI,UNNT,ZBAA,ZSPD,ZGGG,ZUUU,RJAA,VIDP,VABB,WIII \
  --blind-top 60

# 2. сбор с агрегатора → flight_data/raw_<дата>T<время>_NNN.csv
python3 tools/collect_prices.py collect --routes routes.xlsx --months 6

# 3. выгрузки — в каталог контура
mkdir -p data/raw/market_fare
cp flight_data/raw_*.csv data/raw/market_fare/

# 4. дневные минимумы в хранилище (повторная загрузка = дубли, не двойной счёт)
fca fare
fca fare --list                           # что накоплено: пары, полосы, даты

# 5. свёртка в полосы глубины (медиана дневных минимумов)
fca fare --aggregate                      # --min-obs 5 по умолчанию

# 6. почему по паре есть или нет полосы — вместо «…и ещё 2066»
fca fare --why DME-OVB                    # ИАТА или ИКАО, направление как собирали

# 7. витрина читает полосы при старте
fca serve
```

Про сбор:

- Файл выгрузки с меткой времени — не затирается. Повторный запуск в тот же
  день дособирает прерванное, на другой день собирает заново: это и есть
  накопление.
- Число запросов = линии × месяцы; `make_routes` печатает его заранее.
  Начинать с `--months 6`.
- Валюта берётся из колонки `currency`, а без неё — из ссылки агрегатора
  (`expected_price_currency=eur`). `fca fare` печатает, откуда взята;
  строка вовсе без валюты пропускается.
- `collect_prices.py aggregate` — старая сводка CSV для глаз, к хранилищу
  отношения не имеет.

### `tools/make_routes.py` — ключи

| ключ | умолчание | что делает |
|---|---|---|
| `--out` | `routes.xlsx` | файл для сборщика; перезаписывается целиком |
| `--min-days N` | 3 | сколько суток линия должна наблюдаться |
| `--top N` | 40 | сколько наблюдённых линий |
| `--both-directions` | выкл | брать и обратное направление |
| `--airports ФАЙЛ\|КОДЫ` | перечень из хранилища | ограничить отбор списком |
| `--any-airport` | выкл | снять отбор совсем |
| `--blind-from` | `watch` | узлы перебора: `watch` / `tariffed` / `both` |
| `--hubs ИКАО,…` | нет | внутри страны — пары с хабом; между странами — хаб с хабом |
| `--blind-top N` | 40 | сколько строк перебора; `0` выключает |
| `--nm МИН,МАКС` | `150,4000` | полоса плеча перебора, мили (Франкфурт–Пекин ~4 200) |

В файле колонка «Откуда строка»: `наблюдения` или `перебор RU`, `перебор
RU-CN`. У строки перебора число рейсов пусто — «не наблюдалось», не ноль.

---

## Наблюдения эксплуатации (ADS-B)

Единственный источник, где пропущенные сутки не восстанавливаются.

```bash
fca observe --check                       # один запрос, ничего не пишет
fca observe                               # вчерашние сутки
fca observe --day 2026-09-09 --airports EDDF,LEBL,EGKK --pause 2.0
fca observe --aggregate                   # свернуть в факты домена observed
fca observe --gaps --since 2026-09-09     # борта без типа
```

Ключи OpenSky: `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` или
`OPENSKY_CREDENTIALS=<путь к json>`.

---

## Расчёт

### Общие ключи маршрута (`econ`, `explain`, `solve`)

| ключ | умолчание | что задаёт |
|---|---|---|
| `origin` `destination` | обязательны | ИАТА или ИКАО |
| `--ac ТИП` | `A320` | тип ВС, включая свои: `T214`, `USER:A320-MY` |
| `--lf ДОЛЯ` | `0.80` | загрузка |
| `--fare EUR` | нет | средний чек |
| `--as-of ГГГГ-ММ-ДД` | сегодня | **по каким данным** считаем |
| `--month 1-12` | нет | **когда летим**; без него сезонные ставки не срабатывают |
| `--alternate-nm NM` | нет | до запасного; без него запас неполон |
| `--freq N` | нет | рейсов в неделю |
| `--util РЕЖИМ` | `fleet_average` | `dedicated`, `marginal` |
| `--operator КОД` | `*` | компоновка и ставки перевозчика |
| `--set КЛЮЧ=ЗНАЧ` | — | слой сценария, можно повторять |

### Команды

```bash
fca econ FRA BCN --lf 0.82 --fare 95 --month 7 --alternate-nm 150
fca econ DME OVB --ac T214 --lf 0.82          # свой тип: «нельзя», пока нет якоря
fca explain FRA BCN --lf 0.82 --fare 95       # HTML в docs/<марш>-<дата>.html
fca explain FRA BCN --lf 0.82 --fare 95 --out docs/сегодня.html --no-margins
fca solve FRA BCN --lf 0.82 --fare 95 --for fare
fca solve FRA BCN --lf 0.92 --fare 200 --for lf
fca solve FRA BCN --lf 0.82 --fare 95 --for fuel          # цена топлива, EUR/кг
fca solve FRA BCN --lf 0.82 --fare 95 --for fleet_economics.A320.lease_eur_month
fca range A320 --operator FR --points 15                   # нагрузка — дальность
fca heatmap                                                # сборы аэронавигации
fca heatmap --world
```

`econ` возвращает код `2`, если есть протухшие источники. «Не решается» у
`solve` — законный ответ о маршруте.

---

## Слой сценария: `--set`

**Факт хранилища — число:**

```bash
--set fleet_economics.A320.lease_eur_month=280000
--set fleet_economics.LH.A320.maint_eur_per_fh=1100
--set enroute_rate.ED=95
```

Поля ставок: `lease_eur_month`, `monthly_hours`, `maint_eur_per_fh`,
`maint_eur_per_fc`, `crew_eur_per_fh`, `crew_eur_per_fc`.

**Условие начисления — `charge_context.<ИКАО>.<условие>`:**

```bash
--set charge_context.EDDF.noise_cat=3
--set charge_context.EDDF.stand=pier
--set charge_context.UUEE.operator=national
--set charge_context.UUEE.terminal=B
```

| условие | значения | откуда по умолчанию |
|---|---|---|
| `noise_cat` | 1–16, A–H | правила категорий в тарифе аэропорта; у Франкфурта — при посадке |
| `noise_cat_dep` | 1–16, A–H | категория шума при взлёте (Франкфурт §1.2.7) |
| `ac_class` | 0–6 | то же |
| `ac_group` | 1–6 | то же |
| `stand_group` | 1–9 | то же (Франкфурт — Anhang 3; группа 1 = зона АОН, только вручную) |
| `stand` | `apron`, `pier` | вход |
| `park_h` | 0–240 | вход |
| `pax_type` | `local`, `transfer`, `transit` | `local` |
| `dest` | `schengen`, `eu_non_schengen`, `europe_non_eu`, `intercontinental` | выводится |
| `operator` | `national`, `foreign` | по стране аэропорта вылета |
| `terminal` | буква | самый дорогой из тарифа |

Категории теперь выводятся из раздела `categories` файла тарифа; `--set`
их перебивает, и разбор показывает исходное рядом с заданным.

**Допущения пересчёта лизинга:** `--set lease_terms.months=120`,
`annual_rate=0.09`, `balloon_share=0.25`, `in_advance=0`.

**Эталон Франкфурта:**

```bash
fca explain FRA BCN --as-of 2026-09-07 --month 7 --lf 0.87 \
  --set charge_context.EDDF.noise_cat=3 \
  --set charge_context.EDDF.noise_cat_dep=3 \
  --set charge_context.EDDF.ac_class=1 \
  --set charge_context.EDDF.stand_group=1 \
  --set charge_context.EDDF.stand=pier \
  --set charge_context.EDDF.park_h=1.5
# сборы EDDF при 148 пассажирах: 5 971,40 EUR
```

---

## Витрина

```bash
fca serve                                 # http://127.0.0.1:8000, только петля
fca serve --port 8010 --no-warm
fca serve --public                        # запись закрыта: свои типы гостей не сохраняются
```

Вкладки: Маршрут · Разбор · Порог · Типы · Характеристики · Данные.

**Свои типы** — вкладка «Характеристики»: библиотечный тип только
читается, кнопка «Создать свой тип» копирует его; свой тип правится и
сохраняется на месте. Сервер пишет файл в `data/aircraft/user/` и факты в
базу; база восстанавливается из каталога командой
`fca refresh --only aircraft_user`. Ключ своего типа — `USER:…`.

---

## Добавить аэропорт

```bash
# 1. файл тарифа
cp шаблон data/charges/<ИКАО>-<год>.json   # source, source_url, publisher, valid_from — обязательны
# 2. разбор и приёмка
fca refresh --reparse --only airport_charges_tier1
fca review
fca review --accept <N>
# 3. проверка
fca econ <ОТКУДА> <КУДА> --month 7
```

Неточность прочтения (`certainty` ≠ `exact`) требует `error_cost` числом и
`confirm_by`. Отказ разбора — словами в `fca refresh`: неизвестная база
начисления, условие вне словаря, недостижимое правило.

---

## Диагностика SQL (zsh-безопасно)

```bash
# поля домена aircraft
sqlite3 data/flightcost.db "SELECT DISTINCT substr(key, instr(key,'/')+1) FROM facts WHERE domain='aircraft'"

# свои типы в хранилище
sqlite3 data/flightcost.db "SELECT DISTINCT substr(key,1,instr(key,'/')-1) FROM facts WHERE domain='aircraft' AND source_id='aircraft_user' AND valid_to IS NULL"

# валюта наблюдений цен
sqlite3 data/flightcost.db "SELECT unit, COUNT(*) FROM observations WHERE kind='fare_min_daily' GROUP BY unit"

# наблюдения цен по паре
sqlite3 data/flightcost.db "SELECT key, COUNT(*), MIN(observed_at), MAX(observed_at) FROM observations WHERE key LIKE 'UUDD-UNNT/%' GROUP BY key"

# какие таблицы есть
sqlite3 data/flightcost.db ".tables"
```
