'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { resolve } = require('node:path');

const script = readFileSync(resolve(__dirname, '../flightcostapp/web/flightcost-embed.nomodule.js'), 'utf8');
const data = {
  protocol: 'aircraft-designer/flightcost-design', version: 1,
  aircraft: { icao: 'B752', aircraftId: 'b757-200-rb', engine: 'RB211-535E4',
    weightProfile: 'standard', layoutId: 'b752-225', seats: 225,
    cabin: [{ class: 'economy', rows: 38, seatsPerRow: 6, pitchM: .745, lastRowSeats: 3 }] },
  weights: { oew_kg: 56034, mtow_kg: 108862, mzfw_kg: 83461, mlw_kg: 89811, fuel_capacity_kg: 33508 },
  model: { provisional: true }
};
function browser() {
  const handlers = new Map();
  class FakeNode {
    constructor(tag) {
      this.children = []; this.attributes = {}; this.listeners = {}; this.style = {};
      if (tag === 'iframe') {
        this.contentWindow = { messages: [], postMessage: (m, origin) => this.contentWindow.messages.push({ m, origin }) };
      }
    }
    append(...x) { this.children.push(...x); }
    setAttribute(a, b) { this.attributes[a] = b; }
    addEventListener(e, fn) { this.listeners[e] = fn; }
    remove() { this.removed = true; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    click() { this.listeners.click(); }
  }
  const window = {
    addEventListener: (e, fn) => handlers.set(e, fn),
    removeEventListener: (e, fn) => { if (handlers.get(e) === fn) handlers.delete(e); }
  };
  vm.runInNewContext(script, { window, document: { createElement: tag => new FakeNode(tag) }, URL, Number, Array, Object, Error, String });
  return { window, FakeNode, handlers };
}

test('bridge rejects mismatched variant, seat sum and unsupported version', () => {
  const { window } = browser();
  const valid = window.AircraftDesignerFlightCost.isValidDesign;
  assert.equal(valid(data, 'B752', ['RB211-535E4']), true);
  assert.equal(valid(data, 'B752', 'PW2037'), false);
  assert.equal(valid({ ...data, version: 2 }, 'B752', 'RB211-535E4'), false);
  assert.equal(valid({ ...data, aircraft: { ...data.aircraft, seats: 239 } }, 'B752', 'RB211-535E4'), false);
  assert.equal(valid({ ...data, weights: { ...data.weights, mlw_kg: 110000 } }, 'B752', 'RB211-535E4'), false);
});

test('only exact iframe origin/source saves, request ID reaches server, ACK after commit', async () => {
  const { window, FakeNode, handlers } = browser();
  const container = new FakeNode('div');
  let resolveWrite; let writes = 0; let receivedId;
  const pendingWrite = new Promise(resolve => { resolveWrite = resolve; });
  window.AircraftDesignerFlightCost.mount({ container, icao: 'B752', engine: 'RB211-535E4',
    aircraftId: 'b757-200-rb', layoutId: 'b752-225',
    saveDesign: async (design, requestId) => {
      writes++; receivedId = requestId; assert.equal(design.aircraft.seats, 225);
      return await pendingWrite;
    }});
  const [button, status, dialog] = container.children;
  button.click();
  assert.equal(dialog.open, true);
  const frame = dialog.children[1];
  const event = { origin: 'https://aircraft-designer.app', source: frame.contentWindow,
    data: { protocol: data.protocol, version: 1, type: 'DESIGN_EXPORT', requestId: '12345678-abcd', design: data } };
  await handlers.get('message')({ ...event, origin: 'https://evil.example' });
  await handlers.get('message')({ ...event, source: {} });
  assert.equal(writes, 0);
  const saving = handlers.get('message')(event);
  assert.equal(writes, 1);
  assert.equal(receivedId, '12345678-abcd');
  assert.equal(frame.contentWindow.messages.length, 0);
  resolveWrite({ id: 'USER:B752-3D-123' });
  await saving;
  assert.equal(frame.contentWindow.messages.length, 1);
  assert.equal(frame.contentWindow.messages[0].m.saved, true);
  assert.equal(frame.contentWindow.messages[0].m.requestId, '12345678-abcd');
  assert.equal(status.textContent, 'Самолёт сохранён в FlightCost');
});

test('failed save or missing workspace never sends success', async () => {
  const { window, FakeNode, handlers } = browser();
  const container = new FakeNode('div');
  window.AircraftDesignerFlightCost.mount({ container, icao: 'B752', engine: 'RB211-535E4',
    saveDesign: async () => { throw new Error('workspace missing'); } });
  const frame = container.children[2].children[1];
  await handlers.get('message')({ origin: 'https://aircraft-designer.app', source: frame.contentWindow,
    data: { protocol: data.protocol, version: 1, type: 'DESIGN_EXPORT', requestId: 'abcdefgh-1234', design: data } });
  assert.equal(frame.contentWindow.messages.at(-1).m.saved, false);
});
