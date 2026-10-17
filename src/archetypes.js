// Close-range detail: near the camera, homes, mobile homes, sheds and churches drawn from their
// footprints are swapped for Blender archetype models (models/archetypes), scaled to each Atlas
// rectangle, turned to face the street and tinted with the same colors the far version uses.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { hash } from './core.js';
import { U } from './shaders.js';

const NEAR = 380;       // meters (ground distance from the camera) inside which 500 m chunks switch to models
const TINT = { Wall: 'wall', Roof: 'roof', Door: 'door' };

export class Archetypes {
  constructor(app, list) {
    this.app = app; this.list = list || []; this.ready = false; this.group = new THREE.Group(); this.group.name = 'archetypes';
    this.rep = app.buildings.userData.rep; this.active = new Set(); this.byKind = new Map();
    app.scene.add(this.group);
    this.style = new THREE.MeshStandardMaterial({ color: '#f2f1ee', roughness: 0.9 });
  }
  async init() {
    if (!this.list.length) return;
    const loader = new GLTFLoader();
    for (const a of this.list) {
      try {
        const gl = await loader.loadAsync(a.file);
        a.parts = []; const groups = new Map();
        gl.scene.updateMatrixWorld(true);
        gl.scene.traverse(o => {
          if (!o.isMesh) return;
          const g = o.geometry.clone(); g.applyMatrix4(o.matrixWorld);
          const name = (o.material.name || 'Wall').replace(/\.\d+$/, '');
          for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
          if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
          let e = groups.get(name); if (!e) groups.set(name, e = { mat: o.material, geos: [] });
          e.geos.push(g.index ? g.toNonIndexed() : g);
        });
        for (const [name, e] of groups) {
          const geo = mergeGeometries(e.geos); if (!geo) continue;
          const mat = e.mat.clone(); mat.name = name;
          mat.vertexColors = false; // per-vertex colors are dropped when merging; tint comes from instance colors
          const im = new THREE.InstancedMesh(geo, mat, 1200); im.count = 0; im.castShadow = im.receiveShadow = true; im.frustumCulled = false; im.name = `arch ${a.id} ${name}`;
          im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
          if (TINT[name]) im.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(1200 * 3), 3);
          im.userData.orig = mat; im.userData.tint = TINT[name];
          this.group.add(im); a.parts.push(im);
        }
        for (const k of a.kinds || []) { let arr = this.byKind.get(k); if (!arr) this.byKind.set(k, arr = []); arr.push(a); }
      } catch (e) { console.warn('archetype failed', a.id, e); }
    }
    this.ready = this.byKind.size > 0;
  }
  pick(b) {
    const arr = this.byKind.get(b.kind) || (b.kind === 'townhouse' ? this.byKind.get('duplex') : null); if (!arr || !arr.length) return null;
    let asp = (b.fw || b.w) / Math.max(1, b.fd || b.d); const stories = b.h > 8 ? 2 : 1;
    if (b.kind === 'mobile' || b.kind === 'shed') asp = Math.min(asp, 1 / asp); // these turn to fit (see update)
    const scored = arr.map(a => ({ a, s: Math.abs(Math.log(asp / (a.best_aspect || a.bbox_m[0] / a.bbox_m[1]))) + 0.35 * Math.abs((a.stories || 1) - stories) })).sort((x, y) => x.s - y.s);
    const top = scored.filter(x => x.s < scored[0].s + 0.25).slice(0, 3);
    return top[Math.floor(hash(b.i * 31337) * top.length)].a;
  }
  update(force) {
    if (!this.ready) return;
    const cam = this.app.camera.position, ax = cam.x, ay = -cam.z, h = cam.y;
    const want = new Set();
    if (h < 900) for (const c of this.rep) { const d = Math.max(0, Math.hypot(c.cx - ax, c.cy - ay) - 354); if (Math.hypot(d, h * 0.6) < NEAR) want.add(c.key); }
    const same = want.size === this.active.size && [...want].every(k => this.active.has(k));
    if (same && !force) return;
    this.active = want;
    for (const a of this.list) if (a.parts) a.parts.forEach(p => { p.count = 0; });
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
    for (const c of this.rep) {
      const on = want.has(c.key); c.group.visible = !on;
      if (!on) continue;
      for (const b of c.list) {
        if (b.hero) continue;
        const a = this.pick(b); if (!a || !a.parts) { continue; }
        const [bw, bd, bh] = a.bbox_m, fw = b.fw || b.w, fd = b.fd || b.d;
        // mobile homes and sheds whose long side faces the street turn 90 degrees, door side to the street
        const turn = (b.kind === 'mobile' || b.kind === 'shed') && (bw / bd - 1) * (fw / fd - 1) < 0;
        if (turn) { q.setFromAxisAngle(up, Math.atan2(-b.fny, -b.fnx)); s.set(fd / bw, Math.max(2.4, b.h) / bh, fw / bd); }
        else { q.setFromAxisAngle(up, Math.atan2(b.fnx, -b.fny)); s.set(fw / bw, Math.max(2.4, b.h) / bh, fd / bd); }
        p.set(b.cx, 0, -b.cy);
        m.compose(p, q, s);
        for (const im of a.parts) {
          if (im.count >= im.instanceMatrix.count) continue;
          im.setMatrixAt(im.count, m);
          if (im.instanceColor) { const col = b.look ? b.look[im.userData.tint] : null; im.setColorAt(im.count, col || new THREE.Color(1, 1, 1)); }
          im.count++;
        }
      }
    }
    for (const a of this.list) if (a.parts) a.parts.forEach(im => { im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; im.visible = im.count > 0; });
    if (U.uStyle.value) this.applyStyle(U.uStyle.value);
  }
  applyStyle(style) { this.group.traverse(o => { if (o.isInstancedMesh) o.material = style === 0 ? o.userData.orig : this.style; }); }
}
