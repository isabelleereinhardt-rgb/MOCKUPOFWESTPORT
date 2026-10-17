// Blender-built models (the Nine's homes and landmarks) placed on their Atlas footprints.
// Each GLB faces +Z (its street front) with its origin at the footprint center on grade;
// front_heading is the Atlas angle of the front's outward normal (0 = east, 90 = north).
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { U } from './shaders.js';

// Embedded GLB textures decode through <img> rather than fetch(): a host with a strict connect-src
// (such as a published artifact) refuses fetch() of the blob: URLs the loader makes for them.
export function imageTextures(loader) {
  loader.register(parser => { parser.textureLoader = new THREE.TextureLoader(parser.options.manager).setCrossOrigin(parser.options.crossOrigin); return { name: 'WP_image_textures' }; });
  return loader;
}
// A hosted copy that cannot serve .glb files ships each model base64-packed in "<name>.glb.json"
// (tools/pack-models.mjs); a local checkout loads the .glb directly.
export const PACKED = !(location.protocol === 'file:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname));
export async function loadModel(loader, url) {
  if (PACKED) {
    const r = await fetch(url + '.json');
    if (r.ok) {
      const s = (await r.json()).glb, bin = new Uint8Array(s.length * 3 / 4 - (s.endsWith('==') ? 2 : s.endsWith('=') ? 1 : 0));
      const raw = atob(s); for (let i = 0; i < bin.length; i++) bin[i] = raw.charCodeAt(i);
      return loader.parseAsync(bin.buffer, url.replace(/[^/]*$/, ''));
    }
  }
  return loader.loadAsync(url);
}
const loader = imageTextures(new GLTFLoader());
const LOAD_RANGE = 2600; // meters from the camera before a model streams in

export function headingToRotation(deg) {
  const a = THREE.MathUtils.degToRad(deg); const nx = Math.cos(a), ny = Math.sin(a);
  return Math.atan2(nx, -ny);
}

export class Models {
  constructor(app) {
    this.app = app; this.items = []; this.group = new THREE.Group(); this.group.name = 'models';
    app.scene.add(this.group);
    this.styleMats = {
      1: new THREE.MeshStandardMaterial({ color: '#d9d1c4', roughness: 1 }),
      2: new THREE.MeshStandardMaterial({ color: '#2a2a33', roughness: 1 }),
      3: new THREE.MeshStandardMaterial({ color: '#f2f1ee', roughness: 0.9 }),
    };
  }
  register(list) {
    for (const m of list) {
      const it = { ...m, state: 'idle', root: new THREE.Group() };
      it.root.name = 'model ' + m.id;
      it.root.position.set(m.at[0], 0, -m.at[1]);
      it.root.rotation.y = headingToRotation(m.heading ?? 90);
      this.group.add(it.root);
      this.items.push(it);
    }
  }
  async load(it) {
    it.state = 'loading';
    try {
      for (const f of [it.house || it.file, it.lot].filter(Boolean)) {
        const g = await loadModel(loader, f);
        g.scene.traverse(o => {
          if (o.isMesh) {
            o.castShadow = true; o.receiveShadow = true;
            o.userData.orig = o.material;
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            for (const mm of mats) { if (mm.map) mm.map.anisotropy = 8; mm.envMapIntensity = 1; }
          }
        });
        it.root.add(g.scene);
      }
      it.state = 'ready';
      if (it.proxy) it.proxy.visible = false;
      this.applyStyle(U.uStyle.value, it);
    } catch (e) { console.warn('model failed', it.id, e); it.state = 'failed'; }
  }
  update() {
    const cam = this.app.camera.position;
    for (const it of this.items) {
      if (it.state !== 'idle') continue;
      const d = Math.hypot(cam.x - it.at[0], cam.z + it.at[1], cam.y * 0.5);
      if (d < LOAD_RANGE) this.load(it);
    }
  }
  applyStyle(style, only) {
    for (const it of only ? [only] : this.items) it.root.traverse(o => {
      if (!o.isMesh || !o.userData.orig) return;
      o.material = style === 0 ? o.userData.orig : this.styleMats[style];
    });
  }
}
