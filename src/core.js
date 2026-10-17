// Westport 3D: data loading, decoding, QA fixes and spatial lookups.
// World frame: x = Atlas x (east), z = -Atlas y (south), y = up. Meters. Origin = Courthouse Square.
import * as THREE from 'three';

export const BK = ['house', 'duplex', 'mobile', 'shed', 'barn', 'shop', 'office', 'tower', 'deck', 'retail', 'apartments', 'townhouse', 'clubhouse', 'church', 'school', 'gym', 'stands', 'hospital', 'industrial', 'civic', 'motel', 'hotel'];
export const CLS = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway'];
export const HALF = { trunk: 7.5, primary: 6.5, secondary: 5.5, tertiary: 4.5, residential: 3.75, service: 2.75, track: 2.0, path: 1.0, motorway: 9 };
export const NINE_ORDER = ['Calista Yuen', 'Lori Delacroix', 'Reya Patel', 'Nellie Sullivan', 'Charlie Thompson', 'Dalton Abernathy', 'Zane Al-Hassan', 'Morgan Hernandez', 'Elio Rossi'];
export const CAT_COLORS = { civic: '#8A6D5A', school: '#C99A2E', church: '#8E6FA8', park: '#5E9E5A', shop: '#C7604A', food: '#D27A3A', health: '#C24B5B', marina: '#3D7FA8', industry: '#7B7F8A', lodging: '#6C7BB8', landmark: '#9E3D5F', canon: '#B0464B', homepoi: '#6f675c' };
export const STATUS = { locked: 'Locked', canon2: 'Canon 2', 'author-site': 'Your site', confirmed: 'You confirmed', 'author-doc': 'Your doc', proposed: 'Proposed', qa: 'Added by map check' };

export const WATER_Y = -0.7;
export const toWorld = (ax, ay, y = 0) => new THREE.Vector3(ax, y, -ay);
export const toAtlas = v => [v.x, -v.z];

// ---------------------------------------------------------------- random + geometry helpers
export function hash(n) { n = (n ^ 61) ^ (n >>> 16); n = n + (n << 3); n = n ^ (n >>> 4); n = Math.imul(n, 0x27d4eb2d); n = n ^ (n >>> 15); return (n >>> 0) / 4294967296; }
export function hash2(x, y) { return hash((Math.imul(Math.floor(x) | 0, 73856093) ^ Math.imul(Math.floor(y) | 0, 19349663)) | 0); }
export function rng(seed) { let s = (seed >>> 0) || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 1e9) / 1e9; }; }

export function pointInRing(x, y, r) { // r: flat [x,y,...]
  let inside = false;
  for (let i = 0, j = r.length - 2; i < r.length; j = i, i += 2) {
    const xi = r[i], yi = r[i + 1], xj = r[j], yj = r[j + 1];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
export function pointInPoly(x, y, rings) { if (!pointInRing(x, y, rings[0])) return false; for (let k = 1; k < rings.length; k++) if (pointInRing(x, y, rings[k])) return false; return true; }
export function ringBBox(r) { let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity; for (let i = 0; i < r.length; i += 2) { a = Math.min(a, r[i]); c = Math.max(c, r[i]); b = Math.min(b, r[i + 1]); d = Math.max(d, r[i + 1]); } return [a, b, c, d]; }
export function ringArea(r) { let s = 0; for (let i = 0, j = r.length - 2; i < r.length; j = i, i += 2) s += (r[j] - r[i]) * (r[j + 1] + r[i + 1]); return s / 2; }
export function segDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
  let t = L ? ((px - x1) * dx + (py - y1) * dy) / L : 0; t = t < 0 ? 0 : t > 1 ? 1 : t;
  const qx = x1 + t * dx, qy = y1 + t * dy; return [Math.hypot(px - qx, py - qy), qx, qy, t];
}

// Uniform grid over Atlas meters. Items are integer ids with a bbox.
export class Grid {
  constructor(cell = 100) { this.cell = cell; this.m = new Map(); }
  key(i, j) { return i * 100003 + j; }
  insert(id, x0, y0, x1, y1) {
    const c = this.cell;
    for (let i = Math.floor(x0 / c); i <= Math.floor(x1 / c); i++) for (let j = Math.floor(y0 / c); j <= Math.floor(y1 / c); j++) {
      const k = this.key(i, j); let a = this.m.get(k); if (!a) this.m.set(k, a = []); a.push(id);
    }
  }
  query(x0, y0, x1, y1, fn) {
    const c = this.cell, seen = new Set();
    for (let i = Math.floor(x0 / c); i <= Math.floor(x1 / c); i++) for (let j = Math.floor(y0 / c); j <= Math.floor(y1 / c); j++) {
      const a = this.m.get(this.key(i, j)); if (!a) continue;
      for (const id of a) if (!seen.has(id)) { seen.add(id); if (fn(id) === false) return; }
    }
  }
}

// ---------------------------------------------------------------- loading
export async function loadJSON(url, optional = false) {
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(url + ' ' + r.status);
    return await r.json();
  } catch (e) { if (optional) return null; throw e; }
}

// Decode the Atlas file into typed structures and apply the map check's fixes.
export function decode(wp, gaz, qa) {
  const names = wp.names;
  const nm = i => (i < 0 ? null : names[i]);
  const D = { names, gaz, qa, wp };
  // buildings
  const fx = qa && qa.fixes ? qa.fixes : {};
  const removed = new Set(fx.remove_buildings || []);
  const replaced = new Map((fx.replace_buildings || []).map(r => [r.i, r.poly]));
  const list = [];
  wp.b.forEach((b, i) => {
    if (removed.has(i)) return;
    let p = replaced.get(i);
    if (!p) { p = new Array(8); for (let k = 0; k < 8; k++) p[k] = b[2 + k] / 2; }
    list.push({ i, kind: BK[b[0]] || 'house', h: b[1] / 2, poly: p });
  });
  (fx.add_buildings || []).forEach((a, k) => list.push({ i: wp.b.length + k, kind: a.kind || 'house', h: a.h || 7, poly: a.poly, added: true, street: a.street, num: a.num, why: a.why }));
  const addr = new Map();
  for (const [i, s, n] of wp.addr) addr.set(i, [nm(s), n]);
  for (const b of list) {
    const p = b.poly; b.cx = (p[0] + p[2] + p[4] + p[6]) / 4; b.cy = (p[1] + p[3] + p[5] + p[7]) / 4;
    const a = addr.get(b.i); if (a) { b.street = a[0]; b.num = a[1]; }
    const e1 = Math.hypot(p[2] - p[0], p[3] - p[1]), e2 = Math.hypot(p[4] - p[2], p[5] - p[3]);
    b.w = e1; b.d = e2; b.ang = Math.atan2(p[3] - p[1], p[2] - p[0]);
  }
  D.buildings = list;
  D.removedCount = removed.size; D.replacedCount = replaced.size;
  D.bIndex = new Map(list.map((b, k) => [b.i, k]));
  // roads (+ endpoint snaps from the map check)
  const snaps = fx.road_snaps || [];
  D.roads = wp.roads.map(([n, c, br, p], i) => ({ i, name: nm(n), cls: CLS[c] || 'residential', bridge: !!br, pts: p.slice() }));
  for (const s of snaps) { const r = D.roads[s.road]; if (r && r.pts.length > s.vertex * 2 + 1) { r.pts[s.vertex * 2] = s.to[0]; r.pts[s.vertex * 2 + 1] = s.to[1]; } }
  for (const a of fx.add_roads || []) D.roads.push({ i: D.roads.length, name: a.name, cls: a.cls || 'residential', bridge: !!a.bridge, pts: a.pts.slice(), added: true, why: a.why });
  D.rail = wp.rail.map(([yard, p]) => ({ yard: !!yard, pts: p }));
  D.lu = wp.lu.map(([kind, under, outer, holes], i) => ({ i, kind, under: !!under, rings: [outer, ...(holes || [])] }));
  D.land = wp.land; D.marsh = wp.marsh; D.shoal = wp.shoal; D.creeks = wp.creeks; D.piers = wp.piers; D.limits = wp.limits;
  // labels and pois with the check's moves
  const lmv = new Map((fx.move_labels || []).map(m => [m.text, m]));
  D.labels = wp.labels.map(l => { const m = lmv.get(l.text); return m ? { ...l, at: m.at, rot: m.rot ?? l.rot } : l; });
  const pmv = new Map((fx.move_places || []).map(m => [m.id, m.at]));
  const hmv = new Map((fx.move_people || []).map(m => [m.name, m.at]));
  D.places = (gaz ? gaz.places : wp.pois).map(p => ({ ...p, at: pmv.get(p.id) || p.at }));
  D.people = (gaz ? gaz.people : []).map(h => (h.home && hmv.has(h.name) ? { ...h, home: { ...h.home, at: hmv.get(h.name) } } : h));
  D.streets = new Map();
  for (const r of D.roads) if (r.name && r.cls !== 'track') { let s = D.streets.get(r.name); if (!s) D.streets.set(r.name, s = { name: r.name, cls: r.cls, roads: [], len: 0 }); s.roads.push(r.i); s.len += polyLen(r.pts); if (CLS.indexOf(r.cls) < CLS.indexOf(s.cls)) s.cls = r.cls; }
  buildIndexes(D);
  return D;
}

export function polyLen(p) { let s = 0; for (let i = 2; i < p.length; i += 2) s += Math.hypot(p[i] - p[i - 2], p[i + 1] - p[i - 1]); return s; }

function buildIndexes(D) {
  D.bGrid = new Grid(60);
  D.buildings.forEach((b, k) => { const bb = ringBBox(b.poly); D.bGrid.insert(k, bb[0], bb[1], bb[2], bb[3]); });
  D.segs = []; D.rGrid = new Grid(80);
  for (const r of D.roads) {
    const p = r.pts;
    for (let i = 0; i + 3 < p.length; i += 2) {
      const id = D.segs.length; D.segs.push([p[i], p[i + 1], p[i + 2], p[i + 3], r.i]);
      D.rGrid.insert(id, Math.min(p[i], p[i + 2]) - 2, Math.min(p[i + 1], p[i + 3]) - 2, Math.max(p[i], p[i + 2]) + 2, Math.max(p[i + 1], p[i + 3]) + 2);
    }
  }
  D.luGrid = new Grid(400);
  D.lu.forEach((l, k) => { const bb = ringBBox(l.rings[0]); l.bbox = bb; D.luGrid.insert(k, bb[0], bb[1], bb[2], bb[3]); });
  D.landBBox = D.land.map(poly => ringBBox(poly[0]));
}

// Nearest road segment to a point, optionally filtered. Returns {d, x, y, road, seg, bearing}.
export function nearestRoad(D, x, y, maxD = 200, filter = null) {
  let best = null;
  for (let R = Math.min(40, maxD); ; R = Math.min(maxD, R * 2.5)) {
    D.rGrid.query(x - R, y - R, x + R, y + R, id => {
      const s = D.segs[id], r = D.roads[s[4]];
      if (filter && !filter(r)) return;
      const [d, qx, qy] = segDist(x, y, s[0], s[1], s[2], s[3]);
      if (d <= R && (!best || d < best.d)) best = { d, x: qx, y: qy, road: r, seg: id, bearing: Math.atan2(s[3] - s[1], s[2] - s[0]) };
    });
    if (best || R >= maxD) break;
  }
  return best && best.d <= maxD ? best : null;
}

export function landAt(D, x, y) {
  for (let k = 0; k < D.land.length; k++) {
    const bb = D.landBBox[k]; if (x < bb[0] || x > bb[2] || y < bb[1] || y > bb[3]) continue;
    if (pointInPoly(x, y, D.land[k])) return true;
  }
  return false;
}
export function luAt(D, x, y) {
  let hit = null;
  D.luGrid.query(x, y, x, y, k => { const l = D.lu[k]; if (pointInPoly(x, y, l.rings)) { if (!hit || !l.under) hit = l; } });
  return hit;
}
export function buildingAt(D, x, y) {
  let hit = null;
  D.bGrid.query(x, y, x, y, k => { const b = D.buildings[k]; if (pointInRing(x, y, b.poly)) { hit = b; return false; } });
  return hit;
}
export function nearestAddress(D, x, y, R = 80) {
  let best = null;
  D.bGrid.query(x - R, y - R, x + R, y + R, k => { const b = D.buildings[k]; if (!b.num) return; const d = Math.hypot(b.cx - x, b.cy - y); if (d < R && (!best || d < best.d)) best = { d, b }; });
  return best;
}

// True if (x, y) lies on a drivable road surface (within half width + margin of any non-bridge road).
export function onRoadSurface(D, x, y, margin = 0) {
  let hit = false;
  D.rGrid.query(x - 12, y - 12, x + 12, y + 12, id => {
    const s = D.segs[id], r = D.roads[s[4]]; if (r.cls === 'path' || r.bridge) return;
    if (segDist(x, y, s[0], s[1], s[2], s[3])[0] < HALF[r.cls] + margin) { hit = true; return false; }
  });
  return hit;
}

// Modeled lots (the Nine's homes): oriented rectangles in each home's local frame (x right, y back; front = -y).
export function setHeroLots(D, homes) {
  D.heroLots = (homes || []).filter(h => h.lotRect).map(h => {
    const a = h.heading * Math.PI / 180, nx = Math.cos(a), ny = Math.sin(a);
    return { x: h.at[0], y: h.at[1], nx, ny, rect: h.lotRect, id: h.id };
  });
}
export function inHeroLot(D, x, y, margin = 0) {
  for (const L of D.heroLots || []) {
    const vx = x - L.x, vy = y - L.y; if (vx * vx + vy * vy > 3600) continue;
    const lx = vx * L.ny + vy * -L.nx, ly = -(vx * L.nx + vy * L.ny);
    const [x0, y0, x1, y1] = L.rect;
    if (lx >= x0 - margin && lx <= x1 + margin && ly >= y0 - margin && ly <= y1 + margin) return L;
  }
  return null;
}

// Formatting
export function fmtDist(m, unit = 'imperial') {
  if (m == null || !isFinite(m)) return '–';
  if (unit === 'metric') return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`;
  const ft = m * 3.28084;
  return ft < 1000 ? `${Math.round(ft)} ft` : `${(m / 1609.344).toFixed(m < 16093 ? 2 : 1)} mi`;
}
export function fmtTime(s) { if (s == null || !isFinite(s)) return '–'; const m = s / 60; return m < 1 ? '<1 min' : m < 60 ? `${Math.round(m)} min` : `${Math.floor(m / 60)} h ${Math.round(m % 60)} min`; }
export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
