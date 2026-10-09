#!/usr/bin/env bash
# Ночная копия базы рабочих мест гостей (data/user.db). Справочник
# flightcost.db не копируется: он — снимок каталога владельца, его
# восстанавливает `fca publish`. Места гостей восстановить неоткуда,
# кроме этой копии.
#
# Запускает fca-backup.timer от пользователя fca (bootstrap.sh ставит
# оба юнита). Руками: sudo -u fca bash /srv/fca/app/deploy/backup.sh
#
# KEEP — сколько суточных копий хранить. Это число обещано в
# /datenschutz, пункт 7 («удалённые данные могут оставаться в копии до
# 14 дней»): меняете здесь — меняйте текст.
set -euo pipefail

KEEP=14
SRC=/srv/fca/site/data/user.db
DST=/srv/fca/backup
PY=${PY:-/srv/fca/venv/bin/python}

[ -f "$SRC" ] || { echo "нет $SRC — мест ещё не было, копировать нечего"; exit 0; }
install -d -m 700 "$DST"

out="$DST/user-$(date -u +%F).db"
# Online backup API — согласованная копия и при открытой базе; cp мог бы
# снять половину транзакции. Python из окружения витрины, чтобы не
# зависеть от того, стоит ли sqlite3-клиент.
"$PY" - "$SRC" "$out.tmp" <<'PYEOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PYEOF
mv -f "$out.tmp" "$out"
chmod 600 "$out"

# Старше KEEP суток — долой: по имени, не по mtime, чтобы перенос
# каталога не «омолодил» копии.
cutoff=$(date -u -d "-$KEEP days" +%F 2>/dev/null || date -u -v-"$KEEP"d +%F)
for f in "$DST"/user-*.db; do
	[ -e "$f" ] || continue
	d=${f##*/user-}; d=${d%.db}
	[[ "$d" < "$cutoff" ]] && rm -f "$f"
done
echo "копия: $out ($(du -h "$out" | cut -f1)); хранится $(ls "$DST"/user-*.db | wc -l) из $KEEP"
