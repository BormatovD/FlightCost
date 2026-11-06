"""Главный справочник на сервере (решение владельца 03.11.2026).

Где что живёт:

* **Сервер** — главная база `/srv/fca/master/flightcost.db` (владелец
  fcabot). Её обновляют таймер (`refresh`: источники из интернета и
  данные из репозитория) и приёмка кнопками в боте. Витрина получает
  урезанный снимок локально (`snapshot` → fca-swap.path → подмена).
* **Компьютер владельца** — обязательная копия (`pull`) и всё, что на
  сервер не уходит: сырые выгрузки (`data/raw`), подписные и
  лицензионные файлы, свои типы ВС (`aircraft_user`). Источники с
  такими файлами разбираются дома, на сервер уходят только факты —
  предложением в очередь приёмки (`send`).

Команды с компьютера (через `fca master …`):

    fca master push            # один раз: засеять сервер своей базой
    fca master send --only eurostat_par,form41
    fca master pull            # забрать главную базу домой (обязательно, см. PULL_WARN_DAYS)

На сервере (юниты systemd, пользователь fcabot):

    python -m flightcostapp.master import     # посев и присланное с компьютера
    python -m flightcostapp.master refresh    # ежесуточно и после выкладки кода
    python -m flightcostapp.master snapshot   # снимок для витрины и копия для pull
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import notify

ROOT = Path(__file__).resolve().parents[1]
SRV = Path(os.environ.get("FCA_SRV", "/srv/fca"))
MASTER = SRV / "master"
DB = MASTER / "flightcost.db"
DROP = SRV / "drop"
PULLS = SRV / "pulls"
PULL_WARN_DAYS, PULL_ALERT_DAYS = 7, 14
KEEP_BACKUPS = 7

# Источники, у которых сырьё живёт только у владельца. Сервер их не
# обновляет (файлов там нет и не будет), их факты приходят `send`.
HOME_ONLY = {"aircraft_user", "form41", "eurostat_par", "t100", "ru_pairs",
             "adsb_flights", "market_fare", "observation", "db1c_market"}
# Источник в реестре и метка, под которой его факты лежат в базе, не всегда
# совпадают: свёртка наблюдений ADS-B (`fca observe --aggregate`) пишет
# факты с source_id «observation», а в реестре источник — adsb_flights.
# `send` по имени из реестра забирает и такие факты; сервер их принимает.
SEND_ALIASES = {"adsb_flights": ("adsb_flights", "observation")}
EXTRA_SOURCES = {"observation"}
# Чего нет в главной базе вовсе: свои сценарии владельца. `send` их не
# отправляет, `push` вырезает, `pull` восстанавливает из локальных файлов.
NEVER_SEND = {"aircraft_user"}
# Таблицы, которые при посеве не едут: сырые наблюдения (у сервера своя
# база забора), ссылки на локальные файлы, старая очередь.
SEED_CLEAR = ("observations", "artifacts", "proposals")
# То, что при `pull` остаётся от прежней домашней базы.
PULL_KEEP_TABLES = ("observations", "artifacts")


def _now():
    return datetime.now(timezone.utc)


def _integrity(path: Path) -> str:
    db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        return db.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        db.close()


def _backup(src: Path, dst: Path) -> None:
    """Согласованная копия SQLite (не копирование файла посреди записи)."""
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    s.backup(d)
    d.close()
    s.close()


# ── компьютер владельца ──────────────────────────────────────────────────
def _host(a) -> str:
    h = a.host or os.environ.get("FCA_DEPLOY_HOST")
    if not h:
        sys.exit("не задан сервер: --host deploy@адрес или переменная FCA_DEPLOY_HOST")
    return h


RSYNC_PERMS = ("--no-perms", "--no-group", "--no-owner", "--chmod=F660")


def _sh(cmd: list[str]) -> int:
    print("  $", " ".join(cmd))
    return subprocess.run(cmd).returncode


def make_seed(home_db: Path, out: Path) -> dict:
    """Копия домашней базы без своего (NEVER_SEND) и без SEED_CLEAR."""
    _backup(home_db, out)
    db = sqlite3.connect(str(out))
    gone = {}
    for sid in NEVER_SEND:
        gone[f"источник {sid}"] = db.execute("DELETE FROM facts WHERE source_id = ?", (sid,)).rowcount
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in SEED_CLEAR:
        if t in tables:
            gone[f"таблица {t}"] = db.execute(f"DELETE FROM {t}").rowcount
    db.commit()
    db.execute("VACUUM")
    db.close()
    return gone


def cmd_push(a) -> int:
    host = _host(a)
    if subprocess.run(["ssh", host, f"test -e {DB}"]).returncode == 0:
        print("на сервере главная база уже есть — посев не нужен (и затёр бы принятое там).")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="fca-seed-")) / "seed.db"
    gone = make_seed(Path(a.db), tmp)
    print(f"посев: {tmp.stat().st_size / 1e6:.1f} МБ")
    for k, n in gone.items():
        print(f"  не едет {k}: {n}")
    if _sh(["rsync", "-z", "--partial", *RSYNC_PERMS, str(tmp), f"{host}:{DROP}/.seed.db"]) or \
       _sh(["ssh", host, f"mv -f {DROP}/.seed.db {DROP}/seed.db && "
                         "sudo /usr/bin/systemctl start fca-master-import.service"]):
        print("не отправилось — проверьте ssh и bootstrap (каталог /srv/fca/drop)")
        return 2
    print("готово: сервер принял базу; дальше — fca master pull перед работой дома")
    return 0


def proposals_from(home_db: Path, sources: list[str]) -> list[dict]:
    """Действующие факты источников — по предложению на (источник, домен)."""
    from .store import Fact
    db = sqlite3.connect(f"file:{Path(home_db).resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    fields = set(Fact.__dataclass_fields__)
    out = []
    for sid in sources:
        rows = db.execute("SELECT * FROM facts WHERE source_id = ? AND valid_to IS NULL", (sid,)).fetchall()
        by_dom: dict[str, list] = {}
        for r in rows:
            by_dom.setdefault(r["domain"], []).append({k: r[k] for k in r.keys() if k in fields})
        for dom, facts in by_dom.items():
            out.append({"source_id": sid, "origin": "computer",
                        "sent_at": _now().isoformat(timespec="seconds"),
                        "facts": facts,
                        "retire": {"domain": dom,
                                   "prefixes": sorted({f["key"].split("/")[0] for f in facts})}})
    db.close()
    return out


def cmd_send(a) -> int:
    host = _host(a)
    want = [s.strip() for s in a.only.split(",") if s.strip()]
    bad = [s for s in want if s in NEVER_SEND]
    if bad:
        print(f"не отправляю {', '.join(bad)}: свои сценарии владельца на сервер не уходят")
        return 2
    props = proposals_from(Path(a.db), [x for w in want for x in SEND_ALIASES.get(w, (w,))])
    if not props:
        print("действующих фактов у этих источников нет — нечего отправлять")
        return 2
    d = Path(tempfile.mkdtemp(prefix="fca-send-"))
    for i, p in enumerate(props):
        f = d / f"{_now():%Y%m%d%H%M%S}-{p['source_id']}-{i}.json"
        f.write_text(json.dumps(p, ensure_ascii=False, default=str), "utf-8")
        print(f"  {p['source_id']} / {p['retire']['domain']}: фактов {len(p['facts'])}")
    # Файлами, а не каталогом: `rsync -a src/ dst/` переносит и права самого
    # каталога — временный каталог 700, и drop/proposals становился 700, после
    # чего приём от fcabot его не видел (04.11.2026). Группу и права ставит
    # каталог на сервере (setgid fcaxfer), а не наш компьютер.
    files = sorted(str(f) for f in d.glob("*.json"))
    if _sh(["rsync", "-z", "--partial", *RSYNC_PERMS, *files, f"{host}:{DROP}/proposals/"]) or \
       _sh(["ssh", host, "sudo /usr/bin/systemctl start fca-master-import.service"]):
        print("не отправилось")
        return 2
    print("в очереди приёмки на сервере — принять в боте (/queue)")
    return 0


def merge_home_tables(new_db: Path, old_db: Path) -> dict:
    """Перенести в свежую копию то, что есть только дома."""
    if not old_db.exists():
        return {}
    # URI в ATTACH работает, только если само соединение открыто с uri=True:
    # на Linux сборка sqlite часто разрешает URI по умолчанию, на macOS — нет
    # (там это и упало). Путь — абсолютный, иначе URI его не найдёт.
    db = sqlite3.connect(f"file:{Path(new_db).resolve()}", uri=True)
    db.execute("ATTACH DATABASE ? AS old", (f"file:{Path(old_db).resolve()}?mode=ro",))
    kept = {}
    for t in PULL_KEEP_TABLES:
        have = db.execute("SELECT name FROM old.sqlite_master WHERE type='table' AND name = ?", (t,)).fetchone()
        if have:
            db.execute(f"CREATE TABLE IF NOT EXISTS main.{t} AS SELECT * FROM old.{t} WHERE 0")
            kept[t] = db.execute(f"INSERT OR IGNORE INTO main.{t} SELECT * FROM old.{t}").rowcount
    # Свои типы ВС — ровно те строки, что были приняты дома. Перечитывать их
    # из файлов (`fca refresh`) нельзя: у источника gate: review, и каждый
    # pull ставил бы их заново в очередь приёмки.
    cols = [r[1] for r in db.execute("PRAGMA main.table_info(facts)") if r[1] != "id"]
    old_cols = {r[1] for r in db.execute("PRAGMA old.table_info(facts)")}
    cols = [c for c in cols if c in old_cols]
    for sid in sorted(NEVER_SEND):
        db.execute("DELETE FROM main.facts WHERE source_id = ?", (sid,))
        kept[f"источник {sid}"] = db.execute(
            f"INSERT INTO main.facts ({', '.join(cols)}) SELECT {', '.join(cols)} FROM old.facts "
            f"WHERE source_id = ?", (sid,)).rowcount
        st = db.execute("SELECT * FROM old.source_state WHERE source_id = ?", (sid,)).fetchone()
        if st:
            db.execute("INSERT OR REPLACE INTO main.source_state SELECT * FROM old.source_state "
                       "WHERE source_id = ?", (sid,))
    db.commit()
    db.execute("DETACH DATABASE old")
    db.close()
    return kept


def home_only_losses(home: Path, pulled: Path) -> list[str]:
    """Что пропадёт дома при замене базы: свежее, чем в главной, у домашних
    источников, и предложения, ждущие приёмки дома."""
    if not home.exists():
        return []
    q = ("SELECT COUNT(*), MAX(created_at) FROM facts WHERE source_id = ? AND valid_to IS NULL")
    h = sqlite3.connect(f"file:{Path(home).resolve()}?mode=ro", uri=True)
    p = sqlite3.connect(f"file:{Path(pulled).resolve()}?mode=ro", uri=True)
    out = []
    try:
        for sid in sorted(HOME_ONLY - NEVER_SEND):
            hn, ht = h.execute(q, (sid,)).fetchone()
            pn, pt = p.execute(q, (sid,)).fetchone()
            if hn and (hn > (pn or 0) or (ht or "") > (pt or "")):
                out.append(f"{sid}: дома {hn} фактов, новее главной базы (там {pn}) — fca master send --only {sid}")
        try:
            n = h.execute("SELECT COUNT(*) FROM proposals WHERE status = 'pending'").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        if n:
            out.append(f"дома ждут приёмки предложений: {n} — fca review, затем fca master send")
    finally:
        h.close()
        p.close()
    return out


def cmd_pull(a) -> int:
    host = _host(a)
    home = Path(a.db)
    tmp = home.with_name(home.name + ".pulled")
    if _sh(["rsync", "-az", f"{host}:{MASTER}/export/flightcost.db", str(tmp)]):
        print("не скачалось: есть ли на сервере главная база (fca master push) и её копия (snapshot)?")
        return 2
    ok = _integrity(tmp)
    if ok != "ok":
        print(f"копия повреждена: {ok} — домашняя база не тронута")
        return 2
    losses = home_only_losses(home, tmp)
    if losses and not a.force:
        print("домашняя база не заменена — пропало бы то, чего нет на сервере:")
        for line in losses:
            print("  " + line)
        print("отправьте это (или повторите с --force, если оно не нужно)")
        tmp.unlink(missing_ok=True)
        return 2
    kept = merge_home_tables(tmp, home)
    if home.exists():
        bak = home.with_name(f"{home.name}.bak-{_now():%Y%m%d-%H%M}")
        _backup(home, bak)
        olds = sorted(home.parent.glob(f"{home.name}.bak-*"))
        for o in olds[:-3]:
            o.unlink()
        print(f"  прежняя база: {bak.name}")
    for ext in ("-wal", "-shm"):
        Path(str(home) + ext).unlink(missing_ok=True)
    tmp.replace(home)
    for t, n in kept.items():
        print(f"  сохранено из домашней: {t} — {n} строк")
    # Свои типы — из своих файлов: в главной базе их нет по построению.
    subprocess.run(["ssh", host, f"date -u +%Y-%m-%dT%H:%M:%SZ > {PULLS}/last"])
    print("главная база дома")
    return 0


# ── сервер ───────────────────────────────────────────────────────────────
def ensure_tree(master: Path = MASTER, app: Path = ROOT) -> None:
    """Рабочий каталог refresh: data/* — ссылки на репозиторий, своё — raw.

    Пути источников относительные (`data/charges`), а код принадлежит
    deploy и только читается. Поэтому refresh идёт из MASTER, где каждый
    подкаталог data/ — ссылка в репозиторий, кроме сырья и артефактов.
    """
    data = master / "data"
    data.mkdir(parents=True, exist_ok=True)
    for own in ("raw", "artifacts"):
        (data / own).mkdir(exist_ok=True)
    for src in (app / "data").iterdir():
        if src.name in ("raw", "artifacts") or src.suffix == ".db" or src.name.endswith((".db-wal", ".db-shm")):
            continue
        link = data / src.name
        if not link.is_symlink() and not link.exists():
            link.symlink_to(src)
    cfg = master / "config"
    if not cfg.exists():
        cfg.symlink_to(app / "config")


def snapshot(master: Path = MASTER) -> str:
    """Снимок витрине (через fca-swap.path) и копия для `pull`."""
    import fcntl
    from .cli import build_snapshot
    from .store import Store
    out, exp = master / "out", master / "export"
    out.mkdir(exist_ok=True)
    exp.mkdir(exist_ok=True)
    # Снимок собирают три юнита (обновление, приём, бот после приёмки).
    # Без замка два прогона делили одно временное имя, и подмене мог уйти
    # недочищенный файл — со всем, что вырезать обязательно.
    with open(master / ".snapshot.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fd, name = tempfile.mkstemp(prefix=".snapshot-", suffix=".db", dir=out)
        os.close(fd)
        tmp = Path(name)
        try:
            tmp.unlink()                       # sqlite создаст файл сам
            facts, _gone = build_snapshot(Store(master / "flightcost.db"), tmp)
            os.chmod(tmp, 0o600)
            tmp.replace(out / "flightcost.db.new")
            fd, ename = tempfile.mkstemp(prefix=".export-", suffix=".db", dir=exp)
            os.close(fd)
            etmp = Path(ename)
            _backup(master / "flightcost.db", etmp)
            os.chmod(etmp, 0o640)
            etmp.replace(exp / "flightcost.db")
        finally:
            tmp.unlink(missing_ok=True)
    return f"снимок витрине: действующих фактов {facts}"


def rolling_backup(master: Path = MASTER) -> None:
    b = master / "backup"
    b.mkdir(exist_ok=True)
    dst = b / f"flightcost-{_now():%Y%m%d}.db"
    if not dst.exists():
        _backup(master / "flightcost.db", dst)
        os.chmod(dst, 0o600)
    for old in sorted(b.glob("flightcost-*.db"))[:-KEEP_BACKUPS]:
        old.unlink()


def pull_age_days(pulls: Path = PULLS) -> float | None:
    f = pulls / "last"
    if not f.exists():
        return None
    try:
        t = datetime.fromisoformat(f.read_text().strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (_now() - t).total_seconds() / 86400


def cmd_import(a, *, master: Path = MASTER, drop: Path = DROP, spool=None) -> int:
    say = lambda t, lvl="info": notify.post(t, level=lvl, spool=spool)   # noqa: E731
    db = master / "flightcost.db"
    seed = drop / "seed.db"
    if seed.exists():
        if db.exists():
            seed.replace(drop / f"seed.rejected-{_now():%Y%m%d%H%M%S}.db")
            say("Посев отклонён: главная база на сервере уже есть.", "warn")
        else:
            ok = _integrity(seed)
            if ok != "ok":
                seed.replace(drop / "seed.bad.db")
                say(f"Посев повреждён ({ok}) — главная база не создана.", "alert")
                return 1
            tmp = master / ".seed.db"
            shutil.copyfile(seed, tmp)
            con = sqlite3.connect(str(tmp))       # ещё раз — на случай старого клиента
            for sid in NEVER_SEND:
                con.execute("DELETE FROM facts WHERE source_id = ?", (sid,))
            con.commit()
            con.close()
            os.chmod(tmp, 0o600)
            tmp.replace(db)
            seed.unlink()
            say("Главная база на сервере создана. Дальше: fca master pull — копия домой.")
            snapshot(master)
    if not db.exists():
        return 0
    from .refresh import load_registry
    from .store import Store
    known = set(load_registry()["sources"]) | EXTRA_SOURCES
    st = Store(db)
    pdir = drop / "proposals"
    if pdir.exists() and not os.access(pdir, os.R_OK | os.X_OK):
        # Молча не видеть присланное хуже всего: «в очереди на сервере», а
        # очередь пуста. Сказать, что каталог закрыт, и как открыть.
        say(f"Приём с компьютера: каталог {pdir} закрыт для fcabot (права {oct(pdir.stat().st_mode)[-4:]}). "
            f"На сервере от root: chmod 2770 {pdir}; chgrp -R fcaxfer {pdir}", "alert")
        return 1
    for f in sorted(pdir.glob("*.json")):
        try:
            p = json.loads(f.read_text("utf-8"))
            sid = p.pop("source_id")
            if sid not in known or sid in NEVER_SEND or not isinstance(p.get("facts"), list):
                raise ValueError(f"источник {sid!r} не принимается")
            from .store import Fact
            [Fact(**x) for x in p["facts"][:5]]          # форма фактов — до очереди
            pid = st.add_proposal(sid, p)
            say(f"С компьютера: {sid}, фактов {len(p['facts'])} — предложение #{pid}. /queue")
        except Exception as e:                                     # noqa: BLE001
            say(f"С компьютера пришло негодное предложение {f.name}: {e}", "warn")
        f.unlink()
    return 0


def cmd_refresh(a, *, master: Path = MASTER, spool=None) -> int:
    say = lambda t, lvl="info": notify.post(t, level=lvl, spool=spool)   # noqa: E731
    db = master / "flightcost.db"
    if not db.exists():
        return 0
    ensure_tree(master)
    from .refresh import load_registry, plan_due
    from .store import Store
    reg = load_registry()
    st = Store(db)
    before = {r["id"] for r in st.pending_proposals()}
    directory = [s for s, v in reg["sources"].items() if v.get("kind") == "directory"]
    todo = sorted((set(plan_due(reg, st)) | set(directory)) - HOME_ONLY)
    st.db.close()
    fca = Path(sys.executable).with_name("fca")
    r = subprocess.run([str(fca), "--db", str(db), "refresh", "--only", *todo, "--json"],
                       cwd=str(master), capture_output=True, text=True, timeout=7000)
    try:
        reports = json.loads(r.stdout or "[]")
    except ValueError:
        reports = []
        say(f"refresh на сервере: вывод не разобран (код {r.returncode})\n{r.stderr[-1500:]}", "alert")
    changed = [x for x in reports if str(x.get("outcome", "")).startswith("committed")]
    errors = [x for x in reports if str(x.get("outcome", "")).startswith("error")]
    st = Store(db)
    new = [p for p in st.pending_proposals() if p["id"] not in before]
    lines = []
    if changed:
        lines.append("обновлено: " + ", ".join(x["source"] for x in changed))
    if new:
        lines.append("ждут приёмки: " + ", ".join(f"#{p['id']} {p['source_id']}" for p in new) + " — /queue")
    if errors:
        lines.append("ошибки: " + ", ".join(f"{x['source']} ({x['outcome']})" for x in errors))
    # Ряды страницы «План и показатели», у которых нет своей истории (доля
    # заготовки эталонов, медианы сборов по регионам): пишутся, только если
    # значение сдвинулось. Сбой здесь не мешает обновлению справочника.
    recorded = 0
    try:
        from .monitor import record
        recorded = record(st)
    except Exception as exc:                                   # noqa: BLE001
        lines.append(f"ряды мониторинга не записаны: {type(exc).__name__}: {exc}")
    if changed or recorded:
        lines.append(snapshot(master))
    if lines:
        say("Справочник на сервере\n" + "\n".join(lines), "warn" if errors else "info")
    rolling_backup(master)
    age = pull_age_days()
    if age is None or age > PULL_WARN_DAYS:
        say(("Главная база ни разу не выгружалась домой." if age is None else
             f"Главная база не выгружалась домой {age:.0f} сут.") + " Выполните: fca master pull",
            "alert" if age is None or age > PULL_ALERT_DAYS else "warn")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fca master")
    p.add_argument("--db", default="data/flightcost.db")
    p.add_argument("--host", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push", help="один раз: засеять сервер домашней базой")
    s = sub.add_parser("send", help="факты источников с домашним сырьём — в очередь сервера")
    s.add_argument("--only", required=True, help="источники через запятую")
    pl = sub.add_parser("pull", help="главную базу — домой (обязательно раз в неделю)")
    pl.add_argument("--force", action="store_true", help="заменить, даже если дома есть неотправленное")
    sub.add_parser("import", help="сервер: посев и присланное с компьютера")
    sub.add_parser("refresh", help="сервер: обновить главную базу")
    sub.add_parser("snapshot", help="сервер: снимок витрине и копия для pull")
    a = p.parse_args(argv)
    if a.cmd == "snapshot":
        print(snapshot())
        return 0
    return {"push": cmd_push, "send": cmd_send, "pull": cmd_pull,
            "import": cmd_import, "refresh": cmd_refresh}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
