#!/usr/bin/env python3
"""Нагрузочный прогон сборки сети: N человек одновременно жмут «посчитать сеть».

Запускается НА СЕРВЕРЕ, против витрины на петле (мимо Caddy), от deploy:

    python3 /srv/fca/app/tools/load_network.py --users 10
    python3 /srv/fca/app/tools/load_network.py --users 20 --size 6 --types A320,A20N,B738

Каждый «человек» — свой адрес в X-Forwarded-For (у витрины предел тяжёлых
расчётов на адрес) и своя сеть: случайный набор аэропортов из пула, свой
тип. Одновременно отдельный поток раз в 2 секунды меряет то, что видят
все остальные: /healthz и расчёт одного маршрута FRA–BCN.

Печатает: сколько ждал каждый (медиана, 90 %, худший), сколько сетей
отказано («очередь полна» или ошибка), задержку маршрута и healthz во
время нагрузки, память процесса витрины. Ничего не пишет в базу.

Первый прогон после перезапуска витрины — холодный (плечи не в кэше);
повторный с тем же --seed показывает тёплый.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request

POOL = ("FRA,MUC,BER,HAM,DUS,BCN,MAD,PMI,AGP,LIS,OPO,FCO,MXP,VCE,NAP,CDG,ORY,NCE,AMS,BRU,VIE,ZRH,GVA,"
        "CPH,ARN,OSL,HEL,WAW,KRK,PRG,BUD,OTP,SOF,ATH,IST,DUB,LHR,LGW,MAN,EDI").split(",")


def get(base, path, q, ip, timeout=60):
    url = f"{base}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"X-Forwarded-For": ip, "User-Agent": "fca-load"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return time.monotonic() - t0, json.loads(body) if body[:1] in (b"{", b"[") else {}


def user(i, a, rnd, out):
    airports = rnd.sample(POOL, a.size)
    ac = rnd.choice(a.types.split(","))
    q = {"airports": ",".join(airports), "base": airports[0], "ac": ac, "fleet": "3", "month": "7"}
    ip = f"10.77.{i // 250}.{i % 250 + 1}"
    t0 = time.monotonic()
    rec = {"user": i, "ac": ac, "airports": len(airports), "queue_max": 0, "polls": 0}
    try:
        while True:
            _, r = get(a.url, "/api/network", q, ip, timeout=a.timeout)
            rec["polls"] += 1
            if r.get("pending"):
                rec["queue_max"] = max(rec["queue_max"], (r.get("progress") or {}).get("queue") or 0)
                if time.monotonic() - t0 > a.timeout:
                    rec["error"] = "не дождался"
                    break
                time.sleep(1)
                continue
            if r.get("error"):
                rec["error"] = r["error"][:120]
            else:
                rec["pairs"] = len(r.get("pairs") or [])
            break
    except Exception as e:                                         # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:120]
    rec["sec"] = round(time.monotonic() - t0, 1)
    out.append(rec)


def probe(a, stop, out):
    while not stop.is_set():
        for name, path, q in (("healthz", "/healthz", {}),
                              ("маршрут", "/api/route", {"origin": "FRA", "destination": "BCN", "ac": "A320"})):
            try:
                dt, _ = get(a.url, path, q, "10.99.0.1", timeout=60)
                out.setdefault(name, []).append(dt)
            except Exception:                                      # noqa: BLE001
                out.setdefault(name + " отказ", []).append(1)
        stop.wait(2)


def rss_of_fca() -> str:
    try:
        pids = subprocess.run(["pgrep", "-f", "fca.*serve"], capture_output=True, text=True).stdout.split()
        tot = 0
        for p in pids:
            for ln in open(f"/proc/{p}/status"):
                if ln.startswith("VmRSS:"):
                    tot += int(ln.split()[1])
        kids = subprocess.run(["pgrep", "-f", "multiprocessing"], capture_output=True, text=True).stdout.split()
        kid = 0
        for p in kids:
            try:
                for ln in open(f"/proc/{p}/status"):
                    if ln.startswith("VmRSS:"):
                        kid += int(ln.split()[1])
            except OSError:
                pass
        return f"витрина {tot / 1024:.0f} МБ, процессы пула {kid / 1024:.0f} МБ"
    except Exception as e:                                         # noqa: BLE001
        return f"не измерено ({e})"


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--size", type=int, default=5, help="аэропортов в сети одного человека")
    ap.add_argument("--types", default="A320,A20N,B738,A321,E190")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()

    import os
    print(f"ядер на машине: {os.cpu_count()}; людей {a.users}, аэропортов в сети {a.size}, "
          f"пар в сети {a.size * (a.size - 1) // 2}")
    print("память до:", rss_of_fca())
    rnd = random.Random(a.seed)
    out, probes, stop = [], {}, threading.Event()
    pt = threading.Thread(target=probe, args=(a, stop, probes), daemon=True)
    pt.start()
    t0 = time.monotonic()
    th = [threading.Thread(target=user, args=(i, a, random.Random(rnd.random()), out)) for i in range(a.users)]
    for t in th:
        t.start()
        time.sleep(0.2)                       # не строго в одну миллисекунду, как и люди
    peak = ""
    while any(t.is_alive() for t in th):
        time.sleep(3)
        peak = rss_of_fca()
    stop.set()
    total = time.monotonic() - t0

    good = [r for r in out if not r.get("error")]
    bad = [r for r in out if r.get("error")]
    secs = [r["sec"] for r in good]
    print(f"\nвсего {total:.0f} с; готово {len(good)} из {len(out)}")
    if secs:
        print(f"ждали: медиана {statistics.median(secs):.0f} с, 90 % — {pct(secs, .9):.0f} с, "
              f"худший {max(secs):.0f} с; место в очереди до {max(r['queue_max'] for r in out)}")
    for r in bad[:10]:
        print(f"  отказ у {r['user']} ({r['ac']}): {r['error']}")
    for name, xs in probes.items():
        if name.endswith("отказ"):
            print(f"{name}: {len(xs)}")
        else:
            print(f"{name} во время нагрузки: медиана {statistics.median(xs) * 1000:.0f} мс, "
                  f"худший {max(xs) * 1000:.0f} мс ({len(xs)} замеров)")
    print("память на пике:", peak)
    print("\nпо людям (сек, тип, пар, макс. место в очереди):")
    for r in sorted(out, key=lambda r: r["user"]):
        print(f"  {r['user']:>3}  {r['sec']:>6} с  {r['ac']:<5} {r.get('pairs', '-'):>4}  "
              f"очередь {r['queue_max']:>2}  {r.get('error', '')}")


if __name__ == "__main__":
    main()
