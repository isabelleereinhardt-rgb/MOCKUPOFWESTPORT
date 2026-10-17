#!/usr/bin/env python3
"""Mobile-home archetypes for the park instancing (Atlas kind 'mobile', 3,128 footprints, mostly 5 x 19 m).

    mobile-single-a  an older single-wide: bowed metal roof with cross seams, two-tone lap aluminum siding,
                     ribbed skirting, window AC, wooden steps with a small landing and rail
    mobile-single-b  an older, rustier 1970s single-wide: rounder roof with streaky (rust) shading, a stripe
                     band, an aluminum door awning, plain wooden steps
    mobile-single-c  a newer single-wide: 3:12 shingled gable roof with overhangs, vinyl lap siding,
                     shutters, a landing with steps and railing
    mobile-double    a double-wide (about 9 x 18 m): 4:12 shingled gable roof, vinyl siding, shutters,
                     two doors, block-look skirting, a landing with steps

Archetype rules (docs/ASSET-SPEC.md): long axis along Blender Y, the lane end at -Y, the entry steps on
the -X long side; the full XY bounding box (steps included) is centred on the origin and recorded
exactly as bbox_m [w, d, h] (h = top above grade; skirting runs to z = -0.6). Materials are exactly
Wall, Roof, Trim, Glass, Door and Masonry; Wall and Roof are near-white / light grey with shading detail
only, because the map tints them per instance (Door too). Under 2,500 triangles each.

Run:  WP_TEX_DIR=/some/scratch python3 tools/blender/archetypes/mobile.py [--no-render] [--quick --out DIR]
Writes models/archetypes/mobile-*.glb, models/archetypes/index-mobile.json and renders/mobile-archetypes.jpg.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import wp  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

REPO = wp.REPO
ADIR = os.path.join(REPO, 'models', 'archetypes')
MAT = {}
TRI_BUDGET = 2500


# ============================================================================ mesh builder
class Fr:
    """Wall frame: u along U (to the right seen from outside), z up, d along N (outward)."""

    def __init__(self, O, N):
        self.O = Vector(O)
        self.N = Vector(N).normalized()
        self.Z = Vector((0, 0, 1))
        self.U = self.Z.cross(self.N)

    def p(self, u, z, d=0.0):
        return self.O + self.U * u + self.Z * z + self.N * d


class _World:
    U, Z, N = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

    def p(self, u, z, d=0.0):
        return Vector((u, z, d))


WORLD = _World()


class Geo:
    def __init__(self, name):
        self.name = name
        self.V, self.F, self.FM = [], [], []

    def add(self, verts, faces, mat):
        b = len(self.V)
        self.V.extend(Vector(v) for v in verts)
        for f in faces:
            self.F.append(tuple(b + i for i in f))
            self.FM.append(mat)

    def tris(self):
        return sum(len(f) - 2 for f in self.F)

    def bounds(self):
        xs = [v.x for v in self.V]
        ys = [v.y for v in self.V]
        zs = [v.z for v in self.V]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def shift(self, dx, dy):
        for v in self.V:
            v.x += dx
            v.y += dy

    def build(self, name=None):
        mats = list(dict.fromkeys(self.FM))
        me = bpy.data.meshes.new(name or self.name)
        me.from_pydata([tuple(v) for v in self.V], [], self.F)
        for m in mats:
            me.materials.append(MAT[m])
        idx = {m: i for i, m in enumerate(mats)}
        me.polygons.foreach_set('material_index', [idx[m] for m in self.FM])
        me.validate()
        me.update()
        o = bpy.data.objects.new(name or self.name, me)
        bpy.context.scene.collection.objects.link(o)
        return o


def newell(pts):
    n = Vector((0, 0, 0))
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n


def poly(g, mat, pts, facing=None):
    pts = [Vector(p) for p in pts]
    if facing is not None and newell(pts).dot(Vector(facing)) < 0:
        pts = pts[::-1]
    g.add(pts, [list(range(len(pts)))], mat)


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def extrude(g, mat, F, pts, d0, d1, back=False, bottom=True):
    """Polygon [(u, z)] in frame F extruded along F.N from d0 to d1 (back cap optional)."""
    if _area(pts) < 0:
        pts = pts[::-1]
    if d1 < d0:
        d0, d1 = d1, d0
    n = len(pts)
    V = [F.p(u, z, d0) for u, z in pts] + [F.p(u, z, d1) for u, z in pts]
    faces = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    if not bottom and F is WORLD:
        pass
    faces.append(list(range(n, 2 * n)))
    if back:
        faces.append(list(range(n))[::-1])
    g.add(V, faces, mat)


def fbox(g, mat, F, u0, u1, z0, z1, d0, d1, back=False):
    if u1 - u0 <= 1e-5 or z1 - z0 <= 1e-5 or abs(d1 - d0) <= 1e-5:
        return
    extrude(g, mat, F, [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], d0, d1, back=back)


def box(g, mat, x0, x1, y0, y1, z0, z1, bottom=False):
    """World box; the bottom face is left out unless asked for (nothing sees it)."""
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    F = [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    if bottom:
        F.append([3, 2, 1, 0])
    g.add(V, F, mat)


def cbox(g, mat, cx, cy, sx, sy, z0, z1):
    box(g, mat, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1)


def cyl(g, mat, cx, cy, r, z0, z1, seg=8):
    V = [(cx + r * math.cos(2 * math.pi * i / seg), cy + r * math.sin(2 * math.pi * i / seg), z) for z in (z0, z1)
         for i in range(seg)]
    F = [[i, (i + 1) % seg, seg + (i + 1) % seg, seg + i] for i in range(seg)] + [[seg + i for i in range(seg)]]
    g.add(V, F, mat)


# ============================================================================ textures (neutral, shading only)
def _blur1(a, k, axis):
    if k <= 1:
        return a
    c = np.cumsum(np.concatenate([a, np.take(a, range(k), axis=axis)], axis=axis), axis=axis)
    lo = np.take(c, range(0, a.shape[axis]), axis=axis)
    hi = np.take(c, range(k, a.shape[axis] + k), axis=axis)
    return (hi - lo) / k


def streaks(n, rng, along, across, axis):
    r = rng.random((n, n)).astype(np.float32)
    s = _blur1(_blur1(r, along, axis), across, 1 - axis)
    s = _blur1(s, max(1, along // 3), axis)
    return (s - s.min()) / (s.max() - s.min() + 1e-6)


def tex_wall(key, exposure=0.2, n=1024, tile=3.2, seed=3, bands=(), rain=0.05, base=0.93):
    """Lap siding in neutral light grey. The tile spans the whole wall height (UV v = z / tile), so
    horizontal bands are baked as luminance: bands = [(z0, z1, factor), ...] in meters above grade."""
    rng = np.random.default_rng(seed)
    px = n / tile
    rows = int(round(tile / exposure))
    exposure = tile / rows
    r = np.arange(n, dtype=np.float32)[:, None]
    vm = np.broadcast_to((n - 1 - r) / px, (n, n))
    t = (vm % exposure) / exposure
    grain = streaks(n, rng, 40, 2, axis=1)
    rainm = streaks(n, rng, 120, 5, axis=0)
    shade = 0.84 + 0.16 * np.clip(t / 0.1, 0, 1)
    shade = np.where(t < 0.03, 0.55, shade)
    lum = base * shade * (0.975 + 0.05 * grain) * (1 - rain * np.clip((rainm - 0.55) * 3.5, 0, 1))
    for z0, z1, f in bands:
        lum = np.where((vm >= z0) & (vm < z1), lum * f, lum)
    # grime toward the bottom of the wall
    lum = lum * (1 - 0.1 * np.clip(1 - (vm - 0.75) / 0.5, 0, 1))
    alb = np.repeat(lum[..., None], 3, axis=2)
    h = (1 - t) * 0.6 + grain * 0.04
    h = np.where(t < 0.03, 0.0, h)
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 2.4), key + '_n'), tile


def tex_metal_roof(key, n=1024, tile=4.8, seam=1.2, seed=9, streak=0.0, base=0.88):
    """Bowed metal roof from above (u = x across, v = y along): seam lines every `seam` m, mottled coating,
    and (streak > 0) darker down-slope streaks and seam blotches that read as rust once tinted."""
    rng = np.random.default_rng(seed)
    px = n / tile
    r = np.arange(n, dtype=np.float32)[:, None]
    vm = np.broadcast_to((n - 1 - r) / px, (n, n))
    ds = np.abs(((vm + seam / 2) % seam) - seam / 2)
    mid = wp._noise(n, 14, rng, 3)
    big = wp._noise(n, 4, rng, 4)
    sl = streaks(n, rng, 180, 3, axis=1)
    lum = base * (0.9 + 0.12 * mid) * (1 - 0.18 * np.exp(-(ds / 0.012) ** 2))
    worn = np.clip((big * 0.7 + mid * 0.5 - 0.66) * 3.0, 0, 1)
    lum = lum * (1 - 0.12 * worn)
    if streak:
        rm = np.clip((np.exp(-(ds / 0.08) ** 2) * (0.5 + 0.8 * mid) + np.clip((sl - 0.55) * 3, 0, 1) * (0.4 + mid)
                      + np.clip((big - 0.65) * 3, 0, 1) - (1 - streak)) * 1.5, 0, 1)
        lum = lum * (1 - 0.45 * rm)
    alb = np.repeat(lum[..., None], 3, axis=2)
    h = np.exp(-(ds / 0.012) ** 2)
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 1.2), key + '_n'), tile


def tex_shingle_neutral(key, n=1024, tile=3.0, seed=31):
    a, nrm, tile = wp.tex_shingles(key, color='#d4d4d4', n=n, tile=tile, seed=seed)
    return a, nrm, tile


def tex_skirt(key, n=512, tile=2.0, seed=5, color='#cbc7bd'):
    rng = np.random.default_rng(seed)
    px = n / tile
    x = np.arange(n, dtype=np.float32)[None, :] / px
    pw = tile / int(round(tile / 0.4))
    lx = np.broadcast_to(x % pw, (n, n))
    rib = (np.abs(((lx / pw) * 4) % 1 - 0.5) < 0.06)
    joint = lx < 0.006
    nz = wp._noise(n, 6 * tile, rng, 3)
    r = np.arange(n, dtype=np.float32)[:, None]
    vm = np.broadcast_to((n - 1 - r) / px, (n, n))
    dirt = 1 - 0.25 * np.clip(1 - vm / 0.35, 0, 1)        # splash dirt at grade (v = z / tile, grade at 0)
    shade = np.where(rib, 0.86, 1.0) * np.where(joint, 0.62, 1.0) * (0.95 + 0.07 * nz) * dirt
    alb = wp._rgb(color)[None, None, :] * shade[..., None]
    h = np.where(rib, 1.0, 0.0) * 0.5 - joint * 0.6
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 1.6), key + '_n'), tile


def tex_block(key, n=512, tile=1.6, seed=6, color='#bdb9b1'):
    """Painted concrete-block skirting: 0.4 x 0.2 m blocks, running bond."""
    rng = np.random.default_rng(seed)
    px = n / tile
    r = np.arange(n, dtype=np.float32)[:, None]
    c = np.arange(n, dtype=np.float32)[None, :]
    vm = np.broadcast_to((n - 1 - r) / px, (n, n))
    um = np.broadcast_to(c / px, (n, n))
    row = (vm // 0.2).astype(int)
    lu = (um + (row % 2) * 0.2) % 0.4
    lv = vm % 0.2
    joint = (lu < 0.01) | (lv < 0.01)
    nz = wp._noise(n, 20, rng, 3)
    dirt = 1 - 0.22 * np.clip(1 - vm / 0.3, 0, 1)
    shade = np.where(joint, 0.72, 1.0) * (0.92 + 0.12 * nz) * dirt
    alb = wp._rgb(color)[None, None, :] * shade[..., None]
    return wp._save(alb, key), wp._save(wp._normal_from_height(1 - joint * 1.0 + nz * 0.2, 1.5), key + '_n'), tile


def make_materials(aid, kind):
    """Exactly the six archetype materials, with per-archetype textures."""
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)
    MAT.clear()
    k = aid.replace('mobile-', 'mh_')
    if kind == 'a':
        wall = tex_wall(k + '_wall', bands=[(0.0, 1.55, 0.8)], seed=3)
        roof = tex_metal_roof(k + '_roof', streak=0.25, seed=9)
        mas = tex_skirt(k + '_skirt')
    elif kind == 'b':
        wall = tex_wall(k + '_wall', exposure=0.25, bands=[(2.42, 2.6, 0.62)], seed=4, rain=0.09, base=0.9)
        roof = tex_metal_roof(k + '_roof', streak=0.75, seed=10, base=0.84)
        mas = tex_skirt(k + '_skirt', color='#c2bdb2', seed=7)
    elif kind == 'c':
        wall = tex_wall(k + '_wall', exposure=0.178, seed=5, rain=0.02, base=0.95)
        roof = tex_shingle_neutral(k + '_roof', seed=31)
        mas = tex_skirt(k + '_skirt', color='#d2cfc6', seed=8)
    else:
        wall = tex_wall(k + '_wall', exposure=0.178, seed=6, rain=0.02, base=0.95)
        roof = tex_shingle_neutral(k + '_roof', seed=33)
        mas = tex_block(k + '_block')
    MAT['Wall'] = wp.mat('Wall', tex=wall, rough=0.5)
    MAT['Roof'] = wp.mat('Roof', tex=roof, rough=0.6 if kind in 'ab' else 0.85, metal=0.2 if kind in 'ab' else 0.0)
    MAT['Trim'] = wp.mat('Trim', '#e9e9e4', rough=0.45)
    MAT['Glass'] = wp.mat('Glass', '#262c31', rough=0.08)
    MAT['Door'] = wp.mat('Door', '#e6e6e2', rough=0.45)
    MAT['Masonry'] = wp.mat('Masonry', tex=mas, rough=0.8)


# ============================================================================ parts
def window(g, F, uc, sill, w, h, shutters=False, fw=0.05):
    """Glass pane on the wall face with a proud frame (no hole; reads the same from 50 m+)."""
    u0, u1, z0, z1 = uc - w / 2, uc + w / 2, sill, sill + h
    poly(g, 'Glass', [F.p(u0, z0, 0.006), F.p(u1, z0, 0.006), F.p(u1, z1, 0.006), F.p(u0, z1, 0.006)], facing=F.N)
    fbox(g, 'Trim', F, u0 - fw, u1 + fw, z0 - fw, z0, 0, 0.035)
    fbox(g, 'Trim', F, u0 - fw, u1 + fw, z1, z1 + fw, 0, 0.035)
    fbox(g, 'Trim', F, u0 - fw, u0, z0, z1, 0, 0.035)
    fbox(g, 'Trim', F, u1, u1 + fw, z0, z1, 0, 0.035)
    zm = z0 + h / 2
    fbox(g, 'Trim', F, u0, u1, zm - 0.02, zm + 0.02, 0, 0.02)
    if shutters:
        sw = min(0.38, h * 0.36)
        for s in (-1, 1):
            a = uc + s * (w / 2 + fw + 0.03)
            b = a + s * sw
            fbox(g, 'Door', F, min(a, b), max(a, b), z0 - fw, z1 + fw, 0, 0.03)


def door(g, F, uc, z0, w=0.86, h=1.95, storm=True):
    u0, u1 = uc - w / 2, uc + w / 2
    poly(g, 'Door', [F.p(u0, z0, 0.008), F.p(u1, z0, 0.008), F.p(u1, z0 + h, 0.008), F.p(u0, z0 + h, 0.008)], facing=F.N)
    fbox(g, 'Trim', F, u0 - 0.06, u0, z0, z0 + h + 0.06, 0, 0.04)
    fbox(g, 'Trim', F, u1, u1 + 0.06, z0, z0 + h + 0.06, 0, 0.04)
    fbox(g, 'Trim', F, u0, u1, z0 + h, z0 + h + 0.06, 0, 0.04)
    if storm:
        poly(g, 'Glass', [F.p(u0 + 0.06, z0 + 0.95, 0.03), F.p(u1 - 0.06, z0 + 0.95, 0.03), F.p(u1 - 0.06, z0 + h - 0.06, 0.03),
                          F.p(u0 + 0.06, z0 + h - 0.06, 0.03)], facing=F.N)
    else:
        poly(g, 'Glass', [F.p(uc - 0.17, z0 + 1.4, 0.012), F.p(uc + 0.17, z0 + 1.4, 0.012), F.p(uc + 0.17, z0 + 1.7, 0.012),
                          F.p(uc - 0.17, z0 + 1.7, 0.012)], facing=F.N)


def bowed_roof(g, W, L, eave, crown, ovs=0.06, ove=0.05, nx=8, edge=0.09):
    hw = W / 2 + ovs
    ya, yb = -L / 2 - ove, L / 2 + ove

    def rz(x):
        t = max(-1.0, min(1.0, x / hw))
        return eave + 0.03 + crown * (1 - t * t)
    xs = [-hw + 2 * hw * i / nx for i in range(nx + 1)]
    V = [(x, y, rz(x)) for y in (ya, yb) for x in xs]
    F = [[i, i + 1, nx + 2 + i, nx + 1 + i] for i in range(nx)]
    g.add(V, F, 'Roof')
    # rolled edges: sides and ends
    for s in (-1, 1):
        box(g, 'Trim', s * hw, s * (hw + 0.02), ya, yb, eave - edge + 0.03, rz(s * hw) + 0.01)
    for s, y in ((-1, ya), (1, yb)):
        Vs = []
        for x in xs:
            Vs += [(x, y, rz(x) - edge), (x, y, rz(x) + 0.01)]
        Fs = [[2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1] if s < 0 else [2 * i + 1, 2 * i + 3, 2 * i + 2, 2 * i]
              for i in range(nx)]
        g.add(Vs, Fs, 'Trim')
    return rz


def gable_roof(g, W, L, eave, pitch, ovs=0.25, ove=0.18, th=0.14):
    """Shingled gable roof, ridge along Y; fascia and rake boards in Trim."""
    t = math.tan(math.radians(pitch))
    hw = W / 2 + ovs
    ya, yb = -L / 2 - ove, L / 2 + ove
    ze = eave - ovs * t                       # roof surface at the drip edge
    zr = eave + (W / 2) * t
    # roof planes (top surfaces)
    for s in (-1, 1):
        poly(g, 'Roof', [(s * hw, ya, ze), (s * hw, yb, ze), (0, yb, zr), (0, ya, zr)], facing=(s * t, 0, 1))
        # fascia (vertical board at the eave)
        poly(g, 'Trim', [(s * hw, ya, ze - th), (s * hw, yb, ze - th), (s * hw, yb, ze), (s * hw, ya, ze)], facing=(s, 0, 0))
        # soffit
        poly(g, 'Trim', [(s * hw, ya, ze - th), (s * hw, yb, ze - th), (s * W / 2, yb, ze - th + 0.0), (s * W / 2, ya, ze - th)],
             facing=(0, 0, -1))
    for y, sy in ((ya, -1), (yb, 1)):
        # rake boards (gable end edge band) and the roof underside at the overhang
        for s in (-1, 1):
            poly(g, 'Trim', [(s * hw, y, ze - th), (0, y, zr - th), (0, y, zr), (s * hw, y, ze)], facing=(0, sy, 0))
            yi = y - sy * ove
            poly(g, 'Trim', [(s * hw, y, ze - th), (0, y, zr - th), (0, yi, zr - th), (s * hw, yi, ze - th)], facing=(0, 0, -1))
    return zr


def gable_wall(g, F, u0, u1, z0, zr):
    poly(g, 'Wall', [F.p(u0, z0), F.p(u1, z0), F.p((u0 + u1) / 2, zr)], facing=F.N)


def walls_box(g, W, L, zb, zt):
    fr = {
        'W': (Fr((-W / 2, 0, 0), (-1, 0, 0)), -L / 2, L / 2),
        'E': (Fr((W / 2, 0, 0), (1, 0, 0)), -L / 2, L / 2),
        'S': (Fr((0, -L / 2, 0), (0, -1, 0)), -W / 2, W / 2),
        'N': (Fr((0, L / 2, 0), (0, 1, 0)), -W / 2, W / 2),
    }
    for k, (F, a, b) in fr.items():
        poly(g, 'Wall', [F.p(a, zb), F.p(b, zb), F.p(b, zt), F.p(a, zt)], facing=F.N)
    return {k: v[0] for k, v in fr.items()}


def skirting(g, W, L, zt, inset=0.03):
    hw, hl = W / 2 - inset, L / 2 - inset
    for F, a, b in ((Fr((-hw, 0, 0), (-1, 0, 0)), -hl, hl), (Fr((hw, 0, 0), (1, 0, 0)), -hl, hl),
                    (Fr((0, -hl, 0), (0, -1, 0)), -hw, hw), (Fr((0, hl, 0), (0, 1, 0)), -hw, hw)):
        poly(g, 'Masonry', [F.p(a, -0.6), F.p(b, -0.6), F.p(b, zt), F.p(a, zt)], facing=F.N)
        fbox(g, 'Trim', F, a, b, zt - 0.05, zt, 0, 0.02)


def corner_trim(g, W, L, zb, zt):
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * W / 2, sy * L / 2
            box(g, 'Trim', x, x + sx * 0.02, y - sy * 0.08, y + sy * 0.0, zb, zt)
            box(g, 'Trim', x - sx * 0.08, x, y, y + sy * 0.02, zb, zt)


def steps_parallel(g, x_wall, y_land0, y_land1, top, n_rise=4, width=0.95, depth=1.3, rail=True):
    """Wooden landing against the -X wall plus a stair descending toward -Y along the wall."""
    xl = x_wall - depth
    box(g, 'Masonry', xl, x_wall, y_land0, y_land1, top - 0.2, top)
    for (px, py) in ((xl + 0.05, y_land0 + 0.05), (xl + 0.05, y_land1 - 0.05)):
        cbox(g, 'Masonry', px, py, 0.1, 0.1, 0.0, top - 0.2)
    rise = top / n_rise
    run = 0.27
    sx0, sx1 = x_wall - width, x_wall
    for k in range(n_rise - 1):
        zt = top - rise * (k + 1)
        y1 = y_land0 - k * run
        box(g, 'Masonry', sx0, sx1, y1 - run, y1, zt - rise, zt)
    yb = y_land0 - (n_rise - 1) * run
    if rail:
        rt = top + 0.92
        # landing rail (outer side + far end) and the raked stair rail
        box(g, 'Masonry', xl, xl + 0.07, y_land0, y_land1, rt - 0.07, rt)
        box(g, 'Masonry', xl, x_wall, y_land1 - 0.07, y_land1, rt - 0.07, rt)
        for (px, py) in ((xl + 0.035, y_land0 + 0.035), (xl + 0.035, y_land1 - 0.035), (x_wall - 0.06, y_land1 - 0.035)):
            cbox(g, 'Masonry', px, py, 0.08, 0.08, top, rt)
        # baluster panels (thin slabs read as balusters from a distance)
        box(g, 'Masonry', xl + 0.02, xl + 0.045, y_land0 + 0.05, y_land1 - 0.05, top + 0.1, rt - 0.12)
        box(g, 'Masonry', xl + 0.05, x_wall - 0.08, y_land1 - 0.045, y_land1 - 0.02, top + 0.1, rt - 0.12)
        xr = sx0 + 0.035
        V = [(xr - 0.035, y_land0, rt - 0.07), (xr + 0.035, y_land0, rt - 0.07), (xr + 0.035, y_land0, rt),
             (xr - 0.035, y_land0, rt), (xr - 0.035, yb, 0.85), (xr + 0.035, yb, 0.85), (xr + 0.035, yb, 0.92),
             (xr - 0.035, yb, 0.92)]
        g.add(V, [[3, 2, 6, 7], [0, 3, 7, 4], [1, 5, 6, 2], [0, 4, 5, 1]], 'Masonry')
        cbox(g, 'Masonry', xr, yb + 0.04, 0.08, 0.08, 0.0, 0.92)
    return yb


def ac(g, F, uc, sill):
    fbox(g, 'Trim', F, uc - 0.29, uc + 0.29, sill, sill + 0.37, 0, 0.42)


# ============================================================================ archetypes
def build_single(kind):
    g = Geo('House')
    W, L = 4.27, 18.9
    FL, SB = 0.80, 0.74
    if kind == 'a':
        eave, crown = 2.96, 0.17
    elif kind == 'b':
        eave, crown = 2.90, 0.24
    else:
        eave, crown = 2.96, 0.0
    F = walls_box(g, W, L, SB, eave)
    skirting(g, W, L, SB + 0.02)
    corner_trim(g, W, L, SB, eave)
    if kind in ('a', 'b'):
        rz = bowed_roof(g, W, L, eave, crown, ovs=0.06, ove=0.05)
        for k, sgn in (('S', 1), ('N', -1)):
            n = 8
            pts = [F[k].p(-W / 2, eave)] + [F[k].p(-W / 2 + W * i / n, rz((-W / 2 + W * i / n) * sgn) - 0.03)
                                            for i in range(n + 1)] + [F[k].p(W / 2, eave)]
            poly(g, 'Wall', pts, facing=F[k].N)
        top = rz(0) + 0.01
        # furnace roof jack and a vent
        cyl(g, 'Trim', 0.3, -1.5, 0.07, rz(0.3) - 0.02, rz(0.3) + 0.35)
        cyl(g, 'Trim', 0.3, -1.5, 0.13, rz(0.3) + 0.35, rz(0.3) + 0.46)
        box(g, 'Trim', -0.6, -0.25, 4.6, 4.95, rz(-0.4) - 0.02, rz(-0.4) + 0.12)
    else:
        zr = gable_roof(g, W, L, eave, 14.0, ovs=0.22, ove=0.15)
        for k in ('S', 'N'):
            gable_wall(g, F[k], -W / 2, W / 2, eave, zr - 0.02)
        # gable vents
        for k in ('S', 'N'):
            fbox(g, 'Trim', F[k], -0.18, 0.18, eave + 0.12, eave + 0.38, 0, 0.03)
        top = zr
    # windows: west (-X, entry side), east, ends. u on W wall = -y, E wall = y, S = x, N = -x
    sh = kind == 'c'
    if kind == 'a':
        wins_w = [(-7.0, 0.92, 1.6, 1.05), (-0.6, 0.92, 1.85, 0.78), (5.4, 0.6, 2.1, 0.5), (7.6, 0.92, 1.6, 1.05)]
        wins_e = [(-7.2, 1.2, 1.6, 1.05), (-2.4, 0.92, 1.6, 1.05), (1.7, 0.92, 1.6, 1.05), (4.6, 0.6, 2.1, 0.5),
                  (7.5, 0.92, 1.6, 1.05)]
        doors = [(-3.0, True), (3.4, False)]
    elif kind == 'b':
        wins_w = [(-8.0, 0.8, 1.55, 0.95), (-6.0, 0.8, 1.55, 0.95), (-0.8, 0.8, 1.8, 0.7), (2.3, 0.8, 1.55, 0.95),
                  (5.2, 0.55, 2.0, 0.45), (7.8, 0.8, 1.55, 0.95)]
        wins_e = [(-7.0, 1.6, 1.55, 0.95), (-1.5, 0.8, 1.55, 0.95), (2.0, 0.8, 1.55, 0.95), (5.6, 0.55, 2.0, 0.45),
                  (8.0, 0.8, 1.55, 0.95)]
        doors = [(-3.8, False), (4.0, False)]
    else:
        wins_w = [(-7.3, 1.0, 1.55, 1.12), (-0.4, 1.0, 1.75, 0.9), (5.3, 0.6, 2.05, 0.55), (7.5, 1.0, 1.55, 1.12)]
        wins_e = [(-7.3, 1.0, 1.55, 1.12), (-5.0, 1.0, 1.55, 1.12), (0.0, 1.0, 1.55, 1.12), (4.3, 0.6, 2.05, 0.55),
                  (7.3, 1.0, 1.55, 1.12)]
        doors = [(-2.6, True), (3.3, False)]
    for (y, w, s, h) in wins_w:
        window(g, F['W'], -y, s, w, h, shutters=sh and w > 0.7)
    for (y, w, s, h) in wins_e:
        window(g, F['E'], y, s, w, h, shutters=sh and w > 0.7)
    for x in ((-1.0, 1.0) if kind != 'b' else (0.0,)):
        window(g, F['S'], x, 1.55, 0.92 if kind != 'b' else 1.6, 1.05, shutters=sh)
    window(g, F['N'], 0.0, 1.6, 0.92, 1.0)
    for (y, storm) in doors:
        door(g, F['W'], -y, FL, storm=storm)
    if kind == 'a':
        ac(g, F['W'], 7.0, 1.6)
    if kind == 'b':
        ac(g, F['E'], -1.5, 1.55)
    # entry steps (kept compact: the bbox, steps included, is scaled onto the Atlas rectangle)
    xw = -W / 2 - 0.02
    by = doors[1][0]
    if kind == 'a':
        y0 = doors[0][0] - 0.85
        steps_parallel(g, xw, y0, y0 + 1.7, FL - 0.03, depth=1.0, width=0.85)
    elif kind == 'b':
        y0 = doors[0][0] - 0.8
        steps_parallel(g, xw, y0, y0 + 1.6, FL - 0.03, depth=0.95, width=0.85, rail=False)
        # flat aluminum door awning on two posts over the main landing
        yc = doors[0][0]
        box(g, 'Trim', xw - 0.95, xw, yc - 0.85, yc + 0.85, FL + 2.05, FL + 2.12, bottom=True)
        for yy in (yc - 0.8, yc + 0.8):
            cbox(g, 'Trim', xw - 0.9, yy, 0.05, 0.05, FL - 0.03, FL + 2.05)
    else:
        y0 = doors[0][0] - 0.85
        steps_parallel(g, xw, y0, y0 + 1.7, FL - 0.03, depth=1.0, width=0.85)
    steps_parallel(g, xw, by - 0.5, by + 0.5, FL - 0.04, depth=0.75, width=0.75, rail=False)
    return g


def build_double():
    g = Geo('House')
    W, L = 9.0, 18.3
    FL, SB, eave = 0.78, 0.70, 2.95
    F = walls_box(g, W, L, SB, eave)
    skirting(g, W, L, SB + 0.02)
    corner_trim(g, W, L, SB, eave)
    zr = gable_roof(g, W, L, eave, 18.43, ovs=0.3, ove=0.2, th=0.16)
    for k in ('S', 'N'):
        gable_wall(g, F[k], -W / 2, W / 2, eave, zr - 0.02)
        fbox(g, 'Trim', F[k], -0.22, 0.22, eave + 0.25, eave + 0.6, 0, 0.03)
    wins_w = [(-7.0, 1.4, 1.5, 1.12), (-3.9, 1.0, 1.5, 1.12), (1.3, 1.0, 1.7, 0.9), (4.3, 0.6, 2.0, 0.55),
              (6.9, 1.0, 1.5, 1.12)]
    wins_e = [(-7.2, 1.0, 1.5, 1.12), (-3.5, 1.0, 1.5, 1.12), (0.5, 1.0, 1.5, 1.12), (3.6, 0.6, 2.0, 0.55),
              (7.0, 1.0, 1.5, 1.12)]
    for (y, w, s, h) in wins_w:
        window(g, F['W'], -y, s, w, h, shutters=w > 0.7)
    for (y, w, s, h) in wins_e:
        window(g, F['E'], y, s, w, h, shutters=w > 0.7)
    for x in (-2.6, 2.6):
        window(g, F['S'], x, 1.5, 1.0, 1.12, shutters=True)
    for x in (-2.4, 2.4):
        window(g, F['N'], x, 1.5, 1.0, 1.12)
    doors = [(-1.6, True), (2.7, False)]
    for (y, storm) in doors:
        door(g, F['W'], -y, FL, storm=storm)
    y0 = doors[0][0] - 0.9
    steps_parallel(g, -W / 2 - 0.02, y0, y0 + 1.8, FL - 0.03, depth=1.15, width=0.95)
    steps_parallel(g, -W / 2 - 0.02, doors[1][0] - 0.5, doors[1][0] + 0.5, FL - 0.04, depth=0.75, width=0.75, rail=False)
    # a heat-pump condenser would sit outside the bbox; leave it to the lot
    return g


ARCH = [
    ('mobile-single-a', 'a', 'older single-wide: bowed metal roof with cross seams, two-tone lap aluminum siding, '
                             'window AC, wooden landing and steps with a rail'),
    ('mobile-single-b', 'b', 'older, rustier 1970s single-wide: rounder metal roof with streaky (rust) shading, '
                             'stripe band, aluminum door awning, plain wooden stoops'),
    ('mobile-single-c', 'c', 'newer single-wide: 3:12 shingled gable roof with overhangs, vinyl lap siding, '
                             'shutters, landing with steps and railing'),
    ('mobile-double', 'd', 'double-wide (about 9 x 18 m): 4:12 shingled gable roof, vinyl siding, shutters, '
                           'two doors, block-look skirting, landing with steps'),
]


def build(aid, kind):
    make_materials(aid, kind)
    g = build_double() if kind == 'd' else build_single(kind)
    (x0, y0, z0), (x1, y1, z1) = g.bounds()
    g.shift(-(x0 + x1) / 2, -(y0 + y1) / 2)
    (x0, y0, z0), (x1, y1, z1) = g.bounds()
    o = g.build(aid.replace('mobile-', 'Mobile_').replace('-', '_'))
    return o, (x1 - x0, y1 - y0, z1, z0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    os.makedirs(ADIR, exist_ok=True)
    index = []
    for aid, kind, desc in ARCH:
        wp.reset()
        o, (w, d, h, zmin) = build(aid, kind)
        wp.finalize([o])
        tris = wp.tri_count([o])
        assert tris <= TRI_BUDGET, (aid, tris)
        path = os.path.join(ADIR, f'{aid}.glb')
        wp.export_glb(path, [o])
        index.append({'id': aid, 'kinds': ['mobile'], 'bbox_m': [round(w, 3), round(d, 3), round(h, 3)],
                      'z_range_m': [round(zmin, 3), round(h, 3)], 'stories': 1,
                      'best_aspect': round(w / d, 4), 'neighborhoods': ['Riverside'], 'triangles': tris,
                      'file_kb': round(os.path.getsize(path) / 1024, 1), 'description': desc,
                      'front_note': 'long axis along Y; lane end at -Y (glTF +Z); entry steps on the -X side'})
        print(aid, tris, 'tris', [round(w, 3), round(d, 3), round(h, 3)])
    with open(os.path.join(ADIR, 'index-mobile.json'), 'w') as f:
        json.dump(index, f, indent=1)
    if not args.no_render:
        render_lineup(args, index)


def render_lineup(args, index):
    """Lineup: the four archetypes side by side with sample tints, like the map would draw them."""
    wp.reset()
    tints = {'mobile-single-a': ((0.84, 0.88, 0.92), (0.86, 0.86, 0.85), (0.45, 0.33, 0.25)),
             'mobile-single-b': ((0.92, 0.86, 0.74), (0.86, 0.66, 0.52), (0.35, 0.3, 0.28)),
             'mobile-single-c': ((0.82, 0.86, 0.79), (0.62, 0.62, 0.64), (0.3, 0.36, 0.45)),
             'mobile-double': ((0.93, 0.92, 0.88), (0.55, 0.55, 0.57), (0.55, 0.22, 0.2))}
    x = 0.0
    for a in index:
        before = set(bpy.data.objects)
        mb = set(bpy.data.materials)
        bpy.ops.import_scene.gltf(filepath=os.path.join(ADIR, f"{a['id']}.glb"))
        new = [o for o in bpy.data.objects if o not in before]
        wt, rt, dt = tints[a['id']]
        for m in [m for m in bpy.data.materials if m not in mb]:
            base = m.name.split('.')[0]
            col = {'Wall': wt, 'Roof': rt, 'Door': dt}.get(base)
            if col:
                nt = m.node_tree
                bs = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
                inp = bs.inputs['Base Color']
                mix = nt.nodes.new('ShaderNodeMix')
                mix.data_type = 'RGBA'
                mix.blend_type = 'MULTIPLY'
                mix.inputs['Factor'].default_value = 1.0
                if inp.links:
                    nt.links.new(inp.links[0].from_socket, mix.inputs[6])
                else:
                    mix.inputs[6].default_value = inp.default_value
                mix.inputs[7].default_value = (*[c ** 2.2 for c in col], 1.0)
                nt.links.new(mix.outputs[2], inp)
        w = a['bbox_m'][0]
        x += w / 2
        for o in new:
            if o.parent is None:
                o.location = (x, 0, 0)
        x += w / 2 + 3.0
    cx = (x - 3.0) / 2
    samples = 24 if args.quick else 96
    res = (640, 400) if args.quick else (1600, 1000)
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=50, sun_az=205, threads=2, exposure=0.3)
    sun.data.energy = 3.0
    sun.data.angle = math.radians(8)
    sc = bpy.context.scene
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 2
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    wp.camera((cx - 30.0, -38.0, 17.0), (cx - 0.5, 0.5, 0.5), lens=36)
    out = args.out or os.path.join(REPO, 'renders')
    wp.render(os.path.join(out, 'mobile-archetypes.jpg'))


if __name__ == '__main__':
    main()
