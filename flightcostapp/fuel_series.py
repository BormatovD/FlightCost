"""Открытые ряды цены топлива: что пора собрать, проверка черновика агента, приёмка.

Ряды живут в `data/fuel/_series.yaml` (их читает `econ.fuel_series`), демпфер —
в `data/fuel/_ru_damper.yaml`. Агент «топливо» (agent_run.fuel) раз в месяц
ищет новые месяцы по подсказке `find` каждого ряда и присылает черновик
`fuel-ГГГГ-ММ-ДД.json`; дома `fca master drafts` проверяет его этим модулем и
по `--accept-fuel` дописывает точки. Сервер файлы данных не правит.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERIES_PATH = ROOT / "data" / "fuel" / "_series.yaml"
DAMPER_PATH = ROOT / "data" / "fuel" / "_ru_damper.yaml"
MAX_DUE = 3                 # не больше трёх последних месяцев на ряд за прогон
JUMP_LOOK = 0.35            # скачок к прошлой точке больше 35 % — смотреть глазами
DAMPER_MAX = 200_000        # руб/т; больше не бывало и не бывает при цене биржи ~100 тыс.


def _month_add(m: str, n: int) -> str:
    y, mm = int(m[:4]), int(m[5:7]) + n
    while mm > 12:
        y, mm = y + 1, mm - 12
    while mm < 1:
        y, mm = y - 1, mm + 12
    return f"{y:04d}-{mm:02d}"


def load(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text("utf-8")) or {}
    except OSError:
        return {}


def due(series_doc: dict, damper_doc: dict, today: date | None = None) -> dict:
    """{"points": [(ряд, месяц)], "damper": [месяц]} — месяцы после последней точки
    до прошлого месяца включительно, не больше MAX_DUE последних на ряд."""
    last_full = _month_add(f"{(today or date.today()):%Y-%m}", -1)
    out = {"points": [], "damper": []}
    for sid, ser in (series_doc.get("series") or {}).items():
        pts = sorted(str(m)[:7] for m in (ser.get("points") or {}))
        if not pts:
            continue
        months, m = [], _month_add(pts[-1], 1)
        while m <= last_full:
            months.append(m)
            m = _month_add(m, 1)
        out["points"] += [(sid, x) for x in months[-MAX_DUE:]]
    dm = sorted(str(m)[:7] for m in (damper_doc.get("months") or {}))
    if dm:
        months, m = [], _month_add(dm[-1], 1)
        while m <= last_full:
            months.append(m)
            m = _month_add(m, 1)
        out["damper"] = months[-MAX_DUE:]
    return out


_NUM = re.compile(r"\d[\d\s  .,']*\d|\d")


def _readings(tok: str) -> set[float]:
    """Все прочтения числа: «126.263» — 126263 (точка — разряды) или 126,263."""
    t = re.sub(r"[\s  ']", "", tok)
    out = set()
    for thou, dec in ((",", "."), (".", ",")):
        s = t.replace(thou, "").replace(dec, ".")
        try:
            out.add(float(s))
        except ValueError:
            pass
    return out


def number_in(value: float, quote: str) -> bool:
    """Есть ли в цитате это число (с точностью до округления в тексте)."""
    for tok in _NUM.findall(quote or ""):
        for r in _readings(tok):
            if abs(r - value) <= max(0.006, abs(value) * 0.0005):
                return True
    return False


def check(blob: bytes, store=None, series_doc: dict | None = None, damper_doc: dict | None = None) -> dict:
    """Проверка черновика: у каждой точки verdict clean / look / reject и причины."""
    sdoc = load(SERIES_PATH) if series_doc is None else series_doc
    ddoc = load(DAMPER_PATH) if damper_doc is None else damper_doc
    try:
        d = json.loads(blob)
    except ValueError as e:
        return {"rows": [], "error": f"не JSON: {e}", "doubts": []}
    rows = []
    for p in d.get("points") or []:
        sid, m, v = p.get("series"), str(p.get("month") or ""), p.get("value")
        ser = (sdoc.get("series") or {}).get(sid)
        r = {"kind": "point", "series": sid, "month": m, "value": v, "where": p.get("where"),
             "quote": p.get("quote"), "reasons": []}
        rows.append(r)
        if v is None:
            r.update(verdict="skip", reasons=["агент не нашёл значения"])
            continue
        if not ser or not re.fullmatch(r"\d{4}-\d{2}", m) or not isinstance(v, (int, float)) or v <= 0:
            r.update(verdict="reject", reasons=["неизвестный ряд, месяц не ГГГГ-ММ или значение не число > 0"])
            continue
        if not str(p.get("where") or "").startswith("http"):
            r["reasons"].append("нет адреса страницы")
        if not number_in(float(v), str(p.get("quote") or "")):
            r["reasons"].append("числа нет в цитате")
        prev = sorted((str(k)[:7], (x["value"] if isinstance(x, dict) else x))
                      for k, x in (ser.get("points") or {}).items() if str(k)[:7] < m)
        if prev and abs(float(v) / float(prev[-1][1]) - 1) > JUMP_LOOK:
            r["reasons"].append(f"скачок к {prev[-1][0]}: {prev[-1][1]} → {v}")
        if str(m) in {str(k)[:7] for k in (ser.get("points") or {})}:
            r["reasons"].append("месяц уже есть в ряду — точка заменит его")
        if ser.get("mode") == "ratio" and store is not None:
            from .econ import SERIES_K_BAND, _months_back, usgc_month_mean
            win = int(ser.get("spot_window", 1))
            means = [usgc_month_mean(store, _months_back(m, i)) for i in range(win)]
            if all(x is not None for x in means):
                r["k"] = float(v) / (sum(means) / win)
                if not SERIES_K_BAND[0] <= r["k"] <= SERIES_K_BAND[1]:
                    r["reasons"].append(f"k = {r['k']:.2f} вне полосы {SERIES_K_BAND}")
            else:
                r["reasons"].append("нет котировок USGC за окно — k не проверен (fca refresh --only jet_fuel_price)")
        r["verdict"] = "look" if r["reasons"] else "clean"
    for p in d.get("damper") or []:
        m, v = str(p.get("month") or ""), p.get("value")
        r = {"kind": "damper", "series": "ru_damper", "month": m, "value": v, "where": p.get("where"),
             "quote": p.get("quote"), "reasons": []}
        rows.append(r)
        if v is None:
            r.update(verdict="skip", reasons=["агент не нашёл значения"])
            continue
        if not re.fullmatch(r"\d{4}-\d{2}", m) or not isinstance(v, (int, float)) or not 0 <= v <= DAMPER_MAX:
            r.update(verdict="reject", reasons=[f"месяц не ГГГГ-ММ или демпфер вне 0–{DAMPER_MAX} руб/т"])
            continue
        if not number_in(float(v), str(p.get("quote") or "")):
            r["reasons"].append("числа нет в цитате")
        if not str(p.get("where") or "").startswith("http"):
            r["reasons"].append("нет адреса страницы")
        if m in {str(k)[:7] for k in (ddoc.get("months") or {})}:
            r["reasons"].append("месяц уже есть — заменит его")
        r["verdict"] = "look" if r["reasons"] else "clean"
    return {"rows": rows, "doubts": [str(x) for x in d.get("doubts") or []]}


def _dump(path: Path, doc: dict) -> None:
    head = "".join(ln for ln in path.read_text("utf-8").splitlines(True) if ln.startswith("#")) \
        if path.exists() else ""
    path.write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), "utf-8")


def merge(rows: list[dict], series_path: Path = SERIES_PATH, damper_path: Path = DAMPER_PATH) -> list[str]:
    """Дописать принятые точки. Возвращает строки «что добавлено»."""
    sdoc, ddoc, done = load(series_path), load(damper_path), []
    for r in rows:
        if r["kind"] == "point":
            pts = sdoc["series"][r["series"]].setdefault("points", {})
            pts[r["month"]] = {"value": r["value"], "source": r.get("where")}
            sdoc["series"][r["series"]]["points"] = dict(sorted(pts.items(), key=lambda kv: str(kv[0])))
            done.append(f"{r['series']} {r['month']} = {r['value']}")
        elif r["kind"] == "damper":
            ms = ddoc.setdefault("months", {})
            ms[r["month"]] = {"damper_rub_t": r["value"], "source": r.get("where")}
            ddoc["months"] = dict(sorted(ms.items(), key=lambda kv: str(kv[0])))
            done.append(f"демпфер {r['month']} = {r['value']}")
    if any(r["kind"] == "point" for r in rows):
        _dump(series_path, sdoc)
    if any(r["kind"] == "damper" for r in rows):
        _dump(damper_path, ddoc)
    return done
