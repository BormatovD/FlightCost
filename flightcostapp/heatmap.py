"""Тепловая карта сборов за аэронавигацию.

Метрика — стоимость пролёта ста морских миль выбранным типом. Она
сравнима между зонами независимо от их размера: зона Люксембурга и зона
Франции получают сопоставимые числа, хотя пересечь их стоит совершенно
разного. И она зависит от массы, поэтому переключатель типов не
украшение: там, где сбор берётся без учёта массы, карта при смене типа
не меняется вовсе, а в зоне EUROCONTROL — меняется как корень из массы.

Расчёт вынесен в браузер намеренно. Ставка и параметры формулы у зоны
неизменны, меняется только масса, поэтому пересчёт при переключении типа
— три умножения, и делать ради них новый файл незачем.

Проекция равнопромежуточная: широта и долгота ложатся на оси линейно.
Для карты сборов этого достаточно — она про величины, а не про площади,
а искажение к северу читается как привычная растянутость Скандинавии.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .navcharge import PRESETS
from .ui import style_tag

DEFAULT_BBOX = (-32.0, 25.0, 70.0, 72.0)     # запад, юг, восток, север


def _params(formula: str, cfg: dict, zone: str) -> dict:
    """Параметры формулы в виде, пригодном для пересчёта в браузере.

    Умолчания на EUROCONTROL здесь нет и быть не может. Формула — это
    правило EUROCONTROL, а не устройство мира (решение 43): Казахстан и
    Китай считают без учёта массы, США за морские мили. Опечатка в имени
    при умолчании дала бы зоне зависимость от массы, которой у неё нет,
    и карта осталась бы правдоподобной.
    """
    if formula == "custom":
        # `navcharge.charge` принимает custom: параметры целиком в cfg
        # поверх умолчаний Formula. Карта отвергала то, что расчёт
        # принимал, и падала на первой же российской зоне — то есть
        # `fca heatmap` не открывался вовсе, пока UU в кадре.
        from .navcharge import Formula
        base = Formula(**{k: v for k, v in cfg.items()
                          if k in Formula.__dataclass_fields__})
    else:
        base = PRESETS.get(formula)
    if base is None:
        raise KeyError(
            f"зона {zone}: формула {formula!r} неизвестна; известны "
            f"{', '.join(sorted(PRESETS))}")
    out = {"d_div": base.d_div, "d_unit": base.d_unit, "d_exp": base.d_exp,
           "m_div": base.m_div, "m_exp": base.m_exp,
           "bands": list(base.bands)}
    for k in out:
        if k in cfg:
            out[k] = cfg[k]
    return out


def build(store, as_of, zones_path: str | Path,
          bbox=DEFAULT_BBOX, simplify: float = 0.08) -> str:
    from shapely.geometry import shape, box
    from shapely.ops import unary_union

    data = json.loads(Path(zones_path).read_text(encoding="utf-8"))
    clip = box(*bbox)

    # Формулы: файл конфигурации, как и в расчёте
    # Раньше здесь стоял `except Exception: cfgs = {}`. При нечитаемом
    # файле ВСЕ зоны молча получали параметры EUROCONTROL, и карта
    # выглядела совершенно нормальной. Отказ построения честнее
    # правдоподобной карты (решение 37).
    import yaml
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "nav_zones.yaml"
    cfgs = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}) \
        .get("zones", {}) or {}

    # Один контур на зону: полигоны FIR и UIR перекрываются по высоте,
    # а на карте нужен горизонтальный след.
    merged: dict[str, list] = {}
    names: dict[str, str] = {}
    for z in data["zones"]:
        g = shape(z["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        g = g.intersection(clip)
        if g.is_empty:
            continue
        merged.setdefault(z["zone"], []).append(g)
        names.setdefault(z["zone"], z.get("name", ""))

    W, S, E, N = bbox
    sx, sy = 1000.0 / (E - W), 1000.0 / (E - W)
    def proj(lon, lat):
        return (lon - W) * sx, (N - lat) * sy

    zones = []
    for code, geoms in merged.items():
        g = unary_union(geoms).simplify(simplify, preserve_topology=True)
        if g.is_empty:
            continue
        polys = list(getattr(g, "geoms", [g]))
        d = []
        for poly in polys:
            ring = getattr(poly, "exterior", None)
            if ring is None:
                continue
            pts = [proj(x, y) for x, y in ring.coords]
            if len(pts) < 4:
                continue
            d.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        if not d:
            continue
        rate, age = store.value_with_age("enroute_rate", code, as_of)
        cfg = cfgs.get(code, {})
        zones.append({
            "code": code, "name": names.get(code, ""), "d": " ".join(d),
            "rate": rate, "stale": bool(age),
            "note": cfg.get("note", ""),
            "f": _params(cfg.get("formula", "eurocontrol"), cfg, code),
        })

    # Список типов для переключателя — не датированная выборка, а
    # перечень того, что вообще есть в справочнике. Фильтровать его по
    # дате расчёта бессмысленно: пустой список означал бы, что справочник
    # записан позже выбранной даты, а не что типов не существует.
    fleet = []
    # Раньше здесь стоял сырой SELECT мимо единственной точки чтения.
    # Провенанс был не главной бедой: у запроса не было фильтра интервала
    # действия, то есть он не знал СМЫСЛА таблицы. Запись, заведённая
    # будущим числом, побеждала действующую; запись, снятая с учёта без
    # преемника, продолжала показываться как текущая. `select` фильтрует
    # интервал на стороне хранилища и отдаёт провенанс в строке — тогда
    # «масса из истёкшего документа» будет чем показать.
    for key, row in store.select("aircraft", suffix="/mtow_t",
                                 as_of=as_of).items():
        if not row["value"]:
            continue
        fleet.append({"icao": key.split("/")[0], "mtow": float(row["value"])})
    fleet.sort(key=lambda x: x["mtow"])

    have = sum(1 for z in zones if z["rate"])
    return (_TPL
            .replace("__UI__", style_tag(inline_fonts=True))
            .replace("__ZONES__", json.dumps(zones, ensure_ascii=False))
            .replace("__FLEET__", json.dumps(fleet, ensure_ascii=False))
            .replace("__STAT__", html.escape(
                f"{len(zones)} зон в кадре, ставка известна у {have}"))
            .replace("__ASOF__", html.escape(str(as_of))))


_TPL = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сборы за аэронавигацию по зонам</title>
__UI__<style>
body{font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:30px 26px 70px}
h1{margin:0 0 4px;font:600 20px/1.2 var(--sans);color:var(--ink2)}
.sub{color:var(--dim);font-size:13px;max-width:78ch;margin:0 0 20px}
.bar{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
label{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
 margin-right:8px}
select{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;
 padding:7px 11px;font:13px var(--sans)}
.val{font:600 15px var(--sans);color:var(--ink2);font-variant-numeric:tabular-nums}
.tog{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--dim);cursor:pointer}
.tog input{accent-color:var(--accent)}
svg{width:100%;height:auto;display:block;background:var(--ocean);border-radius:10px;
 border:1px solid var(--line)}
path.z{stroke:var(--ocean);stroke-width:.8;cursor:pointer;transition:fill .15s}
path.z:hover{stroke:var(--ink2);stroke-width:1.4}
path.z.nodata{fill:var(--nodata-f);stroke:var(--nodata-line);stroke-dasharray:3 2}
/* Слой раскраски отключается: остаются границы зон на нейтральной заливке,
   а пробелы данных остаются оранжевыми — «нет ставки» не выключается
   вместе с величиной. */
svg.plain path.z{fill:var(--land)}
svg.plain path.z.nodata{fill:var(--nodata-f)}
.legend{display:flex;align-items:center;gap:10px;margin-top:16px;font-size:12px;
 color:var(--dim);flex-wrap:wrap}
.scale{display:flex;height:10px;width:260px;border-radius:3px;overflow:hidden}
.scale i{flex:1}
#info{margin-top:18px;padding:16px 20px;border-radius:8px;background:var(--panel);
 border:1px solid var(--line);min-height:76px}
#info h3{margin:0 0 6px;font-size:16px;color:var(--ink2)}
#info .row{display:flex;justify-content:space-between;gap:20px;padding:4px 0;
 font-size:13.5px;color:var(--ink)}
#info .row b{color:var(--ink2);font:600 13.5px var(--sans);font-variant-numeric:tabular-nums}
.foot{margin-top:22px;color:var(--faint);font-size:12.5px;line-height:1.7;max-width:80ch}
</style></head><body><div class="wrap">
<h1>Сборы за аэронавигацию по зонам</h1>
<p class="sub">Цвет — стоимость пролёта ста морских миль выбранным типом.
Метрика сравнима между зонами независимо от их размера. Оранжевым пунктиром — зоны, для
которых ставки в справочнике нет: это пробел, а не бесплатный пролёт.</p>

<div class="bar">
  <div><label>Тип ВС</label><select id="ac"></select></div>
  <div><label>Масса</label><span class="val" id="mtow">—</span></div>
  <div><label>Разброс</label><span class="val" id="range">—</span></div>
  <label class="tog" style="margin-left:auto;text-transform:none;letter-spacing:0">
    <input type="checkbox" id="layer" checked> раскраска по ставке</label>
</div>

<svg id="map" viewBox="0 0 1000 620" xmlns="http://www.w3.org/2000/svg"></svg>

<div class="legend">
  <span>дешевле</span><div class="scale" id="sc"></div><span>дороже</span>
  <span style="margin-left:14px">
    <i style="display:inline-block;width:11px;height:11px;background:var(--nodata-f);
       border:1px dashed var(--nodata-line);border-radius:2px;vertical-align:-1px"></i> ставки нет</span>
  <span id="stat" style="margin-left:auto">__STAT__</span>
</div>

<div id="info">Наведи или нажми на зону.</div>

<p class="foot">Справочники на дату __ASOF__. Там, где сбор берётся без учёта
массы — Китай, Казахстан, США, — карта при смене типа не меняется: это не
сбой, а свойство тарифа. В зоне EUROCONTROL сбор растёт как корень из
массы, поэтому разница между регионалом и широкофюзеляжным примерно
трёхкратная.</p>
</div>
<script>
const ZONES = __ZONES__, FLEET = __FLEET__;
const NM_KM = 1.852, D100 = 100;   // считаем стоимость ста морских миль

function charge(z, mtow){
  if (z.rate === null || z.rate === undefined) return null;
  const f = z.f;
  let rate = z.rate;
  if (f.bands && f.bands.length){
    const hit = f.bands.find(b => mtow <= b[0]);
    rate = hit ? hit[1] : f.bands[f.bands.length-1][1];
  }
  const d = f.d_unit === 'km' ? D100 * NM_KM : D100;
  const fd = f.d_exp ? Math.pow(d / f.d_div, f.d_exp) : 1;
  const fm = f.m_exp ? Math.pow(mtow / f.m_div, f.m_exp) : 1;
  return rate * fd * fm;
}

// Шкала одного семейства, ярче = дороже: на чёрном фоне яркость и есть
// величина. Светофорные цвета читались бы как «плохо», хотя дорогая зона
// не хуже дешёвой, она просто дороже. Ступени объявлены в ui.css
// (--ramp-0 … --ramp-6) — здесь только их имена.
const RAMP = [0,1,2,3,4,5,6].map(i => `var(--ramp-${i})`);
// Шкала логарифмическая, а не линейная по крайним значениям. Разброс
// ставок 24-кратный: при линейной шкале почти вся Европа садится в два
// деления из семи, а вся разрешающая способность уходит на Молдову.
// Ранговая шкала вылечила бы то же самое, но ценой смысла: она отвечает
// на «какое это место», а карта объявлена отвечающей на «сколько это
// стоит» (решение 86).
function colour(v, lo, hi){
  if (v === null) return null;                 // класс nodata, не цвет
  const t = hi > lo
    ? (Math.log(Math.max(v, 1e-9)) - Math.log(Math.max(lo, 1e-9)))
      / (Math.log(Math.max(hi, 1e-9)) - Math.log(Math.max(lo, 1e-9)))
    : 0.5;
  return RAMP[Math.min(RAMP.length-1, Math.max(0, Math.round(t*(RAMP.length-1))))];
}

const sel = document.getElementById('ac');
FLEET.forEach(a => {
  const o = document.createElement('option');
  o.value = a.icao; o.textContent = `${a.icao} — ${a.mtow.toFixed(0)} т`;
  sel.appendChild(o);
});
sel.value = FLEET.some(a=>a.icao==='A320') ? 'A320' : FLEET[0].icao;

document.getElementById('sc').innerHTML =
  RAMP.map(c=>`<i style="background:${c}"></i>`).join('');

const map = document.getElementById('map');
function draw(){
  const ac = FLEET.find(a => a.icao === sel.value);
  document.getElementById('mtow').textContent = ac.mtow.toFixed(0) + ' т';
  const vals = ZONES.map(z => charge(z, ac.mtow)).filter(v => v !== null);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  document.getElementById('range').textContent =
    vals.length ? `${lo.toFixed(0)}–${hi.toFixed(0)} EUR / 100 nm` : '—';
  map.innerHTML = ZONES.map((z,i) => {
    const v = charge(z, ac.mtow);
    const c = colour(v, lo, hi);
    return c === null
      ? `<path class="z nodata" d="${z.d}" data-i="${i}"></path>`
      : `<path class="z" d="${z.d}" fill="${c}" data-i="${i}"></path>`;
  }).join('');
  map.querySelectorAll('path').forEach(p => {
    p.onmouseenter = p.onclick = () => info(ZONES[+p.dataset.i], ac);
  });
}

function info(z, ac){
  const v = charge(z, ac.mtow);
  const f = z.f;
  const how = f.bands && f.bands.length ? 'плоский сбор по полосе массы'
    : (f.m_exp ? `(D/${f.d_div} ${f.d_unit}) · (MTOW/${f.m_div})^${f.m_exp}`
               : `(D/${f.d_div} ${f.d_unit}), масса не входит`);
  document.getElementById('info').innerHTML =
    `<h3>${z.code} — ${z.name || 'без названия'}</h3>`
    + `<div class="row"><span>Пролёт 100 nm на ${ac.icao}</span><b>`
      + (v === null ? 'ставки нет' : v.toFixed(0) + ' EUR') + `</b></div>`
    + `<div class="row"><span>Ставка</span><b>`
      + (z.rate === null ? '—' : z.rate.toFixed(2)) + `</b></div>`
    + `<div class="row"><span>Способ расчёта</span><b>${how}</b></div>`
    + (z.stale ? `<div class="row"><span>Внимание</span><b>ставка из
        истёкшего документа</b></div>` : '')
    + (z.note ? `<div class="row"><span>Примечание</span><b>${z.note}</b></div>` : '');
}

sel.onchange = draw;
document.getElementById('layer').onchange = e =>
  map.classList.toggle('plain', !e.target.checked);
draw();
</script></body></html>"""
