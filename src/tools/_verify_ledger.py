# -*- coding: utf-8 -*-
"""
台账数据质量对账（抽取期脚本）
------------------------------
1) 宁德1号机：把 xlsx 台账（N101–N105）与从 .doc 报告独立解析的 C1–C8 逐项对账
   —— 两条完全独立的解析链路，若汇总一致则互为强验证。
2) 通道 ↔ 堆芯位置映射一致性：同一机组各次大修之间不应冲突。
3) 数据分布合理性：深度 0–100、幅值 >0、大修序号连续、通道数 ≈ 50。
"""
import os, json, io, sys
from collections import defaultdict

from _paths import DATA_DIR
ROOT = DATA_DIR  # 数据目录（tools/ 下由 _paths 统一解析）
DATA = DATA_DIR

ledger_dir = os.path.join(DATA, 'thimble-ledger')
index = json.load(io.open(os.path.join(ledger_dir, 'index.json'), encoding='utf-8'))
doc_path = os.path.join(DATA, 'ningde-n1-outages.json')

fails, warns, oks = [], [], []


def chk(cond, msg):
    (oks if cond else fails).append(msg)
    return cond


# ---------- 1) 与 .doc 报告对账（宁德1号机） ----------
print('=' * 88)
print('【1】宁德1号机：xlsx 台账  vs  .doc 报告（两条独立解析链路对账）')
print('=' * 88)
if not os.path.exists(doc_path):
    warns.append('未找到 ningde-n1-outages.json，跳过与 .doc 报告的对账')
    print('  (跳过)')
else:
    doc = json.load(io.open(doc_path, encoding='utf-8'))
    doc_map = {o['code']: o for o in doc['outages']}          # C1..C8
    unit = index['units']['N1']
    print('  %-6s %-22s %8s %8s %8s' % ('大修', '对比项', 'xlsx', '.doc', '结果'))
    print('  ' + '-' * 60)
    n_ok = n_bad = 0
    for o in unit['outages']:
        x = o['summary']
        dcode = 'C%d' % o['seq']
        d = doc_map.get(dcode)
        if not d:
            warns.append('%s 在 .doc 报告中无对应 %s' % (o['code'], dcode))
            continue
        ds = d['summary']
        for key, xk in (('tubes', 'tubes'), ('findings', 'findings'),
                        ('ge30', 'ge30'), ('over50', 'over50'),
                        ('maxDepth', 'maxDepth')):
            xv, dv = x[xk], ds[key]
            same = abs(float(xv) - float(dv)) < 0.05
            if same:
                n_ok += 1
            else:
                n_bad += 1
                fails.append('%s/%s %s 不一致: xlsx=%s doc=%s' % (o['code'], dcode, key, xv, dv))
            print('  %-6s %-22s %8s %8s %8s'
                  % (o['code'], '%s (%s)' % (key, dcode), xv, dv, 'OK' if same else 'X 不一致'))
    chk(n_bad == 0, '宁德1号机 xlsx↔.doc 对账：%d 项一致 / %d 项不一致' % (n_ok, n_bad))
    print('  ---- 小计：一致 %d 项，不一致 %d 项' % (n_ok, n_bad))

# ---------- 2) 通道 ↔ 堆芯位置映射一致性 ----------
print()
print('=' * 88)
print('【2】通道 ↔ 堆芯位置映射一致性（同机组各次大修之间不应冲突）')
print('=' * 88)
conf_total = 0
for uc, u in index['units'].items():
    m = {}            # ch -> {pos: [outages]}
    for o in u['outages']:
        for c in o['channels']:
            if c['pos']:
                m.setdefault(c['ch'], defaultdict(list))[c['pos']].append(o['code'])
    conflicts = []
    for ch, pm in m.items():
        if len(pm) > 1:
            conflicts.append((ch, dict(pm)))
    n_pos = len({list(pm)[0] for pm in m.values() if pm})
    flag = 'OK' if not conflicts else 'X %d 处冲突' % len(conflicts)
    print('  %-6s %-10s 大修 %2d 次 · 通道 %2d 个 · 唯一位置 %2d 个 · %s'
          % (uc, u['name'], len(u['outages']), len(m), n_pos, flag))
    for ch, pm in conflicts[:3]:
        fails.append('%s 通道 %s 位置冲突: %s' % (uc, ch, pm))
    conf_total += len(conflicts)
chk(conf_total == 0, '跨大修通道↔位置映射：共 %d 处冲突' % conf_total)

# ---------- 3) 数据分布合理性 ----------
print()
print('=' * 88)
print('【3】数据分布合理性')
print('=' * 88)
rec_total = 0
depth_bad = amp_bad = 0
seq_gaps = []
ch_counts = defaultdict(list)
for uc, u in index['units'].items():
    seqs = [o['seq'] for o in u['outages']]
    missing = [s for s in range(min(seqs), max(seqs) + 1) if s not in seqs]
    if missing:
        seq_gaps.append('%s 缺大修序号 %s' % (uc, missing))
    for o in u['outages']:
        s = o['summary']
        if not (0 <= s['maxDepth'] <= 100):
            depth_bad += 1
        if s['maxDepth'] > 0 and s['findings'] == 0:
            depth_bad += 1
        ch_counts[uc].append(s['channelsTotal'])

print('  %-8s %-22s %s' % ('机组', '各次大修通道数', '最大深度序列'))
for uc, u in index['units'].items():
    print('  %-8s %-22s %s'
          % (uc, ','.join(str(x) for x in ch_counts[uc]),
             '→'.join(str(o['summary']['maxDepth']) for o in u['outages'])))

chk(depth_bad == 0, '深度越界/口径异常：%d 处' % depth_bad)
chk(amp_bad == 0, '幅值异常：%d 处' % amp_bad)
for g in seq_gaps:
    warns.append(g)

# 通道数应接近 50（部分机组可能只测部分通道）
odd_units = []
for uc, counts in ch_counts.items():
    mx = max(counts)
    if mx > 60 or mx < 10:
        odd_units.append('%s 通道数 %d' % (uc, mx))
chk(not odd_units, '通道数异常机组：%s' % (', '.join(odd_units) or '无'))

# ---------- 4) 产出文件 ----------
print()
print('=' * 88)
print('【4】产出文件')
print('=' * 88)
total_bytes = 0
for fn in sorted(os.listdir(ledger_dir)):
    p = os.path.join(ledger_dir, fn)
    sz = os.path.getsize(p)
    total_bytes += sz
    print('  %-24s %8.1f KB' % (fn, sz / 1024))
print('  %-24s %8.1f KB' % ('合计', total_bytes / 1024))

# ---------- 汇总 ----------
print()
print('=' * 88)
print('汇总：%d 项通过 / %d 项失败 / %d 条提示' % (len(oks), len(fails), len(warns)))
print('=' * 88)
for f in fails[:20]:
    print('  X', f)
for w in warns[:20]:
    print('  !', w)
print()
print('LEDGER_VERIFY ' + ('PASS' if not fails else 'FAIL'))
sys.exit(0 if not fails else 1)
