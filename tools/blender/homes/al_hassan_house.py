#!/usr/bin/env python3
"""The Al-Hassan house, 1552 Spinnaker Court, Harborview (hero home #6, Canon 2 address).

Zane Al-Hassan lives here with Dr. Nadir and Dr. Amina Al-Hassan. No reference photo: the design follows
the brief, a contemporary coastal house. A two-story main block in white board-and-batten under a steep
dark standing-seam metal roof, raised 0.75 m on a painted foundation, with a two-story front cross gable
full of tall black-framed windows, a deep full-width covered front porch (standing-seam shed roof,
stained cedar posts and ceiling, black picket rail), a screened porch at the back, and an attached
two-car garage on the left with modern flush doors. The lot GLB carries the concrete drive, a paver walk
to the curb, gravel and grass beds with hydrangeas, a multi-stem river birch, mailbox and bins.

Run (rebuilds GLBs, JSON and the final renders):
    python3 tools/blender/homes/al_hassan_house.py
Iteration renders (24 samples, 640 x 400, into a scratch folder):
    python3 tools/blender/homes/al_hassan_house.py --quick --out /path/to/scratch
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

# >>> KIT (generated block; identical in the three Harborview home scripts) >>>
# ============================================================================ KIT (shared by the Harborview hero homes; core adapted from monet_williams_house.py)
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



# ---------------------------------------------------------------------------- walls and openings
def rect_walls(x0, x1, y0, y1):
    """Outward frames of the four walls of a rectangle: side -> (frame, length). u runs left to right
    as seen from outside."""
    return {'front': (Fr((x0, y0, 0), (1, 0, 0), (0, -1, 0)), x1 - x0),
            'right': (Fr((x1, y0, 0), (0, 1, 0), (1, 0, 0)), y1 - y0),
            'back': (Fr((x1, y1, 0), (-1, 0, 0), (0, 1, 0)), x1 - x0),
            'left': (Fr((x0, y1, 0), (0, -1, 0), (-1, 0, 0)), y1 - y0)}


def wall_holes(g, F, L, z0, z1, holes, mat, reveal_mat=None, reveal=0.16, u0=0.0, top=None, breaks=()):
    """Wall face (u in [u0, L]) with rectangular holes (u0, u1, z0, z1) and reveals. top(u), if given,
    is a piecewise-linear top edge (gable ends); its kinks must be listed in breaks."""
    reveal_mat = reveal_mat or mat
    xs = sorted(set([u0, L] + [h[0] for h in holes] + [h[1] for h in holes] + list(breaks)))
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
        if top is not None:
            poly(g, mat, [F.p(a, zc), F.p(b, zc), F.p(b, top(b)), F.p(a, top(a))], facing=F.N)
        elif z1 > zc + 1e-6:
            poly(g, mat, [F.p(a, zc), F.p(b, zc), F.p(b, z1), F.p(a, z1)], facing=F.N)
    for a, b, h0, h1 in holes:
        dd = -reveal
        poly(g, reveal_mat, [F.p(a, h0), F.p(a, h1), F.p(a, h1, dd), F.p(a, h0, dd)], facing=F.U)
        poly(g, reveal_mat, [F.p(b, h0), F.p(b, h1), F.p(b, h1, dd), F.p(b, h0, dd)], facing=-F.U)
        poly(g, reveal_mat, [F.p(a, h0), F.p(b, h0), F.p(b, h0, dd), F.p(a, h0, dd)], facing=F.Z)
        poly(g, reveal_mat, [F.p(a, h1), F.p(b, h1), F.p(b, h1, dd), F.p(a, h1, dd)], facing=-F.Z)
        poly(g, 'Dark', [F.p(a, h0, dd), F.p(b, h0, dd), F.p(b, h1, dd), F.p(a, h1, dd)], facing=F.N)


def gable_wall(g, F, L, z0, zw, t, holes, mat, inset=0.03, reveal_mat=None, reveal=0.16):
    """Gable-end wall: rectangle to zw, then the gable up to the roof surface (slope t), with holes anywhere."""
    wall_holes(g, F, L, z0, zw, holes, mat, reveal_mat=reveal_mat, reveal=reveal,
               top=lambda u: zw + min(u, L - u) * t - inset, breaks=[L / 2])


def gable_tri(g, F, L, ze, zr, mat, u0=0.0):
    poly(g, mat, [F.p(u0, ze), F.p(L, ze), F.p((u0 + L) / 2, zr)], facing=F.N)


def sashes(g, F, u0, u1, z0, z1, cols=3, rows=2, cols_lo=None, rows_lo=None, mat='Trim', d=-0.07, single=False):
    """Double-hung sashes (or one fixed sash) with muntins and glazing, in a hole u0..u1, z0..z1."""
    zm = (z0 + z1) / 2
    parts = [(z0, z1, d, d + 0.035, cols, rows)] if single else [
        (zm - 0.02, z1, d, d + 0.035, cols, rows),
        (z0, zm + 0.02, d - 0.04, d - 0.005, cols_lo or cols, rows_lo or rows)]
    for (zb, zt, da, db, c, r) in parts:
        fw = 0.05
        fbox(g, mat, F, u0, u0 + fw, zb, zt, da, db)
        fbox(g, mat, F, u1 - fw, u1, zb, zt, da, db)
        fbox(g, mat, F, u0 + fw, u1 - fw, zb, zb + 0.06, da, db)
        fbox(g, mat, F, u0 + fw, u1 - fw, zt - 0.05, zt, da, db)
        iu0, iu1, iz0, iz1 = u0 + fw, u1 - fw, zb + 0.06, zt - 0.05
        poly(g, 'Glass', [F.p(iu0, iz0, da + 0.015), F.p(iu1, iz0, da + 0.015), F.p(iu1, iz1, da + 0.015),
                          F.p(iu0, iz1, da + 0.015)], facing=F.N)
        for i in range(1, c):
            uu = iu0 + (iu1 - iu0) * i / c
            fbox(g, mat, F, uu - 0.011, uu + 0.011, iz0, iz1, da + 0.01, db)
        for j in range(1, r):
            zz = iz0 + (iz1 - iz0) * j / r
            fbox(g, mat, F, iu0, iu1, zz - 0.011, zz + 0.011, da + 0.01, db)


def door_panel(g, F, u0, u1, z0, z1, d, mat='Door', panels=((2, 3),), glass_top=0.0, lites=(1, 1)):
    """Stile-and-rail door leaf with raised panels; optional glazed top fraction."""
    fbox(g, mat, F, u0, u1, z0, z1, d - 0.045, d)
    w = u1 - u0
    zg = z1 - (z1 - z0) * glass_top
    if glass_top > 0:
        gu0, gu1, gz0, gz1 = u0 + 0.12, u1 - 0.12, zg + 0.02, z1 - 0.12
        poly(g, 'Glass', [F.p(gu0, gz0, d + 0.003), F.p(gu1, gz0, d + 0.003), F.p(gu1, gz1, d + 0.003),
                          F.p(gu0, gz1, d + 0.003)], facing=F.N)
        for i in range(1, lites[0]):
            uu = gu0 + (gu1 - gu0) * i / lites[0]
            fbox(g, mat, F, uu - 0.012, uu + 0.012, gz0, gz1, d, d + 0.015)
        for j in range(1, lites[1]):
            zz = gz0 + (gz1 - gz0) * j / lites[1]
            fbox(g, mat, F, gu0, gu1, zz - 0.012, zz + 0.012, d, d + 0.015)
    nc, nr = panels[0]
    pz0, pz1 = z0 + 0.15, (zg - 0.1) if glass_top > 0 else z1 - 0.13
    if pz1 - pz0 > 0.2:
        ph = (pz1 - pz0 - 0.1 * (nr - 1)) / nr
        pw = (w - 0.24 - 0.1 * (nc - 1)) / nc
        for i in range(nc):
            for j in range(nr):
                a = u0 + 0.12 + i * (pw + 0.1)
                b = pz0 + j * (ph + 0.1)
                fbox(g, mat, F, a, a + pw, b, b + ph, d, d + 0.012)
                fbox(g, mat, F, a + 0.04, a + pw - 0.04, b + 0.04, b + ph - 0.04, d + 0.012, d + 0.02)


def knob(g, F, u, z, d):
    fbox(g, 'Brass', F, u - 0.02, u + 0.02, z - 0.02, z + 0.02, d, d + 0.06)


def lantern(g, F, uc, zc, mat='Metal'):
    fbox(g, mat, F, uc - 0.06, uc + 0.06, zc - 0.2, zc + 0.12, -0.005, 0.02)
    fbox(g, mat, F, uc - 0.015, uc + 0.015, zc - 0.02, zc + 0.02, 0.02, 0.1)
    b0, b1 = 0.08, 0.28
    fbox(g, 'LampGlass', F, uc - 0.09, uc + 0.09, zc - 0.17, zc + 0.15, b0 + 0.01, b1 - 0.01)
    for su in (-1, 1):
        for sd in (b0, b1 - 0.02):
            fbox(g, mat, F, uc + su * 0.09 - 0.012, uc + su * 0.09 + 0.012, zc - 0.17, zc + 0.15, sd, sd + 0.02)
    fbox(g, mat, F, uc - 0.11, uc + 0.11, zc + 0.15, zc + 0.19, b0 - 0.02, b1 + 0.02)
    fbox(g, mat, F, uc - 0.07, uc + 0.07, zc + 0.19, zc + 0.24, b0 + 0.02, b1 - 0.02)
    fbox(g, mat, F, uc - 0.1, uc + 0.1, zc - 0.21, zc - 0.17, b0, b1)


# ---------------------------------------------------------------------------- roofs
def gable_roof(g, x0, x1, y0, y1, zw, pitch, ov=0.35, rake=0.3, axis='x', th=0.05, fascia=0.2, soffit=True,
               top='Roof', trim='Trim', caps=True, cut_lo=None, cut_hi=None):
    """Gable roof over the rectangle; the roof surface passes through height zw on the wall lines.
    axis='x': ridge parallel to x (slopes face -y/+y). Returns dict with ridge height and eave height."""
    t = math.tan(math.radians(pitch))
    if axis == 'x':
        half = (y1 - y0) / 2
        yc = (y0 + y1) / 2
        zr = zw + half * t
        ze = zw - ov * t
        X0, X1 = x0 - rake, x1 + rake
        if cut_lo is not None:
            X0 = cut_lo
        if cut_hi is not None:
            X1 = cut_hi
        Ya, Yb = y0 - ov, y1 + ov
        faces = [[(X0, Ya, ze), (X1, Ya, ze), (X1, yc, zr), (X0, yc, zr)],
                 [(X1, Yb, ze), (X0, Yb, ze), (X0, yc, zr), (X1, yc, zr)]]
        for P in faces:
            roof_slab(g, P, th=th, top=top, edge=trim, bottom=trim)
        if caps:
            roof_caps(g, faces)
        for yy, s in ((Ya, 1), (Yb, -1)):    # eave fascia + soffit
            a, b = (yy, yy + 0.035) if s > 0 else (yy - 0.035, yy)
            box(g, trim, X0, X1, a, b, ze - fascia, ze - 0.005)
            if soffit:
                wall = y0 if s > 0 else y1
                zs = ze - fascia + 0.02
                poly(g, trim, [(X0, yy, zs), (X1, yy, zs), (X1, wall, zs), (X0, wall, zs)], facing=(0, 0, -1))
        for xx, s in ((X0, 1), (X1, -1)):   # rake boards
            if (s > 0 and cut_lo is not None) or (s < 0 and cut_hi is not None):
                continue
            Fx = Fr((xx, 0, 0), (0, 1, 0), (1, 0, 0))
            k = fascia / math.cos(math.atan(t))
            pts = [(Ya, ze), (yc, zr), (Yb, ze), (Yb, ze - k), (yc, zr - k), (Ya, ze - k)]
            extrude(g, trim, Fx, pts, 0.0 if s > 0 else -0.035, 0.035 if s > 0 else 0.0)
        return dict(zr=zr, ze=ze, faces=faces)
    else:
        half = (x1 - x0) / 2
        xc = (x0 + x1) / 2
        zr = zw + half * t
        ze = zw - ov * t
        Y0, Y1 = y0 - rake, y1 + rake
        if cut_lo is not None:
            Y0 = cut_lo
        if cut_hi is not None:
            Y1 = cut_hi
        Xa, Xb = x0 - ov, x1 + ov
        faces = [[(Xa, Y1, ze), (Xa, Y0, ze), (xc, Y0, zr), (xc, Y1, zr)],
                 [(Xb, Y0, ze), (Xb, Y1, ze), (xc, Y1, zr), (xc, Y0, zr)]]
        for P in faces:
            roof_slab(g, P, th=th, top=top, edge=trim, bottom=trim)
        if caps:
            roof_caps(g, faces)
        for xx, s in ((Xa, 1), (Xb, -1)):
            a, b = (xx, xx + 0.035) if s > 0 else (xx - 0.035, xx)
            box(g, trim, a, b, Y0, Y1, ze - fascia, ze - 0.005)
            if soffit:
                wall = x0 if s > 0 else x1
                zs = ze - fascia + 0.02
                poly(g, trim, [(xx, Y0, zs), (xx, Y1, zs), (wall, Y1, zs), (wall, Y0, zs)], facing=(0, 0, -1))
        for yy, s in ((Y0, 1), (Y1, -1)):
            if (s > 0 and cut_lo is not None) or (s < 0 and cut_hi is not None):
                continue
            Fy = Fr((0, yy, 0), (1, 0, 0), (0, -1, 0))
            k = fascia / math.cos(math.atan(t))
            pts = [(Xa, ze), (xc, zr), (Xb, ze), (Xb, ze - k), (xc, zr - k), (Xa, ze - k)]
            extrude(g, trim, Fy, pts, 0.0 if s > 0 else -0.035, 0.035 if s > 0 else 0.0)
        return dict(zr=zr, ze=ze, faces=faces)


def hip_roof(g, x0, x1, y0, y1, zw, pitch, ov=0.45, th=0.05, fascia=0.2, top='Roof', trim='Trim', soffit_mat=None,
             caps=True, pitch_ends=None):
    """Hip roof whose surface passes through zw on the wall lines; boxed eaves all round."""
    t = math.tan(math.radians(pitch))
    ze = zw - ov * t
    faces, ridge, hips, zr = hip_planes(x0 - ov, x1 + ov, y0 - ov, y1 + ov, ze, pitch_ends or pitch, pitch)
    for P in faces:
        roof_slab(g, P, th=th, top=top, edge=trim, bottom=trim)
    if caps:
        roof_caps(g, faces)
    X0, X1, Y0, Y1 = x0 - ov, x1 + ov, y0 - ov, y1 + ov
    path_run(g, trim, [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1), (X0, Y0)], ze - fascia, ze - 0.005, 0.0, -0.035)
    zs = ze - fascia + 0.02
    sm = soffit_mat or trim
    for P in ([(X0, Y0), (X1, Y0), (x1, y0), (x0, y0)], [(X1, Y0), (X1, Y1), (x1, y1), (x1, y0)],
              [(X1, Y1), (X0, Y1), (x0, y1), (x1, y1)], [(X0, Y1), (X0, Y0), (x0, y0), (x0, y1)]):
        poly(g, sm, [(p[0], p[1], zs) for p in P], facing=(0, 0, -1))
    return dict(zr=zr, ze=ze, faces=faces)


def shed_roof(g, x0, x1, y_lo, y_hi, z_lo, z_hi, th=0.05, fascia=0.18, top='Roof', trim='Trim', side_ov=0.0):
    """Mono-pitch roof falling toward y_lo (any order); fascia on the low edge and both sides."""
    X0, X1 = x0 - side_ov, x1 + side_ov
    P = [(X0, y_lo, z_lo), (X1, y_lo, z_lo), (X1, y_hi, z_hi), (X0, y_hi, z_hi)]
    roof_slab(g, P, th=th, top=top, edge=trim, bottom=trim)
    a, b = sorted((y_lo, y_lo + (0.035 if y_hi > y_lo else -0.035)))
    box(g, trim, X0, X1, a, b, z_lo - fascia, z_lo - 0.005)
    return P


# ---------------------------------------------------------------------------- columns, rails, steps
def tuscan_column(g, x, y, z0, z1, r=0.13, mat='Trim', seg=14):
    h = z1 - z0
    prof = [(r * 1.32, z0), (r * 1.32, z0 + 0.06), (r * 1.18, z0 + 0.075), (r * 1.18, z0 + 0.11), (r * 1.06, z0 + 0.13),
            (r, z0 + 0.16), (r, z0 + h * 0.33), (r * 0.86, z1 - 0.2), (r * 0.9, z1 - 0.17), (r * 0.9, z1 - 0.15),
            (r * 1.12, z1 - 0.075), (r * 1.12, z1 - 0.055)]
    lathe(g, mat, prof, x, y, seg=seg)
    cbox(g, mat, x, y, r * 2.6, r * 2.6, z1 - 0.055, z1)


def tapered_post(g, mat, cx, cy, z0, z1, w0, w1, wy0=None, wy1=None):
    """Square post tapering from w0 (bottom) to w1 (top)."""
    wy0 = wy0 or w0
    wy1 = wy1 or w1
    V = [(cx - w0 / 2, cy - wy0 / 2, z0), (cx + w0 / 2, cy - wy0 / 2, z0), (cx + w0 / 2, cy + wy0 / 2, z0),
         (cx - w0 / 2, cy + wy0 / 2, z0),
         (cx - w1 / 2, cy - wy1 / 2, z1), (cx + w1 / 2, cy - wy1 / 2, z1), (cx + w1 / 2, cy + wy1 / 2, z1),
         (cx - w1 / 2, cy + wy1 / 2, z1)]
    g.add(V, [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], mat)


def railing(g, p0, p1, z0, h=0.9, mat='Trim', bal=0.04, pitch=0.12, top_w=0.09, rake=0.0):
    """Square-baluster railing from p0 to p1 (2D), standing on z0 (z0 + rake at p1)."""
    p0, p1 = Vector((p0[0], p0[1], 0)), Vector((p1[0], p1[1], 0))
    L = (p1 - p0).length
    U = (p1 - p0).normalized()
    N = U.cross(Vector((0, 0, 1)))
    F = Fr((p0.x, p0.y, 0), U, N)
    k = max(1, int(L / pitch))
    for i in range(k):
        u = (i + 0.5) * L / k
        zb = z0 + rake * u / L
        fbox(g, mat, F, u - bal / 2, u + bal / 2, zb + 0.08, zb + h - 0.06, -bal / 2, bal / 2)
    for zz, hh, ww in ((0.06, 0.05, 0.07), (h - 0.06, 0.06, top_w)):
        pts = [(0, z0 + zz), (L, z0 + zz + rake), (L, z0 + zz + hh + rake), (0, z0 + zz + hh)]
        extrude(g, mat, F, pts, -ww / 2, ww / 2)


def stair(g, mat, xc, w, y_edge, z_top, run=0.29, max_rise=0.185, cheek=None, cheek_mat=None, nosing=0.025,
          direction=-1):
    """Straight stair descending from a floor edge at y_edge (height z_top) toward direction*y to grade.
    Treads are solid blocks down to z=-0.3. Returns the y of the bottom riser."""
    n = max(1, int(math.ceil(z_top / max_rise)))
    rise = z_top / n
    for k in range(1, n):
        zt = z_top - k * rise
        ya = y_edge + direction * k * run
        y_lo, y_hi = sorted((ya, y_edge))
        box(g, mat, xc - w / 2, xc + w / 2, y_lo - (nosing if direction < 0 else 0), y_hi + (nosing if direction > 0 else 0),
            -0.3, zt)
    yb = y_edge + direction * (n - 1) * run
    if cheek:
        cw = cheek
        y_lo, y_hi = sorted((yb, y_edge))
        for s in (-1, 1):
            x = xc + s * (w / 2 + cw / 2)
            # stepped cheek wall following the stair
            Fc = Fr((x - cw / 2, 0, 0), (0, 1, 0), (1, 0, 0))
            if direction < 0:
                pts = [(yb - 0.05, -0.3), (y_edge, -0.3), (y_edge, z_top + 0.1), (yb - 0.05, rise + 0.1)]
            else:
                pts = [(y_edge, -0.3), (yb + 0.05, -0.3), (yb + 0.05, rise + 0.1), (y_edge, z_top + 0.1)]
            extrude(g, cheek_mat or mat, Fc, pts, 0.0, cw)
    return yb


# ---------------------------------------------------------------------------- plants
def leaf_clump(g, mat, c, r, seed, col, nfn=None, flat=0.72, sub=1, rough=0.34):
    blob(g, mat, c, (r, r * 0.95, r * flat), seed=seed, rough=rough, freq=2.2, sub=sub, nfn=nfn,
         colfn=lambda q, d, col=col: col)


def leaf_spray(g, mat, c, size, n_out, rng, col, nleaf=5):
    """A spray of nleaf pointed leaves radiating from c in a plane facing roughly n_out. Opaque, double-sided;
    shaded with the crown normal so a canopy of sprays lights softly, with real gaps between leaves."""
    c = Vector(c)
    n = (Vector(n_out) + Vector(rng.normal(0, 0.7, 3))).normalized()
    t1 = n.cross(Vector((0.3, 0.5, 0.8)).normalized())
    if t1.length < 1e-4:
        t1 = n.cross(Vector((1, 0, 0)))
    t1.normalize()
    t2 = n.cross(t1)
    V, F, N, C = [], [], [], []
    nb = (Vector(n_out) * 0.75 + n * 0.25).normalized()
    a0 = rng.uniform(0, 6.3)
    for i in range(nleaf):
        a = a0 + 2 * math.pi * i / nleaf + rng.uniform(-0.25, 0.25)
        dvec = t1 * math.cos(a) + t2 * math.sin(a)
        perp = n.cross(dvec)
        L = size * rng.uniform(0.7, 1.0)
        w = L * rng.uniform(0.32, 0.42)
        k = len(V)
        V += [c + dvec * 0.03, c + dvec * L * 0.45 + perp * w / 2 + n * L * 0.08, c + dvec * L + n * L * 0.12,
              c + dvec * L * 0.45 - perp * w / 2 + n * L * 0.08]
        F.append([k, k + 1, k + 2, k + 3])
        t = rng.uniform(0.88, 1.12)
        C += [(col[0] * t * 0.85, col[1] * t * 0.85, col[2] * t * 0.85)] + [(col[0] * t, col[1] * t, col[2] * t)] * 3
        N += [tuple(nb)] * 4
    g.add(V, F, mat, smooth=True, colors=C, normals=N)


def leafy_tree(g, base, H, spread, seed, clear=2.2, trunk_r=0.2, n_limbs=6, leaf_mat='Leaves', density=1.0,
               clump_r=(0.3, 0.45), tone=(0.62, 0.72, 0.4), shape=1.0, lean=(0.0, 0.0), limb_seg=8, sprays=12,
               cluster_r=0.45, leaves=5, bounds=None):
    """Broadleaf tree from many small leaf clumps hung on a visible branch frame. The clumps cluster at
    branch ends, leave gaps for sky and limbs, and are darker underneath and toward the inside."""
    rng = np.random.default_rng(seed)
    bx, by = base
    cz = clear + (H - clear) * 0.52
    R, Rz = spread / 2, (H - clear) / 2
    fork = Vector((bx + lean[0], by + lean[1], clear + (H - clear) * 0.18))
    tube(g, 'Bark', [(bx, by, -0.5), (bx, by, 0.0), (bx + lean[0] * 0.4, by + lean[1] * 0.4, clear * 0.55), tuple(fork)],
         [trunk_r * 1.35, trunk_r * 1.2, trunk_r, trunk_r * 0.85], seg=10)
    for k in range(4):   # root flare
        a = 2 * math.pi * k / 4 + rng.uniform(-0.3, 0.3)
        tube(g, 'Bark', [(bx + math.cos(a) * trunk_r * 0.5, by + math.sin(a) * trunk_r * 0.5, 0.5),
                         (bx + math.cos(a) * trunk_r * 1.3, by + math.sin(a) * trunk_r * 1.3, -0.05)],
             [trunk_r * 0.4, trunk_r * 0.15], seg=5)
    nfn = crown_normals((bx + lean[0], by + lean[1], cz - Rz * 0.25), (R, R, Rz), 0.3)
    tips = []
    for i in range(n_limbs):
        az = 2 * math.pi * i / n_limbs + rng.uniform(-0.35, 0.35)
        el = rng.uniform(0.25, 0.75)
        d = Vector((math.cos(az), math.sin(az), 0))
        end = Vector((fork.x + d.x * R * rng.uniform(0.55, 0.75), fork.y + d.y * R * rng.uniform(0.55, 0.75),
                      cz + Rz * (el - 0.35)))
        mid = fork.lerp(end, 0.5) + Vector((0, 0, rng.uniform(0.2, 0.7)))
        tube(g, 'Bark', [tuple(fork), tuple(mid), tuple(end)], [trunk_r * 0.62, trunk_r * 0.38, trunk_r * 0.12], seg=limb_seg)
        tips.append(end)
        for j in range(2):
            s = mid.lerp(end, rng.uniform(0.1, 0.6))
            a2 = az + rng.uniform(-0.9, 0.9)
            e2 = Vector((s.x + math.cos(a2) * R * rng.uniform(0.3, 0.45), s.y + math.sin(a2) * R * rng.uniform(0.3, 0.45),
                         s.z + Rz * rng.uniform(0.15, 0.6)))
            tube(g, 'Bark', [tuple(s), tuple(s.lerp(e2, 0.5) + Vector((0, 0, 0.15))), tuple(e2)],
                 [trunk_r * 0.22, trunk_r * 0.13, trunk_r * 0.05], seg=5, cap_end=False)
            tips.append(e2)
        up = Vector((fork.x + d.x * R * 0.25, fork.y + d.y * R * 0.25, cz + Rz * rng.uniform(0.45, 0.8)))
        tube(g, 'Bark', [tuple(fork.lerp(mid, 0.4)), tuple(up)], [trunk_r * 0.3, trunk_r * 0.06], seg=5, cap_end=False)
        tips.append(up)
    # clusters: around each tip plus points on the crown shell
    centers = []
    for tp in tips:
        centers.append((tp, 1.0))
    nshell = int(38 * density * (R * Rz) / 10.0) + 8
    for k in range(nshell):
        zf = 1 - 2 * (k + 0.5) / nshell
        rr = math.sqrt(max(0.0, 1 - zf * zf))
        a = k * 2.39996 + rng.uniform(-0.3, 0.3)
        f = rng.uniform(0.72, 0.98)
        p = Vector((fork.x + math.cos(a) * rr * R * f, fork.y + math.sin(a) * rr * R * f, cz + zf * Rz * f * shape))
        if p.z < clear + 0.4:
            continue
        centers.append((p, f))
    cc = Vector((fork.x, fork.y, cz - Rz * 0.25))
    for ci, (p, f) in enumerate(centers):
        mg = 2.3 * cluster_r + clump_r[1] + 0.1
        if bounds and not (bounds[0] + mg < p.x < bounds[2] - mg and bounds[1] + mg < p.y < bounds[3] - mg):
            continue
        rad = (p - Vector((fork.x, fork.y, cz))).length
        outer = min(1.0, rad / max(R, 0.1))
        for m in range(sprays):
            o = Vector(rng.normal(0, 1, 3)) * cluster_r
            o.z *= 0.55
            q = p + o
            nrm = Vector(nfn(q, (q - cc).normalized()))
            hz = (q.z - (cz - Rz)) / (2 * Rz)
            b = (0.5 + 0.5 * max(0.0, min(1.0, hz))) * (0.7 + 0.3 * outer) * rng.uniform(0.85, 1.1)
            hue = rng.uniform(-0.06, 0.06)
            col = (tone[0] * b * (1 + hue), tone[1] * b, tone[2] * b * (1 - hue))
            leaf_spray(g, leaf_mat, q, rng.uniform(*clump_r), nrm, rng, col, nleaf=leaves)


def bush(g, mat, c, size, seed, tone=1.0, n=6, fine=False):
    """Light shrub: a few noisy masses, darker toward the ground."""
    rng = np.random.default_rng(seed)
    rx, ry, H = size
    nfn = crown_normals((c[0], c[1], H * 0.3), (rx, ry, H * 0.75), 0.35)
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.4, 0.4)
        f = rng.uniform(0.25, 0.45) if i else 0.0
        cx, cy = c[0] + math.cos(a) * rx * f, c[1] + math.sin(a) * ry * f
        s = rng.uniform(0.6, 0.78)
        cz = H * rng.uniform(0.45, 0.55) if i else H * 0.58
        t = tone * rng.uniform(0.9, 1.08)
        blob(g, mat, (cx, cy, cz), (rx * s, ry * s, H * 0.45), seed=seed * 7 + i, rough=0.3, freq=2.4,
             sub=2 if (fine or not i) else 1,
             colfn=lambda q, d, t=t: (t * (0.42 + 0.58 * min(1.0, max(0.0, q.z / max(H, 0.1)))),) * 3,
             flat_bottom=-0.03, nfn=nfn)


def ground_cover(g, mat, cx, cy, rx, ry, seed, n=12, h=0.25, tone=(0.55, 0.6, 0.4)):
    """Low groundcover / perennials: a scatter of very flat little clumps."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        a = rng.uniform(0, 2 * math.pi)
        f = math.sqrt(rng.uniform(0, 1))
        x, y = cx + math.cos(a) * rx * f, cy + math.sin(a) * ry * f
        r = rng.uniform(0.18, 0.32)
        b = rng.uniform(0.85, 1.1)
        blob(g, mat, (x, y, h * 0.4), (r, r, h * 0.6), seed=seed * 50 + i, rough=0.3, freq=2.4, sub=1,
             colfn=lambda q, d, b=b: (tone[0] * b, tone[1] * b, tone[2] * b), flat_bottom=0.0)


# ---------------------------------------------------------------------------- site
def slab(g, mat, pts, z_top, z_bot=-0.12):
    extrude(g, mat, WORLD, pts, z_bot, z_top)


def ngon(cx, cy, rx, ry=None, n=18, jitter=0.0, seed=0, a0=0.0):
    rng = np.random.default_rng(seed)
    ry = ry or rx
    return [(cx + rx * (1 + rng.uniform(-jitter, jitter)) * math.cos(a0 + 2 * math.pi * i / n),
             cy + ry * (1 + rng.uniform(-jitter, jitter)) * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def mailbox(g, x, y):
    """Post-mounted rural mailbox at the curb, facing the street (-y)."""
    cbox(g, 'Post', x, y, 0.1, 0.1, -0.5, 1.05)
    cbox(g, 'Post', x, y - 0.12, 0.14, 0.42, 0.98, 1.03)
    W = 0.085
    pts = [(-W, 1.03), (W, 1.03), (W, 1.15)] + [(W * math.cos(math.pi * k / 6), 1.15 + W * math.sin(math.pi * k / 6))
                                                 for k in range(1, 6)] + [(-W, 1.15)]
    Fb = Fr((x, y + 0.12, 0), (1, 0, 0), (0, -1, 0))
    extrude(g, 'MailMetal', Fb, pts, 0.0, 0.48)


def trash_cart(g, x, y, rot=0.0, mat='Cart'):
    c, s = math.cos(rot), math.sin(rot)

    def P(px, py, pz):
        return (x + px * c - py * s, y + px * s + py * c, pz)
    V = [P(-0.29, -0.36, 0.0), P(0.29, -0.36, 0.0), P(0.29, 0.36, 0.0), P(-0.29, 0.36, 0.0),
         P(-0.32, -0.4, 1.0), P(0.32, -0.4, 1.0), P(0.32, 0.4, 1.0), P(-0.32, 0.4, 1.0)]
    g.add(V, [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], mat)
    V = [P(-0.34, -0.43, 1.0), P(0.34, -0.43, 1.0), P(0.34, 0.43, 1.0), P(-0.34, 0.43, 1.0),
         P(-0.34, -0.43, 1.05), P(0.34, -0.43, 1.05), P(0.34, 0.43, 1.05), P(-0.34, 0.43, 1.05)]
    g.add(V, [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], mat)


def hvac(g, x, y):
    cbox(g, 'Concrete', x, y, 1.0, 1.0, -0.1, 0.08)
    cbox(g, 'Condenser', x, y, 0.85, 0.85, 0.08, 0.95)
    cbox(g, 'Metal', x, y, 0.6, 0.6, 0.95, 0.97)


def car(g, x, y, rot=0.0, body='CarPaint', L=4.8, W=1.85):
    """Simple sedan/SUV massing (render-only use is fine; kept low-poly)."""
    c, s = math.cos(rot), math.sin(rot)

    def P(px, py, pz):
        return (x + px * c - py * s, y + px * s + py * c, pz)

    def bx_(x0, x1, y0, y1, z0, z1, m, inset_top=0.0, inset_y=0.0):
        V = [P(x0, y0, z0), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0),
             P(x0 + inset_top, y0 + inset_y, z1), P(x1 - inset_top, y0 + inset_y, z1), P(x1 - inset_top, y1 - inset_y, z1),
             P(x0 + inset_top, y1 - inset_y, z1)]
        g.add(V, [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], m)
    # car runs along local y
    bx_(-W / 2, W / 2, -L / 2, L / 2, 0.32, 0.95, body)
    bx_(-W / 2 + 0.06, W / 2 - 0.06, -L / 2 + 1.1, L / 2 - 0.7, 0.95, 1.45, 'Glass', inset_top=0.12, inset_y=0.35)
    for sx in (-1, 1):
        for sy in (-1, 1):
            V0 = P(sx * (W / 2 - 0.12), sy * (L / 2 - 0.85), 0.34)
            cyl_ = []
            seg = 10
            for i in range(seg):
                a = 2 * math.pi * i / seg
                cyl_.append((math.cos(a) * 0.34, math.sin(a) * 0.34))
            Fw = Fr(V0, (c * 0 - s * 1, s * 0 + c * 1, 0) if False else (-s, c, 0), (c, s, 0))
            extrude(g, 'Tire', Fw, [(u, z - 0.0) for u, z in [(cc[0], cc[1]) for cc in cyl_]], -0.11, 0.11)


# ---------------------------------------------------------------------------- run
def bbox(objs):
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            mn = Vector((min(mn.x, p.x), min(mn.y, p.y), min(mn.z, p.z)))
            mx = Vector((max(mx.x, p.x), max(mx.y, p.y), max(mx.z, p.z)))
    return mn, mx


def export_set(objs, path):
    wp.finalize(objs)
    for o in objs:
        apply_custom_uvs(o)
    wp.export_glb(path, objs)
    return wp.tri_count(objs)


def street_and_backdrop(curb_y, x0=-120, x1=120, width=9.0, trees=(), seed=900):
    """Render-only: curb, gutter and asphalt street at the curb line, plus a few background trees."""
    objs = []
    gx = Geo('Render_Street')
    MAT['Asphalt'] = wp.mat('Asphalt', tex=wp.tex_ground('hb_asphalt', kind='asphalt', n=512, tile=4.0), rough=0.9)
    if 'Concrete' not in MAT:
        MAT['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('hb_conc', kind='concrete', n=512, tile=3.0, seed=23)[0], None, 3.0), rough=0.9)
    slab(gx, 'Concrete', [(x0, curb_y - 0.15), (x1, curb_y - 0.15), (x1, curb_y), (x0, curb_y)], 0.12)
    slab(gx, 'Concrete', [(x0, curb_y - 0.6), (x1, curb_y - 0.6), (x1, curb_y - 0.15), (x0, curb_y - 0.15)], 0.008)
    slab(gx, 'Asphalt', [(x0, curb_y - width * 2), (x1, curb_y - width * 2), (x1, curb_y - 0.6), (x0, curb_y - 0.6)], 0.005)
    slab(gx, 'Concrete', [(x0, curb_y - width * 2 - 0.6), (x1, curb_y - width * 2 - 0.6), (x1, curb_y - width * 2),
                          (x0, curb_y - width * 2)], 0.12)
    objs.append(gx.build())
    for i, (b, H, S) in enumerate(trees):
        g = Geo(f'Render_BG_{i}')
        leafy_tree(g, b, H, S, seed + i, clear=H * 0.25, trunk_r=0.03 * H, n_limbs=6, density=0.8,
                   clump_r=(0.5, 0.75), leaf_mat='Leaves', sprays=10, cluster_r=0.7)
        objs.append(g.build())
    return objs


def setup_render(samples, res, sun_elev=46, sun_az=205, exposure=0.4):
    sun, _ = wp.render_rig(samples=samples, res=res, sun_elev=sun_elev, sun_az=sun_az, threads=2, exposure=exposure)
    sc = bpy.context.scene
    try:
        sc.cycles.max_bounces = 6
        sc.cycles.diffuse_bounces = 3
        sc.cycles.glossy_bounces = 2
        sc.cycles.transmission_bounces = 2
        sc.cycles.transparent_max_bounces = 4
        sc.cycles.adaptive_threshold = 0.02
    except Exception:
        pass
    sun.data.color = (1.0, 0.94, 0.85)
    sun.data.energy = 4.3
    sun.data.angle = math.radians(1.2)
    wnt = sc.world.node_tree
    bgn = wnt.nodes['Background']
    sky_link = bgn.inputs['Color'].links[0]
    mixn = wnt.nodes.new('ShaderNodeMix')
    mixn.data_type = 'RGBA'
    mixn.inputs['Factor'].default_value = 0.35
    mixn.inputs[7].default_value = (0.62, 0.62, 0.58, 1.0)
    wnt.links.new(sky_link.from_socket, mixn.inputs[6])
    wnt.links.new(mixn.outputs[2], bgn.inputs['Color'])
    bgn.inputs['Strength'].default_value = 0.42
    lawn = bpy.data.materials.get('RenderLawn')
    if lawn:
        mixl = lawn.node_tree.nodes.new('ShaderNodeMix')
        mixl.data_type = 'RGBA'
        mixl.blend_type = 'MULTIPLY'
        mixl.inputs['Factor'].default_value = 1.0
        mixl.inputs[7].default_value = (0.92, 1.0, 0.66, 1.0)
        bsd = lawn.node_tree.nodes['Principled BSDF']
        src = bsd.inputs['Base Color'].links[0].from_socket
        lawn.node_tree.links.new(src, mixl.inputs[6])
        lawn.node_tree.links.new(mixl.outputs[2], bsd.inputs['Base Color'])
    return sun


def run(H):
    """H: dict with id, build_house(), build_lot(), meta(dict), cams, curb_y, backdrop trees, make_materials()."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='24 samples, 640x400 test renders')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--out', default=None, help='render folder (default: repo renders/)')
    ap.add_argument('--views', default='hero,aerial')
    ap.add_argument('--samples', type=int, default=None)
    args = ap.parse_args()
    ID = H['id']
    wp.reset()
    H['make_materials']()
    house_geos = H['build_house']()
    lot_geos = H['build_lot']()
    for g in house_geos + lot_geos:
        print(f'{g.name:20s} {g.tris():8d} tris  mats={g.mats}')
    house_objs = [g.build() for g in house_geos]
    lot_objs = [g.build() for g in lot_geos]
    mdir = os.path.join(wp.REPO, 'models', 'homes')
    house_glb = os.path.join(mdir, f'{ID}.glb')
    lot_glb = os.path.join(mdir, f'{ID}-lot.glb')
    if args.no_export:
        mdir = os.path.join(wp.TEX_DIR, 'glb')
        house_glb = os.path.join(mdir, f'{ID}.glb')
        lot_glb = os.path.join(mdir, f'{ID}-lot.glb')
    th = export_set(house_objs, house_glb)
    tl = export_set(lot_objs, lot_glb)
    mn, mx = bbox(house_objs)
    lmn, lmx = bbox(lot_objs)
    print(f'house bbox {tuple(round(v, 2) for v in mn)} .. {tuple(round(v, 2) for v in mx)}')
    print(f'lot   bbox {tuple(round(v, 2) for v in lmn)} .. {tuple(round(v, 2) for v in lmx)}')
    if 'lot_rect' in H:
        x0, y0, x1, y1 = H['lot_rect']
        ok = lmn.x >= x0 - 1e-3 and lmn.y >= y0 - 1e-3 and lmx.x <= x1 + 1e-3 and lmx.y <= y1 + 1e-3
        print('LOT RECT CHECK', 'OK' if ok else 'OUTSIDE', H['lot_rect'])
    meta = dict(H['meta'])
    meta.update({'top_height_m': round(mx.z, 2), 'triangles': th + tl, 'triangles_house': th, 'triangles_lot': tl,
                 'files': {'house': f'models/homes/{ID}.glb', 'lot': f'models/homes/{ID}-lot.glb'},
                 'file_mb': {'house': round(os.path.getsize(house_glb) / 1e6, 2),
                             'lot': round(os.path.getsize(lot_glb) / 1e6, 2)},
                 'house_bbox_m': [[round(v, 2) for v in mn], [round(v, 2) for v in mx]],
                 'lot_bbox_m': [[round(v, 2) for v in lmn], [round(v, 2) for v in lmx]]})
    order = ['id', 'name', 'address', 'neighborhood', 'residents', 'status', 'atlas_building_index', 'footprint_m',
             'ridge_height_m', 'top_height_m', 'stories', 'style', 'materials', 'triangles', 'triangles_house',
             'triangles_lot', 'files', 'file_mb', 'house_bbox_m', 'lot_bbox_m', 'lot_local_rect_m', 'curb_line_local_y',
             'notes']
    meta = {k: meta[k] for k in order if k in meta}
    with open(os.path.join(mdir, f'{ID}.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print(json.dumps({k: meta[k] for k in ('triangles', 'triangles_house', 'triangles_lot', 'file_mb', 'ridge_height_m')}))
    if args.no_render:
        return
    out = args.out or os.path.join(wp.REPO, 'renders')
    samples = args.samples or (24 if args.quick else 96)
    res = (640, 400) if args.quick else (1600, 1000)
    extras = street_and_backdrop(H['curb_y'], trees=H.get('backdrop', ()))
    wp.finalize(extras)
    for o in extras:
        apply_custom_uvs(o)
    setup_render(samples, res, **H.get('sun', {}))
    views = args.views.split(',')
    for v in views:
        c = H['cams'].get(v)
        if not c:
            continue
        for o in bpy.context.scene.objects:
            o.hide_render = o.name in c.get('hide', ())
        wp.camera(c['loc'], c['target'], c['lens'])
        name = f'{ID}.jpg' if v == 'hero' else f'{ID}-{v}.jpg'
        wp.render(os.path.join(out, name))
# <<< KIT <<<

# ============================================================================ site + plan (meters)
ID = 'al-hassan-house'
CURB = -28.94
LOT = (-20.5, CURB, 22.0, 25.0)          # halfway to the neighbours at x = -42.1 and +45.2
FF = 0.75
F2 = FF + 2.95
ZW = F2 + 2.75                           # main roof surface at the wall line
PITCH = 35.0
TM = math.tan(math.radians(PITCH))
MX0, MX1, MY0, MY1 = -3.6, 9.0, -4.6, 4.6            # main block
XG0, XG1 = 0.8, 5.0                                  # front cross gable (flush with the front wall)
GP = 44.0                                            # cross-gable pitch
TG = math.tan(math.radians(GP))
GX0, GX1, GY0, GY1 = -11.8, MX0, -3.0, 4.6           # garage
PY0 = -7.5                                           # front porch edge
SX0, SX1, SY1 = 3.4, 9.0, 9.2                        # screened porch (back right)
ENT = 2.9
ZR = ZW + (MY1 - MY0) / 2 * TM


def tex_bnb(key, color='#efeee9', n=1024, tile=1.2, seed=301, pitch=0.30):
    """Painted board-and-batten: wide vertical boards, 60 mm battens over the joints, soft paint variation."""
    rng = np.random.default_rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    k = int(round(tile / pitch))
    pitch = tile / k
    xm = x % pitch
    bat = (np.abs(xm - pitch / 2) < 0.03).astype(np.float32)
    edge = (np.abs(np.abs(xm - pitch / 2) - 0.03) < 0.004).astype(np.float32)
    big = wp._noise(n, 3 * tile, rng, 4)
    fine = wp._noise(n, 40 * tile, rng, 2)
    base = wp._rgb(color)
    shade = 0.96 + 0.04 * bat - 0.12 * edge
    alb = base[None, None, :] * (shade * (0.975 + 0.04 * big + 0.012 * fine))[..., None]
    h = bat * 0.8 + fine * 0.05
    return wp._save(alb, key), wp._save(wp._normal_from_height(h, 2.0), key + '_n'), tile


# ============================================================================ materials
def make_materials():
    M = {}
    M['Siding'] = wp.mat('Siding', tex=tex_bnb('ah_bnb'), rough=0.6)
    M['Trim'] = wp.mat('Trim', tex=tex_paint('ah_trim', '#f2f1ec', seed=302), rough=0.5)
    M['Frame'] = wp.mat('Frame', '#1a1b1c', rough=0.35, metal=0.3)
    M['Dark'] = wp.mat('Dark', '#1a1816', rough=0.9)
    M['Glass'] = wp.mat('Glass', '#ffffff', rough=0.04, tex=tex_glass('ah_glass', seed=303))
    M['Roof'] = wp.mat('Roof', tex=wp.tex_metal('ah_seam', color='#33363a', n=1024, tile=1.8, seam=True, seed=304),
                       rough=0.42, metal=0.55)
    M['Wood'] = wp.mat('Wood', tex=wp.tex_wood('ah_cedar', color='#9c6c44', n=512, board=0.1, seed=305), rough=0.55)
    M['Deck'] = wp.mat('Deck', tex=wp.tex_wood('ah_deck', color='#8a857c', n=512, board=0.14, seed=306, weathered=0.2),
                       rough=0.7)
    M['Foundation'] = wp.mat('Foundation', tex=wp.tex_ground('ah_found', kind='stucco', color='#7f7e79', n=512, tile=2.0,
                                                             seed=307), rough=0.85)
    M['GarageDoor'] = wp.mat('GarageDoor', tex=tex_paint('ah_gdoor', '#3a3c3e', seed=308, amp=0.04), rough=0.4, metal=0.2)
    M['Screen'] = wp.mat('Screen', '#22262a', rough=0.7, alpha=0.5)
    M['Metal'] = wp.mat('Metal', '#1c1d1f', rough=0.4, metal=0.7)
    M['LampGlass'] = wp.mat('LampGlass', '#ece3cb', rough=0.2)
    M['Concrete'] = wp.mat('Concrete', tex=(wp.tex_ground('ah_conc', kind='concrete', color='#c4c0b7', n=512, tile=3.0,
                                                          seed=309)[0], None, 3.0), rough=0.9)
    # lot
    M['Paver'] = wp.mat('Paver', tex=(wp.tex_ground('ah_paver', kind='concrete', color='#b7b2a8', n=512, tile=1.2,
                                                    seed=310)[0], None, 1.2), rough=0.85)
    M['Gravel'] = wp.mat('Gravel', tex=(wp.tex_ground('ah_gravel', kind='gravel', color='#b4ab9b', n=512, tile=2.0,
                                                      seed=311)[0], None, 2.0), rough=0.95)
    M['Mulch'] = wp.mat('Mulch', tex=(tex_straw('ah_mulch', n=512)[0], None, 1.5), rough=0.95)
    M['Bark'] = wp.mat('Bark', tex=tex_paint('ah_birch', '#c9c2b5', seed=312, amp=0.12), rough=0.8)
    M['Leaves'] = vc_material('Leaves', tex_canopy('ah_leaves', '#6c8d3c', n=512, tile=0.8, seed=313, lo=0.6), rough=0.62,
                              double=True)
    M['Grass'] = vc_material('Grass', tex_leaves('ah_grass', '#9a9a62', n=512, tile=0.4, seed=314), rough=0.8)
    M['Flowers'] = vc_material('Flowers', tex_leaves('ah_hydrangea', '#4a6a30', n=512, tile=0.5, seed=315, flowers='#b9c6e6',
                                                     fcov=0.45, fsize=30), rough=0.65)
    M['Boxwood'] = vc_material('Boxwood', tex_leaves('ah_boxwood', '#42622c', n=512, tile=0.6, seed=316), rough=0.6)
    M['MailMetal'] = wp.mat('MailMetal', '#1c1d1f', rough=0.4, metal=0.6)
    M['Post'] = wp.mat('Post', '#1c1d1f', rough=0.5)
    M['Condenser'] = wp.mat('Condenser', '#8d8f8a', rough=0.5, metal=0.3)
    M['Cart'] = wp.mat('Cart', '#3b3f44', rough=0.6)
    MAT.update(M)
    return M


# ============================================================================ house parts
def mwindow(g, F, uc, sill, w, h, holes, split=None, transom=None):
    """Black-framed modern window: slim aluminium-clad frame, optional vertical split (casement pair) and
    transom bar, a thin flat white casing and a black metal sill."""
    u0, u1, z0, z1 = uc - w / 2, uc + w / 2, sill, sill + h
    holes.append((u0, u1, z0, z1))
    c = 0.09
    fbox(g, 'Trim', F, u0 - c, u0, z0, z1, -0.005, 0.022)
    fbox(g, 'Trim', F, u1, u1 + c, z0, z1, -0.005, 0.022)
    fbox(g, 'Trim', F, u0 - c, u1 + c, z1, z1 + c, -0.005, 0.022)
    fbox(g, 'Frame', F, u0 - c - 0.01, u1 + c + 0.01, z0 - 0.04, z0, -0.08, 0.05)
    d = -0.07
    fw = 0.065
    for a, b, za, zb in ((u0, u0 + fw, z0, z1), (u1 - fw, u1, z0, z1), (u0, u1, z0, z0 + fw), (u0, u1, z1 - fw, z1)):
        fbox(g, 'Frame', F, a, b, za, zb, d - 0.05, d)
    poly(g, 'Glass', [F.p(u0 + fw, z0 + fw, d - 0.03), F.p(u1 - fw, z0 + fw, d - 0.03), F.p(u1 - fw, z1 - fw, d - 0.03),
                      F.p(u0 + fw, z1 - fw, d - 0.03)], facing=F.N)
    if split:
        for i in range(1, split):
            uu = u0 + (u1 - u0) * i / split
            fbox(g, 'Frame', F, uu - 0.035, uu + 0.035, z0, z1, d - 0.05, d)
    if transom:
        fbox(g, 'Frame', F, u0, u1, z1 - transom - 0.035, z1 - transom + 0.035, d - 0.05, d)


def front_door(g, F, uc, z0, holes):
    """Wide stained-oak door with a full-height glass sidelight, black frame."""
    w, h, side = 1.07, 2.45, 0.5
    u0, u1 = uc - w / 2, uc + w / 2 + side
    holes.append((u0, u1, z0, z0 + h))
    c = 0.09
    fbox(g, 'Trim', F, u0 - c, u0, z0, z0 + h, -0.005, 0.022)
    fbox(g, 'Trim', F, u1, u1 + c, z0, z0 + h, -0.005, 0.022)
    fbox(g, 'Trim', F, u0 - c, u1 + c, z0 + h, z0 + h + c, -0.005, 0.022)
    for a, b in ((u0, u0 + 0.05), (u1 - 0.05, u1), (uc + w / 2, uc + w / 2 + 0.05)):
        fbox(g, 'Frame', F, a, b, z0, z0 + h, -0.14, -0.06)
    fbox(g, 'Frame', F, u0, u1, z0 + h - 0.05, z0 + h, -0.14, -0.06)
    fbox(g, 'Wood', F, u0 + 0.05, uc + w / 2, z0, z0 + h - 0.05, -0.13, -0.09)
    for k in range(5):     # horizontal reveal grooves
        zz = z0 + 0.4 + k * 0.4
        fbox(g, 'Dark', F, u0 + 0.12, uc + w / 2 - 0.08, zz, zz + 0.012, -0.09, -0.088)
    fbox(g, 'Frame', F, uc + w / 2 - 0.12, uc + w / 2 - 0.09, z0 + 0.6, z0 + 1.6, -0.09, -0.02)
    poly(g, 'Glass', [F.p(uc + w / 2 + 0.05, z0 + 0.02, -0.11), F.p(u1 - 0.05, z0 + 0.02, -0.11), F.p(u1 - 0.05, z0 + h - 0.05, -0.11),
                      F.p(uc + w / 2 + 0.05, z0 + h - 0.05, -0.11)], facing=F.N)
    fbox(g, 'Concrete', F, u0, u1, z0 - 0.02, z0 + 0.015, -0.16, 0.0)


def wall_lamp(g, F, uc, zc):
    """Black barn-style wall light."""
    fbox(g, 'Metal', F, uc - 0.05, uc + 0.05, zc - 0.08, zc + 0.08, -0.005, 0.02)
    seg_box(g, 'Metal', F.p(uc, zc, 0.02), F.p(uc, zc + 0.12, 0.22), 0.025, 0.025, up=tuple(F.U), d0=-0.0125)
    lathe(g, 'Metal', [(0.0, zc + 0.22), (0.17, zc + 0.08), (0.17, zc + 0.06), (0.0, zc + 0.06)],
          *tuple((F.p(uc, 0, 0.28))[:2]), seg=12, caps=False)


def front_top(L):
    """Front wall top: eave line with the cross gable rising between XG0 and XG1."""
    a, b = XG0 - MX0, XG1 - MX0
    m = (a + b) / 2

    def f(u):
        return ZW - 0.03 + max(0.0, ((b - a) / 2 - abs(u - m)) * TG) * (1 if a <= u <= b else 0)
    return f, [a, m, b]


def build_house():
    gH = Geo('House')
    gR = Geo('Roof')
    gP = Geo('Porch')
    zsof = ZW - 0.45 * TM - 0.2 + 0.02
    W = rect_walls(MX0, MX1, MY0, MY1)
    s2 = F2 + 0.45
    # ---------------- main block
    F, L = W['front']
    holes = []
    for x in (-2.4, -1.15):
        mwindow(gH, F, x - MX0, FF + 0.35, 0.95, 2.3, holes, transom=0.45)
    front_door(gH, F, ENT - MX0, FF, holes)
    for x in (5.6, 6.75):
        mwindow(gH, F, x - MX0, FF + 0.35, 0.95, 2.3, holes, transom=0.45)
    for x in (1.75, 2.9, 4.05):                                      # tall gable windows
        mwindow(gH, F, x - MX0, s2 - 0.1, 0.9, 2.1, holes, transom=0.5)
    mwindow(gH, F, ENT - MX0, ZW + 0.55, 1.4, 0.75, holes, split=2)  # gable clerestory
    for x in (-1.8, 7.6):
        mwindow(gH, F, x - MX0, s2, 1.1, 1.5, holes, split=2)
    top, br = front_top(L)
    wall_holes(gH, F, L, FF - 0.05, None, holes, 'Siding', top=top, breaks=br)
    # back
    F, L = W['back']
    holes = []
    for x in (-2.2, 1.2):
        mwindow(gH, F, MX1 - x, FF + 0.35, 1.0, 2.3, holes, transom=0.45)
    holes.append((MX1 - 7.9, MX1 - 4.5, FF, FF + 2.45))              # sliding doors to the screened porch
    for k in range(3):
        a = MX1 - 7.9 + k * (3.4 / 3)
        fbox(gH, 'Frame', F, a, a + 0.06, FF, FF + 2.45, -0.12, -0.05)
        poly(gH, 'Glass', [F.p(a + 0.06, FF + 0.06, -0.1), F.p(a + 3.4 / 3, FF + 0.06, -0.1), F.p(a + 3.4 / 3, FF + 2.39, -0.1),
                           F.p(a + 0.06, FF + 2.39, -0.1)], facing=F.N)
    fbox(gH, 'Frame', F, MX1 - 4.56, MX1 - 4.5, FF, FF + 2.45, -0.12, -0.05)
    fbox(gH, 'Frame', F, MX1 - 7.9, MX1 - 4.5, FF + 2.39, FF + 2.45, -0.12, -0.05)
    for x in (-2.2, 1.2, 4.5, 7.4):
        mwindow(gH, F, MX1 - x, s2, 1.0, 1.5, holes, split=2)
    wall_holes(gH, F, L, FF - 0.05, ZW - 0.03, holes, 'Siding')
    # gable ends
    for side in ('left', 'right'):
        F, L = W[side]
        holes = []
        if side == 'right':
            mwindow(gH, F, 2.3, FF + 0.35, 0.95, 2.3, holes, transom=0.45)
            mwindow(gH, F, 2.3, s2, 0.95, 1.6, holes)
            mwindow(gH, F, 6.5, s2, 0.95, 1.6, holes)
            mwindow(gH, F, L / 2, ZW + 0.5, 0.7, 1.5, holes)
        else:
            mwindow(gH, F, L / 2, s2, 0.9, 1.6, holes)
            mwindow(gH, F, 2.0, s2, 0.9, 1.6, holes)
        gable_wall(gH, F, L, FF - 0.05, ZW, TM, holes, 'Siding')
    # painted foundation (raised coastal floor) and a black drip edge band
    path_run(gH, 'Foundation', [(MX0, MY0), (MX1, MY0), (MX1, MY1), (MX0, MY1), (MX0, MY0)], -0.6, FF - 0.02, 0.03, -0.02)
    path_run(gH, 'Trim', [(MX0, MY0), (MX1, MY0), (MX1, MY1), (MX0, MY1), (MX0, MY0)], FF - 0.05, FF + 0.12, 0.045, -0.02)
    # roof: steep side gable, standing seam, cross gable on the front
    gable_roof(gR, MX0, MX1, MY0, MY1, ZW, PITCH, ov=0.45, rake=0.3, axis='x', fascia=0.2)
    zgr = ZW + (XG1 - XG0) / 2 * TG
    gable_roof(gR, XG0, XG1, MY0, MY0 + 2.0, ZW, GP, ov=0.45, rake=0.35, axis='y', fascia=0.2,
               cut_hi=MY0 + (zgr - ZW) / TM + 0.4)
    # black half-round gutters on the main eaves, downspouts at the corners
    for y in (MY0 - 0.45 - 0.08, MY1 + 0.45 + 0.08):
        seg_box(gR, 'Metal', (MX0 - 0.3, y, ZW - 0.45 * TM - 0.12), (MX1 + 0.3, y, ZW - 0.45 * TM - 0.12), 0.13, 0.12, d0=-0.06)
    for x, y in ((MX0 + 0.15, MY1 + 0.53), (MX1 - 0.15, MY1 + 0.53), (MX1 - 0.15, MY0 - 0.53)):
        cbox(gH, 'Metal', x, y, 0.07, 0.07, 0.0, ZW - 0.45 * TM - 0.12)
    # metal flue
    lathe(gH, 'Metal', [(0.13, ZR - 1.2), (0.13, ZR + 0.7), (0.17, ZR + 0.72), (0.17, ZR + 0.9), (0.0, ZR + 0.92)],
          -1.5, 1.2, seg=12)
    build_porch(gP, gR)
    build_screened(gH, gP, gR)
    build_garage(gH, gR)
    return [gH, gR, gP]


def build_porch(gP, gR):
    """Deep full-width front porch: deck on a skirted frame, cedar posts and ceiling, standing-seam shed roof."""
    x0, x1 = MX0 - 0.0, MX1
    slab(gP, 'Foundation', [(x0, PY0 + 0.05), (x1, PY0 + 0.05), (x1, MY0), (x0, MY0)], FF - 0.06, -0.6)
    slab(gP, 'Deck', [(x0 - 0.03, PY0), (x1 + 0.03, PY0), (x1 + 0.03, MY0), (x0 - 0.03, MY0)], FF, FF - 0.06)
    box(gP, 'Trim', x0 - 0.03, x1 + 0.03, PY0 - 0.02, PY0 + 0.02, FF - 0.3, FF)
    zb = FF + 2.75
    posts = [x0 + 0.15, 0.6, ENT - 1.0, ENT + 1.0, 5.2, x1 - 0.15]
    for x in posts:
        cbox(gP, 'Wood', x, PY0 + 0.2, 0.2, 0.2, FF, zb)
        cbox(gP, 'Metal', x, PY0 + 0.2, 0.24, 0.24, FF, FF + 0.06)
    box(gP, 'Wood', x0, x1, PY0 + 0.08, PY0 + 0.32, zb, zb + 0.3)
    box(gP, 'Wood', x0 + 0.05, x1 - 0.05, PY0 + 0.3, MY0, zb + 0.25, zb + 0.28)
    zw_wall = zb + 0.85
    ov = 0.5
    slope = (zw_wall - (zb + 0.36)) / (MY0 - (PY0 + 0.2))
    zf = zb + 0.36 - ov * slope
    P = [(x0 - 0.3, PY0 + 0.2 - ov, zf), (x1 + 0.3, PY0 + 0.2 - ov, zf), (x1 + 0.3, MY0 + 0.15, zw_wall + 0.15 * slope),
         (x0 - 0.3, MY0 + 0.15, zw_wall + 0.15 * slope)]
    roof_slab(gR, P, th=0.05, top='Roof', edge='Trim', bottom='Wood')
    box(gR, 'Trim', x0 - 0.3, x1 + 0.3, PY0 + 0.2 - ov, PY0 + 0.2 - ov + 0.035, zf - 0.22, zf - 0.005)
    for xx in (x0 - 0.3, x1 + 0.3 - 0.035):
        Fx = Fr((xx, 0, 0), (0, 1, 0), (1, 0, 0))
        extrude(gR, 'Trim', Fx, [(PY0 + 0.2 - ov, zf - 0.22), (MY0, zw_wall - 0.22), (MY0, zw_wall), (PY0 + 0.2 - ov, zf)],
                0.0, 0.035)
    seg_box(gR, 'Metal', (x0 - 0.3, PY0 + 0.2 - ov - 0.08, zf - 0.1), (x1 + 0.3, PY0 + 0.2 - ov - 0.08, zf - 0.1), 0.12, 0.11,
            d0=-0.055)
    # black picket railing between the posts (gap at the steps), wide steps at the entry
    for a, b in zip(posts, posts[1:]):
        if abs((a + b) / 2 - ENT) < 0.3:
            continue
        railing(gP, (a + 0.12, PY0 + 0.2), (b - 0.12, PY0 + 0.2), FF, h=0.92, mat='Metal', bal=0.022, pitch=0.11, top_w=0.06)
    for x in (x0 + 0.15, x1 - 0.15):
        railing(gP, (x, PY0 + 0.32), (x, MY0 - 0.05), FF, h=0.92, mat='Metal', bal=0.022, pitch=0.11, top_w=0.06)
    stair(gP, 'Deck', ENT, 1.85, PY0, FF, run=0.3, max_rise=0.19)
    n = int(math.ceil(FF / 0.19))
    for x in (ENT - 0.97, ENT + 0.97):
        box(gP, 'Foundation', x - 0.05, x + 0.05, PY0 - (n - 1) * 0.3 - 0.05, PY0, -0.3, 0.25)
    Fw = Fr((MX0, MY0, 0), (1, 0, 0), (0, -1, 0))
    wall_lamp(gP, Fw, ENT - MX0 - 0.8, FF + 1.85)
    wall_lamp(gP, Fw, ENT - MX0 + 1.18, FF + 1.85)


def build_screened(gH, gP, gR):
    """Screened back porch: deck, white posts, mesh panels over a board-and-batten kick wall, gable roof."""
    x0, x1, y0, y1 = SX0, SX1, MY1, SY1
    slab(gP, 'Foundation', [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], FF - 0.06, -0.6)
    slab(gP, 'Deck', [(x0, y0), (x1, y0), (x1, y1 + 0.03), (x0, y1 + 0.03)], FF, FF - 0.06)
    zt = FF + 2.7
    W = rect_walls(x0, x1, y0, y1)
    for side in ('left', 'back', 'right'):
        F, L = W[side]
        n = max(2, int(round(L / 1.5)))
        door = side == 'right'
        for i in range(n + 1):
            u = L * i / n
            fbox(gP, 'Trim', F, u - 0.07, u + 0.07, FF, zt, -0.14, 0.0)
        fbox(gP, 'Siding', F, 0, L, FF, FF + 0.6, -0.08, -0.06)
        fbox(gP, 'Trim', F, 0, L, FF + 0.6, FF + 0.68, -0.12, 0.0)
        fbox(gP, 'Trim', F, 0, L, zt - 0.12, zt, -0.14, 0.0)
        poly(gP, 'Screen', [F.p(0, FF + 0.68, -0.07), F.p(L, FF + 0.68, -0.07), F.p(L, zt - 0.12, -0.07), F.p(0, zt - 0.12, -0.07)],
             facing=F.N)
        poly(gP, 'Screen', [F.p(0, FF + 0.68, -0.07), F.p(L, FF + 0.68, -0.07), F.p(L, zt - 0.12, -0.07), F.p(0, zt - 0.12, -0.07)],
             facing=-F.N)
    # screen door + steps on the right side
    F, L = W['right']
    fbox(gP, 'Trim', F, L / 2 - 0.5, L / 2 + 0.5, FF, FF + 2.1, 0.0, 0.04)
    for k in range(1, int(math.ceil(FF / 0.19))):
        zt_ = FF - k * FF / math.ceil(FF / 0.19)
        box(gP, 'Deck', x1, x1 + k * 0.3, (y0 + y1) / 2 - 0.65, (y0 + y1) / 2 + 0.65, -0.3, zt_)
    # gable roof over it, ridge running back from the main roof
    zg = zt + 0.05
    sp = 36
    zr = zg + (x1 - x0) / 2 * math.tan(math.radians(sp))
    gable_roof(gR, x0, x1, y0 - 0.5, y1, zg, sp, ov=0.35, rake=0.35, axis='y', fascia=0.2, cut_lo=y0 - 1.6, soffit=False)
    Fb = Fr((x1, y1, 0), (-1, 0, 0), (0, 1, 0))
    gable_wall(gP, Fb, x1 - x0, zt - 0.05, zg, math.tan(math.radians(sp)), [], 'Siding')
    # ceiling fan-free open ceiling: cedar ceiling under the roof
    poly(gP, 'Wood', [(x0, y0, zt), (x1, y0, zt), (x1, y1, zt), (x0, y1, zt)], facing=(0, 0, -1))


def build_garage(gH, gR):
    """Attached two-car garage: board-and-batten, side gable, two flush modern doors with a glass band."""
    zg = 3.25
    gp = PITCH
    W = rect_walls(GX0, GX1, GY0, GY1)
    F, L = W['front']
    holes = []
    for xc in (GX0 + 1.95, GX1 - 1.95):
        holes.append((xc - 1.37 - GX0, xc + 1.37 - GX0, 0.0, 2.3))
    for (a, b, z0, z1) in holes:
        fbox(gH, 'Trim', F, a - 0.09, a, z0, z1, -0.005, 0.022)
        fbox(gH, 'Trim', F, b, b + 0.09, z0, z1, -0.005, 0.022)
        fbox(gH, 'Trim', F, a - 0.09, b + 0.09, z1, z1 + 0.09, -0.005, 0.022)
        d = -0.12
        fbox(gH, 'GarageDoor', F, a, b, z0, z1, d - 0.04, d)
        for k in range(1, 4):
            zz = z0 + (z1 - z0) * k / 4
            fbox(gH, 'Dark', F, a + 0.02, b - 0.02, zz - 0.008, zz + 0.008, d, d + 0.003)
        gz0, gz1 = z1 - (z1 - z0) / 4 + 0.08, z1 - 0.08
        poly(gH, 'Glass', [F.p(a + 0.08, gz0, d + 0.004), F.p(b - 0.08, gz0, d + 0.004), F.p(b - 0.08, gz1, d + 0.004),
                           F.p(a + 0.08, gz1, d + 0.004)], facing=F.N)
        for i in range(1, 4):
            uu = a + 0.08 + (b - a - 0.16) * i / 4
            fbox(gH, 'Frame', F, uu - 0.02, uu + 0.02, gz0, gz1, d, d + 0.01)
    for u in (0.35, L / 2, L - 0.35):
        wall_lamp(gH, F, u, 2.45)
    wall_holes(gH, F, L, -0.6, zg - 0.03, holes, 'Siding')
    F, L = W['back']
    holes = []
    mwindow(gH, F, L / 2, 1.3, 1.6, 1.2, holes, split=2)
    holes.append((L - 1.6, L - 0.7, 0.05, 2.15))
    fbox(gH, 'GarageDoor', F, L - 1.6, L - 0.7, 0.05, 2.15, -0.12, -0.08)
    wall_holes(gH, F, L, -0.6, zg - 0.03, holes, 'Siding')
    F, L = W['left']
    holes = []
    mwindow(gH, F, L / 2, 1.3, 0.9, 1.2, holes)
    mwindow(gH, F, L / 2, zg + 0.5, 0.7, 0.9, holes)
    gable_wall(gH, F, L, -0.6, zg, math.tan(math.radians(gp)), holes, 'Siding')
    path_run(gH, 'Foundation', [(GX1, GY0), (GX0, GY0), (GX0, GY1), (GX1, GY1)], -0.6, 0.12, 0.03, -0.02)
    gable_roof(gR, GX0, GX1, GY0, GY1, zg, gp, ov=0.4, rake=0.3, axis='x', fascia=0.2, cut_hi=GX1 + 0.1)


# ============================================================================ the lot
def grass_clump(g, x, y, h, seed):
    """Ornamental grass: a fountain of thin blades (opaque narrow spikes)."""
    rng = np.random.default_rng(seed)
    V, F, C = [], [], []
    for i in range(26):
        a = rng.uniform(0, 2 * math.pi)
        lean = rng.uniform(0.15, 0.55)
        L = h * rng.uniform(0.7, 1.05)
        d = Vector((math.cos(a) * lean, math.sin(a) * lean, 1.0)).normalized()
        side = Vector((-math.sin(a), math.cos(a), 0)) * 0.025
        b = Vector((x + math.cos(a) * 0.06, y + math.sin(a) * 0.06, 0.0))
        tip = b + d * L + Vector((math.cos(a), math.sin(a), 0)) * L * 0.25
        k = len(V)
        V += [b - side, b + side, tip]
        F.append([k, k + 1, k + 2])
        t = rng.uniform(0.8, 1.1)
        C += [(0.6 * t, 0.62 * t, 0.45 * t), (0.6 * t, 0.62 * t, 0.45 * t), (1.0 * t, 0.95 * t, 0.75 * t)]
    g.add(V, F, 'Grass', colors=C)


def build_lot():
    gL = Geo('Lot_Hardscape')
    gB = Geo('Lot_Beds')
    gT = Geo('Tree_Birch_1')
    gX = Geo('Lot_Props')
    # concrete drive from the curb to the garage, flaring at the apron
    drive = [(-10.3, CURB), (-5.0, CURB), (-5.0, -12.0), (GX1 + 0.1, -7.0), (GX1 + 0.1, GY0), (GX0 + 0.1, GY0),
             (GX0 + 0.1, -7.0), (-10.3, -12.0)]
    slab(gL, 'Concrete', drive, 0.035)
    # large-format paver walk from the porch steps to the curb, set in a gravel band
    n = int(math.ceil(FF / 0.19))
    ybot = PY0 - (n - 1) * 0.3
    y = CURB + 0.05
    while y < ybot - 0.1:
        y1 = min(y + 0.6, ybot)
        slab(gL, 'Paver', [(ENT - 0.8, y), (ENT + 0.8, y), (ENT + 0.8, y1 - 0.06), (ENT - 0.8, y1 - 0.06)], 0.04)
        y = y1
    slab(gL, 'Gravel', [(ENT - 0.95, CURB), (ENT + 0.95, CURB), (ENT + 0.95, ybot), (ENT - 0.95, ybot)], 0.02, -0.05)
    # side walk from the drive to the porch
    slab(gL, 'Paver', [(-5.0, -9.9), (-3.4, -9.9), (-3.4, PY0 - 0.2), (-5.0, PY0 - 0.2)], 0.04)
    # beds: gravel strip with grasses and hydrangeas along the porch, boxwoods at the corners
    beds = [[(MX0 - 0.1, PY0 - 1.8), (ENT - 1.25, PY0 - 1.8), (ENT - 1.25, PY0), (MX0 - 0.1, PY0)],
            [(ENT + 1.25, PY0 - 1.8), (MX1 + 0.8, PY0 - 1.8), (MX1 + 0.8, PY0), (ENT + 1.25, PY0)],
            [(MX1, MY0 - 0.2), (MX1 + 1.4, MY0 - 0.2), (MX1 + 1.4, MY1), (MX1, MY1)]]
    for P in beds:
        slab(gB, 'Mulch', P, 0.04, -0.05)
    k = 0
    for x in np.arange(MX0 + 0.4, ENT - 1.4, 1.2):
        bush(gB, 'Flowers', (x, PY0 - 0.75, 0), (0.55, 0.5, 0.9), 900 + k, 1.0, n=5); k += 1
    for x in np.arange(ENT + 1.7, MX1 + 0.6, 1.2):
        bush(gB, 'Flowers', (x, PY0 - 0.75, 0), (0.55, 0.5, 0.9), 900 + k, 1.0, n=5); k += 1
    for x in np.arange(MX0 + 0.1, ENT - 1.4, 0.9):
        grass_clump(gB, x, PY0 - 1.45, 0.75, 950 + k); k += 1
    for x in np.arange(ENT + 1.5, MX1 + 0.8, 0.9):
        grass_clump(gB, x, PY0 - 1.45, 0.75, 950 + k); k += 1
    for y in np.arange(MY0 + 0.4, MY1, 1.3):
        bush(gB, 'Boxwood', (MX1 + 0.7, y, 0), (0.5, 0.5, 0.8), 980 + k, 0.95); k += 1
    # multi-stem river birch, front right
    for i, (dx, dy, lean) in enumerate(((0.0, 0.0, (0.5, -0.3)), (0.5, 0.3, (1.2, 0.4)), (-0.4, 0.35, (-0.9, 0.6)))):
        leafy_tree(gT, (TREE[0] + dx, TREE[1] + dy), 10.0 - i, 6.5, 61 + i, clear=2.6, trunk_r=0.13, n_limbs=5, density=0.55,
                   tone=(0.66, 0.76, 0.4), lean=lean, bounds=LOT, clump_r=(0.26, 0.38), cluster_r=0.4)
    slab(gB, 'Mulch', ngon(TREE[0], TREE[1] + 0.2, 1.6, n=16, jitter=0.06, seed=6), 0.035, -0.05)
    mailbox(gX, -11.2, CURB + 0.45)
    trash_cart(gX, GX0 - 0.7, GY1 - 0.8, 0.0)
    trash_cart(gX, GX0 - 0.7, GY1 - 1.7, 0.1)
    hvac(gX, MX0 + 1.2, MY1 + 1.2)
    hvac(gX, MX0 + 2.6, MY1 + 1.2)
    return [gL, gB, gT, gX]


# ============================================================================ main
TREE = (13.5, -13.0)
META = {
    'id': ID, 'name': 'The Al-Hassan house', 'address': '1552 Spinnaker Court', 'neighborhood': 'Harborview',
    'residents': ['Zane Al-Hassan', 'Dr. Nadir Al-Hassan', 'Dr. Amina Al-Hassan'],
    'status': 'Canon 2 (address); design interpreted from the brief (no reference photo)',
    'atlas_building_index': 21135, 'footprint_m': [24.63, 18.61], 'ridge_height_m': round(ZR, 2), 'stories': 2,
    'style': 'Contemporary coastal (modern farmhouse) with an attached garage',
    'materials': ['white painted board-and-batten', 'charcoal standing-seam metal roofing',
                  'black-framed tall windows with thin white flat casings', 'stained cedar porch posts, beams and ceilings',
                  'grey composite porch decking', 'painted grey foundation (raised 0.75 m)',
                  'charcoal flush garage doors with a glass band', 'black screen mesh on the back porch'],
    'lot_local_rect_m': list(LOT), 'curb_line_local_y': CURB,
    'notes': ("Main block 12.6 x 9.2 m, 35 deg side gable, roof surface 6.45 m at the walls, ridge "
              f"{ZR:.1f} m (Atlas height 7.5 m; within the 30% allowance), with a steeper (44 deg) front cross gable over "
              "the entry holding three tall black-framed windows and a clerestory. All of it is interpreted from the brief "
              "(no reference photo): deep full-width front porch with a standing-seam shed roof, cedar posts and black "
              "picket rail; screened porch at the back right under its own gable; attached two-car garage on the left; "
              "concrete drive and paver walk both meet the curb line; beds with hydrangeas and ornamental grasses; one "
              "multi-stem river birch. No fence or hedge on the frontage.")}

CAMS = {
    'hero': dict(loc=(8.5, -30.5, 1.7), target=(-0.8, -4.0, 4.3), lens=31),
    'aerial': dict(loc=(-38.0, -50.0, 44.0), target=(-0.5, -4.0, 1.5), lens=34),
}

if __name__ == '__main__':
    run(dict(id=ID, lot_rect=LOT, make_materials=make_materials, build_house=build_house, build_lot=build_lot, meta=META,
             cams=CAMS, curb_y=CURB, backdrop=[((-24, 14), 14, 10), ((2, 26), 16, 12), ((24, 18), 13, 10), ((-12, 32), 15, 11)],
             sun=dict(sun_elev=45, sun_az=150, exposure=0.3)))
