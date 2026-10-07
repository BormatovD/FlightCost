const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");
// Прогон витрины целиком в jsdom: загрузка, выбор языка, запуск до
// первого расчёта. Синтаксическая проверка не видит ошибок времени
// выполнения — так прожила «t is not a function», ломавшая запуск.
//
//   npm install --no-save jsdom@24
//   node tools/check_page.js [en|de|ru]
//
// Ответы сервера — заглушки; запрос расчёта маршрута заглушка намеренно
// не обслуживает, поэтому строка «заглушка: /api/route» — норма.
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const file = path.join(ROOT, "flightcostapp/web/serve.html");
const lang = process.argv[2];
let html = fs.readFileSync(file, "utf8");
const cat = JSON.parse(fs.readFileSync(path.join(ROOT, "flightcostapp/web/i18n.json"), "utf8"));
html = html.replace("/*I18N*/{}/*/I18N*/", "/*I18N*/" + JSON.stringify(cat).replace(/<\//g, "<\\/") + "/*/I18N*/");
const a = html.indexOf('<script type="module">'), b = html.lastIndexOf("</script>");
let js = html.slice(a + '<script type="module">'.length, b);
js = js.replace(/^import[\s\S]*?from\s+"[^"]+";\s*$/gm, "");
// глобус и геометрия — заглушки: любое свойство — функция, возвращающая заглушку
const stub = `const __p = new Proxy(function(){}, {get: (t, k) => k === Symbol.toPrimitive ? (() => 0) : (k === "then" ? undefined : __p), apply: () => __p});
const orthographic = __p, gcd = () => 590, gcPoint = __p, crossing = __p, fitZoom = () => 1, createGlobe = () => __p;`;
const page = html.slice(0, a) + "<script>(async () => {" + stub + js + "\n})().catch(e => { window.__errs.push('ASYNC: ' + e.message); });</script></body></html>";
const errs = [];
process.on("unhandledRejection", e => errs.push("REJ: " + (e && e.message)));
process.on("uncaughtException", e => errs.push("EXC: " + (e && e.message)));
const vc = new VirtualConsole();
vc.on("jsdomError", e => errs.push("JSDOM: " + (e.detail && e.detail.message || e.message)));
const AIRPORTS = [{key: "EDDF", icao: "EDDF", iata: "FRA", code: "FRA", name: "Frankfurt Airport", lat: 50.03, lon: 8.57, tier: 1, find: "eddf fra frankfurt"},
                  {key: "LEBL", icao: "LEBL", iata: "BCN", code: "BCN", name: "Barcelona-El Prat Airport", lat: 41.3, lon: 2.08, tier: 1, find: "lebl bcn barcelona"}];
const AIRCRAFT = [{icao: "A320", name: "Airbus A320", usable: true, physics: true, tier: 1, find: "a320 airbus a320",
                   layouts: [{operator: "*", seats: 170}, {operator: "FR", seats: 186}], layout_default: {seats: 170},
                   seats_max: 186, seats_typical: 170},
                  {icao: "T214", name: "Tupolev Tu-214", usable: false, physics: false, tier: 4, why_not: "нет якоря",
                   find: "t214 tupolev", layouts: [], layout_default: null, seats_max: 210, seats_typical: 176}];
const dom = new JSDOM(page, {url: "http://127.0.0.1:8000/" + (lang ? "?lang=" + lang : ""), runScripts: "dangerously",
  pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(w) {
    w.__errs = errs;
    w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
    w.addEventListener("error", e => errs.push("ERR: " + e.message));
    w.fetch = async (u) => {
      const path = String(u).split("?")[0];
      const body = path === "/api/airports" ? AIRPORTS : path === "/api/aircraft" ? AIRCRAFT
                 : path === "/api/geo" ? {missing: [], zones: [], land: [], airports: {
                     EDDF: {lat: 50.03, lon: 8.57, tier: 1, flights: 0, watch: true},
                     LEBL: {lat: 41.3, lon: 2.08, tier: 1, flights: 0, watch: true}}} : null;
      if (body === null) throw new Error("заглушка: " + path);
      return {ok: true, json: async () => body};
    };
  }});
setTimeout(() => {
  const d = dom.window.document;
  const tFail = errs.filter(e => /\bt is not a function|_t is not a function/.test(e));
  console.log(JSON.stringify({
    lang: lang || "(браузер)",
    ac: d.querySelector("#ac").value,
    acTitle: d.querySelector("#ac").title,
    layouts: [...d.querySelectorAll("#layout option")].map(o => o.textContent),
    tab: d.querySelector('[data-tab="route"]').textContent,
    lf: (d.querySelector('label[for="lf"]') || {}).textContent,
    langsBtn: d.querySelectorAll("#langs button").length,
    errors_t: tFail.length, errors_other: errs.filter(e => !tFail.includes(e)).map(e => e.slice(0, 80)).slice(0, 3)}));
  const bad = tFail.length || errs.some(e => !/заглушка: \/api\/route/.test(e));
  process.exit(bad ? 1 : 0);
}, 1500);
