// Scene audit: run inside the map page (window.WP) to check that every generated object is in place.
// Trees, parked cars, streetlights and driveways are tested against buildings, road surfaces, water,
// marsh and the modeled lots. Usage (headless browser): page.evaluate(fs.readFileSync(this file)).
(async () => {
  const app = window.WP, D = app.D;
  const HALF = { trunk: 7.5, primary: 6.5, secondary: 5.5, tertiary: 4.5, residential: 3.75, service: 2.75, track: 2.0, path: 1.0, motorway: 9 };
  const inRect = (b, x, y, m) => { const p = b.poly, ux = (p[2] - p[0]) / b.w, uy = (p[3] - p[1]) / b.w, vx = (p[6] - p[0]) / b.d, vy = (p[7] - p[1]) / b.d, dx = x - b.cx, dy = y - b.cy; return Math.abs(dx * ux + dy * uy) < b.w / 2 + m && Math.abs(dx * vx + dy * vy) < b.d / 2 + m; };
  const inBuilding = (x, y, m = 0, self = null) => { let hit = null; D.bGrid.query(x - 2, y - 2, x + 2, y + 2, k => { const b = D.buildings[k]; if (b !== self && inRect(b, x, y, m)) { hit = b; return false; } }); return hit; };
  const onRoad = (x, y, m = 0) => { let hit = null; D.rGrid.query(x - 10, y - 10, x + 10, y + 10, id => { const s = D.segs[id], r = D.roads[s[4]]; if (r.cls === 'path' || r.bridge) return; const dx = s[2] - s[0], dy = s[3] - s[1], L2 = dx * dx + dy * dy || 1; const t = Math.max(0, Math.min(1, ((x - s[0]) * dx + (y - s[1]) * dy) / L2)); if (Math.hypot(s[0] + dx * t - x, s[1] + dy * t - y) < HALF[r.cls] - m) { hit = r; return false; } }); return hit; };
  const wet = (x, y) => !(D.mask.at(x, y) & 1) || !!(D.mask.at(x, y) & 2);
  const heroLot = (x, y) => { for (const L of D.heroLots || []) { const vx = x - L.x, vy = y - L.y; if (vx * vx + vy * vy > 3600) continue; const lx = vx * L.ny - vy * L.nx, ly = -(vx * L.nx + vy * L.ny), [x0, y0, x1, y1] = L.rect; if (lx >= x0 && lx <= x1 && ly >= y0 && ly <= y1) return L; } return null; };
  const out = { trees: { n: 0, building: 0, road: 0, water: 0, heroLot: 0, samples: [] }, cars: { n: 0, building: 0, road: 0, water: 0, heroLot: 0, samples: [] }, lamps: { n: 0, building: 0, road: 0, water: 0, samples: [] }, drives: { n: 0, building: 0, water: 0, samples: [] } };
  const note = (k, what, x, y) => { out[k][what]++; if (out[k].samples.length < 12) out[k].samples.push([what, Math.round(x), Math.round(y)]); };
  // trees: scatter every cell over the developed area (city limits bbox)
  const lim = D.limits[0]; let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (let i = 0; i < lim.length; i += 2) { x0 = Math.min(x0, lim[i]); x1 = Math.max(x1, lim[i]); y0 = Math.min(y0, lim[i + 1]); y1 = Math.max(y1, lim[i + 1]); }
  const C = 250;
  for (let ci = Math.floor(x0 / C); ci <= Math.floor(x1 / C); ci++) for (let cj = Math.floor(y0 / C); cj <= Math.floor(y1 / C); cj++) {
    const c = app.trees.cell(ci, cj);
    for (const t of c.trees) {
      out.trees.n++;
      if (inBuilding(t.x, t.y, 0)) note('trees', 'building', t.x, t.y);
      else if (onRoad(t.x, t.y, 0.2)) note('trees', 'road', t.x, t.y);
      else if (wet(t.x, t.y) && t.sp !== 'bald-cypress') note('trees', 'water', t.x, t.y);
      else if (heroLot(t.x, t.y)) note('trees', 'heroLot', t.x, t.y);
    }
  }
  for (const c of D.cars) {
    out.cars.n++;
    const fx = Math.sin(c.ang), fz = Math.cos(c.ang); // car forward in world (x, z); Atlas y = -z
    const pts = [[c.x, c.y], [c.x + fx * 2.2, c.y - fz * 2.2], [c.x - fx * 2.2, c.y + fz * 2.2]];
    if (pts.some(([x, y]) => inBuilding(x, y, -0.2))) note('cars', 'building', c.x, c.y);
    else if (pts.some(([x, y]) => onRoad(x, y, 0.3))) note('cars', 'road', c.x, c.y);
    else if (pts.some(([x, y]) => wet(x, y))) note('cars', 'water', c.x, c.y);
    else if (heroLot(c.x, c.y)) note('cars', 'heroLot', c.x, c.y);
  }
  for (const L of D.lamps || []) {
    out.lamps.n++;
    if (inBuilding(L.x, L.y, 0)) note('lamps', 'building', L.x, L.y);
    else if (onRoad(L.x, L.y, 0)) note('lamps', 'road', L.x, L.y);
    else if (wet(L.x, L.y)) note('lamps', 'water', L.x, L.y);
  }
  for (const d of D.drives) {
    out.drives.n++;
    const L = Math.hypot(d.x1 - d.x0, d.y1 - d.y0); let bad = null;
    for (let t = 0.6; t < L - 0.2 && !bad; t += 0.8) { const x = d.x0 + d.nx * t, y = d.y0 + d.ny * t; if (inBuilding(x, y, -0.3, d.b)) bad = 'building'; else if (wet(x, y)) bad = 'water'; }
    if (bad) note('drives', bad, d.x0, d.y0);
  }
  return out;
})()
