"""EUROCONTROL: терминальные ставки аэронавигации по тарифным зонам (TCZ).

Отдельная статья от аэропортовых сборов: это плата за диспетчерское
обслуживание захода и в районе аэродрома, а не за пользование
инфраструктурой аэропорта. Взимает EUROCONTROL, а не оператор аэропорта.

Публикуется одной годовой таблицей на 26 зон. Машиночитаемой версии, в
отличие от en-route, нет — но PDF извлекается в текст чисто, а строк
всего два десятка, поэтому парсер детерминированный.

Формат строки: <зона> <число аэропортов> <валюта> <ставка>
    Germany 15 EUR 365.18
    Czech Republic 1 CZK 6 800.00       <- пробел как разделитель тысяч
    Belgium Brussels3, 4 1 EUR 302.32   <- сноски приклеены к названию

Ставка в национальной валюте: пересчёт делается при расчёте, по курсу из
домена fx. Здесь валюта сохраняется как есть — переводить на этапе
разбора значит потерять исходное значение.

Распределение аэропортов по зонам НЕ парсится: в приложении PDF порядок
строк при извлечении разъезжается (метки «France Zone 1» оказываются
после списка), и надёжно связать аэродром с зоной автоматически нельзя.
Для нужных аэропортов связь ведётся вручную в config/tcz.yaml — это
ярус 1 той же трёхъярусной схемы, что и для аэропортовых сборов.
"""

from __future__ import annotations

import io
import re

from ..store import Fact

ROW = re.compile(
    r"^(?P<zone>.+?)\s+(?P<n>\d{1,3})\s+(?P<cur>[A-Z]{3})\s+"
    r"(?P<val>[\d\s]+[.,]\d{2})\s*$"
)
ZONE_NO = re.compile(r"zone\s*\d+$", re.I)      # «France zone 2» — часть ключа
FOOTNOTE = re.compile(r"\d+(?:\s*,\s*\d+)*$")   # «Brussels3, 4» — мусор
YEAR = re.compile(r"applicable from\s+1\s+JANUARY\s+(\d{4})", re.I)


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    text = _text(blob)
    m = YEAR.search(text)
    year = int(m.group(1)) if m else None
    if not year:
        # Диагностика важнее сообщения: парсер писался на текст, извлечённый
        # одним инструментом, а работает на тексте от другого (pypdf). Если
        # извлечение поехало, надо видеть ЧТО он прочитал, а не только что
        # не нашёл.
        head = " | ".join(l.strip() for l in text.splitlines()[:8] if l.strip())
        raise ValueError(
            f"не найдена дата вступления в силу. Извлечено {len(text)} символов, "
            f"начало: {head[:200] or '(пусто — pypdf не установлен?)'}")
    vfrom, vto = f"{year}-01-01", f"{year + 1}-01-01"

    facts: list[Fact] = []
    for line in _joined(text):
        m = ROW.match(line)
        if not m:
            continue
        zone = _clean_zone(m.group("zone"))
        if not zone:
            continue
        val = float(m.group("val").replace(" ", "").replace(",", "."))
        facts.append(Fact(
            domain="terminal_rate", key=zone, valid_from=vfrom, valid_to=vto,
            value=val, unit="per_service_unit", currency=m.group("cur"),
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by="parser:crco_terminal@1", confidence="exact",
            note=f"{m.group('n')} аэродромов в зоне",
        ))
    if len(facts) < 10:
        got = ", ".join(f.key for f in facts[:6]) or "ничего"
        raise ValueError(
            f"разобрано {len(facts)} зон из ожидаемых 26 ({got}). "
            f"Скорее всего извлечение PDF дало другую разбивку строк — "
            f"сохрани артефакт из data/raw/ и посмотри глазами")
    return facts


def _joined(text: str):
    """Склейка разорванных строк.

    В извлечённом тексте название зоны иногда отрывается от своих чисел:
    «Luxembourg3» на одной строке, «1 EUR 309.81» на следующей. Без
    склейки такая зона молча пропадает — из 26 разбирается 25, и заметить
    это можно только пересчитав.
    """
    buf = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("terminal charging", "in 2026",
                                                "national", "currency", "tnc unit")):
            continue
        cand = f"{buf} {line}".strip() if buf else line
        if ROW.match(cand):
            yield cand
            buf = ""
        elif re.fullmatch(r"[A-Za-z][A-Za-z .\-/]*\d*", line):
            buf = line          # похоже на название без чисел — ждём продолжения
        else:
            buf = ""


def _clean_zone(raw: str) -> str:
    """Сноски отрезать, номер зоны сохранить.

    «Belgium Brussels3, 4» -> «Belgium Brussels», но «Romania zone 2»
    обязано остаться с номером: у Румынии три зоны с разными ставками, и
    без номера все три схлопнутся в один ключ, перезаписав друг друга.
    """
    z = re.sub(r"\s+", " ", raw).strip()
    if not ZONE_NO.search(z):
        z = FOOTNOTE.sub("", z).strip()
    z = re.sub(r"(?<=[a-z])\d+$", "", z).strip()
    # Хвост шапки таблицы прилипает к первой строке данных: извлечение PDF
    # не различает конец заголовка и начало тела.
    z = re.sub(r"^.*?(NC\)?\d*|in NC\d*)\s+", "", z, flags=re.I).strip()
    return z.title() if z and z[0].isalpha() else ""


def _text(blob: bytes) -> str:
    if blob[:4] == b"%PDF":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(blob)).pages)
    return blob.decode("utf-8", errors="replace")
