# -*- coding: utf-8 -*-
"""中国省级边界抽稀：DataV GeoAtlas 100000_full.json → 紧凑 provincial rings
- Douglas-Peucker 简化（容差可调），保留地理形状
- 输出 { adcode: { name, rings: [[[lng,lat],...],...] } }，rings 含孔洞环（用 evenodd 渲染）
- 数据合规：DataV GeoAtlas 为公开标准地图数据（含台湾省/香港/澳门/南海诸岛）
"""
import json, math, sys

SRC = '/tmp/c1.json'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import DATA_DIR
DST = os.path.join(DATA_DIR, 'china-provinces.json')
TOL = 0.03  # 度，约 3km；越小越精细（文件越大）

def dp(points, tol):
    """Douglas-Peucker 简化一条环（points: [[x,y],...]，首尾相同则保留闭合标记）"""
    if len(points) < 5:
        return points
    def dist2(a, b):
        return (a[0]-b[0])**2 + (a[1]-b[1])**2
    def seg_dist(p, a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        if dx == 0 and dy == 0:
            return math.sqrt(dist2(p, a))
        t = ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / (dx*dx+dy*dy)
        t = max(0.0, min(1.0, t))
        px, py = a[0]+t*dx, a[1]+t*dy
        return math.sqrt((p[0]-px)**2 + (p[1]-py)**2)
    closed = points[0] == points[-1]
    pts = points[:-1] if closed else points
    keep = [True]*len(pts)
    stack = [(0, len(pts)-1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        a, b = pts[s], pts[e]
        dmax, idx = -1, -1
        for i in range(s+1, e):
            d = seg_dist(pts[i], a, b)
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    out = [p for i, p in enumerate(pts) if keep[i]]
    return out + [out[0]] if closed else out

data = json.load(open(SRC, encoding='utf-8'))
out = {}
scs = {}
for f in data['features']:
    name = (f.get('properties') or {}).get('name') or ''
    adcode = (f.get('properties') or {}).get('adcode')
    geo = f.get('geometry') or {}
    gtype = geo.get('type')
    coords = geo.get('coordinates') or []
    rings = []
    if gtype == 'MultiPolygon':
        polys = coords
    elif gtype == 'Polygon':
        polys = [coords]
    else:
        # MultiPoint/Point（如南海诸岛）暂不处理为面
        polys = []
    tol = TOL * 2 if str(adcode) == '100000_JD' else TOL  # 九段线细线，容忍度放宽一半
    for poly in polys:
        for ring in poly:
            if len(ring) < 4:
                continue
            simple = dp(ring, tol)
            if len(simple) >= 4:
                rings.append(simple)
    if not rings:
        print('SKIP(no polygon):', repr(name), gtype)
        continue
    if str(adcode) == '100000_JD':
        scs['rings'] = rings
        scs['name'] = '南海诸岛'
    else:
        out[str(adcode)] = {'name': name, 'rings': rings}

out['scs'] = scs
json.dump(out, open(DST, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
size = len(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
print('provinces:', len(out) - 1, '| scs rings:', len(scs.get('rings', [])), '| bytes:', size)
tot_pts = sum(len(p) for v in out.values() if 'rings' in v for ring in v['rings'] for p in ring)
print('total points:', tot_pts)
