'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { resolve } = require('node:path');

const script = readFileSync(resolve(__dirname, '../flightcostapp/web/flightcost-embed.nomodule.js'), 'utf8');
const bootScript = readFileSync(resolve(__dirname, '../flightcostapp/web/flightcost-aircraft-designer.js'), 'utf8');
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
    replaceChildren(...x) { this.children = x; }
    setAttribute(a, b) { this.attributes[a] = b; }
    addEventListener(e, fn) { this.listeners[e] = fn; }
    remove() { this.removed = true; }
    click() { return this.listeners.click(); }
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
  const [frame, status] = container.children;
  assert.equal(frame.title, 'B752: Aircraft Designer');
  assert.match(frame.src, /https:\/\/aircraft-designer\.app\/\?embed=flightcost/);
  assert.match(frame.src, /layout=b752-225/);
  assert.equal(container.children.some(c => c.open || c.tag === 'dialog'), false);
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
  const frame = container.children[0];
  await handlers.get('message')({ origin: 'https://aircraft-designer.app', source: frame.contentWindow,
    data: { protocol: data.protocol, version: 1, type: 'DESIGN_EXPORT', requestId: 'abcdefgh-1234', design: data } });
  assert.equal(frame.contentWindow.messages.at(-1).m.saved, false);
});


test('dedicated viewer accepts an external status element and leaves the page to the host', () => {
  const { window, FakeNode, handlers } = browser();
  const container = new FakeNode('main');
  const status = new FakeNode('p');
  const inst = window.AircraftDesignerFlightCost.mount({
    container, status, icao: 'A20N', engine: 'LEAP-1A', layoutId: 'a320-194'
  });
  assert.equal(container.children.length, 1);
  assert.equal(container.children[0].title, 'A20N: Aircraft Designer');
  assert.match(inst.url, /engine=LEAP-1A/);
  assert.match(inst.url, /layout=a320-194/);
  assert.equal(handlers.has('message'), true);
  inst.destroy();
  assert.equal(container.children[0].removed, true);
  assert.equal(status.removed, undefined);
  assert.equal(handlers.has('message'), false);
});


test('separate page creates a guest workspace, saves the selected design, and keeps the return links', async () => {
  const { window, FakeNode, handlers } = browser();
  window.location = { origin: 'https://flightcost.app' };
  const byId = Object.fromEntries([
    'fc3d-data', 'fc3d-message', 'fc3d-engine-note', 'fc3d-links',
    'fc3d-workspace', 'fc3d-create', 'fc3d-mount'
  ].map(id => [id, new FakeNode('div')]));
  const cfg = {
    icao: 'B752', lang: 'ru', selected: 0,
    refEngine: 'RB211-535E4', backHref: '/ru/type/B752',
    route: ['EDDF', 'LEBL'],
    choices: [{ engine: 'RB211-535E4', aircraftId: 'b757-200-rb',
      weightProfile: 'standard', layoutId: 'b752-225' }],
    text: { different: 'engine {designer} {flightcost}', error: 'Error: ', created: 'Created',
      need: 'Create workspace', saving: 'Saving', saved: 'Saved', back: 'Back',
      workspace: 'Workspace', calc: 'Calculate', caveat: 'No fuel', open: 'Open' }
  };
  byId['fc3d-data'].textContent = JSON.stringify(cfg);
  let exists = false;
  let writeCount = 0;
  async function fetch(path, args) {
    if (path === '/api/ws') return { ok: true, json: async () => ({ exists }) };
    if (path === '/api/ws/new') {
      exists = true;
      return { ok: true, json: async () => ({ key: 'private-workspace-key' }) };
    }
    if (path === '/api/aircraft/designer-save') {
      assert.equal(args.method, 'POST');
      assert.equal(JSON.parse(args.body).design.aircraft.layoutId, 'b752-225');
      writeCount++;
      return { ok: true, json: async () => ({ id: 'USER:B752-3D-123',
        icao: 'USER:B752-3D-123', seats: 225, burn_inherited: true }) };
    }
    throw new Error('unexpected request ' + path);
  }
  vm.runInNewContext(bootScript, {
    window, document: { readyState: 'complete',
      getElementById: id => byId[id], createElement: tag => new FakeNode(tag) },
    fetch, URL, JSON, Number, Array, Object, Error, String
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(byId['fc3d-create'].hidden, false);
  assert.equal(byId['fc3d-mount'].children.length, 1);
  const frame = byId['fc3d-mount'].children[0];
  assert.match(frame.src, /layout=b752-225/);
  await byId['fc3d-create'].click();
  assert.equal(byId['fc3d-workspace'].children.length, 1);
  assert.equal(byId['fc3d-workspace'].children[0].href, '/w#private-workspace-key');
  await handlers.get('message')({ origin: 'https://aircraft-designer.app', source: frame.contentWindow,
    data: { protocol: data.protocol, version: 1, type: 'DESIGN_EXPORT',
      requestId: 'abcdefgh-1234', design: data } });
  assert.equal(writeCount, 1);
  assert.equal(frame.contentWindow.messages.at(-1).m.saved, true);
  assert.equal(byId['fc3d-links'].children[0].href, '/ru/type/B752');
  assert.match(byId['fc3d-links'].children[2].href, /ac=USER%3AB752-3D-123/);
  assert.equal(byId['fc3d-workspace'].children.length, 1, 'secret workspace link must persist');
});
