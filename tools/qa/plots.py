"""Before/after plots for the Atlas QA audit (called by tools/qa/audit.mjs; needs Pillow).

Usage: python3 -I tools/qa/plots.py <repo root> < specs.json
specs.json: [{"file": "renders/qa/01-x.png", "title": "...", "bbox": [x0, y0, x1, y1], "note": "...",
              "mark": [[x, y], ...]}, ...]
Each PNG shows the Atlas as it is (left) and with data/qa.json applied (right), at the same scale.
"""
import json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

root = sys.argv[1]
specs = json.load(sys.stdin)
W = json.load(open(os.path.join(root, 'data/wpdata.json')))
Q = json.load(open(os.path.join(root, 'data/qa.json')))
GZ = json.load(open(os.path.join(root, 'data/gaz.json')))
CLS = ['trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'track', 'path', 'motorway']
HALF = dict(trunk=7.5, primary=6.5, secondary=5.5, tertiary=4.5, residential=3.75, service=2.75, track=2.0, path=1.0, motorway=9)
COL = dict(water=(169, 201, 222), land=(243, 240, 233), marsh=(214, 228, 200), creek=(150, 190, 220), road=(255, 255, 255), roadcase=(176, 168, 156),
           major=(250, 214, 140), bridge=(190, 120, 110), track=(185, 168, 142), rail=(110, 105, 100), pier=(176, 150, 110), bld=(150, 140, 128),
           bldline=(110, 102, 92), removed=(214, 60, 50), replaced=(232, 140, 30), added=(40, 150, 70), txt=(40, 36, 32), place=(160, 40, 70), moved=(30, 110, 200))


def font(sz):
    for f in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf']:
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


F_T, F_S = font(15), font(12)
pts = lambda flat, k=1: [(flat[i] / k, flat[i + 1] / k) for i in range(0, len(flat) - 1, 2)]
B0 = [pts(b[2:], 2) for b in W['b']]
rem = set(Q['fixes']['remove_buildings'])
rep = {e['i']: pts(e['poly']) for e in Q['fixes']['replace_buildings']}
add = [pts(e['poly']) for e in Q['fixes']['add_buildings']]
roads0 = [pts(r[3]) for r in W['roads']]
roads1 = [list(p) for p in roads0]
for s in Q['fixes']['road_snaps']:
    roads1[s['road']][s['vertex']] = tuple(s['to'])
places0 = {p['id']: tuple(p['at']) for p in GZ['places']}
places1 = dict(places0)
for m in Q['fixes']['move_places']:
    places1[m['id']] = tuple(m['at'])
labels0 = [(l['text'], tuple(l['at'])) for l in W['labels'] if l.get('at')]
labels1 = []
for t, a in labels0:
    mv = next((m for m in Q['fixes']['move_labels'] if m['text'] == t and abs(m['was'][0] - a[0]) < 0.5 and abs(m['was'][1] - a[1]) < 0.5), None)
    labels1.append((t, tuple(mv['at']) if mv else a))


def panel(bbox, size, after, marks):
    x0, y0, x1, y1 = bbox
    w, h = size
    s = w / (x1 - x0)
    T = lambda p: ((p[0] - x0) * s, (y1 - p[1]) * s)
    im = Image.new('RGB', size, COL['water'])
    d = ImageDraw.Draw(im)
    inb = lambda ps, pad=50: any(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x, y in ps)
    for poly in W['land']:
        d.polygon([T(p) for p in pts(poly[0])], fill=COL['land'])
        for hole in poly[1:]:
            d.polygon([T(p) for p in pts(hole)], fill=COL['water'])
    for poly in W['marsh']:
        d.polygon([T(p) for p in pts(poly[0])], fill=COL['marsh'])
        for hole in poly[1:]:
            d.polygon([T(p) for p in pts(hole)], fill=COL['land'])
    for c in W['creeks']:
        d.line([T(p) for p in pts(c)], fill=COL['creek'], width=max(1, round(6 * s)))
    for r in W['rail']:
        d.line([T(p) for p in pts(r[1])], fill=COL['rail'], width=max(1, round(1.5 * s)))
    rl = roads1 if after else roads0
    order = sorted(range(len(W['roads'])), key=lambda i: (W['roads'][i][2], -W['roads'][i][1]))
    for pass_ in (0, 1):
        for i in order:
            r = W['roads'][i]
            p = rl[i]
            bx = [q[0] for q in p]; by = [q[1] for q in p]
            if max(bx) < x0 - 50 or min(bx) > x1 + 50 or max(by) < y0 - 50 or min(by) > y1 + 50:
                continue
            cls = CLS[r[1]]
            wd = max(1, round(2 * HALF[cls] * s))
            if pass_ == 0:
                if cls not in ('track', 'path'):
                    d.line([T(q) for q in p], fill=COL['bridge'] if r[2] else COL['roadcase'], width=wd + 2, joint='curve')
            else:
                fill = COL['track'] if cls in ('track', 'path') else COL['major'] if r[1] <= 2 or cls == 'motorway' else COL['road']
                d.line([T(q) for q in p], fill=fill, width=wd, joint='curve')
                if s > 1.5:
                    for q in (p[0], p[-1]):
                        cx, cy = T(q)
                        rr = wd / 2
                        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=fill)
    for p in W['piers']:
        d.line([T(q) for q in pts(p)], fill=COL['pier'], width=max(1, round(4 * s)))
    for i, b in enumerate(B0):
        if not inb(b):
            continue
        if after:
            if i in rem:
                continue
            if i in rep:
                d.polygon([T(q) for q in b], outline=(200, 190, 180))
                d.polygon([T(q) for q in rep[i]], fill=COL['replaced'], outline=COL['bldline'])
                continue
            d.polygon([T(q) for q in b], fill=COL['bld'], outline=COL['bldline'])
        else:
            fill = COL['removed'] if i in rem else (COL['replaced'] if i in rep else COL['bld'])
            d.polygon([T(q) for q in b], fill=fill, outline=COL['bldline'])
    if after:
        for b in add:
            d.polygon([T(q) for q in b], fill=COL['added'], outline=(20, 90, 40))
    pl = places1 if after else places0
    for pid, a in pl.items():
        if not inb([a], 0):
            continue
        cx, cy = T(a)
        moved = after and places1[pid] != places0[pid]
        c = COL['moved'] if moved else COL['place']
        d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=c, outline=(255, 255, 255))
        d.text((cx + 7, cy - 7), pid, fill=c, font=F_S)
        if moved:
            ox, oy = T(places0[pid])
            d.line([(ox, oy), (cx, cy)], fill=COL['moved'], width=1)
            d.ellipse([ox - 3, oy - 3, ox + 3, oy + 3], outline=COL['moved'])
    for t, a in (labels1 if after else labels0):
        if inb([a], 0):
            cx, cy = T(a)
            d.text((cx, cy), t, fill=(60, 80, 160), font=F_T, anchor='mm')
    for m in marks or []:
        cx, cy = T(m)
        d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=(220, 30, 30), width=2)
    # scale bar
    L = 10 ** math.floor(math.log10((x1 - x0) / 4))
    for mult in (5, 2, 1):
        if mult * L * s < w / 3:
            L *= mult
            break
    d.rectangle([10, h - 18, 10 + L * s, h - 14], fill=(30, 30, 30))
    d.text((14 + L * s, h - 24), f'{L:g} m', fill=(30, 30, 30), font=F_S)
    return im


for sp in specs:
    x0, y0, x1, y1 = sp['bbox']
    pw = sp.get('panel_w', 560)
    ph = round(pw * (y1 - y0) / (x1 - x0))
    single = sp.get('single', False)
    W2 = pw if single else pw * 2 + 10
    im = Image.new('RGB', (W2, ph + 58), (250, 249, 246))
    d = ImageDraw.Draw(im)
    d.text((8, 6), sp['title'], fill=COL['txt'], font=F_T)
    if sp.get('note'):
        d.text((8, 26), sp['note'], fill=(90, 84, 76), font=F_S)
    im.paste(panel(sp['bbox'], (pw, ph), single and sp.get('after', False), sp.get('mark')), (0, 46))
    if not single:
        im.paste(panel(sp['bbox'], (pw, ph), True, sp.get('mark')), (pw + 10, 46))
        for x, label, col in ((6, 'BEFORE', (150, 40, 40)), (pw + 16, 'AFTER', (30, 120, 60))):
            d.rectangle([x, 50, x + 52, 66], fill=(255, 255, 255))
            d.text((x + 4, 51), label, fill=col, font=F_S)
    out = os.path.join(root, sp['file'])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im = im.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    im.save(out, optimize=True)
    print(out, os.path.getsize(out))
