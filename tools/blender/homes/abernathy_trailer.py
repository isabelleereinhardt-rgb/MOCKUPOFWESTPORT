#!/usr/bin/env python3
"""The Abernathy trailer, Lot 47, Riverside Mobile Home Community, 1118 Holt Street (hero home #3, Canon 2).

Dalton Abernathy and his mother Lisa. Design from the author's photo (reference/dalton-park.webp): an
older 16-ft single-wide in a park of single-wides. Horizontal lap aluminum siding (grey below the window
sills, off-white above, split by a thin aluminum strip), a low bowed galvanized metal roof with crimped
cross seams, worn roof coating and rust at the seams, a furnace roof jack and vent stacks, ribbed vinyl
skirting to the ground with vents, mill-finish aluminum single-hung windows, a window AC unit, a white
steel entry door with an aluminum storm door on the west long side (toward the access stub) reached by
a pressure-treated wooden landing with steps and railing, and a small back-door stoop.

Lot GLB: gravel parking pad from the lane edge with worn tire tracks, worn dirt at the steps, two 100-lb
propane cylinders, a trash cart and a recycling cart, a webbed aluminum folding chair, a T-post
clothesline with a few towels, and the park's power pedestal with its meter.

Frame (differs from site-specs.json, whose computed street is wrong): the trailer's long axis runs along
Blender Y, the lane (Atlas road 90, the unnamed service lane, south) is at -Y, west (toward the access
stub) is -X. The main body sits inside the 5.0 x 19.0 m Atlas footprint.

Run (rebuilds the GLBs, JSON and final renders):
    WP_TEX_DIR=/some/scratch python3 tools/blender/homes/abernathy_trailer.py
Previews:  --quick --out /scratch/folder   (24 samples, 640 x 400)
Other flags: --no-render, --views hero,aerial
The aerial render places the park archetypes (models/archetypes/mobile-*.glb, built by
tools/blender/archetypes/mobile.py) on the neighbouring Atlas lots, 11.5 m apart, when they exist.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import wp  # noqa: E402
import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, noise as mnoise  # noqa: E402

ID = 'abernathy-trailer'
REPO = wp.REPO

# ============================================================================ plan (meters)
W, L = 4.88, 18.70             # 16 ft x 61 ft box (Atlas footprint 5.0 x 19.0)
X0, X1 = -W / 2, W / 2         # west (stub side, entry) / east wall faces
Y0, Y1 = -L / 2, L / 2         # south (lane end) / north end wall faces
FL = 0.86                      # finished floor (steel chassis on block piers)
SB = 0.80                      # bottom of siding
BAND = 1.52                    # grey lower siding / off-white upper siding split
EAVE = 3.04                    # top of the side walls (drip rail)
CROWN = 0.19                   # bow of the roof at the centre line
OVS = 0.06                     # roof overhang at the sides
OVE = 0.04                     # roof overhang at the ends
SKIRT_IN = 0.035               # skirting set back from the siding face
SEAM = 1.2                     # roof cross-seam spacing
CURB_Y = -10.95                # lane edge (lane centre line 4.2 m south of the south wall, half-width 2.75)
LANE_C = -13.70
LOT = (-5.7, CURB_Y, 5.7, 11.5)
STUB_X = X0 - 4.5              # access stub centre line (render only)

DOOR_Y = -3.0                  # main entry (west wall), door centre
DOOR_W, DOOR_H = 0.86, 1.95
BDOOR_Y = 3.6                  # back door (west wall)
LAND = dict(x0=X0 - 1.46, y0=DOOR_Y - 0.95, y1=DOOR_Y + 0.95, top=FL - 0.035)
STAIR_W = 0.95
N_RISE = 4

# windows: (u along the wall from its left edge seen from outside is not used; use world coords)
# west wall (x = X0): (y_center, width, sill_z, height, kind)
WIN_W = [(-7.30, 0.92, 1.66, 1.06, 'ac'), (-0.55, 0.92, 1.92, 0.78, ''), (5.55, 0.62, 2.14, 0.52, ''),
         (7.75, 0.92, 1.66, 1.06, '')]
WIN_E = [(-7.40, 1.22, 1.66, 1.06, ''), (-2.40, 0.92, 1.66, 1.06, ''), (1.70, 0.92, 1.66, 1.06, ''),
         (4.70, 0.62, 2.14, 0.52, ''), (7.55, 0.92, 1.66, 1.06, '')]
WIN_S = [(-1.15, 0.92, 1.66, 1.06, ''), (1.15, 0.92, 1.66, 1.06, '')]   # x centres on the lane end
WIN_N = [(0.0, 0.92, 1.66, 1.06, '')]

CAM_HERO = dict(loc=(-9.0, -18.6, 1.68), target=(-0.9, -3.6, 1.85), lens=26)
CAM_AERIAL = dict(loc=(-23.0, -33.0, 25.5), target=(1.0, -0.5, 0.0), lens=30)
CAM_DEBUG = {
    'entry': dict(loc=(-8.5, -8.5, 1.7), target=(-2.6, -3.0, 1.4), lens=30),
    'back': dict(loc=(9.5, 17.0, 3.0), target=(0.0, 4.0, 1.8), lens=28),
}

MAT = {}


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


WORLD = None


class Geo:
    def __init__(self, name):
        self.name = name
        self.V, self.F, self.FM, self.SM, self.C = [], [], [], [], []
        self.vc = False

    def add(self, verts, faces, mat, colors=None, smooth=False):
        b = len(self.V)
        self.V.extend(tuple(v) for v in verts)
        if colors is not None:
            self.vc = True
            self.C.extend(tuple(c[:3]) for c in colors)
        else:
            self.C.extend([(1.0, 1.0, 1.0)] * len(verts))
        for f in faces:
            self.F.append(tuple(b + i for i in f))
            self.FM.append(mat)
            self.SM.append(smooth)

    def tris(self):
        return sum(len(f) - 2 for f in self.F)

    def build(self):
        mats = list(dict.fromkeys(self.FM))
        me = bpy.data.meshes.new(self.name)
        me.from_pydata(self.V, [], self.F)
        for m in mats:
            me.materials.append(MAT[m])
        idx = {m: i for i, m in enumerate(mats)}
        me.polygons.foreach_set('material_index', [idx[m] for m in self.FM])
        me.polygons.foreach_set('use_smooth', self.SM)
        if self.vc:
            ca = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
            li = [0] * len(me.loops)
            me.loops.foreach_get('vertex_index', li)
            cols = []
            for vi in li:
                c = self.C[vi]
                cols.extend((c[0], c[1], c[2], 1.0))
            ca.data.foreach_set('color', cols)
        me.validate()
        me.update()
        o = bpy.data.objects.new(self.name, me)
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


def poly(g, mat, pts, facing=None, cfn=None, smooth=False):
    pts = [Vector(p) for p in pts]
    if facing is not None and newell(pts).dot(Vector(facing)) < 0:
        pts = pts[::-1]
    g.add(pts, [list(range(len(pts)))], mat, colors=[cfn(p) for p in pts] if cfn else None, smooth=smooth)


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def extrude(g, mat, F, pts, d0, d1, caps=True, cfn=None, skip_back=False):
    """Polygon [(u, z)] in frame F extruded along F.N from d0 to d1."""
    if _area(pts) < 0:
        pts = pts[::-1]
    if d1 < d0:
        d0, d1 = d1, d0
    n = len(pts)
    V = [F.p(u, z, d0) for u, z in pts] + [F.p(u, z, d1) for u, z in pts]
    faces = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    if caps:
        faces.append(list(range(n, 2 * n)))
        if not skip_back:
            faces.append(list(range(n))[::-1])
    g.add(V, faces, mat, colors=[cfn(v) for v in V] if cfn else None)


def fbox(g, mat, F, u0, u1, z0, z1, d0, d1, cfn=None, skip_back=False):
    if u1 - u0 <= 1e-5 or z1 - z0 <= 1e-5 or abs(d1 - d0) <= 1e-5:
        return
    extrude(g, mat, F, [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], d0, d1, cfn=cfn, skip_back=skip_back)


class _World:
    O = Vector((0, 0, 0))
    U = Vector((1, 0, 0))
    Z = Vector((0, 1, 0))
    N = Vector((0, 0, 1))

    def p(self, u, z, d=0.0):
        return Vector((u, z, d))


WORLD = _World()


def box(g, mat, x0, x1, y0, y1, z0, z1, cfn=None):
    fbox(g, mat, WORLD, min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1), z0, z1, cfn=cfn)


def cbox(g, mat, cx, cy, sx, sy, z0, z1, cfn=None):
    box(g, mat, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1, cfn=cfn)


def beam(g, mat, p0, p1, w, h, up=(0, 0, 1)):
    """Rectangular member from p0 to p1 (centre line), w sideways, h along `up`."""
    p0, p1 = Vector(p0), Vector(p1)
    U = (p1 - p0)
    Ln = U.length
    U.normalize()
    up = Vector(up)
    Zv = (up - U * up.dot(U)).normalized()
    S = U.cross(Zv)
    V = []
    for t in (0, Ln):
        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            V.append(p0 + U * t + S * (a * w / 2) + Zv * (b * h / 2))
    faces = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7], [3, 2, 1, 0], [4, 5, 6, 7]]
    # orientation check
    c = sum(V, Vector()) / 8
    out = []
    for f in faces:
        pts = [V[i] for i in f]
        if newell(pts).dot(sum(pts, Vector()) / 4 - c) < 0:
            f = f[::-1]
        out.append(f)
    g.add(V, out, mat)


def tube(g, mat, pts, r, seg=6, smooth=True, caps=False):
    pts = [Vector(p) for p in pts]
    n = len(pts)
    T = []
    for k in range(n):
        a, b = pts[max(k - 1, 0)], pts[min(k + 1, n - 1)]
        T.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    N1 = [(ref - T[0] * ref.dot(T[0])).normalized()]
    for k in range(1, n):
        v = N1[-1] - T[k] * N1[-1].dot(T[k])
        N1.append(v.normalized() if v.length > 1e-6 else N1[-1])
    V = []
    rr = r if isinstance(r, (list, tuple)) else [r] * n
    for k in range(n):
        n2 = T[k].cross(N1[k])
        for i in range(seg):
            a = 2 * math.pi * i / seg
            V.append(pts[k] + rr[k] * (math.cos(a) * N1[k] + math.sin(a) * n2))
    F = []
    for k in range(n - 1):
        for i in range(seg):
            j = (i + 1) % seg
            F.append([k * seg + i, k * seg + j, (k + 1) * seg + j, (k + 1) * seg + i])
    if caps:
        F.append(list(range(seg))[::-1])
        F.append([(n - 1) * seg + i for i in range(seg)])
    g.add(V, F, mat, smooth=smooth)


def lathe(g, mat, prof, cx, cy, seg=16, z0=0.0, cap_top=True, cap_bot=False, smooth=True):
    V, F = [], []
    for r, z in prof:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            V.append((cx + r * math.cos(a), cy + r * math.sin(a), z0 + z))
    for k in range(len(prof) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            F.append([k * seg + i, k * seg + j, (k + 1) * seg + j, (k + 1) * seg + i])
    if cap_top and prof[-1][0] > 0:
        F.append([(len(prof) - 1) * seg + i for i in range(seg)])
    if cap_bot and prof[0][0] > 0:
        F.append(list(range(seg))[::-1])
    g.add(V, F, mat, smooth=smooth)


def slab(g, mat, pts, z, z0=None, cfn=None):
    """Flat polygon at height z (top only when z0 is None, else a solid slab)."""
    if z0 is None:
        poly(g, mat, [(x, y, z) for x, y in pts], facing=(0, 0, 1), cfn=cfn)
    else:
        extrude(g, mat, WORLD, list(pts), z0, z, cfn=cfn, skip_back=True)


def wall_with_holes(g, F, u0, u1, z0, z1, holes, mat, cfn=None):
    """Planar wall rectangle (frame F, at d = 0) minus rectangular holes [(u0, u1, z0, z1)]."""
    us = sorted(set([u0, u1] + [h[0] for h in holes] + [h[1] for h in holes]))
    zs = sorted(set([z0, z1] + [h[2] for h in holes] + [h[3] for h in holes]))
    us = [u for u in us if u0 <= u <= u1]
    zs = [z for z in zs if z0 <= z <= z1]
    for i in range(len(us) - 1):
        for k in range(len(zs) - 1):
            cu, cz = (us[i] + us[i + 1]) / 2, (zs[k] + zs[k + 1]) / 2
            if any(h[0] < cu < h[1] and h[2] < cz < h[3] for h in holes):
                continue
            pts = [F.p(us[i], zs[k]), F.p(us[i + 1], zs[k]), F.p(us[i + 1], zs[k + 1]), F.p(us[i], zs[k + 1])]
            poly(g, mat, pts, facing=F.N, cfn=cfn)


# ============================================================================ textures
def _blur1(a, k, axis):
    """Circular box blur of width k along an axis (tileable)."""
    if k <= 1:
        return a
    c = np.cumsum(np.concatenate([a, np.take(a, range(k), axis=axis)], axis=axis), axis=axis)
    lo = np.take(c, range(0, a.shape[axis]), axis=axis)
    hi = np.take(c, range(k, a.shape[axis] + k), axis=axis)
    return (hi - lo) / k


def streaks(n, rng, along, across, axis):
    """Tileable streak noise: long along `axis` (0 = vertical in the image, 1 = horizontal)."""
    r = rng.random((n, n)).astype(np.float32)
    other = 1 - axis
    s = _blur1(_blur1(r, along, axis), across, other)
    s = _blur1(s, max(1, along // 3), axis)
    s = (s - s.min()) / (s.max() - s.min() + 1e-6)
    return s


def tex_lap(key, color, exposure=0.2, n=1024, tile=2.0, seed=3, rain=0.06, emboss=0.03, board_var=0.025):
    """Horizontal lap aluminum siding. Image rows = height; t = 0 at the butt (bottom) edge of each board."""
    rng = np.random.default_rng(seed)
    px = n / tile
    rows = int(round(tile / exposure))
    exposure = tile / rows
    r = np.arange(n, dtype=np.float32)[:, None]
    vm = (n - 1 - r) / px
    t = np.broadcast_to((vm % exposure) / exposure, (n, n))
    board = np.broadcast_to((vm // exposure).astype(int) % rows, (n, n))
    bv = rng.random(rows + 1)[board]
    grain = streaks(n, rng, 48, 2, axis=1)
    rainm = streaks(n, rng, 160, 6, axis=0)
    shade = 0.83 + 0.17 * np.clip(t / 0.10, 0, 1)
    shade = np.where(t < 0.028, 0.50, shade)
    shade = shade * (1 - 0.035 * np.clip((t - 0.75) / 0.25, 0, 1))
    alb = wp._rgb(color)[None, None, :] * (shade * (1 + (bv - 0.5) * board_var) * (1 - emboss + 2 * emboss * grain))[..., None]
    alb = alb * (1 - rain * np.clip((rainm - 0.55) * 3.5, 0, 1))[..., None]
    h = (1 - t) * 0.6 + grain * 0.04
    h = np.where(t < 0.028, 0.0, h)
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 2.6), key + '_n'), tile


def tex_skirt(key, color, n=512, tile=2.0, seed=5):
    """Ribbed vinyl skirting: vertical panels 0.4 m wide with three ribs each."""
    rng = np.random.default_rng(seed)
    px = n / tile
    x = np.arange(n, dtype=np.float32)[None, :] / px
    pw = tile / int(round(tile / 0.4))
    lx = np.broadcast_to(x % pw, (n, n))
    rib = (np.abs(((lx / pw) * 4) % 1 - 0.5) < 0.06)
    joint = lx < 0.006
    rainm = streaks(n, rng, 90, 5, axis=0)
    nz = wp._noise(n, 6 * tile, rng, 3)
    shade = np.where(rib, 0.86, 1.0) * np.where(joint, 0.62, 1.0)
    alb = wp._rgb(color)[None, None, :] * (shade * (0.95 + 0.07 * nz) * (1 - 0.05 * np.clip((rainm - 0.5) * 3, 0, 1)))[..., None]
    h = np.where(rib, 1.0, 0.0) * 0.5 - joint * 0.6
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 1.6), key + '_n'), tile


def tex_roof_metal(key, tile=4.8, seam=1.2, n=2048, seed=9, rust=0.8, base='#aeb0ac', galv='#878b89'):
    """Coated galvanized roof sheet seen from above: u = across the roof (x), v = along it (y).
    Cross seams every `seam` m (image rows), worn coating patches, rust at seams and in streaks
    that run down-slope (along u)."""
    rng = np.random.default_rng(seed)
    px = n / tile
    r = np.arange(n, dtype=np.float32)[:, None]
    vm = (n - 1 - r) / px
    ds = np.broadcast_to(np.abs(((vm + seam / 2) % seam) - seam / 2), (n, n))   # distance to the nearest seam (m)
    big = wp._noise(n, 3 * tile / 4.8 * 4, rng, 5)
    mid = wp._noise(n, 14 * tile / 4.8 * 4, rng, 3)
    fine = rng.random((n, n)).astype(np.float32)
    sl = streaks(n, rng, 200, 3, axis=1)          # down-slope streaks (along u)
    worn = np.clip((big * 0.7 + mid * 0.5 - 0.62) * 3.0, 0, 1)
    alb = wp._rgb(base)[None, None, :] * (0.9 + 0.12 * mid[..., None] + 0.03 * fine[..., None])
    alb = alb * (1 - worn[..., None]) + wp._rgb(galv)[None, None, :] * (0.85 + 0.25 * mid[..., None]) * worn[..., None]
    # dirt in the slight sag between seams and along streaks
    alb = alb * (1 - 0.10 * np.clip((sl - 0.5) * 3, 0, 1))[..., None]
    seam_zone = np.exp(-(ds / 0.09) ** 2)
    rmask = np.clip((seam_zone * (0.6 + 0.8 * mid) + np.clip((sl - 0.62) * 3, 0, 1) * mid * 0.9
                     + np.clip((big - 0.72) * 4, 0, 1) * 0.6 - (1.0 - rust)) * 1.6, 0, 1)
    rustc = (wp._rgb('#6e4127') * (0.7 + 0.5 * mid[..., None] + 0.1 * fine[..., None]))
    alb = alb * (1 - rmask[..., None]) + rustc * rmask[..., None]
    h = np.exp(-(ds / 0.012) ** 2) * 0.8 + mid * 0.1
    a_p = wp._save(alb, key)
    n_p = wp._save(wp._normal_from_height(h, 1.2), key + '_n')
    from PIL import Image
    Image.open(n_p).resize((1024, 1024), Image.LANCZOS).save(n_p, quality=88)
    return a_p, n_p, tile


def tex_glass(key, n=512, tile=2.4, seed=81):
    """Dark glazing with curtains and mini-blinds behind it."""
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 3, rng, 3)
    folds = streaks(n, rng, 40, 3, axis=0)
    r = np.arange(n, dtype=np.float32)[:, None]
    blinds = np.broadcast_to((((r / n * tile) % 0.025) / 0.025 > 0.35).astype(np.float32), (n, n))
    sel = wp._noise(n, 2, rng, 2)
    curtain = np.clip((big - 0.45) * 3, 0, 1) * (0.55 + 0.45 * folds)
    blind_m = np.clip((sel - 0.5) * 6, 0, 1)
    dark, light, bl = wp._rgb('#20252a'), wp._rgb('#7d7a72'), wp._rgb('#a8a49a')
    alb = dark + (light - dark) * (curtain * 0.5)[..., None]
    alb = alb * (1 - blind_m[..., None] * 0.85) + (bl * (0.55 + 0.45 * blinds)[..., None]) * blind_m[..., None] * 0.6
    return wp._save(alb, key), None, tile


def tex_paint(key, color, n=256, tile=1.0, seed=11, amp=0.04):
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 4 * tile, rng, 4)
    fine = wp._noise(n, 40 * tile, rng, 2)
    alb = wp._rgb(color)[None, None, :] * (1 - amp + 2 * amp * big[..., None]) * (0.985 + 0.03 * fine[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(big * 0.2 + fine * 0.3, 0.3), key + '_n'), tile


def tex_dirt(key, n=1024, tile=2.5, seed=17, color='#7a6a55'):
    rng = np.random.default_rng(seed)
    nz = wp._noise(n, 10 * tile, rng, 5)
    g = wp._noise(n, 160 * tile, rng, 2)
    fine = rng.random((n, n)).astype(np.float32)
    peb = np.clip((g - 0.72) * 6, 0, 1)
    alb = wp._rgb(color)[None, None, :] * (0.78 + 0.35 * nz[..., None] + 0.08 * (fine[..., None] - 0.5))
    alb = alb * (1 - peb[..., None]) + wp._rgb('#a49d90')[None, None, :] * peb[..., None] * (0.8 + 0.3 * fine[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(nz * 0.4 + peb * 0.5, 1.5), key + '_n'), tile


def tex_canopy(key, color, n=1024, tile=2.0, seed=58):
    rng = np.random.default_rng(seed)
    cl = wp._noise(n, 12 * tile, rng, 2)
    cl2 = wp._noise(n, 30 * tile, rng, 2)
    fine = wp._noise(n, 90 * tile, rng, 2)
    clusters = np.clip((cl * 0.6 + cl2 * 0.4 - 0.34) * 3.0, 0, 1)
    leaf = clusters * (0.6 + 0.4 * fine)
    alb = wp._rgb(color)[None, None, :] * (0.28 + 0.9 * leaf[..., None])
    hl = np.clip((fine - 0.6) * 4, 0, 1) * clusters
    alb = alb * (1 - 0.3 * hl[..., None]) + wp._rgb('#9aac5a')[None, None, :] * 0.3 * hl[..., None]
    return wp._save(alb, key), wp._save(wp._normal_from_height(leaf, 2.0), key + '_n'), tile


def vc_mat(name, color='#ffffff', tex=None, rough=0.6, metal=0.0, double=False):
    """wp.mat with the 'Col' vertex colour multiplied in (exported as COLOR_0)."""
    m = wp.mat(name, color, rough=rough, metal=metal, tex=tex, double_sided=double)
    nt = m.node_tree
    bs = nt.nodes['Principled BSDF']
    ca = nt.nodes.new('ShaderNodeVertexColor')
    ca.layer_name = 'Col'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    if bs.inputs['Base Color'].links:
        src = bs.inputs['Base Color'].links[0].from_socket
        nt.links.new(src, mix.inputs[6])
    else:
        mix.inputs[6].default_value = bs.inputs['Base Color'].default_value
    nt.links.new(ca.outputs['Color'], mix.inputs[7])
    nt.links.new(mix.outputs[2], bs.inputs['Base Color'])
    return m


def make_materials():
    M = MAT
    M['Siding'] = vc_mat('Siding', tex=tex_lap('ab_siding_grey', '#a6abab', seed=3), rough=0.5, metal=0.0)
    M['SidingUp'] = vc_mat('SidingUp', tex=tex_lap('ab_siding_white', '#dcddd7', seed=4), rough=0.5)
    M['Skirt'] = vc_mat('Skirt', tex=tex_skirt('ab_skirt', '#d3d0c5'), rough=0.55)
    M['Roof'] = vc_mat('Roof', tex=tex_roof_metal('ab_roof'), rough=0.55, metal=0.25)
    M['Alu'] = wp.mat('Alu', '#b9bcbd', rough=0.42, metal=0.75)
    M['AluDark'] = wp.mat('AluDark', '#7e8283', rough=0.5, metal=0.6)
    M['Trim'] = wp.mat('Trim', tex=tex_paint('ab_trim', '#e7e7e1'), rough=0.45)
    M['Door'] = wp.mat('Door', tex=tex_paint('ab_door', '#e4e3dc', seed=12), rough=0.4)
    M['Glass'] = wp.mat('Glass', '#ffffff', rough=0.04, tex=tex_glass('ab_glass'))
    M['Wood'] = vc_mat('Wood', tex=wp.tex_wood('ab_wood', color='#9a8466', board=0.14, seed=8, weathered=0.38),
                       rough=0.8)
    M['Block'] = wp.mat('Block', tex=(wp.tex_ground('ab_block', kind='concrete', color='#9f9b93', n=512, tile=1.0,
                                                    seed=19)[0], None, 1.0), rough=0.9)
    M['AC'] = wp.mat('AC', tex=tex_paint('ab_ac', '#cbc5b5', seed=13, amp=0.06), rough=0.5)
    M['Grille'] = wp.mat('Grille', '#3f413f', rough=0.6, metal=0.3)
    M['Black'] = wp.mat('Black', '#161718', rough=0.55)
    M['Rubber'] = wp.mat('Rubber', '#232323', rough=0.85)
    # lot
    M['Gravel'] = wp.mat('Gravel', tex=wp.tex_ground('ab_gravel', kind='gravel', color='#8c8579', n=1024, tile=2.0,
                                                     seed=22), rough=0.95)
    M['Dirt'] = wp.mat('Dirt', tex=tex_dirt('ab_dirt'), rough=0.95)
    M['Tank'] = wp.mat('Tank', tex=tex_paint('ab_tank', '#e9e8e2', seed=14, amp=0.05), rough=0.35)
    M['Cart'] = wp.mat('Cart', '#2b3a30', rough=0.55)
    M['CartBlue'] = wp.mat('CartBlue', '#24477a', rough=0.55)
    M['Web'] = wp.mat('Web', '#5b8f6a', rough=0.7, double_sided=True)
    M['Cloth1'] = wp.mat('Cloth1', '#b8463f', rough=0.9, double_sided=True)
    M['Cloth2'] = wp.mat('Cloth2', '#d9d4c3', rough=0.9, double_sided=True)
    M['Cloth3'] = wp.mat('Cloth3', '#4f6b8d', rough=0.9, double_sided=True)
    M['Galv'] = wp.mat('Galv', '#9a9d9b', rough=0.45, metal=0.7)
    M['Meter'] = wp.mat('Meter', '#8f948f', rough=0.5, metal=0.4)
    M['MeterGlass'] = wp.mat('MeterGlass', '#d7dcda', rough=0.1)
    M['Hose'] = wp.mat('Hose', '#2f6b3a', rough=0.6)
    M['Copper'] = wp.mat('Copper', '#9a6440', rough=0.4, metal=0.8)
    M['Pot'] = wp.mat('Pot', '#8b4a2f', rough=0.8)
    M['Leaf'] = vc_mat('Leaf', tex=tex_canopy('ab_leaf', '#4b6a2c', n=512, tile=0.6, seed=59), rough=0.7)
    return M


# ============================================================================ trailer
def roof_z(x):
    """Top of the roof sheet across the width (bowed, highest on the centre line)."""
    hw = W / 2 + OVS
    t = max(-1.0, min(1.0, x / hw))
    return EAVE + 0.03 + CROWN * (1 - t * t)


def wall_cfn(p):
    """Grime on the siding: darker near the bottom (splash) and just under the drip rail."""
    z = p.z
    k = 1.0 - 0.13 * max(0.0, 1 - (z - SB) / 0.55) - 0.05 * max(0.0, 1 - (EAVE - z) / 0.35)
    return (k, k, k * 0.985)


def skirt_cfn(p):
    z = p.z
    k = 1.0 - 0.32 * max(0.0, 1 - (z + 0.02) / 0.32) - 0.06 * max(0.0, 1 - (z + 0.02) / 0.8)
    return (k * 0.99, k * 0.97, k * 0.93)


def roof_cfn(p):
    """Darker toward the eaves (runoff) and the ends."""
    e = 1 - abs(p.x) / (W / 2 + OVS)
    k = 1.0 - 0.18 * max(0.0, 1 - e / 0.18)
    return (k, k * 0.97, k * 0.94)


def window(gH, F, uc, sill, w, h, kind='', mat_frame='Alu'):
    """Surface-mounted aluminum single-hung window in wall frame F (wall face at d = 0)."""
    u0, u1, z0, z1 = uc - w / 2, uc + w / 2, sill, sill + h
    fw, fd = 0.045, 0.028
    # frame ring (proud of the siding)
    fbox(gH, mat_frame, F, u0 - fw, u1 + fw, z0 - fw, z0, -0.01, fd)
    fbox(gH, mat_frame, F, u0 - fw, u1 + fw, z1, z1 + fw, -0.01, fd)
    fbox(gH, mat_frame, F, u0 - fw, u0, z0, z1, -0.01, fd)
    fbox(gH, mat_frame, F, u1, u1 + fw, z0, z1, -0.01, fd)
    # reveal (aluminum) and glass slightly behind
    gd = -0.035
    poly(gH, mat_frame, [F.p(u0, z0, 0), F.p(u1, z0, 0), F.p(u1, z0, gd), F.p(u0, z0, gd)], facing=F.Z)
    poly(gH, mat_frame, [F.p(u0, z1, 0), F.p(u1, z1, 0), F.p(u1, z1, gd), F.p(u0, z1, gd)], facing=-F.Z)
    poly(gH, mat_frame, [F.p(u0, z0, 0), F.p(u0, z1, 0), F.p(u0, z1, gd), F.p(u0, z0, gd)], facing=F.U)
    poly(gH, mat_frame, [F.p(u1, z0, 0), F.p(u1, z1, 0), F.p(u1, z1, gd), F.p(u1, z0, gd)], facing=-F.U)
    poly(gH, 'Glass', [F.p(u0, z0, gd), F.p(u1, z0, gd), F.p(u1, z1, gd), F.p(u0, z1, gd)], facing=F.N)
    # sash frames: meeting rail and sash stiles
    zm = z0 + h * 0.5
    fbox(gH, mat_frame, F, u0, u1, zm - 0.022, zm + 0.022, gd, gd + 0.03)
    fbox(gH, mat_frame, F, u0, u1, z0, z0 + 0.03, gd, gd + 0.02)
    fbox(gH, mat_frame, F, u0, u1, z1 - 0.03, z1, gd, gd + 0.02)
    fbox(gH, mat_frame, F, u0, u0 + 0.03, z0, z1, gd, gd + 0.02)
    fbox(gH, mat_frame, F, u1 - 0.03, u1, z0, z1, gd, gd + 0.02)
    # sill drip
    fbox(gH, mat_frame, F, u0 - fw - 0.01, u1 + fw + 0.01, z0 - fw - 0.012, z0 - fw, -0.01, fd + 0.012)
    return (u0 - fw, u1 + fw, z0 - fw, z1 + fw)


def ac_unit(gH, F, uc, sill, w):
    """Window air conditioner in the lower sash, sticking out of the wall, on an angle bracket."""
    aw, ah, out, inn = 0.58, 0.37, 0.42, 0.18
    zb = sill + 0.005
    fbox(gH, 'AC', F, uc - aw / 2, uc + aw / 2, zb, zb + ah, -inn, out)
    # rear grille (outside face) and side louvres
    fbox(gH, 'Grille', F, uc - aw / 2 + 0.04, uc + aw / 2 - 0.04, zb + 0.04, zb + ah - 0.05, out, out + 0.006)
    for k in range(6):
        z = zb + 0.07 + k * 0.045
        for s in (-1, 1):
            u = uc + s * (aw / 2)
            fbox(gH, 'Grille', F, u - 0.004 if s > 0 else u - 0.002, u + 0.002 if s > 0 else u + 0.004,
                 z, z + 0.018, 0.08, out - 0.06)
    # side accordion panels filling the sash width
    pw = (w - aw) / 2
    for s in (-1, 1):
        u_in = uc + s * aw / 2
        u_out = uc + s * (aw / 2 + pw)
        fbox(gH, 'Trim', F, min(u_in, u_out), max(u_in, u_out), zb, zb + 0.42, -0.03, -0.015)
    # support bracket: two angled bars to the siding
    for s in (-1, 1):
        u = uc + s * (aw / 2 - 0.06)
        beam(gH, 'AluDark', F.p(u, zb - 0.01, out - 0.05), F.p(u, zb - 0.38, 0.01), 0.025, 0.025)
        beam(gH, 'AluDark', F.p(u, zb - 0.012, 0.0), F.p(u, zb - 0.012, out - 0.03), 0.03, 0.02)
    # condensate drip stain on the siding below
    return


def door(gH, F, uc, w, h, storm=True, light=True):
    z0 = FL
    u0, u1, z1 = uc - w / 2, uc + w / 2, z0 + h
    cw = 0.06
    # aluminum door frame / trim
    fbox(gH, 'Alu', F, u0 - cw, u0, z0 - 0.02, z1 + cw, -0.01, 0.03)
    fbox(gH, 'Alu', F, u1, u1 + cw, z0 - 0.02, z1 + cw, -0.01, 0.03)
    fbox(gH, 'Alu', F, u0, u1, z1, z1 + cw, -0.01, 0.03)
    fbox(gH, 'Alu', F, u0 - 0.02, u1 + 0.02, z0 - 0.03, z0, -0.01, 0.05)       # threshold
    dd = -0.04
    poly(gH, 'Alu', [F.p(u0, z1, 0), F.p(u1, z1, 0), F.p(u1, z1, dd), F.p(u0, z1, dd)], facing=-F.Z)
    poly(gH, 'Alu', [F.p(u0, z0, 0), F.p(u0, z1, 0), F.p(u0, z1, dd), F.p(u0, z0, dd)], facing=F.U)
    poly(gH, 'Alu', [F.p(u1, z0, 0), F.p(u1, z1, 0), F.p(u1, z1, dd), F.p(u1, z0, dd)], facing=-F.U)
    # steel door slab with a small high window
    wu0, wu1, wz0, wz1 = uc - 0.18, uc + 0.18, z0 + 1.42, z0 + 1.72
    wall_with_holes(gH, Fr(F.p(0, 0, dd), F.N), u0, u1, z0, z1, [(wu0, wu1, wz0, wz1)], 'Door')
    poly(gH, 'Glass', [F.p(wu0, wz0, dd - 0.01), F.p(wu1, wz0, dd - 0.01), F.p(wu1, wz1, dd - 0.01), F.p(wu0, wz1, dd - 0.01)], facing=F.N)
    for (a0, a1, b0, b1) in ((wu0 - 0.03, wu1 + 0.03, wz0 - 0.03, wz0), (wu0 - 0.03, wu1 + 0.03, wz1, wz1 + 0.03),
                             (wu0 - 0.03, wu0, wz0, wz1), (wu1, wu1 + 0.03, wz0, wz1)):
        fbox(gH, 'Door', F, a0, a1, b0, b1, dd - 0.01, dd + 0.012)
    # embossed panels (two raised rectangles below the window)
    for (pz0, pz1) in ((z0 + 0.15, z0 + 0.62), (z0 + 0.72, z0 + 1.30)):
        for (pu0, pu1) in ((u0 + 0.1, uc - 0.05), (uc + 0.05, u1 - 0.1)):
            fbox(gH, 'Door', F, pu0, pu1, pz0, pz1, dd, dd + 0.008)
    # knob + deadbolt (hinges on the left, knob right)
    for zk in (z0 + 0.92, z0 + 1.08):
        fbox(gH, 'Alu', F, u1 - 0.1, u1 - 0.05, zk - 0.03, zk + 0.03, dd, dd + 0.035)
    if storm:
        sd = 0.075   # aluminum storm door in front
        sw = 0.045
        for (a0, a1, b0, b1) in ((u0 - 0.01, u0 - 0.01 + sw, z0, z1 - 0.01), (u1 + 0.01 - sw, u1 + 0.01, z0, z1 - 0.01),
                                 (u0 - 0.01, u1 + 0.01, z1 - 0.01 - sw, z1 - 0.01), (u0 - 0.01, u1 + 0.01, z0, z0 + 0.22),
                                 (u0 - 0.01, u1 + 0.01, z0 + 0.86, z0 + 0.94)):
            fbox(gH, 'Alu', F, a0, a1, b0, b1, sd - 0.03, sd)
        # lower kick panel (solid, white) and upper glass
        fbox(gH, 'Trim', F, u0 + sw - 0.01, u1 - sw + 0.01, z0 + 0.22, z0 + 0.86, sd - 0.02, sd - 0.012)
        poly(gH, 'Glass', [F.p(u0 + sw - 0.01, z0 + 0.94, sd - 0.016), F.p(u1 - sw + 0.01, z0 + 0.94, sd - 0.016),
                           F.p(u1 - sw + 0.01, z1 - 0.01 - sw, sd - 0.016), F.p(u0 + sw - 0.01, z1 - 0.01 - sw, sd - 0.016)],
             facing=F.N)
        fbox(gH, 'Black', F, u1 - 0.07, u1 - 0.035, z0 + 0.92, z0 + 1.05, sd, sd + 0.03)   # handle
        # closer tube at the top
        tube(gH, 'Alu', [F.p(u0 + 0.15, z1 - 0.12, sd + 0.03), F.p(u0 + 0.5, z1 - 0.12, sd + 0.03)], 0.012, seg=6)
    if light:
        lu = u1 + 0.26
        fbox(gH, 'Black', F, lu - 0.06, lu + 0.06, z0 + 1.62, z0 + 1.80, 0.0, 0.03)
        fbox(gH, 'MeterGlass', F, lu - 0.05, lu + 0.05, z0 + 1.55, z0 + 1.76, 0.03, 0.12)
        fbox(gH, 'Black', F, lu - 0.065, lu + 0.065, z0 + 1.76, z0 + 1.79, 0.02, 0.13)
    return (u0 - cw, u1 + cw, z0 - 0.03, z1 + cw)


def build_trailer():
    gH = Geo('House')       # walls, windows, doors
    gR = Geo('Roof')
    gS = Geo('Skirting')
    gP = Geo('Porch')       # landing, steps, railings, stoop
    walls = {
        'W': (Fr((X0, 0, 0), (-1, 0, 0)), -Y1, -Y0, WIN_W, -1),   # u = -y on the west wall
        'E': (Fr((X1, 0, 0), (1, 0, 0)), Y0, Y1, WIN_E, 1),       # u = y on the east wall
        'S': (Fr((0, Y0, 0), (0, -1, 0)), X0, X1, WIN_S, 1),      # u = x on the south end
        'N': (Fr((0, Y1, 0), (0, 1, 0)), -X1, -X0, WIN_N, -1),    # u = -x on the north end
    }
    for key, (F, u0, u1, wins, sgn) in walls.items():
        holes = []
        for (c, w, sill, h, kind) in wins:
            uc = c * sgn
            hole = (uc - w / 2, uc + w / 2, sill, sill + h)
            holes.append(hole)
            window(gH, F, uc, sill, w, h, kind)
            if kind == 'ac':
                ac_unit(gH, F, uc, sill, w)
        if key == 'W':
            for yc, storm in ((DOOR_Y, True), (BDOOR_Y, False)):
                uc = -yc
                holes.append((uc - DOOR_W / 2, uc + DOOR_W / 2, FL, FL + DOOR_H))
                door(gH, F, uc, DOOR_W, DOOR_H, storm=storm)
        lo = [h for h in holes]
        # grey lower siding / off-white upper siding, split by an aluminum strip
        wall_with_holes(gH, F, u0, u1, SB, BAND, lo, 'Siding', cfn=wall_cfn)
        wall_with_holes(gH, F, u0, u1, BAND, EAVE, lo, 'SidingUp', cfn=wall_cfn)
        # split strip (broken by the doors)
        cuts = sorted([(h[0], h[1]) for h in holes if h[2] < BAND < h[3]])
        a = u0
        for (c0, c1) in cuts + [(u1, u1)]:
            fbox(gH, 'Alu', F, a, c0 - 0.06 if c0 < u1 else c0, BAND - 0.018, BAND + 0.018, 0, 0.018)
            a = c1 + 0.06
        # bottom trim (starter strip) along the siding bottom
        fbox(gH, 'Alu', F, u0, u1, SB - 0.01, SB + 0.03, 0, 0.012)
        if key in ('S', 'N'):
            # gable strip under the bowed roof
            n = 12
            pts = [(u0, EAVE)]
            for i in range(n + 1):
                u = u0 + (u1 - u0) * i / n
                x = u * sgn
                pts.append((u, roof_z(x) - 0.04))
            pts.append((u1, EAVE))
            poly(gH, 'SidingUp', [F.p(u, z) for u, z in pts], facing=F.N, cfn=wall_cfn)
    # corner trims
    for (x, y) in ((X0, Y0), (X1, Y0), (X0, Y1), (X1, Y1)):
        sx, sy = (1 if x > 0 else -1), (1 if y > 0 else -1)
        box(gH, 'Alu', x, x + sx * 0.015, y - sy * 0.075, y, SB - 0.01, EAVE + 0.01)
        box(gH, 'Alu', x - sx * 0.075, x, y, y + sy * 0.015, SB - 0.01, EAVE + 0.01)
    # utility details on the west wall: hose bib, dryer vent, electrical cord into the skirting
    Fw = walls['W'][0]
    fbox(gH, 'AluDark', Fw, -(-1.6) - 0.06, -(-1.6) + 0.06, SB + 0.25, SB + 0.37, 0, 0.06)          # dryer vent hood
    fbox(gH, 'Copper', Fw, -(1.3) - 0.02, -(1.3) + 0.02, SB + 0.12, SB + 0.2, 0, 0.07)               # hose bib
    build_roof(gR)
    build_skirting(gS)
    build_porch(gP)
    return [gH, gR, gS, gP]


def build_roof(g):
    """Bowed galvanized roof: sheet + crimped cross seams + rolled drip edges + roof jacks."""
    hw = W / 2 + OVS
    ya, yb = Y0 - OVE, Y1 + OVE
    nx = 14
    xs = [-hw + 2 * hw * i / nx for i in range(nx + 1)]
    ys = [ya] + [k * SEAM for k in range(int(math.ceil(ya / SEAM)), int(math.floor(yb / SEAM)) + 1)] + [yb]
    ys = sorted(set(round(y, 4) for y in ys))
    V = []
    for y in ys:
        for x in xs:
            V.append((x, y, roof_z(x)))
    F = []
    nxp = nx + 1
    for j in range(len(ys) - 1):
        for i in range(nx):
            F.append([j * nxp + i, j * nxp + i + 1, (j + 1) * nxp + i + 1, (j + 1) * nxp + i])
    g.add(V, F, 'Roof', colors=[roof_cfn(Vector(v)) for v in V], smooth=True)
    # crimped cross seams (raised ribs)
    for y in ys[1:-1]:
        # as a thin box strip following the bow
        Vs, Fs = [], []
        for i, x in enumerate(xs):
            z = roof_z(x)
            Vs += [(x, y - 0.018, z - 0.005), (x, y - 0.006, z + 0.02), (x, y + 0.006, z + 0.02), (x, y + 0.018, z - 0.005)]
        for i in range(nx):
            b0, b1 = i * 4, (i + 1) * 4
            Fs += [[b0, b1, b1 + 1, b0 + 1], [b0 + 1, b1 + 1, b1 + 2, b0 + 2], [b0 + 2, b1 + 2, b1 + 3, b0 + 3]]
        g.add(Vs, Fs, 'Roof', colors=[roof_cfn(Vector(v)) for v in Vs])
    # sides: rolled drip edge over the top of the wall
    for s in (-1, 1):
        x = s * hw
        box(g, 'Alu', min(x, x + s * 0.025), max(x, x + s * 0.025), ya, yb, EAVE - 0.075, roof_z(x) + 0.012)
        box(g, 'Alu', min(s * (W / 2), x), max(s * (W / 2), x), ya, yb, EAVE - 0.075, EAVE - 0.06)
    # ends: edge band following the bow
    for s in (-1, 1):
        y = ya if s < 0 else yb
        Vs, Fs = [], []
        for x in xs:
            z = roof_z(x)
            Vs += [(x, y, z - 0.09), (x, y, z + 0.012), (x, y - s * 0.03, z + 0.012)]
        for i in range(nx):
            b0, b1 = i * 3, (i + 1) * 3
            f1 = [b0, b1, b1 + 1, b0 + 1]
            f2 = [b0 + 1, b1 + 1, b1 + 2, b0 + 2]
            if s > 0:
                f1, f2 = f1[::-1], f2[::-1]
            Fs += [f1, f2]
        g.add(Vs, Fs, 'Alu')
    # roof jacks: furnace flue (galvanized cap), two plumbing vents, bathroom fan
    fx, fy = 0.35, -1.6
    lathe(g, 'Galv', [(0.22, 0.0), (0.22, 0.03), (0.06, 0.05), (0.06, 0.32), (0.13, 0.36), (0.13, 0.47), (0.0, 0.52)],
          fx, fy, seg=14, z0=roof_z(fx) - 0.01)
    for (vx, vy) in ((-0.6, 2.6), (0.7, 5.9)):
        lathe(g, 'Rubber', [(0.12, 0.0), (0.12, 0.02), (0.045, 0.06), (0.03, 0.08)], vx, vy, seg=10, z0=roof_z(vx) - 0.01)
        lathe(g, 'Black', [(0.028, 0.0), (0.028, 0.28), (0.0, 0.28)], vx, vy, seg=10, z0=roof_z(vx))
    bx, by = -0.4, 4.9
    box(g, 'Galv', bx - 0.24, bx + 0.24, by - 0.24, by + 0.24, roof_z(bx) - 0.01, roof_z(bx) + 0.04)
    box(g, 'AluDark', bx - 0.17, bx + 0.17, by - 0.17, by + 0.17, roof_z(bx) + 0.04, roof_z(bx) + 0.13)
    box(g, 'Galv', bx - 0.2, bx + 0.2, by - 0.2, by + 0.2, roof_z(bx) + 0.13, roof_z(bx) + 0.15)


def build_skirting(g):
    """Ribbed vinyl skirting from below grade to the bottom of the siding, with vents and top trim."""
    zt, zb = SB + 0.015, -0.6
    xa, xb = X0 + SKIRT_IN, X1 - SKIRT_IN
    ya, yb = Y0 + SKIRT_IN, Y1 - SKIRT_IN
    vents = {'W': [-6.0, 0.5, 6.8], 'E': [-5.5, 0.0, 5.5], 'S': [], 'N': [0.0]}
    sides = [('S', Fr((0, ya, 0), (0, -1, 0)), xa, xb, 1), ('E', Fr((xb, 0, 0), (1, 0, 0)), ya, yb, 1),
             ('N', Fr((0, yb, 0), (0, 1, 0)), -xb, -xa, -1), ('W', Fr((xa, 0, 0), (-1, 0, 0)), -yb, -ya, -1)]
    for key, F, u0, u1, sgn in sides:
        holes = []
        for c in vents[key]:
            uc = c * sgn
            holes.append((uc - 0.2, uc + 0.2, 0.18, 0.36))
        wall_with_holes(g, F, u0, u1, zb, zt, holes, 'Skirt', cfn=skirt_cfn)
        for (h0, h1, hz0, hz1) in holes:
            # louvred vent panel recessed slightly
            poly(g, 'Grille', [F.p(h0, hz0, -0.012), F.p(h1, hz0, -0.012), F.p(h1, hz1, -0.012), F.p(h0, hz1, -0.012)], facing=F.N)
            for k in range(4):
                z = hz0 + 0.02 + k * 0.04
                fbox(g, 'Skirt', F, h0, h1, z, z + 0.012, -0.012, 0.006)
            fbox(g, 'Skirt', F, h0 - 0.02, h1 + 0.02, hz0 - 0.02, hz0, -0.012, 0.008)
            fbox(g, 'Skirt', F, h0 - 0.02, h1 + 0.02, hz1, hz1 + 0.02, -0.012, 0.008)
            fbox(g, 'Skirt', F, h0 - 0.02, h0, hz0, hz1, -0.012, 0.008)
            fbox(g, 'Skirt', F, h1, h1 + 0.02, hz0, hz1, -0.012, 0.008)
        # top J-channel and bottom rail
        fbox(g, 'Trim', F, u0 - 0.01, u1 + 0.01, zt - 0.05, zt, 0, 0.02)
        fbox(g, 'Trim', F, u0 - 0.01, u1 + 0.01, -0.02, 0.05, 0, 0.015)


def stair_run(g, x0, x1, y_top, z_top, n_rise, direction, run=0.27, tread_th=0.035):
    """Open wooden stair: stringers + treads, descending from (y_top, z_top) along `direction` (+1/-1 in y)
    or, if direction is a string 'x-', along -x from x0 (the landing edge) for a stair across x1..."""
    rise = z_top / n_rise
    L_ = (n_rise - 1) * run
    yb = y_top + direction * L_
    # stringers (2x12) as sloped boards on both sides
    for x in (x0 + 0.02, x1 - 0.02):
        pts = [(y_top, z_top - 0.035), (yb, rise - 0.035), (yb + direction * 0.12, 0.0), (yb - direction * 0.25, 0.0),
               (y_top, z_top - 0.32)]
        extrude(g, 'Wood', Fr((x, 0, 0), (1, 0, 0)), pts, -0.02, 0.02)
    for k in range(n_rise - 1):
        zt = z_top - rise * (k + 1)
        yc0 = y_top + direction * (k * run)
        yc1 = yc0 + direction * (run + 0.02)
        for b in range(2):
            ya = yc0 + direction * b * (run + 0.02) / 2
            yb2 = ya + direction * ((run + 0.02) / 2 - 0.008)
            box(g, 'Wood', x0, x1, ya, yb2, zt - tread_th, zt)
    return yb


def railing_x(g, x, y0, y1, z0, top=0.92, posts=True):
    """Railing along y at fixed x (2x2 balusters between a 2x4 cap and bottom rail)."""
    if posts:
        for y in (y0, y1):
            cbox(g, 'Wood', x, y, 0.09, 0.09, z0 - 0.15, z0 + top + 0.02)
    box(g, 'Wood', x - 0.045, x + 0.045, y0, y1, z0 + top - 0.04, z0 + top)
    box(g, 'Wood', x - 0.02, x + 0.02, y0, y1, z0 + top - 0.12, z0 + top - 0.04)
    box(g, 'Wood', x - 0.02, x + 0.02, y0, y1, z0 + 0.08, z0 + 0.12)
    n = max(1, int(abs(y1 - y0) / 0.13))
    for i in range(1, n):
        y = y0 + (y1 - y0) * i / n
        cbox(g, 'Wood', x, y, 0.038, 0.038, z0 + 0.12, z0 + top - 0.12)


def railing_y(g, y, x0, x1, z0, top=0.92, posts=True):
    if posts:
        for x in (x0, x1):
            cbox(g, 'Wood', x, y, 0.09, 0.09, z0 - 0.15, z0 + top + 0.02)
    box(g, 'Wood', x0, x1, y - 0.045, y + 0.045, z0 + top - 0.04, z0 + top)
    box(g, 'Wood', x0, x1, y - 0.02, y + 0.02, z0 + top - 0.12, z0 + top - 0.04)
    box(g, 'Wood', x0, x1, y - 0.02, y + 0.02, z0 + 0.08, z0 + 0.12)
    n = max(1, int(abs(x1 - x0) / 0.13))
    for i in range(1, n):
        x = x0 + (x1 - x0) * i / n
        cbox(g, 'Wood', x, y, 0.038, 0.038, z0 + 0.12, z0 + top - 0.12)


def build_porch(g):
    lx0, ly0, ly1, top = LAND['x0'], LAND['y0'], LAND['y1'], LAND['top']
    xw = X0 - 0.01
    # landing: decking boards running along x, rim joists, posts on concrete blocks
    nb = int((ly1 - ly0) / 0.145)
    for i in range(nb):
        ya = ly0 + i * (ly1 - ly0) / nb
        yb = ya + (ly1 - ly0) / nb - 0.007
        box(g, 'Wood', lx0, xw, ya, yb, top - 0.032, top)
    box(g, 'Wood', lx0, lx0 + 0.04, ly0, ly1, top - 0.22, top - 0.032)
    box(g, 'Wood', lx0, xw, ly0, ly0 + 0.04, top - 0.22, top - 0.032)
    box(g, 'Wood', lx0, xw, ly1 - 0.04, ly1, top - 0.22, top - 0.032)
    for (px, py) in ((lx0 + 0.05, ly0 + 0.05), (lx0 + 0.05, ly1 - 0.05), (xw - 0.08, ly0 + 0.05), (xw - 0.08, ly1 - 0.05)):
        cbox(g, 'Wood', px, py, 0.09, 0.09, 0.2, top - 0.032)
        cbox(g, 'Block', px, py, 0.4, 0.2, -0.05, 0.2)
    # stair down to the south, against the wall, onto the gravel pad
    sx0, sx1 = X0 - 0.03 - STAIR_W, X0 - 0.03
    yb = stair_run(g, sx0, sx1, ly0, top, N_RISE, -1)
    # railings: west and north sides of the landing, short return on the south side, stair outer rail
    railing_x(g, lx0 + 0.045, ly0 + 0.045, ly1 - 0.045, top)
    railing_y(g, ly1 - 0.045, lx0 + 0.045, xw - 0.06, top)
    railing_y(g, ly0 + 0.045, lx0 + 0.045, sx0, top, posts=False)
    cbox(g, 'Wood', sx0, ly0 + 0.045, 0.09, 0.09, 0.0, top + 0.94)
    # raked stair rail on the outer stringer
    xr = sx0 + 0.045
    ybot = yb - 0.05
    cbox(g, 'Wood', xr, ybot, 0.09, 0.09, 0.0, 0.95)
    p_top = Vector((xr, ly0 + 0.045, top + 0.90))
    p_bot = Vector((xr, ybot, 0.90))
    beam(g, 'Wood', p_top, p_bot, 0.09, 0.04)
    beam(g, 'Wood', p_top - Vector((0, 0, 0.75)), p_bot - Vector((0, 0, 0.75)), 0.04, 0.04)
    n = 6
    for i in range(1, n):
        t = i / n
        p = p_top.lerp(p_bot, t)
        cbox(g, 'Wood', xr, p.y, 0.038, 0.038, p.z - 0.75, p.z - 0.03)
    # concrete pad block at the stair foot
    box(g, 'Block', sx0 - 0.05, sx1, yb - 0.45, yb - 0.02, -0.05, 0.04)
    # back door stoop: small platform and three steps to the west, one handrail
    bx0 = X0 - 1.0
    by0, by1 = BDOOR_Y - 0.6, BDOOR_Y + 0.6
    btop = FL - 0.04
    for i in range(8):
        ya = by0 + i * (by1 - by0) / 8
        box(g, 'Wood', bx0, X0 - 0.01, ya, ya + (by1 - by0) / 8 - 0.007, btop - 0.032, btop)
    box(g, 'Wood', bx0, bx0 + 0.04, by0, by1, btop - 0.2, btop - 0.032)
    for (px, py) in ((bx0 + 0.05, by0 + 0.05), (bx0 + 0.05, by1 - 0.05)):
        cbox(g, 'Wood', px, py, 0.09, 0.09, 0.2, btop - 0.03)
        cbox(g, 'Block', px, py, 0.4, 0.2, -0.05, 0.2)
    rise = btop / 4
    for k in range(3):
        zt = btop - rise * (k + 1)
        xa = bx0 - k * 0.26
        box(g, 'Wood', xa - 0.27, xa, by0 + 0.1, by1 - 0.1, zt - 0.035, zt)
    for y in (by0 + 0.12, by1 - 0.12):
        extrude(g, 'Wood', Fr((0, y, 0), (0, 1, 0)), [(-(bx0), btop - 0.04), (-(bx0), btop - 0.3), (-(bx0 - 0.85), 0.0),
                                                      (-(bx0 - 0.95), 0.0), (-(bx0 - 0.95), 0.03)], -0.02, 0.02)
    cbox(g, 'Wood', bx0 - 0.83, by1 - 0.06, 0.07, 0.07, 0.0, 0.92)
    cbox(g, 'Wood', bx0 + 0.04, by1 - 0.06, 0.07, 0.07, 0.0, btop + 0.9)
    beam(g, 'Wood', (bx0 + 0.04, by1 - 0.06, btop + 0.87), (bx0 - 0.83, by1 - 0.06, 0.89), 0.06, 0.035)
    # doormat on the main landing, a potted plant in the corner
    box(g, 'Rubber', X0 - 0.85, X0 - 0.12, DOOR_Y - 0.4, DOOR_Y + 0.4, top, top + 0.012)
    lathe(g, 'Pot', [(0.11, 0.0), (0.15, 0.24), (0.16, 0.25), (0.0, 0.25)], lx0 + 0.25, ly1 - 0.25, seg=12, z0=top)
    gl = []
    rng = np.random.default_rng(4)
    for k in range(7):
        a = k / 7 * 2 * math.pi
        c = Vector((lx0 + 0.25 + 0.08 * math.cos(a), ly1 - 0.25 + 0.08 * math.sin(a), top + 0.36 + 0.05 * rng.random()))
        blob(g, 'Leaf', c, (0.11, 0.11, 0.09), seed=int(rng.integers(1000)))


def blob(g, mat, c, r3, seed=0, sub=2, rough=0.25, freq=1.6, tone=1.0):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
    off = Vector((seed * 1.37, seed * 0.71, seed * 2.13))
    V = []
    Cs = []
    for v in bm.verts:
        p = v.co.copy()
        d = 1 + rough * mnoise.noise(p * freq + off)
        q = Vector((c[0] + p.x * r3[0] * d, c[1] + p.y * r3[1] * d, c[2] + p.z * r3[2] * d))
        V.append(q)
        k = tone * (0.55 + 0.45 * (p.z * 0.5 + 0.5))
        Cs.append((k, k, k))
    F = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    g.add(V, F, mat, colors=Cs, smooth=True)


# ============================================================================ lot
def build_lot():
    gG = Geo('Lot_Pad')
    gP = Geo('Lot_Props')
    # gravel parking pad from the lane edge (curb line) up the west side to the foot of the stair
    pad = [(-5.62, CURB_Y), (-2.40, CURB_Y), (-2.45, -9.9), (-2.48, -4.70), (-2.75, -4.55), (-4.05, -4.50),
           (-4.70, -4.75), (-5.35, -5.10), (-5.62, -5.60)]
    slab(gG, 'Gravel', pad, 0.03, -0.05)
    # worn tire tracks in the gravel
    for xc in (-4.78, -3.28):
        tr = [(xc - 0.2, CURB_Y + 0.02), (xc + 0.2, CURB_Y + 0.02), (xc + 0.22, -5.9), (xc - 0.18, -5.7)]
        slab(gG, 'Dirt', tr, 0.033)
    # worn dirt where people walk: stair foot -> pad, back stoop, clothesline, along the lane end
    slab(gG, 'Dirt', [(-3.55, -4.5), (-2.5, -4.55), (-2.45, -3.0), (-3.0, -3.3), (-3.6, -3.9)], 0.028)
    slab(gG, 'Dirt', [(-4.6, 2.8), (-3.4, 2.75), (-2.45, 2.9), (-2.45, 4.35), (-3.6, 4.4), (-4.55, 4.1)], 0.026)
    slab(gG, 'Dirt', [(-4.95, 5.6), (-4.2, 5.5), (-4.1, 9.3), (-4.85, 9.4)], 0.024)
    slab(gG, 'Dirt', [(-2.3, CURB_Y), (2.6, CURB_Y), (2.2, -10.2), (-0.5, -9.95), (-2.3, -10.2)], 0.024)
    slab(gG, 'Gravel', [(2.75, CURB_Y), (4.7, CURB_Y), (4.75, -9.75), (2.8, -9.8)], 0.03, -0.05)
    # two 100-lb propane cylinders on a block pad by the kitchen, regulator and copper line
    box(gP, 'Block', -3.38, -2.47, 0.15, 0.62, -0.05, 0.06)
    for k, yc in enumerate((0.27, 0.62)):
        cx = -2.72 - 0.0 * k
        lathe(gP, 'Tank', [(0.0, 0.06), (0.17, 0.06), (0.185, 0.12), (0.185, 1.02), (0.16, 1.12), (0.1, 1.16),
                           (0.0, 1.17)], cx, yc, seg=18, z0=0.0)
        lathe(gP, 'Tank', [(0.17, 0.0), (0.17, 0.08), (0.0, 0.08)], cx, yc, seg=18, z0=0.0)
        # collar (protective ring) with a cut-out
        lathe(gP, 'Tank', [(0.12, 1.15), (0.13, 1.17), (0.13, 1.31), (0.115, 1.31), (0.115, 1.2)], cx, yc, seg=14, z0=0.0)
        lathe(gP, 'Galv', [(0.025, 1.16), (0.025, 1.26), (0.0, 1.27)], cx, yc, seg=8, z0=0.0)
    tube(gP, 'Copper', [(-2.72, 0.45, 1.24), (-2.6, 0.45, 1.3), (-2.52, 0.45, 1.05), (-2.5, 0.45, 0.5), (-2.48, 0.45, 0.3)],
         0.008, seg=5)
    box(gP, 'AluDark', -2.58, -2.48, 0.38, 0.52, 1.0, 1.12)
    # trash cart and recycling cart at the lane end
    for (cx, cy, mat, ang) in ((3.3, -10.15, 'Cart', 0.08), (4.12, -10.2, 'CartBlue', -0.05)):
        cart(gP, cx, cy, mat, ang)
    # webbed aluminum folding chair by the steps, facing the lane
    chair(gP, -4.75, -2.3, math.radians(200))
    # T-post clothesline with three lines and a few towels
    clothesline(gP, -4.55, 5.75, 9.45)
    # park power pedestal with meter (pressure-treated post) by the lane
    px, py = 1.95, -10.35
    cbox(gP, 'Wood', px, py, 0.1, 0.1, -0.1, 1.55)
    box(gP, 'Meter', px - 0.16, px + 0.16, py - 0.15, py - 0.05, 0.85, 1.35)
    Vm = []
    for i in range(14):
        a = 2 * math.pi * i / 14
        Vm.append((px + 0.085 * math.cos(a), py - 0.15, 1.12 + 0.085 * math.sin(a)))
    for i in range(14):
        a = 2 * math.pi * i / 14
        Vm.append((px + 0.08 * math.cos(a), py - 0.24, 1.12 + 0.08 * math.sin(a)))
    Fm = [[i, (i + 1) % 14, 14 + (i + 1) % 14, 14 + i] for i in range(14)] + [[14 + i for i in range(14)]]
    gP.add(Vm, Fm, 'MeterGlass', smooth=False)
    box(gP, 'Meter', px - 0.13, px + 0.13, py - 0.13, py - 0.05, 0.45, 0.8)
    tube(gP, 'Black', [(px, py + 0.05, 0.5), (px, py + 0.05, -0.1)], 0.02, seg=6)
    # garden hose coiled on the ground by the hose bib
    hose = []
    for i in range(46):
        a = i / 46 * 2 * math.pi * 2.6
        r = 0.22 + 0.012 * i / 4.6
        hose.append((-2.95 + r * math.cos(a), 1.3 + r * math.sin(a), 0.025 + 0.012 * (i % 9 == 0)))
    tube(gP, 'Hose', hose, 0.012, seg=5)
    tube(gP, 'Hose', [(-2.95 + 0.4, 1.3, 0.03), (-2.55, 1.3, 0.25), (-2.47, 1.3, 0.98)], 0.012, seg=5)
    # a couple of loose concrete blocks against the skirting
    box(gP, 'Block', 2.47, 2.87, 2.2, 2.4, 0.0, 0.2)
    box(gP, 'Block', 2.5, 2.9, 2.45, 2.65, 0.0, 0.2)
    return [gG, gP]


def cart(g, cx, cy, mat, ang):
    """96-gallon roll cart, lid hinge toward the trailer (+y), wheels at the back."""
    ca, sa = math.cos(ang), math.sin(ang)

    def R(x, y, z):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca, z)
    V, F = [], []
    prof = [(-0.29, -0.33, 0.06), (0.29, -0.33, 0.06), (0.29, 0.30, 0.06), (-0.29, 0.30, 0.06),
            (-0.34, -0.39, 1.02), (0.34, -0.39, 1.02), (0.34, 0.36, 1.02), (-0.34, 0.36, 1.02)]
    V = [R(*p) for p in prof]
    F = [[3, 2, 1, 0], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    g.add(V, F, mat)
    lid = [(-0.36, -0.42, 1.02), (0.36, -0.42, 1.02), (0.36, 0.40, 1.02), (-0.36, 0.40, 1.02)]
    V2 = [R(*p) for p in lid] + [R(p[0], p[1], 1.07) for p in lid]
    F2 = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7], [4, 5, 6, 7], [3, 2, 1, 0]]
    g.add(V2, F2, mat)
    # handle bar and wheels
    tube(g, 'Black', [R(-0.3, 0.42, 1.0), R(0.3, 0.42, 1.0)], 0.017, seg=6)
    for s in (-1, 1):
        c = R(s * 0.27, 0.31, 0.12)
        Vw = []
        for i in range(12):
            a = 2 * math.pi * i / 12
            for dx in (-0.03, 0.03):
                p = (s * 0.27 + dx, 0.31 + 0.12 * math.cos(a), 0.12 + 0.12 * math.sin(a))
                Vw.append(R(*p))
        Fw = [[2 * i, 2 * ((i + 1) % 12), 2 * ((i + 1) % 12) + 1, 2 * i + 1] for i in range(12)]
        Fw += [[2 * i for i in range(12)][::-1], [2 * i + 1 for i in range(12)]]
        g.add(Vw, Fw, 'Rubber', smooth=True)


def chair(g, cx, cy, ang):
    """Webbed aluminum folding lawn chair."""
    ca, sa = math.cos(ang), math.sin(ang)

    def R(x, y, z):
        return Vector((cx + x * ca - y * sa, cy + x * sa + y * ca, z))
    w = 0.56
    r = 0.011
    for s in (-1, 1):
        x = s * w / 2
        # front leg + armrest + back leg loop (side frame)
        tube(g, 'Alu', [R(x, -0.28, 0.0), R(x, -0.25, 0.38), R(x, -0.27, 0.6), R(x, 0.2, 0.62)], r, seg=6)
        tube(g, 'Alu', [R(x, 0.25, 0.0), R(x, 0.12, 0.38), R(x, 0.24, 0.92)], r, seg=6)
        tube(g, 'Alu', [R(x, -0.25, 0.38), R(x, 0.12, 0.38)], r, seg=6)
    tube(g, 'Alu', [R(-w / 2, 0.24, 0.92), R(w / 2, 0.24, 0.92)], r, seg=6)
    tube(g, 'Alu', [R(-w / 2, -0.25, 0.38), R(w / 2, -0.25, 0.38)], r, seg=6)
    tube(g, 'Alu', [R(-w / 2, 0.12, 0.38), R(w / 2, 0.12, 0.38)], r, seg=6)
    # webbing: seat strips (front-back) and back strips (vertical), with a slight sag
    n = 6
    for i in range(n):
        x0 = -w / 2 + 0.03 + i * (w - 0.06) / n
        x1 = x0 + (w - 0.06) / n - 0.012
        poly(g, 'Web', [R(x0, -0.25, 0.385), R(x1, -0.25, 0.385), R(x1, -0.06, 0.35), R(x0, -0.06, 0.35)], facing=(0, 0, 1))
        poly(g, 'Web', [R(x0, -0.06, 0.35), R(x1, -0.06, 0.35), R(x1, 0.12, 0.385), R(x0, 0.12, 0.385)], facing=(0, 0, 1))
    for k in range(5):
        z0 = 0.44 + k * 0.095
        z1 = z0 + 0.07
        y0 = 0.12 + (z0 - 0.38) / 0.54 * 0.12
        y1 = 0.12 + (z1 - 0.38) / 0.54 * 0.12
        poly(g, 'Web', [R(-w / 2, y0, z0), R(w / 2, y0, z0), R(w / 2, y1, z1), R(-w / 2, y1, z1)])
        poly(g, 'Web', [R(-w / 2, y0 + 0.004, z0), R(w / 2, y0 + 0.004, z0), R(w / 2, y1 + 0.004, z1), R(-w / 2, y1 + 0.004, z1)])


def clothesline(g, x, y0, y1):
    top = 1.9
    for y in (y0, y1):
        tube(g, 'Galv', [(x, y, -0.3), (x, y, top + 0.05)], 0.03, seg=8, caps=True)
        tube(g, 'Galv', [(x - 0.42, y, top), (x + 0.42, y, top)], 0.022, seg=8, caps=True)
        for dx in (-0.3, 0.3):
            tube(g, 'Galv', [(x, y, top - 0.32), (x + dx, y, top - 0.01)], 0.012, seg=6)
    lines = (-0.36, 0.0, 0.36)
    sag = 0.07

    def line_z(t):
        return top + 0.02 - sag * 4 * t * (1 - t)
    for dx in lines:
        pts = []
        for i in range(13):
            t = i / 12
            pts.append((x + dx, y0 + (y1 - y0) * t, line_z(t)))
        tube(g, 'Rubber', pts, 0.004, seg=4, smooth=True)
    # towels / a sheet hanging on the outer line (thin, slightly wavy cloth)
    items = [(-0.36, 0.12, 0.30, 0.62, 'Cloth1'), (-0.36, 0.36, 0.55, 0.85, 'Cloth2'),
             (0.36, 0.30, 0.52, 0.6, 'Cloth3'), (0.36, 0.62, 0.78, 0.62, 'Cloth1')]
    for dx, t0, t1, hang, mat in items:
        V, F = [], []
        nu, nv = 6, 4
        for j in range(nv + 1):
            for i in range(nu + 1):
                t = t0 + (t1 - t0) * i / nu
                yy = y0 + (y1 - y0) * t
                zz = line_z(t) - 0.01 - hang * j / nv
                wav = 0.035 * math.sin(i * 1.7 + j * 0.6) * (j / nv) + 0.01
                V.append((x + dx + wav, yy, zz))
        for j in range(nv):
            for i in range(nu):
                a = j * (nu + 1) + i
                F.append([a, a + 1, a + nu + 2, a + nu + 1])
        g.add(V, F, mat, smooth=True)


# ============================================================================ render-only surroundings
def hill_z(x, y):
    """Render-only wooded hills rising north of the park (the photo's backdrop)."""
    t = max(0.0, y - 42.0)
    return 0.32 * t + 6.0 * math.sin(x * 0.021 + 1.3) * min(1.0, t / 40.0) + 4.0 * math.sin(x * 0.047) * min(1.0, t / 60.0)


def tree(g, base, h, spread, seed, tone=1.0, sub=2, n=11, trunk=True, mat='Canopy'):
    rng = np.random.default_rng(seed)
    bx, by = base
    z0 = hill_z(bx, by)
    if trunk:
        tube(g, 'Bark', [(bx, by, z0 - 0.2), (bx + rng.normal(0, 0.2), by + rng.normal(0, 0.2), z0 + h * 0.6)],
             [0.2 * h / 12, 0.11 * h / 12], seg=7)
    for k in range(n):
        a = rng.uniform(0, 2 * math.pi)
        rr = spread * 0.5 * math.sqrt(rng.uniform(0.0, 1.0))
        zc = z0 + h * rng.uniform(0.5, 0.88) - (rr / spread) * h * 0.18
        c = (bx + rr * math.cos(a), by + rr * math.sin(a), zc)
        s = spread * rng.uniform(0.15, 0.24)
        blob(g, mat, c, (s, s, s * 0.85), seed=int(rng.integers(1e5)), sub=sub, rough=0.45, freq=2.6,
             tone=tone * rng.uniform(0.75, 1.1))


def car(g, cx, cy, heading=0.0):
    """Render-only parked sedan (not part of the lot GLB)."""
    ca, sa = math.cos(heading), math.sin(heading)

    def R(x, y, z):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca, z)
    prof = [(-2.33, 0.30), (2.30, 0.30), (2.38, 0.55), (2.33, 0.78), (1.10, 0.93), (0.35, 1.40), (-0.85, 1.42),
            (-1.65, 0.99), (-2.30, 0.95), (-2.38, 0.65)]
    hw = 0.89
    V = [R(-hw, y, z) for y, z in prof] + [R(hw, y, z) for y, z in prof]
    n = len(prof)
    F = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)] + [list(range(n)), list(range(n, 2 * n))[::-1]]
    gc = Geo('Render_Car')
    gc.add(V, F, 'CarPaint')
    o = gc.build()
    me = o.data
    import bmesh as _bm
    bm = _bm.new()
    bm.from_mesh(me)
    _bm.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    b = o.modifiers.new('bev', 'BEVEL')
    b.width = 0.07
    b.segments = 3
    b.limit_method = 'ANGLE'
    for f in me.polygons:
        f.use_smooth = True
    # glass: windshield, rear window, side windows
    gg = Geo('Render_CarGlass')
    w2 = 0.74
    poly(gg, 'CarGlass', [R(-w2, 1.06, 0.97), R(w2, 1.06, 0.97), R(w2, 0.38, 1.41), R(-w2, 0.38, 1.41)], facing=None)
    poly(gg, 'CarGlass', [R(-w2, -0.88, 1.43), R(w2, -0.88, 1.43), R(w2, -1.6, 1.03), R(-w2, -1.6, 1.03)], facing=None)
    for s in (-1, 1):
        x = s * (hw + 0.004)
        poly(gg, 'CarGlass', [R(x, 0.98, 0.99), R(x, 0.38, 1.33), R(x, -0.82, 1.35), R(x, -1.48, 1.01)], facing=None)
    for s in (-1, 1):
        for yy in (1.42, -1.38):
            Vw, Fw = [], []
            for i in range(16):
                a = 2 * math.pi * i / 16
                for dx in (-0.11, 0.11):
                    Vw.append(R(s * (0.8 + dx), yy + 0.33 * math.cos(a), 0.33 + 0.33 * math.sin(a)))
            Fw = [[2 * i, 2 * ((i + 1) % 16), 2 * ((i + 1) % 16) + 1, 2 * i + 1] for i in range(16)]
            Fw += [[2 * i for i in range(16)], [2 * i + 1 for i in range(16)][::-1]]
            gg.add(Vw, Fw, 'Rubber', smooth=True)
            Vh = []
            for i in range(12):
                a = 2 * math.pi * i / 12
                Vh.append(R(s * 0.915, yy + 0.2 * math.cos(a), 0.33 + 0.2 * math.sin(a)))
            gg.add(Vh, [list(range(12)) if s > 0 else list(range(12))[::-1]], 'Galv')
    for s in (-1, 1):
        poly(gg, 'CarLight', [R(s * 0.82, 2.36, 0.62), R(s * 0.45, 2.37, 0.64), R(s * 0.45, 2.33, 0.74), R(s * 0.8, 2.32, 0.73)])
        poly(gg, 'TailLight', [R(s * 0.84, -2.36, 0.72), R(s * 0.5, -2.37, 0.73), R(s * 0.5, -2.33, 0.88), R(s * 0.82, -2.32, 0.88)])
    return [o, gg.build()]


def render_extras(with_neighbors=True):
    objs = []
    MAT['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('ab_asphalt', kind='asphalt', color='#3e3d3b', tile=4.0),
                            rough=0.9)
    MAT['Bark'] = wp.mat('Bark', '#3a3128', rough=0.9)
    MAT['Canopy'] = vc_mat('Canopy', tex=tex_canopy('ab_canopy', '#536f30', tile=3.0), rough=0.8)
    MAT['Canopy2'] = vc_mat('Canopy2', tex=tex_canopy('ab_canopy2', '#6b8236', tile=3.0, seed=61), rough=0.8)
    MAT['HillGrass'] = wp.mat('HillGrass', tex=wp.tex_grass('ab_hillgrass', color='#56702f'), rough=0.95)
    MAT['CarPaint'] = wp.mat('CarPaint', '#5c2a2c', rough=0.32, metal=0.35)
    MAT['CarGlass'] = wp.mat('CarGlass', '#15191c', rough=0.05, double_sided=True)
    MAT['CarLight'] = wp.mat('CarLight', '#d9d6cc', rough=0.1)
    MAT['TailLight'] = wp.mat('TailLight', '#8a1a14', rough=0.2)
    gx = Geo('Render_Street')
    # the unnamed service lane (south), old asphalt with gravel shoulders
    slab(gx, 'Asphalt', [(-80, LANE_C - 2.75), (80, LANE_C - 2.75), (80, CURB_Y), (-80, CURB_Y)], 0.015)
    slab(gx, 'Gravel', [(-80, LANE_C - 3.3), (80, LANE_C - 3.3), (80, LANE_C - 2.75), (-80, LANE_C - 2.75)], 0.012)
    # access stub to the west
    slab(gx, 'Asphalt', [(STUB_X - 1.6, CURB_Y + 0.01), (STUB_X + 1.6, CURB_Y + 0.01), (STUB_X + 1.6, 7.5), (STUB_X - 1.6, 7.5)],
         0.014)
    objs.append(gx.build())
    # wooded hills behind the park
    gh = Geo('Render_Hill')
    xs = [-220 + 10 * i for i in range(45)]
    ys = [38 + 6 * j for j in range(30)]
    Vh = [(x, y, hill_z(x, y) - 0.03) for y in ys for x in xs]
    nx = len(xs)
    Fh = [[j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i] for j in range(len(ys) - 1) for i in range(nx - 1)]
    gh.add(Vh, Fh, 'HillGrass', smooth=True)
    objs.append(gh.build())
    # continuous forest canopy over the hill (crowns as noise bumps, darker in the hollows)
    gb = Geo('Render_Forest')
    fx = [-210 + 2.0 * i for i in range(211)]
    fy = [54 + 2.0 * j for j in range(60)]
    Vb, Cb = [], []
    for y in fy:
        for x in fx:
            n1 = mnoise.noise(Vector((x / 6.5, y / 6.5, 0.3)))
            n2 = mnoise.noise(Vector((x / 2.8, y / 2.8, 1.7)))
            n3 = mnoise.noise(Vector((x / 30.0, y / 30.0, 5.1)))
            h = (15.0 + 3.2 * n1 + 1.1 * n2 + 3.0 * n3) * min(1.0, (y - 54) / 5.0 + 0.35)
            Vb.append((x, y, hill_z(x, y) + h))
            k = 0.5 + 0.32 * (n1 * 0.5 + 0.5) + 0.12 * n2 + 0.08 * n3
            Cb.append((k, k, k))
    nfx = len(fx)
    Fb = [[j * nfx + i, j * nfx + i + 1, (j + 1) * nfx + i + 1, (j + 1) * nfx + i] for j in range(len(fy) - 1)
          for i in range(nfx - 1)]
    gb.add(Vb, Fb, 'Canopy', colors=Cb, smooth=True)
    objs.append(gb.build())
    rng = np.random.default_rng(12)
    gt = Geo('Render_Trees')
    # forest edge: a dense band of individual crowns in front of the canopy blanket
    for i in range(230):
        x = rng.uniform(-200, 200)
        y = rng.uniform(44, 64)
        tree(gt, (x, y), rng.uniform(14, 21), rng.uniform(8, 12), seed=100 + i, tone=rng.uniform(0.7, 1.08),
             sub=1, n=14, trunk=y < 52, mat='Canopy' if rng.random() < 0.7 else 'Canopy2')
    for i in range(40):
        x = rng.uniform(-110, -48)
        y = rng.uniform(-10, 45)
        tree(gt, (x, y), rng.uniform(12, 19), rng.uniform(8, 12), seed=700 + i, tone=rng.uniform(0.75, 1.05),
             sub=1, n=14, mat='Canopy' if rng.random() < 0.7 else 'Canopy2')
    for i, (x, y, h, sp) in enumerate([(6.2, 17.0, 10.0, 7.5), (-17.0, 14.5, 8.0, 6.0), (29.5, 14.0, 11.0, 8.0),
                                       (-30.5, -6.0, 9.0, 7.0)]):
        tree(gt, (x, y), h, sp, seed=900 + i, tone=1.0, n=18, mat='Canopy2' if i % 2 else 'Canopy')
    objs.append(gt.build())
    objs += car(None, -4.05, -8.1, heading=0.0)
    if with_neighbors:
        objs += place_neighbors()
    return objs


def tint_material(m, rgb):
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
    mix.inputs[7].default_value = (*[c ** 2.2 for c in rgb], 1.0)
    nt.links.new(mix.outputs[2], inp)


NEIGHBORS = [  # (archetype id, x, y, wall tint, roof tint, door tint)  -- Atlas lots 11.5 m apart, the north row ~28 m
    ('mobile-single-a', 11.47, -0.9, (0.86, 0.89, 0.92), (0.82, 0.82, 0.8), (0.5, 0.35, 0.25)),
    ('mobile-single-b', -11.47, 0.9, (0.93, 0.88, 0.78), (0.85, 0.62, 0.48), (0.35, 0.3, 0.28)),
    ('mobile-single-c', 22.94, -1.79, (0.82, 0.86, 0.8), (0.8, 0.8, 0.82), (0.6, 0.6, 0.62)),
    ('mobile-single-a', -22.94, 1.79, (0.97, 0.97, 0.95), (0.9, 0.9, 0.88), (0.4, 0.45, 0.5)),
    ('mobile-double', 2.29, 28.4, (0.9, 0.88, 0.84), (0.75, 0.75, 0.76), (0.6, 0.3, 0.25)),
    ('mobile-single-b', -9.18, 28.81, (0.8, 0.84, 0.86), (0.88, 0.86, 0.84), (0.5, 0.5, 0.5)),
    ('mobile-single-a', 13.76, 27.02, (0.95, 0.93, 0.86), (0.8, 0.8, 0.8), (0.3, 0.35, 0.45)),
    ('mobile-single-c', -20.65, 29.7, (0.88, 0.9, 0.93), (0.78, 0.78, 0.8), (0.55, 0.5, 0.45)),
    ('mobile-single-a', 25.2, 26.2, (0.86, 0.88, 0.84), (0.86, 0.84, 0.8), (0.45, 0.35, 0.3)),
    ('mobile-single-b', 34.4, -2.7, (0.9, 0.9, 0.9), (0.8, 0.6, 0.45), (0.5, 0.4, 0.3)),
    ('mobile-single-a', -34.4, 2.7, (0.85, 0.87, 0.88), (0.84, 0.84, 0.84), (0.5, 0.5, 0.45)),
]


def place_neighbors():
    out = []
    adir = os.path.join(REPO, 'models', 'archetypes')
    idx_p = os.path.join(adir, 'index-mobile.json')
    if not os.path.exists(idx_p):
        print('no archetypes yet: render without neighbours')
        return out
    idx = {a['id']: a for a in json.load(open(idx_p))}
    for k, (aid, x, y, wt, rt, dt) in enumerate(NEIGHBORS):
        p = os.path.join(adir, f'{aid}.glb')
        if not os.path.exists(p):
            continue
        before = set(bpy.data.objects)
        mats_before = set(bpy.data.materials)
        bpy.ops.import_scene.gltf(filepath=p)
        new = [o for o in bpy.data.objects if o not in before]
        newm = [m for m in bpy.data.materials if m not in mats_before]
        for m in newm:
            base = m.name.split('.')[0]
            if base == 'Wall':
                tint_material(m, wt)
            elif base == 'Roof':
                tint_material(m, rt)
            elif base == 'Door':
                tint_material(m, dt)
        # scale to the Atlas lot rectangle (5.0 x 19.0 x 3.5) like the map does; the double-wide keeps its size
        a = idx[aid]
        bw, bd, bh = a['bbox_m']
        if aid == 'mobile-double':
            sx, sy, sz = 1.0, 1.0, 1.0
        else:
            sx, sy, sz = 5.0 / bw, 19.0 / bd, 3.5 / bh
        for o in new:
            if o.parent is None:
                o.location = (x, y, 0)
                o.scale = (o.scale[0] * sx, o.scale[1] * sy, o.scale[2] * sz)
                if k % 3 == 2:
                    o.rotation_euler[2] += math.pi        # some units face the other way
        out += new
    return out


# ============================================================================ main
def export_set(objs, path):
    wp.finalize(objs)
    wp.export_glb(path, objs)
    return wp.tri_count(objs)


def bbox(objs):
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            mn = Vector((min(mn.x, p.x), min(mn.y, p.y), min(mn.z, p.z)))
            mx = Vector((max(mx.x, p.x), max(mx.y, p.y), max(mx.z, p.z)))
    return mn, mx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='24 samples, 640 x 400 previews')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--out', default=None)
    ap.add_argument('--views', default='hero,aerial')
    ap.add_argument('--samples', type=int, default=None)
    ap.add_argument('--res', default=None, help='WxH override')
    args = ap.parse_args()

    wp.reset()
    make_materials()
    house_geos = build_trailer()
    lot_geos = build_lot()
    for g in house_geos + lot_geos:
        print(f'{g.name:14s} {g.tris():7d} tris')
    house_objs = [g.build() for g in house_geos]
    lot_objs = [g.build() for g in lot_geos]
    mdir = os.path.join(REPO, 'models', 'homes')
    house_glb = os.path.join(mdir, f'{ID}.glb')
    lot_glb = os.path.join(mdir, f'{ID}-lot.glb')
    if args.no_export:
        wp.finalize(house_objs + lot_objs)
    else:
        th = export_set(house_objs, house_glb)
        tl = export_set(lot_objs, lot_glb)
        mn, mx = bbox(house_objs)
        lmn, lmx = bbox(lot_objs)
        print(f'house bbox {tuple(round(v, 2) for v in mn)} .. {tuple(round(v, 2) for v in mx)}')
        print(f'lot   bbox {tuple(round(v, 2) for v in lmn)} .. {tuple(round(v, 2) for v in lmx)}')
        ridge = roof_z(0.0)
        meta = {
            'id': ID, 'name': 'Abernathy trailer, lot 47', 'address': '1118 Holt Street, Lot 47',
            'neighborhood': 'Riverside', 'park': 'Riverside Mobile Home Community',
            'residents': ['Dalton Abernathy', 'Lisa Abernathy'],
            'status': "Canon 2 (address, lot 47); design from the author's photo (reference/dalton-park.webp)",
            'atlas_building_index': 173, 'footprint_m': [5.0, 19.0],
            'ridge_height_m': round(ridge, 2), 'top_height_m': round(mx.z, 2), 'stories': 1,
            'style': 'older single-wide manufactured home (16 x 61 ft box)',
            'front_note': 'front = lane end (south)',
            'orientation_note': ('Model frame: long axis along Blender Y (glTF -Z..+Z); the lane end (south, Atlas road 90, '
                                 'the unnamed service lane at Atlas y = -2165.2) faces -Y; the entry door, landing and '
                                 'steps are on the west long side (-X), toward the access stub (Atlas road 96). '
                                 'site-specs.json computed the long west side as the front with no street; that is '
                                 'superseded here.'),
            'materials': ['horizontal lap aluminum siding, 200 mm exposure: grey (about #A6ABAB) below the sills, '
                          'off-white (about #DCDDD7) above, split by an aluminum strip',
                          'low bowed galvanized steel roof with crimped cross seams every 1.2 m, worn silver roof '
                          'coating, rust at the seams and down-slope streaks',
                          'ribbed off-white vinyl skirting with louvred vents, splash-dirty at the bottom',
                          'mill-finish aluminum single-hung windows, blinds and curtains behind the glass',
                          'white steel entry door with a small light and an aluminum storm door',
                          'weathered pressure-treated pine landing, stairs and railings on concrete blocks',
                          'window AC unit, furnace roof jack, plumbing vents, bathroom fan'],
            'triangles': th + tl, 'triangles_house': th, 'triangles_lot': tl,
            'files': {'house': f'models/homes/{ID}.glb', 'lot': f'models/homes/{ID}-lot.glb'},
            'file_mb': {'house': round(os.path.getsize(house_glb) / 1e6, 2), 'lot': round(os.path.getsize(lot_glb) / 1e6, 2)},
            'house_bbox_m': [[round(v, 2) for v in mn], [round(v, 2) for v in mx]],
            'lot_bbox_m': [[round(v, 2) for v in lmn], [round(v, 2) for v in lmx]],
            'lot_local_rect_m': list(LOT),
            'curb_line_local_y': CURB_Y,
            'lane_centerline_local_y': LANE_C,
            'access_stub_local_x': round(STUB_X, 2),
            'notes': (f'Box {W:.2f} x {L:.2f} m (16 x 61 ft) inside the 5.0 x 19.0 m Atlas footprint; floor {FL} m above grade '
                      f'on the chassis, side walls to {EAVE} m, bowed roof crown {ridge:.2f} m (Atlas height 3.5 m). '
                      'From the photo: the single-wide type and proportions, grey and white horizontal siding, the low '
                      'metal roof with rust, skirting to the ground, aluminum windows, the wooden steps with a railing. '
                      'From the brief: door on the long side facing the stub, landing with steps and railing, window AC, '
                      'gravel pad, propane cylinder, trash bins, folding chair, short clothesline. Interpreted (not in '
                      'the photo or brief): the two-tone split at sill height, cross-seam spacing, the window layout '
                      '(living room at the lane end, bedrooms at the north end), the back door and its stoop, roof '
                      'jacks, the storm door, the second cylinder, the recycling cart, the power pedestal, hose and '
                      'loose blocks. The lot is the strip beside the trailer only (neighbours stand 11.5 m east and '
                      'west, so it is held to x = -5.7..5.7); the gravel pad meets the lane edge at y = -10.95 and '
                      'opens toward the access stub on its west side.')}
        with open(os.path.join(mdir, f'{ID}.json'), 'w') as f:
            json.dump(meta, f, indent=1)
        print(json.dumps({k: meta[k] for k in ('triangles', 'triangles_house', 'triangles_lot', 'file_mb', 'ridge_height_m')}))

    if args.no_render:
        return
    out = args.out or os.path.join(REPO, 'renders')
    samples = args.samples or (24 if args.quick else 96)
    res = (640, 400) if args.quick else (1600, 1000)
    if args.res:
        res = tuple(int(v) for v in args.res.split('x'))
    views = args.views.split(',')
    extras = render_extras(with_neighbors=True)
    wp.finalize([o for o in extras if o.type == 'MESH' and o.name.startswith('Render_')])
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=52, sun_az=200, threads=2, exposure=0.12)
    # soft, slightly hazy daylight like the photo: a broad sun and a brighter, greyer sky
    sc = bpy.context.scene
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 2
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sun.data.energy = 3.0
    sun.data.angle = math.radians(9.0)
    sun.data.color = (1.0, 0.97, 0.93)
    wnt = bpy.context.scene.world.node_tree
    bgn = wnt.nodes['Background']
    sky_link = bgn.inputs['Color'].links[0]
    mixn = wnt.nodes.new('ShaderNodeMix')
    mixn.data_type = 'RGBA'
    mixn.inputs['Factor'].default_value = 0.45
    mixn.inputs[7].default_value = (0.7, 0.72, 0.74, 1.0)
    wnt.links.new(sky_link.from_socket, mixn.inputs[6])
    wnt.links.new(mixn.outputs[2], bgn.inputs['Color'])
    bgn.inputs['Strength'].default_value = 0.6
    lawn = bpy.data.materials.get('RenderLawn')
    if lawn:
        mixl = lawn.node_tree.nodes.new('ShaderNodeMix')
        mixl.data_type = 'RGBA'
        mixl.blend_type = 'MULTIPLY'
        mixl.inputs['Factor'].default_value = 1.0
        mixl.inputs[7].default_value = (0.95, 1.0, 0.7, 1.0)
        bsd = lawn.node_tree.nodes['Principled BSDF']
        src = bsd.inputs['Base Color'].links[0].from_socket
        lawn.node_tree.links.new(src, mixl.inputs[6])
        lawn.node_tree.links.new(mixl.outputs[2], bsd.inputs['Base Color'])
        # large worn / dry patches, as in a park lawn
        nz = lawn.node_tree.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = 0.09
        nz.inputs['Detail'].default_value = 6.0
        ramp = lawn.node_tree.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.92, 0.98, 0.72, 1)
        ramp.color_ramp.elements[1].position = 0.7
        ramp.color_ramp.elements[1].color = (1.25, 1.02, 0.62, 1)
        lawn.node_tree.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
        lawn.node_tree.links.new(ramp.outputs['Color'], mixl.inputs[7])
    cars = [o for o in bpy.context.scene.objects if o.name.startswith('Render_Car')]
    if 'hero' in views:
        for o in cars:          # the parked car would stand between the lane and the entry; aerial only
            o.hide_render = True
        wp.camera(CAM_HERO['loc'], CAM_HERO['target'], CAM_HERO['lens'])
        wp.render(os.path.join(out, f'{ID}.jpg'))
        for o in cars:
            o.hide_render = False
    if 'aerial' in views:
        wp.camera(CAM_AERIAL['loc'], CAM_AERIAL['target'], CAM_AERIAL['lens'])
        wp.render(os.path.join(out, f'{ID}-aerial.jpg'))
    for v, c in CAM_DEBUG.items():
        if v in views:
            wp.camera(c['loc'], c['target'], c['lens'])
            wp.render(os.path.join(out, f'{ID}-{v}.jpg'))


if __name__ == '__main__':
    main()
