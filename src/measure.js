// Distance tracker: click points on the map to measure in a straight line or by road.
// By road uses src/roadgraph.js (the same router that built data/distances.json).
import * as THREE from 'three';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { fmtDist, fmtTime, esc } from './core.js';
import { roadHeightAt } from './roads.js';

const WALK = 1.34; // m/s

export class Measure {
  constructor(app) {
    this.app = app; this.D = app.D; this.points = []; this.legs = []; this.mode = 'road'; this.active = false;
    this.group = new THREE.Group(); this.group.name = 'measure'; this.group.renderOrder = 1000; app.scene.add(this.group);
    this.mat = new LineMaterial({ color: 0xe8c14a, linewidth: 4, worldUnits: false, depthTest: false, transparent: true, opacity: 0.95 });
    this.matCase = new LineMaterial({ color: 0x15151a, linewidth: 7, worldUnits: false, depthTest: false, transparent: true, opacity: 0.7 });
    this.dotGeo = new THREE.CylinderGeometry(1, 1, 0.6, 20); this.dotMat = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false });
    this.graph = null;
    this.ready = import('./roadgraph.js').then(m => { this.RG = m; const fx = (app.D.qa && app.D.qa.fixes) || {}; this.graph = m.buildGraph(app.D.wp, { roadSnaps: fx.road_snaps || [], extraRoads: (fx.add_roads || []).map(r => [r.name, r.cls, r.bridge || 0, r.pts]) }); return true; }).catch(e => { console.warn('road router unavailable', e); return false; });
    this.tags = document.getElementById('mtags');
  }
  setMode(m) { this.mode = m; this.recompute(); }
  start() { this.active = true; document.body.classList.add('measuring'); }
  stop() { this.active = false; document.body.classList.remove('measuring'); }
  clear() { this.points = []; this.legs = []; this.redraw(); this.render(); }
  undo() { this.points.pop(); this.recompute(); }
  add(at) { this.points.push(at); this.recompute(); }

  async recompute() {
    const P = this.points; this.legs = [];
    if (this.mode === 'road') await this.ready;
    for (let i = 1; i < P.length; i++) {
      const a = P[i - 1], b = P[i], straight = Math.hypot(b[0] - a[0], b[1] - a[1]);
      let leg = { a, b, straight, meters: straight, seconds: null, path: [a, b], roads: [] };
      if (this.mode === 'road' && this.graph) {
        const r = this.RG.route(this.graph, a, b, { metric: 'time' });
        if (r) leg = { ...leg, meters: r.meters, seconds: r.seconds, path: r.path, roads: r.roads || [], gap: this.gapMeters(r.path) };
        else leg.noRoute = true;
      }
      this.legs.push(leg);
    }
    this.redraw(); this.render();
  }

  /** Meters of a route that run along a link the Atlas does not draw (see the map check). */
  gapMeters(path) {
    const links = (this.graph && this.graph.gapLinks) || []; if (!links.length) return 0;
    let m = 0;
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1], b = path[i];
      for (const L of links) {
        const f = L.from, t = L.to;
        if ((Math.hypot(a[0] - f[0], a[1] - f[1]) < 1.5 && Math.hypot(b[0] - t[0], b[1] - t[1]) < 1.5) || (Math.hypot(a[0] - t[0], a[1] - t[1]) < 1.5 && Math.hypot(b[0] - f[0], b[1] - f[1]) < 1.5)) { m += Math.hypot(b[0] - a[0], b[1] - a[1]); break; }
      }
    }
    return m;
  }

  redraw() {
    for (const c of [...this.group.children]) { this.group.remove(c); if (c.geometry && c.geometry !== this.dotGeo) c.geometry.dispose(); }
    const res = new THREE.Vector2(this.app.el.clientWidth, this.app.el.clientHeight);
    this.mat.resolution.copy(res); this.matCase.resolution.copy(res);
    const cd = this.app.camera.position.distanceTo(this.app.controls.target);
    const pts = [];
    for (const leg of this.legs) for (const [x, y] of leg.path) pts.push(x, roadHeightAt(this.D, x, y) + 1.2, -y);
    if (pts.length >= 6) {
      for (const m of [this.matCase, this.mat]) { const g = new LineGeometry(); g.setPositions(pts); const l = new Line2(g, m); l.computeLineDistances(); l.renderOrder = m === this.mat ? 1001 : 1000; l.frustumCulled = false; this.group.add(l); }
    }
    const s = Math.max(1.2, cd / 160);
    for (const [x, y] of this.points) { const d = new THREE.Mesh(this.dotGeo, this.dotMat); d.position.set(x, roadHeightAt(this.D, x, y) + 1.5, -y); d.scale.set(s, 1, s); d.renderOrder = 1002; this.group.add(d); }
  }

  /** Per-leg chips on the map and the panel readout. */
  render() {
    const unit = this.app.units;
    const out = document.getElementById('mRead'); if (!out) return;
    if (!this.points.length) { out.innerHTML = `<p class="hint">Click the map to start. ${this.mode === 'road' ? 'Each click adds a stop; the route follows the streets.' : 'Each click adds a point.'} Backspace removes the last point, Esc ends.</p>`; this.tags.innerHTML = ''; return; }
    const tot = this.legs.reduce((s, l) => s + l.meters, 0), st = this.legs.reduce((s, l) => s + l.straight, 0), secs = this.legs.reduce((s, l) => s + (l.seconds || 0), 0);
    let html = `<div class="mbig">${fmtDist(tot, unit)}</div>`;
    if (this.mode === 'road' && this.legs.length) html += `<div class="msum">${fmtTime(secs)} by car · ${fmtTime(tot / WALK)} on foot · ${fmtDist(st, unit)} straight</div>`;
    else if (this.legs.length) html += `<div class="msum">${fmtTime(tot / WALK)} on foot · ${fmtTime(tot / 13.4)} by car at 30 mph</div>`;
    if (this.legs.length > 1 || (this.legs[0] && this.legs[0].roads.length)) {
      html += '<ol class="legs">' + this.legs.map((l, i) => `<li><b>${fmtDist(l.meters, unit)}</b>${l.seconds != null ? ' · ' + fmtTime(l.seconds) : ''}${l.noRoute ? ' · no road route, straight line shown' : ''}${l.roads.length ? `<div class="via">via ${(rn => rn.slice(0, 7).join(', ') + (rn.length > 7 ? ' and ' + (rn.length - 7) + ' more' : ''))([...new Set(l.roads.filter(r => r.name).map(r => esc(r.name)))])}</div>` : ''}</li>`).join('') + '</ol>';
    }
    const gap = this.legs.reduce((s, l) => s + (l.gap || 0), 0);
    if (gap > 1) html += `<p class="hint">This route crosses ${fmtDist(gap, unit)} where the Atlas has no street (a gap flagged in the map check). The router assumes a connection there.</p>`;
    out.innerHTML = html;
    // chips at leg midpoints
    this.tags.innerHTML = this.legs.map((l, i) => { const m = l.path[Math.floor(l.path.length / 2)]; return `<div class="mtag" data-x="${m[0]}" data-y="${m[1]}">${fmtDist(l.meters, unit)}</div>`; }).join('');
    this.placeTags();
  }
  placeTags() {
    const cam = this.app.camera, W = this.app.el.clientWidth, H = this.app.el.clientHeight, v = new THREE.Vector3();
    for (const el of this.tags.children) { v.set(+el.dataset.x, 2, -el.dataset.y).project(cam); el.style.display = v.z > 1 ? 'none' : ''; el.style.left = ((v.x * 0.5 + 0.5) * W) + 'px'; el.style.top = ((-v.y * 0.5 + 0.5) * H) + 'px'; }
  }
}
