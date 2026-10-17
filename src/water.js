// Water: one sheet under the whole map at the water line, shaded by distance to shore.
import * as THREE from 'three';
import { patch, loadTex } from './shaders.js';
import { WATER_Y } from './core.js';

export function buildWater(shoreTex) {
  const b = shoreTex.userData;
  const m = new THREE.MeshStandardMaterial({ name: 'water', roughness: 0.05, metalness: 0.0, envMapIntensity: 1.0 });
  patch(m, {
    key: 'water',
    uniforms: { tShore: { value: shoreTex }, tWaterN: { value: loadTex('assets/tex/water_n.jpg', { srgb: false }) }, uFrame: { value: new THREE.Vector4(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0) } },
    fHead: 'uniform sampler2D tShore; uniform sampler2D tWaterN; uniform vec4 uFrame; varying float vShoreD; varying float vFoam;',
    color: /* glsl */`
      vec2 p = vec2(vWPos.x, -vWPos.z);
      vec2 suv = (p - uFrame.xy) / uFrame.zw;
      float inF = step(0., suv.x) * step(suv.x, 1.) * step(0., suv.y) * step(suv.y, 1.);
      vec4 sh = texture2D(tShore, clamp(suv, 0., 1.));
      float dShore = mix(400., sh.r * 400., inF);
      float shoal = sh.g * inF;
      float cd = length(vWPos - cameraPosition);
      if (uStyle > .5 && uStyle < 1.5) { col = srgb(vec3(.663, .788, .871)); rough = 1.; }
      else if (uStyle > 1.5 && uStyle < 2.5) { col = srgb(vec3(.039, .075, .11)); rough = 1.; }
      else if (uStyle > 2.5) { col = vec3(.74, .76, .78); rough = .6; }
      else {
        float river = clamp((p.y + 7000.) / 6000., 0., 1.);
        vec3 deep = mix(srgb(vec3(.06, .16, .21)), srgb(vec3(.10, .14, .12)), river);
        vec3 shallow = mix(srgb(vec3(.20, .36, .35)), srgb(vec3(.25, .27, .20)), river);
        col = mix(shallow, deep, smoothstep(0., 200., dShore));
        col = mix(col, srgb(vec3(.50, .50, .38)), shoal * .55);
        float foam = (1. - smoothstep(1.5, 10., dShore)) * smoothstep(.42, .72, fbm(p * .22 + vec2(uTime * .25, -uTime * .18)));
        foam *= 1. - river * .75;
        col = mix(col, vec3(.82, .84, .82), foam * .7 * smoothstep(2500., 400., cd));
        rough = .04 + foam * .55 + smoothstep(1500., 9000., cd) * .06;
      }
    `,
    normal: /* glsl */`
      if (uStyle < .5) {
        vec2 p = vec2(vWPos.x, -vWPos.z);
        float cd = length(vWPos - cameraPosition);
        vec3 n1 = texture2D(tWaterN, p / 41. + uTime * vec2(.011, .006)).xyz * 2. - 1.;
        vec3 n2 = texture2D(tWaterN, p / 13.7 - uTime * vec2(.007, .013)).xyz * 2. - 1.;
        vec3 n3 = texture2D(tWaterN, p / 190. + uTime * vec2(.002, -.003)).xyz * 2. - 1.;
        vec2 n = n1.xy * .55 + n2.xy * .35 + n3.xy * .5;
        float k = mix(.42, .06, smoothstep(150., 5000., cd));
        nW = normalize(vec3(n.x * k, 1., -n.y * k));
      }
    `,
  });
  // A two-triangle plane this size loses depth precision near the camera, enough for the water to show
  // through driveways and walks on the modeled lots. A grid packed toward the town keeps triangles small there.
  const g = new THREE.PlaneGeometry(2, 2, 160, 160); g.rotateX(-Math.PI / 2);
  const pos = g.attributes.position, warp = t => Math.sign(t) * 200000 * Math.abs(t) ** 3;
  for (let i = 0; i < pos.count; i++) pos.setXYZ(i, warp(pos.getX(i)), 0, warp(pos.getZ(i)));
  g.computeBoundingSphere();
  const mesh = new THREE.Mesh(g, m); mesh.position.y = WATER_Y; mesh.receiveShadow = true; mesh.name = 'water';
  // painted first among the flat layers; nothing at ground level writes depth, so nothing can fight
  m.depthWrite = false; mesh.renderOrder = 5;
  return mesh;
}
