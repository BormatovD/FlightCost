#!/usr/bin/env bash
# Одноразовая настройка чистого сервера под витрину.
# Понимает два семейства: AlmaLinux / Rocky / RHEL 9–10 (dnf, firewalld,
# SELinux) и Ubuntu / Debian (apt, ufw).
#
# Запускается с вашего компьютера — от root или от пользователя с sudo:
#     ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh
#     ssh ПОЛЬЗОВАТЕЛЬ@АДРЕС "sudo bash -s" < deploy/bootstrap.sh
#     ...и с доменом:  "sudo bash -s -- flightcost.app"
#
# Повторный запуск безопасен: ничего не ломает, только доводит до нужного
# состояния — так же подключается домен, когда он появится.
set -euo pipefail

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
		echo "системный Python старше 3.11 — нужна Ubuntu 24.04 или новее"; exit 1
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

# ── пользователи ─────────────────────────────────────────────────────────
say "пользователи: fca (витрина) и deploy (выкладка)"
NOLOGIN=$(command -v nologin || echo /usr/sbin/nologin)
id fca >/dev/null 2>&1 || useradd --system --user-group --no-create-home \
	--home-dir /nonexistent --shell "$NOLOGIN" fca
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG fca deploy
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
install -d -o deploy -g fca -m 2775 "$ROOT/site" "$ROOT/site/data" "$ROOT/site/data/geo"
install -d -o deploy -g deploy -m 700 "$ROOT/incoming"

say "код и окружение"
[ -d "$ROOT/app/.git" ] || sudo -u deploy git clone --quiet "$REPO" "$ROOT/app"
[ -d "$ROOT/venv" ] || sudo -u deploy "$PY" -m venv "$ROOT/venv"
sudo -u deploy "$ROOT/venv/bin/pip" install --quiet --disable-pip-version-check -e "$ROOT/app"
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

# ── права deploy ─────────────────────────────────────────────────────────
say "права deploy: перезапуск витрины и журнал, больше ничего"
cat > /etc/sudoers.d/fca-deploy <<'SUDO'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart fca, /usr/bin/systemctl status fca, /usr/bin/journalctl -u fca *
SUDO
chmod 440 /etc/sudoers.d/fca-deploy
visudo -cf /etc/sudoers.d/fca-deploy >/dev/null

# ── служба и прокси ──────────────────────────────────────────────────────
say "служба витрины"
install -m 644 "$ROOT/app/deploy/fca.service" /etc/systemd/system/fca.service
command -v restorecon >/dev/null && restorecon /etc/systemd/system/fca.service || true
systemctl daemon-reload
systemctl enable --quiet fca
# Запускается первой публикацией справочника: без снимка показывать нечего.
[ -f "$ROOT/site/data/flightcost.db" ] && systemctl restart fca || true

say "Caddy: ${DOMAIN:-без домена, только :80}"
sed "s|^ДОМЕН {|${DOMAIN:-:80} {|" "$ROOT/app/deploy/Caddyfile" > /etc/caddy/Caddyfile
install -d -o caddy -g caddy /var/log/caddy
command -v restorecon >/dev/null && restorecon -R /etc/caddy /var/log/caddy || true
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
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
	ufw --force enable >/dev/null
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
