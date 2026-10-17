#!/usr/bin/env python3
"""Monet Williams's house, 648 Oak Street, Garden District (hero home #1).

Design from the author's photo (reference/monet-house.webp, also board-18.jpg): a Lowcountry
Victorian farmhouse. Two stories of pale blue-grey lap siding on brick piers with lattice, a steep
hipped roof with three front dormers, a deep wraparound porch (turned posts, fan brackets, sawn
balusters, scalloped valance, beadboard ceiling), a balcony with flower boxes over the double entry,
brick steps between brick cheek walls, navy shutters, a one-story hipped side wing on the left, a
rear kitchen ell and two brick chimneys. The lot GLB carries the picket fence and gate, brick walk,
shell driveway, beds, boxwood and azaleas, the rounded ornamental tree and three moss-hung live oaks.

Run (rebuilds GLBs, JSON and the final renders):
    python3 tools/blender/homes/monet_williams_house.py
Iteration renders (32 samples, 800 x 500, into a scratch folder):
    python3 tools/blender/homes/monet_williams_house.py --quick --out /path/to/scratch
Other flags: --no-render, --views hero,aerial
Set WP_TEX_DIR to a private scratch folder (textures are generated there).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import wp  # noqa: E402
import bpy  # noqa: E402,F401
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, noise as mnoise  # noqa: E402
from PIL import Image  # noqa: E402

ID = 'monet-williams-house'
REPO = wp.REPO

# ============================================================================ site + plan (meters)
# Local frame: origin = Atlas footprint centre at grade, front faces -Y, +X to the right from the street.
SITE = dict(footprint=(23.52, 20.01), curb_y=-28.66, lot=(-21.2, -28.66, 22.5, 22.5))
MX = 1.5                       # centre line of the main block / entry
X0, X1 = -4.7, 7.7             # main block side walls (12.4 m)
Y0, Y1 = -6.5, 4.5             # main block front / back walls (11.0 m)
FF1, FF2 = 0.95, 4.65          # finished floors (raised ~0.9 m on brick piers)
WT = 0.80                      # bottom of siding / top of piers
MAIN_TOP = 7.62                # top of main walls (hidden in the boxed eave)
OV = 0.5                       # main roof overhang
ZD = 7.82                      # main roof surface at the drip edge
SOF = ZD - 0.22                # main soffit
PF, PE = 38.0, 60.0            # main roof pitches: front/back, hip ends
TF, TE = math.tan(math.radians(PF)), math.tan(math.radians(PE))
ZR = ZD + ((Y1 - Y0) / 2 + OV) * TF   # ridge height
YM = (Y0 + Y1) / 2
RX0 = X0 - OV + (ZR - ZD) / TE
RX1 = X1 + OV - (ZR - ZD) / TE
DORMERS = [MX - 3.9, MX, MX + 3.9]
DY = -5.85                     # dormer front wall line
CHIMNEYS = [(MX - 2.6, 1.6), (MX + 2.6, 1.6)]
CH_TOP = ZR + 0.85

# porch
PFL = 0.90                     # porch floor
PD = 3.0                       # porch depth from the wall to the floor edge
PIN = 0.12                     # post centre inset from the floor edge
PEV = 0.35                     # porch eave beyond the post line
PP = 12.5                      # porch roof pitch
TP = math.tan(math.radians(PP))
PZE = 3.96                     # porch roof surface at its drip edge
P_BEAM = (3.58, 3.88)
P_SOF = PZE - 0.2
P_CEIL = 3.86
YPF = Y0 - PD                  # porch front edge
XPL, XPR = X0 - PD, X1 + PD    # porch side edges
LRET, RRET = -3.43, 0.8        # back ends of the left / right porch returns (floor)
PDEP = PD - PIN + PEV          # eave-to-wall depth (equal on all sides -> clean hips)
PZW = PZE + PDEP * TP          # porch roof where it meets the wall
BAL = (MX - 2.05, MX + 2.05, 1.3)   # balcony x range and depth
BAL_DECK = 4.83
DSTEP_W = 1.8                  # side steps at the back end of the right porch return (toward the drive)
DSTEP_X = XPR - PIN - DSTEP_W / 2 - 0.165

# side wing (left) and rear ell
WX0, WY0, WY1 = -11.3, -1.6, 4.0
W_TOP, W_ZD, W_P = 4.2, 4.35, 30.0
EX0, EX1, EY1 = -0.3, 5.2, 9.3
E_TOP, E_ZD, E_P = 3.95, 4.1, 26.0

# hero camera roughly where the author's photo was taken (in Oak Street, just off the curb)
CAM_HERO = dict(loc=(-0.9, -30.3, 1.65), target=(0.75, -6.5, 5.4), lens=27)
CAM_DEBUG = {
    'porch': dict(loc=(MX + 7.5, -17.5, 2.0), target=(MX + 1.0, -8.0, 2.6), lens=32),
    'wing': dict(loc=(-17.0, -13.0, 3.0), target=(-7.5, -3.0, 2.8), lens=30),
    'back': dict(loc=(14.0, 22.0, 6.0), target=(1.0, 3.0, 4.0), lens=30),
    'roof': dict(loc=(MX - 2.0, -19.0, 14.5), target=(MX, -3.0, 9.5), lens=40),
}
CAM_AERIAL = dict(loc=(44.0, -58.0, 48.0), target=(1.0, -7.0, 2.0), lens=36)


# ============================================================================ mesh builder
class Fr:
    """Right-handed local frame: u along U, z along Z = N x U, d along N (outward)."""

    def __init__(self, O, U, N):
        self.O = Vector(O)
        self.U = Vector(U).normalized()
        self.N = Vector(N).normalized()
        self.Z = self.N.cross(self.U)
        if abs(self.U.z) < 1e-6 and abs(self.N.z) < 1e-6:
            assert self.Z.z > 0.5, 'left-handed wall frame'

    def p(self, u, z, d=0.0):
        return self.O + self.U * u + self.Z * z + self.N * d

    def side(self):
        """Frame whose (u, z) are this frame's (d, z); extrusion runs along -U."""
        return Fr(self.O, self.N, -self.U)


WORLD = Fr((0, 0, 0), (1, 0, 0), (0, 0, 1))   # p(u, z, d) = (u, z, d) = (x, y, z)


class Geo:
    """Accumulates polygons for one output object (several materials)."""

    def __init__(self, name):
        self.name = name
        self.V, self.F, self.FM, self.FS, self.VC = [], [], [], [], []
        self.UV = {}
        self.NRM = {}
        self.mats = []
        self.has_vc = False

    def add(self, verts, faces, mat, smooth=False, colors=None, uvs=None, normals=None):
        if normals is not None:
            b0 = len(self.V)
            for i, nv in enumerate(normals):
                self.NRM[b0 + i] = tuple(nv)
        if mat not in self.mats:
            self.mats.append(mat)
        mi = self.mats.index(mat)
        b = len(self.V)
        self.V.extend([tuple(v) for v in verts])
        if colors is not None:
            self.has_vc = True
            self.VC.extend([tuple(c[:3]) for c in colors])
        else:
            self.VC.extend([(1.0, 1.0, 1.0)] * len(verts))
        for k, f in enumerate(faces):
            if uvs is not None and uvs[k] is not None:
                self.UV[len(self.F)] = uvs[k]
            self.F.append(tuple(b + i for i in f))
            self.FM.append(mi)
            self.FS.append(smooth)

    def tris(self):
        return sum(len(f) - 2 for f in self.F)

    def build(self):
        me = bpy.data.meshes.new(self.name)
        me.from_pydata(self.V, [], self.F)
        for m in self.mats:
            me.materials.append(MAT[m])
        me.polygons.foreach_set('material_index', self.FM)
        me.polygons.foreach_set('use_smooth', self.FS)
        if self.has_vc:
            ca = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
            li = [0] * len(me.loops)
            me.loops.foreach_get('vertex_index', li)
            cols = []
            for vi in li:
                c = self.VC[vi]
                cols.extend((c[0], c[1], c[2], 1.0))
            ca.data.foreach_set('color', cols)
        me.update()
        if self.NRM:
            li = [0] * len(me.loops)
            me.loops.foreach_get('vertex_index', li)
            cn = [tuple(c.vector) for c in me.corner_normals]
            me.normals_split_custom_set([self.NRM.get(vi, cn[k]) for k, vi in enumerate(li)])
        o = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(o)
        o['_geo'] = self.name
        GEOS[self.name] = self
        return o


GEOS = {}
MAT = {}
G_PLANTS = None


def apply_custom_uvs(o):
    """After wp.finalize (box UVs), overwrite the faces that carry their own UVs (roofs, bark)."""
    g = GEOS.get(o.get('_geo'))
    if not g or not g.UV:
        return
    me = o.data
    uvl = me.uv_layers.active.data
    for fi, uvs in g.UV.items():
        poly_ = me.polygons[fi]
        t = me.materials[poly_.material_index].get('tile', 1.0)
        for k, li in enumerate(range(poly_.loop_start, poly_.loop_start + poly_.loop_total)):
            uvl[li].uv = (uvs[k][0] / t, uvs[k][1] / t)


# ---------------------------------------------------------------------------- primitives
def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def newell(pts):
    n = Vector((0, 0, 0))
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n


def poly(g, mat, pts, facing=None, uv=None, smooth=False):
    pts = [Vector(p) for p in pts]
    if facing is not None and newell(pts).dot(Vector(facing)) < 0:
        pts = pts[::-1]
        if uv:
            uv = uv[::-1]
    g.add(pts, [list(range(len(pts)))], mat, smooth=smooth, uvs=[uv] if uv else None)


def extrude(g, mat, F, pts, d0, d1, smooth=False, caps=True, smooth_sides=False):
    """Polygon [(u, z)] in frame F, extruded along F.N from d0 to d1."""
    if _area(pts) < 0:
        pts = pts[::-1]
    if d1 < d0:
        d0, d1 = d1, d0
    n = len(pts)
    V = [F.p(u, z, d0) for u, z in pts] + [F.p(u, z, d1) for u, z in pts]
    faces = []
    sides = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    if smooth_sides:
        g.add(V, sides, mat, True)
        if caps:
            g.add(V, [list(range(n))[::-1], list(range(n, 2 * n))], mat, False)
        return
    if caps:
        faces.append(list(range(n))[::-1])
        faces.append(list(range(n, 2 * n)))
    g.add(V, faces + sides, mat, smooth)


def fbox(g, mat, F, u0, u1, z0, z1, d0, d1):
    if u1 - u0 <= 1e-5 or z1 - z0 <= 1e-5 or abs(d1 - d0) <= 1e-5:
        return
    extrude(g, mat, F, [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], d0, d1)


def box(g, mat, x0, x1, y0, y1, z0, z1):
    fbox(g, mat, WORLD, x0, x1, y0, y1, z0, z1)


def cbox(g, mat, cx, cy, sx, sy, z0, z1):
    box(g, mat, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1)


def seg_frame(p0, p1, up=(0, 0, 1)):
    p0, p1 = Vector(p0), Vector(p1)
    U = (p1 - p0).normalized()
    up = Vector(up)
    N = (up - U * up.dot(U)).normalized()
    return Fr(p0, U, N), (p1 - p0).length


def seg_box(g, mat, p0, p1, w, h, up=(0, 0, 1), d0=0.0, ext=0.0):
    """Beam from p0 to p1; cross-section w wide (sideways) and h along `up`, starting at d0."""
    F, L = seg_frame(p0, p1, up)
    extrude(g, mat, F, [(-ext, -w / 2), (L + ext, -w / 2), (L + ext, w / 2), (-ext, w / 2)], d0, d0 + h)


def lathe(g, mat, prof, cx, cy, seg=10, caps=True):
    V, F = [], []
    for r, z in prof:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            V.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    for k in range(len(prof) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            F.append([k * seg + i, k * seg + j, (k + 1) * seg + j, (k + 1) * seg + i])
    g.add(V, F, mat, smooth=True)
    if caps:
        r0, z0 = prof[0]
        r1, z1 = prof[-1]
        if r0 > 0:
            poly(g, mat, [(cx + r0 * math.cos(2 * math.pi * i / seg), cy + r0 * math.sin(2 * math.pi * i / seg), z0)
                          for i in range(seg)], facing=(0, 0, -1))
        if r1 > 0:
            poly(g, mat, [(cx + r1 * math.cos(2 * math.pi * i / seg), cy + r1 * math.sin(2 * math.pi * i / seg), z1)
                          for i in range(seg)], facing=(0, 0, 1))


def tube(g, mat, pts, radii, seg=8, colors=None, cap_end=True):
    """Tapered tube through pts (parallel-transport frames), with cylindrical UVs in meters."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    T = []
    for k in range(n):
        a = pts[max(k - 1, 0)]
        b = pts[min(k + 1, n - 1)]
        T.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    n1 = (ref - T[0] * ref.dot(T[0])).normalized()
    N1 = [n1]
    for k in range(1, n):
        v = N1[-1] - T[k] * N1[-1].dot(T[k])
        N1.append(v.normalized() if v.length > 1e-6 else N1[-1])
    V, C = [], []
    vs = [0.0]
    for k in range(1, n):
        vs.append(vs[-1] + (pts[k] - pts[k - 1]).length)
    for k in range(n):
        n2 = T[k].cross(N1[k])
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            V.append(pts[k] + radii[k] * (math.cos(a) * N1[k] + math.sin(a) * n2))
            C.append(colors[k] if colors else (1, 1, 1))
    F, UV = [], []
    for k in range(n - 1):
        circ = 2 * math.pi * (radii[0] + radii[-1]) / 2
        circ = max(1.6, round(circ / 1.6) * 1.6) if circ > 0.6 else circ
        for i in range(seg):
            a, b = k * (seg + 1) + i, k * (seg + 1) + i + 1
            c, d = (k + 1) * (seg + 1) + i + 1, (k + 1) * (seg + 1) + i
            F.append([a, b, c, d])
            u0, u1 = circ * i / seg, circ * (i + 1) / seg
            UV.append([(u0, vs[k]), (u1, vs[k]), (u1, vs[k + 1]), (u0, vs[k + 1])])
    if cap_end:
        last = [(n - 1) * (seg + 1) + i for i in range(seg)]
        F.append(last)
        UV.append(None)
    g.add(V, F, mat, smooth=True, colors=C if colors else None, uvs=UV)


_ICO = {}


def ico(sub):
    if sub not in _ICO:
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
        _ICO[sub] = ([tuple(v.co) for v in bm.verts], [[v.index for v in f.verts] for f in bm.faces])
        bm.free()
    return _ICO[sub]


def blob(g, mat, c, r3, seed, rough=0.28, freq=1.4, sub=3, colfn=None, flat_bottom=None, nfn=None):
    V0, F0 = ico(sub)
    rng = np.random.default_rng(seed)
    off = Vector(rng.uniform(-50, 50, 3))
    verts, cols, nrms = [], [], []
    for v in V0:
        d = Vector(v)
        s = 1 + rough * mnoise.noise(d * freq + off) + rough * 0.45 * mnoise.noise(d * freq * 2.7 + off * 1.3)
        if sub >= 3:
            s += rough * 0.3 * mnoise.noise(d * freq * 6.0 + off * 0.7)
        p = Vector((c[0] + d.x * r3[0] * s, c[1] + d.y * r3[1] * s, c[2] + d.z * r3[2] * s))
        if flat_bottom is not None and p.z < flat_bottom:
            p.z = flat_bottom + (p.z - flat_bottom) * 0.15
        verts.append(p)
        cols.append(colfn(p, d) if colfn else (1, 1, 1))
        if nfn:
            nrms.append(nfn(p, d))
    g.add(verts, F0, mat, smooth=True, colors=cols if colfn else None, normals=nrms if nfn else None)


def crown_normals(center, radii, own=0.35):
    """Foliage normal: mostly the outward normal of the whole crown ellipsoid, a little of the clump's own."""
    cx, cy, cz = center
    rx, ry, rz = radii

    def f(p, d):
        n = Vector(((p.x - cx) / (rx * rx), (p.y - cy) / (ry * ry), (p.z - cz) / (rz * rz)))
        n = n.normalized() if n.length > 1e-9 else Vector((0, 0, 1))
        m = n * (1 - own) + d.normalized() * own
        return tuple(m.normalized())
    return f


def path_offset(path, d):
    """Offset a rectilinear polyline to its LEFT by d (all corners are left turns here)."""
    segs = []
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L, dx / L
        segs.append(((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d)))
    out = [segs[0][0]]
    for (a0, a1), (b0, b1) in zip(segs, segs[1:]):
        # intersect line a with line b (axis aligned)
        if abs(a0[1] - a1[1]) < 1e-9:     # a horizontal
            out.append((b0[0], a0[1]))
        else:
            out.append((a0[0], b0[1]))
    out.append(segs[-1][1])
    return out


def path_frames(path):
    """For each segment: frame with U along travel, N = right normal (outward), Z = up."""
    fr = []
    for a, b in zip(path, path[1:]):
        U = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
        N = U.cross(Vector((0, 0, 1)))
        fr.append((Fr((a[0], a[1], 0), U, N), (Vector(b) - Vector(a)).length))
    return fr


def path_run(g, mat, path, z0, z1, d_out, d_in, closed=False):
    """Boxes along a rectilinear (left-turning) path, cross-section from d_out (outward, >=0) to d_in
    (inward, <=0) relative to the path line; corners are owned by the earlier segment."""
    frs = path_frames(path)
    for k, (F, L) in enumerate(frs):
        s0 = (-d_in) if (k > 0 or closed) else 0.0
        s1 = L + d_out if (k < len(frs) - 1 or closed) else L
        fbox(g, mat, F, s0, s1, z0, z1, d_in, d_out)


def scallop_profile(s0, s1, z_top, z_b, r):
    n = max(1, int((s1 - s0) / (2 * r)))
    m = ((s1 - s0) - 2 * r * n) / 2
    pts = [(s0, z_top), (s0, z_b)]
    if m > 0.004:
        pts.append((s0 + m, z_b))
    for k in range(n):
        uc = s0 + m + r + 2 * r * k
        for j in range(1, 4):
            ph = math.pi * j / 4
            pts.append((uc - r * math.cos(ph), z_b - r * math.sin(ph)))
        pts.append((uc + r, z_b))
    if m > 0.004:
        pts.append((s1, z_b))
    pts.append((s1, z_top))
    # drop duplicates
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-6 or abs(p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    return out


def scallop_fascia(g, path, z_top, z_sof, hb=0.045, r=0.05, th=0.025, closed=False):
    """Fascia board along the eave path with a scalloped (gingerbread) lower edge hanging below the soffit."""
    frs = path_frames(path)
    for k, (F, L) in enumerate(frs):
        s0 = th if (k > 0 or closed) else 0.0
        s1 = L
        pts = scallop_profile(s0, s1, z_top, z_sof - hb, r)
        extrude(g, 'Trim', F, pts, -th, 0.0)


def roof_slab(g, P, th=0.05, top='Roof', edge='Metal', bottom='Trim'):
    """Planar roof polygon P (3D, any winding) -> slab with shingle UVs following the slope."""
    P = [Vector(p) for p in P]
    n = newell(P).normalized()
    if n.z < 0:
        P = P[::-1]
        n = -n
    e = Vector((0, 0, 1)).cross(n)
    if e.length < 1e-6:
        e = Vector((1, 0, 0))
    e.normalize()
    s = (Vector((0, 0, 1)) - n * n.z).normalized()
    uv = [(p.dot(e), p.dot(s)) for p in P]
    m = len(P)
    B = [p - n * th for p in P]
    g.add(P, [list(range(m))], top, uvs=[uv])
    g.add(B, [list(range(m))[::-1]], bottom)
    for i in range(m):
        j = (i + 1) % m
        g.add([B[i], B[j], P[j], P[i]], [[0, 1, 2, 3]], edge)


def roof_caps(g, faces, w=0.24, th=0.03):
    """Cap shingles folded over every edge two roof planes share (ridges and hips)."""
    F = [[Vector(p) for p in f] for f in faces]
    norms = []
    for f in F:
        n = newell(f).normalized()
        norms.append(n if n.z > 0 else -n)
    cents = [sum(f, Vector()) / len(f) for f in F]
    done = set()
    for i in range(len(F)):
        for j in range(i + 1, len(F)):
            for a in range(len(F[i])):
                p, q = F[i][a], F[i][(a + 1) % len(F[i])]
                if (p - q).length < 0.05:
                    continue
                shared = any(((p - F[j][b]).length < 1e-3 and (q - F[j][(b + 1) % len(F[j])]).length < 1e-3) or
                             ((q - F[j][b]).length < 1e-3 and (p - F[j][(b + 1) % len(F[j])]).length < 1e-3)
                             for b in range(len(F[j])))
                if not shared:
                    continue
                key = tuple(round(v, 3) for v in (p + q))
                if key in done:
                    continue
                done.add(key)
                lo, hi = (p, q) if p.z <= q.z else (q, p)
                v = hi - lo
                if abs(v.z) > 0.05:      # hip: stop the caps short of the eave
                    lo = lo + v.normalized() * 0.12
                for k in (i, j):
                    t = norms[k].cross(v).normalized()
                    if (cents[k] - lo).dot(t) < 0:
                        t = -t
                    lift = norms[k] * th
                    P = [lo + lift, hi + lift, hi + t * (w / 2) + lift, lo + t * (w / 2) + lift]
                    roof_slab(g, P, th=th + 0.004, top='Roof', edge='Roof', bottom='Roof')


# ============================================================================ textures + materials
def tex_paint(key, color, n=512, tile=1.0, seed=11, amp=0.035):
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 4 * tile, rng, 4)
    fine = wp._noise(n, 48 * tile, rng, 2)
    grain = fine.copy()
    for s in (1, 2, 3, 5, 8, 13):
        grain += np.roll(fine, s, axis=1) + np.roll(fine, -s, axis=1)
    grain = (grain - grain.min()) / (grain.max() - grain.min())
    base = wp._rgb(color)
    alb = base[None, None, :] * (1 - amp + 2 * amp * big[..., None]) * (0.985 + 0.03 * grain[..., None])
    h = big * 0.2 + grain * 0.5
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 0.35), key + '_n'), tile


def tex_roof(key):
    alb_p, nrm_p, tile = wp.tex_shingles(key, color='#77706f', n=2048, tile=4.0, seed=31)
    Image.open(nrm_p).resize((1024, 1024), Image.LANCZOS).save(nrm_p, quality=88)
    a = np.asarray(Image.open(alb_p)).astype(np.float32) / 255
    n = a.shape[0]
    rng = np.random.default_rng(32)
    big = wp._noise(n, 3, rng, 4)
    streak = wp._noise(n, 12, rng, 3)
    st = streak.copy()
    for s in (6, 12, 24, 48, 96, 160):
        st += np.roll(streak, s, 0)
    st = (st - st.min()) / (st.max() - st.min())
    algae = np.clip((st - 0.6) * 2.5, 0, 1) * 0.18
    a = a * (0.9 + 0.2 * big)[..., None] * (1 - algae[..., None])
    a[..., 0] *= (0.98 + 0.05 * big)
    a[..., 2] *= (1.03 - 0.05 * big)
    Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).save(alb_p, quality=88)
    return alb_p, nrm_p, tile


def tex_bark(key, n=1024, tile=1.6, seed=41):
    """Live-oak bark: dark, irregular vertical furrows broken into short blocky plates, lichen patches."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] / n
    w1 = wp._noise(n, 4, rng, 4)
    w2 = wp._noise(n, 9, rng, 3)
    kx = 26
    fx = kx * x + 3.0 * (w1 - 0.5) + 0.8 * (w2 - 0.5)
    fur = np.abs(np.sin(np.pi * fx)) ** 0.6
    col = np.floor(fx).astype(int) % kx
    off = np.random.default_rng(seed + 1).random(kx)[col]
    brk_n = wp._noise(n, 24, rng, 2)
    brk = np.clip((np.abs(np.sin(np.pi * (11 * y + off * 4 + 2.0 * (w2 - 0.5)))) - 0.08) * 6, 0, 1)
    brk = np.maximum(brk, (brk_n > 0.45).astype(np.float32))
    plate = np.clip(fur * 1.4 - 0.15, 0, 1) * brk
    fine = wp._noise(n, 90, rng, 2)
    lich = np.clip((wp._noise(n, 10, rng, 3) - 0.58) * 3.5, 0, 1)
    dark, light, lc = wp._rgb('#17130f'), wp._rgb('#4a3f36'), wp._rgb('#737765')
    alb = dark + (light - dark) * (plate * (0.6 + 0.4 * fine))[..., None]
    lm = (lich * plate)[..., None] * 0.6
    alb = alb * (1 - lm) + lc * lm
    h = plate * 0.8 + fine * 0.2
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 3.0), key + '_n'), tile


def tex_leaves(key, color, n=1024, tile=1.5, seed=51, flowers=None, fcov=0.0, fsize=70):
    rng = np.random.default_rng(seed)
    l1 = wp._noise(n, 45 * tile, rng, 2)
    l2 = wp._noise(n, 100 * tile, rng, 2)
    big = wp._noise(n, 3 * tile, rng, 3)
    leaf = np.clip((l1 * 0.6 + l2 * 0.4 - 0.28) * 2.3, 0, 1)
    base = wp._rgb(color)
    alb = base[None, None, :] * (0.35 + 0.85 * leaf[..., None]) * (0.86 + 0.28 * big[..., None])
    alb[..., 1] *= (0.95 + 0.1 * l2)
    if flowers:
        f = wp._noise(n, fsize * tile, np.random.default_rng(seed + 5), 2)
        fm = np.clip((f - (1 - fcov)) * 9, 0, 1)
        fc = wp._rgb(flowers)[None, None, :] * (0.8 + 0.3 * l2[..., None])
        alb = alb * (1 - fm[..., None]) + fc * fm[..., None]
        leaf = np.maximum(leaf, fm)
    return wp._save(alb, key), wp._save(wp._normal_from_height(leaf, 1.6), key + '_n'), tile


def tex_canopy(key, color, n=1024, tile=2.0, seed=58, lo=0.22):
    """Tree canopy surface: leaf clusters ~10-15 cm with dark gaps (features that survive at 25 m),
    fine leaves inside, sunlit yellow-green flecks."""
    rng = np.random.default_rng(seed)
    cl = wp._noise(n, 14 * tile, rng, 2)
    cl2 = wp._noise(n, 26 * tile, rng, 2)
    fine = wp._noise(n, 90 * tile, rng, 2)
    big = wp._noise(n, 2 * tile, rng, 3)
    clusters = np.clip((cl * 0.65 + cl2 * 0.35 - 0.36) * 3.2, 0, 1)
    leaf = clusters * (0.65 + 0.35 * fine)
    base = wp._rgb(color)
    alb = base[None, None, :] * (lo + (1.17 - lo) * leaf[..., None]) * (0.85 + 0.3 * big[..., None])
    hl = np.clip((fine - 0.62) * 4, 0, 1) * clusters
    alb = alb * (1 - 0.35 * hl[..., None]) + wp._rgb('#a4ad5c')[None, None, :] * 0.35 * hl[..., None]
    return wp._save(alb, key), wp._save(wp._normal_from_height(leaf, 2.4), key + '_n'), tile


def tex_moss(key, n=512, tile=1.0, seed=61):
    rng = np.random.default_rng(seed)
    f = wp._noise(n, 60, rng, 2)
    s = f.copy()
    for k in range(1, 28):
        s += np.roll(f, k * 3, 0)
    s = (s - s.min()) / (s.max() - s.min())
    base = wp._rgb('#878980')
    alb = base[None, None, :] * (0.6 + 0.5 * s[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(s, 1.0), key + '_n'), tile


def tex_straw(key, n=1024, tile=1.5, seed=71):
    rng = np.random.default_rng(seed)
    f = wp._noise(n, 120, rng, 2)
    s1, s2 = f.copy(), f.copy()
    for k in range(1, 10):
        s1 += np.roll(f, k * 2, 1)
        s2 += np.roll(np.roll(f, k * 2, 0), k, 1)
    s = np.maximum(s1, s2)
    s = (s - s.min()) / (s.max() - s.min())
    big = wp._noise(n, 4, rng, 3)
    base = wp._rgb('#7b5636')
    alb = base[None, None, :] * (0.45 + 0.8 * s[..., None]) * (0.85 + 0.3 * big[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(s, 1.5), key + '_n'), tile


def tex_glass(key, n=512, tile=3.0, seed=81):
    """Dark glazing with faint interior shapes (curtains, rooms) so windows do not read as identical."""
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 3, rng, 3)
    folds = wp._noise(n, 18, rng, 2)
    fs = folds.copy()
    for k in range(1, 20):
        fs += np.roll(folds, k * 2, 0)
    fs = (fs - fs.min()) / (fs.max() - fs.min())
    curtain = np.clip((big - 0.5) * 3, 0, 1) * (0.6 + 0.4 * fs)
    dark, light = wp._rgb('#252b30'), wp._rgb('#8a8a86')
    alb = dark + (light - dark) * (curtain * 0.55)[..., None]
    return wp._save(alb, key), None, tile


def vc_material(name, tex, rough=0.75, double=False, spec=0.4):
    """Texture x vertex colour (exported as COLOR_0)."""
    m = wp.mat(name, '#ffffff', rough=rough, tex=tex, double_sided=double)
    nt = m.node_tree
    bs = nt.nodes['Principled BSDF']
    t = [nd for nd in nt.nodes if nd.type == 'TEX_IMAGE' and nd.image and not nd.image.name.endswith('_n.jpg')][0]
    ca = nt.nodes.new('ShaderNodeVertexColor')
    ca.layer_name = 'Col'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    nt.links.new(t.outputs['Color'], mix.inputs[6])
    nt.links.new(ca.outputs['Color'], mix.inputs[7])
    nt.links.new(mix.outputs[2], bs.inputs['Base Color'])
    try:
        bs.inputs['Specular IOR Level'].default_value = spec
    except Exception:
        pass
    return m


def make_materials():
    M = {}
    M['Siding'] = wp.mat('Siding', tex=wp.tex_siding('mw_siding', color='#bfc8d1', exposure=0.115, seed=2), rough=0.55)
    M['Trim'] = wp.mat('Trim', tex=tex_paint('mw_trim', '#f0efe8'), rough=0.42)
    M['Shutter'] = wp.mat('Shutter', tex=tex_paint('mw_shutter', '#2b3350', seed=12, amp=0.05), rough=0.42)
    M['Door'] = wp.mat('Door', tex=tex_paint('mw_door', '#a9a696', seed=13, amp=0.04), rough=0.42)
    M['Glass'] = wp.mat('Glass', '#ffffff', rough=0.04, tex=tex_glass('mw_glass'))
    M['Roof'] = wp.mat('Roof', tex=tex_roof('mw_roof'), rough=0.86)
    M['PorchFloor'] = wp.mat('PorchFloor', tex=wp.tex_wood('mw_porchfloor', color='#858c8f', board=0.0833, seed=8,
                                                              weathered=0.08), rough=0.55)
    M['Ceiling'] = wp.mat('Ceiling', tex=wp.tex_wood('mw_beadboard', color='#d2e2e0', board=0.0909, seed=9), rough=0.5)
    M['Brick'] = wp.mat('Brick', tex=wp.tex_brick('mw_brick', color='#8a503c', mortar='#b3aa9a', var=0.12, seed=1),
                        rough=0.85)
    M['Metal'] = wp.mat('Metal', '#1d1e20', rough=0.38, metal=0.75)
    M['Stone'] = wp.mat('Stone', '#8e8a83', rough=0.8)
    M['Crawl'] = wp.mat('Crawl', '#1c1a17', rough=1.0)
    M['Plants'] = vc_material('Plants', tex_leaves('mw_plants', '#4f6e33', n=512, tile=0.6, seed=52), rough=0.65)
    M['Flowers'] = vc_material('Flowers', tex_leaves('mw_flowers', '#4f6e33', n=512, tile=0.5, seed=53,
                                                     flowers='#f2eef2', fcov=0.42, fsize=40), rough=0.65)
    # lot
    M['FencePaint'] = wp.mat('FencePaint', tex=tex_paint('mw_fence', '#f1f0ea', seed=14), rough=0.45)
    M['Paver'] = wp.mat('Paver', tex=wp.tex_brick('mw_paver', color='#8c4d3a', mortar='#a39782', var=0.16, seed=21),
                        rough=0.88)
    M['Shell'] = wp.mat('Shell', tex=(wp.tex_ground('mw_shell', kind='gravel', color='#bfb5a1', n=512, tile=2.0, seed=22)[0], None, 2.0),
                        rough=0.95)
    M['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('mw_conc', kind='concrete', n=512, tile=3.0, seed=23)[0], None, 3.0),
                           rough=0.9)
    M['PineStraw'] = wp.mat('PineStraw', tex=tex_straw('mw_straw', n=512), rough=0.95)
    M['Bark'] = wp.mat('Bark', tex=tex_bark('mw_bark'), rough=0.92)
    M['OakLeaves'] = vc_material('OakLeaves', tex_canopy('mw_oakleaves', '#5a6c31'), rough=0.72)
    M['Moss'] = wp.mat('Moss', '#ffffff', tex=tex_moss('mw_moss', tile=0.6), rough=0.95, double_sided=True)
    M['Boxwood'] = vc_material('Boxwood', tex_leaves('mw_boxwood', '#40632a', n=512, tile=0.6, seed=55), rough=0.6)
    M['Azalea'] = vc_material('Azalea', tex_leaves('mw_azalea', '#3f6a2c', n=512, tile=0.7, seed=56, flowers='#e0558f',
                                                   fcov=0.33, fsize=45), rough=0.7)
    M['Ornamental'] = vc_material('Ornamental', tex_canopy('mw_ornamental', '#5a8a38', n=512, tile=0.9, seed=57, lo=0.5),
                                  rough=0.5)
    M['MailMetal'] = wp.mat('MailMetal', '#202224', rough=0.4, metal=0.6)
    M['Condenser'] = wp.mat('Condenser', '#8d8f8a', rough=0.5, metal=0.3)
    M['Cart'] = wp.mat('Cart', '#2f4a36', rough=0.6)
    MAT.update(M)
    return M


# ============================================================================ house parts
def wall_faces(g, F, L, z0, z1, holes, mat='Siding', reveal=0.16):
    """Siding face of a wall (u in [0, L]) with rectangular holes, plus painted reveals."""
    xs = sorted(set([0.0, L] + [h[0] for h in holes] + [h[1] for h in holes]))
    for a, b in zip(xs, xs[1:]):
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2
        cov = sorted([(h[2], h[3]) for h in holes if h[0] <= mid <= h[1]])
        zc = z0
        for h0, h1 in cov:
            if h0 > zc + 1e-6:
                poly(g, mat, [F.p(a, zc), F.p(b, zc), F.p(b, h0), F.p(a, h0)], facing=F.N)
            zc = max(zc, h1)
        if z1 > zc + 1e-6:
            poly(g, mat, [F.p(a, zc), F.p(b, zc), F.p(b, z1), F.p(a, z1)], facing=F.N)
    for u0, u1, h0, h1 in holes:
        dd = -reveal
        poly(g, 'Trim', [F.p(u0, h0), F.p(u0, h1), F.p(u0, h1, dd), F.p(u0, h0, dd)], facing=F.U)
        poly(g, 'Trim', [F.p(u1, h0), F.p(u1, h1), F.p(u1, h1, dd), F.p(u1, h0, dd)], facing=-F.U)
        poly(g, 'Trim', [F.p(u0, h0), F.p(u1, h0), F.p(u1, h0, dd), F.p(u0, h0, dd)], facing=F.Z)
        poly(g, 'Trim', [F.p(u0, h1), F.p(u1, h1), F.p(u1, h1, dd), F.p(u0, h1, dd)], facing=-F.Z)


def shutter(g, F, u0, u1, z0, z1):
    """Louvered navy shutter, stiles/rails + raked louvers over a dark backing."""
    d0, d1 = 0.012, 0.045
    zm = z0 + (z1 - z0) * 0.5
    fbox(g, 'Shutter', F, u0, u0 + 0.05, z0, z1, d0, d1)
    fbox(g, 'Shutter', F, u1 - 0.05, u1, z0, z1, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, z0, z0 + 0.085, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, z1 - 0.065, z1, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, zm - 0.04, zm + 0.04, d0, d1)
    poly(g, 'Shutter', [F.p(u0 + 0.05, z0, 0.016), F.p(u1 - 0.05, z0, 0.016), F.p(u1 - 0.05, z1, 0.016),
                        F.p(u0 + 0.05, z1, 0.016)], facing=F.N)
    S = F.side()
    for a, b in ((z0 + 0.085, zm - 0.04), (zm + 0.04, z1 - 0.065)):
        k = int((b - a) / 0.052)
        sp = (b - a) / max(k, 1)
        c0, c1 = -(u1 - 0.05), -(u0 + 0.05)
        for i in range(k):
            zk = a + i * sp + 0.004
            A, B, C = (0.040, zk), (0.018, zk + 0.044), (0.018, zk + 0.034)
            poly(g, 'Shutter', [S.p(A[0], A[1], c0), S.p(B[0], B[1], c0), S.p(B[0], B[1], c1), S.p(A[0], A[1], c1)],
                 facing=F.N + F.Z)
            poly(g, 'Shutter', [S.p(A[0], A[1], c0), S.p(C[0], C[1], c0), S.p(C[0], C[1], c1), S.p(A[0], A[1], c1)],
                 facing=F.N - F.Z)


def sash_window(g, F, uc, sill, w, h, cols=3, rows=2, shut=True, shut_w=None, casing=0.11):
    """Double-hung window set in a hole (uc +- w/2, sill..sill+h): casing, sill, apron, two sashes
    with muntins, glazing and optional louvered shutters."""
    u0, u1, z0, z1 = uc - w / 2, uc + w / 2, sill, sill + h
    c = casing
    fbox(g, 'Trim', F, u0 - c, u0, z0, z1, -0.005, 0.025)
    fbox(g, 'Trim', F, u1, u1 + c, z0, z1, -0.005, 0.025)
    fbox(g, 'Trim', F, u0 - c - 0.015, u1 + c + 0.015, z1, z1 + 0.15, -0.005, 0.03)
    fbox(g, 'Trim', F, u0 - c - 0.035, u1 + c + 0.035, z1 + 0.15, z1 + 0.18, -0.005, 0.06)
    fbox(g, 'Trim', F, u0 - c - 0.04, u1 + c + 0.04, z0 - 0.045, z0, -0.11, 0.06)
    fbox(g, 'Trim', F, u0 - c + 0.04, u1 + c - 0.04, z0 - 0.17, z0 - 0.045, -0.005, 0.022)
    zm = (z0 + z1) / 2
    for (zb, zt, da, db, gd, bot, top) in ((zm - 0.02, z1, -0.078, -0.042, -0.06, 0.035, 0.055),
                                           (z0, zm + 0.02, -0.118, -0.082, -0.10, 0.075, 0.035)):
        fbox(g, 'Trim', F, u0, u0 + 0.055, zb, zt, da, db)
        fbox(g, 'Trim', F, u1 - 0.055, u1, zb, zt, da, db)
        fbox(g, 'Trim', F, u0 + 0.055, u1 - 0.055, zb, zb + bot, da, db)
        fbox(g, 'Trim', F, u0 + 0.055, u1 - 0.055, zt - top, zt, da, db)
        iu0, iu1, iz0, iz1 = u0 + 0.055, u1 - 0.055, zb + bot, zt - top
        poly(g, 'Glass', [F.p(iu0, iz0, gd), F.p(iu1, iz0, gd), F.p(iu1, iz1, gd), F.p(iu0, iz1, gd)], facing=F.N)
        for i in range(1, cols):
            uu = iu0 + (iu1 - iu0) * i / cols
            fbox(g, 'Trim', F, uu - 0.011, uu + 0.011, iz0, iz1, da + 0.006, db)
        for j in range(1, rows):
            zz = iz0 + (iz1 - iz0) * j / rows
            fbox(g, 'Trim', F, iu0, iu1, zz - 0.011, zz + 0.011, da + 0.006, db)
    if shut:
        sw = shut_w or (w / 2 - 0.02)
        shutter(g, F, u0 - c - 0.006 - sw, u0 - c - 0.006, z0 + 0.006, z1)
        shutter(g, F, u1 + c + 0.006, u1 + c + 0.006 + sw, z0 + 0.006, z1)


def glazed_door(g, F, uc, z0, w, h, lites=(2, 4), glass_from=0.38, casing=0.10, threshold=True):
    """Single half/French door in a hole: casing, frame, glazed upper with muntins, raised lower panel."""
    u0, u1, z1 = uc - w / 2, uc + w / 2, z0 + h
    c = casing
    fbox(g, 'Trim', F, u0 - c, u0, z0, z1, -0.005, 0.025)
    fbox(g, 'Trim', F, u1, u1 + c, z0, z1, -0.005, 0.025)
    fbox(g, 'Trim', F, u0 - c - 0.015, u1 + c + 0.015, z1, z1 + 0.15, -0.005, 0.03)
    fbox(g, 'Trim', F, u0 - c - 0.035, u1 + c + 0.035, z1 + 0.15, z1 + 0.18, -0.005, 0.06)
    if threshold:
        fbox(g, 'Door', F, u0, u1, z0 - 0.02, z0 + 0.02, -0.16, 0.03)
    dd0, dd1 = -0.15, -0.11
    fbox(g, 'Door', F, u0 + 0.04, u1 - 0.04, z0 + 0.02, z1 - 0.04, dd0, dd1)
    fbox(g, 'Trim', F, u0, u0 + 0.04, z0, z1, -0.16, -0.08)
    fbox(g, 'Trim', F, u1 - 0.04, u1, z0, z1, -0.16, -0.08)
    fbox(g, 'Trim', F, u0, u1, z1 - 0.04, z1, -0.16, -0.08)
    gz0 = z0 + h * glass_from
    gu0, gu1, gz1 = u0 + 0.16, u1 - 0.16, z1 - 0.16
    poly(g, 'Glass', [F.p(gu0, gz0, dd1 + 0.004), F.p(gu1, gz0, dd1 + 0.004), F.p(gu1, gz1, dd1 + 0.004),
                      F.p(gu0, gz1, dd1 + 0.004)], facing=F.N)
    cols, rows = lites
    for i in range(1, cols):
        uu = gu0 + (gu1 - gu0) * i / cols
        fbox(g, 'Door', F, uu - 0.012, uu + 0.012, gz0, gz1, dd1, dd1 + 0.02)
    for j in range(1, rows):
        zz = gz0 + (gz1 - gz0) * j / rows
        fbox(g, 'Door', F, gu0, gu1, zz - 0.012, zz + 0.012, dd1, dd1 + 0.02)
    # glazing bead and raised panel
    for a, b, za, zb in ((gu0 - 0.02, gu1 + 0.02, gz0 - 0.02, gz0), (gu0 - 0.02, gu1 + 0.02, gz1, gz1 + 0.02),
                         (gu0 - 0.02, gu0, gz0, gz1), (gu1, gu1 + 0.02, gz0, gz1)):
        fbox(g, 'Door', F, a, b, za, zb, dd1, dd1 + 0.018)
    if glass_from > 0.2:
        fbox(g, 'Door', F, gu0 + 0.02, gu1 - 0.02, z0 + 0.2, gz0 - 0.18, dd1, dd1 + 0.02)
    fbox(g, 'Metal', F, u1 - 0.14, u1 - 0.1, z0 + 1.0, z0 + 1.04, dd1, dd1 + 0.07)


def entry(g, F, uc):
    """Double entry doors with arched glazing, sidelights and a transom, between pilasters."""
    u0, u1 = uc - 1.45, uc + 1.45
    z0, zt = FF1, 3.6
    # exterior pilasters, plinths and entablature
    for a, b in ((u0 - 0.17, u0), (u1, u1 + 0.17)):
        fbox(g, 'Trim', F, a, b, z0, zt, -0.005, 0.035)
        fbox(g, 'Trim', F, a - 0.015, b + 0.015, z0, z0 + 0.22, -0.005, 0.048)
        fbox(g, 'Trim', F, a - 0.01, b + 0.01, zt - 0.12, zt - 0.09, -0.005, 0.05)
    fbox(g, 'Trim', F, u0 - 0.2, u1 + 0.2, zt, zt + 0.17, -0.005, 0.04)
    fbox(g, 'Trim', F, u0 - 0.24, u1 + 0.24, zt + 0.17, zt + 0.22, -0.005, 0.075)
    fbox(g, 'Door', F, u0, u1, z0 - 0.02, z0 + 0.02, -0.16, 0.04)
    dd = -0.12
    # frame members
    xs = [u0, u0 + 0.11, u0 + 0.53, u0 + 0.63, uc, uc + 0.82, uc + 0.92, u1 - 0.11, u1]
    for a, b in ((xs[0], xs[1]), (xs[2], xs[3]), (xs[5], xs[6]), (xs[7], xs[8])):
        fbox(g, 'Trim', F, a, b, z0, zt, -0.16, -0.07)
    fbox(g, 'Trim', F, u0, u1, 3.2, 3.27, -0.16, -0.07)
    fbox(g, 'Trim', F, u0, u1, 3.53, zt, -0.16, -0.07)
    # transom
    poly(g, 'Glass', [F.p(xs[1], 3.27, -0.12), F.p(xs[7], 3.27, -0.12), F.p(xs[7], 3.53, -0.12),
                      F.p(xs[1], 3.53, -0.12)], facing=F.N)
    for i in range(1, 8):
        uu = xs[1] + (xs[7] - xs[1]) * i / 8
        fbox(g, 'Trim', F, uu - 0.012, uu + 0.012, 3.27, 3.53, -0.12, -0.095)
    # sidelights
    for a, b in ((xs[1], xs[2]), (xs[6], xs[7])):
        fbox(g, 'Door', F, a, b, z0 + 0.02, 1.78, -0.15, -0.11)
        fbox(g, 'Door', F, a + 0.06, b - 0.06, 1.0, 1.7, -0.11, -0.095)
        poly(g, 'Glass', [F.p(a, 1.78, -0.12), F.p(b, 1.78, -0.12), F.p(b, 3.2, -0.12), F.p(a, 3.2, -0.12)], facing=F.N)
        for j in range(1, 5):
            zz = 1.78 + (3.2 - 1.78) * j / 5
            fbox(g, 'Trim', F, a, b, zz - 0.012, zz + 0.012, -0.12, -0.095)
    # the two leaves: arched glass panels, raised lower panels
    for a, b in ((xs[3], xs[4]), (xs[4], xs[5])):
        fbox(g, 'Door', F, a + 0.005, b - 0.005, z0 + 0.02, 3.2, -0.15, -0.105)
        ga, gb = a + 0.13, b - 0.13
        r = (gb - ga) / 2
        gz0, gzs = 1.95, 3.03 - r
        pts = [(ga, gz0), (gb, gz0)] + [((ga + gb) / 2 + r * math.cos(math.pi * k / 8), gzs + r * math.sin(math.pi * k / 8))
                                       for k in range(0, 9)] + [(ga, gz0)]
        pts = pts[:-1]
        poly(g, 'Glass', [F.p(u, z, -0.1) for u, z in pts], facing=F.N)
        # bead around the glass
        fbox(g, 'Door', F, ga - 0.025, gb + 0.025, gz0 - 0.025, gz0, -0.105, -0.085)
        fbox(g, 'Door', F, ga - 0.025, ga, gz0, gzs, -0.105, -0.085)
        fbox(g, 'Door', F, gb, gb + 0.025, gz0, gzs, -0.105, -0.085)
        fbox(g, 'Door', F, ga + 0.02, gb - 0.02, 1.12, 1.78, -0.105, -0.088)
        fbox(g, 'Metal', F, (b - 0.09) if a < uc - 0.01 else (a + 0.05), (b - 0.05) if a < uc - 0.01 else (a + 0.09),
             FF1 + 0.93, FF1 + 0.98, -0.105, -0.04)


def lantern(g, F, uc, zc):
    fbox(g, 'Metal', F, uc - 0.06, uc + 0.06, zc - 0.2, zc + 0.12, -0.005, 0.02)
    fbox(g, 'Metal', F, uc - 0.015, uc + 0.015, zc - 0.02, zc + 0.02, 0.02, 0.1)
    b0, b1 = 0.08, 0.28
    fbox(g, 'Glass', F, uc - 0.09, uc + 0.09, zc - 0.17, zc + 0.15, b0 + 0.01, b1 - 0.01)
    for su in (-1, 1):
        for sd in (b0, b1 - 0.02):
            fbox(g, 'Metal', F, uc + su * 0.09 - 0.012, uc + su * 0.09 + 0.012, zc - 0.17, zc + 0.15, sd, sd + 0.02)
    fbox(g, 'Metal', F, uc - 0.11, uc + 0.11, zc + 0.15, zc + 0.19, b0 - 0.02, b1 + 0.02)
    fbox(g, 'Metal', F, uc - 0.07, uc + 0.07, zc + 0.19, zc + 0.24, b0 + 0.02, b1 - 0.02)
    fbox(g, 'Metal', F, uc - 0.1, uc + 0.1, zc - 0.21, zc - 0.17, b0, b1)


def water_table(g, F, L, ext0=0.0, ext1=0.0):
    fbox(g, 'Trim', F, -ext0, L + ext1, WT, 1.0, -0.005, 0.03)
    fbox(g, 'Trim', F, -ext0 - 0.01, L + ext1 + 0.01, 1.0, 1.03, -0.005, 0.045)


def corner_boards(g, Fa, La, Fb, z0, z1):
    """External corner where wall A (ending at u=La) meets wall B (starting at u=0)."""
    fbox(g, 'Trim', Fa, La - 0.14, La + 0.025, z0, z1, -0.005, 0.025)
    fbox(g, 'Trim', Fb, 0.005, 0.14, z0, z1, -0.005, 0.025)


def build_walls(gH, walls, z_top, frieze):
    """walls: list of (frame, length, openings). Openings: dict(kind, u, sill, w, h, ...)."""
    for F, L, ops, z_bot in walls:
        holes = []
        for o in ops:
            if o['kind'] == 'entry':
                holes.append((o['u'] - 1.45, o['u'] + 1.45, FF1, 3.6))
            else:
                holes.append((o['u'] - o['w'] / 2, o['u'] + o['w'] / 2, o['sill'], o['sill'] + o['h']))
        wall_faces(gH, F, L, z_bot, z_top, holes)
        for o in ops:
            if o['kind'] == 'win':
                sash_window(gH, F, o['u'], o['sill'], o['w'], o['h'], o.get('cols', 3), o.get('rows', 2),
                            o.get('shut', True), o.get('sw'), o.get('casing', 0.11))
            elif o['kind'] == 'door':
                glazed_door(gH, F, o['u'], o['sill'], o['w'], o['h'], o.get('lites', (2, 4)), o.get('gf', 0.38))
            elif o['kind'] == 'entry':
                entry(gH, F, o['u'])
        if frieze:
            fbox(gH, 'Trim', F, -0.0215, L, frieze[0], frieze[1], -0.005, 0.022)


def hip_planes(x0, x1, y0, y1, zd, pitch_x, pitch_y):
    """Hip roof over the eave rectangle: returns (faces, ridge, hips). pitch_x = slopes facing +-x."""
    tx, ty = math.tan(math.radians(pitch_x)), math.tan(math.radians(pitch_y))
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
    rise = min(hx * tx, hy * ty)
    rx, ry = rise / tx, rise / ty           # horizontal runs of the end and side slopes
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    zr = zd + rise
    if hx - rx >= hy - ry:                  # ridge along x
        a, b = (x0 + rx, cy, zr), (x1 - rx, cy, zr)
    else:
        a, b = (cx, y0 + ry, zr), (cx, y1 - ry, zr)
    c00, c10, c11, c01 = (x0, y0, zd), (x1, y0, zd), (x1, y1, zd), (x0, y1, zd)
    if a[1] == b[1]:
        faces = [[c00, c10, b, a], [c11, c01, a, b], [c01, c00, a], [c10, c11, b]]
        hips = [(c00, a), (c01, a), (c10, b), (c11, b)]
    else:
        faces = [[c10, c11, b, a], [c01, c00, a, b], [c00, c10, a], [c11, c01, b]]
        hips = [(c00, a), (c10, a), (c11, b), (c01, b)]
    return faces, (a, b), hips, zr


def clip_poly_halfspace(P, axis, val, keep_less=True):
    """Sutherland-Hodgman clip of a 3D polygon against axis <= val (or >= val)."""
    out = []
    n = len(P)
    inside = (lambda p: p[axis] <= val + 1e-9) if keep_less else (lambda p: p[axis] >= val - 1e-9)
    for i in range(n):
        a, b = Vector(P[i]), Vector(P[(i + 1) % n])
        ia, ib = inside(a), inside(b)
        if ia:
            out.append(a)
        if ia != ib:
            t = (val - a[axis]) / (b[axis] - a[axis])
            out.append(a + (b - a) * t)
    return out


def eave_trim(gR, path, zd, sof, wall_path_off, closed=False, r=0.045, hb=0.04, valance=True):
    """Fascia with scallops, flat soffit back to the wall."""
    if valance:
        scallop_fascia(gR, path, zd - 0.05, sof, hb=hb, r=r, closed=closed)
    else:
        path_run(gR, 'Trim', path, sof, zd - 0.05, 0.0, -0.025, closed=closed)
    outer = path_offset(path + ([path[1]] if closed else []), 0.025)
    inner = path_offset(path + ([path[1]] if closed else []), wall_path_off)
    if closed:
        outer, inner = outer[1:-1], inner[1:-1]
        outer.append(outer[0])
        inner.append(inner[0])
    for k in range(len(outer) - 1):
        poly(gR, 'Trim', [(outer[k][0], outer[k][1], sof), (outer[k + 1][0], outer[k + 1][1], sof),
                          (inner[k + 1][0], inner[k + 1][1], sof), (inner[k][0], inner[k][1], sof)], facing=(0, 0, -1))


# ---------------------------------------------------------------------------- balusters, posts, rails
def baluster_pts(H, wmax=0.054, wmin=0.021, blk=0.034, n=7):
    def hw(t):
        s = (t - 0.08) / 0.84
        return wmin + (wmax - wmin) * math.sin(2 * math.pi * s) ** 2 if 0 <= s <= 1 else blk
    ts = [0.08 + 0.84 * i / n for i in range(n + 1)]
    right = [(blk, 0.0), (blk, 0.08 * H)] + [(hw(t), t * H) for t in ts] + [(blk, 0.92 * H), (blk, H)]
    right = [right[0], right[1]] + [(max(p[0], 0.012), p[1]) for p in right[2:-2]] + right[-2:]
    left = [(-u, z) for u, z in reversed(right)]
    return right + left


def baluster_row(g, F, s0, s1, zb, H, pitch=0.124, rake=0.0, mat='Trim'):
    """Sawn flat balusters between s0..s1 along frame F (u), bottom at zb (+ rake*u), height H."""
    L = s1 - s0
    k = max(1, int(L / pitch))
    off = (L - (k - 1) * pitch) / 2
    base = baluster_pts(H)
    for i in range(k):
        u = s0 + off + i * pitch
        z = zb + rake * (u - s0)
        pts = [(u + a, z + b) for a, b in base]
        extrude(g, mat, F, pts, -0.012, 0.012, smooth_sides=True)


def railing(g, F, s0, s1, floor_z, top=0.85, rake=0.0):
    """Top rail with handrail cap, bottom rail and sawn balusters along frame F from s0 to s1."""
    zb = floor_z + 0.07
    zt = floor_z + top
    if rake == 0:
        fbox(g, 'Trim', F, s0, s1, zb, zb + 0.055, -0.04, 0.04)
        fbox(g, 'Trim', F, s0, s1, zt - 0.07, zt - 0.02, -0.045, 0.045)
        fbox(g, 'Trim', F, s0, s1, zt - 0.02, zt + 0.015, -0.065, 0.065)
        baluster_row(g, F, s0, s1, zb + 0.055, (zt - 0.07) - (zb + 0.055))
    else:
        L = s1 - s0
        for (za, zb_, w) in ((zb, zb + 0.055, 0.04), (zt - 0.07, zt - 0.02, 0.045), (zt - 0.02, zt + 0.015, 0.065)):
            pts = [(s0, za), (s1, za + rake * L), (s1, zb_ + rake * L), (s0, zb_)]
            extrude(g, 'Trim', F, pts, -w, w)
        k = max(1, int(L / 0.124))
        off = (L - (k - 1) * 0.124) / 2
        for i in range(k):
            u = s0 + off + i * 0.124
            z0 = zb + 0.055 + rake * (u - s0) - 0.03
            z1 = zt - 0.07 + rake * (u - s0) + 0.03
            pts = [(u + a, z0 + b) for a, b in baluster_pts(z1 - z0)]
            extrude(g, 'Trim', F, pts, -0.012, 0.012, smooth_sides=True)


def turned_post(g, x, y, z0, ztop, sq=0.15, rail_top=None):
    rt = rail_top or (z0 + 0.95)
    box(g, 'Trim', x - 0.095, x + 0.095, y - 0.095, y + 0.095, z0, z0 + 0.08)
    cbox(g, 'Trim', x, y, sq, sq, z0 + 0.08, rt)
    cbox(g, 'Trim', x, y, sq + 0.03, sq + 0.03, rt, rt + 0.04)
    zs, ze = rt + 0.04, ztop - 0.24
    L = ze - zs
    prof = [(0.07, zs), (0.075, zs + 0.02), (0.075, zs + 0.06), (0.052, zs + 0.09), (0.046, zs + 0.13),
            (0.056, zs + 0.22 * L), (0.061, zs + 0.45 * L), (0.056, zs + 0.68 * L), (0.046, ze - 0.2),
            (0.05, ze - 0.16), (0.068, ze - 0.12), (0.068, ze - 0.08), (0.05, ze - 0.05), (0.06, ze - 0.02),
            (0.07, ze)]
    lathe(g, 'Trim', prof, x, y, seg=10)
    cbox(g, 'Trim', x, y, sq + 0.03, sq + 0.03, ze, ze + 0.04)
    cbox(g, 'Trim', x, y, sq, sq, ze + 0.04, ztop)


def fan_bracket(g, p, U, R=0.42, z_beam=None):
    """Fan bracket with three radial spindles in the vertical plane through p along U (pointing into the bay)."""
    U = Vector((U[0], U[1], 0)).normalized()
    N = U.cross(Vector((0, 0, 1)))
    F = Fr((p[0], p[1], z_beam), U, N)
    outer = [(R * math.cos(math.radians(a)), -R * math.sin(math.radians(a))) for a in range(0, 91, 10)]
    inner = [((R - 0.045) * math.cos(math.radians(a)), -(R - 0.045) * math.sin(math.radians(a))) for a in range(90, -1, -10)]
    extrude(g, 'Trim', F, outer + inner, -0.02, 0.02)
    hub = [(0, 0), (0.0, -0.09)] + [(0.09 * math.sin(math.radians(a)), -0.09 * math.cos(math.radians(a))) for a in (30, 60)] + [(0.09, 0)]
    extrude(g, 'Trim', F, hub, -0.022, 0.022)
    for a in (22.5, 45, 67.5):
        ca, sa = math.cos(math.radians(a)), -math.sin(math.radians(a))
        r0, r1, w = 0.08, R - 0.04, 0.013
        nx, nz = -sa, ca
        pts = [(ca * r0 + nx * w, sa * r0 + nz * w), (ca * r1 + nx * w, sa * r1 + nz * w),
               (ca * r1 - nx * w, sa * r1 - nz * w), (ca * r0 - nx * w, sa * r0 - nz * w)]
        extrude(g, 'Trim', F, pts, -0.013, 0.013)
        # a turned bead halfway along each spindle
        rm = (r0 + r1) / 2
        pts = [(ca * (rm - 0.03) + nx * 0.022, sa * (rm - 0.03) + nz * 0.022),
               (ca * (rm + 0.03) + nx * 0.022, sa * (rm + 0.03) + nz * 0.022),
               (ca * (rm + 0.03) - nx * 0.022, sa * (rm + 0.03) - nz * 0.022),
               (ca * (rm - 0.03) - nx * 0.022, sa * (rm - 0.03) - nz * 0.022)]
        extrude(g, 'Trim', F, pts, -0.018, 0.018)


def stairs(gS, F, width, n_risers=6, rise=0.15, run=0.28, cheek=0.33, rails=True, top_z=PFL):
    """Brick steps descending along F.N from the porch edge (d=0) between brick cheek walls."""
    n_tr = n_risers - 1
    run_total = n_tr * run
    hw = width / 2
    for k in range(1, n_risers):
        zt = rise * k
        dfront = run_total - run * (k - 1)
        fbox(gS, 'Brick', F, -hw, hw, -0.6 if k == 1 else -0.3, zt, 0.0, dfront)
        fbox(gS, 'Brick', F, -hw, hw, zt - 0.025, zt + 0.004, dfront - 0.01, dfront + 0.02)   # rowlock nosing
    slope = (top_z + 0.22 - (rise + 0.22)) / run_total
    for su in (-1, 1):
        a, b = (hw, hw + cheek) if su > 0 else (-hw - cheek, -hw)
        S = F.side()
        top0, top1 = top_z + 0.22, rise + 0.22
        prof = [(0.0, -0.6), (run_total + 0.12, -0.6), (run_total + 0.12, top1), (run_total, top1), (0.0, top0)]
        extrude(gS, 'Brick', S, prof, -b, -a)
        # brick cap course, slightly proud
        cap = [(-0.01, top0 - 0.01), (run_total, top1 - 0.01), (run_total + 0.14, top1 - 0.01), (run_total + 0.14, top1 + 0.06),
               (run_total, top1 + 0.06), (-0.01, top0 + 0.06)]
        extrude(gS, 'Brick', S, cap, -(b + 0.02), -(a - 0.02))
        if rails:
            uc = (a + b) / 2
            # bottom newel
            dn = run_total + 0.02
            p = F.p(uc, 0, dn)
            zb = top1 + 0.06
            box(gS, 'Trim', p.x - 0.07, p.x + 0.07, p.y - 0.07, p.y + 0.07, zb, zb + 0.95)
            box(gS, 'Trim', p.x - 0.09, p.x + 0.09, p.y - 0.09, p.y + 0.09, zb + 0.95, zb + 1.0)
            pc = F.p(uc, 0, dn)
            lathe(gS, 'Trim', [(0.04, zb + 1.0), (0.06, zb + 1.04), (0.055, zb + 1.09), (0.02, zb + 1.13), (0.0, zb + 1.135)],
                  pc.x, pc.y, seg=8, caps=False)
            # raked rail from the porch post down to the newel
            R = Fr(F.p(uc, 0, 0), F.N, F.N.cross(Vector((0, 0, 1))))   # u = distance out from the porch edge
            s0, s1 = -PIN + 0.075, dn - 0.07
            z_at = lambda s: top0 + 0.06 - (top0 - top1) * s / run_total
            zb0 = z_at(s0)
            railing_raked(gS, R, s0, s1, zb0, -(top0 - top1) / run_total)


def railing_raked(g, F, s0, s1, zcheek0, slope, top=0.62):
    L = s1 - s0
    for (za, zb_, w) in ((0.05, 0.1, 0.04), (top - 0.07, top - 0.02, 0.045), (top - 0.02, top + 0.015, 0.065)):
        pts = [(s0, zcheek0 + za), (s1, zcheek0 + za + slope * L), (s1, zcheek0 + zb_ + slope * L), (s0, zcheek0 + zb_)]
        extrude(g, 'Trim', F, pts, -w, w)
    k = max(1, int(L / 0.124))
    off = (L - (k - 1) * 0.124) / 2
    for i in range(k):
        u = s0 + off + i * 0.124
        z0 = zcheek0 + 0.1 + slope * (u - s0) - 0.015
        z1 = zcheek0 + top - 0.07 + slope * (u - s0) + 0.015
        pts = [(u + a, z0 + b) for a, b in baluster_pts(z1 - z0)]
        extrude(g, 'Trim', F, pts, -0.012, 0.012, smooth_sides=True)


def lattice_panel(g, F, u0, u1, z0, z1, d=-0.06, pitch=0.13, w=0.036, th=0.009):
    """Diagonal painted lattice (two layers at +-45 degrees) clipped to the panel rectangle."""
    def clip(poly2):
        for axis, val, keep_less in ((0, u0, False), (0, u1, True), (1, z0, False), (1, z1, True)):
            out = []
            n = len(poly2)
            for i in range(n):
                a, b = poly2[i], poly2[(i + 1) % n]
                ia = a[axis] <= val if keep_less else a[axis] >= val
                ib = b[axis] <= val if keep_less else b[axis] >= val
                if ia:
                    out.append(a)
                if ia != ib:
                    t = (val - a[axis]) / (b[axis] - a[axis])
                    out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            poly2 = out
            if not poly2:
                return []
        return poly2
    H = z1 - z0
    for layer, sgn in ((0, 1), (1, -1)):
        dd = d - layer * th
        c = -H - pitch
        while c < (u1 - u0) + pitch:
            # strip between lines u - sgn*(z-z0) = c and c + w*sqrt2
            a0 = u0 + c
            w2 = w * math.sqrt(2)
            if sgn > 0:
                strip = [(a0, z0), (a0 + w2, z0), (a0 + w2 + H, z1), (a0 + H, z1)]
            else:
                strip = [(a0 + H, z0), (a0 + H + w2, z0), (a0 + w2, z1), (a0, z1)]
            cp = clip(strip)
            if len(cp) >= 3:
                extrude(g, 'Trim', F, cp, dd - th, dd)
            c += pitch * math.sqrt(2)
    fbox(g, 'Trim', F, u0, u1, z0, z0 + 0.05, d - 2 * th, d + 0.005)
    fbox(g, 'Trim', F, u0, u1, z1 - 0.05, z1, d - 2 * th, d + 0.005)


PIERS = set()


def pier(g, cx, cy, s=0.4, ztop=WT):
    key = (round(cx, 2), round(cy, 2))
    if key in PIERS:
        return
    PIERS.add(key)
    cbox(g, 'Brick', cx, cy, s, s, -0.6, ztop)


def foundation_run(g, F, u0, u1, spacing=2.4, s=0.4):
    L = u1 - u0
    n = max(1, int(math.ceil(L / spacing)))
    us = [u0 + s / 2 + (L - s) * i / n for i in range(n + 1)]
    for u in us:
        p = F.p(u, 0, -s / 2)
        pier(g, p.x, p.y, s)
    for a, b in zip(us, us[1:]):
        lattice_panel(g, F, a + s / 2, b - s / 2, 0.02, WT - 0.02)
        # dark crawlspace behind
        poly(g, 'Crawl', [F.p(a + s / 2, -0.05, -0.2), F.p(b - s / 2, -0.05, -0.2), F.p(b - s / 2, WT, -0.2),
                          F.p(a + s / 2, WT, -0.2)], facing=F.N)


# ============================================================================ the house
def house_top(x, y):
    """Highest point of the house at (x, y) (used to keep trees, limbs and moss clear of the roofs)."""
    z = 0.0
    if X0 - OV - 0.15 <= x <= X1 + OV + 0.15 and Y0 - OV - 0.15 <= y <= Y1 + OV + 0.15:
        xc, yc = min(max(x, X0 - OV), X1 + OV), min(max(y, Y0 - OV), Y1 + OV)
        z = max(z, min(ZD + (yc - (Y0 - OV)) * TF, ZD + ((Y1 + OV) - yc) * TF,
                       ZD + (xc - (X0 - OV)) * TE, ZD + ((X1 + OV) - xc) * TE))
        for cx, cy in CHIMNEYS:
            if abs(x - cx) < 0.9 and abs(y - cy) < 0.8:
                z = max(z, CH_TOP + 0.3)
    for dx in DORMERS:
        if abs(x - dx) < 1.45 and DY - 0.4 <= y <= DY + 3.0:
            z = max(z, 12.1)
    if XPL - 0.6 <= x <= XPR + 0.6 and YPF - 0.6 <= y <= RRET + 0.6:
        z = max(z, PZW + 0.1)
    if BAL[0] - 0.3 <= x <= BAL[1] + 0.3 and Y0 - BAL[2] - 0.6 <= y <= Y0:
        z = max(z, BAL_DECK + 1.15)
    if WX0 - 0.6 <= x <= X0 and WY0 - 0.6 <= y <= WY1 + 0.6:
        z = max(z, 6.3)
    if EX0 - 0.6 <= x <= EX1 + 0.6 and Y1 <= y <= EY1 + 0.6:
        z = max(z, 5.6)
    if 0 <= x <= 4 and -12.5 <= y <= -9.3:
        z = max(z, 2.4)
    return z


def build_house():
    gH, gR, gP, gF, gC = Geo('House'), Geo('Roof'), Geo('Porch'), Geo('Foundation'), Geo('Chimneys')
    global G_PLANTS
    G_PLANTS = Geo('Porch_Plants')

    # ------------------------------------------------------------- main block walls
    Ff = Fr((X0, Y0, 0), (1, 0, 0), (0, -1, 0))
    Fr_ = Fr((X1, Y0, 0), (0, 1, 0), (1, 0, 0))
    Fb = Fr((X1, Y1, 0), (-1, 0, 0), (0, 1, 0))
    Fl = Fr((X0, Y1, 0), (0, -1, 0), (-1, 0, 0))
    W, D = X1 - X0, Y1 - Y0
    g1 = dict(kind='win', sill=1.30, w=0.95, h=2.15, sw=0.45)
    g2 = dict(kind='win', sill=5.20, w=0.85, h=1.75, sw=0.40, casing=0.10)
    u = lambda x: x - X0
    front = [dict(g1, u=u(MX + s)) for s in (-4.97, -2.90, 2.90, 4.97)] + [dict(kind='entry', u=u(MX))]
    front += [dict(g2, u=u(MX + s)) for s in (-4.98, -3.10, 1.10, 3.10, 4.98)]
    front += [dict(kind='door', u=u(MX - 1.0), sill=4.86, w=0.86, h=2.09, lites=(2, 4), gf=0.33)]
    right = [dict(g1, u=y - Y0) for y in (-4.7, -1.0, 2.6)] + [dict(g2, u=y - Y0) for y in (-4.7, -1.0, 2.6)]
    left = [dict(g1, u=Y1 - (-4.7))] + [dict(g2, u=Y1 - y) for y in (-4.7, -1.0, 2.6)]
    back = [dict(g1, u=X1 - x) for x in (-2.4, 6.4)] + [dict(g2, u=X1 - x) for x in (-3.0, -1.0, 4.7, 6.6)]
    build_walls(gH, [(Ff, W, front, WT), (Fr_, D, right, WT), (Fb, W, back, WT), (Fl, D, left, WT)],
                MAIN_TOP, (7.38, MAIN_TOP))
    for Fa, La, Fb_ in ((Ff, W, Fr_), (Fr_, D, Fb), (Fb, W, Fl), (Fl, D, Ff)):
        corner_boards(gH, Fa, La, Fb_, 1.03, 7.38)
    fbox(gH, 'Trim', Ff, -0.03, u(MX) - 1.63, WT, 1.0, -0.005, 0.03)
    fbox(gH, 'Trim', Ff, u(MX) + 1.63, W + 0.03, WT, 1.0, -0.005, 0.03)
    water_table(gH, Fb, W, 0.03, 0.03)
    water_table(gH, Fr_, D, -0.005, -0.005)
    water_table(gH, Fl, D, -0.005, -0.005)
    lantern(gH, Ff, u(MX - 1.74), 2.45)
    lantern(gH, Ff, u(MX + 1.74), 2.45)

    # ------------------------------------------------------------- main roof (steep hip, steeper hip ends)
    ex0, ex1, ey0, ey1 = X0 - OV, X1 + OV, Y0 - OV, Y1 + OV
    faces, ridge, hips, zr = hip_planes(ex0, ex1, ey0, ey1, ZD, PE, PF)
    for f in faces:
        roof_slab(gR, f, th=0.06)
    roof_caps(gR, faces)
    eave_trim(gR, [(ex0, ey0), (ex1, ey0), (ex1, ey1), (ex0, ey1), (ex0, ey0)], ZD, SOF, OV, closed=True)

    # ------------------------------------------------------------- dormers
    for dx in DORMERS:
        dormer(gH, gR, dx)

    # ------------------------------------------------------------- chimneys
    for cx, cy in CHIMNEYS:
        cbox(gC, 'Brick', cx, cy, 0.95, 0.66, 7.0, CH_TOP - 0.3)
        cbox(gC, 'Brick', cx, cy, 1.05, 0.76, CH_TOP - 0.3, CH_TOP - 0.22)
        cbox(gC, 'Brick', cx, cy, 1.11, 0.82, CH_TOP - 0.22, CH_TOP - 0.1)
        cbox(gC, 'Brick', cx, cy, 1.0, 0.71, CH_TOP - 0.1, CH_TOP - 0.02)
        cbox(gC, 'Stone', cx, cy, 1.04, 0.75, CH_TOP - 0.02, CH_TOP + 0.05)
        for ox in (-0.22, 0.22):
            lathe(gC, 'Brick', [(0.1, CH_TOP + 0.05), (0.1, CH_TOP + 0.3), (0.115, CH_TOP + 0.32), (0.115, CH_TOP + 0.36)],
                  cx + ox, cy, seg=10)
        # metal flashing collar where the stack leaves the roof
        zr_ = min(ZD + ((Y1 + OV) - (cy + 0.33)) * TF, ZD + ((Y1 + OV) - (cy - 0.33)) * TF)
        cbox(gC, 'Metal', cx, cy, 0.99, 0.70, zr_ - 0.05, zr_ + 0.12)

    # ------------------------------------------------------------- porch
    build_porch(gP, gR, gF)
    build_balcony(gP, gR)

    # ------------------------------------------------------------- wing + ell
    build_wing(gH, gR, gF)
    build_ell(gH, gR, gF, gP)

    # ------------------------------------------------------------- exposed foundation of the main block
    foundation_run(gF, Fr_, RRET - Y0 + 0.0, D)
    foundation_run(gF, Fb, 0.0, X1 - EX1)
    foundation_run(gF, Fb, X1 - EX0, W)
    foundation_run(gF, Fl, Y1 - WY0, Y1 - LRET)
    return [gH, gR, gP, gF, gC, G_PLANTS]


def dormer(gH, gR, dx):
    hw, ovs, ovf = 1.05, 0.18, 0.15
    yd = DY
    zof = lambda y: ZD + (y - (Y0 - OV)) * TF             # main roof (front plane) height
    yof = lambda z: (Y0 - OV) + (z - ZD) / TF
    zb = zof(yd)
    zwt = 10.35
    dp = math.tan(math.radians(55))
    z_ev = zwt + 0.12 - ovs * dp
    z_rp = zwt + 0.12 + hw * dp
    F = Fr((dx - hw, yd, 0), (1, 0, 0), (0, -1, 0))
    ww, wh, sill = 0.8, 1.13, 8.95
    wall_faces(gH, F, 2 * hw, zb - 0.04, zwt, [(hw - ww / 2, hw + ww / 2, sill, sill + wh)])
    sash_window(gH, F, hw, sill, ww, wh, 3, 2, True, 0.36, casing=0.09)
    # gable (pentagon reaching under the roof slabs)
    poly(gH, 'Siding', [F.p(0, zwt), F.p(2 * hw, zwt), F.p(2 * hw, zwt + 0.07), F.p(hw, zwt + 0.07 + hw * dp),
                        F.p(0, zwt + 0.07)], facing=F.N)
    # cornice band across the gable base, corner boards, apron
    fbox(gH, 'Trim', F, -0.03, 2 * hw + 0.03, zwt - 0.06, zwt + 0.02, -0.005, 0.05)
    fbox(gH, 'Trim', F, -0.05, 2 * hw + 0.05, zwt + 0.02, zwt + 0.05, -0.005, 0.08)
    fbox(gH, 'Trim', F, 0.0, 0.11, zb, zwt - 0.06, -0.005, 0.025)
    fbox(gH, 'Trim', F, 2 * hw - 0.11, 2 * hw, zb, zwt - 0.06, -0.005, 0.025)
    fbox(gH, 'Trim', F, -0.02, 2 * hw + 0.02, zb - 0.03, zb + 0.1, -0.005, 0.03)
    # cheeks
    yc = yof(zwt + 0.07) + 0.05
    for sx, nx in ((dx - hw, -1), (dx + hw, 1)):
        poly(gH, 'Siding', [(sx, yd, zb - 0.04), (sx, yd, zwt + 0.07), (sx, yc, zwt + 0.07)], facing=(nx, 0, 0))
        S = Fr((sx, yd, 0), (0, -1, 0) if nx < 0 else (0, 1, 0), (nx, 0, 0))
        # corner board on the cheek face at the front corner
        if nx < 0:
            fbox(gH, 'Trim', S, -0.1, 0.0, zb, zwt, -0.005, 0.025)
        else:
            fbox(gH, 'Trim', S, 0.0, 0.1, zb, zwt, -0.005, 0.025)
    # roof: two slabs meeting the main roof in valleys (back edges tucked under the main roof)
    yf = yd - ovf
    dfaces = []
    for s in (-1, 1):
        xe = dx + s * (hw + ovs)
        P = [(dx, yf, z_rp), (xe, yf, z_ev), (xe, yof(z_ev) + 0.12, z_ev), (dx, yof(z_rp) + 0.12, z_rp)]
        roof_slab(gR, P, th=0.05, edge='Trim', bottom='Trim')
        dfaces.append(P)
    roof_caps(gR, dfaces, w=0.2)
    # decorative bargeboards with scalloped lower edge, pendant finial
    Fd = Fr((0, yf, 0), (1, 0, 0), (0, -1, 0))
    for s in (-1, 1):
        xe = dx + s * (hw + ovs)
        n = 9
        top = [(xe + (dx - xe) * i / n, z_ev + 0.02 + (z_rp - z_ev) * i / n) for i in range(n + 1)]
        bot = []
        for i in range(n * 4 + 1):
            t = i / (n * 4)
            x = xe + (dx - xe) * t
            z = z_ev + (z_rp - z_ev) * t - 0.15 - 0.045 * abs(math.sin(math.pi * n * t))
            bot.append((x, z))
        pts = top + list(reversed(bot))
        extrude(gR, 'Trim', Fd, pts, 0.002, 0.032)
    pc = Fd.p(dx, 0, 0.017)
    lathe(gR, 'Trim', [(0.0, z_rp - 0.42), (0.03, z_rp - 0.38), (0.045, z_rp - 0.3), (0.03, z_rp - 0.22),
                       (0.04, z_rp - 0.12), (0.04, z_rp + 0.05), (0.025, z_rp + 0.12), (0.035, z_rp + 0.18),
                       (0.0, z_rp + 0.34)], pc.x, pc.y, seg=8, caps=False)


def build_porch(gP, gR, gF):
    xl, xr, yf = XPL + PIN, XPR - PIN, YPF + PIN       # post lines
    yle, yre = LRET - PIN, RRET - PIN                  # end post lines
    front_x = [xl + (MX - 1.5 - xl) * i / 3 for i in range(4)] + [MX + 1.5 + (xr - MX - 1.5) * i / 3 for i in range(4)]
    left_y = [yf + (yle - yf) * i / 2 for i in range(3)]
    right_y = [yf + (yre - yf) * i / 4 for i in range(5)]
    posts = [(x, yf) for x in front_x] + [(xl, y) for y in left_y[1:]] + [(xr, y) for y in right_y[1:]]
    for x, y in posts:
        turned_post(gP, x, y, PFL, P_BEAM[0], rail_top=PFL + 0.95)
    # pilasters where the end beams meet the walls
    for (x, y, nx) in ((X0, yle, -1), (X1, yre, 1)):
        box(gP, 'Trim', min(x, x + nx * 0.05), max(x, x + nx * 0.05), y - 0.08, y + 0.08, PFL, P_BEAM[0])
        box(gP, 'Trim', min(x, x + nx * 0.07), max(x, x + nx * 0.07), y - 0.1, y + 0.1, P_BEAM[0] - 0.12, P_BEAM[0])
    # floor: deck boards with nosing, painted rim
    fl = [(XPL - 0.03, YPF - 0.03, XPR + 0.03, Y0), (XPL - 0.03, Y0, X0, LRET + 0.03), (X1, Y0, XPR + 0.03, RRET + 0.03)]
    for x0, y0, x1, y1 in fl:
        box(gP, 'PorchFloor', x0, x1, y0, y1, PFL - 0.045, PFL)
    edge = [(X0, LRET), (XPL, LRET), (XPL, YPF), (XPR, YPF), (XPR, RRET), (X1, RRET)]
    path_run(gP, 'Trim', edge, 0.70, PFL - 0.045, 0.0, -0.03)
    # piers under the posts, slatted skirting with dark crawlspace behind
    for x, y in posts:
        dx_ = 0.03 if abs(x - xl) < 1e-6 else (-0.03 if abs(x - xr) < 1e-6 else 0.0)
        dy_ = 0.03 if abs(y - yf) < 1e-6 else (-0.03 if (abs(y - yle) < 1e-6 or abs(y - yre) < 1e-6) else 0.0)
        pier(gF, x + dx_, y + dy_, 0.3, 0.70)
    pier(gF, X0 - 0.17, LRET - 0.15, 0.3, 0.70)
    pier(gF, X1 + 0.17, RRET - 0.15, 0.3, 0.70)
    for F, L in path_frames(edge):
        S = Fr(F.O, F.U, F.N)
        n_sl = 7
        for i in range(n_sl):
            z0 = 0.03 + i * 0.095
            fbox(gP, 'Trim', S, 0.0, L, z0, z0 + 0.07, -0.045, -0.025)
        poly(gP, 'Crawl', [S.p(0, -0.05, -0.16), S.p(L, -0.05, -0.16), S.p(L, 0.7, -0.16), S.p(0, 0.7, -0.16)], facing=S.N)
    # beams on the post lines
    beam = [(X0, yle), (xl, yle), (xl, yf), (xr, yf), (xr, yre), (X1, yre)]
    path_run(gP, 'Trim', beam, P_BEAM[0], P_BEAM[1], 0.08, -0.08)
    # brackets into every bay
    spans = []
    for a, b in zip(front_x, front_x[1:]):
        spans.append(((a, yf), (b, yf)))
    for ys, x in ((left_y, xl), (right_y, xr)):
        for a, b in zip(ys, ys[1:]):
            spans.append(((x, a), (x, b)))
    spans += [((xl, yle), (X0, yle)), ((xr, yre), (X1, yre))]
    for a, b in spans:
        d = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
        wall_end = (abs(b[0] - X0) < 1e-6 or abs(b[0] - X1) < 1e-6)
        fan_bracket(gP, (a[0] + d.x * 0.075, a[1] + d.y * 0.075), d, z_beam=P_BEAM[0])
        off = 0.05 if wall_end else 0.075
        fan_bracket(gP, (b[0] - d.x * off, b[1] - d.y * off), -d, z_beam=P_BEAM[0])
    # railings (skip the entry steps bay; the right end bay opens onto the side steps)
    steps_front = (MX - 1.5, MX + 1.5)
    newel_x = DSTEP_X - DSTEP_W / 2 - 0.165
    for a, b in spans:
        if abs(a[1] - yf) < 1e-6 and abs(b[1] - yf) < 1e-6 and abs(a[0] - steps_front[0]) < 1e-6:
            continue
        d = Vector((b[0] - a[0], b[1] - a[1], 0))
        L = d.length
        d.normalize()
        F = Fr((a[0], a[1], 0), d, d.cross(Vector((0, 0, 1))))
        wall_end = (abs(b[0] - X0) < 1e-6 or abs(b[0] - X1) < 1e-6)
        s0 = 0.075
        if abs(a[0] - xr) < 1e-6 and abs(a[1] - yre) < 1e-6 and abs(b[0] - X1) < 1e-6:
            s0 = (xr - newel_x) + 0.07
            cbox(gP, 'Trim', newel_x, yre, 0.14, 0.14, PFL, PFL + 1.0)
            cbox(gP, 'Trim', newel_x, yre, 0.18, 0.18, PFL + 1.0, PFL + 1.05)
            lathe(gP, 'Trim', [(0.04, PFL + 1.05), (0.06, PFL + 1.09), (0.055, PFL + 1.14), (0.02, PFL + 1.18),
                               (0.0, PFL + 1.185)], newel_x, yre, seg=8, caps=False)
        railing(gP, F, s0, L - (0.05 if wall_end else 0.075), PFL)
    # ceiling (beadboard) between the beams and the walls
    cx0, cx1 = xl - 0.08, xr + 0.08
    for x0, y0, x1, y1 in ((cx0, yf - 0.08, cx1, Y0), (cx0, Y0, X0, yle + 0.08), (X1, Y0, cx1, yre + 0.08)):
        poly(gP, 'Ceiling', [(x0, y0, P_CEIL), (x1, y0, P_CEIL), (x1, y1, P_CEIL), (x0, y1, P_CEIL)], facing=(0, 0, -1))
    # crown moulding where the ceiling meets the walls
    path_run(gP, 'Trim', [(X0, yle), (X0, Y0), (X1, Y0), (X1, yre)], P_CEIL - 0.07, P_CEIL, 0.05, 0.0)
    # roof: front plane, side returns with hip ends, all at the same pitch
    xle, xre, ype = xl - PEV, xr + PEV, yf - PEV
    yle_e, yre_e = yle + PEV, yre + PEV
    ze, zw = PZE, PZW
    E = 0.03
    planes = [
        [(xle, ype, ze), (xre, ype, ze), (X1, Y0, zw), (X0, Y0, zw)],
        [(xle, yle_e, ze), (xle, ype, ze), (X0, Y0, zw), (X0, yle_e - PDEP, zw)],
        [(xle, yle_e, ze), (X0, yle_e - PDEP, zw), (X0, yle_e, ze)],
        [(xre, ype, ze), (xre, yre_e, ze), (X1, yre_e - PDEP, zw), (X1, Y0, zw)],
        [(xre, yre_e, ze), (X1, yre_e, ze), (X1, yre_e - PDEP, zw)],
    ]
    for P in planes:
        roof_slab(gR, P, th=0.05)
    # tuck strip into the wall (flashing look)
    for a, b in (((X0, Y0), (X1, Y0)),):
        seg_box(gR, 'Metal', (a[0] - 0.02, a[1] + 0.01, zw - 0.02), (b[0] + 0.02, b[1] + 0.01, zw - 0.02), 0.04, 0.1)
    roof_caps(gR, planes, w=0.2, th=0.025)
    eave = [(X0, yle_e), (xle, yle_e), (xle, ype), (xre, ype), (xre, yre_e), (X1, yre_e)]
    eave_trim(gR, eave, ze, P_SOF, PEV - 0.08, r=0.05, hb=0.05)
    # entry steps and driveway steps
    stairs(gP, Fr((MX, YPF, 0), (1, 0, 0), (0, -1, 0)), 2.7, rails=True)
    stairs(gP, Fr((DSTEP_X, RRET, 0), (-1, 0, 0), (0, 1, 0)), DSTEP_W, rails=True)
    # porch furniture: rocking chairs and hanging ferns
    for (x, y, a) in ((MX - 3.6, Y0 - 1.3, 0.25), (MX - 5.1, Y0 - 1.2, -0.2), (MX + 3.9, Y0 - 1.25, -0.15),
                      (MX + 5.3, Y0 - 1.35, 0.3)):
        rocker(gP, x, y, a)
    for i in (0, 2, 4, 6):
        fern(gP, (front_x[i] + front_x[i + 1]) / 2, yf, P_BEAM[0])
    swing(gP, xr - 1.45, (right_y[1] + right_y[2]) / 2)


def rocker(g, x, y, ang):
    """White porch rocking chair (simplified joinery)."""
    ca, sa = math.cos(ang), math.sin(ang)
    U, N = Vector((ca, sa, 0)), Vector((sa, -ca, 0))
    F = Fr((x, y, 0), U, N)          # d = toward the street (front of the chair)
    z0 = PFL
    for su in (-0.27, 0.27):
        S = Fr(F.p(su, 0, 0), N, -U)
        # rocker runner (arc)
        pts = []
        for i in range(9):
            t = -0.36 + 0.72 * i / 8
            pts.append((t, z0 + 0.003 + 0.5 * t * t))
        pts2 = [(t, z + 0.035) for t, z in reversed(pts)]
        extrude(g, 'Trim', S, pts + pts2, -0.015, 0.015)
        fbox(g, 'Trim', F, su - 0.02, su + 0.02, z0 + 0.04, z0 + 0.62, 0.2, 0.24)     # front legs to arms
        fbox(g, 'Trim', F, su - 0.02, su + 0.02, z0 + 0.04, z0 + 1.05, -0.24, -0.2)   # back legs / stiles
        fbox(g, 'Trim', F, su - 0.03, su + 0.03, z0 + 0.62, z0 + 0.645, -0.25, 0.28)  # arms
    fbox(g, 'Trim', F, -0.27, 0.27, z0 + 0.4, z0 + 0.44, -0.22, 0.24)                  # seat
    for i in range(7):
        uu = -0.21 + 0.07 * i
        fbox(g, 'Trim', F, uu - 0.018, uu + 0.018, z0 + 0.44, z0 + 1.0, -0.225, -0.21)  # back spindles
    fbox(g, 'Trim', F, -0.27, 0.27, z0 + 0.98, z0 + 1.06, -0.235, -0.2)


def fern(g, x, y, z):
    """Hanging Boston fern in a basket under the porch beam."""
    lathe(g, 'Metal', [(0.0, z - 0.55), (0.17, z - 0.55), (0.2, z - 0.4), (0.2, z - 0.36)], x, y, seg=10, caps=False)
    for k in range(3):
        a = 2 * math.pi * k / 3
        seg_box(g, 'Metal', (x + 0.19 * math.cos(a), y + 0.19 * math.sin(a), z - 0.37), (x, y, z), 0.006, 0.006)
    blob(G_PLANTS, 'Plants', (x, y, z - 0.48), (0.36, 0.36, 0.26), seed=int(abs(x * 100)) + 7, rough=0.3, sub=3,
         colfn=lambda p, d: (0.85 + 0.15 * d.z, 0.9 + 0.1 * d.z, 0.8 + 0.1 * d.z))


def swing(g, x, y):
    """Porch swing hung from the ceiling on the right return."""
    F = Fr((x, y, 0), (0, 1, 0), (1, 0, 0))
    z0 = PFL + 0.45
    fbox(g, 'Trim', F, -0.85, 0.85, z0, z0 + 0.05, -0.25, 0.25)
    for i in range(14):
        uu = -0.8 + 1.6 * i / 13
        fbox(g, 'Trim', F, uu - 0.022, uu + 0.022, z0 + 0.05, z0 + 0.5, -0.27, -0.24)
    fbox(g, 'Trim', F, -0.85, 0.85, z0 + 0.48, z0 + 0.55, -0.29, -0.23)
    for su in (-0.85, 0.85):
        fbox(g, 'Trim', F, su - 0.03, su + 0.03, z0 + 0.25, z0 + 0.28, -0.27, 0.27)
        fbox(g, 'Trim', F, su - 0.02, su + 0.02, z0 + 0.05, z0 + 0.27, 0.22, 0.26)
        for dd in (-0.22, 0.22):
            p0 = F.p(su, z0 + 0.05, dd)
            seg_box(g, 'Metal', p0, (p0.x, p0.y, P_CEIL), 0.012, 0.012)


def build_balcony(gP, gR):
    x0, x1, dep = BAL
    yb = Y0 - dep
    zr = lambda y: PZE + (y - (YPF + PIN - PEV)) * TP
    S = Fr((x0, 0, 0), (0, 1, 0), (1, 0, 0))    # u = y, d = x - x0
    prof = [(Y0 + 0.02, zr(Y0) - 0.03), (yb, zr(yb) - 0.03), (yb, BAL_DECK - 0.04), (Y0 + 0.02, BAL_DECK - 0.04)]
    extrude(gP, 'Trim', S, prof, 0.0, x1 - x0)
    box(gP, 'PorchFloor', x0 - 0.03, x1 + 0.03, yb - 0.03, Y0, BAL_DECK - 0.04, BAL_DECK)
    box(gP, 'Trim', x0 - 0.035, x1 + 0.035, yb - 0.035, Y0, BAL_DECK - 0.12, BAL_DECK - 0.04)
    post_pts = [(x0 + 0.06, yb + 0.06), (x1 - 0.06, yb + 0.06), (x0 + 0.06, Y0 - 0.06), (x1 - 0.06, Y0 - 0.06),
                ((x0 + x1) / 2, yb + 0.06)]
    for x, y in post_pts:
        cbox(gP, 'Trim', x, y, 0.11, 0.11, BAL_DECK, BAL_DECK + 0.98)
        cbox(gP, 'Trim', x, y, 0.14, 0.14, BAL_DECK + 0.98, BAL_DECK + 1.02)
        lathe(gP, 'Trim', [(0.03, BAL_DECK + 1.02), (0.05, BAL_DECK + 1.06), (0.045, BAL_DECK + 1.11), (0.0, BAL_DECK + 1.13)],
              x, y, seg=8, caps=False)
    xm = (x0 + x1) / 2
    runs = [((x0 + 0.06, yb + 0.06), (xm, yb + 0.06)), ((xm, yb + 0.06), (x1 - 0.06, yb + 0.06)),
            ((x0 + 0.06, Y0 - 0.06), (x0 + 0.06, yb + 0.06)), ((x1 - 0.06, yb + 0.06), (x1 - 0.06, Y0 - 0.06))]
    for a, b in runs:
        d = Vector((b[0] - a[0], b[1] - a[1], 0))
        L = d.length
        d.normalize()
        F = Fr((a[0], a[1], 0), d, d.cross(Vector((0, 0, 1))))
        railing(gP, F, 0.055, L - 0.055, BAL_DECK, top=0.95)
    # flower boxes hung on the outside of the front rail
    for bx0, bx1 in ((x0 + 0.2, xm - 0.15), (xm + 0.15, x1 - 0.2)):
        yb0, yb1 = yb - 0.3, yb - 0.04
        zb0, zb1 = BAL_DECK + 0.02, BAL_DECK + 0.26
        box(gP, 'Trim', bx0, bx1, yb0, yb1, zb0, zb1)
        box(gP, 'Trim', bx0 - 0.02, bx1 + 0.02, yb0 - 0.02, yb1, zb1 - 0.03, zb1)
        for bx in (bx0 + 0.15, bx1 - 0.15):
            box(gP, 'Trim', bx - 0.02, bx + 0.02, yb1 - 0.01, yb1 + 0.02, zb0 - 0.08, zb1)
        n = int((bx1 - bx0) / 0.3)
        for i in range(n):
            cx = bx0 + 0.15 + (bx1 - bx0 - 0.3) * (i + 0.5) / n
            rng = np.random.default_rng(int(cx * 1000) % 9999)
            blob(G_PLANTS, 'Plants', (cx, (yb0 + yb1) / 2 - 0.02, zb1 + 0.1), (0.2, 0.17, 0.16 + 0.04 * rng.random()),
                 seed=int(cx * 977) % 10000, rough=0.35, sub=2, colfn=lambda p, d: (0.8 + 0.2 * d.z,) * 3)
            if i % 2 == 0:
                blob(G_PLANTS, 'Flowers', (cx + 0.08, yb0 + 0.05, zb1 + 0.04), (0.14, 0.1, 0.11), seed=int(cx * 531) % 10000,
                     rough=0.3, sub=2, colfn=lambda p, d: (1, 1, 1))
            # trailing foliage over the front of the box
            blob(G_PLANTS, 'Plants', (cx, yb0 - 0.03, zb1 - 0.12), (0.17, 0.06, 0.18), seed=int(cx * 313) % 10000,
                 rough=0.4, sub=2, colfn=lambda p, d: (0.75,) * 3)


def build_wing(gH, gR, gF):
    Ff = Fr((WX0, WY0, 0), (1, 0, 0), (0, -1, 0))
    Fl = Fr((WX0, WY1, 0), (0, -1, 0), (-1, 0, 0))
    Fb = Fr((X0, WY1, 0), (-1, 0, 0), (0, 1, 0))
    W, D = X0 - WX0, WY1 - WY0
    gw = dict(kind='win', sill=1.35, w=0.9, h=1.95, sw=0.43, casing=0.1)
    walls = [(Ff, W, [dict(gw, u=1.7), dict(gw, u=4.7)], WT), (Fl, D, [dict(gw, u=1.6), dict(gw, u=3.95)], WT),
             (Fb, W, [dict(gw, u=3.3)], WT)]
    build_walls(gH, walls, W_TOP, (W_TOP - 0.2, W_TOP))
    corner_boards(gH, Fl, D, Ff, 1.03, W_TOP - 0.2)
    corner_boards(gH, Fb, W, Fl, 1.03, W_TOP - 0.2)
    water_table(gH, Ff, W, 0.03, 0.0)
    water_table(gH, Fb, W, 0.0, 0.03)
    water_table(gH, Fl, D, -0.005, -0.005)
    ov = 0.4
    ex0, ex1, ey0, ey1 = WX0 - ov, X0 + ov, WY0 - ov, WY1 + ov
    faces, ridge, hips, zr = hip_planes(ex0, ex1, ey0, ey1, W_ZD, W_P, W_P)
    kept = []
    for f in faces:
        P = clip_poly_halfspace(f, 0, X0 + 0.02, keep_less=True)
        if len(P) >= 3:
            roof_slab(gR, P, th=0.05)
            kept.append(P)
    roof_caps(gR, kept, w=0.22)
    eave = [(X0, ey1), (ex0, ey1), (ex0, ey0), (X0, ey0)]
    eave_trim(gR, eave, W_ZD, W_ZD - 0.2, ov, r=0.045, hb=0.04)
    foundation_run(gF, Ff, 0.0, W)
    foundation_run(gF, Fl, 0.0, D)
    foundation_run(gF, Fb, 0.0, W)


def build_ell(gH, gR, gF, gP):
    Fl = Fr((EX0, EY1, 0), (0, -1, 0), (-1, 0, 0))
    Fb = Fr((EX1, EY1, 0), (-1, 0, 0), (0, 1, 0))
    Frt = Fr((EX1, Y1, 0), (0, 1, 0), (1, 0, 0))
    W, D = EX1 - EX0, EY1 - Y1
    ge = dict(kind='win', sill=1.5, w=0.85, h=1.55, sw=0.40, casing=0.1)
    walls = [(Fl, D, [dict(ge, u=2.4)], WT), (Fb, W, [dict(ge, u=1.35), dict(ge, u=4.1)], WT),
             (Frt, D, [dict(ge, u=1.15), dict(kind='door', u=3.4, sill=FF1, w=0.9, h=2.1, lites=(2, 3), gf=0.45)], WT)]
    build_walls(gH, walls, E_TOP, (E_TOP - 0.18, E_TOP))
    corner_boards(gH, Fb, W, Fl, 1.03, E_TOP - 0.18)
    corner_boards(gH, Frt, D, Fb, 1.03, E_TOP - 0.18)
    water_table(gH, Fl, D, -0.005, 0.0)
    water_table(gH, Fb, W, 0.03, 0.03)
    fbox(gH, 'Trim', Frt, 0.0, 3.4 - 0.56, WT, 1.0, -0.005, 0.03)
    fbox(gH, 'Trim', Frt, 3.4 + 0.56, D - 0.005, WT, 1.0, -0.005, 0.03)
    ov = 0.4
    ex0, ex1, ey1 = EX0 - ov, EX1 + ov, EY1 + ov
    ey0 = ey1 - 2 * (ex1 - ex0)
    faces, ridge, hips, zr = hip_planes(ex0, ex1, ey0, ey1, E_ZD, E_P, E_P)
    kept = []
    for f in faces:
        P = clip_poly_halfspace(f, 1, Y1 - 0.02, keep_less=False)
        if len(P) >= 3:
            roof_slab(gR, P, th=0.05)
            kept.append(P)
    roof_caps(gR, kept, w=0.22)
    eave = [(ex1, Y1), (ex1, ey1), (ex0, ey1), (ex0, Y1)]
    eave_trim(gR, eave, E_ZD, E_ZD - 0.2, ov, r=0.045, hb=0.04)
    foundation_run(gF, Fl, 0.0, D)
    foundation_run(gF, Fb, 0.0, W)
    foundation_run(gF, Frt, 0.0, 3.4 - 0.75)
    foundation_run(gF, Frt, 3.4 + 0.75, D)
    # kitchen stoop with brick steps and a bracketed hood over the door
    Fs = Fr((EX1, Y1 + 3.4, 0), (0, 1, 0), (1, 0, 0))
    fbox(gP, 'Brick', Fs, -0.75, 0.75, -0.6, FF1 - 0.06, 0.0, 0.9)
    fbox(gP, 'Brick', Fs, -0.77, 0.77, FF1 - 0.06, FF1 - 0.02, 0.0, 0.92)
    stairs(gP, Fr(Fs.p(0, 0, 0.9), Fs.U, Fs.N), 1.2, n_risers=6, rise=0.155, cheek=0.25, rails=False, top_z=FF1 - 0.02)
    zh = FF1 + 2.1 + 0.32
    roof_slab(gR, [Fs.p(-0.85, zh + 0.05, 0.0), Fs.p(0.85, zh + 0.05, 0.0), Fs.p(0.85, zh - 0.17, 0.85),
                   Fs.p(-0.85, zh - 0.17, 0.85)], th=0.06, edge='Trim')
    fbox(gR, 'Trim', Fs, -0.87, 0.87, zh - 0.32, zh - 0.2, 0.75, 0.85)
    for su in (-0.75, 0.75):
        fan_bracket(gH, (Fs.p(su, 0, 0.0).x, Fs.p(su, 0, 0.0).y), Fs.N, R=0.38, z_beam=zh - 0.2)


# ============================================================================ the lot
def foliage_clump(g, mat, c, size, seed, tone=1.0, inner=1.0, hue=0.0, nfn=None, n_sub=2):
    """A leafy clump: two or three overlapping noisy masses, darker underneath and toward the crown interior."""
    rng = np.random.default_rng(seed)
    for i in range(n_sub):
        off = np.clip(rng.normal(0, 1, 3), -1.5, 1.5) * np.array([0.42, 0.42, 0.18]) * size
        r = size * rng.uniform(0.46, 0.62)
        cc = (c[0] + off[0], c[1] + off[1], c[2] + off[2])
        t = tone * rng.uniform(0.9, 1.1)

        def colfn(q, d, t=t):
            under = 0.32 + 0.68 * min(1.0, max(0.0, (d.z + 0.55) / 1.25))
            a = t * under * (0.66 + 0.34 * inner)
            return (a * (1.0 + hue), a * 1.03, a * (0.9 - hue))
        blob(g, mat, cc, (r, r * rng.uniform(0.85, 1.15), r * rng.uniform(0.66, 0.82)), seed=seed * 17 + i, rough=0.3,
             freq=2.6, sub=2, colfn=colfn, nfn=nfn)


def oak_tree(g, base, seed, limbs, trunk_r=0.6, fork_z=3.0, lean=(0, 0), moss=1.0, leaf=1.0, bounds=None,
             max_clumps=130, max_strands=2200, n_masses=12, rim=1.0, mass_max=4.6, mass_lift=0.0):
    """Live oak: buttressed, slightly sinuous trunk; long sweeping limbs (azimuth deg, elevation deg, length m)
    forking into secondary branches and twigs; leaf clumps on the upper and outer crown; heavy curtains of
    Spanish moss below. Stays clear of the house roofs and inside the lot rectangle."""
    rng = np.random.default_rng(seed)
    bx, by = base
    LX0, LY0, LX1, LY1 = bounds or SITE['lot']

    def inside(q, m):
        return LX0 + m < q.x < LX1 - m and LY0 + m < q.y < LY1 - m
    zs = [-0.6, 0.0, 0.45, 1.2] + [1.2 + (fork_z - 1.2) * k / 4 for k in (1, 2, 3, 4)]
    tp = []
    for z in zs:
        t = max(0.0, z) / fork_z
        tp.append(Vector((bx + lean[0] * t ** 1.4 + 0.07 * math.sin(3 * t + seed),
                          by + lean[1] * t ** 1.4 + 0.07 * math.cos(2.5 * t + seed), z)))
    tr = [trunk_r * 1.55, trunk_r * 1.42, trunk_r * 1.15, trunk_r * 1.02] + [trunk_r * (1.0 - 0.1 * k / 4) for k in (1, 2, 3, 4)]
    tube(g, 'Bark', tp, tr, seg=16, cap_end=True)
    for k in range(6):
        a = 2 * math.pi * k / 6 + rng.uniform(-0.3, 0.3)
        p0 = (bx + math.cos(a) * trunk_r * 0.55, by + math.sin(a) * trunk_r * 0.55, 1.0)
        p1 = (bx + math.cos(a) * trunk_r * 1.35, by + math.sin(a) * trunk_r * 1.35, 0.1)
        p2 = (bx + math.cos(a) * trunk_r * 2.0, by + math.sin(a) * trunk_r * 2.0, -0.12)
        tube(g, 'Bark', [p0, p1, p2], [trunk_r * 0.45, trunk_r * 0.3, trunk_r * 0.1], seg=7)
    fork = tp[-1]
    sites, anchors = [], []
    up = Vector((0, 0, 1))

    def clear_z(q, r):
        return house_top(q.x, q.y) + 0.9 + r

    def grow(start, az, el, L, r0, r1, nseg, droop, wander):
        pts = [Vector(start)]
        p = Vector(start)
        step = L / nseg
        ph = rng.uniform(0, 6)
        ph2 = rng.uniform(0, 6)
        for i in range(nseg):
            t = (i + 1) / nseg
            e = math.radians(el - droop * 1.3 * t + droop * 1.15 * t ** 3 + 0.6 * wander * math.sin(4.1 * t + ph2))
            a = math.radians(az + wander * math.sin(3.3 * t + ph))
            v = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e)))
            q = p + v * step
            rr = r0 + (r1 - r0) * t
            q.z = max(q.z, clear_z(q, rr), 2.6 + rr)
            if not inside(q, 1.4):
                break
            pts.append(q)
            p = q
        rad = [r0 + (r1 - r0) * i / max(1, len(pts) - 1) for i in range(len(pts))]
        return pts, rad

    def moss_along(pts, rad, start_frac, every=0.4):
        for i in range(max(1, int(len(pts) * start_frac)), len(pts)):
            a, b_ = pts[i - 1], pts[i]
            L = (b_ - a).length
            n = max(1, int(L / every))
            for k in range(n):
                t = (k + rng.uniform(0, 1)) / n
                anchors.append((a + (b_ - a) * t, rad[i], (b_ - a).normalized()))

    for (az, el, L) in limbs:
        r0 = trunk_r * rng.uniform(0.5, 0.6)
        pts, rad = grow(fork - Vector((0, 0, 0.5)), az, el, L, r0, 0.06, 10, rng.uniform(16, 30), rng.uniform(8, 16))
        if len(pts) < 3:
            continue
        tube(g, 'Bark', pts, rad, seg=10)
        moss_along(pts, rad, 0.2)
        sites.append((pts[-1] + up * 0.45, 1.35))
        for bnum in range(int(rng.integers(6, 10))):
            i = min(len(pts) - 2, max(1, int(rng.uniform(0.2, 0.95) * (len(pts) - 1))))
            baz = az + rng.choice([-1, 1]) * rng.uniform(25, 80)
            bp, br = grow(pts[i], baz, rng.uniform(5, 45), rng.uniform(2.5, 5.5), max(0.05, rad[i] * 0.55), 0.03, 5,
                          rng.uniform(8, 22), 16)
            if len(bp) < 2:
                continue
            tube(g, 'Bark', bp, br, seg=6)
            moss_along(bp, br, 0.0)
            sites.append((bp[-1] + up * 0.4, 1.15))
            if len(bp) > 3:
                sites.append((bp[len(bp) // 2] + up * 0.4, 1.05))
            for tw in range(int(rng.integers(2, 4))):
                j = min(len(bp) - 1, max(1, int(rng.uniform(0.3, 1.0) * (len(bp) - 1))))
                tp_, trr = grow(bp[j], baz + rng.uniform(-75, 75), rng.uniform(10, 60), rng.uniform(1.4, 3.0),
                                max(0.025, br[j] * 0.6), 0.012, 3, 8, 14)
                if len(tp_) < 2:
                    continue
                tube(g, 'Bark', tp_, trr, seg=4, cap_end=False)
                moss_along(tp_, trr, 0.0, every=0.5)
                sites.append((tp_[-1] + up * 0.3, 1.0))
    # canopy: foliage sites (upper and outer crown) grouped into a dozen big lumpy masses, plus small clumps
    # around the rim so the outline stays broken; normals from the crown ellipsoid
    if sites:
        zs_ = np.array([p.z for p, _ in sites])
        zcut = np.percentile(zs_, 25)
        sites = [(p, s_) for p, s_ in sites if p.z >= zcut or (p - fork).length > 7.5]
    sites = [(p, s_) for p, s_ in sites if inside(p, 1.6)]
    cen = Vector((fork.x, fork.y, 0))
    hue = rng.uniform(-0.035, 0.035)
    if len(sites) >= 4:
        P = np.array([tuple(p) for p, _ in sites])
        K = int(min(n_masses, len(P) // 2))
        C = P[rng.choice(len(P), K, replace=False)]
        for _ in range(12):
            lab = np.argmin(((P[:, None, :] - C[None, :, :]) * np.array([1, 1, 1.6])) ** 2 @ np.ones(3), axis=1)
            for j in range(K):
                if np.any(lab == j):
                    C[j] = P[lab == j].mean(0)
        ccen = P.mean(0)
        ccen[2] = P[:, 2].min() + 0.25 * (P[:, 2].max() - P[:, 2].min())
        crad = (max(3.0, np.abs(P[:, 0] - ccen[0]).max() + 2.0), max(3.0, np.abs(P[:, 1] - ccen[1]).max() + 2.0),
                max(2.5, (P[:, 2].max() - ccen[2]) + 2.0))
        nfn = crown_normals(tuple(ccen), crad, own=0.3)
        for j in range(K):
            Q = P[lab == j]
            if len(Q) == 0:
                continue
            m = Q.mean(0)
            sd = Q.std(0) if len(Q) > 1 else np.zeros(3)
            rx, ry = min(mass_max, 1.1 * sd[0] + 1.3), min(mass_max, 1.1 * sd[1] + 1.3)
            rz = min(2.3, 0.6 * sd[2] + 0.9, 0.6 * max(rx, ry))
            c = Vector((m[0], m[1], m[2] + 0.55 * rz + mass_lift))
            # stay inside the lot
            rx = min(rx, (c.x - LX0) / 1.35 - 0.2, (LX1 - c.x) / 1.35 - 0.2)
            ry = min(ry, (c.y - LY0) / 1.35 - 0.2, (LY1 - c.y) / 1.35 - 0.2)
            if rx < 0.8 or ry < 0.8:
                continue
            need = max(house_top(c.x + ox * rx, c.y + oy * ry) for ox in (-1, 0, 1) for oy in (-1, 0, 1)) + 0.4
            if c.z - rz * 0.75 < need:
                lift = need - (c.z - rz * 0.75)
                if lift > 2.5:
                    rz *= 0.6
                    lift = need - (c.z - rz * 0.75)
                c.z += lift
            inner = min(1.0, (Vector((c.x, c.y, 0)) - cen).length / 8.0)
            t = rng.uniform(0.86, 1.06)

            def colfn(q, d, t=t, inner=inner):
                under = 0.3 + 0.7 * min(1.0, max(0.0, (d.z + 0.45) / 1.2))
                a = t * under * (0.68 + 0.32 * inner)
                return (a * (1.0 + hue), a * 1.03, a * (0.9 - hue))
            blob(g, 'OakLeaves', tuple(c), (rx, ry, rz), seed=seed * 300 + j, rough=0.3, freq=1.5,
                 sub=4 if max(rx, ry) > 2.4 else 3, colfn=colfn, nfn=nfn, flat_bottom=c.z - rz * 0.72)
            for mm in range(int(4 + 2 * rx)):
                a = rng.uniform(0, 2 * math.pi)
                anchors.append((Vector((c.x + math.cos(a) * rx * rng.uniform(0.2, 0.8),
                                        c.y + math.sin(a) * ry * rng.uniform(0.2, 0.8), c.z - rz * 0.5)),
                                0.0, Vector((math.cos(a), math.sin(a), 0))))
            # small clumps on the rim of the mass break up its outline
            for mm in range(int(rim * (2 + rx))):
                a = rng.uniform(0, 2 * math.pi)
                hz = rng.uniform(-0.2, 0.75)
                rr = math.sqrt(max(0.05, 1 - hz * hz))
                q = Vector((c.x + math.cos(a) * rx * rr * 0.98, c.y + math.sin(a) * ry * rr * 0.98, c.z + hz * rz * 0.9))
                if not inside(q, 1.2) or q.z - 0.6 < house_top(q.x, q.y) + 0.3:
                    continue
                foliage_clump(g, 'OakLeaves', q, rng.uniform(0.7, 1.0), seed * 5000 + j * 50 + mm,
                              tone=t * rng.uniform(0.95, 1.1), inner=inner, hue=hue, nfn=nfn, n_sub=1)
    # Spanish moss: curtains (streaked sheets with ragged bottoms) and loose strands
    rng.shuffle(anchors)
    MV, MF = [], []
    nst = 0
    for (p, r, dirb) in anchors:
        if nst >= max_strands * moss:
            break
        if rng.random() > 0.55:
            continue
        top0 = Vector((p.x, p.y, p.z - r * 0.7))
        floor_z = max(house_top(top0.x, top0.y) + 0.4, 2.0)
        L = float(np.clip(rng.lognormal(math.log(1.0), 0.55), 0.35, 3.0))
        L = min(L, top0.z - floor_z)
        if L < 0.3:
            continue
        hd = Vector((dirb.x, dirb.y, 0))
        hd = hd.normalized() if hd.length > 1e-3 else Vector((1, 0, 0))
        hd = (hd + Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), 0))).normalized()
        if rng.random() < 0.65:
            # curtain
            w = rng.uniform(0.18, 0.5)
            n = max(3, int(w / 0.06))
            b_ = len(MV)
            for i in range(n + 1):
                MV.append(top0 + hd * (w * (i / n - 0.5)) + Vector((0, 0, rng.uniform(-0.03, 0.03))))
            for i in range(n + 1):
                jit = Vector((rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), 0))
                MV.append(top0 + hd * (w * (i / n - 0.5) * 0.9) + jit + Vector((0, 0, -L * rng.uniform(0.3, 0.45))))
            for i in range(n):
                tl = L * rng.uniform(0.45, 1.0)
                MV.append(top0 + hd * (w * ((i + 0.5) / n - 0.5) * 0.85) +
                          Vector((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), -tl)))
            for i in range(n):
                MF.append([b_ + i, b_ + i + 1, b_ + n + 2 + i, b_ + n + 1 + i])
                MF.append([b_ + n + 1 + i, b_ + n + 2 + i, b_ + 2 * n + 2 + i])
            nst += n
        else:
            for s_ in range(int(rng.integers(2, 5))):
                top = top0 + hd * rng.uniform(-0.2, 0.2)
                Ls = L * rng.uniform(0.4, 1.1)
                a = rng.uniform(0, math.pi)
                w0 = rng.uniform(0.04, 0.08)
                b_ = len(MV)
                for k in range(4):
                    t = k / 3
                    dv = Vector((math.cos(a + t), math.sin(a + t), 0))
                    c = top + Vector((rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), -Ls * t))
                    MV.append(c - dv * w0 * (1 - 0.85 * t) / 2)
                    MV.append(c + dv * w0 * (1 - 0.85 * t) / 2)
                for k in range(3):
                    i0 = b_ + 2 * k
                    MF.append([i0, i0 + 1, i0 + 3, i0 + 2])
                nst += 1
    if MV:
        g.add(MV, MF, 'Moss', smooth=True)


def ornamental_tree(g, base, seed=7):
    """Rounded, dense small specimen tree (tea olive / holly type) on a clear trunk."""
    rng = np.random.default_rng(seed)
    bx, by = base
    tube(g, 'Bark', [(bx, by, -0.6), (bx, by, 0.0), (bx + 0.04, by, 0.9), (bx + 0.06, by + 0.03, 1.7)],
         [0.15, 0.14, 0.12, 0.1], seg=10, cap_end=True)
    for k in range(4):
        a = 2 * math.pi * k / 4 + 0.4
        tube(g, 'Bark', [(bx + 0.06, by + 0.03, 1.6), (bx + math.cos(a) * 0.45, by + math.sin(a) * 0.45, 2.5),
                         (bx + math.cos(a) * 0.8, by + math.sin(a) * 0.8, 3.4)], [0.07, 0.05, 0.025], seg=6)
    cz, R, H = 3.85, 1.85, 2.05
    nfn = crown_normals((bx, by, cz - 0.3), (R, R, H), 0.3)
    n = 34
    for k in range(n):
        zf = 1 - 2 * (k + 0.5) / n
        rr = math.sqrt(max(0.0, 1 - zf * zf))
        a = k * 2.39996 + rng.uniform(-0.25, 0.25)
        f = rng.uniform(0.8, 0.98)
        c = (bx + math.cos(a) * rr * R * f, by + math.sin(a) * rr * R * f, cz + zf * H * f * 0.92)
        if c[2] < 2.1:
            continue
        r = rng.uniform(0.5, 0.72)
        t = rng.uniform(0.9, 1.08)
        blob(g, 'Ornamental', c, (r, r * rng.uniform(0.85, 1.15), r * 0.85), seed=seed * 100 + k, rough=0.26, freq=2.2,
             sub=3, nfn=nfn, colfn=lambda q, d, t=t, zf=zf: (t * (0.62 + 0.38 * (zf + 1) / 2),) * 3)
    for k in range(3):
        blob(g, 'Ornamental', (bx + rng.uniform(-.3, .3), by + rng.uniform(-.3, .3), cz + rng.uniform(-.3, .4)),
             (R * 0.78, R * 0.78, H * 0.72), seed=seed * 7 + k, rough=0.2, sub=2, nfn=nfn,
             colfn=lambda q, d: (0.35, 0.37, 0.33))


def shrub(g, mat, c, size, seed, tone=1.0):
    """Clustered shrub: size = (rx, ry, height)."""
    rng = np.random.default_rng(seed)
    rx, ry, H = size
    n = 4 if max(rx, ry) < 0.7 else 6
    for i in range(n + 1):
        if i < n:
            ang = 2 * math.pi * i / n + rng.uniform(-0.4, 0.4)
            f = rng.uniform(0.3, 0.5)
            cx, cy = c[0] + math.cos(ang) * rx * f, c[1] + math.sin(ang) * ry * f
            s = rng.uniform(0.55, 0.72)
            rz = H * rng.uniform(0.36, 0.46)
            cz = H * rng.uniform(0.38, 0.5)
        else:
            cx, cy, s, rz, cz = c[0], c[1], 0.6, H * 0.4, H * 0.6
        t = tone * rng.uniform(0.9, 1.08)

        def colfn(q, d, t=t):
            under = 0.36 + 0.64 * min(1.0, max(0.0, q.z / max(H, 0.1)))
            return (t * under,) * 3
        blob(g, mat, (cx, cy, cz), (rx * s, ry * s, rz), seed=seed * 7 + i, rough=0.32, freq=2.3, sub=2, colfn=colfn,
             flat_bottom=-0.04, nfn=crown_normals((c[0], c[1], H * 0.25), (rx, ry, H * 0.8), 0.3))
    nfn = crown_normals((c[0], c[1], H * 0.25), (rx, ry, H * 0.8), 0.3)
    for i in range(int(6 + 6 * max(rx, ry))):
        a = rng.uniform(0, 2 * math.pi)
        hz = rng.uniform(0.25, 1.0)
        rr = math.sqrt(max(0.05, 1 - hz * hz))
        p = (c[0] + math.cos(a) * rx * rr * 0.85, c[1] + math.sin(a) * ry * rr * 0.85, H * (0.35 + 0.6 * hz))
        r = min(rx, ry) * rng.uniform(0.2, 0.32)
        t = tone * rng.uniform(0.95, 1.15)
        blob(g, mat, p, (r, r, r * 0.85), seed=seed * 11 + i, rough=0.3, freq=2.5, sub=1,
             colfn=lambda q, d, t=t, hz=hz: ((0.55 + 0.4 * hz) * t,) * 3, nfn=nfn)


def picket_fence(g, x0, x1, y, post_every=2.4, h=1.07):
    """White picket fence along y from x0 to x1 (pickets on the street face)."""
    L = x1 - x0
    n = max(1, int(math.ceil(L / post_every)))
    xs = [x0 + L * i / n for i in range(n + 1)]
    for x in xs:
        cbox(g, 'FencePaint', x, y + 0.06, 0.09, 0.09, -0.6, h + 0.1)
        cbox(g, 'FencePaint', x, y + 0.06, 0.12, 0.12, h + 0.1, h + 0.13)
        lathe(g, 'FencePaint', [(0.04, h + 0.13), (0.05, h + 0.16), (0.03, h + 0.2), (0.0, h + 0.21)], x, y + 0.06,
              seg=8, caps=False)
    for a, b in zip(xs, xs[1:]):
        for zr in (0.22, h - 0.25):
            box(g, 'FencePaint', a + 0.045, b - 0.045, y + 0.02, y + 0.06, zr, zr + 0.085)
    F = Fr((0, y, 0), (1, 0, 0), (0, -1, 0))
    pitch = 0.135
    k = int(L / pitch)
    for i in range(k):
        x = x0 + (L - (k - 1) * pitch) / 2 + i * pitch
        if any(abs(x - p) < 0.075 for p in xs):
            continue
        pts = [(x - 0.036, 0.05), (x + 0.036, 0.05), (x + 0.036, h - 0.06), (x, h), (x - 0.036, h - 0.06)]
        extrude(g, 'FencePaint', F, pts, -0.02, 0.0)


def gate(g, xc, y, w=1.3, h=1.0):
    for x in (xc - w / 2 - 0.09, xc + w / 2 + 0.09):
        cbox(g, 'FencePaint', x, y + 0.04, 0.16, 0.16, -0.6, 1.35)
        cbox(g, 'FencePaint', x, y + 0.04, 0.2, 0.2, 1.35, 1.39)
        cbox(g, 'FencePaint', x, y + 0.04, 0.15, 0.15, 1.39, 1.45)
        lathe(g, 'FencePaint', [(0.055, 1.45), (0.07, 1.5), (0.05, 1.57), (0.0, 1.59)], x, y + 0.04, seg=10, caps=False)
    F = Fr((0, y, 0), (1, 0, 0), (0, -1, 0))
    a, b = xc - w / 2 + 0.01, xc + w / 2 - 0.01
    for zr in (0.18, h - 0.22):
        fbox(g, 'FencePaint', F, a, b, zr, zr + 0.09, -0.06, -0.02)
    for u0, z0_, u1, z1_ in ((a + 0.04, 0.27, b - 0.04, h - 0.22), (b - 0.04, 0.27, a + 0.04, h - 0.22)):
        dx, dz = u1 - u0, z1_ - z0_
        Ln = math.hypot(dx, dz)
        nx, nz = -dz / Ln * 0.04, dx / Ln * 0.04
        extrude(g, 'FencePaint', F, [(u0 + nx, z0_ + nz), (u1 + nx, z1_ + nz), (u1 - nx, z1_ - nz), (u0 - nx, z0_ - nz)],
                -0.055, -0.03)
    k = int((b - a) / 0.135)
    for i in range(k):
        x = a + 0.07 + i * (b - a - 0.14) / max(1, k - 1)
        top = h - 0.03 + 0.08 * math.sin(math.pi * (x - a) / (b - a))
        pts = [(x - 0.036, 0.1), (x + 0.036, 0.1), (x + 0.036, top - 0.06), (x, top), (x - 0.036, top - 0.06)]
        extrude(g, 'FencePaint', F, pts, -0.02, 0.0)
    fbox(g, 'MailMetal', F, b - 0.08, b - 0.02, 0.7, 0.76, -0.1, 0.02)


def slab(g, mat, pts, z_top, z_bot=-0.1):
    extrude(g, mat, WORLD, pts, z_bot, z_top)


def ngon(cx, cy, r, n=18, jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return [(cx + r * (1 + rng.uniform(-jitter, jitter)) * math.cos(2 * math.pi * i / n),
             cy + r * (1 + rng.uniform(-jitter, jitter)) * math.sin(2 * math.pi * i / n)) for i in range(n)]


OAKS = [  # (name, base, seed, limbs [(az, el, len)], trunk r, fork z, lean)
    # front left, just inside the fence: in the photo only its trunk shows, at the left edge
    ('Tree_LiveOak_1', (-4.3, -24.5), 11, [(150, 38, 10), (112, 46, 11), (196, 32, 8), (72, 44, 9), (130, 68, 7)],
     0.6, 6.6, (0.5, 0.7)),
    # front yard left of the walk: tall trunk, a long limb sweeping right across the front of the house
    ('Tree_LiveOak_2', (-4.7, -14.6), 23, [(6, 20, 13.5), (38, 38, 10), (150, 38, 10), (112, 44, 9), (200, 30, 9),
                                           (282, 24, 7), (80, 66, 6)], 0.52, 7.2, (0.3, 0.15)),
]
ORN = (6.3, -14.1)


def build_lot():
    gFn, gW, gDr, gB, gS = Geo('Lot_Fence'), Geo('Lot_Walk'), Geo('Lot_Drive'), Geo('Lot_Beds'), Geo('Lot_Shrubs')
    LX0, LY0, LX1, LY1 = SITE['lot']
    yfence = -26.4
    walk_x0, walk_x1 = MX - 0.72, MX + 0.72
    drv_x0, drv_x1 = 12.35, 15.55
    # fence + gate + driveway posts
    picket_fence(gFn, LX0 + 0.3, walk_x0 - 0.2, yfence)
    gate(gFn, MX, yfence, w=1.3)
    picket_fence(gFn, walk_x1 + 0.2, drv_x0 - 0.35, yfence)
    picket_fence(gFn, drv_x1 + 0.35, LX1 - 0.3, yfence)
    for x in (drv_x0 - 0.25, drv_x1 + 0.25):
        cbox(gFn, 'FencePaint', x, yfence + 0.04, 0.16, 0.16, -0.6, 1.35)
        cbox(gFn, 'FencePaint', x, yfence + 0.04, 0.2, 0.2, 1.35, 1.39)
        lathe(gFn, 'FencePaint', [(0.055, 1.39), (0.07, 1.44), (0.05, 1.51), (0.0, 1.53)], x, yfence + 0.04, seg=10, caps=False)
    # mailbox at the curb beside the drive
    mx, my = drv_x1 + 0.9, LY0 + 0.75
    cbox(gFn, 'FencePaint', mx, my, 0.1, 0.1, -0.6, 1.05)
    cbox(gFn, 'FencePaint', mx, my - 0.05, 0.14, 0.5, 1.0, 1.06)
    seg_box(gFn, 'FencePaint', (mx, my, 0.75), (mx, my - 0.22, 1.0), 0.05, 0.05)
    box(gFn, 'MailMetal', mx - 0.09, mx + 0.09, my - 0.3, my + 0.22, 1.06, 1.2)
    box(gFn, 'MailMetal', mx - 0.07, mx + 0.07, my - 0.3, my + 0.22, 1.2, 1.26)
    box(gFn, 'MailMetal', mx - 0.095, mx + 0.095, my - 0.31, my - 0.3, 1.06, 1.25)
    # brick walk (curb -> gate -> steps), soldier edging, landing at the steps
    slab(gW, 'Paver', [(walk_x0, LY0), (walk_x1, LY0), (walk_x1, -11.6), (walk_x0, -11.6)], 0.035)
    slab(gW, 'Paver', [(MX - 1.75, -11.6), (MX + 1.75, -11.6), (MX + 1.75, -10.92), (MX - 1.75, -10.92)], 0.035)
    for x0_, x1_ in ((walk_x0 - 0.11, walk_x0), (walk_x1, walk_x1 + 0.11)):
        slab(gW, 'Brick', [(x0_, LY0), (x1_, LY0), (x1_, -11.6), (x0_, -11.6)], 0.045)
    slab(gW, 'Brick', [(MX - 1.86, -11.71), (MX + 1.86, -11.71), (MX + 1.86, -11.6), (MX - 1.86, -11.6)], 0.045)
    ys0 = RRET + 5 * 0.28 + 0.14
    slab(gW, 'Paver', [(DSTEP_X - 1.05, ys0), (drv_x0 - 0.1, ys0), (drv_x0 - 0.1, ys0 + 1.2), (DSTEP_X - 1.05, ys0 + 1.2)], 0.035)
    # driveway: concrete apron at the street, crushed shell beyond, parking pad by the side porch
    slab(gDr, 'Concrete', [(drv_x0 - 0.5, LY0), (drv_x1 + 0.5, LY0), (drv_x1, LY0 + 2.2), (drv_x0, LY0 + 2.2)], 0.045)
    slab(gDr, 'Shell', [(drv_x0, LY0 + 2.2), (drv_x1, LY0 + 2.2), (drv_x1, -4.0), (drv_x1 + 3.4, -1.0),
                        (drv_x1 + 3.4, 7.5), (drv_x0, 7.5)], 0.03)
    slab(gDr, 'Brick', [(drv_x0 - 0.1, LY0 + 2.2), (drv_x0, LY0 + 2.2), (drv_x0, 7.5), (drv_x0 - 0.1, 7.5)], 0.04)
    # pine-straw beds along the porch, around the trees
    beds = [[(XPL - 0.9, YPF - 1.5), (MX - 1.75, YPF - 1.5), (MX - 1.75, YPF), (XPL - 0.9, YPF)],
            [(MX + 1.75, YPF - 1.5), (XPR + 0.9, YPF - 1.5), (XPR + 0.9, YPF), (MX + 1.75, YPF)],
            [(XPL - 1.1, YPF), (XPL, YPF), (XPL, LRET + 0.6), (XPL - 1.1, LRET + 0.6)],
            [(XPR, YPF), (XPR + 1.0, YPF), (XPR + 1.0, RRET), (XPR, RRET)],
            [(WX0 - 1.0, WY0 - 1.0), (X0 - 3.2, WY0 - 1.0), (X0 - 3.2, WY0), (WX0, WY0), (WX0, WY1),
             (WX0 - 1.0, WY1)]]
    for b in beds:
        slab(gB, 'PineStraw', b, 0.04, -0.08)
    for (name, base, *_), rr in zip(OAKS, (1.3, 1.9)):
        slab(gB, 'PineStraw', ngon(base[0], base[1], rr, 20, 0.08, 3), 0.045, -0.08)
    slab(gB, 'PineStraw', ngon(ORN[0], ORN[1], 1.15, 18, 0.06, 4), 0.045, -0.08)
    # boxwood hedge along the porch front and right return, azaleas at corners and the steps
    rng = np.random.default_rng(5)
    def hedge(x0_, x1_, y_, ax='x'):
        L = abs(x1_ - x0_)
        n = max(1, int(L / 1.05))
        for i in range(n):
            t = (i + 0.5) / n
            p = x0_ + (x1_ - x0_) * t
            c = (p, y_) if ax == 'x' else (y_, p)
            r = (0.68, 0.42, 0.42) if ax == 'x' else (0.42, 0.68, 0.42)
            shrub(gS, 'Boxwood', c, (r[0] * rng.uniform(0.95, 1.1), r[1] * rng.uniform(0.95, 1.1), 0.8 * rng.uniform(0.94, 1.08)),
                  seed=int(rng.integers(1e6)), tone=rng.uniform(0.85, 1.05))
    hedge(XPL - 0.3, MX - 2.4, YPF - 0.62)
    hedge(MX + 2.4, XPR + 0.2, YPF - 0.62)
    hedge(YPF + 0.4, RRET - 0.1, XPR + 0.55, ax='y')
    hedge(YPF + 0.4, LRET + 0.3, XPL - 0.55, ax='y')
    for (x, y, r, h, mat) in ((MX - 2.38, YPF - 0.75, 0.55, 1.15, 'Boxwood'), (MX + 2.38, YPF - 0.75, 0.55, 1.15, 'Boxwood'),
                              (XPL - 0.95, YPF - 0.95, 0.8, 1.3, 'Azalea'), (XPR + 0.95, YPF - 0.95, 0.8, 1.3, 'Azalea'),
                              (MX - 4.6, YPF - 1.0, 0.7, 1.0, 'Azalea'), (MX + 5.2, YPF - 1.0, 0.7, 1.0, 'Azalea'),
                              (XPL - 1.3, -12.0, 1.1, 1.7, 'Boxwood'), (XPL - 2.6, -11.0, 0.95, 1.4, 'Azalea'),
                              (XPL - 0.2, -12.7, 0.8, 1.15, 'Azalea'),
                              (WX0 - 0.85, WY0 + 1.0, 0.7, 1.2, 'Azalea'), (WX0 - 0.9, WY0 + 3.5, 0.75, 1.3, 'Boxwood'),
                              (X0 - 3.6, WY0 - 0.85, 0.7, 1.1, 'Azalea')):
        shrub(gS, mat, (x, y), (r, r * 0.95, h), seed=int(rng.integers(1e6)), tone=rng.uniform(0.85, 1.05))
    # props: two HVAC condensers on a pad behind the house, roll carts by the drive
    gPr = Geo('Lot_Props')
    box(gPr, 'Concrete', 5.75, 7.55, 4.85, 5.75, -0.05, 0.08)
    for cx in (6.2, 7.1):
        box(gPr, 'MailMetal', cx - 0.36, cx + 0.36, 4.95, 5.65, 0.08, 0.18)
        box(gPr, 'Condenser', cx - 0.35, cx + 0.35, 4.96, 5.64, 0.18, 0.85)
        box(gPr, 'MailMetal', cx - 0.36, cx + 0.36, 4.95, 5.65, 0.85, 0.9)
        lathe(gPr, 'MailMetal', [(0.0, 0.9), (0.27, 0.9), (0.27, 0.93), (0.0, 0.93)], cx, 5.3, seg=16, caps=False)
    for k, cx in enumerate((12.05, 12.05)):
        cy = 5.6 + k * 0.75
        box(gPr, 'Cart', cx - 0.3, cx + 0.3, cy - 0.34, cy + 0.34, 0.06, 1.0)
        box(gPr, 'Cart', cx - 0.33, cx + 0.33, cy - 0.38, cy + 0.36, 1.0, 1.06)
        for sy in (-0.24, 0.24):
            box(gPr, 'MailMetal', cx + 0.24, cx + 0.34, cy + sy - 0.09, cy + sy + 0.09, 0.0, 0.18)
    # trees
    trees = []
    for name, base, seed, limbs, tr, fz, lean in OAKS:
        g = Geo(name)
        oak_tree(g, base, seed, limbs, tr, fz, lean, n_masses=9 if name.endswith('_1') else 10,
                 mass_max=4.0 if name.endswith('_1') else 3.4, mass_lift=0.4 if name.endswith('_1') else 1.0,
                 max_strands=1400 if name.endswith('_1') else 2600)
        trees.append(g)
    gO = Geo('Tree_Ornamental')
    ornamental_tree(gO, ORN)
    return [gFn, gW, gDr, gB, gS, gPr] + trees + [gO]


# ============================================================================ render-only surroundings
def render_extras():
    objs = []
    gx = Geo('Render_Street')
    cy = SITE['curb_y']
    slab(gx, 'Concrete', [(-90, cy - 0.15), (90, cy - 0.15), (90, cy + 0.0), (-90, cy + 0.0)], 0.12)
    slab(gx, 'Concrete', [(-90, cy - 0.6), (90, cy - 0.6), (90, cy - 0.15), (-90, cy - 0.15)], 0.0)
    MAT['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('mw_asphalt', kind='asphalt', tile=4.0), rough=0.9)
    slab(gx, 'Asphalt', [(-90, cy - 8.1), (90, cy - 8.1), (90, cy - 0.6), (-90, cy - 0.6)], 0.0)
    objs.append(gx.build())
    bg = [((-31, 8), 101), ((-34, 36), 102), ((-8, 37), 103), ((22, 34), 104), ((37, 16), 105), ((-44, -14), 106),
          ((10, 50), 107), ((-20, 52), 108), ((34, 44), 109), ((28, 2), 110), ((48, -8), 111), ((16, 30), 112),
          ((3, 29), 113), ((-13, 27), 114), ((25, 17), 115, True), ((-21, 19), 116, True)]
    for e in bg:
        b, s, tall = e[0], e[1], len(e) > 2
        g = Geo(f'Render_BG_{s}')
        limbs = [(a + s * 7, 60 if tall else 36, 11 if tall else 10) for a in (0, 72, 144, 216, 288)]
        oak_tree(g, b, s, limbs, 0.65 if tall else 0.6, 6.0 if tall else 3.6, (0, 0), moss=0.5,
                 n_masses=12,
                 bounds=(-200, -200, 200, 200))
        objs.append(g.build())
    return objs


# ============================================================================ main
def export_set(objs, path):
    wp.finalize(objs)
    for o in objs:
        apply_custom_uvs(o)
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
    ap.add_argument('--quick', action='store_true', help='32 samples, 800x500 test renders')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--out', default=None, help='render folder (default: repo renders/)')
    ap.add_argument('--views', default='hero,aerial')
    ap.add_argument('--samples', type=int, default=None)
    ap.add_argument('--hide-trees', action='store_true', help='debug: render the house without trees')
    args = ap.parse_args()

    wp.reset()
    make_materials()
    house_geos = build_house()
    lot_geos = build_lot()
    for g in house_geos + lot_geos:
        print(f'{g.name:20s} {g.tris():8d} tris  mats={g.mats}')
    house_objs = [g.build() for g in house_geos]
    lot_objs = [g.build() for g in lot_geos]

    mdir = os.path.join(REPO, 'models', 'homes')
    house_glb = os.path.join(mdir, f'{ID}.glb')
    lot_glb = os.path.join(mdir, f'{ID}-lot.glb')
    th = export_set(house_objs, house_glb)
    tl = export_set(lot_objs, lot_glb)
    mn, mx = bbox(house_objs)
    lmn, lmx = bbox(lot_objs)
    print(f'house bbox {tuple(round(v, 2) for v in mn)} .. {tuple(round(v, 2) for v in mx)}')
    print(f'lot   bbox {tuple(round(v, 2) for v in lmn)} .. {tuple(round(v, 2) for v in lmx)}')
    meta = {
        'id': ID, 'name': "Monet Williams's house", 'address': '648 Oak Street', 'neighborhood': 'Garden District',
        'residents': ['Monet Williams', 'Calista Yuen', 'Victor Yuen', 'Gordy Yuen'],
        'status': "Canon 2 (address); design from the author's photo (reference/monet-house.webp)",
        'atlas_building_index': 6973, 'footprint_m': list(SITE['footprint']),
        'ridge_height_m': round(ZR, 2), 'top_height_m': round(mx.z, 2), 'stories': 2,
        'style': 'Lowcountry Victorian farmhouse',
        'materials': ['painted lap siding, pale blue-grey (about #B8C3CD after board shading), 115 mm exposure',
                      'white painted trim, corner boards, scalloped fascia valance',
                      'navy louvered shutters (#2B3350)',
                      'weathered grey architectural asphalt shingles',
                      'old red brick piers, steps, cheek walls and chimneys',
                      'white diagonal lattice and slatted porch skirting',
                      'grey painted porch floor, pale blue beadboard porch ceiling'],
        'triangles': th + tl, 'triangles_house': th, 'triangles_lot': tl,
        'files': {'house': f'models/homes/{ID}.glb', 'lot': f'models/homes/{ID}-lot.glb'},
        'file_mb': {'house': round(os.path.getsize(house_glb) / 1e6, 2), 'lot': round(os.path.getsize(lot_glb) / 1e6, 2)},
        'house_bbox_m': [[round(v, 2) for v in mn], [round(v, 2) for v in mx]],
        'lot_local_rect_m': list(SITE['lot']),
        'curb_line_local_y': SITE['curb_y'],
        'notes': ("Main block 12.4 x 11.0 m, first floor raised 0.95 m on brick piers, eaves 7.8 m, ridge "
                  f"{ZR:.1f} m (Atlas height 10 m; the photo needs the taller roof). The photo shows a long ridge with "
                  "near-vertical roof ends, so the hip ends are pitched steeper (60 deg) than the front and back "
                  "(38 deg). Wraparound porch 3.0 m deep on the front and both sides; the left return stops short of "
                  "the side wing, the right return has brick steps at its back end toward the driveway. From the photo: "
                  "massing, three dormers with sawn bargeboards and finials, scalloped fascia, turned posts with fan "
                  "brackets, sawn balusters, balcony with flower boxes, double entry with sidelights and transom, "
                  "lanterns, brick steps, slatted porch skirting, white picket fence with an X-braced gate, brick walk, "
                  "rounded ornamental tree right of the walk, and the two moss-hung live oaks (both stand front left "
                  "in the photo; the brief put one behind the house, the photo was followed). Interpreted (not "
                  "visible in the photo): side and rear elevations, the hipped side wing, the rear kitchen ell and "
                  "stoop, chimney positions on the rear slope, lattice under the house block (per the brief), shell "
                  "driveway with concrete apron, mailbox, HVAC condensers, roll carts, porch rockers, swing and ferns.")}
    with open(os.path.join(mdir, f'{ID}.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print(json.dumps({k: meta[k] for k in ('triangles', 'triangles_house', 'triangles_lot', 'file_mb', 'ridge_height_m')}))

    if args.no_render:
        return
    out = args.out or os.path.join(REPO, 'renders')
    samples = args.samples or (32 if args.quick else 128)
    res = (800, 500) if args.quick else (1600, 1000)
    extras = render_extras()
    wp.finalize(extras)
    for o in extras:
        apply_custom_uvs(o)
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=48, sun_az=212, threads=2, exposure=0.45)
    sun.data.color = (1.0, 0.93, 0.82)
    sun.data.energy = 4.4
    sun.data.angle = math.radians(1.5)
    wnt = bpy.context.scene.world.node_tree
    bgn = wnt.nodes['Background']
    sky_link = bgn.inputs['Color'].links[0]
    mixn = wnt.nodes.new('ShaderNodeMix')
    mixn.data_type = 'RGBA'
    mixn.inputs['Factor'].default_value = 0.4
    mixn.inputs[7].default_value = (0.62, 0.6, 0.53, 1.0)
    wnt.links.new(sky_link.from_socket, mixn.inputs[6])
    wnt.links.new(mixn.outputs[2], bgn.inputs['Color'])
    bgn.inputs['Strength'].default_value = 0.42
    lawn = bpy.data.materials.get('RenderLawn')
    if lawn:
        mixl = lawn.node_tree.nodes.new('ShaderNodeMix')
        mixl.data_type = 'RGBA'
        mixl.blend_type = 'MULTIPLY'
        mixl.inputs['Factor'].default_value = 1.0
        mixl.inputs[7].default_value = (0.95, 1.0, 0.62, 1.0)
        bsd = lawn.node_tree.nodes['Principled BSDF']
        src = bsd.inputs['Base Color'].links[0].from_socket
        lawn.node_tree.links.new(src, mixl.inputs[6])
        lawn.node_tree.links.new(mixl.outputs[2], bsd.inputs['Base Color'])
    if args.hide_trees:
        for o in bpy.context.scene.objects:
            if o.name.startswith(('Tree_', 'Render_BG')):
                o.hide_render = True
    views = args.views.split(',')
    if 'hero' in views:
        wp.camera(CAM_HERO['loc'], CAM_HERO['target'], CAM_HERO['lens'])
        wp.render(os.path.join(out, f'{ID}.jpg'))
    if 'aerial' in views:
        for o in bpy.context.scene.objects:      # background trees standing between the aerial camera and the lot
            if o.name in ('Render_BG_110', 'Render_BG_111', 'Render_BG_105'):
                o.hide_render = True
        wp.camera(CAM_AERIAL['loc'], CAM_AERIAL['target'], CAM_AERIAL['lens'])
        wp.render(os.path.join(out, f'{ID}-aerial.jpg'))
    for v, c in CAM_DEBUG.items():
        if v in views:
            wp.camera(c['loc'], c['target'], c['lens'])
            wp.render(os.path.join(out, f'{ID}-{v}.jpg'))


if __name__ == '__main__':
    main()
