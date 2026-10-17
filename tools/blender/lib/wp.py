"""Shared Blender toolkit for the Westport models.

Every model script imports this module so all assets share one scale, one set of
materials and one render rig. Run scripts with the Blender Python module:

    python3 tools/blender/homes/monet_williams_house.py

Conventions (see docs/ASSET-SPEC.md):
  meters, Blender +Z up, the street-facing front faces -Y, origin = footprint
  center at finished grade. glTF export converts to +Y up, so the front faces +Z
  in the exported file.
"""
import math
import os
import sys
import tempfile

import bpy  # noqa: E402  (bpy must load before bmesh and mathutils)
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TEX_DIR = os.environ.get('WP_TEX_DIR', os.path.join(tempfile.gettempdir(), 'wp-tex'))
os.makedirs(TEX_DIR, exist_ok=True)


# ----------------------------------------------------------------------------- scene

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for c in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.objects):
        for x in list(c):
            c.remove(x)


def col(name):
    """Get or make a collection linked to the scene."""
    c = bpy.data.collections.get(name)
    if not c:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def link(obj, collection=None):
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


# ----------------------------------------------------------------------------- textures
# Each texture is a seamless tile covering `tile` meters of real surface. UVs are
# projected in units of the material's tile (see uv_box), so one repeat = one tile.

def _rng(seed):
    return np.random.default_rng(seed)


def _noise(n, scale, rng, octaves=4):
    """Tileable value noise in [0,1], shape (n, n)."""
    out = np.zeros((n, n), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        cells = max(1, int(scale * (2 ** o)))
        g = rng.random((cells, cells)).astype(np.float32)
        g = np.pad(g, ((0, 1), (0, 1)), mode='wrap')
        xs = np.linspace(0, cells, n, endpoint=False)
        i = xs.astype(int)
        f = xs - i
        f = f * f * (3 - 2 * f)
        a = g[i][:, i] * (1 - f)[None, :] + g[i][:, i + 1] * f[None, :]
        b = g[i + 1][:, i] * (1 - f)[None, :] + g[i + 1][:, i + 1] * f[None, :]
        out += amp * (a * (1 - f)[:, None] + b * f[:, None])
        tot += amp
        amp *= 0.5
    return out / tot


def _save(arr, name, quality=90):
    path = os.path.join(TEX_DIR, name + '.jpg')
    Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8)).save(path, quality=quality)
    return path


def _normal_from_height(h, strength):
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    nz = np.ones_like(h)
    l = np.sqrt(gx * gx + gy * gy + nz * nz)
    # OpenGL convention (glTF): +Y up in tangent space, image row 0 = top
    return np.stack([(-gx / l) * 0.5 + 0.5, (gy / l) * 0.5 + 0.5, (nz / l) * 0.5 + 0.5], -1)


def _rgb(c):
    if isinstance(c, str):
        c = c.lstrip('#')
        return np.array([int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)
    return np.array(c[:3], np.float32)


def tex_brick(key, color='#8a4b38', mortar='#b9b1a3', n=1024, seed=1, var=0.10, tile=1.0, header_every=6):
    """Running-bond brick: 0.203 x 0.057 m bricks, 0.01 m joints. Returns (albedo, normal, tile)."""
    rng = _rng(seed)
    px = n / tile
    bw, bh, j = 0.2134, 0.0667, 0.0095  # brick + joint fits 1 m evenly: 4.68 courses... snapped below
    rows = int(round(tile / bh)); bh = tile / rows
    cols = int(round(tile / bw)); bw = tile / cols
    y, x = np.mgrid[0:n, 0:n] / px
    r = (y / bh).astype(int)
    off = (r % 2) * 0.5 * bw
    cx = ((x + off) / bw).astype(int) % cols
    lx = (x + off) % bw
    ly = y % bh
    joint = (lx < j) | (ly < j)
    base = _rgb(color)
    cell_rand = rng.random((rows + 1, cols + 1)).astype(np.float32)
    cr = cell_rand[r % rows, cx]
    tint = (cr - 0.5) * 2 * var
    burnt = (rng.random((rows + 1, cols + 1)) < 0.08)[r % rows, cx]
    nz = _noise(n, 24 * tile, rng, 3)
    alb = base[None, None, :] * (1 + tint[..., None]) * (0.88 + 0.24 * nz[..., None])
    alb = np.where(burnt[..., None], alb * 0.72, alb)
    alb = np.where(joint[..., None], _rgb(mortar)[None, None, :] * (0.9 + 0.2 * nz[..., None]), alb)
    h = np.where(joint, 0.0, 1.0) * 0.6 + nz * 0.25
    return _save(alb, key), _save(_normal_from_height(h, 2.2), key + '_n'), tile


def tex_siding(key, color='#c3ccd6', exposure=0.127, n=1024, seed=2, tile=1.0, vertical=False):
    """Painted lap siding (clapboard). exposure = visible board height in meters."""
    rng = _rng(seed)
    px = n / tile
    rows = int(round(tile / exposure)); exposure = tile / rows
    y, x = np.mgrid[0:n, 0:n] / px
    if vertical:
        x, y = y, x
    t = (y % exposure) / exposure  # 0 at bottom edge of a board's top (shadow line at t ~ 0)
    h = t  # boards taper: thick at the bottom, thin at the top
    grain = _noise(n, 40 * tile, rng, 3)
    shade = 0.80 + 0.20 * np.clip(t * 6, 0, 1)
    alb = _rgb(color)[None, None, :] * (shade * (0.95 + 0.07 * grain))[..., None]
    return _save(alb, key), _save(_normal_from_height(h * 0.8 + grain * 0.05, 3.0), key + '_n'), tile


def tex_shingles(key, color='#4d4f52', n=1024, seed=3, tile=1.0, row=0.142, kind='architectural'):
    """Asphalt shingles. kind='architectural' (dimensional) or 'slate'."""
    rng = _rng(seed)
    px = n / tile
    rows = int(round(tile / row)); row = tile / rows
    y, x = np.mgrid[0:n, 0:n] / px
    r = (y / row).astype(int)
    tab = 0.33 if kind == 'architectural' else 0.30
    cols = int(round(tile / tab)); tab = tile / cols
    rr = _rng(seed + 7).random((rows + 1, cols + 2)).astype(np.float32)
    jitter = rr[r % rows, 0] * tab
    cx = ((x + jitter + (r % 2) * tab * 0.5) / tab).astype(int) % cols
    lx = (x + jitter + (r % 2) * tab * 0.5) % tab
    t = (y % row) / row
    gap = lx < 0.006 * (1 if kind == 'slate' else 1.5)
    cell = rr[r % rows, cx]
    gran = _noise(n, 90 * tile, rng, 2)
    base = _rgb(color)
    tone = 1 + (cell - 0.5) * (0.35 if kind == 'architectural' else 0.18)
    alb = base[None, None, :] * (tone * (0.78 + 0.3 * gran) * (0.72 + 0.28 * t))[..., None]
    alb = np.where(gap[..., None], alb * 0.45, alb)
    h = t * 0.7 + gran * 0.15 - gap * 0.5
    return _save(alb, key), _save(_normal_from_height(h, 2.5), key + '_n'), tile


def tex_metal(key, color='#9aa1a6', rust=0.0, n=1024, seed=4, tile=1.0, rib=0.0762, seam=False):
    """Corrugated (rib spacing in m) or standing-seam (seam=True, 0.45 m panels) metal roofing."""
    rng = _rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    if seam:
        pn = int(round(tile / 0.45)); pw = tile / pn
        h = np.clip(1 - np.abs((x % pw) - 0.0) / 0.02, 0, 1)
    else:
        rn = int(round(tile / rib)); rw = tile / rn
        h = 0.5 + 0.5 * np.cos(2 * np.pi * x / rw)
    nz = _noise(n, 16 * tile, rng, 4)
    streak = _noise(n, 6 * tile, _rng(seed + 1), 3)
    base = _rgb(color)
    alb = base[None, None, :] * (0.85 + 0.2 * nz[..., None]) * (0.92 + 0.08 * h[..., None])
    if rust > 0:
        rmask = np.clip((nz * 0.6 + streak * 0.6 - (1.05 - rust)) * 4, 0, 1)[..., None]
        rustc = np.array([0.42, 0.22, 0.12], np.float32) * (0.8 + 0.4 * nz[..., None])
        alb = alb * (1 - rmask) + rustc * rmask
    return _save(alb, key), _save(_normal_from_height(h, 1.6), key + '_n'), tile


def tex_wood(key, color='#8b6a4a', n=1024, seed=5, tile=1.0, board=0.14, weathered=0.0):
    rng = _rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    bn = int(round(tile / board)); board = tile / bn
    b = (x / board).astype(int)
    off = _rng(seed + 3).random(bn + 1)[b % bn] * tile
    grain = np.sin((y + off) * 90 + _noise(n, 8, rng, 3) * 12) * 0.5 + 0.5
    gap = (x % board) < 0.005
    tone = 1 + (_rng(seed + 9).random(bn + 1)[b % bn] - 0.5) * 0.25
    c = _rgb(color)
    if weathered:
        c = c * (1 - weathered) + np.array([0.55, 0.53, 0.5]) * weathered
    alb = c[None, None, :] * (tone * (0.82 + 0.18 * grain))[..., None]
    alb = np.where(gap[..., None], alb * 0.4, alb)
    return _save(alb, key), _save(_normal_from_height(grain * 0.2 - gap * 1.0, 2.0), key + '_n'), tile


def tex_ground(key, kind='concrete', color=None, n=1024, seed=6, tile=2.0):
    """concrete (with control joints every 1.5 m), asphalt, gravel, pavers, stucco."""
    rng = _rng(seed)
    px = n / tile
    y, x = np.mgrid[0:n, 0:n] / px
    nz = _noise(n, 30 * tile, rng, 5)
    fine = rng.random((n, n)).astype(np.float32)
    defaults = dict(concrete='#b8b4ab', asphalt='#3d3d3f', gravel='#a39a8b', pavers='#9c5b45', stucco='#e8e2d6')
    base = _rgb(color or defaults[kind])
    h = nz * 0.3
    if kind == 'concrete':
        alb = base * (0.9 + 0.12 * nz[..., None] + 0.04 * fine[..., None])
        jx = (x % 1.5) < 0.008; jy = (y % 1.5) < 0.008
        alb = np.where((jx | jy)[..., None], alb * 0.6, alb); h = h - (jx | jy) * 0.6
    elif kind == 'asphalt':
        alb = base * (0.85 + 0.2 * nz[..., None] + 0.25 * (fine[..., None] - 0.5))
    elif kind == 'gravel':
        g = _noise(n, 220 * tile, rng, 2)
        alb = base * (0.7 + 0.5 * g[..., None] + 0.1 * fine[..., None]); h = g
    elif kind == 'pavers':
        pw, ph = 0.2, 0.1
        r = (y / ph).astype(int)
        lx = (x + (r % 2) * pw / 2) % pw; ly = y % ph
        j = (lx < 0.006) | (ly < 0.006)
        cell = _rng(seed + 2).random((int(tile / ph) + 2, int(tile / pw) + 3))[r % int(tile / ph), (((x + (r % 2) * pw / 2) / pw).astype(int)) % int(tile / pw)]
        alb = base * ((0.85 + 0.25 * cell) * (0.9 + 0.1 * nz))[..., None]
        alb = np.where(j[..., None], np.array([0.55, 0.52, 0.48]), alb); h = 1 - j
    else:  # stucco
        alb = base * (0.93 + 0.1 * nz[..., None] + 0.03 * fine[..., None]); h = nz + fine * 0.2
    return _save(alb, key), _save(_normal_from_height(h, 1.5), key + '_n'), tile


def tex_grass(key, n=1024, seed=7, tile=4.0, color='#5f7d3a'):
    """Lawn texture, used only for render ground planes (the map draws its own ground)."""
    rng = _rng(seed)
    nz = _noise(n, 12 * tile, rng, 5)
    blades = rng.random((n, n)).astype(np.float32)
    base = _rgb(color)
    alb = base * (0.75 + 0.35 * nz[..., None] + 0.18 * (blades[..., None] - 0.5))
    alb[..., 0] += (nz - 0.5) * 0.05
    return _save(alb, key), _save(_normal_from_height(blades * 0.3 + nz * 0.3, 2.0), key + '_n'), tile


# ----------------------------------------------------------------------------- materials

def _img(path, noncolor=False):
    name = os.path.basename(path)
    img = bpy.data.images.get(name) or bpy.data.images.load(path)
    if noncolor:
        img.colorspace_settings.name = 'Non-Color'
    return img


def mat(name, color='#ffffff', rough=0.6, metal=0.0, tex=None, normal_strength=1.0, emission=None,
        alpha=None, transmission=0.0, ior=1.45, double_sided=False):
    """Principled material that exports cleanly to glTF.
    tex: (albedo_path, normal_path, tile_m) from a tex_* function, or None for a flat color.
    The material keeps its tile size in m['tile'] for uv_box."""
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
    c = _rgb(color)
    bs.inputs['Base Color'].default_value = (*[float(v) ** 2.2 for v in c], 1)
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Metallic'].default_value = metal
    m['tile'] = 1.0
    if tex:
        alb, nrm, tile = tex
        t = nt.nodes.new('ShaderNodeTexImage'); t.image = _img(alb)
        if color.lower() not in ('#ffffff', '#fff'):
            mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
            mix.inputs['Factor'].default_value = 1.0
            nt.links.new(t.outputs['Color'], mix.inputs[6])
            mix.inputs[7].default_value = (*[float(v) ** 2.2 for v in c], 1)
            nt.links.new(mix.outputs[2], bs.inputs['Base Color'])
        else:
            nt.links.new(t.outputs['Color'], bs.inputs['Base Color'])
        if nrm:
            tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = _img(nrm, True)
            nm = nt.nodes.new('ShaderNodeNormalMap'); nm.inputs['Strength'].default_value = normal_strength
            nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
            nt.links.new(nm.outputs['Normal'], bs.inputs['Normal'])
        m['tile'] = float(tile)
    if emission:
        bs.inputs['Emission Color'].default_value = (*_rgb(emission[0]), 1)
        bs.inputs['Emission Strength'].default_value = emission[1]
    if alpha is not None:
        bs.inputs['Alpha'].default_value = alpha
        try:
            m.surface_render_method = 'BLENDED'
        except Exception:
            pass
    if transmission:
        bs.inputs['Transmission Weight'].default_value = transmission
        bs.inputs['IOR'].default_value = ior
    m.use_backface_culling = not double_sided
    return m


def glass(name='Glass', tint='#2a3238'):
    """Window glass: dark, glossy, slightly reflective. Reads correctly in glTF viewers and Cycles."""
    return mat(name, tint, rough=0.05, metal=0.0, ior=1.5)


# ----------------------------------------------------------------------------- geometry

def obj_from_bmesh(name, bm, material=None, collection=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    link(o, collection)
    if material is not None:
        mats = material if isinstance(material, (list, tuple)) else [material]
        for mm in mats:
            o.data.materials.append(mm)
    return o


def box(name, sx, sy, sz, loc=(0, 0, 0), material=None, rot_z=0.0, collection=None, bevel=0.0):
    """Axis box with its BOTTOM center at loc (z = base)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, sz / 2), verts=bm.verts)
    if rot_z:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rot_z, 3, 'Z'), verts=bm.verts)
    bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    o = obj_from_bmesh(name, bm, material, collection)
    if bevel:
        add_bevel(o, bevel)
    return o


def cyl(name, r, h, loc=(0, 0, 0), material=None, seg=16, r_top=None, collection=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r if r_top is None else r_top, depth=h)
    bmesh.ops.translate(bm, vec=(loc[0], loc[1], loc[2] + h / 2), verts=bm.verts)
    return obj_from_bmesh(name, bm, material, collection)


def lathe(name, profile, loc=(0, 0, 0), material=None, seg=12, collection=None):
    """Turned shape from a profile [(radius, z), ...] bottom to top (porch posts, balusters, urns)."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        ring = [bm.verts.new((loc[0] + r * math.cos(2 * math.pi * i / seg), loc[1] + r * math.sin(2 * math.pi * i / seg), loc[2] + z)) for i in range(seg)]
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for i in range(seg):
            bm.faces.new((a[i], a[(i + 1) % seg], b[(i + 1) % seg], b[i]))
    bm.faces.new(rings[-1]); bm.faces.new(list(reversed(rings[0])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bmesh(name, bm, material, collection)


def prism(name, pts, z0, z1, material=None, collection=None):
    """Extrude a closed 2D polygon [(x, y), ...] from z0 to z1."""
    bm = bmesh.new()
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    n = len(pts)
    bm.faces.new(list(reversed(bot))); bm.faces.new(top)
    for i in range(n):
        bm.faces.new((bot[i], bot[(i + 1) % n], top[(i + 1) % n], top[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return obj_from_bmesh(name, bm, material, collection)


def roof_hip(name, w, d, z, pitch_deg, overhang=0.45, material=None, thickness=0.12, collection=None, center=(0, 0), gable=False):
    """Hip (or gable, gable=True) roof over a w (x) by d (y) rectangle whose eaves sit at height z.
    Ridge runs along the longer side. Returns the roof object (with thickness and a fascia band)."""
    W, D = w + 2 * overhang, d + 2 * overhang
    t = math.tan(math.radians(pitch_deg))
    bm = bmesh.new()
    cx, cy = center
    if W >= D:
        rise = D / 2 * t
        ridge = (W - D) / 2 if not gable else W / 2
        v = [bm.verts.new(p) for p in [(-W / 2, -D / 2, 0), (W / 2, -D / 2, 0), (W / 2, D / 2, 0), (-W / 2, D / 2, 0), (-ridge, 0, rise), (ridge, 0, rise)]]
        if gable:
            faces = [(v[0], v[1], v[5], v[4]), (v[2], v[3], v[4], v[5]), (v[1], v[2], v[5]), (v[3], v[0], v[4])]
        else:
            faces = [(v[0], v[1], v[5], v[4]), (v[2], v[3], v[4], v[5]), (v[1], v[2], v[5]), (v[3], v[0], v[4])]
    else:
        rise = W / 2 * t
        ridge = (D - W) / 2 if not gable else D / 2
        v = [bm.verts.new(p) for p in [(-W / 2, -D / 2, 0), (W / 2, -D / 2, 0), (W / 2, D / 2, 0), (-W / 2, D / 2, 0), (0, -ridge, rise), (0, ridge, rise)]]
        faces = [(v[1], v[2], v[5], v[4]), (v[3], v[0], v[4], v[5]), (v[0], v[1], v[4]), (v[2], v[3], v[5])]
    for f in faces:
        bm.faces.new(f)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.translate(bm, vec=(cx, cy, z), verts=bm.verts)
    o = obj_from_bmesh(name, bm, material, collection)
    if thickness:
        s = o.modifiers.new('thick', 'SOLIDIFY'); s.thickness = thickness; s.offset = -1
    return o


def add_bevel(o, width=0.01, segments=1):
    b = o.modifiers.new('bevel', 'BEVEL'); b.width = width; b.segments = segments; b.limit_method = 'ANGLE'
    return o


def array_along(o, count, offset, name=None):
    """Duplicate an object `count` times at a fixed offset vector; returns the list (original first)."""
    out = [o]
    for i in range(1, count):
        c = o.copy(); c.data = o.data
        c.location = Vector(o.location) + Vector(offset) * i
        if name:
            c.name = f'{name}.{i:03d}'
        for coll in o.users_collection:
            coll.objects.link(c)
        out.append(c)
    return out


def join(objs, name):
    """Apply modifiers and join objects into one mesh object named `name`."""
    objs = [o for o in objs if o is not None]
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.modifiers or o.data.users > 1:
            ev = o.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(ev)
            o.modifiers.clear()
            o.data = me
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    j = bpy.context.view_layer.objects.active
    j.name = name; j.data.name = name
    return j


def uv_box(o, tile=None):
    """Box-project UVs in meters, divided by each face material's tile size (m['tile'])."""
    me = o.data
    if not me.uv_layers:
        me.uv_layers.new(name='UVMap')
    bm = bmesh.new(); bm.from_mesh(me)
    uv = bm.loops.layers.uv.active
    mw = o.matrix_world
    for f in bm.faces:
        mm = me.materials[f.material_index] if me.materials else None
        t = tile or (mm.get('tile', 1.0) if mm else 1.0)
        n = f.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        for l in f.loops:
            p = mw @ l.vert.co
            if ax == 2:
                u, v = p.x, p.y
            elif ax == 0:
                u, v = p.y * (1 if n.x > 0 else -1), p.z
            else:
                u, v = p.x * (-1 if n.y > 0 else 1), p.z
            l[uv].uv = (u / t, v / t)
    bm.to_mesh(me); bm.free()
    return o


def finalize(objs):
    """Apply modifiers, box-UV every mesh, shade smooth by angle. Call before export."""
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != 'MESH':
            continue
        if o.modifiers:
            ev = o.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(ev)
            o.modifiers.clear(); o.data = me
        uv_box(o)
    return objs


def tri_count(objs):
    n = 0
    for o in objs:
        if o.type == 'MESH':
            o.data.calc_loop_triangles()
            n += len(o.data.loop_triangles)
    return n


# ----------------------------------------------------------------------------- export

def export_glb(path, objs, image_format='JPEG', quality=86):
    """Export only `objs` to a GLB. Front faces -Y in Blender, which becomes +Z in glTF (+Y up)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    kw = dict(filepath=path, export_format='GLB', use_selection=True, export_apply=True, export_yup=True,
              export_texcoords=True, export_normals=True, export_materials='EXPORT', export_cameras=False,
              export_lights=False, export_extras=False)
    try:
        bpy.ops.export_scene.gltf(**kw, export_image_format=image_format, export_jpeg_quality=quality)
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)
    print(f'exported {path}: {os.path.getsize(path) / 1e6:.2f} MB, {tri_count(objs)} tris')


# ----------------------------------------------------------------------------- render rig

def render_rig(samples=96, res=(1600, 1000), sun_elev=38, sun_az=215, threads=2, exposure=0.0, ground=True, ground_size=400):
    """Cycles + physical sky + lawn ground plane (render only, never exported). sun_az: compass degrees
    the sun comes FROM, measured from +Y (north in the model's local frame is +Y = back of the house)."""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    sc.render.threads_mode = 'FIXED'; sc.render.threads = threads
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    sc.view_settings.exposure = exposure
    w = bpy.data.worlds.new('Sky'); sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    sky = nt.nodes.new('ShaderNodeTexSky')
    for t in ('MULTIPLE_SCATTERING', 'NISHITA', 'HOSEK_WILKIE'):
        try:
            sky.sky_type = t; break
        except Exception:
            continue
    try:
        sky.sun_elevation = math.radians(sun_elev); sky.sun_rotation = math.radians(sun_az)
        sky.sun_disc = False
    except Exception:
        pass
    bg = nt.nodes['Background']; bg.inputs['Strength'].default_value = 0.35
    nt.links.new(sky.outputs[0], bg.inputs[0])
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    sun.data.energy = 4.2; sun.data.angle = math.radians(0.6)
    sun.data.color = (1.0, 0.96, 0.9)
    az = math.radians(sun_az); el = math.radians(sun_elev)
    d = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    sun.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    g = None
    if ground:
        gm = mat('RenderLawn', tex=tex_grass('render_lawn'))
        bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=ground_size / 2)
        g = obj_from_bmesh('RenderGround', bm, gm); uv_box(g)
        g.location.z = -0.01
    return sun, g


def camera(loc, target, lens=35):
    sc = bpy.context.scene
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    cam.data.lens = lens; cam.data.clip_end = 5000
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam
    return cam


def render(out_jpg, quality=88):
    """Render the scene camera and save a JPEG (the PNG intermediate is removed)."""
    os.makedirs(os.path.dirname(out_jpg), exist_ok=True)
    png = out_jpg[:-4] + '.tmp.png'
    bpy.context.scene.render.filepath = png
    bpy.ops.render.render(write_still=True)
    Image.open(png).convert('RGB').save(out_jpg, quality=quality)
    os.remove(png)
    print('rendered', out_jpg)


if __name__ == '__main__':
    # smoke test: a tiny brick house with a hip roof, exported and rendered
    reset()
    brick = mat('Brick', tex=tex_brick('brick_red'))
    roof = mat('Roof', tex=tex_shingles('shingle_grey'), rough=0.85)
    body = box('Body', 10, 8, 6, material=brick)
    r = roof_hip('Roof', 10, 8, 6, 30, material=roof)
    objs = finalize([body, r])
    out = os.path.join(TEX_DIR, 'smoke.glb')
    export_glb(out, objs)
    render_rig(samples=16, res=(480, 300))
    camera((14, -18, 9), (0, 0, 3))
    render(os.path.join(TEX_DIR, 'smoke.jpg'))
