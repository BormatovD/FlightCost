"""Контрольный оборот A320 по ВСЕМ файлам тарифов data/charges → turnaround.json.

Тот же расчёт, что `check.py` для одного файла: рейс EDDF → аэропорт, A320 78 т,
148 пасс., июль; сумма строк сборов аэропорта назначения, EUR, по курсам
проверочной базы (приблизительным). Неофициальные данные сюда не входят —
только файлы с опубликованным документом.

    FCA_CHECK_DB=check_base.db python3 research/charges-2026-10/bin/turnaround.py
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402  — путь к репозиторию, проверочная база, курсы

from flightcostapp.econ import route_economics  # noqa: E402
from flightcostapp.parsers import airport_charges  # noqa: E402
from flightcostapp.store import Store  # noqa: E402
from flightcostapp import serve as S  # noqa: E402
import yaml  # noqa: E402

# Части оборота — по коду статьи (последняя часть ключа правила).
PART = (("pax", ("pax", "passenger", "psc", "udf", "terminal", "prm", "pmr", "transfer", "municipal", "tax",
                 "infra", "development", "adf", "pssc", "asf")),
        ("security", ("secur", "screen", "sicur", "avsec", "hbs", "baggage")),
        ("landing", ("land", "takeoff", "take_off", "movement", "noise", "emission", "nox", "co2", "approach")),
        ("parking", ("park", "stand", "bridge", "jet_bridge", "gate", "apron")))


RU = ("UU", "UL", "UN", "UR", "US", "UI", "UH", "UE", "UO", "UW")


def part(key: str) -> str:
    k = key.split("/", 1)[1].lower()
    for name, words in PART:
        if any(w in k for w in words):
            return name
    return "other"


def main():
    root = pathlib.Path(check.GH)
    files = sorted((root / "data" / "charges").glob("[A-Z]*.json"))
    base = check.base_db()
    reg = yaml.safe_load(open(root / "flightcostapp" / "registry.yaml"))
    out = {}
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        icao = d.get("icao")
        if not icao or len(icao) != 4:                       # общегосударственные статьи (LI-…)
            continue
        ctx = {"source_id": "airport_charges_tier1", "extracted_by": "check", "node": "src_airport_tariff"}
        try:
            facts = airport_charges.parse(f.read_bytes(), ctx)
        except Exception as exc:                             # noqa: BLE001
            out[icao] = {"file": f.name, "error": str(exc)}
            continue
        tmp = tempfile.mktemp(suffix=".db")
        shutil.copy(base, tmp)
        try:
            st = Store(tmp)
            st.db.execute("DELETE FROM facts WHERE domain='airport_charge' AND key LIKE ?", (icao + "/%",))
            st.db.commit()
            st.commit_facts(facts)
            c = S.Context(st, reg)
            # Российские прейскуранты часто только для российских эксплуатантов: для них
            # контрольный рейс — внутренний, из Шереметьева, российским перевозчиком (если
            # заведены только ставки для иностранных — как у всех, из Франкфурта).
            ru = icao[:2] in RU and any((r.get("when") or {}).get("operator") != "foreign" for r in d["rules"])
            orig = ("ULLI" if icao == "UUEE" else "UUEE") if ru else ("LEBL" if icao == "EDDF" else "EDDF")
            res = route_economics(st, c.resolve(orig), c.resolve(icao), aircraft="A320",
                                  load_factor=148 / 170, month=7)
            j = S.result_json(res)
            lines = {k: v for k, v in (j.get("charge_lines") or {}).items() if k.startswith(icao + "/")}
            parts = {}
            for k, v in lines.items():
                parts[part(k)] = round(parts.get(part(k), 0) + v, 1)
            g = (j.get("charge_gaps") or {}).get(icao) or {}
            out[icao] = {"file": f.name, "eur": round(sum(lines.values())), "parts": parts, "from": orig,
                         "scenario": "domestic_ru" if ru else "from_fra",
                         "not_charged": sorted(g.get("lost_codes") or []),
                         "missing_type_data": sorted(g.get("missing_data") or [])}
            st.db.close()
        except Exception as exc:                             # noqa: BLE001
            out[icao] = {"file": f.name, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            os.remove(tmp)
        print(icao, out[icao].get("eur", out[icao].get("error")), file=sys.stderr)
    doc = {"method": "Контрольный оборот: рейс из Франкфурта (EDDF), A320 78 т, 148 пасс., июль; сборы аэропорта "
                     "назначения за посадку, стоянку и вылет — расчётным ядром по файлам data/charges "
                     "(bin/turnaround.py). Курсы валют — приблизительные, только для сравнения. Неофициальные "
                     "данные не входят.",
           "airports": out}
    (HERE.parent / "turnaround.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
