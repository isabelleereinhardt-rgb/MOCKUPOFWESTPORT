"""Westport vegetation kit: every species in ASSET-SPEC "Vegetation kit", LOD0 + LOD1.

    WP_TEX_DIR=/tmp/somewhere python3 tools/blender/vegetation/build.py            # export GLBs + index
    python3 tools/blender/vegetation/build.py --render final                        # + final lineup renders
    python3 tools/blender/vegetation/build.py --render iter --only live-oak         # quick look

Conventions: meters, +Z up, origin at the trunk base on finished grade, trunks and
roots continue to z = -0.5 so trees sit on sloped ground. Two materials only, `Bark`
and `Leaves` (Spanish moss, palm fronds, grass blades and blossoms are `Leaves`).
No textures, no alpha: all colour lives in the COLOR_0 vertex colours (dark crown
interiors and undersides, lighter sunlit tops, slight hue shifts between clumps),
multiplied by a white base colour. Crowns are built from many overlapping, gently
displaced low-poly clumps hung on a real branch skeleton, with normals bent toward
the crown envelope so the foliage shades as one soft mass instead of separate rocks.
LOD1 merges the clumps into a few bounding masses (k-means), keeps the trunk and main
limbs, and is recoloured so its average leaf colour matches LOD0.
"""
import argparse
import json
import math
import os
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import wp  # noqa: E402

import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector, noise  # noqa: E402

OUT = os.path.join(wp.REPO, 'models', 'vegetation')
RENDERS = os.path.join(wp.REPO, 'renders')
TAU = 2 * math.pi
UP = Vector((0, 0, 1))


# ----------------------------------------------------------------------------- colour

def hexc(h):
    return np.array(wp._rgb(h), float)


def to_lin(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def grad3(pal, t):
    d, m, l = pal
    t = clamp(t)
    return lerp(d, m, t / 0.5) if t < 0.5 else lerp(m, l, (t - 0.5) / 0.5)


# ----------------------------------------------------------------------------- geometry accumulator

class Geo:
    """Vertices, faces, per-vertex linear colours, optional per-vertex custom normals."""

    def __init__(self):
        self.V, self.C, self.N, self.F, self.M = [], [], [], [], []

    def add(self, V, F, C, m, N=None):
        b = len(self.V)
        self.V.extend(Vector(v) for v in V)
        self.C.extend(C)
        self.N.extend(N if N is not None else [None] * len(V))
        self.F.extend(tuple(b + i for i in f) for f in F)
        self.M.extend([m] * len(F))

    def tris(self, m=None):
        return sum(len(f) - 2 for f, mm in zip(self.F, self.M) if m is None or mm == m)

    def mean_color(self, m='Leaves'):
        """Area-weighted mean linear colour of faces of material m."""
        acc = np.zeros(3); wsum = 0.0
        for f, mm in zip(self.F, self.M):
            if mm != m:
                continue
            p = [self.V[i] for i in f]
            a = sum(((p[k] - p[0]).cross(p[k + 1] - p[0])).length * 0.5 for k in range(1, len(p) - 1))
            c = sum(np.asarray(self.C[i]) for i in f) / len(f)
            acc += c * a; wsum += a
        return acc / max(wsum, 1e-9)

    def scale_colors(self, m, k):
        used = {i for f, mm in zip(self.F, self.M) if mm == m for i in f}
        for i in used:
            self.C[i] = np.clip(np.asarray(self.C[i]) * k, 0, 1)


MATS = {}


def make_materials(leaf_rough=0.85, leaf_spec=0.15):
    """Bark and Leaves: Principled, white base x COLOR_0. Leaves double-sided (ribbons)."""
    MATS.clear()
    for name, rough, spec, dbl in (('Bark', 0.92, 0.2, False), ('Leaves', leaf_rough, leaf_spec, True)):
        m = wp.mat(name, '#ffffff', rough=rough, double_sided=dbl)
        nt = m.node_tree
        bs = nt.nodes['Principled BSDF']
        ca = nt.nodes.new('ShaderNodeVertexColor'); ca.layer_name = 'Col'
        nt.links.new(ca.outputs['Color'], bs.inputs['Base Color'])
        try:
            bs.inputs['Specular IOR Level'].default_value = spec
        except Exception:
            pass
        MATS[name] = m
    return MATS


def build_object(g, name):
    order = [m for m in ('Bark', 'Leaves') if m in g.M]
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in g.V], [], g.F)
    for m in order:
        me.materials.append(MATS[m])
    me.polygons.foreach_set('material_index', [order.index(m) for m in g.M])
    me.shade_smooth()
    ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    flat = []
    for c in g.C:
        flat.extend((float(c[0]), float(c[1]), float(c[2]), 1.0))
    ca.data.foreach_set('color', flat)
    me.color_attributes.active_color = ca
    try:
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
    except Exception:
        pass
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def apply_normals(o, g):
    """Custom normals (bent toward the crown envelope) where the generator supplied them."""
    me = o.data
    if all(n is None for n in g.N):
        return
    vn = [Vector(v.normal) for v in me.vertices]
    me.normals_split_custom_set_from_vertices([tuple(n) if n is not None else tuple(vn[i]) for i, n in enumerate(g.N)])
    me.update()


# ----------------------------------------------------------------------------- primitives

def frames(pts):
    n = len(pts)
    T = [(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized() for i in range(n)]
    ref = UP if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    N = [T[0].cross(ref).normalized()]
    for i in range(1, n):
        nn = N[-1] - T[i] * N[-1].dot(T[i])
        if nn.length < 1e-6:
            nn = T[i].orthogonal()
        N.append(nn.normalized())
    B = [T[i].cross(N[i]) for i in range(n)]
    return T, N, B


def tube(g, pts, radii, sides, colfn, tip=True, rmod=None, m='Bark'):
    """Generalised cylinder. Open base (buried in parent / ground), pointed tip."""
    pts = [Vector(p) for p in pts]
    T, N, B = frames(pts)
    V, C = [], []
    n = len(pts)
    rings = n - 1 if tip else n
    for i in range(rings):
        for k in range(sides):
            a = TAU * k / sides
            r = radii[i] * (rmod(i, a, pts[i]) if rmod else 1.0)
            d = N[i] * math.cos(a) + B[i] * math.sin(a)
            p = pts[i] + d * r
            V.append(p); C.append(colfn(p, d, i / (n - 1)))
    F = []
    for i in range(rings - 1):
        for k in range(sides):
            F.append((i * sides + k, i * sides + (k + 1) % sides, (i + 1) * sides + (k + 1) % sides, (i + 1) * sides + k))
    if tip:
        ti = len(V); V.append(pts[-1]); C.append(colfn(pts[-1], T[-1], 1.0))
        last = (rings - 1) * sides
        for k in range(sides):
            F.append((last + k, last + (k + 1) % sides, ti))
    g.add(V, F, C, m)


_TPL = {}


def template(kind):
    """Unit clump meshes: ico2 (80 tris), uv8 (64), uv6 (36), ico1 (20)."""
    if kind in _TPL:
        return _TPL[kind]
    if kind.startswith('ico'):
        bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=int(kind[3:]), radius=1.0)
        V = [v.co.copy().normalized() for v in bm.verts]
        F = [tuple(v.index for v in f.verts) for f in bm.faces]
        bm.free()
    else:
        parts = kind[2:].split('_')
        seg = int(parts[0]); rings = int(parts[1]) if len(parts) > 1 else (5 if seg >= 8 else 4)
        V = [Vector((0, 0, 1))]
        for i in range(1, rings):
            ph = math.pi * i / rings
            for k in range(seg):
                a = TAU * (k + 0.5 * (i % 2)) / seg
                V.append(Vector((math.sin(ph) * math.cos(a), math.sin(ph) * math.sin(a), math.cos(ph))))
        V.append(Vector((0, 0, -1)))
        S = len(V) - 1
        F = []
        for k in range(seg):
            F.append((0, 1 + k, 1 + (k + 1) % seg))
        for i in range(rings - 2):
            a0 = 1 + i * seg; b0 = a0 + seg
            for k in range(seg):
                k1 = (k + 1) % seg
                if i % 2 == 0:
                    F.append((a0 + k, b0 + k, a0 + k1)); F.append((a0 + k1, b0 + k, b0 + k1))
                else:
                    F.append((a0 + k, b0 + k, b0 + k1)); F.append((a0 + k, b0 + k1, a0 + k1))
        lr = 1 + (rings - 2) * seg
        for k in range(seg):
            F.append((lr + k, S, lr + (k + 1) % seg))
    _TPL[kind] = (V, F)
    return V, F


class Crown:
    """Crown envelope: drives leaf shading (height, interior, underside) and bent normals."""

    def __init__(self, C, R, pal, rng, bend=0.68, under=None, under_mix=0.0, lift=0.0):
        self.C, self.R, self.pal, self.rng = Vector(C), Vector(R), [hexc(p) for p in pal], rng
        self.bend, self.under, self.under_mix, self.lift = bend, (hexc(under) if under else None), under_mix, lift
        self.z0, self.z1 = self.C.z - self.R.z, self.C.z + self.R.z
        self.speck = 1.0

    def q(self, p):
        return Vector(((p.x - self.C.x) / self.R.x, (p.y - self.C.y) / self.R.y, (p.z - self.C.z) / self.R.z))

    def normal(self, p, n_own):
        rad = self.q(p)
        rad = Vector((rad.x / self.R.x, rad.y / self.R.y, rad.z / self.R.z))
        if rad.length < 1e-6:
            return n_own
        return (n_own * (1 - self.bend) + rad.normalized() * self.bend).normalized()

    def color(self, p, n, tone, hue, extra=None):
        q = self.q(p)
        depth = q.length
        out = n.dot(q.normalized()) if depth > 1e-6 else 0.0
        th = clamp((p.z - self.z0) / (self.z1 - self.z0))
        L = 0.06 + 0.42 * th + 0.30 * clamp(0.5 + 0.6 * out) + 0.14 * clamp((depth - 0.5) / 0.45)
        L -= 0.12 * max(0.0, -n.z)
        # leaf-scale speckle: most vertices jitter a little, some fall into dark gaps
        L = L * tone + self.lift + self.speck * (self.rng.normal(0, 0.035) - (0.12 if self.rng.random() < 0.1 else 0.0))
        c = grad3(self.pal, L) * hue
        c = c.mean() + (c - c.mean()) * 1.12
        c = c * 0.86
        if self.under is not None:
            c = lerp(c, self.under, self.under_mix * clamp((-n.z - 0.15) / 0.7))
        if extra:
            c = extra(p, n, c, th, out)
        return to_lin(c)


def clump(g, crown, c, r3, rng, kind='uv8', amp=0.12, flat=0.25, tone=None, hue=None, extra=None, zmin=None):
    """One foliage mass: a gently displaced ellipsoid, normals bent toward the crown."""
    V0, F = template(kind)
    c = Vector(c)
    off = Vector(rng.uniform(-50, 50, 3))
    rot = Matrix.Rotation(rng.uniform(0, TAU), 3, 'Z') @ Matrix.Rotation(rng.uniform(-0.25, 0.25), 3, 'X')
    tone = tone if tone is not None else rng.uniform(0.9, 1.1)
    hue = hue if hue is not None else np.array([rng.uniform(0.94, 1.07), 1.0, rng.uniform(0.92, 1.06)])
    V, N, C = [], [], []
    for d in V0:
        s = 1 + amp * noise.noise(d * 1.3 + off) + amp * 0.6 * noise.noise(d * 3.0 + off * 1.3)
        dd = Vector(d)
        if dd.z < 0:
            dd.z *= (1 - flat)
        loc = rot @ Vector((dd.x * r3[0], dd.y * r3[1], dd.z * r3[2])) * s
        p = c + loc
        if zmin is not None and p.z < zmin:
            p.z = zmin + (p.z - zmin) * 0.15
        n_own = (rot @ Vector((dd.x / r3[0], dd.y / r3[1], dd.z / r3[2]))).normalized()
        V.append(p); N.append(crown.normal(p, n_own)); C.append(crown.color(p, n_own, tone, hue, extra))
    g.add(V, F, C, 'Leaves', N)


def ribbon(g, pts, widths, side, colors, m='Leaves'):
    """Flat strip along pts (2 tris per segment); a zero last width ends in a single point."""
    V, F, C = [], [], []
    n = len(pts)
    for i, (p, w) in enumerate(zip(pts, widths)):
        if i == n - 1 and w <= 1e-6:
            V.append(Vector(p)); C.append(colors[i])
        else:
            V.append(Vector(p) - side * w * 0.5); V.append(Vector(p) + side * w * 0.5)
            C.extend([colors[i], colors[i]])
    for i in range(n - 1):
        a = 2 * i
        if i == n - 2 and widths[-1] <= 1e-6:
            F.append((a, a + 1, a + 2))
        else:
            F.append((a, a + 1, a + 3, a + 2))
    g.add(V, F, C, m)


# ----------------------------------------------------------------------------- bark colour

def bark_fn(rng, base, light, dark=None, lichen=None, mottle=0.0, seed=0.0):
    base, light = hexc(base), hexc(light)
    dark = hexc(dark) if dark else base * 0.7
    lic = hexc(lichen) if lichen else None
    off = Vector((seed, seed * 0.7, seed * 1.3))

    def f(p, d, t):
        k = clamp(0.35 + 0.5 * t + 0.12 * d.z + rng.normal(0, 0.06))
        c = lerp(base, light, k)
        if p.z < 1.0:
            c = lerp(c, dark, clamp((1.0 - p.z) / 1.3) * 0.6)
        if mottle:
            m = noise.noise(Vector(p) * 1.7 + off)
            c = c * (1 + mottle * m)
        if lic is not None and d.z > 0.35:
            c = lerp(c, lic, 0.35 * clamp((d.z - 0.35) / 0.5))
        return to_lin(c)
    return f


# ----------------------------------------------------------------------------- skeleton helpers

class Tree:
    def __init__(self, sid, seed):
        self.id = sid
        self.rng = np.random.default_rng(seed)
        self.wood = []     # dict(pts, radii, level, rmod)
        self.clumps = []   # dict(c, r, tone, hue, kind)
        self.crown = None
        self.bark = None
        self.extra0 = []   # callables(g) adding LOD0-only details
        self.extra1 = []   # callables(g) for LOD1
        self.leaf_extra = None
        self.clump_kind = 'uv8'
        self.clump_amp = 0.2
        self.clump_flat = 0.35
        self.k_lod1 = 8
        self.zmin_leaf = None

    def limb(self, pts, radii, level, rmod=None):
        self.wood.append(dict(pts=[Vector(p) for p in pts], radii=list(radii), level=level, rmod=rmod))
        return self.wood[-1]


def bez(p0, p1, p2, p3, n):
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(p0 * (1 - t) ** 3 + p1 * 3 * (1 - t) ** 2 * t + p2 * 3 * (1 - t) * t * t + p3 * t ** 3)
    return out


def sample_dome(rng, n, C, R, phi_max, frange, min_d, seed=0.0, env=0.14, tries=6000, phi_min=0.0):
    pts = []
    C, R = Vector(C), Vector(R)
    off = Vector((seed, 3.1 + seed, 7.7))
    for _ in range(tries):
        if len(pts) >= n:
            break
        th = rng.uniform(0, TAU)
        cphi = rng.uniform(math.cos(phi_max), math.cos(phi_min))
        sphi = math.sqrt(max(0.0, 1 - cphi * cphi))
        d = Vector((sphi * math.cos(th), sphi * math.sin(th), cphi))
        f = rng.uniform(*frange) * (1 + env * noise.noise(d * 1.6 + off))
        p = Vector((C.x + R.x * d.x * f, C.y + R.y * d.y * f, C.z + R.z * d.z * f))
        if any((p - q).length < min_d for q in pts):
            continue
        pts.append(p)
    return pts


def connect_clumps(t, rng, r0, r1, levels=(0, 1), min_idx=1, sides_hint=None, droop=0.0):
    """Secondary branch from the nearest suitable skeleton point to each clump centre."""
    cand = []
    for w in t.wood:
        if w['level'] not in levels:
            continue
        for i, p in enumerate(w['pts']):
            if i >= min_idx:
                cand.append((p, w['radii'][i]))
    for cl in t.clumps:
        c = Vector(cl['c'])
        best = None
        for p, r in cand:
            v = c - p
            hz = Vector((v.x, v.y, 0))
            ph = Vector((p.x, p.y, 0))
            back = -hz.normalized().dot(ph.normalized()) if hz.length > 0.2 and ph.length > 0.3 else 0.0
            sc = v.length * (1 + 0.8 * max(0.0, back)) + (0.6 if v.z < -1.0 else 0.0) * -v.z
            if best is None or sc < best[0]:
                best = (sc, p, r)
        _, p, r = best
        e = c - (c - p).normalized() * min(cl['r'][0], cl['r'][2]) * 0.35
        mid = p.lerp(e, 0.5) + Vector((0, 0, (e - p).length * (0.12 - droop)))
        rb = min(r0, r * 0.55)
        t.limb([p, mid, e], [rb, max(r1, rb * 0.55), r1 * 0.6], 2)


def kmeans_merge(clumps, K, rng, shrink=0.88):
    if len(clumps) <= K:
        return [dict(c) for c in clumps]
    P = np.array([list(c['c']) for c in clumps]); W = np.array([float(np.prod(c['r'])) for c in clumps])
    idx = [int(np.argmax(W))]
    for _ in range(K - 1):
        d = np.min(((P[:, None, :] - P[idx][None, :, :]) ** 2).sum(-1), axis=1)
        idx.append(int(np.argmax(d)))
    cen = P[idx].copy()
    for _ in range(30):
        lab = np.argmin(((P[:, None, :] - cen[None]) ** 2).sum(-1), axis=1)
        for k in range(K):
            if np.any(lab == k):
                cen[k] = (P[lab == k] * W[lab == k, None]).sum(0) / W[lab == k].sum()
    out = []
    for k in range(K):
        mem = [clumps[i] for i in range(len(clumps)) if lab[i] == k]
        if not mem:
            continue
        c = cen[k]
        ext = np.zeros(3)
        for m in mem:
            ext = np.maximum(ext, np.abs(np.array(list(m['c'])) - c) + np.array(m['r']))
        if len(mem) > 1:
            ext = ext * shrink
        out.append(dict(c=Vector(c), r=tuple(ext), tone=float(np.mean([m['tone'] for m in mem])),
                        hue=np.mean([m['hue'] for m in mem], axis=0)))
    return out


def realize(t, lod):
    """Turn a Tree spec into a Geo at LOD0 or LOD1."""
    g = Geo()
    rng = np.random.default_rng(zlib.crc32(t.id.encode()) + lod)  # stable across runs
    for w in t.wood:
        lv = w['level']
        if lod == 0:
            sides = {0: 9, 1: 5, 2: 3, 3: 3}[lv]
            if t.id in ('crepe-myrtle', 'crepe-myrtle-pink', 'shrub') and lv == 0:
                sides = 6
            tube(g, w['pts'], w['radii'], sides, t.bark, rmod=w['rmod'])
        else:
            if lv >= 2 or (lv == 1 and w.get('lod1') is False):
                continue
            pts, rad = w['pts'], w['radii']
            n = len(pts)
            keep = sorted(set([0, n // 3, (2 * n) // 3, n - 1])) if lv == 0 else sorted(set([0, n // 2, n - 1]))
            tube(g, [pts[i] for i in keep], [rad[i] for i in keep], 5 if lv == 0 else 3, t.bark,
                 rmod=(lambda i, a, p, f=w['rmod'], kk=keep: f(kk[i], a, p)) if w['rmod'] else None)
    if lod == 0:
        cl = t.clumps
        kind = t.clump_kind
    else:
        cl = kmeans_merge(t.clumps, t.k_lod1, rng)
        kind = 'ico1'
        t.crown.speck = 0.3
        t.crown.bend = min(0.8, t.crown.bend + 0.12)
        if t.id == 'shrub':
            # keep the merged masses down on the ground like the LOD0 shrub
            for c in cl:
                top = c['c'].z + c['r'][2]
                if c['c'].z - c['r'][2] * (1 - t.clump_flat) * 0.9 > -0.04:
                    rz = (top + 0.04) / (1 + 0.9 * (1 - t.clump_flat))
                    c['c'] = Vector((c['c'].x, c['c'].y, top - rz))
                    c['r'] = (c['r'][0], c['r'][1], rz)
    for c in cl:
        clump(g, t.crown, c['c'], c['r'], rng, kind=c.get('kind', kind) if lod == 0 else kind,
              amp=t.clump_amp if lod == 0 else 0.07, flat=t.clump_flat, tone=c['tone'], hue=c['hue'],
              extra=t.leaf_extra, zmin=t.zmin_leaf)
    for fn in (t.extra0 if lod == 0 else t.extra1):
        fn(g, rng)
    return g


def add_clumps(t, centers, rx, rz, kind=None, aniso=(0.8, 1.0)):
    rng = t.rng
    for c in centers:
        r = rng.uniform(*rx)
        t.clumps.append(dict(c=Vector(c), r=(r, r * rng.uniform(*aniso), rng.uniform(*rz) * r / np.mean(rx)),
                             tone=rng.uniform(0.9, 1.1),
                             hue=np.array([rng.uniform(0.94, 1.07), 1.0, rng.uniform(0.92, 1.06)]),
                             **({'kind': kind} if kind else {})))


def flare_rmod(z_top=1.6, amp=0.22, lobes=5, phase=0.0, base_boost=0.35):
    def f(i, a, p):
        k = clamp(1 - p.z / z_top) if p.z < z_top else 0.0
        return 1 + k * (base_boost * k + amp * max(0.0, math.cos(lobes * a + phase)) ** 1.5)
    return f


# ----------------------------------------------------------------------------- Spanish moss

MOSS_TOP, MOSS_TIP = hexc('#7b8672'), hexc('#a4ad9a')


def moss_cluster(g, top, rng, n=None, Lmax=1.6, wscale=1.0, segs=None):
    n = n or int(rng.integers(3, 7))
    for s in range(n):
        L = rng.uniform(0.4, Lmax)
        o = top + Vector((rng.uniform(-0.22, 0.22), rng.uniform(-0.22, 0.22), rng.uniform(-0.08, 0.02)))
        phi = rng.uniform(0, TAU)
        side = Vector((math.cos(phi), math.sin(phi), 0))
        drift = Vector((-math.sin(phi), math.cos(phi), 0)) * rng.uniform(-0.06, 0.06)
        ns = segs or (4 if L > 0.8 else 3)
        pts, wid, col = [], [], []
        w0 = rng.uniform(0.07, 0.12) * wscale
        tone = rng.uniform(0.92, 1.06)
        for i in range(ns + 1):
            u = i / ns
            pts.append(o + Vector((0, 0, -L * u)) + drift * math.sin(u * 2.4) + side * 0.02 * math.sin(u * 5 + phi))
            wid.append(w0 * (1 - u) ** 0.8 if i < ns else 0.0)
            col.append(to_lin(lerp(MOSS_TOP, MOSS_TIP, u ** 0.7) * tone))
        ribbon(g, pts, wid, side, col)


def moss_sites(t, rng, n, levels=(1, 2), tmin=0.35, zmax=None, min_d=1.2):
    cand = []
    for w in t.wood:
        if w['level'] not in levels:
            continue
        P = w['pts']
        for i in range(1, len(P)):
            u = i / (len(P) - 1)
            if u < tmin:
                continue
            for s in (0.0, 0.5):
                p = P[i - 1].lerp(P[i], s)
                r = w['radii'][i - 1]
                if zmax and p.z > zmax:
                    continue
                cand.append(p - Vector((0, 0, r * 0.6)))
    rng.shuffle(cand)
    out = []
    for p in cand:
        if p.z < 2.4:
            continue
        if all((p - q).length > min_d for q in out):
            out.append(p)
        if len(out) >= n:
            break
    return out


# ----------------------------------------------------------------------------- species

def sp_live_oak(sid='live-oak', seed=11, scale=1.0, young=False):
    t = Tree(sid, seed)
    rng = t.rng
    S = scale
    t.bark = bark_fn(rng, '#4b443c', '#6f675c', '#3a332c', lichen='#7d806c', mottle=0.10, seed=seed)
    fork = 2.6 * S if not young else 1.7
    tr0 = 0.82 * S if not young else 0.34
    lean = Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0)) * S
    trunk = [Vector((0, 0, -0.5)), Vector((0, 0, 0.0)), Vector((0, 0, 0.6)) + lean * 0.2, Vector((0, 0, 1.4 * S)) + lean * 0.5,
             Vector((0, 0, fork)) + lean]
    t.limb(trunk, [tr0 * 1.35, tr0 * 1.25, tr0 * 1.03, tr0, tr0 * 0.92], 0, rmod=flare_rmod(1.4 * S, 0.30, 5, rng.uniform(0, 6)))
    top = trunk[-1]
    nl = 6 if not young else 5
    az0 = rng.uniform(0, TAU)
    if not young:
        C, R = Vector((0, 0, 8.6)), Vector((10.0, 10.0, 7.2))
    else:
        C, R = Vector((0, 0, 5.0)), Vector((5.0, 5.0, 4.0))
    for i in range(nl):
        az = az0 + TAU * i / nl + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(az), math.sin(az), 0))
        sd = Vector((-d.y, d.x, 0)) * rng.uniform(-1, 1)
        if not young:
            L = rng.uniform(7.0, 9.0)
            z_end = rng.uniform(6.6, 8.2)
            p0 = top + d * 0.25 + Vector((0, 0, -0.35))
            pts = bez(p0, p0 + d * 2.6 + Vector((0, 0, 1.7)), p0 + d * (L * 0.62) + sd * 1.2 + Vector((0, 0, 1.6)),
                      d * L + sd * 0.8 + Vector((0, 0, z_end)), 7)
            rad = [0.52, 0.46, 0.38, 0.30, 0.22, 0.15, 0.09]
        else:
            L = rng.uniform(3.4, 4.2)
            p0 = top + d * 0.1 + Vector((0, 0, -0.2))
            pts = bez(p0, p0 + d * 1.2 + Vector((0, 0, 1.0)), p0 + d * (L * 0.6) + sd * 0.5 + Vector((0, 0, 1.9)),
                      d * L + sd * 0.4 + Vector((0, 0, rng.uniform(4.6, 5.6))), 5)
            rad = [0.22, 0.18, 0.13, 0.09, 0.05]
        t.limb(pts, rad, 1)
    # central limbs rising into the dome
    for i in range(2 if not young else 1):
        az = az0 + rng.uniform(0, TAU)
        d = Vector((math.cos(az), math.sin(az), 0))
        if not young:
            pts = bez(top + Vector((0, 0, -0.2)), top + d * 1.2 + Vector((0, 0, 2.5)), d * 2.5 + Vector((0, 0, 8.5)),
                      d * 3.2 + Vector((0, 0, 11.5)), 6)
            t.limb(pts, [0.46, 0.38, 0.30, 0.22, 0.15, 0.09], 1)
        else:
            pts = bez(top, top + Vector((0, 0, 1.2)), d * 0.8 + Vector((0, 0, 4.5)), d * 1.0 + Vector((0, 0, 6.5)), 4)
            t.limb(pts, [0.2, 0.15, 0.1, 0.06], 1)
    if not young:
        cen = sample_dome(rng, 21, C, R, math.radians(103), (0.70, 0.88), 3.3, seed=seed)
        cen += sample_dome(rng, 2, C + Vector((0, 0, -0.5)), R, math.radians(60), (0.30, 0.45), 3.0, seed=seed)
        add_clumps(t, cen, (2.5, 3.2), (1.55, 2.0))
        add_clumps(t, sample_dome(rng, 4, C, R, math.radians(100), (0.93, 1.02), 3.0, seed=seed + 5), (1.3, 1.7), (0.9, 1.1), kind='uv7_4')
        pal = ('#1d2715', '#3b4a29', '#71804c')
        t.k_lod1 = 8
    else:
        cen = sample_dome(rng, 17, C, R, math.radians(103), (0.66, 0.86), 1.75, seed=seed)
        add_clumps(t, cen, (1.4, 1.8), (0.95, 1.2))
        add_clumps(t, sample_dome(rng, 3, C, R, math.radians(100), (0.93, 1.02), 1.6, seed=seed + 5), (0.8, 1.0), (0.55, 0.7), kind='uv7_4')
        pal = ('#1f2a16', '#3e4d2b', '#74844f')
        t.k_lod1 = 7
    t.crown = Crown(C, R, pal, rng)
    connect_clumps(t, rng, 0.16 if not young else 0.08, 0.05 if not young else 0.03)
    if not young:
        sites = moss_sites(t, rng, 17, tmin=0.3, min_d=1.5)
        sites1 = sites[:8]
        t.extra0.append(lambda g, r, s=sites: [moss_cluster(g, p, r) for p in s])
        t.extra1.append(lambda g, r, s=sites1: [moss_cluster(g, p, r, n=1, wscale=3.0, segs=2, Lmax=1.4) for p in s])
    else:
        sites = moss_sites(t, rng, 5, tmin=0.4, min_d=1.2)
        t.extra0.append(lambda g, r, s=sites: [moss_cluster(g, p, r, Lmax=1.1) for p in s])
        t.extra1.append(lambda g, r, s=sites[:2]: [moss_cluster(g, p, r, n=1, wscale=2.5, segs=2, Lmax=1.0) for p in s])
    t.clump_kind = 'uv8'
    t.meta = dict(height_m=16.0 if not young else 9.0, spread_m=22.0 if not young else 11.0,
                  use='streets|yards|coast')
    return t


def sp_magnolia():
    t = Tree('magnolia', 23)
    rng = t.rng
    t.bark = bark_fn(rng, '#5f5a52', '#7d776d', '#4a453e', mottle=0.06, seed=3)
    t.limb([(0, 0, -0.5), (0, 0, 0), (0.05, 0, 1.2), (0.1, 0.05, 3.5), (0.05, 0.1, 6.5), (0, 0.05, 9.6)],
           [0.36, 0.33, 0.27, 0.22, 0.14, 0.06], 0, rmod=flare_rmod(0.8, 0.18, 4, 1.0))
    for i in range(6):
        z = 1.1 + i * 1.25 + rng.uniform(-0.2, 0.2)
        az = i * 2.399 + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(az), math.sin(az), 0))
        L = 2.6 * (1 - (z - 1) / 11) + 0.8
        p0 = Vector((0.05, 0.05, z))
        pts = bez(p0, p0 + d * L * 0.4 + Vector((0, 0, 0.5)), p0 + d * L * 0.8 + Vector((0, 0, 1.0)), p0 + d * L + Vector((0, 0, 1.2)), 4)
        t.limb(pts, [0.12, 0.09, 0.06, 0.035], 1)
    # conical-oval envelope sampled in height bands
    cen = []
    z0, z1 = 1.2, 10.0
    def rprof(z):
        tt = (z - 0.9) / 10.1
        return 4.25 * (1 - tt) ** 0.7 * min(1.0, (tt + 0.1) / 0.32) ** 0.5
    tries = 0
    while len(cen) < 21 and tries < 5000:
        tries += 1
        z = rng.uniform(z0, z1 - 0.4)
        a = rng.uniform(0, TAU)
        f = rng.uniform(0.6, 0.88)
        p = Vector((math.cos(a) * rprof(z) * f, math.sin(a) * rprof(z) * f, z))
        if all((p - q).length > 1.6 for q in cen):
            cen.append(p)
    cen.append(Vector((0.1, 0, 9.95)))
    add_clumps(t, cen, (1.35, 1.75), (1.15, 1.45), aniso=(0.85, 1.0))
    t.clumps[-1]['r'] = (1.0, 0.95, 1.05)
    C, R = Vector((0, 0, 5.4)), Vector((4.3, 4.3, 5.6))
    t.crown = Crown(C, R, ('#121c0d', '#26381b', '#526a37'), rng, bend=0.62, under='#5c4a2c', under_mix=0.4)
    connect_clumps(t, rng, 0.08, 0.025)
    t.zmin_leaf = 0.55
    # creamy blossoms sitting in the outer leaves of the upper crown
    tops = [c for c in t.clumps if c['c'].z > 3.5]
    bl = []
    for i in range(9):
        c = tops[int(rng.integers(len(tops)))]
        a = rng.uniform(0, TAU); el = rng.uniform(0.15, 0.9)
        d = Vector((math.cos(a) * math.cos(el), math.sin(a) * math.cos(el), math.sin(el)))
        p = c['c'] + Vector((d.x * c['r'][0], d.y * c['r'][1], d.z * c['r'][2])) * 0.93
        bl.append((p, d))

    def blossoms(g, r):
        V0 = [Vector(v) for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]
        F0 = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
        for p, d in bl:
            s = 0.16
            V = [p + Vector((v.x * s, v.y * s, v.z * s * 0.6)) for v in V0]
            col = [to_lin(hexc('#ece6d2') * (0.85 + 0.15 * clamp(v.z + 0.5))) for v in V0]
            g.add(V, F0, col, 'Leaves')
    t.extra0.append(blossoms)
    t.clump_kind = 'uv8'
    t.clump_amp = 0.10
    t.k_lod1 = 9
    t.meta = dict(height_m=11.0, spread_m=8.0, use='streets|yards')
    return t


def sp_hardwood():
    t = Tree('hardwood', 31)
    rng = t.rng
    t.bark = bark_fn(rng, '#504a42', '#726a5f', '#3b352f', mottle=0.08, seed=5)
    lead = [Vector((0, 0, -0.5)), Vector((0, 0, 0)), Vector((0.05, 0, 2.0)), Vector((0.1, 0.05, 4.5)),
            Vector((0.15, 0.1, 7.0)), Vector((0.1, 0.2, 10.0)), Vector((0.0, 0.25, 12.8))]
    t.limb(lead, [0.46, 0.40, 0.33, 0.29, 0.22, 0.14, 0.06], 0, rmod=flare_rmod(1.0, 0.2, 5, 2.0))
    for i in range(6):
        z = 4.4 + i * 0.95 + rng.uniform(-0.2, 0.2)
        az = i * 2.4 + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(az), math.sin(az), 0))
        L = rng.uniform(3.4, 4.6) * (1 - 0.06 * i)
        p0 = Vector((0.1, 0.1, z))
        pts = bez(p0, p0 + d * L * 0.35 + Vector((0, 0, L * 0.45)), p0 + d * L * 0.75 + Vector((0, 0, L * 0.8)),
                  p0 + d * L + Vector((0, 0, L * 0.95)), 5)
        t.limb(pts, [0.2, 0.15, 0.11, 0.07, 0.04], 1)
    C, R = Vector((0, 0, 9.6)), Vector((5.4, 5.4, 5.3))
    cen = sample_dome(rng, 18, C, R, math.radians(122), (0.68, 0.86), 2.3, seed=31)
    cen += sample_dome(rng, 2, C, R, math.radians(90), (0.25, 0.4), 2.0, seed=32)
    add_clumps(t, cen, (1.7, 2.1), (1.35, 1.7))
    add_clumps(t, sample_dome(rng, 4, C, R, math.radians(115), (0.93, 1.02), 2.0, seed=37), (1.0, 1.3), (0.8, 1.0), kind='uv7_4')
    t.crown = Crown(C, R, ('#1a2810', '#3a5221', '#759043'), rng)
    connect_clumps(t, rng, 0.09, 0.03)
    t.clump_kind = 'uv8'
    t.k_lod1 = 8
    t.meta = dict(height_m=15.0, spread_m=12.0, use='streets|yards|woods')
    return t


def pine_tufts(t, rng, z_lo, z_hi, n, Lfn, r_rng, rz_rng, trunk_at, flat_top=True, stub_zone=None):
    """Branches from the trunk ending in irregular two-lobed needle tufts."""
    for i in range(n):
        u = (i + rng.uniform(0, 0.6)) / n
        z = z_lo + (z_hi - z_lo) * u
        az = i * 2.399 + rng.uniform(-0.4, 0.4)
        d = Vector((math.cos(az), math.sin(az), 0))
        sd = Vector((-d.y, d.x, 0))
        L = Lfn(u) * rng.uniform(0.8, 1.15)
        p0 = trunk_at(z)
        rise = L * rng.uniform(0.3, 0.6)
        end = p0 + d * L + Vector((0, 0, rise))
        pts = bez(p0, p0 + d * L * 0.3 + Vector((0, 0, rise * 0.7)), p0 + d * L * 0.7 + Vector((0, 0, rise * 0.95)), end, 4)
        rb = 0.07 + 0.05 * (1 - u)
        t.limb(pts, [rb, rb * 0.7, rb * 0.45, rb * 0.25], 2)
        r = rng.uniform(*r_rng)
        hue = np.array([rng.uniform(0.95, 1.06), 1.0, rng.uniform(0.92, 1.05)])
        t.clumps.append(dict(c=end + Vector((0, 0, 0.1)), r=(r, r * rng.uniform(0.75, 0.95), rng.uniform(*rz_rng)),
                             tone=rng.uniform(0.9, 1.1), hue=hue, kind='uv8_4'))
        # second lobe: a bit back along the branch and to one side, slightly lower
        r2 = r * rng.uniform(0.65, 0.85)
        c2 = end - d * r * rng.uniform(0.6, 0.9) + sd * rng.choice([-1, 1]) * r * rng.uniform(0.3, 0.6) - Vector((0, 0, r * 0.15))
        t.clumps.append(dict(c=c2, r=(r2, r2 * 0.9, rng.uniform(*rz_rng) * 0.85), tone=rng.uniform(0.85, 1.0),
                             hue=hue * np.array([1.0, 1.0, rng.uniform(0.97, 1.03)]), kind='uv7_4'))


def stubs(t, rng, z0, z1, n, trunk_at, Lr=(0.4, 1.0)):
    for i in range(n):
        z = rng.uniform(z0, z1)
        az = rng.uniform(0, TAU)
        d = Vector((math.cos(az), math.sin(az), 0))
        p0 = trunk_at(z)
        L = rng.uniform(*Lr)
        t.limb([p0, p0 + d * L * 0.5 + Vector((0, 0, -0.05)), p0 + d * L + Vector((0, 0, -L * 0.25))], [0.04, 0.028, 0.012], 3)


def sp_loblolly(young=False):
    t = Tree('pine-young' if young else 'loblolly-pine', 41 if not young else 43)
    rng = t.rng
    t.bark = bark_fn(rng, '#5a4133', '#83634a', '#3e2f26', mottle=0.12, seed=7)
    H = 24.0 if not young else 10.0
    top = H - 0.7
    sway = rng.uniform(0, TAU)

    def axis(z):
        return Vector((0.22 * math.sin(z / H * 2.2 + sway) * H / 24, 0.15 * math.sin(z / H * 1.7) * H / 24, z))
    zs = [-0.5, 0.0, 0.6, 2.5, 6.0, 10.0, 14.0, 17.5, 20.5, top] if not young else [-0.5, 0.0, 0.5, 2.0, 4.0, 6.0, 8.0, top]
    if not young:
        rads = [0.42, 0.40, 0.33, 0.30, 0.27, 0.23, 0.19, 0.14, 0.09, 0.03]
    else:
        rads = [0.2, 0.19, 0.15, 0.13, 0.11, 0.08, 0.05, 0.02]
    t.limb([axis(z) for z in zs], rads, 0, rmod=flare_rmod(0.9, 0.12, 6, 0.5, 0.25))

    def trunk_at(z):
        return axis(z)
    if not young:
        stubs(t, rng, 6.0, 13.6, 6, trunk_at)
        pine_tufts(t, rng, 14.4, 22.4, 13, lambda u: 3.4 - 1.0 * u, (1.35, 1.75), (1.0, 1.2), trunk_at)
        for k in range(3):
            a = TAU * k / 3 + rng.uniform(-0.4, 0.4)
            c = axis(23.0) + Vector((math.cos(a), math.sin(a), 0)) * rng.uniform(0.7, 1.2)
            t.clumps.append(dict(c=c, r=(1.35, 1.15, 0.72), tone=1.05, hue=np.array([1.0, 1.0, 0.98]), kind='uv8_4'))
        C, R = Vector((0, 0, 19.0)), Vector((4.8, 4.8, 5.0))
        t.k_lod1 = 8
    else:
        stubs(t, rng, 1.2, 3.4, 4, trunk_at, (0.3, 0.6))
        pine_tufts(t, rng, 3.6, 8.9, 14, lambda u: 2.0 - 1.3 * u, (0.85, 1.1), (0.75, 0.9), trunk_at)
        t.clumps.append(dict(c=axis(9.3), r=(0.7, 0.65, 0.7), tone=1.05, hue=np.array([1.0, 1.0, 1.0]), kind='uv8_4'))
        C, R = Vector((0, 0, 6.5)), Vector((2.6, 2.6, 3.6))
        t.k_lod1 = 7
    t.crown = Crown(C, R, ('#161e0d', '#2f3e1d', '#64753a'), rng, bend=0.55)
    t.clump_kind = 'uv8_4'
    t.clump_amp = 0.2
    t.clump_flat = 0.2
    t.meta = dict(height_m=H, spread_m=10.0 if not young else 5.0, use='woods|yards|streets' if not young else 'woods|yards')
    return t


def sp_cypress():
    t = Tree('bald-cypress', 53)
    rng = t.rng
    t.bark = bark_fn(rng, '#5e4f43', '#7e7266', '#45392f', mottle=0.10, seed=9)
    H = 18.0
    zs = [-0.5, 0.0, 0.5, 1.2, 2.5, 5.0, 8.0, 11.0, 14.0, 16.0, 17.4]
    rads = [1.05, 0.98, 0.72, 0.52, 0.42, 0.36, 0.30, 0.24, 0.17, 0.11, 0.04]
    t.limb([Vector((0.03 * z, 0.0, z)) for z in zs], rads, 0, rmod=flare_rmod(2.2, 0.32, 6, 0.3, 0.1))

    def trunk_at(z):
        return Vector((0.03 * z, 0, z))
    stubs(t, rng, 3.5, 6.5, 4, trunk_at, (0.4, 0.9))
    n = 15
    for i in range(n):
        u = (i + rng.uniform(0, 0.6)) / n
        z = 5.6 + 10.6 * u
        az = i * 2.399 + rng.uniform(-0.4, 0.4)
        d = Vector((math.cos(az), math.sin(az), 0))
        L = (2.5 - 1.3 * u) * rng.uniform(0.85, 1.15)
        p0 = trunk_at(z)
        end = p0 + d * L + Vector((0, 0, L * rng.uniform(0.05, 0.25)))
        pts = bez(p0, p0 + d * L * 0.35 + Vector((0, 0, 0.25)), p0 + d * L * 0.7 + Vector((0, 0, -0.1)), end, 4)
        rb = 0.06 + 0.06 * (1 - u)
        t.limb(pts, [rb, rb * 0.7, rb * 0.45, rb * 0.25], 3)
        r = rng.uniform(1.5, 1.85) * (1 - 0.3 * u)
        t.clumps.append(dict(c=end, r=(r, r * rng.uniform(0.75, 0.95), rng.uniform(1.0, 1.2)), tone=rng.uniform(0.9, 1.1),
                             hue=np.array([rng.uniform(0.96, 1.07), 1.0, rng.uniform(0.92, 1.03)]), kind='uv8_4'))
        m = pts[2]
        r2 = r * 0.78
        t.clumps.append(dict(c=m + Vector((0, 0, 0.12)) + Vector((-d.y, d.x, 0)) * rng.uniform(-0.5, 0.5),
                             r=(r2, r2 * 0.85, 0.9), tone=rng.uniform(0.85, 1.0), hue=np.array([1.0, 1.0, 1.0]), kind='uv7_4'))
    t.clumps.append(dict(c=trunk_at(17.2), r=(1.3, 1.1, 0.8), tone=1.05, hue=np.array([1.02, 1.0, 0.98]), kind='uv8_4'))
    C, R = Vector((0, 0, 12.0)), Vector((3.8, 3.8, 6.0))
    t.crown = Crown(C, R, ('#1e2812', '#465a29', '#849852'), rng, bend=0.55)
    t.clump_kind = 'uv8_4'
    t.clump_amp = 0.2
    t.clump_flat = 0.2
    t.k_lod1 = 8
    knees = []
    for i in range(5):
        a = rng.uniform(0, TAU); dist = rng.uniform(1.3, 2.6)
        knees.append((Vector((math.cos(a) * dist, math.sin(a) * dist, -0.3)), rng.uniform(0.25, 0.6), rng.uniform(0.1, 0.17)))

    def kneefn(g, r):
        for p, h, rr in knees:
            tube(g, [p, p + Vector((0, 0, 0.3 + h * 0.6)), p + Vector((0.02, 0, 0.3 + h))], [rr, rr * 0.75, rr * 0.3], 5, t.bark)
    t.extra0.append(kneefn)
    t.meta = dict(height_m=H, spread_m=8.0, use='wet')
    return t


def sp_crepe(pink=False):
    t = Tree('crepe-myrtle-pink' if pink else 'crepe-myrtle', 61)
    rng = t.rng
    t.bark = bark_fn(rng, '#8f7563', '#b39b84', '#6e5a4c', mottle=0.22, seed=11)
    ns = 5
    az0 = rng.uniform(0, TAU)
    for i in range(ns):
        az = az0 + TAU * i / ns + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(az), math.sin(az), 0))
        sd = Vector((-d.y, d.x, 0))
        b = d * rng.uniform(0.06, 0.16)
        lean = rng.uniform(0.35, 0.6)
        h = rng.uniform(2.9, 3.5)
        pts = bez(b + Vector((0, 0, -0.4)), b + Vector((0, 0, 1.0)) + sd * 0.1, b + d * lean * h * 0.55 + Vector((0, 0, h * 0.7)) - sd * 0.12,
                  b + d * lean * h + Vector((0, 0, h)), 6)
        r0 = rng.uniform(0.065, 0.09)
        t.limb(pts, [r0 * 1.15, r0, r0 * 0.9, r0 * 0.75, r0 * 0.55, r0 * 0.35], 0 if i < 3 else 1)
    C, R = Vector((0, 0, 3.55)), Vector((2.1, 2.1, 1.45))
    cen = sample_dome(rng, 15, C, R, math.radians(100), (0.62, 0.86), 0.85, seed=61)
    add_clumps(t, cen, (0.72, 0.95), (0.58, 0.75))
    add_clumps(t, sample_dome(rng, 3, C, R, math.radians(95), (0.93, 1.02), 0.6, seed=67), (0.45, 0.6), (0.38, 0.48), kind='uv7_4')
    t.crown = Crown(C, R, ('#1a2812', '#375124', '#6d8a46'), rng)
    connect_clumps(t, rng, 0.04, 0.015, min_idx=3)
    if pink:
        pk_d, pk_l = hexc('#b0406e'), hexc('#e682ae')
        off = Vector((5.0, 1.0, 2.0))

        def flowers(p, n, c, th, out):
            f = clamp((th - 0.25) * 1.7) * clamp(0.3 + out) * clamp(0.7 + 0.8 * noise.noise(p * 2.3 + off))
            f = clamp((f - 0.22) * 2.2)
            pk = lerp(pk_d, pk_l, clamp(th * 0.9 + 0.2 * out))
            return lerp(c, pk, clamp(f * 1.15))
        t.leaf_extra = flowers
    t.clump_kind = 'uv8'
    t.k_lod1 = 7
    t.meta = dict(height_m=5.0, spread_m=4.5, use='streets|yards')
    return t


def sp_shrub():
    t = Tree('shrub', 71)
    rng = t.rng
    t.bark = bark_fn(rng, '#4c4238', '#665a4c', seed=13)
    for i in range(3):
        a = TAU * i / 3 + rng.uniform(-0.3, 0.3)
        d = Vector((math.cos(a), math.sin(a), 0))
        t.limb([d * 0.03 + Vector((0, 0, -0.2)), d * 0.12 + Vector((0, 0, 0.2)), d * 0.25 + Vector((0, 0, 0.5))], [0.03, 0.025, 0.012], 2)
    cen = [Vector((0, 0, 0.66))]
    for i in range(6):
        a = TAU * i / 6 + rng.uniform(-0.25, 0.25)
        cen.append(Vector((math.cos(a) * 0.42, math.sin(a) * 0.42, rng.uniform(0.42, 0.56))))
    add_clumps(t, cen, (0.40, 0.52), (0.36, 0.46))
    t.clumps[0]['r'] = (0.62, 0.58, 0.54)
    C, R = Vector((0, 0, 0.55)), Vector((0.8, 0.8, 0.62))
    t.crown = Crown(C, R, ('#15200e', '#2b411d', '#5a7539'), rng)
    t.zmin_leaf = -0.04
    t.clump_kind = 'uv8'
    t.clump_flat = 0.1
    t.k_lod1 = 4
    t.meta = dict(height_m=1.2, spread_m=1.6, use='yards|streets')
    return t


# ----------------------------------------------------------------------------- palmetto

def sp_palmetto():
    t = Tree('sabal-palmetto', 81)
    t.meta = dict(height_m=9.0, spread_m=5.0, use='coast|yards|streets')

    def build(lod):
        g = Geo()
        rng = np.random.default_rng(81)
        bark = bark_fn(rng, '#6a665e', '#857f74', '#55524b', mottle=0.06, seed=17)
        boot_d, boot_l = hexc('#5d4c3a'), hexc('#8b7556')
        zt = 7.7
        lean = Vector((0.35, 0.1, 0))

        def axis(z):
            u = z / zt
            return lean * (u * u) + Vector((0, 0, z))
        nz = 16 if lod == 0 else 4
        zs = [-0.5, 0.0] + [zt * (i / (nz - 1)) ** 1.0 for i in range(1, nz)]
        zs = sorted(set([round(z, 3) for z in zs]))
        pts = [axis(z) for z in zs]
        rad = []
        for z in zs:
            r = 0.21 - 0.02 * clamp(z / 5)
            if z < 0.3:
                r = 0.27 - 0.2 * clamp(z / 0.3) * 0.3
            if z > zt - 2.2:
                r = 0.21 + 0.09 * clamp((z - (zt - 2.2)) / 1.2)
            rad.append(r)

        def rmod(i, a, p):
            if p.z > zt - 2.2:
                return 1 + 0.10 * math.cos(3 * a + i * 1.7) + 0.05 * math.cos(7 * a + i)
            return 1 + 0.025 * math.cos(5 * a + i)

        def tcol(p, d, u):
            if p.z > zt - 2.3:
                k = 0.5 + 0.5 * math.cos(p.z * 9.0 + math.atan2(d.y, d.x) * 3)
                return to_lin(lerp(boot_d, boot_l, k * 0.8 + rng.uniform(0, 0.2)))
            return bark(p, d, u)
        tube(g, pts, rad, 8 if lod == 0 else 5, tcol, tip=False, rmod=rmod)
        crown_c = axis(zt) + Vector((0, 0, 0.25))
        # cap the trunk inside the frond bases
        g.add([crown_c + Vector((0, 0, 0.2))] + [axis(zt) + Vector((math.cos(TAU * k / 6) * 0.3, math.sin(TAU * k / 6) * 0.3, 0)) for k in range(6)],
              [(0, 1 + (k + 1) % 6, 1 + k) for k in range(6)], [to_lin(boot_d)] * 7, 'Bark')
        live_d, live_m, live_l = hexc('#2f3d22'), hexc('#4f6234'), hexc('#7f9053')
        dead_d, dead_l = hexc('#6f5638'), hexc('#a78a5f')
        nf = 30 if lod == 0 else 10
        nd = 7 if lod == 0 else 3
        M = 9 if lod == 0 else 4
        for i in range(nf + nd):
            dead = i >= nf
            az = i * 2.39996 + rng.uniform(-0.2, 0.2)
            if not dead:
                u = i / nf
                el = math.radians(68 - 95 * u ** 0.85 + rng.uniform(-8, 8))
                Lp = rng.uniform(1.3, 1.7)
                blade = rng.uniform(1.15, 1.4)
                span = math.radians(rng.uniform(95, 115))
            else:
                el = math.radians(rng.uniform(-82, -70))
                Lp = rng.uniform(0.7, 1.0)
                blade = rng.uniform(0.9, 1.1)
                span = math.radians(35)
            f = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
            base = crown_c + Vector((math.cos(az), math.sin(az), 0)) * 0.12 - Vector((0, 0, 0.15 if not dead else 0.6))
            # petiole arcs under gravity
            hast = base + f * Lp - Vector((0, 0, 0.18 * Lp * max(0.2, math.cos(el))))
            fd = (hast - base).normalized()
            nb = (UP - fd * UP.dot(fd))
            nb = nb.normalized() if nb.length > 1e-4 else Vector((1, 0, 0))
            sd = fd.cross(nb).normalized()
            if lod == 0:
                ribbon(g, [base, base.lerp(hast, 0.5) + nb * 0.04, hast], [0.07, 0.05, 0.04], sd,
                       [to_lin((dead_d if dead else hexc('#6b6a40')) * 0.9)] * 3)
            # costapalmate blade: pleated fan, halves drooping either side of the costa
            ribs = []
            for j in range(M):
                psi = -span + 2 * span * j / (M - 1)
                rd = (fd * math.cos(psi) + sd * math.sin(psi) - nb * (0.55 * abs(math.sin(psi)) + 0.1)).normalized()
                Lr = blade * (1 - 0.28 * abs(psi) / span)
                fold = (0.07 if j % 2 else -0.05) * (1 if lod == 0 else 0)
                droop = 0.35 + (0.25 if dead else 0.0)
                pm = hast + rd * Lr * 0.5 + nb * fold - Vector((0, 0, droop * 0.25 * Lr))
                pe = hast + rd * Lr + nb * fold * 1.5 - Vector((0, 0, droop * Lr))
                ribs.append((pm, pe, rd))
            V, F, C = [hast], [], []
            if dead:
                C.append(to_lin(dead_d))
            else:
                C.append(to_lin(live_d * rng.uniform(0.9, 1.1)))
            tone = rng.uniform(0.9, 1.08)
            yel = rng.uniform(0, 0.25) * (i / nf if not dead else 0)
            for j, (pm, pe, rd) in enumerate(ribs):
                V += [pm, pe]
                if dead:
                    C += [to_lin(lerp(dead_d, dead_l, 0.4) * tone), to_lin(dead_l * tone)]
                else:
                    lm = clamp(0.45 + 0.35 * f.z + (0.15 if j % 2 else -0.1))
                    cm = lerp(live_d, live_m, lm) if lm < 0.5 else lerp(live_m, live_l, lm - 0.5)
                    ce = lerp(live_m, live_l, clamp(0.55 + 0.4 * f.z + (0.15 if j % 2 else -0.1)))
                    ce = lerp(ce, hexc('#a39a55'), yel)
                    C += [to_lin(cm * tone), to_lin(ce * tone)]
            for j in range(M - 1):
                a, b = 1 + 2 * j, 1 + 2 * (j + 1)
                F.append((0, a, b))
                F.append((a, a + 1, b + 1, b))
            if lod == 0:
                # ragged split tips of the leaf segments
                for j in range(M):
                    pm, pe, rd = ribs[j]
                    k0 = len(V)
                    w = (pe - hast).length * 0.07
                    sdj = rd.cross(nb).normalized()
                    tip = pe + rd * 0.28 - Vector((0, 0, 0.32))
                    V += [pe - sdj * w, pe + sdj * w, tip]
                    cc = C[2 + 2 * j]
                    C += [cc, cc, to_lin(to_srgb(cc) * 1.05)]
                    F.append((k0, k0 + 1, k0 + 2))
            g.add(V, F, C, 'Leaves')
        return g
    t.custom = build
    return t


# ----------------------------------------------------------------------------- hedge, marsh grass

def sp_hedge():
    t = Tree('hedge-1m', 91)
    t.meta = dict(height_m=1.1, spread_m=1.0, use='yards|streets')

    def build(lod):
        g = Geo()
        rng = np.random.default_rng(91)
        if lod == 0:
            prof = [(-0.42, -0.1), (-0.42, 0.04), (-0.415, 0.3), (-0.405, 0.58), (-0.39, 0.82), (-0.355, 0.97), (-0.27, 1.06),
                    (-0.13, 1.1), (0.0, 1.105), (0.13, 1.1), (0.27, 1.06), (0.355, 0.97), (0.39, 0.82), (0.405, 0.58), (0.415, 0.3),
                    (0.42, 0.04), (0.42, -0.1)]
            nx = 14
        else:
            prof = [(-0.42, -0.1), (-0.41, 0.5), (-0.37, 0.95), (-0.15, 1.1), (0.15, 1.1), (0.37, 0.95), (0.41, 0.5), (0.42, -0.1)]
            nx = 1
        npf = len(prof)
        # outward profile normals
        pn = []
        for i in range(npf):
            a = Vector((0, *prof[max(i - 1, 0)])); b = Vector((0, *prof[min(i + 1, npf - 1)]))
            tng = (b - a).normalized()
            pn.append(Vector((0, -tng.z, tng.y)) * -1 if False else Vector((0, tng.z, -tng.y)))
        # make sure normals point away from the hedge centre line
        for i in range(npf):
            c = Vector((0, prof[i][0], prof[i][1] - 0.55))
            if pn[i].dot(c) < 0:
                pn[i] = -pn[i]
        pal = (hexc('#1a2810'), hexc('#2f4420'), hexc('#5f7b3a'))
        V, C, F = [], [], []
        s_len = [0.0]
        for i in range(1, npf):
            s_len.append(s_len[-1] + math.dist(prof[i], prof[i - 1]))
        for ix in range(nx + 1):
            x = -0.5 + ix / nx
            ang = TAU * (x + 0.5)
            for i, (y, z) in enumerate(prof):
                s = s_len[i]
                q = Vector((math.cos(ang) * 0.9, math.sin(ang) * 0.9, s * 2.6))
                q2 = Vector((math.cos(ang) * 2.2 + 3, math.sin(ang) * 2.2, s * 6.0))
                amp = 0.0 if z < 0.06 else (1.0 if lod == 0 else 0.0)
                dsp = amp * (0.035 * noise.noise(q) + 0.014 * noise.noise(q2))
                p = Vector((x, y, z)) + pn[i] * dsp
                V.append(p)
                top = clamp((z - 0.1) / 1.0)
                L = 0.25 + 0.5 * top + 0.25 * clamp(pn[i].z) + 6.0 * dsp + rng.normal(0, 0.04)
                C.append(to_lin(grad3(pal, L)))
        for ix in range(nx):
            for i in range(npf - 1):
                a = ix * npf + i; b = (ix + 1) * npf + i
                F.append((a, b, b + 1, a + 1))
        # end caps (identical at both ends so segments tile)
        for ix, flip in ((0, True), (nx, False)):
            base = ix * npf
            cen = len(V); V.append(Vector((-0.5 + ix / nx, 0, 0.5))); C.append(to_lin(pal[0] * 1.2))
            for i in range(npf - 1):
                f = (base + i, base + i + 1, cen)
                F.append(f if not flip else tuple(reversed(f)))
        g.add(V, F, C, 'Leaves')
        return g
    t.custom = build
    return t


def sp_marsh():
    t = Tree('marsh-grass', 101)
    t.meta = dict(height_m=1.4, spread_m=2.0, use='wet|coast')

    def build(lod):
        g = Geo()
        rng = np.random.default_rng(101)
        n = 330 if lod == 0 else 55
        wmul = 1.0 if lod == 0 else 2.6
        base_c, mid_c, tip_c, dead_c = hexc('#3f4d26'), hexc('#71813f'), hexc('#a9a565'), hexc('#a8936a')
        for b in range(n):
            a = rng.uniform(0, TAU)
            rr = math.sqrt(rng.uniform(0, 1)) * 0.7
            p0 = Vector((math.cos(a) * rr * 1.05, math.sin(a) * rr * 0.95, -0.05))
            H = rng.uniform(0.75, 1.45) * (1 - 0.35 * rr)
            lean = Vector((math.cos(a), math.sin(a), 0)) * (0.08 + 0.3 * rr) * H + Vector((rng.normal(0, 0.06), rng.normal(0, 0.06), 0))
            arc = rng.uniform(0.0, 0.25)
            phi = rng.uniform(0, TAU)
            side = Vector((math.cos(phi), math.sin(phi), 0))
            dead = rng.random() < 0.14
            tone = rng.uniform(0.85, 1.1)
            us = (0.0, 0.4, 0.75, 1.0)
            w0 = rng.uniform(0.016, 0.026) * wmul
            pts, wid, col = [], [], []
            for u in us:
                h = H * u - arc * H * u ** 3
                pts.append(p0 + lean * u ** 1.6 + Vector((0, 0, h)))
                wid.append(w0 * (1 - u) ** 0.7 if u < 1 else 0.0)
                if dead:
                    c = lerp(dead_c * 0.75, dead_c, u)
                else:
                    c = lerp(base_c, mid_c, u / 0.5) if u < 0.5 else lerp(mid_c, tip_c, (u - 0.5) / 0.5 * rng.uniform(0.3, 0.9))
                col.append(to_lin(c * tone))
            ribbon(g, pts, wid, side, col)
        return g
    t.custom = build
    return t


SPECIES = {
    'live-oak': lambda: sp_live_oak(),
    'live-oak-young': lambda: sp_live_oak('live-oak-young', 13, young=True),
    'magnolia': sp_magnolia,
    'loblolly-pine': lambda: sp_loblolly(False),
    'pine-young': lambda: sp_loblolly(True),
    'crepe-myrtle': lambda: sp_crepe(False),
    'crepe-myrtle-pink': lambda: sp_crepe(True),
    'sabal-palmetto': sp_palmetto,
    'bald-cypress': sp_cypress,
    'hardwood': sp_hardwood,
    'shrub': sp_shrub,
    'hedge-1m': sp_hedge,
    'marsh-grass': sp_marsh,
}
LEAF_ROUGH = {'magnolia': 0.42, 'sabal-palmetto': 0.55}
LIMITS = {'live-oak': 3000}
OBJ_NAMES = {'live-oak': 'LiveOak', 'live-oak-young': 'LiveOakYoung', 'magnolia': 'Magnolia', 'loblolly-pine': 'LoblollyPine',
             'pine-young': 'PineYoung', 'crepe-myrtle': 'CrepeMyrtle', 'crepe-myrtle-pink': 'CrepeMyrtlePink',
             'sabal-palmetto': 'SabalPalmetto', 'bald-cypress': 'BaldCypress', 'hardwood': 'Hardwood', 'shrub': 'Shrub',
             'hedge-1m': 'Hedge1m', 'marsh-grass': 'MarshGrass'}


def bbox_of(g):
    A = np.array([list(v) for v in g.V])
    return A.min(0), A.max(0)


def build_species(sid):
    wp.reset()
    make_materials(leaf_rough=LEAF_ROUGH.get(sid, 0.78))
    t = SPECIES[sid]()
    if hasattr(t, 'custom'):
        g0, g1 = t.custom(0), t.custom(1)
    else:
        g0, g1 = realize(t, 0), realize(t, 1)
    # LOD1 average leaf colour matches LOD0
    m0, m1 = g0.mean_color('Leaves'), g1.mean_color('Leaves')
    g1.scale_colors('Leaves', np.clip(m0 / np.maximum(m1, 1e-4), 0.7, 1.4))
    if 'Bark' in g0.M and 'Bark' in g1.M:
        b0, b1 = g0.mean_color('Bark'), g1.mean_color('Bark')
        g1.scale_colors('Bark', np.clip(b0 / np.maximum(b1, 1e-4), 0.7, 1.4))
    res = {}
    for lod, g in ((0, g0), (1, g1)):
        name = OBJ_NAMES[sid] + ('' if lod == 0 else '_LOD1')
        o = build_object(g, name)
        wp.finalize([o])
        # untextured: drop the box UVs so vertices are not split at UV seams (smaller, smoother)
        while o.data.uv_layers:
            o.data.uv_layers.remove(o.data.uv_layers[0])
        apply_normals(o, g)
        path = os.path.join(OUT, sid + ('.glb' if lod == 0 else '-lod1.glb'))
        wp.export_glb(path, [o])
        mn, mx = bbox_of(g)
        res[lod] = dict(tris=g.tris(), path=path, size=os.path.getsize(path), bbox=[mn.tolist(), mx.tolist()],
                        leaf=to_srgb(g.mean_color('Leaves')).round(3).tolist())
    lim0 = LIMITS.get(sid, 2000)
    flag = '' if res[0]['tris'] <= lim0 and res[1]['tris'] <= 300 else '  OVER BUDGET'
    mn, mx = res[0]['bbox']
    h = mx[2]
    spread = max(mx[0] - mn[0], mx[1] - mn[1])
    print(f"SPECIES {sid}: lod0 {res[0]['tris']} lod1 {res[1]['tris']} h={h:.2f} spread={spread:.2f} "
          f"zmin={mn[2]:.2f} leaf0={res[0]['leaf']} leaf1={res[1]['leaf']}{flag}")
    entry = dict(id=sid, height_m=round(h, 2), spread_m=round(spread, 2), triangles=res[0]['tris'],
                 lod1_triangles=res[1]['tris'], use=t.meta['use'],
                 files={'lod0': f'models/vegetation/{sid}.glb', 'lod1': f'models/vegetation/{sid}-lod1.glb'})
    return entry, res


# ----------------------------------------------------------------------------- renders

def import_glb(path, loc, rot=0.0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.parent is None:
            o.location = Vector(loc)
            o.rotation_euler = (0, 0, rot)
    return new


BACK = [('live-oak', -27.0), ('hardwood', -6.5), ('loblolly-pine', 5.0), ('magnolia', 14.5), ('bald-cypress', 25.0)]
FRONT = [('live-oak-young', -24.0), ('crepe-myrtle', -15.5), ('crepe-myrtle-pink', -10.5), ('sabal-palmetto', -4.0),
         ('pine-young', 3.0), ('shrub', 8.5), ('hedge-1m', 11.5), ('marsh-grass', 16.5)]
Y_BACK, Y_FRONT = 14.0, -4.0


def stage(lod=0, only=None):
    suf = '.glb' if lod == 0 else '-lod1.glb'
    placed = {}
    for sid, x in BACK:
        if only and sid not in only:
            continue
        placed[sid] = import_glb(os.path.join(OUT, sid + suf), (x, Y_BACK, 0), rot=0.4 * x)
    for sid, x in FRONT:
        if only and sid not in only:
            continue
        if sid == 'hedge-1m':
            for k in range(4):
                import_glb(os.path.join(OUT, sid + suf), (x + k * 1.0, Y_FRONT, 0))
            continue
        placed[sid] = import_glb(os.path.join(OUT, sid + suf), (x, Y_FRONT, 0), rot=0.7 * x)
    post = wp.mat('PostPaint', '#d9d4c8', rough=0.7)
    wp.box('Post', 0.1, 0.1, 1.85, loc=(-19.5, Y_FRONT - 1.0, -0.05), material=post)
    wp.box('Post2', 0.1, 0.1, 1.85, loc=(-12.0, Y_BACK - 3.5, -0.05), material=post)
    return placed


def do_render(mode, only=None, lod=0, tag=''):
    final = mode == 'final'
    samples, res = (96, (1600, 1000)) if final else (24, (640, 400))
    outdir = RENDERS if final else os.path.join(wp.TEX_DIR, 'iter')
    views = {
        'eye': ((0.0, -54.0, 1.7), (0.0, 0.0, 8.4), 30),
        'aerial': ((0.0, -85.0, 87.0), (0.0, 4.0, 3.0), 40),
    }
    if not final:
        views['top'] = ((-20.0, -120.0, 230.0), (0.0, 4.0, 0.0), 50)
    for v, (loc, tgt, lens) in views.items():
        wp.reset()
        wp.render_rig(samples=samples, res=res, threads=2, ground_size=600, exposure=-0.35)
        stage(lod, only)
        wp.camera(loc, tgt, lens=lens)
        name = {'eye': 'vegetation', 'aerial': 'vegetation-aerial', 'top': 'vegetation-top'}[v]
        wp.render(os.path.join(outdir, name + tag + ('-lod1' if lod else '') + '.jpg'))


def verify():
    """Re-import every GLB in a fresh session: loads, materials, COLOR_0, bbox, origin, tris."""
    out = []
    for sid in SPECIES:
        for suf in ('.glb', '-lod1.glb'):
            wp.reset()
            p = os.path.join(OUT, sid + suf)
            objs = import_glb(p, (0, 0, 0))
            meshes = [o for o in objs if o.type == 'MESH']
            tris = wp.tri_count(meshes)
            mats = sorted({m.name for o in meshes for m in o.data.materials})
            cols = [a.name for o in meshes for a in o.data.color_attributes]
            A = np.array([list(o.matrix_world @ v.co) for o in meshes for v in o.data.vertices])
            mn, mx = A.min(0), A.max(0)
            # trunk centre at grade (vertices within 0.3 m of z=0)
            near = A[np.abs(A[:, 2]) < 0.25]
            c0 = near[:, :2].mean(0) if len(near) else np.zeros(2)
            out.append(dict(file=os.path.basename(p), tris=tris, mats=mats, colors=cols, min=mn.round(2).tolist(),
                            max=mx.round(2).tolist(), base_xy=np.round(c0, 2).tolist(), kb=round(os.path.getsize(p) / 1024, 1)))
            print('VERIFY', json.dumps(out[-1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--render', choices=['none', 'iter', 'final'], default='none')
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--lod', type=int, default=0)
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    ids = a.only or list(SPECIES)
    if not a.no_export:
        idx_path = os.path.join(OUT, 'index.json')
        index = []
        if os.path.exists(idx_path) and a.only:
            index = [e for e in json.load(open(idx_path)) if e['id'] not in ids]
        for sid in ids:
            e, _ = build_species(sid)
            index.append(e)
        order = list(SPECIES)
        index.sort(key=lambda e: order.index(e['id']))
        with open(idx_path, 'w') as f:
            json.dump(index, f, indent=1)
        print('wrote', idx_path)
    if a.verify:
        verify()
    if a.render != 'none':
        do_render(a.render, only=a.only if a.render == 'iter' else None, lod=a.lod)


if __name__ == '__main__':
    main()
