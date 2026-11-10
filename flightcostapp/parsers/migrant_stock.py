"""ООН (UN DESA), International Migrant Stock: сколько уроженцев страны B живёт в стране A — домен `macro`.

Диаспоры дают отдельный, массовый и чувствительный к цене спрос — визиты к родным (VFR):
Германия — Турция, Великобритания — Польша, США — Мексика. Гравитационная модель без
этого признака их занижает.

Файл — xlsx с сайта ООН (Data → «by destination and origin»), рядом в той же папке — таблица
кодов M49 со статистического сайта ООН (Methodology → M49 → Overview → CSV), из неё берётся
перевод номера страны в ISO2. Таблица ищется так: строка заголовка, где есть «code» с
«destination» и с «origin»; годы — колонки с числами 1990–2030 в той же строке; первая группа
годов — оба пола (дальше в файле идут мужчины и женщины). Формат файла ООН меняется от
выпуска к выпуску — разбор тщательно называет, что не нашёл.

Ключ: `migrants/<страна проживания ISO2>-<страна рождения ISO2>/<год>`.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..store import Fact

WHO = "parser:migrant_stock@1"


def _m49(path: Path | None) -> dict[str, str]:
    """Номер M49 (без ведущих нулей) → ISO2 из CSV ООН (колонки «M49 Code», «ISO-alpha2 Code»)."""
    if not path:
        return {}
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = path.read_text(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if text.count(";") > text.count(",") else ","
    out = {}
    for r in csv.DictReader(io.StringIO(text), delimiter=sep):
        k = {c.strip().lower(): (v or "").strip() for c, v in r.items() if c}
        code = next((v for c, v in k.items() if "m49" in c), "")
        iso = next((v for c, v in k.items() if "alpha2" in c.replace("-", "").replace(" ", "")), "")
        if code.isdigit() and len(iso) == 2:
            out[str(int(code))] = iso.upper()
    return out


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import openpyxl
    here = Path(str(ctx.get("url", "")).removeprefix("file:"))
    if here.suffix.lower() == ".csv":
        ctx.setdefault("summary", []).append("таблица кодов M49 — читается вместе с xlsx")
        return []
    m49 = _m49(next(iter(sorted(here.parent.glob("*.csv"))), None))
    if not m49:
        raise ValueError("рядом с xlsx нет CSV кодов M49 (unstats.un.org → M49 → Overview → CSV)")
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        head = None
        for i, r in zip(range(40), rows):
            cells = [str(c or "").lower() for c in r]
            dcol = next((j for j, c in enumerate(cells) if "code" in c and "destination" in c), None)
            ocol = next((j for j, c in enumerate(cells) if "code" in c and "origin" in c), None)
            if dcol is not None and ocol is not None:
                years = [(j, int(float(c))) for j, c in enumerate(r)
                         if isinstance(c, (int, float)) and 1990 <= c <= 2030]
                if not years:
                    continue
                first = []
                for j, y in years:              # первая группа — оба пола
                    if first and y <= first[-1][1]:
                        break
                    first.append((j, y))
                head = (dcol, ocol, first)
                break
        if not head:
            continue
        dcol, ocol, first = head
        out, miss = [], set()
        for r in rows:
            if r is None or len(r) <= max(dcol, ocol):
                continue
            dc, oc = r[dcol], r[ocol]
            try:
                dc, oc = str(int(float(dc))), str(int(float(oc)))
            except (TypeError, ValueError):
                continue
            a, b = m49.get(dc), m49.get(oc)
            if not a or not b:
                miss.add(dc if not a else oc)       # регионы и группы стран — их и нет в ISO
                continue
            for j, y in first:
                v = r[j] if j < len(r) else None
                if isinstance(v, (int, float)) and v > 0:
                    out.append(Fact(domain="macro", key=f"migrants/{a}-{b}/{y}", valid_from=f"{y}-07-01",
                                    value=float(v), unit="человек", source_id=ctx["source_id"],
                                    artifact_sha=ctx.get("sha"), extracted_by=WHO, node=ctx.get("node"),
                                    note=f"UN DESA International Migrant Stock, лист {ws.title}"))
        if out:
            ctx.setdefault("summary", []).append(
                f"лист {ws.title}: пар {len({f.key.split('/')[1] for f in out})}, годы {[y for _, y in first]}, "
                f"кодов без ISO (регионы) {len(miss)}")
            return out
    raise ValueError("не нашёл таблицу: строки заголовка с кодами destination и origin и колонками годов")
