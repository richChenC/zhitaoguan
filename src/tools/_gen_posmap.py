# -*- coding: utf-8 -*-
"""从已解析台账反推「奇偶机组 → 通道↔堆芯位置」标准映射，并定位所有偏离。"""
import os, io, json
from collections import Counter, defaultdict

from _paths import APP_DIR, LEDGER_DIR
HERE = APP_DIR  # 软件目录（tools/ 下由 _paths 统一解析）
idx = json.load(io.open(os.path.join(LEDGER_DIR, 'index.json'), encoding='utf-8'))

odd, even = defaultdict(Counter), defaultdict(Counter)
for uc, u in idx['units'].items():
    par = u['unitNo'] % 2
    for o in u['outages']:
        for c in o['channels']:
            if c['pos']:
                (odd if par else even)[c['ch']][c['pos']] += 1

O = {ch: odd[ch].most_common(1)[0][0] for ch in odd}
E = {ch: even[ch].most_common(1)[0][0] for ch in even}

print('ODD ch1=%s  EVEN ch1=%s  EVEN ch48=%s' % (O[1], E[1], E[48]))
print()
print('--- 偏离标准映射的机组/通道 ---')
n = 0
for uc, u in sorted(idx['units'].items()):
    std = O if u['unitNo'] % 2 else E
    for ch in sorted(std):
        vals = sorted({c['pos'] for o in u['outages']
                       for c in o['channels'] if c['ch'] == ch and c['pos']})
        if vals and vals != [std[ch]]:
            outs = [o['code'] for o in u['outages']
                    for c in o['channels'] if c['ch'] == ch and c['pos'] != std[ch]]
            print('  %-4s %-10s 通道%-3d 标准=%-4s 实际=%-16s 出现于 %s'
                  % (uc, u['name'], ch, std[ch], '/'.join(vals), ','.join(sorted(set(outs)))))
            n += 1
print('  共 %d 处' % n)
print()


def emit(name, M):
    print('%s = {' % name)
    line = '    '
    for ch in sorted(M):
        item = " %d:'%s'," % (ch, M[ch])
        if len(line) + len(item) > 78:
            print(line)
            line = '    '
        line += item
    print(line.rstrip(','))
    print('}')
    print()


emit('ODD_MAP', O)
emit('EVEN_MAP', E)
