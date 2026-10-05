/* globe.js — сборка вида: слои, вращение, приближение, наведение.

   Модуль знает про геометрию и порядок слоёв и НЕ знает про оформление.
   Всплывающие панели рисует потребитель: у разбора маршрута и у мировой
   карты разная вёрстка и разный набор полей, а общая панель затащила бы
   сюда половину `ui.css`.

   Наружу отдаётся событие с объектом и уже посчитанной экранной точкой —
   чтобы потребителю не пришлось повторять проекцию ради позиционирования.
   Если через два вида окажется, что всплывания одинаковые, общая панель
   надстраивается поверх этого события и ничего не ломает.

   Данные приходят аргументом, не из области видимости:
     zones     { код: { n: имя, r: [кольцо, …] } }     кольцо — [[lon,lat]]
     land      [ кольцо, … ]
     airports  { ИКАО: [lat, lon, имя, ИАТА] }                            */

import { ringPath, arcPath, gcPoint, gcd, fitZoom } from "./geo.js";

const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function createGlobe({ svg, proj, data, landStep = 4, zoneStep = 3,
                             aptClass = null }) {
  // `aptClass(icao)` — дополнительный класс точки. Модуль НЕ знает, что
  // такое ярус данных, и знать не должен: он рисует геометрию. Но и
  // раскрашивать точки снаружи, дописывая классы в готовый SVG, нельзя —
  // это вторая правка того же места, которая разойдётся с первой.
  // Крючок: потребитель говорит, чем красить, модуль рисует.
  const cb = { hover: [], leave: [], pick: [] };
  let last = null;                       // последний нарисованный вид

  /* Порядок слоёв не косметика: одни только зоны EUROCONTROL читаются
     как абстрактная мозаика, и на макете это было первым, обо что
     споткнулся владелец. Материки и океан идут ПОД зонами. */
  function draw(view = {}) {
    last = view;
    const { highlight = {}, route = null, selected = [] } = view;
    const st = proj.state || {};
    const parts = [];

    if (proj.kind === "orthographic") {
      const r = (st.radius || 284) * (st.zoom || 1);
      parts.push(`<circle class="oc" cx="${st.cx}" cy="${st.cy}" r="${r}"/>`);
    }

    const dLand = (data.land || [])
      .map(r => ringPath(r, proj, landStep)).filter(Boolean).join(" ");
    if (dLand) parts.push(`<path class="land" d="${dLand}"/>`);

    // Зоны рисуются ДВАЖДЫ: обычные под точками, выделенные поверх.
    // Точка под обычной зоной видна, точка под выделенной подкрашивается
    // — и выделение читается как область, а не как россыпь кружков на
    // цветном фоне. Верхний слой не ловит указатель: иначе наведение на
    // аэропорт внутри выделенной зоны перестало бы работать, а точки
    // важнее зон.
    const zoneTop = [];
    for (const [code, z] of Object.entries(data.zones || {})) {
      // Шаг передаётся ЯВНО. В макете стояло `z.r.map(ringPath)`, и
      // Array.map подставлял вторым аргументом индекс кольца: нулевое
      // уплотнялось на 3°, первое на 1°, второе на 2°. Ошибка тихая и
      // безобидная на трёх кольцах, но у зоны с пятью пятое кольцо
      // получило бы 5° и видимо срезало угол.
      const d = (z.r || []).map(r => ringPath(r, proj, zoneStep))
        .filter(Boolean).join(" ");
      if (!d) continue;
      const on = code in highlight;
      const tip = esc(`${code} — ${z.n || ""}`) +
        (on ? esc(`\nпересечение ${Math.round(highlight[code])} nm`) : "");
      const el = `<path class="zone${on ? " hit" : ""}" d="${d}" ` +
                 `data-zone="${esc(code)}"><title>${tip}</title></path>`;
      (on ? zoneTop : parts).push(el);
    }

    const routeParts = [];
    if (route) {
      const d = arcPath(route.a, route.b, proj, route.steps || 120);
      if (d) routeParts.push(`<path class="arc halo" d="${d}"/>` +
                             `<path class="arc" d="${d}"/>`);
      routeParts.push(...arcLabel(route));
    }

    // Рамка кадра, чтобы не рисовать точки за её пределами. `visible`
    // проверяет ПОЛУСФЕРУ — что точка на видимой стороне шара, — а при
    // приближении в кадр попадает лишь её часть. Без этой отсечки сотни
    // кружков ложатся за краем: их не видно, они мешают попаданию мышью
    // и считаются в «показано N».
    const vb = (svg.getAttribute("viewBox") || "0 0 620 620").split(/\s+/).map(Number);
    const [vx, vy, vw, vh] = vb.length === 4 ? vb : [0, 0, 620, 620];
    for (const [icao, a] of Object.entries(data.airports || {})) {
      if (!proj.visible(a[0], a[1])) continue;
      const [x, y] = proj.project(a[0], a[1]);
      if (x < vx - 8 || y < vy - 8 || x > vx + vw + 8 || y > vy + vh + 8) continue;
      const sel = selected.includes(icao);
      const extra = aptClass ? " " + aptClass(icao) : "";
      parts.push(`<circle class="apt ${sel ? "sel" : "other"}${extra}" ` +
        `cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${sel ? 5 : 3}" ` +
        `data-apt="${esc(icao)}"/>`);
      if (sel) parts.push(`<text class="aptlbl" x="${(x + 9).toFixed(1)}" ` +
        `y="${(y + 4).toFixed(1)}">${esc(a[3] || icao)}</text>`);
    }

    // Порядок слоёв: океан, суша, обычные зоны, ТОЧКИ, выделенные зоны,
    // маршрут. Маршрут последним — он ответ на вопрос и не должен
    // прятаться ни под чем.
    svg.innerHTML = parts.join("") + zoneTop.join("") + routeParts.join("");
    wire();
  }

  /* Подпись ставится по нормали к дуге и всегда над ней: иначе на
     обратном курсе она уезжает под линию и перекрывается зонами. */
  function arcLabel(route) {
    if (!route.label) return [];
    const mid = gcPoint(route.a, route.b, 0.5);
    if (!proj.visible(mid[0], mid[1])) return [];
    const [mx, my] = proj.project(mid[0], mid[1]);
    const p1 = proj.project(...gcPoint(route.a, route.b, 0.42));
    const p2 = proj.project(...gcPoint(route.a, route.b, 0.58));
    let nx = -(p2[1] - p1[1]), ny = p2[0] - p1[0];
    const len = Math.hypot(nx, ny) || 1;
    nx /= len; ny /= len;
    if (ny > 0) { nx = -nx; ny = -ny; }
    const lx = (mx + nx * 30).toFixed(0), ly = my + ny * 30;
    const out = [`<text class="arclbl${route.bad ? " bad" : ""}" x="${lx}" y="${ly.toFixed(0)}">` +
                 `${esc(route.label)}</text>`];
    if (route.sub) out.push(`<text class="arclbl sub" x="${lx}" ` +
      `y="${(ly - 15).toFixed(0)}">${esc(route.sub)}</text>`);
    return out;
  }

  function wire() {
    const box = () => svg.getBoundingClientRect();
    const emit = (name, kind, id, ev) => {
      const b = box();
      // Экранная точка считается здесь: потребитель не должен повторять
      // проекцию ради позиционирования панели.
      for (const f of cb[name]) f({ kind, id, x: ev.clientX - b.left,
                                    y: ev.clientY - b.top, event: ev });
    };
    for (const el of svg.querySelectorAll("[data-apt],[data-zone]")) {
      const kind = el.dataset.apt ? "airport" : "zone";
      const id = el.dataset.apt || el.dataset.zone;
      el.addEventListener("mousemove", e => emit("hover", kind, id, e));
      el.addEventListener("mouseleave", e => emit("leave", kind, id, e));
      el.addEventListener("click", e => emit("pick", kind, id, e));
    }
  }

  /* Вращение мышью. Только для проекций с центром — у равновеликой
     вращать нечего, и метода `rotate` у неё нет. */
  function draggable() {
    if (!proj.rotate) return api;
    // Захват указателя ставится НЕ на нажатии, а после того, как палец
    // сдвинулся дальше порога. С захватом на нажатии Chrome переадресует
    // все последующие события — включая `click` — элементу-захватчику,
    // то есть самому svg, и щелчок по точке аэропорта до неё не доходит.
    // Safari в этом месте ведёт себя иначе, и дефект был виден только в
    // Chrome. Порог в четыре пикселя отделяет щелчок от поворота.
    const DRAG_PX = 4;
    let from = null, dragging = false;
    svg.addEventListener("pointerdown", e => {
      from = { x: e.clientX, y: e.clientY, id: e.pointerId,
               lat: proj.state.lat, lon: proj.state.lon };
      dragging = false;
    });
    svg.addEventListener("pointermove", e => {
      if (!from) return;
      if (!dragging) {
        if (Math.hypot(e.clientX - from.x, e.clientY - from.y) < DRAG_PX) return;
        dragging = true;
        svg.setPointerCapture(from.id);
      }
      const k = 0.35 / (proj.state.zoom || 1);
      proj.rotate(Math.max(-85, Math.min(85, from.lat + (e.clientY - from.y) * k)),
                  from.lon - (e.clientX - from.x) * k);
      draw(last || {});
    });
    const stop = () => { from = null; dragging = false; };
    svg.addEventListener("pointerup", stop);
    svg.addEventListener("pointercancel", stop);
    return api;
  }

  /* Приближение по длине плеча (решение 92) и возврат к целому глобусу
     одним вызовом: 590 миль — десять градусов дуги, приблизишь — теряется
     сфера, оставишь сферу — маршрут стал точкой. */
  function frame(a, b) {
    if (!proj.rotate) return api;
    const mid = gcPoint(a, b, 0.5);
    proj.rotate(mid[0], mid[1]);
    if (proj.setZoom) proj.setZoom(fitZoom(gcd(a, b)));
    return api;
  }
  function whole() {
    if (proj.setZoom) proj.setZoom(1);
    return api;
  }

  // Набор точек меняется на лету: при приближении их становится больше.
  // Заменять весь объект `data` снаружи нельзя — модуль держит на него
  // ссылку, и правка разъехалась бы с отрисовкой.
  function setAirports(m) { data.airports = m; return api; }
  function shown() { return data.airports || {}; }

  const api = { draw, draggable, frame, whole, proj, setAirports, shown,
                on: (name, f) => { (cb[name] || []).push(f); return api; } };
  return api;
}
