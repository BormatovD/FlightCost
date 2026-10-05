/* geo.js — геодезия и проекции. Одна реализация на все виды (решение 97).

   Питон отдаёт широту и долготу, проецирует браузер. Второй реализации
   той же математики нет и не должно быть: она разойдётся с первой так же
   молча, как разошлись два отпечатка состава, оба честно сославшиеся на
   решение 81.

   СОГЛАШЕНИЕ О ПОРЯДКЕ КООРДИНАТ. Оно разное и это не небрежность:
     точка       [lat, lon]   — как в gcd/gcPoint и в справочнике аэропортов
     кольцо      [[lon, lat]] — как в GeoJSON, откуда полигоны и приходят
   Менять порядок при чтении данных дороже, чем помнить правило, но
   правило надо помнить. Всё, что принимает кольцо, названо ring*.

   Проекция — объект, а не функция: у неё есть состояние (центр, масштаб)
   и своё понятие видимости. Виды не делят один глобальный `rot`, поэтому
   разбор маршрута и мировая карта могут жить на одной странице.        */

export const RAD = Math.PI / 180;
const EARTH_NM = 6371 / 1.852;

/* ── геодезия ─────────────────────────────────────────────────────── */

/** Ортодромия между точками, морские мили. */
export function gcd(a, b) {
  const [la1, lo1, la2, lo2] = [a[0] * RAD, a[1] * RAD, b[0] * RAD, b[1] * RAD];
  const d = 2 * Math.asin(Math.sqrt(
    Math.sin((la2 - la1) / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2));
  return d * EARTH_NM;
}

/** Точка на дуге большого круга по доле пути f ∈ [0,1]. */
export function gcPoint(a, b, f) {
  const [la1, lo1, la2, lo2] = [a[0] * RAD, a[1] * RAD, b[0] * RAD, b[1] * RAD];
  const d = 2 * Math.asin(Math.sqrt(
    Math.sin((la2 - la1) / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2));
  if (d < 1e-9) return [a[0], a[1]];
  const A = Math.sin((1 - f) * d) / Math.sin(d);
  const B = Math.sin(f * d) / Math.sin(d);
  const x = A * Math.cos(la1) * Math.cos(lo1) + B * Math.cos(la2) * Math.cos(lo2);
  const y = A * Math.cos(la1) * Math.sin(lo1) + B * Math.cos(la2) * Math.sin(lo2);
  const z = A * Math.sin(la1) + B * Math.sin(la2);
  return [Math.atan2(z, Math.hypot(x, y)) / RAD, Math.atan2(y, x) / RAD];
}

/** Поправка ИКАО к ортодромии — полосами в километрах, прибавляется, а
    не умножается (решение 47): накрутка примерно постоянна, поэтому на
    250 милях даёт 10%, а на 4000 — полтора. */
export function icaoDist(nm) {
  const km = nm * 1.852;
  const dc = km < 550 ? 0 : km < 1200 ? 45 : km < 2400 ? 95
    : km < 4800 ? 200 : km < 9600 ? 450 : 600;
  return (km + dc) / 1.852;
}

/** Точка внутри кольца. ring — [[lon, lat], …]. */
export function inRing(lat, lon, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) &&
        lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Пересечённые зоны: точечная выборка серединами отрезков, как в
    airspace.py. Зоны передаются аргументом, а не берутся из области
    видимости: иначе модуль не переносится между видами.
    zones — { код: { r: [кольцо, …] } }.  Возвращает { код: мили }. */
export function crossing(a, b, zones, stepNm = 10) {
  const nm = icaoDist(gcd(a, b));
  const n = Math.max(8, Math.round(nm / stepNm));
  const out = {};
  for (let i = 0; i < n; i++) {
    const [lat, lon] = gcPoint(a, b, (i + 0.5) / n);
    for (const [code, z] of Object.entries(zones)) {
      if (z.r.some(r => inRing(lat, lon, r))) {
        out[code] = (out[code] || 0) + nm / n;
        break;
      }
    }
  }
  return out;
}

/* ── проекции ─────────────────────────────────────────────────────── */
/* Каждая отдаёт один интерфейс:
     project(lat, lon) -> [x, y]
     visible(lat, lon) -> bool
     clamp(p)          -> [x, y]   вытолкнуть на край, если край есть
   `clamp` отсутствует у проекций без лимба — там его незачем звать.   */

/** Ортографическая: вид сети и дальних плеч. Половина мира за раз. */
export function orthographic({ cx = 310, cy = 310, radius = 284,
                               lat = 0, lon = 0, zoom = 1 } = {}) {
  const st = { cx, cy, radius, lat, lon, zoom };
  const R = () => st.radius * st.zoom;
  const p = {
    kind: "orthographic",
    state: st,
    rotate(la, lo) { st.lat = la; st.lon = lo; return p; },
    setZoom(z) { st.zoom = z; return p; },
    visible(la, lo) {
      return Math.sin(st.lat * RAD) * Math.sin(la * RAD) +
        Math.cos(st.lat * RAD) * Math.cos(la * RAD) *
        Math.cos((lo - st.lon) * RAD) > 0;
    },
    project(la, lo) {
      const a = la * RAD, dl = (lo - st.lon) * RAD, l0 = st.lat * RAD;
      return [st.cx + R() * Math.cos(a) * Math.sin(dl),
              st.cy - R() * (Math.cos(l0) * Math.sin(a) -
                             Math.sin(l0) * Math.cos(a) * Math.cos(dl))];
    },
    clamp(q) {
      const dx = q[0] - st.cx, dy = q[1] - st.cy, r = Math.hypot(dx, dy) || 1;
      return [st.cx + dx / r * R(), st.cy + dy / r * R()];
    },
  };
  return p;
}

/** Гномоническая: разбор одного маршрута. Всякая дуга большого круга —
    прямая, поэтому пересечённые зоны читаются без искажения. Отсечения
    по лимбу нет: полусфера в кадр и не влезает, видимость обрывается
    раньше. */
export function gnomonic({ cx = 310, cy = 310, scale = 284,
                           lat = 0, lon = 0, maxDeg = 75 } = {}) {
  const st = { cx, cy, scale, lat, lon, maxDeg };
  const cosc = (la, lo) =>
    Math.sin(st.lat * RAD) * Math.sin(la * RAD) +
    Math.cos(st.lat * RAD) * Math.cos(la * RAD) * Math.cos((lo - st.lon) * RAD);
  const p = {
    kind: "gnomonic",
    state: st,
    center(la, lo) { st.lat = la; st.lon = lo; return p; },
    setScale(s) { st.scale = s; return p; },
    visible(la, lo) { return cosc(la, lo) > Math.cos(st.maxDeg * RAD); },
    project(la, lo) {
      const c = cosc(la, lo), a = la * RAD, dl = (lo - st.lon) * RAD,
            l0 = st.lat * RAD;
      const k = st.scale / Math.max(c, 1e-6);
      return [st.cx + k * Math.cos(a) * Math.sin(dl),
              st.cy - k * (Math.cos(l0) * Math.sin(a) -
                           Math.sin(l0) * Math.cos(a) * Math.cos(dl))];
    },
  };
  return p;
}

/** Equal Earth: мировая карта сборов (решения 71 и 86). Площадь полигона
    на ней читается как величина и не спорит с цветом. Коэффициенты —
    Šavrič, Patterson, Jenny (2018). */
const EE = [1.340264, -0.081106, 0.000893, 0.003796];
export function equalEarth({ cx = 500, cy = 260, scale = 160 } = {}) {
  const st = { cx, cy, scale };
  const p = {
    kind: "equalEarth",
    state: st,
    visible() { return true; },          // лимба нет, виден весь мир
    project(la, lo) {
      const th = Math.asin(Math.sqrt(3) / 2 * Math.sin(la * RAD));
      const t2 = th * th, t6 = t2 * t2 * t2;
      const x = lo * RAD * Math.cos(th) /
        (Math.sqrt(3) / 2 * (EE[0] + 3 * EE[1] * t2 +
                             t6 * (7 * EE[2] + 9 * EE[3] * t2)));
      const y = th * (EE[0] + EE[1] * t2 + t6 * (EE[2] + EE[3] * t2));
      return [st.cx + st.scale * x, st.cy - st.scale * y];
    },
  };
  return p;
}

/* ── контуры ──────────────────────────────────────────────────────── */

/** Уплотнение кольца до шага в градусах. На равнопромежуточной карте
    ребро полигона — прямая в широте и долготе, и это сходит с рук; на
    глобусе несгущённое ребро видимо срезает угол. */
export function densify(ring, step = 3) {
  const out = [];
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length];
    const n = Math.max(1, Math.ceil(
      Math.max(Math.abs(q[0] - p[0]), Math.abs(q[1] - p[1])) / step));
    for (let k = 0; k < n; k++)
      out.push([p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n]);
  }
  return out;
}

/** Контур кольца в виде пути SVG.

    Невидимую часть не выбрасываем и не заменяем дугой: проецируем её
    точки и выталкиваем на край. Тогда контур идёт по краю ровно в ту
    сторону, куда его ведёт само кольцо.

    Прежний вариант замыкал дугой и выбирал направление обхода по
    разности углов — на полигонах, занимающих больше половины сферы,
    дуга уходила длинной стороной и рвала сферу. Дефект был не
    косметический: картинка оставалась правдоподобной. */
export function ringPath(ring, proj, step = 3) {
  const pts = densify(ring, step).map(([lon, lat]) =>
    ({ lat, lon, v: proj.visible(lat, lon) }));
  if (!pts.some(p => p.v)) return "";
  const out = pts.map(p => {
    const q = proj.project(p.lat, p.lon);
    return p.v || !proj.clamp ? q : proj.clamp(q);
  });
  return "M" + out.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L") + "Z";
}

/** Дуга большого круга как путь. На гномонической выйдет прямая — это
    свойство проекции, а не особый случай здесь. */
export function arcPath(a, b, proj, steps = 64) {
  const seg = [];
  for (let i = 0; i <= steps; i++) {
    const [lat, lon] = gcPoint(a, b, i / steps);
    if (!proj.visible(lat, lon)) { seg.push(null); continue; }
    seg.push(proj.project(lat, lon));
  }
  let d = "", pen = false;
  for (const q of seg) {
    if (!q) { pen = false; continue; }
    d += (pen ? "L" : "M") + q[0].toFixed(1) + "," + q[1].toFixed(1);
    pen = true;
  }
  return d;
}

/** Приближение по длине плеча (решение 92): 590 миль — десять градусов
    дуги, приблизишь — теряется сфера, оставишь сферу — маршрут стал
    точкой. */
export function fitZoom(nm) {
  const deg = nm / 60;
  return Math.max(1, Math.min(2.4, 34 / Math.max(9, deg)));
}
