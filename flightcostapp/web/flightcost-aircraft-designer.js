/* Separate FlightCost 3D workbench. Ordinary script; no JS modules.
 * This only runs on /<lang>/type/<ICAO>/3d, not the indexable type card.
 */
(function () {
  'use strict';
  async function init() {
    var cfgEl = document.getElementById('fc3d-data');
    if (!cfgEl || !window.AircraftDesignerFlightCost) return;
    var cfg = JSON.parse(cfgEl.textContent);
    var option = cfg.choices[cfg.selected];
    if (!option) return;
    var $ = function (id) { return document.getElementById(id); };
    var msg = $('fc3d-message');
    var notes = $('fc3d-engine-note');
    var links = $('fc3d-links');
    var workspace = $('fc3d-workspace');
    var create = $('fc3d-create');
    var mount = $('fc3d-mount');
    var bridge = window.AircraftDesignerFlightCost;

    function engineToken(s) {
      var tokens = { 'пс-90а': 'ps-90a', 'ps-90a': 'ps-90a' };
      var txt = String(s || '').replace(/^\s*2\s*[×x]\s*/i, '').replace(/\s+/g, '').toLocaleLowerCase();
      return tokens[txt] || txt;
    }
    function matchingEngine(a, b) {
      return !!(engineToken(a) && engineToken(b) && engineToken(a) === engineToken(b));
    }
    function say(t) { msg.textContent = t || ''; }
    function link(text, href) {
      var a = document.createElement('a');
      a.href = href;
      a.textContent = text;
      return a;
    }
    async function json(path, body) {
      var response = await fetch(path, body === undefined ? { credentials: 'same-origin' } : {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin', body: JSON.stringify(body)
      });
      var result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || 'HTTP ' + response.status);
      return result;
    }
    async function updateWorkspace() {
      try { create.hidden = !!(await json('/api/ws')).exists; }
      catch (e) { create.hidden = true; say(cfg.text.error + String(e.message || e)); }
    }
    create.addEventListener('click', async function () {
      create.disabled = true;
      try {
        var w = await json('/api/ws/new', {});
        if (!w.key) throw new Error('Workspace did not return its access key');
        create.hidden = true;
        say(cfg.text.created);
        // Keep the secret workspace link visible after any successful save.
        workspace.replaceChildren(link(window.location.origin + '/w#' + w.key,
                                       '/w#' + encodeURIComponent(w.key)));
      } catch (e) { say(cfg.text.error + String(e.message || e)); }
      finally { create.disabled = false; }
    });
    if (matchingEngine(option.engine, cfg.refEngine)) notes.textContent = '';
    else notes.textContent = cfg.text.different.replace('{designer}', option.engine)
      .replace('{flightcost}', cfg.refEngine || '—');

    bridge.mount({
      container: mount,
      status: msg,
      icao: cfg.icao,
      engine: option.engine,
      routeNm: cfg.routeNm,
      designerOrigin: cfg.designerOrigin,
      aircraftId: option.aircraftId,
      layoutId: option.layoutId,
      weightProfile: option.weightProfile,
      supportedEngines: [option.engine],
      saveDesign: async function (design, requestId) {
        var ws = await json('/api/ws');
        if (!ws.exists) {
          create.hidden = false;
          throw new Error(cfg.text.need);
        }
        if (design.aircraft.aircraftId !== option.aircraftId ||
            design.aircraft.layoutId !== option.layoutId ||
            design.aircraft.weightProfile !== option.weightProfile) {
          throw new Error('3D model/engine/layout mismatch');
        }
        say(cfg.text.saving);
        var stored = await json('/api/aircraft/designer-save', {
          requestId: requestId, design: design
        });
        return { id: stored.id, data: stored };
      },
      onSaved: function (stored, design, routeLoad) {
        var data = stored.data;
        say(cfg.text.saved + ' ' + data.icao + ' (' + data.seats + ')');
        links.replaceChildren(link(cfg.text.back, cfg.backHref), link(cfg.text.workspace, '/w'));
        if (data.burn_inherited || data.route_model) {
          var o = cfg.route[0], d = cfg.route[1];
          links.append(link(cfg.text.calc, '/' + cfg.lang + '/calc?o=' + encodeURIComponent(o)
                + '&d=' + encodeURIComponent(d) + '&ac=' + encodeURIComponent(data.icao)
                + (data.route_model && Number.isInteger(routeLoad) && routeLoad >= 40 && routeLoad <= 100 ? '&load=' + routeLoad : '')));
        } else {
          links.append(cfg.text.caveat);
        }
      }
    });
    updateWorkspace();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
