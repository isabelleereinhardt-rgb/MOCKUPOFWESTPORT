// Westport 3D: boot, scene assembly, camera and render loop.
import * as THREE from 'three';
import { MapControls } from 'three/addons/controls/MapControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { loadJSON, decode, toWorld, setHeroLots } from './core.js';
import { U } from './shaders.js';
import { buildGround, shoreTexture } from './ground.js';
import { buildWater } from './water.js';
import { buildRoads, roadMaterial } from './roads.js';
import { buildLots, updateLots } from './lots.js';
import { buildBuildings } from './buildings.js';
import { Atmosphere } from './sky.js';
import { Trees } from './trees.js';
import { Models } from './models.js';
import { UI } from './ui.js';
import { Archetypes } from './archetypes.js';

const Q = new URLSearchParams(location.search);
const say = msg => { const el = document.getElementById('loadmsg'); if (el) el.textContent = msg; };
const tick = () => new Promise(r => setTimeout(r, 0));

export const STYLES = [
  { id: 'realistic', bg: null }, { id: 'atlas', bg: '#a9c9de' }, { id: 'shadows', bg: '#0a131c' }, { id: 'clay', bg: '#e9e7e2' },
];

export class App {
  constructor() {
    this.el = document.getElementById('view');
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: !Q.has('noaa'), powerPreference: 'high-performance', preserveDrawingBuffer: Q.has('shot'), logarithmicDepthBuffer: false });
    r.setPixelRatio(Math.min(window.devicePixelRatio, Q.has('shot') ? 1 : 2));
    r.setSize(this.el.clientWidth, this.el.clientHeight);
    r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 0.92;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    this.el.appendChild(r.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, this.el.clientWidth / this.el.clientHeight, 1, 300000);
    this.controls = new MapControls(this.camera, r.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.09, zoomToCursor: true, screenSpacePanning: false, minDistance: 12, maxDistance: 45000, maxPolarAngle: Math.PI * 0.47, zoomSpeed: 1.2 });
    this.atm = new Atmosphere(r, this.scene);
    this.clock = new THREE.Clock();
    this.style = 0;
    this.onFrame = [];
    window.addEventListener('resize', () => this.resize());
  }

  async load() {
    say('Reading the Atlas');
    const [wp, gaz, qa, models] = await Promise.all([loadJSON('data/wpdata.json'), loadJSON('data/gaz.json', true), loadJSON('data/qa.json', true), loadJSON('data/models.json', true)]);
    this.D = decode(wp, gaz, qa); this.D.models = models;
    setHeroLots(this.D, models && models.homes);
    await tick(); say('Laying out the coastline');
    this.shore = shoreTexture(this.D);
    this.water = buildWater(this.shore); this.scene.add(this.water);
    this.ground = buildGround(this.D); this.scene.add(this.ground);
    await tick(); say('Paving the streets');
    this.roads = buildRoads(this.D); this.scene.add(this.roads);
    await tick(); say(`Raising ${this.D.buildings.length.toLocaleString()} buildings`);
    const heroes = new Set((models && models.replaces) || []);
    this.buildings = buildBuildings(this.D, { separate: heroes }); this.scene.add(this.buildings);
    this.models = new Models(this);
    if (models) {
      const proxies = this.buildings.userData.proxies;
      const reg = [...models.homes.map(h => ({ ...h, kind: 'home' })), ...models.landmarks.map(l => ({ ...l, kind: 'landmark' }))];
      reg.forEach(r => { r.proxy = r.building != null ? proxies.get(r.building) : null; });
      this.models.register(reg);
    }
    await tick(); say('Laying driveways and parking the cars');
    this.lots = buildLots(this.D); this.scene.add(this.lots);
    { const m = new THREE.Mesh(this.lots.userData.driveGeometry, roadMaterial(7)); m.name = 'driveways'; m.receiveShadow = true; m.renderOrder = 17.1; this.lots.add(m); }
    await tick(); say('Planting the trees');
    this.trees = new Trees(this); await this.trees.init(); this.trees.update(true);
    this.arch = new Archetypes(this, models && models.archetypes);
    this.arch.init().then(() => this.arch.update(true));
    this.onFrame.push(() => { this.trees.update(); this.models.update(); this.arch.update(); updateLots(this.lots, this.camera.position); });
    this.composer = this.makeComposer();
    this.applyView(Q.get('view') || '-300,150,2300,345,60');
    if (!Q.has('noui')) this.ui = new UI(this);
    if (Q.has('style')) this.setStyle(+Q.get('style'));
    if (Q.has('hour')) this.atm.setHour(+Q.get('hour'));
    this.resize();
  }

  makeComposer() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    const rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: Q.has('noaa') ? 0 : 4 });
    const c = new EffectComposer(this.renderer, rt);
    c.addPass(new RenderPass(this.scene, this.camera));
    this.ao = null;
    if (Q.get('ao') !== '0') {
      this.ao = new GTAOPass(this.scene, this.camera, w, h);
      this.ao.output = GTAOPass.OUTPUT.Default;
      this.ao.blendIntensity = 0.85;
      this.ao.updateGtaoMaterial({ radius: 6, distanceExponent: 1.4, thickness: 3, scale: 1.0, samples: 12 });
      this.ao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 });
      c.addPass(this.ao);
    }
    c.addPass(new OutputPass());
    return c;
  }

  /** view = "x,y,dist,heading,tilt" in Atlas meters and compass degrees (tilt 0 = straight down). */
  applyView(v) {
    const [x, y, d, hd, tl] = v.split(',').map(Number);
    const target = toWorld(x, y, 0);
    const h = THREE.MathUtils.degToRad(hd), t = THREE.MathUtils.degToRad(Math.max(0.5, tl));
    const off = new THREE.Vector3(-Math.sin(h) * Math.sin(t), Math.cos(t), Math.cos(h) * Math.sin(t)).multiplyScalar(d);
    this.controls.target.copy(target); this.camera.position.copy(target).add(off); this.camera.lookAt(target); this.controls.update();
  }
  getView() {
    const t = this.controls.target, o = this.camera.position.clone().sub(t), d = o.length();
    const tilt = THREE.MathUtils.radToDeg(Math.acos(o.y / d)), hd = (THREE.MathUtils.radToDeg(Math.atan2(-o.x, o.z)) + 360) % 360;
    return [t.x, -t.z, d, hd, tilt].map(n => Math.round(n)).join(',');
  }

  setStyle(i) {
    this.style = i; U.uStyle.value = i;
    this.atm.setStyle(i, STYLES[i].bg || '#c6d3dc');
    this.renderer.toneMapping = i === 0 ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;
    if (this.ao) this.ao.enabled = i === 0 || i === 3;
    if (this.models) this.models.applyStyle(i);
    if (this.arch) this.arch.applyStyle(i);
    for (const fn of this.onStyle || []) fn(i);
  }

  resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h); if (this.composer) this.composer.setSize(w, h);
  }

  frame() {
    const dt = Math.min(0.1, this.clock.getDelta());
    U.uTime.value += dt;
    this.controls.update();
    const d = this.camera.position.distanceTo(this.controls.target);
    U.uCamDist.value = d;
    const camH = Math.max(1, this.camera.position.y);
    this.camera.near = THREE.MathUtils.clamp(Math.min(camH, d) * 0.04, 0.25, 60);
    this.camera.far = 300000; this.camera.updateProjectionMatrix();
    this.atm.follow(this.controls.target, d);
    for (const fn of this.onFrame) fn(dt, d);
    if (this.composer) this.composer.render(); else this.renderer.render(this.scene, this.camera);
  }
  start() { const loop = () => { this.frame(); this.raf = requestAnimationFrame(loop); }; loop(); }
}

export async function boot() {
  const app = window.WP = new App();
  try {
    await app.load();
    document.getElementById('loading').style.display = 'none';
    app.start();
    window.WP_READY = true;
  } catch (e) {
    console.error(e); say('The map could not load: ' + e.message);
  }
  return app;
}
