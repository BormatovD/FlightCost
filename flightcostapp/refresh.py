"""Конвейер обновления справочников.

    plan_due() -> fetch -> sha -> [не изменился? выход] -> parse
                -> gate -> commit | proposal -> mark_source

Три вещи, которые здесь важнее кода:

1. «Проверено» != «изменилось». Если хэш файла тот же — мы отмечаем
   last_checked и выходим, не тратя ни парсинг, ни токены. Для 3000
   аэропортов это разница между работающей схемой и счётом на сотни евро.

2. Ошибка загрузки НЕ обнуляет данные. Источник помечается status=error,
   старые значения продолжают действовать, но их возраст растёт и рано
   или поздно пробьёт SLA — и тогда модель начнёт кричать. Тихая
   деградация невозможна by design.

3. Всё, что не прошло гейт, оседает в proposals и ждёт человека.
   Агент имеет право предлагать, а не записывать.
"""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import yaml

from . import fx as _fx
from .store import Fact, Store
from .validate import GateResult, run_gate

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")


def load_registry(path: str | Path = REGISTRY_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def plan_due(registry: dict, store: Store, today: date | None = None,
             force: bool = False) -> list[str]:
    """Какие источники пора проверять."""
    today = today or date.today()
    due = []
    for sid, src in registry["sources"].items():
        if force:
            due.append(sid)
            continue
        st = store.source_state(sid)
        if st is None or not st["last_checked"]:
            due.append(sid)
            continue
        # Неудачная проверка тоже пишет last_checked. Если считать её
        # состоявшейся, источник с ошибкой не будет повторён до конца
        # периода — а у аэропортовых тарифов это 180 дней. Полгода тишины
        # вместо повторной попытки. Поэтому всё, что не завершилось
        # успехом, пробуется при каждом запуске.
        if st["status"] != "ok":
            due.append(sid)
            continue
        last = datetime.fromisoformat(st["last_checked"]).date()
        if (today - last).days >= src.get("cadence_days", 30):
            due.append(sid)
    return due


def next_due(registry: dict, store: Store, today: date | None = None) -> list[dict]:
    """Когда подойдёт срок у источников, которые сейчас не требуют проверки."""
    today = today or date.today()
    out = []
    for sid, src in registry["sources"].items():
        st = store.source_state(sid)
        if st is None or not st["last_checked"] or st["status"] != "ok":
            continue
        last = datetime.fromisoformat(st["last_checked"]).date()
        left = src.get("cadence_days", 30) - (today - last).days
        if left > 0:
            out.append({"source": sid, "days_left": left,
                        "message": st["message"] or ""})
    return sorted(out, key=lambda x: x["days_left"])


def _package_fetch(package: str) -> tuple[bytes, str]:
    """Источник, поставляемый через pip, а не по адресу.

    Артефактом служит версия пакета: сменилась — переразбор, не сменилась —
    пропуск. Тот же механизм сравнения по хэшу, что и для файлов, просто
    хэшируется строка версии, а не содержимое.
    """
    from importlib.metadata import version

    v = version(package)
    return f"{package}=={v}".encode(), "text/plain"


def _default_fetch(url: str, timeout: int = 60) -> tuple[bytes, str]:
    import requests

    r = requests.get(url, timeout=timeout, headers={"User-Agent": "flightcostapp/0.1"})
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "")


def _get_parser(name: str) -> Callable[[bytes, dict], list[Fact]]:
    mod = importlib.import_module(f".parsers.{name}", package=__package__)
    return getattr(mod, "parse")


def _candidate_urls(src: dict, today: date) -> list[str]:
    """Адреса-кандидаты, от самого свежего к более старому.

    Часть источников живёт по адресу с датой внутри. Жёсткая ссылка тут
    не годится: она перестанет работать через месяц, причём молча —
    источник встанет в error, а заметно это станет только когда пробьёт
    SLA. Но и одного текущего месяца мало: файл ставок за июль был
    опубликован третьего июля, то есть в первые дни месяца его по
    новому адресу ещё нет. Поэтому пробуем текущий месяц, затем
    откатываемся на несколько месяцев назад.
    """
    if src.get("url"):
        # Список адресов — не про даты, а про зеркала: у реестра бортов
        # OpenSky снимок лежит и на основном узле, и в хранилище образцов,
        # и какой из них жив сегодня, знать заранее нельзя. Первый
        # отдавшийся выигрывает; какой именно — попадает в отчёт.
        u = src["url"]
        return list(u) if isinstance(u, (list, tuple)) else [u]
    tpl = src.get("url_template")
    if not tpl:
        return []
    out, y, m = [], today.year, today.month
    for _ in range(1 + int(src.get("url_fallback_months", 1))):
        out.append(tpl.format(Y=f"{y:04d}", m=f"{m:02d}"))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def refresh_source(sid: str, registry: dict, store: Store, *,
                   fetch: Callable = _default_fetch,
                   today: date | None = None,
                   dry_run: bool = False,
                   reparse: bool = False) -> dict:
    src = registry["sources"][sid]
    report = {"source": sid, "title": src.get("title", sid), "outcome": None,
              "findings": [], "stats": {}}

    if src.get("kind") == "directory":
        # Источник — папка в data/, а не сеть. Нужен для тарифов яруса 1:
        # они собираются вручную и агентом, лежат локально и в репозиторий
        # не идут. Артефактом служит объединённое содержимое папки, поэтому
        # сравнение по хэшу работает как для одиночного файла.
        d = Path(src.get("path", ""))
        files = sorted(d.glob(src.get("glob", "*.json"))) if d.is_dir() else []
        if not files:
            store.mark_source(sid, status="todo",
                              message=f"папка {d} пуста или не найдена")
            report["outcome"] = "skipped:empty-directory"
            return report
        report["files"] = len(files)
        return _process_directory(sid, src, store, files, report,
                                  today or date.today(), dry_run, reparse)

    if src.get("kind") == "custom":
        # Источник наполняется не загрузкой, а собственным контуром: поток
        # ADS-B копится по расписанию снаружи и пишет не факты, а таблицу
        # наблюдений. Раньше такой источник проваливался в поиск адреса и
        # уходил в `skipped:no-url` — то есть выглядел ошибкой настройки, а
        # `mark_source` при этом не ставил `last_ok`, и трёхсуточный SLA не
        # мог сработать НИКОГДА. У единственного источника, где пропуск
        # невосстановим, тревога была нема.
        st = store.source_state(sid)
        never = st is None or not st["last_ok"]
        report["outcome"] = "external"
        report["note"] = ("наполняется своим контуром; свежесть считается по "
                          "отметкам этого контура")
        if never:
            report["note"] += " — ни одной отметки, контур не запускался"
        # Отметку ОБЯЗАТЕЛЬНО обновить, иначе в `fca status` навсегда
        # остаётся сообщение прошлой попытки: у наблюдений там висело
        # «skipped: no url in registry» уже после того, как ветка custom
        # заработала. Статус не `ok` намеренно — `last_ok` ставит только
        # сам накопитель, иначе трёхсуточный SLA снова станет немым.
        store.mark_source(
            sid, status="external",
            message=("контур не запускался ни разу" if never
                     else "наполняется своим контуром"))
        return report

    if src.get("kind") == "package":
        pkg = src.get("package") or src.get("parser", "").split("_")[0]
        try:
            blob, media = _package_fetch(pkg)
        except Exception as exc:                       # noqa: BLE001
            store.mark_source(sid, status="error", message=f"пакет {pkg}: {exc}")
            report["outcome"] = "error:package"
            return report
        urls = [f"pkg:{pkg}"]
        return _process(sid, src, store, blob, media, urls[0], report,
                        today or date.today(), dry_run, reparse)

    urls = _candidate_urls(src, today or date.today())
    if not urls:
        report["outcome"] = "skipped:no-url"   # напр. Tier-1 аэропорты — свой список
        store.mark_source(sid, status="skipped", message="no url in registry")
        return report

    # --- загрузка: перебираем кандидатов, пока один не отдастся ---
    blob = media = url = None
    errors = []
    for cand in urls:
        try:
            blob, media = fetch(cand)
            url = cand
            break
        except Exception as exc:                # noqa: BLE001
            errors.append(f"{cand.rsplit('/', 1)[-1]}: {type(exc).__name__}")
    if blob is None:
        store.mark_source(sid, status="error", message="; ".join(errors))
        report["outcome"] = "error:fetch"
        report["error"] = "; ".join(errors)
        return report
    if url != urls[0]:
        report["note"] = f"взят предыдущий месяц: {url.rsplit('/', 1)[-1]}"

    return _process(sid, src, store, blob, media, url, report,
                    today or date.today(), dry_run, reparse)


def _process_directory(sid, src, store, files, report, today, dry_run,
                       reparse=False):
    """Артефакт на ДОКУМЕНТ, а не на папку.

    Раньше считался один sha по склеенному блобу: правка одного файла
    меняла артефакт всем пятнадцати, и различить «тот же документ, другой
    разбор» от «другой документ» было нечем. А это ровно тот признак, по
    которому решается, аннулировать старые ключи или закрывать их датой
    редакции.
    """
    facts, per_file, fresh, rejected = [], [], [], []
    prefixes, annul = set(), set()
    # Курс кладётся в общий контекст сразу: `review.flag` без него не умеет
    # привести значение в евро, и абсолютный порог не проверяется ни у
    # одной строки в чужой валюте — пятьдесят четыре правила Гатвика в
    # фунтах, тенге в Алматы, риал в Дохе. Механизм честно писал «порог не
    # проверен», делал это на каждую строку, и читать перестали (решение 37).
    ctx_all: dict = {"dead_rules": [], "fx": _fx.make_fx(store, today)}
    for f in files:
        blob = f.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        seen = store.artifact_seen(sid, sha)
        store.put_artifact(sid, f"file:{f}", blob, "application/json")
        # `**src` кладёт в ctx всю запись реестра, в том числе ОБЪЯВЛЕННЫЙ
        # адрес. Парсеру нужен адрес РАЗОБРАННОГО артефакта, а он другой:
        # у источника с зеркалами объявлен список, а взят один из них, и
        # `note=ctx["url"]` назвал бы список целиком (а у SQLite нет типа
        # «список» — отсюда падение на привязке параметра).
        # Хранилище в контексте: часть парсеров разрешает коды через
        # указатель, и без него перечень в двух системах не свести. Даётся
        # ТОЛЬКО на чтение по смыслу — писать факты parser'у нечем, он их
        # возвращает.
        ctx = {"source_id": sid, "sha": sha, "today": today.isoformat(),
               **src, "url": f"file:{f}", "store": store}
        try:
            got = _get_parser(src["parser"])(blob, ctx)
        except Exception as exc:                       # noqa: BLE001
            rejected.append(f"{f.name}: {exc}")
            continue
        facts += got
        # Сводка парсера — в отчёт. Прежде `ctx["summary"]` не читал никто:
        # сверка сообщества, «найдено 33 типа» EASA, «без кода сообщества→ИКАО» уходили в
        # никуда, и парсер говорил сам с собой.
        report.setdefault("summary", []).extend(ctx.get("summary", []))
        prefixes |= set(ctx.get("parsed_prefixes", []))
        ctx_all.setdefault("next_edition", {}).update(ctx.get("next_edition", {}))
        # Тот же артефакт — значит изменился наш разбор, а не мир.
        (annul if seen else fresh).add(f.name) if False else None
        (annul.add(f.name) if seen else fresh.append(f.name))
        per_file.append({"file": f.name, "sha": sha[:12], "facts": len(got),
                         "unchanged_artifact": seen})
        rejected += [f"{f.name}: {m}" for m in ctx.get("rejected", [])]
    report["documents"] = per_file
    report["rejected"] = rejected
    if rejected:
        report.setdefault("findings", [])
    if not facts:
        store.mark_source(sid, status="error",
                          message=f"ни один документ не разобран из {len(files)}")
        report["outcome"] = "error:parse"
        return report
    if not fresh and not rejected and not reparse:
        # `--reparse` обязан пробивать и ЭТОТ короткий путь. Раньше он
        # действовал только на одиночный документ, а папка отвечала
        # «не изменилось» — то есть правка парсера или формы записи до
        # хранилища не доезжала, и понять это было нельзя: исход выглядел
        # успехом. Тот же дефект, что был у `--all`, только этажом ниже.
        store.mark_source(sid, status="ok", message="unchanged")
        report["outcome"] = "unchanged"
        return report

    prev_count = store.count_keys(src["domain"]) or None
    gate: GateResult = run_gate(facts, source=src, store=store,
                                prev_count=prev_count, ctx=ctx_all)
    # Отвергнутый документ — находка уровня error, а не строка в поле,
    # которое никто не печатает. Домодедово упал на опечатке в признаке
    # начисления, остальные шестнадцать прошли, и `refresh` показал
    # «proposal … ждёт приёмки» без единого слова о том, что одного
    # аэропорта в поставке нет. Ровно тот тихий отказ, против которого
    # решение 37: список `rejected` собирался с самого начала — и не
    # доезжал до экрана.
    from .validate import Finding
    gate.findings.extend(
        Finding("error", "parse.rejected", f"документ отвергнут: {m}")
        for m in rejected)
    report["findings"] = [asdict(x) for x in gate.findings]
    report["stats"] = gate.stats
    report["verdict"] = gate.verdict
    if dry_run:
        report["outcome"] = f"dry-run:{gate.verdict}"
        return report
    if gate.verdict == "reject":
        store.mark_source(sid, status="rejected",
                          message="; ".join(x.code for x in gate.errors))
        report["outcome"] = "rejected"
        return report
    if gate.verdict == "review":
        # Снятие с учёта — часть поставки, а не часть автоматического
        # пути. Приёмка человеком шла мимо `retire_missing`, и старые
        # ключи оставались открытыми рядом с новыми: на Франкфурте это
        # дало 8 307,92 вместо 5 971,40 — ровно двойной счёт, который мы
        # уже ловили при переходе на ключ по содержанию (решение 61).
        # У тарифов `gate: review` — путь по умолчанию, значит дефект
        # сидел именно там, где чаще всего ходят.
        pid = store.add_proposal(sid, {"facts": [asdict(x) for x in gate.facts],
                                       "findings": [asdict(x) for x in gate.findings],
                                       "retire": {"domain": src["domain"],
                                                  "prefixes": sorted(prefixes)}})
        # Предложение — НЕ успех. Факты в хранилище не попали, и данные
        # источника ровно так же стары, как после прошлой ПРИНЯТОЙ
        # поставки. Прежде здесь стоял `status="ok"`, и `last_ok` двигался
        # вперёд: источник, чья поставка месяц ждёт человека, выглядел
        # свежим. Тот же довод, по которому частичный успех успехом не
        # считается.
        store.mark_source(sid, status="proposal",
                          message=f"ждёт приёмки: fca review {pid}")
        report["outcome"] = "proposal"
        report["proposal_id"] = pid
        return report

    stats = store.commit_facts(gate.facts)
    # Снятие с учёта — только по полностью разобранным документам
    # (решение 63). Отвергнутый файл ничего не снимает.
    gone = store.retire_missing(src["domain"], sid, prefixes=prefixes,
                                keep={x.key for x in gate.facts}, as_of=None)
    stats["retired"] = len(gone)
    report["retired"] = gone[:20]
    # Частичный успех успехом не считается: источник, у которого треть
    # документов отвергнута, свежим быть не должен.
    ok = not rejected
    store.mark_source(sid, status="ok" if ok else "error",
                      message=(f"разобрано {len(per_file)} из {len(files)}"
                               + (f", снято {len(gone)}" if gone else "")
                               + ("" if ok else "; отвергнуты: "
                                  + "; ".join(r.split(":")[0] for r in rejected))),
                      changed=bool(stats["added"]))
    report["outcome"] = "committed" if ok else "committed:partial"
    report["stats"].update(stats)
    return report


def _process(sid, src, store, blob, media, url, report, today, dry_run,
             reparse=False):
    # Проверка ДО сохранения артефакта: иначе только что записанный файл
    # всегда выглядит "уже виденным" и источник навсегда застревает в unchanged.
    sha = hashlib.sha256(blob).hexdigest()
    prev = store.source_state(sid)
    # `--all` двигает РАСПИСАНИЕ, а не разбор: при совпавшем sha документ
    # не разбирается повторно, и правка парсера до хранилища не доезжает.
    # Это верно по умолчанию — незачем перемалывать тот же файл, — но
    # означает, что «переналить фактами полегче» одним `--all` нельзя.
    # Для этого `--reparse`: артефакт тот же, разбор другой.
    if (store.artifact_seen(sid, sha) and prev and prev["status"] == "ok"
            and not reparse):
        store.mark_source(sid, status="ok", message="unchanged")
        report["outcome"] = "unchanged"
        report["sha"] = sha[:16]
        return report

    store.put_artifact(sid, url, blob, media)

    # --- парсинг ---
    try:
        # Адрес разобранного артефакта, а не объявленный в реестре: у
        # источника с зеркалами это разные вещи, и провенанс должен
        # называть тот, который реально отдался.
        ctx = {"source_id": sid, "sha": sha, "today": today.isoformat(),
               **src, "url": url, "store": store}
        facts = _get_parser(src["parser"])(blob, ctx)
        report.setdefault("summary", []).extend(ctx.get("summary", []))
    except NotImplementedError as exc:
        # Заглушка — это известный пробел, а не отказ. Смешивать их нельзя:
        # в списке из пяти строк настоящая поломка тонет среди ненаписанного,
        # и глаз перестаёт различать, что чинить, а что просто не сделано.
        store.mark_source(sid, status="todo", message=str(exc) or "парсер не написан")
        report["outcome"] = "skipped:not-implemented"
        return report
    except Exception as exc:                    # noqa: BLE001
        store.mark_source(sid, status="error", message=f"parse: {exc}")
        report["outcome"] = "error:parse"
        report["error"] = str(exc)
        return report

    prev_count = store.count_keys(src["domain"]) or None
    gate: GateResult = run_gate(facts, source=src, store=store,
                                prev_count=prev_count,
                                ctx={"fx": _fx.make_fx(store, today)})
    report["findings"] = [asdict(f) for f in gate.findings]
    report["stats"] = gate.stats
    report["verdict"] = gate.verdict

    if dry_run:
        report["outcome"] = f"dry-run:{gate.verdict}"
        return report

    if gate.verdict == "reject":
        store.mark_source(sid, status="rejected",
                          message="; ".join(f.code for f in gate.errors))
        report["outcome"] = "rejected"
        return report

    if gate.verdict == "review":
        pid = store.add_proposal(sid, {
            "facts": [asdict(f) for f in gate.facts],
            "findings": [asdict(f) for f in gate.findings],
            "artifact_sha": sha,
        })
        # Предложение — НЕ успех. Факты в хранилище не попали, и данные
        # источника ровно так же стары, как после прошлой ПРИНЯТОЙ
        # поставки. Прежде здесь стоял `status="ok"`, и `last_ok` двигался
        # вперёд: источник, чья поставка месяц ждёт человека, выглядел
        # свежим. Тот же довод, по которому частичный успех успехом не
        # считается.
        store.mark_source(sid, status="proposal",
                          message=f"ждёт приёмки: fca review {pid}")
        report["outcome"] = "proposal"
        report["proposal_id"] = pid
        return report

    stats = store.commit_facts(gate.facts)
    store.mark_source(sid, status="ok", message="auto-committed",
                      changed=bool(stats["added"]))
    report["outcome"] = "committed"
    report["stats"].update(stats)
    return report


def refresh_all(registry: dict, store: Store, *, force: bool = False,
                dry_run: bool = False, only: list[str] | None = None,
                reparse: bool = False) -> list[dict]:
    ids = only or plan_due(registry, store, force=force)
    return [refresh_source(sid, registry, store, dry_run=dry_run,
                           reparse=reparse) for sid in ids]
