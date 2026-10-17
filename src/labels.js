// Map labels as an HTML overlay: neighborhoods, water, streets (set along the street), places, and homes.
// The Nine's homes carry their name in their own color on a dark plate with a leader to the roof. No X marks.
import * as THREE from 'three';
import { CAT_COLORS, NINE_ORDER, esc, polyLen } from './core.js';

const V = new THREE.Vector3();

export class Labels {
  constructor(app) {
    this.app = app; this.D = app.D;
    this.root = document.getElementById('labels');
    this.items = [];
    this.show = { hoods: true, water: true, streets: true, places: true, homes: true };
    this.onClick = null;
    this.build();
  }
  add(o) {
    const el = document.createElement('div'); el.className = 'lb ' + o.cls; el.innerHTML = o.html; el.style.display = 'none'; if (o.style) el.style.cssText += o.style;
    if (o.click) { el.classList.add('hit'); el.addEventListener('click', e => { e.stopPropagation(); this.onClick && this.onClick(o.click); }); }
    if (o.color) el.style.setProperty('--c', o.color);
    this.root.appendChild(el);
    const it = { ...o, el, w: 0, h: 0, on: false };
    this.items.push(it); return it;
  }
  build() {
    const D = this.D;
    // neighborhoods and the town name
    for (const l of D.labels) {
      if (l.kind === 'district') this.add({ type: 'hoods', cls: 'hood', html: esc(l.text), at: l.at, y: 0, pri: 60 - (l.rank || 1) * 5, minD: 300, maxD: 16000 });
      else if (l.kind === 'water') { const a = -(l.rot || 0) * Math.PI / 180; this.add({ type: 'water', cls: 'water', html: esc(l.text), at: l.at, y: 0, pri: 40, minD: 200, maxD: 30000, dir: l.rot ? [Math.cos(a) * 100, Math.sin(a) * 100] : null, style: `font-size:${(l.size || 13) + 1}px;letter-spacing:${(l.ls || 0.1)}em` }); }
      else if (l.kind === 'place' && l.rank === 0) this.add({ type: 'hoods', cls: 'town', html: esc(l.text), at: l.at, y: 0, pri: 70, minD: 5000, maxD: 60000 });
      else if (l.kind === 'place') this.add({ type: 'hoods', cls: 'edge', html: esc(l.text), at: l.at, y: 0, pri: 30, minD: 3000, maxD: 40000 });
    }
    // streets: one label per ~450 m of each named street, on the longest straight pieces
    for (const r of D.roads) {
      if (!r.name || r.cls === 'track' || r.cls === 'path' || r.cls === 'service') continue;
      const p = r.pts, L = polyLen(p); if (L < 70) continue;
      const n = Math.max(1, Math.round(L / 450));
      for (let k = 0; k < n; k++) {
        const s = L * (k + 0.5) / n; let acc = 0;
        for (let i = 2; i < p.length; i += 2) {
          const sl = Math.hypot(p[i] - p[i - 2], p[i + 1] - p[i - 1]);
          if (acc + sl >= s) { const t = (s - acc) / sl; const x = p[i - 2] + (p[i] - p[i - 2]) * t, y = p[i - 1] + (p[i + 1] - p[i - 1]) * t;
            const major = ['trunk', 'primary', 'secondary'].includes(r.cls);
            this.add({ type: 'streets', cls: 'street' + (major ? ' major' : ''), html: esc(r.name), at: [x, y], y: r.bridge ? 8 : 0.5, pri: major ? 22 : 12, minD: 0, maxD: major ? 3200 : 1500, dir: [p[i] - p[i - 2], p[i + 1] - p[i - 1]] });
            break; }
          acc += sl;
        }
      }
    }
    // places (homes listed under people instead)
    const H = new Map(); // address -> people
    for (const h of D.people) { if (!h.home || !h.home.at) continue; const k = h.home.addr || h.home.at.join(','); let e = H.get(k); if (!e) H.set(k, e = { at: h.home.at, addr: h.home.addr, note: h.home.note, people: [] }); e.people.push(h); }
    for (const p of D.places) {
      if (!p.at || p.cat === 'homepoi') continue;
      const color = CAT_COLORS[p.cat] || '#6f675c';
      const b = this.nearBuilding(p.at);
      this.add({ type: 'places', cls: 'place', html: `<i style="background:${color}"></i><span>${esc(p.name)}</span>`, at: p.at, y: b ? b.h + 1.5 : 2, pri: p.status === 'locked' ? 36 : p.cat === 'landmark' || p.cat === 'canon' ? 30 : 20, minD: 0, maxD: p.cat === 'landmark' || p.status === 'locked' ? 5200 : 2600, click: { kind: 'place', id: p.id } });
    }
    for (const [, e] of H) {
      const nine = e.people.filter(h => h.group === 'The Nine').sort((a, b) => NINE_ORDER.indexOf(a.name) - NINE_ORDER.indexOf(b.name));
      const b = this.nearBuilding(e.at); const top = (b ? b.h : 6) + 2;
      if (nine.length) {
        for (const [k, h] of nine.entries()) {
          this.add({ type: 'homes', cls: 'nine', color: h.color, html: `<b>${esc(h.name)}</b><em></em>`, at: e.at, y: top, pri: 90, minD: 0, maxD: 14000, stack: k, click: { kind: 'person', name: h.name } });
        }
      } else {
        const names = e.people.map(h => h.name);
        this.add({ type: 'homes', cls: 'home', html: `<span>${esc(names.length > 2 ? names[0] + ' and ' + (names.length - 1) + ' others' : names.join(' and '))}</span>`, at: e.at, y: top, pri: 26, minD: 0, maxD: 1500, click: { kind: 'person', name: names[0] } });
      }
    }
  }
  nearBuilding(at) {
    let best = null; this.D.bGrid.query(at[0] - 25, at[1] - 25, at[0] + 25, at[1] + 25, k => { const b = this.D.buildings[k]; const d = Math.hypot(b.cx - at[0], b.cy - at[1]); if (d < 25 && (!best || d < best.d)) best = { d, b }; });
    return best && best.b;
  }
  update() {
    const cam = this.app.camera, W = this.root.clientWidth, Hh = this.root.clientHeight;
    const cd = cam.position.distanceTo(this.app.controls.target);
    const placed = [];
    const cand = [];
    for (const it of this.items) {
      if (!this.show[it.type]) { if (it.on) { it.el.style.display = 'none'; it.on = false; } continue; }
      if (cd < it.minD || cd > it.maxD) { if (it.on) { it.el.style.display = 'none'; it.on = false; } continue; }
      V.set(it.at[0], it.y, -it.at[1]);
      const dist = V.distanceTo(cam.position);
      V.project(cam);
      if (V.z > 1 || V.x < -1.1 || V.x > 1.1 || V.y < -1.1 || V.y > 1.1) { if (it.on) { it.el.style.display = 'none'; it.on = false; } continue; }
      it.sx = (V.x * 0.5 + 0.5) * W; it.sy = (-V.y * 0.5 + 0.5) * Hh; it.dist = dist;
      cand.push(it);
    }
    cand.sort((a, b) => b.pri - a.pri || a.dist - b.dist);
    for (const it of cand) {
      if (!it.on) { it.el.style.display = ''; it.on = true; it.w = 0; }
      if (!it.w) { it.w = it.el.offsetWidth; it.h = it.el.offsetHeight; }
      let ang = 0;
      if (it.dir) { // keep street names along the street, upright
        V.set(it.at[0] + it.dir[0], it.y, -(it.at[1] + it.dir[1])).project(cam);
        const ex = (V.x * 0.5 + 0.5) * W, ey = (-V.y * 0.5 + 0.5) * Hh; ang = Math.atan2(ey - it.sy, ex - it.sx);
        if (ang > Math.PI / 2) ang -= Math.PI; if (ang < -Math.PI / 2) ang += Math.PI;
      }
      const stackY = it.cls === 'nine' ? (it.stack || 0) * (it.h + 3) : 0;
      const w = it.dir ? Math.abs(Math.cos(ang)) * it.w + Math.abs(Math.sin(ang)) * it.h : it.w, h = it.dir ? Math.abs(Math.sin(ang)) * it.w + Math.abs(Math.cos(ang)) * it.h : it.h;
      const cy = it.cls === 'nine' ? it.sy - 30 - stackY - it.h / 2 : it.cls === 'place' || it.cls === 'home' ? it.sy - it.h / 2 - 2 : it.sy;
      const r = [it.sx - w / 2 - 3, cy - h / 2 - 2, it.sx + w / 2 + 3, cy + h / 2 + 2];
      const hit = placed.some(q => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1]);
      if (hit && it.cls !== 'nine') { it.el.style.display = 'none'; it.on = false; continue; }
      placed.push(r);
      const fade = it.type === 'hoods' ? Math.min(1, Math.max(0, (cd - it.minD) / 250)) : 1;
      it.el.style.opacity = fade;
      if (it.cls === 'nine') it.el.style.setProperty('--lead', (30 + stackY) + 'px');
      it.el.style.transform = `translate(${it.sx.toFixed(1)}px, ${(it.cls === 'nine' ? it.sy : it.cls === 'place' || it.cls === 'home' ? it.sy : it.sy).toFixed(1)}px) translate(-50%, ${it.cls === 'nine' ? `calc(-100% - ${30 + stackY}px)` : it.cls === 'place' || it.cls === 'home' ? '-100%' : '-50%'}) rotate(${(ang * 180 / Math.PI).toFixed(2)}deg)`;
    }
  }
}
