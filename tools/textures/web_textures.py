"""Make the tileable surface textures the web map uses (assets/tex/*.jpg).

Uses the same procedural generators as the Blender models (tools/blender/lib/wp.py), so the
town and the hero homes share one material language. Run: python3 tools/textures/web_textures.py
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'assets', 'tex')
os.makedirs(OUT, exist_ok=True)
os.environ['WP_TEX_DIR'] = OUT
sys.path.insert(0, os.path.join(HERE, '..', 'blender', 'lib'))
import wp  # noqa: E402

N = 512
# neutral (near-white) textures are tinted per building in the shader
wp.tex_shingles('roof_shingle', color='#d9d9d9', n=N, tile=2.0)
wp.tex_shingles('roof_slate', color='#d4d4d4', n=N, tile=2.0, kind='slate', row=0.18)
wp.tex_metal('roof_metal', color='#e2e2e2', n=N, tile=1.0)
wp.tex_metal('roof_metal_rust', color='#d8d8d8', rust=0.55, n=N, tile=2.0, rib=0.0762)
wp.tex_siding('wall_siding', color='#ececec', n=N, tile=2.0)
wp.tex_brick('wall_brick', color='#9a5640', mortar='#b8b0a2', n=N, tile=2.0)
wp.tex_ground('wall_stucco', kind='stucco', color='#ececec', n=N, tile=2.0)
wp.tex_ground('pave_concrete', kind='concrete', color='#c2bdb3', n=N, tile=3.0)
wp.tex_ground('pave_asphalt', kind='asphalt', color='#47474a', n=N, tile=4.0)
wp.tex_ground('pave_gravel', kind='gravel', color='#9c917f', n=N, tile=4.0)
wp.tex_ground('pave_brick', kind='pavers', color='#9a5a45', n=N, tile=2.0)
wp.tex_grass('ground_grass', n=N, tile=4.0, color='#6f8a45')


def water_normal(n=512, seed=11):
    """Tileable wind-ripple normal map: a sum of periodic waves whose wave vectors are integers."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] / n * 2 * np.pi
    h = np.zeros((n, n), np.float32)
    for _ in range(48):
        kx, ky = rng.integers(-14, 15, 2)
        if kx == 0 and ky == 0:
            continue
        k = np.hypot(kx, ky)
        amp = 1.0 / (k ** 1.35)
        h += amp * np.sin(kx * x + ky * y + rng.random() * 6.283)
    h = (h - h.min()) / (h.max() - h.min())
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 6
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 6
    l = np.sqrt(gx * gx + gy * gy + 1)
    rgb = np.stack([-gx / l, gy / l, 1 / l], -1) * 0.5 + 0.5
    Image.fromarray((rgb * 255).astype(np.uint8)).save(os.path.join(OUT, 'water_n.jpg'), quality=92)


water_normal()
for f in sorted(os.listdir(OUT)):
    print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, 'KB')
