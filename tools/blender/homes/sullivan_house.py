#!/usr/bin/env python3
"""Sullivan house, 2639 Bay Drive (hero home #8, proposed; next door to the Rossis).

A coastal shingle-style cottage, one and a half stories: weathered silver-grey cedar shakes, white trim,
a steep 12:12 side-gable roof in dark grey architectural shingles with three gabled front dormers, a
gabled entry porch on square posts, an exterior brick chimney on the right gable end, a raised
foundation, and a screened side porch on the left (shingled knee wall, screen panels, lattice skirt).
The lot GLB carries the crushed-shell driveway and the front walk (both to the curb line), foundation
beds with hydrangeas and grasses, a mailbox and one young live oak. With --bay it also renders
renders/bay-drive-sullivan-rossi.jpg, placing the Rossi GLBs at their true relative position.

Run (rebuilds GLBs, JSON and the final renders):
    python3 tools/blender/homes/sullivan_house.py
Iteration renders (24 samples, 640 x 400, into a scratch folder):
    python3 tools/blender/homes/sullivan_house.py --quick --out /path/to/scratch
Other flags: --no-render, --views hero,aerial,bay
Set WP_TEX_DIR to a private scratch folder (textures are generated there).

Note on docs/site-specs.json: its neighbors_local x values are mirrored (the generator uses
(n.y, -n.x), the viewer's LEFT). Corrected here: the Rossi house (21164) is on the LEFT at (-40.07, 0.97), rotated -9.5 deg.
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

ID = 'sullivan-house'
REPO = wp.REPO
# ============================================================================ shared kit
# (mesh builder, primitives and texture helpers adapted from monet_williams_house.py; kept inline so
#  this script stays self-contained apart from wp.py)
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

def slab(g, mat, pts, z_top, z_bot=-0.1):
    extrude(g, mat, WORLD, pts, z_bot, z_top)


def ngon(cx, cy, r, n=18, jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return [(cx + r * (1 + rng.uniform(-jitter, jitter)) * math.cos(2 * math.pi * i / n),
             cy + r * (1 + rng.uniform(-jitter, jitter)) * math.sin(2 * math.pi * i / n)) for i in range(n)]

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



# ---------------------------------------------------------------------------- extra textures
def tex_roof2(key, color='#5d5853', seed=31, algae=0.18):
    """Architectural asphalt shingles, 4 m tile, with broad tone drift and faint algae streaks."""
    alb_p, nrm_p, tile = wp.tex_shingles(key, color=color, n=2048, tile=4.0, seed=seed)
    Image.open(nrm_p).resize((1024, 1024), Image.LANCZOS).save(nrm_p, quality=88)
    a = np.asarray(Image.open(alb_p)).astype(np.float32) / 255
    n = a.shape[0]
    rng = np.random.default_rng(seed + 1)
    big = wp._noise(n, 3, rng, 4)
    streak = wp._noise(n, 12, rng, 3)
    st = streak.copy()
    for s in (6, 12, 24, 48, 96, 160):
        st += np.roll(streak, s, 0)
    st = (st - st.min()) / (st.max() - st.min())
    alg = np.clip((st - 0.6) * 2.5, 0, 1) * algae
    a = a * (0.9 + 0.2 * big)[..., None] * (1 - alg[..., None])
    a[..., 0] *= (0.98 + 0.05 * big)
    a[..., 2] *= (1.03 - 0.05 * big)
    Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).save(alb_p, quality=88)
    return alb_p, nrm_p, tile


def tex_shakes(key, color, n=1024, tile=1.2, exposure=0.15, seed=91, var=0.16, painted=False):
    """Cedar shingles (shakes) in courses: random widths 9-30 cm, dark keyways, butt shadow lines,
    vertical grain; weathered (var high) or painted (painted=True: low variation, soft grain)."""
    rng = np.random.default_rng(seed)
    px = n / tile
    rows = int(round(tile / exposure)); exposure = tile / rows
    y, x = np.mgrid[0:n, 0:n] / px
    r = (y / exposure).astype(int) % rows
    t = (y % exposure) / exposure
    ids = np.zeros((n, n), np.int32)
    gap = np.zeros((n, n), bool)
    for k in range(rows):
        cuts, s = [], rng.uniform(0, 0.1)
        while s < tile:
            cuts.append(s); s += rng.uniform(0.09, 0.30)
        cuts = np.array(cuts)
        m = r == k
        xx = x[m]
        idx = np.searchsorted(cuts, xx) % len(cuts)
        ids[m] = idx + k * 64
        lx = np.min(np.abs(xx[:, None] - np.concatenate([cuts, [tile]])[None, :]), axis=1)
        gap[m] = lx < 0.0045
    cell = np.random.default_rng(seed + 5).random(rows * 64 + 64).astype(np.float32)[ids]
    cell2 = np.random.default_rng(seed + 6).random(rows * 64 + 64).astype(np.float32)[ids]
    f = wp._noise(n, 70 * tile, rng, 2)
    gr = f.copy()
    for s in range(1, 14):
        gr += np.roll(f, s * 3, 0)
    gr = (gr - gr.min()) / (gr.max() - gr.min())
    big = wp._noise(n, 3 * tile, rng, 3)
    base = wp._rgb(color)
    tone = 1 + (cell - 0.5) * 2 * var
    shade = 0.68 + 0.32 * np.clip(t * 5, 0, 1)
    if painted:
        alb = base[None, None, :] * (tone * shade * (0.96 + 0.06 * gr) * (0.95 + 0.1 * big))[..., None]
    else:
        brown = np.array([0.42, 0.33, 0.25], np.float32)
        bm = np.clip((cell2 - 0.78) * 3.5, 0, 0.6)[..., None]
        c = base[None, None, :] * (1 - bm) + brown * bm
        alb = c * (tone * shade * (0.84 + 0.3 * gr) * (0.9 + 0.2 * big))[..., None]
    alb = np.where(gap[..., None], alb * 0.35, alb)
    h = t * 0.8 + gr * 0.25 - gap * 0.6
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 3.0), key + '_n'), tile


def tex_chainlink(key, n=512, tile=0.5):
    """Galvanised chain-link mesh (5 cm diamonds) as RGBA PNG; alpha masks the holes."""
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    p = 0.05
    a = ((x + y) % p) / p
    b = ((x - y) % p) / p
    w = 0.0032 / p * 1.414
    wire = (np.minimum(a, 1 - a) < w) | (np.minimum(b, 1 - b) < w)
    rng = np.random.default_rng(3)
    nz = wp._noise(n, 8, rng, 3)
    c = np.array([0.62, 0.64, 0.64], np.float32)[None, None, :] * (0.8 + 0.3 * nz[..., None])
    rgba = np.concatenate([c, wire[..., None].astype(np.float32)], -1)
    path = os.path.join(wp.TEX_DIR, key + '.png')
    Image.fromarray(np.clip(rgba * 255, 0, 255).astype(np.uint8), 'RGBA').save(path)
    return path, tile


def mat_masked(name, png, tile, rough=0.5, metal=0.6):
    """Alpha-clipped material (chain-link, screens) that exports as glTF alphaMode MASK."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    bs = nt.nodes.get('Principled BSDF')
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = wp._img(png)
    nt.links.new(t.outputs['Color'], bs.inputs['Base Color'])
    rnd = nt.nodes.new('ShaderNodeMath'); rnd.operation = 'ROUND'
    nt.links.new(t.outputs['Alpha'], rnd.inputs[0])
    nt.links.new(rnd.outputs[0], bs.inputs['Alpha'])
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Metallic'].default_value = metal
    try:
        m.surface_render_method = 'DITHERED'
    except Exception:
        pass
    m.use_backface_culling = False
    m['tile'] = float(tile)
    return m


# ---------------------------------------------------------------------------- windows, gutters
def sash2(g, F, uc, sill, w, h, top=(3, 2), bot=(1, 1), casing=0.1, shut=False, shut_w=None, frame='Trim',
          apron=True, head=True):
    """Double-hung window in a hole (uc +- w/2, sill..sill+h) with separate upper/lower light grids
    (6-over-1 = top (3, 2), bot (1, 1)); casing, sill, apron, head cap, optional shutters."""
    u0, u1, z0, z1 = uc - w / 2, uc + w / 2, sill, sill + h
    c = casing
    if casing:
        fbox(g, 'Trim', F, u0 - c, u0, z0, z1, -0.005, 0.022)
        fbox(g, 'Trim', F, u1, u1 + c, z0, z1, -0.005, 0.022)
        if head:
            fbox(g, 'Trim', F, u0 - c - 0.01, u1 + c + 0.01, z1, z1 + 0.13, -0.005, 0.026)
            fbox(g, 'Trim', F, u0 - c - 0.03, u1 + c + 0.03, z1 + 0.13, z1 + 0.16, -0.005, 0.05)
        else:
            fbox(g, 'Trim', F, u0 - c, u1 + c, z1, z1 + c, -0.005, 0.022)
    fbox(g, 'Trim', F, u0 - c - 0.03, u1 + c + 0.03, z0 - 0.04, z0, -0.11, 0.05)
    if apron:
        fbox(g, 'Trim', F, u0 - c + 0.03, u1 + c - 0.03, z0 - 0.14, z0 - 0.04, -0.005, 0.02)
    zm = (z0 + z1) / 2
    for (zb, zt, da, db, gd, b_, t_, grid) in ((zm - 0.02, z1, -0.075, -0.04, -0.06, 0.035, 0.05, top),
                                               (z0, zm + 0.02, -0.115, -0.08, -0.10, 0.07, 0.035, bot)):
        fbox(g, frame, F, u0, u0 + 0.05, zb, zt, da, db)
        fbox(g, frame, F, u1 - 0.05, u1, zb, zt, da, db)
        fbox(g, frame, F, u0 + 0.05, u1 - 0.05, zb, zb + b_, da, db)
        fbox(g, frame, F, u0 + 0.05, u1 - 0.05, zt - t_, zt, da, db)
        iu0, iu1, iz0, iz1 = u0 + 0.05, u1 - 0.05, zb + b_, zt - t_
        poly(g, 'Glass', [F.p(iu0, iz0, gd), F.p(iu1, iz0, gd), F.p(iu1, iz1, gd), F.p(iu0, iz1, gd)], facing=F.N)
        cols, rows = grid
        for i in range(1, cols):
            uu = iu0 + (iu1 - iu0) * i / cols
            fbox(g, frame, F, uu - 0.01, uu + 0.01, iz0, iz1, da + 0.006, db - 0.004)
        for j in range(1, rows):
            zz = iz0 + (iz1 - iz0) * j / rows
            fbox(g, frame, F, iu0, iu1, zz - 0.01, zz + 0.01, da + 0.006, db - 0.004)
    if shut:
        sw = shut_w or (w / 2 - 0.02)
        shutter(g, F, u0 - c - 0.006 - sw, u0 - c - 0.006, z0 + 0.006, z1)
        shutter(g, F, u1 + c + 0.006, u1 + c + 0.006 + sw, z0 + 0.006, z1)


def win_group(g, F, uc, sill, w, h, n, mull=0.12, top=(3, 2), bot=(1, 1), casing=0.1, frame='Trim'):
    """n mulled double-hung units sharing one casing; returns the hole (u0, u1, z0, z1)."""
    tot = n * w + (n - 1) * mull
    u0 = uc - tot / 2
    c = casing
    z1 = sill + h
    fbox(g, 'Trim', F, u0 - c, u0, sill, z1, -0.005, 0.022)
    fbox(g, 'Trim', F, u0 + tot, u0 + tot + c, sill, z1, -0.005, 0.022)
    fbox(g, 'Trim', F, u0 - c - 0.01, u0 + tot + c + 0.01, z1, z1 + 0.13, -0.005, 0.026)
    fbox(g, 'Trim', F, u0 - c - 0.03, u0 + tot + c + 0.03, z1 + 0.13, z1 + 0.16, -0.005, 0.05)
    fbox(g, 'Trim', F, u0 - c - 0.03, u0 + tot + c + 0.03, sill - 0.04, sill, -0.11, 0.05)
    fbox(g, 'Trim', F, u0 - c + 0.03, u0 + tot + c - 0.03, sill - 0.14, sill - 0.04, -0.005, 0.02)
    for k in range(n):
        a = u0 + k * (w + mull)
        sash2(g, F, a + w / 2, sill, w, h, top, bot, casing=0, frame=frame, apron=False)
        if k < n - 1:
            fbox(g, 'Trim', F, a + w, a + w + mull, sill, z1, -0.13, 0.022)
    return (u0, u0 + tot, sill, z1)


def gutter(g, p0, p1, z, out, size=0.13):
    """K-style gutter along the eave from p0 to p1 (xy), top at z, hanging on the side `out` (unit xy)."""
    p0, p1 = Vector((p0[0], p0[1], 0)), Vector((p1[0], p1[1], 0))
    U = (p1 - p0).normalized()
    N = Vector((out[0], out[1], 0)).normalized()
    if U.cross(N).z > 0:
        p0, p1 = p1, p0
        U = -U
    F = Fr((p0.x, p0.y, z), U, N)
    L = (p1 - p0).length
    pr = [(0.0, 0.0), (0.0, -0.11), (0.09, -0.115), (0.115, -0.07), (0.105, -0.05), (0.13, -0.015), (0.125, 0.0)]
    S = F.side()
    pts = [(d, zz) for d, zz in pr]
    extrude(g, 'Gutter', S, pts, -L, 0.0)


def downspout(g, x, y, z_top, out, wall_off=0.06, z_bot=0.06, kick=None):
    """Rectangular downspout from a gutter (outlet at x, y, z_top, `out` = outward normal) down the wall."""
    ox, oy = out
    sx = abs(oy) * 0.075 + abs(ox) * 0.055
    sy = abs(ox) * 0.075 + abs(oy) * 0.055
    gx, gy = x + ox * 0.07, y + oy * 0.07
    wx, wy = x + ox * wall_off, y + oy * wall_off
    seg_box(g, 'Gutter', (gx, gy, z_top - 0.1), (wx, wy, z_top - 0.45), 0.075, 0.055, up=(ox, oy, 0), d0=-0.0275)
    cbox(g, 'Gutter', wx, wy, sx, sy, z_bot + 0.3, z_top - 0.42)
    kx, ky = kick or out
    seg_box(g, 'Gutter', (wx, wy, z_bot + 0.32), (wx + kx * 0.35, wy + ky * 0.35, z_bot), 0.075, 0.055,
            up=(kx, ky, 0), d0=-0.0275)
    cbox(g, 'Concrete', wx + kx * 0.6, wy + ky * 0.6, 0.3 + abs(kx) * 0.3, 0.3 + abs(ky) * 0.3, -0.02, 0.04)


def gable_roof(g, x0, x1, y0, y1, z_e, pitch, ov_e=0.4, ov_r=0.3, along='x', th=0.16, caps=True, mat='Roof'):
    """Gable roof over the wall rectangle; ridge along x (eaves front/back) or y. The slab's underside passes
    through the wall line at z_e. Returns (faces, ridge_z_top)."""
    t = math.tan(math.radians(pitch))
    lift = th / math.cos(math.radians(pitch))
    if along == 'x':
        half = (y1 - y0) / 2
        yc = (y0 + y1) / 2
        zr = z_e + half * t + lift
        ze = z_e + lift - ov_e * t
        A = [(x0 - ov_r, y0 - ov_e, ze), (x1 + ov_r, y0 - ov_e, ze), (x1 + ov_r, yc, zr), (x0 - ov_r, yc, zr)]
        B = [(x0 - ov_r, y1 + ov_e, ze), (x0 - ov_r, yc, zr), (x1 + ov_r, yc, zr), (x1 + ov_r, y1 + ov_e, ze)]
    else:
        half = (x1 - x0) / 2
        xc = (x0 + x1) / 2
        zr = z_e + half * t + lift
        ze = z_e + lift - ov_e * t
        A = [(x0 - ov_e, y0 - ov_r, ze), (xc, y0 - ov_r, zr), (xc, y1 + ov_r, zr), (x0 - ov_e, y1 + ov_r, ze)]
        B = [(x1 + ov_e, y0 - ov_r, ze), (x1 + ov_e, y1 + ov_r, ze), (xc, y1 + ov_r, zr), (xc, y0 - ov_r, zr)]
    roof_slab(g, A, th=th, top=mat, edge='Trim', bottom='Soffit')
    roof_slab(g, B, th=th, top=mat, edge='Trim', bottom='Soffit')
    if caps:
        roof_caps(g, [A, B])
    return [A, B], zr


def vent_louver(g, F, uc, zc, w=0.5, h=0.4):
    """Gable-end louvred attic vent (rectangular) mounted on the wall face."""
    fbox(g, 'Trim', F, uc - w / 2 - 0.08, uc + w / 2 + 0.08, zc - h / 2 - 0.08, zc + h / 2 + 0.08, -0.005, 0.03)
    k = int(h / 0.055)
    for i in range(k):
        z = zc - h / 2 + (i + 0.5) * h / k
        extrude(g, 'Trim', F.side(), [(0.03, z - 0.02), (0.06, z + 0.02), (0.055, z + 0.03), (0.025, z - 0.01)],
                -(uc + w / 2), -(uc - w / 2))
    poly(g, 'Crawl', [F.p(uc - w / 2, zc - h / 2, 0.031), F.p(uc + w / 2, zc - h / 2, 0.031),
                      F.p(uc + w / 2, zc + h / 2, 0.031), F.p(uc - w / 2, zc + h / 2, 0.031)], facing=F.N)


# ---------------------------------------------------------------------------- trees
def tree(g, base, seed, H=12.0, spread=10.0, trunk_r=0.28, fork=3.2, n_limbs=5, n_clumps=230, clump=0.55,
         leaf='Leaves', bark='Bark', multi=1, flower=None, flower_frac=0.0, bounds=None, avoid=None, vase=0.0):
    """Broadleaf tree: tapered trunk(s), scaffold limbs, twigs, and many small separate leaf clumps (flattened
    sprays with gaps between them, darker inside and underneath). bounds = (x0, y0, x1, y1) keeps clumps
    inside the lot; avoid(x, y, z) -> True rejects a clump (roofs)."""
    rng = np.random.default_rng(seed)
    bx, by = base
    R = spread / 2
    cz = fork + (H - fork) * 0.52
    rz = (H - fork) * 0.55
    nfn = crown_normals((bx, by, cz - rz * 0.2), (R, R, rz), 0.55)
    limb_pts = []
    stems = []
    for s in range(multi):
        if multi > 1:
            a = 2 * math.pi * s / multi + rng.uniform(-0.4, 0.4)
            off = (math.cos(a) * 0.12, math.sin(a) * 0.12)
            lean = (math.cos(a) * (0.5 + vase), math.sin(a) * (0.5 + vase))
            r0 = trunk_r * rng.uniform(0.75, 1.0)
        else:
            off, lean, r0 = (0, 0), (rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)), trunk_r
        pts, rad = [], []
        for k in range(7):
            t = k / 6
            z = -0.45 + (fork + 0.45) * t
            w = max(0.0, z) / fork
            pts.append(Vector((bx + off[0] + lean[0] * w ** 1.5 + 0.05 * math.sin(5 * t + seed + s),
                               by + off[1] + lean[1] * w ** 1.5 + 0.05 * math.cos(4 * t + seed), z)))
            rad.append(r0 * (1.25 if k == 0 else (1.12 if k == 1 else 1.0 - 0.18 * t)))
        tube(g, bark, pts, rad, seg=10 if multi == 1 else 7)
        stems.append((pts[-1], rad[-1]))
    # scaffold limbs
    for i in range(n_limbs):
        top, rr = stems[i % len(stems)]
        az = 2 * math.pi * i / n_limbs + rng.uniform(-0.35, 0.35)
        el = math.radians(rng.uniform(35, 62))
        L = R * rng.uniform(0.75, 0.95) / max(0.4, math.cos(el)) * 0.75
        P = [Vector(top)]
        d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
        p = Vector(top)
        for k in range(5):
            d = (d + Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), -0.06 * k))).normalized()
            p = p + d * (L / 5)
            P.append(p.copy())
        radii = [rr * 0.72 * (1 - 0.8 * k / 5) + 0.02 for k in range(6)]
        tube(g, bark, P, radii, seg=6)
        limb_pts.extend([(q, radii[k]) for k, q in enumerate(P) if k >= 1])
    # leaf clumps: points in the crown shell
    placed = 0
    tries = 0
    centers = []
    while placed < n_clumps and tries < n_clumps * 30:
        tries += 1
        v = Vector(rng.normal(0, 1, 3))
        v.normalize()
        rr = rng.uniform(0.2, 1.0) ** 0.45
        if v.z < -0.55:
            continue
        q = Vector((bx + v.x * R * rr, by + v.y * R * rr, cz + v.z * rz * rr))
        if q.z < fork + 0.6:
            continue
        if bounds and not (bounds[0] + 0.6 < q.x < bounds[2] - 0.6 and bounds[1] + 0.6 < q.y < bounds[3] - 0.6):
            continue
        if avoid and avoid(q.x, q.y, q.z):
            continue
        if any((q - c).length < clump * 0.45 for c in centers[-60:]):
            continue
        centers.append(q)
        placed += 1
    ccen, crad = (bx, by, cz - rz * 0.15), (R, R, rz)
    for k, q in enumerate(centers):
        d = q - Vector((bx, by, cz))
        inner = min(1.0, Vector((d.x / R, d.y / R, d.z / rz)).length)
        s = clump * rng.uniform(0.75, 1.25) * (0.85 + 0.3 * inner)
        is_fl = flower and rng.random() < flower_frac
        leaf_cards(g, flower if is_fl else leaf, q, s, rng, ccen, crad, inner, tone=rng.uniform(0.85, 1.12),
                   hue=rng.uniform(-0.04, 0.05), ncard=3)
        lp, lr = min(limb_pts, key=lambda t: (t[0] - q).length)
        if (lp - q).length > 0.3 and k % 2 == 0:
            tq = lp + (q - lp) * 0.8
            tube(g, bark, [lp, tq], [max(0.022, lr * 0.45), 0.015], seg=4, cap_end=False)
    return centers


def shrub_at(g, mat, c, size, seed, z=0.0, tone=1.0):
    n0 = len(g.V)
    shrub(g, mat, c, size, seed, tone)
    if z:
        for i in range(n0, len(g.V)):
            v = g.V[i]
            g.V[i] = (v[0], v[1], v[2] + z)


def potted(g, x, y, z=0.0, r=0.2, h=0.32, mat='Terracotta', plant='Plants', seed=0, tone=1.0):
    lathe(g, mat, [(0.0, z), (r * 0.72, z), (r * 0.9, z + h * 0.82), (r, z + h * 0.84), (r, z + h), (r * 0.9, z + h),
                   (0.0, z + h - 0.03)], x, y, seg=12, caps=False)
    shrub_at(g, plant, (x, y), (r * 1.15, r * 1.15, h * 1.4), seed, z=z + h - 0.12, tone=tone)


def mailbox_post(g, x, y, ang=0.0):
    cbox(g, 'PostWood', x, y, 0.1, 0.1, -0.6, 1.05)
    F = Fr((x, y, 0), (math.cos(ang), math.sin(ang), 0), (math.sin(ang), -math.cos(ang), 0))
    fbox(g, 'PostWood', F, -0.08, 0.08, 1.05, 1.1, -0.28, 0.2)
    pts = [(-0.085, 1.1), (0.085, 1.1), (0.085, 1.2)] + [(0.085 * math.cos(math.pi * k / 6), 1.2 + 0.085 * math.sin(math.pi * k / 6)) for k in range(1, 6)] + [(-0.085, 1.2)]
    extrude(g, 'MailMetal', F, pts, -0.26, 0.22)


# ---------------------------------------------------------------------------- render helpers
def setup_render(samples, res, sun_az=212, sun_elev=46, exposure=0.4):
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=sun_elev, sun_az=sun_az, threads=2, exposure=exposure)
    sun.data.color = (1.0, 0.94, 0.84)
    sun.data.energy = 4.4
    sun.data.angle = math.radians(1.5)
    cy_ = bpy.context.scene.cycles          # keep CPU finals affordable on a shared 4-core box
    cy_.max_bounces, cy_.diffuse_bounces, cy_.glossy_bounces = 6, 3, 3
    cy_.transmission_bounces, cy_.transparent_max_bounces = 4, 8
    cy_.use_adaptive_sampling, cy_.adaptive_threshold = True, 0.02
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
    return sun


def street_geo(name, curb_y, x0=-90, x1=90, width=9.0, frame=None):
    """Render-only street: curb (15 cm) + gutter pan + asphalt, along local x at curb_y."""
    if 'Asphalt' not in MAT:
        MAT['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('k_asphalt', kind='asphalt', tile=4.0), rough=0.9)
    if 'Concrete' not in MAT:
        MAT['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('k_conc', kind='concrete', n=512, tile=3.0, seed=23)[0], None, 3.0), rough=0.9)
    gx = Geo(name)
    cy = curb_y
    slab(gx, 'Concrete', [(x0, cy - 0.15), (x1, cy - 0.15), (x1, cy + 0.0), (x0, cy + 0.0)], 0.12)
    slab(gx, 'Concrete', [(x0, cy - 0.6), (x1, cy - 0.6), (x1, cy - 0.15), (x0, cy - 0.15)], 0.0)
    slab(gx, 'Asphalt', [(x0, cy - width - 0.6), (x1, cy - width - 0.6), (x1, cy - 0.6), (x0, cy - 0.6)], 0.0)
    return gx


def check_lot(objs, rect, label):
    mn, mx = bbox(objs)
    x0, y0, x1, y1 = rect
    ok = mn.x >= x0 - 0.01 and mx.x <= x1 + 0.01 and mn.y >= y0 - 0.01 and mx.y <= y1 + 0.01
    print(f'{label} bbox x {mn.x:.2f}..{mx.x:.2f} y {mn.y:.2f}..{mx.y:.2f} z {mn.z:.2f}..{mx.z:.2f} '
          f'inside lot {rect}: {ok}')
    return mn, mx


# ---------------------------------------------------------------------------- leaf-card foliage
def tex_leafcard(key, color, n=512, seed=5, count=900, lsize=0.06, flowers=None, ffrac=0.0, spread=0.23):
    """RGBA leaf-spray texture: a few hundred overlapping leaves (random size, angle and tone) clustered
    toward the card centre; alpha masks the gaps. Flowers (optional) are small round clusters."""
    rng = np.random.default_rng(seed)
    img = np.zeros((n, n, 4), np.float32)
    base = wp._rgb(color)
    fl = wp._rgb(flowers) if flowers else None
    for i in range(count):
        r = abs(rng.normal(0, spread))
        a = rng.uniform(0, 2 * math.pi)
        cx, cy = 0.5 + r * math.cos(a), 0.5 + r * math.sin(a)
        if not (0.05 < cx < 0.95 and 0.05 < cy < 0.95):
            continue
        is_f = fl is not None and rng.random() < ffrac
        L = lsize * rng.uniform(0.65, 1.3) * (0.8 if is_f else 1.0)
        Wd = L * (0.95 if is_f else rng.uniform(0.38, 0.5))
        ang = rng.uniform(0, math.pi)
        tone = rng.uniform(0.55, 1.2)
        hue = rng.uniform(-0.06, 0.06)
        c = (fl * rng.uniform(0.8, 1.1)) if is_f else base * tone * np.array([1 + hue, 1.0, 1 - hue])
        R = int(L * n) + 2
        x0, y0 = int(cx * n) - R, int(cy * n) - R
        yy, xx = np.mgrid[0:2 * R, 0:2 * R]
        px = (xx + x0 + 0.5) / n - cx
        py = (yy + y0 + 0.5) / n - cy
        ca, sa = math.cos(ang), math.sin(ang)
        lx = (px * ca + py * sa) / L
        ly = (-px * sa + py * ca) / Wd
        if is_f:
            m = lx * lx + ly * ly < 1
            shade = 0.85 + 0.15 * np.clip(1 - (lx * lx + ly * ly), 0, 1)
        else:
            m = (np.abs(ly) < (1 - lx * lx) ** 1.2) & (np.abs(lx) < 1)
            shade = 0.82 + 0.18 * (lx + 1) / 2 - 0.12 * (np.abs(ly) < 0.08)
        ys, xs = slice(max(0, y0), min(n, y0 + 2 * R)), slice(max(0, x0), min(n, x0 + 2 * R))
        mm = m[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
        sh = shade[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0] if np.ndim(shade) else shade
        sub = img[ys, xs]
        col = c[None, None, :] * (sh[..., None] if np.ndim(sh) else sh)
        sub[..., :3] = np.where(mm[..., None], col, sub[..., :3])
        sub[..., 3] = np.where(mm, 1.0, sub[..., 3])
        img[ys, xs] = sub
    # gentle darkening of what lies under other leaves is implicit; fill transparent rgb to avoid halos
    rgb = img[..., :3]
    avg = rgb[img[..., 3] > 0].mean(0) if (img[..., 3] > 0).any() else base
    rgb[img[..., 3] == 0] = avg
    path = os.path.join(wp.TEX_DIR, key + '.png')
    Image.fromarray(np.clip(img * 255, 0, 255).astype(np.uint8), 'RGBA').save(path)
    return path


def mat_leafcard(name, png, rough=0.6):
    """Alpha-clipped, double-sided leaf-card material: texture x vertex colour (COLOR_0), alpha MASK."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    bs = nt.nodes.get('Principled BSDF')
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = wp._img(png)
    ca = nt.nodes.new('ShaderNodeVertexColor'); ca.layer_name = 'Col'
    mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 1.0
    nt.links.new(t.outputs['Color'], mix.inputs[6])
    nt.links.new(ca.outputs['Color'], mix.inputs[7])
    nt.links.new(mix.outputs[2], bs.inputs['Base Color'])
    rnd = nt.nodes.new('ShaderNodeMath'); rnd.operation = 'ROUND'
    nt.links.new(t.outputs['Alpha'], rnd.inputs[0])
    nt.links.new(rnd.outputs[0], bs.inputs['Alpha'])
    bs.inputs['Roughness'].default_value = rough
    try:
        bs.inputs['Specular IOR Level'].default_value = 0.35
    except Exception:
        pass
    try:
        m.surface_render_method = 'DITHERED'
    except Exception:
        pass
    m.use_backface_culling = False
    m['tile'] = 1.0
    return m


def leaf_cards(g, mat, q, s, rng, ccen, crad, inner, tone=1.0, hue=0.0, ncard=3, own=0.25):
    """Three crossed alpha leaf cards around q; normals bent outward from the crown, AO in vertex colour."""
    cx, cy, cz = ccen
    rx, ry, rz = crad
    for k in range(ncard):
        if k == 0:
            nrm = Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 1)).normalized()
        else:
            a = rng.uniform(0, 2 * math.pi)
            nrm = Vector((math.cos(a), math.sin(a), rng.uniform(-0.5, 0.5))).normalized()
        t1 = nrm.cross(Vector((0, 0, 1)) if abs(nrm.z) < 0.9 else Vector((1, 0, 0))).normalized()
        rot = rng.uniform(0, 2 * math.pi)
        t1 = (t1 * math.cos(rot) + nrm.cross(t1) * math.sin(rot)).normalized()
        t2 = nrm.cross(t1)
        h = s * rng.uniform(0.8, 1.2) / 2
        P = [q + (-t1 - t2) * h, q + (t1 - t2) * h, q + (t1 + t2) * h, q + (-t1 + t2) * h]
        N, C = [], []
        for p in P:
            d = Vector(((p.x - cx) / rx, (p.y - cy) / ry, (p.z - cz) / rz))
            cn = Vector(((p.x - cx) / (rx * rx), (p.y - cy) / (ry * ry), (p.z - cz) / (rz * rz))).normalized()
            N.append(tuple((cn * (1 - own) + nrm * own).normalized()))
            under = 0.5 + 0.5 * min(1.0, max(0.0, (d.z + 0.7) / 1.4))
            ao = tone * under * (0.5 + 0.5 * min(1.0, d.length))
            C.append((ao * (1 + hue), ao, ao * (1 - hue)))
        g.add(P, [[0, 1, 2, 3]], mat, smooth=True, colors=C, uvs=[[(0, 0), (1, 0), (1, 1), (0, 1)]], normals=N)


# ---------------------------------------------------------------------------- shared house + lot parts
def wall_frames(x0, x1, y0, y1):
    return dict(front=(Fr((x0, y0, 0), (1, 0, 0), (0, -1, 0)), x1 - x0),
                right=(Fr((x1, y0, 0), (0, 1, 0), (1, 0, 0)), y1 - y0),
                back=(Fr((x1, y1, 0), (-1, 0, 0), (0, 1, 0)), x1 - x0),
                left=(Fr((x0, y1, 0), (0, -1, 0), (-1, 0, 0)), y1 - y0))


def foundation(g, x0, x1, y0, y1, z_top, vents=()):
    e = 0.03
    box(g, 'Brick', x0 - e, x1 + e, y0 - e, y1 + e, -0.6, z_top)
    box(g, 'Trim', x0 - e - 0.005, x1 + e + 0.005, y0 - e - 0.005, y1 + e + 0.005, z_top - 0.01, z_top + 0.03)
    for F, u in vents:
        fbox(g, 'Crawl', F, u - 0.2, u + 0.2, 0.12, 0.3, 0.031, 0.036)
        fbox(g, 'Metal', F, u - 0.21, u + 0.21, 0.11, 0.12, 0.03, 0.04)


def column(g, x, y, z0, z1, s=0.2):
    cbox(g, 'Trim', x, y, s + 0.08, s + 0.08, z0, z0 + 0.22)
    cbox(g, 'Trim', x, y, s, s, z0 + 0.22, z1 - 0.14)
    cbox(g, 'Trim', x, y, s + 0.06, s + 0.06, z1 - 0.14, z1 - 0.1)
    cbox(g, 'Trim', x, y, s + 0.09, s + 0.09, z1 - 0.1, z1)


def railing(g, F, u0, u1, zf, top=0.86, pitch=0.11):
    L = u1 - u0
    fbox(g, 'Trim', F, u0, u1, zf + 0.06, zf + 0.14, -0.04, 0.04)
    fbox(g, 'Trim', F, u0, u1, zf + top - 0.07, zf + top, -0.06, 0.06)
    n = int(L / pitch)
    for i in range(n):
        u = u0 + (L - (n - 1) * pitch) / 2 + i * pitch
        fbox(g, 'Trim', F, u - 0.019, u + 0.019, zf + 0.14, zf + top - 0.07, -0.019, 0.019)


def chainlink(gF, pts, h=1.22, gates=()):
    """Chain-link run along a polyline [(x, y), ...]: terminal + line posts, top rail, tension wire, mesh.
    gates: list of (segment index, centre distance, width)."""
    for k, (a, b) in enumerate(zip(pts, pts[1:])):
        a, b = Vector((a[0], a[1], 0)), Vector((b[0], b[1], 0))
        L = (b - a).length
        U = (b - a).normalized()
        spans = [(0.0, L)]
        for gi, gc, gw in gates:
            if gi == k:
                spans = [(0.0, gc - gw / 2 - 0.06), (gc + gw / 2 + 0.06, L)]
                for s in (gc - gw / 2 - 0.06, gc + gw / 2 + 0.06):
                    p = a + U * s
                    cyl(gF, 'FenceSteel', 0.036, -0.6, h + 0.08, p)
                # the gate leaf
                p0 = a + U * (gc - gw / 2)
                p1 = a + U * (gc + gw / 2)
                for z in (0.08, h - 0.04):
                    seg_box(gF, 'FenceSteel', (p0.x, p0.y, z), (p1.x, p1.y, z), 0.035, 0.035, up=(0, 0, 1), d0=-0.0175)
                for p in (p0, p1):
                    cbox(gF, 'FenceSteel', p.x, p.y, 0.035, 0.035, 0.08, h - 0.04)
                mesh_panel(gF, p0, p1, 0.1, h - 0.06)
        for s0, s1 in spans:
            pa, pb = a + U * s0, a + U * s1
            n = max(1, int(math.ceil((s1 - s0) / 3.0)))
            for i in range(n + 1):
                p = pa + (pb - pa) * (i / n)
                term = i in (0, n)
                cyl(gF, 'FenceSteel', 0.036 if term else 0.024, -0.6, h + (0.06 if term else 0.0), p)
                if term:
                    lathe(gF, 'FenceSteel', [(0.042, h + 0.06), (0.042, h + 0.1), (0.0, h + 0.12)], p.x, p.y, seg=8,
                          caps=False)
            seg_box(gF, 'FenceSteel', (pa.x, pa.y, h - 0.02), (pb.x, pb.y, h - 0.02), 0.042, 0.042, d0=-0.021)
            mesh_panel(gF, pa, pb, 0.04, h - 0.02)


def cyl(g, mat, r, z0, z1, p, seg=8):
    lathe(g, mat, [(r, z0), (r, z1)], p.x if hasattr(p, 'x') else p[0], p.y if hasattr(p, 'y') else p[1], seg=seg)


def mesh_panel(g, a, b, z0, z1):
    U = (b - a).normalized()
    N = Vector((U.y, -U.x, 0))
    pts = [a + N * 0.01 + Vector((0, 0, z0)), b + N * 0.01 + Vector((0, 0, z0)),
           b + N * 0.01 + Vector((0, 0, z1)), a + N * 0.01 + Vector((0, 0, z1))]
    poly(g, 'FenceMesh', pts, facing=N)


def raised_bed(g, x0, x1, y0, y1, h=0.3):
    t = 0.05
    box(g, 'PostWood', x0, x1, y0, y0 + t, -0.05, h)
    box(g, 'PostWood', x0, x1, y1 - t, y1, -0.05, h)
    box(g, 'PostWood', x0, x0 + t, y0 + t, y1 - t, -0.05, h)
    box(g, 'PostWood', x1 - t, x1, y0 + t, y1 - t, -0.05, h)
    box(g, 'Soil', x0 + t, x1 - t, y0 + t, y1 - t, -0.05, h - 0.06)


def roll_cart(g, x, y, mat, ang=0.0):
    F = Fr((x, y, 0), (math.cos(ang), math.sin(ang), 0), (math.sin(ang), -math.cos(ang), 0))
    extrude(g, mat, F.side(), [(-0.3, 0.0), (0.33, 0.0), (0.36, 1.0), (-0.36, 1.0)], -0.29, 0.29)
    fbox(g, mat, F, -0.31, 0.31, 1.0, 1.06, -0.4, 0.38)


def condenser(g, x, y):
    cbox(g, 'Concrete', x, y, 0.85, 0.85, -0.02, 0.08)
    cbox(g, 'Condenser', x, y, 0.75, 0.75, 0.08, 0.85)
    lathe(g, 'Metal', [(0.0, 0.85), (0.3, 0.85), (0.3, 0.87), (0.0, 0.88)], x, y, seg=16, caps=False)




# ============================================================================ site + dimensions
SITE = dict(footprint=(21.38, 16.77), curb_y=-28.24, lot=(-20.0, -28.24, 20.8, 25.0))
ROSSI = dict(local=(-40.07, 0.97), rot_deg=-9.5, curb_y=-26.3)
X0, X1, Y0, Y1 = -5.8, 7.4, -5.5, 3.5
XC, YC = (X0 + X1) / 2, (Y0 + Y1) / 2
HALF = (Y1 - Y0) / 2
FF = 0.9
ZE = FF + 2.75
PITCH = 45.0
TH = 0.17
OVE, OVR = 0.4, 0.3
LIFT = TH / math.cos(math.radians(PITCH))
DORMERS = [XC - 3.6, XC + 3.6]
DW = 0.95                    # dormer half width
DYF = Y0 + 0.55              # dormer face
DZE = 6.0                    # dormer eave (underside at the cheek)
SP = (-10.8, X0, -4.6, 2.4)  # screened porch x0, x1, y0, y1
CAM_HERO = dict(loc=(8.5, -26.5, 1.7), target=(-0.6, -3.0, 3.6), lens=30)
CAM_AERIAL = dict(loc=(34.0, -46.0, 34.0), target=(-1.5, -6.0, 1.0), lens=34)
CAM_BAY = dict(loc=(-17.0, -60.0, 10.0), target=(-19.5, -4.0, 3.0), lens=27)


def zroof(y):
    """Top surface of the main roof at y (front and back slopes)."""
    return ZE + LIFT + (HALF - abs(y - YC)) * math.tan(math.radians(PITCH))


def make_materials():
    M = {}
    M['Shakes'] = wp.mat('Shakes', tex=tex_shakes('sl_shakes', '#97928a', tile=1.2, exposure=0.14, seed=93, var=0.17), rough=0.85)
    M['Trim'] = wp.mat('Trim', tex=tex_paint('sl_trim', '#f2f1ec'), rough=0.4)
    M['Soffit'] = wp.mat('Soffit', tex=wp.tex_wood('sl_soffit', color='#efeee8', board=0.0909, seed=9), rough=0.5)
    M['Glass'] = wp.mat('Glass', '#ffffff', rough=0.04, tex=tex_glass('sl_glass', seed=82))
    M['Roof'] = wp.mat('Roof', tex=tex_roof2('sl_roof', '#535557', seed=35, algae=0.16), rough=0.86)
    M['Door'] = wp.mat('Door', tex=tex_paint('sl_door', '#2f4b5c', seed=13, amp=0.04), rough=0.38)
    M['Brick'] = wp.mat('Brick', tex=wp.tex_brick('sl_brick', color='#8a4a3a', mortar='#b5ad9e', var=0.14, seed=3), rough=0.85)
    M['Stucco'] = wp.mat('Stucco', tex=(wp.tex_ground('sl_stucco', kind='stucco', color='#b9b6ae', n=512, tile=2.0, seed=25)[0], None, 2.0), rough=0.9)
    M['Metal'] = wp.mat('Metal', '#1d1e20', rough=0.38, metal=0.75)
    M['Gutter'] = wp.mat('Gutter', tex=tex_paint('sl_gutter', '#efeee9', seed=15, amp=0.02), rough=0.35)
    M['Crawl'] = wp.mat('Crawl', '#1c1a17', rough=1.0)
    M['PorchFloor'] = wp.mat('PorchFloor', tex=wp.tex_wood('sl_porch', color='#8d8f8c', board=0.0833, seed=8, weathered=0.1), rough=0.6)
    M['Ceiling'] = wp.mat('Ceiling', tex=wp.tex_wood('sl_ceiling', color='#dfe9e8', board=0.0909, seed=10), rough=0.5)
    M['Screen'] = mat_masked('Screen', *tex_screen('sl_screen'), rough=0.6, metal=0.3)
    M['Lattice'] = wp.mat('Lattice', tex=tex_lattice('sl_lattice'), rough=0.6)
    M['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('sl_conc', kind='concrete', n=512, tile=3.0, seed=23)[0], None, 3.0), rough=0.9)
    M['Shell'] = wp.mat('Shell', tex=(wp.tex_ground('sl_shell', kind='gravel', color='#c9c0ad', n=1024, tile=2.0, seed=22)[0], None, 2.0), rough=0.95)
    M['Pavers'] = wp.mat('Pavers', tex=wp.tex_brick('sl_paver', color='#8c4d3a', mortar='#a39782', var=0.16, seed=21), rough=0.88)
    M['Mulch'] = wp.mat('Mulch', tex=tex_straw('sl_mulch', n=512), rough=0.95)
    M['Plants'] = vc_material('Plants', tex_leaves('sl_plants', '#4f6d34', n=512, tile=0.6, seed=52), rough=0.65)
    M['Hydrangea'] = vc_material('Hydrangea', tex_leaves('sl_hydr', '#4a6b30', n=512, tile=0.7, seed=56, flowers='#8aa2dc', fcov=0.45, fsize=26), rough=0.7)
    M['Grass'] = vc_material('Grass', tex_leaves('sl_grass', '#8a8a55', n=512, tile=0.5, seed=57), rough=0.8)
    M['PostWood'] = wp.mat('PostWood', tex=wp.tex_wood('sl_wood', color='#8a6d4e', board=0.14, seed=6, weathered=0.45), rough=0.8)
    M['MailMetal'] = wp.mat('MailMetal', '#202224', rough=0.4, metal=0.6)
    M['Condenser'] = wp.mat('Condenser', '#8d8f8a', rough=0.5, metal=0.3)
    M['Bark'] = wp.mat('Bark', tex=tex_bark('sl_bark', n=512), rough=0.92)
    M['Leaves'] = mat_leafcard('Leaves', tex_leafcard('sl_leafcard', '#4b5f2c', n=512, seed=61, count=1100, lsize=0.045))
    MAT.update(M)
    return M


def tex_screen(key, n=256, tile=0.1):
    a = np.zeros((n, n, 4), np.float32)
    y, x = np.mgrid[0:n, 0:n]
    wire = ((x % 4) == 0) | ((y % 4) == 0)
    a[..., :3] = 0.16
    a[..., 3] = np.where(wire, 1.0, 0.0)
    path = os.path.join(wp.TEX_DIR, key + '.png')
    Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), 'RGBA').save(path)
    return path, tile


def tex_lattice(key, n=512, tile=0.6):
    y, x = np.mgrid[0:n, 0:n] / n * tile
    p = 0.15
    a = ((x + y) % p) / p
    b = ((x - y) % p) / p
    slat = (np.minimum(a, 1 - a) < 0.13) | (np.minimum(b, 1 - b) < 0.13)
    over = (np.minimum(a, 1 - a) < 0.13)
    alb = np.where(slat[..., None], np.where(over[..., None], 0.93, 0.86) * np.ones(3), 0.06 * np.ones(3))
    h = slat * 1.0
    return wp._save(alb.astype(np.float32), key), wp._save(wp._normal_from_height(h.astype(np.float32), 2.0), key + '_n'), tile


# ============================================================================ house
def build_house():
    gH, gR, gP = Geo('House'), Geo('Roof'), Geo('Porch')
    W = wall_frames(X0, X1, Y0, Y1)
    zs = FF - 0.15
    t = math.tan(math.radians(PITCH))
    DOOR = XC
    # front
    F, L = W['front']
    holes = []
    for xc in (XC - 3.6, XC + 3.6):
        holes.append(win_group(gH, F, xc - X0, FF + 0.8, 0.8, 1.55, 2, mull=0.12, top=(3, 2), bot=(3, 2)))
    holes.append((DOOR - X0 - 0.5, DOOR - X0 + 0.5, FF, FF + 2.1))
    glazed_door(gH, F, DOOR - X0, FF, 1.0, 2.1, lites=(3, 3), glass_from=0.5)
    wall_faces(gH, F, L, zs, ZE, holes, mat='Shakes')
    # back: windows + kitchen door
    F, L = W['back']
    holes = []
    for u in (1.6, 4.0, 9.2, 11.6):
        holes.append((u - 0.4, u + 0.4, FF + 0.8, FF + 2.35))
        sash2(gH, F, u, FF + 0.8, 0.8, 1.55, (3, 2), (3, 2), casing=0.1)
    holes.append((6.6 - 0.46, 6.6 + 0.46, FF, FF + 2.05))
    glazed_door(gH, F, 6.6, FF, 0.92, 2.05, lites=(3, 3), glass_from=0.45)
    wall_faces(gH, F, L, zs, ZE, holes, mat='Shakes')
    # gable ends (left: french door to the screened porch; right: chimney between windows)
    for side in ('left', 'right'):
        F, L = W[side]
        holes = []
        if side == 'left':
            holes.append((4.0 - 0.75, 4.0 + 0.75, FF, FF + 2.1))
            for k, uu in enumerate((3.65, 4.35)):
                glazed_door(gH, F, uu, FF, 0.7, 2.1, lites=(2, 5), glass_from=0.18, casing=0.0 if k else 0.1, threshold=True)
            for u in (1.4, 7.6):
                holes.append((u - 0.4, u + 0.4, FF + 0.8, FF + 2.35))
                sash2(gH, F, u, FF + 0.8, 0.8, 1.55, (3, 2), (3, 2), casing=0.1)
        else:
            for u in (1.5, 7.5):
                holes.append((u - 0.4, u + 0.4, FF + 0.8, FF + 2.35))
                sash2(gH, F, u, FF + 0.8, 0.8, 1.55, (3, 2), (3, 2), casing=0.1)
        wall_faces(gH, F, L, zs, ZE, holes, mat='Shakes')
        apex = ZE + HALF * t
        up = [(L / 2 - 1.5, 4.55, 0.75, 1.3), (L / 2 + 1.5, 4.55, 0.75, 1.3)]
        hz = [(u - w / 2, u + w / 2, s, s + h) for (u, s, w, h) in up]
        for (u, s, w, h) in up:
            sash2(gH, F, u, s, w, h, (3, 2), (3, 2), casing=0.1)
        # gable: rectangle band with the two upstairs windows, then the triangle above
        zb = 6.05
        ub = zb - ZE
        F2 = Fr(F.p(ub, 0), F.U, F.N)
        wall_faces(gH, F2, L - 2 * ub, ZE, zb, [(a - ub, b - ub, c, d) for (a, b, c, d) in hz], mat='Shakes')
        poly(gH, 'Shakes', [F.p(0, ZE), F.p(ub, ZE), F.p(ub, zb)], facing=F.N)
        poly(gH, 'Shakes', [F.p(L, ZE), F.p(L - ub, zb), F.p(L - ub, ZE)], facing=F.N)
        poly(gH, 'Shakes', [F.p(ub, zb), F.p(L - ub, zb), F.p(L / 2, apex)], facing=F.N)
        vent_louver(gH, F, L / 2, apex - 0.9, 0.45, 0.4)
        # flared shingle belt course at the second floor line
        fbox(gH, 'Trim', F, 0.0, L, ZE - 0.02, ZE + 0.1, -0.005, 0.035)
    for side, (F, L) in W.items():
        fbox(gH, 'Trim', F, -0.005, 0.15, zs, ZE, -0.005, 0.028)
        fbox(gH, 'Trim', F, L - 0.15, L + 0.005, zs, ZE, -0.005, 0.028)
        if side in ('front', 'back'):
            fbox(gH, 'Trim', F, -0.02, L + 0.02, ZE - 0.22, ZE, -0.005, 0.025)
    # raised foundation (painted block) with vents
    e = 0.035
    box(gH, 'Stucco', X0 - e, X1 + e, Y0 - e, Y1 + e, -0.6, zs + 0.02)
    box(gH, 'Trim', X0 - e - 0.01, X1 + e + 0.01, Y0 - e - 0.01, Y1 + e + 0.01, zs, zs + 0.06)
    for F_, u in ((W['front'][0], 1.5), (W['front'][0], 11.5), (W['back'][0], 3.0), (W['back'][0], 10.0), (W['right'][0], 4.5)):
        fbox(gH, 'Crawl', F_, u - 0.2, u + 0.2, 0.2, 0.4, 0.036, 0.04)
    # main roof
    faces, zr = gable_roof(gR, X0, X1, Y0, Y1, ZE, PITCH, OVE, OVR, along='x', th=TH)
    ze_edge = ZE + LIFT - OVE * t
    for yg, out in ((Y0 - OVE, -1), (Y1 + OVE, 1)):
        spans = [(X0 - OVR + 0.02, XC - 1.75), (XC + 1.75, X1 + OVR - 0.02)] if out < 0 else [(X0 - OVR + 0.02, X1 + OVR - 0.02)]
        for xa, xb in spans:
            gutter(gR, (xa, yg), (xb, yg), ze_edge - 0.02, (0, out))
        for x in (X0 + 0.3, X1 - 0.3):
            if out < 0 and x < XC:
                continue
            downspout(gR, x, yg, ze_edge - 0.12, (0, out), wall_off=-(OVE - 0.06))
    for dx in DORMERS:
        dormer(gH, gR, dx)
    chimney(gR)
    build_entry(gP, gR)
    build_screened_porch(gP, gR)
    # back stoop (wood) at the kitchen door
    bx = X1 - 6.6
    box(gP, 'PorchFloor', bx - 1.0, bx + 1.0, Y1, Y1 + 1.4, -0.6, FF - 0.02)
    for k in range(1, 5):
        box(gP, 'PorchFloor', bx - 0.8, bx + 0.8, Y1 + 1.4 + 0.28 * (k - 1), Y1 + 1.4 + 0.28 * k, -0.3, FF - 0.02 - 0.18 * k)
    return [gH, gR, gP], zr


def dormer(gH, gR, dx):
    t = math.tan(math.radians(PITCH))
    zf = zroof(DYF)                        # main roof surface at the dormer face
    F = Fr((dx - DW, DYF, 0), (1, 0, 0), (0, -1, 0))
    L = 2 * DW
    hole = (DW - 0.42, DW + 0.42, zf + 0.25, zf + 0.25 + 1.1)
    sash2(gH, F, DW, hole[2], 0.84, 1.1, (3, 2), (3, 2), casing=0.09)
    wall_faces(gH, F, L, zf - 0.25, DZE, [hole], mat='Shakes')
    apex = DZE + DW * t
    poly(gH, 'Shakes', [F.p(0, DZE), F.p(L, DZE), F.p(DW, apex)], facing=F.N)
    fbox(gH, 'Trim', F, -0.005, 0.12, zf - 0.25, DZE, -0.005, 0.025)
    fbox(gH, 'Trim', F, L - 0.12, L + 0.005, zf - 0.25, DZE, -0.005, 0.025)
    # cheeks down to the roof
    y_e = YC - (zroof(YC) - 0.05 - DZE) / t - 0.0
    for sx in (-1, 1):
        x = dx + sx * DW
        poly(gH, 'Shakes', [(x, DYF, zf - 0.08), (x, DYF, DZE), (x, YC - (HALF - (DZE - ZE - LIFT) / t) + 0.05, DZE)],
             facing=(sx, 0, 0))
    # dormer gable roof, running back into the main roof
    y_back = YC - 0.6
    gable_roof(gR, dx - DW, dx + DW, DYF, y_back, DZE, PITCH, 0.16, 0.22, along='y', th=0.13)


def chimney(gR):
    """Exterior brick chimney on the right gable end with stepped shoulders."""
    cy = YC + 0.4
    x0 = X1 + 0.04
    top = zroof(YC) + 0.95
    box(gR, 'Brick', x0, x0 + 0.75, cy - 0.85, cy + 0.85, -0.6, 2.6)
    for k, (w, z0, z1) in enumerate(((0.85, 2.6, 2.9), (0.6, 2.9, 3.4))):
        # sloped shoulders approximated with two set-back courses
        box(gR, 'Brick', x0, x0 + 0.75 - 0.05 * k, cy - w, cy + w, z0, z1)
    box(gR, 'Brick', x0, x0 + 0.65, cy - 0.42, cy + 0.42, 3.4, top)
    box(gR, 'Brick', x0 - 0.05, x0 + 0.72, cy - 0.5, cy + 0.5, top - 0.3, top - 0.18)
    box(gR, 'Stucco', x0 - 0.02, x0 + 0.68, cy - 0.46, cy + 0.46, top, top + 0.07)
    lathe(gR, 'Stucco', [(0.11, top + 0.07), (0.11, top + 0.32), (0.0, top + 0.32)], x0 + 0.33, cy, seg=8)


def build_entry(gP, gR):
    """Gabled entry porch on square posts, deck landing, wood steps with railings."""
    x0, x1 = XC - 1.4, XC + 1.4
    yf = Y0 - 1.7
    box(gP, 'Stucco', x0, x1, yf, Y0, -0.6, FF - 0.08)
    box(gP, 'PorchFloor', x0 - 0.03, x1 + 0.03, yf - 0.04, Y0, FF - 0.08, FF)
    n, rise, run = 5, FF / 5, 0.28
    for k in range(1, n):
        box(gP, 'PorchFloor', XC - 0.85, XC + 0.85, yf - 0.04 - run * k, yf - 0.04 - run * (k - 1), FF - rise * k - 0.04, FF - rise * k)
        box(gP, 'Trim', XC - 0.85, XC + 0.85, yf - 0.04 - run * (k - 1) - 0.02, yf - 0.04 - run * (k - 1), FF - rise * k, FF - rise * (k - 1) - 0.04)
    for sx in (-1, 1):
        x = XC + sx * 0.88
        box(gP, 'Trim', x - 0.04, x + 0.04, yf - 0.04 - run * (n - 1), yf - 0.04, -0.3, 0.12)
        seg_box(gP, 'Trim', (x, yf - 0.04 - run * (n - 1) + 0.1, 0.95), (x, yf - 0.1, FF + 0.88), 0.06, 0.05, d0=0.0)
        cbox(gP, 'Trim', x, yf - 0.04 - run * (n - 1) + 0.1, 0.1, 0.1, 0.0, 1.0)
    zt = FF + 2.45
    for sx in (-1, 1):
        column(gP, XC + sx * 1.22, yf + 0.18, FF, zt, s=0.16)
        column(gP, XC + sx * 1.22, Y0 - 0.1, FF, zt, s=0.1)
        Fs = Fr((XC + sx * 1.22, 0, 0), (0, 1, 0), (1, 0, 0))
        railing(gP, Fs, yf + 0.32, Y0 - 0.22, FF)
    box(gP, 'Trim', x0 + 0.02, x1 - 0.02, yf + 0.04, yf + 0.32, zt, zt + 0.32)
    for sx in (-1, 1):
        box(gP, 'Trim', XC + sx * 1.22 - 0.12, XC + sx * 1.22 + 0.12, yf + 0.04, Y0, zt, zt + 0.32)
    poly(gP, 'Ceiling', [(x0 + 0.1, yf + 0.32, zt + 0.05), (x1 - 0.1, yf + 0.32, zt + 0.05), (x1 - 0.1, Y0, zt + 0.05),
                         (x0 + 0.1, Y0, zt + 0.05)], facing=(0, 0, -1))
    ze = zt + 0.32
    gable_roof(gR, x0, x1, yf + 0.04, Y0 + 1.3, ze, PITCH, 0.25, 0.25, along='y', th=0.14)
    F = Fr((x0, yf + 0.04, 0), (1, 0, 0), (0, -1, 0))
    L = x1 - x0
    poly(gP, 'Shakes', [F.p(0, ze), F.p(L, ze), F.p(L / 2, ze + L / 2)], facing=F.N)
    fbox(gP, 'Trim', F, 0, L, ze - 0.05, ze + 0.06, -0.005, 0.03)
    lantern(gP, Fr((0, Y0, 0), (1, 0, 0), (0, -1, 0)), XC + 0.85, FF + 1.85)


def build_screened_porch(gP, gR):
    x0, x1, y0, y1 = SP
    zf = FF - 0.1
    # piers + lattice skirt
    for x in (x0 + 0.2, (x0 + x1) / 2, x1 - 0.3):
        for y in (y0 + 0.2, (y0 + y1) / 2, y1 - 0.2):
            cbox(gP, 'Stucco', x, y, 0.35, 0.35, -0.6, zf - 0.2)
    for (a, b, c, d) in ((x0, x1, y0, y0 + 0.03), (x0, x1, y1 - 0.03, y1), (x0, x0 + 0.03, y0, y1)):
        box(gP, 'Lattice', a, b, c, d, -0.05, zf - 0.2)
    box(gP, 'Trim', x0 - 0.02, x1, y0 - 0.02, y1 + 0.02, zf - 0.24, zf - 0.1)
    box(gP, 'PorchFloor', x0, x1, y0, y1, zf - 0.1, zf)
    # walls: shingled knee wall, posts, screen panels
    zk, zt = zf + 0.75, zf + 2.55
    runs = [(Fr((x0, y0, 0), (1, 0, 0), (0, -1, 0)), x1 - x0, 'front'), (Fr((x0, y1, 0), (0, -1, 0), (-1, 0, 0)), y1 - y0, 'left'),
            (Fr((x1, y1, 0), (-1, 0, 0), (0, 1, 0)), x1 - x0, 'back')]
    for F, L, nm in runs:
        door = (L / 2 - 0.5, L / 2 + 0.5) if nm == 'left' else None
        n = max(2, int(round(L / 1.6)))
        posts = [L * i / n for i in range(n + 1)]
        for k, u in enumerate(posts):
            fbox(gP, 'Trim', F, u - 0.07, u + 0.07, zf, zt, -0.07, 0.07)
        for a, b in zip(posts, posts[1:]):
            if door and a <= door[0] + 1e-6 <= b:
                # screen door opening with a kick panel
                fbox(gP, 'Shakes', F, a + 0.07, door[0] - 0.05, zf, zk, -0.06, 0.0)
                fbox(gP, 'Shakes', F, door[1] + 0.05, b - 0.07, zf, zk, -0.06, 0.0)
                for uu in (door[0] - 0.05, door[1]):
                    fbox(gP, 'Trim', F, uu, uu + 0.05, zf, zt, -0.04, 0.04)
                fbox(gP, 'Trim', F, door[0], door[1], zf + 2.05, zf + 2.12, -0.04, 0.04)
                fbox(gP, 'Trim', F, door[0], door[1], zf + 0.0, zf + 0.25, -0.03, 0.01)
                fbox(gP, 'Trim', F, door[0], door[1], zf + 0.95, zf + 1.02, -0.03, 0.01)
                poly(gP, 'Screen', [F.p(door[0], zf + 0.25, -0.01), F.p(door[1], zf + 0.25, -0.01), F.p(door[1], zf + 2.05, -0.01),
                                    F.p(door[0], zf + 2.05, -0.01)], facing=F.N)
                for (p0, p1) in ((a + 0.07, door[0] - 0.05), (door[1] + 0.05, b - 0.07)):
                    poly(gP, 'Screen', [F.p(p0, zk + 0.05, -0.02), F.p(p1, zk + 0.05, -0.02), F.p(p1, zt - 0.05, -0.02),
                                        F.p(p0, zt - 0.05, -0.02)], facing=F.N)
                continue
            fbox(gP, 'Shakes', F, a + 0.07, b - 0.07, zf, zk, -0.06, 0.0)
            fbox(gP, 'Trim', F, a + 0.07, b - 0.07, zk, zk + 0.05, -0.08, 0.03)
            poly(gP, 'Screen', [F.p(a + 0.07, zk + 0.05, -0.02), F.p(b - 0.07, zk + 0.05, -0.02), F.p(b - 0.07, zt - 0.05, -0.02),
                                F.p(a + 0.07, zt - 0.05, -0.02)], facing=F.N)
            fbox(gP, 'Trim', F, a + 0.07, b - 0.07, zt - 0.08, zt, -0.04, 0.04)
        fbox(gP, 'Trim', F, -0.07, L + 0.07, zt, zt + 0.25, -0.08, 0.08)
        if door:
            for k in range(1, 4):
                fbox(gP, 'PorchFloor', F, door[0] - 0.3, door[1] + 0.3, zf - 0.19 * k - 0.04, zf - 0.19 * k, 0.07 + 0.28 * (k - 1), 0.07 + 0.28 * k)
    poly(gP, 'Ceiling', [(x0 + 0.07, y0 + 0.07, zt + 0.22), (x1, y0 + 0.07, zt + 0.22), (x1, y1 - 0.07, zt + 0.22),
                         (x0 + 0.07, y1 - 0.07, zt + 0.22)], facing=(0, 0, -1))
    # gable roof, ridge perpendicular to the house, gable facing out (left)
    ze = zt + 0.25
    gable_roof(gR, x0, x1 + 0.3, y0, y1, ze, 35.0, 0.35, 0.3, along='x', th=0.15)
    F = Fr((x0, y1, 0), (0, -1, 0), (-1, 0, 0))
    L = y1 - y0
    apex = ze + L / 2 * math.tan(math.radians(35))
    poly(gP, 'Shakes', [F.p(0, ze), F.p(L, ze), F.p(L / 2, apex)], facing=F.N)
    vent_louver(gP, F, L / 2, ze + 0.75, 0.6, 0.45)
    t = math.tan(math.radians(35))
    zg = ze + 0.15 / math.cos(math.radians(35)) - 0.35 * t - 0.02
    gutter(gR, (x0 - 0.3, y0 - 0.35), (x1, y0 - 0.35), zg, (0, -1))
    downspout(gR, x0 + 0.1, y0 - 0.35, zg - 0.1, (0, -1), wall_off=-0.3)


# ============================================================================ lot
def build_lot():
    gD, gV, gT, gX = Geo('Lot_Hardscape'), Geo('Lot_Plants'), Geo('Tree_LiveOak_1'), Geo('Lot_Props')
    cy = SITE['curb_y']
    # front walk (brick pavers) from the entry steps to the curb line
    sy = Y0 - 1.7 - 0.04 - 0.28 * 4
    slab(gD, 'Pavers', [(XC - 0.7, cy), (XC + 0.7, cy), (XC + 0.7, sy), (XC - 0.7, sy)], 0.04)
    # crushed-shell driveway on the right, concrete apron at the curb, parking pad by the house
    dx0, dx1 = 10.4, 13.6
    slab(gD, 'Concrete', [(dx0 - 0.7, cy), (dx1 + 0.7, cy), (dx1, cy + 1.6), (dx0, cy + 1.6)], 0.045)
    slab(gD, 'Shell', [(dx0, cy + 1.6), (dx1, cy + 1.6), (dx1, 7.5), (dx0 - 1.6, 7.5), (dx0 - 1.6, -1.0), (dx0, -2.5)], 0.035)
    slab(gD, 'Pavers', [(XC + 0.86, Y0 - 2.6), (dx0, Y0 - 2.6), (dx0, Y0 - 1.8), (XC + 0.86, Y0 - 1.8)], 0.04)
    # foundation beds: hydrangeas, ornamental grasses, low perennials
    for (xa, xb) in ((X0 + 0.0, XC - 1.6), (XC + 1.6, X1 + 0.0)):
        slab(gD, 'Mulch', [(xa, Y0 - 1.7), (xb, Y0 - 1.7), (xb, Y0), (xa, Y0)], 0.06, -0.02)
        n = 4
        for i in range(n):
            x = xa + 0.6 + (xb - xa - 1.2) * i / (n - 1)
            shrub(gV, 'Hydrangea', (x, Y0 - 0.85), (0.6, 0.55, 1.05), 1000 + i + int(xa * 3))
        for i in range(3):
            x = xa + 1.2 + (xb - xa - 2.4) * i / 2
            shrub(gV, 'Grass', (x, Y0 - 1.45), (0.3, 0.3, 0.6), 1100 + i + int(xa * 3), tone=1.05)
    for i in range(5):
        shrub(gV, 'Hydrangea' if i % 2 else 'Plants', (SP[0] + 0.5 + i * 1.0, SP[2] - 0.6), (0.45, 0.4, 0.75), 1200 + i)
    mailbox_post(gX, dx0 - 1.0, cy + 0.45)
    condenser(gX, X0 + 2.2, Y1 + 1.0)
    tree(gT, (-11.0, -16.0), 31, H=10.0, spread=12.0, trunk_r=0.32, fork=2.4, n_limbs=6, n_clumps=520, clump=1.35,
         leaf='Leaves', bark='Bark', bounds=SITE['lot'])
    return [gD, gV, gT, gX]


# ============================================================================ main
def street_ribbon(name, pts, width=9.0, z=0.0):
    """Render-only street along a polyline of curb points (mitred joints; the street lies on the right of
    travel, i.e. -y when the curb runs along +x)."""
    g = Geo(name)
    P = [Vector((p[0], p[1], 0)) for p in pts]
    n = len(P)
    NR = []
    for k in range(n):
        ns = []
        for a, b_ in ((P[max(k - 1, 0)], P[k]), (P[k], P[min(k + 1, n - 1)])):
            if (b_ - a).length > 1e-6:
                U = (b_ - a).normalized()
                ns.append(Vector((U.y, -U.x, 0)))
        m = sum(ns, Vector()).normalized()
        NR.append(m / max(0.5, m.dot(ns[0])))
    for (o0, o1, mat, z0) in ((0.0, 0.15, 'Concrete', 0.12), (0.15, 0.6, 'Concrete', 0.0), (0.6, 0.6 + width, 'Asphalt', 0.0)):
        for k in range(n - 1):
            q = [P[k] + NR[k] * o0, P[k + 1] + NR[k + 1] * o0, P[k + 1] + NR[k + 1] * o1, P[k] + NR[k] * o1]
            extrude(g, mat, WORLD, [(v.x, v.y) for v in q], -0.1, z0 + z)
    return g


def render_extras(bay=False):
    if 'Asphalt' not in MAT:
        MAT['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('sl_asphalt', kind='asphalt', tile=4.0), rough=0.9)
    objs = []
    cy = SITE['curb_y']
    rx, ry = ROSSI['local']
    th = math.radians(ROSSI['rot_deg'])
    R = lambda x, y: (rx + x * math.cos(th) - y * math.sin(th), ry + x * math.sin(th) + y * math.cos(th))
    pts = [R(-70, ROSSI['curb_y']), R(-35, ROSSI['curb_y']), R(0, ROSSI['curb_y']), (-21.0, cy + 0.85), (0.0, cy),
           (40.0, cy), (90.0, cy)]
    objs.append(street_ribbon('Render_Street', pts).build())
    trees = [((-30.0, 16.0), 15.0, 12.0), ((14.0, 26.0), 16.0, 13.0), ((-6.0, 30.0), 14.0, 12.0), ((27.0, 10.0), 13.0, 11.0)]
    for k, (b, h, s) in enumerate(trees):
        g = Geo(f'Render_BG_{k}')
        tree(g, b, 80 + k, H=h, spread=s, trunk_r=0.32, fork=3.8, n_limbs=6, n_clumps=520, clump=1.6, leaf='Leaves', bark='Bark')
        objs.append(g.build())
    return objs


def place_rossi():
    """Import the Rossi GLBs and place them at their true position/rotation in this house's frame."""
    mdir = os.path.join(REPO, 'models', 'homes')
    emp = bpy.data.objects.new('Rossi_Place', None)
    bpy.context.scene.collection.objects.link(emp)
    for f in ('rossi-house.glb', 'rossi-house-lot.glb'):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=os.path.join(mdir, f))
        for o in set(bpy.data.objects) - before:
            if o.parent is None:
                o.parent = emp
    emp.location = (ROSSI['local'][0], ROSSI['local'][1], 0.0)
    emp.rotation_euler = (0, 0, math.radians(ROSSI['rot_deg']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--out', default=None)
    ap.add_argument('--views', default='hero,aerial,bay')
    ap.add_argument('--samples', type=int, default=None)
    args = ap.parse_args()
    wp.reset()
    make_materials()
    house_geos, zr = build_house()
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
    mn, mx = check_lot(house_objs, SITE['lot'], 'house')
    check_lot(lot_objs, SITE['lot'], 'lot')
    meta = {
        'id': ID, 'name': 'Sullivan house', 'address': '2639 Bay Drive', 'neighborhood': None,
        'residents': ['Nellie Sullivan', 'David Sullivan'],
        'status': 'proposed (address); design interpreted from the brief (no reference photo)',
        'atlas_building_index': 21165, 'footprint_m': list(SITE['footprint']),
        'ridge_height_m': round(zr, 2), 'top_height_m': round(mx.z, 2), 'stories': 1.5,
        'style': 'coastal shingle-style cottage',
        'materials': ['weathered (unpainted) cedar shakes, silver-grey with brown strays, 5.5 in exposure',
                      'white painted trim, wide corner boards, belt course, K-style gutters',
                      'white 6-over-6 double-hung windows; teal-blue glazed front door',
                      'dark grey architectural asphalt shingles, 12:12 pitch',
                      'red brick exterior chimney; painted block foundation; white lattice skirt',
                      'screened porch: shingled knee wall, bronze screen panels, beadboard ceiling',
                      'brick paver walk, crushed-shell driveway with a concrete apron'],
        'triangles': th + tl, 'triangles_house': th, 'triangles_lot': tl,
        'files': {'house': f'models/homes/{ID}.glb', 'lot': f'models/homes/{ID}-lot.glb'},
        'file_mb': {'house': round(os.path.getsize(house_glb) / 1e6, 2), 'lot': round(os.path.getsize(lot_glb) / 1e6, 2)},
        'house_bbox_m': [[round(v, 2) for v in mn], [round(v, 2) for v in mx]],
        'lot_local_rect_m': list(SITE['lot']), 'curb_line_local_y': SITE['curb_y'],
        'notes': ('Main block 13.2 x 9.0 m, floor 0.9 m up on a block foundation, 12:12 side-gable roof with three gabled '
                  f'front dormers, ridge {zr:.1f} m (Atlas 8.5 m). Screened porch 5.0 x 7.0 m on the left (toward the '
                  'Rossis) with a French door into the house and a screen door with steps to the side yard. All of the '
                  'design is interpreted from the brief; there is no reference photo. The Atlas footprint (21.4 x 16.8 m) '
                  'is larger than a cottage needs: the house plus porch fill 19.6 m of its width. Lot sides use corrected '
                  'neighbor sides (site-specs.json neighbors_local x is mirrored): the Rossi house is on the left at '
                  '(-40.1, 1.0), rotated -9.5 deg. Main block centred 0.8 m right of the footprint centre so the screened porch stays within 0.2 m of the footprint.')}
    with open(os.path.join(mdir, f'{ID}.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print(json.dumps({k: meta[k] for k in ('triangles', 'triangles_house', 'triangles_lot', 'file_mb', 'ridge_height_m')}))
    if args.no_render:
        return
    out = args.out or os.path.join(REPO, 'renders')
    samples = args.samples or (24 if args.quick else 48)
    res = (640, 400) if args.quick else (1600, 1000)
    extras = render_extras()
    wp.finalize(extras)
    for o in extras:
        apply_custom_uvs(o)
    setup_render(samples, res, sun_az=235, sun_elev=40, exposure=0.15)
    views = args.views.split(',')
    if 'hero' in views:
        wp.camera(CAM_HERO['loc'], CAM_HERO['target'], CAM_HERO['lens'])
        wp.render(os.path.join(out, f'{ID}.jpg'))
    if 'aerial' in views:
        wp.camera(CAM_AERIAL['loc'], CAM_AERIAL['target'], CAM_AERIAL['lens'])
        wp.render(os.path.join(out, f'{ID}-aerial.jpg'))
    if 'bay' in views:
        place_rossi()
        for o in bpy.context.scene.objects:
            if o.name in ('Render_BG_0',):
                o.hide_render = True
        wp.camera(CAM_BAY['loc'], CAM_BAY['target'], CAM_BAY['lens'])
        wp.render(os.path.join(out, 'bay-drive-sullivan-rossi.jpg'))


if __name__ == '__main__':
    main()
