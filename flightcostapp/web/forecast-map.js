(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const cases = {base: 'Базовый сценарий', optimistic: 'Оптимистичный сценарий', pessimistic: 'Пессимистичный сценарий'};
  const kinds = {result: 'Результат расчёта', input: 'Параметр сценария', user: 'Параметр сценария',
    model: 'Расчёт модели', context: 'Контекст и проверка', group: 'Географическая разбивка',
    region: 'Прогноз субрегиона', source: 'Первоисточник', assumption: 'Допущение модели'};
  const mobile = window.matchMedia('(max-width: 820px)');
  const work = document.querySelector('.fm-work');
  const panel = $('fm-inspector');
  const mathBand = $('fm-math');
  const mathModes = $('fm-math-modes');
  const page = window.ForecastMapPageData;
  const isProbe = new URLSearchParams(location.search).getAll('probe').includes('dev');
  let state, graph, parents, active, path, scene, modelRegion, linkPage = 0, lastAddress;
  let formulaMode = 'symbols';

  function initialState(query, fragment) {
    let restored = {};
    try { restored = JSON.parse(fragment.get('scenario') || '{}') || {}; } catch { /* Use the published defaults. */ }
    const core = page.core;
    const years = core.series.years;
    const year = Number(restored.year || query.get('year'));
    const country = query.get('country');
    const countryRegion = country && Object.keys(core.countries || {}).find(id => Object.hasOwn(core.countries[id], country));
    const region = restored.region || countryRegion || query.get('region');
    return {
      year: years.includes(year) ? year : (years.includes(2031) ? 2031 : years[0]),
      region: region && region !== 'world' && Object.hasOwn(core.series.regions, region) ? region : 'Eastern Europe',
      demand: Object.hasOwn(cases, restored.demand) ? restored.demand : 'base',
      scenarios: restored.scenarios && typeof restored.scenarios === 'object' && !Array.isArray(restored.scenarios)
        ? restored.scenarios : {},
    };
  }

  function regionIn(trail = []) {
    const node = trail.findLast(id => id.startsWith('region:'));
    return node?.split(':')[1];
  }

  function rebuild(focusRegion = regionIn(path) || state.region) {
    const query = new URLSearchParams(location.search);
    modelRegion = focusRegion;
    graph = window.ForecastMapModel.build(page.core, {...state, lang: page.lang, focusRegion,
      country: query.get('country'), hub: query.get('hub')});
    parents = new Map(Object.keys(graph.nodes).map(id => [id, []]));
    for (const node of Object.values(graph.nodes)) {
      for (const edge of node.inputs || []) {
        const consumers = parents.get(edge.id);
        if (consumers && !consumers.some(item => item.id === node.id)) consumers.push({...edge, id: node.id, output: true});
      }
    }
    $('fm-year').value = String(state.year);
    $('fm-case').textContent = cases[state.demand];
    const report = new URL(page.forecastUrl, location.href);
    report.search = location.search;
    report.searchParams.set('year', state.year);
    report.hash = new URLSearchParams({scenario: JSON.stringify(state)});
    $('fm-report').href = report.href;
    $('fm-report').title = 'Открыть этот сценарий в прогнозе';
  }

  function pathTo(id, start = graph.root) {
    const previous = new Map([[start, null]]);
    const queue = [start];
    for (let cursor = 0; cursor < queue.length && !previous.has(id); cursor++) {
      const owner = queue[cursor];
      for (const edge of graph.nodes[owner].inputs || []) {
        if (graph.nodes[edge.id] && !previous.has(edge.id)) {
          previous.set(edge.id, owner); queue.push(edge.id);
        }
      }
    }
    if (!previous.has(id)) return [start];
    const result = [];
    for (let step = id; step != null; step = previous.get(step)) result.push(step);
    return result.reverse();
  }
  function linksOf(id) {
    const node = graph.nodes[id];
    const neighbours = new Map();
    for (const edge of [...(node.inputs || []), ...(parents.get(id) || [])]) {
      if (edge.id !== id && graph.nodes[edge.id] && !neighbours.has(edge.id)) neighbours.set(edge.id, edge);
    }
    return [...neighbours.values()];
  }

  function writeAddress() {
    const url = new URL(location.href);
    url.searchParams.set('year', state.year);
    const hash = new URLSearchParams(url.hash.slice(1));
    if (hash.has('scenario') || state.demand !== 'base' || Object.keys(state.scenarios).length) {
      hash.set('scenario', JSON.stringify(state));
    }
    if (active === graph.root) hash.delete('node'); else hash.set('node', active);
    const via = regionIn(path);
    if (via && !active.startsWith('region:')) hash.set('viaRegion', via);
    else hash.delete('viaRegion');
    url.hash = hash.toString();
    if (url.href !== location.href) history.pushState({forecastMapPath: path}, '', url);
    lastAddress = location.href;
  }

  function restore() {
    if (lastAddress === location.href) return;
    const url = new URL(location.href), fragment = new URLSearchParams(url.hash.slice(1));
    state = initialState(url.searchParams, fragment);
    const id = fragment.get('node');
    const via = fragment.get('viaRegion');
    const viaNode = via && via !== 'world' && Object.hasOwn(page.core.series.regions, via) ? 'region:' + via : null;
    rebuild(regionIn(id ? [id] : []) || (viaNode && via) || state.region);
    active = id && Object.hasOwn(graph.nodes, id) ? id : graph.root;
    const previous = history.state?.forecastMapPath;
    if (Array.isArray(previous) && previous[0] === graph.root && previous.at(-1) === active &&
        previous.every(step => Object.hasOwn(graph.nodes, step))) {
      path = [...previous];
    } else {
      const branch = viaNode && graph.nodes[viaNode] ? pathTo(active, viaNode) : [];
      path = branch.at(-1) === active ? [...pathTo(viaNode), ...branch.slice(1)] : pathTo(active);
    }
    if ((regionIn(path) || state.region) !== modelRegion) rebuild();
    linkPage = 0;
    lastAddress = location.href;
    draw(false);
  }

  function choose(id, via) {
    if (!Object.hasOwn(graph.nodes, id)) return;
    if (id !== active) {
      const previousActive = active;
      const position = path.indexOf(id);
      if (position >= 0) path = path.slice(0, position + 1);
      else if (graph.nodes[active].inputs?.some(edge => edge.id === id)) path = [...path, id];
      else if (via && graph.nodes[active].inputs?.some(edge => edge.id === via) &&
          graph.nodes[via].inputs?.some(edge => edge.id === id)) path = [...path, via, id];
      else path = pathTo(id);
      active = id; linkPage = 0;
      if ((regionIn(path) || state.region) !== modelRegion) rebuild();
      writeAddress();
      draw(true, previousActive);
    }
    if (mobile.matches) openDrawer();
    else scene.entries.find(item => item.id === active)?.button.focus({preventScroll: true});
  }

  function draw(animate, previous) {
    const trail = $('fm-trail');
    trail.replaceChildren();
    path.forEach((id, i) => {
      if (i) {
        const separator = el('span', '›', 'fm-separator');
        separator.setAttribute('aria-hidden', 'true'); trail.append(separator);
      }
      const button = el('button', graph.nodes[id].label);
      button.type = 'button';
      if (id === active) button.setAttribute('aria-current', 'location');
      button.onclick = () => choose(id);
      trail.append(button);
    });
    const nearest = linksOf(active);
    const parent = path.at(-2);
    const parentIndex = nearest.findIndex(item => item.id === parent);
    if (parentIndex > 0) nearest.unshift(...nearest.splice(parentIndex, 1));
    const size = 8;
    const pages = Math.max(1, Math.ceil(nearest.length / size));
    linkPage = Math.min(linkPage, pages - 1);
    const visible = nearest.slice(linkPage * size, (linkPage + 1) * size);
    scene.show(graph.nodes, active, visible, parent || previous, animate);
    const pager = $('fm-pager'); pager.replaceChildren(); pager.hidden = pages < 2;
    if (pages > 1) {
      const part = el('span', 'Связи ' + (linkPage * size + 1) + '–' + (linkPage * size + visible.length) + ' из ' + nearest.length);
      const navigate = (label, step) => {
        const button = el('button', step < 0 ? '‹' : '›');
        button.type = 'button'; button.setAttribute('aria-label', label);
        button.disabled = linkPage + step < 0 || linkPage + step >= pages;
        button.onclick = () => {
          linkPage += step; draw(false);
          const buttons = [...pager.querySelectorAll('button')];
          const next = buttons.find(item => item.getAttribute('aria-label') === label && !item.disabled) ||
            buttons.find(item => !item.disabled);
          next?.focus({preventScroll: true});
        };
        return button;
      };
      pager.append(part, navigate('Предыдущие связи', -1), navigate('Следующие связи', 1));
    }
    inspector(graph.nodes[active], nearest);
  }

  function section(title) {
    const block = el('section', null, 'fm-panel-section');
    block.append(el('h3', title)); return block;
  }
  function extra(title, body) {
    const details = el('details', null, 'fm-extra');
    details.append(el('summary', title), body); return details;
  }
  function values(rows) {
    const dl = el('dl', null, 'fm-values');
    for (const [label, value, measure] of rows) {
      const item = el('div');
      const cell = el('dd');
      if (measure) cell.append(formattedQuantity(measure.number, measure.unit));
      else cell.textContent = value;
      item.append(el('dt', label), cell); dl.append(item);
    }
    return dl;
  }
  function link(label, uri, cls) {
    let url;
    try { url = new URL(uri, location.href); } catch { return el('span', label); }
    if (!['https:', 'http:'].includes(url.protocol)) return el('span', label);
    const own = url.origin === location.origin;
    if (isProbe && own) url.searchParams.set('probe', 'dev');
    const anchor = el('a', label, cls);
    anchor.href = url.href;
    if (!own) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; }
    return anchor;
  }

  function mathText(text) {
    const fragment = document.createDocumentFragment();
    // Superscript only the simple powers used in the published derivations.
    // Keep an unrecognised expression intact, including its caret.
    const power = /\^\(((?:[^()]|\([^()]*\))+)\)|\^([−-]?\d+(?:[.,]\d+)?)/g;
    let start = 0;
    for (const match of text.matchAll(power)) {
      fragment.append(text.slice(start, match.index), el('sup', match[1] ?? match[2]));
      start = match.index + match[0].length;
    }
    fragment.append(text.slice(start));
    return fragment;
  }

  function formattedQuantity(number, unit, numberClass) {
    const fragment = document.createDocumentFragment();
    const value = el(numberClass ? 'strong' : 'span', null, numberClass);
    value.lang = page.lang;
    value.append(mathText(number));
    fragment.append(value);
    if (unit) {
      const label = el('small', unit, 'fc-value-unit');
      label.lang = page.lang;
      fragment.append(' ', label);
    }
    return fragment;
  }

  function placeMath() {
    const target = mobile.matches && work.classList.contains('has-drawer') ? $('fm-drawer-math') : $('fm-math-slot');
    if (target && mathBand.parentElement !== target) target.append(mathBand);
  }

  function showNotation(math) {
    const guide = math.trendGuide;
    const symbolic = Boolean(guide && formulaMode === 'symbols');
    mathModes.hidden = !guide;
    for (const button of mathModes.querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === (symbolic ? 'symbols' : 'values')));
    }

    const formula = $('fm-math-substitution');
    formula.replaceChildren();
    formula.hidden = !math.substitution;
    if (math.substitution) {
      const before = symbolic ? guide.symbolic + ' ≈ ' : math.beforeResult;
      if (before != null && math.result) {
        formula.append(mathText(before), formattedQuantity(math.result.number, math.result.unit, 'fm-formula-result'));
      } else {
        formula.append(mathText(math.substitution));
      }
      const description = symbolic ? before + [math.result.number, math.result.unit].filter(Boolean).join(' ') : math.substitution;
      formula.setAttribute('aria-label', description);
    } else formula.removeAttribute('aria-label');

    const legend = $('fm-math-legend');
    legend.replaceChildren();
    legend.hidden = !guide;
    if (!guide) return;
    legend.setAttribute('aria-label', symbolic ? 'Обозначения в формуле' : 'Значения в формуле');
    for (const {symbol, meaning, value, unit, scale, period, status} of guide.legend) {
      const row = el('div'), key = el('dt'), definition = el('dd');
      const label = el('span', meaning, 'fm-variable-meaning');
      if (symbolic) {
        key.textContent = symbol;
      } else {
        key.append(formattedQuantity(value, scale || unit));
        key.lang = page.lang;
        key.setAttribute('aria-label', [value, unit].filter(Boolean).join(' '));
        if (period) label.append(el('span', ' · ' + period, 'fm-variable-period'));
      }
      definition.append(label);
      if (status) definition.append(el('span', status, 'fm-variable-status'));
      row.append(key, definition);
      legend.append(row);
    }
  }

  function showMath(node) {
    placeMath();
    const math = node.math;
    mathBand.hidden = !(math?.expression || math?.substitution || math?.note);
    if (mathBand.hidden) return;
    const title = math.label || (node.id === 'historyWorld' ? 'Ретропроверка' : node.kind === 'source' ? 'Исходные данные' :
      node.kind === 'group' ? 'Разбиение' : node.kind === 'assumption' ? 'Допущение' : 'Расчёт');
    $('fm-math-title').textContent = title + ' · ' + node.label;
    const source = $('fm-math-source');
    source.replaceChildren();
    source.hidden = !math.source?.url;
    if (!source.hidden) source.append(link(math.source.title, math.source.url));
    const expression = $('fm-math-expression');
    expression.hidden = !math.expression;
    expression.replaceChildren();
    if (math.expression) {
      expression.append(mathText(math.expression));
      expression.setAttribute('aria-label', math.expression);
    } else expression.removeAttribute('aria-label');
    showNotation(math);
    const reading = $('fm-math-reading'), note = $('fm-math-note');
    reading.hidden = !(math.trendGuide && math.note);
    const noteParent = reading.hidden ? mathBand : reading;
    if (note.parentElement !== noteParent) noteParent.append(note);
    note.hidden = !math.note;
    note.textContent = math.note || '';
  }

  function inspector(node, nearest) {
    const body = $('fm-panel-body');
    body.replaceChildren();
    panel.style.setProperty('--node-color', 'var(' + window.ForecastMapScene.color(node.kind) + ')');
    $('fm-kind').textContent = kinds[node.kind] || 'Узел модели';
    const title = el('h2', node.label);
    title.id = 'fm-selected-title'; title.tabIndex = -1; body.append(title);
    const drawerSlot = el('div');
    drawerSlot.id = 'fm-drawer-math'; body.append(drawerSlot);
    showMath(node);
    if (node.display) {
      const result = el('div', null, 'fm-result');
      result.append(formattedQuantity(node.display.number, node.display.unit, 'fc-kpi-number'));
      body.append(result);
    }
    if (node.description) body.append(el('p', node.description, 'fm-description'));
    const network = (node.links || []).find(item => {
      try { return new URL(item.url, location.href).pathname === page.networkUrl; } catch { return false; }
    });
    if (network) {
      body.append(link(network.label + ' →', network.url, 'fm-route-action'));
      if (state.demand !== 'base' || Object.keys(state.scenarios).length) {
        body.append(el('p', 'Сетевая карта откроет тот же год и географию. Маршрутные значения взяты из опубликованного расчёта сети.', 'fm-source-detail'));
      }
    }
    if (node.rows?.length || node.methodNote || (node.formula && !node.math)) {
      const method = section(node.kind === 'source' ? 'Как получены данные' : 'Исходные значения');
      if (node.formula && !node.math) method.append(el('p', node.formula, 'fm-formula'));
      const rows = node.rows || [];
      // Short numerical substitutions stay next to the formula. Long filters and notes remain available.
      const compact = rows.filter(row => String(row[1]).length < 85).slice(0, 5);
      if (compact.length) method.append(values(compact));
      const rest = rows.filter(row => !compact.includes(row));
      if (rest.length || node.methodNote) {
        const details = el('div');
        if (node.methodNote) details.append(el('p', node.methodNote, 'fm-description'));
        if (rest.length) details.append(values(rest));
        method.append(extra('Подробности методики', details));
      }
      body.append(method);
    }
    if (node.sources?.length) {
      const sources = section(node.sources.length === 1 ? 'Первоисточник' : 'Первоисточники');
      for (const record of node.sources) {
        const group = el('div', null, 'fm-source');
        group.append(link(record.title, record.url));
        if (record.detail && record.detail !== node.description) group.append(el('p', record.detail, 'fm-source-detail'));
        sources.append(group);
      }
      body.append(sources);
    }
    const more = (node.links || []).filter(item => item !== network);
    if (more.length) {
      const files = section(more.some(item => /маршрут/i.test(item.label)) ? 'Продолжить разбор' : 'Проверить расчёт');
      for (const item of more) files.append(link(item.label, item.url, 'fm-action'));
      body.append(files);
    }
    if (nearest.length) {
      const relations = section('Прямые связи');
      const list = records => {
        const ul = el('ul', null, 'fm-connections');
        for (const item of records) {
          const li = el('li'), button = el('button');
          button.type = 'button';
          button.dataset.targetNode = item.id;
          button.append(el('span', graph.nodes[item.id].label));
          button.append(el('small', item.output ? 'Используется в' : item.label));
          button.onclick = () => choose(item.id);
          li.append(button); ul.append(li);
        }
        return ul;
      };
      relations.append(list(nearest.slice(0, 6)));
      if (nearest.length > 6) relations.append(extra('Показать остальные связи (' + (nearest.length - 6) + ')', list(nearest.slice(6))));
      body.append(relations);
    }
    panel.scrollTop = 0;
  }

  function openDrawer() {
    if (!mobile.matches) return;
    work.classList.add('has-drawer');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    $('fm-scrim').hidden = false; document.body.classList.add('fm-modal-open');
    placeMath();
    $('fm-selected-title')?.focus({preventScroll: true});
  }
  function closeDrawer(returnFocus = true) {
    const wasOpen = work.classList.contains('has-drawer');
    work.classList.remove('has-drawer');
    panel.removeAttribute('role'); panel.removeAttribute('aria-modal');
    $('fm-scrim').hidden = true; document.body.classList.remove('fm-modal-open');
    placeMath();
    if (wasOpen && returnFocus) scene.entries.find(item => item.id === active)?.button.focus({preventScroll: true});
  }
  function init() {
    const notationKey = 'fca.forecastMap.formulaMode';
    try { if (sessionStorage.getItem(notationKey) === 'values') formulaMode = 'values'; } catch { /* Optional display preference. */ }
    for (const button of mathModes.querySelectorAll('button')) {
      button.onclick = () => {
        formulaMode = button.dataset.mode;
        try { sessionStorage.setItem(notationKey, formulaMode); } catch { /* Keep the choice on this page. */ }
        showNotation(graph.nodes[active].math);
      };
    }
    scene = new window.ForecastMapScene.ForecastScene($('fm-scene'), choose,
      display => formattedQuantity(display.number, display.scale, 'fc-kpi-number'));
    const year = $('fm-year');
    for (const y of page.core.series.years) year.append(new Option(y, y));
    year.onchange = () => {
      state = {...state, year: Number(year.value)};
      rebuild(); writeAddress(); draw(false);
    };
    $('fm-open').onclick = openDrawer;
    $('fm-close').onclick = () => closeDrawer();
    $('fm-scrim').onclick = () => closeDrawer();
    mobile.addEventListener('change', () => { closeDrawer(false); if (graph) draw(false); });
    document.addEventListener('keydown', e => {
      if (!work.classList.contains('has-drawer')) return;
      if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); }
      if (e.key === 'Tab') {
        const focusable = [...panel.querySelectorAll('button,a,summary')].filter(n => n.getClientRects().length);
        const first = focusable[0], last = focusable.at(-1);
        if (e.shiftKey && (document.activeElement === first || document.activeElement === $('fm-selected-title'))) {
          e.preventDefault(); last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    });
    window.addEventListener('popstate', () => {
      const refocus = work.classList.contains('has-drawer') || document.activeElement?.closest('#fm-nodes, #fm-trail');
      closeDrawer(false); restore();
      if (refocus) scene.entries.find(item => item.id === active)?.button.focus({preventScroll: true});
    });
    window.addEventListener('hashchange', restore);
    restore(); $('fm-loading').hidden = true;
  }
  try { init(); } catch (error) {
    const notice = $('fm-loading');
    notice.hidden = false; notice.setAttribute('role', 'alert');
    notice.textContent = 'Не удалось прочитать карту этой редакции. ';
    notice.append(link('Открыть методику прогноза', (page?.forecastUrl || '../forecast') + '#scenario-methods'));
    console.error(error);
  }
})();
