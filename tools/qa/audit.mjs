#!/usr/bin/env node
/*
 * Westport Atlas QA + alignment audit.
 *
 * Run from the repo root:   node tools/qa/audit.mjs            (also draws renders/qa/*.png with python3 + Pillow)
 *                           node tools/qa/audit.mjs --no-plots (skip the PNGs)
 *
 * Reads (never writes): data/wpdata.json, data/gaz.json, docs/westport-register.md, docs/site-specs.json
 * Writes: data/qa.json, docs/QA-REPORT.md, renders/qa/*.png (through tools/qa/plots.py)
 *
 * ---------------------------------------------------------------------------------------------
 * data/qa.json, version 1. All coordinates are Atlas meters (x east, y north). Polygons are flat
 * arrays in meters [x1,y1,x2,y2,x3,y3,x4,y4] (NOT the x2 encoding of wpdata.b), in the same vertex
 * order as the original building.
 *
 * {
 *  "version": 1,
 *  "summary": {"buildings": n, "roads": n, "places": n, "issues": n, "fixed": n, "flagged": n,
 *              "by_type": {"<type>": {"found": n, "fixed": n}}},
 *  "fixes": {
 *    "remove_buildings":  [buildingIndex, ...],                         // drop wpdata.b[i]
 *    "replace_buildings": [{"i", "poly": [8 numbers], "why"}],           // use poly instead of wpdata.b[i]; kind, height and address stay
 *    "add_buildings":     [{"kind", "h", "poly", "street", "num", "why"}], // new buildings, "added by QA, proposed" (not canon); for an added
 *                                                                        // house the first edge (poly[0..3]) is the street front, left to right
 *    "move_places":       [{"id", "at": [x,y], "was": [x,y], "why"}],     // gaz.places[id].at and wpdata.pois[id].at
 *    "move_people":       [{"name", "at", "was", "why"}],                 // gaz.people[name].home.at
 *    "move_labels":       [{"text", "at", "was", "why", "rot"?}],         // wpdata.labels: match text AND was (texts repeat); optional rot = new text rotation (deg)
 *    "road_snaps":        [{"road", "vertex", "to": [x,y], "why"}]        // set point `vertex` (pair index) of wpdata.roads[road][3] to `to`
 *  },
 *  "issues": [{"id": "Q0001", "type", "severity": "high|medium|low", "at": [x,y], "ref": {...},
 *              "detail": "plain sentence", "action": "fixed|flagged", "fix": "remove|replace|add|move|snap|none"}]
 * }
 *
 * Apply order: remove_buildings, replace_buildings, add_buildings (appended; the k-th one gets index
 * wpdata.b.length + k), the point and label moves, then road_snaps. An index never appears in both
 * remove_buildings and replace_buildings. Hero homes (docs/site-specs.json) are never changed.
 * ---------------------------------------------------------------------------------------------
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ARGS = new Set(process.argv.slice(2));
const DEBUG = new Set((process.env.QA_DEBUG || '').split(',').filter(Boolean).map(Number));
const T0 = Date.now();
const rd = p => fs.readFileSync(path.join(ROOT, p), 'utf8');
const W = JSON.parse(rd('data/wpdata.json'));
const G = JSON.parse(rd('data/gaz.json'));
const REG = fs.existsSync(path.join(ROOT, 'docs/westport-register.md')) ? rd('docs/westport-register.md') : '';
const SITE = fs.existsSync(path.join(ROOT, 'docs/site-specs.json')) ? JSON.parse(rd('docs/site-specs.json')) : null;

// ------------------------------------------------------------------ constants
const BK = ['house', 'duplex', 'mobile', 'shed', 'barn', 'shop', 'office', 'tower', 'deck', 'retail', 'apartments', 'townhouse', 'clubhouse', 'church', 'school', 'gym', 'stands', 'hospital', 'industrial', 'civic', 'motel', 'hotel'];
const CLS = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway'];
const HALF = { trunk: 7.5, primary: 6.5, secondary: 5.5, tertiary: 4.5, residential: 3.75, service: 2.75, track: 2.0, path: 1.0, motorway: 9 };
const CREEK_HALF = 3.0;                       // creeks are polylines; a 6 m channel
const RAIL_HALF = 2.5, YARD_HALF = 2.0;       // ballast bed of the main line / a yard track
const PIER_HALF = 2.0, BOARDWALK_HALF = 3.0;  // finger piers / the long downtown boardwalk
const PEN_TOL = 0.25;      // m of intrusion into a road/creek/rail/pier surface that counts (coordinates are rounded to 0.5-1 m)
const MARGIN = 0.5;        // m of clearance a fix leaves
const OVERLAP_MIN = 1.0;   // m2 of footprint intersection that counts as an overlap
const OVERLAP_NEW = 0.1;   // m2 a fix may not create
const RESID = new Set(['house', 'duplex', 'mobile', 'townhouse']);
const ROWS = new Set(['townhouse', 'apartments', 'motel', 'retail', 'shop', 'industrial', 'office']); // multi-unit: may lose end units
const TYPE_ORDER = ['building-in-water', 'building-in-marsh', 'building-on-road', 'building-on-rail', 'building-on-creek', 'building-on-pier', 'building-overlap', 'misaligned-building', 'road-into-building', 'road-gap', 'road-dead-end', 'road-crosses-water', 'bridge-dead-end', 'dangling-stub', 'address-missing', 'address-point-mismatch', 'place-off-site', 'label-placement', 'canon-conflict'];

const names = W.names;
const nm = i => (i < 0 ? null : names[i]);
const r2 = v => Math.round(v * 100) / 100;
const P2 = p => [r2(p[0]), r2(p[1])];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const fmt = v => String(Math.round(v * 10) / 10);
const med = arr => { const s = arr.slice().sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN; };

// ------------------------------------------------------------------ geometry
const signedArea = p => { let a = 0; for (let i = 0, n = p.length; i < n; i++) { const q = p[i], r = p[(i + 1) % n]; a += q[0] * r[1] - r[0] * q[1]; } return a / 2; };
const areaOf = p => Math.abs(signedArea(p));
const ccw = p => (signedArea(p) >= 0 ? p : p.slice().reverse());
const centroid = p => { let x = 0, y = 0; for (const q of p) { x += q[0]; y += q[1]; } return [x / p.length, y / p.length]; };
const bboxOf = (p, pad = 0) => { let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity; for (const q of p) { if (q[0] < a) a = q[0]; if (q[1] < b) b = q[1]; if (q[0] > c) c = q[0]; if (q[1] > d) d = q[1]; } return [a - pad, b - pad, c + pad, d + pad]; };
const translate = (p, v) => p.map(q => [q[0] + v[0], q[1] + v[1]]);
const rotateAbout = (p, c, ang) => { const cs = Math.cos(ang), sn = Math.sin(ang); return p.map(q => { const x = q[0] - c[0], y = q[1] - c[1]; return [c[0] + x * cs - y * sn, c[1] + x * sn + y * cs]; }); };
const flatPoly = p => p.flatMap(q => [r2(q[0]), r2(q[1])]);
const ptsOf = flat => { const o = []; for (let i = 0; i + 1 < flat.length; i += 2) o.push([flat[i], flat[i + 1]]); return o; };
const polyLen = pts => { let L = 0; for (let i = 1; i < pts.length; i++) L += dist(pts[i - 1], pts[i]); return L; };
const angMod90 = a => { let d = ((a % 90) + 90) % 90; if (d >= 45) d -= 90; return d; };
const edgeAngle = p => Math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0]) * 180 / Math.PI;
const sides = p => [dist(p[0], p[1]), dist(p[1], p[2])];
// rectangle centered on c, edge 0 runs along u on the side opposite n = left normal of u
const rectAt = (c, u, w, d) => { const n = [-u[1], u[0]], hw = w / 2, hd = d / 2; return [[c[0] - u[0] * hw - n[0] * hd, c[1] - u[1] * hw - n[1] * hd], [c[0] + u[0] * hw - n[0] * hd, c[1] + u[1] * hw - n[1] * hd], [c[0] + u[0] * hw + n[0] * hd, c[1] + u[1] * hw + n[1] * hd], [c[0] - u[0] * hw + n[0] * hd, c[1] - u[1] * hw + n[1] * hd]]; };
// a building facing a street: n points from the street to the building; edge 0 is the front, left to right as seen from the street
const frontRect = (c, n, w, d) => rectAt(c, [n[1], -n[0]], w, d);

function clipConvex(subject, clip) { // both CCW
  let out = subject;
  for (let i = 0; i < clip.length && out.length; i++) {
    const a = clip[i], b = clip[(i + 1) % clip.length]; const inp = out; out = [];
    for (let j = 0; j < inp.length; j++) {
      const P = inp[j], Q = inp[(j + 1) % inp.length];
      const sp = (b[0] - a[0]) * (P[1] - a[1]) - (b[1] - a[1]) * (P[0] - a[0]);
      const sq = (b[0] - a[0]) * (Q[1] - a[1]) - (b[1] - a[1]) * (Q[0] - a[0]);
      if (sp >= 0) out.push(P);
      if ((sp >= 0) !== (sq >= 0)) { const t = sp / (sp - sq); out.push([P[0] + t * (Q[0] - P[0]), P[1] + t * (Q[1] - P[1])]); }
    }
  }
  return out;
}
const interArea = (a, b) => { const c = clipConvex(ccw(a), ccw(b)); return c.length >= 3 ? areaOf(c) : 0; };
// separating axis: the smallest move of b (along axis, away from a) that separates the two convex polygons
function satMTV(a, b) {
  let best = null;
  for (const poly of [a, b]) for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length]; let nx = q[1] - p[1], ny = p[0] - q[0]; const L = Math.hypot(nx, ny); if (L < 1e-9) continue; nx /= L; ny /= L;
    let amin = Infinity, amax = -Infinity, bmin = Infinity, bmax = -Infinity;
    for (const v of a) { const d = v[0] * nx + v[1] * ny; if (d < amin) amin = d; if (d > amax) amax = d; }
    for (const v of b) { const d = v[0] * nx + v[1] * ny; if (d < bmin) bmin = d; if (d > bmax) bmax = d; }
    const o1 = amax - bmin, o2 = bmax - amin; const o = Math.min(o1, o2); if (o <= 0) return null;
    if (!best || o < best.depth) best = { depth: o, axis: o1 < o2 ? [nx, ny] : [-nx, -ny] };
  }
  return best;
}
function ptSeg(px, py, x1, y1, x2, y2) { // -> [dist, t, qx, qy]
  const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
  let t = L === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / L; t = t < 0 ? 0 : t > 1 ? 1 : t;
  const qx = x1 + t * dx, qy = y1 + t * dy; return [Math.hypot(px - qx, py - qy), t, qx, qy];
}
const cross = (ax, ay, bx, by, cx, cy) => (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
function segsCross(a, b, c, d) {
  const d1 = cross(c[0], c[1], d[0], d[1], a[0], a[1]), d2 = cross(c[0], c[1], d[0], d[1], b[0], b[1]);
  const d3 = cross(a[0], a[1], b[0], b[1], c[0], c[1]), d4 = cross(a[0], a[1], b[0], b[1], d[0], d[1]);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}
function ptInPoly(p, x, y) { let c = false; for (let i = 0, j = p.length - 1; i < p.length; j = i++) { const a = p[i], b = p[j]; if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c; } return c; }
function polySegDist(p, x1, y1, x2, y2) {
  if (ptInPoly(p, x1, y1) || ptInPoly(p, x2, y2)) return 0;
  let d = Infinity;
  for (let i = 0; i < p.length; i++) {
    const a = p[i], b = p[(i + 1) % p.length];
    if (segsCross(a, b, [x1, y1], [x2, y2])) return 0;
    d = Math.min(d, ptSeg(a[0], a[1], x1, y1, x2, y2)[0], ptSeg(x1, y1, a[0], a[1], b[0], b[1])[0], ptSeg(x2, y2, a[0], a[1], b[0], b[1])[0]);
  }
  return d;
}
const ptPolyDist = (p, x, y) => { if (ptInPoly(p, x, y)) return 0; let d = Infinity; for (let k = 0; k < p.length; k++) d = Math.min(d, ptSeg(x, y, p[k][0], p[k][1], p[(k + 1) % p.length][0], p[(k + 1) % p.length][1])[0]); return d; };
function samples(p, n) { // n x n points spread over a quad (bilinear)
  const out = [];
  for (let a = 0; a < n; a++) for (let b = 0; b < n; b++) {
    const u = (a + 0.5) / n, v = (b + 0.5) / n;
    out.push([(1 - u) * (1 - v) * p[0][0] + u * (1 - v) * p[1][0] + u * v * p[2][0] + (1 - u) * v * p[3][0],
      (1 - u) * (1 - v) * p[0][1] + u * (1 - v) * p[1][1] + u * v * p[2][1] + (1 - u) * v * p[3][1]]);
  }
  return out;
}

// ------------------------------------------------------------------ spatial indexes
class Grid {
  constructor(cell) { this.c = cell; this.m = new Map(); this.bb = new Map(); }
  *cells(bb) { const c = this.c; for (let ix = Math.floor(bb[0] / c); ix <= Math.floor(bb[2] / c); ix++) for (let iy = Math.floor(bb[1] / c); iy <= Math.floor(bb[3] / c); iy++) yield (ix + 40000) * 80000 + (iy + 40000); }
  add(id, bb) { this.bb.set(id, bb); for (const k of this.cells(bb)) { let a = this.m.get(k); if (!a) this.m.set(k, a = new Set()); a.add(id); } }
  remove(id) { const bb = this.bb.get(id); if (!bb) return; for (const k of this.cells(bb)) { const a = this.m.get(k); if (a) a.delete(id); } this.bb.delete(id); }
  query(bb) { const out = new Set(); for (const k of this.cells(bb)) { const a = this.m.get(k); if (a) for (const id of a) out.add(id); } return out; }
}
class RingIdx { // even-odd point in ring, edges bucketed in horizontal bands
  constructor(flat, band = 25) {
    this.band = band; this.m = new Map(); const p = ptsOf(flat); this.bb = bboxOf(p);
    for (let i = 0; i < p.length; i++) {
      const a = p[i], b = p[(i + 1) % p.length]; if (a[1] === b[1]) continue;
      for (let k = Math.floor(Math.min(a[1], b[1]) / band); k <= Math.floor(Math.max(a[1], b[1]) / band); k++) { let e = this.m.get(k); if (!e) this.m.set(k, e = []); e.push([a[0], a[1], b[0], b[1]]); }
    }
  }
  has(x, y) {
    if (x < this.bb[0] || x > this.bb[2] || y < this.bb[1] || y > this.bb[3]) return false;
    const es = this.m.get(Math.floor(y / this.band)); if (!es) return false; let c = false;
    for (const e of es) if ((e[1] > y) !== (e[3] > y) && x < e[0] + (y - e[1]) * (e[2] - e[0]) / (e[3] - e[1])) c = !c;
    return c;
  }
}
class AreaSet { // polygons: ring 0 outer, later rings holes
  constructor(polys) { this.P = polys.map(p => ({ outer: new RingIdx(p[0]), holes: p.slice(1).map(h => new RingIdx(h)) })); }
  has(x, y) { for (const P of this.P) if (P.outer.has(x, y) && !P.holes.some(h => h.has(x, y))) return true; return false; }
  frac(poly, n = 6) { const s = samples(poly, n); let k = 0; for (const q of s) if (this.has(q[0], q[1])) k++; return k / s.length; }
}
const LAND = new AreaSet(W.land), MARSH = new AreaSet(W.marsh);
const LIMITS = W.limits.map(r => ptsOf(r));
const isWater = (x, y) => !LAND.has(x, y);
const isDry = (x, y) => LAND.has(x, y) && !MARSH.has(x, y);
function shoreDist(pt, rmax = 2000, step = 5) { // distance to the nearest open water
  for (let r = step; r <= rmax; r += step) { const n = Math.max(12, Math.round(2 * Math.PI * r / step)); for (let k = 0; k < n; k++) { const a = 2 * Math.PI * k / n; if (isWater(pt[0] + r * Math.cos(a), pt[1] + r * Math.sin(a))) return r; } }
  return Infinity;
}

// ------------------------------------------------------------------ decode buildings and addresses
const addrOf = new Map(); const byAddr = new Map(); const streetAddrs = new Map();
for (const [i, s, n] of W.addr) {
  const st = nm(s); addrOf.set(i, { street: st, num: n });
  const key = `${n} ${st}`.toLowerCase(); if (!byAddr.has(key)) byAddr.set(key, []); byAddr.get(key).push(i);
  if (!streetAddrs.has(st)) streetAddrs.set(st, []); streetAddrs.get(st).push([i, n]);
}
const B = W.b.map((b, i) => { const pts = []; for (let k = 2; k < 10; k += 2) pts.push([b[k] / 2, b[k + 1] / 2]); return { i, kind: BK[b[0]], h: b[1] / 2, pts0: pts }; });
const addrStr = i => { const a = addrOf.get(i); return a ? `${a.num} ${a.street}` : null; };
const cur = B.map(b => b.pts0); // current footprint, null = removed
const BG = new Grid(40); B.forEach((b, i) => BG.add(i, bboxOf(b.pts0)));
const setPoly = (i, p) => { BG.remove(i); cur[i] = p; if (p) BG.add(i, bboxOf(p)); };
const kindLabel = i => `${B[i].kind} #${i}${addrStr(i) ? ' (' + addrStr(i) + ')' : ''}`;
const parseAddr = s => { if (!s) return null; const m = String(s).match(/^\s*(\d+)\s+([^,]+?)\s*(?:,.*)?$/); return m ? { num: +m[1], street: m[2].trim(), key: `${m[1]} ${m[2].trim()}`.toLowerCase(), raw: String(s) } : null; };
const buildingAt = (pt, r = 0) => { let best = null; for (const j of BG.query([pt[0] - r - 1, pt[1] - r - 1, pt[0] + r + 1, pt[1] + r + 1])) { const p = cur[j]; if (!p) continue; const d = ptPolyDist(p, pt[0], pt[1]); if (d <= r && (!best || d < best.d)) best = { j, d }; } return best; };
const nearestBuilding = (pt, r = 300, ok = null) => { let best = null; for (const j of BG.query([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r])) { if (!cur[j] || (ok && !ok(j))) continue; const d = ptPolyDist(cur[j], pt[0], pt[1]); if (d <= r && (!best || d < best.d)) best = { j, d }; } return best; };

// hero homes are never changed; buildings that carry a named place or a character's home are never removed
const HERO = new Map();
for (const h of (SITE && SITE.homes) || []) HERO.set(h.building_index, h.id);
if (!HERO.size) [['monet-williams-house', 6973], ['thompson-house', 22180], ['patel-house', 23310], ['al-hassan-house', 21135], ['hernandez-house', 30499], ['abernathy-trailer', 173], ['delacroix-house', 23936], ['sullivan-house', 21165], ['rossi-house', 21164]].forEach(([k, i]) => HERO.set(i, k));
const NAMED = new Map(); const markNamed = (j, id) => { if (!NAMED.has(j)) NAMED.set(j, []); if (!NAMED.get(j).includes(id)) NAMED.get(j).push(id); };
for (const pl of G.places) { const at = buildingAt(pl.at, 12); if (at) markNamed(at.j, pl.id); }
for (const pe of G.people) { const at = buildingAt(pe.home.at, 12); if (at) markNamed(at.j, 'home of ' + pe.name); }
const isHero = i => HERO.has(i);
const isNamed = i => NAMED.has(i) || HERO.has(i);
const namedWhy = i => HERO.has(i) ? `hero home ${HERO.get(i)}` : `the building of ${NAMED.get(i).join(', ')}`;

// ------------------------------------------------------------------ bookkeeping
const ISSUES = [];
const FIX = { remove_buildings: [], replace_buildings: [], add_buildings: [], move_places: [], move_people: [], move_labels: [], road_snaps: [] };
const replaced = new Map(); const XFORM = new Map(); // i -> transforms applied (place points follow their building)
const ADDED = [];
function addBuilding(kind, h, poly, street, num, why, info) { const k = W.b.length + ADDED.length; FIX.add_buildings.push({ kind, h, poly: flatPoly(poly), street: street || null, num: num || null, why }); ADDED.push({ k, kind, poly, info }); B.push({ i: k, kind, h, pts0: poly, added: true }); cur.push(poly); BG.add(k, bboxOf(poly)); if (street) addrOf.set(k, { street, num }); return k; }
function issue(type, severity, at, ref, detail, action = 'flagged', fix = 'none') { const o = { id: '', type, severity, at: P2(at), ref, detail, action, fix }; ISSUES.push(o); return o; }
const bref = i => { const o = { building: i, kind: B[i].kind }; const a = addrStr(i); if (a) o.addr = a; if (HERO.has(i)) o.hero = HERO.get(i); if (NAMED.has(i)) o.places = NAMED.get(i); return o; };
function doRemove(i) { if (isNamed(i)) throw new Error('named building ' + i + ' must not be removed'); setPoly(i, null); if (replaced.has(i)) { FIX.replace_buildings.splice(FIX.replace_buildings.indexOf(replaced.get(i)), 1); replaced.delete(i); } FIX.remove_buildings.push(i); }
function doReplace(i, p, why, xf) {
  if (isHero(i)) throw new Error('hero home ' + i + ' must not change');
  setPoly(i, p); if (!XFORM.has(i)) XFORM.set(i, []); XFORM.get(i).push(xf || { t: 'other' });
  if (replaced.has(i)) { const e = replaced.get(i); e.poly = flatPoly(p); e.why += '; ' + why; } else { const e = { i, poly: flatPoly(p), why }; FIX.replace_buildings.push(e); replaced.set(i, e); }
}

// =============================================================================================
// 1. Roads first (gaps, roads that end inside buildings); buildings are then checked against the fixed roads
// =============================================================================================
const roadPts = W.roads.map(r => ptsOf(r[3]));          // original
const roadFix = roadPts.map(p => p.map(q => q.slice())); // after snaps
const roadName = ri => { const r = W.roads[ri]; return r[0] >= 0 ? names[r[0]] : `unnamed ${CLS[r[1]]}`; };
const snapped = new Map();
function snapVertex(ri, v, to, why) { const key = ri + ':' + v; if (snapped.has(key)) { const e = FIX.road_snaps.find(s => s.road === ri && s.vertex === v); e.to = P2(to); e.why += '; ' + why; } else FIX.road_snaps.push({ road: ri, vertex: v, to: P2(to), why }); snapped.set(key, to); roadFix[ri][v] = to.slice(); }
function buildRoadSegs(pts) { const segs = []; W.roads.forEach((r, ri) => { const p = pts[ri]; for (let k = 0; k + 1 < p.length; k++) segs.push({ kind: 'road', idx: ri, k, x1: p[k][0], y1: p[k][1], x2: p[k + 1][0], y2: p[k + 1][1], half: HALF[CLS[r[1]]], cls: CLS[r[1]], bridge: !!r[2], name: nm(r[0]) }); }); return segs; }
function indexSegs(segs) { const g = new Grid(50); segs.forEach((s, id) => { s.id = id; g.add(id, [Math.min(s.x1, s.x2) - s.half, Math.min(s.y1, s.y2) - s.half, Math.max(s.x1, s.x2) + s.half, Math.max(s.y1, s.y2) + s.half]); }); return g; }
function otherRoadsNear(segs, grid, pt, ri, r) { const out = []; for (const id of grid.query([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r])) { const s = segs[id]; if (s.idx === ri) continue; const [d, t, qx, qy] = ptSeg(pt[0], pt[1], s.x1, s.y1, s.x2, s.y2); if (d <= r) out.push({ s, d, t, q: [qx, qy] }); } return out.sort((a, b) => a.d - b.d); }

// 1a. road ends that stop short of the road they meet
const GAP_TARGET = new Map(); // "ri:v" -> the road it was snapped onto
{
  const segs = buildRoadSegs(roadPts); const grid = indexSegs(segs);
  W.roads.forEach((r, ri) => {
    const p = roadPts[ri]; if (p.length < 2) return; const isBr = !!r[2];
    for (const v of [0, p.length - 1]) {
      const ownHalf = HALF[CLS[r[1]]], wide = ['trunk', 'primary', 'secondary', 'motorway'].includes(CLS[r[1]]);
      const pt = p[v]; const cands = otherRoadsNear(segs, grid, pt, ri, 17).filter(c => c.d <= Math.max(4, c.s.half + 1, wide ? ownHalf + c.s.half - 1 : 0)); if (!cands.length || cands[0].d < 0.3) continue;
      const nb = v === 0 ? p[1] : p[p.length - 2]; let pick = null, over = null;
      for (const c of cands) {
        const op = roadPts[c.s.idx]; const nearOtherEnd = [op[0], op[op.length - 1]].some(q => dist(q, pt) <= 4.5);
        if ((isBr || c.s.bridge) && !nearOtherEnd) continue; // a bridge only joins roads at its own ends, never one it passes over
        if (segsCross(pt, nb, [c.s.x1, c.s.y1], [c.s.x2, c.s.y2])) { // overshoot: the end pokes past the road it meets
          const a = [c.s.x1, c.s.y1], b = [c.s.x2, c.s.y2]; const d1 = cross(a[0], a[1], b[0], b[1], pt[0], pt[1]), d2 = cross(a[0], a[1], b[0], b[1], nb[0], nb[1]); const t = d1 / (d1 - d2);
          const x = [pt[0] + (nb[0] - pt[0]) * t, pt[1] + (nb[1] - pt[1]) * t]; if (dist(x, pt) <= Math.max(4, c.s.half + 1)) { pick = c; over = x; } break;
        }
        pick = c; break;
      }
      if (!pick) continue;
      const op = roadPts[pick.s.idx]; let to = over || pick.q, onto = over ? 'the point where it crosses it (it overshot)' : 'its centerline';
      for (let k = 0; k < op.length; k++) if (dist(op[k], to) <= 1.5 && dist(op[k], pt) <= Math.max(4.5, pick.s.half + 1.5)) { to = op[k]; onto = k === 0 || k === op.length - 1 ? 'its end point' : `its vertex ${k}`; break; }
      if (p.slice(0, -1).length && polyLen(v === 0 ? [to, ...p.slice(1)] : [...p.slice(0, -1), to]) < 1) continue; // would collapse the road to nothing
      const gap = over ? dist(over, pt) : pick.d; GAP_TARGET.set(ri + ':' + v, pick.s.idx);
      snapVertex(ri, v, to, `road-gap: ${over ? `ran ${fmt(gap)} m past` : `ended ${fmt(gap)} m short of`} road ${pick.s.idx} (${roadName(pick.s.idx)}); snapped to ${onto}`);
      issue('road-gap', gap > 1.5 ? 'medium' : 'low', pt, { road: ri, road_name: roadName(ri), vertex: v, other_road: pick.s.idx, other_name: roadName(pick.s.idx), gap_m: r2(gap), overshoot: !!over }, `Road ${ri} (${roadName(ri)}) ${over ? `runs ${fmt(gap)} m past` : `ends ${fmt(gap)} m short of`} road ${pick.s.idx} (${roadName(pick.s.idx)}) without a shared point. Snapped its end to ${onto}.`, 'fixed', 'snap');
    }
  });
}
// 1b. dead-end driveways and lanes (service, track) that run into or through a building: stop them at the wall
{
  const segs = buildRoadSegs(roadFix); const grid = indexSegs(segs);
  W.roads.forEach((r, ri) => {
    const cls = CLS[r[1]]; if (r[2] || (cls !== 'service' && cls !== 'track')) return; const half = HALF[cls];
    const p = roadFix[ri]; if (p.length < 2) return; const L = polyLen(p);
    const j0 = otherRoadsNear(segs, grid, p[0], ri, 0.3).length > 0, j1 = otherRoadsNear(segs, grid, p[p.length - 1], ri, 0.3).length > 0;
    if (j0 === j1) return; // through roads, and loose pieces with no joined end
    const seq = j0 ? p.map((q, k) => k) : p.map((q, k) => p.length - 1 - k); // from the joined end to the dead end
    const cum = [0]; for (let k = 1; k < seq.length; k++) cum.push(cum[k - 1] + dist(p[seq[k - 1]], p[seq[k]]));
    const H = new Set(); // buildings the last 60 m of the road runs into
    for (let k = 0; k + 1 < seq.length; k++) { if (cum[k + 1] < L - 60) continue; const a = p[seq[k]], b = p[seq[k + 1]]; for (const j of BG.query(bboxOf([a, b], half + 1))) if (cur[j] && polySegDist(cur[j], a[0], a[1], b[0], b[1]) < half - PEN_TOL) H.add(j); }
    if (!H.size) return; const hb = [...H];
    let stop = null;
    for (let k = 0; k + 1 < seq.length && !stop; k++) { const a = p[seq[k]], b = p[seq[k + 1]]; const sl = cum[k + 1] - cum[k]; for (let t = 0; t <= sl; t += 0.25) { const q = [a[0] + (b[0] - a[0]) * t / Math.max(sl, 1e-9), a[1] + (b[1] - a[1]) * t / Math.max(sl, 1e-9)]; if (hb.some(j => ptPolyDist(cur[j], q[0], q[1]) < half + 0.3)) { stop = { s: Math.max(0, cum[k] + t - 0.25), k }; break; } } }
    const dead = j0 ? p.length - 1 : 0; const pt = p[dead];
    const what = `${cls} road ${ri} (${roadName(ri)}) runs ${hb.some(j => ptInPoly(cur[j], pt[0], pt[1])) ? 'into' : 'through'} ${hb.map(kindLabel).join(', ')} and ends there`;
    const deadNear = hb.some(j => ptPolyDist(cur[j], pt[0], pt[1]) <= 30); // the road ends at (or just past) the building
    if (!stop || stop.s < 3 || L - stop.s > (deadNear ? 80 : 30)) { issue('road-into-building', 'medium', pt, { road: ri, road_name: roadName(ri), vertex: dead, buildings: hb }, `The ${what}. Stopping it at the wall would leave almost nothing of it; left for the author.`); return; }
    const sp = (() => { let k = 1; while (k < cum.length - 1 && cum[k] < stop.s) k++; const a = p[seq[k - 1]], b = p[seq[k]]; const t = (stop.s - cum[k - 1]) / Math.max(cum[k] - cum[k - 1], 1e-9); return { q: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], k }; })();
    for (let k = sp.k; k < seq.length; k++) snapVertex(ri, seq[k], sp.q, `road-into-building: ran into #${hb.join(', #')}; cut back ${fmt(L - stop.s)} m to stop at the wall`);
    issue('road-into-building', 'medium', pt, { road: ri, road_name: roadName(ri), vertex: dead, buildings: hb, cut_back_m: r2(L - stop.s) }, `The ${what}. Cut it back ${fmt(L - stop.s)} m so it stops at the wall.`, 'fixed', 'snap');
  });
}

// 1c. two snapped ends can chase each other; re-seat every snapped end on the current line of the road it joins
for (let pass = 0; pass < 4; pass++) {
  let moved = 0;
  for (const [key, tri] of GAP_TARGET) {
    const [ri, v] = key.split(':').map(Number); const q = roadFix[ri][v]; const tp = roadFix[tri]; let best = null;
    for (let k = 0; k + 1 < tp.length; k++) { const [d, , qx, qy] = ptSeg(q[0], q[1], tp[k][0], tp[k][1], tp[k + 1][0], tp[k + 1][1]); if (!best || d < best.d) best = { d, q: [qx, qy] }; }
    for (const e of [tp[0], tp[tp.length - 1]]) if (dist(e, q) < 1.5 && (!best || dist(e, q) <= best.d + 1.5)) best = { d: dist(e, q), q: e.slice() };
    if (best && best.d > 0.01) { const e = FIX.road_snaps.find(x => x.road === ri && x.vertex === v); e.to = P2(best.q); roadFix[ri][v] = best.q.slice(); moved++; }
  }
  if (!moved) break;
}

// ------------------------------------------------------------------ all linear features, after the road fixes
const SEG = buildRoadSegs(roadFix);
W.creeks.forEach((c, ci) => { const p = ptsOf(c); for (let k = 0; k + 1 < p.length; k++) SEG.push({ kind: 'creek', idx: ci, k, x1: p[k][0], y1: p[k][1], x2: p[k + 1][0], y2: p[k + 1][1], half: CREEK_HALF }); });
W.rail.forEach((r, ri) => { const p = ptsOf(r[1]); for (let k = 0; k + 1 < p.length; k++) SEG.push({ kind: 'rail', idx: ri, k, x1: p[k][0], y1: p[k][1], x2: p[k + 1][0], y2: p[k + 1][1], half: r[0] ? YARD_HALF : RAIL_HALF, yard: !!r[0] }); });
W.piers.forEach((f, pi) => { const p = ptsOf(f); const h = polyLen(p) > 500 ? BOARDWALK_HALF : PIER_HALF; for (let k = 0; k + 1 < p.length; k++) SEG.push({ kind: 'pier', idx: pi, k, x1: p[k][0], y1: p[k][1], x2: p[k + 1][0], y2: p[k + 1][1], half: h }); });
const SG = indexSegs(SEG);
const BLOCKS = s => (s.kind === 'road' ? (!s.bridge && s.cls !== 'path') : true); // what a building must stay off
const featName = s => s.kind === 'road' ? `road ${s.idx} (${s.name ? s.name + ', ' + s.cls : 'unnamed ' + s.cls})` : s.kind === 'creek' ? `creek ${s.idx}` : s.kind === 'rail' ? `${s.yard ? 'yard track' : 'the rail line'} ${s.idx}` : `pier ${s.idx}`;
function linHits(p, filter = BLOCKS, tol = PEN_TOL) {
  const out = []; for (const id of SG.query(bboxOf(p, 1))) { const s = SEG[id]; if (!filter(s)) continue; const d = polySegDist(p, s.x1, s.y1, s.x2, s.y2); const pen = s.half - d; if (pen > tol) out.push({ s, d, pen }); }
  return out.sort((a, b) => b.pen - a.pen);
}
function onSurfaceFrac(p, filter, n = 10) {
  const segs = [...SG.query(bboxOf(p, 1))].map(id => SEG[id]).filter(filter); if (!segs.length) return 0;
  const S = samples(p, n); let k = 0; for (const q of S) if (segs.some(s => ptSeg(q[0], q[1], s.x1, s.y1, s.x2, s.y2)[0] < s.half)) k++; return k / S.length;
}
function bldHits(p, self, minA = OVERLAP_NEW) { const out = []; for (const j of BG.query(bboxOf(p))) { if (j === self || !cur[j]) continue; const a = interArea(p, cur[j]); if (a > minA) out.push({ j, a }); } return out; }
function cleanCheck(p, i, opts = {}) {
  if (linHits(p, BLOCKS, 0).length) return { ok: false, why: 'it would touch a road, creek, rail line or pier' };
  if (bldHits(p, i).length) return { ok: false, why: 'it would overlap a neighbor' };
  if (!opts.waterOk && LAND.frac(p, 4) < 0.99) return { ok: false, why: 'a corner would be in the water' };
  if (!opts.marshOk && MARSH.frac(p, 4) > 0.01) return { ok: false, why: 'a corner would be in the marsh' };
  return { ok: true };
}
function linPush(p, s, margin = MARGIN) { // move p off segment s along its normal, toward the building's side
  const c = centroid(p); const [, , qx, qy] = ptSeg(c[0], c[1], s.x1, s.y1, s.x2, s.y2);
  let nx = c[0] - qx, ny = c[1] - qy, L = Math.hypot(nx, ny); if (L < 1e-6) { nx = -(s.y2 - s.y1); ny = s.x2 - s.x1; L = Math.hypot(nx, ny); } nx /= L; ny /= L;
  let mn = Infinity; for (const v of p) mn = Math.min(mn, (v[0] - qx) * nx + (v[1] - qy) * ny);
  const need = s.half + margin - mn; return need > 0 ? [nx * need, ny * need] : [0, 0];
}
function solveShift(p0, i, maxShift, opts = {}) { // relaxation: add up the pushes until the footprint is clean
  let v = [0, 0];
  for (let it = 0; it < 16; it++) {
    const p = translate(p0, v); const lh = linHits(p, BLOCKS, 0); const bh = bldHits(p, i);
    if (!lh.length && !bh.length) { const ck = cleanCheck(p, i, opts); return ck.ok && Math.hypot(v[0], v[1]) <= maxShift + 1e-9 ? { p, v, d: Math.hypot(v[0], v[1]) } : null; }
    let dx = 0, dy = 0;
    for (const h of lh) { const u = linPush(p, h.s); dx += u[0]; dy += u[1]; }
    for (const h of bh) { const m = satMTV(cur[h.j], p); if (m) { dx += m.axis[0] * (m.depth + 0.3); dy += m.axis[1] * (m.depth + 0.3); } }
    if (Math.hypot(dx, dy) < 1e-6) return null; v = [v[0] + dx, v[1] + dy]; if (Math.hypot(v[0], v[1]) > maxShift + 1e-9) return null;
  }
  return null;
}
function solveSlide(p0, i, s, maxShift, opts = {}) { // straight away from one feature, in 0.5 m steps
  const u = linPush(p0, s); const L = Math.hypot(u[0], u[1]); if (L < 1e-6) return null; const n = [u[0] / L, u[1] / L];
  for (let m = L; m <= maxShift + 1e-9; m += 0.5) { const p = translate(p0, [n[0] * m, n[1] * m]); if (cleanCheck(p, i, opts).ok) return { p, v: [n[0] * m, n[1] * m], d: m }; }
  return null;
}
function solveTrim(p0, i, minKeep, maxCut, opts = {}) { // greedy: cut back whichever face most reduces the intrusion, until clean
  const A0 = areaOf(p0); const e = [[p0[1][0] - p0[0][0], p0[1][1] - p0[0][1]], [p0[3][0] - p0[0][0], p0[3][1] - p0[0][1]]]; const len = e.map(v => Math.hypot(v[0], v[1])); const u = e.map((v, k) => [v[0] / len[k], v[1] / len[k]]);
  const cuts = [0, 0, 0, 0]; // axis0 at p0 side, axis0 far side, axis1 at p0 side, axis1 far side
  const make = c => { const a0 = c[0], a1 = len[0] - c[1], b0 = c[2], b1 = len[1] - c[3]; const at = (a, b) => [p0[0][0] + u[0][0] * a + u[1][0] * b, p0[0][1] + u[0][1] * a + u[1][1] * b]; return [at(a0, b0), at(a1, b0), at(a1, b1), at(a0, b1)]; };
  const pen = p => linHits(p, BLOCKS, 0).reduce((t, h) => t + h.pen + 0.01, 0);
  let cur0 = pen(p0);
  for (let it = 0; it < 400 && cur0 > 0; it++) {
    let best = null;
    for (let f = 0; f < 4; f++) { const c = cuts.slice(); c[f] += 0.5; const ax = f < 2 ? 0 : 1; if (len[ax] - c[ax * 2] - c[ax * 2 + 1] < minKeep * len[ax]) continue; const p = make(c); if (1 - areaOf(p) / A0 > maxCut) continue; const v = pen(p); if (!best || v < best.v) best = { f, v, c }; }
    if (!best || best.v >= cur0 - 1e-9) { // no single face helps: try cutting deeper on each face in one go
      let jump = null; for (let f = 0; f < 4 && !jump; f++) for (let d = 1; d <= 30; d += 0.5) { const c = cuts.slice(); c[f] += d; const ax = f < 2 ? 0 : 1; if (len[ax] - c[ax * 2] - c[ax * 2 + 1] < minKeep * len[ax]) break; const p = make(c); if (1 - areaOf(p) / A0 > maxCut) break; const v = pen(p); if (v < cur0 - 1e-9) { jump = { c, v }; break; } }
      if (!jump) return null; cuts.splice(0, 4, ...jump.c); cur0 = jump.v; continue;
    }
    cuts.splice(0, 4, ...best.c); cur0 = best.v;
  }
  const p = make(cuts); const keep = areaOf(p) / A0; const cut = Math.max(...cuts);
  if (cleanCheck(p, i, opts).ok) return { p, cut, keep, cuts };
  if (opts.nudge) { const r = solveShift(p, i, 4, opts); if (r) return { p: r.p, cut, keep, cuts, nudge: r.d }; }
  return null;
}
function splitRow(p0, i, s) { // keep both ends of a row that a road crosses in the middle
  const e = sides(p0); const ax = e[0] >= e[1] ? 0 : 1; // long axis
  const A = ax === 0 ? [p0[0], p0[1], p0[2], p0[3]] : [p0[1], p0[2], p0[3], p0[0]]; // A[0]->A[1] is the long side
  const Lr = dist(A[0], A[1]); const u = [(A[1][0] - A[0][0]) / Lr, (A[1][1] - A[0][1]) / Lr];
  const piece = (t0, t1) => [[A[0][0] + u[0] * t0, A[0][1] + u[1] * t0], [A[0][0] + u[0] * t1, A[0][1] + u[1] * t1], [A[3][0] + u[0] * t1, A[3][1] + u[1] * t1], [A[3][0] + u[0] * t0, A[3][1] + u[1] * t0]];
  const restore = q => ax === 0 ? q : [q[3], q[0], q[1], q[2]]; // same vertex order as the original
  let a = null, b = null;
  for (let t = Lr; t >= 0.3 * Lr; t -= 0.25) { const q = piece(0, t); if (!linHits(q, x => x.idx === s.idx && x.kind === s.kind, 0).length) { a = t; break; } }
  for (let t = 0; t <= 0.7 * Lr; t += 0.25) { const q = piece(t, Lr); if (!linHits(q, x => x.idx === s.idx && x.kind === s.kind, 0).length) { b = t; break; } }
  if (a == null || b == null || a > b || a < 8 || Lr - b < 8) return null;
  const pa = restore(piece(0, a)), pb = restore(piece(b, Lr));
  if (!cleanCheck(pa, i).ok || !cleanCheck(pb, i).ok || interArea(pa, pb) > 0) return null;
  return { a: pa, b: pb, la: a, lb: Lr - b };
}
function solveShrink(p0, i, s, minKeep, opts = {}) { // cut back the face that looks at the feature (opts.maxCut: share of that side; opts.nudge: allow a <= 4 m nudge after)
  const c = centroid(p0); const [, , qx, qy] = ptSeg(c[0], c[1], s.x1, s.y1, s.x2, s.y2); let n = [c[0] - qx, c[1] - qy]; const L = Math.hypot(n[0], n[1]) || 1; n = [n[0] / L, n[1] / L];
  const ax = [[p0[1][0] - p0[0][0], p0[1][1] - p0[0][1]], [p0[3][0] - p0[0][0], p0[3][1] - p0[0][1]]].map(a => { const l = Math.hypot(a[0], a[1]); return { u: [a[0] / l, a[1] / l], len: l }; });
  const order = Math.abs(ax[0].u[0] * n[0] + ax[0].u[1] * n[1]) >= Math.abs(ax[1].u[0] * n[0] + ax[1].u[1] * n[1]) ? [ax[0], ax[1]] : [ax[1], ax[0]];
  for (const A of order) {
    const sgn = (A.u[0] * n[0] + A.u[1] * n[1]) >= 0 ? 1 : -1;
    const proj = p0.map(v => ((v[0] - c[0]) * A.u[0] + (v[1] - c[1]) * A.u[1]) * sgn); const mn = Math.min(...proj);
    const lim = Math.min(1 - minKeep, opts.maxCut ?? 1) * A.len;
    for (let cut = 0.25; cut <= lim + 1e-9; cut += 0.25) {
      const p = p0.map((v, k) => (proj[k] < mn + 0.05 * A.len ? [v[0] + A.u[0] * sgn * cut, v[1] + A.u[1] * sgn * cut] : v));
      if (linHits(p, x => x === s, 0).length) continue; // still on the feature it is cut back from
      if (cleanCheck(p, i, opts).ok) return { p, cut, keep: (A.len - cut) / A.len };
      if (opts.nudge) { const r = solveShift(p, i, 4, opts); if (r) return { p: r.p, cut, keep: (A.len - cut) / A.len, nudge: r.d }; }
    }
  }
  return null;
}

// =============================================================================================
// 2. Buildings in water or marsh
// =============================================================================================
const PIER_BUILDINGS = new Set();
const nearSeg = (pt, kind, r) => [...SG.query([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r])].map(id => SEG[id]).filter(s => s.kind === kind && ptSeg(pt[0], pt[1], s.x1, s.y1, s.x2, s.y2)[0] <= r);
for (let i = 0; i < B.length; i++) {
  const p = cur[i]; const c = centroid(p); const wf = 1 - LAND.frac(p, 6); const cw = isWater(c[0], c[1]);
  const onPier = nearSeg(c, 'pier', Math.max(...p.map(v => dist(v, c))) + 3).length > 0;
  if (cw || wf > 0.25) {
    const why = `${cw ? 'its center is' : `${Math.round(wf * 100)}% of it is`} over open water`;
    if (onPier || B[i].kind === 'deck') { PIER_BUILDINGS.add(i); issue('building-in-water', 'low', c, bref(i), `${kindLabel(i)}: ${why}, but it stands on a pier, so it stays as a pier building.`); }
    else if (isNamed(i)) issue('building-in-water', 'high', c, bref(i), `${kindLabel(i)}: ${why}. It is ${namedWhy(i)}, so it is not removed; the author should decide.`);
    else { doRemove(i); issue('building-in-water', 'high', c, bref(i), `${kindLabel(i)}: ${why}. Removed.`, 'fixed', 'remove'); }
    continue;
  }
  const mf = MARSH.frac(p, 6); const cm = MARSH.has(c[0], c[1]);
  if (cm || mf > 0.25) {
    const why = `${cm ? 'its center is' : `${Math.round(mf * 100)}% of it is`} in the marsh`;
    if (isNamed(i)) issue('building-in-marsh', 'high', c, bref(i), `${kindLabel(i)}: ${why}. It is ${namedWhy(i)}, so it is not removed; the author should decide.`);
    else if (onPier) { PIER_BUILDINGS.add(i); issue('building-in-marsh', 'low', c, bref(i), `${kindLabel(i)}: ${why}, on a boardwalk; kept.`); }
    else { doRemove(i); issue('building-in-marsh', 'high', c, bref(i), `${kindLabel(i)}: ${why}. Removed.`, 'fixed', 'remove'); }
  }
}

// =============================================================================================
// 3. Buildings on roads, rail, creeks and piers
//    ladder: nudge <= 4 m; remove if > 40% on it; trim (keep >= 70%); move further (<= 10 m, or a quarter
//    of the long side for big buildings); cut end units off multi-unit rows (keep >= 50%); remove a stray; flag.
//    Hero homes are only flagged; named places are never removed.
// =============================================================================================
const placeById0 = new Map(G.places.map(p => [p.id, p])); const rehomed = new Map();
const KIND_FOR = { school: ['school', 'gym'], civic: ['civic', 'office'], church: ['church'], lodging: ['hotel', 'motel'], shop: ['retail', 'shop'], food: ['retail', 'shop'], health: ['hospital', 'office', 'civic'], industry: ['industrial'], landmark: ['civic', 'office', 'tower'], marina: ['clubhouse', 'civic', 'shop'], canon: ['civic', 'shop', 'retail'], homepoi: ['house', 'mobile', 'duplex'] };
const spurOk = (i, s) => s.kind === 'rail' && s.yard && B[i].kind === 'industrial'; // a yard track running up to a warehouse is a rail spur, not a stray
const LIN_TYPES = { road: 'building-on-road', rail: 'building-on-rail', creek: 'building-on-creek', pier: 'building-on-pier' };
const ladderStats = {};
for (const kind of ['road', 'rail', 'creek', 'pier']) {
  const type = LIN_TYPES[kind]; const filt = s => s.kind === kind && BLOCKS(s);
  for (let i = 0; i < B.length; i++) {
    const p = cur[i]; if (!p || (kind === 'pier' && PIER_BUILDINGS.has(i))) continue;
    const hits = linHits(p, filt).filter(h => !spurOk(i, h.s)); if (!hits.length) continue;
    const h = hits[0]; const c = centroid(p); const frac = onSurfaceFrac(p, filt);
    const ref = { ...bref(i), [kind]: h.s.idx, depth_m: r2(h.pen), share: r2(frac) }; if (h.s.name) ref.road_name = h.s.name;
    const sev = frac > 0.1 || h.pen > 2 ? 'high' : h.pen > 0.75 ? 'medium' : 'low';
    const what = `${kindLabel(i)} reaches ${fmt(h.pen)} m into ${featName(h.s)}${hits.length > 1 ? ` (${hits.length} segments)` : ''}; ${Math.round(frac * 100)}% of its footprint is on it`;
    const note = NAMED.has(i) ? ` It carries ${NAMED.get(i).join(', ')}; the point moves with it.` : '';
    const done = (how, fix, d) => { ladderStats[type + ':' + how] = (ladderStats[type + ':' + how] || 0) + 1; issue(type, sev, c, ref, `${what}. ${d}${fix === 'replace' ? note : ''}`, 'fixed', fix); };
    if (isHero(i)) { issue(type, sev, c, ref, `${what}. It is ${namedWhy(i)}, which QA never changes; the author should decide.`); continue; }
    const long = Math.max(...sides(p));
    if (DEBUG.has(i)) console.log('DEBUG', i, B[i].kind, 'hits', hits.map(h => [h.s.kind, h.s.idx, h.s.name, r2(h.pen)]), 'frac', r2(frac), 'trim70', !!solveTrim(p, i, 0.7, 0.3), 'trim50', !!solveTrim(p, i, 0.5, 0.5, { nudge: true }), 'trim50raw', (() => { const r = solveTrim(p, i, 0.5, 0.5); return r ? 'ok' : 'null'; })());
    let r = solveShift(p, i, 4) || solveSlide(p, i, h.s, 4);
    if (r) { doReplace(i, r.p, `${type}: shifted ${fmt(r.d)} m off ${featName(h.s)}`, { t: 'shift', v: r.v }); done('shift', 'replace', `Shifted ${fmt(r.d)} m away from it.`); continue; }
    if (frac > 0.4 && !isNamed(i)) { doRemove(i); done('remove-mostly', 'remove', 'It stood mostly on it, so it was removed.'); continue; }
    const maxCut = Math.max(0.15, 3 * frac + 0.05); // never cut away far more than the part that is on it
    let k = solveShrink(p, i, h.s, 0.7, { maxCut }) || solveTrim(p, i, 0.7, Math.min(0.3, maxCut));
    if (k) { doReplace(i, k.p, `${type}: trimmed ${fmt(k.cut)} m off the side facing ${featName(h.s)}`, { t: 'trim' }); done('trim', 'replace', `Trimmed ${fmt(k.cut)} m off the side${k.cuts && k.cuts.filter(x => x > 0).length > 1 ? 's' : ''} facing it (keeps ${Math.round(k.keep * 100)}% of ${k.cuts ? 'its area' : 'that side'}).`); continue; }
    const far = Math.min(25, Math.max(10, long / 4));
    r = solveShift(p, i, far) || solveSlide(p, i, h.s, far);
    if (r) { doReplace(i, r.p, `${type}: moved ${fmt(r.d)} m clear of ${featName(h.s)}`, { t: 'shift', v: r.v }); done('move', 'replace', `Moved ${fmt(r.d)} m to clear it (more than a 4 m nudge, into free ground).`); continue; }
    if (NAMED.has(i) || areaOf(p) >= 3000 || ROWS.has(B[i].kind)) { // a named place, a big building or a row: look for the nearest free ground before cutting it down
      const R = NAMED.has(i) ? Math.max(30, Math.min(150, 1.25 * long)) : areaOf(p) >= 3000 ? Math.max(40, Math.min(60, 0.5 * long)) : Math.min(25, 0.6 * long); let best = null;
      const crossesMain = v => { const a0 = centroid(p), a1 = [a0[0] + v[0], a0[1] + v[1]]; for (const id of SG.query(bboxOf([a0, a1]))) { const g = SEG[id]; if (g.kind === 'road' && ['trunk', 'primary', 'secondary', 'motorway'].includes(g.cls) && segsCross(a0, a1, [g.x1, g.y1], [g.x2, g.y2])) return true; } return false; };
      for (const sameSide of [true, false]) { // stay on the same side of the main roads when possible
        for (let rr = 1; rr <= R && !best; rr += rr < 30 ? 1 : 2) for (let a = 0; a < 36; a++) { const v = [rr * Math.cos(a * Math.PI / 18), rr * Math.sin(a * Math.PI / 18)]; if (sameSide && crossesMain(v)) continue; const q = translate(p, v); if (cleanCheck(q, i).ok) { best = { p: q, v, d: rr, crossed: !sameSide }; break; } }
        if (best) break;
      }
      if (best) { doReplace(i, best.p, `${type}: moved ${fmt(best.d)} m to free ground clear of ${featName(h.s)}`, { t: 'shift', v: best.v }); done('move', 'replace', `Moved ${fmt(best.d)} m to the nearest free ground${hits.length > 1 ? ', clear of every road it touched' : ''}${best.crossed ? ' (across a main road; there was no room on its own side)' : ''}.`); continue; }
    }
    if (ROWS.has(B[i].kind) || NAMED.has(i)) { k = solveShrink(p, i, h.s, 0.5, { maxCut, nudge: true }) || solveTrim(p, i, 0.5, Math.min(0.5, maxCut), { nudge: true }); if (k) { doReplace(i, k.p, `${type}: cut back ${fmt(k.cut)} m clear of ${featName(h.s)}${k.nudge ? ` and nudged ${fmt(k.nudge)} m` : ''}`, { t: 'trim' }); done('trim-row', 'replace', `Cut back ${fmt(k.cut)} m on the side facing it (keeps ${Math.round(k.keep * 100)}% of that side)${k.nudge ? ` and nudged ${fmt(k.nudge)} m` : ''}.`); continue; } }
    const big = areaOf(p) >= 3000;
    if (ROWS.has(B[i].kind) && !isNamed(i) && new Set(hits.map(x => x.s.idx)).size === 1) { // a lane through the middle of a row: split the row in two around it
      const sp = splitRow(p, i, h.s);
      if (sp) { doReplace(i, sp.a, `${type}: split in two around ${featName(h.s)}; this is one half`, { t: 'trim' }); const k2 = addBuilding(B[i].kind, B[i].h, sp.b, null, null, `${type}: the other half of ${B[i].kind} #${i}, split by QA around ${featName(h.s)} (proposed)`, { type: 'split', from: i }); done('split', 'replace', `It runs through the middle, so the row was split in two around it: #${i} keeps ${fmt(sp.la)} m and the other ${fmt(sp.lb)} m becomes added building #${k2}.`); continue; }
    }
    if (!isNamed(i) && !big && (frac >= 0.05 || h.pen >= 1)) { doRemove(i); done('remove-stray', 'remove', 'No nudge, move or trim clears it without a new conflict, so this stray was removed.'); continue; }
    if (NAMED.has(i) && !isHero(i) && frac >= 0.25 && !big) { // a named place on a stray building: re-home the place onto a fitting building nearby
      const pls = NAMED.get(i).filter(id => placeById0.has(id)).map(id => placeById0.get(id));
      const homes = pls.map(pl => [pl, nearestBuilding(pl.at, 100, j => j !== i && !isNamed(j) && ([...(KIND_FOR[pl.cat] || []), 'office', 'retail', 'shop', 'motel'].includes(B[j].kind)) && !linHits(cur[j]).length)]);
      if (pls.length && pls.length === NAMED.get(i).length && homes.every(([, nb]) => nb)) {
        for (const [pl, nb] of homes) { rehomed.set(pl.id, { to: nb.j, from: i }); NAMED.get(i).splice(NAMED.get(i).indexOf(pl.id), 1); markNamed(nb.j, pl.id); }
        if (!NAMED.get(i).length) NAMED.delete(i);
        doRemove(i); done('remove-stray', 'remove', `This stray stood ${Math.round(frac * 100)}% on the road and nothing clears it, so it was removed; ${homes.map(([pl, nb]) => `${pl.name} moves to ${kindLabel(nb.j)}, ${fmt(nb.d)} m away`).join('; ')}.`); continue;
      }
    }
    issue(type, isNamed(i) ? 'high' : sev, c, ref, `${what}. No nudge, move or trim clears it without a new conflict${isNamed(i) ? `; it is ${namedWhy(i)}, so it is not removed` : ''}. Left for the author.`);
  }
}

// =============================================================================================
// 4. Overlapping buildings
// =============================================================================================
{
  const pairs = [];
  for (let i = 0; i < cur.length; i++) { if (!cur[i]) continue; for (const j of BG.query(bboxOf(cur[i]))) { if (j <= i || !cur[j]) continue; const a = interArea(cur[i], cur[j]); if (a > OVERLAP_MIN) pairs.push([i, j, a]); } }
  pairs.sort((x, y) => y[2] - x[2]);
  for (const [i0, j0] of pairs) {
    if (!cur[i0] || !cur[j0]) continue; const a = interArea(cur[i0], cur[j0]); if (a <= OVERLAP_MIN) continue;
    let s = areaOf(cur[i0]) <= areaOf(cur[j0]) ? i0 : j0, l = s === i0 ? j0 : i0;
    if ((isHero(s) || (isNamed(s) && !isNamed(l))) && !isHero(l)) [s, l] = [l, s];
    const As = areaOf(cur[s]), Al = areaOf(cur[l]); const iou = a / (As + Al - a); const c = centroid(clipConvex(ccw(cur[s]), ccw(cur[l])));
    const ref = { building: s, kind: B[s].kind, other: l, other_kind: B[l].kind, overlap_m2: r2(a), iou: r2(iou) }; if (addrStr(s)) ref.addr = addrStr(s); if (addrStr(l)) ref.other_addr = addrStr(l);
    const sev = a > 20 ? 'high' : a > 5 ? 'medium' : 'low'; const what = `${kindLabel(s)} and ${kindLabel(l)} overlap by ${fmt(a)} m2`;
    if (isHero(s)) { issue('building-overlap', sev, c, ref, `${what}. Both are hero homes; left for the author.`); continue; }
    if (iou > 0.7 && !isNamed(s)) { doRemove(s); issue('building-overlap', sev, c, ref, `${what}; they are near-identical duplicates (${Math.round(iou * 100)}% shared). Removed #${s}.`, 'fixed', 'remove'); continue; }
    if (B[s].kind === 'shed' && !isNamed(s)) { doRemove(s); issue('building-overlap', sev, c, ref, `${what}. Removed the shed.`, 'fixed', 'remove'); continue; }
    let r = solveShift(cur[s], s, 3);
    if (r) { doReplace(s, r.p, `building-overlap: shifted ${fmt(r.d)} m clear of #${l}`, { t: 'shift', v: r.v }); issue('building-overlap', sev, c, ref, `${what}. Shifted the smaller one ${fmt(r.d)} m clear.`, 'fixed', 'replace'); continue; }
    const m = satMTV(cur[l], cur[s]); // party walls in a row: shave the overlap off the smaller one
    if (m && m.depth < 2) {
      const cs = centroid(cur[s]); const pv = cur[s].map(v => (v[0] - cs[0]) * m.axis[0] + (v[1] - cs[1]) * m.axis[1]); const mn = Math.min(...pv); const span = Math.max(...pv) - mn; const cut = m.depth + 0.1;
      const p = cur[s].map((v, k) => (pv[k] < mn + 0.05 * span ? [v[0] + m.axis[0] * cut, v[1] + m.axis[1] * cut] : v));
      if ((span - cut) / span >= 0.85 && cleanCheck(p, s).ok) { doReplace(s, p, `building-overlap: shaved ${fmt(cut)} m off the wall shared with #${l}`, { t: 'trim' }); issue('building-overlap', sev, c, ref, `${what}. Shaved ${fmt(cut)} m off the shared wall of the smaller one.`, 'fixed', 'replace'); continue; }
    }
    if (!isHero(l) && !isNamed(l)) { r = solveShift(cur[l], l, 3); if (r) { doReplace(l, r.p, `building-overlap: shifted ${fmt(r.d)} m clear of #${s}`, { t: 'shift', v: r.v }); issue('building-overlap', sev, c, ref, `${what}. Shifted the larger one ${fmt(r.d)} m clear.`, 'fixed', 'replace'); continue; } }
    issue('building-overlap', sev, c, ref, `${what}. No shift up to 3 m or trim clears it; left for the author.`);
  }
}

// =============================================================================================
// 5. Houses that sit 3 to 20 degrees off the street they face
// =============================================================================================
const fixCum = roadFix.map(p => { const c = [0]; for (let k = 1; k < p.length; k++) c.push(c[k - 1] + dist(p[k - 1], p[k])); return c; });
function pointAt(ri, s) { const p = roadFix[ri], c = fixCum[ri]; s = Math.max(0, Math.min(c[c.length - 1], s)); let k = 1; while (k < c.length - 1 && c[k] < s) k++; const L = c[k] - c[k - 1] || 1; const t = (s - c[k - 1]) / L; return [p[k - 1][0] + t * (p[k][0] - p[k - 1][0]), p[k - 1][1] + t * (p[k][1] - p[k - 1][1])]; }
const localBearing = (ri, s, span = 8) => { const a = pointAt(ri, s - span), b = pointAt(ri, s + span); return Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI; };
function nearestOnRoads(pt, r, filter) {
  const best = new Map();
  for (const id of SG.query([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r])) {
    const s = SEG[id]; if (s.kind !== 'road' || !filter(s)) continue; const [d, t, qx, qy] = ptSeg(pt[0], pt[1], s.x1, s.y1, s.x2, s.y2); if (d > r) continue;
    const sAlong = fixCum[s.idx][s.k] + t * (fixCum[s.idx][s.k + 1] - fixCum[s.idx][s.k]); const o = best.get(s.idx); if (!o || d < o.d) best.set(s.idx, { ri: s.idx, d, s: sAlong, seg: s, q: [qx, qy] });
  }
  return [...best.values()].sort((a, b) => a.d - b.d);
}
const alignStats = { checked: 0, aligned: 0, candidates: 0, keptForNeighbors: 0, over20: 0 };
{
  const cand = new Map(); const devAll = new Map();
  for (let i = 0; i < cur.length; i++) {
    const p = cur[i]; if (!p || !RESID.has(B[i].kind)) continue;
    const c = centroid(p); const rs = nearestOnRoads(c, 45, s => !s.bridge && s.cls !== 'path'); if (!rs.length) continue;
    alignStats.checked++;
    const a = addrOf.get(i); const ref = (a && rs.find(r => W.roads[r.ri][0] >= 0 && names[W.roads[r.ri][0]] === a.street)) || rs[0];
    const ba = edgeAngle(p); const devOf = r => angMod90(ba - localBearing(r.ri, r.s)); const dev = devOf(ref); devAll.set(i, dev);
    if (Math.abs(dev) < 3 || rs.filter(r => r.d - r.seg.half < 25).some(r => Math.abs(devOf(r)) < 3)) { alignStats.aligned++; continue; }
    if (Math.abs(dev) > 20) { alignStats.over20++; continue; }
    cand.set(i, { dev, ref, c });
  }
  alignStats.candidates = cand.size;
  for (const [i, o] of cand) {
    if (isHero(i)) continue; const p = cur[i]; const ba = edgeAngle(p);
    // a house that matches the angle of its street-square neighbors was placed that way on purpose (curves, cul-de-sac bulbs)
    const nbs = [...BG.query(bboxOf(p, 30))].filter(j => j !== i && cur[j] && RESID.has(B[j].kind) && dist(centroid(cur[j]), o.c) < 35);
    if (nbs.filter(j => devAll.has(j) && Math.abs(devAll.get(j)) < 3 && Math.abs(angMod90(edgeAngle(cur[j]) - ba)) < 2).length >= 2) { alignStats.keptForNeighbors++; continue; }
    const rname = roadName(o.ref.ri); const iref = { ...bref(i), road: o.ref.ri, road_name: rname, deviation_deg: r2(o.dev) };
    const sev = Math.abs(o.dev) >= 10 ? 'medium' : 'low';
    const rp = rotateAbout(p, o.c, -o.dev * Math.PI / 180);
    const ck = cleanCheck(rp, i, { marshOk: MARSH.frac(p, 4) > 0.01, waterOk: LAND.frac(p, 4) < 0.99 });
    if (ck.ok) { doReplace(i, rp, `misaligned-building: turned ${fmt(-o.dev)} deg to square it to ${rname}`, { t: 'rot', c: o.c, a: -o.dev * Math.PI / 180 }); issue('misaligned-building', sev, o.c, iref, `${kindLabel(i)} sat ${fmt(Math.abs(o.dev))} degrees off ${rname}. Turned it about its center to square it to the street.`, 'fixed', 'replace'); }
    else issue('misaligned-building', sev, o.c, iref, `${kindLabel(i)} sits ${fmt(Math.abs(o.dev))} degrees off ${rname}, but turning it is blocked: ${ck.why}. Left as is.`);
  }
}

// a driveway that could not be cut back may have been cleared by moving or removing the building instead
for (const o of ISSUES) {
  if (o.type !== 'road-into-building' || o.action !== 'flagged') continue; const ri = o.ref.road; const p = roadFix[ri]; const half = HALF[CLS[W.roads[ri][1]]];
  const still = o.ref.buildings.filter(j => cur[j] && p.some((q, k) => k + 1 < p.length && polySegDist(cur[j], q[0], q[1], p[k + 1][0], p[k + 1][1]) < half - PEN_TOL));
  if (still.length) continue; const gone = o.ref.buildings.filter(j => !cur[j]);
  o.action = 'fixed'; o.fix = gone.length === o.ref.buildings.length ? 'remove' : 'replace'; o.detail = o.detail.replace(/ Stopping it at the wall.*$/, ` It runs on past the building, so the road was kept and the building was ${gone.length === o.ref.buildings.length ? 'removed' : 'moved clear of it'} instead (see building-on-road).`);
}

// =============================================================================================
// 6. Other road checks: water crossings, bridges that end over water, dead-end stubs into buildings
// =============================================================================================
const RSEG = SEG.filter(s => s.kind === 'road').map(s => ({ ...s })); const RG = indexSegs(RSEG);
const joined = (ri, pt) => otherRoadsNear(RSEG, RG, pt, ri, 0.3).length > 0;
const EDGE = bboxOf(roadFix.flat());
W.roads.forEach((r, ri) => {
  const p = roadFix[ri]; const name = roadName(ri);
  if (!r[2] && ['trunk', 'primary', 'secondary', 'motorway'].includes(CLS[r[1]])) for (const v of [0, p.length - 1]) { // main roads that stop dead in town
    const pt = p[v]; if (pt[0] < EDGE[0] + 200 || pt[0] > EDGE[2] - 200 || pt[1] < EDGE[1] + 200 || pt[1] > EDGE[3] - 200 || joined(ri, pt)) continue;
    const o = otherRoadsNear(RSEG, RG, pt, ri, 500)[0]; const inB = buildingAt(pt, 2);
    const dest = G.places.find(pl => dist(pl.at, pt) < 250); if (dest && !o) continue; // a road out to one destination (the Coast Guard station) may stop there
    issue('road-dead-end', 'medium', pt, { road: ri, road_name: name, cls: CLS[r[1]], vertex: v, nearest_road: o ? o.s.idx : null, gap_m: o ? r2(o.d) : null }, `${name} (${CLS[r[1]]}, road ${ri}) stops dead${inB ? ` inside ${kindLabel(inB.j)}` : ''}${o ? `, ${fmt(o.d)} m short of road ${o.s.idx} (${roadName(o.s.idx)})` : ''}. A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision.`);
  }
  if (!r[2]) {
    let run = 0, a = null, b = null; const runs = [];
    const flush = () => { if (run > 15) runs.push({ run, a, b }); run = 0; a = null; };
    for (let k = 0; k + 1 < p.length; k++) { const L = dist(p[k], p[k + 1]); const n = Math.max(1, Math.ceil(L / 2)); for (let m = 0; m < n; m++) { const t = (m + 0.5) / n; const q = [p[k][0] + t * (p[k + 1][0] - p[k][0]), p[k][1] + t * (p[k + 1][1] - p[k][1])]; if (isWater(q[0], q[1])) { if (!a) a = q; b = q; run += L / n; } else flush(); } }
    flush();
    for (const w of runs) issue('road-crosses-water', w.run > 60 ? 'high' : 'medium', [(w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2], { road: ri, road_name: name, cls: CLS[r[1]], wet_m: r2(w.run) }, `Road ${ri} (${name}, ${CLS[r[1]]}) runs ${fmt(w.run)} m over open water but is not marked as a bridge. QA does not move roads; it needs a bridge flag or a new line.`);
  } else {
    for (const v of [0, p.length - 1]) { const pt = p[v]; if (isWater(pt[0], pt[1]) && !joined(ri, pt)) issue('bridge-dead-end', 'high', pt, { road: ri, road_name: name, cls: CLS[r[1]], vertex: v }, `Bridge road ${ri} (${name}, ${CLS[r[1]]}) ends over open water and joins nothing there: a bridge to nowhere. QA does not delete roads; it should be removed or carried to the far bank.`); }
  }
  const cls = CLS[r[1]]; if (cls !== 'service' && cls !== 'track') return; const L = polyLen(p); if (L >= 12) return;
  if (joined(ri, p[0]) && joined(ri, p[p.length - 1])) return;
  const touch = new Set(); for (let k = 0; k + 1 < p.length; k++) for (const j of BG.query(bboxOf([p[k], p[k + 1]], HALF[cls] + 1))) if (cur[j] && polySegDist(cur[j], p[k][0], p[k][1], p[k + 1][0], p[k + 1][1]) < HALF[cls]) touch.add(j);
  if (!touch.size) return;
  issue('dangling-stub', 'low', centroid(p), { road: ri, cls, length_m: r2(L), buildings: [...touch] }, `A ${fmt(L)} m dead-end ${cls} stub (road ${ri}) runs into ${[...touch].map(kindLabel).join(', ')}. Probably a leftover driveway; consider deleting it.`);
});

// =============================================================================================
// 7. Places, homes and addresses
// =============================================================================================
const placeById = new Map(G.places.map(p => [p.id, p]));
const movedPlace = new Map(), movedPerson = new Map();
function movePlace(id, to, why) { if (movedPlace.has(id)) return false; if (dist(to, (placeById.get(id) || W.pois.find(p => p.id === id)).at) < 0.5) { movedPlace.set(id, to); return true; } const pl = placeById.get(id) || W.pois.find(p => p.id === id); movedPlace.set(id, to); FIX.move_places.push({ id, at: P2(to), was: P2(pl.at), why }); return true; }
function movePerson(pe, to, why) { if (movedPerson.has(pe.name)) return false; movedPerson.set(pe.name, to); FIX.move_people.push({ name: pe.name, at: P2(to), was: P2(pe.home.at), why }); return true; }
const NON_BUILDING = new Set(['courthouse-square', 'city-park', 'riverside-park', 'waterfront-park', 'city-cemetery', 'black-cemetery', 'sports-complex', 'marsh-park', 'acres-park', 'pinecrest-park', 'boat-ramp-n', 'boat-ramp-s', 'town-beach', 'rec-fields', 'pier-bar', 'country-club', 'quarry', 'nine-acres', 'rosewood-site', 'old-mill', 'working-docks', 'marina', 'riverside-mhc', 'airport', 'college']);
const WATER_OK = new Set(['pier-bar', 'boat-ramp-n', 'boat-ramp-s', 'working-docks', 'marina', 'harbor-master', 'yacht-club', 'fish-houses', 'crab-house', 'langfords', 'town-beach', 'coast-guard', 'waterfront-park']);
const isBuildingType = pl => !NON_BUILDING.has(pl.id) && pl.cat !== 'park';
const BIG = /Lowe|Home Depot|Walmart|Supercenter|movie theater|megachurch|distribution center/i; // one big building, not a strip
function kindMatched(pl, pt, r = pl.cat === 'school' ? 250 : 120) {
  for (const k of KIND_FOR[pl.cat] || []) { const nb = nearestBuilding(pt, r, j => B[j].kind === k && (!BIG.test(pl.name) || areaOf(cur[j]) >= 1500)); if (nb) return nb; }
  return null;
}
const onRoadSurface = pt => { for (const id of SG.query([pt[0] - 10, pt[1] - 10, pt[0] + 10, pt[1] + 10])) { const s = SEG[id]; if (s.kind === 'road' && s.cls !== 'path' && ptSeg(pt[0], pt[1], s.x1, s.y1, s.x2, s.y2)[0] < s.half) return s; } return null; };
const addrTargets = (a, pt) => (byAddr.get(a.key) || []).filter(j => cur[j]).map(j => ({ j, d: dist(centroid(cur[j]), pt) })).sort((x, y) => x.d - y.d);

// street chains and the town's numbering rule (number ~ a + b x meters from the street's end nearest Courthouse Square; odd on one side)
const chainCache = new Map();
function streetChain(name) {
  if (chainCache.has(name)) return chainCache.get(name);
  const pieces = W.roads.map((r, ri) => ri).filter(ri => W.roads[ri][0] >= 0 && names[W.roads[ri][0]] === name);
  if (!pieces.length) { chainCache.set(name, null); return null; }
  const left = pieces.map(ri => roadFix[ri].slice());
  let bi = 0, bend = 0, bd = Infinity; left.forEach((p, k) => { [0, p.length - 1].forEach(e => { const d = Math.hypot(...p[e]); if (d < bd) { bd = d; bi = k; bend = e; } }); });
  let chain = bend === 0 ? left[bi] : left[bi].slice().reverse(); left.splice(bi, 1);
  while (left.length) { const tail = chain[chain.length - 1]; let best = null; left.forEach((p, k) => { const d0 = dist(p[0], tail), d1 = dist(p[p.length - 1], tail); if (!best || Math.min(d0, d1) < best.d) best = { k, d: Math.min(d0, d1), rev: d1 < d0 }; }); if (best.d > 60) break; const p = best.rev ? left[best.k].slice().reverse() : left[best.k]; chain = chain.concat(dist(p[0], tail) < 0.5 ? p.slice(1) : p); left.splice(best.k, 1); }
  const cum = [0]; for (let k = 1; k < chain.length; k++) cum.push(cum[k - 1] + dist(chain[k - 1], chain[k]));
  const out = { name, pts: chain, cum, len: cum[cum.length - 1], half: HALF[CLS[W.roads[pieces[0]][1]]] }; chainCache.set(name, out); return out;
}
function chainProject(ch, pt) { let best = null; for (let k = 0; k + 1 < ch.pts.length; k++) { const a = ch.pts[k], b = ch.pts[k + 1]; const [d, t, qx, qy] = ptSeg(pt[0], pt[1], a[0], a[1], b[0], b[1]); if (!best || d < best.d) best = { d, s: ch.cum[k] + t * (ch.cum[k + 1] - ch.cum[k]), q: [qx, qy], side: cross(a[0], a[1], b[0], b[1], pt[0], pt[1]) > 0 ? 'left' : 'right' }; } return best; }
function chainPoint(ch, s) { s = Math.max(0, Math.min(ch.len, s)); let k = 1; while (k < ch.cum.length - 1 && ch.cum[k] < s) k++; const L = ch.cum[k] - ch.cum[k - 1] || 1, t = (s - ch.cum[k - 1]) / L; const a = ch.pts[k - 1], b = ch.pts[k]; return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]; }
function chainTangent(ch, s, span = 10) { const a = chainPoint(ch, s - span), b = chainPoint(ch, s + span); const L = dist(a, b) || 1; return [(b[0] - a[0]) / L, (b[1] - a[1]) / L]; }
const MODEL = (() => {
  const fits = []; const sd = { oddLeft: 0, oddRight: 0 };
  for (const [st, list] of streetAddrs) { if (list.length < 20) continue; const ch = streetChain(st); if (!ch) continue; const xs = [], ys = [];
    for (const [i, n] of list) { const pr = chainProject(ch, centroid(B[i].pts0)); xs.push(pr.s); ys.push(n); if (n % 2 === 1) pr.side === 'left' ? sd.oddLeft++ : sd.oddRight++; }
    const mx = xs.reduce((a, b) => a + b) / xs.length, my = ys.reduce((a, b) => a + b) / ys.length; let sxx = 0, sxy = 0; xs.forEach((x, k) => { sxx += (x - mx) ** 2; sxy += (x - mx) * (ys[k] - my); }); if (sxx > 0) fits.push({ a: my - sxy / sxx * mx, b: sxy / sxx }); }
  return { a: med(fits.map(f => f.a)), b: med(fits.map(f => f.b)), oddSide: sd.oddLeft >= sd.oddRight ? 'left' : 'right', streets: fits.length, oddLeft: sd.oddLeft, oddRight: sd.oddRight };
})();
const kindDims = k => { const ws = [], ds = [], hs = []; B.forEach((b, i) => { if (b.kind !== k || !cur[i] || b.added) return; const s = sides(b.pts0); ws.push(Math.max(...s)); ds.push(Math.min(...s)); hs.push(b.h); }); return { w: med(ws), d: med(ds), h: med(hs) }; };

// a proposed house for a home address with no building: placed by the street numbering, sized and set back like its neighbors
function proposeHouse(addr) {
  const ch = streetChain(addr.street); if (!ch) return { fail: `there is no road named ${addr.street}` };
  const list = (streetAddrs.get(addr.street) || []).map(([i, n]) => ({ n, s: chainProject(ch, centroid(B[i].pts0)).s })).sort((a, b) => a.n - b.n);
  const lo = list.filter(o => o.n <= addr.num).pop(), hi = list.find(o => o.n >= addr.num);
  let target, how;
  if (lo && hi && hi.n !== lo.n) { target = lo.s + (addr.num - lo.n) * (hi.s - lo.s) / (hi.n - lo.n); how = `interpolated between ${lo.n} and ${hi.n} ${addr.street}`; }
  else { target = (addr.num - MODEL.a) / MODEL.b; how = `${addr.street} has no numbered buildings, so the town-wide rule was used: number = ${Math.round(MODEL.a)} + ${MODEL.b.toFixed(3)} x meters from the street's end nearest Courthouse Square, odd numbers on the ${MODEL.oddSide}`; }
  const side = (addr.num % 2 === 1) === (MODEL.oddSide === 'left') ? 'left' : 'right';
  const ref = chainPoint(ch, target); const ws = [], ds = [], sets = [];
  const nearHouses = [...BG.query([ref[0] - 400, ref[1] - 400, ref[0] + 400, ref[1] + 400])].filter(j => cur[j] && B[j].kind === 'house' && addrOf.get(j) && dist(centroid(cur[j]), ref) <= 400).sort((x, y) => dist(centroid(cur[x]), ref) - dist(centroid(cur[y]), ref)).slice(0, 30);
  for (const j of nearHouses) {
    const p = cur[j];
    const sc = streetChain(addrOf.get(j).street); if (!sc) continue; const pr = chainProject(sc, centroid(p)); if (pr.d > 60) continue;
    let mn = Infinity; for (const v of p) mn = Math.min(mn, chainProject(sc, v).d);
    const t = chainTangent(sc, pr.s); const e1 = dist(p[0], p[1]), e2 = dist(p[1], p[2]); const u = [(p[1][0] - p[0][0]) / e1, (p[1][1] - p[0][1]) / e1]; const par = Math.abs(u[0] * t[0] + u[1] * t[1]) > 0.7;
    ws.push(par ? e1 : e2); ds.push(par ? e2 : e1); sets.push(mn - sc.half);
  }
  const Wd = ws.length ? Math.round(med(ws) * 2) / 2 : 14, Dp = ds.length ? Math.round(med(ds) * 2) / 2 : 12, setback = sets.length ? Math.round(med(sets) * 2) / 2 : 8;
  for (let off = 0; off <= 60; off += 1) for (const sg of off ? [1, -1] : [1]) {
    const s = target + sg * off; if (s < 15 || s > ch.len - 15) continue;
    const q = chainPoint(ch, s), t = chainTangent(ch, s); let n = [-t[1], t[0]]; if (side === 'right') n = [-n[0], -n[1]];
    const c = [q[0] + n[0] * (ch.half + setback + Dp / 2), q[1] + n[1] * (ch.half + setback + Dp / 2)];
    const poly = frontRect(c, n, Wd, Dp);
    if (linHits(poly, BLOCKS, -1.5).length) continue;                       // 1.5 m to any road edge
    if (bldHits(frontRect(c, n, Wd + 8, Dp + 8), -1, 0).length) continue;  // 4 m of yard to any building
    if (LAND.frac(poly, 5) < 1 || MARSH.frac(poly, 5) > 0) continue;
    return { poly, c, s, target, how, side, Wd, Dp, setback, ch };
  }
  return { fail: `no free dry lot within 60 m of where ${addr.num} ${addr.street} falls` };
}
// a proposed building for a named place with nothing on the ground: at its point if that is dry and free, else the nearest dry, free spot by a road
function proposeSite(pl, w, d, a, maxRoad = 90, maxRad = 700) {
  const fits = (c) => {
    const rs = nearestOnRoads(c, maxRoad, s => !s.bridge && s.cls !== 'path' && s.cls !== 'track'); if (!rs.length) { fits.dbg.road++; return null; }
    const r = rs.find(x => a && x.seg.name === a.street) || rs[0]; let n = [c[0] - r.q[0], c[1] - r.q[1]]; const L = Math.hypot(n[0], n[1]); if (L < 1) return null; n = [n[0] / L, n[1] / L];
    const p = frontRect(c, n, w, d); if (linHits(p, BLOCKS, -2).length) { fits.dbg.lin++; return null; } if (bldHits(frontRect(c, n, w + 10, d + 10), -1, 0).length) { fits.dbg.bld++; return null; } if (LAND.frac(p, 6) < 1 || MARSH.frac(p, 6) > 0) { fits.dbg.wet++; return null; }
    return { p, r };
  };
  let best = null, stopAt = maxRad; const dbg = { dry: 0, road: 0, lin: 0, bld: 0, wet: 0 }; fits.dbg = dbg;
  for (let rad = 0; rad <= stopAt; rad += 10) {
    const n = rad ? Math.max(8, Math.round(2 * Math.PI * rad / 15)) : 1;
    for (let k = 0; k < n; k++) {
      const c = [pl.at[0] + rad * Math.cos(2 * Math.PI * k / n), pl.at[1] + rad * Math.sin(2 * Math.PI * k / n)]; if (!isDry(c[0], c[1])) continue; dbg.dry++;
      const f = fits(c); if (!f) continue; const score = rad + (a && f.r.seg.name !== a.street ? 150 : 0);
      if (!best || score < best.score) { best = { p: f.p, c, score, road: f.r, rad }; stopAt = Math.min(stopAt, score); }
    }
  }
  if (process.env.QA_DEBUG_SITE) console.log('SITE', pl.id, dbg, fits.dbg);
  return best;
}

// 7-pre-a. places whose stray building was removed move to the fitting building QA found for them
for (const [id, { to, from }] of rehomed) { const pl = placeById.get(id); if (pl && movePlace(id, centroid(cur[to]), `its building #${from} stood in a road and was removed; moved onto ${kindLabel(to)}`)) issue('place-off-site', 'medium', pl.at, { place: id, building: from, to_building: to }, `${pl.name}: its building #${from} stood in the road and was removed, so the point moved ${fmt(dist(pl.at, centroid(cur[to])))} m onto ${kindLabel(to)}.`, 'fixed', 'move'); }
// 7-pre-b. points that sat on a building QA moved, trimmed or turned follow it
for (const [i, xs] of XFORM) {
  if (!NAMED.has(i)) continue; const p0 = B[i].pts0, p1 = cur[i]; if (!p1) continue;
  const moves = xs.some(x => x.t === 'shift' || x.t === 'rot');
  const follow = pt => { if (ptPolyDist(p0, pt[0], pt[1]) > 12) return null; if (!moves && ptInPoly(p1, pt[0], pt[1])) return null; let q = pt.slice(); for (const x of xs) { if (x.t === 'shift') q = [q[0] + x.v[0], q[1] + x.v[1]]; else if (x.t === 'rot') q = rotateAbout([q], x.c, x.a)[0]; } if (dist(q, pt) < 0.05) return null; return ptInPoly(p0, pt[0], pt[1]) && !ptInPoly(p1, q[0], q[1]) ? centroid(p1) : q; };
  for (const pl of G.places) { const q = follow(pl.at); if (q && movePlace(pl.id, q, `follows its building #${i}, which QA moved off a road or neighbor`)) issue('place-off-site', 'low', pl.at, { place: pl.id, building: i }, `${pl.name}: its building #${i} was moved off a road or neighbor, so the point moved with it.`, 'fixed', 'move'); }
  for (const pe of G.people) { const q = follow(pe.home.at); if (q) movePerson(pe, q, `follows the home building #${i}, which QA moved off a road or neighbor`); }
}

// 7a. every place and home point against the building under it and the building with its address
const homesNoBuilding = new Map(); const ADDR_ONLY_GAZ = []; const needSite = [];
function checkPoint(who, src, pl, pt, a, onMove, isHome, already) {
  if (already) return; // it already moved with its building
  const at = buildingAt(pt, 0);
  if (at) {
    const own = addrStr(at.j); const tg = a ? addrTargets(a, pt) : [];
    if (a && own && own.toLowerCase() !== a.key) issue('address-point-mismatch', 'low', pt, { who, addr: `${a.num} ${a.street}`, point_building: at.j, point_building_addr: own, same_address_on: tg.map(t => t.j).slice(0, 3) }, `${who}: the point sits on ${kindLabel(at.j)}, which the Atlas numbers "${own}", not "${a.num} ${a.street}"${tg.length ? `; that exact address belongs to ${kindLabel(tg[0].j)}, ${fmt(tg[0].d)} m away${tg[0].d > 250 ? ' (numbers climb both ways from Courthouse Square, so that number falls on the other side of Courthouse Square)' : ''}` : ''}. The point is taken as the intent; nothing moved.`);
    else if (a && !own && tg.length && tg[0].d > 15) issue('address-point-mismatch', 'low', pt, { who, addr: `${a.num} ${a.street}`, point_building: at.j, address_building: tg[0].j, distance_m: r2(tg[0].d) }, `${who}: the point sits on ${kindLabel(at.j)}, while "${a.num} ${a.street}" is on ${kindLabel(tg[0].j)}, ${fmt(tg[0].d)} m away.${/Lot|Mobile Home/i.test(who + (pl ? pl.name : '') + a.raw) ? ' The point shows the intent: a lot inside a community that shares one street address. Kept as info; nothing moved.' : ' The point is taken as the intent; nothing moved.'}`);
    else if (a && !own) ADDR_ONLY_GAZ.push(who);
    return;
  }
  const fitsKind = j => isHome ? RESID.has(B[j].kind) : (pl && isBuildingType(pl) && (KIND_FOR[pl.cat] || []).includes(B[j].kind));
  const tgAll = a ? addrTargets(a, pt).filter(t => t.d <= 250) : []; const tg = tgAll.filter(t => fitsKind(t.j));
  if (tgAll.length && !tg.length && (isHome || (pl && isBuildingType(pl)))) issue('address-point-mismatch', 'low', pt, { who, addr: `${a.num} ${a.street}`, address_building: tgAll[0].j, distance_m: r2(tgAll[0].d) }, `${who}: the Atlas gives "${a.num} ${a.street}" to ${kindLabel(tgAll[0].j)}, ${fmt(tgAll[0].d)} m away, which is not a ${pl ? pl.cat : 'home'} building. Two places share one address; the point was not moved onto it.`);
  if (tg.length) {
    const t = tg[0]; if (t.d <= 15) return;
    onMove(centroid(cur[t.j]), `address: moved onto ${kindLabel(t.j)}, the building that carries ${a.num} ${a.street}`);
    issue('address-point-mismatch', 'medium', pt, { who, place: pl ? pl.id : null, addr: `${a.num} ${a.street}`, address_building: t.j, distance_m: r2(t.d) }, `${who}: the point was ${fmt(t.d)} m from ${kindLabel(t.j)}, the building with that address, and on no building itself. Moved the point onto it.`, 'fixed', 'move');
    return;
  }
  const nb = nearestBuilding(pt, 300); const road = onRoadSurface(pt); const wet = isWater(pt[0], pt[1]);
  if (isHome) {
    if (nb && nb.d <= 15) { issue('address-missing', 'medium', pt, { who, addr: a ? `${a.num} ${a.street}` : null, nearest_building: nb.j, nearest_m: r2(nb.d) }, `${who}: no building carries "${a ? a.num + ' ' + a.street : '?'}" and the point is on no building (nearest is ${kindLabel(nb.j)}, ${fmt(nb.d)} m away).`); return; }
    if (a) { if (!homesNoBuilding.has(a.key)) homesNoBuilding.set(a.key, { a, pt, places: [], people: [] }); return 'add'; }
    return;
  }
  if (!pl) return;
  const bt = isBuildingType(pl); const problems = [];
  if (road && !(road.bridge && WATER_OK.has(pl.id))) problems.push(`sits on the surface of ${featName(road)}`);
  if (wet && !WATER_OK.has(pl.id)) problems.push('sits in open water');
  if (bt && (!nb || nb.d > 60)) problems.push(`is ${nb ? fmt(nb.d) + ' m' : 'over 300 m'} from the nearest building`);
  if (!problems.length) return;
  const ref = { place: pl.id, source: src, addr: pl.addr || null }; const pr = problems.join(' and ');
  if (bt) {
    const km = kindMatched(pl, pt);
    if (km) { const to = centroid(cur[km.j]); onMove(to, `place-off-site: ${pr}; moved onto the nearest ${B[km.j].kind} building, #${km.j}`); issue('place-off-site', 'medium', pt, { ...ref, to_building: km.j, moved_m: r2(dist(pt, to)) }, `${pl.name} ${pr}, and no fitting building carries its address. Moved the point ${fmt(dist(pt, to))} m onto ${kindLabel(km.j)}, the nearest ${B[km.j].kind} building${BIG.test(pl.name) ? ' big enough for it' : ''}.`, 'fixed', 'move'); return; }
    if (!nb || nb.d > 110 || wet) { needSite.push({ pl, pt, ref, problems: pr }); return; }
    issue('place-off-site', 'medium', pt, { ...ref, nearest_building: nb.j, nearest_m: r2(nb.d) }, `${pl.name} ${pr}; no building of a fitting kind is near, so it was left for the author.`); return;
  }
  if (wet || road) { // open-air places (parks, ramps, fields): only water and road surfaces are wrong
    let spot = null; for (let r = 5; r <= 400 && !spot; r += 5) for (let k = 0; k < 36 && !spot; k++) { const q = [pt[0] + r * Math.cos(k * Math.PI / 18), pt[1] + r * Math.sin(k * Math.PI / 18)]; if ((WATER_OK.has(pl.id) || isDry(q[0], q[1])) && !onRoadSurface(q) && !buildingAt(q, 2)) spot = q; }
    if (spot) { onMove(spot, `place-off-site: ${pr}; moved ${fmt(dist(pt, spot))} m to the nearest open ground`); issue('place-off-site', 'low', pt, { ...ref, moved_m: r2(dist(pt, spot)) }, `${pl.name} ${pr}. Moved the point ${fmt(dist(pt, spot))} m to the nearest open ground.`, 'fixed', 'move'); }
    else issue('place-off-site', 'low', pt, ref, `${pl.name} ${pr}; left for the author.`);
  }
}
for (const pl of G.places) {
  const a = parseAddr(pl.addr); const isHome = pl.cat === 'homepoi' && pl.id.startsWith('home-');
  if (checkPoint(`${pl.name} (${pl.id})`, 'gaz', pl, pl.at, a, (to, why) => movePlace(pl.id, to, why), isHome, movedPlace.has(pl.id)) === 'add') homesNoBuilding.get(a.key).places.push(pl);
}
for (const po of W.pois) { const pl = placeById.get(po.id); if (pl && dist(pl.at, po.at) < 1.5) continue; checkPoint(`${po.name} (${po.id}, Atlas POI)`, 'wpdata.pois', { ...(pl || {}), ...po }, po.at, pl ? parseAddr(pl.addr) : null, (to, why) => movePlace(po.id, to, why), false, movedPlace.has(po.id)); }
for (const pe of G.people) {
  const a = parseAddr(pe.home.addr);
  if (checkPoint(`${pe.name}'s home`, 'gaz.people', null, pe.home.at, a, (to, why) => movePerson(pe, to, why), true, movedPerson.has(pe.name)) === 'add') homesNoBuilding.get(a.key).people.push(pe);
  if (pe.later) checkPoint(`${pe.name}'s later home`, 'gaz.people', null, pe.later.at, parseAddr(pe.later.addr), () => { }, false);
}
// 7b. homes whose address has no building and nothing near the point: add a proposed house by the street numbering
for (const [, h] of homesNoBuilding) {
  const who = [...h.places.map(p => p.name), ...h.people.map(p => p.name)].join(', ');
  const nb = nearestBuilding(h.pt, 300); const pr = proposeHouse(h.a);
  const ref = { addr: `${h.a.num} ${h.a.street}`, who, nearest_building: nb ? nb.j : null, nearest_m: nb ? r2(nb.d) : null };
  if (pr.fail) { issue('address-missing', 'high', h.pt, ref, `"${h.a.num} ${h.a.street}" (${who}) has no building and nothing stands within 110 m of its point; QA could not add one: ${pr.fail}.`); continue; }
  const moved = dist(h.pt, pr.c);
  const k = addBuilding('house', 7.5, pr.poly, h.a.street, h.a.num, `address-missing: added by QA, proposed. ${h.a.num} ${h.a.street} had no building; placed on the ${pr.side} (${h.a.num % 2 ? 'odd' : 'even'}) side ${fmt(pr.s)} m along the street (${pr.how}), ${pr.Wd} x ${pr.Dp} m like nearby houses, set back ${pr.setback} m from the curb like its neighbors`, { ...pr, a: h.a, who, moved, type: 'home' });
  for (const pl of h.places) movePlace(pl.id, pr.c, `address-missing: moved onto the house added by QA for ${h.a.num} ${h.a.street} (proposed)`);
  for (const pe of h.people) movePerson(pe, pr.c, `address-missing: moved onto the house added by QA for ${h.a.num} ${h.a.street} (proposed)`);
  issue('address-missing', 'high', h.pt, { ...ref, added_building: k, new_at: P2(pr.c), moved_m: r2(moved) }, `"${h.a.num} ${h.a.street}" (${who}) had no building, and nothing stood within ${nb ? Math.floor(nb.d) : 300} m of the point (${nb ? fmt(dist(h.pt, centroid(cur[nb.j]))) : '300+'} m to the nearest house center). Added by QA, proposed: a ${pr.Wd} x ${pr.Dp} m house on the ${pr.side} side of ${h.a.street}, ${fmt(pr.s)} m from its start (${pr.how}), and moved the point${h.people.length + h.places.length > 1 ? 's' : ''} ${fmt(moved)} m onto it.`, 'fixed', 'add');
}
// 7c. named places with nothing on the ground: add a proposed building of a fitting kind
const SITE_KIND = { school: 'school', civic: 'civic', lodging: 'hotel', shop: 'retail', food: 'retail', health: 'office', industry: 'industrial', landmark: 'office', canon: 'civic', marina: 'clubhouse' };
const homeDepot = placeById.get('home-depot') ? buildingAt(placeById.get('home-depot').at) : null;
for (const ns of needSite) {
  const { pl, pt, ref, problems } = ns; const a = parseAddr(pl.addr);
  const kind = SITE_KIND[pl.cat] || 'civic'; let dims = kind === 'hotel' ? { w: 45, d: 18, h: 21 } : kindDims(kind);
  if (BIG.test(pl.name)) dims = { w: 110, d: 75, h: homeDepot ? B[homeDepot.j].h : 9 }; // a Lowe's-size box, about 8,000 m2
  if (/Government Center/.test(pl.name)) dims = { w: 60, d: 40, h: 12 };
  if (pl.hood === 'Uptown' && kind === 'office') dims.h = Math.max(dims.h, 16);
  dims = { w: Math.round(dims.w * 2) / 2, d: Math.round(dims.d * 2) / 2, h: Math.round(dims.h * 2) / 2 };
  const site = proposeSite(pl, dims.w, dims.d, a) || proposeSite(pl, dims.w, dims.d, a, 160, 1500);
  if (!site) { issue('place-off-site', 'high', pt, ref, `${pl.name} ${problems}, and there is no building for it; QA found no dry, free spot by a road within 700 m. Left for the author.`); continue; }
  const where = site.rad ? `on the nearest dry, free ground by ${roadName(site.road.ri)}, ${Math.round(site.rad)} m from the old point` : 'at its point';
  const k = addBuilding(kind, dims.h, site.p, a ? a.street : null, a ? a.num : null, `place-off-site: added by QA, proposed. ${pl.name} had no building (its point ${problems}); a ${dims.w} x ${dims.d} m ${kind} ${where}`, { pl, site, dims, kind, type: 'place' });
  movePlace(pl.id, site.c, `place-off-site: moved onto the ${kind} added by QA (proposed)`);
  issue('place-off-site', 'high', pt, { ...ref, added_building: k, new_at: P2(site.c), moved_m: r2(site.rad) }, `${pl.name} ${problems}, and no building stands for it. Added by QA, proposed: a ${dims.w} x ${dims.d} m ${kind} ${where}, and moved the point onto it.`, 'fixed', 'add');
}
// =============================================================================================
// 8. Labels
// =============================================================================================
const HOOD_OF_LABEL = { 'Westport Beach': 'The beach' };
const builtArea = (pt, r) => { let A = 0; for (const j of BG.query([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r])) if (cur[j] && dist(centroid(cur[j]), pt) <= r) A += areaOf(cur[j]); return A; };
function waterAxis(pt, r = 400) { // main direction of the water around pt, as a text rotation (degrees clockwise on screen)
  let n = 0, mx = 0, my = 0; const P = []; for (let x = -r; x <= r; x += 20) for (let y = -r; y <= r; y += 20) if (x * x + y * y <= r * r && isWater(pt[0] + x, pt[1] + y)) { P.push([x, y]); mx += x; my += y; n++; }
  if (n < 10) return null; mx /= n; my /= n; let sxx = 0, syy = 0, sxy = 0; for (const [x, y] of P) { sxx += (x - mx) ** 2; syy += (y - my) ** 2; sxy += (x - mx) * (y - my); }
  if (Math.abs(sxx - syy) < 0.2 * (sxx + syy) && Math.abs(sxy) < 0.2 * (sxx + syy)) return null; // no clear direction
  return -0.5 * Math.atan2(2 * sxy, sxx - syy) * 180 / Math.PI;
}
const wrap90 = d => ((d % 180) + 270) % 180 - 90;
for (const l of W.labels) {
  if (!l.at) continue; const pt = l.at;
  if (l.kind === 'district') {
    const hood = HOOD_OF_LABEL[l.text] || l.text; const own = G.places.filter(p => p.hood === hood).map(p => p.at);
    const dOwn = own.length ? Math.min(...own.map(q => dist(q, pt))) : Infinity;
    let other = null; for (const pl of G.places) { if (pl.hood === hood || /Elsewhere|Strip|North of|Quarry|port and/.test(pl.hood)) continue; const d = dist(pl.at, pt); if (d < 0.5 * dOwn && d < 400 && (!other || d < other.d)) other = { d, hood: pl.hood, id: pl.id }; }
    const problems = []; if (!isDry(pt[0], pt[1])) problems.push(isWater(pt[0], pt[1]) ? 'it sits on the water' : 'it sits in the marsh'); if (other) problems.push(`the nearest named place is ${other.id}, in ${other.hood}`); if (builtArea(pt, 350) < 5000) problems.push('almost nothing is built within 350 m');
    if (!problems.length) continue;
    const cx = own.length ? [own.reduce((s, q) => s + q[0], 0) / own.length, own.reduce((s, q) => s + q[1], 0) / own.length] : pt;
    const okSpot = q => isDry(q[0], q[1]) && builtArea(q, 350) >= 20000 && !onRoadSurface(q);
    let to = okSpot(cx) ? cx : null; for (let r = 25; r <= 1500 && !to; r += 25) for (let k = 0; k < 24 && !to; k++) { const q = [cx[0] + r * Math.cos(k * Math.PI / 12), cx[1] + r * Math.sin(k * Math.PI / 12)]; if (okSpot(q)) to = q; }
    if (to) { FIX.move_labels.push({ text: l.text, at: P2(to), was: P2(pt), why: `label-placement: ${problems.join('; ')}` }); issue('label-placement', 'medium', pt, { label: l.text, kind: l.kind }, `District label "${l.text}": ${problems.join('; ')}. Moved it to the middle of ${hood}.`, 'fixed', 'move'); }
    else issue('label-placement', 'medium', pt, { label: l.text, kind: l.kind }, `District label "${l.text}": ${problems.join('; ')}.`);
  } else if (l.kind === 'water') {
    const marsh = /marsh/i.test(l.text); const want = marsh ? 'the marsh' : 'open water';
    const ring = (q, r, k, f) => Array.from({ length: k }, (_, m) => [q[0] + r * Math.cos(2 * Math.PI * m / k), q[1] + r * Math.sin(2 * Math.PI * m / k)]).every(v => f(v[0], v[1]));
    const good = q => marsh ? MARSH.has(q[0], q[1]) && ring(q, 60, 8, (x, y) => MARSH.has(x, y)) : isWater(q[0], q[1]) && ring(q, 30, 8, isWater);
    let to = null; if (!good(pt)) for (let r = 10; r <= 2000 && !to; r += 10) { const n = Math.max(12, Math.round(2 * Math.PI * r / 15)); for (let k = 0; k < n && !to; k++) { const q = [pt[0] + r * Math.cos(2 * Math.PI * k / n), pt[1] + r * Math.sin(2 * Math.PI * k / n)]; if (good(q)) to = q; } }
    const at = to || pt; let rot = null;
    if (/River/.test(l.text)) { const ax = waterAxis(at); if (ax != null) { const d = wrap90(ax - (l.rot || 0)); if (Math.abs(d) > 15) rot = Math.round(((l.rot || 0) + d) * 10) / 10; } }
    if (!to && rot == null) continue;
    const det = []; if (to) det.push(`its anchor sat on ${isWater(pt[0], pt[1]) ? 'water too close to the bank' : MARSH.has(pt[0], pt[1]) ? 'the marsh' : 'dry land'}, not ${want}`); if (rot != null) det.push(`its text ran ${fmt(Math.abs(wrap90(rot - (l.rot || 0))))} degrees across the river instead of along it`);
    const mv = { text: l.text, at: P2(at), was: P2(pt), why: `label-placement: ${det.join('; ')}` }; if (rot != null) mv.rot = rot; FIX.move_labels.push(mv);
    issue('label-placement', 'medium', pt, { label: l.text, kind: l.kind, rot: l.rot || 0, new_rot: rot }, `Water label "${l.text}": ${det.join('; ')}. ${to ? `Moved it ${fmt(dist(pt, to))} m onto ${want}` : 'Kept its place'}${rot != null ? ` and turned it from ${l.rot || 0} to ${rot} degrees` : ''}.`, 'fixed', 'move');
  }
}

// =============================================================================================
// 9. Canon and data conflicts (flagged, never changed)
// =============================================================================================
const canon = (sev, at, ref, detail) => issue('canon-conflict', sev, at, ref, detail);
{
  const mh = placeById.get('motel-hwy'), st = G.people.find(p => p.name === 'Steven Villanueva');
  if (mh && st) { const bm = buildingAt(mh.at); canon('medium', mh.at, { place: 'motel-hwy', person: st.name, place_addr: mh.addr, person_addr: st.home.addr, building: bm ? bm.j : null }, `The register puts "the motel on the Highway" at ${mh.addr}, but Steven Villanueva's room 12 there is listed at ${st.home.addr}. Both points are the same spot${bm ? `, ${kindLabel(bm.j)}` : ''}. One number should change; a motel has one street number, and the room number is separate.`); }
  const dl = placeById.get('home-delacroix'); if (dl) {
    const b = buildingAt(dl.at); const c = b ? centroid(cur[b.j]) : dl.at; const sd = shoreDist(c);
    let wp = null; for (let k = 0; k < 360 && !wp; k += 2) { const q = [c[0] + sd * Math.cos(k * Math.PI / 180), c[1] + sd * Math.sin(k * Math.PI / 180)]; if (isWater(q[0], q[1])) wp = q; }
    const between = new Set(); if (wp) for (let t = 0; t <= 1; t += 0.01) { const q = [c[0] + (wp[0] - c[0]) * t, c[1] + (wp[1] - c[1]) * t]; const bb = buildingAt(q); if (bb && (!b || bb.j !== b.j)) between.add(bb.j); }
    const roadsBetween = new Set(); if (wp) for (let t = 0; t <= 1; t += 0.01) { const q = [c[0] + (wp[0] - c[0]) * t, c[1] + (wp[1] - c[1]) * t]; const rs = onRoadSurface(q); if (rs) roadsBetween.add(roadName(rs.idx)); }
    canon('medium', c, { place: 'home-delacroix', building: b ? b.j : null, open_water_m: sd, buildings_between: [...between], roads_between: [...roadsBetween] }, `The Delacroix house is "the big house on the water" (Book 1 Spine), but its lot at ${dl.addr} (building ${b ? b.j : '?'}) is about ${sd} m from open water${between.size || roadsBetween.size ? `, with ${[between.size ? `${between.size} other building${between.size > 1 ? 's' : ''}` : '', roadsBetween.size ? [...roadsBetween].join(' and ') : ''].filter(Boolean).join(' and ')} between it and the shore` : ''}. Either pick a waterfront lot on Harbor Drive or drop "on the water".`);
  }
  const seen = new Map(); for (const pl of G.places) { const a = parseAddr(pl.addr); if (!a) continue; if (!seen.has(a.key)) seen.set(a.key, []); seen.get(a.key).push(pl); }
  for (const [, list] of seen) { const biz = list.filter(p => !p.id.startsWith('home-')); if (biz.length < 2) continue; const d = Math.max(...biz.map(p => dist(p.at, biz[0].at))); canon('medium', biz[0].at, { places: biz.map(p => p.id), addr: biz[0].addr, apart_m: r2(d) }, `${biz.map(p => p.name).join(' and ')} share one address, ${biz[0].addr}, though their points are ${fmt(d)} m apart. Two businesses on separate lots need two numbers.`); }
  const pier = placeById.get('pier-bar'), bait = placeById.get('langfords'), crab = placeById.get('crab-house'), diner = placeById.get('chadwicks-diner');
  if (pier && bait && crab) canon('medium', pier.at, { places: ['pier-bar', 'langfords', 'crab-house', 'chadwicks-diner'], pier_to_bait_m: Math.round(dist(pier.at, bait.at)), pier_to_crab_m: Math.round(dist(pier.at, crab.at)), diner_to_pier_m: diner ? Math.round(dist(diner.at, pier.at)) : null, diner_to_bait_m: diner ? Math.round(dist(diner.at, bait.at)) : null }, `The register says the pier and pier bar (locked) stand "near the bait shop and the crab house", and that Chadwick's is "near the bait shop and the pier". On the map the pier is ${Math.round(dist(pier.at, bait.at))} m from Langford's Bait & Tackle and ${Math.round(dist(pier.at, crab.at))} m from the crab house${diner ? `; Chadwick's is ${Math.round(dist(diner.at, pier.at))} m from the pier but ${Math.round(dist(diner.at, bait.at))} m from the bait shop` : ''}. That is about a mile along Harbor Drive, not "near". Moving the bait shop and crab house east, to the 300s to 500s of Harbor Drive, would fix it.`);
  const ch = placeById.get('home-chadwick'), na = placeById.get('nine-acres'); const add = ADDED.find(x => x.info && x.info.type === 'home' && x.info.a.street === 'Chadwick Road');
  if (ch && na) { const hp = add ? add.info.c : ch.at; canon('low', hp, { place: 'home-chadwick', field: 'nine-acres', house_to_field_m: Math.round(dist(hp, na.at)) }, `The Chadwick house is "on the family land by the field". Chadwick Road has no numbered buildings; by the town's numbering, 299 falls about ${add ? fmt(add.info.s) : '?'} m along the road, ${Math.round(dist(hp, na.at))} m from the middle of the nine acres (516 Chadwick Road). If the house should sit at the field, a number in the 500s fits better.`); }
  const mk = placeById.get('home-mckenzie'); if (mk) { const at = buildingAt(mk.at); const inL = ptInPoly(LIMITS[0], mk.at[0], mk.at[1]); const og = streetChain('Oak Grove Road'); const pr = og ? chainProject(og, mk.at) : null; canon('low', mk.at, { place: 'home-mckenzie', point_building: at ? at.j : null, its_addr: at ? addrStr(at.j) : null, oak_grove_road_m: pr ? r2(pr.d) : null, inside_city_limits: inL }, `The McKenzie farmhouse is listed at 2282 Oak Grove Road, but no Atlas building has that address. The point sits on ${at ? kindLabel(at.j) : 'no building'}${at && !addrStr(at.j) ? ' (no street number)' : ''}, ${pr ? fmt(pr.d) : '?'} m off Oak Grove Road${pr ? ` beside the stretch numbered about ${Math.round((MODEL.a + MODEL.b * pr.s) / 2) * 2}` : ''}, so the number fits a farmhouse set well back from the road. It is ${inL ? 'inside' : 'outside'} the city limits${inL ? ', though the register says "just outside town"' : ', which matches "just outside town"'}. QA keeps the point on that building.`); }
  const hs = placeById.get('westport-high'); if (hs) { const pb = streetChain('Patriots Boulevard'); const mv = movedPlace.get('westport-high') || hs.at; const d = pb ? chainProject(pb, mv).d : null; if (d != null && d > 150) canon('low', mv, { place: 'westport-high', patriots_blvd_m: Math.round(d) }, `The register says Westport High "sits on Patriots Boulevard", but its address is ${hs.addr} and the school is ${Math.round(d)} m from Patriots Boulevard.`); }
  const chk = (id, want, txt) => { const pl = placeById.get(id); if (!pl) return; const inside = LIMITS.some(r => ptInPoly(r, pl.at[0], pl.at[1])); if (inside !== want) canon('medium', pl.at, { place: id, inside_city_limits: inside }, `${pl.name}: the register says it is ${txt}, but its point is ${inside ? 'inside' : 'outside'} the city limits drawn on the map.`); };
  chk('nine-acres', true, 'inside the city limits'); chk('quarry', false, 'outside the city limits'); chk('town-beach', true, 'inside the city limits');
  const mhc = placeById.get('riverside-mhc'); if (mhc) { let dm = Infinity; for (let r = 25; r <= 3000 && dm === Infinity; r += 25) for (let k = 0; k < 72; k++) { const a = k * Math.PI / 36; if (MARSH.has(mhc.at[0] + r * Math.cos(a), mhc.at[1] + r * Math.sin(a))) { dm = r; break; } } if (dm > 600) canon('low', mhc.at, { place: 'riverside-mhc', marsh_m: dm }, `The lock says the marsh runs up a tidal creek behind the trailer park; the nearest marsh is about ${dm} m from the park's point.`); }
  const dupe = new Map(); for (const [, list] of byAddr) { if (list.length < 2) continue; const cs = list.map(i => centroid(B[i].pts0)); let far = 0; for (let x = 0; x < cs.length; x++) for (let y = x + 1; y < cs.length; y++) far = Math.max(far, dist(cs[x], cs[y])); if (far < 100) continue; const st = addrOf.get(list[0]).street; dupe.set(st, (dupe.get(st) || 0) + 1); }
  if (dupe.size) { const top = [...dupe.entries()].sort((a, b) => b[1] - a[1]); const total = top.reduce((s, x) => s + x[1], 0); canon('medium', [-308, 191], { streets: Object.fromEntries(top.slice(0, 15)), numbers: total, streets_affected: top.length }, `${total} street numbers are used twice on the same street, on ${top.length} streets, because numbers climb outward from Courthouse Square in both directions (most: ${top.slice(0, 5).map(([s, n]) => `${s} ${n}`).join(', ')}). Real towns split these into East and West (or North and South) Main Street and so on. Places on these streets can match the wrong building; "226 Main Street" is both East's Nook Books and a shop about 400 m west of it.`); }
  { // streets numbered outward in both directions from Courthouse Square: the same range appears on both halves
    const vs = []; for (const [st, list] of streetAddrs) { if (list.length < 20) continue; const ch = streetChain(st); if (!ch) continue; const pts = list.map(([i, n]) => ({ n, s: chainProject(ch, centroid(B[i].pts0)).s })).sort((a, b) => a.s - b.s); const k = pts.reduce((m, o, idx) => (o.n < pts[m].n ? idx : m), 0); const left = pts.slice(0, k), right = pts.slice(k + 1); if (left.length >= 5 && right.length >= 5 && left[0].n > pts[k].n + 50 && right[right.length - 1].n > pts[k].n + 50) vs.push([st, list.length]); }
    const ex = ISSUES.filter(o => o.type === 'address-point-mismatch' && /other side of Courthouse Square/.test(o.detail));
    if (vs.length) canon('medium', [-308, 191], { streets: vs.map(v => v[0]), examples: ex.map(o => o.ref.who) }, `${vs.length} streets that run through downtown (${vs.slice(0, 6).map(v => v[0]).join(', ')}${vs.length > 6 ? ' and others' : ''}) are numbered outward from Courthouse Square in both directions, so the same range of numbers appears on both halves with no East or West in the name. ${ex.length ? `That is why ${[...new Set(ex.map(o => o.ref.who.replace(/ \(.*$/, '')))].slice(0, 3).join(', ')} sit on buildings numbered differently from their addresses: the Atlas puts their number on the other half of the street. ` : ''}Adding East/West Main Street (and so on) would make every downtown address unique.`);
  }
  for (const n of names) if (/^(\w+)\s+\1$/i.test(n)) canon('low', (streetChain(n) || { pts: [[0, 0]] }).pts[0], { street: n }, `A street is named "${n}", which reads as a generator slip. Rename it.`);
  for (const po of W.pois) { const pl = placeById.get(po.id); if (!pl) { canon('low', po.at, { poi: po.id }, `Atlas POI "${po.name}" (${po.id}) has no gazetteer entry.`); continue; } const d = dist(pl.at, po.at); if (d > 1.5) canon('low', pl.at, { place: po.id, gaz_at: P2(pl.at), poi_at: P2(po.at), apart_m: r2(d) }, `${pl.name}: the gazetteer point and the Atlas POI point are ${fmt(d)} m apart.`); if (pl.name !== po.name) canon('low', pl.at, { place: po.id }, `${po.id}: the gazetteer calls it "${pl.name}" and the Atlas POI "${po.name}".`); }
  // register tables against the gazetteer
  const STATUS = { 'canon 2': 'canon2', 'your site': 'author-site', 'you confirmed': 'confirmed', locked: 'locked', proposed: 'proposed', 'your doc': 'author-doc' };
  const rows = []; let mode = null;
  for (const line of REG.split('\n')) { if (/^\|\s*Place\s*\|\s*Address\s*\|\s*Status/.test(line)) { mode = 'place'; continue; } if (/^\|\s*Person\s*\|/.test(line)) { mode = 'person'; continue; } if (!line.startsWith('|')) { mode = null; continue; } if (/^\|\s*-/.test(line) || !mode) continue; rows.push({ mode, c: line.split('|').slice(1, -1).map(s => s.trim()) }); }
  const norm = s => s.toLowerCase().replace(/[’']/g, "'");
  const usedGaz = new Set();
  for (const { mode: md, c } of rows) {
    if (md === 'place') {
      const [name, addr, status] = c; const cands = G.places.filter(p => norm(p.name) === norm(name) && !usedGaz.has(p.id)); const pl = cands.find(p => (p.addr || '') === (addr || '')) || cands[0];
      if (!pl) { canon('low', [0, 0], { register_place: name }, `The register lists "${name}" (${addr || 'no address'}) but the gazetteer has no place by that name.`); continue; } usedGaz.add(pl.id);
      if ((addr || null) !== (pl.addr || null)) canon('medium', pl.at, { place: pl.id, register: addr, gazetteer: pl.addr }, `${name}: the register gives "${addr}" but the gazetteer "${pl.addr}".`);
      const sw = STATUS[(status || '').toLowerCase()]; if (sw && sw !== pl.status) canon('low', pl.at, { place: pl.id, register: status, gazetteer: pl.status }, `${name}: the register marks it "${status}" but the gazetteer "${pl.status}".`);
    } else {
      const [name, , , addr, status] = c; const pe = G.people.find(p => p.name === name); if (!pe) { canon('low', [0, 0], { register_person: name }, `The register lists ${name}, but the gazetteer has no such person.`); continue; }
      if (addr !== pe.home.addr) canon('medium', pe.home.at, { person: name, register: addr, gazetteer: pe.home.addr }, `${name}: the register gives "${addr}" but the gazetteer "${pe.home.addr}".`);
      const sw = STATUS[(status || '').toLowerCase()]; if (sw && sw !== pe.home.status) canon('low', pe.home.at, { person: name, register: status, gazetteer: pe.home.status }, `${name}: the register marks the home "${status}" but the gazetteer "${pe.home.status}".`);
    }
  }
  for (const pl of G.places) if (!pl.id.startsWith('home-') && !usedGaz.has(pl.id)) canon('low', pl.at, { place: pl.id }, `${pl.name} (${pl.id}) is in the gazetteer but not in the register's place tables.`);
  const noAddr = G.places.filter(p => !p.addr && isBuildingType(p)); if (noAddr.length) canon('low', noAddr[0].at, { places: noAddr.map(p => p.id) }, `${noAddr.length} places that are buildings have no street address yet: ${noAddr.map(p => p.name).join(', ')}.`);
}

// =============================================================================================
// 10. Verification: the building checks again, on the fixed set
// =============================================================================================
const VERIFY = { road: [], rail: [], creek: [], pier: [], water: [], marsh: [], overlap: [] };
{ // rebuild the footprints from the fixes exactly as they will be written (rounded to 1 cm), not from memory
  const rem = new Set(FIX.remove_buildings); const rp = new Map(FIX.replace_buildings.map(e => [e.i, ptsOf(e.poly)]));
  for (let i = 0; i < W.b.length; i++) { const p = rem.has(i) ? null : rp.has(i) ? rp.get(i) : B[i].pts0; if (p !== cur[i] && !(p && cur[i] && p.every((q, k) => dist(q, cur[i][k]) < 0.02))) throw new Error('fix list and working state differ at building ' + i); setPoly(i, p); }
  FIX.add_buildings.forEach((a, k) => setPoly(W.b.length + k, ptsOf(a.poly)));
}
const SNAP_CHECK = { checked: 0, off: 0 }; // every road end QA snapped must sit on the road it joins
for (const [key, tri] of GAP_TARGET) { const [ri, v] = key.split(':').map(Number); const q = FIX.road_snaps.find(x => x.road === ri && x.vertex === v).to; const tp = roadFix[tri]; let d = Infinity; for (let k = 0; k + 1 < tp.length; k++) d = Math.min(d, ptSeg(q[0], q[1], tp[k][0], tp[k][1], tp[k + 1][0], tp[k + 1][1])[0]); SNAP_CHECK.checked++; if (d > 0.02) SNAP_CHECK.off++; }
for (let i = 0; i < cur.length; i++) {
  const p = cur[i]; if (!p) continue; const c = centroid(p);
  if (!PIER_BUILDINGS.has(i)) { if (isWater(c[0], c[1]) || 1 - LAND.frac(p, 6) > 0.25) VERIFY.water.push(i); else if (MARSH.has(c[0], c[1]) || MARSH.frac(p, 6) > 0.25) VERIFY.marsh.push(i); }
  for (const h of linHits(p)) { if ((h.s.kind === 'pier' && PIER_BUILDINGS.has(i)) || spurOk(i, h.s)) continue; if (!VERIFY[h.s.kind].includes(i)) VERIFY[h.s.kind].push(i); }
  for (const j of BG.query(bboxOf(p))) if (j > i && cur[j] && interArea(p, cur[j]) > OVERLAP_MIN) VERIFY.overlap.push([i, j]);
}
const flaggedB = new Set(ISSUES.filter(o => o.action === 'flagged' && o.ref && o.ref.building != null).map(o => o.ref.building));
const unexplained = {}; for (const [k, v] of Object.entries(VERIFY)) unexplained[k] = v.filter(x => (Array.isArray(x) ? !(flaggedB.has(x[0]) || flaggedB.has(x[1])) : !flaggedB.has(x)));

// =============================================================================================
// 11. data/qa.json
// =============================================================================================
const SEV = { high: 0, medium: 1, low: 2 };
ISSUES.sort((a, b) => (TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type)) || (SEV[a.severity] - SEV[b.severity]) || (a.action === b.action ? 0 : a.action === 'flagged' ? -1 : 1));
ISSUES.forEach((o, k) => { o.id = 'Q' + String(k + 1).padStart(4, '0'); });
const by_type = {}; for (const t of TYPE_ORDER) { const L = ISSUES.filter(o => o.type === t); if (L.length) by_type[t] = { found: L.length, fixed: L.filter(o => o.action === 'fixed').length }; }
FIX.remove_buildings = [...new Set(FIX.remove_buildings)].sort((a, b) => a - b);
const removedSet = new Set(FIX.remove_buildings); FIX.replace_buildings = FIX.replace_buildings.filter(e => !removedSet.has(e.i)).sort((a, b) => a.i - b.i);
FIX.road_snaps.sort((a, b) => a.road - b.road || a.vertex - b.vertex);
const summary = { buildings: W.b.length, roads: W.roads.length, places: G.places.length, issues: ISSUES.length, fixed: ISSUES.filter(o => o.action === 'fixed').length, flagged: ISSUES.filter(o => o.action === 'flagged').length, by_type };
const QA = { version: 1, summary, fixes: FIX, issues: ISSUES };
fs.writeFileSync(path.join(ROOT, 'data/qa.json'), JSON.stringify(QA));

// =============================================================================================
// 12. docs/QA-REPORT.md and renders/qa/*.png
// =============================================================================================
const T = (rows, head) => ['| ' + head.join(' | ') + ' |', '|' + head.map(() => '---').join('|') + '|', ...rows.map(r => '| ' + r.map(x => String(x ?? '').replace(/\|/g, '/').replace(/\n/g, ' ')).join(' | ') + ' |')].join('\n');
const xy = p => `${Math.round(p[0])}, ${Math.round(p[1])}`;
const cnt = t => (by_type[t] ? by_type[t].found : 0), cfx = t => (by_type[t] ? by_type[t].fixed : 0);
const ofType = (t, f = () => true) => ISSUES.filter(o => o.type === t && f(o));
const plots = [];
const plotSpec = (file, title, note, center, half, mark) => {
  let bb = [center[0] - half, center[1] - half * 0.62, center[0] + half, center[1] + half * 0.62];
  if (mark && mark.length > 1) { const xs = mark.map(m => m[0]), ys = mark.map(m => m[1]); const pad = half * 0.25; let x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad; const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2; let hw = (x1 - x0) / 2, hh = (y1 - y0) / 2; if (hh > hw * 0.62) hw = hh / 0.62; else hh = hw * 0.62; bb = [cx - hw, cy - hh, cx + hw, cy + hh]; }
  plots.push({ file: 'renders/qa/' + file, title, note, bbox: bb, panel_w: 560, mark: mark || [center] });
};
{
  const add = ADDED.find(x => x.info && x.info.type === 'home' && x.info.a.street === 'Chadwick Road');
  if (add) plotSpec('01-chadwick-house-added.png', 'Chadwick house: 299 Chadwick Road had no building', 'Added by QA, proposed (green); the home point moves onto it.', [(add.info.c[0] + 6250) / 2, (add.info.c[1] - 3200) / 2], 260, [add.info.c, [6250, -3200]]);
  const tw = ofType('building-on-road', o => o.ref.kind === 'townhouse' && o.action === 'fixed')[0]; if (tw) plotSpec('02-townhouse-lane.png', 'Townhouse rows that their own service lane runs through', 'Each row is split in two around the lane (orange = the kept half, green = the other half).', tw.at, 90);
  const sh = ofType('building-on-road', o => o.ref.kind === 'mobile' && o.fix === 'remove' && o.ref.road_name === 'Sand Hill Road')[0] || ofType('building-on-road', o => o.ref.kind === 'mobile' && o.fix === 'remove')[0]; if (sh) plotSpec('03-mobiles-on-road.png', `Mobile homes standing on ${sh.ref.road_name || 'a road'}`, 'Red = removed (standing on the road); orange = moved clear or turned square.', sh.at, 70);
  const wt = ISSUES.find(o => o.type === 'building-on-road' && o.ref.places && o.ref.places.includes('water-tower')); if (wt) plotSpec('04-water-tower.png', 'Water tower footprint on Mariner Drive', 'Moved clear of the road; the landmark point moves with it.', wt.at, 70);
  const cc = ISSUES.find(o => o.type === 'place-off-site' && o.ref.place === 'county-center'); if (cc) { const na = cc.ref.new_at || cc.at; plotSpec('05-county-center.png', 'County Government Center: point in the river, bridge stub to nowhere', 'Added by QA, proposed (green) on the nearest dry ground; the bridge stub is flagged.', [(cc.at[0] + na[0]) / 2, (cc.at[1] + na[1]) / 2], Math.max(300, dist(cc.at, na) * 0.8), [cc.at, na]); }
  const ri = ofType('road-into-building', o => o.action === 'fixed' && o.fix === 'snap' && o.ref.buildings.some(j => NAMED.has(j)))[0]; if (ri) { const bj = ri.ref.buildings.find(j => NAMED.has(j)); plotSpec('06-driveway-into-building.png', `Driveway running through ${NAMED.get(bj).join(', ')} (${B[bj].kind} #${bj})`, 'The driveway is cut back so it stops at the wall (road_snaps); the part through and past the building goes.', centroid(cur[bj]), 70); }
  const ma = ofType('misaligned-building', o => o.action === 'fixed' && Math.abs(o.ref.deviation_deg) > 8)[0]; if (ma) plotSpec('07-misaligned-houses.png', 'Houses turned square to their street', 'Orange = turned about its center; faint outline = before.', ma.at, 70);
  const lb = ofType('label-placement', o => o.action === 'fixed')[0]; if (lb) { const mv = FIX.move_labels.find(m => m.text === lb.ref.label); plotSpec('08-labels.png', `Label "${lb.ref.label}" off its water`, 'Moved onto the water it names.', [(lb.at[0] + mv.at[0]) / 2, (lb.at[1] + mv.at[1]) / 2], Math.max(500, dist(lb.at, mv.at) * 0.9), [lb.at, mv.at]); }
}
fs.writeFileSync(path.join(ROOT, 'docs/QA-REPORT.md'), buildReport());
let plotOut = '';
if (!ARGS.has('--no-plots')) {
  fs.mkdirSync(path.join(ROOT, 'renders/qa'), { recursive: true });
  for (const f of fs.readdirSync(path.join(ROOT, 'renders/qa'))) if (f.endsWith('.png')) fs.unlinkSync(path.join(ROOT, 'renders/qa', f));
  const r = spawnSync('python3', ['-I', path.join(HERE, 'plots.py'), ROOT], { input: JSON.stringify(plots), encoding: 'utf8' });
  plotOut = r.status === 0 ? r.stdout.trim() : `plots failed: ${(r.stderr || r.error || '').toString().slice(0, 400)}`;
}
console.log(JSON.stringify(summary, null, 1));
console.log('fixes:', Object.fromEntries(Object.entries(FIX).map(([k, v]) => [k, v.length])));
console.log('verify (remaining after fixes):', Object.fromEntries(Object.entries(VERIFY).map(([k, v]) => [k, v.length])), 'not covered by a flag:', Object.fromEntries(Object.entries(unexplained).map(([k, v]) => [k, v.length])));
console.log('snapped ends seated:', SNAP_CHECK);
console.log('ladder:', ladderStats);
console.log('alignment:', alignStats);
if (plotOut) console.log(plotOut);
console.log(`done in ${((Date.now() - T0) / 1000).toFixed(1)} s`);

// ------------------------------------------------------------------ report text
function buildReport() {
  const L = []; const s = summary; const n = v => Number(v).toLocaleString('en-US');
  const vt = Object.fromEntries(Object.entries(VERIFY).map(([k, v]) => [k, v.length])); const vsum = Object.values(vt).reduce((a, b) => a + b, 0);
  const pname = id => (placeById.get(id) || {}).name || id; const paddr = id => (placeById.get(id) || {}).addr || '';
  const lad = (t, k) => ladderStats[t + ':' + k] || 0;
  const removedKinds = {}; for (const i of FIX.remove_buildings) removedKinds[B[i].kind] = (removedKinds[B[i].kind] || 0) + 1;
  const kindList = o => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${v} ${k === 'house' ? (v > 1 ? 'houses' : 'house') : k === 'mobile' ? (v > 1 ? 'mobile homes' : 'mobile home') : k === 'shed' ? (v > 1 ? 'sheds' : 'shed') : k + (v > 1 ? (/s$/.test(k) ? '' : 's') : '')}`).join(', ');
  L.push('# Westport Atlas: QA and alignment report', '');
  L.push('You asked me to check the map for stray assets, make sure everything sits where it should, and line up whatever does not. This is what I checked, what I fixed and what I left for you. I did not edit `data/wpdata.json` or `data/gaz.json`. Every correction is in `data/qa.json`, which the 3D map applies when it loads, so you can review or undo each one on its own. To rerun: `node tools/qa/audit.mjs`.', '');
  L.push('## The short version', '');
  L.push(`- I checked ${n(s.buildings)} buildings, ${n(s.roads)} roads, ${s.places} gazetteer places, ${G.people.length} people's homes, ${W.pois.length} map POIs and ${W.labels.length} labels.`);
  L.push(`- I found ${n(s.issues)} issues. ${n(s.fixed)} are fixed. ${n(s.flagged)} are flagged for you: ${by_type['canon-conflict'] ? by_type['canon-conflict'].found : 0} canon conflicts, ${cnt('address-point-mismatch') - cfx('address-point-mismatch')} points that disagree with the address table, ${cnt('road-dead-end') + cnt('bridge-dead-end')} road ends that need a decision, and a few small items.`);
  const splits = ADDED.filter(x => x.info && x.info.type === 'split').length;
  L.push(`- Buildings: ${FIX.remove_buildings.length} strays removed (${kindList(removedKinds)}), ${n(FIX.replace_buildings.length)} nudged, trimmed, moved or turned, and ${FIX.add_buildings.length - splits} added where a home or a named place had no building (marked "added by QA, proposed").${splits ? ` Another ${splits} entries in add_buildings are the second halves of townhouse rows split around the lane that ran through them.` : ''}`);
  L.push(`- Points: ${FIX.move_places.length} place points, ${FIX.move_people.length} home points and ${FIX.move_labels.length} labels moved. Roads: ${n(FIX.road_snaps.length)} road points snapped or pulled back.`);
  L.push(`- After the fixes, the same checks find ${vt.road} buildings on roads, ${vt.water + vt.marsh} in water or marsh, ${vt.overlap} overlapping pairs, ${vt.rail} on the rail line and ${vt.creek + vt.pier} on creeks or piers.${vsum ? ' Each of those is a flagged item below that needs your decision.' : ''}`);
  L.push('- No hero home changed. The nine character houses keep their Atlas footprints exactly, so the house models and `docs/site-specs.json` still fit.', '');
  L.push('## Counts by check', '');
  const DESC = { 'building-in-water': 'Footprint center, or over 25% of it, over open water', 'building-in-marsh': 'Footprint center, or over 25% of it, in the marsh', 'building-on-road': 'Footprint reaches more than 0.25 m into a road (bridges and footpaths ignored)', 'building-on-rail': 'Footprint on the rail bed', 'building-on-creek': 'Footprint on a creek (3 m each side)', 'building-on-pier': 'Land building on a pier or the boardwalk', 'building-overlap': 'Two footprints share more than 1 m2', 'misaligned-building': 'House, duplex, mobile home or townhouse 3 to 20 degrees off its street', 'road-into-building': 'Dead-end driveway or lane that runs into or through a building', 'road-gap': 'Road end that stops just short of the road it meets, or pokes just past it, without a shared point', 'road-dead-end': 'Main road (secondary or bigger) that stops dead in town', 'road-crosses-water': 'Road that is not a bridge, over open water for more than 15 m', 'bridge-dead-end': 'Bridge that ends over open water', 'dangling-stub': 'Dead-end service or track stub under 12 m that touches a building', 'address-missing': 'Home address with no building', 'address-point-mismatch': 'Point and address table disagree', 'place-off-site': 'Place point on a road, in water, or far from any building', 'label-placement': 'Label outside its neighborhood or off its water', 'canon-conflict': 'Register, gazetteer and map disagree (flagged only)' };
  L.push(T(TYPE_ORDER.filter(t => by_type[t]).map(t => [t, DESC[t] || '', n(cnt(t)), n(cfx(t)), n(cnt(t) - cfx(t))]), ['Check', 'What it means', 'Found', 'Fixed', 'Flagged']), '');
  L.push('## What I fixed, and how', '');
  const ex = []; const sand = ofType('building-on-road', o => o.ref.kind === 'mobile' && o.ref.road_name === 'Sand Hill Road'); if (sand.length) ex.push(`${sand.length} mobile homes in a column on Sand Hill Road`);
  const th = ofType('building-on-road', o => o.ref.kind === 'townhouse'); if (th.length) ex.push(`${th.length} townhouse rows that their own service lanes run through (10 clusters built the same way)`);
  const four = ofType('building-on-road', o => o.ref.road_name === 'Fourth Street' && o.ref.kind === 'shop'); if (four.length) ex.push('a shop in the middle of Fourth Street');
  const hosp = ofType('building-on-road', o => o.ref.places && o.ref.places.includes('hospital'))[0]; if (hosp) ex.push('Westport Hospital, which Patriots Boulevard, Down East Road and a service lane all ran through');
  L.push(`**Buildings on roads (${cnt('building-on-road')}).** Most are houses and mobile homes whose front corner reaches a meter or two into the street. Some are whole buildings standing in a road: ${ex.join('; ')}. I tried these fixes in order and kept the first one that worked: ${[['shift', 'a nudge of up to 4 m straight away from the road'], ['remove-mostly', 'removal when the building stood mostly on the road'], ['trim', 'trimming the side that faces the road, keeping at least 70% and never cutting much more than the part on the road'], ['move', 'a longer move into free ground, up to 10 m for an ordinary building, 60 m for a big one and 150 m for a named place'], ['trim-row', 'cutting end units off a townhouse or storefront row'], ['split', 'splitting a row in two where a lane runs through its middle'], ['remove-stray', 'removing a stray that nothing else could clear']].filter(([k]) => lad('building-on-road', k)).map(([k, t]) => `${t} (${lad('building-on-road', k)})`).join('; ')}. Before accepting a new position, I checked it against every road, neighbor, creek, the water and the marsh.`, '');
  const rail = ofType('building-on-rail'); if (rail.length) L.push(`**Buildings on the rail line (${rail.length}).** The main line runs straight through an apartment complex off Ocean Highway (around ${xy(rail.find(o => o.ref.kind === 'apartments')?.at || rail[0].at)}) and crosses its parking loop twice; it also clipped the corner of a big industrial building. What happened: ${rail.map(o => `${kindLabel(o.ref.building)} ${o.fix === 'remove' ? 'was removed' : /Moved/.test(o.detail) ? 'was ' + o.detail.match(/Moved [\d.]+ m/)[0].toLowerCase() : 'was trimmed'}`).join(', ')}. The complex itself still straddles the tracks, which is worth fixing at the source. Yard tracks that run up to a warehouse are rail spurs and were left alone.`, '');
  L.push(`**Overlapping buildings (${cnt('building-overlap')}).** All are small (1 to 2 m2): neighboring downtown storefronts and a few houses that touch. Each pair was nudged apart by less than a meter, or the shared wall was shaved by a few tenths of a meter.`, '');
  const turned = ofType('misaligned-building', o => o.action === 'fixed');
  L.push(`**Houses off square (${n(cnt('misaligned-building'))}).** I measured every house, duplex, mobile home and townhouse within 45 m of a street against the direction of the street right in front of it. ${n(alignStats.aligned)} of ${n(alignStats.checked)} were within 3 degrees. I turned ${n(turned.length)} that sat 3 to 20 degrees off about their own centers to face the street (median turn ${fmt(med(turned.map(o => Math.abs(o.ref.deviation_deg))))} degrees). I left alone ${alignStats.over20} houses more than 20 degrees off (corner lots and cul-de-sacs) and ${alignStats.keptForNeighbors} that match their square neighbors on curves and cul-de-sac bulbs, since those were placed that way on purpose.`, '');
  const gaps = ofType('road-gap'); const over = gaps.filter(o => o.ref.overshoot).length;
  L.push(`**Roads (${n(cnt('road-gap') + cnt('road-into-building'))}).** ${n(gaps.length)} road ends met another road without a shared point: ${n(gaps.length - over)} stopped just short of it and ${n(over)} poked just past it (median ${fmt(med(gaps.map(o => o.ref.gap_m)))} m, mostly rounding). Each end was snapped onto the road it meets, so routing works; a side street that stops at the curb of a wide road counts as meeting it. ${n(cfx('road-into-building'))} dead-end driveways and farm tracks ran into or through a building; most were cut back to stop at the wall, and where the road carries on past the building, the building moved instead. Bridges are never joined to the roads they pass over.`, '');
  const homes = ADDED.filter(x => x.info && x.info.type === 'home');
  if (homes.length) { L.push(`**Homes with no house (${homes.length}).** QA added a house and moved the home points onto it. It is marked "added by QA, proposed":`, ''); for (const x of homes) L.push(`- ${x.info.a.num} ${x.info.a.street} (${x.info.who}): a ${x.info.Wd} x ${x.info.Dp} m house, building index ${x.k}, on the ${x.info.side} (odd) side of the street, ${fmt(x.info.s)} m from its start, set back ${x.info.setback} m from the curb like nearby houses, at ${xy(x.info.c)}. ${x.info.how[0].toUpperCase() + x.info.how.slice(1)}. The old point was ${fmt(x.info.moved)} m away, in an empty field.`); L.push(''); }
  const sites = ADDED.filter(x => x.info && x.info.type === 'place');
  if (sites.length) { L.push(`**Places with nothing on the ground (${sites.length}).** These points sat in the marsh, in the river or in an empty lot, with no building of their kind nearby. QA added a proposed building for each, at the point when it was dry and free, otherwise on the nearest dry, free ground by a road, and moved the point onto it:`, ''); L.push(T(sites.map(x => [x.info.pl.name, x.info.pl.addr || '', `${x.info.dims.w} x ${x.info.dims.d} m ${x.info.kind}, ${x.info.dims.h} m tall`, x.k, xy(x.info.site.c), x.info.site.rad ? `${Math.round(x.info.site.rad)} m, by ${roadName(x.info.site.road.ri)}` : 'at its point']), ['Place', 'Address', 'Added building', 'Index', 'At (x, y)', 'Moved'])); L.push(''); }
  const bigMoves = ISSUES.filter(o => /^building-on/.test(o.type) && o.fix === 'replace' && /Moved [\d.]+ m/.test(o.detail)).map(o => [o.id, kindLabel(o.ref.building), o.ref.places ? o.ref.places.map(pname).join(', ') : '', o.detail.match(/Moved ([\d.]+) m/)[1] + ' m', xy(o.at)]).sort((a, b) => parseFloat(b[3]) - parseFloat(a[3]));
  if (bigMoves.length) { L.push(`**Buildings moved more than a nudge (${bigMoves.length}).** These stood across a road and had room nearby:`, ''); L.push(T(bigMoves, ['ID', 'Building', 'Place', 'Moved', 'Was at (x, y)'])); L.push(''); }
  const mvp = FIX.move_places.map(m => [pname(m.id), paddr(m.id), xy(m.was), xy(m.at), m.why.replace(/^[a-z-]+: /, '').replace(/^follows/, 'Follows').replace(/^moved/, 'Moved').replace(/^sits/, 'Sat').replace(/^is /, 'Was ')]);
  if (mvp.length) { L.push(`**Place points moved (${mvp.length}).** The people who live at a moved home point move with it.`, ''); L.push(T(mvp, ['Place', 'Address', 'Was at', 'Now at', 'Why'])); L.push(''); }
  const lbl = ofType('label-placement', o => o.action === 'fixed'); if (lbl.length) L.push(`**Labels (${lbl.length}).** ${lbl.map(o => o.detail).join(' ')}`, '');
  { // neighbors of the hero homes that QA touched (the lot rectangles in site-specs.json were drawn from the old neighbors)
    const lines = [];
    for (const h of (SITE && SITE.homes) || []) {
      const ch = []; for (const nb of h.neighbors_local || []) { const i = nb.i; if (!replaced.has(i) && !FIX.remove_buildings.includes(i)) continue; if (FIX.remove_buildings.includes(i)) { ch.push(`#${i} removed`); continue; } const d = dist(centroid(B[i].pts0), centroid(cur[i])); const why = replaced.get(i).why.split(':')[0]; ch.push(`#${i} ${why === 'misaligned-building' ? 'turned square' : 'moved'}${d >= 0.05 ? ` (center ${fmt(d)} m)` : ''}`); }
      if (ch.length) lines.push(`- ${h.id}: ${ch.join(', ')}.`);
    }
    if (lines.length) { L.push('**Next to the hero homes.** The hero footprints did not change, but QA touched a few neighbors. The lot rectangles in `docs/site-specs.json` were measured from the old neighbors; every change is small, so the lots still fit:', '', ...lines, ''); }
  }
  L.push('## Flagged for your decision', '');
  L.push('Canon conflicts are only flagged: I changed nothing that the register or your books settle.', '');
  const cc = ofType('canon-conflict', o => o.severity !== 'low'); const ccl = ofType('canon-conflict', o => o.severity === 'low');
  L.push(T(cc.map(o => [o.id, o.detail, xy(o.at)]), ['ID', 'Conflict', 'Atlas x, y']), '');
  if (ccl.length) { L.push('Smaller notes:', ''); for (const o of ccl) L.push(`- ${o.id}: ${o.detail}`); L.push(''); }
  const need = ISSUES.filter(o => o.action === 'flagged' && !['canon-conflict', 'address-point-mismatch'].includes(o.type) && o.severity !== 'low');
  if (need.length) { L.push('Map items I left alone because a fix needs your call:', ''); L.push(T(need.map(o => [o.id, o.type, o.detail, xy(o.at)]), ['ID', 'Check', 'Detail', 'Atlas x, y'])); L.push(''); }
  const minor = ISSUES.filter(o => o.action === 'flagged' && !['canon-conflict', 'address-point-mismatch'].includes(o.type) && o.severity === 'low');
  if (minor.length) { L.push(`Minor items left as they are: ${minor.map(o => `${o.id} (${o.type === 'misaligned-building' ? `${kindLabel(o.ref.building)}, ${fmt(Math.abs(o.ref.deviation_deg))} degrees off; turning it would hit a neighbor or road` : o.detail.split('.')[0]})`).join('; ')}.`, ''); }
  const info = ofType('address-point-mismatch', o => o.action === 'flagged');
  if (info.length) { L.push('Points that sit on a different building than the address table gives (kept, since the point usually shows what you meant):', ''); for (const o of info) L.push(`- ${o.id}: ${o.detail}`); L.push(''); }
  L.push('## Most important items', '');
  const actionText = o => { if (o.action !== 'fixed') return 'flagged'; const ss = o.detail.split(/(?<=\.)\s+(?=[A-Z])/); const keep = ss.slice(1).filter(t => !/^It carries/.test(t)); return (keep.length ? keep.join(' ') : ss[ss.length - 1]).replace(/\.$/, ''); };
  const firstSentence = t => t.split(/(?<=[a-z0-9")])\.\s+(?=[A-Z])/)[0].replace(/\.$/, '');
  const key = []; const K = (o, what, name) => { if (o) key.push([o.id, what, name || '', xy(o.at), actionText(o)]); };
  for (const o of ofType('address-missing', o => o.fix === 'add')) K(o, `${o.ref.who}: no house at ${o.ref.addr}`, o.ref.addr);
  for (const o of ofType('place-off-site', o => o.fix === 'add')) K(o, `${pname(o.ref.place)}: no building`, paddr(o.ref.place));
  for (const o of ofType('building-on-road', o => o.ref.places && o.ref.places.some(id => placeById.has(id)))) K(o, `${o.ref.places.filter(id => placeById.has(id)).map(pname).join(', ')} stood on ${o.ref.road_name || 'a service road'}`, o.ref.places.map(paddr).filter(Boolean).join(', '));
  for (const o of ofType('place-off-site', o => o.fix === 'move' && o.ref.to_building != null)) K(o, `${pname(o.ref.place)}: point off its building`, paddr(o.ref.place));
  for (const o of ofType('bridge-dead-end')) K(o, 'Bridge that ends over the water (the county center driveway)', o.ref.road_name);
  for (const o of ofType('road-dead-end')) K(o, `${o.ref.road_name} stops dead`, o.ref.road_name);
  for (const o of ofType('building-on-rail')) K(o, `${kindLabel(o.ref.building)} on the rail line`, '');
  for (const o of ofType('label-placement')) K(o, `Label "${o.ref.label}" off its water`, o.ref.label);
  for (const o of ofType('canon-conflict', o => o.severity === 'medium')) K(o, `Canon: ${firstSentence(o.detail)}`, '');
  L.push(T(key, ['ID', 'Item', 'Address or name', 'Atlas x, y', 'What happened']), '');
  L.push('## Verification', '');
  L.push('After applying every fix in `data/qa.json` to the Atlas, I ran the building checks again on the result, including the added buildings:', '');
  L.push(T(Object.entries(VERIFY).map(([k, v]) => [k === 'overlap' ? 'Overlapping pairs (over 1 m2)' : k === 'water' ? 'Buildings over open water' : k === 'marsh' ? 'Buildings in the marsh' : k === 'road' ? 'Buildings on roads' : `Buildings on ${k === 'rail' ? 'the rail line' : k + 's'}`, v.length, unexplained[k].length]), ['Check', 'Remaining', 'Not covered by a flag']), '');
  L.push(vsum ? 'Everything that remains is one of the flagged items above.' : 'Nothing remains. The pier bar building stands over the water on its pier, as it should, and is not counted.', '');
  L.push(`The footprints for this check are rebuilt from the fix lists exactly as written to \`data/qa.json\`. I also checked that ${SNAP_CHECK.off ? `${SNAP_CHECK.checked - SNAP_CHECK.off} of ${SNAP_CHECK.checked}` : `all ${SNAP_CHECK.checked}`} snapped road ends sit on the road they join (within 2 cm), that no hero home appears in the fixes, and that no building is both removed and replaced.`, '');
  L.push('## How the checks work', '');
  L.push('- Roads are measured with these half-widths: trunk 7.5 m, primary 6.5, secondary 5.5, tertiary 4.5, residential 3.75, service 2.75, track 2, motorway 9. Bridges (raised) and footpaths are ignored for buildings. An intrusion counts when it is deeper than 0.25 m, because Atlas coordinates are rounded to half a meter (buildings) and a meter (roads). The rail bed is 2.5 m each side of the main line and 2 m for yard tracks; creeks 3 m; piers 2 m and the downtown boardwalk 3 m.');
  L.push('- Land and water come from the Atlas land polygons (outer ring land, inner rings water), and the marsh from the marsh polygons. Footprints are sampled on a 6 x 6 grid for water and marsh, and 10 x 10 for roads.');
  L.push('- Overlaps are exact convex polygon intersections. A spatial grid keeps the whole run to a few seconds.');
  L.push('- A road end counts as a gap when it is 0.3 to 4 m from another road, or within the other road\'s half-width plus 1 m (a side street that stops at the curb of a wide road). Ends are snapped to a vertex of the other road when one is within 1.5 m, otherwise onto its centerline.');
  L.push(`- Street numbers in the Atlas follow one rule: a house number is about ${Math.round(MODEL.a)} + ${MODEL.b.toFixed(3)} x its distance in meters from the street's end nearest Courthouse Square (1,000 per mile), with odd numbers on the ${MODEL.oddSide} going outward (${n(MODEL.oddLeft)} of ${n(MODEL.oddLeft + MODEL.oddRight)} odd numbers). I fitted this on ${MODEL.streets} streets, and it is what placed the added Chadwick house.`);
  L.push(`- ${ADDR_ONLY_GAZ.length} places sit on a civic or commercial building that has no number in the Atlas address table. For those the gazetteer address is the only one, which is fine.`);
  L.push('- Hero homes (`docs/site-specs.json`) are never changed. Buildings that carry a named place or a character\'s home are never removed; when one had to move off a road, its point moved with it. Landmark builders (the water tower, for example) should place their models on the footprint from `data/qa.json` when it lists the building.', '');
  L.push('## Pictures', '');
  for (const p of plots) L.push(`- \`${p.file}\`: ${p.title}. ${p.note}`);
  L.push('', 'In each picture, the left half is the Atlas as it is and the right half has the fixes applied. Red means removed, orange changed, green added by QA, and blue dots are moved points (a thin line joins each to where it was).', '');
  return L.join('\n');
}
