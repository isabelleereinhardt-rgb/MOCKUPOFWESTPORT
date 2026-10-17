// Buildings from the Atlas footprints: walls with procedural facades, real roofs (hip, gable,
// low-slope, flat with parapets and rooftop units), porches, chimneys and church steeples.
// Geometry is merged per 1 km chunk so the camera frustum culls it.
import * as THREE from 'three';
import { patch, loadTex } from './shaders.js';
import { hash, nearestRoad } from './core.js';

const KIND = { house: 0, duplex: 1, mobile: 2, shed: 3, barn: 4, shop: 5, office: 6, tower: 7, deck: 8, retail: 9, apartments: 10, townhouse: 11, clubhouse: 12, church: 13, school: 14, gym: 15, stands: 16, hospital: 17, industrial: 18, civic: 19, motel: 20, hotel: 21 };
const FLAT = new Set(['shop', 'office', 'tower', 'deck', 'retail', 'school', 'gym', 'stands', 'hospital', 'industrial', 'motel', 'hotel', 'civic']);
export const REPLACEABLE = new Set(['house', 'duplex', 'townhouse', 'mobile', 'shed', 'barn', 'church', 'apartments', 'motel']);
const MAT = { siding: 0, brick: 1, stucco: 2, panel: 3, glass: 4, wood: 5 };
const ROOF = { shingle: 0, metal: 1, slate: 2, flat: 3, unit: 4, rust: 5 };

const C = hex => new THREE.Color(hex);
const PAL = {
  siding: ['#f2efe6', '#ebe4d2', '#e8e3d6', '#d9d6cf', '#c9ccc8', '#b9c3cb', '#c6cdb6', '#d8c8a8', '#efe3bf', '#e6d6c3', '#a9b6a4', '#c8b8a6', '#f6f4ef', '#9fa9ad'],
  brick: ['#9a5640', '#8a4a37', '#a4644b', '#7e4636', '#b07258', '#8c5a46'],
  stucco: ['#e8dfcf', '#e2d5bf', '#d8cdb8', '#efe9dc', '#cfc3ad', '#e6d2b8'],
  panel: ['#b8bcbf', '#a7b0b5', '#c9c6bd', '#9aa4a8', '#d3d0c8'],
  roof: ['#55575a', '#4a4b4e', '#606265', '#3f4043', '#6b6660', '#5a524b', '#4d4a46', '#727478', '#3a3c40'],
  metal: ['#a9aeb2', '#b9bdbf', '#8d9396', '#7d4a3d', '#4f6656', '#9c9fa2'],
  flat: ['#8f8d88', '#6e6c69', '#a5a39e', '#c9c7c2', '#7d7a74', '#56585a', '#b4b2ac'],
  door: ['#7a2e2a', '#22272e', '#2f3b52', '#f2efe6', '#5b3f2a', '#3d4f3e', '#8a6d3b'],
  shutter: ['#22272e', '#2f3b52', '#3d4f3e', '#5b3f2a', '#f2efe6', '#6b7f86'],
};
const pick = (arr, r) => arr[Math.floor(r * arr.length) % arr.length];

// ---------------------------------------------------------------- shaders
const FACADE = /* glsl */`
  float kind = vB.x, seed = vB.y, eave = vB.z, wm = vB.w;
  float u = vW.x, v = vW.y, wl = vW.z, front = vW.w;
  vec2 p = vec2(vWPos.x, -vWPos.z);
  float cd = length(vWPos - cameraPosition);
  if (uStyle > .5) {
    col = uStyle < 1.5 ? srgb(vec3(.851, .816, .765)) : uStyle < 2.5 ? srgb(vec3(.165, .165, .2)) : vec3(.93);
    col *= uStyle < 2.5 ? mix(.86, 1.06, smoothstep(0., 6., v)) : mix(.8, 1., smoothstep(0., 3., v));
    rough = .95;
  } else {
    vec3 base = baseC;
    vec3 t;
    if (wm == 1.) t = texture2D(tBrick, vec2(u, v) / 2.).rgb * (base / vec3(.32, .093, .051)) * .9;
    else if (wm == 0.) t = texture2D(tSiding, vec2(u, v) / 2.).rgb * base * 1.08;
    else if (wm == 5.) t = texture2D(tSiding, vec2(v, u) / 2.).rgb * base;
    else t = texture2D(tStucco, vec2(u, v) / 2.).rgb * base;
    if (wm == 3.) t = base * (.92 + .08 * step(.5, fract(u / 1.2)));      // metal or precast panels
    col = t; rough = wm == 3. ? .55 : .85; metal = wm == 3. ? .25 : 0.;
    // floors and bays
    bool com = (kind == 5. || kind == 9. || kind == 6. || kind == 19. || kind == 20. || kind == 21. || kind == 17. || kind == 14.);
    float fh = com ? 3.8 : (kind == 2. ? 9. : 3.0);
    float gf = (kind == 5. || kind == 9.) ? 4.4 : fh;
    float bw = kind == 2. ? 4.2 : com ? 2.6 : kind == 13. ? 4.5 : 3.3;
    float nb = max(1., floor((wl - .8) / bw));
    float uu = u - (wl - nb * bw) * .5;
    float bay = floor(uu / bw), fu = (fract(uu / bw) - .5) * bw;
    float inBays = step(0., bay) * step(bay, nb - 1.);
    float fl = v < gf ? 0. : 1. + floor((v - gf) / fh);
    float fv = v < gf ? v : mod(v - gf, fh);
    float flh = v < gf ? gf : fh;
    float rnd = h12(vec2(seed * 31. + bay, fl * 7. + front));
    float ww = kind == 2. ? .9 : com ? 1.5 : kind == 13. ? 1.1 : .95;
    float wh = kind == 2. ? .95 : com ? 1.75 : kind == 13. ? 3.6 : 1.55;
    float sill = kind == 2. ? 1.15 : com ? 1.0 : kind == 13. ? 1.1 : .95;
    if (kind == 7. || kind == 8.) { ww = bw * .92; wh = flh * .62; sill = .55; }
    vec2 q = vec2(fu, fv - (sill + wh * .5));
    vec2 aw = fwidth(vec2(u, v)) * .8 + 1e-4;
    vec2 dd = abs(q) - vec2(ww, wh) * .5;
    vec2 mm = 1. - smoothstep(-aw, aw, dd);
    float win = mm.x * mm.y * inBays * step(v, eave - .25) * step(.3, v);
    vec2 df = abs(q) - (vec2(ww, wh) * .5 + .09);
    vec2 mf = 1. - smoothstep(-aw, aw, df);
    float frame = mf.x * mf.y * inBays * step(v, eave - .2) * (1. - win);
    // storefront ground floor
    float store = 0.;
    if ((kind == 5. || kind == 9.) && v < gf) {
      store = step(.45, v) * step(v, 3.25) * step(.6, u) * step(u, wl - .6);
      float mull = step(fract(u / 1.6), .045);
      win = store * (1. - mull); frame = store * mull;
      float awning = step(3.3, v) * step(v, 3.75) * step(h12(vec2(seed, 9.)), .55) * front;
      col = mix(col, srgb(mix(vec3(.18, .3, .25), vec3(.45, .12, .1), h12(vec2(seed, 3.)))) * (1. - .25 * step(.5, fract(u / .6))), awning);
    }
    // a front door, centered on the front wall (two on duplexes)
    float door = 0.;
    if (front > .5 && kind != 7. && kind != 8.) {
      float dc = kind == 1. ? abs(abs(u - wl * .5) - wl * .25) : abs(u - wl * (kind == 2. ? .3 : .5));
      door = (1. - smoothstep(.48, .52, dc)) * step(.12, v) * step(v, kind == 2. ? 2.0 : 2.15) * step(kind, 4.5);
      win *= 1. - (1. - smoothstep(.9, 1.1, dc)) * step(v, 2.4) * step(kind, 4.5);
      frame *= 1. - door;
    }
    // shutters on houses
    float shut = 0.;
    if ((kind == 0. || kind == 1. || kind == 11.) && h12(vec2(seed, 5.)) < .45) {
      vec2 sq = vec2(abs(fu) - (ww * .5 + .32), q.y);
      vec2 sd = abs(sq) - vec2(.24, wh * .5);
      vec2 sm2 = 1. - smoothstep(-aw, aw, sd);
      shut = sm2.x * sm2.y * inBays * step(v, eave - .25) * (1. - store);
    }
    vec3 trim = kind == 2. ? srgb(vec3(.75)) : srgb(vec3(.93, .92, .88));
    vec3 glass = srgb(vec3(.05, .065, .075));
    col = mix(col, trim, frame);
    col = mix(col, srgb(SHUTS[int(h12(vec2(seed, 2.)) * 4.99)]), shut);
    col = mix(col, srgb(DOORS[int(h12(vec2(seed, 4.)) * 5.99)]), door);
    col = mix(col, glass, win);
    rough = mix(rough, .08, win); metal = mix(metal, .0, win);
    // night windows
    emis = win * uNight * step(.55, rnd) * srgb(vec3(1., .78, .45)) * 1.6;
    // detail fades with distance; base of walls darker (splash, grime, ground occlusion)
    col *= mix(.72, 1., smoothstep(0., .9, v));
    if (kind == 2.) col *= 1. - .35 * step(v, .75);                       // mobile skirting
    col *= .94 + .1 * fbm(p * .5 + v * .3);
  }
`;

const ROOFSH = /* glsl */`
  float type = vR.z, seed = vR.w;
  vec2 ruv = vR.xy;
  vec2 p = vec2(vWPos.x, -vWPos.z);
  if (uStyle > .5) {
    col = uStyle < 1.5 ? srgb(vec3(.886, .859, .812)) : uStyle < 2.5 ? srgb(vec3(.18, .18, .216)) : vec3(.97);
    rough = .95;
  } else {
    vec3 base = baseC;
    if (type == 0.) col = texture2D(tShingle, ruv / 2.).rgb * base * 1.25;
    else if (type == 2.) col = texture2D(tSlate, ruv / 2.).rgb * base * 1.2;
    else if (type == 1.) { col = texture2D(tMetal, ruv / vec2(1., 2.)).rgb * base; metal = .55; rough = .45; }
    else if (type == 5.) { col = texture2D(tRust, ruv / 2.).rgb * base; metal = .3; rough = .6; }
    else if (type == 3.) { col = base * (.9 + .12 * fbm(p * .25)) * (1. - .12 * smoothstep(.6, .8, fbm(p * .08 + seed))); rough = .9; }
    else { col = base; metal = .5; rough = .4; }
    if (type < 2.5 || type == 5.) {
      col *= mix(.78, 1., smoothstep(0., .35, ruv.y));                        // gutters and eave shadow
      col *= .9 + .15 * fbm(p * .3 + seed);                                   // weathering
      col = mix(col, col * vec3(.85, .9, .8), smoothstep(.62, .8, fbm(p * .12)) * .5); // mildew streaks
    }
  }
`;

function wallMaterial() {
  const m = new THREE.MeshStandardMaterial({ name: 'walls', roughness: 0.85, vertexColors: true });
  patch(m, {
    key: 'walls',
    uniforms: { tSiding: { value: loadTex('assets/tex/wall_siding.jpg') }, tBrick: { value: loadTex('assets/tex/wall_brick.jpg') }, tStucco: { value: loadTex('assets/tex/wall_stucco.jpg') } },
    vHead: 'attribute vec4 aW; attribute vec4 aB; varying vec4 vW; varying vec4 vB;',
    vMain: 'vW = aW; vB = vec4(aB.x, aB.y / 255. * 100., aB.z / 4., aB.w);',
    fHead: 'uniform sampler2D tSiding; uniform sampler2D tBrick; uniform sampler2D tStucco; varying vec4 vW; varying vec4 vB; const vec3 DOORS[6] = vec3[6](vec3(.48,.18,.16), vec3(.13,.15,.18), vec3(.18,.23,.32), vec3(.93,.92,.88), vec3(.36,.25,.17), vec3(.24,.31,.24)); const vec3 SHUTS[5] = vec3[5](vec3(.13,.15,.18), vec3(.18,.23,.32), vec3(.24,.31,.24), vec3(.36,.25,.17), vec3(.42,.5,.53));',
    color: 'vec3 baseC = pow(vColor.rgb, vec3(2.2));\n' + FACADE,
  });
  return fixVertexColor(m);
}

function roofMaterial() {
  const m = new THREE.MeshStandardMaterial({ name: 'roofs', roughness: 0.85, vertexColors: true, side: THREE.DoubleSide });
  patch(m, {
    key: 'roofs',
    uniforms: { tShingle: { value: loadTex('assets/tex/roof_shingle.jpg') }, tSlate: { value: loadTex('assets/tex/roof_slate.jpg') }, tMetal: { value: loadTex('assets/tex/roof_metal.jpg') }, tRust: { value: loadTex('assets/tex/roof_metal_rust.jpg') } },
    vHead: 'attribute vec4 aR; varying vec4 vR;', vMain: 'vR = aR;',
    fHead: 'uniform sampler2D tShingle; uniform sampler2D tSlate; uniform sampler2D tMetal; uniform sampler2D tRust; varying vec4 vR;',
    color: 'vec3 baseC = pow(vColor.rgb, vec3(2.2));\n' + ROOFSH,
  });
  return fixVertexColor(m);
}

// three multiplies diffuse by the vertex color before map_fragment; capture it and reset to white
function fixVertexColor(m) {
  const orig = m.onBeforeCompile;
  m.onBeforeCompile = sh => {
    orig(sh);
    sh.fragmentShader = sh.fragmentShader.replace('#include <color_fragment>', '');
  };
  return m;
}

// ---------------------------------------------------------------- geometry
// compact vertex storage: normals int8, colors uint8, building info uint8 (kind, seed, eave*4, material)
class GB {
  constructor() { this.p = []; this.n = []; this.col = []; this.a = []; this.b = []; this.i = []; }
  vert(x, y, z, n, col, a, b) {
    this.p.push(x, y, z); this.n.push(Math.round(n[0] * 127), Math.round(n[1] * 127), Math.round(n[2] * 127));
    const c = col.clone().convertLinearToSRGB(); this.col.push(Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255));
    this.a.push(a[0], a[1], a[2], a[3]); if (b) this.b.push(b[0], Math.round(b[1]) & 255, Math.min(255, Math.round(b[2] * 4)), b[3]);
    return this.p.length / 3 - 1;
  }
  get count() { return this.p.length / 3; }
  geometry(kind) {
    if (!this.p.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(new Int8Array(this.n), 3, true));
    g.setAttribute('color', new THREE.BufferAttribute(new Uint8Array(this.col), 3, true));
    if (kind === 'wall') { g.setAttribute('aW', new THREE.Float32BufferAttribute(this.a, 4)); g.setAttribute('aB', new THREE.BufferAttribute(new Uint8Array(this.b), 4, false)); }
    else g.setAttribute('aR', new THREE.Float32BufferAttribute(this.a, 4));
    g.setIndex(this.p.length > 65535 * 3 ? new THREE.Uint32BufferAttribute(this.i, 1) : new THREE.Uint16BufferAttribute(this.i, 1));
    g.computeBoundingSphere(); g.computeBoundingBox(); return g;
  }
}

// world point from Atlas (x, y) and height
const W = (x, y, h) => [x, h, -y];

function wallQuad(G, a, b, h0, h1, info, uStart = 0) {
  // a, b: Atlas [x, y]; outward normal = right of a->b for a CCW ring
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy); if (L < 0.05) return;
  const n = [dy / L, 0, dx / L]; // Atlas (dy,-dx) -> world (dy, 0, dx)
  const o = G.p.length / 3;
  const bb = [info.kind, info.seed, info.eave, info.mat];
  for (const [P, u, v] of [[a, uStart, h0], [b, uStart + L, h0], [b, uStart + L, h1], [a, uStart, h1]]) G.vert(...W(P[0], P[1], v), n, info.color, [u, v, L, info.front], bb);
  G.i.push(o, o + 1, o + 2, o, o + 2, o + 3);
}

function gableTri(G, a, b, apex, h0, info, center) { // vertical triangle above an eave edge, facing away from center
  if ((b[1] - a[1]) * ((a[0] + b[0]) / 2 - center[0]) - (b[0] - a[0]) * ((a[1] + b[1]) / 2 - center[1]) < 0) [a, b] = [b, a];
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy); if (L < 0.05) return;
  const n = [dy / L, 0, dx / L], o = G.p.length / 3; const bb = [info.kind, info.seed, info.eave, info.mat];
  G.vert(...W(a[0], a[1], h0), n, info.color, [0, h0, L, 0], bb);
  G.vert(...W(b[0], b[1], h0), n, info.color, [L, h0, L, 0], bb);
  G.vert(...W(apex[0], apex[1], apex[2]), n, info.color, [L / 2, apex[2], L, 0], bb);
  G.i.push(o, o + 1, o + 2);
}

function roofFace(R, pts, color, type, seed, uAxis) { // pts: [[x,y,h], ...] convex; wound to face up
  const o = R.p.length / 3;
  let A = new THREE.Vector3(...W(pts[0][0], pts[0][1], pts[0][2])), B = new THREE.Vector3(...W(pts[1][0], pts[1][1], pts[1][2])), Cc = new THREE.Vector3(...W(pts[2][0], pts[2][1], pts[2][2]));
  const n = new THREE.Vector3().subVectors(B, A).cross(new THREE.Vector3().subVectors(Cc, A)).normalize();
  if (n.y < 0) { n.negate(); pts = pts.slice().reverse(); }
  const up = new THREE.Vector3(...W(uAxis[0], uAxis[1], 0)).normalize(); // along-eave axis in world
  const slope = new THREE.Vector3().crossVectors(n, up).normalize(); if (slope.y < 0) slope.negate();
  const origin = new THREE.Vector3(...W(pts[0][0], pts[0][1], pts[0][2]));
  const minV = Math.min(...pts.map(q => q[2]));
  for (const q of pts) {
    const P = new THREE.Vector3(...W(q[0], q[1], q[2]));
    const d = P.clone().sub(origin);
    R.vert(P.x, P.y, P.z, [n.x, n.y, n.z], color, [d.dot(up), (q[2] - minV) / Math.max(0.05, slope.y), type, seed]);
  }
  for (let k = 1; k < pts.length - 1; k++) R.i.push(o, o + k, o + k + 1);
}

function flatRoof(R, ring, h, color, seed) {
  const o = R.p.length / 3;
  for (const q of ring) R.vert(...W(q[0], q[1], h), [0, 1, 0], color, [q[0], q[1], ROOF.flat, seed]);
  R.i.push(o, o + 1, o + 2, o, o + 2, o + 3);
}

function boxInto(G, R, cx, cy, ux, uy, len, wid, h0, h1, info, roofColor, roofType) {
  // oriented box: walls into G (mat from info), top into R
  const vx = -uy, vy = ux;
  const c = [[cx - ux * len / 2 - vx * wid / 2, cy - uy * len / 2 - vy * wid / 2], [cx + ux * len / 2 - vx * wid / 2, cy + uy * len / 2 - vy * wid / 2], [cx + ux * len / 2 + vx * wid / 2, cy + uy * len / 2 + vy * wid / 2], [cx - ux * len / 2 + vx * wid / 2, cy - uy * len / 2 + vy * wid / 2]];
  for (let k = 0; k < 4; k++) wallQuad(G, c[k], c[(k + 1) % 4], h0, h1, info);
  if (R) { const o = R.p.length / 3; for (const q of c) R.vert(...W(q[0], q[1], h1), [0, 1, 0], roofColor, [q[0], q[1], roofType, 0]); R.i.push(o, o + 1, o + 2, o, o + 2, o + 3); }
}

// ---------------------------------------------------------------- one building
function building(b, G, R, D, front) {
  const r = hash(b.i * 7919 + 13), r2 = hash(b.i * 104729 + 7), r3 = hash(b.i * 1299709 + 3), r4 = hash(b.i * 15485863 + 11);
  // ring in CCW order
  let ring = [[b.poly[0], b.poly[1]], [b.poly[2], b.poly[3]], [b.poly[4], b.poly[5]], [b.poly[6], b.poly[7]]];
  let area = 0; for (let k = 0; k < 4; k++) { const a = ring[k], c = ring[(k + 1) % 4]; area += a[0] * c[1] - c[0] * a[1]; }
  if (area < 0) ring = ring.reverse();
  const kind = b.kind, K = KIND[kind] ?? 0;
  const e0 = Math.hypot(ring[1][0] - ring[0][0], ring[1][1] - ring[0][1]), e1 = Math.hypot(ring[2][0] - ring[1][0], ring[2][1] - ring[1][1]);
  // front edge = the edge facing the street
  let fe = 0;
  if (front) { let best = -2; for (let k = 0; k < 4; k++) { const a = ring[k], c = ring[(k + 1) % 4]; const mx = (a[0] + c[0]) / 2 - b.cx, my = (a[1] + c[1]) / 2 - b.cy, L = Math.hypot(mx, my) || 1; const d = (mx * front[0] + my * front[1]) / L; if (d > best) { best = d; fe = k; } } }
  const h = Math.max(2.6, b.h);
  // material and colors by kind
  let mat = MAT.siding, wall = C(pick(PAL.siding, r)), roofT = ROOF.shingle, roofC = C(pick(PAL.roof, r2));
  const brickHouse = r3 < 0.28;
  switch (kind) {
    case 'house': case 'duplex': case 'townhouse': if (brickHouse) { mat = MAT.brick; wall = C(pick(PAL.brick, r)); } if (r4 < 0.08) { roofT = ROOF.metal; roofC = C(pick(PAL.metal, r2)); } else if (r4 > 0.93) roofT = ROOF.slate; break;
    case 'mobile': wall = C(pick(['#eeeeea', '#e3e3dc', '#d6d8d6', '#cfd3d2', '#e8e2d0', '#c4c9c7', '#b8bec0'], r)); roofT = r4 < 0.12 ? ROOF.rust : ROOF.metal; roofC = C(pick(['#c7cacb', '#b7bbbd', '#d9dadb', '#a5a9ab'], r2)); break;
    case 'shed': mat = r3 < 0.5 ? MAT.wood : MAT.siding; wall = C(pick(['#8b6a4a', '#a58a68', '#d8d4c8', '#7c7f7a', '#9a5c45'], r)); roofT = r4 < 0.5 ? ROOF.metal : ROOF.shingle; roofC = C(pick(PAL.metal.concat(PAL.roof), r2)); break;
    case 'barn': mat = MAT.wood; wall = C(pick(['#8a3b2c', '#7a7268', '#6b5845', '#9a4a34'], r)); roofT = r4 < 0.5 ? ROOF.rust : ROOF.metal; roofC = C(pick(PAL.metal, r2)); break;
    case 'shop': mat = r3 < 0.62 ? MAT.brick : MAT.stucco; wall = C(mat === MAT.brick ? pick(PAL.brick, r) : pick(PAL.stucco.concat(['#c9d3cf', '#d9c4b0', '#e9e1d0', '#b9c6c9']), r)); roofT = ROOF.flat; roofC = C(pick(PAL.flat, r2)); break;
    case 'retail': case 'motel': case 'hotel': case 'clubhouse': mat = MAT.stucco; wall = C(pick(PAL.stucco, r)); roofT = kind === 'clubhouse' ? ROOF.shingle : ROOF.flat; roofC = C(kind === 'clubhouse' ? pick(PAL.roof, r2) : pick(PAL.flat, r2)); break;
    case 'office': case 'civic': case 'school': mat = r3 < 0.7 ? MAT.brick : MAT.stucco; wall = C(mat === MAT.brick ? pick(PAL.brick, r) : pick(PAL.stucco, r)); roofT = ROOF.flat; roofC = C(pick(PAL.flat, r2)); break;
    case 'tower': mat = MAT.panel; wall = C(pick(['#9fb3bf', '#8aa0ad', '#b4c0c6', '#7f939f'], r)); roofT = ROOF.flat; roofC = C(pick(PAL.flat, r2)); break;
    case 'hospital': mat = MAT.panel; wall = C('#e2ddd2'); roofT = ROOF.flat; roofC = C(pick(PAL.flat, r2)); break;
    case 'industrial': case 'gym': case 'stands': case 'deck': mat = MAT.panel; wall = C(pick(PAL.panel, r)); roofT = ROOF.flat; roofC = C(pick(PAL.flat, r2)); break;
    case 'apartments': mat = r3 < 0.5 ? MAT.brick : MAT.siding; wall = C(mat === MAT.brick ? pick(PAL.brick, r) : pick(PAL.siding, r)); roofT = ROOF.shingle; break;
    case 'church': mat = r3 < 0.6 ? MAT.brick : MAT.siding; wall = C(mat === MAT.brick ? pick(PAL.brick, r) : '#f4f2ec'); roofT = r4 < 0.5 ? ROOF.slate : ROOF.shingle; roofC = C(pick(['#3f4043', '#4a4b4e', '#55575a'], r2)); break;
  }
  const flat = FLAT.has(kind) || (kind === 'apartments' && r4 < 0.3);
  // rotate the ring so ring[0]->ring[1] is the front edge; long axis
  ring = ring.slice(fe).concat(ring.slice(0, fe));
  const fw = Math.hypot(ring[1][0] - ring[0][0], ring[1][1] - ring[0][1]), fd = Math.hypot(ring[2][0] - ring[1][0], ring[2][1] - ring[1][1]);
  const info = { kind: K, seed: Math.floor(r * 255.99), eave: h, mat, color: wall, front: 0 };
  // remembered for the close-range archetype models
  b.fw = fw; b.fd = fd; b.fnx = (ring[1][1] - ring[0][1]) / fw; b.fny = -(ring[1][0] - ring[0][0]) / fw;
  b.look = { wall, roof: roofC, door: C(pick(PAL.door, r4)), brick: mat === MAT.brick, metal: roofT === ROOF.metal || roofT === ROOF.rust };
  if (flat) {
    const par = kind === 'stands' ? 0 : 0.8;
    for (let k = 0; k < 4; k++) { info.front = k === 0 ? 1 : 0; wallQuad(G, ring[k], ring[(k + 1) % 4], 0, h, info); }
    flatRoof(R, ring, h - par, roofC, info.seed);
    if (par) { // parapet inner faces and cap
      const inset = 0.25, cx = b.cx, cy = b.cy; const inner = ring.map(q => { const dx = cx - q[0], dy = cy - q[1], L = Math.hypot(dx, dy) || 1; return [q[0] + dx / L * inset * 1.41, q[1] + dy / L * inset * 1.41]; });
      const pinfo = { ...info, front: 0, eave: 0 };
      for (let k = 0; k < 4; k++) wallQuad(G, inner[(k + 1) % 4], inner[k], h - par, h, pinfo);
      const o = R.p.length / 3; // cap ring
      for (let k = 0; k < 4; k++) { const a = ring[k], c = ring[(k + 1) % 4], ai = inner[k], ci = inner[(k + 1) % 4]; const oo = R.p.length / 3; for (const q of [a, c, ci, ai]) R.vert(...W(q[0], q[1], h + 0.02), [0, 1, 0], C('#b8b4ac'), [q[0], q[1], ROOF.flat, 0]); R.i.push(oo, oo + 1, oo + 2, oo, oo + 2, oo + 3); }
      void o;
    }
    // rooftop units on commercial roofs
    const units = kind === 'stands' || kind === 'deck' ? 0 : Math.min(6, Math.floor(fw * fd / 220) + (r2 < 0.5 ? 1 : 0));
    const ux = (ring[1][0] - ring[0][0]) / fw, uy = (ring[1][1] - ring[0][1]) / fw;
    for (let k = 0; k < units; k++) {
      const a = hash(b.i * 31 + k), c = hash(b.i * 57 + k * 3);
      const px = b.cx + ux * (a - 0.5) * fw * 0.6 - uy * (c - 0.5) * fd * 0.6, py = b.cy + uy * (a - 0.5) * fw * 0.6 + ux * (c - 0.5) * fd * 0.6;
      const s = 1.4 + hash(b.i * 91 + k) * 1.8;
      boxInto(G, R, px, py, ux, uy, s * 1.3, s, h - par, h - par + 1.1 + s * 0.3, { ...info, mat: MAT.panel, color: C('#b9bcbd'), kind: 7, eave: 0, front: 0 }, C('#9ea2a4'), ROOF.unit);
    }
    return;
  }
  // pitched roofs
  const pitchDeg = kind === 'mobile' ? 9 : kind === 'church' ? 44 : kind === 'barn' ? 32 : kind === 'shed' ? 20 : kind === 'apartments' ? 24 : 26 + r2 * 10;
  const long = fw >= fd; // ridge runs along the front if the front is the long side
  const S = long ? fd : fw;
  let rise = Math.min(S / 2 * Math.tan(pitchDeg * Math.PI / 180), h * (kind === 'church' ? 0.55 : 0.48));
  if (kind === 'mobile') rise = Math.min(rise, 0.6);
  const eave = Math.max(2.3, h - rise);
  info.eave = eave;
  const ov = kind === 'mobile' ? 0.15 : kind === 'shed' ? 0.2 : 0.42;
  const hip = (kind === 'house' && r4 < 0.55) || kind === 'clubhouse';
  // porch: houses get a front porch inside the footprint (body set back)
  const porch = (kind === 'house' && r3 > 0.45 && fd > 9 && fw > 8) ? Math.min(2.6, fd * 0.2) : 0;
  let body = ring;
  if (porch) {
    const nx = (ring[3][0] - ring[0][0]) / fd, ny = (ring[3][1] - ring[0][1]) / fd;
    body = [[ring[0][0] + nx * porch, ring[0][1] + ny * porch], [ring[1][0] + nx * porch, ring[1][1] + ny * porch], ring[2], ring[3]];
  }
  for (let k = 0; k < 4; k++) { info.front = k === 0 ? 1 : 0; wallQuad(G, body[k], body[(k + 1) % 4], 0, eave, info); }
  // roof over the body
  const bw = Math.hypot(body[1][0] - body[0][0], body[1][1] - body[0][1]), bd = Math.hypot(body[2][0] - body[1][0], body[2][1] - body[1][1]);
  const ux = (body[1][0] - body[0][0]) / bw, uy = (body[1][1] - body[0][1]) / bw; // along front
  const vx = (body[3][0] - body[0][0]) / bd, vy = (body[3][1] - body[0][1]) / bd;   // toward back
  const cx = (body[0][0] + body[2][0]) / 2, cy = (body[0][1] + body[2][1]) / 2;
  const A = long ? [ux, uy] : [vx, vy], Bv = long ? [vx, vy] : [ux, uy];
  const La = (long ? bw : bd) / 2 + ov, Sb = (long ? bd : bw) / 2 + ov;
  const P = (sa, sb, z) => [cx + A[0] * sa + Bv[0] * sb, cy + A[1] * sa + Bv[1] * sb, z];
  const riseO = rise * (Sb / Math.max(0.1, Sb - ov));
  const zE = eave - (riseO - rise);
  const top = eave + rise;
  const hipIn = hip ? Math.min(La, Sb) : 0;
  const r0 = P(-La, -Sb, zE), r1 = P(La, -Sb, zE), r2_ = P(La, Sb, zE), r3_ = P(-La, Sb, zE), k0 = P(-La + hipIn, 0, top), k1 = P(La - hipIn, 0, top);
  roofFace(R, [r0, r1, k1, k0], roofC, roofT, info.seed, A);
  roofFace(R, [r2_, r3_, k0, k1], roofC, roofT, info.seed, [-A[0], -A[1]]);
  if (hip) { roofFace(R, [r1, r2_, k1], roofC, roofT, info.seed, Bv); roofFace(R, [r3_, r0, k0], roofC, roofT, info.seed, [-Bv[0], -Bv[1]]); }
  else {
    // gable end walls on the two short sides of the body
    const g0a = P(-(La - ov), -(Sb - ov), 0), g0b = P(-(La - ov), Sb - ov, 0), g1a = P(La - ov, Sb - ov, 0), g1b = P(La - ov, -(Sb - ov), 0);
    gableTri(G, [g0b[0], g0b[1]], [g0a[0], g0a[1]], [...P(-(La - ov), 0, 0).slice(0, 2), top], eave, { ...info, front: 0 }, [cx, cy]);
    gableTri(G, [g1b[0], g1b[1]], [g1a[0], g1a[1]], [...P(La - ov, 0, 0).slice(0, 2), top], eave, { ...info, front: 0 }, [cx, cy]);
  }
  // fascia band along the eaves (thin vertical strip)
  const fasc = { ...info, mat: MAT.stucco, color: C('#ecebe6'), kind: 7, front: 0, eave: 0 };
  wallQuad(G, [r0[0], r0[1]], [r1[0], r1[1]], zE - 0.18, zE, fasc); wallQuad(G, [r2_[0], r2_[1]], [r3_[0], r3_[1]], zE - 0.18, zE, fasc);
  if (hip) { wallQuad(G, [r1[0], r1[1]], [r2_[0], r2_[1]], zE - 0.18, zE, fasc); wallQuad(G, [r3_[0], r3_[1]], [r0[0], r0[1]], zE - 0.18, zE, fasc); }
  // porch: low shed roof on posts across the front
  if (porch) {
    const ph = Math.min(eave - 0.2, 2.9);
    const f0 = ring[0], f1 = ring[1];
    const b0 = body[0], b1 = body[1];
    roofFace(R, [[f0[0], f0[1], ph - 0.25], [f1[0], f1[1], ph - 0.25], [b1[0], b1[1], ph + 0.35], [b0[0], b0[1], ph + 0.35]], roofC, roofT, info.seed, [ux, uy]);
    const posts = Math.max(2, Math.round(fw / 2.6));
    const postInfo = { ...info, mat: MAT.stucco, color: C('#f1efe9'), kind: 7, front: 0, eave: 0 };
    for (let k = 0; k <= posts; k++) {
      const t = 0.03 + 0.94 * k / posts; const px = f0[0] + (f1[0] - f0[0]) * t + vx * 0.2, py = f0[1] + (f1[1] - f0[1]) * t + vy * 0.2;
      wallQuad(G, [px - ux * 0.1, py - uy * 0.1], [px + ux * 0.1, py + uy * 0.1], 0.45, ph - 0.25, postInfo);
      wallQuad(G, [px + ux * 0.1, py + uy * 0.1], [px - ux * 0.1, py - uy * 0.1], 0.45, ph - 0.25, postInfo);
    }
    // porch floor: deck top and its front face
    const fl = { ...info, mat: MAT.wood, color: C('#a7a39a'), kind: 7, front: 0, eave: 0 };
    wallQuad(G, f0, f1, 0, 0.45, fl);
    const oo = R.p.length / 3; for (const q of [f0, f1, b1, b0]) R.vert(...W(q[0], q[1], 0.45), [0, 1, 0], C('#8f8576'), [q[0], q[1], ROOF.flat, 0]); R.i.push(oo, oo + 1, oo + 2, oo, oo + 2, oo + 3);
  }
  // chimney
  if ((kind === 'house' && r2 > 0.55) || kind === 'townhouse') {
    const t = r < 0.5 ? -0.32 : 0.32;
    const px = cx + A[0] * (long ? bw : bd) * t + Bv[0] * Sb * 0.25, py = cy + A[1] * (long ? bw : bd) * t + Bv[1] * Sb * 0.25;
    boxInto(G, R, px, py, A[0], A[1], 0.9, 0.7, eave - 0.5, top + 0.9, { ...info, mat: MAT.brick, color: C(pick(PAL.brick, r3)), kind: 7, front: 0, eave: 0 }, C('#4a4442'), ROOF.flat);
  }
  // church steeple at the front
  if (kind === 'church') {
    const s = Math.min(4.2, (long ? bd : bw) * 0.38);
    const px = cx - (long ? 0 : 0) + (long ? 0 : 0), py = cy;
    const fx = (ring[0][0] + ring[1][0]) / 2 + vx * (s / 2 + 0.1), fy = (ring[0][1] + ring[1][1]) / 2 + vy * (s / 2 + 0.1);
    void px; void py;
    const towerTop = top + 4.5;
    boxInto(G, null, fx, fy, ux, uy, s, s, -0.3, towerTop, { ...info, front: 0, eave: 0, kind: 13 });
    const spire = towerTop + 9 + r4 * 6, hs = s / 2;
    const c = [[fx - ux * hs - vx * hs, fy - uy * hs - vy * hs], [fx + ux * hs - vx * hs, fy + uy * hs - vy * hs], [fx + ux * hs + vx * hs, fy + uy * hs + vy * hs], [fx - ux * hs + vx * hs, fy - uy * hs + vy * hs]];
    for (let k = 0; k < 4; k++) roofFace(R, [[...c[k], towerTop], [...c[(k + 1) % 4], towerTop], [fx, fy, spire]], mat === MAT.brick ? C('#f2f0ea') : C('#4a4b4e'), mat === MAT.brick ? ROOF.flat : ROOF.slate, 0, [c[(k + 1) % 4][0] - c[k][0], c[(k + 1) % 4][1] - c[k][1]]);
  }
}

// ---------------------------------------------------------------- contact shadows under buildings
function contactMaterial() {
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uStyle: { value: 0 } },
    vertexShader: 'attribute vec4 aQ; varying vec4 vQ; void main(){ vQ = aQ; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }',
    fragmentShader: 'uniform float uStyle; varying vec4 vQ; void main(){ vec2 d = max(abs(vQ.xy) - vQ.zw, 0.); float e = length(d) / 2.2; float a = pow(1. - smoothstep(0., 1., e), 1.6) * .5; if (uStyle > .5) a *= .3; gl_FragColor = vec4(0., 0., 0., a); }',
  });
  return m;
}

// ---------------------------------------------------------------- build all
export function buildBuildings(D, opts = {}) {
  const skip = opts.skip || new Set(), separate = opts.separate || new Set();
  const proxies = new Map();
  const group = new THREE.Group(); group.name = 'buildings';
  const chunks = new Map(); const CH = 1000, RCH = 500;
  const get = (x, y) => { const k = Math.floor(x / CH) + ':' + Math.floor(y / CH); let c = chunks.get(k); if (!c) chunks.set(k, c = { G: new GB(), R: new GB() }); return c; };
  // homes and small buildings that close-range archetypes can replace live in their own 500 m chunks
  const rep = new Map();
  const getRep = (x, y) => { const k = Math.floor(x / RCH) + ':' + Math.floor(y / RCH); let c = rep.get(k); if (!c) rep.set(k, c = { G: new GB(), R: new GB(), list: [], i: Math.floor(x / RCH), j: Math.floor(y / RCH) }); return c; };
  const cp = [], cq = [], ci = [];
  const tooth = 2.2; // contact shadow reach (m)
  for (const b of D.buildings) {
    if (skip.has(b.i)) continue;
    if (separate.has(b.i)) b.hero = true;
    const nr = nearestRoad(D, b.cx, b.cy, 120, r => r.cls !== 'path' && r.cls !== 'track' && !r.bridge);
    b.front = nr ? [(nr.x - b.cx) / Math.max(nr.d, 1e-3), (nr.y - b.cy) / Math.max(nr.d, 1e-3)] : null;
    b.road = nr ? nr.road.i : -1;
    const c = separate.has(b.i) ? (proxies.set(b.i, { G: new GB(), R: new GB() }), proxies.get(b.i)) : REPLACEABLE.has(b.kind) ? getRep(b.cx, b.cy) : get(b.cx, b.cy);
    if (c.list) c.list.push(b);
    building(b, c.G, c.R, D, b.front);
    // contact shadow quad, slightly larger than the footprint, in the footprint's own frame
    const p = b.poly, ux = (p[2] - p[0]) / b.w, uy = (p[3] - p[1]) / b.w, vx = (p[6] - p[0]) / b.d, vy = (p[7] - p[1]) / b.d;
    const hw = b.w / 2 + tooth, hd = b.d / 2 + tooth, o = cp.length / 3;
    for (const [sa, sb] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      cp.push(b.cx + ux * hw * sa + vx * hd * sb, 0, -(b.cy + uy * hw * sa + vy * hd * sb));
      cq.push(sa * hw, sb * hd, b.w / 2, b.d / 2);
    }
    const area = (ux * vy - uy * vx) > 0;
    if (area) ci.push(o, o + 1, o + 2, o, o + 2, o + 3); else ci.push(o, o + 2, o + 1, o, o + 3, o + 2);
  }
  const wm = wallMaterial(), rm = roofMaterial();
  for (const [k, c] of chunks) {
    const g = c.G.geometry('wall'), r = c.R.geometry('roof');
    if (g) { const m = new THREE.Mesh(g, wm); m.castShadow = m.receiveShadow = true; m.name = 'walls ' + k; group.add(m); }
    if (r) { const m = new THREE.Mesh(r, rm); m.castShadow = m.receiveShadow = true; m.name = 'roofs ' + k; group.add(m); }
  }
  group.userData.rep = [];
  for (const [k, c] of rep) {
    const pg = new THREE.Group(); pg.name = 'rep ' + k;
    const g = c.G.geometry('wall'), r = c.R.geometry('roof');
    if (g) { const m = new THREE.Mesh(g, wm); m.castShadow = m.receiveShadow = true; pg.add(m); }
    if (r) { const m = new THREE.Mesh(r, rm); m.castShadow = m.receiveShadow = true; pg.add(m); }
    group.add(pg); group.userData.rep.push({ key: k, group: pg, list: c.list, cx: (c.i + 0.5) * RCH, cy: (c.j + 0.5) * RCH });
  }
  group.userData.proxies = new Map();
  for (const [i, c] of proxies) {
    const pg = new THREE.Group(); pg.name = 'proxy ' + i;
    const g = c.G.geometry('wall'), r = c.R.geometry('roof');
    if (g) { const m = new THREE.Mesh(g, wm); m.castShadow = m.receiveShadow = true; pg.add(m); }
    if (r) { const m = new THREE.Mesh(r, rm); m.castShadow = m.receiveShadow = true; pg.add(m); }
    group.add(pg); group.userData.proxies.set(i, pg);
  }
  // contact shadows: aQ in footprint units, 1 at the wall; fade out over `tooth` meters
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(cp, 3));
  g.setAttribute('aQ', new THREE.Float32BufferAttribute(cq, 4));
  g.setIndex(new THREE.Uint32BufferAttribute(ci, 1));
  const cm = new THREE.Mesh(g, contactMaterial()); cm.name = 'contact-shadows'; cm.renderOrder = 17.2; cm.frustumCulled = false; cm.raycast = () => {};
  group.add(cm);
  group.userData.contact = cm;
  return group;
}
