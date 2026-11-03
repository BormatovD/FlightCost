#!/usr/bin/env bash
# Подмена снимка витрины, собранного из главной базы на сервере.
# Ставится bootstrap.sh КОПИЕЙ в /usr/local/sbin/fca-swap (владелец root) —
# root не исполняет скрипт из каталога кода, который может править deploy.
# Запускает fca-swap.path, когда fcabot кладёт out/flightcost.db.new.
#
# Root здесь не трогает ни одного файла сам. Каталог out/ принадлежит
# fcabot (бот смотрит в интернет), site/data — deploy и fca (витрина
# смотрит в интернет): любое действие root с путём в этих каталогах можно
# подменить ссылкой и направить на системный файл. Поэтому файлы двигают
# их владельцы через runuser — fcabot отдаёт снимок, deploy (владелец базы
# витрины) кладёт его на место; root только перезапускает витрину.
set -euo pipefail
OUT=/srv/fca/master/out
NEW=$OUT/flightcost.db.new
SITE=/srv/fca/site/data/flightcost.db
as_bot() { runuser -u fcabot -- "$@"; }
as_dep() { runuser -u deploy -- "$@"; }

as_bot test -e "$NEW" || exit 0
# Забрать атомарно: снимок, пришедший во время подмены, останется на
# месте и запустит подмену снова, а не будет стёрт.
TAKE=$OUT/.taking-$$
as_bot mv -T -- "$NEW" "$TAKE"
TMP=$(as_dep mktemp "$SITE.swap.XXXXXX")
trap 'as_dep rm -f -- "$TMP" || true; as_bot rm -f -- "$TAKE" || true' EXIT
as_bot cat -- "$TAKE" | as_dep sh -c 'cat > "$1"' _ "$TMP"
ok=$(as_dep sqlite3 "file:$TMP?mode=ro" 'PRAGMA integrity_check' 2>&1 | head -1)
if [ "$ok" != ok ]; then
	as_bot mv -T -- "$TAKE" "$OUT/flightcost.db.bad"
	echo "снимок повреждён: $ok — витрина не тронута" >&2
	exit 1
fi
# Рядом и переименованием: гость не увидит половину базы.
as_dep chgrp fca "$TMP"
as_dep chmod 664 "$TMP"
as_dep mv -fT -- "$TMP" "$SITE"
systemctl restart fca
for _ in $(seq 1 30); do
	sleep 1
	curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && { echo "витрина на новом снимке"; exit 0; }
done
echo "витрина не ответила после подмены — journalctl -u fca -n 50" >&2
exit 1
