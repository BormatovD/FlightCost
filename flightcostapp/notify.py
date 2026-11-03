"""Сообщения владельцу через бота — общий почтовый ящик на диске.

Таймеры, агент и сбойные юниты не знают токена бота и не ходят в сеть:
они кладут JSON-файл в /srv/fca/spool, бот забирает его и отправляет в
чат владельца. Так у токена один владелец (пользователь fcabot), а
«сообщить» может любой процесс из группы fcaspool. Кнопок в ящике нет:
бот их не отправит, даже если они там окажутся.

    python -m flightcostapp.notify "текст"              # просто сообщение
    python -m flightcostapp.notify --unit fca-observe.service   # юнит упал
    python -m flightcostapp.notify --digest            # недельная сводка

Файл пишется во временное имя и переименовывается — бот не увидит
половину сообщения.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

SPOOL = Path(os.environ.get("FCA_SPOOL", "/srv/fca/spool"))
LEVELS = ("info", "warn", "alert")


def post(text: str, *, level: str = "info", attach: str | None = None,
         spool: Path | None = None) -> Path:
    d = Path(spool or SPOOL)
    d.mkdir(parents=True, exist_ok=True)
    msg = {"text": text, "level": level if level in LEVELS else "info",
           "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    if attach:
        msg["attach"] = str(attach)
    name = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}.json"
    tmp = d / f".{name}.tmp"
    old = os.umask(0o007)
    try:
        tmp.write_text(json.dumps(msg, ensure_ascii=False), "utf-8")
        tmp.replace(d / name)
    finally:
        os.umask(old)
    return d / name


def unit_failed(unit: str, lines: int = 15) -> str:
    try:
        log = subprocess.run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "cat"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:                                        # noqa: BLE001
        log = f"(журнал не прочитан: {e})"
    return f"⚠️ сбой: {unit}\n\n{log[-3000:]}"


def digest(site_db: str = "/srv/fca/site/data/flightcost.db",
           observe_db: str = "/srv/fca/observe/flightcost.db") -> str:
    """Неделя одним сообщением: посетители, протухшие источники, забор ADS-B."""
    from .refresh import load_registry
    from .store import Store
    from .validate import freshness_report
    from .visits import ALL, Visits, stats_path

    out = ["📊 Неделя FlightCost"]
    sp = stats_path(site_db)
    if sp.exists():
        rows = [r for r in Visits(sp).report(7) if r[1] == ALL]
        if rows:
            out.append("Посетители (суточные уникальные / просмотры):")
            out += [f"  {d}  {u:>4} / {v:>5}" for d, _, v, u in sorted(rows)]
            out.append(f"  итого просмотров {sum(r[2] for r in rows)}")
    if Path(site_db).exists():
        st = Store(site_db)
        bad = [r for r in freshness_report(st, load_registry()) if r["state"] != "fresh"]
        stale = [r for r in bad if r["state"] == "stale"]
        if stale:
            out.append(f"Протухли ({len(stale)}):")
            out += [f"  {r['source']}: {r['age_days']} сут. при сроке {r['sla']}"
                    + (f" — {r['why']}" if r.get("why") else "") for r in stale[:15]]
        else:
            out.append("Источники: все в сроке (кроме ни разу не загружавшихся на витрине).")
    if Path(observe_db).exists():
        import sqlite3
        db = sqlite3.connect(f"file:{observe_db}?mode=ro", uri=True)
        last = db.execute("SELECT MAX(observed_at) FROM observations WHERE kind = '_fetched'").fetchone()[0]
        n = db.execute("SELECT COUNT(*) FROM observations WHERE kind = 'frequency' "
                       "AND observed_at >= date('now', '-7 days')").fetchone()[0]
        out.append(f"ADS-B: последний забор {str(last or '—')[:16]}, рейсов за неделю {n}")
    # Каталоги главной базы витрине закрыты (группа fcaxfer) — о выгрузке
    # домой напоминает само обновление базы. Здесь — только если видно.
    try:
        from .master import DB as MASTER_DB, pull_age_days
        if MASTER_DB.exists():
            age = pull_age_days()
            out.append("Главная база: выгрузка домой " + ("не делалась ни разу" if age is None
                                                           else f"{age:.0f} сут. назад") + " (fca master pull)")
    except OSError:
        pass
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m flightcostapp.notify")
    p.add_argument("text", nargs="?")
    p.add_argument("--level", default="info", choices=LEVELS)
    p.add_argument("--unit", help="юнит systemd, который упал (для OnFailure=)")
    p.add_argument("--digest", action="store_true")
    p.add_argument("--attach")
    a = p.parse_args(argv)
    if a.unit:
        post(unit_failed(a.unit), level="alert")
    elif a.digest:
        post(digest())
    elif a.text:
        post(a.text, level=a.level, attach=a.attach)
    else:
        p.error("нужен текст, --unit или --digest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
