#!/usr/bin/env bash
# Забрать наблюдения ADS-B, накопленные на сервере, в свою базу.
# Запускается у владельца, из корня проекта:
#     bash deploy/pull-observations.sh                  # в data/flightcost.db
#     bash deploy/pull-observations.sh путь/к/базе.db
# Адрес — из FCA_DEPLOY_HOST (как у fca publish).
#
# Слияние без дублей: ключ наблюдения — (вид, ключ, борт, момент), тот же,
# что у уникального индекса. У меток «забрано» борта нет (NULL), а NULL в
# уникальном индексе SQLite различны — поэтому сравнение через IS, а не
# INSERT OR IGNORE: иначе метки удваивались бы при каждом заборе.
# Повторный запуск безопасен: второй раз добавит ноль строк.
set -euo pipefail

HOST=${FCA_DEPLOY_HOST:?задайте FCA_DEPLOY_HOST=deploy@АДРЕС}
DB=${1:-data/flightcost.db}
[ -f "$DB" ] || { echo "нет базы $DB — запускать из корня проекта"; exit 1; }
command -v sqlite3 >/dev/null || { echo "нужен sqlite3"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Согласованная копия на сервере (.backup, не cp: забор может идти прямо
# сейчас), потом домой.
ssh "$HOST" "sqlite3 /srv/fca/observe/flightcost.db '.backup /home/deploy/observe-pull.db'"
scp -q "$HOST:observe-pull.db" "$tmp/srv.db"
ssh "$HOST" "rm -f /home/deploy/observe-pull.db"

sqlite3 "$DB" <<SQL
ATTACH '$tmp/srv.db' AS srv;
SELECT 'на сервере: наблюдений '
       || (SELECT COUNT(*) FROM srv.observations WHERE kind NOT IN ('_fetched', 'fare_min_daily'))
       || ', забранных суток '
       || (SELECT COUNT(DISTINCT observed_at) FROM srv.observations WHERE kind = '_fetched')
       || ', последние ' || IFNULL((SELECT MAX(observed_at) FROM srv.observations
                                    WHERE kind = '_fetched'), '—');
INSERT INTO observations (kind, key, value, unit, observed_at, source_id, ref, note)
SELECT s.kind, s.key, s.value, s.unit, s.observed_at, s.source_id, s.ref, s.note
  FROM srv.observations s
 WHERE NOT EXISTS (SELECT 1 FROM main.observations m
                    WHERE m.kind = s.kind AND m.key = s.key
                      AND m.ref IS s.ref AND m.observed_at = s.observed_at);
SELECT 'добавлено строк: ' || changes();
SQL

echo "дальше: fca observe --aggregate   (свернуть в факты домена observed)"
