// Ground: land, land use, marsh, creeks, shore banks, the mainland apron beyond the Atlas frame,
// and the shore-distance texture the water reads.
import * as THREE from 'three';
import { patch, loadTex, U } from './shaders.js';
import { ringArea, ringBBox, pointInPoly, WATER_Y } from './core.js';

export const GCLS = ['land', 'residential', 'commercial', 'industrial', 'park', 'golf', 'cemetery', 'school', 'hospital', 'civic', 'parking', 'yard', 'plaza', 'pitch', 'track', 'pool', 'woods', 'forest', 'farm', 'field', 'beach', 'airport', 'marsh', 'creek', 'bank', 'apron'];
const CI = Object.fromEntries(GCLS.map((k, i) => [k, i]));

// Map-token palettes (from the Westport Atlas themes), index = GCLS
const ATLAS = { land: '#F3F0E9', residential: '#ECE8E0', commercial: '#F1E4DF', industrial: '#E4E1E3', park: '#CFE6BE', golf: '#D2E8C3', cemetery: '#D9E4CE', school: '#EFE7D4', hospital: '#F0E0DF', civic: '#EDE5D8', parking: '#E2DFD9', yard: '#E3DFD7', plaza: '#EAE5DC', pitch: '#BBDCA3', track: '#D8A48C', pool: '#9CCDE7', woods: '#D8E4C9', forest: '#CFDDBF', farm: '#EEEBD8', field: '#E3E6C3', beach: '#F2E5C2', airport: '#E6E3DC', marsh: '#DCE7CF', creek: '#A9C9DE', bank: '#D9D2C2', apron: '#EDEAE1' };
const SHADOWS = { land: '#141418', residential: '#18181D', commercial: '#1C1A1F', industrial: '#19191F', park: '#14201A', golf: '#15211A', cemetery: '#171D18', school: '#1C1B1A', hospital: '#1E1A1B', civic: '#1B1A1C', parking: '#1D1D22', yard: '#1B1B20', plaza: '#1C1C21', pitch: '#18261B', track: '#3A2A26', pool: '#132B3B', woods: '#121A14', forest: '#111912', farm: '#18181A', field: '#1D2117', beach: '#262119', airport: '#1A1A1E', marsh: '#121C16', creek: '#0A131C', bank: '#101013', apron: '#121216' };
const pal = P => GCLS.map(k => new THREE.Color(P[k]));

export const BOUNDS = { x0: -16000, x1: 16000, y0: -12717, y1: 12000 };

const GROUND_FRAG = /* glsl */`
uniform sampler2D tGrass; uniform sampler2D tAsphalt; uniform sampler2D tConcrete; uniform sampler2D tGravel; uniform sampler2D tPavers;
uniform vec3 uPalA[26]; uniform vec3 uPalS[26]; uniform vec3 uSun; uniform float uTreeRange;
varying float vCls; varying float vAng; varying float vSeed;
vec3 lawn(vec2 p, float dryness){
  vec3 g = texture2D(tGrass, p / 4.).rgb * .6 + texture2D(tGrass, p / 27.).rgb * .4;
  float m = fbm(p * .012), n = fbm(p * .09), k = fbm(p * .6);
  vec3 c = g * vec3(.82, .84, .6);
  c = mix(vec3(dot(c, vec3(.3, .59, .11))), c, .72);                       // real lawns are less saturated than paint
  c = mix(c, c * vec3(1.25, 1.08, .78), smoothstep(.45, .8, m) * dryness);      // sun-dried patches
  c = mix(c, c * vec3(.82, .9, .78), smoothstep(.5, .75, fbm(p * .035 + 4.)) * .7); // shade and clover
  c *= .8 + .3 * n + .08 * (k - .5);
  return c;
}
vec3 crowns(vec2 p, float scale, float density, out float cover){
  vec4 w = worley(p / scale);
  float keep = step(1. - density, w.y);
  float r = 1. - smoothstep(.28, .72, w.x);
  cover = r * keep;
  vec2 dir = normalize(w.zw + 1e-4);
  float lit = .62 + .5 * dot(-dir, normalize(uSun.xz + 1e-4)) * r;
  vec3 dark = mix(srgb(vec3(.16, .25, .12)), srgb(vec3(.24, .33, .16)), h12(vec2(w.y * 91.)));
  return dark * lit * (.8 + .4 * fbm3(p * .7));
}
`;

const GROUND_COLOR = /* glsl */`
float cls = floor(vCls + .5);
vec2 p = vec2(vWPos.x, -vWPos.z);
float cd = length(vWPos - cameraPosition);
if (uStyle > .5 && uStyle < 1.5) { col = uPalA[int(cls)]; rough = .95; }
else if (uStyle > 1.5 && uStyle < 2.5) { col = uPalS[int(cls)]; rough = .95; }
else if (uStyle > 2.5) { col = vec3(.86, .85, .83) * (cls == 23. || cls == 15. ? .8 : 1.); rough = .9; }
else {
  rough = .92;
  float ca = cos(vAng), sa = sin(vAng);
  vec2 q = mat2(ca, -sa, sa, ca) * p;           // polygon-aligned frame
  if (cls == 0. || cls == 19. || cls == 21.) {   // rural meadow, fields, airport grass
    col = lawn(p, 1.);
    float scrub = smoothstep(.62, .78, fbm(p * .02 + 3.1));
    col = mix(col, srgb(vec3(.36, .40, .22)), scrub * .55);
    col = mix(col, col * vec3(1.1, 1.02, .8), smoothstep(.5, .9, fbm(p * .004)) * .5);
  } else if (cls == 1. || cls == 7. || cls == 8. || cls == 9.) { // mowed lawns
    col = lawn(p, .55) * vec3(.97, 1.04, .95);
    float cov; vec3 cr = crowns(p, 11., .34, cov);
    col = mix(col, cr, cov * smoothstep(uTreeRange * .75, uTreeRange * 1.15, cd));
  } else if (cls == 4. || cls == 5. || cls == 13. || cls == 6.) { // parks, golf, pitches, cemeteries
    col = lawn(p, .3) * vec3(.95, 1.08, .9);
    float stripe = step(.5, fract(q.x / (cls == 13. ? 6. : 9.)));
    col *= .93 + .1 * stripe;
    if (cls == 4.) { float cov; vec3 cr = crowns(p, 15., .22, cov); col = mix(col, cr, cov * smoothstep(uTreeRange * .75, uTreeRange * 1.15, cd)); }
    if (cls == 6.) { vec2 g = fract(q / vec2(1.6, 3.2)); float stone = step(.75, g.x) * step(.55, g.y) * step(g.y, .7); col = mix(col, srgb(vec3(.62, .62, .6)), stone * smoothstep(400., 150., cd)); }
  } else if (cls == 2. || cls == 3. || cls == 11.) { // commercial, industrial, yards
    vec3 con = texture2D(tConcrete, p / 3.).rgb, grav = texture2D(tGravel, p / 4.).rgb;
    float m = fbm(p * .04 + vSeed);
    vec3 asp = texture2D(tAsphalt, p / 4.).rgb * (.85 + .25 * fbm(p * .05));
    if (cls == 2.) {
      // commercial ground reads as parcels: lots paved in asphalt or concrete, some edged with planting strips
      vec2 cq = q / vec2(28., 22.), ci = floor(cq), cf = fract(cq);
      float edge = min(min(cf.x, 1. - cf.x) * 28., min(cf.y, 1. - cf.y) * 22.);
      float aa = fwidth(edge) + .02;
      col = h12(ci + vSeed) < .5 ? asp : con * .82;
      col = mix(col, srgb(vec3(.5, .49, .47)) * (.9 + .1 * m), smoothstep(.12 + aa, .12 - aa, edge) * .6); // expansion joint
      col = mix(col, lawn(p, .5), step(.68, h12(ci * 1.37 + vSeed + 2.)) * smoothstep(1.6 + aa, 1.6 - aa, edge) * .95);
    } else col = mix(grav * .88, con * .8, smoothstep(.45, .55, m));
    rough = .85;
  } else if (cls == 10.) {                        // parking: asphalt with painted stalls
    vec3 a = texture2D(tAsphalt, p / 4.).rgb * (.9 + .2 * fbm(p * .05));
    float row = mod(q.y, 18.);
    float inStall = step(.4, row) * step(row, 5.6) + step(12.4, row) * step(row, 17.6);
    float sep = step(mod(q.x, 2.75), .1) * inStall + (step(abs(row - 5.6), .06) + step(abs(row - 12.4), .06));
    float fade = smoothstep(700., 200., cd);
    col = mix(a, srgb(vec3(.92)), sep * .85 * fade);
    col *= 1. - .25 * smoothstep(.6, .9, fbm(q * vec2(.6, 1.5))) * inStall; // oil stains in stalls
    rough = .8;
  } else if (cls == 12.) { col = texture2D(tPavers, p / 2.).rgb; rough = .7; }
  else if (cls == 14.) { col = srgb(vec3(.62, .3, .24)) * (.9 + .15 * fbm(p * .5)); }
  else if (cls == 15. || cls == 23.) {            // pools and creeks
    col = cls == 15. ? srgb(vec3(.36, .68, .78)) * (.85 + .2 * fbm(p * .4 + uTime * .2)) : srgb(vec3(.16, .2, .17)) * (.9 + .1 * fbm(p * .3));
    rough = .08;
  } else if (cls == 16. || cls == 17.) {          // woods: forest floor near, canopy far
    float cov; vec3 cr = crowns(p, cls == 17. ? 5. : 6.5, .96, cov);
    // coastal pine woods: pine straw and leaf litter, patched with yaupon, fern and grass understory
    vec3 straw = srgb(vec3(.46, .35, .23)) * (.75 + .4 * fbm(p * .35));
    float under = smoothstep(.45, .7, fbm(p * .07 + 3.)) * .7 + .2 * smoothstep(.55, .8, fbm(p * .6));
    vec3 floorc = mix(straw, lawn(p, .15) * vec3(.78, .95, .68), under);
    vec3 gap = srgb(vec3(.09, .12, .07));
    vec3 canopy = mix(gap, cr, cov);
    col = mix(floorc, canopy, smoothstep(uTreeRange * .7, uTreeRange * 1.05, cd));
  } else if (cls == 18.) {                         // farm rows
    float crop = h12(vec2(vSeed, 3.));
    float rows = .5 + .5 * sin(q.y * 6.2832 / .95);
    vec3 a = crop < .3 ? srgb(vec3(.42, .5, .22)) : crop < .55 ? srgb(vec3(.72, .64, .38)) : crop < .78 ? srgb(vec3(.36, .27, .18)) : srgb(vec3(.33, .45, .2));
    col = a * (.8 + .25 * mix(1., rows, smoothstep(900., 250., cd))) * (.9 + .2 * fbm(p * .03));
  } else if (cls == 20.) {                         // beach sand, wetter toward the water
    col = srgb(vec3(.86, .79, .64)) * (.92 + .12 * fbm(p * .3)) * (.97 + .05 * sin(q.x * 2.1 + fbm(p * .2) * 4.));
    rough = .95;
  } else if (cls == 22.) {                         // spartina marsh with tidal channels
    float m = fbm(p * .015), n = fbm(p * .25);
    col = mix(srgb(vec3(.42, .46, .25)), srgb(vec3(.55, .5, .32)), smoothstep(.35, .7, m)) * (.85 + .3 * n);
    float ch = abs(fbm(p * .008 + 9.) - .5);
    col = mix(col, srgb(vec3(.12, .16, .15)), smoothstep(.022, .012, ch));
    rough = mix(.9, .2, smoothstep(.022, .012, ch));
  } else if (cls == 24.) {                         // shore bank
    col = srgb(vec3(.5, .45, .35)) * (.8 + .3 * fbm(p * .4 + vWPos.y));
  } else {                                         // apron: mainland beyond the Atlas frame
    float m = fbm(p * .0012);
    float cov; vec3 cr = crowns(p, 7., .96, cov);
    vec3 forest = mix(srgb(vec3(.09, .12, .07)), cr, cov);
    vec3 fieldc = lawn(p, 1.) * vec3(1.05, 1., .8);
    col = mix(forest, fieldc, smoothstep(.52, .58, m));
  }
}
`;

function triangulateRings(rings) {
  // rings: flat arrays; first outer, rest holes. Returns {pos: [x,y,...], idx: []}
  const toV = r => { const a = []; const n = r.length; let m = n; if (r[0] === r[n - 2] && r[1] === r[n - 1]) m -= 2; for (let i = 0; i < m; i += 2) a.push(new THREE.Vector2(r[i], r[i + 1])); return a; };
  const outer = toV(rings[0]); const holes = rings.slice(1).map(toV).filter(h => h.length >= 3);
  if (outer.length < 3) return null;
  const tris = THREE.ShapeUtils.triangulateShape(outer, holes);
  const all = outer.concat(...holes);
  return { pts: all, tris };
}

class Builder {
  constructor() { this.pos = []; this.nrm = []; this.cls = []; this.ang = []; this.seed = []; this.idx = []; }
  addPoly(rings, cls, ang = 0, seed = 0, y = 0) {
    const t = triangulateRings(rings); if (!t) return;
    const base = this.pos.length / 3;
    for (const v of t.pts) { this.pos.push(v.x, y, -v.y); this.nrm.push(0, 1, 0); this.cls.push(cls); this.ang.push(ang); this.seed.push(seed); }
    for (const f of t.tris) { // keep every triangle counter-clockwise seen from above (normal up)
      const a = t.pts[f[0]], b = t.pts[f[1]], c = t.pts[f[2]];
      const cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
      if (cross >= 0) this.idx.push(base + f[0], base + f[1], base + f[2]); else this.idx.push(base + f[0], base + f[2], base + f[1]);
    }
  }
  addQuad(a, b, c, d, n, cls) { // winding is fixed up to face the given normal
    const fn = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(d, a));
    if (fn.dot(n) < 0) [b, d] = [d, b];
    const base = this.pos.length / 3;
    for (const v of [a, b, c, d]) { this.pos.push(v.x, v.y, v.z); this.nrm.push(n.x, n.y, n.z); this.cls.push(cls); this.ang.push(0); this.seed.push(0); }
    this.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  geometry() {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(this.nrm, 3));
    g.setAttribute('aCls', new THREE.Float32BufferAttribute(this.cls, 1));
    g.setAttribute('aAng', new THREE.Float32BufferAttribute(this.ang, 1));
    g.setAttribute('aSeed', new THREE.Float32BufferAttribute(this.seed, 1));
    g.setIndex(this.idx.length > 65535 ? new THREE.Uint32BufferAttribute(this.idx, 1) : new THREE.Uint16BufferAttribute(this.idx, 1));
    g.computeBoundingSphere(); return g;
  }
}

// Main axis angle of a ring (for stall and crop row orientation)
function ringAngle(r) {
  let best = 0, bestL = 0;
  for (let i = 0; i + 3 < r.length; i += 2) { const dx = r[i + 2] - r[i], dy = r[i + 3] - r[i + 1], L = dx * dx + dy * dy; if (L > bestL) { bestL = L; best = Math.atan2(dy, dx); } }
  return best;
}

export function groundMaterial(layer, sun) {
  const m = new THREE.MeshStandardMaterial({ name: 'ground' + layer, roughness: .92, metalness: 0 });
  // flat layers are painted in order (renderOrder) without depth writes, so coplanar layers never fight
  m.depthWrite = false;
  patch(m, {
    key: 'ground',
    uniforms: {
      tGrass: { value: loadTex('assets/tex/ground_grass.jpg') }, tAsphalt: { value: loadTex('assets/tex/pave_asphalt.jpg') },
      tConcrete: { value: loadTex('assets/tex/pave_concrete.jpg') }, tGravel: { value: loadTex('assets/tex/pave_gravel.jpg') }, tPavers: { value: loadTex('assets/tex/pave_brick.jpg') },
      uPalA: { value: pal(ATLAS) }, uPalS: { value: pal(SHADOWS) }, uSun: U.uSun, uTreeRange: U.uTreeRange,
    },
    vHead: 'attribute float aCls; attribute float aAng; attribute float aSeed; varying float vCls; varying float vAng; varying float vSeed;',
    vMain: 'vCls = aCls; vAng = aAng; vSeed = aSeed;',
    fHead: GROUND_FRAG,
    color: GROUND_COLOR,
  });
  return m;
}

/** Build every ground layer. Returns a Group. */
export function buildGround(D) {
  const group = new THREE.Group(); group.name = 'ground';
  const layers = [new Builder(), new Builder(), new Builder(), new Builder(), new Builder(), new Builder(), new Builder()];
  // 0: apron + land + banks, 1: lu under, 2: woods, 3: farm/beach/field, 4: marsh, 5: other lu, 6: creeks
  D.land.forEach((poly, k) => { const n0 = layers[0].idx.length; layers[0].addPoly(poly, CI.land); if (window.WP_DEBUG) console.log('land', k, poly.map(r => r.length / 2).join('/'), 'tris', (layers[0].idx.length - n0) / 3, 'area', Math.round(ringArea(poly[0]) / 1e6) + ' km2'); });
  // land-use areas that lie out over open water (the park the Atlas marks at the end of the town pier)
  // would paint lawn on the bay: skip any whose sampled interior is mostly water
  D.luOverWater = [];
  const overWater = l => {
    if (l.kind === 'beach' || l.kind === 'marsh' || !D.mask) return false;
    const [x0, y0, x1, y1] = l.bbox || ringBBox(l.rings[0]), st = Math.max(2, Math.min(x1 - x0, y1 - y0) / 8);
    let n = 0, dry = 0;
    for (let x = x0 + st / 2; x < x1; x += st) for (let y = y0 + st / 2; y < y1; y += st) if (pointInPoly(x, y, l.rings)) { n++; if (D.mask.at(x, y) & 1) dry++; }
    return n > 0 && dry / n < 0.35;
  };
  D.lu.forEach(l => {
    if (overWater(l)) { D.luOverWater.push(l.i); return; }
    const k = l.kind in CI ? CI[l.kind] : CI.land;
    const ang = ringAngle(l.rings[0]), seed = (l.i * 0.618) % 1 * 100;
    const L = l.under ? 1 : (l.kind === 'woods' || l.kind === 'forest') ? 2 : (l.kind === 'farm' || l.kind === 'beach' || l.kind === 'field') ? 3 : 5;
    layers[L].addPoly(l.rings, k, ang, seed);
  });
  D.marsh.forEach(poly => layers[4].addPoly(poly, CI.marsh));
  // creeks: ribbons
  for (const c of D.creeks) ribbon(layers[6], c, 3.2, CI.creek);
  // banks: land rings drop to below the water line, facing the water
  for (const poly of D.land) poly.forEach((r, k) => bank(layers[0], r, k === 0 ? 1 : -1, 0, WATER_Y - 0.03));
  for (const poly of D.marsh) bank(layers[4], poly[0], 1, 0, WATER_Y - 0.03);
  apron(layers[0], D);
  layers.forEach((b, i) => {
    if (!b.pos.length) return;
    const mesh = new THREE.Mesh(b.geometry(), groundMaterial(i));
    mesh.receiveShadow = true; mesh.name = 'ground-' + i; mesh.renderOrder = 10 + i;
    group.add(mesh);
  });
  return group;
}

function ribbon(B, p, half, cls) {
  const n = p.length / 2; if (n < 2) return;
  const L = [], R = [];
  for (let i = 0; i < n; i++) {
    const x = p[2 * i], y = p[2 * i + 1];
    const xa = p[2 * Math.max(0, i - 1)], ya = p[2 * Math.max(0, i - 1) + 1], xb = p[2 * Math.min(n - 1, i + 1)], yb = p[2 * Math.min(n - 1, i + 1) + 1];
    let dx = xb - xa, dy = yb - ya; const l = Math.hypot(dx, dy) || 1; dx /= l; dy /= l;
    const w = half * (0.6 + 0.4 * Math.min(1, i / 8)); // creeks taper at their heads
    L.push([x - dy * w, y + dx * w]); R.push([x + dy * w, y - dx * w]);
  }
  const base = B.pos.length / 3;
  for (let i = 0; i < n; i++) for (const q of [L[i], R[i]]) { B.pos.push(q[0], 0, -q[1]); B.nrm.push(0, 1, 0); B.cls.push(cls); B.ang.push(0); B.seed.push(0); }
  for (let i = 0; i < n - 1; i++) { const a = base + 2 * i; B.idx.push(a, a + 1, a + 3, a, a + 3, a + 2); }
}

function bank(B, r, sideSign, yTop, yBot) {
  // sideSign +1: water is outside the ring (outer ring); -1: water inside (hole)
  const ccw = ringArea(r) > 0 ? 1 : -1;
  const n = r.length;
  for (let i = 0; i < n; i += 2) {
    const j = (i + 2) % n;
    const x1 = r[i], y1 = r[i + 1], x2 = r[j], y2 = r[j + 1];
    const dx = x2 - x1, dy = y2 - y1, l = Math.hypot(dx, dy); if (l < 0.01) continue;
    // outward normal of a CCW ring is (dy, -dx)
    const s = ccw * sideSign; const nx = s * dy / l, ny = s * -dx / l;
    const nrm = new THREE.Vector3(nx, 0, -ny);
    // slope the bank 1.6 m outward so it reads as a shore, not a wall
    const ox = nx * 1.6, oy = ny * 1.6;
    const a = new THREE.Vector3(x1, yTop, -y1), b = new THREE.Vector3(x2, yTop, -y2);
    const c = new THREE.Vector3(x2 + ox, yBot, -(y2 + oy)), d = new THREE.Vector3(x1 + ox, yBot, -(y1 + oy));
    const tilt = new THREE.Vector3(nx * 0.7, 0.7, -ny * 0.7).normalize();
    // winding: seen from the water side
    if (s > 0) B.addQuad(b, a, d, c, tilt, CI.bank); else B.addQuad(a, b, c, d, tilt, CI.bank);
  }
}

// Extend the mainland past the Atlas frame wherever land touches the frame, so the town does not end at a cliff.
function apron(B, D) {
  const { x0, x1, y0, y1 } = BOUNDS, FAR = 60000, eps = 2;
  const onEdge = (x, y) => (Math.abs(x - x0) < eps ? 'W' : Math.abs(x - x1) < eps ? 'E' : Math.abs(y - y1) < eps ? 'N' : Math.abs(y - y0) < eps ? 'S' : null);
  const out = { W: [-1, 0], E: [1, 0], N: [0, 1], S: [0, -1] };
  const corners = new Set();
  for (const poly of D.land) {
    const r = poly[0], n = r.length;
    for (let i = 0; i < n; i += 2) {
      const j = (i + 2) % n;
      const e1 = onEdge(r[i], r[i + 1]), e2 = onEdge(r[j], r[j + 1]);
      if (!e1 || e1 !== e2 || e1 === 'S') continue;
      const [ox, oy] = out[e1];
      const q = [[r[i], r[i + 1]], [r[j], r[j + 1]], [r[j] + ox * FAR, r[j + 1] + oy * FAR], [r[i] + ox * FAR, r[i + 1] + oy * FAR]];
      B.addPoly([q.flat()], CI.apron);
      for (const [x, y] of [[r[i], r[i + 1]], [r[j], r[j + 1]]]) {
        if (Math.abs(Math.abs(x) - x1) < eps && Math.abs(y - y1) < eps) corners.add(Math.sign(x));
      }
    }
  }
  for (const sx of corners) { // fill the northern corners
    const cx = sx > 0 ? x1 : x0;
    B.addPoly([[cx, y1, cx + sx * FAR, y1, cx + sx * FAR, y1 + FAR, cx, y1 + FAR]], CI.apron);
  }
}

/** Shore-distance texture over the Atlas frame: R = distance to land (0..1 = 0..400 m), G = shoal. */
export function shoreTexture(D, W = 2048) {
  const { x0, x1, y0, y1 } = BOUNDS; const H = Math.round(W * (y1 - y0) / (x1 - x0));
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H; const g = cv.getContext('2d');
  const X = x => (x - x0) / (x1 - x0) * W, Y = y => (y1 - y) / (y1 - y0) * H;
  const path = rings => { g.beginPath(); for (const r of rings) { g.moveTo(X(r[0]), Y(r[1])); for (let i = 2; i < r.length; i += 2) g.lineTo(X(r[i]), Y(r[i + 1])); g.closePath(); } };
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H); g.fillStyle = '#fff';
  for (const poly of D.land) { path(poly); g.fill('evenodd'); }
  for (const poly of D.marsh) { path(poly); g.fill('evenodd'); }
  const land = g.getImageData(0, 0, W, H).data;
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H); g.fillStyle = '#fff';
  for (const poly of D.marsh) { path(poly); g.fill('evenodd'); }
  const marsh = g.getImageData(0, 0, W, H).data;
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H); g.fillStyle = '#fff';
  for (const poly of D.land) { path(poly); g.fill('evenodd'); }
  const landOnly = g.getImageData(0, 0, W, H).data;
  const LM = new Uint8Array(W * H); for (let i = 0; i < W * H; i++) LM[i] = (landOnly[i * 4] > 127 ? 1 : 0) | (marsh[i * 4] > 127 ? 2 : 0);
  D.mask = { W, H, x0, x1, y0, y1, a: LM, at(x, y) { const i = Math.floor((x - x0) / (x1 - x0) * W), j = Math.floor((y1 - y) / (y1 - y0) * H); return i < 0 || j < 0 || i >= W || j >= H ? 1 : LM[j * W + i]; } };
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H); g.fillStyle = '#fff'; g.filter = 'blur(3px)';
  for (const poly of D.shoal) { path(poly); g.fill('evenodd'); }
  g.filter = 'none';
  const shoal = g.getImageData(0, 0, W, H).data;
  // two-pass chamfer distance transform (in pixels)
  const N = W * H, d = new Float32Array(N), BIG = 1e9;
  for (let i = 0; i < N; i++) d[i] = land[i * 4] > 127 ? 0 : BIG;
  const a = 1, b = Math.SQRT2;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = y * W + x; let v = d[i]; if (!v) continue;
    if (x > 0) v = Math.min(v, d[i - 1] + a); if (y > 0) { v = Math.min(v, d[i - W] + a); if (x > 0) v = Math.min(v, d[i - W - 1] + b); if (x < W - 1) v = Math.min(v, d[i - W + 1] + b); } d[i] = v; }
  for (let y = H - 1; y >= 0; y--) for (let x = W - 1; x >= 0; x--) { const i = y * W + x; let v = d[i]; if (!v) continue;
    if (x < W - 1) v = Math.min(v, d[i + 1] + a); if (y < H - 1) { v = Math.min(v, d[i + W] + a); if (x < W - 1) v = Math.min(v, d[i + W + 1] + b); if (x > 0) v = Math.min(v, d[i + W - 1] + b); } d[i] = v; }
  const px = (x1 - x0) / W, out = new Uint8Array(N * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { // texture row 0 = the south edge
    const i = y * W + x, o = ((H - 1 - y) * W + x) * 4;
    out[o] = Math.min(255, d[i] * px / 400 * 255); out[o + 1] = shoal[i * 4]; out[o + 2] = land[i * 4]; out[o + 3] = 255;
  }
  const t = new THREE.DataTexture(out, W, H, THREE.RGBAFormat); t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; t.needsUpdate = true;
  t.userData = { x0, x1, y0, y1 };
  return t;
}
