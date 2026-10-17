// Road graph and router for the Westport Atlas (data/wpdata.json: meters, x east, y north).
// Dependency-free ES module; runs in browsers and in Node 22.
//
//   buildGraph(wp, { roadSnaps })    nodes at road vertices; roads join where they share a vertex
//                                    (0.5 m), where a road end lies on another road, and where two
//                                    non-bridge roads cross at grade. Bridges join only at their own
//                                    ends. Pieces of the Atlas that no road reaches are tied to the
//                                    network by short "gap links" (see below).
//   nearest(graph, x, y, opts)       closest point on the road network
//   route(graph, from, to, opts)     A*, fastest ('time', the default) or shortest ('distance')
//   oneToMany(graph, from, targets)  one Dijkstra, same conventions as route()
//   straight(a, b)                   straight-line meters
//
// Conventions: route meters include the straight access legs from each point to its road and the
// partial edges at both ends. Seconds are driving time on roads only (the access legs are walked
// and not added). Footpaths ('path') are left out of routing unless opts.classes names them.
//
// Gap links: the Atlas has whole subdivisions and one neighborhood (Riverside) whose streets stop
// short of every other road. buildGraph ties each such piece to the rest with the shortest straight
// link over land (no water) up to opts.gapLinks meters (default 300; false turns this off). A link
// takes the class and name of the road it starts from, is never used for snapping, and is listed
// in graph.gapLinks so the missing streets can be drawn into the Atlas.

export const SPEED_MPH = Object.freeze({ trunk: 50, primary: 45, secondary: 35, tertiary: 30, residential: 25, service: 12, track: 10, path: 3, motorway: 65 });

const CLASSES = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway'];
const MPS_PER_MPH = 0.44704;
const DEFAULT_EXCLUDE = ['path'];
const DEFAULT_GAP = 300;

const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());

/** Straight-line distance in meters between [x,y] points. */
export function straight(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }

// ---------------------------------------------------------------------------------------------
// Uniform grid of segments (CSR). A segment is registered in every cell touched by the padded
// bounding box of each of its pieces (pieces no longer than a cell), so long diagonals stay cheap.

function buildSegGrid(n, ax, ay, bx, by, keep, cs, pad) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    if (keep && !keep(i)) continue;
    x0 = Math.min(x0, ax[i], bx[i]); x1 = Math.max(x1, ax[i], bx[i]);
    y0 = Math.min(y0, ay[i], by[i]); y1 = Math.max(y1, ay[i], by[i]);
  }
  if (!isFinite(x0)) { x0 = y0 = 0; x1 = y1 = 1; }
  x0 -= cs; y0 -= cs; x1 += cs; y1 += cs;
  const nx = Math.max(1, Math.ceil((x1 - x0) / cs)), ny = Math.max(1, Math.ceil((y1 - y0) / cs)), NC = nx * ny;
  const start = new Int32Array(NC + 1), last = new Int32Array(NC).fill(-1);
  const visit = (i, fn) => {
    const dx = bx[i] - ax[i], dy = by[i] - ay[i], pieces = Math.max(1, Math.ceil(Math.hypot(dx, dy) / cs));
    for (let p = 0; p < pieces; p++) {
      const sx = ax[i] + dx * p / pieces, sy = ay[i] + dy * p / pieces, ex = ax[i] + dx * (p + 1) / pieces, ey = ay[i] + dy * (p + 1) / pieces;
      const cx0 = Math.max(0, Math.floor((Math.min(sx, ex) - pad - x0) / cs)), cx1 = Math.min(nx - 1, Math.floor((Math.max(sx, ex) + pad - x0) / cs));
      const cy0 = Math.max(0, Math.floor((Math.min(sy, ey) - pad - y0) / cs)), cy1 = Math.min(ny - 1, Math.floor((Math.max(sy, ey) + pad - y0) / cs));
      for (let cy = cy0; cy <= cy1; cy++) for (let cx = cx0; cx <= cx1; cx++) { const c = cy * nx + cx; if (last[c] !== i) { last[c] = i; fn(c); } }
    }
  };
  for (let i = 0; i < n; i++) if (!keep || keep(i)) visit(i, c => { start[c + 1]++; });
  for (let c = 0; c < NC; c++) start[c + 1] += start[c];
  const fill = start.slice(0, NC), items = new Int32Array(start[NC]);
  last.fill(-1);
  for (let i = 0; i < n; i++) if (!keep || keep(i)) visit(i, c => { items[fill[c]++] = i; });
  return { x0, y0, cs, nx, ny, start, items };
}

// point to segment; out = [t (0..1), qx, qy, distance]
function projSeg(px, py, ax, ay, bx, by, out) {
  const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
  let t = L2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / L2 : 0;
  if (t < 0) t = 0; else if (t > 1) t = 1;
  const qx = ax + dx * t, qy = ay + dy * t;
  out[0] = t; out[1] = qx; out[2] = qy; out[3] = Math.hypot(px - qx, py - qy);
  return out;
}

// Ring search over a segment grid: closest item passing ok(e) within maxDist. Returns best index or -1; out holds the projection.
function gridNearest(G, ax, ay, bx, by, x, y, ok, maxDist, seen, stampId, out) {
  const qx = Math.floor((x - G.x0) / G.cs), qy = Math.floor((y - G.y0) / G.cs);
  const maxR = Math.max(Math.abs(qx), Math.abs(qx - (G.nx - 1)), Math.abs(qy), Math.abs(qy - (G.ny - 1)));
  const pr = [0, 0, 0, 0];
  let best = -1, bd = Infinity;
  for (let r = 0; r <= maxR; r++) {
    if ((r - 1) * G.cs > Math.min(bd, maxDist)) break; // nothing left in reach
    for (let cy = qy - r; cy <= qy + r; cy++) {
      if (cy < 0 || cy >= G.ny) continue;
      const step = (cy === qy - r || cy === qy + r) ? 1 : 2 * r; // whole top and bottom rows, two cells on the sides
      for (let cx = qx - r; cx <= qx + r; cx += step) {
        if (cx < 0 || cx >= G.nx) continue;
        const c = cy * G.nx + cx;
        for (let k = G.start[c]; k < G.start[c + 1]; k++) {
          const e = G.items[k];
          if (seen[e] === stampId) continue; seen[e] = stampId;
          if (!ok(e)) continue;
          projSeg(x, y, ax[e], ay[e], bx[e], by[e], pr);
          if (pr[3] < bd) { bd = pr[3]; best = e; out[0] = pr[0]; out[1] = pr[1]; out[2] = pr[2]; out[3] = pr[3]; }
        }
      }
    }
  }
  return bd <= maxDist ? best : -1;
}

// ---------------------------------------------------------------------------------------------
// Stage 1: vertices, joins, splits and crossing points (independent of gap links).

function prepare(wp, opts) {
  const JOIN = opts.joinTol != null ? opts.joinTol : 0.5;
  const names = (wp.names || []).slice();
  const roads = (wp.roads || []).slice();
  for (const x of opts.extraRoads || []) { // hypothetical roads: [name|nameIndex, class|classIndex, isBridge, [x,y,...]]
    let ni = x[0];
    if (typeof ni === 'string') { ni = names.indexOf(x[0]); if (ni < 0) { names.push(x[0]); ni = names.length - 1; } }
    const ci = typeof x[1] === 'string' ? CLASSES.indexOf(x[1]) : x[1];
    roads.push([ni == null ? -1 : ni, ci, x[2] ? 1 : 0, x[3]]);
  }
  const R = roads.length;
  const stats = { roads: R, vertices: 0, snapsApplied: 0, sharedVertexJoins: 0, endOnSegment: 0, endOnBridgeIgnored: 0, vertexOnSegment: 0, crossings: 0, parallelOverlaps: 0 };

  // copy coordinates, apply the QA snaps, drop repeated points
  const byRoad = new Map();
  for (const s of opts.roadSnaps || []) {
    if (!s || !Array.isArray(s.to) || !(s.road >= 0 && s.road < (wp.roads || []).length)) continue;
    let a = byRoad.get(s.road); if (!a) byRoad.set(s.road, a = []); a.push(s);
  }
  const roadStart = new Int32Array(R + 1), rBridge = new Uint8Array(R), rClass = new Uint8Array(R), rName = new Int32Array(R);
  const X = [], Y = [];
  for (let r = 0; r < R; r++) {
    const rd = roads[r], src = rd[3] || [], n = src.length >> 1;
    rName[r] = rd[0] == null ? -1 : rd[0]; rClass[r] = rd[1] >= 0 && rd[1] < CLASSES.length ? rd[1] : CLASSES.indexOf('service'); rBridge[r] = rd[2] ? 1 : 0;
    const xs = new Float64Array(n), ys = new Float64Array(n);
    for (let i = 0; i < n; i++) { xs[i] = +src[2 * i]; ys[i] = +src[2 * i + 1]; }
    const sn = byRoad.get(r);
    if (sn) for (const s of sn) if (s.vertex >= 0 && s.vertex < n) { xs[s.vertex] = +s.to[0]; ys[s.vertex] = +s.to[1]; stats.snapsApplied++; }
    let px = NaN, py = NaN;
    for (let i = 0; i < n; i++) {
      if (Math.abs(xs[i] - px) < 1e-6 && Math.abs(ys[i] - py) < 1e-6) continue;
      X.push(xs[i]); Y.push(ys[i]); px = xs[i]; py = ys[i];
    }
    roadStart[r + 1] = X.length;
  }
  const V = X.length; stats.vertices = V;
  const vRoad = new Int32Array(V);
  for (let r = 0; r < R; r++) for (let v = roadStart[r]; v < roadStart[r + 1]; v++) vRoad[v] = r;
  const isEnd = v => v === roadStart[vRoad[v]] || v === roadStart[vRoad[v] + 1] - 1;
  const isPrivate = v => rBridge[vRoad[v]] === 1 && !isEnd(v); // a bridge's interior joins nothing

  // union-find over points: vertices first, then crossing points
  const PX = X.slice(), PY = Y.slice(), parent = new Array(V);
  for (let i = 0; i < V; i++) parent[i] = i;
  const find = a => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  const union = (a, b) => { a = find(a); b = find(b); if (a === b) return false; if (a < b) parent[b] = a; else parent[a] = b; return true; };
  const addPoint = (x, y) => { PX.push(x); PY.push(y); parent.push(parent.length); return parent.length - 1; };

  // shared vertices (within JOIN)
  {
    const cell = new Map(); // hashed cells; a collision only costs a distance check
    const key = (cx, cy) => (Math.imul(cx, 73856093) ^ Math.imul(cy, 19349663)) & 0x3fffffff;
    for (let v = 0; v < V; v++) {
      if (isPrivate(v)) continue;
      const cx = Math.floor(X[v] / JOIN), cy = Math.floor(Y[v] / JOIN);
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const l = cell.get(key(cx + dx, cy + dy)); if (!l) continue;
        for (const w of l) if (Math.hypot(X[v] - X[w], Y[v] - Y[w]) <= JOIN && union(v, w) && vRoad[v] !== vRoad[w]) stats.sharedVertexJoins++;
      }
      const k = key(cx, cy); let l = cell.get(k); if (!l) cell.set(k, l = []); l.push(v);
    }
  }

  // segments: segment s runs from vertex sV[s] to sV[s] + 1
  const segList = [];
  for (let r = 0; r < R; r++) for (let v = roadStart[r]; v < roadStart[r + 1] - 1; v++) segList.push(v);
  const SN = segList.length, sV = Int32Array.from(segList);
  const sax = new Float64Array(SN), say = new Float64Array(SN), sbx = new Float64Array(SN), sby = new Float64Array(SN);
  for (let i = 0; i < SN; i++) { const v = sV[i]; sax[i] = X[v]; say[i] = Y[v]; sbx[i] = X[v + 1]; sby[i] = Y[v + 1]; }
  const sBridge = i => rBridge[vRoad[sV[i]]] === 1;
  const splits = new Map(); // segment -> [[t, point], ...]
  const addSplit = (s, t, p) => { let a = splits.get(s); if (!a) splits.set(s, a = []); a.push([t, p]); };
  const BG = buildSegGrid(SN, sax, say, sbx, sby, null, 50, JOIN + 0.01);
  const pr = new Float64Array(4);

  // a road end on another road's segment: split that segment there (never a bridge's span)
  for (let r = 0; r < R; r++) {
    const a = roadStart[r], b = roadStart[r + 1] - 1; if (b < a) continue;
    for (const e of a === b ? [a] : [a, b]) {
      const cx = Math.floor((X[e] - BG.x0) / BG.cs), cy = Math.floor((Y[e] - BG.y0) / BG.cs);
      if (cx < 0 || cy < 0 || cx >= BG.nx || cy >= BG.ny) continue;
      const c = cy * BG.nx + cx;
      for (let k = BG.start[c]; k < BG.start[c + 1]; k++) {
        const s = BG.items[k], v0 = sV[s];
        if (v0 === e || v0 + 1 === e) continue; // its own segment
        projSeg(X[e], Y[e], sax[s], say[s], sbx[s], sby[s], pr);
        if (pr[3] > JOIN) continue;
        if (sBridge(s)) { if (find(e) !== find(v0) && find(e) !== find(v0 + 1)) stats.endOnBridgeIgnored++; continue; }
        const L = Math.hypot(sbx[s] - sax[s], sby[s] - say[s]);
        if (pr[0] * L <= JOIN) union(e, v0);
        else if ((1 - pr[0]) * L <= JOIN) union(e, v0 + 1);
        else { addSplit(s, pr[0], e); stats.endOnSegment++; }
      }
    }
  }

  // at-grade crossings of non-bridge roads with no shared vertex
  if (opts.crossings !== false) {
    for (let c = 0; c < BG.nx * BG.ny; c++) {
      const s0 = BG.start[c], s1 = BG.start[c + 1]; if (s1 - s0 < 2) continue;
      const ccx = c % BG.nx, ccy = (c / BG.nx) | 0;
      for (let p = s0; p < s1; p++) {
        const i = BG.items[p]; if (sBridge(i)) continue;
        for (let q = p + 1; q < s1; q++) {
          const j = BG.items[q]; if (sBridge(j)) continue;
          const vi = sV[i], vj = sV[j];
          if (vi === vj || vi + 1 === vj || vj + 1 === vi) continue; // same or consecutive segments of one road
          const rx = sbx[i] - sax[i], ry = sby[i] - say[i], qx = sbx[j] - sax[j], qy = sby[j] - say[j];
          const den = rx * qy - ry * qx, Li = Math.hypot(rx, ry), Lj = Math.hypot(qx, qy);
          if (Li < 1e-9 || Lj < 1e-9) continue;
          if (Math.abs(den) < 1e-9 * Li * Lj) { // parallel: count collinear overlaps for the report
            if (Math.abs((sax[j] - sax[i]) * ry - (say[j] - say[i]) * rx) / Li < 0.05) {
              const u0 = ((sax[j] - sax[i]) * rx + (say[j] - say[i]) * ry) / (Li * Li), u1 = ((sbx[j] - sax[i]) * rx + (sby[j] - say[i]) * ry) / (Li * Li);
              const lo = Math.max(Math.min(u0, u1), 0), hi = Math.min(Math.max(u0, u1), 1);
              if ((hi - lo) * Li > 1 && Math.floor((sax[i] + rx * lo - BG.x0) / BG.cs) === ccx && Math.floor((say[i] + ry * lo - BG.y0) / BG.cs) === ccy) stats.parallelOverlaps++;
            }
            continue;
          }
          const wx = sax[j] - sax[i], wy = say[j] - say[i];
          const ti = (wx * qy - wy * qx) / den, tj = (wx * ry - wy * rx) / den;
          if (ti < -1e-9 || ti > 1 + 1e-9 || tj < -1e-9 || tj > 1 + 1e-9) continue;
          const ix = sax[i] + rx * ti, iy = say[i] + ry * ti;
          if (Math.floor((ix - BG.x0) / BG.cs) !== ccx || Math.floor((iy - BG.y0) / BG.cs) !== ccy) continue; // counted in its own cell
          const ni = ti * Li <= JOIN ? vi : (1 - ti) * Li <= JOIN ? vi + 1 : -1;
          const nj = tj * Lj <= JOIN ? vj : (1 - tj) * Lj <= JOIN ? vj + 1 : -1;
          if (ni >= 0 && nj >= 0) union(ni, nj);
          else if (ni >= 0) { if (find(ni) !== find(vj) && find(ni) !== find(vj + 1)) { addSplit(j, tj, ni); stats.vertexOnSegment++; } }
          else if (nj >= 0) { if (find(nj) !== find(vi) && find(nj) !== find(vi + 1)) { addSplit(i, ti, nj); stats.vertexOnSegment++; } }
          else { const P = addPoint(ix, iy); addSplit(i, ti, P); addSplit(j, tj, P); stats.crossings++; }
        }
      }
    }
  }
  const NP = parent.length, root = new Int32Array(NP);
  for (let p = 0; p < NP; p++) root[p] = find(p);
  return { JOIN, names, R, rName, rClass, rBridge, V, vRoad, SN, sV, PX, PY, root, NP, splits, stats };
}

// ---------------------------------------------------------------------------------------------
// Stage 2: nodes, edges, adjacency, edge grid. `links` = gap links found on a first assembly.

function assemble(base, links, opts) {
  const { names, rName, rClass, rBridge, vRoad, SN, sV, root, NP } = base;
  const PX = base.PX.slice(), PY = base.PY.slice();
  const extraSplits = new Map(), linkPairs = [];
  if (links) for (const L of links) {
    let tp = L.toPoint;
    if (tp < 0) { tp = PX.length; PX.push(L.to[0]); PY.push(L.to[1]); let a = extraSplits.get(L.toSeg); if (!a) extraSplits.set(L.toSeg, a = []); a.push([L.toT, tp]); }
    linkPairs.push([L.fromPoint, tp, L.road]);
  }
  const TP = PX.length, nodeOf = new Int32Array(TP).fill(-1), rep = [];
  const nxs = [], nys = [];
  for (let p = 0; p < TP; p++) {
    const r = p < NP ? root[p] : p;
    if (nodeOf[r] < 0) { nodeOf[r] = nxs.length; nxs.push(PX[r]); nys.push(PY[r]); rep.push(r); }
    nodeOf[p] = nodeOf[r];
  }
  const N = nxs.length, nx = Float64Array.from(nxs), ny = Float64Array.from(nys);

  // edges: one per piece of a segment between consecutive distinct nodes, then the gap links
  const EA = [], EB = [], ER = [], ES = [], ET0 = [], ET1 = [], EV = [];
  const piece = (a, b, r, s, t0, t1) => { if (a === b) return; EA.push(a); EB.push(b); ER.push(r); ES.push(s); ET0.push(t0); ET1.push(t1); EV.push(0); };
  for (let s = 0; s < SN; s++) {
    const v = sV[s], r = vRoad[v], s1 = base.splits.get(s), s2 = extraSplits.get(s);
    if (!s1 && !s2) { piece(nodeOf[v], nodeOf[v + 1], r, s, 0, 1); continue; }
    const sp = s1 && s2 ? s1.concat(s2) : (s1 || s2).slice();
    sp.sort((a, b) => a[0] - b[0]);
    let pt = 0, pn = nodeOf[v];
    for (const [tt, p] of sp) { const n = nodeOf[p]; piece(pn, n, r, s, pt, tt); if (n !== pn) { pn = n; pt = tt; } }
    piece(pn, nodeOf[v + 1], r, s, pt, 1);
  }
  for (const [pa, pb, r] of linkPairs) { const a = nodeOf[pa], b = nodeOf[pb]; if (a === b) continue; EA.push(a); EB.push(b); ER.push(r); ES.push(-1); ET0.push(0); ET1.push(1); EV.push(1); }
  const E = EA.length;
  const eA = Int32Array.from(EA), eB = Int32Array.from(EB), eRoad = Int32Array.from(ER), eSeg = Int32Array.from(ES);
  const eT0 = Float64Array.from(ET0), eT1 = Float64Array.from(ET1), eVirtual = Uint8Array.from(EV);
  const eLen = new Float64Array(E), eTime = new Float64Array(E), eClass = new Uint8Array(E), eBridge = new Uint8Array(E);
  const speedsMps = new Float64Array(CLASSES.length);
  for (let c = 0; c < CLASSES.length; c++) speedsMps[c] = SPEED_MPH[CLASSES[c]] * MPS_PER_MPH;
  for (let e = 0; e < E; e++) {
    const a = eA[e], b = eB[e], r = eRoad[e];
    eLen[e] = Math.hypot(nx[b] - nx[a], ny[b] - ny[a]); eClass[e] = rClass[r]; eBridge[e] = eVirtual[e] ? 0 : rBridge[r];
    eTime[e] = eLen[e] / speedsMps[eClass[e]];
  }
  const adjStart = new Int32Array(N + 1);
  for (let e = 0; e < E; e++) { adjStart[eA[e] + 1]++; adjStart[eB[e] + 1]++; }
  for (let n = 0; n < N; n++) adjStart[n + 1] += adjStart[n];
  const adjEdge = new Int32Array(2 * E), adjNode = new Int32Array(2 * E), fillA = adjStart.slice(0, N);
  for (let e = 0; e < E; e++) { let k = fillA[eA[e]]++; adjEdge[k] = e; adjNode[k] = eB[e]; k = fillA[eB[e]]++; adjEdge[k] = e; adjNode[k] = eA[e]; }

  // edge geometry and the spatial grid used by nearest() (gap links are never snapped to)
  const gax = new Float64Array(E), gay = new Float64Array(E), gbx = new Float64Array(E), gby = new Float64Array(E);
  for (let e = 0; e < E; e++) { gax[e] = nx[eA[e]]; gay[e] = ny[eA[e]]; gbx[e] = nx[eB[e]]; gby[e] = ny[eB[e]]; }
  const grid = buildSegGrid(E, gax, gay, gbx, gby, e => !eVirtual[e], opts.cell || 100, 0);

  return {
    classes: CLASSES.slice(), speedMph: SPEED_MPH, speedsMps, names, roadName: rName, roadClass: rClass, roadBridge: rBridge,
    nodeCount: N, edgeCount: E, nx, ny, eA, eB, eLen, eTime, eRoad, eClass, eBridge, eVirtual, eSeg, eT0, eT1,
    adjStart, adjEdge, adjNode, grid, gax, gay, gbx, gby, rep: Int32Array.from(rep),
    gapLinks: [], stats: Object.assign({}, base.stats), _ws: null, _comp: new Map(),
  };
}

// ---------------------------------------------------------------------------------------------
// Gap links: Boruvka rounds. Every piece other than the largest finds its shortest straight link
// over land to a road in another piece (within maxGap); links join pieces until none is left in reach.

function landTester(land) {
  const polys = [];
  for (const poly of land || []) {
    if (!poly || !poly.length) continue;
    const rings = (Array.isArray(poly[0]) ? poly : [poly]).map(r => { let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity; for (let i = 0; i < r.length; i += 2) { a = Math.min(a, r[i]); c = Math.max(c, r[i]); b = Math.min(b, r[i + 1]); d = Math.max(d, r[i + 1]); } return { r, bb: [a, b, c, d] }; });
    polys.push(rings);
  }
  const inRing = (R, x, y) => {
    const { r, bb } = R; if (x < bb[0] || x > bb[2] || y < bb[1] || y > bb[3]) return false;
    let inside = false;
    for (let i = 0, j = r.length - 2; i < r.length; j = i, i += 2) {
      const xi = r[i], yi = r[i + 1], xj = r[j], yj = r[j + 1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  if (!polys.length) return () => true;
  return (x, y) => { for (const rings of polys) { if (!inRing(rings[0], x, y)) continue; let hole = false; for (let k = 1; k < rings.length; k++) if (inRing(rings[k], x, y)) { hole = true; break; } if (!hole) return true; } return false; };
}

function findGapLinks(g, land, maxGap, JOIN) {
  const onLand = landTester(land);
  const mask = allowMask(null);
  const cc = components(g, mask);
  const K = cc.sizes.length; if (K < 2) return [];
  const cp = new Int32Array(K); for (let i = 0; i < K; i++) cp[i] = i;
  const cfind = a => { while (cp[a] !== a) { cp[a] = cp[cp[a]]; a = cp[a]; } return a; };
  const csize = Float64Array.from(cc.sizes);
  const { eA, eB, eClass, eBridge, eVirtual, nx, ny, adjStart, adjEdge, nodeCount: N } = g;
  // nodes that can start a link: on a usable non-bridge road
  const startClass = new Int16Array(N).fill(-1), startRoad = new Int32Array(N).fill(-1);
  for (let n = 0; n < N; n++) for (let k = adjStart[n]; k < adjStart[n + 1]; k++) {
    const e = adjEdge[k]; if (!mask[eClass[e]] || eBridge[e] || eVirtual[e]) continue;
    if (startClass[n] < 0 || eClass[e] < startClass[n]) { startClass[n] = eClass[e]; startRoad[n] = g.eRoad[e]; }
  }
  const seen = new Int32Array(g.edgeCount); let stampId = 0;
  const out = [0, 0, 0, 0];
  const clearOverLand = (x0, y0, x1, y1) => { const L = Math.hypot(x1 - x0, y1 - y0), k = Math.max(1, Math.ceil(L / 2)); for (let i = 0; i <= k; i++) if (!onLand(x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k)) return false; return true; };
  const links = [];
  for (let round = 0; round < 64; round++) {
    let big = -1; for (let i = 0; i < K; i++) if (cfind(i) === i && (big < 0 || csize[i] > csize[big])) big = i;
    // per piece, the TOP shortest candidates (one per start node); searches are bounded by the worst kept
    const TOP = 8, cand = new Map();
    let S = -1;
    const foreign = f => mask[eClass[f]] && !eBridge[f] && cc.comp[eA[f]] >= 0 && cfind(cc.comp[eA[f]]) !== S;
    for (let n = 0; n < N; n++) {
      const c = cc.comp[n]; if (c < 0 || startClass[n] < 0) continue;
      S = cfind(c); if (S === big) continue;
      let a = cand.get(S); if (!a) cand.set(S, a = []);
      const bound = a.length >= TOP ? a[a.length - 1].d : maxGap;
      const e = gridNearest(g.grid, g.gax, g.gay, g.gbx, g.gby, nx[n], ny[n], foreign, bound, seen, ++stampId, out);
      if (e < 0) continue;
      const k = { n, e, t: out[0], x: out[1], y: out[2], d: out[3] };
      let i = a.length; a.push(k); while (i > 0 && a[i - 1].d > k.d) { a[i] = a[i - 1]; i--; } a[i] = k;
      if (a.length > TOP) a.pop();
    }
    const chosen = [];
    for (const [P, a] of cand) for (const k of a) if (clearOverLand(nx[k.n], ny[k.n], k.x, k.y)) { chosen.push({ S: P, ...k }); break; }
    chosen.sort((p, q) => p.d - q.d);
    let added = 0;
    for (const k of chosen) {
      const S = cfind(k.S), T = cfind(cc.comp[eA[k.e]]); if (S === T) continue;
      const e = k.e, L = g.eLen[e];
      let toPoint = -1, toSeg = -1, toT = 0, to = [k.x, k.y];
      if (k.t * L <= JOIN) { toPoint = g.rep[eA[e]]; to = [nx[eA[e]], ny[eA[e]]]; }
      else if ((1 - k.t) * L <= JOIN) { toPoint = g.rep[eB[e]]; to = [nx[eB[e]], ny[eB[e]]]; }
      else { toSeg = g.eSeg[e]; toT = g.eT0[e] + k.t * (g.eT1[e] - g.eT0[e]); }
      links.push({ fromPoint: g.rep[k.n], from: [nx[k.n], ny[k.n]], toPoint, toSeg, toT, to, meters: Math.hypot(to[0] - nx[k.n], to[1] - ny[k.n]), road: startRoad[k.n], toRoad: g.eRoad[e], joined: [csize[S], csize[T]] });
      if (csize[S] > csize[T]) { cp[T] = S; csize[S] += csize[T]; } else { cp[S] = T; csize[T] += csize[S]; }
      added++;
    }
    if (!added) break;
  }
  return links;
}

/**
 * Build the routable road graph.
 * @param {object} wp parsed data/wpdata.json (never modified)
 * @param {object} [opts]
 *   roadSnaps: [{road, vertex, to:[x,y]}]  QA fixes, applied to a copy first
 *   gapLinks: max meters for links that tie unreached pieces to the network (default 300; false = none)
 *   extraRoads: [[name, class, isBridge, [x,y,...]]]  hypothetical roads to add (for what-ifs)
 *   joinTol (0.5), crossings (true), cell (100)
 */
export function buildGraph(wp, opts = {}) {
  const t0 = now(), ms = {};
  let tt = now();
  const base = prepare(wp, opts);
  ms.prepare = now() - tt; tt = now();
  let g = assemble(base, null, opts);
  const raw = components(g, allowMask(null));
  const rawStats = { components: raw.sizes.length, largest: raw.sizes[0] || 0, sizes: raw.sizes.slice(0, 12) };
  ms.assemble = now() - tt; tt = now();
  if (opts.gapLinks !== false) {
    const maxGap = typeof opts.gapLinks === 'number' ? opts.gapLinks : DEFAULT_GAP;
    const links = findGapLinks(g, wp.land, maxGap, base.JOIN);
    ms.gapLinks = now() - tt; tt = now();
    if (links.length) {
      g = assemble(base, links, opts);
      ms.reassemble = now() - tt;
      g.gapLinks = links.map(L => ({ from: L.from, to: L.to, meters: L.meters, road: L.road, toRoad: L.toRoad, joined: L.joined }));
    }
  }
  const cc = components(g, allowMask(null));
  const st = g.stats;
  st.nodes = g.nodeCount; st.edges = g.edgeCount;
  st.componentsBeforeGapLinks = rawStats.components; st.largestBeforeGapLinks = rawStats.largest;
  st.gapLinks = g.gapLinks.length; st.gapLinkMeters = Math.round(g.gapLinks.reduce((s, l) => s + l.meters, 0));
  st.components = cc.sizes.length; st.componentSizes = cc.sizes.slice(); st.largestComponent = cc.sizes[0] || 0;
  st.buildMs = Math.round(now() - t0);
  for (const k in ms) ms[k] = Math.round(ms[k]);
  st.phaseMs = ms;
  return g;
}

// ---------------------------------------------------------------------------------------------

function allowMask(classes) {
  const m = new Uint8Array(CLASSES.length);
  if (classes && classes.length) { for (const c of classes) { const i = typeof c === 'number' ? c : CLASSES.indexOf(c); if (i >= 0) m[i] = 1; } }
  else { m.fill(1); for (const c of DEFAULT_EXCLUDE) m[CLASSES.indexOf(c)] = 0; }
  return m;
}

/** Connected components over the allowed classes (cached per class set). Labels are ranked by size: 0 = largest. */
function components(graph, mask) {
  const key = mask.join('');
  let c = graph._comp.get(key); if (c) return c;
  const { nodeCount: N, adjStart, adjEdge, adjNode, eClass } = graph;
  const comp = new Int32Array(N).fill(-1), stack = new Int32Array(N), raw = [];
  for (let s = 0; s < N; s++) {
    if (comp[s] >= 0) continue;
    let has = false; for (let k = adjStart[s]; k < adjStart[s + 1]; k++) if (mask[eClass[adjEdge[k]]]) { has = true; break; }
    if (!has) continue; // no usable road at this node
    const id = raw.length; let sz = 0, sp = 0; stack[sp++] = s; comp[s] = id;
    while (sp) { const u = stack[--sp]; sz++; for (let k = adjStart[u]; k < adjStart[u + 1]; k++) { if (!mask[eClass[adjEdge[k]]]) continue; const w = adjNode[k]; if (comp[w] < 0) { comp[w] = id; stack[sp++] = w; } } }
    raw.push(sz);
  }
  const order = raw.map((_, i) => i).sort((a, b) => raw[b] - raw[a]);
  const rank = new Int32Array(raw.length); order.forEach((id, r) => { rank[id] = r; });
  for (let n = 0; n < N; n++) if (comp[n] >= 0) comp[n] = rank[comp[n]];
  c = { comp, sizes: order.map(id => raw[id]) };
  graph._comp.set(key, c);
  return c;
}

// Points snap to roads that belong to a real network, not to a stray stub that reaches nothing:
// pieces smaller than 1% of the largest are skipped unless opts.minComponent says otherwise.
function snapThreshold(graph, mask) {
  const cc = components(graph, mask);
  return cc.sizes.length ? Math.max(2, Math.ceil(cc.sizes[0] * 0.01)) : 0;
}

/**
 * Closest point on the road network (gap links excluded).
 * opts.classes: allow-list of class names (default: every class but 'path').
 * opts.minComponent: ignore roads in pieces with fewer nodes (default 0: any road).
 * @returns {{edge:number,t:number,x:number,y:number,dist:number,road:number}|null}
 */
export function nearest(graph, x, y, opts = {}) {
  const mask = opts._mask || allowMask(opts.classes);
  const minComp = opts.minComponent || 0;
  const cc = minComp > 1 ? components(graph, mask) : null;
  const { eA, eClass } = graph;
  const ws = workspace(graph), out = ws.pr;
  const ok = cc ? e => { if (!mask[eClass[e]]) return false; const c = cc.comp[eA[e]]; return c >= 0 && cc.sizes[c] >= minComp; } : e => mask[eClass[e]] === 1;
  const e = gridNearest(graph.grid, graph.gax, graph.gay, graph.gbx, graph.gby, x, y, ok, Infinity, ws.eStamp, ++ws.eStampId, out);
  if (e < 0) return null;
  return { edge: e, t: out[0], x: out[1], y: out[2], dist: out[3], road: graph.eRoad[e] };
}

// ---------------------------------------------------------------------------------------------
// search workspace (reused between calls; single-threaded JS makes that safe)

function workspace(graph) {
  let ws = graph._ws;
  if (!ws) {
    const N = graph.nodeCount, E = graph.edgeCount, H = 2 * E + 16;
    ws = graph._ws = {
      g: new Float64Array(N), g2: new Float64Array(N), prev: new Int32Array(N), stamp: new Int32Array(N), stampId: 0,
      done: new Uint8Array(N), eStamp: new Int32Array(E), eStampId: 0, pr: [0, 0, 0, 0],
      hk: new Float64Array(H), hv: new Int32Array(H), hn: 0, topKey: 0,
    };
  }
  return ws;
}

// binary min-heap on (hk, hv)
function hpush(ws, k, v) {
  if (ws.hn >= ws.hk.length) { const nk = new Float64Array(ws.hk.length * 2), nv = new Int32Array(ws.hv.length * 2); nk.set(ws.hk); nv.set(ws.hv); ws.hk = nk; ws.hv = nv; }
  const hk = ws.hk, hv = ws.hv; let i = ws.hn++;
  while (i > 0) { const p = (i - 1) >> 1; if (hk[p] <= k) break; hk[i] = hk[p]; hv[i] = hv[p]; i = p; }
  hk[i] = k; hv[i] = v;
}
function hpop(ws) { // returns the value; its key is left in ws.topKey
  const hk = ws.hk, hv = ws.hv, v = hv[0]; ws.topKey = hk[0];
  const n = --ws.hn; if (n === 0) return v;
  const k = hk[n], x = hv[n]; let i = 0;
  for (;;) { let c = 2 * i + 1; if (c >= n) break; if (c + 1 < n && hk[c + 1] < hk[c]) c++; if (hk[c] >= k) break; hk[i] = hk[c]; hv[i] = hv[c]; i = c; }
  hk[i] = k; hv[i] = x; return v;
}

function snapOpts(graph, opts, mask) {
  return { _mask: mask, minComponent: opts.minComponent != null ? opts.minComponent : snapThreshold(graph, mask) };
}
function speedBound(graph, mask) {
  let v = 0; for (let c = 0; c < CLASSES.length; c++) if (mask[c]) v = Math.max(v, graph.speedsMps[c]);
  return v || 1;
}
function roadNameOf(graph, r) { const i = graph.roadName[r]; return i >= 0 && i < graph.names.length ? graph.names[i] : null; }

/**
 * Route between two points [x,y].
 * opts.metric: 'time' (default) or 'distance'. opts.classes: allow-list (default: all but 'path').
 * @returns {{meters:number,seconds:number,path:number[][],roads:{name:string|null,meters:number}[],access:number[]}|null}
 */
export function route(graph, from, to, opts = {}) {
  const mask = allowMask(opts.classes);
  const so = snapOpts(graph, opts, mask);
  const sa = nearest(graph, from[0], from[1], so), sb = nearest(graph, to[0], to[1], so);
  if (!sa || !sb) return null;
  const useLen = opts.metric === 'distance';
  const cost = useLen ? graph.eLen : graph.eTime;
  const hScale = useLen ? 1 : 1 / speedBound(graph, mask);
  const { eA, eB, nx, ny, adjStart, adjEdge, adjNode, eClass } = graph;
  const ws = workspace(graph);
  const sid = ++ws.stampId; ws.hn = 0;
  const g = ws.g, prev = ws.prev, stamp = ws.stamp, done = ws.done;
  const ea = sa.edge, eb = sb.edge, ta = sa.t, tb = sb.t, tx = sb.x, ty = sb.y;

  let best = Infinity, bestNode = -1;
  if (ea === eb) best = Math.abs(ta - tb) * cost[ea]; // straight along the shared edge
  const seed = (n, c) => {
    if (stamp[n] === sid && g[n] <= c) return;
    stamp[n] = sid; g[n] = c; prev[n] = -1; done[n] = 0; hpush(ws, c + Math.hypot(nx[n] - tx, ny[n] - ty) * hScale, n);
  };
  seed(eA[ea], ta * cost[ea]); seed(eB[ea], (1 - ta) * cost[ea]);
  const tA = eA[eb], tB = eB[eb], xA = tb * cost[eb], xB = (1 - tb) * cost[eb];

  while (ws.hn) {
    const u = hpop(ws);
    if (ws.topKey >= best) break;
    if (done[u]) continue;
    done[u] = 1;
    const gu = g[u];
    if (u === tA && gu + xA < best) { best = gu + xA; bestNode = u; }
    if (u === tB && gu + xB < best) { best = gu + xB; bestNode = u; }
    for (let k = adjStart[u]; k < adjStart[u + 1]; k++) {
      const e = adjEdge[k]; if (!mask[eClass[e]]) continue;
      const w = adjNode[k], gw = gu + cost[e];
      if (stamp[w] !== sid) { stamp[w] = sid; done[w] = 0; g[w] = gw; prev[w] = e; hpush(ws, gw + Math.hypot(nx[w] - tx, ny[w] - ty) * hScale, w); }
      else if (!done[w] && gw < g[w]) { g[w] = gw; prev[w] = e; hpush(ws, gw + Math.hypot(nx[w] - tx, ny[w] - ty) * hScale, w); }
    }
  }
  if (!isFinite(best)) return null;

  // pieces [road, meters, seconds] in travel order
  const mps = e => graph.speedsMps[eClass[e]];
  const pieces = [], path = [[from[0], from[1]], [sa.x, sa.y]];
  if (bestNode < 0) {
    const m = Math.abs(ta - tb) * graph.eLen[ea];
    pieces.push([graph.eRoad[ea], m, m / mps(ea)]);
  } else {
    const edges = []; let n = bestNode;
    while (prev[n] >= 0) { const e = prev[n]; edges.push(e); n = eA[e] === n ? eB[e] : eA[e]; }
    edges.reverse();
    const ma = (n === eA[ea] ? ta : 1 - ta) * graph.eLen[ea];
    pieces.push([graph.eRoad[ea], ma, ma / mps(ea)]);
    path.push([nx[n], ny[n]]);
    let cur = n;
    for (const e of edges) { cur = eA[e] === cur ? eB[e] : eA[e]; pieces.push([graph.eRoad[e], graph.eLen[e], graph.eTime[e]]); path.push([nx[cur], ny[cur]]); }
    const mb = (bestNode === eA[eb] ? tb : 1 - tb) * graph.eLen[eb];
    pieces.push([graph.eRoad[eb], mb, mb / mps(eb)]);
  }
  path.push([sb.x, sb.y], [to[0], to[1]]);

  let netM = 0, sec = 0; const roads = [];
  for (const [r, m, s] of pieces) {
    netM += m; sec += s; if (m <= 1e-9) continue;
    const name = roadNameOf(graph, r), last = roads[roads.length - 1];
    if (last && last.name === name) last.meters += m; else roads.push({ name, meters: m });
  }
  const clean = [];
  for (const p of path) { const q = clean[clean.length - 1]; if (!q || Math.abs(q[0] - p[0]) > 1e-6 || Math.abs(q[1] - p[1]) > 1e-6) clean.push(p); }
  return { meters: netM + sa.dist + sb.dist, seconds: sec, path: clean, roads, access: [sa.dist, sb.dist] };
}

/**
 * One source, many targets, one Dijkstra. Same conventions as route(): meters include the access
 * legs, seconds do not. Returns one {meters, seconds, access} per target, or null where no road route exists.
 */
export function oneToMany(graph, from, targets, opts = {}) {
  const mask = allowMask(opts.classes);
  const so = snapOpts(graph, opts, mask);
  const sa = nearest(graph, from[0], from[1], so);
  if (!sa) return targets.map(() => null);
  const snaps = targets.map(p => nearest(graph, p[0], p[1], so));
  const useLen = opts.metric === 'distance';
  const cost = useLen ? graph.eLen : graph.eTime, other = useLen ? graph.eTime : graph.eLen;
  const { eA, eB, adjStart, adjEdge, adjNode, eClass } = graph;
  const ws = workspace(graph);
  const sid = ++ws.stampId; ws.hn = 0;
  const g = ws.g, g2 = ws.g2, stamp = ws.stamp, done = ws.done;
  const need = new Set(); for (const s of snaps) if (s) { need.add(eA[s.edge]); need.add(eB[s.edge]); }
  const ea = sa.edge, ta = sa.t;
  const seed = (n, c, c2) => { if (stamp[n] === sid && g[n] <= c) return; stamp[n] = sid; g[n] = c; g2[n] = c2; done[n] = 0; hpush(ws, c, n); };
  seed(eA[ea], ta * cost[ea], ta * other[ea]); seed(eB[ea], (1 - ta) * cost[ea], (1 - ta) * other[ea]);
  let left = need.size;
  while (ws.hn && left > 0) {
    const u = hpop(ws);
    if (done[u]) continue;
    done[u] = 1; if (need.has(u)) left--;
    const gu = g[u], g2u = g2[u];
    for (let k = adjStart[u]; k < adjStart[u + 1]; k++) {
      const e = adjEdge[k]; if (!mask[eClass[e]]) continue;
      const w = adjNode[k], gw = gu + cost[e];
      if (stamp[w] !== sid) { stamp[w] = sid; done[w] = 0; g[w] = gw; g2[w] = g2u + other[e]; hpush(ws, gw, w); }
      else if (!done[w] && gw < g[w]) { g[w] = gw; g2[w] = g2u + other[e]; hpush(ws, gw, w); }
    }
  }
  return snaps.map(sb => {
    if (!sb) return null;
    const e = sb.edge, t = sb.t, a = eA[e], b = eB[e];
    let bc = Infinity, b2 = Infinity;
    if (e === ea) { bc = Math.abs(ta - t) * cost[e]; b2 = Math.abs(ta - t) * other[e]; }
    if (stamp[a] === sid && done[a]) { const c = g[a] + t * cost[e]; if (c < bc) { bc = c; b2 = g2[a] + t * other[e]; } }
    if (stamp[b] === sid && done[b]) { const c = g[b] + (1 - t) * cost[e]; if (c < bc) { bc = c; b2 = g2[b] + (1 - t) * other[e]; } }
    if (!isFinite(bc)) return null;
    const net = useLen ? bc : b2, sec = useLen ? b2 : bc;
    return { meters: net + sa.dist + sb.dist, seconds: sec, access: [sa.dist, sb.dist] };
  });
}
