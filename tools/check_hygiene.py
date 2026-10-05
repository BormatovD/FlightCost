#!/usr/bin/env python3
"""Проверка репозитория перед публикацией.

Три вопроса, на которые ответ должен быть «нет»:

  1. Отслеживает ли git то, что по `.gitignore` в репозитории быть не
     должно? `.gitignore` не действует на файлы, уже взятые под контроль:
     база, добавленная в коммит месяц назад, уедет на GitHub и с новым
     `.gitignore`.
  2. Был ли в ИСТОРИИ хоть раз ключ — агрегатора цен, OpenSky, любой
     токен в коде? Удалённый из рабочей копии ключ остаётся во всех
     прошлых коммитах. Если найден — ключ перевыпустить у сервиса; чистить
     историю бесполезно, её уже могли скачать.
  3. Нет ли больших файлов, похожих на данные?

    python3 tools/check_hygiene.py

Код возврата 1, если хоть одна проверка нашла что-то.
"""

from __future__ import annotations

import re
import subprocess
import sys

SECRET = [
    (r"TP_TOKEN\s*[=:]\s*['\"]?[0-9a-f]{20,}", "ключ Travelpayouts"),
    (r"X-Access-Token['\"]?\s*[:=]\s*['\"][0-9a-f]{20,}", "ключ Travelpayouts в заголовке"),
    (r"OPENSKY_CLIENT_SECRET\s*[=:]\s*['\"]?[^\s'\"$]{8,}", "секрет OpenSky"),
    (r"client_secret['\"]?\s*[:=]\s*['\"][^'\"$]{8,}['\"]", "client_secret"),
    (r"(?i)(api[_-]?key|token|secret)['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]",
     "похоже на ключ в коде"),
]
TRACKED_BAD = [
    (r"^data/flightcost\.db", "хранилище"),
    (r"^data/(raw|artifacts|geo)/", "чужие данные или кэш рецепта"),
    (r"^data/codes/(?!(airports_list\.xlsx|tkp_codes\.yaml)$)",
     "указатель кодов: CC BY-SA, только рецептом"),
    (r"^data/aircraft/user/", "свои типы владельца"),
    (r"^data/tkp/.*\.xlsx$", "сырая выгрузка сообщества — в репозиторий только упаковка: fca tkp-pack"),
    (r"^flight_data/|(^|/)routes\.xlsx$", "сбор цен"),
    (r"\.bak$|(^|/)\.env$", "резервная копия или окружение"),
    (r"^docs/(?!example-).*\.html$", "порождаемый разбор"),
]
BIG = 1_000_000
# Большие файлы, которые лежат в репозитории НАМЕРЕННО, — с причиной.
# Проверка, которая на каждом выпуске краснеет по известной причине, через
# месяц перестаёт читаться (решение 96): известное объявляется, новое ловится.
BIG_ALLOWED = [
    (r"^tests/fixtures/", "фикстура теста"),
]


def git(*args) -> str:
    # Не `text=True`: в репозитории бывают текстовые файлы не в UTF-8 —
    # немецкий документ в Windows-1252, CSV из Excel, — и строгое чтение
    # роняло проверку на первом же «ü». Ключи ищутся латиницей, поэтому
    # непонятный байт заменяется и чтение идёт дальше.
    out = subprocess.run(["git", *args], capture_output=True, check=True).stdout
    return out.decode("utf-8", errors="replace")


def main() -> int:
    try:
        git("rev-parse", "--git-dir")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("здесь нет репозитория git — проверять нечего")
        return 0
    bad = 0

    files = [f for f in git("ls-files", "-z").split("\0") if f]
    if not files:
        # «Проверено и чисто» и «проверять было нечего» — разные ответы
        # (решение 37). Пустой индекс — второй, и зелёным он быть не должен.
        print("не проверено: git не отслеживает ни одного файла — сначала  git add .")
        return 1
    print(f"== 1. отслеживаемые файлы, которым не место в репозитории ({len(files)} всего)")
    for rx, why in TRACKED_BAD:
        hit = [f for f in files if re.search(rx, f)]
        for f in hit[:10]:
            print(f"   {f}  — {why}")
        if len(hit) > 10:
            print(f"   …и ещё {len(hit) - 10}")
        bad += len(hit)
    if not bad:
        print("   чисто")
    else:
        print("   снять с контроля, не удаляя с диска:  git rm --cached -r <путь>")

    # До первого коммита истории нет — проверяется то, что ПОДГОТОВЛЕНО к
    # коммиту (`git add`). Это тот самый момент, когда ключ ещё можно не
    # выпустить: после push он раскрыт навсегда.
    try:
        git("rev-parse", "--verify", "HEAD")
        print("== 2. ключи во всей истории коммитов")
        log = git("log", "-p", "--all", "--no-color", "--format=@@COMMIT %h %ad",
                  "--date=short")
    except subprocess.CalledProcessError:
        print("== 2. ключи в подготовленном к первому коммиту (истории ещё нет)")
        log = "@@COMMIT подготовлено\n" + git("diff", "--cached", "--no-color")
    found, commit = [], ""
    for line in log.splitlines():
        if line.startswith("@@COMMIT "):
            commit = line[9:]
            continue
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        for rx, why in SECRET:
            if re.search(rx, line):
                found.append((commit, why, line[:110]))
    for commit, why, line in found[:15]:
        print(f"   {commit}  {why}:  {line}")
    if found:
        print("   в истории: ключ считается раскрытым — перевыпустить у сервиса;"
              "\n   в подготовленном: убрать из файла в переменную окружения до коммита")
        bad += len(found)
    else:
        print("   чисто")

    print("== 3. большие отслеживаемые файлы")
    # `-z`: пути как есть, без экранирования кириллицы в \320\222…
    out = git("ls-files", "-s", "-z")
    big = []
    for row in filter(None, out.split("\0")):
        sha, path = row.split()[1], row.split("\t", 1)[1]
        size = int(git("cat-file", "-s", sha).strip())
        if size > BIG:
            why = next((w for rx, w in BIG_ALLOWED if re.search(rx, path)), None)
            big.append((size, path, why))
    for size, path, why in sorted(big, reverse=True)[:10]:
        print(f"   {size / 1e6:6.1f} МБ  {path}" + (f"  — объявлен: {why}" if why else ""))
    unknown = [b for b in big if not b[2]]
    if unknown:
        bad += len(unknown)
    elif not big:
        print("   чисто")

    print("\nИТОГ:", "готово к публикации" if not bad else f"найдено {bad} — разобрать до push")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
