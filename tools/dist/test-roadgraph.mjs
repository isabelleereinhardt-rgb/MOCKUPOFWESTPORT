// Tests for src/roadgraph.js.  Run: node tools/dist/test-roadgraph.mjs
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { SPEED_MPH, buildGraph, nearest, route, oneToMany, straight } from '../../src/roadgraph.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const rd = f => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
let passed = 0;
const test = (name, fn) => { const t = performance.now(); fn(); passed++; console.log(`ok  ${name} (${Math.round(performance.now() - t)} ms)`); };
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b} (tol ${tol})`);
const MPS = mph => mph * 0.44704;

// ------------------------------------------------------------------ synthetic network
//  C: (0,150)-(200,150)        P (path): (0,150) -> (400,0), passes over the bridge
//  |                |
//  |      E         B (bridge, (200,-150)-(200,150), over A at (200,0))
//  A: (0,0) ---(100,0)--- (400,0)     E crosses A at (100,0) with no shared vertex
//                   |          |
//                   D: (200,-150)-(400,-150)-(400,0)
const toy = {
  names: ['A Street', 'B Bridge', 'C Street', 'D Street', 'E Street', 'P Path'],
  roads: [
    [0, 4, 0, [0, 0, 400, 0]],
    [1, 4, 1, [200, -150, 200, 150]],
    [2, 4, 0, [0, 0, 0, 150, 200, 150]],
    [3, 4, 0, [400, 0, 400, -150, 200, -150]],
    [4, 4, 0, [100, -100, 100, 100]],
    [5, 7, 0, [0, 150, 400, 0]],
  ],
  land: [],
};
const toyCopy = JSON.stringify(toy);
const T = buildGraph(toy, { gapLinks: false });
const res = MPS(SPEED_MPH.residential);

test('at-grade crossing without a shared vertex becomes a junction', () => {
  const r = route(T, [100, 90], [150, 0]);
  assert.ok(r, 'route exists');
  near(r.meters, 140, 1e-6, 'meters'); near(r.seconds, 140 / res, 1e-6, 'seconds');
  assert.deepEqual(r.roads.map(x => x.name), ['E Street', 'A Street']);
  const T0 = buildGraph(toy, { gapLinks: false, crossings: false });
  assert.equal(route(T0, [100, 90], [150, 0]), null, 'no junction when crossings are off');
});

test('same-edge routing', () => {
  const r = route(T, [120, 3], [180, -4]);
  near(r.meters, 60 + 3 + 4, 1e-9, 'meters include both access legs');
  near(r.seconds, 60 / res, 1e-9, 'seconds exclude access legs');
  assert.deepEqual(r.access.map(v => Math.round(v * 1e6) / 1e6), [3, 4]);
  assert.deepEqual(r.path, [[120, 3], [120, 0], [180, 0], [180, -4]]);
  assert.deepEqual(r.roads, [{ name: 'A Street', meters: 60 }]);
  const back = route(T, [180, -4], [120, 3]);
  near(back.meters, r.meters, 1e-9, 'reverse');
  const same = route(T, [150, 2], [150, 2]);
  near(same.meters, 4, 1e-9, 'same point: two access legs'); near(same.seconds, 0, 1e-12, 'same point seconds');
  const o = oneToMany(T, [120, 3], [[180, -4], [100, 90], [120, 3]]);
  near(o[0].meters, 67, 1e-9, 'oneToMany same edge'); near(o[0].seconds, 60 / res, 1e-9, 'oneToMany same edge seconds');
  near(o[1].meters, 3 + 20 + 90, 1e-9, 'oneToMany via the crossing');
  near(o[2].meters, 6, 1e-9, 'oneToMany to itself');
});

test('a bridge is not connected to the road below it', () => {
  for (let n = 0; n < T.nodeCount; n++) assert.ok(Math.hypot(T.nx[n] - 200, T.ny[n]) > 1, 'no node where the bridge passes over A Street');
  const r = route(T, [200, 60], [260, 0]); // on the bridge -> on the road under it
  near(r.meters, 700, 1e-6, 'goes round by the bridge ends');
  assert.ok(r.meters > 5 * straight([200, 60], [260, 0]));
  assert.ok(r.roads.some(x => x.name === 'B Bridge'));
});

test('footpaths are left out unless asked for', () => {
  const car = route(T, [0, 150], [400, 0], { metric: 'distance' });
  near(car.meters, 550, 1e-6, 'default classes');
  assert.ok(!car.roads.some(x => x.name === 'P Path'));
  const all = Object.keys(SPEED_MPH);
  const foot = route(T, [0, 150], [400, 0], { metric: 'distance', classes: all });
  near(foot.meters, Math.hypot(400, 150), 1e-6, 'with paths');
  assert.deepEqual(foot.roads.map(x => x.name), ['P Path']);
  const nn = nearest(T, 200, 76); assert.equal(T.names[T.roadName[nn.road]], 'B Bridge', 'nearest skips the path by default');
  const np = nearest(T, 200, 76, { classes: ['path'] }); assert.equal(T.names[T.roadName[np.road]], 'P Path');
});

test('buildGraph leaves its input alone; snaps apply to a copy', () => {
  const g = buildGraph(toy, { gapLinks: false, roadSnaps: [{ road: 4, vertex: 0, to: [100, 0] }] });
  assert.equal(JSON.stringify(toy), toyCopy);
  near(route(g, [100, 50], [150, 0]).meters, 100, 1e-6, 'snapped end joins A Street');
});

test('straight()', () => { near(straight([0, 0], [3, 4]), 5, 1e-12, 'hypot'); });

// ------------------------------------------------------------------ the Atlas
const wp = rd('data/wpdata.json'), qa = rd('data/qa.json'), gaz = rd('data/gaz.json');
const snaps = qa.fixes.road_snaps;
const before = JSON.stringify(snaps.slice(0, 50).map(s => wp.roads[s.road][3]));
let G, buildMs;
test('buildGraph on the Atlas is under 1.5 s', () => {
  const t = performance.now(); G = buildGraph(wp, { roadSnaps: snaps }); buildMs = performance.now() - t;
  assert.ok(buildMs < 1500, `buildGraph took ${Math.round(buildMs)} ms`);
  assert.equal(JSON.stringify(snaps.slice(0, 50).map(s => wp.roads[s.road][3])), before, 'wpdata not mutated');
  assert.equal(G.stats.snapsApplied, snaps.length);
  assert.equal(G.stats.components, 1, 'one connected network after gap links');
  console.log(`    ${G.stats.nodes} nodes, ${G.stats.edges} edges, ${G.stats.crossings} crossings added, ${G.stats.gapLinks} gap links (${G.stats.gapLinkMeters} m), ${Math.round(buildMs)} ms`);
});

const moved = new Map(qa.fixes.move_places.map(m => [m.id, m.at]));
const pts = gaz.places.filter(p => p.at).map(p => moved.get(p.id) || p.at);
let seed = 7; const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const pick = () => pts[Math.floor(rnd() * pts.length)];

test('Atlas bridges join only at their ends', () => {
  let checked = 0;
  for (let e = 0; e < G.edgeCount; e++) {
    if (!G.eBridge[e]) continue;
    const r = G.eRoad[e], coords = wp.roads[r][3], n = coords.length >> 1;
    const ends = [[coords[0], coords[1]], [coords[2 * n - 2], coords[2 * n - 1]]];
    for (const v of [G.eA[e], G.eB[e]]) {
      if (ends.some(([x, y]) => Math.hypot(G.nx[v] - x, G.ny[v] - y) < 2)) continue; // a bridge end (or its QA snap)
      for (let k = G.adjStart[v]; k < G.adjStart[v + 1]; k++) assert.equal(G.eRoad[G.adjEdge[k]], r, `bridge ${r} interior node joins road ${G.eRoad[G.adjEdge[k]]}`);
      checked++;
    }
  }
  assert.ok(checked > 20);
  // a road laid under the Dalton Bridge does not join it
  const g2 = buildGraph(wp, { roadSnaps: snaps, gapLinks: false, extraRoads: [['Under Street', 'residential', 0, [-500, -300, -200, -300]]] });
  const under = new Set(), bridge = new Set();
  for (let e = 0; e < g2.edgeCount; e++) { const nm = g2.names[g2.roadName[g2.eRoad[e]]]; if (nm === 'Under Street') { under.add(g2.eA[e]); under.add(g2.eB[e]); } if (nm === 'Dalton Bridge') { bridge.add(g2.eA[e]); bridge.add(g2.eB[e]); } }
  assert.ok(under.size >= 2 && bridge.size >= 2);
  for (const n of under) assert.ok(!bridge.has(n), 'Under Street shares a node with the Dalton Bridge');
});

test('route >= straight line, and A* matches Dijkstra', () => {
  for (let i = 0; i < 60; i++) {
    const a = pick(), b = pick(); const r = route(G, a, b);
    assert.ok(r, 'reachable');
    assert.ok(r.meters >= straight(a, b) - 1e-6, 'road shorter than straight line');
    const d = route(G, a, b, { metric: 'distance' });
    assert.ok(d.meters <= r.meters + 1e-6 && d.seconds >= r.seconds - 1e-6, 'metric trade-off');
    const sum = r.roads.reduce((s, x) => s + x.meters, 0) + r.access[0] + r.access[1];
    near(sum, r.meters, 1e-6, 'roads add up');
  }
  const src = pick(), tg = Array.from({ length: 40 }, pick);
  const many = oneToMany(G, src, tg);
  tg.forEach((b, k) => { const r = route(G, src, b); near(many[k].seconds, r.seconds, 1e-6 * Math.max(1, r.seconds), 'oneToMany vs route seconds'); near(many[k].meters, r.meters, Math.max(1, 0.01 * r.meters), 'oneToMany vs route meters'); });
});

test('distances are symmetric', () => {
  for (let i = 0; i < 40; i++) {
    const a = pick(), b = pick(); const r = route(G, a, b), s = route(G, b, a);
    near(r.seconds, s.seconds, 1e-6 * Math.max(1, r.seconds), 'seconds');
    near(r.meters, s.meters, Math.max(1, 0.01 * r.meters), 'meters');
  }
});

test('nearest() matches brute force', () => {
  for (let i = 0; i < 200; i++) {
    const x = -9000 + rnd() * 17000, y = -9000 + rnd() * 17000;
    const n = nearest(G, x, y);
    let best = Infinity;
    for (let e = 0; e < G.edgeCount; e++) {
      if (G.eVirtual[e] || G.eClass[e] === 7) continue;
      const ax = G.nx[G.eA[e]], ay = G.ny[G.eA[e]], bx = G.nx[G.eB[e]], by = G.ny[G.eB[e]], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      const t = Math.max(0, Math.min(1, L2 ? ((x - ax) * dx + (y - ay) * dy) / L2 : 0));
      best = Math.min(best, Math.hypot(x - ax - dx * t, y - ay - dy * t));
    }
    near(n.dist, best, 1e-6, 'nearest distance');
  }
});

test('a route across the whole town takes < 30 ms', () => {
  const far = [[[-10300, 8200], [-650, -10020]], [[4700, -8780], [2980, 8650]], [[-7600, -4700], [7180, -3150]], [[-6900, 2450], [5600, 4700]]];
  for (const [a, b] of far) route(G, a, b); // warm up
  const times = [];
  for (let k = 0; k < 5; k++) for (const [a, b] of far) { const t = performance.now(); const r = route(G, a, b); times.push(performance.now() - t); assert.ok(r && r.meters > 10000); }
  times.sort((p, q) => p - q);
  const med = times[times.length >> 1];
  console.log(`    median ${med.toFixed(2)} ms, max ${times[times.length - 1].toFixed(2)} ms over ${times.length} cross-town routes`);
  assert.ok(med < 30, `median ${med} ms`);
});

console.log(`\n${passed} tests passed`);
