#!/usr/bin/env bash
# Выкладка кода на сервер. Запускает GitHub Actions после зелёных тестов:
#     ssh deploy@сервер /srv/fca/app/deploy/deploy.sh
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

"$ROOT/venv/bin/pip" install --quiet --disable-pip-version-check -e .
echo "$after" > "$ROOT/VERSION"

sudo /usr/bin/systemctl restart fca

# Выкладка удалась, только если витрина ответила и назвала новую версию.
for _ in $(seq 1 30); do
	sleep 1
	if out=$(curl -fsS http://127.0.0.1:8000/healthz 2>/dev/null); then
		case "$out" in
			*"\"version\": \"$after\""*) echo "витрина отвечает, версия $after"; exit 0 ;;
		esac
	fi
done

echo "витрина не ответила с версией $after за 30 секунд. Последние строки журнала:" >&2
sudo /usr/bin/journalctl -u fca -n 40 --no-pager >&2 || true
exit 1
