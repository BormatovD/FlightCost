#!/usr/bin/env bash
# Выкладка кода на сервер. Запускает GitHub Actions после зелёных тестов:
#     ssh deploy@сервер bash /srv/fca/app/deploy/deploy.sh
# Можно запустить и руками — то же самое.
#
# Сервер код не правит никогда: он всегда приводится к тому, что лежит в
# main на GitHub. Поэтому `reset --hard`, а не `pull` — случайная правка на
# сервере не помешает выкладке, а просто исчезнет.
set -euo pipefail

ROOT=/srv/fca
cd "$ROOT/app"

before=$(git rev-parse --short HEAD)
git fetch --quiet origin main
git reset --quiet --hard origin/main
after=$(git rev-parse --short HEAD)
echo "код: $before → $after"

exec bash "$ROOT/app/deploy/apply-release.sh" "$before"
