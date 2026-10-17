// Map check, step 2: road network connectivity. Run after audit.mjs.
// The Atlas road network falls into separate pieces: streets that stop short of the road they should
// meet. The router (src/roadgraph.js) finds the shortest link over land that joins each loose piece.
// Short links that clear every building are added to the map as road extensions (fixes.add_roads,
// marked proposed); the rest are flagged for the author and only the router uses them.
// Writes data/qa.json in place (idempotent: earlier connectivity results are replaced).
import fs from 'node:fs';
import path from 'node:path';
import { buildGraph } from '../../src/roadgraph.js';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const wp = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/wpdata.json'), 'utf8'));
const qaPath = path.join(ROOT, 'data/qa.json');
const qa = JSON.parse(fs.readFileSync(qaPath, 'utf8'));
const fx = qa.fixes;
const MAX_ADD = 120;   // meters: longer links are left for the author
const MARGIN = 1.5;    // meters of clearance from any building

// buildings after the audit's fixes
const removed = new Set(fx.remove_buildings || []);
const replaced = new Map((fx.replace_buildings || []).map(r => [r.i, r.poly]));
const B = [];
wp.b.forEach((b, i) => { if (removed.has(i)) return; B.push(replaced.get(i) || b.slice(2).map(v => v / 2)); });
for (const a of fx.add_buildings || []) B.push(a.poly);
const rects = B.map(p => {
  const cx = (p[0] + p[2] + p[4] + p[6]) / 4, cy = (p[1] + p[3] + p[5] + p[7]) / 4;
  const w = Math.hypot(p[2] - p[0], p[3] - p[1]), d = Math.hypot(p[6] - p[0], p[7] - p[1]);
  return { cx, cy, ux: (p[2] - p[0]) / w, uy: (p[3] - p[1]) / w, vx: (p[6] - p[0]) / d, vy: (p[7] - p[1]) / d, w, d };
});
const hitsBuilding = (a, b) => {
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(2, Math.ceil(L));
  for (const r of rects) {
    if (Math.abs(r.cx - (a[0] + b[0]) / 2) > L / 2 + r.w + r.d || Math.abs(r.cy - (a[1] + b[1]) / 2) > L / 2 + r.w + r.d) continue;
    for (let k = 0; k <= n; k++) {
      const x = a[0] + (b[0] - a[0]) * k / n - r.cx, y = a[1] + (b[1] - a[1]) * k / n - r.cy;
      if (Math.abs(x * r.ux + y * r.uy) < r.w / 2 + MARGIN && Math.abs(x * r.vx + y * r.vy) < r.d / 2 + MARGIN) return true;
    }
  }
  return false;
};

// forget earlier connectivity results, then measure on the audited network
fx.add_roads = [];
qa.issues = qa.issues.filter(i => i.type !== 'road-network-gap');
const raw = buildGraph(wp, { roadSnaps: fx.road_snaps || [], gapLinks: false });
const g = buildGraph(wp, { roadSnaps: fx.road_snaps || [] });
const CLS = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway'];
const nm = i => (i == null || i < 0 ? null : wp.names[wp.roads[i][0]] ?? null);
const cls = i => (i == null || i < 0 ? 'residential' : CLS[wp.roads[i][1]] || 'residential');
let n = qa.issues.reduce((m, i) => Math.max(m, +String(i.id).replace(/\D/g, '') || 0), 0);
let added = 0, flagged = 0;
for (const L of g.gapLinks) {
  const name = nm(L.road), to = nm(L.toRoad);
  const safe = L.meters <= MAX_ADD && !hitsBuilding(L.from, L.to);
  const where = name ? `${name}` : 'an unnamed road';
  const at = [+(((L.from[0] + L.to[0]) / 2).toFixed(1)), +(((L.from[1] + L.to[1]) / 2).toFixed(1))];
  if (safe) {
    // a road extension: the loose street continues until it meets the road it should join
    fx.add_roads.push({ name, cls: L.meters < 0.6 ? cls(L.road) : cls(L.road) === 'track' ? 'track' : cls(L.road), bridge: 0, pts: [+L.from[0].toFixed(2), +L.from[1].toFixed(2), +L.to[0].toFixed(2), +L.to[1].toFixed(2)], why: `road-network-gap: ${where} stopped ${Math.round(L.meters)} m short of ${to || 'the road network'}; extended to meet it (proposed)` });
    added++;
    qa.issues.push({ id: 'Q' + String(++n).padStart(4, '0'), type: 'road-network-gap', severity: L.meters > 40 ? 'medium' : 'low', at, ref: { road: L.road, to: L.toRoad }, detail: `${where} stopped ${Math.round(L.meters)} m short of ${to || 'the road network'}, so its streets were cut off. The map extends it to meet ${to || 'the network'} (proposed).`, action: 'fixed', fix: 'add' });
  } else {
    flagged++;
    qa.issues.push({ id: 'Q' + String(++n).padStart(4, '0'), type: 'road-network-gap', severity: 'high', at, ref: { road: L.road, to: L.toRoad }, detail: `${where} stops ${Math.round(L.meters)} m short of ${to || 'the road network'}${L.meters > MAX_ADD ? '' : ', and a straight link would run through a building'}. Nothing on the map reaches it by road. The router assumes a connection here so distances work; draw the real street in the Atlas to settle it.`, action: 'flagged', fix: 'none' });
  }
}
const s = qa.summary;
s.by_type['road-network-gap'] = { found: g.gapLinks.length, fixed: added };
s.issues = Object.values(s.by_type).reduce((a, v) => a + v.found, 0);
s.fixed = Object.values(s.by_type).reduce((a, v) => a + v.fixed, 0);
s.flagged = s.issues - s.fixed;
s.network = { pieces_before: raw.stats.components, links: g.gapLinks.length, link_meters: Math.round(g.gapLinks.reduce((a, l) => a + l.meters, 0)), added_roads: added, flagged_links: flagged };
fs.writeFileSync(qaPath, JSON.stringify(qa));
console.log(`road network: ${raw.stats.components} pieces; ${g.gapLinks.length} links; ${added} added as road extensions, ${flagged} flagged`);
