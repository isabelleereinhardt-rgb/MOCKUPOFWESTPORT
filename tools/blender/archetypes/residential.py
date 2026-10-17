"""Residential archetypes for the Westport 3D map (ASSET-SPEC "Archetypes", residential set).

Builds 13 generic houses, duplexes and a townhouse row as low-poly GLBs (<= 3,000 triangles each),
writes models/archetypes/index-residential.json, and renders a lineup and a street scene.

    WP_TEX_DIR=/tmp/somewhere python3 tools/blender/archetypes/residential.py            # everything
    python3 tools/blender/archetypes/residential.py --only house-cape --no-render         # one model
    python3 tools/blender/archetypes/residential.py --renders-only --preview             # quick renders

Conventions: meters, +Z up, street front faces -Y, origin = center of the full XY bounding box
(porches and steps included) at finished grade; foundations, piers and steps run down to z = -0.6.
Materials are exactly Wall, Roof, Trim, Glass, Door, Masonry. Wall and Roof carry near-white or
light-grey textures with shading detail only; the map multiplies Wall, Roof and Door by
per-building colors, so nothing here bakes in a color for them.
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
RENDERS = os.path.join(REPO, 'renders')
ARGS = sys.argv[1:]
PREVIEW = '--preview' in ARGS
Z_FOUND = -0.6

# ============================================================================ materials

def _half_normal(tex, n=512):
    """Keep albedo at its size, store the normal map at n px (the GLB stays small)."""
    alb, nrm, tile = tex
    im = Image.open(nrm)
    if im.size[0] > n:
        im.resize((n, n), Image.LANCZOS).save(nrm, quality=90)
    return alb, nrm, tile


def make_materials(roof='shingle'):
    M = {}
    M['Wall'] = wp.mat('Wall', '#ffffff', rough=0.78, normal_strength=0.8,
                       tex=_half_normal(wp.tex_siding('arch_siding_white', color='#f3f2ef', n=512, tile=1.0, seed=12)))
    if roof == 'metal':
        rt = wp.tex_metal('arch_metal_light', color='#e9e9e7', n=512, tile=1.8, seam=True, seed=14)
        M['Roof'] = wp.mat('Roof', '#ffffff', rough=0.42, metal=0.35, normal_strength=0.9, tex=_half_normal(rt))
    else:
        rt = wp.tex_shingles('arch_shingle_light', color='#ececea', n=512, tile=2.0, seed=13)
        M['Roof'] = wp.mat('Roof', '#ffffff', rough=0.88, normal_strength=0.9, tex=_half_normal(rt))
    M['Trim'] = wp.mat('Trim', '#f1f0eb', rough=0.5)
    M['Glass'] = wp.glass('Glass', tint='#2b3238')
    M['Door'] = wp.mat('Door', '#f2f2f0', rough=0.45)
    M['Masonry'] = wp.mat('Masonry', '#ffffff', rough=0.86, normal_strength=0.9,
                          tex=_half_normal(wp.tex_brick('arch_brick', color='#8e4e3a', mortar='#b4ab9c', n=512, tile=1.0, seed=15)))
    return M


# ============================================================================ mesh builder

def newell(pts):
    n = Vector((0, 0, 0))
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n


class G:
    """Polygon soup with a material per face; becomes one mesh object."""

    def __init__(self):
        self.V, self.F, self.M = [], [], []

    def poly(self, pts, mat, facing=None):
        pts = [Vector(p) for p in pts]
        if facing is not None and newell(pts).dot(Vector(facing)) < 0:
            pts = pts[::-1]
        b = len(self.V)
        self.V.extend(tuple(p) for p in pts)
        self.F.append(tuple(range(b, b + len(pts))))
        self.M.append(mat)

    def tris(self):
        return sum(len(f) - 2 for f in self.F)


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


def taper(g, mat, cx, cy, w0, w1, z0, z1):
    """Square column tapering from w0 (bottom) to w1 (top); sides only."""
    a, b = w0 / 2, w1 / 2
    lo = [(cx - a, cy - a), (cx + a, cy - a), (cx + a, cy + a), (cx - a, cy + a)]
    hi = [(cx - b, cy - b), (cx + b, cy - b), (cx + b, cy + b), (cx - b, cy + b)]
    for i in range(4):
        j = (i + 1) % 4
        mid = ((lo[i][0] + lo[j][0]) / 2 - cx, (lo[i][1] + lo[j][1]) / 2 - cy, 0)
        g.poly([(*lo[i], z0), (*lo[j], z0), (*hi[j], z1), (*hi[i], z1)], mat, mid)
    g.poly([(*hi[0], z1), (*hi[1], z1), (*hi[2], z1), (*hi[3], z1)], mat, (0, 0, 1))


def seg_box(g, mat, p0, p1, w, h, ends=False):
    """Box of section w x h along a segment (p0, p1 are the centers of the top... bottom-center line)."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0).normalized()
    side = d.cross(Vector((0, 0, 1)))
    if side.length < 1e-6:
        side = Vector((1, 0, 0))
    side.normalize()
    up = side.cross(d).normalized()
    s, u = side * (w / 2), up * h
    c = [p0 - s, p0 + s, p0 + s + u, p0 - s + u]
    e = [p1 - s, p1 + s, p1 + s + u, p1 - s + u]
    for i in range(4):
        j = (i + 1) % 4
        mid = (c[i] + c[j]) / 2 - (p0 + u / 2)
        g.poly([c[i], c[j], e[j], e[i]], mat, mid)
    if ends:
        g.poly(c, mat, -d)
        g.poly(e, mat, d)


class Fr:
    """Wall frame: u along U, z up, d along the outward normal N = U x Z."""

    def __init__(self, O, U):
        self.O = Vector(O)
        self.U = Vector(U).normalized()
        self.N = self.U.cross(Vector((0, 0, 1)))

    def p(self, u, z, d=0.0):
        return self.O + self.U * u + Vector((0, 0, z)) + self.N * d


def fq(g, F, mat, u0, u1, z0, z1, d=0.0, facing=None):
    g.poly([F.p(u0, z0, d), F.p(u1, z0, d), F.p(u1, z1, d), F.p(u0, z1, d)], mat, F.N if facing is None else facing)


def fbox(g, F, mat, u0, u1, z0, z1, d0, d1, skip='back'):
    """Box in a wall frame; faces: front (d1), left, right, top, bottom; never the back."""
    U, N, Z = F.U, F.N, Vector((0, 0, 1))
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


def window(g, F, a, b, c, d, shutters=False, mull=0, rail=True, cw=0.09, cp=0.035, rd=0.1, sill='Trim', head=0.13):
    U, N, Z = F.U, F.N, Vector((0, 0, 1))
    T = 'Trim'
    # casing: jambs and head, proud of the wall
    fq(g, F, T, a - cw, a, c, d, cp)
    fq(g, F, T, b, b + cw, c, d, cp)
    fq(g, F, T, a - cw, b + cw, d, d + head, cp)
    g.poly([F.p(a - cw, c, 0), F.p(a - cw, c, cp), F.p(a - cw, d + head, cp), F.p(a - cw, d + head, 0)], T, -U)
    g.poly([F.p(b + cw, c, 0), F.p(b + cw, c, cp), F.p(b + cw, d + head, cp), F.p(b + cw, d + head, 0)], T, U)
    g.poly([F.p(a - cw, d + head, 0), F.p(b + cw, d + head, 0), F.p(b + cw, d + head, cp + 0.01), F.p(a - cw, d + head, cp + 0.01)], T, Z)
    # reveal (jambs, head, stool) into the wall
    g.poly([F.p(a, c, cp), F.p(a, c, -rd), F.p(a, d, -rd), F.p(a, d, cp)], T, U)
    g.poly([F.p(b, c, cp), F.p(b, c, -rd), F.p(b, d, -rd), F.p(b, d, cp)], T, -U)
    g.poly([F.p(a, d, cp), F.p(b, d, cp), F.p(b, d, -rd), F.p(a, d, -rd)], T, -Z)
    g.poly([F.p(a, c, 0.0), F.p(b, c, 0.0), F.p(b, c, -rd), F.p(a, c, -rd)], T, Z)
    fq(g, F, 'Glass', a, b, c, d, -rd)
    if rail:   # meeting rail of a double-hung sash
        zm = c + (d - c) * 0.52
        fbox(g, F, T, a, b, zm - 0.03, zm + 0.03, -rd, -rd + 0.035, skip='lr')
    for k in range(1, mull + 1):
        um = a + (b - a) * k / (mull + 1)
        fbox(g, F, T, um - 0.05, um + 0.05, c, d, -rd, -rd + 0.05, skip='tb')
    if sill:
        fbox(g, F, sill, a - cw - 0.04, b + cw + 0.04, c - 0.06, c, 0.0, 0.065)
    if shutters:
        sw = min(0.55, (b - a) / 2 + 0.02)
        for u0, u1 in ((a - cw - 0.02 - sw, a - cw - 0.02), (b + cw + 0.02, b + cw + 0.02 + sw)):
            fbox(g, F, 'Door', u0, u1, c, d + 0.05, 0.0, 0.035, skip='b')


def door(g, F, a, b, c, d, cw=0.1, cp=0.04, rd=0.14, lite=False, transom=0.0):
    U, N, Z = F.U, F.N, Vector((0, 0, 1))
    T = 'Trim'
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
    fq(g, F, 'Door', a, b, c, d, -rd)
    if lite:
        m = 0.12
        fq(g, F, 'Glass', a + m, b - m, c + (d - c) * 0.6, d - m, -rd + 0.006)
    if transom:
        fq(g, F, 'Glass', a, b, d, top, -rd)
        fbox(g, F, T, a, b, d - 0.02, d + 0.04, -rd, -rd + 0.04, skip='lr')


def flat_window(g, F, a, b, c, d, d0=0.0, louver=False):
    """Surface-mounted window (gables, dormers): trim frame with glass set in front of the wall."""
    fbox(g, F, 'Trim', a - 0.09, b + 0.09, c - 0.09, d + 0.1, d0, d0 + 0.04, skip='b')
    if louver:   # gable vent: horizontal slats read as dark bands
        n = max(2, int((d - c) / 0.12))
        for i in range(n):
            z = c + (d - c) * (i + 0.5) / n
            fq(g, F, 'Glass', a, b, z - 0.03, z + 0.025, d0 + 0.045)
    else:
        fq(g, F, 'Glass', a, b, c, d, d0 + 0.045)
        zm = (c + d) / 2
        fq(g, F, 'Trim', a, b, zm - 0.03, zm + 0.03, d0 + 0.05)


# ============================================================================ house body

def sides(x0, x1, y0, y1):
    """Wall frames and their u ranges. u is +x on S, +y on E, -x on N, -y on W."""
    return {
        'S': (Fr((0, y0, 0), (1, 0, 0)), x0, x1, 1),
        'E': (Fr((x1, 0, 0), (0, 1, 0)), y0, y1, 1),
        'N': (Fr((0, y1, 0), (-1, 0, 0)), -x1, -x0, -1),
        'W': (Fr((x0, 0, 0), (0, -1, 0)), -y1, -y0, -1),
    }


def body(g, x0, x1, y0, y1, fz, zp, ops, wmat='Wall', found='Masonry', corners=True, belt=None,
         fdepth=Z_FOUND, skip_walls=''):
    """Walls fz..zp with openings, foundation below, corner boards and an optional belt course.
    ops[side] = list of ('w'|'d'|'f', center_along_world_axis, width, z0, z1, kwargs)."""
    if found:
        box(g, found, x0 - 0.04, x1 + 0.04, y0 - 0.04, y1 + 0.04, fdepth, fz + 0.02, skip='b')
    for key, (F, u0, u1, sgn) in sides(x0, x1, y0, y1).items():
        if key in skip_walls:
            continue
        holes, items = [], []
        for op in ops.get(key, []):
            kind, cpos, w, za, zb = op[:5]
            kw = op[5] if len(op) > 5 else {}
            uc = cpos * sgn
            a, b = uc - w / 2, uc + w / 2
            if kind in 'wd':
                holes.append((a, b, za, zb + kw.get('transom', 0.0)))
            items.append((kind, a, b, za, zb, kw))
        wall(g, F, u0, u1, fz, zp, holes, wmat)
        for kind, a, b, za, zb, kw in items:
            if kind == 'w':
                window(g, F, a, b, za, zb, **kw)
            elif kind == 'd':
                door(g, F, a, b, za, zb, **kw)
            else:
                flat_window(g, F, a, b, za, zb, **kw)
    if corners and wmat == 'Wall':
        k, o = 0.10, 0.025
        for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            sx = 1 if cx == x0 else -1
            sy = 1 if cy == y0 else -1
            xa, xb = sorted((cx - sx * o, cx + sx * k))
            ya, yb = sorted((cy - sy * o, cy + sy * k))
            box(g, 'Trim', xa, xb, ya, yb, fz, zp, skip='tb')
    if belt:
        box(g, 'Trim', x0 - 0.03, x1 + 0.03, y0 - 0.03, y1 + 0.03, belt, belt + 0.2, skip='b')


# ============================================================================ roofs

FH, TH = 0.2, 0.07   # fascia height, roof slab thickness


def roof_gable(g, cx, cy, L, S, zp, pitch, axis='x', ov=0.4, rake=0.3, walls=(True, True), wmat='Wall',
               soffit=True, ends=(True, True)):
    """Gable roof over an L (ridge direction) by S (span) wall rectangle whose plate (soffit) is at zp.
    axis 'x': ridge along x. axis 'y': ridge along y; end 0 is then the FRONT (-y) gable."""
    tn = math.tan(math.radians(pitch))
    Yw, Xw = S / 2, L / 2
    Yo, Xr = Yw + ov, Xw + rake

    def zb(Y):
        return zp + FH + (Yo - abs(Y)) * tn

    def P(X, Y, z):
        return (cx + X, cy + Y, z) if axis == 'x' else (cx - Y, cy + X, z)

    def Nv(x, y, z):
        return (x, y, z) if axis == 'x' else (-y, x, z)

    for s in (-1, 1):
        g.poly([P(-Xr, s * Yo, zb(Yo) + TH), P(Xr, s * Yo, zb(Yo) + TH), P(Xr, 0, zb(0) + TH), P(-Xr, 0, zb(0) + TH)], 'Roof', Nv(0, s, 1))
        g.poly([P(-Xr, s * Yo, zp + FH), P(Xr, s * Yo, zp + FH), P(Xr, s * Yo, zp + FH + TH), P(-Xr, s * Yo, zp + FH + TH)], 'Roof', Nv(0, s, 0))
        g.poly([P(-Xr, s * Yo, zp), P(Xr, s * Yo, zp), P(Xr, s * Yo, zp + FH), P(-Xr, s * Yo, zp + FH)], 'Trim', Nv(0, s, 0))
        if soffit:
            g.poly([P(-Xw, s * Yw, zp), P(Xw, s * Yw, zp), P(Xw, s * Yo, zp), P(-Xw, s * Yo, zp)], 'Trim', Nv(0, 0, -1))
    for k, sx in enumerate((-1, 1)):
        if not ends[k]:
            continue
        for s in (-1, 1):
            g.poly([P(sx * Xr, s * Yo, zb(Yo)), P(sx * Xr, s * Yo, zb(Yo) + TH), P(sx * Xr, 0, zb(0) + TH), P(sx * Xr, 0, zb(0))], 'Roof', Nv(sx, 0, 0))
            g.poly([P(sx * Xr, s * Yo, zp), P(sx * Xr, s * Yo, zb(Yo)), P(sx * Xr, 0, zb(0)), P(sx * Xr, 0, zb(0) - FH)], 'Trim', Nv(sx, 0, 0))
            g.poly([P(sx * Xw, s * Yo, zp), P(sx * Xr, s * Yo, zp), P(sx * Xr, 0, zb(0) - FH), P(sx * Xw, 0, zb(0) - FH)], 'Trim', Nv(0, 0, -1))
            if soffit:
                g.poly([P(sx * Xw, s * Yw, zp), P(sx * Xw, s * Yo, zp), P(sx * Xw, s * Yw, zb(Yw) - FH)], 'Trim', Nv(sx, 0, 0))
        if walls[k]:
            g.poly([P(sx * Xw, -Yw, zp), P(sx * Xw, Yw, zp), P(sx * Xw, Yw, zb(Yw) - FH), P(sx * Xw, 0, zb(0) - FH), P(sx * Xw, -Yw, zb(Yw) - FH)], wmat, Nv(sx, 0, 0))
    return zb(0) + TH   # ridge top


def gable_z(zp, S, ov, pitch, off):
    """Height of the gable wall's top edge at distance `off` from the ridge line."""
    tn = math.tan(math.radians(pitch))
    return zp + FH + (S / 2 + ov - abs(off)) * tn - FH


def roof_hip(g, cx, cy, L, S, zp, pitch, ov=0.45, soffit='ring'):
    """Hip roof over an L (x) by S (y) wall rectangle, plate (soffit) at zp. Returns ridge top z."""
    tn = math.tan(math.radians(pitch))
    Xw, Yw = L / 2, S / 2
    Xo, Yo = Xw + ov, Yw + ov
    zt = zp + FH + TH
    m = min(Xo, Yo)
    zr = zt + m * tn
    P = lambda x, y, z: (cx + x, cy + y, z)
    c = [P(-Xo, -Yo, zt), P(Xo, -Yo, zt), P(Xo, Yo, zt), P(-Xo, Yo, zt)]
    if Xo >= Yo:
        r0, r1 = P(-(Xo - Yo), 0, zr), P(Xo - Yo, 0, zr)
        faces = [([c[0], c[1], r1, r0], (0, -1, 1)), ([c[1], c[2], r1], (1, 0, 1)),
                 ([c[2], c[3], r0, r1], (0, 1, 1)), ([c[3], c[0], r0], (-1, 0, 1))]
    else:
        r0, r1 = P(0, -(Yo - Xo), zr), P(0, Yo - Xo, zr)
        faces = [([c[0], c[1], r0], (0, -1, 1)), ([c[1], c[2], r1, r0], (1, 0, 1)),
                 ([c[2], c[3], r1], (0, 1, 1)), ([c[3], c[0], r0, r1], (-1, 0, 1))]
    for pts, f in faces:
        if len(pts) == 4 and (Vector(pts[2]) - Vector(pts[3])).length < 1e-4:
            pts = pts[:3]
        g.poly(pts, 'Roof', f)
    o = [(-Xo, -Yo), (Xo, -Yo), (Xo, Yo), (-Xo, Yo)]
    w = [(-Xw, -Yw), (Xw, -Yw), (Xw, Yw), (-Xw, Yw)]
    for i in range(4):
        j = (i + 1) % 4
        mid = ((o[i][0] + o[j][0]) / 2, (o[i][1] + o[j][1]) / 2, 0)
        g.poly([P(*o[i], zp + FH), P(*o[j], zp + FH), P(*o[j], zt), P(*o[i], zt)], 'Roof', mid)
        g.poly([P(*o[i], zp), P(*o[j], zp), P(*o[j], zp + FH), P(*o[i], zp + FH)], 'Trim', mid)
        if soffit == 'ring':
            g.poly([P(*w[i], zp), P(*w[j], zp), P(*o[j], zp), P(*o[i], zp)], 'Trim', (0, 0, -1))
    if soffit == 'full':
        g.poly([P(*o[0], zp), P(*o[1], zp), P(*o[2], zp), P(*o[3], zp)], 'Trim', (0, 0, -1))
    return zr


def roof_porch(g, F, s0, s1, D, zp, pitch, ov=0.3, ends=('hip', 'hip')):
    """Porch roof leaning on a wall (frame F: u along the wall, d outward). It covers u in [s0, s1]
    out to the beam line at distance D, with eaves `ov` beyond. Ends: 'hip' (hipped), 'miter'
    (hip line but no end plane: a wraparound corner where the next porch roof takes over) or
    'flush' (runs straight to s0 / s1, e.g. against a wall). The ridge lies on the wall."""
    tn = math.tan(math.radians(pitch))
    Ro = D + ov
    zt = zp + FH + TH
    zr = zt + Ro * tn
    Z = Vector((0, 0, 1))
    eL = s0 - ov if ends[0] != 'flush' else s0
    eR = s1 + ov if ends[1] != 'flush' else s1
    rL = eL + Ro if ends[0] != 'flush' else s0
    rR = eR - Ro if ends[1] != 'flush' else s1
    if rL > rR:
        rL = rR = (rL + rR) / 2
    pts = [F.p(eL, zt, Ro), F.p(eR, zt, Ro), F.p(rR, zr, 0), F.p(rL, zr, 0)]
    if (pts[2] - pts[3]).length < 1e-4:
        pts = pts[:3]
    g.poly(pts, 'Roof', F.N + Z)
    fq(g, F, 'Roof', eL, eR, zp + FH, zt, Ro)
    fq(g, F, 'Trim', eL, eR, zp, zp + FH, Ro)
    for k, (e, r, sg) in enumerate(((eL, rL, -1), (eR, rR, 1))):
        if ends[k] == 'hip':
            g.poly([F.p(e, zt, Ro), F.p(e, zt, 0), F.p(r, zr, 0)], 'Roof', F.U * sg + Z)
            g.poly([F.p(e, zp, Ro), F.p(e, zp, 0), F.p(e, zt, 0), F.p(e, zt, Ro)], 'Trim', F.U * sg)
        if ends[k] in ('hip', 'flush'):
            # closure where the roof meets the wall line (hidden when a wall stands behind it)
            g.poly([F.p(e, zp, 0), F.p(r, zp, 0), F.p(r, zr, 0), F.p(e, zt if ends[k] == 'hip' else zr, 0)], 'Trim', -F.N)
    g.poly([F.p(eL, zp, 0), F.p(eR, zp, 0), F.p(eR, zp, Ro), F.p(eL, zp, Ro)], 'Trim', -Z)
    return zr


# ============================================================================ porch parts

def chimney(g, x0, x1, y0, y1, z0, z1, cap=True):
    box(g, 'Masonry', x0, x1, y0, y1, z0, z1, skip='b')
    if cap:
        box(g, 'Masonry', x0 - 0.05, x1 + 0.05, y0 - 0.05, y1 + 0.05, z1, z1 + 0.1, skip='b')
        box(g, 'Masonry', (x0 + x1) / 2 - 0.13, (x0 + x1) / 2 + 0.13, (y0 + y1) / 2 - 0.13, (y0 + y1) / 2 + 0.13, z1 + 0.1, z1 + 0.32, skip='b')


def ext_chimney(g, side, xw, yc, ztop, w=1.5, wtop=0.85, dep=0.75, zsh=2.6):
    """Exterior end chimney against a side wall (side 'W' at x = xw extends to -x; 'E' to +x)."""
    sg = -1 if side == 'W' else 1
    xa, xb = sorted((xw, xw + sg * dep))
    box(g, 'Masonry', xa, xb, yc - w / 2, yc + w / 2, Z_FOUND, zsh, skip='b')
    # sloped shoulders
    x_out = xw + sg * dep
    for s in (-1, 1):
        ya, yb = yc + s * w / 2, yc + s * wtop / 2
        g.poly([(xw, ya, zsh), (x_out, ya, zsh), (x_out, yb, zsh + 0.5), (xw, yb, zsh + 0.5)], 'Masonry', (0, s, 1))
    g.poly([(x_out, yc - w / 2, zsh), (x_out, yc + w / 2, zsh), (x_out, yc + wtop / 2, zsh + 0.5), (x_out, yc - wtop / 2, zsh + 0.5)], 'Masonry', (sg, 0, 0))
    xa2, xb2 = sorted((xw, xw + sg * (dep - 0.05)))
    chimney(g, xa2, xb2, yc - wtop / 2, yc + wtop / 2, zsh + 0.5 - 0.01, ztop)


def steps(g, xc, w, y_edge, z_top, mat='Masonry', run=0.28, direction=-1, cheeks=False, axis='y'):
    """Straight run of steps down from z_top at y_edge toward `direction` (−1 = toward -y / street)."""
    n = max(1, round(z_top / 0.18))
    rise = z_top / n
    for k in range(1, n):
        zt = z_top - k * rise
        ya, yb = sorted((y_edge + direction * (k - 1) * run, y_edge + direction * k * run))
        if axis == 'y':
            box(g, mat, xc - w / 2, xc + w / 2, ya, yb, -0.3, zt, skip='bn' if direction < 0 else 'bs')
        else:
            box(g, mat, ya, yb, xc - w / 2, xc + w / 2, -0.3, zt, skip='bw' if direction > 0 else 'be')
    if cheeks and n > 1:
        L = (n - 1) * run
        for sx in (-1, 1):
            x = xc + sx * (w / 2 + 0.12)
            ya, yb = sorted((y_edge, y_edge + direction * L))
            box(g, mat, x - 0.12, x + 0.12, ya, yb, -0.3, z_top + 0.05, skip='b')
    return n


def post(g, x, y, z0, z1, s=0.14, mat='Trim'):
    box(g, mat, x - s / 2, x + s / 2, y - s / 2, y + s / 2, z0, z1, skip='tb')


def railing(g, p0, p1, zf, out, h=0.9, spacing=0.17):
    """Top and bottom rails with square balusters (outward-facing quads) between posts."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    if L < 0.2:
        return
    u = d.normalized()
    out = Vector(out).normalized()
    side = u.cross(Vector((0, 0, 1)))
    for z0, hh, w in ((zf + h - 0.06, 0.06, 0.09), (zf + 0.08, 0.05, 0.07)):
        a, b = p0 + Vector((0, 0, z0)), p1 + Vector((0, 0, z0))
        seg_box(g, 'Trim', a, b, w, hh)
    n = int(L / spacing)
    for i in range(1, n):
        c = p0 + u * (L * i / n)
        for o in (out, -out):
            q = [c - u * 0.022 + o * 0.022, c + u * 0.022 + o * 0.022]
            g.poly([q[0] + Vector((0, 0, zf + 0.13)), q[1] + Vector((0, 0, zf + 0.13)),
                    q[1] + Vector((0, 0, zf + h - 0.06)), q[0] + Vector((0, 0, zf + h - 0.06))], 'Trim', o)


def deck(g, x0, x1, y0, y1, fz, floor='Masonry', skirt='Masonry', rim=0.22):
    """Porch floor: masonry base or piers below, a rim band and the floor on top."""
    if floor == 'Masonry':
        box(g, 'Masonry', x0, x1, y0, y1, Z_FOUND, fz, skip='bn')
        return
    box(g, skirt, x0 + 0.05, x1 - 0.05, y0 + 0.05, y1 - 0.05, Z_FOUND, fz - rim, skip='bnt')
    box(g, 'Trim', x0, x1, y0, y1, fz - rim, fz, skip='bn')


def piers(g, pts, z1, s=0.4):
    for x, y in pts:
        cbox(g, 'Masonry', x, y, s, s, Z_FOUND, z1, skip='b')


def beam(g, x0, x1, y0, y1, z0, z1):
    box(g, 'Trim', x0, x1, y0, y1, z0, z1, skip='')


def dormer(g, xc, yf, w, z_bot, zp, pitch_main_dummy, depth, pitch=45, ov=0.15, win=(0.8, 0.85)):
    """Gabled dormer: front wall at y = yf with a window, cheeks running back `depth` into the roof."""
    x0, x1 = xc - w / 2, xc + w / 2
    F = Fr((0, yf, 0), (1, 0, 0))
    ww, wh = win
    zc = zp - 0.12 - wh
    wall(g, F, x0, x1, z_bot, zp, [(xc - ww / 2, xc + ww / 2, zc, zc + wh)])
    window(g, F, xc - ww / 2, xc + ww / 2, zc, zc + wh, cw=0.08, head=0.08)
    box(g, 'Trim', x0 - 0.02, x0 + 0.08, yf - 0.02, yf + 0.08, z_bot, zp, skip='tb')
    box(g, 'Trim', x1 - 0.08, x1 + 0.02, yf - 0.02, yf + 0.08, z_bot, zp, skip='tb')
    for x, n in ((x0, (-1, 0, 0)), (x1, (1, 0, 0))):
        g.poly([(x, yf, z_bot), (x, yf + depth, z_bot), (x, yf + depth, zp), (x, yf, zp)], 'Wall', n)
    return roof_gable(g, xc, yf + depth / 2, depth, w, zp, pitch, axis='y', ov=ov, rake=ov, walls=(True, False), ends=(True, False))


# ============================================================================ archetypes
# Each builder fills a G and returns metadata. Coordinates are drafted with the front wall near
# y = -d/2; everything is re-centered on the XY bounding box afterwards.

FIRST = dict(sill=0.85, head=2.25)    # above floor


def W(c, w, z0, z1, **kw):
    return ('w', c, w, z0, z1, kw)


def D(c, w, z0, z1=None, **kw):
    return ('d', c, w, z0, z0 + 2.06 if z1 is None else z1, kw)


def Fw(c, w, z0, z1, **kw):
    return ('f', c, w, z0, z1, kw)


def b_ranch(g):
    x0, x1, y0, y1 = -6.6, 6.6, -4.0, 4.0
    fz, zp = 0.45, 0.45 + 2.5
    s, h = fz + 0.9, fz + 2.15
    ops = {
        'S': [W(-4.1, 2.6, s - 0.1, h, mull=2, rail=False), D(-1.6, 0.92, fz, lite=True), W(1.0, 1.1, s, h),
              W(3.4, 1.1, s, h), W(5.4, 0.8, fz + 1.45, h)],
        'E': [W(-1.6, 1.0, s, h), W(1.8, 1.0, s, h)],
        'N': [W(-4.6, 1.1, s, h), D(-2.4, 0.86, fz), W(-0.4, 1.4, fz + 1.2, h, mull=1), W(2.6, 1.0, s, h), W(5.0, 1.0, s, h)],
        'W': [W(-1.8, 1.0, s, h), W(1.6, 0.8, fz + 1.45, h)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops)
    ztop = roof_hip(g, 0, 0, x1 - x0, y1 - y0, zp, 22, ov=0.5)
    chimney(g, -3.6, -2.9, 0.9, 1.6, zp, ztop + 0.5)
    # front stoop with steps
    deck(g, -2.6, -0.6, y0 - 1.3, y0, fz - 0.03)
    steps(g, -1.6, 1.4, y0 - 1.3, fz - 0.03)
    # back stoop
    box(g, 'Masonry', -3.0, -1.8, y1, y1 + 1.0, Z_FOUND, fz - 0.03, skip='bs')
    return dict(stories=1, style='1950s-60s ranch, low hip roof', hoods=['Westport Acres', 'Pinecrest', 'North End', 'South of the river'])


def b_brick_ranch(g):
    x0, x1, y0, y1 = -7.2, 7.2, -4.3, 4.3
    fz, zp = 0.5, 0.5 + 2.5
    s, h = fz + 0.9, fz + 2.15
    kw = dict(shutters=True, sill='Masonry', cw=0.07)
    ops = {
        'S': [W(-5.0, 2.0, s - 0.15, h, mull=1, **kw), W(-2.6, 1.0, s, h, **kw), D(-0.8, 0.92, fz, lite=True),
              W(1.6, 1.0, s, h, **kw), W(3.9, 1.0, s, h, **kw), W(6.1, 0.75, fz + 1.4, h, sill='Masonry', cw=0.07)],
        'E': [W(-1.6, 1.0, s, h, sill='Masonry', cw=0.07), W(1.8, 1.0, s, h, sill='Masonry', cw=0.07)],
        'N': [W(-5.2, 1.0, s, h, sill='Masonry'), W(-2.6, 1.6, fz + 1.2, h, mull=1, sill='Masonry'), D(0.2, 0.86, fz),
              W(2.6, 1.0, s, h, sill='Masonry'), W(5.2, 1.0, s, h, sill='Masonry')],
        'W': [W(2.4, 0.8, fz + 1.4, h, sill='Masonry')],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, wmat='Masonry', found='Masonry', corners=False)
    pitch, ov = 23, 0.4
    ztop = roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, pitch, ov=ov, rake=0.3)
    # gable vents
    for sx in (-1, 1):
        F = Fr((sx * x1, 0, 0), (0, sx, 0))
        flat_window(g, F, -0.45, 0.45, zp + 0.55, zp + 1.25, louver=True)
    ext_chimney(g, 'W', x0, -0.3, ztop + 0.6, w=1.6, wtop=0.9, zsh=2.3)
    # gabled entry portico on two posts over a brick stoop
    px0, px1, py0 = -2.1, 0.5, y0 - 1.7
    deck(g, px0 - 0.1, px1 + 0.1, py0, y0, fz - 0.03)
    steps(g, -0.8, 1.6, py0, fz - 0.03)
    zpp = zp - 0.12
    for x in (px0 + 0.12, px1 - 0.12):
        post(g, x, py0 + 0.14, fz - 0.03, zpp - 0.22, s=0.15)
    beam(g, px0, px1, py0 + 0.04, py0 + 0.24, zpp - 0.22, zpp)
    roof_gable(g, (px0 + px1) / 2, y0 - 1.7 + 2.15, 4.3, px1 - px0, zpp, 38, axis='y', ov=0.18, rake=0.15, walls=(True, False), ends=(True, False))
    return dict(stories=1, style='brick ranch, side gable with siding gables and a gabled entry portico', hoods=['Westport Acres', 'Pinecrest', 'Harborview', 'North End', 'South of the river'])


def b_bungalow(g):
    x0, x1, y0, y1 = -4.5, 4.5, -5.0, 6.2
    fz, zp = 0.6, 0.6 + 2.7
    s, h = fz + 0.85, fz + 2.2
    ops = {
        'S': [D(-1.5, 0.92, fz, lite=True), W(-3.3, 1.2, s, h), W(2.8, 1.9, s, h, mull=1)],
        'E': [W(-3.4, 1.0, s, h), W(-1.6, 1.0, s, h), W(1.6, 1.0, s, h), W(4.4, 0.8, fz + 1.4, h)],
        'N': [W(-2.4, 1.0, s, h), D(1.6, 0.86, fz)],
        'W': [W(-4.2, 1.0, s, h), W(-2.4, 1.0, s, h), W(0.6, 1.3, fz + 1.1, h, mull=1), W(3.6, 1.0, s, h)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops)
    pitch, ov = 27, 0.6
    L = y1 - y0
    roof_gable(g, 0, (y0 + y1) / 2, L, x1 - x0, zp, pitch, axis='y', ov=ov, rake=0.5)
    F = Fr((0, y0, 0), (1, 0, 0))
    flat_window(g, F, -0.55, 0.55, zp + 0.6, zp + 1.35, louver=True)
    Fb = Fr((0, y1, 0), (-1, 0, 0))
    flat_window(g, Fb, -0.45, 0.45, zp + 0.6, zp + 1.25, louver=True)
    # exterior chimney on the east wall
    xa = x1
    box(g, 'Masonry', xa, xa + 0.7, 0.8, 2.2, Z_FOUND, zp + 0.25, skip='b')
    chimney(g, xa, xa + 0.62, 1.05, 1.95, zp + 0.24, 6.1)
    # front-gable porch: brick piers, tapered columns, brick knee walls
    px0, px1, D_ = -4.5, 1.6, 2.6
    py0 = y0 - D_
    deck(g, px0, px1, py0, y0, fz)
    zpp = zp - 0.25
    pier_xs = [px0 + 0.25, (px0 + px1) / 2 - 1.15, px1 - 0.25]
    for x in pier_xs:
        cbox(g, 'Masonry', x, py0 + 0.25, 0.5, 0.5, fz - 0.01, fz + 0.95, skip='b')
        taper(g, 'Trim', x, py0 + 0.25, 0.36, 0.24, fz + 0.95, zpp - 0.3)
    # knee walls between piers, leaving the opening at the steps
    box(g, 'Masonry', pier_xs[1] + 0.25, pier_xs[2] - 0.25, py0 + 0.1, py0 + 0.36, fz, fz + 0.8, skip='b')
    box(g, 'Masonry', px1 - 0.36, px1 - 0.1, py0 + 0.5, y0, fz, fz + 0.8, skip='b')
    beam(g, px0, px1, py0 + 0.1, py0 + 0.4, zpp - 0.3, zpp)
    steps(g, (pier_xs[0] + pier_xs[1]) / 2, 1.5, py0, fz, cheeks=False)
    roof_gable(g, (px0 + px1) / 2, py0 + (D_ + 2.0) / 2, D_ + 2.0, px1 - px0, zpp, pitch, axis='y', ov=0.35, rake=0.35, walls=(True, False), ends=(True, False))
    Fp = Fr((0, py0 + 0.0, 0), (1, 0, 0))
    flat_window(g, Fp, (px0 + px1) / 2 - 0.4, (px0 + px1) / 2 + 0.4, zpp + 0.35, zpp + 0.85, louver=True)
    return dict(stories=1, style='Craftsman bungalow, front gable with an offset front-gable porch on brick piers', hoods=['Riverside', 'Garden District', 'North End', 'Downtown'])


def b_cape(g):
    x0, x1, y0, y1 = -5.2, 5.2, -4.1, 4.1
    fz, zp = 0.5, 0.5 + 2.55
    s, h = fz + 0.85, fz + 2.2
    kw = dict(shutters=True)
    ops = {
        'S': [W(-3.6, 0.95, s, h, **kw), W(-1.9, 0.95, s, h, **kw), D(0.0, 0.95, fz, transom=0.3),
              W(1.9, 0.95, s, h, **kw), W(3.6, 0.95, s, h, **kw)],
        'E': [W(-1.8, 0.95, s, h), W(1.8, 0.95, s, h)],
        'N': [W(-3.2, 0.95, s, h), D(-1.0, 0.86, fz), W(1.2, 1.4, fz + 1.1, h, mull=1), W(3.6, 0.95, s, h)],
        'W': [W(2.0, 0.95, s, h)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops)
    pitch, ov = 43, 0.3
    ztop = roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, pitch, ov=ov, rake=0.25)
    for sx in (-1, 1):
        F = Fr((sx * x1, 0, 0), (0, sx, 0))
        for u in (-1.3, 1.3):
            flat_window(g, F, u - 0.42, u + 0.42, zp + 0.6, zp + 1.75)
        flat_window(g, F, -0.3, 0.3, zp + 2.6, zp + 3.05, louver=True)
    tn = math.tan(math.radians(pitch))
    for xc in (-2.6, 2.6):
        yf = y0 + 0.75
        zroof = zp + FH + (ov + 0.75) * tn
        dormer(g, xc, yf, 1.55, zroof - 0.15, zroof + 1.25, pitch, 2.4, pitch=45, win=(0.8, 0.95))
    ext_chimney(g, 'W', x0, 0.4, ztop + 0.6, w=1.6, wtop=0.85, zsh=2.5)
    deck(g, -1.1, 1.1, y0 - 1.2, y0, fz - 0.03)
    steps(g, 0.0, 1.6, y0 - 1.2, fz - 0.03)
    # small pediment hood over the door on brackets
    roof_gable(g, 0.0, y0 - 0.45 + 0.9, 1.8, 1.7, fz + 2.62, 35, axis='y', ov=0.1, rake=0.12, walls=(True, False), ends=(True, False))
    return dict(stories=1.5, style='Cape Cod, steep side gable, two gabled dormers, end chimney', hoods=['Westport Acres', 'Garden District', 'Harborview', 'North End'])


def b_colonial(g):
    x0, x1, y0, y1 = -6.2, 6.2, -4.1, 4.1
    fz = 0.6
    z2 = fz + 2.75 + 0.3
    zp = z2 + 2.6
    s1, h1 = fz + 0.8, fz + 2.3
    s2, h2 = z2 + 0.7, z2 + 2.15
    kw = dict(shutters=True)
    xs = (-4.75, -2.25, 2.25, 4.75)
    S = [W(x, 0.85, s1, h1, **kw) for x in xs] + [D(0.0, 1.0, fz, transom=0.35)]
    S += [W(x, 0.85, s2, h2, **kw) for x in xs] + [W(0.0, 0.75, s2 + 0.15, h2, **kw)]
    ops = {
        'S': S,
        'E': [W(-1.9, 0.95, s1, h1), W(1.9, 0.95, s1, h1), W(-1.9, 0.95, s2, h2), W(1.9, 0.95, s2, h2)],
        'N': [W(-4.4, 0.95, s1, h1), D(-1.6, 0.9, fz, lite=True), W(1.4, 1.5, fz + 1.1, h1, mull=1), W(4.4, 0.95, s1, h1),
              W(-4.4, 0.95, s2, h2), W(-1.6, 0.7, s2 + 0.4, h2), W(1.4, 0.95, s2, h2), W(4.4, 0.95, s2, h2)],
        'W': [W(-1.9, 0.95, s1, h1), W(1.9, 0.95, s1, h1), W(-1.9, 0.95, s2, h2), W(1.9, 0.95, s2, h2)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, belt=z2 - 0.12)
    pitch, ov = 33, 0.35
    ztop = roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, pitch, ov=ov, rake=0.25)
    for sx in (-1, 1):
        F = Fr((sx * x1, 0, 0), (0, sx, 0))
        flat_window(g, F, -0.35, 0.35, zp + 0.7, zp + 1.5, louver=True)
    ext_chimney(g, 'E', x1, 0.0, ztop + 0.6, w=1.7, wtop=0.9, zsh=z2 + 1.4)
    # entry portico: two columns, pediment
    px0, px1, py0 = -1.3, 1.3, y0 - 1.5
    deck(g, px0 - 0.2, px1 + 0.2, py0, y0, fz - 0.03)
    steps(g, 0.0, 2.0, py0, fz - 0.03)
    zpp = fz + 2.95
    for x in (px0 + 0.15, px1 - 0.15):
        taper(g, 'Trim', x, py0 + 0.2, 0.26, 0.22, fz - 0.03, zpp - 0.3)
    beam(g, px0, px1, py0 + 0.05, py0 + 0.35, zpp - 0.3, zpp)
    roof_gable(g, 0.0, py0 + 2.0, 4.0, px1 - px0, zpp, 30, axis='y', ov=0.18, rake=0.18, walls=(True, False), ends=(True, False))
    return dict(stories=2, style='Colonial Revival, two stories, side gable, five bays with shutters, end chimney', hoods=['Harborview', 'Garden District', 'Westport Acres', 'Uptown'])


def b_foursquare(g):
    x0, x1, y0, y1 = -4.5, 4.5, -4.0, 4.5
    fz = 0.75
    z2 = fz + 2.8 + 0.3
    zp = z2 + 2.6
    s1, h1 = fz + 0.8, fz + 2.3
    s2, h2 = z2 + 0.7, z2 + 2.1
    ops = {
        'S': [W(-2.6, 1.0, s1, h1), D(1.2, 1.0, fz, lite=True, transom=0.3), W(-2.4, 1.0, s2, h2), W(0.0, 0.7, s2 + 0.3, h2), W(2.4, 1.0, s2, h2)],
        'E': [W(-2.2, 1.0, s1, h1), W(1.0, 1.6, s1, h1, mull=1), W(3.2, 0.7, fz + 1.5, h1), W(-2.2, 1.0, s2, h2), W(1.0, 1.0, s2, h2), W(3.2, 0.9, s2, h2)],
        'N': [W(-2.4, 1.0, s1, h1), D(0.8, 0.9, fz), W(2.8, 1.0, s1, h1), W(-2.4, 1.0, s2, h2), W(2.4, 1.0, s2, h2)],
        'W': [W(-2.2, 1.0, s1, h1), W(1.0, 1.0, s1, h1), W(3.2, 1.0, s1, h1), W(-2.2, 1.0, s2, h2), W(1.0, 1.0, s2, h2), W(3.2, 0.9, s2, h2)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, belt=z2 - 0.12)
    pitch, ov = 30, 0.55
    ztop = roof_hip(g, 0, (y0 + y1) / 2, x1 - x0, y1 - y0, zp, pitch, ov=ov)
    chimney(g, 2.6, 3.3, 1.6, 2.3, zp, ztop + 0.3)
    # hipped front dormer
    tn = math.tan(math.radians(pitch))
    yf = y0 + 1.0
    zroof = zp + FH + TH + (ov + 1.0) * tn
    xd0, xd1 = -1.2, 1.2
    zpd = zroof + 0.95
    F = Fr((0, yf, 0), (1, 0, 0))
    wall(g, F, xd0, xd1, zroof - 0.15, zpd, [(-0.9, -0.1, zroof + 0.2, zpd - 0.12), (0.1, 0.9, zroof + 0.2, zpd - 0.12)])
    window(g, F, -0.9, -0.1, zroof + 0.2, zpd - 0.12, rail=False, cw=0.07, head=0.07)
    window(g, F, 0.1, 0.9, zroof + 0.2, zpd - 0.12, rail=False, cw=0.07, head=0.07)
    for x, n in ((xd0, (-1, 0, 0)), (xd1, (1, 0, 0))):
        g.poly([(x, yf, zroof - 0.15), (x, yf + 2.2, zroof - 0.15), (x, yf + 2.2, zpd), (x, yf, zpd)], 'Wall', n)
    roof_hip(g, 0.0, yf + 1.1, xd1 - xd0, 2.2, zpd, 22, ov=0.3)
    # full-width front porch
    D_ = 2.4
    py0 = y0 - D_
    fzp = fz - 0.05
    deck(g, x0 - 0.15, x1 + 0.15, py0, y0, fzp, floor='Trim')
    zpp = fz + 2.75
    for x in (x0 - 0.0, -1.6, 2.4, x1 - 0.0):
        cbox(g, 'Masonry', x, py0 + 0.22, 0.42, 0.42, fzp, fzp + 0.5, skip='b')
        post(g, x, py0 + 0.22, fzp + 0.5, zpp - 0.28, s=0.26)
    beam(g, x0 - 0.15, x1 + 0.15, py0 + 0.08, py0 + 0.36, zpp - 0.28, zpp)
    Fs = Fr((0, y0, 0), (1, 0, 0))
    roof_porch(g, Fs, x0 - 0.15, x1 + 0.15, D_, zpp, 16, ov=0.35)
    railing(g, (x0, py0 + 0.22, 0), (-1.6, py0 + 0.22, 0), fzp, (0, -1, 0), h=0.85)
    for x in (x0 - 0.1, x1 + 0.1):
        railing(g, (x, py0 + 0.22, 0), (x, y0, 0), fzp, (1 if x > 0 else -1, 0, 0), h=0.85)
    railing(g, (2.4, py0 + 0.22, 0), (x1, py0 + 0.22, 0), fzp, (0, -1, 0), h=0.85)
    steps(g, 0.4, 1.8, py0, fzp, cheeks=True)
    return dict(stories=2.5, style='American Foursquare, hip roof with hipped dormer, full-width porch', hoods=['Garden District', 'Downtown', 'North End', 'Riverside'])


def b_farmhouse(g):
    x0, x1, y0, y1 = -5.6, 5.6, -3.1, 3.1
    fz = 0.6
    z2 = fz + 2.8 + 0.3
    zp = z2 + 2.5
    s1, h1 = fz + 0.75, fz + 2.35
    s2, h2 = z2 + 0.65, z2 + 2.1
    ops = {
        'S': [W(-3.9, 0.95, s1, h1), W(-1.6, 0.95, s1, h1), D(0.4, 1.0, fz, transom=0.35), W(2.4, 0.95, s1, h1), W(4.2, 0.95, s1, h1),
              W(-3.9, 0.95, s2, h2), W(-1.6, 0.95, s2, h2), W(1.1, 0.95, s2, h2), W(3.8, 0.95, s2, h2)],
        'E': [W(-1.4, 0.95, s1, h1), D(1.4, 0.9, fz, lite=True), W(-1.4, 0.95, s2, h2), W(1.2, 0.95, s2, h2)],
        'N': [W(-4.0, 0.95, s1, h1), W(-3.6, 0.95, s2, h2), W(3.8, 0.95, s2, h2), W(4.6, 0.95, s1, h1)],
        'W': [W(-1.2, 0.95, s1, h1), W(1.2, 0.95, s1, h1), W(-1.2, 0.95, s2, h2), W(1.2, 0.95, s2, h2)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops)
    pitch, ov = 40, 0.35
    ztop = roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, pitch, ov=ov, rake=0.25)
    for sx in (-1, 1):
        F = Fr((sx * x1, 0, 0), (0, sx, 0))
        flat_window(g, F, -0.4, 0.4, zp + 0.5, zp + 1.5)
    for sx in (-1, 1):
        chimney(g, sx * 4.6 - 0.35, sx * 4.6 + 0.35, 0.05, 0.75, zp, ztop + 0.45)
    # one-story rear ell
    ex0, ex1, ey1 = -2.6, 2.4, y1 + 3.6
    zpe = fz + 2.7
    ops_e = {'E': [W(y1 + 1.8, 0.95, s1, h1)], 'W': [W(y1 + 1.4, 0.95, s1, h1), D(y1 + 2.9, 0.86, fz)],
             'N': [W(-1.0, 0.95, s1, h1), W(1.0, 0.95, s1, h1)]}
    body(g, ex0, ex1, y1 - 0.2, ey1, fz, zpe, ops_e, skip_walls='S')
    roof_gable(g, (ex0 + ex1) / 2, (y1 - 0.2 + ey1) / 2 + 0.6, ey1 - y1 + 0.2 + 1.2, ex1 - ex0, zpe, 35, axis='y', ov=0.3, rake=0.25, walls=(False, True), ends=(False, True))
    # wraparound porch: front and east side
    Dp = 2.3
    py0 = y0 - Dp
    sx1 = x1 + Dp
    fzp = fz - 0.05
    deck(g, x0 - 0.1, sx1, py0, y0, fzp, floor='Trim')
    deck(g, x1, sx1, y0, y1 - 0.4, fzp, floor='Trim')
    zpp = fz + 2.75
    Fs = Fr((0, y0, 0), (1, 0, 0))
    Fe = Fr((x1, 0, 0), (0, 1, 0))
    roof_porch(g, Fs, x0 - 0.1, sx1, Dp, zpp, 14, ov=0.3, ends=('hip', 'miter'))
    roof_porch(g, Fe, py0, y1 - 0.4, Dp, zpp, 14.5, ov=0.3, ends=('miter', 'hip'))
    for x in (x0 + 0.0, -2.2, 1.6, 4.4, sx1 - 0.15):
        post(g, x, py0 + 0.15, fzp, zpp - 0.25, s=0.16)
    for y in (y0 + 0.1, y1 - 0.55):
        post(g, sx1 - 0.15, y, fzp, zpp - 0.25, s=0.16)
    beam(g, x0 - 0.1, sx1, py0 + 0.05, py0 + 0.3, zpp - 0.25, zpp)
    beam(g, sx1 - 0.3, sx1 - 0.05, py0, y1 - 0.4, zpp - 0.25, zpp)
    steps(g, 0.4, 1.8, py0, fzp)
    return dict(stories=2, style='two-story farmhouse (I-house) with standing-seam metal roof, rear ell, wraparound porch', hoods=['North of town', 'Riverside', 'North End', 'Marsh Point'])


def b_shotgun(g):
    x0, x1, y0, y1 = -2.4, 2.4, -6.6, 7.4
    fz = 0.8
    zp = fz + 3.0
    s, h = fz + 0.6, fz + 2.55
    ops = {
        'S': [D(-1.2, 0.9, fz, transom=0.4), W(1.0, 0.9, s, h)],
        'E': [W(-4.4, 0.85, s, h), W(-0.8, 0.85, s, h), W(2.6, 0.85, s, h), W(5.8, 0.75, fz + 1.2, h)],
        'W': [W(-3.8, 0.85, s, h), W(0.2, 0.85, s, h), W(4.4, 0.85, s, h)],
        'N': [D(1.2, 0.86, fz), W(-1.0, 0.85, s, h)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, found=None)
    # brick piers under the sill beam, a skirt board ties them visually
    pts = [(x, y) for y in (y0 + 0.2, y0 + 2.6, y0 + 5.0, y0 + 7.4, y0 + 9.8, y0 + 12.2, y1 - 0.2) for x in (x0 + 0.2, x1 - 0.2)]
    piers(g, pts, fz - 0.22, s=0.38)
    box(g, 'Trim', x0 - 0.03, x1 + 0.03, y0 - 0.03, y1 + 0.03, fz - 0.24, fz + 0.02, skip='bt')
    # main front-gable roof runs forward over the porch
    Dp = 1.9
    py0 = y0 - Dp
    pitch = 28
    roof_gable(g, 0, (py0 + y1) / 2, y1 - py0, x1 - x0, zp, pitch, axis='y', ov=0.35, rake=0.3)
    g.poly([(x0, py0, zp), (x1, py0, zp), (x1, y0, zp), (x0, y0, zp)], 'Trim', (0, 0, -1))   # porch ceiling
    Fp = Fr((0, py0, 0), (1, 0, 0))
    flat_window(g, Fp, -0.35, 0.35, zp + 0.25, zp + 0.85, louver=True)
    # porch floor on piers, posts, brackets, rail
    piers(g, [(x0 + 0.2, py0 + 0.2), (x1 - 0.2, py0 + 0.2), (0.0, py0 + 0.2)], fz - 0.25, s=0.38)
    box(g, 'Trim', x0, x1, py0, y0, fz - 0.25, fz - 0.03, skip='bn')
    for x in (x0 + 0.12, -0.25, x1 - 0.12):
        post(g, x, py0 + 0.12, fz - 0.03, zp, s=0.14)
    beam(g, x0, x1, py0, py0 + 0.24, zp - 0.3, zp)
    railing(g, (0.0, py0 + 0.12, 0), (x1 - 0.12, py0 + 0.12, 0), fz - 0.03, (0, -1, 0), h=0.85)
    for x in (x0 + 0.12, x1 - 0.12):
        railing(g, (x, py0 + 0.12, 0), (x, y0, 0), fz - 0.03, (1 if x > 0 else -1, 0, 0), h=0.85)
    steps(g, -1.25, 1.1, py0, fz - 0.03, mat='Masonry')
    chimney(g, -0.35, 0.35, 1.0, 1.6, zp, 5.95)
    box(g, 'Masonry', 0.6, 1.8, y1, y1 + 0.9, Z_FOUND, fz - 0.03, skip='bs')
    return dict(stories=1, style='shotgun house on brick piers, front gable over a full-width porch', hoods=['Riverside', 'Downtown', 'South of the river'])


def b_coastal(g):
    x0, x1, y0, y1 = -4.5, 4.5, -3.6, 4.4
    fz = 2.2
    zp = fz + 2.9
    s, h = fz + 0.55, fz + 2.35
    ops = {
        'S': [W(-3.0, 0.95, s, h), D(-0.9, 0.95, fz, lite=True), W(1.0, 0.95, s, h), W(3.0, 0.95, s, h)],
        'E': [W(-1.8, 0.95, s, h), W(0.6, 0.95, s, h), W(2.8, 0.95, s, h)],
        'N': [W(-2.8, 0.95, s, h), D(-0.4, 1.6, fz, lite=True), W(2.6, 1.5, s + 0.3, h, mull=1)],
        'W': [W(-1.8, 0.95, s, h), W(1.0, 0.95, s, h), W(2.8, 0.7, fz + 1.3, h)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, found=None)
    box(g, 'Trim', x0 - 0.04, x1 + 0.04, y0 - 0.04, y1 + 0.04, fz - 0.32, fz + 0.02, skip='t')   # floor band
    pts = [(x, y) for x in (x0 + 0.2, -1.5, 1.5, x1 - 0.2) for y in (y0 + 0.2, 0.4, y1 - 0.2)]
    piers(g, pts, fz - 0.32, s=0.4)
    ztop = roof_hip(g, 0, (y0 + y1) / 2, x1 - x0, y1 - y0, zp, 28, ov=0.55)
    chimney(g, 2.2, 2.85, 1.6, 2.25, zp, ztop + 0.2)
    # front porch on posts down to grade, hip roof tucked under the main eave
    Dp = 2.4
    py0 = y0 - Dp
    box(g, 'Trim', x0, x1, py0, y0, fz - 0.3, fz - 0.03, skip='n')
    zpp = zp - 0.3
    for x in (x0 + 0.1, -1.5, 1.5, x1 - 0.1):
        post(g, x, py0 + 0.1, Z_FOUND, zpp - 0.25, s=0.18)
        post(g, x, y0 - 0.1, Z_FOUND, fz - 0.3, s=0.16)
    beam(g, x0, x1, py0, py0 + 0.24, zpp - 0.25, zpp)
    roof_porch(g, Fr((0, y0, 0), (1, 0, 0)), x0, x1, Dp, zpp, 11, ov=0.3)
    railing(g, (x0 + 0.1, py0 + 0.1, 0), (1.5, py0 + 0.1, 0), fz - 0.03, (0, -1, 0), h=0.95)
    railing(g, (2.7, py0 + 0.1, 0), (x1 - 0.1, py0 + 0.1, 0), fz - 0.03, (0, -1, 0), h=0.95)
    for x in (x0 + 0.1, x1 - 0.1):
        railing(g, (x, py0 + 0.1, 0), (x, y0, 0), fz - 0.03, (1 if x > 0 else -1, 0, 0), h=0.95)
    # stair parallel to the porch front: top at x = 2.6, running down toward -x
    n = round((fz - 0.03) / 0.18)
    rise = (fz - 0.03) / n
    run = 0.26
    sy0, sy1 = py0 - 1.15, py0 - 0.05
    xt = 2.6
    for k in range(1, n):
        x = xt - k * run
        box(g, 'Trim', x - run - 0.02, x, sy0 + 0.04, sy1 - 0.04, fz - 0.03 - k * rise - 0.05, fz - 0.03 - k * rise, skip='')
    xb = xt - n * run
    for y in (sy0, sy1 - 0.06):
        seg_box(g, 'Trim', (xb, y + 0.03, -0.25), (xt, y + 0.03, fz - 0.33), 0.06, 0.28, ends=True)
    seg_box(g, 'Trim', (xb, sy0 + 0.03, 0.9), (xt, sy0 + 0.03, fz + 0.9), 0.07, 0.06, ends=True)
    post(g, xb + 0.05, sy0 + 0.03, -0.3, 1.0, s=0.1)
    box(g, 'Masonry', xb - 0.9, xb + 0.1, sy0 - 0.05, sy1 + 0.05, -0.2, 0.06, skip='b')   # landing pad
    return dict(stories=1, style='raised coastal cottage on brick piers, hip roof, porch with a side-running stair', hoods=['The beach', 'Marsh Point', 'Harborview'])


def b_victorian(g):
    x0, x1, y0, y1 = -5.0, 3.0, -3.0, 6.2
    fz = 0.8
    z2 = fz + 3.0 + 0.3
    zp = z2 + 2.8
    s1, h1 = fz + 0.7, fz + 2.6
    s2, h2 = z2 + 0.65, z2 + 2.3
    bx0, bx1, by0 = 0.6, 5.2, -5.2    # projecting front-gable bay
    ops = {
        'S': [W(-3.6, 0.95, s1, h1), D(-1.4, 1.05, fz, lite=True, transom=0.4), W(-3.6, 0.95, s2, h2), W(-1.4, 0.95, s2, h2)],
        'E': [W(1.0, 0.95, s1, h1), W(3.6, 0.95, s1, h1), W(1.0, 0.95, s2, h2), W(3.6, 0.95, s2, h2)],
        'N': [W(-3.6, 0.95, s1, h1), D(-1.0, 0.9, fz), W(1.6, 0.95, s1, h1), W(-3.6, 0.95, s2, h2), W(0.6, 0.95, s2, h2)],
        'W': [W(-1.6, 0.95, s1, h1), W(1.0, 0.95, s1, h1), W(3.8, 0.95, s1, h1), W(-1.6, 0.95, s2, h2), W(1.6, 0.95, s2, h2), W(3.8, 0.95, s2, h2)],
    }
    body(g, x0, x1, y0, y1, fz, zp, ops, belt=z2 - 0.12)
    ops_b = {
        'S': [W(2.1, 0.95, s1, h1), W(3.7, 0.95, s1, h1), W(2.1, 0.95, s2, h2), W(3.7, 0.95, s2, h2)],
        'E': [W(-4.0, 0.95, s1, h1), W(-4.0, 0.95, s2, h2), W(-1.5, 0.95, s1, h1)],
        'W': [W(-4.2, 0.8, s2, h2)],
    }
    body(g, bx0, bx1, by0, -0.4, fz, zp, ops_b, belt=z2 - 0.12, skip_walls='N')
    ztop = roof_hip(g, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, zp, 42, ov=0.5)
    pb = 48
    roof_gable(g, (bx0 + bx1) / 2, (by0 + 2.4) / 2, 2.4 - by0, bx1 - bx0, zp, pb, axis='y', ov=0.4, rake=0.4, walls=(True, False), ends=(True, False))
    Fb = Fr((0, by0, 0), (1, 0, 0))
    flat_window(g, Fb, (bx0 + bx1) / 2 - 0.45, (bx0 + bx1) / 2 + 0.45, zp + 0.5, zp + 1.6)
    # decorative gable truss band
    box(g, 'Trim', bx0 - 0.05, bx1 + 0.05, by0 - 0.08, by0 + 0.02, zp - 0.02, zp + 0.18, skip='b')
    for xc, yc in ((-3.6, 4.4), (1.6, 1.0)):
        chimney(g, xc - 0.35, xc + 0.35, yc - 0.45, yc + 0.45, zp, ztop + 0.6)
    # wraparound porch: across the front of the main block and down the west side
    Dp = 2.3
    py0 = y0 - Dp
    sx0 = x0 - Dp
    fzp = fz - 0.05
    deck(g, sx0, bx0, py0, y0, fzp, floor='Trim')
    deck(g, sx0, x0, y0, 2.6, fzp, floor='Trim')
    zpp = fz + 2.85
    roof_porch(g, Fr((0, y0, 0), (1, 0, 0)), sx0, bx0, Dp, zpp, 16, ov=0.3, ends=('miter', 'flush'))
    roof_porch(g, Fr((x0, 0, 0), (0, -1, 0)), -2.6, -py0, Dp, zpp, 16.5, ov=0.3, ends=('hip', 'miter'))
    posts_xy = [(sx0 + 0.12, py0 + 0.12), (-4.0, py0 + 0.12), (-1.4 + 0.9, py0 + 0.12), (bx0 - 0.12, py0 + 0.12),
                (sx0 + 0.12, y0 + 0.1), (sx0 + 0.12, 2.45)]
    for x, y in posts_xy:
        post(g, x, y, fzp, zpp - 0.25, s=0.15)
    beam(g, sx0, bx0, py0, py0 + 0.24, zpp - 0.25, zpp)
    beam(g, sx0, sx0 + 0.24, py0, 2.6, zpp - 0.25, zpp)
    railing(g, (sx0 + 0.12, py0 + 0.12, 0), (-2.3, py0 + 0.12, 0), fzp, (0, -1, 0))
    railing(g, (-0.5, py0 + 0.12, 0), (bx0 - 0.12, py0 + 0.12, 0), fzp, (0, -1, 0))
    railing(g, (sx0 + 0.12, py0 + 0.12, 0), (sx0 + 0.12, 2.45, 0), fzp, (-1, 0, 0))
    steps(g, -1.4, 1.6, py0, fzp, cheeks=False)
    return dict(stories=2.5, style='Queen Anne Victorian: steep hip with a front cross gable bay, wraparound porch, tall chimneys', hoods=['Garden District', 'Downtown', 'Uptown'])


def b_duplex_one(g):
    x0, x1, y0, y1 = -7.7, 7.7, -4.5, 4.5
    fz, zp = 0.4, 0.4 + 2.5
    s, h = fz + 0.9, fz + 2.15
    S, N, E = [], [], []
    for sg in (-1, 1):
        S += [W(sg * 5.4, 2.0, s - 0.1, h, mull=1), D(sg * 1.5, 0.92, fz, lite=True), W(sg * 3.2, 0.9, s, h)]
        N += [W(sg * 5.6, 1.0, s, h), W(sg * 3.4, 0.8, fz + 1.4, h), D(sg * 1.4, 0.86, fz)]
    ops = {'S': S, 'N': N, 'E': [W(-1.8, 1.0, s, h), W(1.8, 1.0, s, h)], 'W': [W(-1.8, 1.0, s, h), W(1.8, 1.0, s, h)]}
    body(g, x0, x1, y0, y1, fz, zp, ops)
    roof_hip(g, 0, 0, x1 - x0, y1 - y0, zp, 22, ov=0.5)
    for sg in (-1, 1):
        xc = sg * 1.5
        deck(g, xc - 1.0, xc + 1.0, y0 - 1.3, y0, fz - 0.03)
        steps(g, xc, 1.3, y0 - 1.3, fz - 0.03)
        for x in (xc - 0.85, xc + 0.85):
            post(g, x, y0 - 1.15, fz - 0.03, zp - 0.35, s=0.12)
        beam(g, xc - 1.0, xc + 1.0, y0 - 1.3, y0 - 1.05, zp - 0.5, zp - 0.3)
        roof_porch(g, Fr((0, y0, 0), (1, 0, 0)), xc - 1.0, xc + 1.0, 1.3, zp - 0.3, 18, ov=0.2)
        box(g, 'Masonry', -sg * 1.4 - 0.6, -sg * 1.4 + 0.6, y1, y1 + 0.9, Z_FOUND, fz - 0.03, skip='bs')
    return dict(stories=1, style='one-story side-by-side duplex, hip roof, twin covered stoops', hoods=['Westport Acres', 'Riverside', 'North of Patriots Boulevard', 'Pinecrest'])


def b_duplex_two(g):
    x0, x1, y0, y1 = -6.7, 6.7, -3.9, 3.9
    fz = 0.6
    z2 = fz + 2.7 + 0.3
    zp = z2 + 2.5
    s1, h1 = fz + 0.8, fz + 2.25
    s2, h2 = z2 + 0.7, z2 + 2.1
    S, N = [], []
    for sg in (-1, 1):
        S += [D(sg * 1.0, 0.92, fz, lite=True), W(sg * 4.1, 1.7, s1, h1, mull=1), W(sg * 1.3, 0.9, s2, h2), W(sg * 4.1, 0.95, s2, h2)]
        N += [D(sg * 1.2, 0.86, fz), W(sg * 4.0, 1.0, s1, h1), W(sg * 1.6, 0.9, s2, h2), W(sg * 4.6, 0.9, s2, h2)]
    ops = {'S': S, 'N': N,
           'E': [W(-1.4, 0.95, s1, h1), W(1.6, 0.95, s1, h1), W(-1.4, 0.95, s2, h2), W(1.6, 0.95, s2, h2)],
           'W': [W(-1.4, 0.95, s1, h1), W(1.6, 0.95, s1, h1), W(-1.4, 0.95, s2, h2), W(1.6, 0.95, s2, h2)]}
    body(g, x0, x1, y0, y1, fz, zp, ops)
    roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, 30, ov=0.35, rake=0.25)
    for sx in (-1, 1):
        F = Fr((sx * x1, 0, 0), (0, sx, 0))
        flat_window(g, F, -0.35, 0.35, zp + 0.55, zp + 1.25, louver=True)
    # shared full-width porch, divided at the party line
    Dp = 2.2
    py0 = y0 - Dp
    fzp = fz - 0.05
    deck(g, x0, x1, py0, y0, fzp)
    zpp = fz + 2.7
    for x in (x0 + 0.1, -3.3, 0.0, 3.3, x1 - 0.1):
        post(g, x, py0 + 0.12, fzp, zpp - 0.25, s=0.15)
    beam(g, x0, x1, py0, py0 + 0.24, zpp - 0.25, zpp)
    roof_porch(g, Fr((0, y0, 0), (1, 0, 0)), x0, x1, Dp, zpp, 15, ov=0.3)
    railing(g, (0.0, py0 + 0.12, 0), (0.0, y0, 0), fzp, (1, 0, 0), h=0.9)
    for sg in (-1, 1):
        steps(g, sg * 1.0, 1.3, py0, fzp)
    return dict(stories=2, style='two-story side-by-side duplex, side gable, shared front porch', hoods=['Riverside', 'Downtown', 'North End', 'South of the river'])


def b_townhouse(g):
    x0, x1, y0, y1 = -13.8, 13.8, -4.6, 4.6
    fz = 0.5
    z2 = fz + 2.7 + 0.3
    zp = z2 + 2.5
    s1, h1 = fz + 0.8, fz + 2.25
    s2, h2 = z2 + 0.7, z2 + 2.1
    uw = (x1 - x0) / 4
    S, N = [], []
    doors = []
    for i in range(4):
        cx = x0 + uw * (i + 0.5)
        sg = -1 if i % 2 == 0 else 1     # mirrored pairs: doors toward the outer side
        dx = cx + sg * 1.9
        doors.append(dx)
        S += [D(dx, 0.95, fz, lite=True, transom=0.3), W(cx - sg * 1.2, 1.8, s1, h1, mull=1, shutters=False),
              W(cx - 1.6, 0.95, s2, h2, shutters=True), W(cx + 1.6, 0.95, s2, h2, shutters=True)]
        N += [D(cx + sg * 1.9, 0.86, fz), W(cx - sg * 1.0, 1.6, s1, h1, mull=1), W(cx - 1.4, 0.95, s2, h2), W(cx + 1.4, 0.95, s2, h2)]
    ops = {'S': S, 'N': N, 'E': [W(-1.5, 0.95, s2, h2), W(1.5, 0.95, s1, h1)], 'W': [W(-1.5, 0.95, s2, h2), W(1.5, 0.95, s1, h1)]}
    body(g, x0, x1, y0, y1, fz, zp, ops, belt=z2 - 0.12)
    ztop = roof_gable(g, 0, 0, x1 - x0, y1 - y0, zp, 28, ov=0.35, rake=0.25)
    # brick party-wall parapets between the units, just proud of the roof
    tn = math.tan(math.radians(28))
    for i in range(1, 4):
        x = x0 + uw * i
        for s_ in (-1, 1):
            yo = y1 + 0.35
            a = (x - 0.18, s_ * yo, zp + FH + TH)
            b_ = (x + 0.18, s_ * yo, zp + FH + TH)
            top_e, top_r = zp + FH + TH + 0.22, ztop + 0.22
            g.poly([(x - 0.18, s_ * yo, zp + FH + TH - 0.1), (x - 0.18, 0, ztop - 0.1), (x - 0.18, 0, top_r), (x - 0.18, s_ * yo, top_e)], 'Masonry', (-1, 0, 0))
            g.poly([(x + 0.18, s_ * yo, zp + FH + TH - 0.1), (x + 0.18, 0, ztop - 0.1), (x + 0.18, 0, top_r), (x + 0.18, s_ * yo, top_e)], 'Masonry', (1, 0, 0))
            g.poly([(x - 0.18, s_ * yo, top_e), (x + 0.18, s_ * yo, top_e), (x + 0.18, 0, top_r), (x - 0.18, 0, top_r)], 'Masonry', (0, s_, 1))
            g.poly([(x - 0.18, s_ * yo, zp + FH + TH - 0.1), (x + 0.18, s_ * yo, zp + FH + TH - 0.1), (x + 0.18, s_ * yo, top_e), (x - 0.18, s_ * yo, top_e)], 'Masonry', (0, s_, 0))
        box(g, 'Trim', x - 0.08, x + 0.08, y0 - 0.06, y0 + 0.02, fz, zp, skip='tb')
    for dx in doors:
        deck(g, dx - 0.85, dx + 0.85, y0 - 1.1, y0, fz - 0.03)
        steps(g, dx, 1.2, y0 - 1.1, fz - 0.03)
        roof_porch(g, Fr((0, y0, 0), (1, 0, 0)), dx - 0.75, dx + 0.75, 0.75, fz + 2.75, 25, ov=0.12)
        for x in (dx - 0.7, dx + 0.7):   # brackets under the hood
            box(g, 'Trim', x - 0.05, x + 0.05, y0 - 0.6, y0, fz + 2.55, fz + 2.75, skip='')
    return dict(stories=2, style='row of four two-story townhouses, side gable, brick party-wall parapets, door hoods', hoods=['Downtown', 'Uptown', 'Harborview'])


ARCH = [
    ('house-ranch', b_ranch, 'shingle', ['house']),
    ('house-brick-ranch', b_brick_ranch, 'shingle', ['house']),
    ('house-bungalow', b_bungalow, 'shingle', ['house']),
    ('house-cape', b_cape, 'shingle', ['house']),
    ('house-colonial', b_colonial, 'shingle', ['house']),
    ('house-foursquare', b_foursquare, 'shingle', ['house']),
    ('house-farmhouse', b_farmhouse, 'metal', ['house']),
    ('house-shotgun', b_shotgun, 'shingle', ['house']),
    ('house-coastal', b_coastal, 'metal', ['house']),
    ('house-victorian', b_victorian, 'shingle', ['house']),
    ('duplex-one', b_duplex_one, 'shingle', ['duplex']),
    ('duplex-two', b_duplex_two, 'shingle', ['duplex']),
    ('townhouse-row', b_townhouse, 'shingle', ['townhouse']),
]


# ============================================================================ build + export

def to_object(g, name, M):
    xs = [v[0] for v in g.V]
    ys = [v[1] for v in g.V]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    verts = [(x - cx, y - cy, z) for x, y, z in g.V]
    order = ['Wall', 'Roof', 'Trim', 'Glass', 'Door', 'Masonry']
    used = [m for m in order if m in set(g.M)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], g.F)
    for m in used:
        me.materials.append(M[m])
    me.polygons.foreach_set('material_index', [used.index(m) for m in g.M])
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def roof_uvs(o):
    """Shingle courses and metal seams follow each roof plane: u along the eave, v up the slope."""
    me = o.data
    uvl = me.uv_layers.active.data
    for p in me.polygons:
        m = me.materials[p.material_index]
        if not m.name.startswith('Roof') or p.normal.z < 0.15:
            continue
        n = p.normal
        hz = Vector((n.x, n.y, 0))
        if hz.length < 1e-4:
            continue
        hz.normalize()
        e = Vector((-hz.y, hz.x, 0))
        t = m.get('tile', 1.0)
        for li in range(p.loop_start, p.loop_start + p.loop_total):
            v = me.vertices[me.loops[li].vertex_index].co
            u = v.dot(e)
            w = -v.dot(hz) / max(n.z, 0.2)
            uvl[li].uv = (u / t, w / t)


def build(aid, fn, roof, kinds):
    wp.reset()
    M = make_materials(roof)
    g = G()
    meta = fn(g)
    o = to_object(g, 'House', M)
    wp.finalize([o])
    roof_uvs(o)
    for p in o.data.polygons:
        p.use_smooth = False
    path = os.path.join(OUT, aid + '.glb')
    wp.export_glb(path, [o])
    bb = [Vector(c) for c in o.bound_box]
    xs, ys, zs = [c.x for c in bb], [c.y for c in bb], [c.z for c in bb]
    w, d, h = max(xs) - min(xs), max(ys) - min(ys), max(zs)
    tris = wp.tri_count([o])
    entry = {'id': aid, 'kinds': kinds, 'bbox_m': [round(w, 2), round(d, 2), round(h, 2)], 'stories': meta['stories'],
             'best_aspect': round(w / d, 3), 'neighborhoods': meta['hoods'], 'triangles': tris,
             'style': meta['style'], 'roof': roof, 'size_kb': round(os.path.getsize(path) / 1024)}
    print(f'{aid}: bbox {w:.2f} x {d:.2f} x {h:.2f}, z min {min(zs):.2f}, {tris} tris, {entry["size_kb"]} KB')
    return entry


# ============================================================================ renders

def tint(m, hexcol):
    c = wp._rgb(hexcol)
    lin = [float(v) ** 2.2 for v in c]
    nt = m.node_tree
    bs = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    inp = bs.inputs['Base Color']
    if inp.is_linked:
        src = inp.links[0].from_socket
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        nt.links.new(src, mix.inputs[6])
        mix.inputs[7].default_value = (*lin, 1)
        nt.links.new(mix.outputs[2], inp)
    else:
        dv = inp.default_value
        inp.default_value = (dv[0] * lin[0], dv[1] * lin[1], dv[2] * lin[2], 1)


def place(aid, loc, rot=0.0, scale=(1, 1, 1), look=None):
    bpy.ops.import_scene.gltf(filepath=os.path.join(OUT, aid + '.glb'))
    objs = list(bpy.context.selected_objects)
    for o in objs:
        if o.parent is None:
            o.location = loc
            o.rotation_euler = (0, 0, rot)
            o.scale = scale
        if look and o.type == 'MESH':
            for slot in o.material_slots:
                m = slot.material
                if m is None:
                    continue
                key = m.name.split('.')[0]
                if key in look:
                    m2 = m.copy()
                    slot.material = m2
                    tint(m2, look[key])
    return objs


LOOKS = [
    dict(Wall='#f2efe6', Roof='#55575a', Door='#7a2e2a'), dict(Wall='#ebe4d2', Roof='#4a4b4e', Door='#22272e'),
    dict(Wall='#b9c3cb', Roof='#3f4043', Door='#f2efe6'), dict(Wall='#c6cdb6', Roof='#5a524b', Door='#2f3b52'),
    dict(Wall='#f6f4ef', Roof='#3a3c40', Door='#22272e'), dict(Wall='#d8c8a8', Roof='#6b6660', Door='#3d4f3e'),
    dict(Wall='#e8e3d6', Roof='#9c9fa2', Door='#7a2e2a'), dict(Wall='#a9b6a4', Roof='#4d4a46', Door='#f2efe6'),
    dict(Wall='#efe3bf', Roof='#a9aeb2', Door='#2f3b52'), dict(Wall='#c8b8a6', Roof='#3f4043', Door='#5b3f2a'),
    dict(Wall='#d9d6cf', Roof='#606265', Door='#3d4f3e'), dict(Wall='#e6d6c3', Roof='#55575a', Door='#22272e'),
    dict(Wall='#9fa9ad', Roof='#4a4b4e', Door='#8a6d3b'),
]


def fast_cycles():
    """Adaptive sampling and fewer bounces: the same look at a fraction of the cost on a shared CPU."""
    sc = bpy.context.scene
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.03
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 2
    sc.cycles.transmission_bounces = 2


def render_lineup(index):
    wp.reset()
    by = {e['id']: e for e in index}
    rows = [['house-ranch', 'house-brick-ranch', 'house-bungalow', 'house-cape', 'house-colonial'],
            ['house-foursquare', 'house-farmhouse', 'house-shotgun', 'house-coastal', 'house-victorian'],
            ['duplex-one', 'duplex-two', 'townhouse-row']]
    k = 0
    for r, row in enumerate(rows):
        widths = [by[a]['bbox_m'][0] for a in row]
        gap = 5.0
        total = sum(widths) + gap * (len(row) - 1)
        x = -total / 2
        y = r * 21.0
        for a, w in zip(row, widths):
            place(a, (x + w / 2, y, 0), look=LOOKS[k % len(LOOKS)])
            x += w + gap
            k += 1
    samples, res = (24, (640, 400)) if PREVIEW else (96, (1600, 1000))
    wp.render_rig(samples=samples, res=res, sun_elev=40, sun_az=215, threads=2, ground_size=3000)
    fast_cycles()
    wp.camera((0, -66, 44), (0, 15, 0), lens=30)
    wp.render(os.path.join(RENDERS, 'archetypes-residential' + ('-preview' if PREVIEW else '') + '.jpg'))


def render_street(index):
    wp.reset()
    road = wp.mat('RenderRoad', tex=wp.tex_ground('render_asphalt', 'asphalt', n=512, tile=4.0))
    conc = wp.mat('RenderConcrete', tex=wp.tex_ground('render_concrete', 'concrete', n=512, tile=3.0))
    L = 170.0
    wp.box('Road', 7.5, L, 0.02, loc=(0, 0, 0.0), material=road, rot_z=0)
    # houses along both sides, 40 m lots, fronts to the road (road along y, x = 0)
    north = [('house-colonial', (1.0, 1.05, 1.0)), ('house-bungalow', (1.05, 0.9, 0.95)), ('house-cape', (1.1, 1.0, 1.0)),
             ('house-foursquare', (1.0, 1.1, 1.0))]
    south = [('house-ranch', (1.15, 1.0, 1.0)), ('house-victorian', (0.95, 1.0, 1.05)), ('duplex-two', (1.0, 0.95, 1.1)),
             ('house-farmhouse', (0.9, 1.0, 1.0))]
    looks = [LOOKS[i] for i in (0, 2, 3, 5, 7, 9, 10, 1)]
    k = 0
    for side, items in ((1, north), (-1, south)):
        for i, (aid, sc) in enumerate(items):
            e = next(x for x in index if x['id'] == aid)
            w, d, h = e['bbox_m']
            y = -60 + i * 40 + (20 if side < 0 else 0)
            setback = 3.75 + 9.0 + d * sc[1] / 2
            x = side * setback
            rot = -math.pi / 2 if side > 0 else math.pi / 2
            place(aid, (x, y, 0), rot=rot, scale=sc, look=looks[k])
            k += 1
            # driveway from the road edge past the house side
            dy = y + side * -1 * 0 + (w * sc[0] / 2 + 2.0) * (1 if i % 2 == 0 else -1)
            dl = 9.0 + d * sc[1] * 0.6
            o = wp.box(f'Drive{k}', dl, 3.2, 0.03, loc=(side * (3.75 + dl / 2), dy, 0.0), material=conc)
            wp.uv_box(o)
            o2 = wp.box(f'Walk{k}', 9.0, 1.2, 0.03, loc=(side * (3.75 + 4.5), y, 0.0), material=conc)
            wp.uv_box(o2)
    wp.uv_box(bpy.data.objects['Road'])
    samples, res = (24, (640, 400)) if PREVIEW else (96, (1600, 1000))
    wp.render_rig(samples=samples, res=res, sun_elev=42, sun_az=135, threads=2, ground_size=3000)
    fast_cycles()
    wp.camera((-34, -88, 40), (4, -6, 0), lens=40)
    wp.render(os.path.join(RENDERS, 'archetypes-street' + ('-preview' if PREVIEW else '') + '.jpg'))


def main():
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, 'index-residential.json')
    only = ARGS[ARGS.index('--only') + 1].split(',') if '--only' in ARGS else None
    if '--renders-only' not in ARGS:
        old = json.load(open(idx_path)) if os.path.exists(idx_path) else []
        old = {e['id']: e for e in old}
        for aid, fn, roof, kinds in ARCH:
            if only and aid not in only:
                continue
            old[aid] = build(aid, fn, roof, kinds)
        index = [old[a[0]] for a in ARCH if a[0] in old]
        with open(idx_path, 'w') as f:
            json.dump(index, f, indent=1)
        print('wrote', idx_path)
    index = json.load(open(idx_path))
    if '--no-render' in ARGS:
        return
    if '--street-only' not in ARGS:
        render_lineup(index)
    if '--lineup-only' not in ARGS:
        render_street(index)


if __name__ == '__main__':
    main()
