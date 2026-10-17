"""Outbuildings and civic archetypes for the Westport 3D map (ASSET-SPEC "Archetypes", misc set).

Builds shed, shed-metal, barn, church-brick, church-frame, apartments-garden and motel-strip as
low-poly GLBs and writes models/archetypes/index-misc.json.

    WP_TEX_DIR=/tmp/somewhere python3 tools/blender/archetypes/misc.py              # everything
    python3 tools/blender/archetypes/misc.py --only barn --no-render                  # one model
    python3 tools/blender/archetypes/misc.py --lineup out.jpg                         # also render a lineup

Conventions: meters, +Z up, street front faces -Y, origin = center of the full XY bounding box at
finished grade; foundations and steps run down to z = -0.6. Materials are exactly Wall, Roof, Trim,
Glass, Door, Masonry. Wall, Roof and Door are near-white so the map's per-instance tint shows.

The first half of this file is a small polygon-soup kit (G, box, walls with openings, windows,
roofs, round bars) that tools/blender/landmarks/build.py imports too.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import wp  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from PIL import Image  # noqa: E402

REPO = wp.REPO
OUT = os.path.join(REPO, 'models', 'archetypes')
ZF = -0.6


# ============================================================================ polygon soup kit

def newell(pts):
    n = Vector((0, 0, 0))
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n


class G:
    """Polygon soup with a material key (and smooth flag) per face; becomes one mesh object."""

    def __init__(self):
        self.V, self.F, self.M, self.S = [], [], [], []

    def poly(self, pts, mat, facing=None, smooth=False):
        pts = [Vector(p) for p in pts]
        if facing is not None and newell(pts).dot(Vector(facing)) < 0:
            pts = pts[::-1]
        b = len(self.V)
        self.V.extend(tuple(p) for p in pts)
        self.F.append(tuple(range(b, b + len(pts))))
        self.M.append(mat); self.S.append(smooth)

    def tris(self):
        return sum(len(f) - 2 for f in self.F)

    def bbox(self):
        xs = [v[0] for v in self.V]; ys = [v[1] for v in self.V]; zs = [v[2] for v in self.V]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def shift(self, dx, dy, dz=0.0):
        self.V = [(x + dx, y + dy, z + dz) for x, y, z in self.V]

    def extend(self, other):
        b = len(self.V)
        self.V.extend(other.V)
        self.F.extend(tuple(i + b for i in f) for f in other.F)
        self.M.extend(other.M); self.S.extend(other.S)


def to_object(g, name, M, collection=None):
    """Make one mesh object from a soup; M maps material keys to bpy materials."""
    keys = []
    for k in g.M:
        if k not in keys:
            keys.append(k)
    me = bpy.data.meshes.new(name)
    me.from_pydata(g.V, [], g.F)
    me.update()
    for k in keys:
        me.materials.append(M[k])
    idx = [keys.index(k) for k in g.M]
    me.polygons.foreach_set('material_index', idx)
    me.polygons.foreach_set('use_smooth', [bool(s) for s in g.S])
    me.update()
    o = bpy.data.objects.new(name, me)
    (collection or bpy.context.scene.collection).objects.link(o)
    return o


def box(g, mat, x0, x1, y0, y1, z0, z1, skip='b'):
    if x1 - x0 < 1e-5 or y1 - y0 < 1e-5 or z1 - z0 < 1e-5:
        return
    if 's' not in skip:
        g.poly([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], mat, (0, -1, 0))
    if 'n' not in skip:
        g.poly([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], mat, (0, 1, 0))
    if 'e' not in skip:
        g.poly([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], mat, (1, 0, 0))
    if 'w' not in skip:
        g.poly([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], mat, (-1, 0, 0))
    if 't' not in skip:
        g.poly([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], mat, (0, 0, 1))
    if 'b' not in skip:
        g.poly([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], mat, (0, 0, -1))


def cbox(g, mat, cx, cy, sx, sy, z0, z1, skip='b'):
    box(g, mat, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, z0, z1, skip)


def ngon(g, mat, cx, cy, r0, z0, z1, n=8, r1=None, caps='t', rot=None, smooth=True):
    """Vertical n-sided prism / frustum (columns, cylinders, spires). r1 = top radius (0 = point)."""
    r1 = r0 if r1 is None else r1
    rot = (math.pi / n) if rot is None else rot
    ang = [rot + 2 * math.pi * i / n for i in range(n)]
    lo = [(cx + r0 * math.cos(a), cy + r0 * math.sin(a), z0) for a in ang]
    hi = [(cx + r1 * math.cos(a), cy + r1 * math.sin(a), z1) for a in ang]
    for i in range(n):
        j = (i + 1) % n
        am = (ang[i] + ang[j]) / 2
        out = (math.cos(am), math.sin(am), 0)
        if r1 < 1e-6:
            g.poly([lo[i], lo[j], hi[i]], mat, out, smooth)
        else:
            g.poly([lo[i], lo[j], hi[j], hi[i]], mat, out, smooth)
    if 't' in caps and r1 > 1e-6:
        g.poly(hi, mat, (0, 0, 1))
    if 'b' in caps:
        g.poly(lo, mat, (0, 0, -1))


def lathe(g, mat, cx, cy, prof, n=16, smooth=True, cap_top=True):
    """Surface of revolution from [(r, z), ...] bottom to top."""
    rings = []
    for r, z in prof:
        rings.append([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)])
    for k in range(len(prof) - 1):
        a, b = rings[k], rings[k + 1]
        for i in range(n):
            j = (i + 1) % n
            am = 2 * math.pi * (i + 0.5) / n
            dr = prof[k + 1][0] - prof[k][0]; dz = prof[k + 1][1] - prof[k][1]
            out = (math.cos(am) * dz, math.sin(am) * dz, -dr)
            if prof[k + 1][0] < 1e-6:
                g.poly([a[i], a[j], b[i]], mat, out, smooth)
            elif prof[k][0] < 1e-6:
                g.poly([a[i], b[j], b[i]], mat, out, smooth)
            else:
                g.poly([a[i], a[j], b[j], b[i]], mat, out, smooth)
    if cap_top and prof[-1][0] > 1e-6:
        g.poly(rings[-1], mat, (0, 0, 1))


def bar(g, mat, p0, p1, w, h=None, n=4, ends=False, smooth=False):
    """Bar between two 3D points: square (n=4, w x h section) or round (n>4, diameter w)."""
    h = w if h is None else h
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0)
    if d.length < 1e-6:
        return
    d.normalize()
    ref = Vector((0, 0, 1)) if abs(d.z) < 0.95 else Vector((1, 0, 0))
    s = d.cross(ref).normalized()
    u = s.cross(d).normalized()
    if n == 4:
        offs = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    else:
        offs = [(w / 2 * math.cos(2 * math.pi * i / n), w / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    c = [p0 + s * a + u * b for a, b in offs]
    e = [p1 + s * a + u * b for a, b in offs]
    k = len(offs)
    for i in range(k):
        j = (i + 1) % k
        mid = (c[i] + c[j]) / 2 - p0
        g.poly([c[i], c[j], e[j], e[i]], mat, mid, smooth and n > 4)
    if ends:
        g.poly(c, mat, -d); g.poly(e, mat, d)


class Fr:
    """Wall frame: u along U, z up, d along the outward normal N = U x Z."""

    def __init__(self, O, U):
        self.O = Vector(O); self.U = Vector(U).normalized(); self.N = self.U.cross(Vector((0, 0, 1)))

    def p(self, u, z, d=0.0):
        return self.O + self.U * u + Vector((0, 0, z)) + self.N * d


def sides(x0, x1, y0, y1):
    """Wall frames. u is +x on S, +y on E, -x on N, -y on W. Returns {key: (F, u0, u1, sign)}."""
    return {'S': (Fr((0, y0, 0), (1, 0, 0)), x0, x1, 1), 'E': (Fr((x1, 0, 0), (0, 1, 0)), y0, y1, 1),
            'N': (Fr((0, y1, 0), (-1, 0, 0)), -x1, -x0, -1), 'W': (Fr((x0, 0, 0), (0, -1, 0)), -y1, -y0, -1)}


def fq(g, F, mat, u0, u1, z0, z1, d=0.0):
    g.poly([F.p(u0, z0, d), F.p(u1, z0, d), F.p(u1, z1, d), F.p(u0, z1, d)], mat, F.N)


def fbox(g, F, mat, u0, u1, z0, z1, d0, d1, skip=''):
    """Box in a wall frame (never the back face)."""
    U, Z = F.U, Vector((0, 0, 1))
    fq(g, F, mat, u0, u1, z0, z1, d1)
    if 'l' not in skip:
        g.poly([F.p(u0, z0, d0), F.p(u0, z0, d1), F.p(u0, z1, d1), F.p(u0, z1, d0)], mat, -U)
    if 'r' not in skip:
        g.poly([F.p(u1, z0, d0), F.p(u1, z0, d1), F.p(u1, z1, d1), F.p(u1, z1, d0)], mat, U)
    if 't' not in skip:
        g.poly([F.p(u0, z1, d0), F.p(u1, z1, d0), F.p(u1, z1, d1), F.p(u0, z1, d1)], mat, Z)
    if 'b' not in skip:
        g.poly([F.p(u0, z0, d0), F.p(u1, z0, d0), F.p(u1, z0, d1), F.p(u0, z0, d1)], mat, -Z)


def wall(g, F, u0, u1, z0, z1, holes, mat='Wall'):
    """Rectangular wall with rectangular holes (a, b, c, d) = (u0, u1, z0, z1), split into bands."""
    zs = {z0, z1}
    for a, b, c, d in holes:
        zs.add(min(max(c, z0), z1)); zs.add(min(max(d, z0), z1))
    zs = sorted(zs)
    for za, zb in zip(zs, zs[1:]):
        if zb - za < 1e-5:
            continue
        hs = sorted([h for h in holes if h[2] <= za + 1e-6 and h[3] >= zb - 1e-6], key=lambda h: h[0])
        u = u0
        for a, b, c, d in hs:
            if a > u + 1e-5:
                fq(g, F, mat, u, a, za, zb)
            u = max(u, b)
        if u1 > u + 1e-5:
            fq(g, F, mat, u, u1, za, zb)


def arch_pts(a, b, zs, n=8):
    r = (b - a) / 2; uc = (a + b) / 2
    return [(uc - r * math.cos(math.pi * i / n), zs + r * math.sin(math.pi * i / n)) for i in range(n + 1)]


def arch_fill(g, F, a, b, zs, mat='Wall', n=8):
    """Wall spandrels between a semicircular arch (spring zs) and its bounding rectangle, plus the arch reveal."""
    r = (b - a) / 2; top = zs + r
    P = arch_pts(a, b, zs, n)
    for (u0, z0), (u1, z1) in zip(P, P[1:]):
        if top - max(z0, z1) > 1e-4 or True:
            g.poly([F.p(u0, z0), F.p(u1, z1), F.p(u1, top), F.p(u0, top)], mat, F.N)
    return P


def window(g, F, a, b, c, d, rd=0.1, cw=0.09, cp=0.035, rail=True, mull=0, sill=True, head=0.13,
           shutters=False, arch=False, T='Trim', glassmat='Glass', wallmat='Wall', lintel=None):
    """Recessed window in a wall hole (a..b, c..d). arch=True: the top is a half circle springing at d - r."""
    U, Z = F.U, Vector((0, 0, 1))
    if arch:
        r = (b - a) / 2; zs = d - r
        P = arch_fill(g, F, a, b, zs, wallmat)
        # reveal: jambs up to spring, then arch strips
        g.poly([F.p(a, c, 0), F.p(a, c, -rd), F.p(a, zs, -rd), F.p(a, zs, 0)], wallmat, U)
        g.poly([F.p(b, c, 0), F.p(b, c, -rd), F.p(b, zs, -rd), F.p(b, zs, 0)], wallmat, -U)
        for (u0, z0), (u1, z1) in zip(P, P[1:]):
            g.poly([F.p(u0, z0, 0), F.p(u1, z1, 0), F.p(u1, z1, -rd), F.p(u0, z0, -rd)], wallmat, F.p((a + b) / 2, zs, 0) - F.p((u0 + u1) / 2, (z0 + z1) / 2, 0))
        g.poly([F.p(a, c, -rd)] + [F.p(u, z, -rd) for u, z in P] + [F.p(b, c, -rd)], glassmat, F.N)
        # brick or stone arch ring
        if lintel:
            for (u0, z0), (u1, z1) in zip(P, P[1:]):
                k0 = Vector((u0 - (a + b) / 2, z0 - zs)).normalized(); k1 = Vector((u1 - (a + b) / 2, z1 - zs)).normalized()
                w = 0.22
                g.poly([F.p(u0, z0, 0.02), F.p(u1, z1, 0.02), F.p(u1 + k1.x * w, z1 + k1.y * w, 0.02), F.p(u0 + k0.x * w, z0 + k0.y * w, 0.02)], lintel, F.N)
        if rail:
            fbox(g, F, T, a, b, zs - 0.03, zs + 0.03, -rd, -rd + 0.035, skip='lr')
        for k in range(1, mull + 1):
            um = a + (b - a) * k / (mull + 1)
            fbox(g, F, T, um - 0.04, um + 0.04, c, zs + r * math.sin(math.acos(min(1, abs(um - (a + b) / 2) / r))) - 0.02, -rd, -rd + 0.04, skip='tb')
    else:
        fq(g, F, T, a - cw, a, c, d, cp)
        fq(g, F, T, b, b + cw, c, d, cp)
        g.poly([F.p(a - cw, c, 0), F.p(a - cw, c, cp), F.p(a - cw, d + head, cp), F.p(a - cw, d + head, 0)], T, -U)
        g.poly([F.p(b + cw, c, 0), F.p(b + cw, c, cp), F.p(b + cw, d + head, cp), F.p(b + cw, d + head, 0)], T, U)
        if lintel:
            fbox(g, F, lintel, a - cw - 0.05, b + cw + 0.05, d, d + head + 0.08, 0, cp + 0.02)
        else:
            fq(g, F, T, a - cw, b + cw, d, d + head, cp)
            g.poly([F.p(a - cw, d + head, 0), F.p(b + cw, d + head, 0), F.p(b + cw, d + head, cp + 0.01), F.p(a - cw, d + head, cp + 0.01)], T, Z)
        g.poly([F.p(a, c, cp), F.p(a, c, -rd), F.p(a, d, -rd), F.p(a, d, cp)], T, U)
        g.poly([F.p(b, c, cp), F.p(b, c, -rd), F.p(b, d, -rd), F.p(b, d, cp)], T, -U)
        g.poly([F.p(a, d, cp), F.p(b, d, cp), F.p(b, d, -rd), F.p(a, d, -rd)], T, -Z)
        g.poly([F.p(a, c, 0.0), F.p(b, c, 0.0), F.p(b, c, -rd), F.p(a, c, -rd)], T, Z)
        fq(g, F, glassmat, a, b, c, d, -rd)
        if rail:
            zm = c + (d - c) * 0.52
            fbox(g, F, T, a, b, zm - 0.03, zm + 0.03, -rd, -rd + 0.035, skip='lr')
        for k in range(1, mull + 1):
            um = a + (b - a) * k / (mull + 1)
            fbox(g, F, T, um - 0.035, um + 0.035, c, d, -rd, -rd + 0.04, skip='tb')
    if sill:
        fbox(g, F, T if sill is True else sill, a - cw - 0.04, b + cw + 0.04, c - 0.06, c, 0.0, 0.065)
    if shutters:
        sw = min(0.55, (b - a) / 2 + 0.02)
        top = d if not arch else d - (b - a) / 2
        for u0, u1 in ((a - cw - 0.02 - sw, a - cw - 0.02), (b + cw + 0.02, b + cw + 0.02 + sw)):
            fbox(g, F, shutters if isinstance(shutters, str) else 'Door', u0, u1, c, top + 0.05, 0.0, 0.035)


def door(g, F, a, b, c, d, cw=0.1, cp=0.04, rd=0.14, lite=False, transom=0.0, T='Trim', D='Door', pair=False, glassmat='Glass'):
    U, Z = F.U, Vector((0, 0, 1))
    top = d + transom
    fq(g, F, T, a - cw, a, c, top, cp)
    fq(g, F, T, b, b + cw, c, top, cp)
    fq(g, F, T, a - cw, b + cw, top, top + 0.15, cp)
    g.poly([F.p(a - cw, c, 0), F.p(a - cw, c, cp), F.p(a - cw, top + 0.15, cp), F.p(a - cw, top + 0.15, 0)], T, -U)
    g.poly([F.p(b + cw, c, 0), F.p(b + cw, c, cp), F.p(b + cw, top + 0.15, cp), F.p(b + cw, top + 0.15, 0)], T, U)
    g.poly([F.p(a - cw, top + 0.15, 0), F.p(b + cw, top + 0.15, 0), F.p(b + cw, top + 0.15, cp + 0.015), F.p(a - cw, top + 0.15, cp + 0.015)], T, Z)
    g.poly([F.p(a, c, cp), F.p(a, c, -rd), F.p(a, top, -rd), F.p(a, top, cp)], T, U)
    g.poly([F.p(b, c, cp), F.p(b, c, -rd), F.p(b, top, -rd), F.p(b, top, cp)], T, -U)
    g.poly([F.p(a, top, cp), F.p(b, top, cp), F.p(b, top, -rd), F.p(a, top, -rd)], T, -Z)
    g.poly([F.p(a, c + 0.02, 0.02), F.p(b, c + 0.02, 0.02), F.p(b, c + 0.02, -rd), F.p(a, c + 0.02, -rd)], T, Z)
    fq(g, F, D, a, b, c, d, -rd)
    if pair:
        um = (a + b) / 2
        fbox(g, F, T, um - 0.015, um + 0.015, c, d, -rd, -rd + 0.02, skip='tb')
    if lite:
        m = 0.12
        if pair:
            um = (a + b) / 2
            for u0, u1 in ((a + m, um - m), (um + m, b - m)):
                fq(g, F, glassmat, u0, u1, c + (d - c) * 0.45, d - m, -rd + 0.006)
        else:
            fq(g, F, glassmat, a + m, b - m, c + (d - c) * 0.55, d - m, -rd + 0.006)
    if transom:
        fq(g, F, glassmat, a, b, d, top, -rd)
        fbox(g, F, T, a, b, d - 0.02, d + 0.04, -rd, -rd + 0.04, skip='lr')


def body(g, x0, x1, y0, y1, fz, zp, ops, wmat='Wall', found='Masonry', corners=True, fdepth=ZF, skip_walls='', found_out=0.04):
    """Walls fz..zp with openings and a foundation below.
    ops[side] = list of (kind 'w'|'d'|'a' (arched window), center along the world axis, width, z0, z1, kwargs)."""
    if found:
        box(g, found, x0 - found_out, x1 + found_out, y0 - found_out, y1 + found_out, fdepth, fz + 0.02, skip='b')
    for key, (F, u0, u1, sgn) in sides(x0, x1, y0, y1).items():
        if key in skip_walls:
            continue
        holes, items = [], []
        for op in ops.get(key, []):
            kind, cpos, w, za, zb = op[:5]
            kw = op[5] if len(op) > 5 else {}
            uc = cpos * sgn
            a, b = uc - w / 2, uc + w / 2
            holes.append((a, b, za, zb + kw.get('transom', 0.0)))
            items.append((kind, a, b, za, zb, kw))
        wall(g, F, u0, u1, fz, zp, holes, wmat)
        for kind, a, b, za, zb, kw in items:
            if kind == 'w':
                window(g, F, a, b, za, zb, wallmat=wmat, **kw)
            elif kind == 'a':
                window(g, F, a, b, za, zb, arch=True, wallmat=wmat, **kw)
            else:
                door(g, F, a, b, za, zb, **kw)
    if corners:
        k, o = 0.10, 0.025
        for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            sx = 1 if cx == x0 else -1; sy = 1 if cy == y0 else -1
            xa, xb = sorted((cx - sx * o, cx + sx * k)); ya, yb = sorted((cy - sy * o, cy + sy * k))
            box(g, 'Trim' if corners is True else corners, xa, xb, ya, yb, fz, zp, skip='tb')


FH, TH = 0.2, 0.08   # fascia height, roof slab thickness


def roof_gable(g, cx, cy, L, S, zp, pitch, axis='y', ov=0.4, rake=0.3, wmat='Wall', ends=(True, True),
               rmat='Roof', T='Trim', ridge_cap=True, soffit=True):
    """Gable roof over an L (ridge direction) by S (span) wall rectangle, plate at zp.
    axis 'y': ridge along y (end 0 = front gable at -y). Returns the ridge height (top)."""
    tn = math.tan(math.radians(pitch))
    hs = S / 2
    zr = zp + hs * tn            # underside at the ridge line
    th = TH / math.cos(math.radians(pitch))

    def P(c, a, z):
        return (cx + c, cy + a, z) if axis == 'y' else (cx + a, cy + c, z)

    A0, A1 = -L / 2 - rake, L / 2 + rake
    ce = hs + ov
    ze = zp - ov * tn
    for s in (-1, 1):
        out = P(s * 1, 0, 1)
        out = (out[0] - cx, out[1] - cy, 1) if axis == 'y' else (out[0] - cx, out[1] - cy, 1)
        nrm = (s, 0, 1 / max(tn, 1e-3)) if axis == 'y' else (0, s, 1 / max(tn, 1e-3))
        # top slope
        g.poly([P(s * ce, A0, ze + th), P(s * ce, A1, ze + th), P(0, A1, zr + th), P(0, A0, zr + th)], rmat, nrm)
        # underside
        dn = (-nrm[0], -nrm[1], -nrm[2])
        g.poly([P(s * ce, A0, ze), P(s * ce, A1, ze), P(0, A1, zr), P(0, A0, zr)], T, dn)
        # fascia
        fn = (s, 0, 0) if axis == 'y' else (0, s, 0)
        g.poly([P(s * ce, A0, ze - 0.06), P(s * ce, A1, ze - 0.06), P(s * ce, A1, ze + th + 0.01), P(s * ce, A0, ze + th + 0.01)], T, fn)
        # rake boards at both ends
        for a, e in ((A0, -1), (A1, 1)):
            en = (0, e, 0) if axis == 'y' else (e, 0, 0)
            g.poly([P(s * ce, a, ze - 0.06), P(0, a, zr - 0.06), P(0, a, zr + th + 0.01), P(s * ce, a, ze + th + 0.01)], T, en)
    # gable end walls
    for a, e, on in ((-L / 2, -1, ends[0]), (L / 2, 1, ends[1])):
        if on:
            en = (0, e, 0) if axis == 'y' else (e, 0, 0)
            g.poly([P(-hs, a, zp), P(hs, a, zp), P(0, a, zr)], wmat, en)
    if ridge_cap:
        w = 0.14
        for s in (-1, 1):
            nrm = (s, 0, 1) if axis == 'y' else (0, s, 1)
            g.poly([P(0, A0, zr + th + 0.04), P(0, A1, zr + th + 0.04), P(s * w, A1, zr + th - w * tn + 0.005), P(s * w, A0, zr + th - w * tn + 0.005)], rmat, nrm)
    return zr + th + 0.04


def roof_hip(g, cx, cy, w, d, zp, pitch, ov=0.45, rmat='Roof', T='Trim'):
    """Hip roof over a w (x) by d (y) wall rectangle with its plate at zp; boxed soffit and fascia.
    Returns the ridge height."""
    tn = math.tan(math.radians(pitch))
    W, D = w + 2 * ov, d + 2 * ov
    ze = zp - ov * tn * 0.35          # boxed eave: fascia bottom a little under the plate
    th = TH / math.cos(math.radians(pitch))
    z0 = zp + 0.0
    if W >= D:
        rise = D / 2 * tn; rl = (W - D) / 2
        r0, r1 = (cx - rl, cy, z0 + rise + th), (cx + rl, cy, z0 + rise + th)
    else:
        rise = W / 2 * tn; rl = (D - W) / 2
        r0, r1 = (cx, cy - rl, z0 + rise + th), (cx, cy + rl, z0 + rise + th)
    c = [(cx - W / 2, cy - D / 2, z0 + th), (cx + W / 2, cy - D / 2, z0 + th), (cx + W / 2, cy + D / 2, z0 + th), (cx - W / 2, cy + D / 2, z0 + th)]
    if W >= D:
        g.poly([c[0], c[1], r1, r0], rmat, (0, -1, 1)); g.poly([c[2], c[3], r0, r1], rmat, (0, 1, 1))
        g.poly([c[1], c[2], r1], rmat, (1, 0, 1)); g.poly([c[3], c[0], r0], rmat, (-1, 0, 1))
    else:
        g.poly([c[1], c[2], r1, r0], rmat, (1, 0, 1)); g.poly([c[3], c[0], r0, r1], rmat, (-1, 0, 1))
        g.poly([c[0], c[1], r0], rmat, (0, -1, 1)); g.poly([c[2], c[3], r1], rmat, (0, 1, 1))
    # fascia band and flat boxed soffit
    box(g, T, cx - W / 2, cx + W / 2, cy - D / 2, cy + D / 2, ze, z0 + th, skip='tb')
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2
    X0, X1, Y0, Y1 = cx - W / 2, cx + W / 2, cy - D / 2, cy + D / 2
    for q in ([(X0, Y0), (X1, Y0), (x1, y0), (x0, y0)], [(X1, Y0), (X1, Y1), (x1, y1), (x1, y0)],
              [(X1, Y1), (X0, Y1), (x0, y1), (x1, y1)], [(X0, Y1), (X0, Y0), (x0, y0), (x0, y1)]):
        g.poly([(p[0], p[1], ze) for p in q], T, (0, 0, -1))
    return z0 + rise + th


def stairs(g, mat, x0, x1, y_front, y_back, z_top, n, cheeks=None, axis='y', sign=-1):
    """Straight run of n risers from grade to z_top. The run goes from y_back (top) toward y_front (-y)."""
    rh = z_top / n
    depth = abs(y_back - y_front)
    tr = depth / n
    for i in range(n):
        zt = z_top - i * rh
        ya = y_back - i * tr * (1 if y_front < y_back else -1)
        yb = y_back - (i + 1) * tr * (1 if y_front < y_back else -1)
        lo, hi = sorted((yb, y_back))
        box(g, mat, x0, x1, lo, hi, ZF if i == n - 1 else zt - rh - 0.02, zt, skip='bn')
    if cheeks:
        cw = cheeks
        for xa, xb in ((x0 - cw, x0), (x1, x1 + cw)):
            g.poly([(xa, y_front, ZF), (xa, y_back, ZF), (xa, y_back, z_top + 0.1), (xa, y_front, 0.25)], mat, (-1, 0, 0))
            g.poly([(xb, y_front, ZF), (xb, y_back, ZF), (xb, y_back, z_top + 0.1), (xb, y_front, 0.25)], mat, (1, 0, 0))
            g.poly([(xa, y_front, 0.25), (xb, y_front, 0.25), (xb, y_back, z_top + 0.1), (xa, y_back, z_top + 0.1)], mat, (0, 0, 1))
            g.poly([(xa, y_front, ZF), (xb, y_front, ZF), (xb, y_front, 0.25), (xa, y_front, 0.25)], mat, (0, -1, 0))


def railing(g, mat, pts, z0, h=0.95, post=0.09, spacing=1.8, rail=0.07, balusters=0, mid=True):
    """Posts and rails along a polyline at deck height z0. balusters = spacing (m) of thin pickets, 0 = none."""
    for a, b in zip(pts, pts[1:]):
        a = Vector((a[0], a[1], z0)); b = Vector((b[0], b[1], z0))
        L = (b - a).length
        n = max(1, int(round(L / spacing)))
        for i in range(n + 1):
            p = a + (b - a) * (i / n)
            cbox(g, mat, p.x, p.y, post, post, z0, z0 + h + 0.04, skip='b')
        up = Vector((0, 0, 1))
        bar(g, mat, a + up * (h - rail / 2), b + up * (h - rail / 2), rail * 1.4, rail)
        if mid:
            bar(g, mat, a + up * 0.12, b + up * 0.12, rail, rail * 0.8)
        if balusters:
            m = max(1, int(L / balusters))
            for i in range(1, m):
                p = a + (b - a) * (i / m)
                bar(g, mat, p + up * 0.12, p + up * (h - rail), 0.035, 0.035)


# ============================================================================ materials

def small_normal(tex, n=512):
    alb, nrm, tile = tex
    im = Image.open(nrm)
    if im.size[0] > n:
        im.resize((n, n), Image.LANCZOS).save(nrm, quality=90)
    return alb, nrm, tile


def make_materials(wall='siding', roof='shingle', masonry='brick'):
    M = {}
    if wall == 'siding':
        t = wp.tex_siding('misc_siding', color='#f3f2ef', n=512, tile=1.0, seed=21)
    elif wall == 'vertical':
        t = wp.tex_siding('misc_t111', color='#f1f0ec', exposure=0.2, n=512, tile=1.2, seed=22, vertical=True)
    elif wall == 'boards':
        t = wp.tex_siding('misc_bnb', color='#efeeea', exposure=0.3, n=512, tile=1.2, seed=23, vertical=True)
    elif wall == 'metal':
        t = wp.tex_metal('misc_wallmetal', color='#efefed', n=512, tile=1.0, rib=0.23, seed=24)
    else:  # stucco / painted block
        t = wp.tex_ground('misc_stucco', kind='stucco', color='#f1efe9', n=512, tile=2.0, seed=25)
    M['Wall'] = wp.mat('Wall', '#ffffff', rough=0.8 if wall != 'metal' else 0.5, metal=0.0 if wall != 'metal' else 0.3,
                       normal_strength=0.8, tex=small_normal(t))
    if roof == 'metal':
        rt = wp.tex_metal('misc_roofmetal', color='#e6e7e6', n=512, tile=1.8, seam=True, seed=26)
        M['Roof'] = wp.mat('Roof', '#ffffff', rough=0.42, metal=0.35, normal_strength=0.9, tex=small_normal(rt))
    elif roof == 'corrugated':
        rt = wp.tex_metal('misc_roofcorr', color='#e8e8e6', n=512, tile=1.0, rib=0.076, seed=27)
        M['Roof'] = wp.mat('Roof', '#ffffff', rough=0.45, metal=0.35, normal_strength=0.9, tex=small_normal(rt))
    else:
        rt = wp.tex_shingles('misc_shingle', color='#ececea', n=512, tile=2.0, seed=28)
        M['Roof'] = wp.mat('Roof', '#ffffff', rough=0.88, normal_strength=0.9, tex=small_normal(rt))
    M['Trim'] = wp.mat('Trim', '#f1f0eb', rough=0.5)
    M['Glass'] = wp.glass('Glass', tint='#2b3238')
    M['Door'] = wp.mat('Door', '#f2f2f0', rough=0.45)
    if masonry == 'brick':
        mt = wp.tex_brick('misc_brick', color='#8e4e3a', mortar='#b4ab9c', n=512, tile=1.0, seed=29)
    else:
        mt = wp.tex_ground('misc_concrete', kind='concrete', color='#b5b1a8', n=512, tile=2.0, seed=30)
    M['Masonry'] = wp.mat('Masonry', '#ffffff', rough=0.86, normal_strength=0.9, tex=small_normal(mt))
    return M


# ============================================================================ archetypes

def b_shed(g):
    """3 x 4 prefab wood storage shed: T1-11 siding, front-gable double doors, on concrete blocks."""
    x0, x1, y0, y1 = -1.3, 1.3, -1.8, 1.8
    fz, zp = 0.25, 2.2
    # concrete block piers under a treated skid rim
    for x in (x0 + 0.12, 0, x1 - 0.12):
        for y in (y0 + 0.15, 0, y1 - 0.15):
            cbox(g, 'Masonry', x, y, 0.2, 0.4, ZF, 0.12)
    box(g, 'Trim', x0, x1, y0, y1, 0.12, fz, skip='b')
    ops = {'S': [('d', 0, 1.5, fz, fz + 1.85, dict(pair=True, cw=0.1, rd=0.04))],
           'E': [('w', 0.2, 0.6, 1.2, 1.75, dict(rail=False, mull=1, rd=0.05))]}
    body(g, x0, x1, y0, y1, fz, zp, ops, found=None)
    # X braces on the doors
    F = sides(x0, x1, y0, y1)['S'][0]
    for u0, u1 in ((-0.75, 0.0), (0.0, 0.75)):
        bar(g, 'Trim', F.p(u0 + 0.08, fz + 0.12, -0.01), F.p(u1 - 0.08, fz + 1.73, -0.01), 0.09, 0.025)
        fbox(g, F, 'Trim', u0 + 0.02, u1 - 0.02, fz + 0.85, fz + 0.95, -0.04, -0.01, skip='')
    top = roof_gable(g, 0, 0, 3.6, 2.6, zp, 26, axis='y', ov=0.2, rake=0.2, soffit=False)
    # gable vent
    fbox(g, F, 'Trim', -0.22, 0.22, zp + 0.18, zp + 0.42, 0, 0.03)
    fq(g, F, 'Glass', -0.17, 0.17, zp + 0.22, zp + 0.38, 0.035)
    return dict(stories=1, kinds=['shed'], style='prefab wood storage shed, front gable, T1-11 siding, double doors, on concrete blocks',
                hoods=['everywhere'], wall='vertical', roof='shingle', masonry='concrete')


def b_shed_metal(g):
    """6 x 8 steel workshop / garage on a slab: corrugated walls, roll-up door, low gable."""
    x0, x1, y0, y1 = -2.85, 2.85, -3.85, 3.85
    fz, zp = 0.1, 2.75
    box(g, 'Masonry', x0 - 0.05, x1 + 0.05, y0 - 0.05, y1 + 0.05, ZF, fz, skip='b')
    ops = {'S': [('d', 0.0, 3.0, fz, 2.55, dict(cw=0.08, rd=0.12))],
           'E': [('d', 2.2, 0.9, fz, 2.13, dict(rd=0.08)), ('w', -1.0, 1.0, 1.2, 1.95, dict(rail=False, mull=1, rd=0.06))],
           'W': [('w', 0.5, 1.0, 1.2, 1.95, dict(rail=False, mull=1, rd=0.06))]}
    body(g, x0, x1, y0, y1, fz, zp, ops, found=None)
    F = sides(x0, x1, y0, y1)['S'][0]
    for k in range(1, 8):   # roll-up door ribs
        z = fz + (2.55 - fz) * k / 8
        fbox(g, F, 'Door', -1.5, 1.5, z - 0.02, z + 0.02, -0.12, -0.1, skip='lr')
    roof_gable(g, 0, 0, 7.7, 5.7, zp, 12.5, axis='y', ov=0.15, rake=0.15, soffit=False)
    return dict(stories=1, kinds=['shed'], style='steel workshop / garage on a slab, corrugated walls, roll-up door, low gable',
                hoods=['everywhere'], wall='metal', roof='corrugated', masonry='concrete')


def b_barn(g):
    """12 x 18 pole barn: board-and-batten, metal roof, front sliding doors, hay door, ridge cupola."""
    x0, x1, y0, y1 = -5.7, 5.7, -8.7, 8.7
    fz, zp = 0.15, 3.25
    box(g, 'Masonry', x0 - 0.04, x1 + 0.04, y0 - 0.04, y1 + 0.04, ZF, fz, skip='b')
    ops = {'S': [('d', 0.0, 3.6, fz, 2.95, dict(cw=0.12, rd=0.1, pair=True))],
           'N': [('d', 0.0, 3.0, fz, 3.0, dict(cw=0.12, rd=0.1, pair=True))],
           'E': [('w', y, 0.9, 1.9, 2.6, dict(rail=False, mull=1, rd=0.08)) for y in (-5.0, 0.0, 5.0)] + [('d', 7.2, 0.9, fz, 2.2, dict(rd=0.08))],
           'W': [('w', y, 0.9, 1.9, 2.6, dict(rail=False, mull=1, rd=0.08)) for y in (-5.0, 0.0, 5.0)]}
    body(g, x0, x1, y0, y1, fz, zp, ops, found=None)
    F = sides(x0, x1, y0, y1)['S'][0]
    # sliding door track, Z bracing
    fbox(g, F, 'Trim', -3.7, 3.7, 3.1, 3.22, 0, 0.12)
    for u0, u1 in ((-1.8, 0.0), (0.0, 1.8)):
        bar(g, 'Trim', F.p(u0 + 0.1, fz + 0.15, 0.0), F.p(u1 - 0.1, 2.8, 0.0), 0.14, 0.04)
        fbox(g, F, 'Trim', u0 + 0.05, u1 - 0.05, 1.65, 1.8, -0.02, 0.03)
    # hay door in the front gable
    fbox(g, F, 'Door', -0.65, 0.65, 3.55, 4.6, 0, 0.05)
    fbox(g, F, 'Trim', -0.75, 0.75, 4.6, 4.7, 0, 0.08)
    bar(g, 'Trim', F.p(-0.6, 3.6, 0.05), F.p(0.6, 4.55, 0.05), 0.12, 0.03)
    top = roof_gable(g, 0, 0, 17.4, 11.4, zp, 18, axis='y', ov=0.3, rake=0.3)
    # ridge vent cupola
    zr = top - 0.06
    cbox(g, 'Wall', 0, 0, 1.2, 1.2, zr - 0.5, zr + 0.45, skip='b')
    for s in ('S', 'E', 'N', 'W'):
        Fc = sides(-0.6, 0.6, -0.6, 0.6)[s][0]
        for k in range(3):
            fq(g, Fc, 'Glass', -0.42, 0.42, zr + 0.04 + k * 0.12, zr + 0.1 + k * 0.12, 0.005)
    tn = math.tan(math.radians(30))
    g.poly([(-0.8, -0.8, zr + 0.6), (0.8, -0.8, zr + 0.6), (0, 0, zr + 0.6 + 0.8 * tn)], 'Roof', (0, -1, 1))
    g.poly([(0.8, -0.8, zr + 0.6), (0.8, 0.8, zr + 0.6), (0, 0, zr + 0.6 + 0.8 * tn)], 'Roof', (1, 0, 1))
    g.poly([(0.8, 0.8, zr + 0.6), (-0.8, 0.8, zr + 0.6), (0, 0, zr + 0.6 + 0.8 * tn)], 'Roof', (0, 1, 1))
    g.poly([(-0.8, 0.8, zr + 0.6), (-0.8, -0.8, zr + 0.6), (0, 0, zr + 0.6 + 0.8 * tn)], 'Roof', (-1, 0, 1))
    return dict(stories=1, kinds=['barn'], style='pole barn, board-and-batten, metal roof, sliding doors, ridge cupola',
                hoods=['rural', 'outside the limits'], wall='boards', roof='metal', masonry='concrete')


def b_church_brick(g):
    """14 x 28 brick church: gable nave with arched windows and pilasters, a brick tower with a white
    belfry and spire to 28 m on the front, brick entry steps."""
    x0, x1, y0, y1 = -6.6, 6.6, -10.0, 13.6
    fz, zp = 0.9, 6.0
    arch = dict(rail=False, mull=1, rd=0.18, sill='Trim', lintel='Trim')
    ops = {'E': [('a', y, 1.25, 1.9, 5.2, arch) for y in (-6.8, -3.0, 0.8, 4.6, 8.4)],
           'W': [('a', y, 1.25, 1.9, 5.2, arch) for y in (-6.8, -3.0, 0.8, 4.6, 8.4)],
           'S': [('a', x, 1.1, 2.2, 5.0, arch) for x in (-4.4, 4.4)],
           'N': [('a', 0.0, 2.0, 2.2, 5.6, dict(rail=False, mull=2, rd=0.18, lintel='Trim'))]}
    body(g, x0, x1, y0, y1, fz, zp, ops, wmat='Masonry', found='Masonry', corners=False, found_out=0.06)
    # stone water table and brick pilasters
    box(g, 'Trim', x0 - 0.07, x1 + 0.07, y0 - 0.07, y1 + 0.07, fz - 0.05, fz + 0.12, skip='b')
    for y in (-8.7, -4.9, -1.1, 2.7, 6.5, 10.3, 13.35):
        for x, s in ((x0, -1), (x1, 1)):
            box(g, 'Masonry', *sorted((x, x + s * 0.16)), y - 0.25, y + 0.25, fz + 0.12, zp - 0.05, skip='b')
    # white frieze under the eaves
    box(g, 'Trim', x0 - 0.02, x1 + 0.02, y0 - 0.02, y1 + 0.02, zp - 0.35, zp, skip='tb')
    ridge = roof_gable(g, 0, (y0 + y1) / 2, y1 - y0, x1 - x0, zp, 30, axis='y', ov=0.4, rake=0.35, wmat='Masonry')
    # ---- tower: brick shaft 4.4 x 4.4, front face at y = -12.8
    tx0, tx1, ty0, ty1 = -2.2, 2.2, -12.8, -9.2
    tops = 10.6
    tops_ops = {'S': [('a', 0.0, 1.8, fz, fz + 3.4, dict(rail=False, sill=False, rd=0.3, lintel='Trim', glassmat='Door')),
                      ('a', 0.0, 0.9, 6.2, 8.4, dict(rail=False, mull=0, rd=0.2, lintel='Trim'))],
                'E': [('a', -11.0, 0.8, 5.8, 8.0, dict(rail=False, rd=0.2, lintel='Trim'))],
                'W': [('a', -11.0, 0.8, 5.8, 8.0, dict(rail=False, rd=0.2, lintel='Trim'))]}
    body(g, tx0, tx1, ty0, ty1, fz, tops, tops_ops, wmat='Masonry', found='Masonry', corners=False, skip_walls='N', found_out=0.06)
    box(g, 'Masonry', tx0, tx1, ty0, ty1, ZF, fz, skip='bn')
    box(g, 'Trim', tx0 - 0.07, tx1 + 0.07, ty0 - 0.07, ty1, fz - 0.05, fz + 0.12, skip='bn')
    # door leaves sit in the arched opening (the arch glass uses Door)
    Fs = sides(tx0, tx1, ty0, ty1)['S'][0]
    fbox(g, Fs, 'Trim', -0.02, 0.02, fz, fz + 2.5, -0.3, -0.27)
    # entry steps: 5 risers to the floor at 0.9
    for i in range(5):
        zt = fz - i * 0.18
        box(g, 'Masonry', -1.9 - i * 0.12, 1.9 + i * 0.12, -12.8 - (i + 1) * 0.24, -12.8, ZF, zt, skip='bn')
    # cornice at the top of the brick, white belfry stage, octagonal lantern, spire
    box(g, 'Trim', tx0 - 0.18, tx1 + 0.18, ty0 - 0.18, ty1 + 0.18, tops, tops + 0.35, skip='')
    bx = 1.75; by0, by1 = (ty0 + ty1) / 2 - 1.75, (ty0 + ty1) / 2 + 1.75; cyb = (ty0 + ty1) / 2
    z0, z1 = tops + 0.35, tops + 3.6
    louv = dict(rail=False, sill=False, rd=0.12, T='Trim', glassmat='Glass', lintel=None)
    bops = {k: [('a', 0.0 if k in 'SN' else cyb * (1 if k == 'E' else -1), 1.5, z0 + 0.5, z1 - 0.35, louv)] for k in 'SENW'}
    body(g, -bx, bx, by0, by1, z0, z1, bops, wmat='Trim', found=None, corners=False)
    for cx_, cy_ in ((-bx, by0), (bx, by0), (bx, by1), (-bx, by1)):
        cbox(g, 'Trim', cx_, cy_, 0.4, 0.4, z0, z1, skip='b')
    # louver slats
    for k in 'SENW':
        F = sides(-bx, bx, by0, by1)[k][0]
        uc = 0.0 if k in 'SN' else cyb * (1 if k == 'E' else -1)
        for j in range(6):
            z = z0 + 0.65 + j * 0.3
            fbox(g, F, 'Trim', uc - 0.72, uc + 0.72, z, z + 0.05, -0.1, -0.06, skip='lr')
    box(g, 'Trim', -bx - 0.3, bx + 0.3, by0 - 0.3, by1 + 0.3, z1, z1 + 0.4, skip='')
    ngon(g, 'Trim', 0, cyb, 1.25, z1 + 0.4, z1 + 2.4, n=8, r1=1.25, caps='')
    ngon(g, 'Trim', 0, cyb, 1.5, z1 + 2.4, z1 + 2.7, n=8, r1=1.5, caps='tb')
    ngon(g, 'Trim', 0, cyb, 1.35, z1 + 2.7, 27.6, n=8, r1=0.0, caps='', smooth=False)
    lathe(g, 'Trim', 0, cyb, [(0.06, 27.4), (0.11, 27.6), (0.09, 27.8), (0.02, 28.0)], n=8)
    return dict(stories=1, kinds=['church'], style='brick church, gable nave with arched windows, brick tower with white belfry and spire on the front',
                hoods=['Downtown', 'Garden District', 'Riverside', 'North End'], wall='siding', roof='shingle', masonry='brick',
                body_height_m=round(ridge, 2))


def b_church_frame(g):
    """10 x 20 white clapboard country church: front-gable, tall windows, entry hood, small belfry."""
    x0, x1, y0, y1 = -4.6, 4.6, -9.0, 9.6
    fz, zp = 0.75, 3.75
    win = dict(rail=True, mull=1, rd=0.1, shutters=False)
    ops = {'E': [('w', y, 1.0, 1.5, 3.35, win) for y in (-6.0, -2.0, 2.0, 6.0)],
           'W': [('w', y, 1.0, 1.5, 3.35, win) for y in (-6.0, -2.0, 2.0, 6.0)],
           'S': [('d', 0.0, 1.6, fz, fz + 2.3, dict(pair=True, transom=0.45, rd=0.12)),
                 ('w', -2.7, 0.9, 1.6, 3.3, win), ('w', 2.7, 0.9, 1.6, 3.3, win)],
           'N': [('w', 0.0, 1.2, 1.7, 3.2, win)]}
    body(g, x0, x1, y0, y1, fz, zp, ops, found='Masonry')
    ridge = roof_gable(g, 0, (y0 + y1) / 2, y1 - y0, x1 - x0, zp, 33, axis='y', ov=0.4, rake=0.3)
    # front gable round vent
    F = sides(x0, x1, y0, y1)['S'][0]
    fbox(g, F, 'Trim', -0.45, 0.45, zp + 0.8, zp + 1.6, 0, 0.04)
    for j in range(4):
        fq(g, F, 'Glass', -0.34, 0.34, zp + 0.88 + j * 0.17, zp + 0.98 + j * 0.17, 0.045)
    # entry hood on brackets, steps
    hz = fz + 2.85
    box(g, 'Trim', -1.4, 1.4, y0 - 1.0, y0, hz - 0.12, hz, skip='')
    g.poly([(-1.5, y0 - 1.1, hz), (0, y0 - 1.1, hz + 0.7), (0, y0, hz + 0.7), (-1.5, y0, hz)], 'Roof', (-1, 0, 1))
    g.poly([(1.5, y0 - 1.1, hz), (0, y0 - 1.1, hz + 0.7), (0, y0, hz + 0.7), (1.5, y0, hz)], 'Roof', (1, 0, 1))
    g.poly([(-1.4, y0 - 1.0, hz), (1.4, y0 - 1.0, hz), (0, y0 - 1.0, hz + 0.62)], 'Trim', (0, -1, 0))
    for x in (-1.25, 1.25):
        bar(g, 'Trim', (x, y0 - 0.02, hz - 0.9), (x, y0 - 0.9, hz - 0.12), 0.1, 0.1)
    for i in range(4):
        zt = fz - i * 0.19
        box(g, 'Masonry', -1.3, 1.3, y0 - (i + 1) * 0.28 - 0.0, y0, ZF, zt, skip='bn')
    # belfry on the front of the ridge
    cy = y0 + 1.2
    zb = ridge - 0.3
    base_top = ridge + 0.2
    cbox(g, 'Wall', 0, cy, 1.6, 1.6, zb - 0.6, base_top, skip='b')
    box(g, 'Trim', -0.9, 0.9, cy - 0.9, cy + 0.9, base_top, base_top + 0.12, skip='')
    for sx in (-0.7, 0.7):
        for sy in (-0.7, 0.7):
            cbox(g, 'Trim', sx, cy + sy, 0.16, 0.16, base_top + 0.12, base_top + 1.1, skip='b')
    cbox(g, 'Glass', 0, cy, 0.9, 0.9, base_top + 0.12, base_top + 1.1, skip='b')
    box(g, 'Trim', -0.95, 0.95, cy - 0.95, cy + 0.95, base_top + 1.1, base_top + 1.25, skip='')
    ztop = base_top + 1.25 + 1.2
    for (a, b, nrm) in (((-0.95, -0.95), (0.95, -0.95), (0, -1, 1)), ((0.95, -0.95), (0.95, 0.95), (1, 0, 1)),
                        ((0.95, 0.95), (-0.95, 0.95), (0, 1, 1)), ((-0.95, 0.95), (-0.95, -0.95), (-1, 0, 1))):
        g.poly([(a[0], cy + a[1], base_top + 1.25), (b[0], cy + b[1], base_top + 1.25), (0, cy, ztop)], 'Roof', nrm)
    lathe(g, 'Trim', 0, cy, [(0.05, ztop - 0.05), (0.08, ztop + 0.1), (0.02, ztop + 0.35)], n=6)
    return dict(stories=1, kinds=['church'], style='white clapboard country church, front gable, entry hood, small belfry',
                hoods=['Riverside', 'South of the river', 'rural', 'North End'], wall='siding', roof='shingle', masonry='brick',
                body_height_m=round(ridge, 2))


def b_apartments(g):
    """40 x 14 three-story garden walk-up: brick ground floor, siding above, two recessed open
    breezeway stairs, balconies with sliders, low hip roof."""
    x0, x1, y0, y1 = -19.5, 19.5, -5.5, 5.5
    fz = 0.3
    f = [fz, fz + 2.8, fz + 5.6, fz + 8.4]
    zp = f[3] + 0.15
    bw = [(-10.2, -6.6), (6.6, 10.2)]  # breezeways (x ranges), recessed through the building front
    # foundation
    box(g, 'Masonry', x0 - 0.04, x1 + 0.04, y0 - 0.04, y1 + 0.04, ZF, fz + 0.02, skip='b')
    # walls: build the long faces in segments around the breezeways
    segs = [(x0, bw[0][0]), (bw[0][1], bw[1][0]), (bw[1][1], x1)]
    Fs = sides(x0, x1, y0, y1)
    rec = 2.2   # breezeway recess depth on the front
    for k in ('S', 'N'):
        F, u0, u1, sgn = Fs[k]
        for xa, xb in segs:
            ua, ub = sorted((xa * sgn, xb * sgn))
            holes, items = [], []
            # windows / sliders per bay on each floor
            nb = 3 if xb - xa > 10 else 2
            for i in range(nb):
                xc = xa + (xb - xa) * (i + 0.5) / nb
                for fl in range(3):
                    if (i % 2 == 0 and k == 'S') or (i % 2 == 1 and k == 'N'):
                        holes.append((xc * sgn - 0.9, xc * sgn + 0.9, f[fl] + 0.05, f[fl] + 2.15)); items.append(('d', xc * sgn, fl))
                    else:
                        holes.append((xc * sgn - 0.75, xc * sgn + 0.75, f[fl] + 0.9, f[fl] + 2.2)); items.append(('w', xc * sgn, fl))
            # brick ground floor, siding above
            wall(g, F, ua, ub, f[0], f[1], [h for h in holes if h[3] <= f[1] + 0.01], 'Masonry')
            wall(g, F, ua, ub, f[1], zp, [h for h in holes if h[2] >= f[1] - 0.01], 'Wall')
            for kind, uc, fl in items:
                if kind == 'w':
                    window(g, F, uc - 0.75, uc + 0.75, f[fl] + 0.9, f[fl] + 2.2, mull=1, rd=0.1, wallmat='Masonry' if fl == 0 else 'Wall')
                else:
                    door(g, F, uc - 0.9, uc + 0.9, f[fl] + 0.05, f[fl] + 2.15, D='Glass', rd=0.12, cw=0.06)
                    if fl > 0:   # balcony slab and railing
                        y = F.p(uc, 0, 0).y
                        s = -1 if k == 'S' else 1
                        ya, yb = sorted((y, y + s * 1.3))
                        xa_, xb_ = uc * sgn - 1.4, uc * sgn + 1.4
                        box(g, 'Trim', xa_, xb_, ya, yb, f[fl] - 0.2, f[fl] - 0.02, skip='')
                        yo = y + s * 1.3
                        za_ = f[fl] - 0.02
                        # picket panels read as a slightly see-through rail: posts, top rail, panel
                        box(g, 'Trim', xa_, xb_, *sorted((yo, yo - s * 0.05)), za_ + 0.12, za_ + 1.0, skip='b')
                        box(g, 'Trim', xa_, xa_ + 0.05, ya, yb, za_ + 0.12, za_ + 1.0, skip='b')
                        box(g, 'Trim', xb_ - 0.05, xb_, ya, yb, za_ + 0.12, za_ + 1.0, skip='b')
                    else:          # ground floor patio slab
                        y = F.p(uc, 0, 0).y; s = -1 if k == 'S' else 1
                        ya, yb = sorted((y, y + s * 1.3))
                        box(g, 'Masonry', uc * sgn - 1.4, uc * sgn + 1.4, ya, yb, 0.0, 0.05, skip='b')
        # belt between brick and siding
        box(g, 'Trim', x0 - 0.04, x1 + 0.04, *sorted((F.p(0, 0, 0).y, F.p(0, 0, 0.04).y)), f[1] - 0.06, f[1] + 0.08, skip='')
    # end walls
    for k in ('E', 'W'):
        F, u0, u1, sgn = Fs[k]
        holes = []; items = []
        for fl in range(3):
            for uc in (-2.6, 2.6):
                holes.append((uc - 0.6, uc + 0.6, f[fl] + 0.9, f[fl] + 2.2)); items.append((uc, fl))
        wall(g, F, u0, u1, f[0], f[1], [h for h in holes if h[3] <= f[1] + 0.01], 'Masonry')
        wall(g, F, u0, u1, f[1], zp, [h for h in holes if h[2] >= f[1] - 0.01], 'Wall')
        for uc, fl in items:
            window(g, F, uc - 0.6, uc + 0.6, f[fl] + 0.9, f[fl] + 2.2, rd=0.1, wallmat='Masonry' if fl == 0 else 'Wall')
    # breezeways: inner walls, landings and stairs, open front and back
    for xa, xb in bw:
        for x, s in ((xa, 1), (xb, -1)):
            g.poly([(x, y0, f[0]), (x, y1, f[0]), (x, y1, zp), (x, y0, zp)], 'Masonry' if False else 'Wall', (s, 0, 0))
        g.poly([(xa, y0, f[0]), (xb, y0, f[0]), (xb, y1, f[0]), (xa, y1, f[0])], 'Masonry', (0, 0, 1))
        box(g, 'Masonry', xa, xb, y0, y1, ZF, f[0], skip='tb')
        # apartment entry doors on the breezeway walls, each floor
        for fl in range(3):
            for x, s in ((xa, 1), (xb, -1)):
                g.poly([(x + s * 0.01, -0.6, f[fl]), (x + s * 0.01, 0.4, f[fl]), (x + s * 0.01, 0.4, f[fl] + 2.05), (x + s * 0.01, -0.6, f[fl] + 2.05)], 'Door', (s, 0, 0))
            if fl > 0:   # landing slab across the back half
                box(g, 'Trim', xa, xb, -1.0, y1, f[fl] - 0.25, f[fl], skip='')
                box(g, 'Trim', xa, xb, -1.05, -1.0, f[fl], f[fl] + 1.0, skip='b')
        # two flights per floor from the front, rising toward the back
        for fl in range(3):
            if fl == 2:
                break
            za, zb_ = f[fl], f[fl + 1]
            n = 16
            run = (y1 - 1.0) - (y0 + 0.4)
            xm = (xa + xb) / 2
            for i in range(n):
                z = za + (zb_ - za) * (i + 1) / n
                ya_ = y0 + 0.4 + run * i / n * 0.55
                yb_ = ya_ + run * 0.55 / n
                box(g, 'Trim', xm - 1.05, xm + 1.05, ya_, yb_ + 0.02, z - 0.05, z, skip='b')
            bar(g, 'Trim', (xm - 1.05, y0 + 0.4, za + 0.9), (xm - 1.05, y0 + 0.4 + run * 0.55, zb_ + 0.9), 0.05, 0.05)
            bar(g, 'Trim', (xm + 1.05, y0 + 0.4, za + 0.9), (xm + 1.05, y0 + 0.4 + run * 0.55, zb_ + 0.9), 0.05, 0.05)
    ridge = roof_hip(g, 0, 0, x1 - x0, y1 - y0, zp, 17, ov=0.5)
    return dict(stories=3, kinds=['apartments'], style='three-story garden walk-up, brick ground floor, siding above, two open breezeway stairs, balconies, low hip roof',
                hoods=['North End', 'Westport Acres', 'Uptown', 'Pinecrest', 'South of the river'], wall='siding', roof='shingle', masonry='brick')


def b_motel(g):
    """36 x 12 two-story strip motel: rooms open onto exterior walkways, end stairs, mansard fascia."""
    L = 33.3
    x0, x1, y0, y1 = -L / 2, L / 2, -3.35, 5.7          # rooms block
    wy = -5.65                                          # walkway front edge
    fz = 0.15
    f = [fz, fz + 2.9, fz + 5.8]
    zp = f[2] - 0.05
    box(g, 'Masonry', x0 - 0.04, x1 + 0.04, y0 - 0.04, y1 + 0.04, ZF, fz, skip='b')
    # ground walkway slab and the upper walkway deck (concrete)
    box(g, 'Masonry', x0 - 0.04, x1 + 0.04, wy, y0, ZF, fz, skip='bn')
    box(g, 'Masonry', x0, x1, wy - 0.05, y0, f[1] - 0.25, f[1], skip='n')
    n = 8
    bay = L / n
    Fs = sides(x0, x1, y0, y1)
    F = Fs['S'][0]
    holes, items = [], []
    for fl in range(2):
        for i in range(n):
            xc = x0 + bay * (i + 0.5)
            dx, wx = xc - 1.1, xc + 0.75
            holes.append((dx - 0.48, dx + 0.48, f[fl], f[fl] + 2.1)); items.append(('d', dx, fl))
            holes.append((wx - 0.85, wx + 0.85, f[fl] + 0.95, f[fl] + 2.2)); items.append(('w', wx, fl))
    wall(g, F, x0, x1, f[0], zp, holes, 'Wall')
    for kind, xc, fl in items:
        if kind == 'd':
            door(g, F, xc - 0.48, xc + 0.48, f[fl], f[fl] + 2.1, rd=0.1, cw=0.06)
        else:
            window(g, F, xc - 0.85, xc + 0.85, f[fl] + 0.95, f[fl] + 2.2, rail=False, mull=1, rd=0.08, sill=False)
            fbox(g, F, 'Trim', xc - 0.38, xc + 0.38, f[fl] + 0.35, f[fl] + 0.75, 0, 0.18)   # PTAC sleeve
            fq(g, F, 'Glass', xc - 0.34, xc + 0.34, f[fl] + 0.4, f[fl] + 0.7, 0.185)
    # back wall: small bathroom windows
    Fn = Fs['N'][0]
    bh = []
    for fl in range(2):
        for i in range(n):
            xc = x0 + bay * (i + 0.5)
            bh.append((-(xc - 1.0) - 0.35, -(xc - 1.0) + 0.35, f[fl] + 1.6, f[fl] + 2.1))
    wall(g, Fn, -x1, -x0, f[0], zp, bh, 'Wall')
    for a, b, c, d in bh:
        window(g, Fn, a, b, c, d, rail=False, rd=0.06, sill=False, head=0.08)
    for k in ('E', 'W'):
        Fk, u0, u1, sgn = Fs[k]
        wall(g, Fk, u0, u1, f[0], zp, [], 'Wall')
    # walkway posts, upper railing and the roof canopy over the upper walkway
    for i in range(n + 1):
        x = x0 + bay * i
        cbox(g, 'Trim', x, wy + 0.15, 0.2, 0.2, fz, f[1] - 0.25, skip='b')
        cbox(g, 'Trim', x, wy + 0.15, 0.16, 0.16, f[1], zp, skip='b')
    railing(g, 'Trim', [(x0, wy + 0.1), (x1, wy + 0.1)], f[1], h=1.05, spacing=bay, balusters=0.16, mid=False)
    # flat roof with a mansard fascia across the front and ends
    box(g, 'Masonry', x0 - 0.25, x1 + 0.25, wy - 0.25, y1 + 0.25, zp, zp + 0.25, skip='')
    mz0, mz1 = zp + 0.25, zp + 1.0
    o = 0.25
    g.poly([(x0 - o, wy - o, mz0), (x1 + o, wy - o, mz0), (x1 - 0.35, wy + 0.35, mz1), (x0 + 0.35, wy + 0.35, mz1)], 'Roof', (0, -1, 0.4))
    for x, s in ((x0 - o, -1), (x1 + o, 1)):
        g.poly([(x, wy - o, mz0), (x, y1 + o, mz0), (x - s * 0.6, y1 + o, mz1), (x - s * 0.6, wy + 0.35, mz1)], 'Roof', (s, 0, 0.4))
    g.poly([(x0 + 0.35, wy + 0.35, mz1), (x1 - 0.35, wy + 0.35, mz1), (x1 - 0.35, y1 + o, mz1), (x0 + 0.35, y1 + o, mz1)], 'Masonry', (0, 0, 1))
    g.poly([(x0 - o, y1 + o, mz0), (x1 + o, y1 + o, mz0), (x1 - 0.35, y1 + o, mz1), (x0 + 0.35, y1 + o, mz1)], 'Wall', (0, 1, 0))
    # exterior stairs against both end walls: rise from the back toward the front, landing at the walkway end
    sw = 1.15
    for s in (-1, 1):
        xs = x1 if s > 0 else x0
        xa, xb = sorted((xs, xs + s * sw))
        box(g, 'Masonry', xa, xb, wy, y0, f[1] - 0.25, f[1], skip='')            # landing
        cbox(g, 'Trim', xs + s * (sw - 0.1), wy + 0.1, 0.16, 0.16, fz, f[1] - 0.25, skip='b')
        nst = 16
        run = 4.6
        for i in range(nst):
            z = f[0] + (f[1] - f[0]) * (i + 1) / nst
            yb_ = y0 + run - run * i / nst
            ya_ = yb_ - run / nst - 0.02
            box(g, 'Masonry', xa, xb, ya_, yb_, z - 0.06, z, skip='b')
        bar(g, 'Masonry', (xs + s * sw / 2, y0 + run, fz - 0.15), (xs + s * sw / 2, y0 + 0.1, f[1] - 0.3), 0.3, 0.25)
        xo = xs + s * (sw - 0.03)
        bar(g, 'Trim', (xo, y0 + run, f[0] + 0.95), (xo, y0, f[1] + 0.95), 0.05, 0.05)
        cbox(g, 'Trim', xo, y0 + run, 0.07, 0.07, f[0], f[0] + 1.0, skip='b')
        railing(g, 'Trim', [(xo, y0), (xo, wy + 0.05)], f[1], h=1.05, spacing=3, balusters=0.16, mid=False)
    return dict(stories=2, kinds=['motel'], style='two-story strip motel, exterior walkway with railing, end stairs, mansard fascia, PTAC units',
                hoods=['Ocean Highway', 'Highway strip'], wall='stucco', roof='shingle', masonry='concrete')


ARCH = [('shed', b_shed), ('shed-metal', b_shed_metal), ('barn', b_barn), ('church-brick', b_church_brick),
        ('church-frame', b_church_frame), ('apartments-garden', b_apartments), ('motel-strip', b_motel)]


def build_one(aid, fn):
    wp.reset()
    g = G()
    info = fn(g)
    x0, x1, y0, y1, z0, z1 = g.bbox()
    g.shift(-(x0 + x1) / 2, -(y0 + y1) / 2)
    x0, x1, y0, y1, z0, z1 = g.bbox()
    M = make_materials(info.get('wall', 'siding'), info.get('roof', 'shingle'), info.get('masonry', 'brick'))
    o = to_object(g, aid, M)
    wp.finalize([o])
    path = os.path.join(OUT, aid + '.glb')
    wp.export_glb(path, [o])
    bb = [round(x1 - x0, 2), round(y1 - y0, 2), round(z1, 2)]
    e = dict(id=aid, file=f'models/archetypes/{aid}.glb', kinds=info['kinds'], bbox_m=bb, stories=info['stories'],
             best_aspect=round(bb[0] / bb[1], 3), neighborhoods=info['hoods'], triangles=wp.tri_count([o]),
             style=info['style'], roof=info.get('roof'), size_kb=round(os.path.getsize(path) / 1024), z_min_m=round(z0, 2))
    if 'body_height_m' in info:
        e['body_height_m'] = info['body_height_m']
        e['note'] = ('bbox_m[2] includes the steeple/belfry; scale height by the Atlas height over body_height_m '
                     '(the nave ridge) rather than over bbox_m[2], or the tower is squashed.')
    print(aid, e['bbox_m'], e['triangles'], 'tris')
    return e


def lineup(out, ids):
    wp.reset()
    x = 0.0
    for aid in ids:
        bpy.ops.import_scene.gltf(filepath=os.path.join(OUT, aid + '.glb'))
        objs = list(bpy.context.selected_objects)
        w = max(o.dimensions.x for o in objs)
        for o in objs:
            o.location.x += x + w / 2
        x += w + 6
    wp.render_rig(samples=int(os.environ.get('WP_SAMPLES', 24)), res=tuple(int(v) for v in os.environ.get('WP_RES', '1600x700').split('x')), threads=2, sun_elev=40, sun_az=200)
    wp.camera((x / 2, -x * 0.62, x * 0.16), (x / 2, 0, 5), lens=35)
    wp.render(out)


if __name__ == '__main__':
    args = sys.argv[1:]
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    entries = []
    idx_path = os.path.join(OUT, 'index-misc.json')
    old = {e['id']: e for e in json.load(open(idx_path))} if os.path.exists(idx_path) else {}
    for aid, fn in ARCH:
        if only and aid not in only:
            if aid in old:
                entries.append(old[aid])
            continue
        entries.append(build_one(aid, fn))
    with open(idx_path, 'w') as fh:
        json.dump(entries, fh, indent=1)
    print('wrote', idx_path)
    if '--lineup' in args:
        lineup(args[args.index('--lineup') + 1], [a for a, _ in ARCH])
