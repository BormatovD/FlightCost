"""Налёт борта и экипажи в режиме «Сеть» — из плеч сети, а не одной цифрой 300 ч.

План network-calc (09.11.2026), статья research/network-2026-10.

Пиковый день. База открыта `window_h` часов (по умолчанию 18: 06:00–24:00 — типичная
база с ночными ограничениями). Рейсов = ⌊(окно + оборот) ÷ (блок + оборот)⌋; у челнока
от базы — до чётного, чтобы последний рейс вернул борт домой. Плечо от LONG_H часов
окно не ограничивает: дальний борт летает круглые сутки с долгим оборотом. От EVEN_BELOW_H до LONG_H часов — без округления до чётного: так
летают трансконы и W-ротации (без этого у JetBlue и Delta на плечах 4,5 ч факт выше модели).

Год. Пиковый день × 365/12 — это лето без поломок. Годовой коэффициент снимает зиму,
тяжёлое ТО, резерв и задержки. Он не цитата: откалиброван по Form 41 T-2 2025
(факт ÷ пиковый день по средней длине плеча перевозчика на типе, медиана по бортам,
research/network-2026-10/bin/util_calib.py) по типу сети. Frontier и Southwest в
калибровку не входили — на них проверка (tests/test_netutil.py).

Резерв и тяжёлое ТО внутри коэффициента — явными долями, но долями-допущениями:
открытых данных о них по перевозчикам нет. Остаток — сезонность и задержки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

WINDOW_H = 18.0
TURN_MIN = 25.0
LONG_H = 5.0                 # плечо от 5 ч — дальнее: окно базы не ограничивает
LONG_TURN_MIN = 90.0
EVEN_BELOW_H = 3.5           # короче — челнок «туда-обратно» до чётного; длиннее — W-ротации и ночные
                             # рейсы, борт к ночи домой не обязан (трансконы США: иначе факт > модели)
DAYS_MONTH = 365 / 12

# Тип сети перевозчиков США для калибровки (util_calib.py). Региональные не берутся.
CLASS_OF = {
    "WN": "shuttle", "B6": "shuttle",
    "AA": "hub", "UA": "hub", "DL": "hub", "AS": "hub", "HA": "hub",
    "F9": "leisure", "NK": "leisure", "G4": "leisure", "SY": "leisure", "MX": "leisure",
}

# Годовой коэффициент по типу сети: медиана по бортам, Form 41 T-2 2025, без F9 и WN.
# Пересчёт — util_calib.py; при смене чисел поправить и тест.
ANNUAL = {
    "shuttle": 0.81,    # B6, 2 типа (WN — проверка: 0,77–0,84)
    "hub": 0.74,        # AA, UA, DL, AS — 21 тип, разброс 0,51–0,97
    "leisure": 0.52,    # NK, G4 — 3 типа, 0,46–0,72 (F9 — проверка: 0,58): сезонность и пики выходных
    "longhaul": 0.73,   # плечо от 5 ч — один тип (UA 777): заготовка слабая
}
NAMES = {"shuttle": "челнок от базы", "hub": "хаб", "leisure": "лоукост и курортные (сезонность)",
         "longhaul": "дальний"}

# Доли внутри коэффициента — допущения с диапазоном, не измерения.
RESERVE = (0.03, (0.02, 0.05))     # резервные борта: около одного на 30
HEAVY_MX = (0.03, (0.02, 0.05))    # C-check: 2–4 недели раз в 1,5–2 года

PILOT_H_YEAR = 750.0               # налёт пилота в год, диапазон 500–900 (потолок EASA — 900)
PILOT_RANGE = (500.0, 900.0)
REPORT_MIN, RELEASE_MIN = 60.0, 30.0


def flights_in_window(block_h: float, window_h: float = WINDOW_H, turn_min: float = TURN_MIN,
                      shuttle: bool = True) -> int:
    if block_h >= LONG_H:
        t = LONG_TURN_MIN / 60
        return max(1, math.floor((24 + t) / (block_h + t)))
    t = turn_min / 60
    n = math.floor((window_h + t) / (block_h + t))
    if shuttle and block_h < EVEN_BELOW_H:
        n -= n % 2
    return max(n, 0)


def peak_day(block_h: float, window_h: float = WINDOW_H, turn_min: float = TURN_MIN) -> float:
    """Блок-часы борта в пиковый день."""
    return flights_in_window(block_h, window_h, turn_min) * block_h


def max_sectors(block_h: float, turn_min: float = TURN_MIN) -> int:
    """Сколько секторов одна смена EASA (начало 06:00–13:29) закрывает при этом плече:
    13 ч на один-два сектора, на полчаса меньше за каждый следующий, не меньше 9 ч."""
    best = 0
    for n in range(1, 13):
        fdp = max(13.0 - 0.5 * max(n - 2, 0), 9.0)
        need = REPORT_MIN / 60 + n * block_h + (n - 1) * turn_min / 60 + RELEASE_MIN / 60
        if need <= fdp:
            best = n
    return best


@dataclass
class Util:
    h_month: float
    kind: str
    factor: float
    peak_h: float
    window_h: float
    turn_min: float
    note: str
    shares: dict


def network_util(legs: list[tuple[float, float]], kind: str | None = None,
                 window_h: float = WINDOW_H, turn_min: float = TURN_MIN) -> Util:
    """`legs` — [(блок-часы плеча, вес)], вес — рейсов в неделю или 1, если частоты нет."""
    if not legs:
        raise ValueError("нет плеч — налёт не из чего считать")
    w = sum(x for _, x in legs) or 1.0
    peak = sum(peak_day(b, window_h, turn_min) * x for b, x in legs) / w
    mean_b = sum(b * x for b, x in legs) / w
    if kind is None:
        kind = "longhaul" if mean_b >= LONG_H else "shuttle"
    if kind not in ANNUAL:
        raise ValueError(f"тип сети {kind!r} не из {sorted(ANNUAL)}")
    k = ANNUAL[kind]
    rest = k / ((1 - RESERVE[0]) * (1 - HEAVY_MX[0]))
    h = peak * DAYS_MONTH * k
    note = (f"пиковый день {peak:.1f} ч (окно {window_h:g} ч, оборот {turn_min:g} мин, плечо в среднем "
            f"{mean_b:.2f} ч) × {DAYS_MONTH:.1f} × {k:.2f} — {NAMES[kind]}: резерв {RESERVE[0]:.0%}, "
            f"тяжёлое ТО {HEAVY_MX[0]:.0%} (допущения), остальное — зима и задержки ×{rest:.2f}; "
            f"коэффициент — Form 41 T-2 2025")
    return Util(h, kind, k, peak, window_h, turn_min, note,
                {"reserve": RESERVE[0], "heavy_mx": HEAVY_MX[0], "season_delay": rest})


def crews(h_month: float, pilot_h: float = PILOT_H_YEAR) -> float:
    """Экипажей (по два пилота) на борт: годовые часы борта ÷ налёт пилота. Без резерва
    на болезни, отпуска и обучение."""
    return h_month * 12 / pilot_h


def duty_notes(legs: list[tuple[str, float]], window_h: float = WINDOW_H,
               turn_min: float = TURN_MIN) -> list[str]:
    """Пары, где пиковый день борта не закрывается одной сменой экипажа."""
    out = []
    for name, b in legs:
        n, s = flights_in_window(b, window_h, turn_min), max_sectors(b, turn_min)
        if s == 0:
            out.append(f"{name}: плечо {b:.1f} ч не помещается в одну смену EASA — нужен усиленный экипаж")
        elif n > s:
            out.append(f"{name}: борт делает {n} рейсов за день, смена экипажа — {s}: "
                       f"в день {math.ceil(n / s)} смены")
    return out
