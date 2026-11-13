/* FlightCost side: one full-page iframe (never a modal), no imports or modules.
 * The top-level page stays on flightcost.app so its guest workspace is
 * first-party. A server-validated, owner-scoped write is required for success.
 */
(function (root) {
  'use strict';
  var DESIGNER_ORIGIN = 'https://aircraft-designer.app';
  var PROTOCOL = 'aircraft-designer/flightcost-design';
  var VERSION = 1;

  function isValidDesign(design, expectedIcao, acceptedEngines) {
    if (!design || typeof design !== 'object' || design.protocol !== PROTOCOL || design.version !== VERSION ||
        !design.aircraft || !design.weights) return false;
    var a = design.aircraft;
    var allowed = Array.isArray(acceptedEngines) ? acceptedEngines : [acceptedEngines];
    if (a.icao !== expectedIcao || !allowed.includes(a.engine) ||
        !Array.isArray(a.cabin) || a.cabin.length === 0 || a.cabin.length > 100) return false;
    var count = 0;
    for (var i = 0; i < a.cabin.length; i++) {
      var z = a.cabin[i];
      if (!z || !['economy', 'business', 'premium'].includes(z.class) ||
          !Number.isInteger(z.rows) || z.rows < 1 || z.rows > 100 ||
          !Number.isInteger(z.seatsPerRow) || z.seatsPerRow < 2 || z.seatsPerRow > 10 ||
          !Number.isFinite(z.pitchM) || z.pitchM < 0.65 || z.pitchM > 1.5) return false;
      var end = z.lastRowSeats === undefined ? z.seatsPerRow : z.lastRowSeats;
      if (!Number.isInteger(end) || end < 1 || end > z.seatsPerRow) return false;
      count += (z.rows - 1) * z.seatsPerRow + end;
    }
    if (!Number.isInteger(a.seats) || a.seats < 1 || a.seats > 400 || count !== a.seats) return false;
    var w = design.weights;
    for (var j = 0, keys = ['oew_kg', 'mtow_kg', 'mzfw_kg', 'mlw_kg', 'fuel_capacity_kg']; j < keys.length; j++) {
      var val = w[keys[j]];
      if (typeof val !== 'number' || !Number.isFinite(val) || val < 0 || val > 1000000) return false;
    }
    if (!(w.oew_kg < w.mzfw_kg && w.mzfw_kg <= w.mtow_kg && w.mlw_kg <= w.mtow_kg)) return false;
    // These numbers are proposed engineering inputs, NOT a verified fuel burn model.
    if (!design.model || design.model.provisional !== true) return false;
    return true;
  }

  function mount(options) {
    if (!options || !options.container || !/^[A-Z0-9]{2,5}$/.test(options.icao) || !options.engine) {
      throw new Error('Aircraft Designer: container, ICAO and an exact engine are required');
    }
    var icao = options.icao;
    var engines = options.supportedEngines || [options.engine];
    var url = new URL('/', DESIGNER_ORIGIN);
    url.searchParams.set('embed', 'flightcost');
    url.searchParams.set('ac', icao);
    url.searchParams.set('engine', options.engine);
    if (options.layoutId) url.searchParams.set('layout', options.layoutId);
    if (options.aircraftId) url.searchParams.set('aircraft', options.aircraftId);
    if (options.weightProfile) url.searchParams.set('profile', options.weightProfile);

    var status = options.status || document.createElement('p');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    var frame = document.createElement('iframe');
    frame.title = icao + ': Aircraft Designer';
    frame.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.setAttribute('loading', 'eager');
    frame.setAttribute('allowfullscreen', '');
    frame.src = url.href;
    options.container.append(frame);
    if (!options.status) options.container.append(status);
    var active = true;
    var saving = false;
    async function onMessage(event) {
      if (!active || saving || event.origin !== DESIGNER_ORIGIN || event.source !== frame.contentWindow) return;
      var msg = event.data;
      if (!msg || msg.protocol !== PROTOCOL || msg.version !== VERSION || msg.type !== 'DESIGN_EXPORT' ||
          typeof msg.requestId !== 'string' || !/^[a-zA-Z0-9-]{8,80}$/.test(msg.requestId)) return;
      var ack = function (saved, error) {
        if (active && frame.contentWindow) frame.contentWindow.postMessage({
          protocol: PROTOCOL, version: VERSION, type: 'DESIGN_ACK', requestId: msg.requestId,
          saved: saved, ...(error ? { error: error } : {})
        }, DESIGNER_ORIGIN);
      };
      if (!isValidDesign(msg.design, icao, engines)) {
        status.textContent = 'Ошибка: тип, двигатель, компоновка или массы не совпали';
        ack(false, status.textContent);
        return;
      }
      if (typeof options.saveDesign !== 'function') {
        status.textContent = '3D доступен. Сохранение в FlightCost ещё не подключено';
        ack(false, status.textContent);
        return;
      }
      saving = true;
      status.textContent = 'Сохранение в workspace FlightCost…';
      var saved = null;
      var committed = false;
      try {
        // The callback MUST do a same-origin, CSRF-protected write to the CURRENT guest workspace.
        saved = await options.saveDesign(msg.design, msg.requestId);
        if (!saved || typeof saved.id !== 'string' || !saved.id.trim() || saved.id.length > 256) {
          throw new Error('Workspace не подтвердил запись ID сохранённого самолёта');
        }
        committed = true;
        status.textContent = 'Самолёт сохранён в FlightCost';
        ack(true);  // Never acknowledge before the actual persistence promise resolves.
      } catch (error) {
        status.textContent = 'Ошибка сохранения: ' + (error instanceof Error ? error.message : String(error));
        ack(false, status.textContent);
      } finally { saving = false; }
      // Navigation/UI hook errors do not retroactively change a successful DB write.
      if (committed && typeof options.onSaved === 'function') {
        try { options.onSaved(saved, msg.design); } catch (_ignored) { /* confirmed save remains valid */ }
      }
    }
    root.addEventListener('message', onMessage);
    return {
      url: url.href,
      destroy: function () {
        active = false;
        root.removeEventListener('message', onMessage);
        frame.src = 'about:blank';
        frame.remove();
        if (!options.status) status.remove();
      }
    };
  }
  root.AircraftDesignerFlightCost = Object.freeze({ mount: mount, isValidDesign: isValidDesign });
})(window);
