#!/usr/bin/env bash
# Одноразовая настройка чистого сервера под витрину.
# Понимает два семейства: AlmaLinux / Rocky / RHEL 9–10 (dnf, firewalld,
# SELinux) и Ubuntu 22.04+ / Debian (apt, ufw). Сервер может быть общим:
# чужие сайты в Caddy и чужие службы скрипт не трогает.
#
# Запускается с вашего компьютера — от root или от пользователя с sudo:
#     ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh
#     ssh ПОЛЬЗОВАТЕЛЬ@АДРЕС "sudo bash -s" < deploy/bootstrap.sh
#     ...и с доменом:  "sudo bash -s -- flightcost.app"
#
# Повторный запуск безопасен: ничего не ломает, только доводит до нужного
# состояния — так же подключается домен, когда он появится.
set -euo pipefail
# Локаль приходит с компьютера по SSH (на macOS LC_CTYPE=UTF-8), а на
# сервере такой нет — perl и apt сыпали предупреждениями на каждом шаге.
export LC_ALL=C.UTF-8 LANG=C.UTF-8
unset LC_CTYPE LANGUAGE

DOMAIN="${1:-}"
REPO="https://github.com/BormatovD/FlightCost.git"
ROOT=/srv/fca

say() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "запускать от root"; exit 1; }
# Рабочий каталог — корень, а не /root. Иначе `sudo -u deploy pip` при
# повторном запуске падает: editable-установка кладёт в sys.path
# относительный «путь» __editable__…__path_hook__, pip делает ему stat
# относительно текущего каталога, а /root пользователю deploy закрыт.
cd /

if command -v dnf >/dev/null; then FAMILY=el
elif command -v apt-get >/dev/null; then FAMILY=deb
else echo "не знаю этот дистрибутив: нет ни dnf, ни apt-get"; exit 1; fi
. /etc/os-release
say "система: $PRETTY_NAME (семейство $FAMILY)"

# ── пакеты ────────────────────────────────────────────────────────────────
say "пакеты"
if [ "$FAMILY" = el ]; then
	# Без `curl`: в минимальном образе стоит curl-minimal, и полный curl с ним
	# конфликтует — dnf остановил бы скрипт. Команда curl уже есть.
	dnf install -y -q git rsync sqlite tar sudo dnf-plugins-core firewalld \
		policycoreutils-python-utils dnf-automatic
	# Обновления безопасности ставятся сами — сервер, о котором забыли, не дырявый.
	sed -i -e 's/^upgrade_type *=.*/upgrade_type = security/' \
		-e 's/^apply_updates *=.*/apply_updates = yes/' /etc/dnf/automatic.conf
	systemctl enable --now -q dnf-automatic.timer
else
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq
	apt-get install -y -qq python3 python3-venv python3-pip git rsync sqlite3 curl ufw \
		debian-keyring debian-archive-keyring apt-transport-https gnupg unattended-upgrades
	dpkg-reconfigure -f noninteractive unattended-upgrades
fi

# Python 3.11+: его требует openap. На AlmaLinux 9 системный — 3.9, поэтому
# ставится отдельный python3.12 рядом с системным, не вместо него.
PY=python3
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
	if [ "$FAMILY" = el ]; then
		dnf install -y -q python3.12 python3.12-pip
		PY=python3.12
	else
		# Ubuntu 22.04: системный 3.10. Ставим 3.12 рядом из PPA deadsnakes —
		# системный python3 не трогаем: на сервере живут другие проекты.
		apt-get install -y -qq software-properties-common
		add-apt-repository -y -n ppa:deadsnakes/ppa >/dev/null
		apt-get update -qq
		apt-get install -y -qq python3.12 python3.12-venv
		PY=python3.12
	fi
fi
say "Python: $($PY --version)"

# ── Caddy ────────────────────────────────────────────────────────────────
if ! command -v caddy >/dev/null; then
	say "Caddy — обратный прокси с HTTPS"
	if [ "$FAMILY" = el ]; then
		dnf copr enable -y -q @caddy/caddy
		dnf install -y -q caddy
	else
		curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
			| gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
		curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
			> /etc/apt/sources.list.d/caddy-stable.list
		apt-get update -qq && apt-get install -y -qq caddy
	fi
fi

# ── Node.js 24 и OpenClaw для агента ─────────────────────────────────────
# OpenClaw требует Node 24.16+. Версия OpenClaw ЗАКРЕПЛЕНА: релизы выходят
# почти ежедневно, а набор инструментов модели проверяется тестом
# tests/test_agent.py (Cage) именно на этой версии. Поднимать — вручную:
# сменить строку, прогнать тест с FCA_TEST_OPENCLAW, выложить.
OPENCLAW_VERSION=2026.10.5
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 24 ]; then
	say "Node.js 24 (NodeSource)"
	if [ "$FAMILY" = el ]; then
		curl -fsSL https://rpm.nodesource.com/setup_24.x | bash - >/dev/null
		dnf install -y -q nodejs
	else
		curl -fsSL https://deb.nodesource.com/setup_24.x | bash - >/dev/null
		apt-get install -y -qq nodejs
	fi
fi
# Владелец root, агент только читает: переписать свой бинарник он не может.
# --ignore-scripts: никакие установочные скрипты зависимостей не исполняются.
if [ "$(cat /srv/fca/openclaw/.version 2>/dev/null)" != "$OPENCLAW_VERSION" ]; then
	say "OpenClaw $OPENCLAW_VERSION"
	install -d -m 755 /srv/fca /srv/fca/openclaw
	(cd /srv/fca/openclaw && npm install --prefix /srv/fca/openclaw --ignore-scripts --no-audit \
		--no-fund --loglevel=error "openclaw@$OPENCLAW_VERSION" >/dev/null)
	echo "$OPENCLAW_VERSION" > /srv/fca/openclaw/.version
fi
# Свой установочный шаг OpenClaw (чистка dist, встроенные плагины) пропущен
# --ignore-scripts, и OpenClaw доделывает его при первом запуске — записью в
# собственный каталог. У агента каталог только для чтения, и запуск падал:
# «package lifecycle is incomplete … EROFS». Доделываем здесь, один раз, от
# непривилегированного nobody (не от root), пока каталог ему открыт.
OC_PKG=/srv/fca/openclaw/node_modules/openclaw
if [ -e "$OC_PKG/.openclaw-lifecycle-pending" ] || [ -e "$OC_PKG/dist/openclaw-install-guard" ]; then
	say "OpenClaw: завершение установки"
	chown -R nobody /srv/fca/openclaw
	runuser -u nobody -- env HOME=/tmp NO_COLOR=1 DO_NOT_TRACK=1 node "$OC_PKG/openclaw.mjs" --version
fi
chown -R root:root /srv/fca/openclaw && chmod -R a+rX,go-w /srv/fca/openclaw

# ── пользователи ─────────────────────────────────────────────────────────
say "пользователи: fca (витрина), deploy (выкладка), fcabot (бот), agent (агент)"
NOLOGIN=$(command -v nologin || echo /usr/sbin/nologin)
id fca >/dev/null 2>&1 || useradd --system --user-group --no-create-home \
	--home-dir /nonexistent --shell "$NOLOGIN" fca
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG fca deploy
# Три узкие группы вместо одной общей (проверка безопасности 03.11.2026:
# общая группа давала витрине — процессу, что смотрит в интернет, — чтение
# главной базы и присланного людьми):
#   fcaspool — ящик сообщений владельцу: пишут бот, агент и служебные юниты
#              (им группа даётся в юните, SupplementaryGroups), читает бот;
#   fcaq     — очередь и черновики агента: только бот и агент;
#   fcaxfer  — обмен с компьютером владельца: только deploy и бот.
# Витрина (fca) не состоит ни в одной.
for g in fcaspool fcaq fcaxfer; do getent group "$g" >/dev/null || groupadd --system "$g"; done
id fcabot >/dev/null 2>&1 || useradd --system --user-group --no-create-home \
	--home-dir /srv/fca/bot --shell "$NOLOGIN" fcabot
id agent >/dev/null 2>&1 || useradd --system --user-group --no-create-home \
	--home-dir /srv/fca/agent/home --shell "$NOLOGIN" agent
# Прежняя версия заводила agent с оболочкой для интерактивного OpenClaw.
# Теперь агент запускается только юнитом — входить им незачем.
usermod -s "$NOLOGIN" agent
usermod -aG fcaspool,fcaq,fcaxfer fcabot
usermod -aG fcaspool,fcaq agent
usermod -aG fcaxfer deploy
# Прежняя черновая версия заводила одну общую группу fcabus — убрать.
if getent group fcabus >/dev/null; then
	for u in fca fcabot agent deploy; do gpasswd -d "$u" fcabus >/dev/null 2>&1 || true; done
	groupdel fcabus || true
fi
# Журналы deploy читает через группу systemd-journal (только чтение), а не
# через sudo journalctl: sudo с «*» пропускал любые ключи, в том числе
# очистку журнала всей машины.
usermod -aG systemd-journal deploy
# Ваш ключ — и для deploy. Берётся у root и у того, кто запустил скрипт
# через sudo: облачные образы AlmaLinux часто не пускают root вовсе, и
# тогда ключ лежит у обычного пользователя, а у root его нет.
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
KEYSRC=(/root/.ssh/authorized_keys)
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
	KEYSRC+=("$(getent passwd "$SUDO_USER" | cut -d: -f6)/.ssh/authorized_keys")
fi
for src in "${KEYSRC[@]}"; do
	[ -f "$src" ] || continue
	while read -r k; do
		[ -n "$k" ] && ! grep -qxF "$k" /home/deploy/.ssh/authorized_keys && echo "$k" >> /home/deploy/.ssh/authorized_keys
	done < "$src"
done
if [ ! -s /home/deploy/.ssh/authorized_keys ]; then
	echo "не нашёл ни одного ключа SSH ни у root, ни у ${SUDO_USER:-запустившего} —"
	echo "без ключа fca publish не войдёт на сервер. Сначала: ssh-copy-id"
	exit 1
fi
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
command -v restorecon >/dev/null && restorecon -R /home/deploy/.ssh || true

# ── каталоги, код, окружение ─────────────────────────────────────────────
say "каталоги"
install -d -o deploy -g fca -m 755 "$ROOT"
# Без права чтения для «прочих»: на сервере живёт ещё агент обновления данных
# (пользователь agent) — к базе витрины у него доступа нет, только сервер.
install -d -o deploy -g fca -m 2770 "$ROOT/site" "$ROOT/site/data" "$ROOT/site/data/geo" "$ROOT/site/data/airspace"
chmod 2770 "$ROOT/site" "$ROOT/site/data"
find "$ROOT/site/data" -maxdepth 1 -type f -name '*.db*' -exec chmod o-rwx {} + 2>/dev/null || true
install -d -o deploy -g deploy -m 700 "$ROOT/incoming"
# Копии базы рабочих мест гостей: пишет только fca, читает только root.
install -d -o fca -g fca -m 700 "$ROOT/backup"

say "код и окружение"
[ -d "$ROOT/app/.git" ] || sudo -u deploy git clone --quiet "$REPO" "$ROOT/app"
[ -d "$ROOT/venv" ] || sudo -u deploy "$PY" -m venv "$ROOT/venv"
sudo -u deploy "$ROOT/venv/bin/pip" install --quiet --disable-pip-version-check -e "$ROOT/app[pdf]"
sudo -u deploy sh -c "cd $ROOT/app && git rev-parse --short HEAD > $ROOT/VERSION"
chmod -R g+rX "$ROOT/app" "$ROOT/venv"

# SELinux (AlmaLinux): файлы в /srv получают метку var_t, и systemd
# отказывается запускать из них программу — в журнале одно «Permission
# denied» без объяснений. Окружению Python ставится метка исполняемых
# файлов; правило постоянное и переживёт пересборку окружения.
if command -v getenforce >/dev/null && [ "$(getenforce)" != Disabled ]; then
	say "SELinux: метки для окружения Python и данных"
	semanage fcontext -a -t bin_t "$ROOT/venv/bin(/.*)?" 2>/dev/null \
		|| semanage fcontext -m -t bin_t "$ROOT/venv/bin(/.*)?"
	restorecon -R "$ROOT/venv/bin"
	# Caddy проксирует на 127.0.0.1:8000 — разрешить веб-серверу исходящие
	# соединения (безвредно, если Caddy работает вне домена httpd_t).
	setsebool -P httpd_can_network_connect 1
fi

# ── бот, агент, ящик сообщений: каталоги и ключи ────────────────────────
say "каталоги бота и агента, ящик сообщений владельцу"
# Агент кладёт найденное только к себе (out/) — в справочник это попадает
# после проверки человеком. Группы fca у него нет: каталог данных витрины
# ему закрыт; sudo нет.
install -d -o agent -g deploy -m 2770 "$ROOT/inbox"
gpasswd -d agent fca >/dev/null 2>&1 || true
# Ящик: пишут бот, агент и служебные юниты; читает и удаляет бот.
install -d -o root -g fcaspool -m 2770 "$ROOT/spool"
# Присланное людьми — только боту (файлы «только для проверки» тоже здесь).
install -d -o fcabot -g fcabot -m 700 "$ROOT/bot"
# Агент: свой каталог; очередь пишет бот, черновики читает бот.
install -d -o agent -g fcaq -m 2750 "$ROOT/agent" "$ROOT/agent/out"
install -d -o agent -g fcaq -m 2770 "$ROOT/agent/queue"
install -d -o agent -g agent -m 700 "$ROOT/agent/runs" "$ROOT/agent/home"
# Ключи — только root; службам их отдаёт systemd (LoadCredential).
install -d -o root -g root -m 700 /etc/fca
# Главная база (решение владельца 03.11.2026): владелец fcabot, база и
# копии 600. Копию для `fca master pull` (export/) читает deploy через
# fcaxfer; снимок витрине (out/) — только fcabot, подмену делает root.
install -d -o fcabot -g fcaxfer -m 2750 "$ROOT/master" "$ROOT/master/export"
install -d -o fcabot -g fcabot -m 700 "$ROOT/master/out" "$ROOT/master/backup" "$ROOT/master/data" "$ROOT/master/home"
# Сюда компьютер кладёт посев и предложения; забирает fcabot.
install -d -o deploy -g fcaxfer -m 2770 "$ROOT/drop" "$ROOT/drop/proposals"
# Отметка последней выгрузки домой — по ней сервер напоминает о pull.
install -d -o deploy -g fcaxfer -m 2750 "$ROOT/pulls"
# Своих типов владельца на сервере быть не должно и в базе забора: её
# засевали полной копией домашней базы до решения о главной базе.
if [ -f "$ROOT/observe/flightcost.db" ]; then
	runuser -u fca -- sqlite3 "$ROOT/observe/flightcost.db" "DELETE FROM facts WHERE source_id = 'aircraft_user'"
fi

# ── PDF отчёта: Chromium в общий каталог ─────────────────────────────────
if [ ! -d "$ROOT/ms-playwright" ]; then
	say "Chromium для PDF отчёта по парку"
	if [ "$FAMILY" = deb ]; then
		PLAYWRIGHT_BROWSERS_PATH="$ROOT/ms-playwright" "$ROOT/venv/bin/playwright" install --with-deps chromium
	else
		dnf install -y -q nss nspr atk at-spi2-atk at-spi2-core cups-libs libdrm libxkbcommon \
			libXcomposite libXdamage libXfixes libXrandr libxshmfence mesa-libgbm pango cairo alsa-lib
		PLAYWRIGHT_BROWSERS_PATH="$ROOT/ms-playwright" "$ROOT/venv/bin/playwright" install chromium
	fi
	chmod -R a+rX "$ROOT/ms-playwright"
fi

# ── права deploy ─────────────────────────────────────────────────────────
say "права deploy: перезапуск витрины и бота, запуск приёма и обновления базы — ровно эти команды"
cat > /etc/sudoers.d/fca-deploy <<'SUDO'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart fca, /usr/bin/systemctl status fca, /usr/bin/systemctl restart fca-bot, /usr/bin/systemctl start fca-master-import.service, /usr/bin/systemctl start --no-block fca-master-refresh.service
SUDO
chmod 440 /etc/sudoers.d/fca-deploy
visudo -cf /etc/sudoers.d/fca-deploy >/dev/null

# ── служба и прокси ──────────────────────────────────────────────────────
say "служба витрины"
# Сообщение о сбое любого юнита — первым: на него ссылаются OnFailure= остальных.
install -m 644 "$ROOT/app/deploy/fca-notify@.service" /etc/systemd/system/
install -m 644 "$ROOT/app/deploy/fca.service" /etc/systemd/system/fca.service
command -v restorecon >/dev/null && restorecon /etc/systemd/system/fca.service || true
systemctl daemon-reload
systemctl enable --quiet fca
# Запускается первой публикацией справочника: без снимка показывать нечего.
[ -f "$ROOT/site/data/flightcost.db" ] && systemctl restart fca || true

say "ночная копия базы рабочих мест гостей"
install -m 644 "$ROOT/app/deploy/fca-backup.service" "$ROOT/app/deploy/fca-backup.timer" /etc/systemd/system/
command -v restorecon >/dev/null && restorecon /etc/systemd/system/fca-backup.* || true
systemctl daemon-reload
systemctl enable --now --quiet fca-backup.timer

say "забор наблюдений ADS-B — своя база, свой таймер"
# Своя база, а не снимок витрины: fca publish подменяет снимок целиком и
# вычищает из него наблюдения. Группа fca (в ней deploy) читает базу, чтобы
# владелец мог забрать накопленное; ключи OpenSky — только fca.
install -d -o fca -g fca -m 2750 "$ROOT/observe"
install -m 644 "$ROOT/app/deploy/fca-observe.service" "$ROOT/app/deploy/fca-observe.timer" /etc/systemd/system/
command -v restorecon >/dev/null && restorecon /etc/systemd/system/fca-observe.* || true
systemctl daemon-reload
if [ -f "$ROOT/observe/flightcost.db" ] && [ -f "$ROOT/observe/opensky.json" ]; then
	systemctl enable --now --quiet fca-observe.timer
	echo "таймер включён: $(systemctl list-timers fca-observe.timer --no-legend | awk '{print $1, $2, $3}')"
else
	# Таймер без базы и ключей падал бы каждые сутки — включается, когда
	# оба файла на месте. Повторный bootstrap после их появления включит.
	echo "таймер НЕ включён: нет $( [ -f "$ROOT/observe/flightcost.db" ] || printf 'базы ' )$( [ -f "$ROOT/observe/opensky.json" ] || printf 'ключей' )"
	echo "  порядок — deploy/README.md, раздел «Наблюдения ADS-B на сервере»"
fi

say "главная база: приём с компьютера, обновление, подмена снимка витрины"
install -m 755 -o root -g root "$ROOT/app/deploy/swap.sh" /usr/local/sbin/fca-swap
install -m 644 "$ROOT/app/deploy/fca-master-import.service" "$ROOT/app/deploy/fca-master-refresh.service" \
	"$ROOT/app/deploy/fca-master-refresh.timer" "$ROOT/app/deploy/fca-swap.service" \
	"$ROOT/app/deploy/fca-swap.path" /etc/systemd/system/
systemctl daemon-reload
# Без главной базы юнит обновления пропускается (ConditionPathExists) —
# таймер можно держать включённым с первого дня.
systemctl enable --now --quiet fca-master-refresh.timer
systemctl enable --now --quiet fca-swap.path
[ -f "$ROOT/master/flightcost.db" ] && echo "главная база есть" \
	|| echo "главной базы ещё нет: с компьютера — fca master push (deploy/README.md, «Главная база»)"

say "Телеграм-бот и недельная сводка"
install -m 644 "$ROOT/app/deploy/fca-bot.service" "$ROOT/app/deploy/fca-digest.service" \
	"$ROOT/app/deploy/fca-digest.timer" /etc/systemd/system/
systemctl daemon-reload
# Сводка копится в ящике и без бота — включается сразу.
systemctl enable --now --quiet fca-digest.timer
if [ -s /etc/fca/bot.token ] && [ -s /etc/fca/bot.env ]; then
	systemctl enable --quiet fca-bot && systemctl restart fca-bot
	echo "бот запущен: journalctl -u fca-bot -n 20"
else
	echo "бот НЕ запущен: нужны /etc/fca/bot.token и /etc/fca/bot.env — deploy/README.md, «Бот и агент»"
fi

say "агент обновления данных (OpenClaw)"
install -m 644 "$ROOT/app/deploy/fca-agent@.service" "$ROOT/app/deploy/fca-agent-submissions.timer" \
	"$ROOT/app/deploy/fca-agent-charges.timer" "$ROOT/app/deploy/fca-agent-watch.timer" \
	"$ROOT/app/deploy/fca-agent-fuel.timer" "$ROOT/app/deploy/fca-agent-night.timer" \
	"$ROOT/app/deploy/fca-agent-prices.timer" /etc/systemd/system/
# Свои внешние адреса сервера — тоже под запретом для агента: на них
# слушают игра и порты Docker. Адреса машины, поэтому не в репозитории.
install -d /etc/systemd/system/fca-agent@.service.d
printf '[Service]\nIPAddressDeny=%s\n' "$(hostname -I)" > /etc/systemd/system/fca-agent@.service.d/10-host.conf
systemctl daemon-reload
if [ -s /etc/fca/anthropic.key ]; then
	systemctl enable --now --quiet fca-agent-submissions.timer
	systemctl enable --now --quiet fca-agent-charges.timer
	systemctl enable --now --quiet fca-agent-watch.timer
	systemctl enable --now --quiet fca-agent-fuel.timer
	systemctl enable --now --quiet fca-agent-night.timer
	systemctl enable --now --quiet fca-agent-prices.timer
	echo "таймеры агента включены"
else
	echo "агент НЕ включён: нет ключа /etc/fca/anthropic.key — deploy/README.md, «Бот и агент»"
fi

# Без домена — адрес сервера по http, а не `:80`: catch-all `:80` спорит с
# любым другим `:80` в общем Caddyfile («ambiguous site definition»), а на
# общем сервере такой блок почти всегда есть (заготовка пакета Caddy).
SITE_ADDR="${DOMAIN:-http://$(hostname -I | awk '{print $1}')}"
say "Caddy: $SITE_ADDR"
# Наш сайт — отдельным файлом, который главный Caddyfile подключает через
# import. Главный файл НЕ перезаписывается: на сервере могут жить другие
# сайты (play.flightcost.app). Прежняя версия скрипта затирала его целиком.
sed "s|^ДОМЕН {|$SITE_ADDR {|" "$ROOT/app/deploy/Caddyfile" > /etc/caddy/fca.caddy
if [ ! -f /etc/caddy/Caddyfile ]; then
	echo "import /etc/caddy/fca.caddy" > /etc/caddy/Caddyfile
elif ! grep -q '^import /etc/caddy/fca.caddy' /etc/caddy/Caddyfile; then
	cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
	printf '\n# FlightCost (flightcost.app) — bootstrap.sh\nimport /etc/caddy/fca.caddy\n' >> /etc/caddy/Caddyfile
fi
install -d -o caddy -g caddy /var/log/caddy
command -v restorecon >/dev/null && restorecon -R /etc/caddy /var/log/caddy || true
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
# validate от root сам создаёт файл журнала — с владельцем root и правами
# 600. Служба Caddy работает от пользователя caddy, открыть его не может и
# падает при старте. Возвращаем каталог журнала его хозяину.
chown -R caddy:caddy /var/log/caddy
command -v restorecon >/dev/null && restorecon -R /var/log/caddy || true
systemctl enable --quiet caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy

# ── межсетевой экран и ssh ───────────────────────────────────────────────
say "межсетевой экран: открыты только ssh, 80, 443"
if [ "$FAMILY" = el ]; then
	systemctl enable --now -q firewalld
	firewall-cmd -q --permanent --add-service=ssh --add-service=http --add-service=https
	firewall-cmd -q --reload
else
	ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
	# Экран включаем только на чистом сервере. Если уже слушают другие
	# службы (Docker, игра, агенты), включение закрыло бы их без
	# предупреждения — а порты Docker ufw всё равно не закрывает: их
	# публикацию надо ограничивать в самом compose (127.0.0.1:порт).
	if ufw status | grep -q inactive && ss -tlnH | awk '{print $4}' | grep -qvE ':(22|80|443)$'; then
		echo "  ufw НЕ включён: на сервере слушают другие службы — проверьте их порты сами (ss -tlnp)"
	else
		ufw --force enable >/dev/null
	fi
fi

say "ssh: только по ключу"
# Если скрипт запущен через sudo обычным пользователем, вход root по SSH
# закрывается совсем: администрировать есть кем. Если от root — root
# остаётся, но только по ключу, иначе вы бы заперли себя снаружи.
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then ROOTLOGIN=no; else ROOTLOGIN=prohibit-password; fi
cat > /etc/ssh/sshd_config.d/10-fca.conf <<SSH
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin $ROOTLOGIN
SSH
sshd -t
systemctl reload sshd 2>/dev/null || systemctl reload ssh

say "готово"
echo "Дальше, с вашего компьютера:"
echo "  fca publish --host deploy@$(curl -fsS -4 https://ifconfig.me 2>/dev/null || echo АДРЕС)"
echo "  затем откройте http://${DOMAIN:-АДРЕС}/   (с доменом — https://)"
