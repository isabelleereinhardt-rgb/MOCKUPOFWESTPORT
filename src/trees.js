// Vegetation: deterministic scatter (woods, yards, streets, parks, wet edges, coast) in 250 m cells,
// drawn as instanced meshes with two levels of detail around the camera. Uses the Blender vegetation
// kit (models/vegetation) when present, and simple procedural stand-ins otherwise.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { U } from './shaders.js';
import { HALF, hash, rng, pointInPoly, nearestRoad, inHeroLot } from './core.js';

const CELL = 250;
const LOD0 = 420, LOD1 = 1700;          // meters from the camera
const SPECIES = ['live-oak', 'live-oak-young', 'magnolia', 'loblolly-pine', 'pine-young', 'crepe-myrtle', 'crepe-myrtle-pink', 'sabal-palmetto', 'bald-cypress', 'hardwood'];
const SP = Object.fromEntries(SPECIES.map((s, i) => [s, i]));

// ---------------------------------------------------------------- procedural stand-ins
function standIn(id, lod) {
  const parts = [];
  const bark = new THREE.Color('#5a4a3c'), leaf = new THREE.Color(id.startsWith('magnolia') ? '#2f4a26' : id.includes('pine') ? '#33462a' : id.includes('crepe') ? '#4f6a33' : id.includes('cypress') ? '#5b6b3a' : '#3f5a2c');
  const seg = lod ? 5 : 8;
  const add = (g, c) => { const col = new Float32Array(g.attributes.position.count * 3); for (let i = 0; i < col.length; i += 3) { const y = g.attributes.position.array[i + 1]; const k = c === bark ? 1 : 0.75 + 0.35 * Math.min(1, y / 14); col[i] = c.r * k; col[i + 1] = c.g * k; col[i + 2] = c.b * k; } g.setAttribute('color', new THREE.BufferAttribute(col, 3)); parts.push({ g: g.toNonIndexed ? g : g, leaf: c !== bark }); };
  const blob = (r, x, y, z, sy = 0.8) => { const g = new THREE.IcosahedronGeometry(r, lod ? 0 : 1); g.scale(1, sy, 1); g.translate(x, y, z); return g; };
  if (id.includes('pine')) {
    const H = id === 'pine-young' ? 10 : 22;
    add(new THREE.CylinderGeometry(0.18, 0.32, H * 0.75, seg).translate(0, H * 0.375, 0), bark);
    add(blob(H * 0.16, 0, H * 0.82, 0, 0.7), leaf); add(blob(H * 0.12, H * 0.08, H * 0.72, 0.5, 0.7), leaf);
  } else if (id === 'sabal-palmetto') {
    add(new THREE.CylinderGeometry(0.2, 0.25, 8, seg).translate(0, 4, 0), bark);
    add(blob(2.2, 0, 8.5, 0, 0.5), leaf);
  } else if (id.startsWith('crepe')) {
    add(new THREE.CylinderGeometry(0.08, 0.12, 2.5, seg).translate(0, 1.25, 0), bark);
    add(blob(2.0, 0, 3.4, 0, 0.75), leaf); add(blob(1.4, 0.9, 3.9, 0.3, 0.8), leaf);
  } else if (id === 'bald-cypress') {
    add(new THREE.CylinderGeometry(0.25, 0.6, 14, seg).translate(0, 7, 0), bark);
    add(new THREE.ConeGeometry(3.2, 13, seg).translate(0, 11, 0), leaf);
  } else if (id === 'magnolia') {
    add(new THREE.CylinderGeometry(0.2, 0.3, 3, seg).translate(0, 1.5, 0), bark);
    add(new THREE.ConeGeometry(3.6, 9, seg + 2).translate(0, 6.5, 0), leaf);
  } else { // oaks, hardwoods
    const big = id === 'live-oak', H = big ? 15 : id === 'hardwood' ? 14 : 8, R = big ? 9 : id === 'hardwood' ? 5 : 4;
    add(new THREE.CylinderGeometry(0.3, 0.55, H * 0.45, seg).translate(0, H * 0.22, 0), bark);
    add(blob(R * 0.62, 0, H * 0.6, 0), leaf); add(blob(R * 0.5, R * 0.45, H * 0.52, R * 0.2), leaf); add(blob(R * 0.5, -R * 0.4, H * 0.55, -R * 0.25), leaf); if (!lod) add(blob(R * 0.42, R * 0.1, H * 0.75, -R * 0.4), leaf);
  }
  const barkG = mergeGeometries(parts.filter(p => !p.leaf).map(p => p.g.index ? p.g.toNonIndexed() : p.g));
  const leafG = mergeGeometries(parts.filter(p => p.leaf).map(p => p.g.index ? p.g.toNonIndexed() : p.g));
  return { bark: barkG, leaves: leafG };
}

// ---------------------------------------------------------------- materials (wind sway + style)
function treeMaterial(kind) {
  const m = new THREE.MeshStandardMaterial({ name: 'tree-' + kind, vertexColors: true, roughness: kind === 'leaves' ? 0.82 : 0.9, metalness: 0 });
  m.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, { uTime: U.uTime, uStyle: U.uStyle });
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nuniform float uTime;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
      #ifdef USE_INSTANCING
        float ph = instanceMatrix[3].x * .013 + instanceMatrix[3].z * .017;
        float sway = smoothstep(2., 18., transformed.y) * (.05 + .04 * sin(uTime * 1.7 + ph));
        transformed.x += sway * sin(uTime * .9 + ph); transformed.z += sway * cos(uTime * .7 + ph);
      #endif`);
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uStyle;')
      .replace('#include <color_fragment>', `#include <color_fragment>
      if (uStyle > .5) { diffuseColor.rgb = uStyle < 1.5 ? vec3(.62, .72, .5) : uStyle < 2.5 ? vec3(.06, .09, .065) : vec3(.92); }`);
  };
  return m;
}

// ---------------------------------------------------------------- the forest manager
export class Trees {
  constructor(app) {
    this.app = app; this.D = app.D; this.group = new THREE.Group(); this.group.name = 'trees';
    this.cells = new Map(); this.kit = null; this.last = null; this.enabled = true;
    this.mats = { bark: treeMaterial('bark'), leaves: treeMaterial('leaves') };
    this.meshes = []; // [species][lod] -> {bark, leaves} InstancedMesh
  }

  async init() {
    const kit = await fetch('models/vegetation/index.json').then(r => (r.ok ? r.json() : null)).catch(() => null);
    const loader = new GLTFLoader();
    const geo = {};
    for (const id of SPECIES) {
      geo[id] = [];
      for (const lod of [0, 1]) {
        let g = null;
        const entry = kit && kit.find(k => k.id === id);
        if (entry) {
          try {
            const gl = await loader.loadAsync(`models/vegetation/${id}${lod ? '-lod1' : ''}.glb`);
            g = splitByMaterial(gl.scene);
          } catch (e) { g = null; }
        }
        geo[id].push(g || standIn(id, lod));
      }
    }
    this.kitLoaded = !!kit;
    // instanced meshes with generous capacity; counts change per update
    const cap = [9000, 26000];
    this.meshes = SPECIES.map(id => [0, 1].map(lod => {
      const g = geo[id][lod]; const out = {};
      for (const part of ['bark', 'leaves']) {
        if (!g[part]) continue;
        const m = new THREE.InstancedMesh(g[part], this.mats[part], cap[lod]);
        m.count = 0; m.castShadow = lod === 0 || part === 'leaves'; m.receiveShadow = true; m.frustumCulled = false; m.name = `tree ${id} ${part} lod${lod}`;
        m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        if (part === 'leaves') m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cap[lod] * 3), 3);
        this.group.add(m); out[part] = m;
      }
      return out;
    }));
    U.uTreeRange.value = LOD1;
    this.app.scene.add(this.group);
  }

  // ---- scatter one 250 m cell (deterministic)
  cell(ci, cj) {
    const key = ci + ':' + cj; let c = this.cells.get(key); if (c) return c;
    const D = this.D, x0 = ci * CELL, y0 = cj * CELL, out = [];
    const R = rng(Math.imul(ci, 73856093) ^ Math.imul(cj, 19349663));
    const clearOf = (x, y, r) => {
      if (!(D.mask.at(x, y) & 1) || (D.mask.at(x, y) & 2)) return false;
      let ok = true;
      D.bGrid.query(x - r - 2, y - r - 2, x + r + 2, y + r + 2, k => {
        const b = D.buildings[k]; if (b.hero) return; const p = b.poly;
        // distance from point to the rectangle (in its own frame)
        const ux = (p[2] - p[0]) / b.w, uy = (p[3] - p[1]) / b.w, vx = (p[6] - p[0]) / b.d, vy = (p[7] - p[1]) / b.d;
        const dx = x - b.cx, dy = y - b.cy, a = Math.abs(dx * ux + dy * uy) - b.w / 2, bb = Math.abs(dx * vx + dy * vy) - b.d / 2;
        if (Math.hypot(Math.max(a, 0), Math.max(bb, 0)) < r) { ok = false; return false; }
      });
      if (!ok) return false;
      const nr = nearestRoad(D, x, y, 30); if (nr && nr.d < (HALF[nr.road.cls] || 3) + r * 0.6 + 1.2) return false;
      if (inHeroLot(D, x, y, r)) return false; // modeled lots bring their own trees
      if (D.driveGrid) { let onDrive = false; D.driveGrid.query(x - r, y - r, x + r, y + r, k => { const d = D.drives[k]; const dx = d.x1 - d.x0, dy = d.y1 - d.y0, L2 = dx * dx + dy * dy; const t = Math.max(0, Math.min(1, ((x - d.x0) * dx + (y - d.y0) * dy) / L2)); if (Math.hypot(d.x0 + dx * t - x, d.y0 + dy * t - y) < d.w / 2 + r * 0.5 + 0.4) { onDrive = true; return false; } }); if (onDrive) return false; }
      return true;
    };
    const push = (sp, x, y, s) => out.push({ sp, x, y, s, r: R() * Math.PI * 2, tint: R() });
    // 1. woods and forests: jittered grid
    D.luGrid.query(x0, y0, x0 + CELL, y0 + CELL, k => {
      const l = D.lu[k];
      const dense = l.kind === 'woods' || l.kind === 'forest' ? (l.kind === 'forest' ? 8 : 9.5) : l.kind === 'park' ? 20 : l.kind === 'cemetery' ? 22 : l.kind === 'golf' ? 30 : l.kind === 'residential' || l.kind === 'civic' || l.kind === 'school' ? 0 : 0;
      if (!dense) return;
      for (let gx = x0 + dense / 2; gx < x0 + CELL; gx += dense) for (let gy = y0 + dense / 2; gy < y0 + CELL; gy += dense) {
        const x = gx + (R() - 0.5) * dense * 0.9, y = gy + (R() - 0.5) * dense * 0.9;
        if (!pointInPoly(x, y, l.rings)) continue;
        const wet = D.mask.at(x + 25, y) === 0 || D.mask.at(x - 25, y) === 0 || D.mask.at(x, y + 25) === 0 || D.mask.at(x, y - 25) === 0;
        const r = R();
        const sp = wet && r < 0.5 ? 'bald-cypress' : l.kind === 'park' || l.kind === 'golf' ? (r < 0.5 ? 'live-oak' : r < 0.75 ? 'hardwood' : 'magnolia') : l.kind === 'cemetery' ? (r < 0.6 ? 'live-oak' : 'magnolia') : r < 0.5 ? 'loblolly-pine' : r < 0.62 ? 'pine-young' : r < 0.86 ? 'hardwood' : r < 0.94 ? 'live-oak-young' : 'magnolia';
        if (clearOf(x, y, 2)) push(sp, x, y, 0.8 + R() * 0.45);
      }
    });
    // 2. yard trees around homes
    D.bGrid.query(x0, y0, x0 + CELL, y0 + CELL, k => {
      const b = D.buildings[k]; if (b.cx < x0 || b.cx >= x0 + CELL || b.cy < y0 || b.cy >= y0 + CELL) return;
      if (!['house', 'duplex', 'mobile', 'townhouse', 'apartments', 'church', 'civic', 'school'].includes(b.kind)) return;
      const rb = hash(b.i * 2654435761 >>> 0);
      const n = b.kind === 'mobile' ? (rb < 0.4 ? 1 : 0) : b.kind === 'apartments' || b.kind === 'school' ? 4 : rb < 0.12 ? 0 : rb < 0.45 ? 1 : rb < 0.8 ? 2 : 3;
      for (let t = 0; t < n; t++) {
        for (let tries = 0; tries < 6; tries++) {
          const ang = R() * Math.PI * 2, dist = Math.max(b.w, b.d) / 2 + 4 + R() * 12;
          const x = b.cx + Math.cos(ang) * dist, y = b.cy + Math.sin(ang) * dist;
          const r = R();
          const sp = b.kind === 'mobile' ? (r < 0.6 ? 'loblolly-pine' : 'hardwood') : r < 0.26 ? 'live-oak' : r < 0.5 ? 'magnolia' : r < 0.66 ? 'crepe-myrtle' : r < 0.72 ? 'crepe-myrtle-pink' : r < 0.84 ? 'loblolly-pine' : r < 0.94 ? 'hardwood' : 'live-oak-young';
          const rad = sp === 'live-oak' ? 6 : sp.startsWith('crepe') ? 1.5 : 3;
          if (clearOf(x, y, rad)) { push(sp, x, y, 0.75 + R() * 0.4); break; }
        }
      }
    });
    // 3. street trees in the old grid neighborhoods
    D.rGrid.query(x0, y0, x0 + CELL, y0 + CELL, id => {
      const s = D.segs[id], r = D.roads[s[4]];
      if (r.bridge || !['residential', 'tertiary'].includes(r.cls)) return;
      const mx = (s[0] + s[2]) / 2, my = (s[1] + s[3]) / 2; if (mx < x0 || mx >= x0 + CELL || my < y0 || my >= y0 + CELL) return;
      const old = Math.hypot(mx + 900, my - 900) < 1700; // Garden District, Downtown edges, North End
      if (!old) return;
      const L = Math.hypot(s[2] - s[0], s[3] - s[1]); const ux = (s[2] - s[0]) / L, uy = (s[3] - s[1]) / L;
      for (let d = 7; d < L - 7; d += 15) for (const side of [-1, 1]) {
        const o = (HALF[r.cls] + 1.1) * side; const x = s[0] + ux * d - uy * o, y = s[1] + uy * d + ux * o;
        if (R() < 0.25) continue;
        if (clearOf(x, y, 1.0)) push(R() < 0.7 ? 'live-oak' : 'magnolia', x, y, 0.62 + R() * 0.3);
      }
    });
    c = { trees: out, x: x0 + CELL / 2, y: y0 + CELL / 2 };
    this.cells.set(key, c);
    return c;
  }

  update(force = false) {
    if (!this.meshes.length) return;
    const cam = this.app.camera.position, ax = cam.x, ay = -cam.z, h = Math.max(0, cam.y);
    const tgt = this.app.controls.target;
    if (!force && this.last && Math.hypot(ax - this.last[0], ay - this.last[1]) < 40 && Math.abs(h - this.last[2]) < 25 && Math.hypot(tgt.x - this.last[3], tgt.z - this.last[4]) < 60) return;
    this.last = [ax, ay, h, tgt.x, tgt.z];
    const counts = this.meshes.map(() => [0, 0]);
    const show = this.enabled && h < 6000;
    if (show) {
      // the region around the point under the view and around the camera
      const cx = (ax + tgt.x) / 2, cy = (ay - tgt.z) / 2, R = LOD1 + Math.hypot(ax - tgt.x, ay + tgt.z) / 2;
      const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), col = new THREE.Color(), up = new THREE.Vector3(0, 1, 0);
      for (let ci = Math.floor((cx - R) / CELL); ci <= Math.floor((cx + R) / CELL); ci++) for (let cj = Math.floor((cy - R) / CELL); cj <= Math.floor((cy + R) / CELL); cj++) {
        const ccx = (ci + 0.5) * CELL, ccy = (cj + 0.5) * CELL;
        const dc = Math.hypot(ccx - ax, ccy - ay, h); if (dc > LOD1 + CELL) continue;
        const c = this.cell(ci, cj);
        for (const t of c.trees) {
          const d = Math.hypot(t.x - ax, t.y - ay, h);
          const lod = d < LOD0 ? 0 : d < LOD1 ? 1 : -1; if (lod < 0) continue;
          const si = SP[t.sp]; const set = this.meshes[si][lod]; const idx = counts[si][lod];
          const capN = set.leaves ? set.leaves.instanceMatrix.count : 0; if (idx >= capN) continue;
          q.setFromAxisAngle(up, t.r); s.setScalar(t.s); p.set(t.x, 0, -t.y);
          m.compose(p, q, s);
          if (set.bark) set.bark.setMatrixAt(idx, m);
          if (set.leaves) { set.leaves.setMatrixAt(idx, m); const k = 0.86 + t.tint * 0.28; col.setRGB(k * (0.95 + t.tint * 0.1), k, k * (0.9 + (1 - t.tint) * 0.15)); set.leaves.setColorAt(idx, col); }
          counts[si][lod]++;
        }
      }
    }
    this.meshes.forEach((lods, si) => lods.forEach((set, lod) => {
      for (const part of ['bark', 'leaves']) { const im = set[part]; if (!im) continue; im.count = counts[si][lod]; im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; im.visible = im.count > 0; }
    }));
    this.total = counts.reduce((a, c) => a + c[0] + c[1], 0);
  }
}

// GLB scene -> {bark, leaves} geometries in the model's own units, vertex colors kept
function splitByMaterial(root) {
  const parts = { bark: [], leaves: [] };
  root.updateMatrixWorld(true);
  root.traverse(o => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    const g = o.geometry.clone(); g.applyMatrix4(o.matrixWorld);
    const keep = ['position', 'normal', 'color'];
    for (const k of Object.keys(g.attributes)) if (!keep.includes(k)) g.deleteAttribute(k);
    if (!g.attributes.color) { const c = new Float32Array(g.attributes.position.count * 3).fill(1); g.setAttribute('color', new THREE.BufferAttribute(c, 3)); }
    else if (g.attributes.color.itemSize === 4) { const a = g.attributes.color, c = new Float32Array(a.count * 3); for (let i = 0; i < a.count; i++) { c[i * 3] = a.getX(i); c[i * 3 + 1] = a.getY(i); c[i * 3 + 2] = a.getZ(i); } g.setAttribute('color', new THREE.BufferAttribute(c, 3)); }
    // multiply in the material's base color so flat-colored kits still read
    const mc = mats[0].color || new THREE.Color(1, 1, 1); const ca = g.attributes.color;
    const arr = new Float32Array(ca.count * 3); for (let i = 0; i < ca.count; i++) { arr[i * 3] = ca.getX(i) * mc.r; arr[i * 3 + 1] = ca.getY(i) * mc.g; arr[i * 3 + 2] = ca.getZ(i) * mc.b; } g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
    const isLeaf = /leaf|leaves|foliage|moss|crown|frond/i.test(mats[0].name || o.name);
    (isLeaf ? parts.leaves : parts.bark).push(g.index ? g.toNonIndexed() : g);
  });
  return { bark: parts.bark.length ? mergeGeometries(parts.bark) : null, leaves: parts.leaves.length ? mergeGeometries(parts.leaves) : null };
}
