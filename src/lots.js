// Everyday detail the Atlas does not draw: a driveway from each house to its street, and parked cars
// (in driveways, in the painted stalls of parking lots, beside mobile homes). Everything is checked
// against buildings, roads, water and the modeled lots so nothing lands where it should not.
import * as THREE from 'three';
import { HALF, hash, Grid, pointInPoly, nearestRoad, inHeroLot, ringBBox } from './core.js';
import { U } from './shaders.js';

const CAR_COLORS = ['#f2f2f0', '#f2f2f0', '#e9e9e6', '#1d1f22', '#1d1f22', '#2b2d31', '#8d9196', '#b4b8bc', '#b4b8bc', '#6b6f74', '#7b1e22', '#9a2a25', '#23395d', '#2f4f6f', '#3b4a3a', '#c9bfa8', '#5a3b2a', '#d8d2c2'];

// ---------------------------------------------------------------- car meshes (sedan, SUV, pickup), +Z = forward
function carGeometry(kind) {
  const g = []; const L = kind === 2 ? 5.6 : kind === 1 ? 4.8 : 4.7, W = kind === 1 ? 1.95 : 1.85;
  const body = (x0, x1, y0, y1, z0, z1, top) => ({ x0, x1, y0, y1, z0, z1, top }); // z along length
  const parts = [];
  parts.push([body(-W / 2, W / 2, 0.32, kind === 1 ? 1.05 : 0.95, -L / 2, L / 2), 'paint']);
  if (kind === 2) { parts.push([body(-W / 2 + 0.06, W / 2 - 0.06, 0.95, 1.75, -0.3, 1.05), 'paint']); parts.push([body(-W / 2 + 0.1, W / 2 - 0.1, 0.96, 1.62, -0.25, 1.0), 'glass']); }
  else { const c0 = kind === 1 ? -1.7 : -1.35, c1 = kind === 1 ? 1.0 : 0.85, h = kind === 1 ? 1.8 : 1.45; parts.push([body(-W / 2 + 0.08, W / 2 - 0.08, 0.95, h, c0, c1), 'paint']); parts.push([body(-W / 2 + 0.07, W / 2 - 0.07, 1.0, h - 0.08, c0 + 0.08, c1 - 0.06), 'glass']); }
  for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) parts.push([body(x * W / 2 - (x > 0 ? 0.24 : 0), x * W / 2 + (x < 0 ? 0.24 : 0), 0, 0.66, z * (L / 2 - 0.85) - 0.33, z * (L / 2 - 0.85) + 0.33), 'tire']);
  const pos = [], nrm = [], col = [];
  const C = { paint: [1, 1, 1], glass: [0.05, 0.06, 0.07], tire: [0.04, 0.04, 0.04] };
  for (const [b, m] of parts) {
    const v = [[b.x0, b.y0, b.z0], [b.x1, b.y0, b.z0], [b.x1, b.y1, b.z0], [b.x0, b.y1, b.z0], [b.x0, b.y0, b.z1], [b.x1, b.y0, b.z1], [b.x1, b.y1, b.z1], [b.x0, b.y1, b.z1]];
    // taper the cabin top inward for a windshield slope
    if (b.y1 > 1.2 && m !== 'tire') { v[2][2] += 0.35; v[3][2] += 0.35; v[6][2] -= 0.25; v[7][2] -= 0.25; }
    const faces = [[0, 1, 2, 3, 0, 0, -1], [5, 4, 7, 6, 0, 0, 1], [4, 0, 3, 7, -1, 0, 0], [1, 5, 6, 2, 1, 0, 0], [3, 2, 6, 7, 0, 1, 0]];
    for (const [a, bb, c, d, nx, ny, nz] of faces) {
      // wind each face counter-clockwise as seen from outside (matches its normal)
      const e1 = v[bb].map((q, i) => q - v[a][i]), e2 = v[c].map((q, i) => q - v[a][i]);
      const cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
      const order = cr[0] * nx + cr[1] * ny + cr[2] * nz >= 0 ? [a, bb, c, a, c, d] : [a, c, bb, a, d, c];
      for (const i of order) { pos.push(...v[i]); nrm.push(nx, ny, nz); col.push(...C[m]); }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3)); geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return geo;
}

// ---------------------------------------------------------------- build
export function buildLots(D) {
  const group = new THREE.Group(); group.name = 'lots';
  const drives = []; D.driveGrid = new Grid(40); D.drives = drives;
  const blocked = (x, y, self) => {
    if (!(D.mask.at(x, y) & 1) || (D.mask.at(x, y) & 2)) return true;
    if (inHeroLot(D, x, y, 0.5)) return true;
    let hit = false;
    D.bGrid.query(x - 1, y - 1, x + 1, y + 1, k => {
      const b = D.buildings[k]; if (b === self) return; const p = b.poly;
      const ux = (p[2] - p[0]) / b.w, uy = (p[3] - p[1]) / b.w, vx = (p[6] - p[0]) / b.d, vy = (p[7] - p[1]) / b.d;
      const dx = x - b.cx, dy = y - b.cy;
      if (Math.abs(dx * ux + dy * uy) < b.w / 2 + 0.6 && Math.abs(dx * vx + dy * vy) < b.d / 2 + 0.6) { hit = true; return false; }
    });
    return hit;
  };
  // driveways: from one front corner of each house straight out to its street
  for (const b of D.buildings) {
    if (b.hero || !['house', 'duplex', 'townhouse'].includes(b.kind) || b.fnx == null) continue;
    const r = hash(b.i * 977 + 5); if (r < 0.08) continue; // some lots have none (street parking)
    const ex = -b.fny, ey = b.fnx; // along the front edge
    const side = hash(b.i * 131) < 0.5 ? -1 : 1;
    const off = Math.max(0, b.fw / 2 - 2.0);
    let x0 = b.cx + b.fnx * (b.fd / 2) + ex * side * off, y0 = b.cy + b.fny * (b.fd / 2) + ey * side * off;
    let len = 0, ok = false, road = null;
    for (let t = 0.5; t < 48; t += 0.5) {
      const x = x0 + b.fnx * t, y = y0 + b.fny * t;
      const nr = nearestRoad(D, x, y, 12, rr => rr.cls !== 'path' && !rr.bridge);
      if (nr && nr.d < HALF[nr.road.cls] - 0.2) { len = t; ok = true; road = nr.road; break; }
      if (blocked(x, y, b)) break;
    }
    if (!ok || len < 3) continue;
    const rural = len > 26 || road.cls === 'track';
    drives.push({ b, x0, y0, x1: x0 + b.fnx * len, y1: y0 + b.fny * len, nx: b.fnx, ny: b.fny, w: b.kind === 'duplex' ? 5.2 : 3.1, rural });
    const d = drives[drives.length - 1]; const bb = [Math.min(d.x0, d.x1) - 2, Math.min(d.y0, d.y1) - 2, Math.max(d.x0, d.x1) + 2, Math.max(d.y0, d.y1) + 2];
    D.driveGrid.insert(drives.length - 1, ...bb);
  }
  // driveway ribbons use the sidewalk shader (class 9), with gravel for long rural drives (class 6)
  const pos = [], nrm = [], road = [], cls = [], idx = [];
  for (const d of drives) {
    const px = -d.ny * d.w / 2, py = d.nx * d.w / 2, L = Math.hypot(d.x1 - d.x0, d.y1 - d.y0), o = pos.length / 3;
    const Q = [[d.x0 - px, d.y0 - py, 0, -d.w / 2], [d.x0 + px, d.y0 + py, 0, d.w / 2], [d.x1 + px, d.y1 + py, L, d.w / 2], [d.x1 - px, d.y1 - py, L, -d.w / 2]];
    for (const [x, y, s, a] of Q) { pos.push(x, 0, -y); nrm.push(0, 1, 0); road.push(s, a, d.w / 2, 1e4); cls.push(d.rural ? 6 : 9); }
    const ccw = (Q[1][0] - Q[0][0]) * (Q[2][1] - Q[0][1]) - (Q[1][1] - Q[0][1]) * (Q[2][0] - Q[0][0]) > 0; // counter-clockwise in Atlas = facing up
    if (ccw) idx.push(o, o + 1, o + 2, o, o + 2, o + 3); else idx.push(o, o + 2, o + 1, o, o + 3, o + 2);
  }
  const dg = new THREE.BufferGeometry();
  dg.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); dg.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  dg.setAttribute('aRoad', new THREE.Float32BufferAttribute(road, 4)); dg.setAttribute('aCls', new THREE.Float32BufferAttribute(cls, 1));
  dg.setIndex(new THREE.Uint32BufferAttribute(idx, 1)); dg.computeBoundingSphere();
  group.userData.driveGeometry = dg;

  // cars
  const cars = []; // {x, y, ang, kind, color}
  const R = s => hash(s >>> 0);
  drives.forEach((d, k) => {
    if (R(k * 7 + 3) > 0.62) return;
    const t = 2.5 + R(k * 11) * 2.5, L = Math.hypot(d.x1 - d.x0, d.y1 - d.y0); if (L < t + 3.5) return;
    const x = d.x0 + d.nx * (t + 2.4), y = d.y0 + d.ny * (t + 2.4);
    cars.push({ x, y, ang: Math.atan2(d.nx, -d.ny) + (R(k * 13) < 0.5 ? Math.PI : 0), kind: R(k * 17) < 0.3 ? 1 : R(k * 19) < 0.25 ? 2 : 0, color: CAR_COLORS[Math.floor(R(k * 23) * CAR_COLORS.length)] });
  });
  // parking lots: the same stall grid the ground shader paints (18 m modules, 2.75 m stalls)
  for (const l of D.lu) {
    if (l.kind !== 'parking') continue;
    const ang = l.ang ?? ringAngleOf(l.rings[0]), ca = Math.cos(ang), sa = Math.sin(ang);
    const bb = ringBBox(l.rings[0]); const busy = 0.18 + 0.4 * hash(l.i * 71);
    // walk the polygon's bbox in the rotated frame
    const corners = [[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]]].map(([x, y]) => [ca * x + sa * y, -sa * x + ca * y]);
    const qx0 = Math.min(...corners.map(c => c[0])), qx1 = Math.max(...corners.map(c => c[0])), qy0 = Math.min(...corners.map(c => c[1])), qy1 = Math.max(...corners.map(c => c[1]));
    let n = 0;
    for (let m = Math.floor(qy0 / 18); m <= Math.floor(qy1 / 18) && n < 320; m++) for (const rowc of [3.0, 15.0]) for (let k = Math.floor(qx0 / 2.75); k <= Math.floor(qx1 / 2.75); k++) {
      const qx = (k + 0.5) * 2.75, qy = m * 18 + rowc;
      const x = ca * qx - sa * qy, y = sa * qx + ca * qy;
      const s = (Math.imul(l.i, 9973) ^ Math.imul(k, 7919) ^ Math.imul(m * 2 + (rowc > 9 ? 1 : 0), 104729)) >>> 0;
      if (R(s) > busy) continue;
      if (!pointInPoly(x, y, l.rings) || !pointInPoly(x + ca * 1.5, y + sa * 1.5, l.rings) || !pointInPoly(x - ca * 1.5, y - sa * 1.5, l.rings) || !pointInPoly(x - sa * 2.7, y + ca * 2.7, l.rings) || !pointInPoly(x + sa * 2.7, y - ca * 2.7, l.rings)) continue;
      if (blocked(x, y, null)) continue;
      const nr = nearestRoad(D, x, y, 12); if (nr && nr.d < HALF[nr.road.cls] + 1.5) continue;
      cars.push({ x, y, ang: Math.atan2(-sa, -ca) + (R(s * 3) < 0.5 ? Math.PI : 0) + (R(s * 5) - 0.5) * 0.06, kind: R(s * 7) < 0.35 ? 1 : R(s * 11) < 0.2 ? 2 : 0, color: CAR_COLORS[Math.floor(R(s * 13) * CAR_COLORS.length)] });
      n++;
    }
  }
  // mobile homes: a car beside many of them, toward the lane end
  for (const b of D.buildings) {
    if (b.kind !== 'mobile' || b.hero || b.fnx == null || hash(b.i * 313) > 0.5) continue;
    const ex = -b.fny, ey = b.fnx, side = hash(b.i * 17) < 0.5 ? -1 : 1;
    const x = b.cx + b.fnx * (b.fd / 2 - 3.2) + ex * side * (b.fw / 2 + 1.6), y = b.cy + b.fny * (b.fd / 2 - 3.2) + ey * side * (b.fw / 2 + 1.6);
    if (blocked(x, y, b) || blocked(x + b.fnx * 2.4, y + b.fny * 2.4, b) || blocked(x - b.fnx * 2.4, y - b.fny * 2.4, b)) continue;
    const nr = nearestRoad(D, x, y, 8); if (nr && nr.d < HALF[nr.road.cls] + 1.2) continue;
    cars.push({ x, y, ang: Math.atan2(b.fnx, -b.fny), kind: hash(b.i * 7) < 0.45 ? 2 : 0, color: CAR_COLORS[Math.floor(hash(b.i * 29) * CAR_COLORS.length)] });
  }
  D.cars = cars;
  // merge cars per 1 km chunk (static, vertex-colored)
  const geos = [carGeometry(0), carGeometry(1), carGeometry(2)];
  const chunks = new Map(); const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), s1 = new THREE.Vector3(1, 1, 1), v = new THREE.Vector3(), c = new THREE.Color();
  for (const car of cars) {
    const k = Math.floor(car.x / 1000) + ':' + Math.floor(car.y / 1000); let a = chunks.get(k); if (!a) chunks.set(k, a = { pos: [], nrm: [], col: [] });
    const g = geos[car.kind]; q.setFromAxisAngle(up, car.ang); m.compose(v.set(car.x, 0, -car.y), q, s1);
    const P = g.attributes.position.array, N = g.attributes.normal.array, Cc = g.attributes.color.array; c.set(car.color);
    const tv = new THREE.Vector3(), tn = new THREE.Vector3(), nm = new THREE.Matrix3().getNormalMatrix(m);
    for (let i = 0; i < P.length; i += 3) {
      tv.set(P[i], P[i + 1], P[i + 2]).applyMatrix4(m); tn.set(N[i], N[i + 1], N[i + 2]).applyMatrix3(nm);
      a.pos.push(tv.x, tv.y, tv.z); a.nrm.push(tn.x, tn.y, tn.z);
      const paint = Cc[i] === 1; a.col.push(paint ? c.r : Cc[i], paint ? c.g : Cc[i + 1], paint ? c.b : Cc[i + 2]);
    }
  }
  const mat = new THREE.MeshStandardMaterial({ name: 'cars', vertexColors: true, roughness: 0.35, metalness: 0.35 });
  mat.onBeforeCompile = sh => { Object.assign(sh.uniforms, { uStyle: U.uStyle }); sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uStyle;').replace('#include <color_fragment>', '#include <color_fragment>\n if (uStyle > .5) diffuseColor.rgb = uStyle < 1.5 ? vec3(.75, .72, .68) : uStyle < 2.5 ? vec3(.2, .2, .24) : vec3(.9);'); };
  group.userData.carMeshes = [];
  for (const [k, a] of chunks) {
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(a.pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(a.nrm, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(a.col, 3)); g.computeBoundingSphere();
    const mesh = new THREE.Mesh(g, mat); mesh.castShadow = true; mesh.receiveShadow = true; mesh.name = 'cars ' + k; group.add(mesh); group.userData.carMeshes.push(mesh);
  }
  return group;
}

function ringAngleOf(r) { let best = 0, bestL = 0; for (let i = 0; i + 3 < r.length; i += 2) { const dx = r[i + 2] - r[i], dy = r[i + 3] - r[i + 1], L = dx * dx + dy * dy; if (L > bestL) { bestL = L; best = Math.atan2(dy, dx); } } return best; }

/** Hide cars far from the camera (they are tiny there and cost triangles). */
export function updateLots(group, cam) {
  for (const m of group.userData.carMeshes || []) { const s = m.geometry.boundingSphere; m.visible = Math.hypot(s.center.x - cam.x, s.center.z - cam.z) - s.radius < 2200 && cam.y < 3500; }
}
