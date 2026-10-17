"""Westport landmarks (ASSET-SPEC "Landmarks"): water tower, pier bar, Williams Funeral Home,
Chadwick's, the Lindon County Courthouse and the Carnegie Library.

    WP_TEX_DIR=/tmp/somewhere python3 tools/blender/landmarks/build.py            # GLBs + JSON + renders
    python3 tools/blender/landmarks/build.py --only courthouse --no-render         # one model
    WP_SAMPLES=24 WP_TILE=320x200 python3 tools/blender/landmarks/build.py --preview  # quick renders to WP_TEX_DIR

Placement comes from data/wpdata.json + data/gaz.json with the data/qa.json fixes applied
(replace_buildings, remove_buildings, move_places, road_snaps, add_roads), computed the same way as
tools/qa/site-specs.py: front = the footprint edge facing the nearest NAMED street.
Every model: meters, +Z up, front faces -Y, origin = Atlas footprint center at grade (z = 0).
The only text on any model is the water tower's canon lettering, WESTPORT / FOUNDED 1625.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
sys.path.insert(0, os.path.join(HERE, '..', 'archetypes'))
import wp  # noqa: E402
import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, Matrix  # noqa: E402
from PIL import Image  # noqa: E402
from misc import (G, to_object, box, cbox, ngon, lathe, bar, Fr, sides, fq, fbox, wall, window, door,  # noqa: E402
                  body, roof_gable, roof_hip, railing, small_normal, ZF)

REPO = wp.REPO
OUT = os.path.join(REPO, 'models', 'landmarks')
RENDERS = os.path.join(REPO, 'renders')
ARGS = sys.argv[1:]
PREVIEW = '--preview' in ARGS
SAMPLES = int(os.environ.get('WP_SAMPLES', 24 if PREVIEW else 96))
TEX = wp.TEX_DIR

# ============================================================================ placement (Atlas)

BK = ['house', 'duplex', 'mobile', 'shed', 'barn', 'shop', 'office', 'tower', 'deck', 'retail', 'apartments', 'townhouse', 'clubhouse',
      'church', 'school', 'gym', 'stands', 'hospital', 'industrial', 'civic', 'motel', 'hotel']
CLS = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway']
HALF = {'trunk': 7.5, 'primary': 6.5, 'secondary': 5.5, 'tertiary': 4.5, 'residential': 3.75, 'service': 2.75, 'track': 2, 'path': 1, 'motorway': 9}


def atlas():
    w = json.load(open(os.path.join(REPO, 'data', 'wpdata.json')))
    g = json.load(open(os.path.join(REPO, 'data', 'gaz.json')))
    q = json.load(open(os.path.join(REPO, 'data', 'qa.json')))['fixes']
    names = w['names']
    B = {}
    for i, b in enumerate(w['b']):
        p = [v / 2 for v in b[2:]]
        B[i] = dict(kind=BK[b[0]], h=b[1] / 2, pts=list(zip(p[0::2], p[1::2])))
    for i in q.get('remove_buildings', []):
        B.pop(i, None)
    for r in q.get('replace_buildings', []):
        p = r['poly']; B[r['i']]['pts'] = list(zip(p[0::2], p[1::2]))
    for b in B.values():
        b['c'] = (sum(x for x, y in b['pts']) / 4, sum(y for x, y in b['pts']) / 4)
    roads = [[r[0], r[1], r[2], list(r[3])] for r in w['roads']]
    for s in q.get('road_snaps', []):
        roads[s['road']][3][2 * s['vertex']] = s['to'][0]; roads[s['road']][3][2 * s['vertex'] + 1] = s['to'][1]
    for a in q.get('add_roads', []):
        roads.append([names.index(a['name']) if a['name'] in names else -1, CLS.index(a['cls']), a['bridge'], a['pts']])
    places = {p['id']: p['at'] for p in g['places']}
    for m in q.get('move_places', []):
        if m['id'] in places:
            places[m['id']] = m['at']
    return w, names, B, roads, places


def near_named_road(roads, names, x, y):
    best = None
    for r in roads:
        if r[0] < 0:
            continue
        p = r[3]
        for i in range(0, len(p) - 2, 2):
            x1, y1, x2, y2 = p[i:i + 4]
            dx, dy = x2 - x1, y2 - y1; L = dx * dx + dy * dy
            t = 0 if L == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L))
            px, py = x1 + t * dx, y1 + t * dy; d = math.hypot(x - px, y - py)
            if best is None or d < best[0]:
                best = (d, names[r[0]], CLS[r[1]], (px, py))
    return best


def site(A, bi):
    w, names, B, roads, places = A
    b = B[bi]; c = b['c']; pts = b['pts']
    d, nm, cls, foot = near_named_road(roads, names, *c)
    fx, fy = (foot[0] - c[0]) / d, (foot[1] - c[1]) / d
    best = None
    for i in range(4):
        a, bb = pts[i], pts[(i + 1) % 4]
        mx, my = (a[0] + bb[0]) / 2 - c[0], (a[1] + bb[1]) / 2 - c[1]; L = math.hypot(mx, my)
        dot = (mx * fx + my * fy) / L
        if best is None or dot > best[0]:
            best = (dot, i, math.dist(a, bb), (mx / L, my / L))
    _, ei, W, nrm = best
    D = math.dist(pts[(ei + 1) % 4], pts[(ei + 2) % 4])
    return dict(building_index=bi, center_atlas=[round(c[0], 2), round(c[1], 2)],
                front_heading_deg_atlas=round(math.degrees(math.atan2(nrm[1], nrm[0])), 1), footprint_m=[round(W, 2), round(D, 2)],
                atlas_kind=b['kind'], atlas_height_m=b['h'], street=nm, street_class=cls,
                curb_line_local_y=round(-(d - HALF[cls]), 2))


def nearest_building(A, x, y, maxd=30):
    B = A[2]
    best = None
    for i, b in B.items():
        d = math.hypot(b['c'][0] - x, b['c'][1] - y)
        if d < maxd and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


# ============================================================================ textures and materials

def tex_painted(key, base, n=1024, tile=3.0, seams=(2.4, 3.0), streak=0.08, seed=11):
    """Painted steel plate: faint weld seams, mottled paint and soft vertical grime streaks."""
    rng = np.random.default_rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    nz = wp._noise(n, 6 * tile, rng, 5)
    st = wp._noise(n, 3 * tile, np.random.default_rng(seed + 1), 3)
    st = np.repeat(st[:1, :], n, 0) * 0.6 + st * 0.4       # vertical streaks
    sh, sw = seams
    rows = (y // sh).astype(int)
    seam = ((y % sh) < 0.012) | (((x + (rows % 2) * sw / 2) % sw) < 0.012)
    c = wp._rgb(base)
    alb = c[None, None, :] * (0.95 + 0.07 * nz[..., None]) * (1 - streak * np.clip(st[..., None] - 0.45, 0, 1) * 2)
    alb = np.where(seam[..., None], alb * 0.9, alb)
    h = nz * 0.15 + seam * 0.6
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 1.2), key + '_n'), tile


def tex_paint_over(src, key, white='#ece9e2', keep=0.22):
    """Painted brick: lift a brick albedo toward a paint color, keeping a little of the joints and texture."""
    alb, nrm, tile = src
    a = np.asarray(Image.open(alb)).astype(np.float32) / 255
    lum = a.mean(-1, keepdims=True)
    out = wp._rgb(white)[None, None, :] * (1 - keep + keep * lum / max(1e-3, float(lum.mean())))
    return wp._save(out, key), nrm, tile


def tex_checker(key, a='#e9e4d8', b='#1d1d1f', n=512, tile=0.6):
    rng = np.random.default_rng(3)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    s = 0.3
    chk = (((x // s) + (y // s)) % 2).astype(bool)
    nz = wp._noise(n, 8, rng, 3)
    alb = np.where(chk[..., None], wp._rgb(b), wp._rgb(a)) * (0.94 + 0.08 * nz[..., None])
    return wp._save(alb, key), None, tile


def tex_canvas(key, color, n=512, tile=1.0, stripes=None):
    rng = np.random.default_rng(9)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    weave = (np.sin(x * 900) * np.sin(y * 900)) * 0.5 + 0.5
    nz = wp._noise(n, 6 * tile, rng, 4)
    c = np.broadcast_to(wp._rgb(color), (n, n, 3)).copy()
    if stripes:
        band = ((x / stripes[0]).astype(int) % 2 == 1)
        c[band] = wp._rgb(stripes[1])
    alb = c * (0.88 + 0.06 * weave[..., None] + 0.1 * nz[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(weave * 0.2, 1.0), key + '_n'), tile


def retile(tex, tile):
    return tex[0], tex[1], tile


MATS = {}


def M(name):
    """Landmark material library (created on demand in the current scene)."""
    if name in MATS and MATS[name].name in bpy.data.materials:
        return MATS[name]
    f = {
        'Trim': lambda: wp.mat('Trim', '#efede6', rough=0.5),
        'TrimStone': lambda: wp.mat('TrimStone', '#ffffff', rough=0.8, tex=retile(small_normal(wp.tex_ground('lm_lime', kind='stucco', color='#ddd6c6', n=1024, tile=2.0, seed=41)), 2.0)),
        'Glass': lambda: wp.glass('Glass', tint='#232a30'),
        'ShopGlass': lambda: wp.mat('ShopGlass', '#9fb4bd', rough=0.03, alpha=0.22, double_sided=True),
        'Shutter': lambda: wp.mat('Shutter', '#1c1e20', rough=0.45),
        'DoorBlack': lambda: wp.mat('DoorBlack', '#15181a', rough=0.3),
        'DoorWood': lambda: wp.mat('DoorWood', '#ffffff', rough=0.5, tex=wp.tex_wood('lm_doorwood', color='#5a3a24', n=512, tile=1.0, board=0.18, seed=42)),
        'BrickRed': lambda: wp.mat('BrickRed', '#ffffff', rough=0.85, tex=small_normal(wp.tex_brick('lm_brick_red', color='#8a4532', mortar='#bdb3a2', n=1024, tile=1.0, seed=43))),
        'BrickBuff': lambda: wp.mat('BrickBuff', '#ffffff', rough=0.85, tex=small_normal(wp.tex_brick('lm_brick_buff', color='#b98f63', mortar='#cfc4b0', n=1024, tile=1.0, seed=44, var=0.08))),
        'BrickPainted': lambda: wp.mat('BrickPainted', '#ffffff', rough=0.7, normal_strength=0.7,
                                       tex=small_normal(tex_paint_over(wp.tex_brick('lm_brick_tmp', color='#9a6a55', mortar='#d8d2c6', n=1024, tile=1.0, seed=45, var=0.05), 'lm_brick_painted'))),
        'Ashlar': lambda: wp.mat('Ashlar', '#ffffff', rough=0.85, tex=retile(small_normal(wp.tex_brick('lm_ashlar', color='#cbc3b1', mortar='#b3ab99', n=1024, tile=1.0, seed=46, var=0.05)), 3.0)),
        'Slate': lambda: wp.mat('Slate', '#ffffff', rough=0.75, tex=small_normal(wp.tex_shingles('lm_slate', color='#4b5057', n=1024, tile=2.0, seed=47, kind='slate'))),
        'Copper': lambda: wp.mat('Copper', '#ffffff', rough=0.55, metal=0.2, tex=small_normal(wp.tex_metal('lm_verdigris', color='#6f9b88', n=512, tile=1.5, seam=True, seed=48))),
        'Concrete': lambda: wp.mat('Concrete', '#ffffff', rough=0.9, tex=small_normal(wp.tex_ground('lm_concrete', kind='concrete', n=1024, tile=3.0, seed=49))),
        'Block': lambda: wp.mat('Block', '#ffffff', rough=0.85, tex=small_normal(wp.tex_ground('lm_block', kind='stucco', color='#e6e0d2', n=1024, tile=2.0, seed=50))),
        'TowerPaint': lambda: wp.mat('TowerPaint', '#ffffff', rough=0.5, metal=0.1, tex=tex_painted('lm_tower_paint', '#a7b8c4')),
        'Lettering': lambda: wp.mat('Lettering', '#1d2742', rough=0.4, metal=0.2),
        'Steel': lambda: wp.mat('Steel', '#7d8388', rough=0.5, metal=0.7),
        'Stainless': lambda: wp.mat('Stainless', '#ffffff', rough=0.22, metal=1.0, tex=wp.tex_metal('lm_stainless', color='#c9ccce', n=512, tile=0.6, rib=0.05, seed=51)),
        'Enamel': lambda: wp.mat('Enamel', '#efe7d2', rough=0.25),
        'EnamelRed': lambda: wp.mat('EnamelRed', '#8f1f24', rough=0.3),
        'Awning': lambda: wp.mat('Awning', '#ffffff', rough=0.9, tex=tex_canvas('lm_awning', '#7d1a1e')),
        'Checker': lambda: wp.mat('Checker', '#ffffff', rough=0.35, tex=tex_checker('lm_checker')),
        'Interior': lambda: wp.mat('Interior', '#d9cdb4', rough=0.8),
        'Counter': lambda: wp.mat('Counter', '#c94a3f', rough=0.35),
        'Vinyl': lambda: wp.mat('Vinyl', '#9a2125', rough=0.4),
        'Lamp': lambda: wp.mat('Lamp', '#fff1d6', rough=0.4, emission=('#ffdcaa', 6.0)),
        'Bulb': lambda: wp.mat('Bulb', '#fff3dc', rough=0.3, emission=('#ffcf8a', 14.0)),
        'Wire': lambda: wp.mat('Wire', '#151515', rough=0.6),
        'WoodWeathered': lambda: wp.mat('WoodWeathered', '#ffffff', rough=0.9, tex=small_normal(wp.tex_wood('lm_wood_siding', color='#7d6b58', n=1024, tile=1.2, board=0.2, weathered=0.55, seed=52))),
        'DeckWood': lambda: wp.mat('DeckWood', '#ffffff', rough=0.9, tex=small_normal(wp.tex_wood('lm_deck', color='#86735e', n=1024, tile=1.2, board=0.14, weathered=0.6, seed=53))),
        'Piling': lambda: wp.mat('Piling', '#ffffff', rough=0.95, tex=wp.tex_wood('lm_piling', color='#5c5044', n=512, tile=1.0, board=0.3, weathered=0.4, seed=54)),
        'MetalRoof': lambda: wp.mat('MetalRoof', '#ffffff', rough=0.5, metal=0.6, tex=small_normal(wp.tex_metal('lm_roof_galv', color='#a2a8ab', rust=0.25, n=1024, tile=1.5, seed=55))),
        'PaintedWood': lambda: wp.mat('PaintedWood', '#ffffff', rough=0.7, tex=wp.tex_wood('lm_painted_wood', color='#3f5a5e', n=512, tile=1.0, board=0.15, weathered=0.25, seed=56)),
        'Bronze': lambda: wp.mat('Bronze', '#2a2622', rough=0.4, metal=0.8),
        'ClockFace': lambda: wp.mat('ClockFace', '#f3efe2', rough=0.4),
        'Roofing': lambda: wp.mat('Roofing', '#ffffff', rough=0.9, tex=small_normal(wp.tex_ground('lm_roofing', kind='gravel', color='#8d8a84', n=512, tile=2.0, seed=57))),
        'HVAC': lambda: wp.mat('HVAC', '#b9bcbd', rough=0.5, metal=0.4),
    }[name]
    MATS[name] = f()
    return MATS[name]


class Lib(dict):
    def __missing__(self, k):
        v = M(k); self[k] = v
        return v


# ============================================================================ helpers

def column(g, x, y, z0, z1, r, mat='Trim', n=14, order='tuscan'):
    """Classical column with base, entasis shaft, echinus and square abacus."""
    h = z1 - z0
    base = 0.12 * h / 9
    prof = [(r * 1.3, z0), (r * 1.3, z0 + 0.12), (r * 1.18, z0 + 0.16), (r * 1.18, z0 + 0.26), (r * 1.02, z0 + 0.3)]
    zs = z0 + 0.3; ze = z1 - 0.45
    for k in range(1, 6):
        t = k / 5
        rr = r * (1.0 - 0.14 * max(0, (t - 0.33) / 0.67) ** 1.4)
        prof.append((rr, zs + (ze - zs) * t))
    prof += [(r * 0.92, ze + 0.06), (r * 0.98, ze + 0.12), (r * 1.15, ze + 0.27)]
    lathe(g, mat, x, y, prof, n=n, cap_top=True)
    cbox(g, mat, x, y, r * 2.5, r * 2.5, ze + 0.27, z1, skip='b')
    cbox(g, mat, x, y, r * 2.7, r * 2.7, z0 - 0.02, z0 + 0.1, skip='b') if order == 'plinth' else None


def pediment(g, x0, x1, y_front, y_back, z, pitch, rmat, tymp='Trim', T='Trim', ov=0.25):
    """Gable pediment: raking cornices, tympanum on the front, roof slopes back to y_back."""
    tn = math.tan(math.radians(pitch))
    hw = (x1 - x0) / 2; cx = (x0 + x1) / 2
    apex = z + hw * tn
    g.poly([(x0, y_front, z), (x1, y_front, z), (cx, y_front, apex)], tymp, (0, -1, 0))
    th = 0.35
    for s in (-1, 1):
        xe = cx + s * (hw + ov)
        ze = z - ov * tn
        g.poly([(xe, y_front - ov, ze + th), (cx, y_front - ov, apex + th), (cx, y_back, apex + th), (xe, y_back, ze + th)], rmat, (s, 0, 1 / tn))
        g.poly([(xe, y_front - ov, ze), (cx, y_front - ov, apex), (cx, y_front - ov, apex + th), (xe, y_front - ov, ze + th)], T, (0, -1, 0))
        g.poly([(xe, y_front - ov, ze), (cx, y_front - ov, apex), (cx, y_back, apex), (xe, y_back, ze)], T, (s * 0, 0, -1))
        g.poly([(xe, y_front - ov, ze), (xe, y_back, ze), (xe, y_back, ze + th), (xe, y_front - ov, ze + th)], T, (s, 0, 0))
    # horizontal cornice under the tympanum, and the back of the gable closed
    box(g, T, x0 - 0.1, x1 + 0.1, y_front - 0.25, y_front + 0.02, z - 0.05, z + 0.12, skip='')
    g.poly([(cx - hw - ov, y_back, z - ov * tn), (cx + hw + ov, y_back, z - ov * tn), (cx, y_back, apex + th)], T, (0, 1, 0))
    return apex + th


def steps_y(g, mat, x0, x1, y_top, z_top, n, tread=0.3, grow=0.0):
    """n risers from grade up to z_top, the top step meeting y_top, descending toward -y."""
    rh = z_top / n
    for i in range(n):
        zt = z_top - i * rh
        box(g, mat, x0 - i * grow, x1 + i * grow, y_top - (i + 1) * tread, y_top, ZF, zt, skip='bn')


def lantern(g, F, u, z, s=0.22):
    """Wall lantern: black box with a lit glass body."""
    fbox(g, F, 'Shutter', u - 0.05, u + 0.05, z - 0.25, z + 0.25, 0, 0.12)
    fbox(g, F, 'Lamp', u - s / 2, u + s / 2, z - 0.18, z + 0.18, 0.12, 0.12 + s)
    fbox(g, F, 'Shutter', u - s / 2 - 0.03, u + s / 2 + 0.03, z + 0.18, z + 0.24, 0.1, 0.14 + s)


def finish(lid, objs, meta, extra=None):
    objs = [o for o in objs if o is not None]
    wp.finalize(objs)
    path = os.path.join(OUT, lid + '.glb')
    wp.export_glb(path, objs)
    xs, ys, zs = [], [], []
    for o in objs:
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            xs.append(p.x); ys.append(p.y); zs.append(p.z)
    meta = dict(meta)
    meta['triangles'] = wp.tri_count(objs)
    meta['size_kb'] = round(os.path.getsize(path) / 1024)
    meta['bbox_local_m'] = [round(min(xs), 2), round(max(xs), 2), round(min(ys), 2), round(max(ys), 2), round(min(zs), 2), round(max(zs), 2)]
    meta['height_m'] = meta.get('height_m') or round(max(zs), 2)
    if extra:
        meta.update(extra)
    with open(os.path.join(OUT, lid + '.json'), 'w') as fh:
        json.dump(meta, fh, indent=1)
    print(lid, meta['triangles'], 'tris', meta['size_kb'], 'KB', meta['bbox_local_m'])
    return meta


def soup_obj(g, name, L):
    return to_object(g, name, L)


# ============================================================================ water tower

def text_mesh(txt, size, font_path, R, zc, theta0=0.0, depth=0.025, off=0.02, step=0.2):
    """Real lettering: Blender text -> mesh, sliced into narrow strips and wrapped onto a cylinder of radius R
    so every letter follows the shell. theta0 = angle of the text center (0 = facing -Y)."""
    cu = bpy.data.curves.new('txt', 'FONT')
    cu.body = txt
    cu.font = bpy.data.fonts.load(font_path, check_existing=True)
    cu.size = size
    cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    cu.extrude = depth / 2
    cu.resolution_u = 4
    cu.fill_mode = 'BOTH'
    ob = bpy.data.objects.new('txt', cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob); bpy.data.curves.remove(cu)
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    xs = [v.co.x for v in bm.verts]
    x = min(xs) + step
    while x < max(xs):
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(x, 0, 0), plane_no=(1, 0, 0))
        x += step
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    for v in bm.verts:
        tx, ty, tz = v.co
        r = R + off + depth / 2 + tz
        th = theta0 + tx / R
        v.co = Vector((r * math.sin(th), -r * math.cos(th), zc + ty))
    bm.normal_update()
    bm.to_mesh(me); bm.free()
    return me


def build_water_tower(A):
    wp.reset(); L = Lib()
    pt = A[4]['water-tower']
    bi = nearest_building(A, *pt, maxd=6)
    s = site(A, bi) if bi is not None else None
    g = G()
    R = 6.5                    # tank shell radius (13 m diameter)
    zb, zs0, zs1 = 30.6, 33.4, 39.4    # bottom of the lower head, shell bottom, shell top
    # tank: ellipsoidal bottom head, cylindrical shell, conical-ellipsoidal roof
    prof = []
    for k in range(7):
        a = math.pi / 2 * (1 - k / 6)
        prof.append((R * math.cos(a) if k else 0.0, zs0 - (zs0 - zb) * math.sin(a)))
    prof[0] = (0.0, zb)
    prof += [(R, zs1)]
    for k in range(1, 6):
        t = k / 5
        prof.append((R * (1 - t) ** 0.9 + 0.35 * t, zs1 + 3.4 * (1 - (1 - t) ** 1.6)))
    lathe(g, 'TowerPaint', 0, 0, [(0.001, zb)] + prof[1:], n=48)
    zroof = prof[-1][1]
    # roof vent / finial
    lathe(g, 'TowerPaint', 0, 0, [(0.6, zroof - 0.05), (0.6, zroof + 0.5), (0.85, zroof + 0.55), (0.85, zroof + 0.75), (0.2, zroof + 1.05), (0.06, zroof + 1.4), (0.12, zroof + 1.55), (0.0, zroof + 1.7)], n=16)
    # balcony at the shell bottom
    zbal = zs0 - 0.15
    lathe(g, 'TowerPaint', 0, 0, [(R - 0.05, zbal - 0.25), (R + 1.05, zbal - 0.25), (R + 1.05, zbal), (R - 0.05, zbal)], n=48, smooth=False, cap_top=False)
    nposts = 32
    for i in range(nposts):
        a = 2 * math.pi * i / nposts
        x, y = (R + 1.0) * math.cos(a), (R + 1.0) * math.sin(a)
        bar(g, 'TowerPaint', (x, y, zbal), (x, y, zbal + 1.1), 0.07)
    ring_top = [(R + 1.0, zbal + 1.06), (R + 1.0, zbal + 1.12)]
    lathe(g, 'TowerPaint', 0, 0, [(R + 0.96, zbal + 1.05), (R + 1.04, zbal + 1.05), (R + 1.04, zbal + 1.12), (R + 0.96, zbal + 1.12), (R + 0.96, zbal + 1.05)], n=48, smooth=False, cap_top=False)
    lathe(g, 'TowerPaint', 0, 0, [(R + 0.98, zbal + 0.55), (R + 1.02, zbal + 0.55), (R + 1.02, zbal + 0.6), (R + 0.98, zbal + 0.6), (R + 0.98, zbal + 0.55)], n=48, smooth=False, cap_top=False)
    # six battered tubular legs, footings, struts and rod bracing
    NL = 6; Rb, Rt = 8.2, R
    legs = []
    for i in range(NL):
        a = 2 * math.pi * (i + 0.5) / NL
        bot = Vector((Rb * math.cos(a), Rb * math.sin(a), 0.25)); top = Vector((Rt * math.cos(a), Rt * math.sin(a), zs0))
        legs.append((bot, top))
        bar(g, 'TowerPaint', bot, top + Vector((0, 0, 0.6)), 0.76, n=12, smooth=True)
        ngon(g, 'Concrete', bot.x, bot.y, 1.0, ZF, 0.25, n=12, caps='t')
        ngon(g, 'TowerPaint', bot.x, bot.y, 0.62, 0.25, 0.32, n=12, caps='t')
    levels = [0.0, 8.4, 16.8, 25.2, zs0 - 0.3]

    def at(i, z):
        b, t = legs[i % NL]
        return b + (t - b) * ((z - b.z) / (t.z - b.z))
    for li, z in enumerate(levels):
        for i in range(NL):
            if 0 < li < len(levels) - 1:
                bar(g, 'TowerPaint', at(i, z), at(i + 1, z), 0.34, n=8, smooth=True)
            if li < len(levels) - 1:
                z0 = max(z, 0.9); z1 = levels[li + 1]
                for (pa, pb) in ((at(i, z0), at(i + 1, z1)), (at(i + 1, z0), at(i, z1))):
                    bar(g, 'Steel', pa, pb, 0.06, n=4)
    # riser pipe and its base
    ngon(g, 'TowerPaint', 0, 0, 0.95, 0.3, zb + 0.2, n=16, caps='')
    ngon(g, 'Concrete', 0, 0, 1.8, ZF, 0.3, n=16, caps='t')
    lathe(g, 'TowerPaint', 0, 0, [(0.95, 0.3), (1.25, 0.3), (1.25, 1.2), (0.95, 1.5)], n=16, cap_top=False)
    # ladder up the front-right leg with a cage, and up the roof
    b, t = legs[NL - 1]
    d = (t - b).normalized(); side = d.cross(Vector((0, 0, 1))).normalized()
    out = Vector((b.x, b.y, 0)).normalized()
    for sgn in (-1, 1):
        bar(g, 'Steel', b + side * sgn * 0.22 + out * 0.55 + d * 3.0, t + side * sgn * 0.22 + out * 0.55 - d * 0.3, 0.06)
    nr = int(((t - b).length - 3.3) / 0.35)
    for k in range(nr):
        p = b + d * (3.0 + k * 0.35) + out * 0.55
        bar(g, 'Steel', p - side * 0.22, p + side * 0.22, 0.03)
    for k in range(0, nr, 3):
        p = b + d * (3.0 + k * 0.35) + out * 0.55
        if k * 0.35 > 2.5:
            pts = [p - side * 0.35, p - side * 0.35 + out * 0.7, p + side * 0.35 + out * 0.7, p + side * 0.35]
            for pa, pb in zip(pts, pts[1:]):
                bar(g, 'Steel', pa, pb, 0.04)
    aL = math.atan2(t.y, t.x)
    rp = [(R, zs1)] + prof[-5:]
    for sgn in (-1, 1):
        aa = aL + sgn * 0.04
        for (r0, z0), (r1, z1) in zip(rp, rp[1:]):
            if r1 < 0.8:
                break
            bar(g, 'Steel', ((r0 + 0.12) * math.cos(aa), (r0 + 0.12) * math.sin(aa), z0 + 0.12), ((r1 + 0.12) * math.cos(aa), (r1 + 0.12) * math.sin(aa), z1 + 0.12), 0.05)
    tank = soup_obj(g, 'WaterTower', L)
    # lettering: WESTPORT, and FOUNDED 1625 below in smaller letters (canon), front and back
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    if not os.path.exists(font):
        font = os.path.join(bpy.utils.system_resource('DATAFILES'), 'fonts', 'DejaVuSans.woff2')
    letters = []
    for th0 in (0.0, math.pi):
        for txt, size, zc in (('WESTPORT', 1.9, 37.65), ('FOUNDED 1625', 0.8, 35.85)):
            me = text_mesh(txt, size, font, R, zc, theta0=th0)
            o = bpy.data.objects.new('Lettering', me)
            bpy.context.scene.collection.objects.link(o)
            o.data.materials.append(L['Lettering'])
            letters.append(o)
    lett = wp.join(letters, 'Lettering')
    meta = dict(id='water-tower', name='water tower (FOUNDED 1625)', file='models/landmarks/water-tower.glb',
                address='592 Mariner Drive', status='locked',
                atlas=dict(building_index=bi, center_atlas=[round(pt[0], 2), round(pt[1], 2)],
                           front_heading_deg_atlas=s['front_heading_deg_atlas'] if s else 0.0, footprint_m=s['footprint_m'] if s else [12, 12],
                           atlas_kind=s['atlas_kind'] if s else None, atlas_height_m=s['atlas_height_m'] if s else None, street=s['street'] if s else None),
                lettering=['WESTPORT', 'FOUNDED 1625'],
                notes=('Classic six-leg elevated steel tank, pale blue-grey (#A7B8C4), 13 m tank on battered tubular legs with tie-rod X bracing, '
                       'a balcony at the shell bottom, central riser and a caged ladder. Lettering is real geometry (DejaVu Sans Bold, navy), '
                       'WESTPORT over FOUNDED 1625, on the front (toward Mariner Drive) and the back. Center is the QA-moved place point '
                       '(qa.json move_places), which is also the center of Atlas building %s (kind %s in the Atlas, not "tower"). '
                       'Leg footings spread to a 16.4 m circle, a little beyond the 12 m Atlas square.' % (bi, s['atlas_kind'] if s else '?')))
    return [tank, lett], meta


# ============================================================================ pier bar

def build_pier_bar(A):
    wp.reset(); L = Lib()
    w = A[0]; pt = A[4]['pier-bar']
    best = None
    for pi, pl in enumerate(w['piers']):
        for i in range(0, len(pl) - 2, 2):
            x1, y1, x2, y2 = pl[i:i + 4]; dx, dy = x2 - x1, y2 - y1; LL = dx * dx + dy * dy
            t = 0 if LL == 0 else max(0, min(1, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / LL))
            d = math.hypot(pt[0] - (x1 + t * dx), pt[1] - (y1 + t * dy))
            if best is None or d < best[0]:
                best = (d, pi)
    pi = best[1]; pl = w['piers'][pi]
    P = list(zip(pl[0::2], pl[1::2]))
    # the seaward end is the end farther from the nearest named road
    dA = near_named_road(A[3], A[1], *P[0])[0]; dB = near_named_road(A[3], A[1], *P[-1])[0]
    if dA > dB:
        P = P[::-1]
    Lp = sum(math.dist(a, b) for a, b in zip(P, P[1:]))
    end, prev = P[-1], P[-2]
    ux, uy = (end[0] - prev[0]) / math.dist(end, prev), (end[1] - prev[1]) / math.dist(end, prev)
    PW, PD = 16.0, 20.0          # pier-head platform (x across, y along the pier)
    cdist = Lp + PD / 2          # the platform starts exactly where the app's pier deck ends
    cx, cy = end[0] + ux * PD / 2, end[1] + uy * PD / 2
    heading = math.degrees(math.atan2(-uy, -ux))
    bi = nearest_building(A, *pt, maxd=12)
    DZ = 1.2                     # deck top (PIER_DECK_Y = WATER_Y + 1.9 = 1.2 m over grade)
    WZ = -0.7
    g = G()
    # platform: decking, rim joists, stringers, pilings with cross bracing
    box(g, 'DeckWood', -PW / 2, PW / 2, -PD / 2, PD / 2, DZ - 0.06, DZ, skip='b')
    box(g, 'Piling', -PW / 2 - 0.05, PW / 2 + 0.05, -PD / 2 - 0.05, PD / 2 + 0.05, DZ - 0.36, DZ - 0.06, skip='t')
    xs = [-PW / 2 + 0.25 + k * (PW - 0.5) / 6 for k in range(7)]
    ys = [-PD / 2 + 0.25 + k * (PD - 0.5) / 8 for k in range(9)]
    for x in xs:
        box(g, 'Piling', x - 0.1, x + 0.1, -PD / 2, PD / 2, DZ - 0.6, DZ - 0.36, skip='t')
    for x in xs:
        for y in ys:
            edge = x in (xs[0], xs[-1]) or y in (ys[0], ys[-1])
            top = DZ + 1.05 if (edge and not (abs(x) < 1.8 and y == ys[0])) else DZ - 0.6
            ngon(g, 'Piling', x, y, 0.16, -4.0, top, n=8, caps='t')
    for x in (xs[0], xs[-1]):
        for a, b in zip(ys, ys[1:]):
            bar(g, 'Piling', (x, a, WZ + 0.2), (x, b, DZ - 0.7), 0.08, 0.2)
    for y in (ys[0], ys[-1]):
        for a, b in zip(xs, xs[1:]):
            bar(g, 'Piling', (a, y, WZ + 0.2), (b, y, DZ - 0.7), 0.08, 0.2)
    # deck rail on the outer pilings (opening at the land side where the pier comes in)
    rz = DZ
    yf, yb_, xl, xr = -PD / 2 + 0.25, PD / 2 - 0.25, -PW / 2 + 0.25, PW / 2 - 0.25
    for run in ([(-1.8, yf), (xl, yf), (xl, yb_), (xr, yb_), (xr, yf), (1.8, yf)],):
        for a, b in zip(run, run[1:]):
            a3 = Vector((a[0], a[1], 0)); b3 = Vector((b[0], b[1], 0))
            bar(g, 'DeckWood', a3 + Vector((0, 0, rz + 1.07)), b3 + Vector((0, 0, rz + 1.07)), 0.14, 0.05)
            bar(g, 'DeckWood', a3 + Vector((0, 0, rz + 0.95)), b3 + Vector((0, 0, rz + 0.95)), 0.06, 0.14)
            bar(g, 'DeckWood', a3 + Vector((0, 0, rz + 0.5)), b3 + Vector((0, 0, rz + 0.5)), 0.05, 0.12)
    # the bar: 10 x 14 weathered board building, raised sill, big propped bar windows, metal gable roof
    bx0, bx1, by0, by1 = -5.0, 5.0, -6.0, 8.0
    fz, zp = DZ + 0.02, DZ + 3.2     # the bar's floor is the deck (z = 1.2) plus a 2 cm finish
    box(g, 'DeckWood', bx0 - 0.05, bx1 + 0.05, by0 - 0.05, by1 + 0.05, DZ, fz, skip='b')
    ops = {'S': [('d', 0.0, 1.9, fz, fz + 2.2, dict(pair=True, lite=True, D='PaintedWood', T='DeckWood', rd=0.12)),
                 ('w', -3.3, 2.4, fz + 0.95, fz + 2.15, dict(rail=False, sill='DeckWood', T='DeckWood', mull=1, rd=0.12, glassmat='Glass')),
                 ('w', 3.3, 2.4, fz + 0.95, fz + 2.15, dict(rail=False, sill='DeckWood', T='DeckWood', mull=1, rd=0.12, glassmat='Glass'))],
           'E': [('w', y, 3.6, fz + 0.95, fz + 2.15, dict(rail=False, sill='DeckWood', T='DeckWood', rd=0.15, glassmat='Glass')) for y in (-3.0, 1.8)] +
                [('w', 6.3, 0.8, fz + 1.4, fz + 2.1, dict(rail=False, T='DeckWood', rd=0.08))],
           'W': [('w', y, 3.6, fz + 0.95, fz + 2.15, dict(rail=False, sill='DeckWood', T='DeckWood', rd=0.15, glassmat='Glass')) for y in (-1.8, 3.0)] +
                [('d', 6.6, 0.95, fz, fz + 2.1, dict(D='PaintedWood', T='DeckWood', rd=0.1))],
           'N': [('w', x, 1.2, fz + 1.2, fz + 2.1, dict(rail=False, T='DeckWood', rd=0.08, mull=1)) for x in (-2.5, 2.5)]}
    body(g, bx0, bx1, by0, by1, fz, zp, ops, wmat='WoodWeathered', found=None, corners='DeckWood')
    # bar counters under the side openings (the shutters are propped open above them)
    S = sides(bx0, bx1, by0, by1)
    for k, centers in (('E', (-3.0, 1.8)), ('W', (1.8, -3.0))):
        F = S[k][0]
        for c in centers:
            u = c if k == 'E' else c
            fbox(g, F, 'DeckWood', u - 1.9, u + 1.9, fz + 0.9, fz + 0.96, -0.15, 0.35)
            # propped plywood flap: hinged at the head, held out at ~35 degrees by two struts
            zt = fz + 2.22
            ang = math.radians(35)
            ln = 1.3
            p0a, p0b = F.p(u - 1.9, zt, 0.05), F.p(u + 1.9, zt, 0.05)
            dv = F.N * math.sin(ang) * ln + Vector((0, 0, -math.cos(ang) * ln))
            g.poly([p0a, p0b, p0b + dv, p0a + dv], 'WoodWeathered', F.N * 0.0 + Vector((0, 0, 1)) + F.N)
            g.poly([p0a, p0b, p0b + dv, p0a + dv], 'WoodWeathered', -(F.N * 0.0 + Vector((0, 0, 1)) + F.N))
            for uu in (u - 1.6, u + 1.6):
                bar(g, 'DeckWood', F.p(uu, fz + 0.96, 0.3), F.p(uu, zt, 0.05) + dv * 0.92, 0.05)
    # interior: dark room, bar, warm light
    box(g, 'Interior', bx0 + 0.15, bx1 - 0.15, by0 + 0.15, by1 - 0.15, fz, fz + 0.01, skip='b')
    box(g, 'DoorWood', -3.8, 3.8, 3.0, 3.8, fz, fz + 1.08, skip='b')
    box(g, 'DoorWood', -4.0, 4.0, 2.9, 3.9, fz + 1.08, fz + 1.14, skip='')
    box(g, 'Interior', -4.6, 4.6, 6.6, 7.8, fz, fz + 2.0, skip='b')
    for x in (-3.0, 0.0, 3.0):
        box(g, 'Lamp', x - 0.15, x + 0.15, 1.5 - 0.15, 1.5 + 0.15, zp - 0.35, zp - 0.15, skip='')
    box(g, 'Interior', bx0 + 0.1, bx1 - 0.1, by0 + 0.1, by1 - 0.1, zp - 0.02, zp, skip='t')
    rtop = roof_gable(g, 0, (by0 + by1) / 2 - 0.6, by1 - by0 + 1.2, bx1 - bx0, zp, 18, axis='y', ov=0.6, rake=0.6,
                      wmat='WoodWeathered', rmat='MetalRoof', T='DeckWood')
    # front porch posts carrying the extended rake
    for x in (bx0 + 0.1, bx1 - 0.1):
        cbox(g, 'DeckWood', x, by0 - 1.12, 0.16, 0.16, DZ, zp - 0.22, skip='b')
    box(g, 'DeckWood', bx0, bx1, by0 - 1.25, by0 - 1.0, zp - 0.24, zp, skip='')
    # tables and chairs on the deck
    tables = [(-5.9, -8.0), (-2.6, -8.3), (2.6, -8.3), (5.9, -8.0), (-6.6, -3.5), (6.6, -3.5), (-6.6, 1.5), (6.6, 4.5), (-3.0, 9.0), (3.0, 9.0)]
    for i, (x, y) in enumerate(tables):
        ngon(g, 'DeckWood', x, y, 0.42, DZ + 0.72, DZ + 0.76, n=10, caps='tb', smooth=False)
        ngon(g, 'Steel', x, y, 0.04, DZ, DZ + 0.72, n=6, caps='')
        ngon(g, 'Steel', x, y, 0.25, DZ, DZ + 0.03, n=8, caps='t', smooth=False)
        for k in range(2 if abs(x) > 6 or abs(y) > 8.5 else 3):
            a = math.radians(30 + i * 37 + k * (180 if abs(x) > 6 else 120))
            ccx, ccy = x + 0.72 * math.cos(a), y + 0.72 * math.sin(a)
            if abs(ccx) > PW / 2 - 0.5 or abs(ccy) > PD / 2 - 0.5:
                continue
            cbox(g, 'PaintedWood', ccx, ccy, 0.42, 0.42, DZ + 0.42, DZ + 0.46)
            for dx in (-0.18, 0.18):
                for dy in (-0.18, 0.18):
                    cbox(g, 'PaintedWood', ccx + dx, ccy + dy, 0.035, 0.035, DZ, DZ + 0.42, skip='b')
            bx_, by_ = ccx + 0.2 * math.cos(a), ccy + 0.2 * math.sin(a)
            bar(g, 'PaintedWood', (bx_, by_, DZ + 0.46), (bx_ + 0.05 * math.cos(a), by_ + 0.05 * math.sin(a), DZ + 0.9), 0.4, 0.03)
    # string lights: catenaries from the eaves to the rail posts, warm bulbs every ~0.55 m
    eave_z = zp + 0.1
    runs = [((-5.6, -6.6), (-7.75, -9.75)), ((5.6, -6.6), (7.75, -9.75)), ((-4.0, -7.2), (-1.8, -9.75)), ((4.0, -7.2), (1.8, -9.75)),
            ((-5.6, -1.0), (-7.75, -2.0)), ((5.6, 1.0), (7.75, 2.0)), ((-5.6, 6.0), (-7.75, 9.75)), ((5.6, 6.0), (7.75, 9.75)),
            ((-5.6, 8.6), (0.0, 9.75)), ((5.6, 8.6), (0.0, 9.75))]
    for (a, b) in runs:
        za, zb2 = eave_z, DZ + 2.4
        A3 = Vector((a[0], a[1], za)); B3 = Vector((b[0], b[1], zb2))
        n = max(6, int((B3 - A3).length / 0.55))
        pts = []
        for k in range(n + 1):
            t = k / n
            p = A3 + (B3 - A3) * t
            p.z -= 0.45 * 4 * t * (1 - t)
            pts.append(p)
        for p0, p1 in zip(pts, pts[1:]):
            bar(g, 'Wire', p0, p1, 0.012)
        for p in pts[1:-1]:
            lathe(g, 'Bulb', p.x, p.y, [(0.0, p.z - 0.09), (0.035, p.z - 0.07), (0.03, p.z - 0.02), (0.0, p.z)], n=5, smooth=True)
    # light poles at the far corners to carry the runs out over the deck
    for x, y in ((-7.75, -9.75), (7.75, -9.75), (0.0, -9.75), (-7.75, 9.75), (7.75, 9.75), (0.0, 9.75), (-7.75, -2.0), (7.75, 2.0)):
        if abs(x) < 0.1:
            continue
        cbox(g, 'DeckWood', x, y, 0.1, 0.1, DZ + 1.05, DZ + 2.45, skip='b')
    for x, y in ((0.0, 9.75),):
        cbox(g, 'DeckWood', x, y, 0.1, 0.1, DZ + 1.05, DZ + 2.45, skip='b')
    # front-center pole beside the pier entrance (two posts flank the opening)
    for x in (-1.8, 1.8):
        cbox(g, 'DeckWood', x, -9.75, 0.12, 0.12, DZ, DZ + 2.45, skip='b')
    runs_fix = None  # noqa
    o = soup_obj(g, 'PierBar', L)
    meta = dict(id='pier-bar', name='the pier and the pier bar', file='models/landmarks/pier-bar.glb', address='376 Harbor Drive', status='locked',
                atlas=dict(building_index=bi, replaces_atlas_kind=A[2][bi]['kind'] if bi is not None else None,
                           center_atlas=[round(cx, 2), round(cy, 2)], front_heading_deg_atlas=round(heading, 1), footprint_m=[PW, PD]),
                pier_index=pi, pier_length_m=round(Lp, 2), distance_along_pier_m=round(cdist, 2),
                deck_z_m=DZ, water_z_m=WZ,
                notes=('Origin = the platform center at map grade z = 0; the deck top is z = 1.2 (PIER_DECK_Y = WATER_Y + 1.9), pilings run to z = -4. '
                       'The app draws pier %d as a 3 m deck (%.1f m long); this model brings its own 16 x 20 m pier-head platform that starts '
                       'exactly at the seaward end of that polyline (so the app deck and rails do not overlap it) and runs 20 m on along the last '
                       'segment; the 10 x 14 m bar sits on it with 3 m of deck all round. Front (-Y) faces back up the pier toward Harbor Drive; '
                       'the rail has a 3.6 m opening where the pier comes in. Atlas building %s (a %s at the old pier-bar point) is the bar it replaces; hide it. '
                       'distance_along_pier_m is the platform center measured from the land end, 10 m past the polyline end.')
                % (pi, Lp, bi, A[2][bi]['kind'] if bi is not None else '?'))
    meta['height_m'] = round(rtop, 2)
    return [o], meta


# ============================================================================ Williams Funeral Home

def build_funeral(A):
    wp.reset(); L = Lib()
    s = site(A, 3160)
    W, D = s['footprint_m']
    g = G()
    T = 'Trim'
    # main block: two stories, painted brick, x -9..9, y -6..8
    x0, x1, y0, y1 = -9.0, 9.0, -5.6, 8.0
    fz, f2, zp = 0.75, 4.35, 7.7
    sh = dict(rail=True, mull=1, rd=0.14, shutters='Shutter', cw=0.1, sill='TrimStone')
    ops = {'S': [('d', 0.0, 1.8, fz, fz + 2.6, dict(pair=True, transom=0.55, rd=0.25, D='DoorBlack'))] +
                [('w', x, 1.05, fz + 0.75, fz + 2.6, sh) for x in (-6.6, -3.2, 3.2, 6.6)] +
                [('w', x, 1.05, f2 + 0.7, f2 + 2.5, sh) for x in (-6.6, -3.2, 0.0, 3.2, 6.6)],
           'E': [('w', y, 1.05, fz + 0.75, fz + 2.6, sh) for y in (-2.6, 4.6)] + [('d', 0.6, 1.0, fz, fz + 2.2, dict(rd=0.14, D='DoorBlack'))] +
                [('w', y, 1.05, f2 + 0.7, f2 + 2.5, sh) for y in (-2.6, 1.0, 4.6)],
           'W': [('w', y, 1.05, f2 + 0.7, f2 + 2.5, sh) for y in (-2.6, 1.0, 4.6)],
           'N': [('w', x, 1.05, fz + 0.75, fz + 2.6, sh) for x in (-6.0, -2.0, 6.0)] + [('w', x, 1.05, f2 + 0.7, f2 + 2.5, sh) for x in (-6.0, -2.0, 2.0, 6.0)]}
    body(g, x0, x1, y0, y1, fz, zp, ops, wmat='BrickPainted', found='BrickPainted', corners=False, found_out=0.05)
    box(g, T, x0 - 0.06, x1 + 0.06, y0 - 0.06, y1 + 0.06, f2 - 0.12, f2 + 0.1, skip='')
    box(g, T, x0 - 0.1, x1 + 0.1, y0 - 0.1, y1 + 0.1, zp - 0.45, zp, skip='b')
    rt = roof_hip(g, 0, (y0 + y1) / 2, x1 - x0, y1 - y0, zp, 27, ov=0.55, rmat='Slate')
    for x in (-5.0, 5.0):   # interior-end chimneys rising through the roof
        box(g, 'BrickPainted', x - 0.55, x + 0.55, 3.5, 4.4, zp - 1, rt + 1.0, skip='b')
        box(g, T, x - 0.65, x + 0.65, 3.4, 4.5, rt + 1.0, rt + 1.15, skip='')
    # two-story portico: four columns, entablature, pediment, porch floor and steps
    px0, px1, py0 = -5.6, 5.6, -9.0
    box(g, 'BrickPainted', px0, px1, py0, y0, ZF, fz - 0.05, skip='bn')
    box(g, 'TrimStone', px0 - 0.04, px1 + 0.04, py0 - 0.04, y0, fz - 0.05, fz, skip='bn')
    for x in (-4.8, -1.6, 1.6, 4.8):
        column(g, x, py0 + 0.55, fz, zp - 0.75, 0.3)
    box(g, T, px0, px1, py0 + 0.1, y0, zp - 0.75, zp, skip='bn')
    pediment(g, px0, px1, py0 + 0.1, y0 + 5.8, zp, 24, 'Slate')
    box(g, T, px0 + 0.3, px1 - 0.3, py0 + 0.2, y0, zp - 0.77, zp - 0.75, skip='')   # porch ceiling
    steps_y(g, 'TrimStone', -3.0, 3.0, py0, fz, 4, tread=0.32)
    Fs = sides(x0, x1, y0, y1)['S'][0]
    for u in (-1.55, 1.55):
        lantern(g, Fs, u, fz + 2.1)
    # second floor balcony over the entry
    box(g, T, -1.6, 1.6, py0 + 0.9, y0, f2 - 0.15, f2 + 0.05, skip='')
    railing(g, T, [(-1.5, y0), (-1.5, py0 + 1.0), (1.5, py0 + 1.0), (1.5, y0)], f2 + 0.05, h=0.95, spacing=1.5, balusters=0.14, mid=True)
    # chapel wing (left): one story, tall windows, hip roof
    cx0, cx1, cy0, cy1 = -16.5, -9.0, -3.6, 9.5
    czp = 5.4
    cw = dict(rail=True, mull=1, rd=0.14, shutters='Shutter', sill='TrimStone')
    cops = {'S': [('w', -13.0, 1.1, fz + 0.75, fz + 3.3, cw)],
            'W': [('w', y, 1.1, fz + 0.75, fz + 3.3, cw) for y in (-1.0, 3.0, 7.0)],
            'N': [('d', -12.9, 1.0, fz, fz + 2.2, dict(rd=0.12, D='DoorBlack'))]}
    body(g, cx0, cx1, cy0, cy1, fz, czp, cops, wmat='BrickPainted', found='BrickPainted', corners=False, skip_walls='E', found_out=0.05)
    box(g, T, cx0 - 0.08, cx1, cy0 - 0.08, cy1 + 0.08, czp - 0.4, czp, skip='b')
    roof_hip(g, (cx0 + cx1) / 2, (cy0 + cy1) / 2, cx1 - cx0, cy1 - cy0, czp, 27, ov=0.45, rmat='Slate')
    steps_y(g, 'TrimStone', -13.6, -12.2, cy1 + 1.05, fz, 3, tread=-0.35) if False else None
    for i in range(3):
        box(g, 'TrimStone', -13.6, -12.2, cy1, cy1 + (3 - i) * 0.3, ZF, fz - i * 0.25, skip='bs')
    # porte-cochere (right): flat roof on four columns, balustrade; garage behind
    qx0, qx1, qy0, qy1 = 9.0, 16.9, -4.6, 3.0
    for x, y in ((qx1 - 0.4, qy0 + 0.4), (qx1 - 0.4, qy1 - 0.4)):
        column(g, x, y, 0.0, 4.2, 0.24)
    box(g, T, x1, qx1, qy0, qy1, 4.2, 4.85, skip='')
    railing(g, T, [(x1 + 0.1, qy0 + 0.1), (qx1 - 0.1, qy0 + 0.1), (qx1 - 0.1, qy1 - 0.1), (x1 + 0.1, qy1 - 0.1)], 4.85, h=0.8, spacing=1.9, balusters=0.16, mid=True)
    box(g, 'Concrete', x1, qx1, qy0, qy1, -0.1, 0.03, skip='b')
    box(g, 'TrimStone', x1, x1 + 0.9, -0.1, 1.3, ZF, fz - 0.05, skip='b')
    box(g, 'TrimStone', x1 + 0.9, x1 + 1.3, -0.1, 1.3, ZF, fz / 2, skip='b')
    gx0, gx1, gy0, gy1 = 9.0, 16.5, 3.4, 11.6
    gops = {'E': [('d', 7.5, 3.0, 0.1, 2.5, dict(rd=0.15, D='Trim'))],
            'S': [('w', 12.8, 1.0, 1.2, 2.6, dict(shutters='Shutter', rd=0.12))]}
    body(g, gx0, gx1, gy0, gy1, 0.1, 3.6, gops, wmat='BrickPainted', found='BrickPainted', corners=False)
    roof_hip(g, (gx0 + gx1) / 2, (gy0 + gy1) / 2, gx1 - gx0, gy1 - gy0, 3.6, 24, ov=0.4, rmat='Slate')
    box(g, 'Concrete', gx1, gx1 + 0.4, 5.5, 9.5, -0.1, 0.03, skip='b')
    # rear ell
    rops = {'N': [('w', 0.0, 1.0, fz + 0.75, fz + 2.4, sh)], 'E': [('w', 9.8, 1.0, fz + 0.75, fz + 2.4, sh)]}
    body(g, -5.0, 5.0, y1, 11.4, fz, 4.0, rops, wmat='BrickPainted', found='BrickPainted', corners=False, skip_walls='S')
    roof_hip(g, 0, (y1 + 11.4) / 2, 10.0, 11.4 - y1, 4.0, 27, ov=0.4, rmat='Slate')
    o = soup_obj(g, 'FuneralHome', L)
    meta = dict(id='williams-funeral-home', name='Williams Funeral Home', file='models/landmarks/williams-funeral-home.glb',
                address='205 Main Street', status='locked',
                atlas=dict(building_index=s['building_index'], center_atlas=s['center_atlas'], front_heading_deg_atlas=s['front_heading_deg_atlas'],
                           footprint_m=s['footprint_m'], atlas_kind=s['atlas_kind'], atlas_height_m=s['atlas_height_m'], street=s['street'],
                           curb_line_local_y=s['curb_line_local_y']),
                height_m=round(rt + 1.15, 2),
                notes=('Interpretation (no reference image): a two-story Greek Revival house in white-painted brick under a slate hip roof, '
                       'with a full-height four-column portico and pediment, black shutters on 6-over-6 windows, lanterns, a small balcony over the '
                       'entry, a one-story chapel wing on the left, a porte-cochere and garage on the right and a rear ell. No signs. '
                       'Front faces Main Street; the building sits back from the curb as the Atlas footprint does.'))
    return [o], meta


# ============================================================================ Chadwick's

def build_chadwicks(A):
    wp.reset(); L = Lib()
    s = site(A, 3730)
    W, D = s['footprint_m']
    hw, hd = W / 2, D / 2
    g = G()
    # dining room: full width, front 10 m of the footprint
    x0, x1 = -hw + 0.55, hw - 0.55
    y0, y1 = -hd + 1.3, -hd + 10.8
    fz = 0.3
    sill, head, zp = fz + 0.85, fz + 2.55, fz + 3.5
    # low wall: stainless below the windows on a short block base
    box(g, 'Concrete', x0 - 0.05, x1 + 0.05, y0 - 0.05, y1, ZF, fz, skip='b')
    S = sides(x0, x1, y0, y1)
    for k in ('S', 'E', 'W'):
        F, u0, u1, sgn = S[k]
        holes = []
        if k == 'S':
            holes = [(u0 + 0.3, -1.35, sill, head), (-1.25, 1.25, fz, head), (1.35, u1 - 0.3, sill, head)]
        else:
            holes = [(u0 + 0.3, u1 - 0.6, sill, head)]
        # stainless lower panel, enamel band above windows, red stripe
        for a, b in [(u0, u1)]:
            pass
        lowmat = 'Stainless'
        wall(g, F, u0, u1, fz, sill, [h for h in holes if h[2] < sill - 0.01], lowmat)
        wall(g, F, u0, u1, sill, head, holes, 'Enamel')
        fq(g, F, 'Enamel', u0, u1, head, zp)
        fbox(g, F, 'EnamelRed', u0, u1, head + 0.25, head + 0.42, 0, 0.02, skip='lr')
        fbox(g, F, 'Stainless', u0, u1, sill - 0.05, sill + 0.03, 0, 0.06, skip='lr')
        for (a, b, c, d) in holes:
            if d - c < 2.0 and k == 'S' and a > -1.3 and b < 1.3:
                continue
            if c < sill - 0.01:
                continue
            # big fixed panes with slim stainless mullions every ~1.2 m
            n = max(1, int(round((b - a) / 1.2)))
            for i in range(n + 1):
                u = a + (b - a) * i / n
                fbox(g, F, 'Stainless', u - 0.04, u + 0.04, c, d, -0.12, 0.02, skip='')
            fbox(g, F, 'Stainless', a, b, c - 0.02, c + 0.04, -0.12, 0.02, skip='lr')
            fbox(g, F, 'Stainless', a, b, d - 0.04, d + 0.02, -0.12, 0.02, skip='lr')
            fq(g, F, 'ShopGlass', a, b, c, d, -0.06)
            g.poly([F.p(a, c, 0), F.p(b, c, 0), F.p(b, c, -0.14), F.p(a, c, -0.14)], 'Stainless', (0, 0, 1))
            g.poly([F.p(a, d, 0), F.p(b, d, 0), F.p(b, d, -0.14), F.p(a, d, -0.14)], 'Enamel', (0, 0, -1))
    # entry vestibule (glass and stainless), front door
    vx0, vx1, vy0 = -1.25, 1.25, -hd + 0.05
    box(g, 'Concrete', vx0 - 0.4, vx1 + 0.4, vy0 - 0.0, y0, ZF, 0.15, skip='b')
    box(g, 'Concrete', vx0, vx1, vy0 + 0.2, y0, 0.15, fz, skip='b')
    for x in (vx0, vx1):
        box(g, 'Stainless', x - 0.05, x + 0.05, vy0 + 0.2, y0, fz, head, skip='b')
    box(g, 'Stainless', vx0 - 0.05, vx1 + 0.05, vy0 + 0.15, y0, head, head + 0.4, skip='b')
    Fv = Fr((0, vy0 + 0.2, 0), (1, 0, 0))
    fq(g, Fv, 'ShopGlass', vx0 + 0.05, vx1 - 0.05, fz, head)
    fbox(g, Fv, 'Stainless', -0.5, 0.5, fz, fz + 2.15, 0, 0.04)
    fq(g, Fv, 'ShopGlass', -0.42, 0.42, fz + 0.12, fz + 2.05, 0.045)
    bar(g, 'Stainless', Fv.p(0.3, fz + 0.9, 0.1), Fv.p(0.3, fz + 1.3, 0.1), 0.03, n=6)
    for x in (vx0, vx1):
        Fsd = Fr((x, 0, 0), (0, 1 if x > 0 else -1, 0))
        g.poly([(x, vy0 + 0.2, fz), (x, y0, fz), (x, y0, head), (x, vy0 + 0.2, head)], 'ShopGlass', (1 if x > 0 else -1, 0, 0))
    # roof: flat, with a rounded stainless-capped fascia that overhangs on three sides
    box(g, 'Roofing', x0, x1, y0, y1, zp, zp + 0.05, skip='b')
    for (k, ov) in (('S', 0.5), ('E', 0.35), ('W', 0.35)):
        F, u0, u1, sgn = S[k]
        e0 = 0.35 if k != 'S' else 0.35
        lo, hi = zp - 0.05, zp + 0.55
        prof = [(0.0, lo), (ov * 0.6, lo), (ov, lo + 0.15), (ov, hi - 0.12), (ov * 0.75, hi), (0.0, hi)]
        ua, ub = u0 - (0.35 if k == 'S' else 0), u1 + (0.35 if k == 'S' else 0)
        if k == 'E':
            ua, ub = u0 - 0.5, u1
        if k == 'W':
            ua, ub = u0, u1 + 0.5
        for (d0, z0), (d1, z1) in zip(prof, prof[1:]):
            mat = 'Stainless' if z0 > lo + 0.1 or z1 > lo + 0.1 else 'Enamel'
            g.poly([F.p(ua, z0, d0), F.p(ub, z0, d0), F.p(ub, z1, d1), F.p(ua, z1, d1)], mat, F.N * (z1 - z0) - Vector((0, 0, 1)) * (d1 - d0) if (d1 - d0) or (z1 - z0) else F.N)
    # awnings over the front windows (no lettering)
    Fs = S['S'][0]
    for a, b in ((x0 + 0.25, -1.4), (1.4, x1 - 0.25)):
        zt, zb_, out = head + 0.22, head - 0.35, 1.05
        g.poly([Fs.p(a, zt, 0.02), Fs.p(b, zt, 0.02), Fs.p(b, zb_, out), Fs.p(a, zb_, out)], 'Awning', (0, -1, 1))
        g.poly([Fs.p(a, zt, 0.02), Fs.p(b, zt, 0.02), Fs.p(b, zb_, out), Fs.p(a, zb_, out)], 'Awning', (0, 1, -1))
        n = int((b - a) / 0.3)
        for i in range(n):
            ua_, ub_ = a + (b - a) * i / n, a + (b - a) * (i + 1) / n
            um = (ua_ + ub_) / 2
            g.poly([Fs.p(ua_, zb_, out), Fs.p(ub_, zb_, out), Fs.p(ub_, zb_ - 0.18, out), Fs.p(um, zb_ - 0.26, out), Fs.p(ua_, zb_ - 0.18, out)], 'Awning', (0, -1, 0))
        for u in (a, b):
            g.poly([Fs.p(u, zt, 0.02), Fs.p(u, zb_, out), Fs.p(u, zb_ - 0.2, out)], 'Awning', (1 if u == b else -1, 0, 0))
        for u in (a + 0.05, b - 0.05):
            bar(g, 'Steel', Fs.p(u, zb_ - 0.1, out - 0.02), Fs.p(u, zb_ - 0.8, 0.02), 0.025, n=6)
    # interior: checker floor, booths along the windows, counter with stools, back bar, pendant lights
    box(g, 'Checker', x0 + 0.1, x1 - 0.1, y0 + 0.1, y1 - 0.1, fz - 0.01, fz + 0.005, skip='b')
    box(g, 'Interior', x0 + 0.1, x1 - 0.1, y0 + 0.1, y1 - 0.1, zp - 0.3, zp - 0.25, skip='t')
    box(g, 'Interior', x0 + 0.1, x1 - 0.1, y1 - 0.35, y1 - 0.1, fz, zp - 0.25, skip='b')
    for x in [x0 + 1.1 + k * 2.15 for k in range(6)]:
        if abs(x) < 1.6:
            continue
        cbox(g, 'Counter', x, y0 + 0.75, 0.8, 0.75, fz + 0.7, fz + 0.75, skip='')
        cbox(g, 'Stainless', x, y0 + 0.75, 0.08, 0.08, fz, fz + 0.7, skip='b')
        for dx in (-0.75, 0.75):
            cbox(g, 'Vinyl', x + dx, y0 + 0.75, 0.5, 1.2, fz, fz + 0.45, skip='b')
            cbox(g, 'Vinyl', x + dx + (0.2 if dx > 0 else -0.2), y0 + 0.75, 0.12, 1.2, fz + 0.45, fz + 1.15, skip='b')
    for y in (y0 + 2.6, y0 + 5.0):
        for x in (x0 + 0.75, x1 - 0.75):
            cbox(g, 'Counter', x, y, 0.75, 0.8, fz + 0.7, fz + 0.75, skip='')
            cbox(g, 'Stainless', x, y, 0.08, 0.08, fz, fz + 0.7, skip='b')
    cy = y1 - 2.3
    box(g, 'Stainless', -5.0, 5.0, cy - 0.35, cy + 0.35, fz, fz + 1.0, skip='b')
    box(g, 'Counter', -5.15, 5.15, cy - 0.5, cy + 0.4, fz + 1.0, fz + 1.06, skip='')
    for i in range(11):
        x = -4.5 + i * 0.9
        ngon(g, 'Stainless', x, cy - 0.85, 0.035, fz, fz + 0.7, n=6, caps='')
        ngon(g, 'Vinyl', x, cy - 0.85, 0.2, fz + 0.7, fz + 0.78, n=10, caps='t', smooth=False)
    box(g, 'Stainless', -5.0, 5.0, y1 - 0.9, y1 - 0.35, fz, fz + 0.95, skip='b')
    box(g, 'Counter', -5.0, 5.0, y1 - 0.95, y1 - 0.35, fz + 0.95, fz + 1.0, skip='')
    box(g, 'ShopGlass', -1.0, 0.5, y1 - 0.85, y1 - 0.45, fz + 1.0, fz + 1.45, skip='b')
    ngon(g, 'Stainless', 2.2, y1 - 0.62, 0.18, fz + 1.0, fz + 1.55, n=10, caps='t')
    for x in (-4.0, -1.3, 1.3, 4.0):
        for y in (y0 + 1.2, cy - 0.3):
            bar(g, 'Wire', (x, y, zp - 0.25), (x, y, zp - 0.75), 0.015)
            lathe(g, 'Lamp', x, y, [(0.0, zp - 0.95), (0.2, zp - 0.92), (0.12, zp - 0.75), (0.02, zp - 0.72)], n=10)
    # kitchen block behind: painted block, flat roof, rooftop HVAC and exhaust, back door
    kx0, kx1, ky0, ky1 = -hw + 0.6, hw - 0.6, y1, hd - 0.75
    kz = 3.6
    kops = {'N': [('d', 3.6, 0.95, 0.3, 2.35, dict(D='DoorBlack', rd=0.1, T='Stainless')), ('w', -2.5, 1.2, 1.8, 2.5, dict(rail=False, rd=0.1, sill=False))],
            'E': [('w', ky0 + 3.0, 1.2, 1.8, 2.5, dict(rail=False, rd=0.1, sill=False))],
            'W': [('d', ky0 + 7.5, 0.95, 0.3, 2.35, dict(D='DoorBlack', rd=0.1, T='Stainless'))]}
    body(g, kx0, kx1, ky0, ky1, 0.3, kz, kops, wmat='Block', found='Concrete', corners=False, skip_walls='S')
    box(g, 'Block', kx0 - 0.05, kx1 + 0.05, ky0, ky1 + 0.05, kz, kz + 0.45, skip='b')
    box(g, 'Roofing', kx0, kx1, ky0, ky1, kz + 0.02, kz + 0.06, skip='b')
    box(g, 'Stainless', kx0 - 0.08, kx1 + 0.08, ky0, ky1 + 0.08, kz + 0.45, kz + 0.52, skip='b')
    box(g, 'HVAC', -4.0, -2.2, ky0 + 2.0, ky0 + 3.4, kz + 0.06, kz + 1.25, skip='b')
    ngon(g, 'Wire', -3.1, ky0 + 2.7, 0.45, kz + 1.25, kz + 1.27, n=12, caps='t')
    box(g, 'HVAC', 1.5, 3.9, ky0 + 4.5, ky0 + 5.7, kz + 0.06, kz + 1.0, skip='b')
    cbox(g, 'Stainless', 0.5, ky0 + 7.0, 0.9, 0.9, kz + 0.06, kz + 0.7, skip='b')
    lathe(g, 'Stainless', 0.5, ky0 + 7.0, [(0.35, kz + 0.7), (0.35, kz + 1.1), (0.7, kz + 1.15), (0.55, kz + 1.35), (0.0, kz + 1.4)], n=12)
    cbox(g, 'Concrete', 3.6, ky1 + 0.45, 1.6, 0.9, ZF, 0.28)
    o = soup_obj(g, 'Chadwicks', L)
    meta = dict(id='chadwicks', name="Chadwick's", file='models/landmarks/chadwicks.glb', address='524 Harbor Drive', status='you confirmed',
                atlas=dict(building_index=s['building_index'], center_atlas=s['center_atlas'], front_heading_deg_atlas=s['front_heading_deg_atlas'],
                           footprint_m=s['footprint_m'], atlas_kind=s['atlas_kind'], atlas_height_m=s['atlas_height_m'], street=s['street'],
                           curb_line_local_y=s['curb_line_local_y']),
                notes=('Interpretation: a classic one-story diner filling the Atlas footprint: a full-width dining room across the front with a '
                       'continuous band of big windows (stainless mullions, see-through glass), cream enamel and a red stripe, a rounded stainless '
                       'roof edge, a glass entry vestibule and deep red canvas awnings; inside a checkerboard floor, booths along the windows, '
                       'a counter with eleven stools, a back bar and lit pendants; a painted-block kitchen behind with rooftop units. '
                       'The Atlas height (%.0f m) is far above a one-story diner; the model is %.1f m. No sign or name on the building.'))
    meta['notes'] = meta['notes'] % (s['atlas_height_m'], kz + 1.4)
    return [o], meta


# ============================================================================ Lindon County Courthouse

def build_courthouse(A):
    wp.reset(); L = Lib()
    s = site(A, 0)
    W, D = s['footprint_m']
    hw, hd = W / 2, D / 2
    g = G()
    T = 'Trim'
    x0, x1, y0, y1 = -hw + 1.2, hw - 1.2, -hd + 6.0, hd - 0.6
    fz, f2, zp = 1.6, 6.7, 11.6
    w1 = dict(rail=True, mull=1, rd=0.22, sill='TrimStone', lintel='TrimStone', cw=0.0, head=0.25)
    w2 = dict(rail=True, mull=1, rd=0.22, sill='TrimStone', lintel='TrimStone')
    ops = {'S': [], 'N': [], 'E': [], 'W': []}
    # front wall: windows either side of the portico, entry and windows behind it
    for x in (-14.6, -11.2, 11.2, 14.6, -3.3, 3.3):
        ops['S'].append(('w', x, 1.4, fz + 0.9, fz + 3.6, w1))
        ops['S'].append(('a', x, 1.4, f2 + 0.9, f2 + 4.1, w2))
    ops['S'].append(('d', 0.0, 2.2, fz, fz + 3.2, dict(pair=True, transom=0.8, rd=0.35, D='DoorWood', lite=False)))
    ops['S'].append(('a', 0.0, 1.6, f2 + 0.6, f2 + 4.1, w2))
    nside = 9
    for i in range(nside):
        y = y0 + 3.0 + i * (y1 - y0 - 6.0) / (nside - 1)
        for k in ('E', 'W'):
            if k == 'E' and i == nside // 2:
                ops[k].append(('d', y, 1.8, fz, fz + 2.8, dict(pair=True, transom=0.6, rd=0.3, D='DoorWood')))
            else:
                ops[k].append(('w', y, 1.4, fz + 0.9, fz + 3.6, w1))
            ops[k].append(('a', y, 1.4, f2 + 0.9, f2 + 4.1, w2))
    for x in (-13.5, -8.1, -2.7, 2.7, 8.1, 13.5):
        ops['N'].append(('w', x, 1.4, fz + 0.9, fz + 3.6, w1))
        ops['N'].append(('a', x, 1.4, f2 + 0.9, f2 + 4.1, w2))
    body(g, x0, x1, y0, y1, fz, zp, ops, wmat='BrickRed', found=None, corners=False)
    # rusticated stone basement, belt course, quoins, entablature and cornice
    box(g, 'Ashlar', x0 - 0.12, x1 + 0.12, y0 - 0.12, y1 + 0.12, ZF, fz, skip='b')
    box(g, 'TrimStone', x0 - 0.18, x1 + 0.18, y0 - 0.18, y1 + 0.18, fz - 0.05, fz + 0.15, skip='')
    box(g, 'TrimStone', x0 - 0.06, x1 + 0.06, y0 - 0.06, y1 + 0.06, f2 - 0.1, f2 + 0.18, skip='')
    for cx_, cy_ in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        # quoins: continuous courses at the corner, long and short faces alternating
        nq = int((zp - 1.1 - fz - 0.2) / 0.42)
        for k in range(nq):
            z = fz + 0.17 + k * 0.42
            wa, wb = (0.95, 0.5) if k % 2 == 0 else (0.5, 0.95)
            sx = 1 if cx_ == x0 else -1; sy = 1 if cy_ == y0 else -1
            xa, xb = sorted((cx_ - sx * 0.05, cx_ + sx * wa)); ya, yb = sorted((cy_ - sy * 0.05, cy_ + sy * wb))
            box(g, 'TrimStone', xa, xb, ya, yb, z + 0.015, z + 0.405, skip='')
    # basement windows under the first-floor windows
    for k in ('E', 'W', 'N'):
        F, u0, u1, sgn = sides(x0 - 0.12, x1 + 0.12, y0 - 0.12, y1 + 0.12)[k]
        for op in ops[k]:
            if op[0] == 'w':
                u = op[1] * sgn
                fq(g, F, 'Glass', u - 0.5, u + 0.5, 0.35, 1.1, 0.005)
                fbox(g, F, 'TrimStone', u - 0.6, u + 0.6, 0.25, 0.35, 0, 0.06)
    box(g, T, x0 - 0.15, x1 + 0.15, y0 - 0.15, y1 + 0.15, zp - 1.1, zp - 0.3, skip='b')
    box(g, T, x0 - 0.45, x1 + 0.45, y0 - 0.45, y1 + 0.45, zp - 0.3, zp, skip='b')
    rt = roof_hip(g, 0, (y0 + y1) / 2, x1 - x0, y1 - y0, zp, 20, ov=0.5, rmat='Slate')
    # hexastyle portico, giant order, stylobate and steps
    px0, px1 = -9.2, 9.2
    py0 = y0 - 3.4
    box(g, 'Ashlar', px0, px1, py0, y0, ZF, fz - 0.05, skip='bn')
    box(g, 'TrimStone', px0 - 0.05, px1 + 0.05, py0 - 0.05, y0, fz - 0.05, fz + 0.05, skip='bn')
    for x in (-8.25, -4.95, -1.65, 1.65, 4.95, 8.25):
        column(g, x, py0 + 0.65, fz + 0.05, zp - 1.1, 0.46, n=16)
    box(g, T, px0, px1, py0 + 0.05, y0, zp - 1.1, zp, skip='bn')
    box(g, T, px0 + 0.4, px1 - 0.4, py0 + 0.3, y0, zp - 1.12, zp - 1.1, skip='')
    pd_top = pediment(g, px0 - 0.15, px1 + 0.15, py0 - 0.1, y0 + 11.6, zp, 22, 'Slate')
    # oculus in the tympanum
    lathe(g, T, 0, py0 - 0.12, [], n=3) if False else None
    Fp = Fr((0, py0 - 0.11, 0), (1, 0, 0))
    ring = [(0.0, zp + 1.8)]
    oc = []
    for i in range(16):
        a = 2 * math.pi * i / 16
        oc.append(Fp.p(0.75 * math.cos(a), zp + 1.75 + 0.75 * math.sin(a), 0.02))
    g.poly(oc, 'Glass', (0, -1, 0))
    nsteps = 9
    steps_y(g, 'TrimStone', px0 + 0.6, px1 - 0.6, py0, fz, nsteps, tread=0.3)
    # cupola: square clock stage, octagonal lantern, dome and finial on the ridge
    cyc = (y0 + y1) / 2
    cz0 = rt - 1.2
    cz1 = rt + 3.4
    bw = 2.6
    box(g, 'Trim', -bw, bw, cyc - bw, cyc + bw, cz0, cz1, skip='b')
    box(g, T, -bw - 0.25, bw + 0.25, cyc - bw - 0.25, cyc + bw + 0.25, cz1, cz1 + 0.4, skip='')
    for k in ('S', 'E', 'N', 'W'):
        F = sides(-bw, bw, cyc - bw, cyc + bw)[k][0]
        uc = 0.0 if k in 'SN' else (cyc if k == 'E' else -cyc)
        zc = (cz0 + cz1) / 2 + 0.6
        ring = [F.p(uc + 1.25 * math.cos(2 * math.pi * i / 24), zc + 1.25 * math.sin(2 * math.pi * i / 24), 0.04) for i in range(24)]
        g.poly(ring, 'Bronze', F.N)
        face = [F.p(uc + 1.1 * math.cos(2 * math.pi * i / 24), zc + 1.1 * math.sin(2 * math.pi * i / 24), 0.06) for i in range(24)]
        g.poly(face, 'ClockFace', F.N)
        for h in range(12):
            a = 2 * math.pi * h / 12
            r0, r1 = (0.82 if h % 3 else 0.72), 0.98
            bar(g, 'Bronze', F.p(uc + r0 * math.cos(a), zc + r0 * math.sin(a), 0.075), F.p(uc + r1 * math.cos(a), zc + r1 * math.sin(a), 0.075), 0.05, 0.02)
        # hands at about ten past ten
        for ang, ln, wd in ((math.radians(150), 0.55, 0.07), (math.radians(30), 0.85, 0.045)):
            bar(g, 'Bronze', F.p(uc, zc, 0.09), F.p(uc + ln * math.cos(ang), zc + ln * math.sin(ang), 0.09), wd, 0.02)
        fbox(g, F, T, uc - 1.6, uc + 1.6, cz0 + 0.3, cz0 + 0.5, 0, 0.08)
    # octagonal lantern with columns and arched openings (dark inside)
    lz0, lz1 = cz1 + 0.4, cz1 + 3.6
    ngon(g, 'Glass', 0, cyc, 1.7, lz0, lz1, n=8, caps='')
    for i in range(8):
        a = 2 * math.pi * i / 8
        column(g, 2.05 * math.cos(a), cyc + 2.05 * math.sin(a), lz0, lz1 - 0.1, 0.13, n=8)
    ngon(g, T, 0, cyc, 2.45, lz0 - 0.05, lz0 + 0.15, n=8, caps='t', smooth=False)
    ngon(g, T, 0, cyc, 2.45, lz1 - 0.1, lz1 + 0.4, n=8, caps='tb', smooth=False)
    prof = [(2.2, lz1 + 0.4), (2.15, lz1 + 0.9)]
    for k in range(1, 8):
        a = math.pi / 2 * k / 8
        prof.append((2.15 * math.cos(a), lz1 + 0.9 + 2.1 * math.sin(a)))
    prof.append((0.25, lz1 + 3.0))
    lathe(g, 'Copper', 0, cyc, prof, n=24)
    top = lz1 + 3.0
    lathe(g, 'Bronze', 0, cyc, [(0.25, top), (0.18, top + 0.3), (0.3, top + 0.55), (0.06, top + 0.8), (0.04, top + 1.6), (0.0, top + 1.7)], n=8)
    o = soup_obj(g, 'Courthouse', L)
    meta = dict(id='courthouse', name='Lindon County Courthouse', file='models/landmarks/courthouse.glb', address='129 Second Street', status='Canon 2',
                atlas=dict(building_index=s['building_index'], center_atlas=s['center_atlas'], front_heading_deg_atlas=s['front_heading_deg_atlas'],
                           footprint_m=s['footprint_m'], atlas_kind=s['atlas_kind'], atlas_height_m=s['atlas_height_m'], street=s['street'],
                           curb_line_local_y=s['curb_line_local_y']),
                height_m=round(top + 1.7, 2),
                notes=('Interpretation (no reference image): a two-story neoclassical red-brick courthouse on a rusticated stone basement, '
                       'stone quoins, belt course, keystone lintels and arched second-floor windows; a hexastyle giant-order portico with a pediment '
                       'and oculus over a broad flight of granite steps; slate hip roof; a white cupola with four clock faces (no numerals), an '
                       'octagonal colonnaded lantern and a verdigris copper dome. The site-specs method puts the front toward %s (heading %.1f), '
                       'not Second Street (its address); the Atlas building is %s x %s m with the long side running back from the street.'
                       % (s['street'], s['front_heading_deg_atlas'], s['footprint_m'][0], s['footprint_m'][1])))
    return [o], meta


# ============================================================================ Carnegie Library

def build_library(A):
    wp.reset(); L = Lib()
    s = site(A, 4)
    W, D = s['footprint_m']
    hw, hd = W / 2, D / 2
    g = G()
    T = 'TrimStone'
    x0, x1, y0, y1 = -hw + 0.45, hw - 0.45, -hd + 3.6, hd - 0.45
    fz, zp = 1.7, 7.8
    aw = dict(rail=True, mull=2, rd=0.25, sill='TrimStone', lintel='TrimStone', T='Trim')
    ops = {'S': [('a', x, 2.0, fz + 1.0, zp - 1.0, aw) for x in (-11.2, -7.6, 7.6, 11.2)] +
                [('d', 0.0, 2.0, fz, fz + 2.9, dict(pair=True, rd=0.12, D='Bronze', T='TrimStone', lite=True))],
           'E': [('a', y, 2.0, fz + 1.0, zp - 1.0, aw) for y in (-4.0, 0.2, 4.4)],
           'W': [('a', y, 2.0, fz + 1.0, zp - 1.0, aw) for y in (-4.0, 0.2, 4.4)],
           'N': [('w', x, 1.6, fz + 1.4, zp - 1.4, dict(rail=True, mull=1, rd=0.2, sill='TrimStone', lintel='TrimStone')) for x in (-10.0, -4.0, 4.0, 10.0)]}
    body(g, x0, x1, y0, y1, fz, zp, ops, wmat='BrickBuff', found=None, corners=False)
    box(g, 'Ashlar', x0 - 0.15, x1 + 0.15, y0 - 0.15, y1 + 0.15, ZF, fz, skip='b')
    box(g, T, x0 - 0.22, x1 + 0.22, y0 - 0.22, y1 + 0.22, fz - 0.08, fz + 0.12, skip='')
    # basement windows
    for k in ('S', 'E', 'W', 'N'):
        F, u0, u1, sgn = sides(x0 - 0.15, x1 + 0.15, y0 - 0.15, y1 + 0.15)[k]
        for op in ops[k]:
            u = op[1] * sgn
            fq(g, F, 'Glass', u - 0.55, u + 0.55, 0.4, 1.2, 0.005)
            fbox(g, F, T, u - 0.65, u + 0.65, 0.3, 0.4, 0, 0.06)
    # stone pilasters at the corners, entablature, dentil-less cornice and a balustraded parapet
    for cx_ in (x0, x1):
        for cy_ in (y0, y1):
            box(g, T, cx_ - 0.45, cx_ + 0.45, cy_ - 0.45, cy_ + 0.45, fz + 0.12, zp, skip='b')
    box(g, T, x0 - 0.2, x1 + 0.2, y0 - 0.2, y1 + 0.2, zp, zp + 0.9, skip='b')
    box(g, T, x0 - 0.5, x1 + 0.5, y0 - 0.5, y1 + 0.5, zp + 0.9, zp + 1.2, skip='')
    pz = zp + 1.2
    box(g, T, x0 - 0.2, x1 + 0.2, y0 - 0.2, y1 + 0.2, pz, pz + 0.18, skip='b')
    for (ax, ay, bx, by) in ((x0 - 0.1, y0 - 0.1, x1 + 0.1, y0 - 0.1), (x1 + 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1),
                             (x1 + 0.1, y1 + 0.1, x0 - 0.1, y1 + 0.1), (x0 - 0.1, y1 + 0.1, x0 - 0.1, y0 - 0.1)):
        Ln = math.hypot(bx - ax, by - ay); n = int(Ln / 0.32)
        for i in range(n):
            t = (i + 0.5) / n
            lathe(g, T, ax + (bx - ax) * t, ay + (by - ay) * t, [(0.09, pz + 0.18), (0.12, pz + 0.3), (0.07, pz + 0.55), (0.09, pz + 0.7)], n=6)
    box(g, T, x0 - 0.25, x1 + 0.25, y0 - 0.25, y1 + 0.25, pz + 0.7, pz + 0.85, skip='')
    box(g, 'Roofing', x0, x1, y0, y1, pz - 0.2, pz - 0.15, skip='b')
    for xp in (x0 + 0.2, x1 - 0.4):
        pass
    # low copper saucer dome on a drum over the reading room
    lathe(g, 'BrickBuff', 0, 0.5, [(3.2, pz - 0.2), (3.2, pz + 0.9)], n=24, cap_top=False)
    lathe(g, T, 0, 0.5, [(3.35, pz + 0.9), (3.45, pz + 1.15), (3.2, pz + 1.15)], n=24, cap_top=False)
    prof = [(3.2, pz + 1.15)]
    for k in range(1, 7):
        a = math.pi / 2 * k / 7
        prof.append((3.2 * math.cos(a), pz + 1.15 + 1.5 * math.sin(a)))
    prof.append((0.0, pz + 2.65))
    lathe(g, 'Copper', 0, 0.5, prof, n=24)
    # entry pavilion: projecting, pedimented, two Ionic-ish columns in antis, bronze doors
    ex0, ex1 = -4.6, 4.6
    ey0 = y0 - 1.0
    box(g, 'Ashlar', ex0 - 0.15, ex1 + 0.15, ey0 - 0.15, y0, ZF, fz, skip='bn')
    for xa, xb in ((ex0, ex0 + 1.5), (ex1 - 1.5, ex1)):
        box(g, 'BrickBuff', xa, xb, ey0, y0, fz, zp, skip='bn')
        box(g, T, xa - 0.05, xb + 0.05, ey0 - 0.05, y0, fz, fz + 0.4, skip='bn')
        for zq in (2.6, 3.9, 5.2, 6.5):
            box(g, T, xa - 0.04, xb + 0.04, ey0 - 0.04, ey0 + 0.3, zq, zq + 0.35, skip='')
    for x in (-1.45, 1.45):
        column(g, x, ey0 + 0.45, fz, zp, 0.36, n=14)
    box(g, T, ex0 - 0.1, ex1 + 0.1, ey0 - 0.1, y0, zp, zp + 1.2, skip='n')
    pediment(g, ex0 - 0.2, ex1 + 0.2, ey0 - 0.3, y0 + 0.5, zp + 1.2, 21, 'Copper', tymp=T, T=T)
    # recessed entry wall with bronze doors and a lunette window
    Fe = Fr((0, y0, 0), (1, 0, 0))
    fq(g, Fe, 'Glass', -1.0, 1.0, fz + 3.3, fz + 4.6, 0.01)
    fbox(g, Fe, T, -1.15, 1.15, fz + 4.6, fz + 4.85, 0, 0.1)
    box(g, T, ex0 + 1.5, ex1 - 1.5, ey0 + 0.1, y0, fz - 0.02, fz, skip='b')
    # steps and lamp standards on the cheek blocks
    steps_y(g, T, -3.0, 3.0, ey0 - 0.15, fz, 8, tread=0.3)
    sy0 = ey0 - 0.15 - 8 * 0.3
    for x in (-3.55, 3.55):
        g.poly([(x - 0.5, sy0, ZF), (x + 0.5, sy0, ZF), (x + 0.5, sy0, 0.7), (x - 0.5, sy0, 0.7)], 'Ashlar', (0, -1, 0))
        box(g, 'Ashlar', x - 0.5, x + 0.5, sy0, ey0 - 0.15, ZF, 0.7, skip='bs')
        box(g, 'Ashlar', x - 0.5, x + 0.5, sy0 + 1.2, ey0 - 0.15, 0.7, fz, skip='b')
        box(g, T, x - 0.58, x + 0.58, sy0 - 0.05, sy0 + 1.0, 0.7, 0.85, skip='b')
        lathe(g, 'Bronze', x, sy0 + 0.5, [(0.18, 0.85), (0.1, 1.1), (0.06, 1.3), (0.05, 2.5), (0.09, 2.6)], n=8)
        lathe(g, 'Lamp', x, sy0 + 0.5, [(0.0, 2.6), (0.2, 2.72), (0.24, 2.9), (0.2, 3.08), (0.0, 3.18)], n=10)
    o = soup_obj(g, 'CarnegieLibrary', L)
    meta = dict(id='carnegie-library', name='Carnegie Library (1912)', file='models/landmarks/carnegie-library.glb', address='285 Third Street', status='Canon 2',
                atlas=dict(building_index=s['building_index'], center_atlas=s['center_atlas'], front_heading_deg_atlas=s['front_heading_deg_atlas'],
                           footprint_m=s['footprint_m'], atlas_kind=s['atlas_kind'], atlas_height_m=s['atlas_height_m'], street=s['street'],
                           curb_line_local_y=s['curb_line_local_y']),
                height_m=round(pz + 2.65, 2),
                notes=('Interpretation (no reference image): a small 1912 Beaux-Arts Carnegie library in buff brick on a raised ashlar base; '
                       'a projecting pedimented entry pavilion with two columns in antis, bronze doors and a lunette over a flight of eight steps '
                       'with lamp standards; tall arched windows with stone keystones; stone corner pilasters, entablature, a balustraded parapet and '
                       'a low verdigris dome over the reading room. The site-specs method puts the front toward %s (heading %.1f) although the '
                       'address is on Third Street.' % (s['street'], s['front_heading_deg_atlas'])))
    return [o], meta


BUILDERS = [('water-tower', build_water_tower), ('pier-bar', build_pier_bar), ('williams-funeral-home', build_funeral),
            ('chadwicks', build_chadwicks), ('courthouse', build_courthouse), ('carnegie-library', build_library)]

# camera presets per landmark: (eye, target, lens) in the model frame (front = -Y)
CAMS = {'water-tower': ((21, -42, 2.0), (0, 0, 21.5), 28), 'pier-bar': ((-17, -24, 5.5), (0, 0, 2.6), 30),
        'williams-funeral-home': ((-20, -30, 4.0), (0, 0, 4.8), 30), 'chadwicks': ((-11, -21, 2.2), (0, -3, 2.2), 30),
        'courthouse': ((-36, -58, 7.0), (0, -4, 10), 30), 'carnegie-library': ((-20, -30, 3.0), (0, -2, 5.0), 30)}


def render_scene(lid, objs, out, res, samples):
    """Render one model in its own scene: lawn (or water for the pier), a road strip at the curb."""
    wp.render_rig(samples=samples, res=res, threads=2, sun_elev=34, sun_az=215, ground=(lid != 'pier-bar'), ground_size=600)
    if lid == 'pier-bar':
        wm = wp.mat('RenderWater', '#1f3b44', rough=0.08)
        bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=300)
        wo = wp.obj_from_bmesh('RenderWater', bm, wm); wo.location.z = -0.7
        # the app's pier deck leading in from land (render only)
        dm = M('DeckWood')
        d = wp.box('RenderPier', 3.0, 60, 0.3, loc=(0, -10 - 30, 0.9), material=dm)
        wp.uv_box(d)
    eye, tgt, lens = CAMS[lid]
    wp.camera(eye, tgt, lens=lens)
    wp.render(out)


def contact_sheet(tiles, out, cols=3, rows=2, size=(1600, 1000)):
    tw, th = size[0] // cols, size[1] // rows
    sheet = Image.new('RGB', size, (20, 20, 20))
    for i, p in enumerate(tiles):
        im = Image.open(p).convert('RGB').resize((tw, th), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(out, quality=90)
    print('contact sheet', out)


if __name__ == '__main__':
    only = ARGS[ARGS.index('--only') + 1].split(',') if '--only' in ARGS else None
    A = atlas()
    os.makedirs(OUT, exist_ok=True)
    tile = tuple(int(v) for v in os.environ.get('WP_TILE', '534x500').split('x'))
    tiles = []
    for lid, fn in BUILDERS:
        if only and lid not in only:
            tp = os.path.join(TEX, 'tiles', f'tile-{lid}.jpg')
            if os.path.exists(tp) and not PREVIEW:
                tiles.append(tp)     # keep the earlier final tile for the sheet
            continue
        MATS.clear()
        objs, meta = fn(A)
        finish(lid, objs, meta)
        if '--no-render' in ARGS:
            continue
        tdir = TEX if PREVIEW else os.path.join(TEX, 'tiles')
        os.makedirs(tdir, exist_ok=True)
        tp = os.path.join(tdir, f'tile-{lid}.jpg')
        render_scene(lid, objs, tp, tile, SAMPLES)
        tiles.append(tp)
        if lid == 'water-tower' and not PREVIEW and '--tile-only' not in ARGS:
            wp.reset(); MATS.clear()
            objs, meta = fn(A)
            wp.finalize(objs)
            wp.render_rig(samples=SAMPLES, res=(1600, 1000), threads=2, sun_elev=34, sun_az=215, ground_size=800)
            wp.camera((30, -62, 1.7), (0, 0, 20.5), lens=28)
            wp.render(os.path.join(RENDERS, 'water-tower.jpg'))
    if len(tiles) == len(BUILDERS):
        contact_sheet(tiles, os.path.join(RENDERS, 'landmarks.jpg') if not PREVIEW else os.path.join(TEX, 'landmarks-preview.jpg'))
