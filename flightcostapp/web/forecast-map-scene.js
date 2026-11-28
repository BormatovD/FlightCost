/* A local neighbourhood of the forecast graph, projected with a perspective camera. */
(() => {
  'use strict';
  const TAU = Math.PI * 2;
  const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
  const glyphs = {
    macroReference: 'M-10 8V-6 M-10 8H10 M-7 4L-2 0L2 2L9 -7',
    macroDemand: 'M-9 8V3H-6V8Z M-2 8V-2H1V8Z M5 8V-8H8V8Z',
    population: 'M-2 -3a3 3 0 1 1 0 -6a3 3 0 1 1 0 6 M-9 7C-9 0 3 0 3 7 M6 -8a3 3 0 0 1 0 6 M6 1Q11 2 11 7',
    geography: 'M0 -7L-8 7 M0 -7L8 7 M-8 7H8 M0 -10a3 3 0 1 0 .1 0 M-8 5a2 2 0 1 0 .1 0 M8 5a2 2 0 1 0 .1 0',
    macroEvents: 'M-11 1H-6L-2 -7L2 8L6 -2L8 1H11',
    macroInvestment: 'M-9 8H9 M-6 4V0 M0 4V-4 M6 4V-8 M2 -6L6 -10L10 -6',
    historyWorld: 'M0 -9a9 9 0 1 0 .1 0 M0 -5V0L5 3',
    source: 'M-6 -9H3L7 -5V9H-6Z M3 -9V-5H7 M-3 0H4 M-3 4H4',
    assumption: 'M0 -9L10 8H-10Z M0 -3V2 M0 5V6',
    group: 'M-6 -7H6 M0 -7V0 M-8 6V0H8V6 M0 0V6',
    input: 'M-9 -5H9 M-9 5H9 M-4 -8V-2 M4 2V8',
    region: 'M0 9S-7 1 -7 -3a7 7 0 1 1 14 0C7 1 0 9 0 9Z M0 -5a2 2 0 1 0 .1 0',
    default: 'M-7 0H7 M0 -7V7',
  };
  const icons = Object.fromEntries(Object.entries(glyphs).map(([id, path]) => [id, new Path2D(path)]));
  const colorVars = { result: '--calc', model: '--calc', region: '--calc', input: '--user', user: '--user',
    group: '--doc', source: '--doc', context: '--doc', assumption: '--guess' };
  const variable = kind => colorVars[kind] || '--doc';

  class ForecastScene {
    constructor(stage, select, formatValue) {
      this.stage = stage;
      this.canvas = stage.querySelector('canvas');
      this.layer = stage.querySelector('#fm-nodes');
      this.ctx = this.canvas.getContext('2d');
      this.select = select;
      this.formatValue = formatValue;
      this.motion = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.placed = new Map();
      this.entries = [];
      this.edges = [];
      this.colors = {};
      this.yaw = .17;
      this.pitch = -.1;
      this.zoom = 1;
      new ResizeObserver(() => this.resize()).observe(stage);
      this.bind();
    }

    resize() {
      if (!this.colors['--bg']) {
        const style = getComputedStyle(this.stage);
        this.colors = Object.fromEntries(['--bg', '--panel', '--land', '--dim', '--doc', '--calc', '--guess', '--user']
          .map(key => [key, style.getPropertyValue(key).trim()]));
      }
      this.width = this.stage.clientWidth;
      this.height = this.stage.clientHeight;
      if (!this.width || !this.height) return;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = Math.round(this.width * ratio);
      this.canvas.height = Math.round(this.height * ratio);
      this.ctx?.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.narrow = this.width < 525;
      this.stage.style.setProperty('--label-width', this.narrow ? '92px' : '148px');
      this.stage.style.setProperty('--focus-width', this.narrow ? '130px' : '186px');
      this.draw();
    }

    show(nodes, selected, neighbours, via, animate) {
      this.nodes = nodes;
      this.selected = selected;
      const origin = this.placed.get(selected);
      this.from = new Map(this.placed);
      this.start = origin && animate && !this.motion.matches ? performance.now() : null;
      this.origin = origin;
      this.entries = [{id: selected, point: [0, 0, 0], focus: true}];
      const seen = new Set([selected, ...neighbours.map(item => item.id)]);
      const count = neighbours.length;
      for (const [i, item] of neighbours.entries()) {
        const a = (count === 1 ? -.78 : -1.97 + i * TAU / count);
        const x = Math.cos(a), y = Math.sin(a);
        const z = .31 * Math.sin(2 * a + .6);
        this.entries.push({id: item.id, point: [x * .91, y * .92, z], via: selected,
          relation: item.output ? 'Используется в этом блоке' : item.label});
        if (this.stage.clientWidth < 525) continue;
        // Show one real dependency behind a neighbour. Its card can be opened directly.
        const deeper = nodes[item.id].inputs?.find(edge => nodes[edge.id] && !seen.has(edge.id));
        if (deeper && count <= 9 && item.id !== via) {
          seen.add(deeper.id);
          const angle = a + .24;
          this.entries.push({id: deeper.id, distant: true, via: item.id,
            point: [Math.cos(angle) * 1.12, Math.sin(angle) * 1.15, z - .65]});
        }
      }
      this.edges = [];
      const visible = new Set(this.entries.map(n => n.id));
      for (const to of visible) {
        for (const edge of nodes[to].inputs || []) {
          if (visible.has(edge.id) && edge.id !== to) this.edges.push({from: edge.id, to, role: edge.role || 'input'});
        }
      }
      this.layer.replaceChildren();
      for (const item of this.entries) {
        const node = nodes[item.id];
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'fm-node' + (item.focus ? ' is-current' : item.distant ? ' is-distant' : '');
        btn.dataset.node = item.id;
        btn.setAttribute('aria-label', node.label);
        if (item.relation) { btn.title = item.relation; btn.setAttribute('aria-description', item.relation); }
        if (item.focus) btn.setAttribute('aria-current', 'true');
        const label = document.createElement('span');
        label.className = 'fm-label';
        label.textContent = node.label;
        btn.append(label);
        if (item.focus && node.display) {
          const value = document.createElement('span');
          value.className = 'fm-node-value';
          value.append(this.formatValue(node.display));
          btn.setAttribute('aria-description', [
            item.relation, [node.display.number, node.display.unit].filter(Boolean).join(' ')
          ].filter(Boolean).join('. '));
          btn.append(value);
        }
        btn.onclick = () => this.select(item.id, item.via);
        btn.onpointerenter = () => { this.hover = item.id; this.draw(); };
        btn.onpointerleave = () => { this.hover = null; this.draw(); };
        this.layer.append(btn);
        item.button = btn;
      }
      this.hover = null;
      this.resize();
    }

    project([x, y, z]) {
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
      const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
      const ahead = -x * sy + z * cy;
      const depth = y * sp + ahead * cp;
      const perspective = 4.6 / (4.6 - depth);
      const rx = this.width / 2 - (this.narrow ? 47 : 76);
      const ry = this.height / 2 - (this.narrow ? 55 : 49);
      return {x: this.width / 2 + (x * cy + z * sy) * perspective * rx * this.zoom,
        y: this.height * .465 + (y * cp - ahead * sp) * perspective * ry * this.zoom, z: depth, perspective};
    }

    draw() {
      if (!this.width || !this.height || !this.entries.length) return;
      const ctx = this.colors['--land'] && this.colors['--bg'] ? this.ctx : null;
      if (ctx) {
        ctx.clearRect(0, 0, this.width, this.height);
        this.floor();
      }
      const t = this.start === null ? 1 : Math.min(1, (performance.now() - this.start) / 300);
      const ease = 1 - (1 - t) ** 3;
      const points = new Map();
      for (const item of this.entries) {
        const p = this.project(item.point);
        const before = this.from.get(item.id) || this.origin;
        if (ease < 1 && before) {
          p.x = before.x + (p.x - before.x) * ease;
          p.y = before.y + (p.y - before.y) * ease;
        }
        p.r = item.focus ? (this.narrow ? 25 : 35) : item.distant ? 4.3 : (this.narrow ? 13 : 17);
        p.r *= clamp(p.perspective * this.zoom, .75, 1.23);
        points.set(item.id, p);
      }
      if (ctx) {
        for (const edge of this.edges) this.line(edge, points);
        for (const item of [...this.entries].sort((a, b) => points.get(a.id).z - points.get(b.id).z)) {
          this.sphere(item, points.get(item.id));
        }
      }
      this.labels(points);
      this.placed = points;
      if (t < 1 && !this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this.draw(); });
    }

    floor() {
      const ctx = this.ctx;
      ctx.save();
      ctx.strokeStyle = this.colors['--dim'];
      ctx.lineWidth = .65;
      ctx.globalAlpha = .125;
      ctx.beginPath();
      for (let i = -5; i <= 5; i++) {
        const v = i * .29;
        for (const [a, b] of [[[v, .67, -1.45], [v, .67, 1.45]], [[-1.45, .67, v], [1.45, .67, v]]]) {
          const start = this.project(a), end = this.project(b);
          ctx.moveTo(start.x, start.y);
          ctx.lineTo(end.x, end.y);
        }
      }
      ctx.stroke();
      ctx.restore();
    }

    line(edge, points) {
      const ctx = this.ctx;
      const a = points.get(edge.from), b = points.get(edge.to);
      const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy);
      if (dist <= a.r + b.r + 4) return;
      const ux = dx / dist, uy = dy / dist;
      const focus = edge.from === this.selected || edge.to === this.selected;
      const endX = b.x - ux * (b.r + 4), endY = b.y - uy * (b.r + 4);
      const role = edge.role;
      const color = this.colors[role === 'context' ? '--dim' : role === 'breakdown' ? '--doc' : '--calc'];
      ctx.save();
      ctx.strokeStyle = ctx.fillStyle = color;
      ctx.globalAlpha = focus ? .85 : .20;
      if (focus && (edge.from === this.hover || edge.to === this.hover)) ctx.lineWidth = 2.2;
      else ctx.lineWidth = focus ? 1.45 : 1;
      ctx.setLineDash(role === 'context' ? [1.8, 4.6] : role === 'breakdown' ? [7, 4] : []);
      ctx.beginPath(); ctx.moveTo(a.x + ux * (a.r + 2), a.y + uy * (a.r + 2));
      ctx.lineTo(endX, endY); ctx.stroke();
      if (focus && role === 'input') {
        ctx.beginPath(); ctx.moveTo(endX, endY);
        ctx.lineTo(endX - ux * 7 - uy * 3, endY - uy * 7 + ux * 3);
        ctx.lineTo(endX - ux * 7 + uy * 3, endY - uy * 7 - ux * 3); ctx.fill();
      }
      ctx.restore();
    }

    sphere(item, p) {
      const ctx = this.ctx;
      const node = this.nodes[item.id];
      const color = this.colors[variable(node.kind)];
      const r = p.r;
      ctx.save(); ctx.translate(p.x, p.y);
      if (item.distant) {
        ctx.fillStyle = this.colors['--panel']; ctx.strokeStyle = color; ctx.globalAlpha = .52;
        ctx.beginPath(); ctx.arc(0, 0, r, 0, TAU); ctx.fill(); ctx.stroke(); ctx.restore(); return;
      }
      if (item.focus || this.hover === item.id) {
        ctx.strokeStyle = color; ctx.globalAlpha = .28; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(0, 0, r + (item.focus ? 7 : 4), 0, TAU); ctx.stroke();
        ctx.globalAlpha = 1;
      }
      const surface = ctx.createRadialGradient(-r * .34, -r * .40, 0, 0, 0, r);
      surface.addColorStop(0, this.colors['--land']); surface.addColorStop(1, this.colors['--bg']);
      ctx.fillStyle = surface; ctx.strokeStyle = color; ctx.lineWidth = item.focus ? 1.8 : 1.1;
      ctx.beginPath(); ctx.arc(0, 0, r, 0, TAU); ctx.fill(); ctx.stroke();
      ctx.fillStyle = color; ctx.globalAlpha = item.focus ? .15 : .1; ctx.fill(); ctx.globalAlpha = 1;
      ctx.strokeStyle = color;
      if (item.id === 'world') this.globe(r);
      else {
        ctx.scale(r / 16, r / 16); ctx.lineWidth = 1.4; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
        ctx.stroke(icons[item.id] || icons[node.kind] || icons.default);
      }
      ctx.restore();
    }

    globe(r) {
      const ctx = this.ctx;
      ctx.rotate(-.27 + this.pitch * .20);
      ctx.lineWidth = 1; ctx.globalAlpha = .76;
      // Orthographic graticule. Only the hemisphere facing the viewer is visible.
      for (let i = 0; i < 7; i++) {
        const longitude = i * Math.PI / 7 + this.yaw;
        const k = Math.sin(longitude) * (Math.cos(longitude) < 0 ? -1 : 1);
        ctx.beginPath();
        for (let j = 0; j <= 32; j++) {
          const lat = -Math.PI / 2 + Math.PI * j / 32;
          const x = Math.cos(lat) * k * r, y = Math.sin(lat) * r;
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      for (const y of [-.65, -.33, 0, .33, .65]) {
        const w = Math.sqrt(1 - y * y) * r;
        ctx.beginPath(); ctx.moveTo(-w, r * y); ctx.quadraticCurveTo(0, r * (y + .24), w, r * y); ctx.stroke();
      }
    }

    labels(points) {
      const labels = this.entries.map(item => {
        const p = points.get(item.id), b = item.button;
        const w = b.offsetWidth, h = b.offsetHeight;
        return {item, p, w, h, x: clamp(p.x, w / 2 + 3, this.width - w / 2 - 3),
          y: item.distant ? p.y : p.y + p.r + (item.focus ? 10 : 5)};
      });
      const occupied = [];
      for (const label of labels.filter(label => !label.item.distant)) {
        const {w, h} = label;
        const maxY = this.height - h - 4;
        label.y = clamp(label.y, 3, maxY);
        // Try the closest unoccupied label position, retaining the projected anchor.
        const top = label.y;
        for (const offset of [0, 16, -16, 32, -32, 48, -48, 64, -64, 80]) {
          label.y = clamp(top + offset, 3, maxY);
          if (!occupied.some(other => Math.abs(other.x - label.x) < (other.w + w) / 2 + 3 &&
              label.y < other.y + other.h + 3 && other.y < label.y + h + 3)) break;
        }
        occupied.push(label);
      }
      for (const {item, p, x, y} of labels) {
        const b = item.button;
        b.style.left = x.toFixed(1) + 'px'; b.style.top = y.toFixed(1) + 'px';
        b.style.zIndex = item.focus ? 20 : item.distant ? 1 : String(10 + Math.round(p.z));
      }
    }

    reset() { this.yaw = .17; this.pitch = -.1; this.zoom = 1; this.viewChanged(); }
    viewChanged() {
      this.start = null;
      document.getElementById('fm-in').disabled = this.zoom >= 1.45;
      document.getElementById('fm-out').disabled = this.zoom <= .70;
      this.draw();
    }
    scale(step) { this.zoom = clamp(Number((this.zoom + step).toFixed(2)), .70, 1.45); this.viewChanged(); }
    bind() {
      const stage = this.stage;
      document.getElementById('fm-in').onclick = () => this.scale(.15);
      document.getElementById('fm-out').onclick = () => this.scale(-.15);
      document.getElementById('fm-reset').onclick = () => this.reset();
      let pointer = null;
      stage.addEventListener('pointerdown', e => {
        if (e.target.closest('button') || e.button !== 0 || !e.isPrimary) return;
        pointer = {id: e.pointerId, x: e.clientX, y: e.clientY, yaw: this.yaw, pitch: this.pitch, moved: false};
        stage.setPointerCapture(e.pointerId);
      });
      stage.addEventListener('pointermove', e => {
        if (!pointer || e.pointerId !== pointer.id) return;
        const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
        if (Math.hypot(dx, dy) < 4 && !pointer.moved) return;
        pointer.moved = true;
        stage.classList.add('fm-dragging');
        this.yaw = pointer.yaw + dx / 190;
        this.pitch = clamp(pointer.pitch - dy / 230, -.94, .94);
        this.viewChanged();
      });
      const end = e => {
        if (!pointer || pointer.id !== e.pointerId) return;
        const tap = !pointer.moved && e.type === 'pointerup';
        pointer = null; stage.classList.remove('fm-dragging');
        if (stage.hasPointerCapture(e.pointerId)) stage.releasePointerCapture(e.pointerId);
        if (tap) {
          const rect = stage.getBoundingClientRect();
          const hit = [...this.entries].sort((a, b) => this.placed.get(b.id).z - this.placed.get(a.id).z).find(item => {
            const p = this.placed.get(item.id);
            return p && Math.hypot(e.clientX - rect.left - p.x, e.clientY - rect.top - p.y) <= p.r + 5;
          });
          if (hit) this.select(hit.id, hit.via);
        }
      };
      stage.addEventListener('pointerup', end); stage.addEventListener('pointercancel', end);
      stage.addEventListener('keydown', e => {
        if (e.target !== stage) return;
        const shifts = {ArrowLeft:[-.17, 0], ArrowRight:[.17, 0], ArrowUp:[0, .13], ArrowDown:[0, -.13]};
        if (shifts[e.key]) {
          e.preventDefault(); this.yaw += shifts[e.key][0]; this.pitch = clamp(this.pitch + shifts[e.key][1], -.94, .94);
          this.viewChanged();
        } else if (['+', '=', '-'].includes(e.key)) { e.preventDefault(); this.scale(e.key === '-' ? -.15 : .15); }
        else if (e.key === 'Home') { e.preventDefault(); this.reset(); }
      });
    }
  }
  window.ForecastMapScene = {ForecastScene, color: variable};
})();
