// The map's interface: gazetteer search, cards, distances, measuring, layers, views, map check.
import * as THREE from 'three';
import { esc, fmtDist, fmtTime, buildingAt, nearestAddress, nearestRoad, toWorld, STATUS, CAT_COLORS, NINE_ORDER } from './core.js';
import { Labels } from './labels.js';
import { Measure } from './measure.js';

const $ = id => document.getElementById(id);
const KEY_PLACES = [['westport-high', 'Westport High School'], ['pier-bar', 'The pier and the pier bar'], ['nine-acres', 'The nine acres (the field)'], ['chadwicks-diner', "Chadwick's"], ['easts-nook', "East's Nook Books"], ['courthouse-square', 'Courthouse Square'], ['hospital', 'Westport Hospital']];
const KIND_NAMES = { house: 'House', duplex: 'Duplex', mobile: 'Mobile home', shed: 'Shed or garage', barn: 'Barn', shop: 'Downtown storefront', office: 'Office', tower: 'Office tower', deck: 'Parking deck', retail: 'Store', apartments: 'Apartment building', townhouse: 'Townhouse row', clubhouse: 'Clubhouse', church: 'Church', school: 'School', gym: 'Gym', stands: 'Stands', hospital: 'Hospital', industrial: 'Industrial building', civic: 'Civic building', motel: 'Motel', hotel: 'Hotel' };

export class UI {
  constructor(app) {
    this.app = app; this.D = app.D; app.units = localGet('wp-units') || 'imperial';
    this.labels = new Labels(app);
    this.labels.onClick = t => this.open(t);
    this.measure = new Measure(app);
    this.dist = null; this.sel = null;
    this.index();
    this.wire();
    this.ring = new THREE.Mesh(new THREE.RingGeometry(0.82, 1, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthTest: false }));
    this.ring.rotation.x = -Math.PI / 2; this.ring.visible = false; this.ring.renderOrder = 999; app.scene.add(this.ring);
    fetch('data/distances.json').then(r => (r.ok ? r.json() : null)).then(d => { if (d) this.useDistances(d); }).catch(() => {});
    app.onFrame.push(dt => this.frame(dt));
  }

  // ------------------------------------------------------------ search index
  index() {
    const D = this.D, I = this.items = [];
    for (const p of D.places) if (p.at) I.push({ kind: 'place', id: p.id, name: p.name, sub: [p.addr, p.hood].filter(Boolean).join(' · '), at: p.at, status: p.status, cat: p.cat, hay: [p.name, p.addr, p.was, ...(p.people || [])].join(' ').toLowerCase(), group: p.hood || 'Elsewhere' });
    for (const h of D.people) if (h.home && h.home.at) I.push({ kind: 'person', name: h.name, sub: [h.home.addr, h.home.note].filter(Boolean).join(' · '), at: h.home.at, color: h.color, status: h.home.status, hay: [h.name, h.role, h.home.addr, h.home.note].join(' ').toLowerCase(), group: h.group || 'Westport' });
    for (const [name, s] of D.streets) { const r = D.roads[s.roads[0]]; const p = r.pts, k = Math.floor(p.length / 4) * 2; I.push({ kind: 'street', name, sub: `${s.cls} · ${fmtDist(s.len, this.app.units)}`, at: [p[k], p[k + 1]], hay: name.toLowerCase(), group: 'Streets' }); }
  }
  search(q) {
    q = q.trim().toLowerCase(); const res = $('results');
    if (!q) { this.listDefault(); return; }
    const out = [];
    const m = q.match(/^(\d+)\s+(.+)$/);
    if (m) { // a street address
      const num = +m[1], st = m[2];
      for (const b of this.D.buildings) if (b.num === num && b.street && b.street.toLowerCase().startsWith(st)) out.push({ kind: 'address', name: `${b.num} ${b.street}`, sub: KIND_NAMES[b.kind] || b.kind, at: [b.cx, b.cy], b, group: 'Addresses' });
    }
    for (const it of this.items) if (it.hay.includes(q)) out.push(it);
    res.innerHTML = out.length ? this.renderList(out.slice(0, 120)) : `<p class="hint pad">Nothing matches “${esc(q)}”. Try a street, a name, or an address like 648 Oak Street.</p>`;
  }
  listDefault() {
    const nine = NINE_ORDER.map(n => this.items.find(i => i.kind === 'person' && i.name === n)).filter(Boolean);
    const places = this.items.filter(i => i.kind === 'place');
    $('results').innerHTML = `<div class="group-h">The Nine</div>${this.renderList(nine, false)}<div class="group-h">Places</div>${this.renderList(places, true)}`;
  }
  renderList(arr, grouped = true) {
    let html = '', g = null;
    arr.forEach((it, k) => {
      if (grouped && it.group !== g) { g = it.group; html += `<div class="group-h">${esc(g)}</div>`; }
      const dot = it.kind === 'person' && it.color ? `<span class="sw" style="background:${it.color}"></span>` : it.kind === 'place' ? `<span class="dot" style="background:${CAT_COLORS[it.cat] || '#999'}"></span>` : `<span class="dot hollow"></span>`;
      html += `<button class="res" data-k="${this.items.indexOf(it)}" data-ad="${it.kind === 'address' ? it.at.join(',') : ''}">${dot}<span><span class="nm">${esc(it.name)}</span>${it.status ? ` <span class="chip ${chipCls(it.status)}">${esc(STATUS[it.status] || it.status)}</span>` : ''}<span class="sub">${esc(it.sub || '')}</span></span></button>`;
    });
    return html;
  }

  // ------------------------------------------------------------ wiring
  wire() {
    const app = this.app;
    $('q').addEventListener('input', e => this.search(e.target.value));
    $('results').addEventListener('click', e => {
      const b = e.target.closest('.res'); if (!b) return;
      if (b.dataset.ad) { const [x, y] = b.dataset.ad.split(',').map(Number); this.openBuilding(buildingAt(this.D, x, y), [x, y]); return; }
      const it = this.items[+b.dataset.k]; this.open(it.kind === 'person' ? { kind: 'person', name: it.name } : it.kind === 'place' ? { kind: 'place', id: it.id } : { kind: 'street', name: it.name });
    });
    $('gazToggle').onclick = () => document.body.classList.toggle('gaz-min');
    document.querySelectorAll('#segStyle button').forEach(b => b.onclick = () => { app.setStyle(+b.dataset.v); this.syncSeg(); this.saveHash(); });
    document.querySelectorAll('#segView button').forEach(b => b.onclick = () => this.setView(b.dataset.v));
    for (const [btn, pan] of [['layersBtn', 'layers'], ['measureBtn', 'measure'], ['distBtn', 'dist'], ['qaBtn', 'qa'], ['aboutBtn', 'about']]) $(btn).onclick = () => this.togglePanel(pan);
    document.querySelectorAll('.panel .x').forEach(x => x.onclick = () => this.togglePanel(x.closest('.panel').id, false));
    // layers
    for (const el of document.querySelectorAll('#layers input[data-l]')) el.onchange = () => this.layer(el.dataset.l, el.checked);
    $('hour').oninput = e => { app.atm.setHour(+e.target.value); $('hourOut').textContent = clock(+e.target.value); };
    $('units').onchange = e => { app.units = e.target.value; localSet('wp-units', app.units); this.measure.render(); if (this.sel) this.open(this.sel, false); this.renderDist(); };
    // measure
    document.querySelectorAll('#mMode button').forEach(b => b.onclick = () => { document.querySelectorAll('#mMode button').forEach(x => x.classList.toggle('on', x === b)); this.measure.setMode(b.dataset.m); });
    $('mClear').onclick = () => this.measure.clear();
    // distances panel
    document.querySelectorAll('#dTabs button').forEach(b => b.onclick = () => { this.dTab = b.dataset.t; document.querySelectorAll('#dTabs button').forEach(x => x.classList.toggle('on', x === b)); this.renderDist(); });
    // picking, hover
    const cv = app.renderer.domElement; let down = null;
    cv.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY, performance.now()]; });
    cv.addEventListener('pointerup', e => { if (!down || e.button !== 0) return; const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]); if (moved < 5 && performance.now() - down[2] < 500) this.click(e); down = null; });
    cv.addEventListener('pointermove', e => this.hover(e));
    window.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT') return;
      if (this.measure.active && (e.key === 'Backspace' || e.key === 'Delete')) { this.measure.undo(); e.preventDefault(); }
      if (e.key === 'Escape') { if (this.street) this.setView('3D'); else if (this.measure.active) this.togglePanel('measure', false); else this.closeCard(); }
      if (e.key === 'm' || e.key === 'M') this.togglePanel('measure');
      if (e.key === '/') { $('q').focus(); e.preventDefault(); }
    });
    $('compass').onclick = () => this.northUp();
    $('zin').onclick = () => this.zoomBy(0.6); $('zout').onclick = () => this.zoomBy(1.6);
    window.addEventListener('hashchange', () => this.fromHash());
    this.listDefault(); this.syncSeg(); this.fromHash(true);
    $('cardBody').addEventListener('click', e => {
      const a = e.target.closest('[data-open]'); if (a) { const [kind, ...rest] = a.dataset.open.split(':'); const v = rest.join(':'); this.open(kind === 'person' ? { kind, name: v } : kind === 'place' ? { kind, id: v } : { kind, name: v }); }
      const m = e.target.closest('[data-measure]'); if (m) { const [x, y] = m.dataset.measure.split(',').map(Number); this.togglePanel('measure', true); this.measure.clear(); this.measure.add([x, y]); }
      const d = e.target.closest('[data-dist]'); if (d) { this.distOrigin = this.sel; this.togglePanel('dist', true); this.renderDist(); }
    });
  }
  syncSeg() { document.querySelectorAll('#segStyle button').forEach(b => b.classList.toggle('on', +b.dataset.v === this.app.style)); const th = this.app.style === 2 ? 'dark' : this.app.style === 0 ? null : 'light'; if (th) document.documentElement.dataset.theme = th; else delete document.documentElement.dataset.theme; document.body.dataset.style = this.app.style; }
  togglePanel(id, force) {
    const el = $(id); const on = force ?? el.classList.contains('hidden');
    for (const p of ['layers', 'measure', 'dist', 'qa', 'about']) if (p !== id && on && ['measure', 'dist', 'qa', 'about'].includes(id) && ['measure', 'dist', 'qa', 'about'].includes(p)) { $(p).classList.add('hidden'); $(p + 'Btn')?.classList.remove('on'); }
    el.classList.toggle('hidden', !on); $(id + 'Btn')?.classList.toggle('on', on);
    if (id === 'measure') { on ? this.measure.start() : this.measure.stop(); this.measure.render(); }
    if (id === 'dist' && on) this.renderDist();
    if (id === 'qa' && on) this.renderQA();
  }
  layer(l, on) {
    const app = this.app;
    if (l in this.labels.show) { this.labels.show[l] = on; return; }
    if (l === 'trees') { app.trees.enabled = on; app.trees.update(true); }
    if (l === 'buildings') { app.buildings.visible = on; app.models.group.visible = on; }
    if (l === 'shadows') app.atm.sun.castShadow = on;
    if (l === 'ao' && app.ao) app.ao.enabled = on;
  }

  // ------------------------------------------------------------ camera moves
  flyTo(at, dist = 420, tilt = 55, heading = null) {
    const app = this.app, c = app.controls, from = { t: c.target.clone(), p: app.camera.position.clone() };
    const target = toWorld(at[0], at[1], 0);
    const off = app.camera.position.clone().sub(c.target);
    const hd = heading == null ? Math.atan2(-off.x, off.z) : THREE.MathUtils.degToRad(heading);
    const tl = THREE.MathUtils.degToRad(this.mode2D ? 0.5 : tilt);
    const toP = target.clone().add(new THREE.Vector3(-Math.sin(hd) * Math.sin(tl), Math.cos(tl), Math.cos(hd) * Math.sin(tl)).multiplyScalar(dist));
    this.anim = { t0: performance.now(), dur: 1300, from, to: { t: target, p: toP } };
  }
  zoomBy(k) { const c = this.app.controls, p = this.app.camera.position; const off = p.clone().sub(c.target).multiplyScalar(k); this.anim = { t0: performance.now(), dur: 450, from: { t: c.target.clone(), p: p.clone() }, to: { t: c.target.clone(), p: c.target.clone().add(off) } }; }
  northUp() { const c = this.app.controls, p = this.app.camera.position; const off = p.clone().sub(c.target); const h = Math.hypot(off.x, off.z); this.anim = { t0: performance.now(), dur: 600, from: { t: c.target.clone(), p: p.clone() }, to: { t: c.target.clone(), p: c.target.clone().add(new THREE.Vector3(0, off.y, h)) } }; }
  setView(v) {
    const app = this.app, c = app.controls;
    document.querySelectorAll('#segView button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
    this.leaveStreet();
    this.mode2D = v === '2D';
    if (v === '2D') { c.maxPolarAngle = 0.001; c.enableRotate = true; this.flyTo([c.target.x, -c.target.z], app.camera.position.distanceTo(c.target), 0, 0); }
    else if (v === '3D') { c.maxPolarAngle = Math.PI * 0.47; this.flyTo([c.target.x, -c.target.z], app.camera.position.distanceTo(c.target), 55); }
    else if (v === 'Street') this.enterStreet();
  }
  enterStreet() {
    const app = this.app, c = app.controls; this.street = { yaw: 0, pitch: 0, keys: new Set() };
    const t = c.target.clone(); const off = app.camera.position.clone().sub(t); this.street.yaw = Math.atan2(-off.x, -off.z) + Math.PI;
    // stand on the nearest sidewalk or road edge, not inside a building
    const [x, y] = [t.x, -t.z]; const nr = nearestRoad(this.D, x, y, 400, r => r.cls !== 'track' && !r.bridge);
    const at = nr ? [nr.x, nr.y] : [x, y];
    app.camera.position.set(at[0], 1.7, -at[1]); c.enabled = false; document.body.classList.add('street');
    $('streetHelp').classList.remove('hidden');
    const kd = e => { this.street && this.street.keys.add(e.key.toLowerCase()); }, ku = e => { this.street && this.street.keys.delete(e.key.toLowerCase()); };
    let drag = null; const pd = e => { drag = [e.clientX, e.clientY]; }, pm = e => { if (!drag || !this.street) return; this.street.yaw -= (e.clientX - drag[0]) * 0.004; this.street.pitch = THREE.MathUtils.clamp(this.street.pitch - (e.clientY - drag[1]) * 0.003, -1.2, 1.2); drag = [e.clientX, e.clientY]; }, pu = () => { drag = null; };
    window.addEventListener('keydown', kd); window.addEventListener('keyup', ku); app.renderer.domElement.addEventListener('pointerdown', pd); window.addEventListener('pointermove', pm); window.addEventListener('pointerup', pu);
    this.street.off = () => { window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku); app.renderer.domElement.removeEventListener('pointerdown', pd); window.removeEventListener('pointermove', pm); window.removeEventListener('pointerup', pu); };
  }
  leaveStreet() {
    if (!this.street) return; const app = this.app; this.street.off(); this.street = null; document.body.classList.remove('street'); $('streetHelp').classList.add('hidden');
    const p = app.camera.position; app.controls.target.set(p.x, 0, p.z - 1); app.camera.position.set(p.x, 160, p.z + 140); app.controls.enabled = true; app.controls.update();
  }

  // ------------------------------------------------------------ per frame
  frame(dt) {
    const app = this.app;
    if (this.anim) {
      const a = this.anim, k = Math.min(1, (performance.now() - a.t0) / a.dur), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      app.controls.target.lerpVectors(a.from.t, a.to.t, e); app.camera.position.lerpVectors(a.from.p, a.to.p, e);
      if (k >= 1) { this.anim = null; this.saveHash(); }
    }
    if (this.street) {
      const s = this.street, cam = app.camera, sp = (s.keys.has('shift') ? 9 : 2.2) * dt;
      const fw = new THREE.Vector3(-Math.sin(s.yaw), 0, -Math.cos(s.yaw)), rt = new THREE.Vector3(-fw.z, 0, fw.x);
      if (s.keys.has('w') || s.keys.has('arrowup')) cam.position.addScaledVector(fw, sp);
      if (s.keys.has('s') || s.keys.has('arrowdown')) cam.position.addScaledVector(fw, -sp);
      if (s.keys.has('a') || s.keys.has('arrowleft')) cam.position.addScaledVector(rt, -sp);
      if (s.keys.has('d') || s.keys.has('arrowright')) cam.position.addScaledVector(rt, sp);
      cam.position.y = 1.7; cam.rotation.set(s.pitch, s.yaw, 0, 'YXZ');
    }
    this.labels.update();
    this.measure.placeTags();
    if (this.ring.visible) { const t = performance.now() / 1000; this.ring.material.opacity = 0.55 + 0.35 * Math.sin(t * 3); }
    this.scaleBar(); this.compass();
    if (!this.street && (this._h = (this._h || 0) + 1) % 30 === 0) this.saveHash(true);
  }
  scaleBar() {
    const app = this.app, d = app.camera.position.distanceTo(app.controls.target);
    const mpp = 2 * d * Math.tan(THREE.MathUtils.degToRad(app.camera.fov / 2)) / app.el.clientHeight;
    const metric = app.units === 'metric';
    const unitM = metric ? 1 : 0.3048; const target = 110 * mpp / unitM;
    const nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000].find(n => n >= target * 0.6) || 50000;
    const px = nice * unitM / mpp;
    $('scaleBar').style.width = px.toFixed(0) + 'px';
    $('scaleTxt').textContent = metric ? (nice >= 1000 ? nice / 1000 + ' km' : nice + ' m') : (nice >= 5280 ? (nice / 5280).toFixed(nice % 5280 ? 1 : 0) + ' mi' : nice + ' ft');
  }
  compass() { const app = this.app; const o = app.camera.position.clone().sub(app.controls.target); const hd = this.street ? -this.street.yaw : Math.atan2(-o.x, o.z); $('needle').style.transform = `rotate(${(-hd * 180 / Math.PI).toFixed(1)}deg)`; }

  // ------------------------------------------------------------ picking
  groundAt(e) {
    const app = this.app, r = app.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, app.camera);
    return { rc, p: rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3()) };
  }
  click(e) {
    const { rc, p } = this.groundAt(e); if (!p) return;
    let at = [p.x, -p.z];
    if (this.measure.active) { this.measure.add(at); return; }
    // models and buildings first (they stand above the ground)
    const hits = rc.intersectObjects([this.app.models.group, this.app.buildings], true).filter(h => h.object.isMesh && h.object.name !== 'contact-shadows');
    if (hits.length) { const h = hits[0]; at = [h.point.x, -h.point.z]; let o = h.object; while (o && !o.name.startsWith('model ')) o = o.parent; if (o) { const it = this.app.models.items.find(i => i.root === o); if (it) { this.openModel(it); return; } } }
    const near = this.nearest(at);
    if (near) { this.open(near); return; }
    const b = buildingAt(this.D, at[0], at[1]) || buildingAt(this.D, p.x, -p.z);
    if (b) { this.openBuilding(b, at); return; }
    const nr = nearestRoad(this.D, at[0], at[1], 12, r => !!r.name);
    if (nr) { this.open({ kind: 'street', name: nr.road.name }); return; }
    this.openSpot(at);
  }
  nearest(at) {
    let best = null;
    for (const it of this.items) { if (it.kind === 'street') continue; const d = Math.hypot(it.at[0] - at[0], it.at[1] - at[1]); if (d < 14 && (!best || d < best.d)) best = { d, it }; }
    if (!best) return null; const it = best.it; return it.kind === 'person' ? { kind: 'person', name: it.name } : { kind: 'place', id: it.id };
  }
  hover(e) {
    if (this.street) return; const { p } = this.groundAt(e); if (!p) return;
    const at = [p.x, -p.z], a = nearestAddress(this.D, at[0], at[1], 60), u = this.app.units;
    $('readout').innerHTML = `<span>${Math.round(at[0])} E, ${Math.round(at[1])} N</span>${a ? `<span>near ${a.b.num} ${esc(a.b.street)}</span>` : ''}<span>${fmtDist(Math.hypot(at[0], at[1]), u)} from Courthouse Square</span>`;
    if (this.measure.active && this.measure.points.length) { const l = this.measure.points[this.measure.points.length - 1]; $('readout').innerHTML += `<span class="live">${fmtDist(Math.hypot(at[0] - l[0], at[1] - l[1]), u)} from the last point</span>`; }
  }

  // ------------------------------------------------------------ cards
  open(t, fly = true) {
    const D = this.D; this.sel = t; let at, html;
    if (t.kind === 'place') {
      const p = D.places.find(x => x.id === t.id); if (!p) return; at = p.at;
      const model = this.app.models.items.find(m => m.id === p.id);
      html = this.cardHead(p.name, p.status, [p.addr, p.hood].filter(Boolean).join(' · '))
        + (p.was ? `<p class="was">Was: ${esc(p.was)}</p>` : '') + (p.people && p.people.length ? `<dl><dt>People</dt><dd>${p.people.map(esc).join('<br>')}</dd></dl>` : '') + (p.note ? `<p>${esc(p.note)}</p>` : '')
        + (model ? this.modelBlock(model) : '') + this.distBlock({ kind: 'place', id: p.id, at: p.at });
    } else if (t.kind === 'person') {
      const h = D.people.find(x => x.name === t.name); if (!h) return; at = h.home.at;
      const mates = D.people.filter(x => x !== h && x.home && x.home.addr === h.home.addr).map(x => x.name);
      const model = this.app.models.items.find(m => m.kind === 'home' && (m.residents || []).includes(h.name));
      html = `<div class="top"><h2 class="${h.group === 'The Nine' ? 'nine' : ''}" style="${h.color ? `--c:${h.color}` : ''}">${esc(h.name)}</h2><div class="addr">${esc(h.group || '')}${h.role ? ' · ' + esc(h.role) : ''}</div></div>`
        + `<div class="body"><dl><dt>Home</dt><dd>${esc(h.home.addr || '')}${h.home.note ? `<br><span class="mu">${esc(h.home.note)}</span>` : ''}</dd><dt>Status</dt><dd><span class="chip ${chipCls(h.home.status)}">${esc(STATUS[h.home.status] || h.home.status || '')}</span></dd>${mates.length ? `<dt>Lives with</dt><dd>${mates.map(n => `<a data-open="person:${esc(n)}">${esc(n)}</a>`).join(', ')}</dd>` : ''}${h.later ? `<dt>Later</dt><dd>${esc(typeof h.later === 'string' ? h.later : h.later.addr || '')}</dd>` : ''}</dl>`
        + (model ? this.modelBlock(model) : '') + this.distBlock({ kind: 'home', name: h.name, at: h.home.at }) + '</div>';
    } else if (t.kind === 'street') {
      const s = D.streets.get(t.name); if (!s) return; const r = D.roads[s.roads[0]]; const k = Math.floor(r.pts.length / 4) * 2; at = [r.pts[k], r.pts[k + 1]];
      const nums = D.buildings.filter(b => b.street === t.name && b.num).map(b => b.num);
      html = this.cardHead(t.name, null, `${cap(s.cls)} road · ${fmtDist(s.len, this.app.units)} long`) + `<div class="body"><dl>${nums.length ? `<dt>Numbers</dt><dd>${Math.min(...nums)} to ${Math.max(...nums)} (${nums.length} addresses)</dd>` : ''}${D.bridges && D.bridges.some(b => b.road.name === t.name) ? '<dt>Bridge</dt><dd>Yes</dd>' : ''}</dl></div>`;
    }
    if (!html) return;
    this.showCard(html); if (fly && at) this.flyTo(at, t.kind === 'street' ? 900 : 300); this.mark(at);
    this.saveHash();
  }
  openModel(it) { if (it.kind === 'home') { const h = this.D.people.find(p => (it.residents || []).includes(p.name) && p.group === 'The Nine') || this.D.people.find(p => (it.residents || []).includes(p.name)); if (h) { this.open({ kind: 'person', name: h.name }, false); return; } } const p = this.D.places.find(x => x.id === it.id); if (p) this.open({ kind: 'place', id: p.id }, false); }
  openBuilding(b, at) {
    if (!b) return; const u = this.app.units, D = this.D;
    const nr = nearestRoad(D, b.cx, b.cy, 200, r => !!r.name);
    const qa = D.qa && D.qa.fixes; const moved = qa && (qa.replace_buildings || []).find(r => r.i === b.i);
    const title = b.num ? `${b.num} ${b.street}` : KIND_NAMES[b.kind] || cap(b.kind);
    const html = this.cardHead(title, b.added ? 'qa' : null, b.num ? (KIND_NAMES[b.kind] || cap(b.kind)) : 'No street number in the Atlas')
      + `<div class="body"><dl><dt>Footprint</dt><dd>${dims(b.w, b.d, u)}</dd><dt>Height</dt><dd>${u === 'metric' ? b.h.toFixed(1) + ' m' : Math.round(b.h * 3.28084) + ' ft'}</dd>${nr ? `<dt>Street</dt><dd>${esc(nr.road.name)}, ${fmtDist(nr.d, u)} to its center line</dd>` : ''}<dt>Center</dt><dd>${Math.round(b.cx)} E, ${Math.round(b.cy)} N</dd><dt>From the square</dt><dd>${fmtDist(Math.hypot(b.cx, b.cy), u)} straight</dd>${moved ? `<dt>Map check</dt><dd>${esc(moved.why || 'Adjusted to sit square and clear of roads')}</dd>` : ''}${b.added ? `<dt>Map check</dt><dd>${esc(b.why || 'Added by the map check')}</dd>` : ''}</dl>`
      + `<div class="acts"><button data-measure="${b.cx},${b.cy}">Measure from here</button></div>` + this.distBlock({ kind: 'spot', at: [b.cx, b.cy] }) + '</div>';
    this.sel = null; this.showCard(html); this.mark([b.cx, b.cy]);
  }
  openSpot(at) {
    const u = this.app.units, a = nearestAddress(this.D, at[0], at[1], 120);
    const html = this.cardHead(`${Math.round(at[0])} E, ${Math.round(at[1])} N`, null, a ? `Near ${a.b.num} ${a.b.street}` : 'Open ground') + `<div class="body"><dl><dt>From the square</dt><dd>${fmtDist(Math.hypot(at[0], at[1]), u)} straight</dd></dl><div class="acts"><button data-measure="${at[0]},${at[1]}">Measure from here</button></div>${this.distBlock({ kind: 'spot', at })}</div>`;
    this.sel = null; this.showCard(html); this.mark(at);
  }
  cardHead(name, status, sub) { return `<div class="top"><h2>${esc(name)}</h2>${status ? `<span class="chip ${chipCls(status)}">${esc(STATUS[status] || status)}</span>` : ''}<div class="addr">${esc(sub || '')}</div></div>`; }
  modelBlock(m) {
    return `<figure class="render">${m.render ? `<img src="${m.render}" alt="${esc(m.name)}, rendered in Blender" loading="lazy">` : ''}<figcaption>${esc(m.style || '')}${m.stories ? ` · ${m.stories} stories` : ''}${m.ridge ? ` · ridge ${this.app.units === 'metric' ? m.ridge.toFixed(1) + ' m' : Math.round(m.ridge * 3.28084) + ' ft'}` : ''}. <a href="homes.html#${m.id}" target="_blank" rel="noopener">Open the 3D model</a></figcaption></figure>`;
  }
  showCard(html) { $('cardBody').innerHTML = html; $('card').classList.remove('hidden'); $('cardBody').scrollTop = 0; }
  closeCard() { $('card').classList.add('hidden'); this.ring.visible = false; this.sel = null; this.saveHash(); }
  mark(at) { const cd = this.app.camera.position.distanceTo(this.app.controls.target); this.ring.position.set(at[0], 0.5, -at[1]); const s = 14; this.ring.scale.setScalar(s); this.ring.visible = true; void cd; }

  // ------------------------------------------------------------ distances
  useDistances(d) {
    this.dist = d; this.dIdx = new Map(d.points.map((p, i) => [p.key, i]));
    if (this.sel) this.open(this.sel, false);
  }
  keyOf(t) { return t.kind === 'place' ? 'place:' + t.id : t.kind === 'home' ? 'home:' + t.name : null; }
  rowsFrom(t) {
    // returns [{name, key, at, straight, road, drive, kind, color}]
    const d = this.dist, u = []; if (!d) return null;
    const k = this.keyOf(t), i = k != null ? this.dIdx.get(k) : undefined;
    if (i === undefined) return null;
    d.points.forEach((p, j) => { if (j === i) return; u.push({ name: p.name, key: p.key, at: p.at, kind: p.kind, group: p.group, straight: d.straight_m[i][j], road: d.road_m[i][j], drive: d.drive_s[i][j] }); });
    return u;
  }
  distBlock(t) {
    const u = this.app.units, rows = this.rowsFrom(t);
    const pick = [];
    const nine = NINE_ORDER.map(n => this.D.people.find(p => p.name === n)).filter(Boolean);
    if (rows) {
      for (const h of nine) { const r = rows.find(r => r.key === 'home:' + h.name); if (r) pick.push({ ...r, label: h.name, color: h.color }); }
      for (const [id, nm] of KEY_PLACES) { const r = rows.find(r => r.key === 'place:' + id); if (r) pick.push({ ...r, label: nm }); }
    } else {
      for (const h of nine) if (h.home && h.home.at) pick.push({ label: h.name, color: h.color, straight: Math.hypot(h.home.at[0] - t.at[0], h.home.at[1] - t.at[1]) });
      for (const [id, nm] of KEY_PLACES) { const p = this.D.places.find(x => x.id === id); if (p && p.at) pick.push({ label: nm, straight: Math.hypot(p.at[0] - t.at[0], p.at[1] - t.at[1]) }); }
    }
    const seen = new Set(); const list = pick.filter(r => r.straight > 1 && !seen.has(r.label) && seen.add(r.label));
    if (!list.length) return '';
    return `<h3>How far from here</h3><table class="dt"><thead><tr><th></th><th>By road</th><th>Drive</th><th>Straight</th></tr></thead><tbody>${list.map(r => `<tr><td>${r.color ? `<span class="sw" style="background:${r.color}"></span>` : ''}${esc(r.label)}</td><td>${r.road != null ? fmtDist(r.road, u) : '–'}</td><td>${r.drive != null ? fmtTime(r.drive) : '–'}</td><td>${fmtDist(r.straight, u)}</td></tr>`).join('')}</tbody></table>${rows ? '<div class="acts"><button data-dist="1">Distances to everything</button></div>' : '<p class="mu">Road distances appear when the router has loaded.</p>'}`;
  }
  renderDist() {
    const el = $('distBody'); if (!el || $('dist').classList.contains('hidden')) return;
    const u = this.app.units, d = this.dist;
    if (!d) { el.innerHTML = '<p class="hint">The distance table (data/distances.json) is not available yet.</p>'; return; }
    const tab = this.dTab || 'from';
    if (tab === 'nine') {
      const nine = NINE_ORDER.map(n => this.dIdx.get('home:' + n));
      const first = n => n.split(' ')[0];
      el.innerHTML = `<p class="hint">Road distance and drive time between the Nine's homes. Hover a cell for the straight-line distance.</p><div class="mx"><table class="dt mxt"><thead><tr><th></th>${NINE_ORDER.map(n => `<th>${first(n)}</th>`).join('')}</tr></thead><tbody>${NINE_ORDER.map((n, a) => `<tr><th>${first(n)}</th>${NINE_ORDER.map((m, b) => { const i = nine[a], j = nine[b]; if (i == null || j == null) return '<td>–</td>'; if (a === b) return '<td class="self">·</td>'; return `<td title="${fmtDist(d.straight_m[i][j], u)} straight">${fmtDist(d.road_m[i][j], u)}<span>${fmtTime(d.drive_s[i][j])}</span></td>`; }).join('')}</tr>`).join('')}</tbody></table></div>`;
      return;
    }
    const origin = this.distOrigin || this.sel || { kind: 'place', id: 'courthouse-square' };
    const t = origin.kind === 'person' ? { kind: 'home', name: origin.name } : origin;
    const rows = this.rowsFrom(t) || [];
    const name = t.kind === 'home' ? t.name : (this.D.places.find(p => p.id === t.id) || {}).name || 'Courthouse Square';
    const f = this.dFilter || 'all';
    const shown = rows.filter(r => f === 'all' || (f === 'nine' ? r.group === 'The Nine' : f === 'homes' ? r.kind === 'home' : r.kind === 'place')).sort((a, b) => a.road - b.road);
    el.innerHTML = `<p class="hint">From <b>${esc(name)}</b> to every place and home in the gazetteer, nearest first. Pick any card's “Distances to everything” to change the starting point.</p>
      <div class="filters">${['all', 'nine', 'places', 'homes'].map(k => `<button data-f="${k}" class="${k === f ? 'on' : ''}">${{ all: 'Everything', nine: 'The Nine', places: 'Places', homes: 'Homes' }[k]}</button>`).join('')}${LOCAL ? '<a class="dl" href="data/distances.csv" download>Download all (CSV)</a>' : `<a class="dl" href="${REPO_RAW}data/distances.csv" target="_blank" rel="noopener">Download all (CSV)</a>`}</div>
      <table class="dt"><thead><tr><th>To</th><th>By road</th><th>Drive</th><th>Straight</th></tr></thead><tbody>${shown.map(r => `<tr data-go="${r.at.join(',')}"><td>${esc(r.name)}</td><td>${r.road >= 0 ? fmtDist(r.road, u) : '–'}</td><td>${r.drive >= 0 ? fmtTime(r.drive) : '–'}</td><td>${fmtDist(r.straight, u)}</td></tr>`).join('')}</tbody></table>`;
    el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { this.dFilter = b.dataset.f; this.renderDist(); });
    el.querySelectorAll('[data-go]').forEach(r => r.onclick = () => { const [x, y] = r.dataset.go.split(',').map(Number); this.flyTo([x, y], 350); this.mark([x, y]); });
  }

  // ------------------------------------------------------------ map check (QA)
  renderQA() {
    const el = $('qaBody'), qa = this.D.qa;
    if (!qa) { el.innerHTML = '<p class="hint">No map check results (data/qa.json) yet.</p>'; return; }
    const s = qa.summary, f = this.qaFilter || 'flagged';
    const rows = Object.entries(s.by_type).map(([k, v]) => `<tr><td>${esc(k.replace(/-/g, ' '))}</td><td>${v.found}</td><td>${v.fixed}</td><td>${v.found - v.fixed}</td></tr>`).join('');
    const list = qa.issues.filter(i => f === 'all' || (f === 'flagged' ? i.action !== 'fixed' : i.type === f)).slice(0, 400);
    el.innerHTML = `<p class="hint">Every building, road, place and label in the Atlas was checked for stray or misplaced pieces. Fixes are applied on this map without changing the Atlas files; flagged items need your decision. The full report is in docs/QA-REPORT.md.</p>
      <div class="qasum"><div><b>${s.issues.toLocaleString()}</b><span>found</span></div><div><b>${s.fixed.toLocaleString()}</b><span>fixed</span></div><div><b>${s.flagged}</b><span>for you</span></div></div>
      <table class="dt"><thead><tr><th>Check</th><th>Found</th><th>Fixed</th><th>Open</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="filters"><button data-q="flagged" class="${f === 'flagged' ? 'on' : ''}">For your decision</button>${Object.keys(s.by_type).filter(k => s.by_type[k].fixed).slice(0, 5).map(k => `<button data-q="${k}" class="${f === k ? 'on' : ''}">${esc(k.replace(/-/g, ' '))}</button>`).join('')}</div>
      <ol class="issues">${list.map(i => `<li data-at="${(i.at || []).join(',')}"><span class="chip ${i.action === 'fixed' ? 'canon' : 'new'}">${i.action === 'fixed' ? 'fixed' : 'flagged'}</span> ${esc(i.detail)}</li>`).join('')}</ol>`;
    el.querySelectorAll('[data-q]').forEach(b => b.onclick = () => { this.qaFilter = b.dataset.q; this.renderQA(); });
    el.querySelectorAll('[data-at]').forEach(li => li.onclick = () => { const v = li.dataset.at.split(',').map(Number); if (v.length === 2 && isFinite(v[0])) { this.flyTo(v, 260); this.mark(v); } });
  }

  // ------------------------------------------------------------ URL state
  saveHash(quiet) {
    if (this.anim || this.street) return;
    const v = this.app.getView(); const s = this.sel ? (this.sel.kind === 'person' ? 'p=' + encodeURIComponent(this.sel.name) : this.sel.kind === 'place' ? 'pl=' + this.sel.id : 's=' + encodeURIComponent(this.sel.name)) : '';
    const h = `#v=${v}&st=${this.app.style}${s ? '&' + s : ''}`;
    if (h !== location.hash) { this._own = h; history.replaceState(null, '', h); }
    void quiet;
  }
  fromHash(first) {
    if (location.hash === this._own) return;
    let h = location.hash.slice(1);
    // the homes gallery leaves its "See it on the map" view in storage too, for hosts that drop #state from links
    if (first) { const g = localGet('wp-goto'); if (g) { localSet('wp-goto', ''); if (!h) h = g; } }
    const P = new URLSearchParams(h);
    if (P.get('v')) this.app.applyView(P.get('v'));
    if (P.get('st')) { this.app.setStyle(+P.get('st')); this.syncSeg(); }
    if (P.get('p')) this.open({ kind: 'person', name: P.get('p') }, !P.get('v'));
    else if (P.get('pl')) this.open({ kind: 'place', id: P.get('pl') }, !P.get('v'));
    void first;
  }
}

function chipCls(s) { return s === 'canon2' || s === 'locked' || s === 'confirmed' ? 'canon' : s === 'proposed' || s === 'qa' ? 'new' : ''; }
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : ''; }
function clock(h) { const H = Math.floor(h), M = Math.round((h - H) * 60); const ap = H >= 12 ? 'pm' : 'am'; return `${((H + 11) % 12) + 1}:${String(M).padStart(2, '0')} ${ap}`; }
function dims(w, d, u) { return u === 'metric' ? `${w.toFixed(1)} × ${d.toFixed(1)} m` : `${Math.round(w * 3.28084)} × ${Math.round(d * 3.28084)} ft`; }
const REPO_RAW = 'https://github.com/isabelleereinhardt-rgb/MOCKUPOFWESTPORT/raw/claude/friendly-faraday-qe6vvd/';
const LOCAL = location.protocol === 'file:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
function localGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function localSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
