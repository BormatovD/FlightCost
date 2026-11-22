#!/usr/bin/env python3
"""Сводка по HTTP-запросам калькулятора из журнала доступа Caddy."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flightcostapp.probe import is_probe  # noqa: E402

ENDPOINTS = ("/api/route", "/api/network", "/api/netcompare", "/api/compare", "/api/solve")


@dataclass
class RequestStats:
    durations: list[float] = field(default_factory=list)
    errors: int = 0


@dataclass
class Report:
    endpoints: dict[tuple[str, bool], RequestStats] = field(
        default_factory=lambda: {
            (endpoint, probe): RequestStats()
            for endpoint in ENDPOINTS
            for probe in (False, True)
        }
    )
    first_timestamp: float | None = None
    skipped: int = 0


def log_paths(log_dir: Path) -> list[Path]:
    # Во время сжатия ротации могут одновременно быть видны оба её файла.
    paths = {
        path.name.removesuffix(".gz"): path for path in sorted(log_dir.iterdir())
        if path.name == "fca.log"
        or (path.name.startswith("fca-") and path.name.endswith((".log", ".log.gz")))
    }
    if not paths:
        raise FileNotFoundError(f"Журналы Caddy fca.log и fca-*.log[.gz] отсутствуют в {log_dir}")
    return list(paths.values())


def _number(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Ожидалось конечное число")
    return float(value)


def read_report(paths: list[Path], start: datetime, end: datetime) -> Report:
    report = Report()
    start_ts, end_ts = start.timestamp(), end.timestamp()
    for path in paths:
        open_log = gzip.open if path.suffix == ".gz" else open
        try:
            with open_log(path, "rb") as log:
                for line in log:
                    try:
                        record = json.loads(line)
                        timestamp = _number(record["ts"])
                        if timestamp < 0:
                            raise ValueError("Отрицательная метка времени")
                        uri = record["request"]["uri"]
                        if not isinstance(uri, str):
                            raise ValueError("Ожидался URI")
                        target = urlsplit(uri)
                        if start_ts <= timestamp < end_ts and target.path in ENDPOINTS:
                            duration = _number(record["duration"])
                            status = record["status"]
                            if duration < 0 or type(status) is not int:
                                raise ValueError("Некорректные метрики запроса")
                            stats = report.endpoints[target.path, is_probe(target.query)]
                            stats.durations.append(duration)
                            stats.errors += 400 <= status < 600
                    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
                        report.skipped += 1
                        continue
                    if timestamp < end_ts and (
                        report.first_timestamp is None or timestamp < report.first_timestamp
                    ):
                        report.first_timestamp = timestamp
        except (OSError, EOFError, zlib.error) as exc:
            raise OSError(f"Не удалось прочитать {path}: {exc}") from exc
    return report


def _format_percentile(ordered: list[float], percentile: int) -> str:
    if not ordered:
        return "—"
    rank = (len(ordered) * percentile + 99) // 100
    return f"{ordered[rank - 1]:.3f}"


def _utc_label(instant: datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


def print_report(report: Report, start: datetime, end: datetime) -> None:
    print(f"Период UTC [{_utc_label(start)}, {_utc_label(end)})")
    if report.first_timestamp is None:
        print("В журналах нет пригодных записей. Покрытие периода неизвестно.")
    elif report.first_timestamp > start.timestamp():
        first = datetime.fromtimestamp(report.first_timestamp, tz=timezone.utc)
        print(f"Первая доступная запись {_utc_label(first)}. Начало периода может быть не покрыто.")
    print(f"Пропущено некорректных записей во всех проверенных файлах — {report.skipped}.")
    print("Единица учёта — HTTP-запрос, включая POST и опрос статуса расчёта.")
    print()
    print(f"{'API':<16} {'Группа':<12} {'Запросы':>8} {'p50, с':>9} {'p95, с':>9} {'>3 с':>8} {'4xx/5xx':>8}")
    for probe in (False, True):
        label = "probe=dev" if probe else "без метки"
        for endpoint in ENDPOINTS:
            stats = report.endpoints[endpoint, probe]
            durations = sorted(stats.durations)
            p50 = _format_percentile(durations, 50)
            p95 = _format_percentile(durations, 95)
            slow = sum(duration > 3 for duration in durations)
            print(f"{endpoint:<16} {label:<12} {len(durations):>8} {p50:>9} {p95:>9} {slow:>8} {stats.errors:>8}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="длина периода в сутках (по умолчанию 7)")
    parser.add_argument("--log-dir", type=Path, default=Path("/var/log/caddy"), help="каталог журналов Caddy")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days должен быть положительным")
    end = datetime.now(timezone.utc)
    try:
        start = end - timedelta(days=args.days)
    except OverflowError:
        parser.error("--days слишком велик")
    try:
        report = read_report(log_paths(args.log_dir), start, end)
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 1
    print_report(report, start, end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
