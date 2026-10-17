// Packs every .glb under models/ as base64 in "<name>.glb.json" for hosts that cannot serve .glb files
// (the map's loadModel() reads these when it is not running from a local server).
// Usage: node tools/pack-models.mjs <out dir>   (writes <out dir>/models/**/<name>.glb.json)
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.resolve(process.argv[2] || path.join(ROOT, 'dist'));
let n = 0, bytes = 0;
const walk = dir => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) walk(f);
    else if (e.name.endsWith('.glb')) {
      const rel = path.relative(ROOT, f), dst = path.join(OUT, rel + '.json');
      fs.mkdirSync(path.dirname(dst), { recursive: true });
      const body = JSON.stringify({ glb: fs.readFileSync(f).toString('base64') });
      fs.writeFileSync(dst, body); n++; bytes += body.length;
    }
  }
};
walk(path.join(ROOT, 'models'));
console.log(`packed ${n} models, ${(bytes / 1e6).toFixed(1)} MB, into ${OUT}`);
