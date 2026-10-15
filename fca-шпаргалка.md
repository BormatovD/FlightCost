# `fca` — шпаргалка

Составлено по `cli.py` от 2026-09-28 (выкладка — 2026-10-13) и по скриптам в `tools/`. Заменяет
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

Единственный источник, где пропущенные сутки не восстанавливаются
(догоняется неделя назад, не больше). Забор подготовлен **на сервере** — своя
база `/srv/fca/observe/flightcost.db`, таймер в 05:20 UTC, — и включается после
переезда на сервер в Германии; до тех пор `fca observe` дома раз в несколько дней.
Настройка один раз — `deploy/README.md`, «Наблюдения ADS-B на сервере».

```bash
# дома: забрать накопленное с сервера и свернуть
bash deploy/pull-observations.sh          # слияние без дублей, повтор безопасен
fca observe --aggregate                   # свернуть в факты домена observed
fca observe --gaps --since 2026-09-09     # борта без типа

# как прошли заборы на сервере
ssh deploy@flightcost.app sudo journalctl -u fca-observe -n 20
ssh root@flightcost.app systemctl list-timers fca-observe.timer

# руками, локально (только если сервер не пускают к OpenSky)
fca observe --check                       # один запрос, ничего не пишет
fca observe                               # догнать незабранные сутки
fca observe --day 2026-09-09 --airports EDDF,LEBL,EGKK --pause 2.0
```

Ключи OpenSky: `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET` или
`OPENSKY_CREDENTIALS=<путь к json>`; на сервере — `/srv/fca/observe/opensky.json`.
Одна учётная запись — один забор: два прогона делят суточный бюджет.

---

## Бенчмарк флота: Form 41 США и IATA ACMG

Полоса рядом с заготовкой владения, ТОиР, экипажа и налёта — в расчёт не
подставляется (решение 177). Видна в `fca bench`, в «Разборе» у ставок
флота и в панели «Флот» витрины.

```bash
# ACMG — машиной, с GitHub книги EUROCONTROL (CC BY 4.0)
fca refresh --only acmg_cost acmg_structure && fca review   # принять оба

# Form 41 — три файла руками с TranStats в data/raw/form41/ (имя любое, .csv или .zip)
fca refresh --only form41
fca bench                       # сводка по всем типам выборки
fca bench A320                  # полосы, модель на плече выборки, «час + цикл»
fca bench A321 --carriers       # строки перевозчиков, из которых сложена полоса
fca bench B738 --year 2024
```

Что скачать (TranStats, раз в год, после выхода Q4 — примерно в мае):

| файл | где | что отметить |
|---|---|---|
| Schedule P-5.2 | Air Carrier Financial Reports (Form 41) → Schedule P-5.2 → Download | год, все кварталы, все поля (Select all) |
| Schedule T-2 | Air Carrier Summary Data → T2 → Download | тот же год, все кварталы, все поля |
| L_AIRCRAFT_TYPE | на странице загрузки у поля AircraftType — ссылка на таблицу расшифровки | — |

Адреса страниц загрузки: `transtats.bts.gov/DL_SelectFields.asp?gnoyr_VQ=FMK`
(P-5.2) и `…?gnoyr_VQ=FIH` (T-2).

Файл узнаётся по заголовку. Незнакомый заголовок — отказ со списком колонок:
прислать эту строку, парсер дополняется. Тип BTS без нашего ИКАО печатается
в `fca bench` строкой «кодов типа без нашего ИКАО» — дописывается шаблон в
`bench.TYPE_PATTERNS`.

Как читать: ТОиР — счёт 52990 (прямой плюс накладные ТОиР) на блок-час;
экипаж — только лётный, модель приводится к лётному по структуре ACMG;
владение — аренда и амортизация по балансу, нижняя граница для нового
борта. Модель сравнивается на СРЕДНЕМ ПЛЕЧЕ ВЫБОРКИ, а не на своём.

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
fca serve --public                        # запись в справочник закрыта; гости — в своих местах
fca serve --guests                        # рабочие места и локально: data/user.db
```

Вкладки: Маршрут · Разбор · Порог · Типы · Характеристики · Данные.

**Валюта** — переключатель рядом с языком (EUR · USD · RUB · INR · CNY),
`?cur=USD` в адресе. Считается всё в евро, пересчёт на экране по курсу из
хранилища: доллар, рупия, юань — ЕЦБ (`fx_rates`), рубль — Банк России
(`cbr_fx`). Нет курса — валюта в списке выключена: `fca refresh --only fx_rates
cbr_fx` и `fca publish`. «Разбор» всегда в евро. CLI — в евро.

**Телефон** — та же страница; до 900 px один столбец, параметры под
строкой «Параметры расчёта», Impressum/Datenschutz в подвале. Проверить
локально без телефона: DevTools → Toggle device toolbar (Ctrl/Cmd+Shift+M),
iPhone 14/15 → `http://127.0.0.1:8000/`.

**Рабочее место гостя** — кнопка в шапке (на домене всегда, локально с
`--guests`). Создать → ссылка вида `https://flightcost.app/w#<32 hex>`:
это единственный вход, сервер хранит только хеш. Ключ после `#` до
сервера не доходит — в журналах его нет. В панели: ссылка, экспорт в
JSON, импорт, новая ссылка (старая гаснет), выйти (только cookie),
удалить (всё). Ставки флота там же — ложатся в слой сценария под явным
`--set`. Своего типа без места на домене не сохранить: кнопка откроет
панель. Файл `data/user.db` в `fca publish` не входит; на сервере его
ночью копирует `fca-backup.timer` в `/srv/fca/backup/`, 14 суток.

```bash
curl -s https://flightcost.app/api/ws                     # enabled, exists (по cookie)
# проверка копий — от root на сервере:
systemctl list-timers fca-backup.timer                     # «0 timers listed» → повторить bootstrap
systemctl start fca-backup.service                         # снять копию сейчас
journalctl -u fca-backup -n 5 --no-pager                   # «копия: … хранится N из 14»
ls -la /srv/fca/backup/
sqlite3 /srv/fca/backup/user-$(date -u +%F).db "PRAGMA integrity_check; SELECT COUNT(*) FROM workspaces"
sqlite3 /srv/fca/site/data/user.db "SELECT COUNT(*) FROM workspaces"   # должно совпасть
```

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

## Сеть в витрине

Переключатель «Маршрут / Сеть» в шапке или `http://127.0.0.1:8000/?mode=net`.
Чипы аэропортов (код, название, щелчок по точке; щелчок по чипу — база),
парк, цена, частоты → «Считать сеть». Первый расчёт состава — ядро по
каждому плечу (секунды, на домене до минуты), дальше парк/цены/частоты
пересчитываются мгновенно: сложенная сеть кэшируется на сервере по
составу. Вкладка «Рынок» — свои цены по направлениям и поток по парам;
«Сохранить сеть» — документ в рабочем месте, список рядом.

```bash
curl -s "http://127.0.0.1:8000/api/network?airports=FRA,BCN,DME,OVB,ALA,DEL&base=ALA&ac=A321&fleet=4&fares=ALA-FRA:300,ALA-DEL:170" | python3 -m json.tool | head -40
```

Ключи: `airports`, `base`, `ac`, `fleet`, `util_h`, `lease` (EUR), `fare_mult`,
`fare_conv`, `lf`, `alpha`, `fares` (`A-B:EUR`, направленно), `market`
(`A-B:пасс/мес`), `freqs` (`A-B:рейсов/нед`), `month`, `set`.

## Сеть: симулятор авиакомпании на одном типе

```bash
# пары сложатся сами: права → небо → дальность; база задаёт национальность
fca network FRA BCN DME OVB ALA DEL --base ALA --ac A21N --fleet 4

# цена на 10% ниже рынка, свои частоты, свой поток и ставка лизинга
fca network ALA FRA DME OVB DEL --base ALA --ac A21N --fleet 4 \
    --fare-mult 0.9 --freq ALA-DME=7 --freq ALA-FRA=3 \
    --market-pax ALA-DME=40000 --lease 380000

# нет рыночной цены по паре — задать свою (оба направления)
fca network … --fare ALA-OVB=120
# S-кривая: показатель — допущение, 1.0 = пропорция
fca network … --alpha 1.5
# всё в JSON для разбора
fca network … --json
```

Границы FIR мира для обхода закрытого неба (раз в цикл AIRAC):

```bash
fca refresh --only fir_world          # → data/geo/zones_world.json, CC BY-SA
```

Закрытия неба и посадки — `data/rights/closures.yaml`: запись с датой,
документом и `certainty`. Снятое закрытие получает `valid_to`, а не
удаляется.

## Пассажиропоток по парам (M10)

Европа — Eurostat, таблицы `avia_par_<страна>` (`de`, `es`, `it`, `fr`, `tr`, …):

1. Data Browser → поиск `avia_par_de` → Download → **TSV** или **SDMX-CSV**,
   «full dataset» (можно .gz). Нужна месячная частота и мера `PAS_CRD`
   (пассажиры перевезённые) — остальное парсер пропустит сам.
2. Положить в `data/raw/eurostat_par/` (имя любое).
3. `fca refresh --only eurostat_par` — в отчёте «пар N, месяцев с … по …».

США — BTS T-100 Segment (All Carriers), со страницы TranStats, как Form 41:
файл (.csv, .zip или .gz) в `data/raw/t100/`, затем
`fca refresh --only airport_codes t100`. Коды ИАТА переводятся в ИКАО
указателем; непереведённые названы в сводке.

Индия — DGCA, скачивается само (сборка Vonter/india-aviation-traffic на
GitHub): `fca refresh --only airport_codes dgca_domestic dgca_international`.
Города переводятся в аэропорты по `config/dgca_cities.yaml`; что не
перевелось — в сводке разбора, дописывается туда же (ИАТА или ИКАО).

Россия — годовая таблица по парам городов без первоисточника (xlsx, «От — До —
<год> Янв-Дек», коды От2/До2): в `data/raw/ru_pairs/`, затем
`fca refresh --only ru_pairs`. Москва — весь город (@MOW).

На Mac Терминал по умолчанию не видит «Загрузки» («Operation not
permitted»): перетащить файлы в папку проекта Finder'ом или дать доступ —
Системные настройки → Конфиденциальность → Файлы и папки → Терминал.

Пару публикуют обе страны — берётся среднее, расхождение называется.
Хранятся последние 36 месяцев каждого файла. Где виден поток: вкладка
«Маршрут» (блок «Поток по паре»), «Типы» (под полем пассажиров), сеть →
«Рынок» и колонка «нужно». Россия и Казахстан — оценка по наблюдённым
рейсам или своё число на вкладке «Рынок». Кресла в оценке — по типам
наблюдённых бортов: после сбора ADS-B выполнить `fca observe --aggregate`.

## Отчёт по парку (Ф5)

Сеть → вкладка «Типы» → «Сравнить» → «Отчёт по парку ↗» / PDF / Excel.
Вопрос отчёта: **эту долю потока на этих парах — сколько рейсов, бортов и
денег на каждом типе**. Объём на входе, парк на выходе (решение 204).

| Ввод (на странице отчёта) | По умолчанию | Что делает |
|---|---|---|
| Доля потока | 10% | объём пары = поток × доля |
| Цена к рынку | как у сети | доля × цена^(−эластичность) |
| Эластичность | 1,5 | **допущение**, данных нет |
| Плановая загрузка | 80% | под неё подбираются частоты |
| Рейсов в неделю не меньше | 7 | реже — не линия; держит большой борт полупустым на тонком рынке |
| Резерв парка | 10%, ≥1 борт | лизинг платится и за резерв |

Пары без потока не летаются — поток задаётся на вкладке «Рынок».
ЛТХ и поставки — `data/types/specs.yaml` и `availability.yaml` (обзоры на
30.09.2026; после 31.03.2027 отчёт пишет «сведения старше полугода»).

PDF печатает безголовый Chromium. На сервере один раз:
```bash
/srv/fca/venv/bin/pip install playwright && /srv/fca/venv/bin/playwright install --with-deps chromium
```
Без этого страница и Excel работают, а PDF отвечает, что поставить.

## Выкладка на flightcost.app

Два канала, не смешивать: **код** — через git, **справочник** — через
`fca publish`.

```bash
# код: страницы, serve.py, скрипты
git add -A && git commit -m "…" && git push
# если секреты DEPLOY_* в GitHub заданы — выложится само после зелёных тестов;
# если нет — руками:
ssh deploy@АДРЕС bash /srv/fca/app/deploy/deploy.sh

# справочник: после refresh и review у себя
fca publish --dry-run            # что уедет и сколько весит
fca publish                      # адрес из FCA_DEPLOY_HOST=deploy@АДРЕС

# пакет сообщества из сырой выгрузки (сырая в репозиторий не идёт)
fca tkp-pack                     # data/raw/tkp → data/tkp/tkp_charges.json

# что сейчас на сервере: версия кода, дата снимка, незаполненные реквизиты
curl -s https://flightcost.app/healthz
```

Перенастройка сервера (новый сервер, смена домена, правка `Caddyfile`,
новый юнит systemd — например таймер копий):

```bash
ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh -- flightcost.app
```

Реквизиты Impressum и политики — `flightcostapp/web/legal.json`, едут
как код. Пустое поле видно на странице и в `/healthz` (`legal_missing`).

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
