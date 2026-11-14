"""Сборка сети в отдельных процессах — по ядру на сборку (О2, 04.11.2026).

Расчёт сети — чистый Python, и потоки витрины делят одну блокировку
интерпретатора: две сборки шли на одном ядре, а остальные ядра простаивали.
Здесь сборка уходит в постоянный пул процессов, каждый — своё ядро.

Что живёт в процессе пула:
  * своё соединение с базой (открывается заново, если снимок подменили —
    по времени изменения файла);
  * свой кэш плеч и обходов — но общий кэш живёт в витрине: она передаёт
    процессу уже посчитанные плечи этих аэропортов, а процесс возвращает
    новые. Добавленный к сети седьмой аэропорт — только его плечи, в каком
    бы процессе ни считался.

Ход («пар посчитано») процесс шлёт через очередь; витрина разбирает её
одним потоком и раскладывает по заданиям.

Пул выключается переменной FCA_NET_PROCS=0 — тогда сборка идёт потоком,
как раньше. По умолчанию процессов — ядер минус одно (рядом на сервере
игра), но не больше четырёх и не меньше одного.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

LEG_CACHE_MAX = 4000

_state: dict = {}            # внутри процесса пула: база, кэши, очередь хода


def default_procs() -> int:
    raw = os.environ.get("FCA_NET_PROCS")
    if raw is not None and raw.strip() != "":
        try:
            return max(0, int(raw))
        except ValueError:
            return 0
    return max(1, min(4, (os.cpu_count() or 2) - 1))


def _init(progress_q) -> None:
    _state.clear()
    _state.update(q=progress_q, store=None, store_key=None, legs={}, detours={})


def _store(path: str):
    from .store import Store
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_ino)
    if _state.get("store_key") != key:
        old = _state.get("store")
        if old is not None:
            try:
                old.db.close()
            except Exception:                                  # noqa: BLE001
                pass
        _state["store"] = Store(path, shared=True)
        _state["store_key"] = key
        _state["legs"], _state["detours"] = {}, {}           # новый снимок — новые плечи
    return _state["store"]


def build(job_id: str, store_path: str, guest: tuple | None, scope: str,
          airports: list, base: str, kw: dict, ov: dict,
          seed_legs: dict | None = None, seed_detours: dict | None = None) -> tuple:
    """Задание процесса пула: сложить сеть и ставку флота. Возвращает
    (pairs, fleet, мс, новые плечи, новые обходы)."""
    from .econ import route_economics
    from .network import fleet_from_core, form_network
    t0 = time.monotonic()
    base_store = _store(store_path)
    store = base_store
    gdb = None
    if guest:
        from .guest import GuestDB, GuestStore
        gdb = GuestDB(guest[0])
        store = GuestStore(base_store, gdb, guest[1])
    q = _state.get("q")

    def progress(done, total, key):
        if q is not None:
            try:
                q.put_nowait((job_id, done, total, key))
            except Exception:                                  # noqa: BLE001
                pass

    legs = _state["legs"].setdefault(scope, {})
    legs.update(seed_legs or {})
    _state["detours"].update(seed_detours or {})
    legs_before, det_before = set(legs), set(_state["detours"])
    try:
        pairs = form_network(store, airports, base=base, aircraft=kw["aircraft"],
                             as_of=kw.get("as_of"), month=kw.get("month"),
                             overrides=ov or None, operator=kw.get("operator", "*"),
                             leg_cache=legs, detour_cache=_state["detours"],
                             progress=progress, seats=kw.get("seats"), aircraft_age=kw.get("aircraft_age"))
        ok = [p for p in pairs if p.status == "ok"]
        fleet = None
        if ok:
            fleet = fleet_from_core(route_economics, store, ok[0].a, ok[0].b,
                                    aircraft=kw["aircraft"], as_of=kw.get("as_of"),
                                    month=kw.get("month"), overrides=ov or None,
                                    operator=kw.get("operator", "*"), seats=kw.get("seats"),
                                    aircraft_age=kw.get("aircraft_age"))
    finally:
        if gdb is not None:
            try:
                gdb.db.close()
            except Exception:                                  # noqa: BLE001
                pass
    new_legs = {k: v for k, v in legs.items() if k not in legs_before}
    new_det = {k: v for k, v in _state["detours"].items() if k not in det_before}
    if sum(len(v) for v in _state["legs"].values()) > LEG_CACHE_MAX:
        _state["legs"].clear()
    return pairs, fleet, round((time.monotonic() - t0) * 1000), new_legs, new_det


class Pool:
    """Пул процессов и разборщик хода. Один на витрину."""

    def __init__(self, procs: int):
        import multiprocessing as mp
        import threading
        from concurrent.futures import ProcessPoolExecutor
        # spawn, а не fork: в витрине уже идут потоки (HTTP, ограничитель,
        # прогрев), и fork копировал бы их замки в захваченном состоянии.
        ctx = mp.get_context("spawn")
        self.procs = procs
        self.q = ctx.Queue()
        self.ex = ProcessPoolExecutor(max_workers=procs, mp_context=ctx,
                                      initializer=_init, initargs=(self.q,))
        self.jobs: dict = {}
        threading.Thread(target=self._drain, daemon=True, name="net-progress").start()

    def _drain(self):
        while True:
            try:
                job_id, done, total, key = self.q.get()
            except Exception:                                  # noqa: BLE001
                time.sleep(0.5)
                continue
            job = self.jobs.get(job_id)
            if job is not None:
                job["progress"].update(done=done, total=total, last=key)

    def submit(self, job_id: str, job: dict, *args):
        self.jobs[job_id] = job
        return self.ex.submit(build, job_id, *args)

    def forget(self, job_id: str):
        self.jobs.pop(job_id, None)


def store_path_of(store) -> str:
    return str(Path(getattr(store, "path", store)))
