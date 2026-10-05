#!/usr/bin/env python3
"""Перевод словаря `dest` в тарифных файлах на четырёхступенчатую шкалу.

    было:  EU · Europe_non_EU · intercontinental
    стало: schengen · eu_non_schengen · europe_non_eu · intercontinental

ЭТО НЕ ЗАМЕНА СТРОКИ. `Europe_non_EU` переименовывается один в один, а
`EU` РАСЩЕПЛЯЕТСЯ НА ДВА ПРАВИЛА с той же ставкой: у Франкфурта примечание
к §1.3.2 говорит «ЕС + IS/LI/NO/CH», то есть строка покрывает и шенгенские
государства, и Ирландию с Кипром — они в ЕС, но вне Шенгена. Одно значение
новой шкалы этого не выражает.

Расщепление — наше прочтение документа, а не его буква (решение 42),
поэтому в каждое порождённое правило кладётся довод: через полгода
останется файл, а не разговор.

Скрипт НИЧЕГО НЕ РЕШАЕТ ЗА ВАС. Он показывает, что собирается сделать, и
меняет файлы только с ключом --apply. Перед этим откройте примечание
каждого правила: если у аэропорта «EU» означает что-то другое —
например, только Шенген, — расщепление будет неверным, и правило надо
править руками.

    python3 tools/migrate_dest.py                 # показать
    python3 tools/migrate_dest.py --apply         # применить, с .bak
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

# Прочтение, на котором держится расщепление. Записано здесь, чтобы его
# можно было оспорить, а не искать в истории команд.
SPLIT = {
    "EU": (
        ["schengen", "eu_non_schengen"],
        "строка «ЕС» в тарифе покрывает и шенгенские государства, и "
        "Ирландию с Кипром: они в ЕС и вне Шенгена. В четырёхступенчатой "
        "шкале это два значения с одной ставкой",
    ),
}
RENAME = {
    "Europe_non_EU": "europe_non_eu",
    "europe_non_EU": "europe_non_eu",
    "EEA": "schengen",          # встречается у части документов как синоним
}
ALLOWED = {"schengen", "eu_non_schengen", "europe_non_eu", "intercontinental"}


def migrate_rules(rules: list[dict]) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    log: list[str] = []
    for r in rules:
        dest = (r.get("when") or {}).get("dest")
        if dest is None or dest in ALLOWED:
            out.append(r)
            continue
        if dest in RENAME:
            new = dict(r, when=dict(r["when"], dest=RENAME[dest]))
            log.append(f"    {r.get('code')}: dest {dest} -> {RENAME[dest]}"
                       f"  (ставка {r.get('rate')})")
            out.append(new)
            continue
        if dest in SPLIT:
            targets, why = SPLIT[dest]
            for t in targets:
                new = dict(r, when=dict(r["when"], dest=t))
                note = (new.get("source_note") or "").strip()
                # Довод расщепления едет в файл рядом с исходным
                # примечанием, а не вместо него: одно говорит, что
                # написано в документе, другое — что мы из этого вывели.
                new["source_note"] = (note + " | " if note else "") + \
                    f"расщеплено из dest={dest}: {why}"
                out.append(new)
            log.append(f"    {r.get('code')}: dest {dest} -> "
                       f"{' + '.join(targets)}, ставка {r.get('rate')} у обоих")
            continue
        log.append(f"    !! {r.get('code')}: dest {dest!r} — правила перевода "
                   f"нет, оставлено как есть, файл не разберётся")
        out.append(r)
    return out, log


def equal_rates(rules: list[dict]) -> list[str]:
    """Правила, различающиеся ТОЛЬКО направлением, но с одной ставкой.

    Если «ЕС» и «Европа вне ЕС» стоят одинаково, то направление у этого
    аэропорта ничего не различает — и условие `dest`, скорее всего,
    приписано нами при разборе, а тариф режет шкалу по чему-то другому.
    У Вены это дальность плеча, а не клуб.

    Не отказ: одинаковые ставки бывают. Но перечитать документ стоит,
    потому что лишнее условие — это правило, которое однажды не сработает
    там, где должно.
    """
    seen: dict[tuple, list] = {}
    for r in rules:
        when = dict(r.get("when") or {})
        dest = when.pop("dest", None)
        if dest is None:
            continue
        k = (r.get("code"), r.get("base"), json.dumps(when, sort_keys=True))
        seen.setdefault(k, []).append((dest, r.get("rate")))
    out = []
    for (code, _base, _w), items in seen.items():
        rates = {x[1] for x in items}
        if len(items) > 1 and len(rates) == 1:
            out.append(f"    ? {code}: {len(items)} направления с одной "
                       f"ставкой {items[0][1]} — условие dest ничего не "
                       f"различает, перечитайте документ")
    return out


def process(path: pathlib.Path, apply: bool) -> bool:
    doc = json.loads(path.read_text(encoding="utf-8"))
    warn = equal_rates(doc.get("rules") or [])
    touched = False
    lines: list[str] = []

    for block, label in [(doc.get("rules"), "rules")] + [
            (extra, f"airport_extra/{icao}")
            for icao, extra in (doc.get("airport_extra") or {}).items()]:
        if not block:
            continue
        new, log = migrate_rules(block)
        if log:
            touched = True
            lines.append(f"  {label}:")
            lines += log
            if label == "rules":
                doc["rules"] = new
            else:
                doc["airport_extra"][label.split("/", 1)[1]] = new

    if warn:
        lines += warn
        touched = True
    if not touched:
        return False
    print(f"\n{path.name}")
    print("\n".join(lines))
    if apply:
        shutil.copy(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"  записано, прежний файл в {path.name}.bak")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="data/charges")
    ap.add_argument("--apply", action="store_true",
                    help="изменить файлы (без ключа — только показать)")
    a = ap.parse_args()

    files = sorted(pathlib.Path(a.dir).glob("*.json"))
    if not files:
        print(f"в {a.dir} нет файлов разбора")
        return 2
    n = sum(process(p, a.apply) for p in files)
    print(f"\nзатронуто файлов: {n} из {len(files)}")
    if n and not a.apply:
        print("это был показ. применить: python3 tools/migrate_dest.py --apply")
        print("после применения:  fca refresh --only airport_charges_tier1 --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
