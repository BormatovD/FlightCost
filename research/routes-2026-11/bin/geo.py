"""Подложка карт статьи: суша Natural Earth 1:50m (общественное достояние) → out/land_<регион>.json —
упрощённые полигоны в рамке региона. Исходник скачивается с GitHub (nvkelso/natural-earth-vector) во временную
папку и в репозиторий не кладётся; кладётся только упрощённая вырезка.

    python3 research/routes-2026-11/bin/geo.py <ne_50m_land.geojson>
"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BOX = {"europe": (-12, 30, 70, 62), "india": (68, 8, 92, 29), "world": (-110, -45, 150, 65)}
STEP = {"europe": 0.25, "india": 0.2, "world": 0.8}


def simplify(ring, step):
    out, last = [], None
    for x, y in ring:
        if last is None or abs(x - last[0]) + abs(y - last[1]) >= step:
            out.append([round(x, 2), round(y, 2)])
            last = (x, y)
    return out


def main(src):
    g = json.load(open(src))
    for reg, (x0, y0, x1, y1) in BOX.items():
        polys = []
        for f in g["features"]:
            geo = f["geometry"]
            rings = geo["coordinates"] if geo["type"] == "Polygon" else [p[0] for p in geo["coordinates"]]
            if geo["type"] == "Polygon":
                rings = [rings[0]]
            for r in rings:
                xs, ys = [p[0] for p in r], [p[1] for p in r]
                if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                    continue
                s = simplify(r, STEP[reg])
                if len(s) >= 4:
                    polys.append(s)
        (HERE / "out" / f"land_{reg}.json").write_text(json.dumps({"box": BOX[reg], "polys": polys},
                                                                  separators=(",", ":")), encoding="utf-8")
        print(reg, len(polys), sum(len(p) for p in polys))


if __name__ == "__main__":
    main(sys.argv[1])
