// Shared shader pieces. Every map surface is a MeshStandardMaterial patched with onBeforeCompile,
// so it keeps three.js lighting, shadows, fog and image-based reflections.
import * as THREE from 'three';

// One uniform set shared by every patched material: map style, time, camera.
export const U = {
  uStyle: { value: 0 },      // 0 realistic, 1 atlas, 2 shadows, 3 clay
  uTime: { value: 0 },
  uNight: { value: 0 },      // 0 day .. 1 night (window lights, street lamps)
  uCamDist: { value: 1000 }, // camera distance to its target, for level-of-detail fades
  uSun: { value: new THREE.Vector3(0.4, 0.8, 0.3) }, // world direction toward the sun (set by sky.js)
  uTreeRange: { value: 0 },   // distance where 3D trees end and painted canopy takes over (0 until trees load)
};

export const NOISE = /* glsl */`
float h12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec2 h22(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * vec3(.1031, .1030, .0973)); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.xx + p3.yz) * p3.zy); }
float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3. - 2. * f);
  return mix(mix(h12(i), h12(i + vec2(1, 0)), u.x), mix(h12(i + vec2(0, 1)), h12(i + vec2(1, 1)), u.x), u.y); }
float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + 17.1; a *= .5; } return s; }
float fbm3(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 3; i++) { s += a * vnoise(p); p = p * 2.03 + 17.1; a *= .5; } return s; }
// Worley cell: x = distance to nearest feature, y = cell id hash, zw = vector to the feature
vec4 worley(vec2 p){ vec2 i = floor(p), f = fract(p); float d = 9.; vec2 best = vec2(0); float id = 0.;
  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) { vec2 g = vec2(x, y); vec2 o = h22(i + g); vec2 r = g + o - f; float dd = dot(r, r);
    if (dd < d) { d = dd; best = r; id = h12(i + g + 7.7); } }
  return vec4(sqrt(d), id, best); }
vec3 srgb(vec3 c){ return pow(c, vec3(2.2)); }
`;

const tex = new Map();
export function loadTex(url, { srgb = true, repeat = true, aniso = 8 } = {}) {
  const k = url + srgb; if (tex.has(k)) return tex.get(k);
  const t = new THREE.TextureLoader().load(url);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = aniso; tex.set(k, t); return t;
}

/** Patch a MeshStandardMaterial.
 * o.uniforms: extra uniforms; o.vHead/o.vMain: vertex additions (vWPos is provided);
 * o.fHead: fragment declarations; o.color: code that sets `vec3 col` and may set `float rough`, `float metal`, `vec3 emis`;
 * o.normal: optional code that sets `vec3 nW` (world-space normal) from vWPos etc. */
export function patch(mat, o) {
  mat.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, U, o.uniforms || {});
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vWPos;\n${o.vHead || ''}`)
      .replace('#include <project_vertex>', `#include <project_vertex>\n { vec4 wp4 = vec4(transformed, 1.0);\n#ifdef USE_INSTANCING\n wp4 = instanceMatrix * wp4;\n#endif\n vWPos = (modelMatrix * wp4).xyz; }\n${o.vMain || ''}`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vWPos;\nuniform float uStyle; uniform float uTime; uniform float uNight; uniform float uCamDist;\n${NOISE}\n${o.fHead || ''}`)
      .replace('#include <map_fragment>', `#include <map_fragment>\n float rough = roughness; float metal = metalness; vec3 emis = vec3(0.); vec3 col = diffuseColor.rgb;\n {\n${o.color || ''}\n }\n diffuseColor.rgb = col;`)
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = rough;')
      .replace('#include <metalnessmap_fragment>', 'float metalnessFactor = metal;')
      .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\n totalEmissiveRadiance += emis;');
    if (o.normal) {
      sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>\n { vec3 nW = vec3(0., 1., 0.);\n${o.normal}\n normal = normalize((viewMatrix * vec4(nW, 0.)).xyz); }`);
    }
    mat.userData.shader = sh;
  };
  mat.customProgramCacheKey = () => o.key || mat.name;
  return mat;
}
