# Выкладка на сервер

Три потока, потому что код живёт в git, а данные — нет:

```
код         git push ──▶ GitHub: тесты ──▶ зелёные ──▶ сервер: deploy.sh
справочник  fca refresh, fca review ──▶ fca publish ──▶ сервер: снимок, подмена
гости       живут только на сервере (site/data/user.db); копия каждую ночь
```

Красный тест — на сервер не уходит ничего. Сервер код не правит никогда:
он всегда приводится к `main` на GitHub, поэтому откатывать — тоже через git.

На сервере:

```
/srv/fca/app          код, клон репозитория
/srv/fca/venv         окружение Python
/srv/fca/site/data    снимок справочника и геометрия — то, что показывает витрина;
                      там же user.db — рабочие места гостей, в снимок не входит
/srv/fca/incoming     сюда приходит новый снимок перед подменой
/srv/fca/backup       ночные копии user.db, 14 суток (fca-backup.timer, только root читает)
/srv/fca/observe      своя база забора ADS-B и ключи OpenSky (fca-observe.timer)
/srv/fca/VERSION      какой коммит сейчас выложен
```

Витрина работает от пользователя `fca` и пишет только в `site/data`.
Выкладывает пользователь `deploy`: ему разрешено перезапустить витрину и
читать её журнал, и больше ничего.

---

## Один раз

**1. Сервер.** AlmaLinux 9–10 (или Ubuntu 24.04 — скрипт понимает обе), расположение — ЕС (Германия, Нидерланды, Финляндия): витрина подпадает под GDPR, хостер должен подписать договор обработки данных (ст. 28). При
создании добавьте свой ключ SSH. Почасовая оплата: для тренировки создали,
прошли шаги, удалили — копейки. Всё ниже воспроизводимо скриптами, поэтому
сервер одноразовый: потерять его не страшно.

**2. Настройка.** С вашего компьютера, из корня проекта:

```bash
ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh
```

Скрипт ставит Python 3.11+ и Caddy, заводит пользователей `fca` и `deploy`,
открывает в межсетевом экране только ssh, 80 и 443, отключает вход по
паролю и включает автоматические обновления безопасности. На AlmaLinux он
ещё ставит метки SELinux: без них systemd не запустит витрину из `/srv`, а
в журнале будет только «Permission denied». Повторный запуск безопасен.

Если витрина всё же не стартует на AlmaLinux, первое, что смотреть, —
отказы SELinux: `ausearch -m avc -ts recent`.

**3. Первый снимок справочника.**

```bash
fca publish --dry-run                     # что уйдёт и что будет вычищено
fca publish --host deploy@АДРЕС
```

Откройте `http://АДРЕС/` — витрина работает. `http://АДРЕС/healthz` покажет
версию кода и дату снимка.

Чтобы не писать адрес каждый раз: `export FCA_DEPLOY_HOST=deploy@АДРЕС` в
`~/.zshrc`.

**4. Ключ для GitHub.** Отдельный, только для выкладки:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/fca_actions -N "" -C "github-actions-deploy"
PUB=$(cat ~/.ssh/fca_actions.pub)
ssh deploy@АДРЕС "echo 'command=\"/bin/bash /srv/fca/app/deploy/deploy.sh\",restrict $PUB' >> ~/.ssh/authorized_keys"
```

`command=` и `restrict` значат: этим ключом можно только запустить
выкладку. Даже утёкший из GitHub ключ не откроет на сервере командную
строку.

Три секрета в репозитории — Settings → Secrets and variables → Actions →
New repository secret:

| имя | значение |
|---|---|
| `DEPLOY_HOST` | адрес сервера |
| `DEPLOY_SSH_KEY` | содержимое `~/.ssh/fca_actions` — закрытый ключ, целиком |
| `DEPLOY_KNOWN_HOSTS` | вывод `ssh-keyscan -t ed25519 АДРЕС` |

Последний — отпечаток сервера: GitHub будет заходить только на него, а не
на любой сервер, оказавшийся по этому адресу.

Проверка: любой push в `main`, вкладка Actions — после тестов пойдёт
выкладка и закончится строкой «витрина отвечает, версия …».

**5. Домен.** У регистратора — запись `A` с именем `@` и адресом сервера
(и `AAAA`, если у сервера есть IPv6). Когда `dig +short ДОМЕН` начнёт
отвечать адресом сервера:

```bash
ssh root@АДРЕС "bash -s -- ДОМЕН" < deploy/bootstrap.sh
```

Caddy получит сертификат сам — сайт откроется по `https://ДОМЕН`.

---

## Каждый раз

**Код.**

```bash
git commit -am "…" && git push
```

Дальше всё само. Посмотреть — вкладка Actions; проверить — `curl -s
https://ДОМЕН/healthz`.

**Справочник.**

```bash
fca refresh && fca review       # как обычно
fca publish
```

**Откатить код** — `git revert <коммит> && git push`. История остаётся
честной, сервер приедет к исправленному состоянию тем же путём.

**Журнал витрины** — `ssh deploy@АДРЕС sudo journalctl -u fca -n 50`.

**Рабочие места гостей.** Единственное на сервере, что не восстановить
ни из git, ни из `fca publish`. `fca-backup.timer` снимает копию каждую
ночь в `/srv/fca/backup/user-ДАТА.db` и держит 14 суток — ровно столько
обещает политика конфиденциальности (пункт 7). Вернуть из копии —
остановить витрину, положить файл на место `site/data/user.db`
(владелец `fca`), запустить. При переезде на другой сервер этот файл
забрать вместе с кодом.

Копия, которую ни разу не открывали, — не копия. Проверка, от root:

```bash
systemctl list-timers fca-backup.timer      # «0 timers listed» — юнита нет: повторить bootstrap
systemctl start fca-backup.service          # снять копию сейчас, не дожидаясь ночи
journalctl -u fca-backup -n 5 --no-pager    # «копия: …user-ДАТА.db (…); хранится N из 14»
ls -la /srv/fca/backup/
# копия открывается и в ней то же, что в живой базе:
sqlite3 /srv/fca/backup/user-$(date -u +%F).db "PRAGMA integrity_check; SELECT COUNT(*) FROM workspaces"
sqlite3 /srv/fca/site/data/user.db "SELECT COUNT(*) FROM workspaces"
```

Нет `user.db` вовсе — гостей ещё не было, сервис честно пишет «копировать
нечего» и завершается без ошибки.

---

## Наблюдения ADS-B на сервере

Забор с OpenSky — единственный источник, где просрочка означает потерю:
`fca observe` догоняет неделю назад, дальше пропуск невосстановим. Ноутбук
неделю не включался — дыра навсегда, поэтому забор живёт на сервере.

Пишет он в **свою** базу `/srv/fca/observe/flightcost.db`, не в снимок
витрины: `fca publish` подменяет снимок целиком и вычищает из него
наблюдения. Тип борта определяется в момент забора по реестру бортов, а
реестра в снимке нет (`fca publish` его не возит) — поэтому своя база
засевается один раз копией вашей.

**Один раз** — с вашего компьютера, из корня проекта. Юниты забора едут
с кодом, поэтому сначала `git push` (сервер подтянет их сам), потом:

```bash
# 1. каталог и юниты: bootstrap повторно — безопасно. Таймер он пока НЕ
#    включит и скажет, чего не хватает: базы и ключей
ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh -- flightcost.app

# 2. засеять базу копией своей (в ней реестр бортов) и положить ключи OpenSky
sqlite3 data/flightcost.db ".backup /tmp/observe-seed.db"
scp /tmp/observe-seed.db root@АДРЕС:/srv/fca/observe/flightcost.db
scp ~/ПУТЬ/credentials.json root@АДРЕС:/srv/fca/observe/opensky.json
ssh root@АДРЕС "chown fca:fca /srv/fca/observe/*; chmod 640 /srv/fca/observe/flightcost.db; chmod 600 /srv/fca/observe/opensky.json; restorecon -R /srv/fca/observe 2>/dev/null || true"

# 3. проверить, что OpenSky отвечает именно с этого сервера
ssh root@АДРЕС "cd /srv/fca/observe && sudo -u fca OPENSKY_CREDENTIALS=/srv/fca/observe/opensky.json \
    /srv/fca/venv/bin/fca --db /srv/fca/observe/flightcost.db observe --check"

# 4. включить таймер и снять первые сутки, не дожидаясь утра
ssh root@АДРЕС "systemctl enable --now fca-observe.timer && systemctl start fca-observe.service; \
    journalctl -u fca-observe -n 20 --no-pager"
```

Если шаг 3 отвечает отказом при правильных ключах, а с вашего компьютера
те же ключи работают — OpenSky не пускает адрес сервера. Тогда забор
остаётся дома (cron/launchd с `fca observe`), а таймер на сервере не
включать.

На одной учётной записи OpenSky — один забор: если дома стоит cron с
`fca observe`, снять его, иначе два прогона делят суточный бюджет.

**Каждый раз** — забрать накопленное домой и свернуть:

```bash
bash deploy/pull-observations.sh     # слияние без дублей, повтор безопасен
fca observe --aggregate              # факты домена observed
ssh deploy@АДРЕС sudo journalctl -u fca-observe -n 20   # как прошли последние заборы
```

Реестр бортов в серверной базе — снимок на день засева. Раз в полгода
засеять заново (сначала `bash deploy/pull-observations.sh` — чтобы не потерять
накопленное с прошлого забора, — затем шаг 2).

---

## До объявления адреса

Технически витрина готова к показу после шага 3. Но публично объявлять
домен стоит, когда будут:

- **Impressum и Datenschutzerklärung** — обязательны для сайта оператора в
  Германии — есть;
- **слой гостя** — есть: свои типы и ставки сохраняются в рабочем месте по
  ссылке;
- **английский и немецкий** в интерфейсе — есть.

## PDF отчёта по парку

Нужен Chromium. Ставится один раз от root в общий каталог — витрина
работает от `fca` без домашнего каталога и чужих домашних не видит:

```bash
PLAYWRIGHT_BROWSERS_PATH=/srv/fca/ms-playwright /srv/fca/venv/bin/playwright install chromium
chmod -R a+rX /srv/fca/ms-playwright
```

На Debian/Ubuntu добавьте `--with-deps`. На AlmaLinux он не работает (нет
apt-get) — библиотеки через dnf:

```bash
dnf install -y nss nspr atk at-spi2-atk at-spi2-core cups-libs libdrm libxkbcommon \
  libXcomposite libXdamage libXfixes libXrandr libxshmfence mesa-libgbm pango cairo alsa-lib
```

Путь к браузеру витрине сообщает `fca.service` (`PLAYWRIGHT_BROWSERS_PATH`).
Проверка — кнопка PDF в отчёте по парку или `journalctl -u fca -n 30`.

## Статистика посещений

Витрина сама считает просмотры страниц и уникальных посетителей по суткам,
без cookie и без хранения адресов (как именно — `flightcostapp/visits.py`
и раздел 4 политики конфиденциальности). Счётчики лежат в
`/srv/fca/site/data/stats.db`. Посмотреть:

```bash
ssh deploy@АДРЕС /srv/fca/venv/bin/fca --db /srv/fca/site/data/flightcost.db stats            # по дням, 30 суток
ssh deploy@АДРЕС /srv/fca/venv/bin/fca --db /srv/fca/site/data/flightcost.db stats --pages --days 7
```

Уникальные считаются в пределах суток: один человек, зашедший в понедельник
и во вторник, — два уникальных за неделю. Связать дни нельзя нарочно: соль
хеша меняется каждые сутки и прошлая стирается.

За последние 7 дней до появления счётчика ориентир даёт журнал Caddy (адреса
усечены до /24, поэтому «уникальные» — это сети, а не люди):

```bash
ssh root@АДРЕС "cat /var/log/caddy/fca*.log | jq -r 'select(.request.uri==\"/\") | (.ts|todate[0:10]) + \" \" + .request.remote_ip' | sort -u | cut -d' ' -f1 | uniq -c"
```

## Поисковики

Что сайт отдаёт для них (`flightcostapp/seo.py`):

- `/ru/`, `/en/`, `/de/` — витрина с языком в адресе, заголовком, описанием, связями языков (hreflang) и разметкой
  schema.org; `/` — версия по умолчанию (язык браузера).
- `/<язык>/about` — о сервисе и вопросы-ответы; `/<язык>/types` и `/<язык>/type/<ИКАО>` — страница каждого типа ВС
  из справочника (паспорт с источниками и заготовка калькулятора).
- `/robots.txt`, `/sitemap.xml`, `/llms.txt` (описание для ИИ-ассистентов), `/og.png` (картинка для ссылок).
- Адрес сайта в ссылках — `FCA_SITE_URL`, по умолчанию `https://flightcost.app`.
- Витрина принимает маршрут и тип адресом: `/en/?o=EDDF&d=LEBL&ac=A320`.

После каждой выкладки с новым кодом `deploy.sh` отправляет адреса из sitemap в IndexNow (Bing, Яндекс): ключ —
`seo.INDEXNOW_KEY`, файл подтверждения — `/<ключ>.txt`, его отдаёт витрина.

Один раз, руками:

1. **Google Search Console** (search.google.com/search-console) → «Добавить ресурс» → «Доменный ресурс»
   `flightcost.app` → запись TXT у регистратора домена. Затем «Файлы Sitemap» → `sitemap.xml`.
2. **Bing Webmaster Tools** (bing.com/webmasters) → «Импорт из Google Search Console» — подтверждение и sitemap
   переносятся сами. Через Bing сайт находят ChatGPT и Copilot.
3. **Яндекс.Вебмастер** (webmaster.yandex.ru) — если нужна русскоязычная выдача: подтверждение мета-тегом или DNS,
   затем sitemap.

Проверить, что видит поисковик: `curl -s https://flightcost.app/en/type/A320 | head -40`, и в Search Console —
«Проверка URL».
