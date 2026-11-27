"""Build the web edition from frozen HTML without rebuilding the research model."""
from collections import defaultdict
import base64
import gzip
import hashlib
import json
import re

DIRECTORY = "forecast-web"
BLOB = re.compile(rb'(<script\b[^>]*\bid="([^"]+)"[^>]*>)(.*?)(</script>)', re.S)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def inline_json(value):
    return json_bytes(value).replace(b"<", br"\u003c")


def replace_once(html, before, after):
    a, b = before.encode(), after.encode()
    if html.count(a) != 1:
        raise ValueError(f"Expected one occurrence of {before[:120]!r}")
    return html.replace(a, b, 1)


def decode(block):
    return json.loads(gzip.decompress(base64.b64decode(block)))


class Store:
    def __init__(self, root):
        self.root = root / DIRECTORY
        self.root.mkdir(exist_ok=True)

    def gzip(self, compressed):
        name = hashlib.sha256(compressed).hexdigest() + ".json.gz"
        (self.root / name).write_bytes(compressed)
        return "/outputs/" + DIRECTORY + "/" + name

    def put(self, data):
        return self.gzip(gzip.compress(json_bytes(data), compresslevel=4, mtime=0))


FETCH = """
const forecastDownloads = (() => {
  const cache = new Map();
  function retry(container, label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", action);
    container.replaceChildren(button);
  }
  function load(path) {
    if (cache.has(path)) return cache.get(path);
    const url = new URL(path, location.href);
    if (new URLSearchParams(location.search).getAll("probe").includes("dev")) url.searchParams.set("probe", "dev");
    const request = fetch(url).then(response => {
      if (!response.ok || !response.body) throw new Error("HTTP " + response.status + ": " + url.pathname);
      return new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).json();
    }).catch(error => { cache.delete(path); throw error; });
    cache.set(path, request);
    if (cache.size > 12) cache.delete(cache.keys().next().value);
    return request;
  }
  return {load, retry};
})();
"""


def add_script(html, script):
    return replace_once(html, '</head>', '<script>' + FETCH + script + '</script></head>')


def build_forecast(html, store):
    blocks = {match[2]: match[3] for match in BLOB.finditer(html)}
    if set(blocks) != {b"core", b"manufacturer-data", b"operations-data"}:
        raise ValueError("Unexpected embedded blocks in the standalone forecast")
    core = store.gzip(gzip.compress(blocks[b"core"], compresslevel=4, mtime=0))
    manufacturer = store.gzip(gzip.compress(blocks[b"manufacturer-data"], compresslevel=4, mtime=0))
    operations = decode(blocks[b"operations-data"])
    direct = operations.pop("directRoutes")
    scopes = defaultdict(lambda: defaultdict(dict))
    for year, horizon in direct.pop("horizons").items():
        for method, values in horizon["methods"].items():
            for demand, view in values["demands"].items():
                groups = view["scopes"]
                panels = {"world": groups["world"], **groups["regions"], **groups["countries"]}
                for scope, panel in panels.items():
                    scopes[year, scope][method][demand] = panel
    assets = defaultdict(dict)
    for (year, scope), values in scopes.items():
        assets[year][scope] = store.put(values)
    direct.pop("coverage", None)  # The map reads coverage from each panel.
    routes = operations["routes"]
    summary = {"routes": {key: routes[key] for key in ("aircraft", "newRanks", "newRoutes", "links", "fares")},
               "networks": {}, "networkScreen": {}, "directRoutes": direct,
               "localFareHubs": operations["localFareHubs"]}
    archive = store.put(operations)

    def strip(match):
        return match[1] + match[4] if match[2] in (b"core", b"manufacturer-data", b"operations-data") else match[0]

    html = BLOB.sub(strip, html)
    settings = dict(core=core, manufacturer=manufacturer, assets=assets, summary=summary, archive=archive)
    html = add_script(html, "const forecastAssets = " + inline_json(settings).decode() + ";")
    html = replace_once(html, "  const core = JSON.parse(document.getElementById('core').textContent);",
                        """  const initialHash = location.hash;
  let followInitialHash = initialHash.length > 1;
  if (followInitialHash) {
    for (const event of ['pointerdown', 'click', 'touchstart', 'keydown', 'wheel', 'hashchange', 'popstate']) {
      window.addEventListener(event, () => { followInitialHash = false; }, {capture: true, once: true, passive: true});
    }
  }
  function placeInitialAnchor(changed) {
    if (!followInitialHash || location.hash !== initialHash) return;
    requestAnimationFrame(() => {
      if (!followInitialHash || location.hash !== initialHash) return;
      const target = document.getElementById(initialHash.slice(1));
      if (!target) return;
      if (changed && !changed.contains(target) &&
          !(changed.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING)) return;
      target.scrollIntoView({block: 'start', behavior: 'instant'});
    });
  }
  let core;
  try { core = await forecastDownloads.load(forecastAssets.core); }
  catch (error) {
    forecastDownloads.retry(document.getElementById('regional-map'), 'Повторить загрузку прогноза', () => location.reload());
    return;
  }""")
    html = replace_once(html, "  BriefFleet.mount(document.getElementById('flow-fleet'), core, api);",
                        "  BriefFleet.mount(document.getElementById('flow-fleet'), core, api);\n"
                        "  placeInitialAnchor();")
    html = replace_once(html, '  BriefManufacturer.mount(document.getElementById(\'manufacturer\'), core, api, params,',
                        '  const manufacturer = document.getElementById("manufacturer");\n'
                        '  function mountManufacturer(data) {\n  BriefManufacturer.mount(manufacturer, core, api, params,')
    html = replace_once(html, '''    JSON.parse(document.getElementById('manufacturer-data').textContent));''',
                        '''    data);
  }
  const watch = (element, start, hashes) => {
    if (!window.IntersectionObserver) { start(); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) begin();
    });
    const match = () => hashes.some(hash => location.hash.startsWith(hash));
    function begin() {
      observer.disconnect();
      window.removeEventListener('hashchange', fromHash);
      start();
    }
    function fromHash() { if (match()) begin(); }
    if (match()) begin();
    else {
      window.addEventListener('hashchange', fromHash);
      observer.observe(element);
    }
  };
  manufacturer.style.minHeight = '12rem';
  watch(manufacturer, () => {
    const start = () => forecastDownloads.load(forecastAssets.manufacturer).then(data => {
      manufacturer.style.minHeight = '';
      mountManufacturer(data);
      placeInitialAnchor(manufacturer);
    }).catch(() => {
      forecastDownloads.retry(manufacturer, 'Повторить загрузку требований к самолёту', start);
    });
    start();
  }, ['#manufacturer']);''')
    html = replace_once(html, '''  const panel = document.getElementById('operations');
  try {''', '''  const panel = document.getElementById('operations');
  watch(panel, () => {
  try {''')
    start = html.index(b"    const packed = document.getElementById('operations-data');")
    marker = b"    panel.setAttribute('aria-busy', 'false');"
    stop = html.index(marker, start) + len(marker)
    html = html[:start] + b"    BriefOps.mount(panel, core, api, forecastAssets.summary, params);" + html[stop:]
    html = replace_once(html, """    // Fragment navigation may have run before the maps acquired their full heights.
    const anchor = document.getElementById(location.hash.slice(1));
    if (anchor && !window.scrollY) anchor.scrollIntoView();""", "    placeInitialAnchor(panel);")
    html = replace_once(html, '''    console.error(error);
  }
})();''', '''    console.error(error);
  }
  }, ['#operations']);
})();''')
    html = replace_once(html, '''    const panel = routes.rankings[method]?.''', '''    const panel = routes.rankings?.[method]?.''')
    html = replace_once(html, '''    const scopes = data?.horizons?.[state.year]?.methods?.[method]?.demands?.[demand]?.scopes;
    const panel = world ? scopes?.world : country ? scopes?.countries?.[country] : scopes?.regions?.[state.region];''',
                        '''    const panel = data?.scope?.[method]?.[demand];''')
    html = replace_once(html, '''    function render() {
      const state = api.state;
      const directRanking''', '''    let requested = 0;
    let activeScope;
    let archive;
    function render() {
      const request = ++requested;
      const state = api.state;
      const directRanking''')
    html = replace_once(html, '''      if (directRanking) view = fullDirectView''', '''      const path = directRanking
        ? forecastAssets.assets[state.year]?.[rankWorld ? "world" : country || state.region]
        : mode !== "ranking" ? forecastAssets.archive : null;
      if (path && (directRanking ? activeScope !== path : !archive)) {
        const summary = get(".bo-summary");
        get(".bo-grid").hidden = false;
        get(".bo-map").hidden = routeList.hidden = detail.hidden = true;
        get(".bo-artifacts").hidden = true;
        summary.textContent = "Загружается выбранный расчёт…";
        root.setAttribute("aria-busy", "true");
        get(".bo-controls").hidden = true;
        forecastDownloads.load(path).then(result => {
          if (request !== requested) return;
          if (directRanking) {
            data.directRoutes.scope = result;
            activeScope = path;
          } else {
            archive = result;
            Object.assign(data, archive);
          }
          render();
        }).catch(() => {
          if (request !== requested) return;
          forecastDownloads.retry(summary, "Повторить загрузку расчёта", render);
          root.setAttribute("aria-busy", "false");
        });
        return;
      }
      if (directRanking && !path) data.directRoutes.scope = activeScope = null;
      get(".bo-map").hidden = false;
      root.setAttribute("aria-busy", "false");
      if (directRanking) view = fullDirectView''')
    html = replace_once(html, '''        frame.dataset.scope=locationKey;
        }
        return;''', '''        frame.dataset.scope=locationKey;
        }
        root.setAttribute("aria-busy", "false");
        return;''')
    return html


def build_network(html, store):
    blocks = {}
    def strip(match):
        key = match[2].decode()
        if key == "payload":
            blocks[key] = decode(match[3])
            return match[1] + match[4]
        if key.startswith(("network-", "pool-")):
            blocks[key] = store.gzip(base64.b64decode(match[3]))
            return b""
        return match[0]

    html = BLOB.sub(strip, html)
    payload = blocks.pop("payload")
    payload["poolHubs"] = [key.removeprefix("pool-") for key in blocks if key.startswith("pool-")]
    world = payload.get("world")
    lookup, year_hubs, regions = {}, {}, defaultdict(dict)
    for iso, country in (world or {}).get("countries", {}).items():
        for year, data in country["years"].items():
            area = regions[country["region"]].setdefault(year, {})
            area[iso] = data
            year_hubs.setdefault(year, []).extend(data["hubs"])
        country["years"] = {}
    catalogue = defaultdict(list)
    for row in payload["study"]["results"]:
        catalogue[row["region"]].append(row)
        if not world:
            year_hubs.setdefault(str(row["year"]), []).append(row)
        lookup[row["hub"]] = {"hub_label": row.get("hub_label", row["hub"]), "country": row.get("country", "")}
    payload["study"]["results"] = []
    if world:
        for row in year_hubs.get(str(world["years"][0]), []):
            lookup[row["hub"]] = {"hub_label": row.get("hub_label", row["hub"]), "country": row.get("country", "")}
    defaults = {year: max((row for row in hubs if str(row["year"]) == year and row["route_count"] > 0),
                          key=lambda row: row["annual_profit_usd"], default={}).get("region")
                for year, hubs in year_hubs.items()}
    for area, years in regions.items():
        regions[area] = {year: store.put(rows) for year, rows in years.items()}
    lazy = dict(payload=store.put(payload), blocks=store.put(blocks), lookup=store.put(lookup), defaultRegions=defaults,
                regions=regions, archive={area: store.put(rows) for area, rows in catalogue.items()})
    html = add_script(html, "const forecastAssets = " + inline_json(lazy).decode() + ";")
    html = replace_once(html, """  const packed=document.getElementById('payload');
  const { study, diagnostic, fareHoldout, features, geometryNote, countries, fareCounts, localFares, world }=await unpack(packed);
  packed.remove();""", """  let networkData;
  try { networkData = await forecastDownloads.load(forecastAssets.payload); }
  catch (error) {
    forecastDownloads.retry(document.querySelector('.workspace'), 'Повторить загрузку сети', () => location.reload());
    return;
  }
  const {study, diagnostic, fareHoldout, features, geometryNote, countries, fareCounts, localFares, world} = networkData;
  const poolHubs = new Set(networkData.poolHubs);""")
    html = replace_once(html, '''  const firstYearHubs = world ? Object.values(world.countries).flatMap(country => country.years[firstYear]?.hubs ?? []) : study.results;
  const bestOverall = firstYearHubs.filter(row => Number(row.year) === firstYear && row.route_count>0)
    .sort((a,b) => b.annual_profit_usd - a.annual_profit_usd)[0];
  const firstRegion = scopeRegions[params.get('country')] ?? bestOverall?.region ?? regionOptions[0]?.[0];''',
                        '''  const firstRegion = scopeRegions[params.get('country')] ?? forecastAssets.defaultRegions[firstYear] ?? regionOptions[0]?.[0];''')
    html = replace_once(html, """    if (world && edition === 'world') {
      const selection""", """    if (world && edition === 'world') {
      const path = forecastAssets.regions[region]?.[year];
      const index = path ? await forecastDownloads.load(path) : {};
      if (request !== scopeRequest) return;
      for (const [iso, entry] of Object.entries(index)) world.countries[iso].years[year] = entry;
      const selection""")
    html = replace_once(html, '''    const candidates = study.results.filter''', '''    const path = forecastAssets.archive[region];
    const archived = path ? await forecastDownloads.load(path) : [];
    if (request !== scopeRequest) return;
    const candidates = archived.filter''')
    html = replace_once(html, """      const details=await unpack(el('network-'+plan.input_key));""", """      const blocks = await forecastDownloads.load(forecastAssets.blocks);
      const details = await forecastDownloads.load(blocks['network-'+plan.input_key]);""")
    html = replace_once(html, '''  const airports = new Map(study.results.map(row => [row.hub, row]));
  for (const country of Object.values(world?.countries ?? {})) {
    for (const row of country.years[world.years[0]]?.hubs ?? []) airports.set(row.hub, row);
  }''', '''  let airports;''')
    html = replace_once(html, '''    const pool = el('pool-'+plan.hub);
    const decoded = pool ? await unpack(pool) : [];''', '''    const [blocks, lookup] = await Promise.all([
      forecastDownloads.load(forecastAssets.blocks), forecastDownloads.load(forecastAssets.lookup),
    ]);
    const pool = blocks['pool-'+plan.hub];
    const decoded = pool ? [...await forecastDownloads.load(pool)] : [];
    airports ??= new Map(Object.entries(lookup));''')
    html = replace_once(html, """    box.hidden=!plan || (!el('pool-'+plan.hub) && !Object.keys(market?.references ?? {}).length);""",
                        """    box.hidden = !plan || (!poolHubs.has(plan.hub) && !Object.keys(market?.references ?? {}).length);""")
    html = replace_once(html, """  section.addEventListener('toggle', load);""", """  function openMarket() {
    const request = version;
    load().catch(() => {
      if (request === version) forecastDownloads.retry(el('marketCount'), 'Повторить загрузку реестра', openMarket);
    });
  }
  section.addEventListener('toggle', openMarket);""")
    html = replace_once(html, """    load();
  };
}""", """    openMarket();
  };
}""")
    html = replace_once(html, """  if (embedded) {
    new ResizeObserver(()=>window.parent.postMessage({kind:'fc-country-height',height:Math.ceil(document.body.getBoundingClientRect().height)},location.protocol==='file:'?'*':location.origin)).observe(document.body);
  }""", """  let scopeReady = false;
  function reportHeight() {
    if (embedded && scopeReady) {
      window.parent.postMessage({kind:'fc-country-height', height:Math.ceil(document.body.getBoundingClientRect().height)}, location.origin);
    }
  }
  if (embedded) new ResizeObserver(reportHeight).observe(document.body);""")
    replacements = {
        "el('region').addEventListener('change', () => changeScope": "el('region').addEventListener('change', () => openScope",
        "el('country').addEventListener('change', () => changeScope": "el('country').addEventListener('change', () => openScope",
        "el('year').addEventListener('change', () => changeScope": "el('year').addEventListener('change', () => openScope",
        "el('hub').addEventListener('change', () => changeScope": "el('hub').addEventListener('change', () => openScope",
        "el('edition').addEventListener('change', () => changeScope": "el('edition').addEventListener('change', () => openScope",
        "await changeScope(params.get('hub'),params.get('country'),initialEdition);":
            "await openScope(params.get('hub'),params.get('country'),initialEdition);",
    }
    for before, after in replacements.items():
        html = replace_once(html, before, after)
    html = replace_once(html, """  el('region').addEventListener('change', () => openScope""", """
  const loadError = document.createElement('button');
  loadError.type = 'button';
  loadError.textContent = 'Повторить загрузку сети';
  loadError.hidden = true;
  el('region').closest('label').after(loadError);
  async function openScope(...args) {
    const request = scopeRequest + 1;
    scopeReady = false;
    loadError.hidden = true;
    try { await changeScope(...args); }
    catch (error) {
      if (request !== scopeRequest) return;
      loadError.onclick = () => openScope(...args);
      loadError.hidden = false;
    } finally {
      if (request === scopeRequest) {
        scopeReady = true;
        reportHeight();
      }
    }
  }
  el('region').addEventListener('change', () => openScope""")
    return html


def build_web(root, forecast, network):
    store = Store(root)
    paths = {}
    for name, content in (("forecast", build_forecast(forecast, store)), ("network", build_network(network, store))):
        path = store.root / (name + ".html")
        path.write_bytes(content)
        paths[name] = path
    return paths
