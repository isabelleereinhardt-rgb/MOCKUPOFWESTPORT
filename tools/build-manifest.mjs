// Collects every Blender model's metadata into data/models.json, which the map reads at load.
// Run after adding or rebuilding models: node tools/build-manifest.mjs
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const read = f => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
const exists = f => f && fs.existsSync(path.join(ROOT, f));
const list = dir => (fs.existsSync(path.join(ROOT, dir)) ? fs.readdirSync(path.join(ROOT, dir)) : []);

const specs = Object.fromEntries(read('docs/site-specs.json').homes.map(h => [h.id, h]));
const out = { version: 1, homes: [], landmarks: [], archetypes: [], replaces: [] };

for (const f of list('models/homes').filter(f => f.endsWith('.json'))) {
  const m = read('models/homes/' + f), s = specs[m.id];
  if (!s || !exists(m.files?.house)) continue;
  out.homes.push({
    id: m.id, name: m.name, address: m.address, neighborhood: m.neighborhood, residents: m.residents || [], status: m.status,
    house: m.files.house, lot: exists(m.files.lot) ? m.files.lot : null,
    at: s.center_atlas, heading: s.front_heading_deg_atlas, building: m.atlas_building_index ?? s.building_index,
    render: exists(`renders/${m.id}.jpg`) ? `renders/${m.id}.jpg` : null, aerial: exists(`renders/${m.id}-aerial.jpg`) ? `renders/${m.id}-aerial.jpg` : null,
    style: m.style, stories: m.stories, ridge: m.ridge_height_m, footprint: m.footprint_m, materials: m.materials, notes: m.notes, triangles: m.triangles,
    lotRect: m.lot_local_rect_m,
  });
  out.replaces.push(m.atlas_building_index ?? s.building_index);
}

for (const f of list('models/landmarks').filter(f => f.endsWith('.json'))) {
  const m = read('models/landmarks/' + f);
  const id = m.id || f.replace('.json', '');
  const file = m.file || m.files?.model || `models/landmarks/${id}.glb`;
  if (!exists(file)) continue;
  const a = m.atlas || m.placement || m;
  const at = a.center_atlas || a.center || a.at || a.position_atlas;
  const heading = a.front_heading_deg_atlas ?? a.heading ?? 90;
  const bi = a.building_index ?? a.atlas_building_index ?? null;
  if (!at) continue;
  out.landmarks.push({ id, name: m.name || id, file, at, heading, building: bi, height: m.height_m || null, notes: m.notes || '' });
  if (bi != null && bi >= 0) out.replaces.push(bi);
}

for (const f of list('models/archetypes').filter(f => /^index-.*\.json$/.test(f))) {
  const arr = read('models/archetypes/' + f);
  for (const a of arr) if (exists(`models/archetypes/${a.id}.glb`)) out.archetypes.push({ ...a, file: `models/archetypes/${a.id}.glb` });
}

fs.writeFileSync(path.join(ROOT, 'data/models.json'), JSON.stringify(out, null, 1));
console.log(`models.json: ${out.homes.length} homes, ${out.landmarks.length} landmarks, ${out.archetypes.length} archetypes, ${out.replaces.length} Atlas buildings replaced`);
