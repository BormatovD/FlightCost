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
/srv/fca/bot          бот: присланное людьми (файлы, анкеты) — только пользователь fcabot
/srv/fca/spool        ящик сообщений владельцу: таймеры и агент пишут, бот отправляет
/srv/fca/agent        агент: очередь, черновики (out/), прогоны (runs/), журнал расходов
/srv/fca/openclaw     OpenClaw закреплённой версии, владелец root
/etc/fca              ключи и настройки бота и агента, только root
/srv/fca/master       ГЛАВНАЯ база (fcabot): обновление, приёмка, снимок витрине,
                      export/ — копия для fca master pull, backup/ — 7 суточных копий
/srv/fca/drop         посев и предложения с компьютера владельца
/srv/fca/pulls        отметка последней выгрузки домой
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

С главной базой на сервере (раздел «Главная база») — так:

```bash
fca master pull                            # сначала копия домой
fca refresh --only eurostat_par && fca review   # домашние источники — как обычно
fca master send --only eurostat_par        # факты — в очередь сервера, принять в боте
```

Остальное сервер обновляет сам; данные из репозитория (`data/charges`,
каталог типов) попадают в главную базу при выкладке кода. До `fca master
push` — по-старому: `fca refresh && fca review && fca publish`.

**Откатить код** — `git revert <коммит> && git push`. История остаётся
честной, сервер приедет к исправленному состоянию тем же путём.

**Журнал витрины** — `ssh deploy@АДРЕС journalctl -u fca -n 50`.

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
fca master send --only adsb_flights  # свёрнутое — в главную базу на сервере
ssh deploy@АДРЕС journalctl -u fca-observe -n 20   # как прошли последние заборы
```

Реестр бортов в серверной базе — снимок на день засева. Раз в полгода
засеять заново (сначала `bash deploy/pull-observations.sh` — чтобы не потерять
накопленное с прошлого забора, — затем шаг 2).

---

## Главная база

Решение владельца 03.11.2026: главная база справочника — на сервере, дома —
обязательная копия; чувствительные файлы на сервер не уходят.

| Где | Что |
|---|---|
| сервер, `/srv/fca/master` | база; обновление раз в сутки и после выкладки кода (`fca-master-refresh`); приёмка кнопками в боте; снимок витрине — сам (`fca-swap.path`) |
| компьютер | копия (`fca master pull`); сырьё `data/raw` (Eurostat, BTS, Form 41, ru_pairs), подписная выгрузка сообщества, Platts, свои типы ВС (`aircraft_user`) |

Источники с домашним сырьём (`HOME_ONLY` в `flightcostapp/master.py`) сервер
не обновляет: их разбираете дома, как раньше, а факты отправляете
предложением — `fca master send --only eurostat_par`. Свои типы ВС не
уходят никогда (ни посевом, ни `send`); после `pull` они восстанавливаются
из ваших файлов.

`fca publish` с компьютера больше не подменяет базу на сервере — только
геометрию (`data/geo`, `data/airspace`), и говорит об этом.

**Один раз:**

```bash
ssh deploy@АДРЕС bash /srv/fca/app/deploy/deploy.sh      # свежий код
ssh root@АДРЕС "bash -s" < deploy/bootstrap.sh       # каталоги и юниты главной базы
fca master push                                      # засеять сервер своей базой
fca master pull                                      # и сразу забрать — проверка круга
```

**Обязательно:** `fca master pull` не реже раза в неделю — и всегда перед
работой с базой дома (исследования, `fca refresh` домашних источников).
Сервер напоминает в Телеграме через 7 суток и тревожит через 14. Домашняя
копия до `pull` сохраняется рядом (`flightcost.db.bak-*`, три последних);
наблюдения и ссылки на ваши файлы переносятся в новую копию.

---

## Бот и агент

Бот — `flightcostapp/bot.py`, служба `fca-bot`: приём данных от людей и
пульт владельца (карточки присланного, очередь приёмки, сбои юнитов,
недельная сводка). Модели в боте нет. Агент — `flightcostapp/agent_run.py`,
который запускает установленный OpenClaw с закреплённым конфигом
`deploy/agent/openclaw.json5`. Провайдер — OpenAI, прямой Responses API
(`https://api.openai.com/v1/responses`), без промежуточного шлюза.
Результат — черновик; в справочник его переносит человек.

| Задание | Модель | Расписание таймера | Объём по умолчанию |
| --- | --- | --- | --- |
| `submissions` | `openai/gpt-6-luna` | Каждые 15 минут, случайная задержка до 60 секунд | Очередь присланных документов |
| `charges` | `openai/gpt-6.1-sol` | Понедельник и четверг, 07:40 UTC | До 3 аэропортов |
| `watch` | `openai/gpt-6-luna` | 3-го числа месяца, 07:20 UTC | До 8 тарифов |
| `fuel` | `openai/gpt-6-luna` | 8-го числа месяца, 07:30 UTC | Недостающие месяцы рядов |
| `night` | `openai/gpt-6-luna` | Вторник, 07:50 UTC | До 8 аэропортов |
| `prices` | `openai/gpt-6-luna` | Среда, 07:50 UTC | До 4 типов ВС |

Имена `openai/…` — идентификаторы OpenClaw; в API передаётся имя модели
без префикса провайдера. Доступ к выбранным моделям должен быть разрешён
в проекте OpenAI. Модели по заданиям — `JOBS` в `agent_run.py`.

Клетка агента — четыре слоя: у модели нет командной строки (только чтение
и запись в папке задания, web_fetch и чтение PDF; проверяет
`tests/test_agent.py`, класс Cage); юнит работает от пользователя `agent`
и не видит справочник, базы и бот; результат проверяет программа (цитаты
сверяются с текстом документа, тариф — парсером); принимает человек.
Один API-ключ OpenAI для всех шести заданий хранится в
`/etc/fca/agent.env` (владелец root, права `600`). systemd читает этот файл
через `EnvironmentFile` и передаёт `OPENAI_API_KEY` исполнителю
`agent_run.py`, а исполнитель — дочернему процессу OpenClaw. Парсер PDF
ключа в окружении не получает. В файлы задания ключ не записывается.
Возврата на Anthropic нет.

### Первое включение

Этот порядок — для нового сервера, где `agent.env` ещё не настроен.
На работающем сервере используйте следующий раздел миграции. Выполняйте
команды от root в одной сессии Bash. Ключи вводятся без отображения и в
историю оболочки не попадают. API-ключ можно выпустить в существующем
проекте вашего аккаунта OpenAI; отдельный проект — только опция для
раздельного учёта расходов. Передача данных для обучения в настройках
проекта должна оставаться отключённой. Если сервер ещё не подготовлен,
сначала выполните обычную установку из раздела «Один раз» без API-ключа.

```bash
set -e
umask 077

# 1. Новый токен бота, полученный у @BotFather.
read -rs -p "токен бота: " FCA_BOT_TOKEN_INPUT
printf '\n'
printf '%s' "$FCA_BOT_TOKEN_INPUT" > /etc/fca/bot.token
unset FCA_BOT_TOKEN_INPUT
# Номер вашего чата, полученный у @userinfobot.
printf 'FCA_BOT_OWNER=%s\n' 123456789 > /etc/fca/bot.env

# 2. Настройки агента. Строка API-ключа пока пустая.
cat > /etc/fca/agent.env <<'ENV'
OPENAI_API_KEY=
# Локальный месячный порог: после него новые задания не запускаются.
FCA_AGENT_MONTH_USD=20
# Порог предупреждения о стоимости одного прогона.
FCA_AGENT_RUN_USD=2
# Пилот тарифов: ИКАО через запятую; пусто — порядок _todo.yaml.
FCA_AGENT_CHARGES_ONLY=
FCA_AGENT_CHARGES_PER_RUN=3
FCA_AGENT_WATCH_PER_RUN=8
ENV
chmod 600 /etc/fca/bot.token /etc/fca/bot.env /etc/fca/agent.env

# 3. Свежий код и юниты. С пустым OPENAI_API_KEY bootstrap не включает таймеры агента.
sudo -u deploy bash /srv/fca/app/deploy/deploy.sh
bash /srv/fca/app/deploy/bootstrap.sh                  # пока DNS не переключён
# bash /srv/fca/app/deploy/bootstrap.sh flightcost.app  # после переключения — с доменом

# 4. После установки юнитов — один ключ OpenAI в том же agent.env.
read -rs -p "ключ OpenAI: " FCA_OPENAI_KEY_INPUT
printf '\n'
test -n "$FCA_OPENAI_KEY_INPUT"
sed -i '/^[[:space:]]*OPENAI_API_KEY[[:space:]]*=/d' /etc/fca/agent.env
printf '\nOPENAI_API_KEY=%s\n' "$FCA_OPENAI_KEY_INPUT" >> /etc/fca/agent.env
unset FCA_OPENAI_KEY_INPUT
chmod 600 /etc/fca/agent.env

# 5. Локальные проверки, затем два коротких платных вызова без документов.
systemctl start fca-agent@check
journalctl -u fca-agent@check -n 15 --no-pager
cd /srv/fca/app
FCA_TEST_OPENCLAW=/srv/fca/openclaw/node_modules/.bin/openclaw \
  /srv/fca/venv/bin/python -m unittest tests.test_agent -v
systemctl start fca-agent@smoke
journalctl -u fca-agent@smoke -n 25 --no-pager

# 6. Расписание включаем после успешных проверок.
systemctl enable --now fca-agent-{submissions,charges,watch,fuel,night,prices}.timer
systemctl list-timers 'fca-agent-*' --no-pager
systemctl status fca-bot --no-pager
```

Комментарии в `agent.env` пишите отдельными строками: это файл systemd
`EnvironmentFile`, а не shell-скрипт. Все шесть заданий получают один
`OPENAI_API_KEY` из этого файла при запуске службы. Отдельный файл ключа
не нужен; сам ключ не передавайте аргументом командной строки.

Проверка клетки после изменения версии OpenClaw или конфигурации API:

```bash
cd /srv/fca/app
FCA_TEST_OPENCLAW=/srv/fca/openclaw/node_modules/.bin/openclaw \
  /srv/fca/venv/bin/python -m unittest tests.test_agent -v
```

Это проверка против локального макета API, без настоящего ключа и без
платных запросов. Она не доказывает, что аккаунт OpenAI разрешает выбранные
модели: для этого предназначен `smoke`. `--check` тоже не вызывает модель.

### Переключение уже работающего сервера с Anthropic

Подготовьте патч и проверьте его в отдельной ветке. **До остановки таймеров
не сливайте его в `main` и не делайте `push` в `main`: зелёный CI автоматически
выкладывает код на сервер.** Выполняйте следующие шаги от root в одной сессии
Bash. Подготовьте действующий API-ключ в вашем аккаунте OpenAI; он будет
общим для всех шести заданий в прежнем контуре OpenClaw.

1. Остановите все шесть таймеров и дождитесь завершения текущих заданий.
   Остановка таймера не обрывает уже идущий агент. Этот шаг выполняется
   до изменения кода работающих агентов.

```bash
set -e
fca_agent_jobs=(submissions charges watch fuel night prices)
fca_agent_timers=()
for fca_agent_job in "${fca_agent_jobs[@]}"; do
    fca_agent_timers+=("fca-agent-${fca_agent_job}.timer")
done
systemctl stop "${fca_agent_timers[@]}"
for fca_agent_job in "${fca_agent_jobs[@]}"; do
    while :; do
        fca_agent_state=$(systemctl show --property=ActiveState --value "fca-agent@${fca_agent_job}.service")
        case "$fca_agent_state" in
            active|activating|deactivating) sleep 5 ;;
            *) break ;;
        esac
    done
done
```

2. Теперь слейте проверенную ветку или отправьте коммит в `main` и
   дождитесь зелёного CI. Он выполнит обычную выкладку кода; следующий
   вызов `deploy.sh` также позволяет выполнить её вручную. Таймеры всё
   это время остаются остановленными. Обновите только строку `OPENAI_API_KEY`
   в существующем `agent.env`, затем установите обновлённый юнит. Для этой
   миграции `bootstrap.sh` повторять не нужно: OpenClaw, пользователи и
   каталоги уже установлены. При непустом `OPENAI_API_KEY` в `agent.env`
   `bootstrap.sh` включает таймеры, поэтому здесь следуйте явным шагам.

```bash
sudo -u deploy bash /srv/fca/app/deploy/deploy.sh
umask 077
read -rs -p "ключ OpenAI: " FCA_OPENAI_KEY_INPUT
printf '\n'
test -n "$FCA_OPENAI_KEY_INPUT"
sed -i '/^[[:space:]]*OPENAI_API_KEY[[:space:]]*=/d' /etc/fca/agent.env
printf '\nOPENAI_API_KEY=%s\n' "$FCA_OPENAI_KEY_INPUT" >> /etc/fca/agent.env
unset FCA_OPENAI_KEY_INPUT
chmod 600 /etc/fca/agent.env
install -m 644 /srv/fca/app/deploy/fca-agent@.service /etc/systemd/system/fca-agent@.service
systemctl daemon-reload
systemctl restart fca-bot
```

Бюджеты и остальные настройки в `agent.env`, журнал расходов, состояния
поиска и черновики сохраняются. Проверьте, что числовые значения
`FCA_AGENT_MONTH_USD` и `FCA_AGENT_RUN_USD` записаны без комментариев на той
же строке.

Новые отправки после обновлённого согласия бот помечает в `meta.json`
как `ai_provider: openai`. Прежнее согласие прямо называло Anthropic:
отправки без этой отметки агент переносит в `queue/held-provider`, **не
отправляя документы в OpenAI**. Их можно разобрать вручную либо попросить
автора отправить документы заново через обновлённую форму. Вручную
приписывать старым отправкам нового провайдера нельзя. Ранее созданные
черновики и принятые справочные данные остаются доступными. Копии в
`held-provider` удаляются общей очисткой через 30 дней.

3. Проверьте конфигурацию и границы инструментов, затем доступ к обеим
   моделям. `smoke` делает два коротких платных вызова (Luna и Sol) с
   искусственным заданием на запись `probe.json`, без документов
   пользователей. При ошибке оставьте таймеры остановленными и исправьте
   её до следующего шага.

```bash
systemctl start fca-agent@check
journalctl -u fca-agent@check -n 15 --no-pager
cd /srv/fca/app
FCA_TEST_OPENCLAW=/srv/fca/openclaw/node_modules/.bin/openclaw \
  /srv/fca/venv/bin/python -m unittest tests.test_agent -v
systemctl start fca-agent@smoke
journalctl -u fca-agent@smoke -n 25 --no-pager
```

4. Включите прежнее расписание. После первого рабочего прогона сверьте
   `ledger.jsonl`, черновик и расходы в проекте OpenAI. Старый ключ Anthropic
   для этой системы больше не используется; после успешного перехода его
   можно отозвать в прежнем проекте.

```bash
systemctl enable --now "${fca_agent_timers[@]}"
systemctl list-timers 'fca-agent-*' --no-pager
```

### Черновики и расходы

Черновики тарифов бот присылает в Телеграм и кладёт копию в
`/srv/fca/master/export/drafts/`. Дома `fca master drafts` забирает их,
проверяет парсером и контрольным оборотом A320 против коридора региона и
печатает «ЧИСТЫЙ / СМОТРЕТЬ / ОТВЕРГНУТ»; `--accept-clean` кладёт чистые в
`data/charges/`, `--accept ИКАО,…` — названные после просмотра.

`watch` ищет новые редакции заведённых тарифов; найденная новая редакция
встаёт первой в очередь `charges`. Таймеры устанавливает `bootstrap.sh`;
обычный `deploy.sh` их не меняет.

`fuel` ищет новые месяцы рядов из `data/fuel/_series.yaml` (BTS — стоимость
галлона у перевозчиков США; биржа ТС-1) и демпфер. Черновик
`fuel-ГГГГ-ММ-ДД.json` проверяется командой `fca master drafts`: число
с цитатой, скачок к прошлой точке и k к USGC. `--accept-fuel` дописывает
чистые и просмотренные точки в `data/fuel/`.

`night` собирает ночные ограничения: запрет, квоту или ночную надбавку и
часы по местному времени с цитатой. `fca master drafts` сверяет часы;
`--accept-night` пишет в `data/airports/_night.yaml`.

`prices` собирает каталог, цену сделки за борт, оценку рынка и ставку
лизинга раздельно, с цитатой и ссылкой. Начинает с лент новостей поиска
(RSS). `fca master drafts` сверяет число с цитатой и полосы правдоподобия;
`--accept-prices` пишет в `data/prices/_observations.yaml`, страница типа
рисует ряд. Для всех принятых изменений дальше — commit и deploy.

Расходы записываются в `/srv/fca/agent/ledger.jsonl`: одна строка на прогон.
OpenClaw сообщает стоимость основного диалога. До запуска записывается
резерв, после ответа он уточняется. При неизвестной полной стоимости
дальнейшие задания текущего запуска останавливаются.

У закреплённого OpenClaw есть ограничение: отдельный вызов модели внутри
инструмента `pdf` не входит в стоимость основного диалога. Поэтому после
использования `pdf` эта известная сумма сохраняется отдельно, а итог
помечается как оценка с консервативным резервом; текущая пачка заданий
останавливается. Сумму нужно сверить с Usage проекта OpenAI. Резерв не
является точным счётом и может отличаться от фактических затрат.

`FCA_AGENT_MONTH_USD=20` — локальная проверка перед следующим прогоном,
`FCA_AGENT_RUN_USD=2` — порог предупреждения и величина резерва, а не
остановка внутри API-вызова. Журнал сохраняется при переходе: расходы
прежнего провайдера за текущий месяц также учитываются в локальном бюджете.

В OpenAI отдельно настройте уведомления о расходах и, если доступен в
проекте, **Enforce a hard limit**. Уведомление само по себе запросы не
останавливает; жёсткий лимит блокирует новые обращения с `429`, но применяется
с задержкой, поэтому небольшое превышение возможно. Не подменяйте им
локальный учёт. Подробности —
[Spend limits](https://developers.openai.com/api/docs/guides/spend-limits).

### Хранение у провайдера

В закреплённом OpenClaw `2026.10.5` основной вызов Responses API к
`api.openai.com` принудительно использует `store: true`. При обычных
настройках OpenAI данные ответа сохраняются не менее 30 дней. Отдельно
действуют журналы проверки злоупотреблений: по умолчанию до 30 дней,
с исключениями, описанными провайдером. Отключённое обучение не означает
отсутствия хранения. Эта конфигурация не обещает Zero Data Retention;
одобрение и настройки такого режима на аккаунте отдельно не проверены.
Условия: [Data controls](https://developers.openai.com/api/docs/guides/your-data).

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

- `/ru/`, `/en/`, `/de/` — главная: обложка, три входа (типы ВС · расчёт · сеть), пример расчёта. `/` — та же
  главная на языке браузера (версия x-default); `/` с параметрами (`?o=…&ac=…`) и `/w#…` — сразу калькулятор.
- `/<язык>/calc` — калькулятор (витрина) с заголовком, связями языков (hreflang) и разметкой schema.org;
  `?mode=net` — маршрутная сеть.
- `/<язык>/about` — о сервисе и вопросы-ответы; `/<язык>/types` и `/<язык>/type/<ИКАО>` — страница каждого типа ВС
  (гражданские от 11 кресел): паспорт с источниками, схема, экономика на типовом маршруте из Франкфурта (Вена /
  Барселона / Пекин по классу, `seo.ROUTES`) и сравнение с классом. Расчёты страниц делает фоновый поток при
  запуске и раз в 6 часов (`Context.start_seo_econ`), около минуты.
- `/robots.txt`, `/sitemap.xml`, `/llms.txt` (описание для ИИ-ассистентов), `/og.png` (картинка для ссылок).
- Адрес сайта в ссылках — `FCA_SITE_URL`, по умолчанию `https://flightcost.app`.
- Калькулятор принимает маршрут и тип адресом: `/en/calc?o=EDDF&d=LEBL&ac=A320`.

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
