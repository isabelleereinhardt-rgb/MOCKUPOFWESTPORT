// Sky, sun, image-based light, fog and time of day.
import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';
import { U } from './shaders.js';

// The Sky shader outputs very bright radiance; scale it so the horizon reads at a normal exposure.
function dimSky(sky, k) {
  sky.material.onBeforeCompile = sh => { sh.fragmentShader = sh.fragmentShader.replace(/gl_FragColor = vec4\(\s*texColor\s*,\s*1\.0\s*\);/, 'gl_FragColor = vec4(texColor * ' + k.toFixed(3) + ', 1.0);'); };
  sky.material.needsUpdate = true;
}

export class Atmosphere {
  constructor(renderer, scene) {
    this.renderer = renderer; this.scene = scene;
    this.sky = new Sky(); this.sky.scale.setScalar(250000); this.sky.name = 'sky'; this.sky.frustumCulled = false;
    const su = this.sky.material.uniforms;
    su.turbidity.value = 3.2; su.rayleigh.value = 1.35; su.mieCoefficient.value = 0.004; su.mieDirectionalG.value = 0.82;
    dimSky(this.sky, 0.42);
    this.sky.renderOrder = -100;
    scene.add(this.sky);
    this.sun = new THREE.DirectionalLight(0xfff3e2, 3.0);
    this.sun.castShadow = true;
    const s = this.sun.shadow; s.mapSize.set(4096, 4096); s.bias = -0.00025; s.normalBias = 0.6; s.radius = 2;
    s.camera.near = 10; s.camera.far = 9000;
    scene.add(this.sun); scene.add(this.sun.target);
    this.hemi = new THREE.HemisphereLight(0xcfe3ff, 0x5b5a3f, 0.35); scene.add(this.hemi);
    this.fog = new THREE.FogExp2(0xc6d3dc, 0.000055); scene.fog = this.fog;
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.envScene = new THREE.Scene(); this.envSky = new Sky(); this.envSky.scale.setScalar(1000); this.envScene.add(this.envSky);
    for (const k of ['turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) this.envSky.material.uniforms[k].value = su[k].value;
    dimSky(this.envSky, 0.05); this.envSky.material.uniforms.showSunDisc.value = 0;
    this.dir = new THREE.Vector3(); this.hour = 15.5; this.style = 0;
    this.setHour(this.hour);
  }
  /** Sun path for coastal North Carolina in early summer: rises ENE, high in the south at 1:30 pm, sets WNW. */
  sunFor(hour) {
    const t = (hour - 6.1) / (20.4 - 6.1);
    const elev = Math.sin(Math.PI * Math.min(1, Math.max(0, t))) * 76 * Math.PI / 180 - (t < 0 || t > 1 ? 0.12 : 0);
    const az = (62 + t * (298 - 62)) * Math.PI / 180; // compass bearing the sun shines FROM
    const ce = Math.cos(elev);
    return new THREE.Vector3(Math.sin(az) * ce, Math.sin(elev), -Math.cos(az) * ce).normalize();
  }
  setHour(hour) {
    this.hour = hour;
    this.dir.copy(this.sunFor(hour));
    U.uSun.value.copy(this.dir);
    const up = this.dir.y;
    const night = THREE.MathUtils.smoothstep(-up, -0.02, 0.12);
    U.uNight.value = night;
    const warm = THREE.MathUtils.smoothstep(0.35 - up, 0.0, 0.3);
    this.sun.color.setRGB(1, 0.96 - warm * 0.22, 0.9 - warm * 0.42);
    this.sun.intensity = Math.max(0, THREE.MathUtils.smoothstep(up, -0.02, 0.15)) * 2.6;
    this.hemi.intensity = 0.12 + 0.26 * THREE.MathUtils.smoothstep(up, -0.1, 0.4);
    this.hemi.color.setRGB(0.78 - night * 0.6, 0.86 - night * 0.6, 1.0 - night * 0.5);
    for (const sk of [this.sky, this.envSky]) sk.material.uniforms.sunPosition.value.copy(this.dir);
    const fogC = new THREE.Color().setRGB(0.76 - warm * 0.05, 0.82 - warm * 0.1, 0.86 - warm * 0.2).multiplyScalar(1 - night * 0.85);
    this.fog.color.copy(fogC);
    this.renderer.toneMappingExposure = 0.92 + night * 0.6;
    this.updateEnv();
  }
  updateEnv() {
    if (this.envRT) this.envRT.dispose();
    this.envRT = this.pmrem.fromScene(this.envScene, 0.02);
    this.scene.environment = this.envRT.texture;
    this.scene.environmentIntensity = this.style === 0 ? 1.0 : 0.6;
  }
  setStyle(style, bg) {
    this.style = style;
    this.sky.visible = style === 0;
    this.scene.background = style === 0 ? null : new THREE.Color(bg);
    this.fog.color.set(style === 0 ? this.fog.color : bg);
    if (style !== 0) this.fog.color.set(bg);
    this.baseFog = style === 0 ? 1 : 0.6;
    this.sun.castShadow = style !== 1;
    this.scene.environmentIntensity = style === 0 ? 1.0 : 0.6;
    if (style === 0) this.setHour(this.hour);
  }
  /** Keep the shadow map centered on what the camera looks at, sized to the view. */
  follow(target, viewDist) {
    const ext = THREE.MathUtils.clamp(viewDist * 0.85, 120, 2600);
    const cam = this.sun.shadow.camera;
    cam.left = -ext; cam.right = ext; cam.top = ext; cam.bottom = -ext;
    const texel = (2 * ext) / this.sun.shadow.mapSize.x;
    const t = target.clone(); t.x = Math.round(t.x / texel) * texel; t.z = Math.round(t.z / texel) * texel; t.y = 0;
    this.sun.target.position.copy(t);
    this.sun.position.copy(t).addScaledVector(this.dir, 4000);
    cam.far = 9000; cam.updateProjectionMatrix();
    // haze scales with the view: light around what you look at, thick toward the horizon
    this.fog.density = (this.baseFog ?? 1) * 0.3 / Math.max(600, viewDist * 3.2);
    this.sun.shadow.normalBias = 0.25 + ext / 900;
  }
}
