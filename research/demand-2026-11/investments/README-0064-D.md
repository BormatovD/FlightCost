# 0064-D — офлайн-детализация исходных XML IATI

Этот этап продолжает 0064-C. **Он не скачивает данные, не вызывает Datastore,
не использует IATI API-ключ, не меняет production FlightCost и не строит прогноз пассажиропотока.**

## Что обнаружено в пилоте 0064-C

- Три исходных XML дали 240 записей и 213 дополнительных IATI ID по отношению
  к прежнему пилоту Datastore. Итоговое объединение источников — 452 уникальных
  IATI ID, **не 452 независимых инвестиционных объекта**.
- В публикации `afd-tz` — 17 родительских и 24 дочерних активности с 48
  взаимными ссылками. Финансовые суммы родителей и дочерних записей не складывать.
- Старая маска `WATCH_SECTORS` не распознавала BRT (21012), солнечную
  энергетику (23230), гидроэлектростанции (23220) и дороги (21023).
  Маска расширена, но остаётся **индикатором отбора, не фильтром выгрузки**.
- Шесть строк содержат `actual_end` в будущем относительно снимка 12.11.2026;
  12 строк со статусом планирования/реализации имеют прошедший плановый срок.
  Это признаки проверки источника, не фактические даты ввода.
- `*.scan.json` содержит только метаданные, без сумм финансовых операций и
  координат. Поэтому построена дополнительная *локальная* стадия разбора XML.

## Что делает `bulk_detail.py`

- Считывает 1–3 ранее скачанных исходных XML из `bulk/raw/`.
- Проверяет локальные `.cache.json`, SHA256, URL, хеш редакции из индекса,
  согласованность с `*.scan.json`, запрет DTD/entities и предельный размер файла.
- Сохраняет отдельные исходные финансовые записи `transaction` и `budget`, не
  суммирует разные стадии, типы операций и валюты.
- Сохраняет `related-activity`, координаты (только валидный WGS84), гео-ID,
  `location-class`, `location-reach`, `exactness`, исходные сектора и даты.
- Различает источники через `source_id=iati_bulk:<dataset>` и сохраняет
  варианты по SHA256 оригинальной структурированной XML-активности.
- Создаёт `candidates.jsonl`, `manifest.json`, `relations.json` под правами
  `0600` в новом каталоге `0700`. Повторная запись в непустой каталог запрещена.

**Предел данных:** `source_variant_sha256` отражает структурную XML-запись; это
не дата первого публичного раскрытия. Сведения, полученные сейчас, не могут
быть подставлены в старый backtest без подтверждённых исторических снимков.

## Применение на Mac

Патч совместим с 0064-C; при наличии локальных изменений сначала проверьте
`git status`. Не накладывайте на старую версию 0064-B.

```bash
git apply --check ~/Downloads/0064-D-bulk-detail.patch
git apply ~/Downloads/0064-D-bulk-detail.patch
python -m unittest discover -s research/demand-2026-11/investments -p 'test_*.py' -q
git diff --check

git add research/demand-2026-11/investments/bulk_seed.py \
  research/demand-2026-11/investments/bulk_detail.py \
  research/demand-2026-11/investments/test_bulk_detail.py \
  research/demand-2026-11/investments/README-0064-D.md
git commit -m "Enrich cached IATI Bulk records without API calls"
git push origin main
```

Дождаться **зелёного GitHub Actions** (деплой восстановлен).

## Запуск на сервере после deploy

Сначала локальный режим: без API-ключа и без сетевых запросов.

```bash
sudo systemd-run --wait --pipe --collect \
  --unit=fca-iati-bulk-detail-0064d \
  -p User=agent \
  -p WorkingDirectory=/srv/fca/app \
  /bin/sh -c '
    base=/srv/fca/agent/research/iati/bulk
    out="$base/structured-$(date -u +%Y%m%dT%H%M%SZ)"
    exec /srv/fca/venv/bin/python \
      /srv/fca/app/research/demand-2026-11/investments/bulk_detail.py \
      --raw-dir "$base/raw" \
      --scans "$base/afdb-morocco.scan.json" "$base/afd-tz.scan.json" "$base/worldbank-cv.scan.json" \
      --out "$out"
  '
```

Записать из вывода путь `structured-…`, затем проверить `manifest.json`.
*Ожидается* 240 исходных записей при отсутствии изменений в кеше; фактическое
количество транзакций и доступность координат нам пока неизвестны и будут
определены только после сканирования оригинальных XML на сервере.

## Импорт в исследовательский SQLite-реестр

**Перед импортом обязательно проверить** `manifest.json`, список конфликтов
и `relations.json`. Импорт добавляет отдельные источники `iati_bulk:<dataset>`
в тот же `evidence.sqlite`, не подменяя прежние записи Datastore:

```bash
sudo -u agent /srv/fca/venv/bin/python \
  /srv/fca/app/research/demand-2026-11/investments/registry.py \
  --db /srv/fca/agent/research/iati/evidence.sqlite \
  --candidates /srv/fca/agent/research/iati/bulk/structured-ВАША_ДАТА/candidates.jsonl
```

`registry.py` пока считает `project_id` **парой источник × IATI ID**. Поэтому
количество строк `project` после импорта будет выше числа физических объектов.
Это **не ошибка**, а намеренное разделение свидетельств. Объединять эти строки
или суммы в один объект можно только после следующего, отдельного этапа
проверки связей и источников. `related-activity` пока хранится в исходном
JSON и отдельном `relations.json`, а не как FK в реестре.

## Что отправлять для следующего анализа

Достаточно `structured-…/manifest.json`, `relations.json` и `candidates.jsonl`
в закрытом архиве. Ни ключи, ни SQLite API-бюджет, ни массивы исходных XML
пока передавать не нужно. Эти файлы содержат публичные IATI данные, но всё
равно используйте `0600` и не делайте исследовательский реестр публичным.

## Статус тестов

Локально: 46 офлайн-тестов `test_bulk_seed`, `test_investment_registry`,
`test_bulk_detail` пройдены. Настоящие XML в этой сессии отсутствуют — только
присланные `*.scan.json`; запуск по полным XML на сервере ещё не выполнен.
