"""Проверка файла тарифа: разбор парсером проекта + контрольный оборот A320.

    python3 check.py ../out/LFPG-2026.json [--ac A320] [--pax 148] [--from EDDF]

1. Парсер `airport_charges` (тот же, что `fca refresh`): ошибки схемы, отвергнутые
   правила, предупреждения.
2. Контрольный оборот: рейс EDDF → аэропорт, A320 78 т, 148 пасс., июль. Печатает
   строки сборов аэропорта (EUR), сумму и пропуски (что не начислено и почему).
   Коридоры за оборот A320: Европа ~3 500–6 500 EUR, СНГ 1 400–3 000, Залив и Индия
   заметно ниже, Африка — широкий разброс; вылет за коридор почти всегда — ошибка в
   признаке начисления (landing/movement/turnaround) или в разряде числа.

Курсы валют в проверочной базе ПРИБЛИЗИТЕЛЬНЫЕ (только для коридора), в данные не идут.
"""
import argparse, json, os, shutil, sys, tempfile
GH = "/tmp/claude-0/-home-claude/b0fbc39f-7d96-5983-bd3c-73a271730072/scratchpad/gh3"
BASE = "/tmp/claude-0/-home-claude/b0fbc39f-7d96-5983-bd3c-73a271730072/scratchpad/charges/check_base.db"
sys.path.insert(0, GH)
import yaml                                                    # noqa: E402
from flightcostapp.store import Store, Fact                    # noqa: E402
from flightcostapp.parsers import airport_charges              # noqa: E402

FX = {"GBP": 0.855, "USD": 1.08, "INR": 93.0, "ZAR": 20.0, "EGP": 53.0, "KES": 140.0, "NGN": 1700.0,
      "MAD": 10.9, "DZD": 146.0, "TND": 3.35, "GHS": 16.5, "XOF": 655.957, "XAF": 655.957, "ETB": 155.0,
      "CHF": 0.94, "DKK": 7.46, "NOK": 11.7, "SEK": 11.2, "TRY": 44.0, "PLN": 4.27, "CZK": 24.9,
      "HUF": 395.0, "RON": 5.0, "ISK": 150.0, "CNY": 7.8, "AED": 3.97, "SAR": 4.05, "QAR": 3.93,
      "TZS": 2900.0, "UGX": 4000.0, "RWF": 1550.0, "MUR": 50.0, "AOA": 1000.0, "ZMW": 29.0,
      "BWP": 14.7, "NAD": 20.0, "MZN": 69.0, "SCR": 15.5, "LKR": 330.0, "NPR": 150.0, "BDT": 130.0,
      "PKR": 300.0, "JPY": 165.0, "KZT": 520.0, "RUB": 95.0, "BGN": 1.956, "RSD": 117.0}


def base_db():
    if not os.path.exists(BASE):
        shutil.copy(GH + "/../seo/full.db", BASE)
        st = Store(BASE)
        st.commit_facts([Fact(domain="fx", key=c, valid_from="2026-01-01", value=v, unit="per_EUR",
                              source_id="fx_declared", extracted_by="check_only") for c, v in FX.items()])
        st.db.close()
    return BASE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--ac", default="A320"); ap.add_argument("--pax", type=int, default=148)
    ap.add_argument("--from", dest="orig", default="EDDF"); ap.add_argument("--month", type=int, default=7)
    a = ap.parse_args()
    blob = open(a.file, "rb").read()
    ctx = {"source_id": "airport_charges_tier1", "extracted_by": "check", "node": "src_airport_tariff"}
    try:
        facts = airport_charges.parse(blob, ctx)
    except Exception as exc:                                   # noqa: BLE001
        print("ПАРСЕР ОТВЕРГ ФАЙЛ:", exc); print("\n".join(ctx.get("rejected", []))); sys.exit(1)
    for k in ("rejected", "warnings", "summary"):
        for x in ctx.get(k, []) or []:
            print(f"[{k}] {x}")
    icao = json.loads(blob)["icao"] if blob.strip().startswith(b"{") else None
    tmp = tempfile.mktemp(suffix=".db"); shutil.copy(base_db(), tmp)
    try:
        st = Store(tmp)
        # Уже заведённый тариф этого аэропорта в проверочной базе убрать: иначе
        # старые и новые строки сложатся, и оборот выйдет двойным.
        st.db.execute("DELETE FROM facts WHERE domain='airport_charge' AND key LIKE ?", (icao + "/%",))
        st.db.commit()
        st.commit_facts(facts)
        from flightcostapp import serve as S
        from flightcostapp.econ import route_economics
        c = S.Context(st, yaml.safe_load(open(GH + "/flightcostapp/registry.yaml")))
        seats = 170
        res = route_economics(st, c.resolve(a.orig), c.resolve(icao), aircraft=a.ac, load_factor=a.pax / seats,
                              month=a.month)
        j = S.result_json(res)
        lines = {k: v for k, v in (j.get("charge_lines") or {}).items() if k.startswith(icao + "/")}
        tot = sum(lines.values())
        print(f"\nКонтрольный оборот {a.ac}, {a.pax} пасс., из {a.orig}, месяц {a.month}: {icao} = {tot:,.0f} EUR")
        for k, v in sorted(lines.items(), key=lambda x: -x[1]):
            print(f"  {k:32s} {v:10,.2f}")
        g = (j.get("charge_gaps") or {}).get(icao)
        if g:
            print(f"  правил-кодов {g['total_codes']}, начислено {len(g['priced_codes'])}; не начислено: {g['lost_codes']}"
                  f"; частично: {g['partial_codes']}; не хватает данных типа: {g['missing_data']}; "
                  f"ввода: {g['missing_input']}; валюты: {g['currencies']}")
        for w in j.get("warnings", []):
            if icao in w:
                print("  ! " + w)
    finally:
        os.remove(tmp)


if __name__ == "__main__":
    main()
