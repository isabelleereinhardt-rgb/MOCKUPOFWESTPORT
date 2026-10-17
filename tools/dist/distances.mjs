// Distance tracker: road meters, drive seconds and straight meters between every gazetteer point.
//
//   node tools/dist/distances.mjs
//
// Reads data/wpdata.json, data/gaz.json and data/qa.json (QA road snaps and point moves applied),
// builds the road graph with src/roadgraph.js and writes data/distances.json, data/distances.csv
// and docs/DISTANCES.md. No npm packages.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SPEED_MPH, buildGraph, nearest, route, oneToMany, straight } from '../../src/roadgraph.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const rd = f => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
const MI = 1609.344;
const t0 = performance.now();

const wp = rd('data/wpdata.json'), gaz = rd('data/gaz.json'), qa = rd('data/qa.json');
const fixes = (qa && qa.fixes) || {};

// ---------------------------------------------------------------- graph
let t = performance.now();
const extraRoads = (fixes.add_roads || []).map(r => [r.name, r.cls, r.bridge || 0, r.pts]); // road extensions from tools/qa/connect.mjs
const graph = buildGraph(wp, { roadSnaps: fixes.road_snaps || [], extraRoads });
const buildMs = performance.now() - t;
const st = graph.stats;
const rawGraph = buildGraph(wp, { roadSnaps: fixes.road_snaps || [], gapLinks: false });
const roadName = r => { const i = graph.roadName[r]; return i >= 0 ? graph.names[i] : null; };
const className = r => graph.classes[graph.roadClass[r]];

// ---------------------------------------------------------------- points (QA moves applied)
const movedPlace = new Map((fixes.move_places || []).map(m => [m.id, m.at]));
const movedPerson = new Map((fixes.move_people || []).map(m => [m.name, m.at]));
const r2 = v => Math.round(v * 100) / 100;
const points = [];
for (const p of gaz.places) {
  if (!Array.isArray(p.at)) continue;
  const at = movedPlace.get(p.id) || p.at;
  points.push({ key: 'place:' + p.id, name: p.name, addr: p.addr || null, kind: 'place', at: [+at[0], +at[1]] });
}
for (const p of gaz.people) {
  if (!p.home || !Array.isArray(p.home.at)) continue;
  const at = movedPerson.get(p.name) || p.home.at;
  const homeName = String(p.home.note || p.home.addr || p.name + "'s home").split(' · ')[0];
  points.push({ key: 'home:' + p.name, name: homeName, addr: p.home.addr || null, kind: 'home', group: p.group, at: [+at[0], +at[1]] });
}

// unique locations: identical address and point (to the centimeter) are one place on the map
const uniq = [], uIndex = new Map(), pointU = [];
for (const p of points) {
  const k = `${(p.addr || '').toLowerCase()}|${p.at[0].toFixed(2)}|${p.at[1].toFixed(2)}`;
  let u = uIndex.get(k);
  if (u == null) { u = uniq.length; uIndex.set(k, u); uniq.push({ name: p.name, addr: p.addr, at: p.at, keys: [] }); }
  else if (uniq[u].keys.every(x => x.startsWith('home:')) && p.kind === 'place') uniq[u].name = p.name; // a place names a shared home
  uniq[u].keys.push(p.key);
  pointU.push(u);
}
// CSV labels must be unique: add the address where two locations share a name
const nameCount = new Map(); for (const u of uniq) nameCount.set(u.name, (nameCount.get(u.name) || 0) + 1);
for (const u of uniq) u.label = nameCount.get(u.name) > 1 && u.addr ? `${u.name} (${u.addr})` : u.name;
for (const u of uniq) if ([...uniq].filter(v => v.label === u.label).length > 1) u.label = `${u.label} [${Math.round(u.at[0])}, ${Math.round(u.at[1])}]`;

// snaps (same rule the router uses: roads in pieces of at least 1% of the largest)
const minComponent = Math.max(2, Math.ceil(st.largestComponent * 0.01));
for (const u of uniq) { const s = nearest(graph, u.at[0], u.at[1], { minComponent }); u.snap = s ? { at: [r2(s.x), r2(s.y)], m: r2(s.dist), road: s.road } : null; }

// ---------------------------------------------------------------- matrices over unique locations
t = performance.now();
const U = uniq.length;
const RM = Array.from({ length: U }, () => new Int32Array(U)), DS = Array.from({ length: U }, () => new Int32Array(U)), SM = Array.from({ length: U }, () => new Int32Array(U));
const targets = uniq.map(u => u.at);
let unreachable = 0;
for (let i = 0; i < U; i++) {
  const res = oneToMany(graph, uniq[i].at, targets, { metric: 'time' });
  for (let j = 0; j < U; j++) {
    SM[i][j] = Math.round(straight(uniq[i].at, uniq[j].at));
    if (i === j) { RM[i][j] = 0; DS[i][j] = 0; continue; }
    const r = res[j];
    if (!r) { RM[i][j] = -1; DS[i][j] = -1; unreachable++; continue; }
    RM[i][j] = Math.round(r.meters); DS[i][j] = Math.round(r.seconds);
  }
}
const matrixMs = performance.now() - t;

// checks: reachability, symmetry, triangle with straight line
let asym = 0, maxAsym = 0, shorter = 0;
for (let i = 0; i < U; i++) for (let j = i + 1; j < U; j++) {
  const d = Math.abs(DS[i][j] - DS[j][i]); if (d > 1) asym++; maxAsym = Math.max(maxAsym, d);
  if (RM[i][j] >= 0 && RM[i][j] + 1 < SM[i][j]) shorter++;
}

// ---------------------------------------------------------------- distances.json
const outPoints = points.map((p, k) => {
  const u = uniq[pointU[k]];
  const o = { key: p.key, name: p.name, addr: p.addr, kind: p.kind };
  if (p.group) o.group = p.group;
  o.at = [r2(p.at[0]), r2(p.at[1])];
  o.snap = u.snap ? { at: u.snap.at, m: u.snap.m } : null;
  return o;
});
const expand = M => pointU.map(ui => Array.from(pointU, uj => M[ui][uj]));
const json = {
  version: 1,
  speeds_mph: SPEED_MPH,
  points: outPoints,
  road_m: expand(RM), drive_s: expand(DS), straight_m: expand(SM),
  gap_links: graph.gapLinks.map(l => ({ from: [r2(l.from[0]), r2(l.from[1])], to: [r2(l.to[0]), r2(l.to[1])], m: r2(l.meters), road: roadName(l.road), to_road: roadName(l.toRoad) })),
};
fs.writeFileSync(path.join(ROOT, 'data/distances.json'), JSON.stringify(json));
const jsonBytes = fs.statSync(path.join(ROOT, 'data/distances.json')).size;

// ---------------------------------------------------------------- distances.csv
const csvQ = s => /[",\n]/.test(s) ? '"' + String(s).replace(/"/g, '""') + '"' : String(s);
const f2 = v => (Math.round(v * 100) / 100).toFixed(2);
const rows = ['from,to,straight_mi,road_mi,drive_min'];
for (let i = 0; i < U; i++) for (let j = 0; j < U; j++) {
  if (i === j) continue;
  rows.push([csvQ(uniq[i].label), csvQ(uniq[j].label), f2(SM[i][j] / MI), RM[i][j] < 0 ? '' : f2(RM[i][j] / MI), DS[i][j] < 0 ? '' : f2(DS[i][j] / 60)].join(','));
}
fs.writeFileSync(path.join(ROOT, 'data/distances.csv'), rows.join('\n') + '\n');

// ---------------------------------------------------------------- the Nine and canon checks
const P = key => { const k = points.findIndex(p => p.key === key); if (k < 0) throw new Error('missing point ' + key); return k; };
const NINE = ['Calista Yuen', 'Lori Delacroix', 'Reya Patel', 'Nellie Sullivan', 'Charlie Thompson', 'Dalton Abernathy', 'Zane Al-Hassan', 'Morgan Hernandez', 'Elio Rossi'];
const PLACES = [['westport-high', 'Westport High'], ['pier-bar', 'the pier'], ['nine-acres', 'the nine acres'], ['chadwicks-diner', "Chadwick's"], ['easts-nook', "East's Nook Books"], ['hospital', 'Westport Hospital']];
const first = n => n.split(' ')[0];
const U_ = key => pointU[P(key)];
const mi = m => (m / MI).toFixed(1), mins = s => s < 30 ? '<1' : String(Math.round(s / 60));
const cell = (a, b) => { const i = U_(a), j = U_(b); if (i === j) return '0'; return RM[i][j] < 0 ? 'no road' : `${mi(RM[i][j])} / ${mins(DS[i][j])}`; };

const via = r => r.roads.filter(x => x.name && x.meters >= 150).map(x => x.name).filter((n, k, a) => a.indexOf(n) === k);
const usesName = (r, name) => r.roads.some(x => x.name === name);
const routeOf = (a, b, g = graph, metric = 'time') => route(g, points[P(a)].at, points[P(b)].at, { metric });
const school = 'place:westport-high', daltonK = 'home:Dalton Abernathy', charlieK = 'home:Charlie Thompson';
const dS = routeOf(daltonK, school), dSd = routeOf(daltonK, school, graph, 'distance');
const cS = routeOf(charlieK, school), cSd = routeOf(charlieK, school, graph, 'distance');
const dc = routeOf(daltonK, charlieK), dcd = routeOf(daltonK, charlieK, graph, 'distance');

// what-if: Jefferson Street carried on south from River Road to the top of Spencer Street (Riverside)
const EXT = [-370, -690, -396, -1041];
const extLen = Math.hypot(EXT[2] - EXT[0], EXT[3] - EXT[1]);
const gExt = buildGraph(wp, { roadSnaps: fixes.road_snaps || [], extraRoads: [...extraRoads, ['Jefferson Street', 'secondary', 0, EXT]] });
const xS = routeOf(daltonK, school, gExt), xC = routeOf(daltonK, charlieK, gExt);
const morganK = 'home:Morgan Hernandez', mS = routeOf(morganK, school), xM = routeOf(morganK, school, gExt);

// which gap links a route drives over (path points are node positions, as are the link ends)
const ck = q => q[0].toFixed(2) + ',' + q[1].toFixed(2);
const linkAt = new Map();
graph.gapLinks.forEach((l, i) => { linkAt.set(ck(l.from) + '|' + ck(l.to), i); linkAt.set(ck(l.to) + '|' + ck(l.from), i); });
const linksOn = r => { const out = new Set(); for (let i = 1; i < r.path.length; i++) { const k = linkAt.get(ck(r.path[i - 1]) + '|' + ck(r.path[i])); if (k != null) out.add(k); } return out; };
const ownLinks = NINE.map(a => { // links that most trips from this home cross (the way out of its piece of the map)
  const count = new Map(), trips = [...NINE.filter(x => x !== a).map(x => 'home:' + x), ...PLACES.map(([id]) => 'place:' + id)];
  for (const b of trips) for (const i of linksOn(routeOf('home:' + a, b))) count.set(i, (count.get(i) || 0) + 1);
  return { a, links: [...count].filter(([, c]) => c > trips.length / 2).map(([i]) => i) };
});

// the gap links that matter for the points: the ones on the routes above, plus every link 50 m or longer
const bigLinks = graph.gapLinks.filter(l => l.meters >= 80 || Math.min(...l.joined) >= 100).sort((a, b) => b.meters - a.meters);
const restLinks = graph.gapLinks.filter(l => !bigLinks.includes(l));

// access legs
const access = uniq.map(u => ({ u, m: u.snap ? u.snap.m : Infinity })).sort((a, b) => b.m - a.m);
const medAccess = access.map(a => a.m).sort((a, b) => a - b)[access.length >> 1];

// ---------------------------------------------------------------- DISTANCES.md
const L = [];
const fmtMi = m => (m / MI).toFixed(1) + ' miles';
const fmtMin = s => { const m = s / 60; return (m < 10 ? m.toFixed(1) : Math.round(m)) + ' minutes'; };
const roadsLine = r => via(r).join(', ');
L.push('# Westport distances', '');
L.push('You asked for a distance tracker: how far everything is from everything else. This file explains the numbers, gives the Nine\'s commutes, and checks the distances the register states against the map.', '');
L.push('The full tables are in `data/distances.json` (for the 3D map) and `data/distances.csv` (one row per pair of places, for a spreadsheet). In the 3D map, the ruler tool measures by road with the same router, so it agrees with these tables.', '');
L.push('## What the numbers mean', '');
L.push('- **Road miles** is the length of the fastest drive between two points, on the Atlas roads.');
L.push('- **Drive minutes** is the time for that drive at a fixed speed for each kind of road. There is no traffic, no stop signs or lights, and no time lost at turns, so a real drive takes somewhat longer, most of all downtown.');
L.push('- **Straight miles** is the distance as the crow flies.');
const farOff = access.filter(a => a.m >= 250);
L.push(`- Each place is joined to the nearest road by a straight walk (the "access leg"): from a house to its street, or from a big building across its lot. Road miles include that walk; drive minutes do not. The median access leg is ${Math.round(medAccess)} m. A few points sit well away from any road, so their road miles include a long walk: ${farOff.map(a => `${a.u.name} ${Math.round(a.m)} m`).join(', ')}.`);
L.push('- Every road is two-way. Footpaths are not used. A bridge joins only the roads at its two ends, never the road or river under it. Where two roads cross on the ground, they meet.');
L.push('- The QA fixes in `data/qa.json` are applied first: snapped road ends and moved place and home points.', '');
L.push('Speeds used:', '');
L.push('| Road | mph | Road | mph |', '|---|---|---|---|');
const sp = Object.entries(SPEED_MPH);
for (let k = 0; k < sp.length; k += 2) L.push(`| ${sp[k][0]} | ${sp[k][1]} | ${sp[k + 1] ? sp[k + 1][0] : ''} | ${sp[k + 1] ? sp[k + 1][1] : ''} |`);
L.push('');
{ // say which main roads fall in which class, from the data
  const len = new Map();
  wp.roads.forEach((r, i) => { if (r[0] < 0 || r[1] > 2) return; const nm = wp.names[r[0]]; let m = 0; for (let k = 2; k < r[3].length; k += 2) m += Math.hypot(r[3][k] - r[3][k - 2], r[3][k + 1] - r[3][k - 1]); const o = len.get(nm) || { m: 0, c: r[1] }; o.m += m; len.set(nm, o); });
  const byClass = c => [...len].filter(([, o]) => o.c === c && o.m > 400).sort((a, b) => b[1].m - a[1].m).map(([n]) => n);
  const list = a => a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
  const cls = ['trunk', 'primary', 'secondary'].map((c, i) => { const n = byClass(i); return n.length ? `${list(n)} ${n.length > 1 ? 'are' : 'is'} ${c} (${SPEED_MPH[c]} mph)` : null; }).filter(Boolean);
  L.push(`On the main roads: ${cls.join('; ')}. Neighborhood collectors are tertiary (30), house streets residential (25), and driveways, lanes and parking lots are service roads (12).`, '');
}

L.push('## Missing road links on the map', '');
L.push(`The Atlas has pieces that no road reaches. Before any fix, the roads fall into ${rawGraph.stats.components} separate pieces; the biggest holds ${Math.round(100 * rawGraph.stats.largestComponent / rawGraph.stats.nodes)}% of the road network. Whole subdivisions have streets that stop 50 to 70 m short of the collector they should join. Riverside, with the trailer park and the Hernandez house, connects to nothing: its streets stop 250 to 350 m south of River Road, and Mercer Street stops ${(() => { const l = graph.gapLinks.find(x => roadName(x.road) === 'Mercer Street'); return l ? Math.round(l.meters) + ' m' : 'short'; })()} short of Ocean Highway. Country Club Road west of the river stops ${(() => { const l = graph.gapLinks.find(x => roadName(x.road) === 'Country Club Road'); return l ? Math.round(l.meters) + ' m' : 'short'; })()} short of Ocean Highway.`, '');
L.push(`So the router ties each loose piece to the rest with the shortest straight link it can find over land, never across water, and only as many links as it takes to join everything: ${graph.gapLinks.length} links, ${(st.gapLinkMeters / 1000).toFixed(1)} km in all. A link is driven at the speed of the road it starts from. After that, every place and home on the map can be reached by road, the beach included: the barrier island is joined by the Ocean Highway high bridge, which the router uses like any other road.`, '');
L.push('These links join whole neighborhoods or are 80 m or longer. Each one marks a piece of street the Atlas should draw:', '');
L.push('| From | To | Length | At (x, y) |', '|---|---|---|---|');
for (const l of bigLinks) L.push(`| ${roadName(l.road) || 'unnamed ' + className(l.road)} | ${roadName(l.toRoad) || 'unnamed ' + className(l.toRoad)} | ${Math.round(l.meters)} m | ${Math.round(l.from[0])}, ${Math.round(l.from[1])} |`);
L.push('', `The other ${restLinks.length} are subdivision entrances that stop 50 to 75 m short of their collector, and driveways and lanes that stop a few meters to 50 m short of their road. All ${graph.gapLinks.length} are listed in \`gap_links\` in \`data/distances.json\`.`, '');

L.push('## The Nine', '');
L.push('Road miles / drive minutes between their homes. Charlie is at the Thompson house on Pelican Point Drive (before Book 3).', '');
L.push('| | ' + NINE.map(first).join(' | ') + ' |', '|---|' + NINE.map(() => '---|').join(''));
for (const a of NINE) L.push(`| **${first(a)}** | ` + NINE.map(b => a === b ? '' : cell('home:' + a, 'home:' + b)).join(' | ') + ' |');
L.push('');
L.push('From each home to the places they go (road miles / drive minutes):', '');
L.push('| | ' + PLACES.map(p => p[1]).join(' | ') + ' |', '|---|' + PLACES.map(() => '---|').join(''));
for (const a of NINE) L.push(`| **${a}** | ` + PLACES.map(([id]) => cell('home:' + a, 'place:' + id)).join(' | ') + ' |');
L.push('');
const nell = U_('home:Nellie Sullivan'), elio = U_('home:Elio Rossi');
L.push(`Nellie and Elio live next door to each other on Bay Drive (${Math.round(SM[nell][elio])} m apart), so their rows are nearly the same. Charlie's later room over East's Nook Books is the East's Nook Books column.`, '');
{
  const byLink = new Map();
  for (const { a, links } of ownLinks) for (const i of links) { if (!byLink.has(i)) byLink.set(i, []); byLink.get(i).push(first(a)); }
  const lines = [...byLink].map(([i, who]) => { const l = graph.gapLinks[i]; return `${who.join(' and ')} (${roadName(l.road)} to ${roadName(l.toRoad)}, ${Math.round(l.meters)} m)`; });
  const list = a => a.length < 2 ? a.join('') : a.slice(0, -1).join('; ') + '; and ' + a[a.length - 1];
  const nWho = ownLinks.filter(o => o.links.length).length, word = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'][nWho];
  if (lines.length) L.push(`Nearly every trip from ${word} of these homes crosses one of the gap links above, so those rows depend on a street the Atlas has not drawn yet: ${list(lines)}. The other homes reach these places on the roads as drawn, except when the trip goes to one of those homes.`, '');
}

L.push('## Canon checks', '');
L.push('The register says Westport High "sits on Patriots Boulevard" so that Canon 2\'s commutes come close. Measured on the map:', '');
L.push('| Statement | Register | Canon 2 | Map, fastest drive | Map, shortest road |', '|---|---|---|---|---|');
L.push(`| Dalton's trailer to school | about 5 miles, over the Dalton Bridge | 4 miles | ${fmtMi(dS.meters)}, ${fmtMin(dS.seconds)} | ${fmtMi(dSd.meters)} |`);
L.push(`| Charlie's drive, Pelican Point Drive to school | about 4 miles, 8 to 9 minutes | | ${fmtMi(cS.meters)}, ${fmtMin(cS.seconds)} | ${fmtMi(cSd.meters)}, ${fmtMin(cSd.seconds)} |`);
L.push(`| Dalton's and Charlie's homes | about 5.3 road miles | 6.3 miles | ${fmtMi(dc.meters)}, ${fmtMin(dc.seconds)} | ${fmtMi(dcd.meters)} |`);
L.push('');
const dalBr = usesName(dS, 'Dalton Bridge');
L.push(`**Dalton to school.** ${dalBr ? 'The route does cross the Dalton Bridge, but it gets there the long way.' : 'The route does not cross the Dalton Bridge.'} It runs ${roadsLine(dS)}. The trailer park has no street north to River Road, so the drive goes west on Mercer Street to Ocean Highway, then ${dalBr ? 'back east along River Road to the bridge' : 'north'}. That is ${fmtMi(dS.meters)}, not 5.`, '');
L.push(`If Jefferson Street carried on south from River Road for about ${Math.round(extLen)} m to the top of Spencer Street, the trailer would be ${fmtMi(xS.meters)} and ${fmtMin(xS.seconds)} from school, ${usesName(xS, 'Dalton Bridge') ? 'over the Dalton Bridge' : 'not over the Dalton Bridge'}, by ${roadsLine(xS)}. That matches the register's "about 5 miles over the Dalton Bridge", so the register's figure assumes a street the map does not have yet. The same piece would bring Morgan's drive to school from ${fmtMi(mS.meters)} down to ${fmtMi(xM.meters)}.`, '');
L.push(`**Charlie to school.** ${fmtMi(cS.meters)} and ${fmtMin(cS.seconds)} by ${roadsLine(cS)}. That is about ${(cS.meters / MI - 4).toFixed(1)} miles longer than the register's 4 miles. The school is ${fmtMi(SM[U_(charlieK)][U_(school)])} from the Thompson house in a straight line, but no road runs that way: the fast drive goes down to Harbor Drive, up Harborview Drive and back west along Patriots Boulevard.${Math.abs(cSd.meters - cS.meters) > 0.1 * MI ? ` The shortest road route, ${fmtMi(cSd.meters)} by ${roadsLine(cSd)}, takes ${fmtMin(cSd.seconds)}.` : ''} This drive uses only roads drawn on the Atlas, so either the line becomes "about ${Math.round(cS.meters / MI)} miles, ${Math.round(cS.seconds / 60)} minutes", or the drive needs a more direct road north from Harborview.`, '');
L.push(`**Dalton and Charlie.** ${fmtMi(dc.meters)} and ${fmtMin(dc.seconds)} by ${roadsLine(dc)}, against the register's 5.3 (Canon 2's 6.3). With the Jefferson Street piece above it would be ${fmtMi(xC.meters)} and ${fmtMin(xC.seconds)}, which is the register's figure.`, '');
L.push('A road named "Dalton Bridge" is on the map: the 515 m bridge that carries Jefferson Street over the river from downtown to River Road.', '');

L.push('## Files', '');
L.push('- `data/distances.json`: every gazetteer place (`place:<id>`) and every person\'s home (`home:<name>`; people who share a house have the same numbers) with matrices `road_m` (meters), `drive_s` (seconds) and `straight_m` (meters), in the order of `points`, plus the gap links. A missing road route would be -1; there are none.');
L.push('- `data/distances.csv`: one row per ordered pair of distinct locations (shared homes once), in miles and minutes.');
L.push('- To rebuild after the Atlas or the QA fixes change: `node tools/dist/distances.mjs`. The tests are `node tools/dist/test-roadgraph.mjs`.');
L.push('');
const md = L.join('\n');
if (/—/.test(md)) throw new Error('em dash in DISTANCES.md');
fs.writeFileSync(path.join(ROOT, 'docs/DISTANCES.md'), md);

// ---------------------------------------------------------------- report
const total = performance.now() - t0;
console.log(`graph: ${st.nodes} nodes, ${st.edges} edges, built in ${Math.round(buildMs)} ms`);
console.log(`  joins: ${st.sharedVertexJoins} shared vertices, ${st.endOnSegment} road ends on another road, ${st.vertexOnSegment} vertices on another road, ${st.crossings} at-grade crossings added, ${st.endOnBridgeIgnored} road end on a bridge span ignored`);
console.log(`  pieces before gap links: ${rawGraph.stats.components} (largest ${rawGraph.stats.largestComponent} nodes; next ${rawGraph.stats.componentSizes.slice(1, 8).join(', ')})`);
console.log(`  gap links: ${graph.gapLinks.length}, ${st.gapLinkMeters} m; pieces after: ${st.components} (${st.componentSizes.join(', ')})`);
console.log(`points: ${points.length} (${gaz.places.length} places, ${points.length - gaz.places.length} people) -> ${U} unique locations`);
console.log(`matrices: ${U}x${U} in ${Math.round(matrixMs)} ms; unreachable pairs ${unreachable}; drive-time asymmetry > 1 s: ${asym} (max ${maxAsym} s); road shorter than straight: ${shorter}`);
console.log(`access legs: median ${medAccess} m; longest ${access.slice(0, 5).map(a => `${a.u.name} ${Math.round(a.m)} m`).join('; ')}`);
console.log(`Dalton -> school: ${fmtMi(dS.meters)}, ${fmtMin(dS.seconds)}, Dalton Bridge: ${dalBr} | shortest ${fmtMi(dSd.meters)} | with Jefferson ext ${fmtMi(xS.meters)}, ${fmtMin(xS.seconds)}, Dalton Bridge: ${usesName(xS, 'Dalton Bridge')}`);
console.log(`Charlie -> school: ${fmtMi(cS.meters)}, ${fmtMin(cS.seconds)} | shortest ${fmtMi(cSd.meters)}, ${fmtMin(cSd.seconds)}`);
console.log(`Dalton <-> Charlie: ${fmtMi(dc.meters)}, ${fmtMin(dc.seconds)} | shortest ${fmtMi(dcd.meters)} | with Jefferson ext ${fmtMi(xC.meters)}`);
console.log(`wrote data/distances.json (${(jsonBytes / 1e6).toFixed(2)} MB), data/distances.csv (${rows.length - 1} rows), docs/DISTANCES.md in ${Math.round(total)} ms`);
if (unreachable) { console.error(`FAIL: ${unreachable} unreachable pairs`); process.exit(1); }
if (jsonBytes > 3e6) { console.error('FAIL: distances.json over 3 MB'); process.exit(1); }
