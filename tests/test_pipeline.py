"""Прогон конвейера на фикстурах, без сети.

Фикстура ставок — настоящий опубликованный файл CRCO, не выдуманные
числа. Отсюда правило, которому подчинён весь этот тест: **не проверять
внешние данные на равенство**. Количество зон, номер месяца и курсы
валют меняются при каждом обновлении источника, и тест, зашивший их
константами, ломается на первом же свежем файле, ничего при этом не
обнаружив.

Проверяются свойства, которые обязаны выполняться в любом месяце:
структура разбора, разделение доменов, замкнутость интервалов действия,
срабатывание гейта на порче данных.

Файл фикстуры берётся любой из tests/fixtures/ur-*.txt, дата прогона
выводится из него самого.
"""
import datetime, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp.store import Store
from flightcostapp.refresh import load_registry, refresh_source, plan_due
from flightcostapp.econ import route_economics
from flightcostapp.validate import freshness_report
from flightcostapp.graph import check_against_trace
from flightcostapp.parsers.crco_enroute import parse as parse_rates

FIX = pathlib.Path(__file__).parent / "fixtures"
fixtures = sorted(FIX.glob("ur-*.txt"))
if not fixtures:
    sys.exit("нет фикстуры: положи файл ставок CRCO в tests/fixtures/ur-<год>-<мес>.txt")
RATES_FILE = fixtures[-1]                      # самый свежий
RATES = RATES_FILE.read_bytes()

AIRPORTS = b"""id,ident,type,name,latitude_deg,longitude_deg,iso_country,iata_code
1,EDDF,large_airport,Frankfurt am Main,50.026421,8.543125,DE,FRA
2,LEBL,large_airport,Barcelona El Prat,41.297078,2.078464,ES,BCN
3,GCLP,large_airport,Gran Canaria,27.9319,-15.3866,ES,LPA
"""

# --- дата прогона выводится из самой фикстуры, а не зашита -------------
probe = parse_rates(RATES, {"source_id": "x"})
rates_probe = [f for f in probe if f.domain == "enroute_rate"]
VFROM = min(f.valid_from for f in rates_probe)
VTO = max(f.valid_to for f in rates_probe)
DAY = datetime.date.fromisoformat(VFROM) + datetime.timedelta(days=14)

# порча: сдвиг десятичной точки в первой строке с данными
first_val = rates_probe[0].value
BROKEN = RATES.replace(f"\t{int(first_val * 100)}\t".encode(),
                       f"\t{int(first_val * 10000)}\t".encode(), 1)
SHORT = b"\n".join(RATES.split(b"\n")[:4])     # оборванная закачка

fails = []
def ok(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        fails.append(label)

fetch = lambda blob: (lambda url, timeout=60: (blob, "text/plain"))

store = Store(pathlib.Path(tempfile.mkdtemp()) / "t.db")
reg = load_registry()
reg["sources"]["ourairports"]["validators"]["row_count_min"] = 1
reg["sources"]["crco_enroute_rates"]["validators"]["row_count_min"] = 10

print(f"фикстура: {RATES_FILE.name}, действует {VFROM} … {VTO}, "
      f"прогон на {DAY}")

print("\n== источники к обновлению на чистой базе ==")
print(" ", plan_due(reg, store))

print("\n== детерминированный контур: аэропорты ==")
r = refresh_source("ourairports", reg, store, fetch=fetch(AIRPORTS), today=DAY)
ok(f"первый прогон -> {r['outcome']}, {r['stats'].get('added')} фактов",
   r["outcome"] == "committed")
r = refresh_source("ourairports", reg, store, fetch=fetch(AIRPORTS), today=DAY)
ok("повторный прогон -> unchanged, парсинг пропущен", r["outcome"] == "unchanged")

print("\n== ставки CRCO ==")
r = refresh_source("crco_enroute_rates", reg, store, fetch=fetch(RATES), today=DAY)
dom = r["stats"]["domains"]
ok(f"разобрано по доменам: {dom}",
   dom.get("enroute_rate", 0) >= 10 and dom.get("fx", 0) >= 1)
ok(f"чистые данные приняты без ревью -> {r['outcome']}", r["outcome"] == "committed")

de = store.value("enroute_rate", "ED", DAY)
le = store.value("enroute_rate", "LE", DAY)
gc = store.value("enroute_rate", "GC", DAY)
ok(f"Германия найдена по зоне ED: {de} EUR/SU", de is not None and 20 < de < 300)
ok(f"у Испании две зоны: LE {le} != GC {gc}",
   le is not None and gc is not None and le != gc)
chf = store.value("fx", "CHF", DAY)
ok(f"курс франка ушёл в домен fx, а не в ставки: {chf}",
   chf is not None and 0.5 < chf < 2.0)
ok("интервал замкнут: на следующий день после конца ставки нет",
   store.value("enroute_rate", "ED", VTO) is None)

print("\n== гейт ==")
r = refresh_source("crco_enroute_rates", reg, store, fetch=fetch(BROKEN), today=DAY)
ok(f"сдвиг десятичной точки отвергнут -> {r['outcome']}", r["outcome"] == "rejected")
r = refresh_source("crco_enroute_rates", reg, store, fetch=fetch(SHORT), today=DAY)
ok(f"оборванный файл отвергнут -> {r['outcome']}", r["outcome"] == "rejected")

# Скачок ставки в следующем месяце. Проверка неочевидная: интервал у
# помесячных источников истекает ровно тогда, когда начинается новый,
# поэтому наивный поиск предыдущего значения «на дату нового» ничего не
# находит и сравнение молча не выполняется.
nxt = datetime.date.fromisoformat(VTO)
JUMPED = (RATES.replace(VFROM.replace("-", "/").encode(),
                        f"{nxt:%Y/%m/%d}".encode())
               .replace(f"\t{int(first_val * 100)}\t".encode(),
                        f"\t{int(first_val * 160)}\t".encode(), 1))
r = refresh_source("crco_enroute_rates", reg, store, fetch=fetch(JUMPED),
                   today=nxt + datetime.timedelta(days=14))
ok(f"скачок ставки на +60% поднят до ревью -> {r['outcome']}",
   r["outcome"] == "proposal"
   and any(f["code"] == "delta.jump" for f in r["findings"]))

print("\n== справочник ВС ==")
r = refresh_source("aircraft_openap", reg, store, today=DAY)
ok(f"загружен из openap -> {r['outcome']}, {r['stats'].get('added')} фактов",
   r["outcome"] == "committed" and r["stats"].get("added", 0) > 300)
from flightcostapp.econ import load_aircraft
a = load_aircraft(store, "A320", DAY)
ok(f"A320: {a.seats} кресел, MTOW {a.mtow_t} т, {a.cruise_kt:.0f} kt",
   abs(a.mtow_t - 78.0) < 0.1 and 150 <= a.seats <= 200)
r = refresh_source("fleet_reference", reg, store, today=DAY)
if r.get("proposal_id"):
    store.resolve_proposal(r["proposal_id"], True, "сверено")
ok(f"компоновки и массы пассажира загружены: {r['stats'].get('n_facts')} фактов",
   r["outcome"] in ("committed", "proposal"))
ok("компоновка перевозчика перекрывает типовую",
   load_aircraft(store, "A320", DAY, "U2").seats
   != load_aircraft(store, "A320", DAY).seats)
from flightcostapp.parsers.ourairports_runways import parse as parse_rwy
store.commit_facts(parse_rwy((FIX / "runways.csv").read_bytes(),
                             {"source_id": "ourairports_runways",
                              "today": VFROM}))
from flightcostapp.fuel import required_runway_m
ok(f"полоса EGLC {store.value('airport_limits','EGLC/runway_length_m',DAY):,.0f} м "
   f"меньше потребных {required_runway_m(78.0):,.0f} м для A320",
   store.value("airport_limits", "EGLC/runway_length_m", DAY)
   < required_runway_m(78.0))
try:
    load_aircraft(store, "ZZZZ", DAY)
    ok("неизвестный тип отвергнут", False)
except KeyError as e:
    ok(f"неизвестный тип отвергнут с подсказкой", "нет в справочнике" in str(e))

print("\n== выполнимость рейса ==")
from flightcostapp.fuel import trip_fuel
near, far = trip_fuel("A320", 590, 148), trip_fuel("A320", 5551, 148)
ok("ближнее плечо выполнимо", near.feasible.ok)
ok(f"дальнее отвергнуто: {far.feasible.reasons[0][:60] if far.feasible.reasons else ''}",
   not far.feasible.ok and far.feasible.max_pax < 148)

print("\n== терминальные ставки ==")
from flightcostapp.parsers.crco_terminal import parse as parse_term
TERM = (FIX / "terminal-2026.txt").read_bytes()
r = refresh_source("crco_terminal_rates", reg, store, fetch=fetch(TERM), today=DAY)
if r["outcome"] == "proposal":
    store.resolve_proposal(r["proposal_id"], True, "сверено")
zones = store.current("terminal_rate", DAY)
ok(f"разобрано зон: {len(zones)}", len(zones) >= 20)
ok("номер зоны сохранён: у Румынии три разные ставки",
   len({store.value("terminal_rate", f"Romania Zone {i}", DAY) for i in (1, 2, 3)}) == 3)
ok(f"Испания {store.value('terminal_rate','Spain',DAY)} != "
   f"Германия {store.value('terminal_rate','Germany',DAY)}",
   store.value("terminal_rate", "Spain", DAY) != store.value("terminal_rate", "Germany", DAY))

print("\n== расчёт ==")
res = route_economics(store, "FRA", "BCN", load_factor=0.82, fare_eur=95,
                      as_of=DAY.isoformat(), freshness=freshness_report(store, reg))
ok("ставка найдена по зоне ИКАО, а не по коду страны",
   not any("нет ставок" in w for w in res.warnings))
ok("карта данных покрывает трассировку", not check_against_trace(res))
ok("протухшие источники помечены", res.degraded)

print("\n== обращение расчёта ==")
from flightcostapp.solve import solve
# Тариф выше безубыточного: обращение ищет ПРЕДЕЛЬНУЮ ставку лизинга, и
# смысл проверки — что она выше текущей. При 110 маршрут стал убыточным,
# когда терминальный сбор начал считаться на обоих концах (+499 EUR на
# Франкфурте), и порог ушёл под текущую ставку — это не дефект обращения.
base = dict(aircraft="A320", load_factor=0.82, fare_eur=125,
            as_of=DAY.isoformat())
sol = solve(store, "FRA", "BCN", param="fare", base_kwargs=base)
direct = route_economics(store, "FRA", "BCN", load_factor=0.82, fare_eur=125,
                         as_of=DAY.isoformat()).breakeven_fare_eur
ok(f"обратный расчёт по тарифу сходится с прямым: "
   f"{sol.value:.2f} против {direct:.2f}",
   sol.ok and abs(sol.value - direct) < 0.5)
sol = solve(store, "FRA", "BCN", param="fleet_economics.A320.lease_eur_month",
            base_kwargs=base)
ok(f"предельная ставка лизинга найдена: {sol.value:,.0f} EUR/мес при "
   f"текущих {sol.baseline:,.0f}", sol.ok and sol.value > sol.baseline)

# Цена топлива — прямой параметр обращения. Тариф выше безубыточного:
# порог по цене лежит ВЫШЕ текущей, иначе это не порог, а дефект.
sol = solve(store, "FRA", "BCN", param="fuel", base_kwargs=base)
ok(f"порог по цене топлива найден: {sol.value:.3f} EUR/кг при текущих "
   f"{(sol.baseline or 0):.3f}", sol.ok and sol.baseline and sol.value > sol.baseline)

print("\n== витрина: сервер ==")
from flightcostapp.serve import Context
from flightcostapp.solve import margins
ctx = Context(store, reg)
# Один разбор параметров на маршрут и порог: месяц и --set обязаны
# доезжать до `base_kwargs` (ловушка `--month` из ROADMAP).
kw = ctx._kwargs({"month": "7", "fare": "125", "lf": "0.82",
                  "set": "fleet_economics.A320.lease_eur_month=250000"})
ok("месяц и --set доезжают до аргументов ядра",
   kw["month"] == 7 and kw["fare_eur"] == 125.0
   and kw.get("overrides") and any("lease" in str(k) for k in kw["overrides"]))
rows = margins(store, "FRA", "BCN", dict(base, month=7), "A320")
ok("в запасе прочности семь строк, среди них цена топлива",
   len(rows) == 7 and any(r["param"] == "fuel" for r in rows))
ok("у каждой строки статус из трёх", all(r["status"] in ("ok", "unreachable", "failed")
                                        for r in rows))
# Кресла рейсом старше компоновки и идут в трассировку как ввод.
r150 = route_economics(store, "FRA", "BCN", seats=150, load_factor=0.82,
                       fare_eur=125, as_of=DAY.isoformat())
st = next((x for x in r150.trace if x.label == "Кресел"), None)
ok("заданные кресла доезжают до расчёта с провенансом input",
   r150.inputs["seats"] == 150 and st is not None and st.prov == "input"
   and st.formula == "задано")
ok("витрина передаёт кресла в ядро",
   ctx._kwargs({"seats": "186"})["seats"] == 186 and ctx._kwargs({})["seats"] is None)
acs = ctx.aircraft()
a320 = next((a for a in acs if a["icao"] == "A320"), None)
ok(f"типы ВС читаются из хранилища: {len(acs)}, A320 среди них",
   a320 is not None and a320["usable"])
ok("у типа названо, есть ли физика (три состояния, не два)",
   all(a["physics"] in (True, False, None) for a in acs))
from flightcostapp import inventory
store.registry = reg
inv = inventory.collect(store, DAY.isoformat())
held = {d["domain"]: d for d in inv["domains"] if d.get("holds")}
ok("домены без фактов показаны состоянием хранилища, а не нулём",
   all(d["holds"]["state"] in ("unknown", "empty", "stale", "live") for d in held.values()))

print(f"\n{res.report()}")
if fails:
    print(f"\nпровалено проверок: {len(fails)}")
    sys.exit(1)
print("\nвсе проверки пройдены")
