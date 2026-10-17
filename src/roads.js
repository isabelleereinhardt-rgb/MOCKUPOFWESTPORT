// Roads, sidewalks, bridges, rail and piers, all generated from the Atlas polylines.
// Polyline points carry Atlas coordinates (x, y), arc length s, a left normal (nx, ny),
// a deck height h (bridges only), distance to the nearest junction j, and a downtown flag.
import * as THREE from 'three';
import { patch, loadTex } from './shaders.js';
import { CLS, HALF, WATER_Y, pointInRing, luAt, polyLen, inHeroLot } from './core.js';

const ORDER = ['path', 'track', 'service', 'residential', 'tertiary', 'secondary', 'primary', 'trunk', 'motorway'];
const LAYER0 = 8;     // ground uses 0..6, sidewalks 7
const WALK = 9;       // class id for sidewalk ribbons in the road shader
export const PIER_DECK_Y = WATER_Y + 1.9;

const ROAD_ATLAS = ['#F5CC78', '#FAE4A2', '#FFF2CC', '#FFFFFF', '#FFFFFF', '#FBFAF7', '#B9A88E', '#EAE5DC', '#F5CC78', '#ECE7DD'];
const ROAD_SHADOWS = ['#7A6534', '#4C4636', '#3B3A40', '#34343B', '#2E2E35', '#26262C', '#3A352E', '#2A2A30', '#7A6534', '#1B1B20'];

// ---------------------------------------------------------------- materials
export function roadMaterial(layer) {
  const m = new THREE.MeshStandardMaterial({ name: 'road' + layer, roughness: 0.88, metalness: 0 });
  m.depthWrite = layer >= 18; // ground-level ribbons paint in order; bridge decks write depth (layers 18+)
  patch(m, {
    key: 'road',
    uniforms: {
      tAsphalt: { value: loadTex('assets/tex/pave_asphalt.jpg') }, tConcrete: { value: loadTex('assets/tex/pave_concrete.jpg') }, tGravel: { value: loadTex('assets/tex/pave_gravel.jpg') },
      uRoadA: { value: ROAD_ATLAS.map(c => new THREE.Color(c)) }, uRoadS: { value: ROAD_SHADOWS.map(c => new THREE.Color(c)) },
    },
    vHead: 'attribute vec4 aRoad; attribute float aCls; varying vec4 vRoad; varying float vCls;',
    vMain: 'vRoad = aRoad; vCls = aCls;',
    fHead: 'uniform sampler2D tAsphalt; uniform sampler2D tConcrete; uniform sampler2D tGravel; uniform vec3 uRoadA[10]; uniform vec3 uRoadS[10]; varying vec4 vRoad; varying float vCls;',
    color: /* glsl */`
      // vRoad: x = meters along, y = signed meters across (left +), z = half width, w = junction distance (+100000 downtown)
      vec2 p = vec2(vWPos.x, -vWPos.z);
      float cls = floor(vCls + .5);
      float u = vRoad.x, a = vRoad.y, hw = vRoad.z, aa = abs(a);
      float town = step(50000., vRoad.w); float j = vRoad.w - town * 100000.;
      float cd = length(vWPos - cameraPosition);
      if (uStyle > .5 && uStyle < 2.5) {
        vec3 c = uStyle < 1.5 ? uRoadA[int(cls)] : uRoadS[int(cls)];
        vec3 cs = uStyle < 1.5 ? srgb(vec3(.74, .70, .64)) : srgb(vec3(.043));
        float casing = cls < 8.5 ? smoothstep(hw - .9, hw - .6, aa) : 0.;
        col = mix(c, cs, casing * .9); rough = 1.;
      } else if (uStyle > 2.5) { col = cls == 9. ? vec3(.9) : vec3(.78); rough = .9; }
      else if (cls == 6.) {                                    // dirt and gravel track
        vec3 dirt = texture2D(tGravel, p / 4.).rgb * vec3(1., .93, .8);
        float rut = smoothstep(.45, .1, abs(aa - .85));
        col = mix(dirt, dirt * .72, rut);
        col = mix(col, col * vec3(.8, .95, .7), smoothstep(.15, 0., aa) * .6); rough = .95;
      } else if (cls == 9. || cls == 7.) {                     // sidewalks and paths
        vec3 c = texture2D(tConcrete, p / 3.).rgb * (.92 + .1 * fbm(p * .2));
        float joint = step(fract(u / 1.524), .012);
        col = c * (1. - .3 * joint * smoothstep(250., 60., cd)); rough = .85;
      } else {
        vec3 asp = texture2D(tAsphalt, p / 4.).rgb * (.8 + .32 * fbm(p * .045));
        if (cls == 5.) asp *= vec3(1.12, 1.11, 1.08);          // older, greyer service drives
        float lp = fract(aa / 3.6);
        float wear = smoothstep(.16, 0., abs(lp - .27)) + smoothstep(.16, 0., abs(lp - .73));
        col = asp * (1. - .07 * wear);
        col *= 1. - .1 * smoothstep(.74, .8, fbm(p * .09 + 3.));                               // patches
        col *= 1. - .25 * smoothstep(.012, 0., abs(fbm(p * .35) - .5)) * smoothstep(300., 80., cd); // cracks
        float gut = smoothstep(hw - .5, hw - .32, aa) * step(cls, 4.5) * step(1.5, cls);
        col = mix(col, texture2D(tConcrete, p / 3.).rgb * .92, gut);
        float vis = smoothstep(.8, 1.6, j) * smoothstep(2200., 600., cd);
        float dash = step(fract(u / 12.), .25);
        float yel = 0., wht = 0.;
        if (cls <= 1. || cls == 8.) {
          yel = step(abs(aa - .2), .065);
          wht = step(abs(aa - (cls == 0. ? 3.7 : 3.25)), .07) * dash + step(abs(aa - (hw - .65)), .08);
        } else if (cls == 2.) {
          yel = step(abs(aa - .17), .06);
          wht = step(abs(aa - (hw - .55)), .07);
        } else if (cls == 3.) {
          yel = step(aa, .065) * dash;
        }
        col = mix(col, srgb(vec3(.93, .74, .22)), yel * vis * .92);
        col = mix(col, vec3(.88), wht * vis * .9);
        float cw = town * step(.7, j) * step(j, 3.6) * step(aa, hw - .45) * step(.5, fract(a / 1.1));
        col = mix(col, vec3(.86), cw * smoothstep(1000., 300., cd));
        rough = .9 - (yel + wht + cw) * .2;
      }
    `,
  });
  return m;
}

function railMaterial() {
  const m = new THREE.MeshStandardMaterial({ name: 'rail', roughness: 0.9 });
  m.depthWrite = false;
  patch(m, {
    key: 'rail', uniforms: { tGravel: { value: loadTex('assets/tex/pave_gravel.jpg') } },
    vHead: 'attribute vec4 aRoad; varying vec4 vRoad;', vMain: 'vRoad = aRoad;',
    fHead: 'uniform sampler2D tGravel; varying vec4 vRoad;',
    color: /* glsl */`
      vec2 p = vec2(vWPos.x, -vWPos.z); float a = abs(vRoad.y), u = vRoad.x;
      if (uStyle > .5 && uStyle < 1.5) { col = srgb(vec3(.55, .52, .49)) * (step(fract(u / 6.), .5) * .3 + .7); rough = 1.; }
      else if (uStyle > 1.5 && uStyle < 2.5) { col = srgb(vec3(.33, .32, .3)) * (step(fract(u / 6.), .5) * .4 + .6); rough = 1.; }
      else if (uStyle > 2.5) { col = vec3(.7); }
      else {
        col = texture2D(tGravel, p / 3.).rgb * vec3(.85, .82, .8);
        float tie = step(fract(u / .6), .38) * step(a, 1.3);
        col = mix(col, srgb(vec3(.24, .19, .15)), tie * .9);
        float railL = step(abs(a - .72), .04);
        col = mix(col, srgb(vec3(.55, .55, .56)), railL);
        rough = mix(.95, .35, railL); metal = railL * .8;
        col *= 1. - .25 * smoothstep(1.4, 2., a);
      }
    `,
  });
  return m;
}

function deckMaterial() {
  const m = new THREE.MeshStandardMaterial({ name: 'pierdeck', roughness: 0.92 });
  patch(m, {
    key: 'pierdeck',
    vHead: 'attribute vec4 aRoad; varying vec4 vRoad;', vMain: 'vRoad = aRoad;', fHead: 'varying vec4 vRoad;',
    color: /* glsl */`
      vec2 p = vec2(vWPos.x, -vWPos.z); float u = vRoad.x, a = vRoad.y;
      if (uStyle > .5 && uStyle < 1.5) { col = srgb(vec3(.72, .65, .54)); rough = 1.; }
      else if (uStyle > 1.5 && uStyle < 2.5) { col = srgb(vec3(.24, .22, .19)); rough = 1.; }
      else if (uStyle > 2.5) { col = vec3(.85); }
      else {
        float board = floor(u / .15); float gap = step(fract(u / .15), .08);
        float tone = .78 + .3 * h12(vec2(board, 1.)) ;
        col = srgb(vec3(.52, .46, .38)) * tone * (.85 + .2 * fbm(vec2(u * .3, a * 4.) + board)) * (1. - .55 * gap);
      }
    `,
  });
  return m;
}

// ---------------------------------------------------------------- builders
class RB { // ribbons with road attributes
  constructor() { this.p = []; this.n = []; this.r = []; this.c = []; this.i = []; }
  v(wx, wy, wz, along, across, half, j, cls, nx = 0, ny = 1, nz = 0) { this.p.push(wx, wy, wz); this.n.push(nx, ny, nz); this.r.push(along, across, half, j); this.c.push(cls); return this.p.length / 3 - 1; }
  tri(a, b, c) { this.i.push(a, b, c); }
  geometry() {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(this.n, 3));
    g.setAttribute('aRoad', new THREE.Float32BufferAttribute(this.r, 4));
    g.setAttribute('aCls', new THREE.Float32BufferAttribute(this.c, 1));
    g.setIndex(this.p.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(this.i, 1) : new THREE.Uint16BufferAttribute(this.i, 1));
    g.computeBoundingSphere(); return g;
  }
}

export class SB { // plain structures: quads, boxes, beams
  constructor() { this.p = []; this.n = []; this.i = []; }
  quad(a, b, c, d) {
    const n = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(d, a)).normalize();
    const o = this.p.length / 3; for (const v of [a, b, c, d]) { this.p.push(v.x, v.y, v.z); this.n.push(n.x, n.y, n.z); }
    this.i.push(o, o + 1, o + 2, o, o + 2, o + 3);
  }
  box(c, along, len, wid, hgt) { // c: bottom-center Vector3, along: unit Vector3 in xz
    const ax = along.clone().multiplyScalar(len / 2), bx = new THREE.Vector3(-along.z, 0, along.x).multiplyScalar(wid / 2), up = new THREE.Vector3(0, hgt, 0);
    const P = (sa, sb, top) => c.clone().addScaledVector(ax, sa).addScaledVector(bx, sb).addScaledVector(up, top);
    const v = [P(-1, -1, 0), P(1, -1, 0), P(1, 1, 0), P(-1, 1, 0), P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1)];
    this.quad(v[4], v[5], v[6], v[7]); this.quad(v[3], v[2], v[1], v[0]);
    this.quad(v[0], v[1], v[5], v[4]); this.quad(v[1], v[2], v[6], v[5]); this.quad(v[2], v[3], v[7], v[6]); this.quad(v[3], v[0], v[4], v[7]);
  }
  beam(a, b, t) {
    const d = new THREE.Vector3().subVectors(b, a); if (d.length() < 1e-3) return;
    const z = d.clone().normalize(); const x = Math.abs(z.y) > .9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0).cross(z).normalize(); const y = z.clone().cross(x);
    const c = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => x.clone().multiplyScalar(sx * t / 2).addScaledVector(y, sy * t / 2));
    for (let k = 0; k < 4; k++) { const p0 = c[k], p1 = c[(k + 1) % 4]; this.quad(a.clone().add(p0), a.clone().add(p1), b.clone().add(p1), b.clone().add(p0)); }
  }
  geometry() {
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(this.n, 3));
    g.setIndex(this.p.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(this.i, 1) : new THREE.Uint16BufferAttribute(this.i, 1)); g.computeBoundingSphere(); return g;
  }
}

// ---------------------------------------------------------------- polyline helpers
export function resample(p, cuts, maxSeg = 40) {
  const out = []; let s = 0; const cs = [...new Set(cuts.map(c => Math.round(c * 10) / 10))].sort((a, b) => a - b); let ci = 0;
  out.push({ x: p[0], y: p[1], s: 0 });
  for (let i = 2; i < p.length; i += 2) {
    const x0 = p[i - 2], y0 = p[i - 1], x1 = p[i], y1 = p[i + 1], L = Math.hypot(x1 - x0, y1 - y0); if (L < 1e-6) continue;
    const ts = []; while (ci < cs.length && cs[ci] < s + L - 0.05) { if (cs[ci] > s + 0.05) ts.push(cs[ci] - s); ci++; }
    const n = Math.ceil(L / maxSeg); for (let k = 1; k < n; k++) ts.push(L * k / n);
    ts.sort((a, b) => a - b);
    for (const t of ts) out.push({ x: x0 + (x1 - x0) * t / L, y: y0 + (y1 - y0) * t / L, s: s + t });
    s += L; out.push({ x: x1, y: y1, s });
  }
  return out;
}

export function frames(P) { // left normal per vertex, miter-scaled
  const n = P.length;
  for (let i = 0; i < n; i++) {
    const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)], c = P[i];
    let d0x = c.x - a.x, d0y = c.y - a.y, d1x = b.x - c.x, d1y = b.y - c.y;
    let l0 = Math.hypot(d0x, d0y), l1 = Math.hypot(d1x, d1y);
    if (l0 < 1e-6) { d0x = d1x; d0y = d1y; l0 = l1; } if (l1 < 1e-6) { d1x = d0x; d1y = d0y; l1 = l0; }
    d0x /= l0 || 1; d0y /= l0 || 1; d1x /= l1 || 1; d1y /= l1 || 1;
    let tx = d0x + d1x, ty = d0y + d1y; const tl = Math.hypot(tx, ty) || 1; tx /= tl; ty /= tl;
    const cosh = Math.max(0.5, tx * d1x + ty * d1y);
    c.nx = -ty / cosh; c.ny = tx / cosh; c.tx = tx; c.ty = ty; c.turn = Math.acos(Math.max(-1, Math.min(1, d0x * d1x + d0y * d1y)));
    if (c.h == null) c.h = 0; if (c.j == null) c.j = 1e4; if (c.town == null) c.town = 0;
  }
  return P;
}

// strip between signed offsets o0 < o1 (left positive)
function band(B, P, o0, o1, half, cls, dy = 0) {
  const base = B.p.length / 3;
  for (const v of P) {
    const jw = v.j + (v.town ? 100000 : 0);
    B.v(v.x + v.nx * o0, v.h + dy, -(v.y + v.ny * o0), v.s, o0, half, jw, cls);
    B.v(v.x + v.nx * o1, v.h + dy, -(v.y + v.ny * o1), v.s, o1, half, jw, cls);
  }
  for (let k = 0; k < P.length - 1; k++) { const a = base + 2 * k; B.tri(a, a + 3, a + 1); B.tri(a, a + 2, a + 3); }
}

function disc(B, v, half, cls) {
  const seg = 16, c = B.v(v.x, v.h, -v.y, v.s, 0, half, 0, cls), first = B.p.length / 3;
  for (let k = 0; k < seg; k++) { const a = k / seg * Math.PI * 2; B.v(v.x + Math.cos(a) * half, v.h, -(v.y + Math.sin(a) * half), v.s, half, half, 0, cls); }
  for (let k = 0; k < seg; k++) B.tri(c, first + k, first + ((k + 1) % seg));
}

// ---------------------------------------------------------------- junctions
function analyzeJunctions(D) {
  const key = (x, y) => Math.round(x * 2) + ',' + Math.round(y * 2);
  const nodes = new Map();
  for (const r of D.roads) {
    if (r.cls === 'path') continue; const p = r.pts;
    for (let i = 0; i < p.length; i += 2) { const k = key(p[i], p[i + 1]); let e = nodes.get(k); if (!e) nodes.set(k, e = new Map()); e.set(r.i, Math.max(e.get(r.i) || 0, HALF[r.cls])); }
  }
  const J = new Map();
  const add = (ri, s, cross) => { let a = J.get(ri); if (!a) J.set(ri, a = []); a.push({ s, cross }); };
  for (const r of D.roads) {
    if (r.cls === 'path') continue; const p = r.pts; let s = 0;
    for (let i = 0; i < p.length; i += 2) {
      if (i) s += Math.hypot(p[i] - p[i - 2], p[i + 1] - p[i - 1]);
      const e = nodes.get(key(p[i], p[i + 1]));
      if (e && e.size > 1) { let cross = 0; for (const [ri, h] of e) if (ri !== r.i) cross = Math.max(cross, h); add(r.i, s, cross); }
    }
  }
  // T-junctions: an endpoint of one road on the interior of another road's segment
  for (const r of D.roads) {
    if (r.cls === 'path') continue;
    for (const k of [0, r.pts.length - 2]) {
      const x = r.pts[k], y = r.pts[k + 1];
      D.rGrid.query(x - 1.5, y - 1.5, x + 1.5, y + 1.5, id => {
        const sg = D.segs[id]; if (sg[4] === r.i) return; const o = D.roads[sg[4]]; if (o.cls === 'path' || o.bridge !== r.bridge) return;
        const dx = sg[2] - sg[0], dy = sg[3] - sg[1], L2 = dx * dx + dy * dy; if (!L2) return;
        const t = ((x - sg[0]) * dx + (y - sg[1]) * dy) / L2; if (t <= 0.01 || t >= 0.99) return;
        if (Math.hypot(sg[0] + t * dx - x, sg[1] + t * dy - y) > 1.2) return;
        let s = 0; const q = o.pts;
        for (let i = 2; i < q.length; i += 2) { if (q[i - 2] === sg[0] && q[i - 1] === sg[1] && q[i] === sg[2] && q[i + 1] === sg[3]) { s += t * Math.sqrt(L2); break; } s += Math.hypot(q[i] - q[i - 2], q[i + 1] - q[i - 1]); }
        add(o.i, s, HALF[r.cls]); add(r.i, k ? polyLen(r.pts) : 0, HALF[o.cls]);
      });
    }
  }
  return J;
}

// deck height along a bridge, ramping up from both ends
export function bridgeProfile(r, L) {
  const H = r.name === 'Dalton Bridge' ? 9 : L > 600 ? 19 : L > 250 ? 8 : 4.5;
  const ramp = Math.min(L * 0.32, H * 14);
  return { H, f: s => H * Math.min(1, sm(s / ramp), sm((L - s) / ramp)) };
}
const sm = t => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));

// Height of the road surface at an Atlas point (bridge decks rise above the water; everything else is 0)
export function roadHeightAt(D, x, y) {
  for (const b of D.bridges || []) {
    const P = b.P; if (!P) continue;
    for (let k = 0; k < P.length - 1; k++) {
      const a = P[k], c = P[k + 1], dx = c.x - a.x, dy = c.y - a.y, L2 = dx * dx + dy * dy; if (!L2) continue;
      const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / L2));
      if (Math.hypot(a.x + dx * t - x, a.y + dy * t - y) < HALF[b.road.cls] + 1) return a.h + (c.h - a.h) * t;
    }
  }
  return 0;
}

// ---------------------------------------------------------------- build everything
export function buildRoads(D) {
  const group = new THREE.Group(); group.name = 'roads';
  const J = analyzeJunctions(D);
  const layers = new Map(); const RBfor = l => { let b = layers.get(l); if (!b) layers.set(l, b = new RB()); return b; };
  const walks = new RB(), railB = new RB(), deckB = new RB();
  const concrete = new SB(), steel = new SB(), wood = new SB();
  const city = D.limits && D.limits[0];
  const townAt = (x, y) => { if (Math.hypot(x, y) < 700) return true; const l = luAt(D, x, y); return !!l && l.kind === 'commercial'; };
  const developed = (x, y) => {
    if (!city || !pointInRing(x, y, city)) return false;
    let n = 0; D.bGrid.query(x - 45, y - 45, x + 45, y + 45, () => { n++; if (n >= 2) return false; }); return n >= 2;
  };
  D.bridges = [];
  for (const r of D.roads) {
    if (r.cls === 'path') continue;
    const half = HALF[r.cls], cls = CLS.indexOf(r.cls), L = polyLen(r.pts); if (L < 0.5) continue;
    const js = J.get(r.i) || [];
    const cuts = [];
    for (const j of js) for (const o of [-j.cross - 4, -j.cross - 0.8, 0, j.cross + 0.8, j.cross + 4]) { const c = j.s + o; if (c > 0 && c < L) cuts.push(c); }
    const P = frames(resample(r.pts, cuts, r.bridge ? 10 : 40));
    const prof = r.bridge ? bridgeProfile(r, L) : null;
    const townRoad = !r.bridge && ['residential', 'tertiary', 'secondary', 'primary'].includes(r.cls);
    for (const v of P) {
      let jd = 1e4; for (const j of js) jd = Math.min(jd, Math.abs(v.s - j.s) - j.cross);
      v.j = jd; v.h = prof ? prof.f(v.s) : 0; v.town = townRoad && townAt(v.x, v.y) ? 1 : 0;
    }
    const layer = LAYER0 + ORDER.indexOf(r.cls) + (r.bridge ? 10 : 0);
    const B = RBfor(layer);
    band(B, P, -half, half, half, cls);
    const isJ = s => js.some(j => Math.abs(j.s - s) < 0.5);
    P.forEach((v, k) => { if (k === 0 || k === P.length - 1 || v.turn > 0.45 || isJ(v.s)) disc(B, v, half, cls); });
    if (r.bridge) { D.bridges.push({ road: r, L, H: prof.H, prof, P }); bridgeStructure(concrete, steel, P, half, r, prof); continue; }
    if (townRoad) {
      let run = [];
      const flush = () => {
        if (run.length > 1) {
          const tw = run[Math.floor(run.length / 2)].town;
          const inner = tw ? half + 0.05 : half + 1.8, outer = tw ? half + 3.4 : half + 3.3;
          band(walks, run, inner, outer, half, WALK, 0.0); band(walks, run, -outer, -inner, half, WALK, 0.0);
        }
        run = [];
      };
      // modeled lots own their frontage (fence, walk, drive), so the generic sidewalk stops at their edges
      for (const v of P) { if (v.j > 1.5 && developed(v.x, v.y) && !inHeroLot(D, v.x + v.nx * (half + 2.5), v.y + v.ny * (half + 2.5), 0.5) && !inHeroLot(D, v.x - v.nx * (half + 2.5), v.y - v.ny * (half + 2.5), 0.5)) run.push(v); else flush(); }
      flush();
    }
  }
  for (const [layer, B] of layers) { const m = new THREE.Mesh(B.geometry(), roadMaterial(layer)); m.receiveShadow = true; m.name = 'road-' + layer; m.renderOrder = 10 + layer; group.add(m); }
  if (walks.p.length) { const m = new THREE.Mesh(walks.geometry(), roadMaterial(7)); m.receiveShadow = true; m.name = 'sidewalks'; m.renderOrder = 17; group.add(m); }
  for (const rl of D.rail) { const P = frames(resample(rl.pts, [], 30)); band(railB, P, -2.0, 2.0, 2.0, 0); }
  if (railB.p.length) { const m = new THREE.Mesh(railB.geometry(), railMaterial()); m.receiveShadow = true; m.name = 'rail'; m.renderOrder = 17.5; group.add(m); }
  D.pierInfo = [];
  D.piers.forEach((pp, i) => { const L = polyLen(pp); const w = L > 250 ? 6 : L > 60 ? 3 : 2.2; D.pierInfo.push({ i, L, w }); pierStructure(wood, deckB, pp, w); });
  const mats = {
    concrete: new THREE.MeshStandardMaterial({ name: 'bridge-concrete', color: 0xb9b4aa, roughness: 0.85, side: THREE.DoubleSide }),
    steel: new THREE.MeshStandardMaterial({ name: 'bridge-steel', color: 0x4f5d63, roughness: 0.5, metalness: 0.65, side: THREE.DoubleSide }),
    wood: new THREE.MeshStandardMaterial({ name: 'pier-wood', color: 0x6f604e, roughness: 0.92, side: THREE.DoubleSide }),
  };
  for (const [sb, mat, nm] of [[concrete, mats.concrete, 'bridge-structure'], [steel, mats.steel, 'bridge-steel'], [wood, mats.wood, 'pier-structure']]) {
    if (!sb.p.length) continue; const m = new THREE.Mesh(sb.geometry(), mat); m.castShadow = true; m.receiveShadow = true; m.name = nm; m.userData.styleable = true; group.add(m);
  }
  if (deckB.p.length) { const m = new THREE.Mesh(deckB.geometry(), deckMaterial()); m.castShadow = true; m.receiveShadow = true; m.name = 'pier-deck'; group.add(m); }
  return group;
}

// ---------------------------------------------------------------- bridges
function bridgeStructure(concrete, steel, P, half, r, prof) {
  const W = (v, o, dy) => new THREE.Vector3(v.x + v.nx * o, v.h + dy, -(v.y + v.ny * o));
  const edge = half + 0.35;
  for (let k = 0; k < P.length - 1; k++) {
    const a = P[k], b = P[k + 1];
    for (const side of [1, -1]) {
      const o = side * edge;
      // deck fascia
      const a0 = W(a, o, 0.05), b0 = W(b, o, 0.05), a1 = W(a, o, -1.3), b1 = W(b, o, -1.3);
      if (side > 0) concrete.quad(a1, b1, b0, a0); else concrete.quad(b1, a1, a0, b0);
      // parapet: inner face, top, outer face
      const oi = side * (half + 0.05), oo = side * (half + 0.35);
      const ai = W(a, oi, 0), bi = W(b, oi, 0), ait = W(a, oi, 0.9), bit = W(b, oi, 0.9), aot = W(a, oo, 0.9), bot = W(b, oo, 0.9), ao = W(a, oo, 0.05), bo = W(b, oo, 0.05);
      if (side > 0) { concrete.quad(bi, ai, ait, bit); concrete.quad(ait, aot, bot, bit); concrete.quad(ao, bo, bot, aot); }
      else { concrete.quad(ai, bi, bit, ait); concrete.quad(bit, bot, aot, ait); concrete.quad(bo, ao, aot, bot); }
    }
    // deck soffit
    concrete.quad(W(a, -edge, -1.3), W(b, -edge, -1.3), W(b, edge, -1.3), W(a, edge, -1.3));
  }
  // piers every ~32 m where the deck is above the water
  const L = P[P.length - 1].s; const n = Math.max(1, Math.round(L / 32));
  for (let k = 1; k < n; k++) {
    const s = L * k / n; let i = 1; while (i < P.length - 1 && P[i].s < s) i++;
    const a = P[i - 1], b = P[i], t = (s - a.s) / Math.max(1e-6, b.s - a.s);
    const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t, h = prof.f(s);
    if (h < 2.2) continue;
    const along = new THREE.Vector3(a.tx, 0, -a.ty).normalize();
    const across = new THREE.Vector3(-along.z, 0, along.x);
    for (const sd of [-1, 1]) {
      const c = new THREE.Vector3(x, WATER_Y, -y).addScaledVector(across, sd * half * 0.55);
      concrete.box(c, along, 1.6, 1.6, h - 1.3 - WATER_Y);
    }
    concrete.box(new THREE.Vector3(x, h - 2.1, -y), across, half * 2 + 0.6, 1.8, 0.8); // pier cap
  }
  // Dalton Bridge: a steel through truss along both parapets
  if (r.name === 'Dalton Bridge') {
    const T = 7.5, step = 9;
    const at = s => { let i = 1; while (i < P.length - 1 && P[i].s < s) i++; const a = P[i - 1], b = P[i], t = Math.min(1, Math.max(0, (s - a.s) / Math.max(1e-6, b.s - a.s))); return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, nx: a.nx, ny: a.ny, h: prof.f(s) }; };
    const flat = P.filter(v => v.h > prof.H - 0.05); if (flat.length < 2) return;
    const s0 = flat[0].s, s1 = flat[flat.length - 1].s, m = Math.max(2, Math.round((s1 - s0) / step));
    for (const side of [1, -1]) {
      const o = side * (half + 0.6);
      const pt = (s, dy) => { const v = at(s); return new THREE.Vector3(v.x + v.nx * o, v.h + dy, -(v.y + v.ny * o)); };
      for (let k = 0; k <= m; k++) {
        const s = s0 + (s1 - s0) * k / m;
        steel.beam(pt(s, 0.2), pt(s, T), 0.35);                                  // verticals
        if (k < m) {
          const s2 = s0 + (s1 - s0) * (k + 1) / m;
          steel.beam(pt(s, T), pt(s2, T), 0.5); steel.beam(pt(s, 0.3), pt(s2, 0.3), 0.5); // chords
          steel.beam(k < m / 2 ? pt(s, T) : pt(s, 0.3), k < m / 2 ? pt(s2, 0.3) : pt(s2, T), 0.28); // diagonals
        }
      }
      steel.beam(pt(s0, 0.2), pt(s0 - 6, -0.3), 0.5); steel.beam(pt(s1, 0.2), pt(s1 + 6, -0.3), 0.5);
    }
    for (let k = 0; k <= m; k += 2) { // top lateral bracing
      const s = s0 + (s1 - s0) * k / m, v = at(s);
      steel.beam(new THREE.Vector3(v.x + v.nx * (half + 0.6), v.h + T, -(v.y + v.ny * (half + 0.6))), new THREE.Vector3(v.x - v.nx * (half + 0.6), v.h + T, -(v.y - v.ny * (half + 0.6))), 0.3);
    }
  }
}

// ---------------------------------------------------------------- piers and docks
function pierStructure(wood, deckB, pp, w) {
  const P = frames(resample(pp, [], 6)); const half = w / 2;
  for (const v of P) v.h = PIER_DECK_Y;
  band(deckB, P, -half, half, half, 0);
  const W = (v, o, y) => new THREE.Vector3(v.x + v.nx * o, y, -(v.y + v.ny * o));
  for (let k = 0; k < P.length - 1; k++) { // deck edge boards
    const a = P[k], b = P[k + 1];
    wood.quad(W(a, half, PIER_DECK_Y - 0.3), W(b, half, PIER_DECK_Y - 0.3), W(b, half, PIER_DECK_Y), W(a, half, PIER_DECK_Y));
    wood.quad(W(b, -half, PIER_DECK_Y - 0.3), W(a, -half, PIER_DECK_Y - 0.3), W(a, -half, PIER_DECK_Y), W(b, -half, PIER_DECK_Y));
  }
  const L = P[P.length - 1].s, n = Math.max(2, Math.round(L / 3.6));
  let i = 1;
  for (let k = 0; k <= n; k++) {
    const s = L * k / n; while (i < P.length - 1 && P[i].s < s) i++;
    const a = P[i - 1], b = P[i], t = Math.min(1, Math.max(0, (s - a.s) / Math.max(1e-6, b.s - a.s)));
    const v = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, nx: a.nx, ny: a.ny };
    const along = new THREE.Vector3(a.tx, 0, -a.ty);
    for (const sd of [-1, 1]) {
      const c = W(v, sd * (half - 0.15), WATER_Y);
      wood.box(c, along, 0.32, 0.32, PIER_DECK_Y - WATER_Y + (w >= 3 ? 1.05 : 0)); // pilings rise as rail posts on wide piers
    }
  }
  if (w >= 3) for (const sd of [-1, 1]) for (let k = 0; k < P.length - 1; k++) { // handrail
    const a = P[k], b = P[k + 1];
    wood.beam(W(a, sd * (half - 0.15), PIER_DECK_Y + 1.0), W(b, sd * (half - 0.15), PIER_DECK_Y + 1.0), 0.14);
  }
}
