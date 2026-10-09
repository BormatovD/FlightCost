"""Обход закрытого воздушного пространства (решения 156, 158).

Пара через закрытое небо по прямой не считается: число полёта, которого
не бывает, хуже честного отказа. Здесь строится путь в обход — кратчайший
из возможных по графу видимости: вершины — концы маршрута и вершины
закрытых полигонов, отодвинутые наружу на зазор; ребро есть, если дуга
между вершинами не входит ни в один закрытый полигон. Дальше Дейкстра.

Геометрия нарочно простая и та же, что у пересечения зон в `airspace`:
границы FIR — прямые в координатах широта/долгота, дуга маршрута режется
на куски по 150 км и проверяется кусками. Для ±15% этого достаточно;
ломается это только на антимеридиане, и об этом сказано в `Detour`.

Что обход НЕ учитывает — и об этом говорит оговорка: структуру трасс,
односторонние потоки, высотные ограничения, платные коридоры. Он
отвечает на вопрос «сколько километров стоит закрытие», не «по какой
трассе лететь».
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

R_KM = 6371.0
PIECE_KM = 150.0          # шаг дробления дуги при проверке пересечений
BUFFER_KM = 25.0          # зазор от границы закрытой зоны
MAX_STRETCH = 2.2         # кандидаты только внутри эллипса d(o,v)+d(v,d) ≤ k·d(o,d)
MAX_VERTICES = 400        # на все закрытые полигоны вместе, после упрощения


@dataclass
class Detour:
    found: bool
    direct_km: float
    path_km: float
    waypoints: list                       # [(lat, lon), …], включая концы
    avoided: list = field(default_factory=list)   # идентификаторы зон
    warnings: list = field(default_factory=list)

    @property
    def extra_km(self) -> float:
        return self.path_km - self.direct_km

    @property
    def extra_share(self) -> float:
        return self.path_km / self.direct_km - 1 if self.direct_km else 0.0


# ── сферическая геометрия ───────────────────────────────────────────────

def gc_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    x = (math.sin(la1) * math.sin(la2)
         + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1))
    return R_KM * math.acos(max(-1.0, min(1.0, x)))


def gc_points(a, b, n: int) -> list:
    """n+1 точек дуги большого круга от a до b включительно."""
    if n <= 1 or gc_km(a, b) < 1e-6:
        return [tuple(a), tuple(b)]
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    d = math.acos(max(-1.0, min(1.0, math.sin(la1) * math.sin(la2)
                                + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1))))
    out = []
    for i in range(n + 1):
        f = i / n
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))),
                    math.degrees(math.atan2(y, x))))
    return out


# ── полигоны ────────────────────────────────────────────────────────────

def _simplify(ring: list, tol_deg: float) -> list:
    """Дуглас — Пекер по замкнутому кольцу. Вершины — те же точки границы,
    только реже: кандидаты обхода остаются на реальной границе."""
    if len(ring) <= 4 or tol_deg <= 0:
        return ring
    pts = np.asarray(ring, dtype=float)

    def rec(i, j, keep):
        if j <= i + 1:
            return
        a, b = pts[i], pts[j]
        seg = b - a
        L2 = float(seg @ seg)
        if L2 == 0:
            d = np.linalg.norm(pts[i + 1:j] - a, axis=1)
        else:
            t = np.clip(((pts[i + 1:j] - a) @ seg) / L2, 0, 1)
            d = np.linalg.norm(pts[i + 1:j] - (a + t[:, None] * seg), axis=1)
        k = int(np.argmax(d))
        if d[k] > tol_deg:
            keep.add(i + 1 + k)
            rec(i, i + 1 + k, keep)
            rec(i + 1 + k, j, keep)

    keep = {0, len(pts) - 1}
    # опорная вершина посередине, чтобы замкнутое кольцо не схлопнулось в отрезок
    mid = len(pts) // 2
    keep.add(mid)
    rec(0, mid, keep)
    rec(mid, len(pts) - 1, keep)
    return [tuple(pts[i]) for i in sorted(keep)]


def _inside(lat: float, lon: float, ring: np.ndarray) -> bool:
    """Чёт-нечет по лучу; ring — массив (n, 2) [lat, lon], замкнутый."""
    y, x = lat, lon
    ys, xs = ring[:, 0], ring[:, 1]
    y1, x1 = ys[:-1], xs[:-1]
    y2, x2 = ys[1:], xs[1:]
    cond = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
    return bool(np.sum(cond & (x < xin)) % 2)


def _segments_cross(p, q, rings: list) -> bool:
    """Пересекает ли отрезок p–q (в координатах широта/долгота) хоть одно
    ребро хоть одного кольца. Ориентированные площади, векторно."""
    py, px = p
    qy, qx = q
    for ring in rings:
        ay, ax = ring[:-1, 0], ring[:-1, 1]
        by, bx = ring[1:, 0], ring[1:, 1]
        # быстрый отсев по прямоугольникам
        if (min(px, qx) > ring[:, 1].max() or max(px, qx) < ring[:, 1].min()
                or min(py, qy) > ring[:, 0].max() or max(py, qy) < ring[:, 0].min()):
            continue
        d1 = (qx - px) * (ay - py) - (qy - py) * (ax - px)
        d2 = (qx - px) * (by - py) - (qy - py) * (bx - px)
        d3 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        d4 = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax)
        if np.any((d1 * d2 < 0) & (d3 * d4 < 0)):
            return True
    return False


def _arc_blocked(a, b, rings: list) -> bool:
    n = max(1, int(math.ceil(gc_km(a, b) / PIECE_KM)))
    pts = gc_points(a, b, n)
    for p, q in zip(pts, pts[1:]):
        if _segments_cross(p, q, rings):
            return True
        my, mx = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        if any(_inside(my, mx, r) for r in rings):
            return True
    return False


def _offset_vertices(ring: np.ndarray, buffer_km: float) -> list:
    """Вершины кольца, отодвинутые наружу по биссектрисе на зазор.
    Наружу — проверкой: если точка попала внутрь, знак меняется."""
    out = []
    n = len(ring) - 1                     # кольцо замкнуто, последняя = первая
    for i in range(n):
        v = ring[i]
        a, b = ring[i - 1 if i else n - 1], ring[i + 1]
        k = math.cos(math.radians(v[0])) or 1e-9
        # локальные километры: восток, север
        def loc(p):
            return np.array([(p[1] - v[1]) * 111.32 * k, (p[0] - v[0]) * 110.57])
        ea, eb = loc(a), loc(b)
        na = ea / (np.linalg.norm(ea) or 1); nb = eb / (np.linalg.norm(eb) or 1)
        bis = -(na + nb)
        if np.linalg.norm(bis) < 1e-6:      # прямой угол — нормаль к ребру
            bis = np.array([-na[1], na[0]])
        bis = bis / np.linalg.norm(bis) * buffer_km
        lat = v[0] + bis[1] / 110.57
        lon = v[1] + bis[0] / (111.32 * k)
        if _inside(lat, lon, ring):
            lat = v[0] - bis[1] / 110.57
            lon = v[1] - bis[0] / (111.32 * k)
        out.append((float(lat), float(lon)))
    return out


# ── обход ───────────────────────────────────────────────────────────────

def detour(origin, destination, closed: dict, *, buffer_km: float = BUFFER_KM,
           simplify_deg: float = 0.05) -> Detour:
    """closed: {zone_id: [ring, …]}, ring — список (lat, lon) внешней границы.

    Дырки полигонов не учитываются: закрытая зона с островком чужого неба
    внутри закрыта целиком, это безопасная сторона ошибки.
    """
    o, d = tuple(map(float, origin)), tuple(map(float, destination))
    direct = gc_km(o, d)
    warnings = []
    rings, owners = [], []
    for zid, rs in closed.items():
        for ring in rs:
            r = [tuple(map(float, p)) for p in ring]
            if r[0] != r[-1]:
                r.append(r[0])
            if max(p[1] for p in r) - min(p[1] for p in r) > 180:
                warnings.append(f"зона {zid} пересекает антимеридиан — обход там не строится")
                continue
            rr = _simplify(r, simplify_deg)
            if rr[0] != rr[-1]:
                rr.append(rr[0])
            rings.append(np.asarray(rr, dtype=float))
            owners.append(zid)
    if not rings:
        return Detour(True, direct, direct, [o, d], [], warnings)

    # Что именно задевает прямая
    hit = [owners[i] for i, r in enumerate(rings) if _arc_blocked(o, d, [r])]
    if not hit:
        return Detour(True, direct, direct, [o, d], [], warnings)

    cands = []
    for r in rings:
        cands += _offset_vertices(r, buffer_km)
    cands = [c for c in cands
             if gc_km(o, c) + gc_km(c, d) <= MAX_STRETCH * direct
             and not any(_inside(c[0], c[1], r) for r in rings)]
    if len(cands) > MAX_VERTICES:
        # Реже, но равномерно: каждая k-я вершина, а не первые N
        step = len(cands) / MAX_VERTICES
        cands = [cands[int(i * step)] for i in range(MAX_VERTICES)]
    nodes = [o, d] + cands
    n = len(nodes)
    adj: list[list] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not _arc_blocked(nodes[i], nodes[j], rings):
                w = gc_km(nodes[i], nodes[j])
                adj[i].append((j, w)); adj[j].append((i, w))
    dist = [math.inf] * n; prev = [-1] * n; dist[0] = 0.0
    pq = [(0.0, 0)]
    while pq:
        du, u = heapq.heappop(pq)
        if du > dist[u]:
            continue
        if u == 1:
            break
        for v, w in adj[u]:
            if du + w < dist[v]:
                dist[v], prev[v] = du + w, u
                heapq.heappush(pq, (dist[v], v))
    if dist[1] == math.inf:
        warnings.append("обход не найден: закрытые зоны отрезают пункт назначения")
        return Detour(False, direct, math.inf, [], sorted(set(hit)), warnings)
    path, u = [], 1
    while u != -1:
        path.append(nodes[u]); u = prev[u]
    path.reverse()
    return Detour(True, direct, dist[1], path, sorted(set(hit)), warnings)
