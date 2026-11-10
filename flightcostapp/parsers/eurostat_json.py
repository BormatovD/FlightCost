"""Eurostat, API статистики (JSON-stat 2.0) — региональные показатели по NUTS, домен `macro`.

Один разборщик на несколько таблиц: что брать, говорит реестр. Поля источника:
  indicator — короткое имя показателя в ключе (gdp_pc_pps, pop, nights, emp_k …);
  dims      — какие значения остальных измерений нужны, если в ответе их несколько
              (например, `{"nace_r2": ["K", "TOTAL"]}` — тогда в ключ попадает и код);
адрес уже фильтрует по единице и прочим измерениям (`&unit=…&sex=T`).

JSON-stat: `id` — порядок измерений, `size` — их размеры, `dimension.<d>.category.index`
— код → позиция, `value` — словарь «плоский номер → значение» (пропуски не пишутся).

Ключ: `nuts/<код NUTS>/<показатель>[.<код измерения>]/<период>`; период — год или ГГГГ-ММ.
В tour_occ_nin2m год хранится в `time`, месяц — отдельно в `month` (M01–M12).
Их объединяем в период; `month=TOTAL` — годовой итог, в месячный ряд не входит.
Лицензия Eurostat — CC BY 4.0.
"""

from __future__ import annotations

import gzip
import itertools
import json

from ..store import Fact

WHO = "parser:eurostat_json@2"


def _period(p: str, month: str | None = None) -> tuple[str, str] | None:
    p = p.strip()
    if month is not None:
        # У регионального туризма freq=A, хотя наблюдение относится к месяцу.
        # TOTAL нельзя принять за январь или добавить к тем же месячным ключам.
        if (len(p) != 4 or not p.isdigit() or len(month) != 3 or month[0] != "M"
                or not month[1:].isdigit() or not 1 <= int(month[1:]) <= 12):
            return None
        p = f"{p}-{month[1:]}"
    if len(p) == 4 and p.isdigit():
        return p, f"{p}-01-01"
    if len(p) == 7 and p[4] in "-M" and p[:4].isdigit() and p[5:].isdigit():
        return f"{p[:4]}-{p[5:]}", f"{p[:4]}-{p[5:]}-01"
    return None


def decode(d: dict):
    """(словарь измерение → код, значение) по каждому непустому числу JSON-stat."""
    ids, size = d["id"], d["size"]
    codes = []
    for dim in ids:
        idx = d["dimension"][dim]["category"]["index"]
        if isinstance(idx, dict):
            arr = [None] * len(idx)
            for k, p in idx.items():
                arr[p] = k
        else:
            arr = list(idx)
        codes.append(arr)
    vals = d.get("value") or {}
    if isinstance(vals, list):
        vals = {str(i): v for i, v in enumerate(vals) if v is not None}
    mult = [1] * len(size)
    for i in range(len(size) - 2, -1, -1):
        mult[i] = mult[i + 1] * size[i + 1]
    for k, v in vals.items():
        if v is None:
            continue
        n, pos = int(k), {}
        for i, dim in enumerate(ids):
            pos[dim] = codes[i][(n // mult[i]) % size[i]]
        yield pos, float(v)


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    d = json.loads(blob)
    if "id" not in d or "value" not in d:
        raise ValueError(f"не JSON-stat: {str(d)[:300]}")
    ind = ctx.get("indicator") or ctx["source_id"]
    want = ctx.get("dims") or {}
    unit = ctx.get("unit_text")
    fixed = {"geo", "time", "freq", "month"}
    out, seen = [], set()
    for pos, v in decode(d):
        per = _period(str(pos.get("time", "")), pos.get("month"))
        geo = pos.get("geo")
        if not per or not geo:
            continue
        tag = []
        skip = False
        for dim, code in pos.items():
            if dim in fixed:
                continue
            if dim in want:
                if code not in want[dim]:
                    skip = True
                    break
                if len(want[dim]) > 1:
                    tag.append(code)
            elif d["size"][d["id"].index(dim)] > 1:
                skip = True             # измерение не отфильтровано адресом и не названо — не угадываем
                break
        if skip:
            continue
        name = ind + ("." + ".".join(tag) if tag else "")
        key = f"nuts/{geo}/{name}/{per[0]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(Fact(domain="macro", key=key, valid_from=per[1], value=v, unit=unit,
                        source_id=ctx["source_id"], artifact_sha=ctx.get("sha"), extracted_by=WHO,
                        node=ctx.get("node"), note=f"Eurostat {d.get('label') or ''}".strip()))
    if not out:
        multi = [f"{x}({s})" for x, s in zip(d["id"], d["size"]) if s > 1 and x not in fixed]
        raise ValueError(f"ни одного значения: измерения без фильтра {multi} — уточните адрес или dims")
    ctx.setdefault("summary", []).append(
        f"{ind}: значений {len(out)}, регионов {len({f.key.split('/')[1] for f in out})}, "
        f"периоды {min(f.key.rsplit('/', 1)[1] for f in out)}–{max(f.key.rsplit('/', 1)[1] for f in out)}")
    return out
