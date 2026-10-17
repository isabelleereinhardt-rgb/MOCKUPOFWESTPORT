#!/usr/bin/env python3
"""Delacroix house, 3064 Harbor Drive, Harborview (hero home #2, proposed).

Lori Delacroix's family estate. Design from the author's film still (reference/lori-house.webp), with
reference/board-17.jpg and board-19.jpg for detail: a red-brown brick Georgian / Colonial Revival house.

  * Main block: symmetrical, two full stories plus an attic (2.5 stories), Flemish-bond brick on a
    projecting brick base with a limestone water table, dark slate hipped roof, white dentil cornice,
    two pedimented dormers front and back, twin tall corbelled end chimneys.
  * Centre: a projecting brick pavilion with white corner pilasters and a white pediment. A large
    Palladian window (arched fanlight door with sidelights) rises into the tympanum. Below it the entry
    portico: paired Tuscan columns, a full entablature and a flat roof with a white balustrade that
    forms the balcony. Panelled entry door with sidelights and transom, carriage lanterns either side.
  * 6-over-6 double-hung windows with black louvered shutters, limestone sills, jack-arch lintels with
    keystones; arched fanlight windows on the main first floor.
  * Left: a 1.5-story cross-gabled wing with a front-facing gable, a gable window and a box bay with a
    lead-coated copper roof; a shed-roofed side porch fills the corner between the wing and the pavilion
    (as in the photo).  Right: a lower two-story hipped wing with a side entry.  Rear: a one-story ell.
  * Wide brick steps with bluestone-capped plinths and cast-stone urns (house GLB).
  * Lot GLB: circular asphalt drive with Belgian-block edging and a planted island, reaching the curb at
    two points, a spur to a parking court, brick gate piers with lanterns, boxwood foundation plantings,
    mulch beds, a rear brick terrace and three mature hardwoods.

Run (rebuilds GLBs, JSON and the final renders):
    python3 tools/blender/homes/delacroix_house.py
Iteration renders (32 samples, 800 x 500, into a scratch folder):
    python3 tools/blender/homes/delacroix_house.py --quick --out /path/to/scratch
Other flags: --no-render, --no-export, --views hero,aerial,front,left,rear
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
from mathutils.geometry import tessellate_polygon  # noqa: E402
from PIL import Image  # noqa: E402

ID = 'delacroix-house'
REPO = wp.REPO

# ============================================================================ site (meters, local frame)
# Origin = Atlas footprint centre at grade; the front faces -Y (Harbor Drive); +X is to the right as seen
# from the street.  docs/site-specs.json: footprint 24.4 x 18.74, curb line y = -33.04, neighbours at
# x = +42.3 and -44.4 (so the lot runs halfway to them).
FOOT = (24.4, 18.74)
CURB_Y = -33.04
LOT = (-22.0, CURB_Y, 21.0, 25.0)          # x0, y0, x1, y1

# ============================================================================ plan + heights
MX0, MX1, MY0, MY1 = -9.0, 9.0, -5.75, 5.75    # main block walls (18.0 x 11.5)
PX, PY0 = 2.8, -6.75                         # pavilion half width, pavilion front wall
FF1, FF2 = 0.60, 4.15                        # finished floors
WTAB = 0.54                                  # top of the limestone water table (bottom of wall faces)
SOF = 7.20                                   # main cornice soffit
OV = 0.66                                    # main roof drip edge, out from the wall face
ZE = SOF + 0.34                              # roof top surface at the drip edge
TH = 0.07                                    # roof slab (slate + deck) thickness
PITCH = 34.0
T = math.tan(math.radians(PITCH))
W2, D2 = MX1 + OV, MY1 + OV                  # roof outline half sizes (9.66, 6.41)
RX = W2 - D2                                 # half ridge length
ZR = ZE + D2 * T                             # main ridge
PED_P = 30.0
PT = math.tan(math.radians(PED_P))
PXO = PX + OV                                # pediment roof half width (3.46)
Z_PED = ZE + PXO * PT                        # pediment apex (roof top)
Y_VAL = -D2 + (Z_PED - ZE) / T               # where the pediment ridge dies into the main roof
BAYS = (-7.45, -4.35, 4.35, 7.45)            # main block window bays (x)
DORMERS = (-5.0, 5.0)
CHIMNEYS = ((-7.0, 1.2), (7.0, 1.2))
CH_TOP = 13.55

# left wing (front-facing gable), side porch, right wing, rear ell
LW = dict(x0=-15.0, x1=MX0, y0=-8.0, y1=3.5, sof=4.55, ov=0.35, pitch=43.0)
LW_ZE = LW['sof'] + 0.20
LW_T = math.tan(math.radians(LW['pitch']))
LW_XC = (LW['x0'] + LW['x1']) / 2
LW_ZR = LW_ZE + ((LW['x1'] - LW['x0']) / 2 + LW['ov']) * LW_T
PORCH = dict(x0=MX0, x1=-3.85, y0=-7.75, fl=0.45, z_wall=4.40, pitch=14.0, ov=0.30)
RW = dict(x0=MX1, x1=15.0, y0=-4.75, y1=4.25, sof=6.10, ov=0.45, ff2=3.75)
RW_ZE = RW['sof'] + 0.20
EL = dict(x0=-3.0, x1=3.0, y0=MY1, y1=9.3, sof=3.90, ov=0.40, pitch=30.0)
EL_ZE = EL['sof'] + 0.20

# portico
PO = dict(xi=2.05, yf=-8.85, col_z1=3.55, deck=4.05, cols=(-2.2, -1.65, 1.65, 2.2), col_y=-9.0, col_r=0.16)
STEPS = dict(x=3.4, y_top=-9.45, n=4, run=0.36)

CAM_HERO = dict(loc=(-12.0, -29.0, 1.7), target=(0.6, -5.0, 4.4), lens=26)
CAM_AERIAL = dict(loc=(30.0, -64.0, 50.0), target=(0.0, -6.0, 2.0), lens=30)
CAM_FRONT = dict(loc=(0.0, -36.0, 1.7), target=(0.0, -4.0, 5.2), lens=28)
CAM_LEFT = dict(loc=(-34.0, -18.0, 3.0), target=(-6.0, -2.0, 4.5), lens=30)
CAM_REAR = dict(loc=(-26.0, 36.0, 9.0), target=(0.0, 2.0, 4.0), lens=30)


# ============================================================================ mesh builder
class Fr:
    """Right-handed frame: u along U, z along Z, d along N (outward); U x Z = N."""

    def __init__(self, O, U, N, Z=None):
        self.O = Vector(O)
        self.U = Vector(U).normalized()
        self.N = Vector(N).normalized()
        self.Z = Vector(Z).normalized() if Z is not None else self.N.cross(self.U)

    def p(self, u, z, d=0.0):
        return self.O + self.U * u + self.Z * z + self.N * d

    def v(self, u, z, d=0.0):
        return self.U * u + self.Z * z + self.N * d

    def side(self):
        """Frame whose (u, z) are this frame's (d, z); its extrusion axis is -U."""
        return Fr(self.O, self.N, -self.U, self.Z)


WORLD = Fr((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0))   # p(u, z, d) = (u, z, d)


def wallF(a, b):
    """Frame for a wall from a to b (plan points, walls traversed counter-clockwise, so outward = right)."""
    U = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
    N = Vector((U.y, -U.x, 0))
    return Fr((a[0], a[1], 0), U, N), (Vector(b) - Vector(a)).length


GEOS = {}
MAT = {}


class Geo:
    """Accumulates polygons for one output object (several materials)."""

    def __init__(self, name):
        self.name = name
        self.V, self.F, self.FM, self.FS, self.C = [], [], [], [], []
        self.UV = {}
        self.NRM = {}
        self.mats = []
        self.vc = False

    def add(self, verts, faces, mat, smooth=False, colors=None, uvs=None, normals=None):
        if mat not in self.mats:
            self.mats.append(mat)
        mi = self.mats.index(mat)
        b = len(self.V)
        if normals is not None:
            for i, nv in enumerate(normals):
                self.NRM[b + i] = tuple(nv)
        self.V.extend(tuple(v) for v in verts)
        if colors is not None:
            self.vc = True
            self.C.extend(tuple(c[:3]) for c in colors)
        else:
            self.C.extend([(1.0, 1.0, 1.0)] * len(verts))
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
        if self.vc:
            ca = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
            li = [0] * len(me.loops)
            me.loops.foreach_get('vertex_index', li)
            cols = []
            for vi in li:
                c = self.C[vi]
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


def apply_custom_uvs(o):
    """After wp.finalize (box UVs), overwrite the faces that carry their own UVs (roofs, bark)."""
    g = GEOS.get(o.get('_geo'))
    if not g or not g.UV or len(o.data.polygons) != len(g.F):
        return
    me = o.data
    uvl = me.uv_layers.active.data
    for fi, uvs in g.UV.items():
        pl = me.polygons[fi]
        t = me.materials[pl.material_index].get('tile', 1.0)
        for k, li in enumerate(range(pl.loop_start, pl.loop_start + pl.loop_total)):
            uvl[li].uv = (uvs[k][0] / t, uvs[k][1] / t)


# ---------------------------------------------------------------------------- primitives
def area2(pts):
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


def fill(g, mat, F, outline, holes=(), d=0.0, facing=None):
    """Planar face in frame F: an outline polygon [(u, z)] with polygon holes, triangulated."""
    loops = [[Vector((u, z, 0)) for u, z in outline]] + [[Vector((u, z, 0)) for u, z in h] for h in holes]
    tris = tessellate_polygon(loops)
    flat = [F.p(p.x, p.y, d) for L in loops for p in L]
    fac = Vector(facing) if facing is not None else F.N
    faces = []
    for t in tris:
        a, b, c = flat[t[0]], flat[t[1]], flat[t[2]]
        nn = (b - a).cross(c - a)
        if nn.length < 1e-9:
            continue
        faces.append(t if nn.dot(fac) > 0 else (t[0], t[2], t[1]))
    g.add(flat, faces, mat)


def extrude(g, mat, F, pts, d0, d1, caps=True, smooth=False, cap_mat=None):
    """Polygon [(u, z)] in frame F, extruded along F.N from d0 to d1."""
    if area2(pts) < 0:
        pts = pts[::-1]
    if d1 < d0:
        d0, d1 = d1, d0
    n = len(pts)
    V = [F.p(u, z, d0) for u, z in pts] + [F.p(u, z, d1) for u, z in pts]
    sides = [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    g.add(V, sides, mat, smooth)
    if caps:
        g.add(V, [list(range(n))[::-1], list(range(n, 2 * n))], cap_mat or mat, False)


def fbox(g, mat, F, u0, u1, z0, z1, d0, d1):
    if abs(u1 - u0) < 1e-5 or abs(z1 - z0) < 1e-5 or abs(d1 - d0) < 1e-5:
        return
    u0, u1 = min(u0, u1), max(u0, u1)
    z0, z1 = min(z0, z1), max(z0, z1)
    extrude(g, mat, F, [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], d0, d1)


def uextrude(g, mat, F, prof, u0, u1, caps=True):
    """Cross-section [(d, z)] in frame F extruded along F.U from u0 to u1 (sills, mouldings)."""
    extrude(g, mat, F.side(), prof, -u1, -u0, caps=caps)


def box(g, mat, x0, x1, y0, y1, z0, z1):
    fbox(g, mat, WORLD, x0, x1, y0, y1, z0, z1)


def cbox(g, mat, cx, cy, sx, sy, z0, z1):
    box(g, mat, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1)


def prism(g, mat, pts, z0, z1, caps=True):
    extrude(g, mat, WORLD, pts, z0, z1, caps=caps)


def seg_box(g, mat, p0, p1, w, h, up=(0, 0, 1), ext=0.0):
    """Box along p0->p1, w wide (horizontal) and h tall (along `up`), centred on the line."""
    p0, p1 = Vector(p0), Vector(p1)
    U = (p1 - p0).normalized()
    upv = Vector(up)
    Z = (upv - U * upv.dot(U)).normalized()
    N = U.cross(Z)
    F = Fr(p0, U, N, Z)
    L = (p1 - p0).length
    fbox(g, mat, F, -ext, L + ext, -h / 2, h / 2, -w / 2, w / 2)


def lathe(g, mat, prof, cx, cy, seg=12, z0=0.0, caps=True, smooth=True, colors=None):
    """Turned solid from a profile [(r, z)] bottom to top."""
    rings = []
    V = []
    for r, z in prof:
        ring = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ring.append(len(V))
            V.append((cx + r * math.cos(a), cy + r * math.sin(a), z0 + z))
        rings.append(ring)
    F = []
    for A, B in zip(rings, rings[1:]):
        for i in range(seg):
            F.append([A[i], A[(i + 1) % seg], B[(i + 1) % seg], B[i]])
    g.add(V, F, mat, smooth=smooth, colors=colors)
    if caps:
        if prof[0][0] > 1e-4:
            poly(g, mat, [V[i] for i in rings[0]], facing=(0, 0, -1))
        if prof[-1][0] > 1e-4:
            poly(g, mat, [V[i] for i in rings[-1]], facing=(0, 0, 1))


def tube(g, mat, pts, radii, seg=8, colors=None, cap_end=True, uv_circ=1.6):
    """Tapered tube through pts (parallel-transport frames), with cylindrical UVs in meters."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    Tn = []
    for k in range(n):
        a = pts[max(k - 1, 0)]
        b = pts[min(k + 1, n - 1)]
        Tn.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(Tn[0].z) < 0.9 else Vector((1, 0, 0))
    n1 = (ref - Tn[0] * ref.dot(Tn[0])).normalized()
    N1 = [n1]
    for k in range(1, n):
        v = N1[-1] - Tn[k] * N1[-1].dot(Tn[k])
        N1.append(v.normalized() if v.length > 1e-6 else N1[-1])
    V, C = [], []
    vs = [0.0]
    for k in range(1, n):
        vs.append(vs[-1] + (pts[k] - pts[k - 1]).length)
    for k in range(n):
        n2 = Tn[k].cross(N1[k])
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            V.append(pts[k] + radii[k] * (math.cos(a) * N1[k] + math.sin(a) * n2))
            C.append(colors[k] if colors else (1, 1, 1))
    F, UV = [], []
    circ = 2 * math.pi * (radii[0] + radii[-1]) / 2
    circ = max(uv_circ, round(circ / uv_circ) * uv_circ) if circ > 0.6 else circ
    for k in range(n - 1):
        for i in range(seg):
            a, b = k * (seg + 1) + i, k * (seg + 1) + i + 1
            c, d = (k + 1) * (seg + 1) + i + 1, (k + 1) * (seg + 1) + i
            F.append([a, b, c, d])
            u0, u1 = circ * i / seg, circ * (i + 1) / seg
            UV.append([(u0, vs[k]), (u1, vs[k]), (u1, vs[k + 1]), (u0, vs[k + 1])])
    if cap_end:
        F.append([(n - 1) * (seg + 1) + i for i in range(seg)])
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


def blob(g, mat, c, r3, seed, rough=0.28, freq=1.4, sub=2, colfn=None, flat_bottom=None, nfn=None):
    V0, F0 = ico(sub)
    rng = np.random.default_rng(seed)
    off = Vector(rng.uniform(-50, 50, 3))
    verts, cols, nrms = [], [], []
    for v in V0:
        d = Vector(v)
        s = 1 + rough * mnoise.noise(d * freq + off) + rough * 0.45 * mnoise.noise(d * freq * 2.7 + off * 1.3)
        p = Vector((c[0] + d.x * r3[0] * s, c[1] + d.y * r3[1] * s, c[2] + d.z * r3[2] * s))
        if flat_bottom is not None and p.z < flat_bottom:
            p.z = flat_bottom + (p.z - flat_bottom) * 0.15
        verts.append(p)
        cols.append(colfn(p, d) if colfn else (1, 1, 1))
        if nfn:
            nrms.append(nfn(p, d))
    g.add(verts, F0, mat, smooth=True, colors=cols if colfn else None, normals=nrms if nfn else None)


def rect(u0, u1, z0, z1):
    return [(u0, z0), (u1, z0), (u1, z1), (u0, z1)]


def arc(cu, cz, r, a0, a1, n):
    return [(cu + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cz + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def arch_poly(u0, u1, z0, zs, n=16):
    r = (u1 - u0) / 2
    return [(u0, z0), (u1, z0)] + arc((u0 + u1) / 2, zs, r, 0, 180, n)


def reveal(g, mat, F, hole, depth, d0=0.0):
    """Return faces (jambs, head, sill) of an opening through a wall face, from d0 back to d0 - depth."""
    h = list(hole)
    if area2(h) < 0:
        h = h[::-1]
    n = len(h)
    for i in range(n):
        a, b = h[i], h[(i + 1) % n]
        du, dz = b[0] - a[0], b[1] - a[1]
        if abs(du) + abs(dz) < 1e-7:
            continue
        fac = F.U * (-dz) + F.Z * du          # into the opening
        poly(g, mat, [F.p(a[0], a[1], d0), F.p(b[0], b[1], d0), F.p(b[0], b[1], d0 - depth),
                      F.p(a[0], a[1], d0 - depth)], facing=fac)


def line_mid(pa, da, pb, db):
    """Midpoint of the closest points of two lines (miter joints)."""
    w0 = pa - pb
    a, b, c = da.dot(da), da.dot(db), db.dot(db)
    d, e = da.dot(w0), db.dot(w0)
    den = a * c - b * b
    if abs(den) < 1e-9:
        return (pa + pb) / 2
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    return ((pa + da * s) + (pb + db * t)) / 2


def plane_hit(p, d, plane):
    o, n = plane
    den = d.dot(n)
    if abs(den) < 1e-9:
        return p
    return p + d * ((o - p).dot(n) / den)


def sweep(g, mats, path, profile, outs=None, ups=None, closed=False, caps=(True, True), end_planes=(None, None),
          closed_profile=False, smooth=False):
    """Extrude a profile [(d, h)] along a 3D polyline with mitred joints.
    Profile traversed with the solid on its LEFT (so faces point to the right). For each path segment, d
    runs along outs[s] and h along ups[s]; by default outs = right-hand horizontal normal, ups = +Z.
    mats: one material or a list per profile edge."""
    P = [Vector((p[0], p[1], p[2] if len(p) > 2 else 0.0)) for p in path]
    npts = len(P)
    nseg = npts if closed else npts - 1
    dirs = [(P[(s + 1) % npts] - P[s]).normalized() for s in range(nseg)]
    if outs is None:
        outs = [Vector((dd.y, -dd.x, 0)).normalized() for dd in dirs]
    if ups is None:
        ups = [Vector((0, 0, 1))] * nseg
    outs = [Vector(o) for o in outs]
    ups = [Vector(u) for u in ups]
    m = len(profile)
    rings = []
    for k in range(npts):
        segs = []
        if closed or k > 0:
            segs.append((k - 1) % nseg)
        if closed or k < npts - 1:
            segs.append(k % nseg)
        ring = []
        for (d, h) in profile:
            if len(segs) == 1:
                s = segs[0]
                q = P[k] + outs[s] * d + ups[s] * h
                pl = end_planes[0] if k == 0 else end_planes[1]
                if pl is not None:
                    q = plane_hit(q, dirs[s], pl)
                ring.append(q)
            else:
                a, b = segs
                ring.append(line_mid(P[k] + outs[a] * d + ups[a] * h, dirs[a], P[k] + outs[b] * d + ups[b] * h, dirs[b]))
        rings.append(ring)
    ne = m if closed_profile else m - 1
    for s in range(nseg):
        r0, r1 = rings[s], rings[(s + 1) % npts]
        for i in range(ne):
            j = (i + 1) % m
            (d0, h0), (d1, h1) = profile[i], profile[j]
            fac = outs[s] * (h1 - h0) - ups[s] * (d1 - d0)
            mat = mats[i] if isinstance(mats, (list, tuple)) else mats
            if (r0[i] - r0[j]).length < 1e-7 and (r1[i] - r1[j]).length < 1e-7:
                continue
            poly(g, mat, [r0[i], r0[j], r1[j], r1[i]], facing=fac, smooth=smooth)
    if not closed:
        cm = mats[0] if isinstance(mats, (list, tuple)) else mats
        prof2 = [Vector((d, h, 0)) for d, h in profile]
        tris = tessellate_polygon([prof2])
        for end, ring, fac in ((0, rings[0], -dirs[0]), (1, rings[-1], dirs[-1])):
            if not caps[end]:
                continue
            for t in tris:
                poly(g, cm, [ring[t[0]], ring[t[1]], ring[t[2]]], facing=fac)


# ============================================================================ textures + materials
def _norm01(a):
    return (a - a.min()) / max(1e-6, a.max() - a.min())


def tex_flemish(key, n=2048, tile=2.58, seed=1):
    """Flemish bond (stretcher + header in every course, headers centred over the stretchers below), warm
    red-brown handmade-look brick with darker burnt headers, recessed light mortar, gentle soiling."""
    rng = np.random.default_rng(seed)
    px = n / tile
    courses = 39
    ch = tile / courses
    per = tile / 8
    sw, hw = per * 2 / 3, per / 3
    jt = 0.0095
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / px
    r = (y / ch).astype(int)
    off = (r % 2) * (per / 2)
    xx = (x + off) % tile
    k = (xx / per).astype(int) % 8
    lx = xx - k * per
    hdr = lx >= sw
    lxb = np.where(hdr, lx - sw, lx)
    bw = np.where(hdr, hw, sw)
    ly = y - r * ch
    joint = (lxb < jt) | (ly < jt)
    # distance to the joint (for arris shading)
    ex = np.minimum(lxb - jt, bw - lxb)
    ey = np.minimum(ly - jt, ch - ly)
    edge = np.clip(np.minimum(ex, ey) / 0.006, 0, 1)
    bid = (r % courses) * 16 + k * 2 + hdr
    R = np.random.default_rng(seed + 1).random((courses * 16 + 16, 4)).astype(np.float32)
    rb = R[bid]
    base = wp._rgb('#84503f')
    tone = 1 + (rb[..., 0] - 0.5) * 0.28
    # palette: muted red-brown, brown, salmon, plum-dark and a few greyed (weathered) bricks
    pal = np.array([wp._rgb('#8f5341'), wp._rgb('#7f4738'), wp._rgb('#75473b'), wp._rgb('#986349'),
                    wp._rgb('#6a3e34'), wp._rgb('#87594b'), wp._rgb('#7b5b50'), wp._rgb('#8a4a3a')])
    pick = (rb[..., 1] * len(pal)).astype(int) % len(pal)
    col = pal[pick] * 0.65 + base * 0.35
    col = col * tone[..., None]
    burnt = hdr & (rb[..., 2] < 0.55)
    col = np.where(burnt[..., None], col * np.array([0.72, 0.70, 0.78]), col)
    fine = wp._noise(n, 160 * tile / 2.58, rng, 2)
    mid = wp._noise(n, 40 * tile / 2.58, rng, 3)
    big = wp._noise(n, 3, rng, 3)
    speck = (rng.random((n, n)) < 0.012).astype(np.float32)
    col = col * (0.88 + 0.22 * fine[..., None]) * (0.92 + 0.12 * mid[..., None])
    col = col * (1 - 0.35 * speck[..., None])
    col = col * (0.82 + 0.18 * edge[..., None])
    mort = wp._rgb('#aba393') * (0.86 + 0.2 * fine[..., None])
    alb = np.where(joint[..., None], mort, col)
    alb = alb * (0.93 + 0.1 * big[..., None])
    h = np.where(joint, 0.0, 0.55 + 0.45 * edge) + fine * 0.12 + mid * 0.08
    a = wp._save(alb, key, quality=88)
    nrm = wp._save(wp._normal_from_height(h, 2.4), key + '_n', quality=85)
    Image.open(nrm).resize((1024, 1024), Image.LANCZOS).save(nrm, quality=85)
    return a, nrm, tile


def tex_slate(key, n=2048, tile=3.0, seed=3):
    """Natural slate: 0.1875 m exposure, 0.30 m wide, blue-grey/plum/green-grey mix, butt-edge shadows."""
    rng = np.random.default_rng(seed)
    px = n / tile
    rows = 16
    rh = tile / rows
    cols = 10
    cw = tile / cols
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / px
    r = (y / rh).astype(int)
    jit = np.random.default_rng(seed + 4).random(rows + 1)[r % rows] * 0.12
    xx = (x + (r % 2) * cw / 2 + jit) % tile
    c = (xx / cw).astype(int) % cols
    lx = xx - c * cw
    t = (y - r * rh) / rh          # 0 at the top of a course (under the butt above), 1 at its own butt
    R = np.random.default_rng(seed + 1).random((rows + 1, cols + 1, 3)).astype(np.float32)
    rr = R[r % rows, c]
    pal = np.array([wp._rgb('#3c4148'), wp._rgb('#41434b'), wp._rgb('#3a3e3d'), wp._rgb('#46454c'),
                    wp._rgb('#34383e'), wp._rgb('#4a4c50')])
    col = pal[(rr[..., 0] * len(pal)).astype(int) % len(pal)]
    col = col * (0.88 + 0.24 * rr[..., 1])[..., None]
    streak = wp._noise(n, 30, rng, 3)
    st = streak.copy()
    for s in (1, 2, 3, 5, 8):
        st += np.roll(streak, s * 3, 0)
    st = _norm01(st)
    fine = wp._noise(n, 150, rng, 2)
    col = col * (0.86 + 0.16 * st[..., None]) * (0.94 + 0.1 * fine[..., None])
    shade = 0.62 + 0.38 * np.clip(t * 3.5, 0, 1)
    butt = np.clip((t - 0.93) / 0.07, 0, 1)
    col = col * shade[..., None] * (1 + 0.18 * butt[..., None])
    gap = (lx < 0.005) | (lx > cw - 0.003)
    col = np.where(gap[..., None], col * 0.45, col)
    big = wp._noise(n, 2, rng, 3)
    col = col * (0.9 + 0.16 * big[..., None])
    h = t * 0.8 - gap * 0.5 + st * 0.08 + fine * 0.05
    a = wp._save(col, key, quality=88)
    nrm = wp._save(wp._normal_from_height(h, 2.8), key + '_n', quality=85)
    Image.open(nrm).resize((1024, 1024), Image.LANCZOS).save(nrm, quality=85)
    return a, nrm, tile


def tex_paint(key, color, n=512, tile=1.0, seed=11, amp=0.035):
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 4 * tile, rng, 4)
    fine = wp._noise(n, 48 * tile, rng, 2)
    grain = fine.copy()
    for s in (1, 2, 3, 5, 8, 13):
        grain += np.roll(fine, s, axis=1) + np.roll(fine, -s, axis=1)
    grain = _norm01(grain)
    base = wp._rgb(color)
    alb = base[None, None, :] * (1 - amp + 2 * amp * big[..., None]) * (0.985 + 0.03 * grain[..., None])
    h = big * 0.2 + grain * 0.5
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 0.3), key + '_n'), tile


def tex_stone(key, color, n=1024, tile=1.5, seed=21, amp=0.10, cleft=0.0):
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 3 * tile, rng, 4)
    mid = wp._noise(n, 14 * tile, rng, 3)
    fine = rng.random((n, n)).astype(np.float32)
    base = wp._rgb(color)
    alb = base * (1 - amp + 2 * amp * big[..., None]) * (0.95 + 0.07 * mid[..., None]) * (0.97 + 0.05 * fine[..., None])
    if cleft:
        cl = wp._noise(n, 6 * tile, rng, 5)
        alb = alb * (0.9 + 0.2 * cl[..., None])
    h = big * 0.3 + mid * 0.3 + fine * 0.1 + (cleft * wp._noise(n, 8 * tile, rng, 4))
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 1.2), key + '_n'), tile


def tex_glass(key, n=512, tile=2.0, seed=81):
    """Dark glazing with faint interior shapes (curtains, rooms) so windows do not read as identical."""
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 3, rng, 3)
    folds = wp._noise(n, 18, rng, 2)
    fs = folds.copy()
    for k in range(1, 20):
        fs += np.roll(folds, k * 2, 0)
    fs = _norm01(fs)
    curtain = np.clip((big - 0.5) * 3, 0, 1) * (0.6 + 0.4 * fs)
    dark, light = wp._rgb('#1e2327'), wp._rgb('#8c8678')
    alb = dark + (light - dark) * (curtain * 0.45)[..., None]
    return wp._save(alb, key), None, tile


def tex_copper(key, n=512, tile=1.0, seed=31):
    rng = np.random.default_rng(seed)
    big = wp._noise(n, 3, rng, 4)
    streak = wp._noise(n, 10, rng, 3)
    st = streak.copy()
    for s in range(1, 12):
        st += np.roll(streak, s * 4, 0)
    st = _norm01(st)
    base = wp._rgb('#5f4a3c')
    pat = wp._rgb('#6d7f72')
    m = np.clip((st - 0.62) * 2.5, 0, 1) * 0.5
    alb = base * (0.85 + 0.3 * big[..., None])
    alb = alb * (1 - m[..., None]) + pat * m[..., None]
    return wp._save(alb, key), wp._save(wp._normal_from_height(big * 0.2, 0.5), key + '_n'), tile


def tex_bark(key, n=1024, tile=1.4, seed=41):
    """Hardwood (white oak) bark: grey-brown, shallow blocky ridges with lichen."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] / n
    w1 = wp._noise(n, 4, rng, 4)
    w2 = wp._noise(n, 9, rng, 3)
    kx = 18
    fx = kx * x + 2.4 * (w1 - 0.5) + 0.8 * (w2 - 0.5)
    fur = np.abs(np.sin(np.pi * fx)) ** 0.7
    col_ = np.floor(fx).astype(int) % kx
    off = np.random.default_rng(seed + 1).random(kx)[col_]
    brk = np.clip((np.abs(np.sin(np.pi * (7 * y + off * 4 + 1.5 * (w2 - 0.5)))) - 0.06) * 5, 0, 1)
    plate = np.clip(fur * 1.4 - 0.2, 0, 1) * brk
    fine = wp._noise(n, 80, rng, 2)
    lich = np.clip((wp._noise(n, 9, rng, 3) - 0.6) * 3.5, 0, 1)
    dark, light, lc = wp._rgb('#2a2622'), wp._rgb('#6e675e'), wp._rgb('#8a8d7c')
    alb = dark + (light - dark) * (plate * (0.6 + 0.4 * fine))[..., None]
    lm = (lich * plate)[..., None] * 0.5
    alb = alb * (1 - lm) + lc * lm
    h = plate * 0.8 + fine * 0.2
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 3.0), key + '_n'), tile


def tex_leaves(key, color, n=1024, tile=1.5, seed=51, flowers=None, fcov=0.0, fsize=70, contrast=1.0):
    rng = np.random.default_rng(seed)
    l1 = wp._noise(n, 45 * tile, rng, 2)
    l2 = wp._noise(n, 100 * tile, rng, 2)
    big = wp._noise(n, 3 * tile, rng, 3)
    leaf = np.clip((l1 * 0.6 + l2 * 0.4 - 0.28) * 2.3 * contrast, 0, 1)
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


def tex_foliage(key, color, n=1024, tile=1.2, seed=61, leaf=0.07, var=0.16, gap='#18200f', cover=2.4,
                flowers=None, fcov=0.0):
    """Leafy texture: thousands of small overlapping leaves (random angle, size and tint, the lower ones darker)
    over dark gaps; wraps at the edges so it tiles."""
    from PIL import ImageDraw
    rng = np.random.default_rng(seed)
    px = n / tile
    Ll, Wl = leaf * px, leaf * px * 0.46
    count = int(n * n / (0.8 * Ll * Wl) * cover)
    base = wp._rgb(color)
    img = Image.new('RGB', (n, n), tuple(int(c * 255) for c in wp._rgb(gap)))
    hg = Image.new('L', (n, n), 0)
    d, dh = ImageDraw.Draw(img), ImageDraw.Draw(hg)
    fl = wp._rgb(flowers) if flowers else None
    for i in range(count):
        cx, cy = rng.uniform(0, n, 2)
        a = rng.uniform(0, math.pi)
        sz = rng.uniform(0.7, 1.3)
        l, w = Ll * sz / 2, Wl * sz / 2
        depth = i / count
        if fl is not None and rng.random() < fcov:
            col = fl * rng.uniform(0.85, 1.05)
            l, w = l * 0.6, w * 1.2
        else:
            hj = rng.uniform(-1, 1) * 0.07
            col = base * (1 + (rng.random() - 0.5) * 2 * var) * (0.62 + 0.45 * depth) * np.array([1 + hj, 1, 1 - hj])
        col = tuple(int(c) for c in np.clip(col * 255, 0, 255))
        ca, sa = math.cos(a), math.sin(a)
        shape = [(-1, 0), (-0.6, 0.75), (0, 1), (0.6, 0.75), (1, 0), (0.6, -0.75), (0, -1), (-0.6, -0.75)]
        pts = [(cx + ca * x * l - sa * y * w, cy + sa * x * l + ca * y * w) for x, y in shape]
        hv = int(60 + 190 * depth)
        for ox in (-n, 0, n):
            for oy in (-n, 0, n):
                if (ox and not (cx + ox > -l and cx + ox < n + l)) or (oy and not (cy + oy > -l and cy + oy < n + l)):
                    continue
                q = [(x + ox, y + oy) for x, y in pts]
                d.polygon(q, fill=col)
                dh.polygon(q, fill=hv)
    alb = np.asarray(img).astype(np.float32) / 255
    h = np.asarray(hg).astype(np.float32) / 255
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 2.0), key + '_n'), tile


def tex_leafcard(key, color, n=1024, seed=91, leaf=0.07, size=1.1, var=0.2):
    """RGBA cluster of overlapping leaves with a ragged outline on a transparent ground (foliage cards)."""
    from PIL import ImageDraw
    rng = np.random.default_rng(seed)
    px = n / size
    Ll, Wl = leaf * px, leaf * px * 0.46
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    hg = Image.new('L', (n, n), 0)
    d, dh = ImageDraw.Draw(img), ImageDraw.Draw(hg)
    base = wp._rgb(color)
    count = 1100
    k = 0
    while k < count:
        cx, cy = rng.normal(0.5, 0.17, 2) * n
        if not (0.05 * n < cx < 0.95 * n and 0.05 * n < cy < 0.95 * n):
            continue
        k += 1
        depth = k / count
        a = rng.uniform(0, math.pi)
        sz = rng.uniform(0.7, 1.3)
        l, w = Ll * sz / 2, Wl * sz / 2
        hj = rng.uniform(-1, 1) * 0.07
        col = base * (1 + (rng.random() - 0.5) * 2 * var) * (0.55 + 0.5 * depth) * np.array([1 + hj, 1, 1 - hj])
        col = tuple(int(c) for c in np.clip(col * 255, 0, 255)) + (255,)
        ca, sa = math.cos(a), math.sin(a)
        shape = [(-1, 0), (-0.6, 0.75), (0, 1), (0.6, 0.75), (1, 0), (0.6, -0.75), (0, -1), (-0.6, -0.75)]
        pts = [(cx + ca * x * l - sa * y * w, cy + sa * x * l + ca * y * w) for x, y in shape]
        d.polygon(pts, fill=col)
        dh.polygon(pts, fill=int(60 + 190 * depth))
    path = os.path.join(wp.TEX_DIR, key + '.png')
    img.save(path)
    h = np.asarray(hg).astype(np.float32) / 255
    return path, wp._save(wp._normal_from_height(h, 2.0), key + '_n')


def card_material(name, png, nrm, rough=0.8, spec=0.25):
    """Alpha-clipped, double-sided foliage card material (exports as glTF alphaMode MASK) x vertex colour."""
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    bs = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = bpy.data.images.load(png)
    ca = nt.nodes.new('ShaderNodeVertexColor')
    ca.layer_name = 'Col'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    nt.links.new(t.outputs['Color'], mix.inputs[6])
    nt.links.new(ca.outputs['Color'], mix.inputs[7])
    nt.links.new(mix.outputs[2], bs.inputs['Base Color'])
    gt = nt.nodes.new('ShaderNodeMath')
    gt.operation = 'GREATER_THAN'
    gt.inputs[1].default_value = 0.5
    nt.links.new(t.outputs['Alpha'], gt.inputs[0])
    nt.links.new(gt.outputs[0], bs.inputs['Alpha'])
    tn = nt.nodes.new('ShaderNodeTexImage')
    tn.image = bpy.data.images.load(nrm)
    tn.image.colorspace_settings.name = 'Non-Color'
    nm = nt.nodes.new('ShaderNodeNormalMap')
    nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
    nt.links.new(nm.outputs['Normal'], bs.inputs['Normal'])
    bs.inputs['Roughness'].default_value = rough
    try:
        bs.inputs['Specular IOR Level'].default_value = spec
    except Exception:
        pass
    try:
        m.surface_render_method = 'DITHERED'
    except Exception:
        pass
    m.use_backface_culling = False
    m['tile'] = 1.0
    return m


def tex_lawn(key, n=2048, tile=12.0, seed=81):
    """Render-only lawn: fine blades, soft patches and mowing stripes 1.5 m wide (along x)."""
    rng = np.random.default_rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / px
    blades = rng.random((n, n)).astype(np.float32)
    bl = blades.copy()
    for s_ in (1, 2, 3):
        bl += np.roll(blades, s_, 0)
    bl = _norm01(bl)
    patch = wp._noise(n, 6, rng, 4)
    mid = wp._noise(n, 30, rng, 3)
    stripe = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * y / 3.0))
    base = wp._rgb('#517229')
    alb = base * (0.78 + 0.3 * patch[..., None]) * (0.9 + 0.12 * mid[..., None]) * (0.82 + 0.3 * bl[..., None])
    alb = alb * (0.93 + 0.1 * stripe[..., None])
    alb[..., 0] *= 1 + (patch - 0.5) * 0.25
    return wp._save(alb, key), wp._save(wp._normal_from_height(bl * 0.6 + mid * 0.3, 2.0), key + '_n'), tile


def tex_mulch(key, n=1024, tile=1.5, seed=71):
    rng = np.random.default_rng(seed)
    f = wp._noise(n, 110, rng, 2)
    s1, s2 = f.copy(), f.copy()
    for k in range(1, 8):
        s1 += np.roll(f, k * 2, 1)
        s2 += np.roll(np.roll(f, k * 2, 0), k, 1)
    s = _norm01(np.maximum(s1, s2))
    big = wp._noise(n, 4, rng, 3)
    base = wp._rgb('#4e3626')
    alb = base[None, None, :] * (0.45 + 0.8 * s[..., None]) * (0.85 + 0.3 * big[..., None])
    return wp._save(alb, key), wp._save(wp._normal_from_height(s, 1.5), key + '_n'), tile


def tex_granite(key, n=512, tile=1.0, seed=91):
    rng = np.random.default_rng(seed)
    fine = rng.random((n, n)).astype(np.float32)
    mid = wp._noise(n, 30, rng, 2)
    big = wp._noise(n, 3, rng, 3)
    base = wp._rgb('#8e8c87')
    alb = base * (0.75 + 0.35 * fine[..., None]) * (0.9 + 0.15 * mid[..., None]) * (0.9 + 0.15 * big[..., None])
    alb = np.where((fine < 0.06)[..., None], alb * 0.45, alb)
    return wp._save(alb, key), wp._save(wp._normal_from_height(mid * 0.5 + fine * 0.1, 1.0), key + '_n'), tile


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
    brick = tex_flemish('dlx_brick')
    M['Brick'] = wp.mat('Brick', tex=brick, rough=0.86, normal_strength=0.9)
    M['BrickBase'] = wp.mat('BrickBase', '#c9b8ae', tex=brick, rough=0.9, normal_strength=0.9)
    M['BrickSoot'] = wp.mat('BrickSoot', '#9a8e88', tex=brick, rough=0.9, normal_strength=0.9)
    M['Trim'] = wp.mat('Trim', tex=tex_paint('dlx_trim', '#eeebe2'), rough=0.42)
    M['Shutter'] = wp.mat('Shutter', tex=tex_paint('dlx_shutter', '#1b1d1e', seed=12, amp=0.06), rough=0.38,
                          double_sided=True)
    M['Door'] = wp.mat('Door', tex=tex_paint('dlx_door', '#151a18', seed=13, amp=0.05), rough=0.25)
    M['Glass'] = wp.mat('Glass', '#ffffff', rough=0.03, tex=tex_glass('dlx_glass'))
    M['Slate'] = wp.mat('Slate', '#c8cbcf', tex=tex_slate('dlx_slate'), rough=0.6, normal_strength=1.0)
    M['Lead'] = wp.mat('Lead', '#4d5256', rough=0.5, metal=0.35)
    M['Copper'] = wp.mat('Copper', tex=tex_copper('dlx_copper'), rough=0.5, metal=0.55)
    M['Stone'] = wp.mat('Stone', tex=tex_stone('dlx_limestone', '#d6ccb8', seed=22, amp=0.06), rough=0.7)
    M['Bluestone'] = wp.mat('Bluestone', tex=tex_stone('dlx_bluestone', '#6f767b', seed=23, amp=0.09, cleft=0.4),
                            rough=0.75)
    M['Paver'] = wp.mat('Paver', tex=wp.tex_ground('dlx_paver', kind='pavers', color='#94513d', n=1024, tile=2.0,
                                                    seed=24), rough=0.85)
    M['Iron'] = wp.mat('Iron', '#141414', rough=0.45, metal=0.6)
    M['Brass'] = wp.mat('Brass', '#9c7a3c', rough=0.3, metal=0.9)
    M['Glow'] = wp.mat('Glow', '#ffd8a0', rough=0.4, emission=('#ffb45e', 4.5))
    M['Dark'] = wp.mat('Dark', '#0d0d0d', rough=0.9)
    M['Terracotta'] = wp.mat('Terracotta', tex=tex_stone('dlx_terracotta', '#9a5b42', seed=27, amp=0.1), rough=0.85)
    M['CastStone'] = wp.mat('CastStone', tex=tex_stone('dlx_caststone', '#bdb6a6', seed=25, amp=0.12), rough=0.85)
    # plants
    M['Boxwood'] = vc_material('Boxwood', tex_foliage('dlx_boxwood', '#47672b', n=512, tile=0.45, seed=55,
                                                       leaf=0.018, var=0.14, gap='#141c0c'), rough=0.7,
                                spec=0.28)
    M['Shrub'] = vc_material('Shrub', tex_foliage('dlx_shrub', '#3d5c2c', n=512, tile=0.7, seed=56, leaf=0.05,
                                                  var=0.15, gap='#121a0c'), rough=0.75, spec=0.25)
    M['Flowers'] = vc_material('Flowers', tex_foliage('dlx_flowers', '#4c6b30', n=512, tile=0.5, seed=53,
                                                        leaf=0.03, flowers='#e2587f', fcov=0.42), rough=0.65)
    M['FlowersW'] = vc_material('FlowersW', tex_foliage('dlx_flowersw', '#4c6b30', n=512, tile=0.5, seed=57,
                                                          leaf=0.03, flowers='#f3f0e8', fcov=0.45), rough=0.65)
    M['Leaves'] = vc_material('Leaves', tex_foliage('dlx_leaves', '#506b2b', n=1024, tile=1.6, seed=54, leaf=0.085,
                                                      var=0.2, gap='#1a230f'), rough=0.85, spec=0.22)
    M['LeafCards'] = card_material('LeafCards', *tex_leafcard('dlx_leafcard', '#56722d'))
    M['Bark'] = wp.mat('Bark', tex=tex_bark('dlx_bark'), rough=0.92)
    M['Mulch'] = wp.mat('Mulch', tex=tex_mulch('dlx_mulch', n=512), rough=0.95)
    M['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('dlx_asphalt', kind='asphalt', color='#606062', n=1024,
                                                        tile=4.0, seed=26), rough=0.88)
    M['Granite'] = wp.mat('Granite', tex=tex_granite('dlx_granite'), rough=0.8)
    MAT.update(M)
    return M


# ============================================================================ house parts
def shutter(g, F, u0, u1, z0, z1):
    """Black louvered shutter on the wall face: stiles, rails and raked louvers over a dark backing."""
    d0, d1 = 0.012, 0.042
    zm = z0 + (z1 - z0) * 0.52
    fbox(g, 'Shutter', F, u0, u0 + 0.05, z0, z1, d0, d1)
    fbox(g, 'Shutter', F, u1 - 0.05, u1, z0, z1, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, z0, z0 + 0.09, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, z1 - 0.065, z1, d0, d1)
    fbox(g, 'Shutter', F, u0 + 0.05, u1 - 0.05, zm - 0.04, zm + 0.04, d0, d1)
    poly(g, 'Shutter', [F.p(u0 + 0.05, z0, 0.016), F.p(u1 - 0.05, z0, 0.016), F.p(u1 - 0.05, z1, 0.016),
                        F.p(u0 + 0.05, z1, 0.016)], facing=F.N)
    for a, b in ((z0 + 0.09, zm - 0.04), (zm + 0.04, z1 - 0.065)):
        k = max(1, int((b - a) / 0.05))
        sp = (b - a) / k
        for i in range(k):
            zk = a + i * sp + 0.004
            poly(g, 'Shutter', [F.p(u0 + 0.05, zk, 0.038), F.p(u1 - 0.05, zk, 0.038),
                                F.p(u1 - 0.05, zk + 0.042, 0.017), F.p(u0 + 0.05, zk + 0.042, 0.017)],
                 facing=F.N + F.Z)


def stone_sill(g, F, u0, u1, z0, back=-0.07, horn=0.07, mat='Stone'):
    uextrude(g, mat, F, [(back, z0 - 0.11), (0.055, z0 - 0.11), (0.055, z0 - 0.035), (back, z0)],
             u0 - horn, u1 + horn)


def jack_lintel(g, F, u0, u1, z1, hgt=0.26, mat='Stone'):
    uc = (u0 + u1) / 2
    extrude(g, mat, F, [(u0 - 0.05, z1), (u1 + 0.05, z1), (u1 + 0.17, z1 + hgt), (u0 - 0.17, z1 + hgt)],
            0.0, 0.018)
    extrude(g, mat, F, [(uc - 0.085, z1 - 0.03), (uc + 0.085, z1 - 0.03), (uc + 0.115, z1 + hgt + 0.04),
                            (uc - 0.115, z1 + hgt + 0.04)], 0.0, 0.035)


def archivolt(g, F, uc, zs, r, band=0.13, n=16, mat='Stone'):
    outer = arc(uc, zs, r + band, 0, 180, n)
    inner = arc(uc, zs, r, 180, 0, n)
    extrude(g, mat, F, outer + inner, 0.0, 0.02)
    # impost blocks and keystone
    for s in (-1, 1):
        a = uc + s * r
        b = uc + s * (r + band + 0.03)
        fbox(g, mat, F, min(a, b), max(a, b), zs - 0.09, zs, 0.0, 0.025)
    k = [(uc - 0.075, zs + r - 0.03), (uc + 0.075, zs + r - 0.03), (uc + 0.11, zs + r + band + 0.08),
         (uc - 0.11, zs + r + band + 0.08)]
    extrude(g, mat, F, k, 0.0, 0.04)


def sash_pair(g, F, su0, su1, sz0, sz1, cols=3, rows=2, d_front=-0.075):
    """Two sashes of a double-hung window (upper outside, lower inside) with muntins and glass."""
    zm = (sz0 + sz1) / 2
    for (zb, zt, da, db, gd, bot, top) in ((zm - 0.018, sz1, d_front - 0.035, d_front, d_front - 0.02, 0.035, 0.05),
                                           (sz0, zm + 0.018, d_front - 0.075, d_front - 0.04, d_front - 0.06, 0.075,
                                            0.035)):
        fbox(g, 'Trim', F, su0, su0 + 0.05, zb, zt, da, db)
        fbox(g, 'Trim', F, su1 - 0.05, su1, zb, zt, da, db)
        fbox(g, 'Trim', F, su0 + 0.05, su1 - 0.05, zb, zb + bot, da, db)
        fbox(g, 'Trim', F, su0 + 0.05, su1 - 0.05, zt - top, zt, da, db)
        iu0, iu1, iz0, iz1 = su0 + 0.05, su1 - 0.05, zb + bot, zt - top
        poly(g, 'Glass', [F.p(iu0, iz0, gd), F.p(iu1, iz0, gd), F.p(iu1, iz1, gd), F.p(iu0, iz1, gd)], facing=F.N)
        for i in range(1, cols):
            uu = iu0 + (iu1 - iu0) * i / cols
            fbox(g, 'Trim', F, uu - 0.011, uu + 0.011, iz0, iz1, da + 0.005, db - 0.004)
        for j in range(1, rows):
            zz = iz0 + (iz1 - iz0) * j / rows
            fbox(g, 'Trim', F, iu0, iu1, zz - 0.011, zz + 0.011, da + 0.005, db - 0.004)


def fanlight(g, F, uc, zs, r, d=-0.12, spokes=5, frame=0.06):
    """Semicircular fanlight: arched frame, sunburst muntins, hub, glass."""
    outer = arc(uc, zs, r, 0, 180, 18)
    inner = arc(uc, zs, r - frame, 180, 0, 18)
    extrude(g, 'Trim', F, outer + inner, d - 0.06, -0.07)
    gl = arc(uc, zs, r - frame + 0.005, 0, 180, 18)
    fill(g, 'Glass', F, gl, d=d - 0.02)
    hub = arc(uc, zs, 0.11, 0, 180, 8)
    extrude(g, 'Trim', F, hub, d - 0.05, d + 0.005)
    for k in range(1, spokes + 1):
        a = math.radians(180 * k / (spokes + 1))
        p0 = Vector((uc + 0.11 * math.cos(a), zs + 0.11 * math.sin(a)))
        p1 = Vector((uc + (r - frame) * math.cos(a), zs + (r - frame) * math.sin(a)))
        nrm = Vector((-math.sin(a), math.cos(a))) * 0.011
        extrude(g, 'Trim', F, [tuple(p0 - nrm), tuple(p1 - nrm), tuple(p1 + nrm), tuple(p0 + nrm)], d - 0.045, d)
    # spring-line transom bar
    fbox(g, 'Trim', F, uc - r, uc + r, zs - 0.035, zs + 0.03, d - 0.06, -0.07)


def window(gW, gT, F, uc, z0, w, h, arch=False, shutters=True, lintel=True, cols=3, rows=2, reveal_mat='Brick',
           shut_h=None, sill_mat='Stone', lintel_mat='Stone', RD=0.075):
    """A 6-over-6 (default) double-hung window set in a masonry opening. Returns the hole polygon.
    z0 = top of the stone sill; h = height of the rectangular part (to the head, or to the arch spring)."""
    u0, u1 = uc - w / 2, uc + w / 2
    z1 = z0 + h
    hole = arch_poly(u0, u1, z0, z1) if arch else rect(u0, u1, z0, z1)
    bm = 0.065
    reveal(gW, reveal_mat, F, hole, RD)
    # brickmould (frame) at the back of the reveal
    fbox(gT, 'Trim', F, u0, u0 + bm, z0, z1, -0.19, -RD)
    fbox(gT, 'Trim', F, u1 - bm, u1, z0, z1, -0.19, -RD)
    if arch:
        r = w / 2
        fanlight(gT, F, uc, z1, r, d=-0.12, frame=bm)
        top = z1 - 0.035
    else:
        fbox(gT, 'Trim', F, u0, u1, z1 - bm, z1, -0.19, -RD)
        top = z1 - bm
    fbox(gT, 'Trim', F, u0 + bm, u1 - bm, z0, z0 + 0.035, -0.2, -RD + 0.005)
    sash_pair(gT, F, u0 + bm, u1 - bm, z0 + 0.035, top, cols, rows, d_front=-0.085)
    if sill_mat:
        stone_sill(gT, F, u0, u1, z0, back=-RD, mat=sill_mat)
    if lintel:
        if arch:
            archivolt(gT, F, uc, z1, w / 2, mat=lintel_mat)
        else:
            jack_lintel(gT, F, u0, u1, z1, mat=lintel_mat)
    if shutters:
        sw = w / 2 + 0.01
        sh = z1 if shut_h is None else z0 + shut_h
        shutter(gT, F, u0 - 0.025 - sw, u0 - 0.025, z0 + 0.012, sh)
        shutter(gT, F, u1 + 0.025, u1 + 0.025 + sw, z0 + 0.012, sh)
    return hole


def french_door(gW, gT, F, uc, z0, w, h, arch=False, reveal_mat='Brick', shutters=True, lintel_mat='Stone'):
    """Pair of glazed (10-lite) doors with an optional fanlight, in a masonry opening; returns the hole."""
    u0, u1 = uc - w / 2, uc + w / 2
    z1 = z0 + h
    hole = arch_poly(u0, u1, z0, z1) if arch else rect(u0, u1, z0, z1)
    RD, bm = 0.10, 0.065
    reveal(gW, reveal_mat, F, hole, RD)
    fbox(gT, 'Trim', F, u0, u0 + bm, z0, z1, -0.2, -RD)
    fbox(gT, 'Trim', F, u1 - bm, u1, z0, z1, -0.2, -RD)
    if arch:
        fanlight(gT, F, uc, z1, w / 2, d=-0.14, frame=bm)
        top = z1 - 0.035
    else:
        fbox(gT, 'Trim', F, u0, u1, z1 - bm, z1, -0.2, -RD)
        top = z1 - bm
    fbox(gT, 'Stone', F, u0 - 0.02, u1 + 0.02, z0 - 0.06, z0 + 0.02, -0.22, 0.04)
    dd = -0.15
    for a, b in ((u0 + bm, uc), (uc, u1 - bm)):
        fbox(gT, 'Trim', F, a, a + 0.06, z0 + 0.02, top, dd - 0.04, dd)
        fbox(gT, 'Trim', F, b - 0.06, b, z0 + 0.02, top, dd - 0.04, dd)
        fbox(gT, 'Trim', F, a + 0.06, b - 0.06, z0 + 0.02, z0 + 0.42, dd - 0.04, dd)
        fbox(gT, 'Trim', F, a + 0.06, b - 0.06, top - 0.06, top, dd - 0.04, dd)
        fbox(gT, 'Trim', F, a + 0.12, b - 0.12, z0 + 0.1, z0 + 0.34, dd, dd + 0.012)
        iu0, iu1, iz0, iz1 = a + 0.06, b - 0.06, z0 + 0.42, top - 0.06
        poly(gT, 'Glass', [F.p(iu0, iz0, dd - 0.02), F.p(iu1, iz0, dd - 0.02), F.p(iu1, iz1, dd - 0.02),
                           F.p(iu0, iz1, dd - 0.02)], facing=F.N)
        fbox(gT, 'Trim', F, (iu0 + iu1) / 2 - 0.011, (iu0 + iu1) / 2 + 0.011, iz0, iz1, dd - 0.035, dd - 0.004)
        for j in range(1, 5):
            zz = iz0 + (iz1 - iz0) * j / 5
            fbox(gT, 'Trim', F, iu0, iu1, zz - 0.011, zz + 0.011, dd - 0.035, dd - 0.004)
    fbox(gT, 'Brass', F, uc - 0.09, uc - 0.07, z0 + 1.0, z0 + 1.14, dd, dd + 0.05)
    if lintel_mat:
        if arch:
            archivolt(gT, F, uc, z1, w / 2, mat=lintel_mat)
        else:
            jack_lintel(gT, F, u0, u1, z1, mat=lintel_mat)
    if shutters:
        sw = w / 2 + 0.01
        shutter(gT, F, u0 - 0.025 - sw, u0 - 0.025, z0 + 0.03, z1)
        shutter(gT, F, u1 + 0.025, u1 + 0.025 + sw, z0 + 0.03, z1)
    return hole


def downspout(g, x, y, z_top, n_out, z_bot=0.0):
    """Round aged-copper downspout with a leader head, straps and a splash block shoe."""
    n_out = Vector(n_out).normalized()
    off = 0.09
    cx, cy = x + n_out.x * off, y + n_out.y * off
    lathe(g, 'Copper', [(0.038, z_bot + 0.25), (0.038, z_top - 0.45)], cx, cy, seg=10, caps=False)
    tube(g, 'Copper', [(cx, cy, z_bot + 0.26), (cx + n_out.x * 0.12, cy + n_out.y * 0.12, z_bot + 0.08),
                       (cx + n_out.x * 0.32, cy + n_out.y * 0.32, z_bot + 0.05)], [0.038, 0.038, 0.04], seg=10)
    # leader head + gooseneck into the cornice
    hb = Vector((cx, cy, z_top - 0.45))
    cbox(g, 'Copper', hb.x, hb.y, 0.24 if abs(n_out.x) < 0.5 else 0.18, 0.18 if abs(n_out.x) < 0.5 else 0.24,
         z_top - 0.45, z_top - 0.18)
    for zz in np.arange(z_bot + 0.6, z_top - 0.6, 1.8):
        cbox(g, 'Copper', cx - n_out.x * 0.04, cy - n_out.y * 0.04, 0.10 if abs(n_out.x) < 0.5 else 0.14,
             0.14 if abs(n_out.x) < 0.5 else 0.10, zz, zz + 0.03)


# ---------------------------------------------------------------------------- roofs
def clip_half(P, a, b, c):
    """Keep the part of convex polygon P (list of (x, y)) where a*x + b*y + c <= 0."""
    out = []
    n = len(P)
    for i in range(n):
        p, q = P[i], P[(i + 1) % n]
        fp, fq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if fp <= 1e-9:
            out.append(p)
        if (fp < -1e-9 and fq > 1e-9) or (fp > 1e-9 and fq < -1e-9):
            t = fp / (fp - fq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def plane_eave(x0, x1, y0, y1, side, ze, t):
    """Roof plane z = A x + B y + C rising from the eave on `side` of the rectangle."""
    if side == 'front':
        return (0.0, t, ze - t * y0)
    if side == 'back':
        return (0.0, -t, ze + t * y1)
    if side == 'left':
        return (t, 0.0, ze - t * x0)
    return (-t, 0.0, ze + t * x1)


def roof_faces(x0, x1, y0, y1, planes):
    """Faces of a roof over a rectangle given its planes {name: (A, B, C)}: each face is the region where its
    plane is the lowest. Returns a list of 3D polygons (counter-clockwise from above)."""
    out = []
    R = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for k, (A, B, C) in planes.items():
        P = R
        for j, (A2, B2, C2) in planes.items():
            if j == k:
                continue
            P = clip_half(P, A - A2, B - B2, C - C2)
            if len(P) < 3:
                break
        if len(P) >= 3 and abs(area2(P)) > 1e-6:
            out.append([Vector((x, y, A * x + B * y + C)) for x, y in P])
    return out


def face_uv(pts):
    n = newell(pts).normalized()
    if abs(n.z) > 0.999:
        U, V = Vector((1, 0, 0)), Vector((0, 1, 0))
    else:
        U = Vector((0, 0, 1)).cross(n).normalized()
        V = n.cross(U)
    return [(p.dot(U), p.dot(V)) for p in pts], n


def roof_slab(g, faces, th=TH, top='Slate', bottom='Trim', edge='Slate', skip_edges=()):
    """Thick roof from its top faces: slate top (UVs along the slope), underside, edge faces on the outline."""
    key = lambda p: (round(p.x, 3), round(p.y, 3), round(p.z, 3))
    cnt = {}
    for f in faces:
        for i in range(len(f)):
            e = tuple(sorted((key(f[i]), key(f[(i + 1) % len(f)]))))
            cnt[e] = cnt.get(e, 0) + 1
    for f in faces:
        uv, n = face_uv(f)
        if n.z < 0:
            n = -n
        loops = [Vector((u, v, 0)) for u, v in uv]
        tris = tessellate_polygon([loops]) if len(f) > 4 else [tuple(range(len(f)))]
        for t in tris:
            pts = [f[i] for i in t]
            uvs = [uv[i] for i in t]
            poly(g, top, pts, facing=n, uv=uvs)
            poly(g, bottom, [p - n * th for p in pts], facing=-n)
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            e = tuple(sorted((key(a), key(b))))
            if cnt[e] > 1:
                continue
            if any(skip(a, b) for skip in skip_edges):
                continue
            outv = (b - a).cross(n)
            poly(g, edge, [a, b, b - n * th, a - n * th], facing=outv)


def ridge_caps(g, faces, w=0.11, lift=0.035, mat='Lead', skip=()):
    """Lead caps over every convex shared edge (ridges and hips) of a roof made of `faces`."""
    key = lambda p: (round(p.x, 3), round(p.y, 3), round(p.z, 3))
    edges = {}
    for fi, f in enumerate(faces):
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            e = tuple(sorted((key(a), key(b))))
            edges.setdefault(e, []).append((fi, a, b))
    for e, lst in edges.items():
        if len(lst) != 2:
            continue
        (f1, a, b), (f2, _, _) = lst
        if any(s(a, b) for s in skip):
            continue
        n1 = newell(faces[f1]).normalized()
        n2 = newell(faces[f2]).normalized()
        c2 = sum(faces[f2], Vector()) / len(faces[f2])
        if (c2 - a).dot(n1) > -1e-4:
            continue               # valley, not a ridge/hip
        ed = (b - a).normalized()
        nav = (n1 + n2).normalized()
        V = []
        for fi, nn in ((f1, n1), (f2, n2)):
            cc = sum(faces[fi], Vector()) / len(faces[fi])
            s = nn.cross(ed).normalized()
            if (cc - a).dot(s) < 0:
                s = -s
            V.append((s, nn))
        top_a, top_b = a + nav * lift, b + nav * lift
        for s, nn in V:
            sa, sb = a + s * w + nn * 0.012, b + s * w + nn * 0.012
            poly(g, mat, [top_a, top_b, sb, sa], facing=nn + nav)
            poly(g, mat, [sa, sb, sb - nn * 0.02, sa - nn * 0.02], facing=s)


def valley_strip(g, a, b, n_avg, w=0.09):
    a, b = Vector(a), Vector(b)
    ed = (b - a).normalized()
    s = Vector(n_avg).normalized().cross(ed).normalized()
    lift = Vector(n_avg).normalized() * 0.006
    poly(g, 'Copper', [a - s * w + lift, b - s * w + lift, b + s * w + lift, a + s * w + lift], facing=n_avg)


# ============================================================================ house
# Cornice profiles (d out from the wall face, z up), traversed with the solid on the left.
MAIN_CORNICE = [(0, -0.38), (0.025, -0.38), (0.025, -0.16), (0.05, -0.14), (0.05, -0.02), (0.14, 0.0),
                (0.58, 0.0), (0.58, 0.16), (0.61, 0.18), (0.63, 0.22), (0.65, 0.27), (0.65, 0.29), (0.0, 0.29)]
HC = 0.29
RAKE = [(0, 0), (0.58, 0), (0.58, 0.16), (0.61, 0.18), (0.63, 0.22), (0.65, 0.27), (0.65, 0.29), (0, 0.29)]
SMALL_CORNICE = [(0, -0.18), (0.02, -0.18), (0.02, -0.03), (0.06, 0.0), (0.30, 0.0), (0.30, 0.14), (0.32, 0.16),
                 (0.34, 0.20), (0.34, 0.22), (0, 0.22)]
HCS = 0.22
SMALL_RAKE = [(0, 0), (0.30, 0), (0.30, 0.14), (0.32, 0.16), (0.34, 0.20), (0.34, 0.22), (0, 0.22)]
BASE = [(0, -0.6), (0.05, -0.6), (0.05, 0.40), (0.075, 0.40), (0.075, 0.45), (0.0, WTAB)]
BASE_MATS = ['BrickBase', 'BrickBase', 'Stone', 'Stone', 'Stone']
LANTERNS = []          # (position, kind) for the render's warm lights


def shift(prof, dz):
    return [(d, h + dz) for d, h in prof]


def convex_at(P, k, closed):
    n = len(P)
    if not closed and (k == 0 or k == n - 1):
        return None
    a, b, c = P[(k - 1) % n], P[k], P[(k + 1) % n]
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) > 0


def dentils(g, path, z0, z1, d0, d1, w=0.065, pitch=0.13, closed=False):
    n = len(path)
    nseg = n if closed else n - 1
    for s in range(nseg):
        a, b = path[s], path[(s + 1) % n]
        F, L = wallF(a, b)
        m = []
        for k in (s, (s + 1) % n):
            c = convex_at(path, k, closed)
            m.append(0.06 if c is None else (0.03 if c else d1 + 0.012))
        u0, u1 = m[0], L - m[1]
        if u1 - u0 < w:
            continue
        cnt = int((u1 - u0 - w) / pitch) + 1
        span = (cnt - 1) * pitch
        st = (u0 + u1) / 2 - span / 2
        for i in range(cnt):
            u = st + i * pitch
            fbox(g, 'Trim', F, u - w / 2, u + w / 2, z0, z1, d0, d1)


def base_run(g, path, closed=False):
    sweep(g, BASE_MATS, path, BASE, closed=closed, caps=(False, False))


def tuscan(g, x, y, z0, z1, r=0.16):
    """Tuscan column: square plinth, torus base, shaft with entasis, astragal, echinus, square abacus."""
    H = z1 - z0
    sq = r * 2.55
    cbox(g, 'Trim', x, y, sq, sq, z0, z0 + 0.09)
    rt = r * 0.84
    prof = [(r * 1.24, 0.09), (r * 1.28, 0.12), (r * 1.24, 0.155), (r * 1.08, 0.17), (r * 1.04, 0.19), (r, 0.21)]
    zs = np.linspace(0.21, H - 0.27, 9)
    for z in zs[1:]:
        t = (z - 0.21) / (H - 0.48)
        prof.append((r if t < 0.33 else r * (1 - 0.16 * ((t - 0.33) / 0.67) ** 1.4), z))
    prof += [(rt * 1.1, H - 0.255), (rt * 1.1, H - 0.225), (rt, H - 0.21), (rt, H - 0.17), (rt * 1.07, H - 0.16),
             (rt * 1.32, H - 0.10), (rt * 1.32, H - 0.095)]
    lathe(g, 'Trim', prof, x, y, seg=18, z0=z0, caps=False)
    cbox(g, 'Trim', x, y, sq * 0.98, sq * 0.98, z1 - 0.095, z1)


BAL_PROF = [(0.42, 0.0), (0.42, 0.06), (0.30, 0.085), (0.30, 0.12), (0.37, 0.16), (0.50, 0.29), (0.53, 0.36),
            (0.47, 0.46), (0.28, 0.62), (0.20, 0.71), (0.25, 0.79), (0.31, 0.84), (0.31, 0.89), (0.42, 0.93),
            (0.42, 1.0)]


def baluster(g, x, y, z0, h, w=0.13):
    lathe(g, 'Trim', [(r * w, z * h) for r, z in BAL_PROF], x, y, seg=10, z0=z0, caps=False)


def balustrade(g, p0, p1, zb, top, pitch=0.155, w=0.13):
    """Rails and vase balusters from p0 to p1 (plan points), resting on z = zb, handrail top at `top`."""
    p0, p1 = Vector((p0[0], p0[1], 0)), Vector((p1[0], p1[1], 0))
    L = (p1 - p0).length
    seg_box(g, 'Trim', (p0.x, p0.y, zb + 0.06), (p1.x, p1.y, zb + 0.06), 0.20, 0.12)
    seg_box(g, 'Trim', (p0.x, p0.y, top - 0.10), (p1.x, p1.y, top - 0.10), 0.16, 0.06)
    seg_box(g, 'Trim', (p0.x, p0.y, top - 0.035), (p1.x, p1.y, top - 0.035), 0.20, 0.07)
    n = max(1, int((L - 0.1) / pitch))
    for i in range(n):
        t = (i + 0.5) / n
        q = p0 + (p1 - p0) * t
        baluster(g, q.x, q.y, zb + 0.12, top - 0.13 - (zb + 0.12), w)


def pedestal(g, x, y, z0, z1, s=0.30):
    cbox(g, 'Trim', x, y, s + 0.04, s + 0.04, z0, z0 + 0.12)
    cbox(g, 'Trim', x, y, s, s, z0 + 0.12, z1 - 0.10)
    cbox(g, 'Trim', x, y, s + 0.05, s + 0.05, z1 - 0.10, z1 - 0.04)
    cbox(g, 'Trim', x, y, s + 0.07, s + 0.07, z1 - 0.04, z1)


def wall_lantern(g, F, u, zc, arm=0.17):
    """Black carriage lantern on a wall bracket; glowing glass core."""
    fbox(g, 'Iron', F, u - 0.06, u + 0.06, zc - 0.34, zc - 0.02, 0.0, 0.02)
    fbox(g, 'Iron', F, u - 0.015, u + 0.015, zc - 0.27, zc - 0.24, 0.02, arm + 0.03)
    dc, s = arm + 0.12, 0.105
    fbox(g, 'Iron', F, u - s - 0.012, u + s + 0.012, zc - 0.33, zc - 0.29, dc - s - 0.012, dc + s + 0.012)
    fbox(g, 'Glow', F, u - s + 0.008, u + s - 0.008, zc - 0.29, zc + 0.06, dc - s + 0.008, dc + s - 0.008)
    for su in (-1, 1):
        for sd in (-1, 1):
            fbox(g, 'Iron', F, u + su * s - 0.012, u + su * s + 0.012, zc - 0.29, zc + 0.06, dc + sd * s - 0.012,
                 dc + sd * s + 0.012)
    fbox(g, 'Iron', F, u - s - 0.02, u + s + 0.02, zc + 0.06, zc + 0.09, dc - s - 0.02, dc + s + 0.02)
    apex = F.p(u, zc + 0.24, dc)
    ring = [F.p(u - s - 0.02, zc + 0.09, dc - s - 0.02), F.p(u + s + 0.02, zc + 0.09, dc - s - 0.02),
            F.p(u + s + 0.02, zc + 0.09, dc + s + 0.02), F.p(u - s - 0.02, zc + 0.09, dc + s + 0.02)]
    for i in range(4):
        a, b = ring[i], ring[(i + 1) % 4]
        poly(g, 'Iron', [a, b, apex], facing=((a + b) / 2 - F.p(u, zc + 0.09, dc)) + F.Z * 0.3)
    fbox(g, 'Iron', F, u - 0.012, u + 0.012, zc + 0.22, zc + 0.30, dc - 0.012, dc + 0.012)
    LANTERNS.append((F.p(u, zc - 0.11, dc), 'wall'))


def pendant_lantern(g, x, y, z_ceil, z_bot):
    s = 0.15
    zt = z_bot + 0.55
    cbox(g, 'Iron', x, y, 0.025, 0.025, zt + 0.12, z_ceil)
    cbox(g, 'Iron', x, y, 0.16, 0.16, z_ceil - 0.03, z_ceil)
    cbox(g, 'Iron', x, y, 2 * s + 0.04, 2 * s + 0.04, z_bot, z_bot + 0.05)
    cbox(g, 'Glow', x, y, 2 * s - 0.02, 2 * s - 0.02, z_bot + 0.05, zt)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cbox(g, 'Iron', x + sx * s, y + sy * s, 0.025, 0.025, z_bot + 0.05, zt)
    cbox(g, 'Iron', x, y, 2 * s + 0.06, 2 * s + 0.06, zt, zt + 0.04)
    lathe(g, 'Iron', [(s + 0.03, 0.0), (0.04, 0.12)], x, y, seg=4, z0=zt + 0.04, caps=False, smooth=False)
    LANTERNS.append((Vector((x, y, z_bot + 0.3)), 'pendant'))


def urn(g, x, y, z0, scale=1.0, plant='Boxwood', seed=1):
    """Cast-stone urn on a square foot, planted."""
    s = scale
    cbox(g, 'CastStone', x, y, 0.36 * s, 0.36 * s, z0, z0 + 0.08 * s)
    prof = [(0.10, 0.08), (0.08, 0.14), (0.09, 0.18), (0.13, 0.22), (0.20, 0.30), (0.26, 0.42), (0.28, 0.52),
            (0.30, 0.56), (0.31, 0.60), (0.27, 0.60), (0.25, 0.58)]
    lathe(g, 'CastStone', [(r * s, z * s) for r, z in prof], x, y, seg=16, z0=z0, caps=False)
    poly(g, 'Mulch', [(x + 0.25 * s * math.cos(2 * math.pi * i / 12), y + 0.25 * s * math.sin(2 * math.pi * i / 12),
                       z0 + 0.57 * s) for i in range(12)], facing=(0, 0, 1))
    rng = np.random.default_rng(seed)

    def colfn(q, d):
        a = 0.55 + 0.45 * min(1.0, max(0.0, (d.z + 0.6) / 1.4))
        return (a, a, a)
    if plant == 'Boxwood':
        blob(g, 'Boxwood', (x, y, z0 + 0.82 * s), (0.30 * s, 0.30 * s, 0.30 * s), seed, rough=0.12, freq=2.5, sub=2,
             colfn=colfn)
    else:
        for i in range(5):
            a = 2 * math.pi * i / 5 + rng.uniform(-0.3, 0.3)
            blob(g, plant, (x + math.cos(a) * 0.14 * s, y + math.sin(a) * 0.14 * s, z0 + 0.66 * s),
                 (0.17 * s, 0.17 * s, 0.13 * s), seed + i, rough=0.25, freq=3.0, sub=2, colfn=colfn)
        blob(g, 'Shrub', (x, y, z0 + 0.78 * s), (0.16 * s, 0.16 * s, 0.22 * s), seed + 9, rough=0.3, freq=3.0, sub=2,
             colfn=colfn)


def chimney(gW, gT, cx, cy, sx, sy, z0, ztop, pots=2):
    """Brick stack with three corbelled courses, a soot-darkened head, limestone cap and clay flue pots."""
    zc = ztop - 0.62
    box(gW, 'Brick', cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, zc - 0.55)
    box(gW, 'BrickSoot', cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, zc - 0.55, zc)
    # recessed panel band
    for k, e in enumerate((0.035, 0.07, 0.105)):
        za = zc + k * 0.075
        box(gW, 'BrickSoot', cx - sx / 2 - e, cx + sx / 2 + e, cy - sy / 2 - e, cy + sy / 2 + e, za, za + 0.075)
    e = 0.105
    box(gW, 'BrickSoot', cx - sx / 2 - e + 0.035, cx + sx / 2 + e - 0.035, cy - sy / 2 - e + 0.035,
        cy + sy / 2 + e - 0.035, zc + 0.225, ztop - 0.10)
    box(gT, 'Stone', cx - sx / 2 - 0.15, cx + sx / 2 + 0.15, cy - sy / 2 - 0.15, cy + sy / 2 + 0.15, ztop - 0.10, ztop)
    for i in range(pots):
        px = cx + (i - (pots - 1) / 2) * (sx / pots)
        lathe(gT, 'Terracotta', [(0.15, 0.0), (0.14, 0.05), (0.12, 0.08), (0.12, 0.40), (0.135, 0.43), (0.135, 0.47),
                                 (0.10, 0.47), (0.10, 0.30)], px, cy, seg=12, z0=ztop, caps=False)


def gable_rake(g, y_plane, xa, xb, xc, zrs_fn, prof, outward, end_x=None):
    """Raking cornice up and down a gable in the vertical plane y = y_plane (outward = -1 for a front gable)."""
    pts = [Vector((xa, y_plane, zrs_fn(xa))), Vector((xc, y_plane, zrs_fn(xc))), Vector((xb, y_plane, zrs_fn(xb)))]
    out = Vector((0, outward, 0))
    ups = []
    for a, b in zip(pts, pts[1:]):
        dd = (b - a).normalized()
        up = Vector((0, 0, 1)) - dd * dd.z
        ups.append(up.normalized())
    ex0 = end_x[0] if end_x else xa
    ex1 = end_x[1] if end_x else xb
    sweep(g, 'Trim', pts, prof, outs=[out, out], ups=ups,
          end_planes=((Vector((ex0, 0, 0)), Vector((1, 0, 0))), (Vector((ex1, 0, 0)), Vector((1, 0, 0)))))


def entry(gT, F, uc):
    """Front entry: panelled reveal, six-panel door, sidelights and transom, pilastered surround."""
    u0, u1, z0, z1 = uc - 1.15, uc + 1.15, FF1, 3.20
    hole = rect(u0, u1, z0, z1)
    D = -0.28
    reveal(gT, 'Trim', F, hole, -D)
    fbox(gT, 'Stone', F, u0, u1, z0 - 0.04, z0 + 0.02, D - 0.02, 0.05)
    for a, b in ((u0, u0 + 0.08), (u1 - 0.08, u1), (uc - 0.58, uc - 0.50), (uc + 0.50, uc + 0.58)):
        fbox(gT, 'Trim', F, a, b, z0, z1, D - 0.06, D + 0.04)
    fbox(gT, 'Trim', F, u0, u1, 2.86, 2.94, D - 0.06, D + 0.04)
    fbox(gT, 'Trim', F, u0, u1, z1 - 0.07, z1, D - 0.06, D + 0.04)
    du0, du1 = uc - 0.50, uc + 0.50
    fbox(gT, 'Door', F, du0, du1, z0 + 0.01, 2.86, D - 0.05, D - 0.01)
    for col_ in (0, 1):
        pu0 = du0 + 0.09 + col_ * 0.43
        pu1 = pu0 + 0.39
        for (pz0, pz1) in ((z0 + 0.14, z0 + 0.74), (z0 + 0.88, z0 + 1.52), (z0 + 1.66, 2.74)):
            fbox(gT, 'Door', F, pu0, pu1, pz0, pz1, D - 0.01, D + 0.004)
            fbox(gT, 'Door', F, pu0 + 0.05, pu1 - 0.05, pz0 + 0.05, pz1 - 0.05, D + 0.004, D + 0.016)
    fbox(gT, 'Brass', F, du1 - 0.13, du1 - 0.07, z0 + 0.97, z0 + 1.05, D, D + 0.07)
    fbox(gT, 'Brass', F, uc - 0.06, uc + 0.06, 2.08, 2.22, D + 0.004, D + 0.035)
    fbox(gT, 'Brass', F, du0 + 0.05, du1 - 0.05, z0 + 0.02, z0 + 0.14, D - 0.01, D + 0.003)
    for (a, b) in ((u0 + 0.08, uc - 0.58), (uc + 0.58, u1 - 0.08)):
        fbox(gT, 'Door', F, a, b, z0, z0 + 0.55, D - 0.05, D - 0.01)
        fbox(gT, 'Door', F, a + 0.06, b - 0.06, z0 + 0.08, z0 + 0.47, D - 0.01, D + 0.005)
        poly(gT, 'Glass', [F.p(a, z0 + 0.55, D - 0.03), F.p(b, z0 + 0.55, D - 0.03), F.p(b, 2.86, D - 0.03),
                           F.p(a, 2.86, D - 0.03)], facing=F.N)
        fbox(gT, 'Trim', F, (a + b) / 2 - 0.011, (a + b) / 2 + 0.011, z0 + 0.55, 2.86, D - 0.03, D - 0.005)
        for j in range(1, 5):
            zz = z0 + 0.55 + (2.86 - z0 - 0.55) * j / 5
            fbox(gT, 'Trim', F, a, b, zz - 0.011, zz + 0.011, D - 0.03, D - 0.005)
    poly(gT, 'Glass', [F.p(u0 + 0.08, 2.94, D - 0.03), F.p(u1 - 0.08, 2.94, D - 0.03), F.p(u1 - 0.08, z1 - 0.07, D - 0.03),
                       F.p(u0 + 0.08, z1 - 0.07, D - 0.03)], facing=F.N)
    for i in range(1, 10):
        uu = u0 + 0.08 + (u1 - u0 - 0.16) * i / 10
        fbox(gT, 'Trim', F, uu - 0.011, uu + 0.011, 2.94, z1 - 0.07, D - 0.03, D - 0.005)
    # surround: pilasters, frieze and cornice
    for a, b in ((u0 - 0.18, u0), (u1, u1 + 0.18)):
        fbox(gT, 'Trim', F, a, b, z0, z1, 0.0, 0.05)
        fbox(gT, 'Trim', F, a - 0.015, b + 0.015, z0, z0 + 0.26, 0.0, 0.065)
        fbox(gT, 'Trim', F, a - 0.01, b + 0.01, z1 - 0.14, z1 - 0.10, 0.0, 0.065)
    fbox(gT, 'Trim', F, u0 - 0.22, u1 + 0.22, z1, z1 + 0.18, 0.0, 0.045)
    uextrude(gT, 'Trim', F, [(0, z1 + 0.18), (0.07, z1 + 0.18), (0.13, z1 + 0.24), (0.13, z1 + 0.28), (0, z1 + 0.28)],
             u0 - 0.30, u1 + 0.30)
    return hole


# ---------------------------------------------------------------------------- main block
def main_path():
    return [(MX0, MY0), (-PX, MY0), (-PX, PY0), (PX, PY0), (PX, MY0), (MX1, MY0), (MX1, MY1), (MX0, MY1)]


def z_rs_ped(x):
    """Pediment rake soffit line on the tympanum plane."""
    return ZE + (PXO - abs(x)) * PT - (TH + HC) / math.cos(math.radians(PED_P))


def pavilion_front(gW, gT, F, L):
    uc = L / 2
    r, zs = 0.8, 7.10
    hole_e = entry(gT, F, uc)
    for s in (-1, 1):
        wall_lantern(gT, F, uc + s * 1.78, 2.62)
    side_holes = []
    for s in (-1, 1):
        cu = uc + s * 1.25
        side_holes.append(window(gW, gT, F, cu, 4.55, 0.5, 1.90, shutters=False, lintel=False, cols=2, rows=3,
                                 sill_mat='Trim'))
    zb = FF2 + 0.05
    outline = [(0, WTAB), (L, WTAB), (L, SOF), (uc + r, SOF), (uc + r, zb), (uc - r, zb), (uc - r, SOF), (0, SOF)]
    fill(gW, 'Brick', F, outline, [hole_e] + side_holes)
    french_door(gW, gT, F, uc, zb, 2 * r, zs - zb, arch=True, reveal_mat='Trim', shutters=False, lintel_mat='Trim')
    # Palladian frame: inner pilasters up to the soffit, outer pilasters, entablatures over the sidelights
    for s in (-1, 1):
        a, b = sorted((uc + s * 0.8, uc + s * 1.0))
        fbox(gT, 'Trim', F, a, b, zb, SOF, 0.0, 0.035)
        fbox(gT, 'Trim', F, a - 0.01, b + 0.01, zb, zb + 0.2, 0.0, 0.045)
        fbox(gT, 'Trim', F, a - 0.015, b + 0.015, SOF - 0.13, SOF - 0.09, 0.0, 0.05)
        a2, b2 = sorted((uc + s * 1.5, uc + s * 1.68))
        fbox(gT, 'Trim', F, a2, b2, zb, 6.45, 0.0, 0.035)
        fbox(gT, 'Trim', F, a2 - 0.01, b2 + 0.01, zb, zb + 0.2, 0.0, 0.045)
        a3, b3 = sorted((uc + s * 1.0, uc + s * 1.72))
        fbox(gT, 'Trim', F, a3, b3, 6.45, 6.62, 0.0, 0.03)
        uextrude(gT, 'Trim', F, [(0, 6.62), (0.05, 6.62), (0.08, 6.66), (0.08, 6.72), (0, 6.72)], a3, b3)
    # corner pilasters (front, with a return on the pavilion sides)
    for a, b in ((-0.045, 0.40), (L - 0.40, L + 0.045)):
        fbox(gT, 'Trim', F, a, b, WTAB, SOF - 0.40, 0.0, 0.045)
        fbox(gT, 'Trim', F, a - 0.015, b + 0.015, WTAB, 0.95, 0.0, 0.06)
        fbox(gT, 'Trim', F, a - 0.02, b + 0.02, SOF - 0.58, SOF - 0.40, 0.0, 0.07)
    # tympanum (white) with the fanlight rising into it
    a0 = math.degrees(math.asin((SOF - zs) / r))
    notch = arc(uc, zs, r, 180 - a0, a0, 18)
    tymp = [(0, SOF)] + notch + [(L, SOF), (L, z_rs_ped(PX)), (uc, z_rs_ped(0)), (0, z_rs_ped(PX))]
    fill(gT, 'Trim', F, tymp, d=0.0)
    archivolt(gT, F, uc, zs, r, band=0.14, mat='Trim')
    gable_rake(gT, PY0, -PXO, PXO, 0.0, z_rs_ped, RAKE, -1)


def build_main(gW, gT, gR):
    P = main_path()
    n = len(P)
    for s in range(n):
        a, b = P[s], P[(s + 1) % n]
        F, L = wallF(a, b)
        holes = []
        if s == 0:
            for x in BAYS[:2]:
                u = x - MX0
                holes.append(french_door(gW, gT, F, u, FF1, 1.1, 2.5, arch=True))
                holes.append(window(gW, gT, F, u, 4.90, 1.0, 1.60))
        elif s == 2:
            pavilion_front(gW, gT, F, L)
            continue
        elif s == 4:
            for x in BAYS[2:]:
                u = x - PX
                holes.append(window(gW, gT, F, u, 1.15, 1.1, 1.95, arch=True))
                holes.append(window(gW, gT, F, u, 4.90, 1.0, 1.60))
        elif s == 6:
            for x in BAYS:
                u = MX1 - x
                holes.append(window(gW, gT, F, u, 1.15, 1.1, 2.0))
                holes.append(window(gW, gT, F, u, 4.90, 1.0, 1.60))
        if s in (1, 3):
            a_, b_ = (L - 0.40, L + 0.045) if s == 1 else (-0.045, 0.40)
            fbox(gT, 'Trim', F, a_, b_, WTAB, SOF - 0.40, 0.0, 0.045)
            fbox(gT, 'Trim', F, a_ - 0.015, b_ + 0.015, WTAB, 0.95, 0.0, 0.06)
            fbox(gT, 'Trim', F, a_ - 0.02, b_ + 0.02, SOF - 0.58, SOF - 0.40, 0.0, 0.07)
        fill(gW, 'Brick', F, rect(0, L, WTAB, SOF), holes)
    base_run(gW, P, closed=True)
    # dentil cornice, broken at the centre for the fanlight
    cp = [(1.05, PY0)] + P[3:] + P[:3] + [(-1.05, PY0)]
    sweep(gT, 'Trim', cp, shift(MAIN_CORNICE, SOF))
    dentils(gT, cp, SOF - 0.12, SOF - 0.03, 0.05, 0.12)
    # roof
    front = [(-W2, -D2), (-PXO, -D2), (0, Y_VAL), (PXO, -D2), (W2, -D2), (RX, 0), (-RX, 0)]
    faces = [[Vector((x, y, ZE + (y + D2) * T)) for x, y in front],
             [Vector((x, y, ZE + (W2 - x) * T)) for x, y in [(W2, -D2), (W2, D2), (RX, 0)]],
             [Vector((x, y, ZE + (D2 - y) * T)) for x, y in [(W2, D2), (-W2, D2), (-RX, 0), (RX, 0)]],
             [Vector((x, y, ZE + (x + W2) * T)) for x, y in [(-W2, D2), (-W2, -D2), (-RX, 0)]],
             [Vector((x, y, ZE + (x + PXO) * PT)) for x, y in [(-PXO, PY0 - OV), (0, PY0 - OV), (0, Y_VAL), (-PXO, -D2)]],
             [Vector((x, y, ZE + (PXO - x) * PT)) for x, y in [(0, PY0 - OV), (PXO, PY0 - OV), (PXO, -D2), (0, Y_VAL)]]]
    roof_slab(gR, faces)
    ridge_caps(gR, faces)
    nf = Vector((0, -math.sin(math.radians(PITCH)), math.cos(math.radians(PITCH))))
    for s in (-1, 1):
        valley_strip(gR, (s * PXO, -D2, ZE), (0, Y_VAL, Z_PED), (nf + Vector((s * 0.5, 0, 0.87))).normalized())
    for x in DORMERS:
        dormer(gW, gT, gR, x, front=True)
        dormer(gW, gT, gR, x, front=False)
    for (cx, cy) in CHIMNEYS:
        chimney(gW, gT, cx, cy, 1.7, 1.0, SOF - 0.2, CH_TOP, pots=3)
    # downspouts
    for (x, y, nn) in ((MX1 - 0.25, MY0, (0, -1)), (MX1 - 0.25, MY1, (0, 1)), (MX0 + 0.25, MY1, (0, 1))):
        downspout(gT, x, y, SOF - 0.02, nn)


def dormer(gW, gT, gR, xc, front=True):
    """Pedimented attic dormer: white panelled front with pilasters, slate-hung cheeks, slate gable roof."""
    sg = -1 if front else 1
    yf = sg * (MY1 - 0.20)
    zroof = lambda y: ZE + (D2 - abs(y)) * T
    hw = 0.75
    win_w, win_h = 0.74, 1.05
    sill = zroof(yf) + 0.20
    sof = sill + win_h + 0.20
    zde = sof + HCS + 0.05
    dp = 35.0
    dt = math.tan(math.radians(dp))
    hwr = hw + 0.35
    zap = zde + hwr * dt
    # roof extends back until it is under the main roof
    y_end = sg * (D2 - (zap - ZE) / T) - sg * 0.15
    if front:
        F, L = wallF((xc - hw, yf), (xc + hw, yf))
    else:
        F, L = wallF((xc + hw, yf), (xc - hw, yf))
    zb = zroof(yf) - 0.15
    hole = window(gT, gT, F, L / 2, sill, win_w, win_h, shutters=False, lintel=False, reveal_mat='Trim',
                  sill_mat='Trim', RD=0.06)
    fill(gT, 'Trim', F, rect(0, L, zb, sof), [hole])
    for a, b in ((0, 0.16), (L - 0.16, L)):
        fbox(gT, 'Trim', F, a, b, zb + 0.1, sof - 0.18, 0.0, 0.03)
    # cheeks (slate-hung), up to the underside of the dormer roof
    z_u = zde + (hwr - hw) * dt - TH / math.cos(math.radians(dp))
    y_cheek = sg * (D2 - (z_u + 0.1 - ZE) / T)
    for sx in (-1, 1):
        x = xc + sx * hw
        pts = [Vector((x, yf, zb)), Vector((x, yf, z_u)), Vector((x, y_cheek, z_u))]
        poly(gW, 'Slate', pts, facing=(sx, 0, 0))
    # cornice across the front with short returns on the cheeks
    if front:
        path = [(xc - hw, yf + 0.3), (xc - hw, yf), (xc + hw, yf), (xc + hw, yf + 0.3)]
    else:
        path = [(xc + hw, yf - 0.3), (xc + hw, yf), (xc - hw, yf), (xc - hw, yf - 0.3)]
    sweep(gT, 'Trim', path, shift(SMALL_CORNICE, sof))
    zrs = lambda x: zde + (hwr - abs(x - xc)) * dt - (TH + HCS) / math.cos(math.radians(dp))
    # tympanum + rake
    tymp = [(0, sof), (L, sof), (L, zrs(xc + hw)), (L / 2, zrs(xc)), (0, zrs(xc - hw))]
    fill(gT, 'Trim', F, tymp)
    pts = [Vector((xc - hwr, yf, zrs(xc - hwr))), Vector((xc, yf, zrs(xc))), Vector((xc + hwr, yf, zrs(xc + hwr)))]
    out = Vector((0, sg, 0))
    ups = []
    for a, b in zip(pts, pts[1:]):
        dd = (b - a).normalized()
        ups.append((Vector((0, 0, 1)) - dd * dd.z).normalized())
    sweep(gT, 'Trim', pts, SMALL_RAKE, outs=[out, out], ups=ups)
    # roof
    y_front = yf + sg * 0.36
    ya, yb = sorted((y_front, y_end))
    faces = [[Vector((x, y, zde + (x - (xc - hwr)) * dt)) for x, y in [(xc - hwr, ya), (xc, ya), (xc, yb), (xc - hwr, yb)]],
             [Vector((x, y, zde + ((xc + hwr) - x) * dt)) for x, y in [(xc, ya), (xc + hwr, ya), (xc + hwr, yb), (xc, yb)]]]
    roof_slab(gR, faces)
    ridge_caps(gR, faces)
    # sanity: the dormer must stay on the front/back slope, clear of the hips
    hip = lambda x: ZE + (W2 - abs(x)) * T
    for x, z in ((xc, zap), (xc + hwr, zde), (xc - hwr, zde)):
        if z > hip(x) - 0.02:
            print(f'WARNING dormer at {xc} pokes through the hip at x={x:.2f}: {z:.2f} > {hip(x):.2f}')


# ---------------------------------------------------------------------------- wings, porch, ell
def gable_wall(gW, F, L, z_rs_u, holes):
    out = [(0, WTAB), (L, WTAB), (L, z_rs_u(L)), (L / 2, z_rs_u(L / 2)), (0, z_rs_u(0))]
    fill(gW, 'Brick', F, out, holes)


def bay_window(gW, gT, gR, xc, yw):
    """Box bay (2.8 x 0.75 m) on a brick base: three 6-over-6 windows in front, one each side, entablature and a
    lead-coated copper hipped roof."""
    bx0, bx1, by0 = xc - 1.4, xc + 1.4, yw - 0.75
    box(gW, 'BrickBase', bx0, bx1, by0, yw, -0.6, 0.40)
    box(gW, 'Brick', bx0, bx1, by0, yw, 0.40, 0.85)
    box(gT, 'Stone', bx0 - 0.04, bx1 + 0.04, by0 - 0.04, yw, 0.85, 0.95)
    zt = 3.05
    for (a, b, us, w, cols) in (((bx0, by0), (bx1, by0), (0.5, 1.4, 2.3), 0.72, 3),
                                ((bx1, by0), (bx1, yw), (0.375,), 0.40, 2),
                                ((bx0, yw), (bx0, by0), (0.375,), 0.40, 2)):
        F, L = wallF(a, b)
        holes = [window(gT, gT, F, u, 1.0, w, 1.95, shutters=False, lintel=False, reveal_mat='Trim', sill_mat=None,
                        RD=0.05, cols=cols) for u in us]
        fill(gT, 'Trim', F, rect(0, L, 0.95, zt), holes)
        for u in ([0.0, L] + ([0.95, 1.85] if len(us) == 3 else [])):
            fbox(gT, 'Trim', F, max(0, u - 0.04), min(L, u + 0.04), 0.95, zt, 0.0, 0.025)
    path = [(bx0, yw), (bx0, by0), (bx1, by0), (bx1, yw)]
    sof = zt + 0.18
    sweep(gT, 'Trim', path, shift(SMALL_CORNICE, sof), caps=(False, False))
    ze = sof + HCS + 0.04
    t = math.tan(math.radians(22))
    o = 0.35
    pl = {k: plane_eave(bx0 - o, bx1 + o, by0 - o, yw + 0.3, k, ze, t) for k in ('front', 'left', 'right')}
    faces = roof_faces(bx0 - o, bx1 + o, by0 - o, yw + 0.2, pl)
    roof_slab(gR, faces, th=0.05, top='Copper', edge='Copper')
    ridge_caps(gR, faces, w=0.05, lift=0.02, mat='Copper')


def build_left_wing(gW, gT, gR):
    x0, x1, y0, y1, sof, ov = LW['x0'], LW['x1'], LW['y0'], LW['y1'], LW['sof'], LW['ov']
    xc, hw = LW_XC, (x1 - x0) / 2
    zt = lambda x: LW_ZE + (hw + ov - abs(x - xc)) * LW_T
    k = (TH + HCS) / math.cos(math.radians(LW['pitch']))
    zrs = lambda x: zt(x) - k
    # front gable with gable window and box bay
    F, L = wallF((x0, y0), (x1, y0))
    gable_wall(gW, F, L, lambda u: zrs(x0 + u), [window(gW, gT, F, L / 2, 4.98, 0.85, 1.30)])
    bay_window(gW, gT, gR, xc, y0)
    gable_rake(gT, y0, x0 - ov + 0.42, x1 + ov - 0.42, xc, zrs, SMALL_RAKE, -1)
    # back gable
    F, L = wallF((x1, y1), (x0, y1))
    gable_wall(gW, F, L, lambda u: zrs(x1 - u), [window(gW, gT, F, L / 2, 1.15, 1.0, 2.0),
                                                 window(gW, gT, F, L / 2, 4.98, 0.85, 1.30)])
    gable_rake(gT, y1, x0 - ov + 0.42, x1 + ov - 0.42, xc, zrs, SMALL_RAKE, 1)
    # left side
    F, L = wallF((x0, y1), (x0, y0))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), [window(gW, gT, F, u, 1.15, 1.0, 2.0) for u in (2.3, 5.75, 9.2)])
    # right side, front part (inside the side porch)
    F, L = wallF((x1, y0), (x1, MY0))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), [window(gW, gT, F, L / 2 - 0.05, 1.15, 0.9, 2.0)])
    base_run(gW, [(x1, y1), (x0, y1), (x0, y0), (x1, y0), (x1, MY0)])
    sweep(gT, 'Trim', [(x0 + 0.5, y1), (x0, y1), (x0, y0), (x0 + 0.5, y0)], shift(SMALL_CORNICE, sof))
    sweep(gT, 'Trim', [(x1 - 0.5, y0), (x1, y0), (x1, MY0)], shift(SMALL_CORNICE, sof), caps=(True, False))
    # return tops (small lead-coated hips over the cornice returns)
    for (xa, xb, yy, sgn) in ((x0 - 0.34, x0 + 0.5, y0, -1), (x1 - 0.5, x1 + 0.34, y0, -1), (x0 - 0.34, x0 + 0.5, y1, 1)):
        za = sof + HCS
        poly(gT, 'Lead', [(xa, yy + sgn * 0.34, za), (xb, yy + sgn * 0.34, za), (xb, yy, za + 0.12), (xa, yy, za + 0.12)],
             facing=(0, sgn, 1))
    # roof
    rr = (x0 - ov, x1 + ov, y0 - 0.36, y1 + 0.36)
    pl = {k: plane_eave(*rr, k, LW_ZE, LW_T) for k in ('left', 'right')}
    faces = roof_faces(*rr, pl)
    roof_slab(gR, faces)
    ridge_caps(gR, faces)
    downspout(gT, x0, y0 + 0.25, sof - 0.02, (-1, 0))
    downspout(gT, x0, y1 - 0.25, sof - 0.02, (-1, 0))


def build_porch(gW, gT, gR):
    """Side porch in the corner between the left wing and the pavilion: brick floor, Tuscan columns, beams,
    sloped beadboard ceiling, slate roof hipped at the pavilion end."""
    x0, x1, yb, fl = PORCH['x0'], -2.75, PORCH['y0'], PORCH['fl']
    box(gW, 'Brick', x0, x1, yb + 0.03, MY0, -0.6, fl - 0.05)
    box(gT, 'Bluestone', x0, x1, yb, MY0, fl - 0.05, fl)
    # steps (3 risers) between the middle columns
    cx, sw = -6.0, 0.75
    for k in range(1, 3):
        zt_ = fl - k * 0.15
        yf = yb - k * 0.33
        box(gW, 'Brick', cx - sw, cx + sw, yf + 0.025, yb - (k - 1) * 0.33, -0.4, zt_ - 0.05)
        box(gT, 'Bluestone', cx - sw - 0.02, cx + sw + 0.02, yf, yb - (k - 1) * 0.33, zt_ - 0.05, zt_)
    yc = -7.55
    zc = 3.30
    cols = (-7.0, -5.0, -3.0)
    for x in cols:
        tuscan(gT, x, yc, fl, zc, r=0.125)
    fbox(gT, 'Trim', wallF((x0, yc), (x0 + 1, yc))[0], 0.0, 0.18, fl, zc, -0.12, 0.12)
    # beams
    box(gT, 'Trim', x0, -2.9, yc - 0.11, yc + 0.11, zc, zc + 0.30)
    box(gT, 'Trim', x0, -2.88, yc - 0.13, yc + 0.13, zc + 0.24, zc + 0.30)
    box(gT, 'Trim', -3.11, -2.89, yc, MY0, zc, zc + 0.30)
    # roof: front plane and a hip at the pavilion end
    pt = math.tan(math.radians(PORCH['pitch']))
    ye, xe = -7.98, -2.82
    ze = PORCH['z_wall'] - (MY0 - ye) * pt
    pl = {'front': (0.0, pt, ze - pt * ye), 'right': (-pt, 0.0, ze + pt * xe)}
    faces = roof_faces(x0, xe, ye, MY0, pl)
    roof_slab(gR, faces, th=0.06)
    ridge_caps(gR, faces)
    # fascia + soffit along the eaves
    box(gT, 'Trim', x0, xe, ye, ye + 0.025, ze - 0.24, ze - 0.06)
    box(gT, 'Trim', xe - 0.025, xe, ye, MY0, ze - 0.24, ze - 0.06)
    poly(gT, 'Trim', [(x0, ye, ze - 0.24), (xe, ye, ze - 0.24), (xe, yc - 0.11, ze - 0.24), (x0, yc - 0.11, ze - 0.24)],
         facing=(0, 0, -1))
    poly(gT, 'Trim', [(-2.89, ye, ze - 0.24), (xe, ye, ze - 0.24), (xe, MY0, ze - 0.24), (-2.89, MY0, ze - 0.24)],
         facing=(0, 0, -1))
    # sloped ceiling under the rafters
    pc = {k: (A, B, C - 0.30) for k, (A, B, C) in pl.items()}
    cf = roof_faces(x0, -3.11, yc + 0.11, MY0, pc)
    for f in cf:
        poly(gT, 'Trim', f, facing=(0, 0, -1))
    xl, yl = -6.0, -6.65
    zc_l = min(A * xl + B * yl + C for (A, B, C) in pc.values())
    pendant_lantern(gT, xl, yl, zc_l, 2.95)


def build_right_wing(gW, gT, gR):
    x0, x1, y0, y1, sof, ov = RW['x0'], RW['x1'], RW['y0'], RW['y1'], RW['sof'], RW['ov']
    F, L = wallF((x0, y0), (x1, y0))
    holes = []
    for u in (1.5, 4.5):
        holes.append(window(gW, gT, F, u, 1.15, 1.0, 2.0))
        holes.append(window(gW, gT, F, u, 4.30, 1.0, 1.30))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), holes)
    F, L = wallF((x1, y0), (x1, y1))
    holes = [side_door(gW, gT, F, 4.5)]
    for u in (1.6, 7.4):
        holes.append(window(gW, gT, F, u, 1.15, 1.0, 2.0))
    for u in (1.6, 4.5, 7.4):
        holes.append(window(gW, gT, F, u, 4.30, 1.0, 1.30))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), holes)
    F, L = wallF((x1, y1), (x0, y1))
    holes = []
    for u in (1.5, 4.5):
        holes.append(window(gW, gT, F, u, 1.15, 1.0, 2.0))
        holes.append(window(gW, gT, F, u, 4.30, 1.0, 1.30))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), holes)
    path = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    base_run(gW, path)
    sweep(gT, 'Trim', path, shift(SMALL_CORNICE, sof), caps=(False, False))
    rr = (x0 - ov, x1 + ov, y0 - ov, y1 + ov)
    pl = {k: plane_eave(*rr, k, RW_ZE, T) for k in ('front', 'back', 'left', 'right')}
    faces = roof_faces(*rr, pl)
    roof_slab(gR, faces)
    ridge_caps(gR, faces)
    chimney(gW, gT, 12.0, 2.3, 1.2, 0.8, sof - 0.2, 10.9, pots=2)
    downspout(gT, x1 - 0.25, y0, sof - 0.02, (0, -1))
    downspout(gT, x1 - 0.25, y1, sof - 0.02, (0, 1))


def side_door(gW, gT, F, uc):
    """Side entry: six-panel door with a four-light transom, casing, a copper-roofed hood on brackets, a lantern
    and a brick stoop with bluestone treads."""
    w, z0 = 0.95, FF1
    u0, u1, z1 = uc - w / 2, uc + w / 2, FF1 + 2.62
    hole = rect(u0, u1, z0, z1)
    D = -0.16
    reveal(gW, 'Brick', F, hole, -D + 0.04)
    fbox(gT, 'Trim', F, u0, u1, z0, z1, D - 0.06, D)
    fbox(gT, 'Door', F, u0 + 0.06, u1 - 0.06, z0 + 0.01, z1 - 0.48, D, D + 0.04)
    for c in (0, 1):
        pu0 = u0 + 0.13 + c * 0.36
        for (pz0, pz1) in ((z0 + 0.15, z0 + 0.7), (z0 + 0.85, z0 + 1.45), (z0 + 1.6, z1 - 0.62)):
            fbox(gT, 'Door', F, pu0, pu0 + 0.30, pz0, pz1, D + 0.04, D + 0.055)
    fbox(gT, 'Brass', F, u1 - 0.17, u1 - 0.12, z0 + 0.97, z0 + 1.03, D + 0.04, D + 0.1)
    poly(gT, 'Glass', [F.p(u0 + 0.06, z1 - 0.42, D + 0.01), F.p(u1 - 0.06, z1 - 0.42, D + 0.01),
                       F.p(u1 - 0.06, z1 - 0.06, D + 0.01), F.p(u0 + 0.06, z1 - 0.06, D + 0.01)], facing=F.N)
    for i in range(1, 4):
        uu = u0 + 0.06 + (w - 0.12) * i / 4
        fbox(gT, 'Trim', F, uu - 0.011, uu + 0.011, z1 - 0.42, z1 - 0.06, D + 0.01, D + 0.03)
    fbox(gT, 'Trim', F, u0 + 0.06, u1 - 0.06, z1 - 0.48, z1 - 0.42, D, D + 0.04)
    for a, b in ((u0 - 0.14, u0), (u1, u1 + 0.14)):
        fbox(gT, 'Trim', F, a, b, z0, z1, 0.0, 0.035)
    fbox(gT, 'Trim', F, u0 - 0.16, u1 + 0.16, z1, z1 + 0.16, 0.0, 0.04)
    # hood on brackets
    hz = z1 + 0.32
    for a in (u0 - 0.12, u1 + 0.04):
        extrude(gT, 'Trim', F.side(), [(0.0, hz - 0.45), (0.10, hz - 0.40), (0.62, hz - 0.03), (0.62, hz), (0.0, hz)],
                -(a + 0.08), -a)
    fbox(gT, 'Trim', F, u0 - 0.25, u1 + 0.25, hz, hz + 0.16, 0.0, 0.72)
    hp = [F.p(u0 - 0.30, hz + 0.16, 0.77), F.p(u1 + 0.30, hz + 0.16, 0.77), F.p(u1 + 0.30, hz + 0.40, 0.0),
          F.p(u0 - 0.30, hz + 0.40, 0.0)]
    roof_slab(gT, [hp], th=0.04, top='Copper', bottom='Trim', edge='Copper')
    wall_lantern(gT, F, u1 + 0.45, z0 + 2.0)
    # stoop
    Fs = Fr(F.p(uc, 0, 0), F.U, F.N)
    fbox(gW, 'Brick', Fs, -0.85, 0.85, -0.5, FF1 - 0.06, 0.0, 1.1)
    fbox(gT, 'Bluestone', Fs, -0.87, 0.87, FF1 - 0.06, FF1 - 0.01, 0.0, 1.12)
    for k in range(1, 4):
        zt_ = FF1 - 0.01 - k * 0.148
        d0, d1 = 1.1 + (k - 1) * 0.32, 1.1 + k * 0.32
        fbox(gW, 'Brick', Fs, -0.85, 0.85, -0.4, zt_ - 0.05, d0, d1 - 0.02)
        fbox(gT, 'Bluestone', Fs, -0.87, 0.87, zt_ - 0.05, zt_, d0, d1)
    return hole


def build_ell(gW, gT, gR):
    x0, x1, y0, y1, sof, ov = EL['x0'], EL['x1'], EL['y0'], EL['y1'], EL['sof'], EL['ov']
    F, L = wallF((x1, y0), (x1, y1))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), [window(gW, gT, F, L / 2, 1.15, 1.0, 2.0)])
    F, L = wallF((x1, y1), (x0, y1))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), [french_door(gW, gT, F, L / 2, FF1, 1.5, 2.45)])
    wall_lantern(gT, F, L / 2 - 1.55, FF1 + 2.0)
    F, L = wallF((x0, y1), (x0, y0))
    fill(gW, 'Brick', F, rect(0, L, WTAB, sof), [window(gW, gT, F, L / 2, 1.15, 1.0, 2.0)])
    path = [(x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    base_run(gW, path)
    sweep(gT, 'Trim', path, shift(SMALL_CORNICE, sof), caps=(False, False))
    t = math.tan(math.radians(EL['pitch']))
    rr = (x0 - ov, x1 + ov, y0 - 0.5, y1 + ov)
    pl = {k: plane_eave(*rr, k, EL_ZE, t) for k in ('back', 'left', 'right')}
    faces = roof_faces(*rr, pl)
    roof_slab(gR, faces)
    ridge_caps(gR, faces)
    # steps down to the terrace
    for k in range(1, 4):
        zt_ = FF1 - k * 0.15
        ya, yb = y1 + (k - 1) * 0.33, y1 + k * 0.33
        box(gW, 'Brick', -1.2, 1.2, ya, yb - 0.025, -0.4, zt_ - 0.05)
        box(gT, 'Bluestone', -1.22, 1.22, ya, yb, zt_ - 0.05, zt_)
    box(gW, 'Brick', -1.2, 1.2, y1 - 0.01, y1 + 0.001, -0.4, FF1 - 0.04)
    downspout(gT, x1 - 0.25, y1, sof - 0.02, (0, 1))
    downspout(gT, x0 + 0.25, y1, sof - 0.02, (0, 1))


def build_portico(gT, gW, gR):
    xi, yf = PO['xi'], PO['yf']
    for x in PO['cols']:
        tuscan(gT, x, PO['col_y'], FF1, PO['col_z1'], r=PO['col_r'])
    z1, zd = PO['col_z1'], PO['deck']
    prof = [(0, z1), (0.30, z1), (0.30, z1 + 0.20), (0.32, z1 + 0.22), (0.32, z1 + 0.38), (0.37, z1 + 0.40),
            (0.43, z1 + 0.43), (0.48, z1 + 0.47), (0.48, zd), (0, zd)]
    path = [(-xi, PY0), (-xi, yf), (xi, yf), (xi, PY0)]
    sweep(gT, 'Trim', path, prof, caps=(False, False), closed_profile=True)
    # coffered ceiling and pendant lantern
    poly(gT, 'Trim', [(-xi, yf, z1 + 0.10), (xi, yf, z1 + 0.10), (xi, PY0, z1 + 0.10), (-xi, PY0, z1 + 0.10)],
         facing=(0, 0, -1))
    for x in (-0.7, 0.7):
        box(gT, 'Trim', x - 0.06, x + 0.06, yf, PY0, z1 + 0.0, z1 + 0.10)
    pendant_lantern(gT, 0.0, (yf + PY0) / 2, z1 + 0.10, 2.70)
    # flat roof deck (bluestone) and balustrade
    box(gT, 'Bluestone', -xi, xi, yf, PY0, zd - 0.08, zd)
    xb, ybf, ybw = xi + 0.25, yf - 0.25, PY0 - 0.17
    top = zd + 1.05
    for x in (-xb, xb):
        pedestal(gT, x, ybf, zd, top + 0.08)
        pedestal(gT, x, ybw, zd, top + 0.08, s=0.24)
        balustrade(gT, (x, ybf + 0.17), (x, ybw - 0.14), zd, top)
    balustrade(gT, (-xb + 0.17, ybf), (xb - 0.17, ybf), zd, top)
    # terrace and wide steps (bluestone treads on brick)
    tw, yt = 2.75, STEPS['y_top']
    box(gW, 'Brick', -tw + 0.03, tw - 0.03, yt + 0.03, PY0, -0.5, FF1 - 0.06)
    box(gT, 'Bluestone', -tw, tw, yt, PY0, FF1 - 0.06, FF1)
    n, run = STEPS['n'], STEPS['run']
    rise = FF1 / n
    for k in range(1, n):
        zt_ = FF1 - k * rise
        ya, yb = yt - k * run, yt - (k - 1) * run
        box(gW, 'Brick', -tw + 0.03, tw - 0.03, ya + 0.03, yb, -0.5, zt_ - 0.05)
        box(gT, 'Bluestone', -tw, tw, ya, yb, zt_ - 0.05, zt_)
    yfront = yt - (n - 1) * run
    for s in (-1, 1):
        x = s * (tw + 0.36)
        cbox(gW, 'Brick', x, yfront + 0.37, 0.70, 0.70, -0.4, 0.80)
        cbox(gT, 'Bluestone', x, yfront + 0.37, 0.80, 0.80, 0.80, 0.88)
        urn(gT, x, yfront + 0.37, 0.88, scale=1.15, plant='Boxwood', seed=11 + s)
        urn(gT, s * 1.55, PY0 - 0.45, FF1, scale=0.95, plant='Flowers', seed=21 + s)


# ============================================================================ the lot
DRIVE_W = 4.0
LOOP = dict(cx=0.0, cy=-22.5, r=9.5)           # horseshoe: legs at x = +-9.5, top arc centred at (0, -22.5)
SPUR = [(7.6, -16.6), (11.0, -14.2), (14.6, -12.6), (17.4, -11.2), (18.75, -9.3)]
COURT = (16.8, -9.6, 20.7, 4.2)
ISLAND = dict(cx=0.0, cy=-22.6, rx=4.7, ry=4.0)
TREES = [((-13.2, -22.4), 41, 17.5, 17.0, 0.55), ((13.2, -25.4), 42, 16.5, 15.0, 0.5),
         ((-13.6, 16.0), 43, 18.0, 16.0, 0.58)]


def drive_centerlines():
    L = []
    cx, cy, r = LOOP['cx'], LOOP['cy'], LOOP['r']
    left = [(-r, CURB_Y - 1.0)] + [(-r, y) for y in np.linspace(CURB_Y, cy, 12)]
    top = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in np.linspace(180, 0, 48)]
    right = [(r, y) for y in np.linspace(cy, CURB_Y, 12)] + [(r, CURB_Y - 1.0)]
    L.append(left + top[1:] + right[1:])
    L.append(SPUR)
    return L


def _seg_dist(X, Y, pts):
    d = np.full(X.shape, 1e9, np.float32)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = np.clip(((X - ax) * vx + (Y - ay) * vy) / L2, 0, 1)
        dx, dy = X - (ax + t * vx), Y - (ay + t * vy)
        d = np.minimum(d, np.sqrt(dx * dx + dy * dy))
    return d


def drive_sdf(X, Y):
    lines = drive_centerlines()
    d = _seg_dist(X, Y, lines[0])
    # flared mouths at the curb: widen within 4 m of the curb line
    flare = np.clip(1 - (Y - CURB_Y) / 4.5, 0, 1) ** 2 * 1.6
    f = d - (DRIVE_W / 2 + flare)
    f = np.minimum(f, _seg_dist(X, Y, lines[1]) - 1.6)
    x0, y0, x1, y1 = COURT
    qx = np.abs(X - (x0 + x1) / 2) - ((x1 - x0) / 2 - 1.0)
    qy = np.abs(Y - (y0 + y1) / 2) - ((y1 - y0) / 2 - 1.0)
    box_ = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - 1.0
    f = np.minimum(f, box_)
    # smooth the junctions a little (fillet) and cut at the curb line
    f = np.maximum(f, CURB_Y - Y)
    return f


def marching_loops(f, xs, ys):
    """Iso-contour (f = 0) of a grid as closed loops of points; inside is f < 0."""
    ny, nx = f.shape
    inside = f < 0
    pts = {}

    def ep(key):
        if key not in pts:
            k, i, j = key
            if k == 'h':
                a, b = f[j, i], f[j, i + 1]
                t = a / (a - b) if a != b else 0.5
                pts[key] = (xs[i] + (xs[i + 1] - xs[i]) * t, ys[j])
            else:
                a, b = f[j, i], f[j + 1, i]
                t = a / (a - b) if a != b else 0.5
                pts[key] = (xs[i], ys[j] + (ys[j + 1] - ys[j]) * t)
        return pts[key]
    nxt = {}
    for j in range(ny - 1):
        for i in range(nx - 1):
            c = (inside[j, i], inside[j, i + 1], inside[j + 1, i + 1], inside[j + 1, i])
            idx = c[0] * 1 + c[1] * 2 + c[2] * 4 + c[3] * 8
            if idx in (0, 15):
                continue
            B, R, Tt, Lf = ('h', i, j), ('v', i + 1, j), ('h', i, j + 1), ('v', i, j)
            # segments oriented consistently (inside on the right), so they chain into loops
            table = {1: [(Lf, B)], 2: [(B, R)], 3: [(Lf, R)], 4: [(R, Tt)], 6: [(B, Tt)], 7: [(Lf, Tt)],
                     8: [(Tt, Lf)], 9: [(Tt, B)], 11: [(Tt, R)], 12: [(R, Lf)], 13: [(R, B)], 14: [(B, Lf)]}
            if idx == 5:
                segs = [(Lf, Tt), (R, B)] if (f[j, i] + f[j, i + 1] + f[j + 1, i] + f[j + 1, i + 1]) < 0 else [(Lf, B), (R, Tt)]
            elif idx == 10:
                segs = [(B, Lf), (Tt, R)] if (f[j, i] + f[j, i + 1] + f[j + 1, i] + f[j + 1, i + 1]) < 0 else [(B, R), (Tt, Lf)]
            else:
                segs = table[idx]
            for a, b in segs:
                nxt[a] = b
    loops = []
    seen = set()
    for st in list(nxt.keys()):
        if st in seen:
            continue
        loop = []
        k = st
        while k not in seen and k in nxt:
            seen.add(k)
            loop.append(ep(k))
            k = nxt[k]
        if len(loop) > 2:
            loops.append(loop)
    return loops


def dp_simplify(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    L = np.linalg.norm(ab)
    P = np.array(pts)
    if L < 1e-9:
        d = np.linalg.norm(P - a, axis=1)
    else:
        d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > tol:
        return dp_simplify(pts[:i + 1], tol)[:-1] + dp_simplify(pts[i:], tol)
    return [pts[0], pts[-1]]


def slab_from_loops(g, mat, loops, z_top, z_bot=-0.12, side_mat=None):
    """Flat hardscape with sides, from closed loops (outer + holes)."""
    L3 = [[Vector((x, y, 0)) for x, y in lp] for lp in loops]
    tris = tessellate_polygon(L3)
    flat = [Vector((p.x, p.y, z_top)) for lp in L3 for p in lp]
    faces = []
    for t in tris:
        a, b, c = flat[t[0]], flat[t[1]], flat[t[2]]
        nn = (b - a).cross(c - a)
        if nn.length < 1e-10:
            continue
        faces.append(t if nn.z > 0 else (t[0], t[2], t[1]))
    g.add(flat, faces, mat)
    for lp in loops:
        ccw = area2(lp) > 0
        for i in range(len(lp)):
            a, b = lp[i], lp[(i + 1) % len(lp)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            out = (dy, -dx) if ccw else (-dy, dx)
            poly(g, side_mat or mat, [(a[0], a[1], z_bot), (b[0], b[1], z_bot), (b[0], b[1], z_top), (a[0], a[1], z_top)],
                 facing=(out[0], out[1], 0))


def ellipse(cx, cy, rx, ry, n=48, rot=0.0):
    return [(cx + rx * math.cos(2 * math.pi * i / n + rot), cy + ry * math.sin(2 * math.pi * i / n + rot)) for i in range(n)]


def build_drive(g):
    h = 0.1
    xs = np.arange(LOT[0] + 0.5, LOT[2] - 0.2 + 1e-6, h)
    ys = np.arange(CURB_Y, 6.0, h)
    X, Y = np.meshgrid(xs, ys)
    f = drive_sdf(X, Y)
    f[:, 0] = np.abs(f[:, 0]) + 0.01
    f[:, -1] = np.abs(f[:, -1]) + 0.01
    f[-1, :] = np.abs(f[-1, :]) + 0.01
    loops = marching_loops(f, xs, ys)
    out = []
    for lp in loops:
        lp = [(x, CURB_Y if abs(y - CURB_Y) < 1e-4 else y) for x, y in lp]
        lp = dp_simplify(lp + [lp[0]], 0.015)[:-1]
        out.append(lp)
    slab_from_loops(g, 'Asphalt', out, 0.035, side_mat='Asphalt')
    # Belgian-block edging on every edge except along the curb line
    prof = [(0.0, -0.12), (0.13, -0.12), (0.13, 0.05), (0.115, 0.065), (0.015, 0.065), (0.0, 0.05)]
    for lp in out:
        if area2(lp) < 0:
            lp = lp[::-1]
        n = len(lp)
        on_curb = [abs(lp[i][1] - CURB_Y) < 1e-6 and abs(lp[(i + 1) % n][1] - CURB_Y) < 1e-6 for i in range(n)]
        if not any(on_curb):
            sweep(g, 'Granite', lp, prof, closed=True, closed_profile=True)
            continue
        k0 = on_curb.index(True)
        chain = []
        for kk in range(1, n + 1):
            i = (k0 + kk) % n
            if on_curb[(i - 1) % n] and not on_curb[i]:
                chain = [lp[i]]
            elif not on_curb[i]:
                chain.append(lp[i])
            if chain and on_curb[i] and not on_curb[(i - 1) % n]:
                chain.append(lp[i])
                if len(chain) > 1:
                    sweep(g, 'Granite', chain, prof, closed_profile=True)
                chain = []
    return out


def foliage_colfn(t=1.0, hue=0.0, inner=1.0, base=0.32):
    def colfn(q, d):
        under = base + (1 - base) * min(1.0, max(0.0, (d.z + 0.55) / 1.25))
        a = t * under * (0.7 + 0.3 * inner)
        return (a * (1.0 + hue), a * 1.02, a * (0.92 - hue))
    return colfn


def boxwood(g, x, y, r, seed, z0=0.03, mat='Boxwood', squash=0.85, sub=3, tone=1.0, nfn=None):
    rng = np.random.default_rng(seed)
    blob(g, mat, (x, y, z0 + r * squash * 0.92), (r, r * rng.uniform(0.92, 1.08), r * squash), seed, rough=0.16,
         freq=2.8, sub=sub, colfn=foliage_colfn(tone * rng.uniform(0.9, 1.08), rng.uniform(-0.02, 0.02)),
         flat_bottom=z0 + 0.05, nfn=nfn)


def ring_hedge_normals(cx, cy, rx, ry, zc, own=0.45):
    def f(p, d):
        a = math.atan2((p.y - cy) / ry, (p.x - cx) / rx)
        q = Vector((cx + rx * math.cos(a), cy + ry * math.sin(a), zc))
        n = (p - q)
        n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
        return tuple((n * (1 - own) + d.normalized() * own).normalized())
    return f


def hardwood(g, base, seed, height, spread, trunk_r, bounds=None, n_limbs=5, lod=1.0):
    """Mature deciduous hardwood (white oak habit): flared, slightly leaning trunk forking at ~30% of its height
    into scaffold limbs and secondary branches, under a broad domed crown built from many overlapping lumpy leaf
    clumps on the crown shell plus darker interior masses (darker underneath and inside)."""
    rng = np.random.default_rng(seed)
    bx, by = base
    LX0, LY0, LX1, LY1 = bounds or LOT
    fork = 0.21 * height
    lean = Vector((rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), 0))
    zs = [-0.5, 0.0, 0.5, 1.2, fork * 0.5, fork * 0.8, fork]
    tp = [Vector((bx, by, z)) + lean * max(0.0, z / fork) ** 1.5 for z in zs]
    tr = [trunk_r * 1.5, trunk_r * 1.35, trunk_r * 1.1, trunk_r * 1.0, trunk_r * 0.95, trunk_r * 0.9, trunk_r * 0.82]
    tube(g, 'Bark', tp, tr, seg=14)
    for k in range(5):
        a = 2 * math.pi * k / 5 + rng.uniform(-0.3, 0.3)
        p0 = (bx + math.cos(a) * trunk_r * 0.5, by + math.sin(a) * trunk_r * 0.5, 0.9)
        p1 = (bx + math.cos(a) * trunk_r * 1.25, by + math.sin(a) * trunk_r * 1.25, 0.12)
        p2 = (bx + math.cos(a) * trunk_r * 1.9, by + math.sin(a) * trunk_r * 1.9, -0.15)
        tube(g, 'Bark', [p0, p1, p2], [trunk_r * 0.42, trunk_r * 0.28, trunk_r * 0.08], seg=6)
    top = tp[-1]
    crx = min(spread / 2, bx - LX0 - 0.3, LX1 - bx - 0.3, by - LY0 - 0.3, LY1 - by - 0.3)
    crz = (height - fork - 1.4) / 2
    c0 = Vector((top.x, top.y, height - crz))

    def ell(u, v, f):
        cv = math.sqrt(max(0.0, 1 - v * v))
        return Vector((c0.x + math.cos(u) * crx * f * cv, c0.y + math.sin(u) * crx * f * cv, c0.z + v * crz * f))

    def curve(p0, p1, r0, r1, n, rise=0.35):
        pts = []
        for i in range(n + 1):
            t = i / n
            q = p0.lerp(p1, t)
            q.z += math.sin(math.pi * t) * rise * (p1 - p0).length * 0.25
            q += Vector((rng.normal(0, 0.12), rng.normal(0, 0.12), rng.normal(0, 0.08))) * (0 < i < n)
            pts.append(q)
        return pts, [r0 + (r1 - r0) * i / n for i in range(n + 1)]

    sites = []
    az0 = rng.uniform(0, 2 * math.pi)
    for li in range(n_limbs):
        u = az0 + 2 * math.pi * li / n_limbs + rng.uniform(-0.3, 0.3)
        tgt = ell(u, rng.uniform(-0.35, 0.25), 0.72)
        start = top - Vector((0, 0, rng.uniform(0.0, 0.9)))
        pts, rad = curve(start, tgt, trunk_r * 0.55, 0.08, 7)
        tube(g, 'Bark', pts, rad, seg=8, cap_end=False)
        sites.append(pts[-1])
        for bi in range(int(rng.integers(3, 5))):
            i = int(rng.integers(2, len(pts) - 1))
            u2 = u + rng.uniform(-0.7, 0.7)
            t2 = ell(u2, rng.uniform(-0.35, 0.8), 0.9)
            bp, br = curve(pts[i], t2, max(0.05, rad[i] * 0.5), 0.025, 4, rise=0.2)
            tube(g, 'Bark', bp, br, seg=5, cap_end=False)
            sites.append(bp[-1])
    hue = rng.uniform(-0.03, 0.03)
    zbot = c0.z - crz

    def mk_col(tone, lc=None, lr=None):
        def colfn(q, d):
            under = 0.36 + 0.64 * min(1.0, max(0.0, (d.z + 0.5) / 1.3))
            rel = Vector(((q.x - c0.x) / crx, (q.y - c0.y) / crx, (q.z - c0.z) / crz)).length
            shell = 0.5 + 0.5 * min(1.0, max(0.0, (rel - 0.35) / 0.6))
            if lc is not None:
                shell *= 0.75 + 0.25 * min(1.0, (q - lc).length / lr)
            ht = 0.7 + 0.3 * min(1.0, max(0.0, (q.z - zbot) / (2 * crz)))
            a = tone * under * shell * ht
            return (a * (1.0 + hue), a, a * (0.88 - hue))
        return colfn
    # lobes: one per scaffold limb plus a crown top; each lobe is a dark core covered with small leaf clumps
    lobes = []
    for k in range(n_limbs):
        u = az0 + 2 * math.pi * k / n_limbs + rng.uniform(-0.25, 0.25)
        lobes.append((ell(u, rng.uniform(-0.35, 0.15), 0.6), crx * rng.uniform(0.44, 0.54)))
    for k in range(3):
        u = az0 + 2 * math.pi * (k + 0.5) / 3 + rng.uniform(-0.3, 0.3)
        lobes.append((ell(u, rng.uniform(0.35, 0.6), 0.5), crx * rng.uniform(0.4, 0.48)))
    lobes.append((ell(0, 1.0, 0.42) + Vector((rng.normal(0, 0.6), rng.normal(0, 0.6), 0)), crx * 0.46))
    nclump = int(16 * lod)
    ncard = int(150 * lod)

    def mk_nrm(lc, lr, lrz, own):
        def f(p, d):
            nl = Vector(((p.x - lc.x) / (lr * lr), (p.y - lc.y) / (lr * lr), (p.z - lc.z) / (lrz * lrz))).normalized()
            nc = Vector(((p.x - c0.x) / (crx * crx), (p.y - c0.y) / (crx * crx), (p.z - c0.z) / (crz * crz))).normalized()
            return tuple((nl * (0.75 - own) + nc * 0.25 + d.normalized() * own).normalized())
        return f
    for k, (lc, lr) in enumerate(lobes):
        lr_z = lr * crz / crx * 1.05
        blob(g, 'Leaves', tuple(lc), (lr * 0.86, lr * 0.86, lr_z * 0.82), seed * 50 + k, rough=0.3, freq=1.4, sub=3,
             colfn=mk_col(0.8, lc, lr), nfn=mk_nrm(lc, lr, lr_z, 0.4))
        outward = (lc - c0)
        outward.z *= 0.6
        outward = outward.normalized() if outward.length > 1e-6 else Vector((0, 0, 1))
        for j in range(nclump):
            dvec = Vector(rng.normal(0, 1, 3)).normalized()
            if dvec.dot(outward) < -0.3 and dvec.z < 0.2:
                dvec = (dvec + outward * 1.2).normalized()
            if dvec.z < -0.55:
                dvec.z *= 0.5
                dvec.normalize()
            c = lc + Vector((dvec.x * lr, dvec.y * lr, dvec.z * lr_z)) * rng.uniform(0.7, 1.02)
            rel = Vector(((c.x - c0.x) / crx, (c.y - c0.y) / crx, (c.z - c0.z) / crz)).length
            if rel > 1.02:
                c = c0 + (c - c0) * (1.02 / rel)
            sc = lr * rng.uniform(0.13, 0.38)
            blob(g, 'Leaves', tuple(c), (sc, sc * rng.uniform(0.85, 1.15), sc * rng.uniform(0.7, 0.9)),
                 seed * 1000 + k * 100 + j, rough=0.4, freq=2.4, sub=2, colfn=mk_col(rng.uniform(0.92, 1.05), lc, lr),
                 flat_bottom=c.z - sc * 0.55, nfn=mk_nrm(lc, lr, lr_z, 0.16))
        # leaf-cluster cards on the lobe surface break the outline into leaves
        nf = mk_nrm(lc, lr, lr_z, 0.0)
        cf = mk_col(1.0, lc, lr)
        for j in range(ncard):
            dvec = Vector(rng.normal(0, 1, 3)).normalized()
            if dvec.dot(outward) < -0.4:
                dvec = (dvec + outward * 1.3).normalized()
            if dvec.z < -0.6:
                dvec.z *= 0.5
                dvec.normalize()
            c = lc + Vector((dvec.x * lr, dvec.y * lr, dvec.z * lr_z)) * rng.uniform(0.85, 1.12)
            rel = Vector(((c.x - c0.x) / crx, (c.y - c0.y) / crx, (c.z - c0.z) / crz)).length
            if rel > 1.08:
                c = c0 + (c - c0) * (1.08 / rel)
            nrm = (dvec + Vector(rng.normal(0, 0.45, 3))).normalized()
            t1 = nrm.cross(Vector((0, 0, 1)))
            t1 = t1.normalized() if t1.length > 1e-3 else Vector((1, 0, 0))
            t2 = nrm.cross(t1).normalized()
            ang = rng.uniform(0, 2 * math.pi)
            a_ = t1 * math.cos(ang) + t2 * math.sin(ang)
            b_ = nrm.cross(a_).normalized()
            hs = rng.uniform(0.45, 0.72)
            P = [c - a_ * hs - b_ * hs, c + a_ * hs - b_ * hs, c + a_ * hs + b_ * hs, c - a_ * hs + b_ * hs]
            g.add(P, [[0, 1, 2, 3]], 'LeafCards', smooth=True, colors=[cf(q, dvec) for q in P],
                  uvs=[[(0, 0), (1, 0), (1, 1), (0, 1)]], normals=[nf(q, (q - lc).normalized()) for q in P])


def gate_pier(g, x, y, h=1.75):
    cbox(g, 'Brick', x, y, 0.62, 0.62, -0.4, h)
    cbox(g, 'Stone', x, y, 0.74, 0.74, h, h + 0.08)
    cbox(g, 'Stone', x, y, 0.66, 0.66, h + 0.08, h + 0.14)
    # lantern on the cap
    z = h + 0.14
    cbox(g, 'Iron', x, y, 0.22, 0.22, z, z + 0.05)
    cbox(g, 'Glow', x, y, 0.17, 0.17, z + 0.05, z + 0.40)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cbox(g, 'Iron', x + sx * 0.09, y + sy * 0.09, 0.02, 0.02, z + 0.05, z + 0.40)
    lathe(g, 'Iron', [(0.15, 0.0), (0.03, 0.14), (0.015, 0.2)], x, y, seg=4, z0=z + 0.40, caps=False, smooth=False)
    LANTERNS.append((Vector((x, y, z + 0.22)), 'post'))


def bed(g, pts, z=0.05):
    slab_from_loops(g, 'Mulch', [pts], z, -0.05)


def build_lot():
    gD = Geo('Lot_Drive')
    gB = Geo('Lot_Beds')
    gP = Geo('Lot_Plants')
    build_drive(gD)
    # landing between the bottom step and the drive
    box(gD, 'Paver', -2.95, 2.95, -11.25, -10.5, -0.1, 0.04)
    # rear terrace (U around the ell) with a seat wall
    ter = [(-6.4, MY1), (EL['x0'], MY1), (EL['x0'], EL['y1']), (EL['x1'], EL['y1']), (EL['x1'], MY1), (6.4, MY1),
           (6.4, 14.2), (-6.4, 14.2)]
    slab_from_loops(gD, 'Paver', [ter], 0.04, -0.1)
    for (a, b) in (((-6.4, 14.2), (-1.4, 14.2)), ((1.4, 14.2), (6.4, 14.2)), ((-6.4, 14.2), (-6.4, 10.0)),
                   ((6.4, 14.2), (6.4, 10.0))):
        seg_box(gD, 'Brick', (a[0], a[1], 0.23), (b[0], b[1], 0.23), 0.36, 0.46, ext=0.18)
        seg_box(gD, 'Bluestone', (a[0], a[1], 0.49), (b[0], b[1], 0.49), 0.44, 0.06, ext=0.22)
    # walk from the court to the side door stoop is the court itself; walk from the terrace to the court
    walk = [(6.4, 10.4), (16.8, 10.4), (16.8, 11.6), (6.4, 11.6)]
    slab_from_loops(gD, 'Paver', [walk], 0.035, -0.1)
    # gate piers at the two drive mouths
    r = LOOP['r']
    for sx in (-1, 1):
        for off in (-1, 1):
            gate_pier(gD, sx * r + off * 4.2, CURB_Y + 1.6)
    # island: mulch bed, clipped boxwood ring, Japanese maple, white flowers
    I = ISLAND
    bed(gB, ellipse(I['cx'], I['cy'], I['rx'], I['ry'], 56))
    ring = ellipse(I['cx'], I['cy'], I['rx'] - 0.45, I['ry'] - 0.45, 44)
    rn = ring_hedge_normals(I['cx'], I['cy'], I['rx'] - 0.45, I['ry'] - 0.45, 0.05 + 0.42 * 0.8 * 0.92 - 0.1)
    for k, (x, y) in enumerate(ring):
        boxwood(gP, x, y, 0.42, 900 + k, z0=0.05, sub=2, squash=0.8, nfn=rn)
    cbox(gP, 'CastStone', I['cx'], I['cy'], 0.80, 0.80, -0.1, 0.18)
    cbox(gP, 'CastStone', I['cx'], I['cy'], 0.56, 0.56, 0.18, 0.95)
    cbox(gP, 'CastStone', I['cx'], I['cy'], 0.70, 0.70, 0.95, 1.05)
    urn(gP, I['cx'], I['cy'], 1.05, scale=1.35, plant='Flowers', seed=31)
    for k, (x, y) in enumerate(ellipse(I['cx'], I['cy'], 1.25, 1.25, 10)):
        boxwood(gP, x, y, 0.32, 990 + k, z0=0.05, sub=2, squash=0.8)
    rng = np.random.default_rng(77)
    for k in range(16):
        a = 2 * math.pi * k / 16 + rng.uniform(-0.1, 0.1)
        rr = rng.uniform(0.45, 0.7)
        x, y = I['cx'] + math.cos(a) * (I['rx'] - 1.2) * (0.7 + 0.25 * rr), I['cy'] + math.sin(a) * (I['ry'] - 1.2) * (0.7 + 0.25 * rr)
        blob(gP, 'FlowersW', (x, y, 0.12), (0.45, 0.45, 0.2), 950 + k, rough=0.25, freq=2.5, sub=2,
             colfn=foliage_colfn(1.0, 0.0, 1.0, base=0.6), flat_bottom=0.06)
    # foundation beds and boxwoods
    beds = [
        [(2.85, -7.7), (9.0, -7.7), (9.0, -5.75), (2.85, -5.75)],               # main front right
        [(9.0, -6.5), (15.4, -6.5), (15.4, -4.75), (9.0, -4.75)],               # right wing front
        [(-9.0, -9.0), (-6.9, -9.0), (-6.9, -7.75), (-9.0, -7.75)],             # porch front left of steps
        [(-5.1, -9.0), (-2.95, -9.0), (-2.95, -7.75), (-5.1, -7.75)],           # porch front right of steps
        [(-15.6, -9.7), (-9.0, -9.7), (-9.0, -8.0), (-15.6, -8.0)],             # left wing front
        [(-16.6, -8.0), (-15.0, -8.0), (-15.0, 3.5), (-16.6, 3.5)],             # left wing side
        [(2.85, -9.6), (2.95, -9.6), (2.95, -7.7), (2.85, -7.7)],
    ]
    for b_ in beds[:6]:
        bed(gB, b_)
    k = 0
    for x in np.arange(3.6, 8.7, 1.25):
        boxwood(gP, x, -6.85, 0.55, 100 + k); k += 1
    for x in np.arange(9.8, 15.0, 1.3):
        boxwood(gP, x, -5.6, 0.55, 120 + k); k += 1
    for x in (-8.4, -7.5, -4.4, -3.5):
        boxwood(gP, x, -8.4, 0.5, 140 + k); k += 1
    for x in (-15.0, -14.1, -9.8, -8.9):
        boxwood(gP, x, -8.85, 0.55, 160 + k); k += 1
    for x in np.arange(-13.0, -10.9, 0.7):
        boxwood(gP, x, -9.15, 0.38, 170 + k, squash=0.75); k += 1
    for y in np.arange(-7.2, 3.0, 1.3):
        boxwood(gP, -15.8, y, 0.55, 180 + k); k += 1
    # larger rounded shrubs (hollies / rhododendrons) at the corners
    for (x, y, rr) in ((-16.1, -9.1, 0.95), (9.3, -6.2, 0.85), (15.0, -5.9, 0.9), (-3.3, -8.55, 0.7), (3.4, -7.3, 0.75)):
        boxwood(gP, x, y, rr, 200 + k, mat='Shrub', squash=1.05, tone=0.9); k += 1
    # flanking the drive at the steps landing
    for sx in (-1, 1):
        boxwood(gP, sx * 3.55, -10.85, 0.42, 230 + sx)
    # mature hardwoods
    for i, ((bx, by), seed, hgt, spread, tr) in enumerate(TREES):
        gt = Geo(f'Tree_Hardwood_{i + 1}')
        hardwood(gt, (bx, by), seed, hgt, spread, tr)
        TREE_GEOS.append(gt)
    return [gD, gB, gP] + TREE_GEOS


TREE_GEOS = []


# ============================================================================ build, export, render
def build_house():
    gW = Geo('House')
    gT = Geo('House_Trim')
    gR = Geo('House_Roof')
    gE = Geo('House_Entry')
    build_main(gW, gT, gR)
    build_left_wing(gW, gT, gR)
    build_porch(gW, gE, gR)
    build_right_wing(gW, gT, gR)
    build_ell(gW, gT, gR)
    build_portico(gE, gW, gR)
    return [gW, gT, gR, gE]


def render_extras():
    objs = []
    gx = Geo('Render_Street')
    cy = CURB_Y
    box(gx, 'Granite', -160, 160, cy - 0.16, cy, -0.2, 0.13)
    MAT['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('dlx_conc', kind='concrete', n=512, tile=3.0, seed=29)[0],
                                              None, 3.0), rough=0.9)
    box(gx, 'Asphalt', -160, 160, cy - 11.2, cy - 0.16, -0.2, 0.0)
    box(gx, 'Granite', -160, 160, cy - 11.36, cy - 11.2, -0.2, 0.13)
    objs.append(gx.build())
    bg = [((-31, 6), 101, 17, 14), ((-35, -18), 102, 15, 12), ((31, 9), 103, 18, 15), ((35, -16), 104, 16, 13),
          ((-12, 36), 105, 19, 15), ((10, 38), 106, 18, 14), ((-30, 30), 107, 17, 14), ((29, 32), 108, 17, 15),
          ((-48, -4), 109, 18, 15), ((47, -2), 110, 17, 15), ((-26, -58), 111, 15, 13), ((24, -60), 112, 16, 13),
          ((0, 52), 113, 20, 16), ((-46, 22), 114, 17, 14), ((45, 24), 115, 18, 15)]
    for (b, s_, h, sp) in bg:
        g = Geo(f'Render_BG_{s_}')
        hardwood(g, b, s_, h, sp, 0.45, bounds=(-400, -400, 400, 400), n_limbs=4, lod=0.6)
        objs.append(g.build())
    return objs


def export_set(objs, path, image_format='JPEG'):
    wp.finalize(objs)
    for o in objs:
        apply_custom_uvs(o)
    wp.export_glb(path, objs, image_format=image_format)
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


def setup_render(samples, res, sun_elev=8.5, sun_az=232.0):
    """Golden hour: low warm sun from the front left, a dimmed sky, a mown lawn plane (render only)."""
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=sun_elev, sun_az=sun_az, threads=2, exposure=0.35,
                           ground=False)
    sun.data.color = (1.0, 0.66, 0.40)
    sun.data.energy = 9.0
    sun.data.angle = math.radians(1.0)
    wnt = bpy.context.scene.world.node_tree
    bgn = wnt.nodes['Background']
    bgn.inputs['Strength'].default_value = 0.13
    lawn = wp.mat('RenderLawnDLX', tex=tex_lawn('dlx_lawn'), rough=0.95, normal_strength=0.6)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=250)
    g = wp.obj_from_bmesh('RenderGround', bm, lawn)
    wp.uv_box(g)
    g.location.z = -0.01
    for i, (p, kind) in enumerate(LANTERNS):
        L = bpy.data.lights.new(f'Lantern_{i}', 'POINT')
        L.energy = {'wall': 14.0, 'pendant': 22.0, 'post': 10.0}[kind]
        L.color = (1.0, 0.68, 0.38)
        L.shadow_soft_size = 0.06
        o = bpy.data.objects.new(f'Lantern_{i}', L)
        o.location = p
        bpy.context.scene.collection.objects.link(o)
    return sun


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='32 samples, 800x500 test renders')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--out', default=None, help='render folder (default: repo renders/)')
    ap.add_argument('--views', default='hero,aerial')
    ap.add_argument('--samples', type=int, default=None)
    ap.add_argument('--res', default=None)
    ap.add_argument('--hide-trees', action='store_true')
    args = ap.parse_args()

    wp.reset()
    make_materials()
    house_geos = build_house()
    lot_geos = build_lot()
    for g in house_geos + lot_geos:
        print(f'{g.name:22s} {g.tris():8d} tris  mats={g.mats}')
    house_objs = [g.build() for g in house_geos]
    lot_objs = [g.build() for g in lot_geos]

    mdir = os.path.join(REPO, 'models', 'homes')
    house_glb = os.path.join(mdir, f'{ID}.glb')
    lot_glb = os.path.join(mdir, f'{ID}-lot.glb')
    if args.no_export:
        wp.finalize(house_objs + lot_objs)
        for o in house_objs + lot_objs:
            apply_custom_uvs(o)
    else:
        th = export_set(house_objs, house_glb)
        tl = export_set(lot_objs, lot_glb, image_format='AUTO')   # keeps the leaf-card PNG (alpha); JPEGs stay JPEG
        mn, mx = bbox(house_objs)
        lmn, lmx = bbox(lot_objs)
        print(f'house bbox {tuple(round(v, 2) for v in mn)} .. {tuple(round(v, 2) for v in mx)}')
        print(f'lot   bbox {tuple(round(v, 2) for v in lmn)} .. {tuple(round(v, 2) for v in lmx)}')
        meta = {
            'id': ID, 'name': 'Delacroix house', 'address': '3064 Harbor Drive', 'neighborhood': 'Harborview',
            'residents': ['Lori Delacroix', 'Charles Delacroix', 'Madeleine Delacroix', 'Philippe Delacroix'],
            'status': "proposed (address and placement); design from the author's film still "
                      "(reference/lori-house.webp), detail from reference/board-17.jpg and board-19.jpg",
            'atlas_building_index': 23936, 'footprint_m': list(FOOT),
            'ridge_height_m': round(ZR, 2), 'top_height_m': round(mx.z, 2), 'stories': 2.5,
            'style': 'Georgian / Colonial Revival brick estate',
            'materials': ['warm red-brown brick in Flemish bond with darker burnt headers, light mortar',
                          'darker brick base with a limestone water table',
                          'dark natural slate hipped roof with lead hip and ridge caps, copper valleys',
                          'white painted dentil cornice, pediment, pilasters, portico and balustrade',
                          'black louvered shutters, 6-over-6 white sash windows, arched fanlights',
                          'limestone sills, jack-arch lintels and keystones; bluestone terrace and treads',
                          'lead-coated copper bay roof, aged copper downspouts',
                          'asphalt drive with Belgian-block (granite) edging, brick paver landing and terrace'],
            'triangles': th + tl, 'triangles_house': th, 'triangles_lot': tl,
            'files': {'house': f'models/homes/{ID}.glb', 'lot': f'models/homes/{ID}-lot.glb'},
            'file_mb': {'house': round(os.path.getsize(house_glb) / 1e6, 2),
                        'lot': round(os.path.getsize(lot_glb) / 1e6, 2)},
            'house_bbox_m': [[round(v, 2) for v in mn], [round(v, 2) for v in mx]],
            'house_extents_m': {'width_x': round(mx.x - mn.x, 2), 'depth_y': round(mx.y - mn.y, 2)},
            'lot_bbox_m': [[round(v, 2) for v in lmn], [round(v, 2) for v in lmx]],
            'lot_local_rect_m': list(LOT),
            'curb_line_local_y': CURB_Y,
            'notes': (
                f'Main block 18.0 x 11.5 m (x -9..9, y -5.75..5.75), first floor 0.60 m above grade, second floor '
                f'{FF2} m, cornice soffit {SOF} m, {PITCH:.0f} deg slate hip to a {ZR:.1f} m ridge; twin corbelled end '
                f'chimneys to {CH_TOP} m. The Atlas height (8.0 m) is too low for a 2.5-story Georgian house with the '
                f'tall roof in the photo, so the ridge is about {ZR / 8 * 100 - 100:.0f}% higher. The pavilion projects '
                f'1.0 m; the portico, terrace and steps reach y = -10.5 (1.1 m beyond the footprint). Wings make the '
                f'house about 30 m wide: the 1.5-story front-gabled left wing (x -15..-9) and the two-story hipped right '
                f'wing (x 9..15). From the photo: brick, dark slate hip, tall corbelled chimney, white columned portico '
                f'with balustraded balcony, pedimented pavilion with an arched fanlight rising into the pediment, black '
                f'shutters, front-gabled left wing, the shed-roofed porch between the wing and the portico, lanterns, '
                f'arched first-floor windows on the right, attic dormers, curving drive. Interpretations: the side, rear '
                f'and roof plan (rear ell, dormers front and back, side entry, chimney positions), the box bay on the '
                f'wing (after board-19), Flemish bond, the drive layout (a horseshoe with a planted island and a spur to '
                f'a parking court at the right wing), gate piers, rear terrace and the three hardwoods. The lot GLB has '
                f'no lawn; its drive meets the curb line exactly at two flared mouths.')}
        with open(os.path.join(mdir, f'{ID}.json'), 'w') as f:
            json.dump(meta, f, indent=1)
        print(json.dumps({k: meta[k] for k in ('triangles', 'triangles_house', 'triangles_lot', 'file_mb',
                                               'ridge_height_m', 'house_bbox_m')}))

    if args.no_render:
        return
    out = args.out or os.path.join(REPO, 'renders')
    samples = args.samples or (32 if args.quick else 128)
    res = (800, 500) if args.quick else (1600, 1000)
    if args.res:
        res = tuple(int(v) for v in args.res.split('x'))
    extras = render_extras()
    wp.finalize(extras)
    for o in extras:
        apply_custom_uvs(o)
    setup_render(samples, res)
    if args.hide_trees:
        for o in bpy.context.scene.objects:
            if o.name.startswith(('Tree_', 'Render_BG')):
                o.hide_render = True
    cams = {'hero': (CAM_HERO, f'{ID}.jpg'), 'aerial': (CAM_AERIAL, f'{ID}-aerial.jpg'),
            'front': (CAM_FRONT, f'{ID}-front.jpg'), 'left': (CAM_LEFT, f'{ID}-left.jpg'),
            'rear': (CAM_REAR, f'{ID}-rear.jpg')}
    for v in (args.views.split(';') if ';' in args.views or args.views.startswith('cam:') else args.views.split(',')):
        if v.startswith('cam:'):
            # cam:name:x,y,z:tx,ty,tz:lens
            _, nm, lo, ta, le = v.split(':')
            c = dict(loc=tuple(float(t) for t in lo.split(',')), target=tuple(float(t) for t in ta.split(',')),
                     lens=float(le))
            cams[nm] = (c, f'{ID}-{nm}.jpg')
            v = nm
        c, fn = cams[v]
        wp.camera(c['loc'], c['target'], c['lens'])
        wp.render(os.path.join(out, fn))


if __name__ == '__main__':
    main()
