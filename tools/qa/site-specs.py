"""Compute site specs (footprint, street frontage, lot) for the character homes from the Atlas data.
Usage: python3 -I tools/qa/site-specs.py data/wpdata.json data/gaz.json > docs/site-specs.json"""
import json, math, sys
w = json.load(open(sys.argv[1])); g = json.load(open(sys.argv[2]))
BK = ['house','duplex','mobile','shed','barn','shop','office','tower','deck','retail','apartments','townhouse','clubhouse','church','school','gym','stands','hospital','industrial','civic','motel','hotel']
CLS = ['trunk','primary','secondary','tertiary','residential','service','track','path','motorway']
HALF = {'trunk':7.5,'primary':6.5,'secondary':5.5,'tertiary':4.5,'residential':3.75,'service':2.75,'track':2,'path':1,'motorway':9}
names = w['names']
B = []
for b in w['b']:
    p = [v/2 for v in b[2:]]; pts = list(zip(p[0::2], p[1::2]))
    B.append(dict(kind=BK[b[0]], h=b[1]/2, pts=pts, c=(sum(x for x,y in pts)/4, sum(y for x,y in pts)/4)))
segs = []
for ri, r in enumerate(w['roads']):
    p = r[3]
    for i in range(0, len(p)-2, 2): segs.append((p[i], p[i+1], p[i+2], p[i+3], ri))
def near_road(x, y, want=None):
    best = None
    for (x1,y1,x2,y2,ri) in segs:
        r = w['roads'][ri]; nm = names[r[0]] if r[0] >= 0 else None
        if want and nm != want: continue
        dx, dy = x2-x1, y2-y1; L = dx*dx+dy*dy
        t = 0 if L == 0 else max(0, min(1, ((x-x1)*dx+(y-y1)*dy)/L))
        px, py = x1+t*dx, y1+t*dy; d = math.hypot(x-px, y-py)
        if best is None or d < best[0]: best = (d, nm, CLS[r[1]], (px, py), ri)
    return best
def spec(key, bi, street):
    b = B[bi]; c = b['c']; pts = b['pts']
    d, nm, cls, foot, ri = near_road(*c, street)
    # front normal = unit vector from center toward the road foot point
    fx, fy = (foot[0]-c[0])/d, (foot[1]-c[1])/d
    # choose the footprint edge whose outward normal best matches the front direction
    best = None
    for i in range(4):
        a, bb = pts[i], pts[(i+1) % 4]
        mx, my = (a[0]+bb[0])/2-c[0], (a[1]+bb[1])/2-c[1]; L = math.hypot(mx, my)
        dot = (mx*fx+my*fy)/L
        if best is None or dot > best[0]: best = (dot, i, math.dist(a, bb), (mx/L, my/L))
    _, ei, W, nrm = best
    D = math.dist(pts[(ei+1) % 4], pts[(ei+2) % 4])
    # local frame: +y_local = back (away from street), front faces -y_local (Blender -Y)
    ux, uy = -nrm[1], nrm[0]  # local +x (to the right when facing the house from the street? see note)
    # facing the house from the street you look along -nrm; your right hand is (+nrm rotated -90) = (nrm.y, -nrm.x)
    rx, ry = nrm[1], -nrm[0]
    def local(px, py):
        vx, vy = px-c[0], py-c[1]
        return (round(vx*rx+vy*ry, 2), round(-(vx*nrm[0]+vy*nrm[1]), 2))
    # neighbors within 80 m
    nb = []
    for j, o in enumerate(B):
        if j == bi: continue
        dd = math.dist(o['c'], c)
        if dd < 80: nb.append(dict(i=j, kind=o['kind'], h=o['h'], local=local(*o['c']), dist=round(dd, 1)))
    nb.sort(key=lambda o: o['dist'])
    heading = math.degrees(math.atan2(nrm[1], nrm[0]))  # atlas angle of the front normal (0 = east, 90 = north)
    return dict(id=key, building_index=bi, kind=b['kind'], atlas_height_m=b['h'], center_atlas=[round(c[0], 2), round(c[1], 2)],
        footprint_w_along_street_m=round(W, 2), footprint_d_deep_m=round(D, 2),
        front_normal_atlas=[round(nrm[0], 4), round(nrm[1], 4)], front_heading_deg_atlas=round(heading, 1),
        street=nm, street_class=cls, street_centerline_dist_m=round(d, 2), street_half_width_m=HALF[cls],
        curb_line_local_y=round(-(d-HALF[cls]), 2),
        footprint_local=[local(*p) for p in pts], neighbors_local=nb[:10])
homes = [('monet-williams-house', 6973, 'Oak Street'), ('thompson-house', 22180, 'Pelican Point Drive'), ('patel-house', 23310, 'Sandpiper Lane'),
         ('al-hassan-house', 21135, 'Spinnaker Court'), ('hernandez-house', 30499, 'Mercer Street'), ('abernathy-trailer', 173, None),
         ('delacroix-house', 23936, 'Harbor Drive'), ('sullivan-house', 21165, 'Bay Drive'), ('rossi-house', 21164, 'Bay Drive')]
print(json.dumps({'convention': 'Local frame: origin = footprint center at grade; local +x = to your right when standing in the street looking at the front door; local -y = toward the street (front); local +y = toward the back. In Blender build with front facing -Y, up +Z. Atlas: x east, y north, meters.',
                  'homes': [spec(*h) for h in homes]}, indent=1))
