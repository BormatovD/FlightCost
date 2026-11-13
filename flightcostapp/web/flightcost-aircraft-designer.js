/* FlightCost type-page bootstrap. Plain ES5-compatible script (no modules).
 * No navigation, DB mutation or network call until an explicit user action.
 */
(function () {
  'use strict';
  function init() {
    var cfgEl = document.getElementById('fc3d-data');
    if (!cfgEl || !window.AircraftDesignerFlightCost) return;
    var cfg = JSON.parse(cfgEl.textContent);
    var $ = function (id) { return document.getElementById(id); };
    var select = $('fc3d-choice');
    var msg = $('fc3d-message');
    var notes = $('fc3d-engine-note');
    var links = $('fc3d-links');
    var create = $('fc3d-create');
    var mount = $('fc3d-mount');
    var bridge = window.AircraftDesignerFlightCost;
    var mounted = null;

    function engineToken(s) {
      var tokens = { 'пс-90а': 'ps-90a', 'ps-90a': 'ps-90a' };
      var text = String(s || '').replace(/^\s*2\s*[×x]\s*/i, '').replace(/\s+/g, '').toLocaleLowerCase();
      return tokens[text] || text;
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
        create.hidden = true;
        say(cfg.text.created);
        links.replaceChildren(link(window.location.origin + '/w#' + w.key,
                                   '/w#' + w.key));
      } catch (e) { say(cfg.text.error + String(e.message || e)); }
      finally { create.disabled = false; }
    });
    function pick() {
      var option = cfg.choices[Number(select.value)];
      if (!option) return;
      if (mounted) mounted.destroy();
      links.replaceChildren();
      say('');
      if (matchingEngine(option.engine, cfg.refEngine)) notes.textContent = '';
      else notes.textContent = cfg.text.different.replace('{designer}', option.engine)
        .replace('{flightcost}', cfg.refEngine || '—');
      mounted = bridge.mount({
        container: mount,
        icao: cfg.icao,
        engine: option.engine,
        aircraftId: option.aircraftId,
        layoutId: option.layoutId,
        weightProfile: option.weightProfile,
        supportedEngines: [option.engine],
        buttonText: cfg.text.open,
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
        onSaved: function (stored) {
          var data = stored.data;
          say(cfg.text.saved + ' ' + data.icao + ' (' + data.seats + ')');
          links.replaceChildren();
          if (data.burn_inherited) {
            var o = cfg.route[0], d = cfg.route[1];
            links.append(link(cfg.text.calc, '/' + cfg.lang + '/calc?o=' + encodeURIComponent(o)
                  + '&d=' + encodeURIComponent(d) + '&ac=' + encodeURIComponent(data.icao)));
            links.append(' · ' + cfg.text.caveat);
          } else {
            links.textContent = cfg.text.caveat;
          }
        }
      });
    }
    select.addEventListener('change', pick);
    pick();
    updateWorkspace();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
