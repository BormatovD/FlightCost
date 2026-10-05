"""Полнота документа против корпуса, а не только внутри него.

`coverage_check` смотрит внутрь строки: статья различает значения условия,
но покрыты не все. Отсутствия строки целиком он не видит — покрывать
нечего, и все проверки проходят. Так тариф Дохи одиннадцать лет лежал без
пассажирских сборов вовсе: занижение в одиннадцать раз, ни одного
предупреждения.

Корпус это видит. Набор кодов статей узок и почти универсален, поэтому
аэропорт без почти-универсальной статьи — кандидат в пропуск.

Свойство, редкое для этого проекта: чем больше аэропортов, тем проверка
сильнее. Почти всё остальное с ростом объёма шумит.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    icao: str
    code: str
    present_at: int      # у скольких аэропортов корпуса статья есть
    absent_at: int       # у скольких нет
    peers: list          # у кого ещё нет — чтобы видеть, выброс это или полоса


def check_corpus(by_airport: dict[str, set], resolved: dict[str, set],
                 *, max_absent: int = 1) -> list[Candidate]:
    """Статьи, присутствующие почти у всех и отсутствующие у одного.

    `by_airport`   — {ИКАО: множество кодов статей}.
    `resolved`     — {ИКАО: коды, объявленные неприменимыми с доводом}.
    `max_absent`   — сколько аэропортов могут не иметь статью, чтобы она
                     ещё считалась почти-универсальной.

    Порог задан ЧИСЛОМ, а не долей, сознательно: на четырнадцати
    документах и на ста «почти все» — разные вещи, и доля молча меняет
    строгость при росте корпуса. Число меняет только человек.

    Сигнал даёт почти-универсальная статья, а не просто частая. При
    отсутствии у одного из четырнадцати это выброс; при отсутствии у
    четырёх — распределение, и строки в отчёте быть не должно.

    Разрешённый кандидат не всплывает заново: иначе список будет вечно
    содержать известное, и его перестанут читать (решение 57).

    Проверка не превращается в требование: аэропорт не обязан иметь все
    статьи, отчёт называет кандидатов, решает человек (решение 4).
    """
    codes: dict[str, set] = {}
    for icao, cs in by_airport.items():
        for c in cs:
            codes.setdefault(c, set()).add(icao)
    out = []
    everyone = set(by_airport)
    for code, present in sorted(codes.items()):
        absent = everyone - present
        if not absent or len(absent) > max_absent:
            continue
        for icao in sorted(absent):
            if code in resolved.get(icao, set()):
                continue
            out.append(Candidate(icao=icao, code=code, present_at=len(present),
                                 absent_at=len(absent), peers=sorted(absent - {icao})))
    return sorted(out, key=lambda c: (-c.present_at, c.icao))


def from_facts(store, domain: str = "airport_charge", as_of=None):
    """Корпус из хранилища: {ИКАО: коды} и {ИКАО: разрешённые коды}."""
    by, res = {}, {}
    for key, row in store.current(domain, as_of).items():
        parts = key.split("/")
        # В корпус входят только аэропорты. Общегосударственная статья
        # ключуется двухбуквенным кодом государства (`LI/...`) или парой
        # (`LI:LICC/...`), и без этого отбора она выглядела бы аэропортом,
        # у которого нет ничего, кроме надбавки. Проверено: она не только
        # давала ложного кандидата, но и МАСКИРОВАЛА настоящего — статья
        # landing отсутствовала уже у двоих и переставала быть
        # почти-универсальной.
        if len(parts) < 2 or len(parts[0]) != 4 or parts[0].startswith("_"):
            continue
        icao, code = parts[0], parts[1]
        if code == "_na":
            res.setdefault(icao, set()).add(parts[2])
            by.setdefault(icao, set())
        elif not code.startswith("_"):
            by.setdefault(icao, set()).add(code)
    return by, res
