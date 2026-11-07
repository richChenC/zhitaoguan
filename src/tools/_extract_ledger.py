# -*- coding: utf-8 -*-
r"""
全量机组台账解析（抽取期脚本，运行时零依赖）
--------------------------------------------------
把 `指套管数据测试 202007/` 下各基地各机组历次大修的**逐条原始涡流检测明细**
解析为前端可直接消费的分层 JSON 数据底座。

运行：需要 openpyxl；岭澳 L3/L4 老 .xls 用 xlrd（隔离 venv）或后端标准库 xls_reader 回退读取。
  C:/Users/22234/.workbuddy/binaries/python/envs/default/Scripts/python.exe _extract_ledger.py

产出（src/desktop-ui/modules/analytics/data/thimble-ledger/）：
  index.json            基地/机组/大修索引 + 每次大修汇总指标（小，首屏用）
  ledger-<UNIT>.json    单机组的逐条明细（按需懒加载）

设计要点：
  1. 列名有 14 种变体（通道/通道编号/通道管号/通道号；堆芯位置/堆内位置/在堆芯内的位置；
     幅值/电压/幅值（V)…），统一走「语义优先级匹配」映射到标准字段，不硬编码列索引。
  2. 大亚湾/防城港版式前有 5 个元信息列（电站名称/机组号/安全级别/设备名称/被检部位），自动忽略。
  3. 脏值 `/`、`　/`、`-`、空串 统一归一为 None。
  4. 通道号合并单元格 → 前向填充。
  5. 校验：深度 0–100、堆芯位置 `[A-R]` 列 + 行 1–15、列 ∈ RPNMLKJHGFEDCBA。
"""
import os, re, json, glob, math
from collections import OrderedDict

import openpyxl

from _paths import PROJECT_ROOT, REFERENCE_DIR, LEDGER_DIR
ROOT = PROJECT_ROOT
SRC = os.path.join(REFERENCE_DIR, '指套管数据测试 202007')
DST = LEDGER_DIR

# 基地字母 → 中文名（与 server.STATION_CODES / china-map.js SITE_GEO.apiCode 保持一致；
# 陆丰取 LF，避免与岭澳 L 撞码；太平岭（惠州）台账用 P）
BASE_NAME = {
    'N': '宁德', 'H': '红沿河', 'Y': '阳江', 'D': '大亚湾',
    'F': '防城港', 'L': '岭澳', 'T': '台山', 'C': '苍南', 'P': '太平岭',
    'LF': '陆丰',
}

# 标准字段 → 表头匹配正则（按优先级顺序尝试；先到先得，避免「位置」被堆芯位置抢走）
FIELD_PATTERNS = [
    ('ch',       r'^(通道编号|通道管号|通道号|通道)$'),
    # 堆芯位置列名有 4 种变体：堆芯位置 / 在堆芯内的位置 / 堆内位置 / 堆芯内位置（岭澳 L4）
    ('pos',      r'^(堆芯位置|在堆芯内的位置|堆内位置|堆芯内的位置|堆芯内位置)$'),
    ('amp',      r'^(幅值|电压|幅值\(V\)|电压\(V\)|幅值（V）|电压（V）|幅值（V）|幅值（V\)|幅值（V)$'),
    ('ph',       r'^(相位|相位角|相位\(°\))$'),
    ('depth',    r'^(磨损深度|磨损深度\(%\)|磨损深度（%）|磨损深度%)$'),
    ('state',    r'^(三字符)$'),
    ('mch',      r'^(测量通道|记录通道)$'),
    ('wpos',     r'^(磨损位置|位置)$'),
    ('probe',    r'^(探头类型|探头型号)$'),
    ('analyst',  r'^(分析人员)$'),
    ('datafile', r'^(数据)$'),
    ('grp',      r'^(数据组|数据组号|数据组名)$'),
    ('note',     r'^(备注)$'),
    ('shift',    r'^(堵管移位信息|移位堵管信息)$'),
]
NULL_TOKENS = {'', '/', '　/', '-', '—', '－', '无', '/ ', ' /', '　', ' '}

# 合法堆芯位置：列 R P N M L K J H G F E D C B A；行 1–15
POS_RE = re.compile(r'^([A-R])(\d{1,2})$')
VALID_COLS = set('RPNMLKJHGFEDCBA')


def norm(v):
    """脏值归一：None / 各种斜杠横线 → None；字符串去全角空格；数字原样。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    s = str(v).replace('　', '').replace('\xa0', '').strip()
    if s in NULL_TOKENS:
        return None
    return s


def to_float(v):
    n = norm(v)
    if n is None:
        return None
    if isinstance(n, (int, float)):
        return float(n)
    s = str(n).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def to_int(v):
    n = norm(v)
    if n is None:
        return None
    if isinstance(n, (int, float)):
        return int(n)
    s = str(n).strip()
    if re.fullmatch(r'\d+(\.0+)?', s):
        return int(float(s))
    return None


def map_header(header_row):
    """表头行 → {标准字段: 列索引}"""
    cells = [str(c).replace('　', '').replace('\xa0', '').strip() if c is not None else ''
             for c in header_row]
    mapping, used = {}, set()
    for field, pat in FIELD_PATTERNS:
        rx = re.compile(pat)
        for i, name in enumerate(cells):
            if i in used or not name:
                continue
            if rx.match(name):
                mapping[field] = i
                used.add(i)
                break
    return mapping


def find_header(rows):
    """在前 6 行里找表头行下标：命中「通道编号/通道管号/通道号/通道」且同时有「三字符」。

    注意：用 `|` 拼接后 `^通道$` 锚的是整串首尾，匹配不到「通道|堆芯位置|…」中间的 `通道`，
    必须用 `(^|[|])通道([|]|$)` 这种分隔符边界写法（N301/N302/N303/H301 就栽在这里）。
    """
    pat = re.compile(r'(^|\|)(通道编号|通道管号|通道号|通道)(\||$)')
    for i, row in enumerate(rows[:6]):
        cells = [str(c).strip() if c is not None else '' for c in row]
        joined = '|'.join(cells)
        if pat.search(joined) and '三字符' in joined:
            return i
    return None


def parse_sheet(rows):
    """解析单个 sheet（rows 为二维 list）→ (records, warnings)"""
    hi = find_header(rows)
    if hi is None:
        return None, ['NO-HEADER']
    mapping = map_header(rows[hi])
    missing = [f for f in ('ch', 'pos', 'depth') if f not in mapping]
    warns = []
    if missing:
        warns.append('缺列:' + ','.join(missing))

    records, last_ch, last_pos = [], None, None
    for row in rows[hi + 1:]:
        def g(f):
            i = mapping.get(f)
            return row[i] if i is not None and i < len(row) else None

        ch = to_int(g('ch'))
        pos = norm(g('pos'))
        depth = to_float(g('depth'))
        state = norm(g('state'))
        # 空行 / 汇总行跳过
        if ch is None and pos is None and depth is None and not state:
            continue
        # 合并单元格前向填充
        if ch is None:
            ch = last_ch
        else:
            last_ch = ch
        if pos is None:
            pos = last_pos
        else:
            last_pos = pos

        amp = to_float(g('amp'))
        ph = to_int(g('ph'))
        wpos = norm(g('wpos'))
        shift = norm(g('shift'))

        # ---- 校验 ----
        if depth is not None and not (0 <= depth <= 100):
            warns.append('深度越界 ch%s d=%s' % (ch, depth))
            depth = None
        if pos:
            m = POS_RE.match(str(pos).upper().replace(' ', ''))
            if not m or m.group(1) not in VALID_COLS or not (1 <= int(m.group(2)) <= 15):
                warns.append('位置非法 ch%s pos=%s' % (ch, pos))
            else:
                pos = m.group(1) + m.group(2)
        # WAR=磨损显示 NDD=无降质显示 NOS=未测/无信号（H1 机组出现过）
        if state and str(state).upper() not in ('WAR', 'NDD', 'NDF', 'NOS'):
            warns.append('状态异常 ch%s st=%s' % (ch, state))

        records.append(OrderedDict([
            ('ch', ch), ('pos', pos), ('amp', amp), ('ph', ph),
            ('depth', depth), ('state', (str(state).upper() if state else None)),
            ('mch', norm(g('mch'))), ('wpos', wpos),
            ('probe', norm(g('probe'))), ('analyst', norm(g('analyst'))),
            ('grp', norm(g('grp'))), ('note', norm(g('note'))), ('shift', shift),
        ]))
    return records, warns


def summarize(records):
    """按通道聚合出本次大修的汇总指标"""
    by_ch = OrderedDict()
    for r in records:
        if r['ch'] is None:
            continue
        b = by_ch.setdefault(r['ch'], {'ch': r['ch'], 'pos': r['pos'], 'n': 0,
                                       'depths': [], 'amps': [], 'locs': [], 'shift': None})
        b['n'] += 1
        if r['depth'] is not None:
            b['depths'].append(r['depth'])
        if r['amp'] is not None:
            b['amps'].append(r['amp'])
        if r['wpos'] and r['wpos'] not in b['locs']:
            b['locs'].append(r['wpos'])
        if r['pos'] and not b['pos']:
            b['pos'] = r['pos']
        if r['shift'] and not b['shift']:
            b['shift'] = r['shift']

    channels = []
    for ch in sorted(by_ch):
        b = by_ch[ch]
        ds = b['depths']
        channels.append(OrderedDict([
            ('ch', ch), ('pos', b['pos']), ('state', 'WAR' if ds else 'NDD'),
            ('maxDepth', round(max(ds), 1) if ds else 0),
            ('maxAmp', round(max(b['amps']), 2) if b['amps'] else None),
            ('n', len(ds)),
            ('depths', [round(d, 1) for d in ds]),
            ('locs', b['locs']),
            ('shift', b['shift']),
        ]))

    all_depths = [d for c in channels for d in c['depths']]
    tubes = sum(1 for c in channels if c['n'] > 0)
    return {
        'channels': channels,
        'summary': OrderedDict([
            ('tubes', tubes),                                   # 有磨损显示的管数
            ('channelsTotal', len(channels)),                   # 总通道数
            ('findings', len(all_depths)),                      # 磨损显示处数
            ('ndd', len(channels) - tubes),                     # 无降质显示通道数
            ('ge30', sum(1 for d in all_depths if d >= 30)),
            ('over50', sum(1 for d in all_depths if d > 50)),
            ('maxDepth', round(max(all_depths), 1) if all_depths else 0),
            ('avgDepth', round(sum(all_depths) / len(all_depths), 1) if all_depths else 0),
        ]),
    }


def outage_label(seq):
    return '第%d次大修' % seq


def resolve_pos_conflicts(units):
    """「通道 ↔ 堆芯位置」权威校验：自举出奇偶机组两套标准映射，修正偏离并留痕。

    ★ 关键领域规律（实测得出）：
      50 个测量通道的堆芯位置，由机组号的**奇偶**决定，存在两套固定映射：
        奇数机组（1/3/5 号机）→ ODD  映射，通道1 = L11
        偶数机组（2/4/6 号机）→ EVEN 映射，通道1 = B5
      20 台机组 × 72 次大修实测：48/50 个通道在各自奇偶组内 100% 一致。
      因此可比对本机组的每一次大修——**连「整台机组全错」也能检出**
      （这种情况用「机组内多数表决」永远发现不了）。

    检出的真实录入错误（源数据问题，非解析问题）：
      D1 通道1  ：L1  → L11   4 次大修全错，疑漏写一个「1」
      D2 通道48 ：C8  → L8    4 次大修全错，C8 恰是偶数机组通道2 的位置（串行）
                              —— 与用户 `D2指套管堆芯位置对应错误.xlsx` 的记载吻合
      H1 通道3  ：G14 → N7    仅 H103 错，G14 是奇数机组通道16 的位置
      H4 通道13 ：N10 → F6    仅 H401 错，N10 是偶数机组通道46 的位置

    策略：自举众数得到标准映射 → 回填修正 → 冲突原样写入 unit['posConflicts']
    **不静默抹掉问题**，前端可据此提示数据质量。
    """
    from collections import Counter, defaultdict
    # ---- 第一轮：按 (奇偶, 通道) 自举标准映射 ----
    votes = {0: defaultdict(Counter), 1: defaultdict(Counter)}
    for u in units.values():
        par = u['unitNo'] % 2
        for recs in u['_recs'].values():
            for r in recs:
                if r['ch'] is not None and r['pos']:
                    votes[par][r['ch']][r['pos']] += 1
    std = {p: {ch: c.most_common(1)[0][0] for ch, c in votes[p].items()} for p in (0, 1)}

    # ---- 第二轮：校验 + 修正 + 留痕 ----
    for uc, u in units.items():
        par = u['unitNo'] % 2
        table = std[par]
        for code, recs in u['_recs'].items():
            for r in recs:
                ch, pos = r['ch'], r['pos']
                if ch is None or not pos or ch not in table:
                    continue
                want = table[ch]
                if pos == want:
                    continue
                r['posFix'] = pos          # 保留原值供追溯
                r['pos'] = want
                hit = next((c for c in u['posConflicts']
                            if c['ch'] == ch and c['wrong'] == pos), None)
                if hit:
                    hit['outages'].append(code)
                else:
                    u['posConflicts'].append(OrderedDict([
                        ('ch', ch), ('authoritative', want), ('wrong', pos),
                        ('outages', [code]),
                        ('votes', OrderedDict(votes[par][ch].most_common())),
                    ]))
    return std


def iter_sheets(path):
    """统一迭代 (sheet_name, rows)，自动适配 .xlsx (openpyxl) 与老 .xls。

    老 .xls 只有岭澳 L3/L4 两台机组。优先用隔离 venv 里的 xlrd（xlrd 2.x 仅支持 .xls）；
    xlrd 不可用时回退到后端自带的标准库读取器 xls_reader（接口对齐 openpyxl），
    避免缺依赖时静默丢掉岭澳两个机组。
    """
    if path.lower().endswith('.xls'):
        try:
            import xlrd
        except ImportError:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
            from xls_reader import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            for sn in wb.sheetnames:
                yield sn, [list(r) for r in wb[sn].iter_rows(values_only=True)]
            wb.close()
            return
        wb = xlrd.open_workbook(path)
        for sn in wb.sheet_names():
            ws = wb.sheet_by_name(sn)
            rows = [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)]
            yield sn, rows
        return
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for sn in wb.sheetnames:
        ws = wb[sn]
        yield sn, [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()


def main():
    os.makedirs(DST, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, '**', '*.xls*'), recursive=True))
    files = [f for f in files
             if not os.path.basename(f).startswith('~$')
             and not os.path.basename(f).endswith('.xlsx~')]

    units = OrderedDict()          # unitCode -> {...}
    all_warnings = []
    total_records = 0

    for f in files:
        base_name = os.path.basename(f)
        try:
            sheet_iter = list(iter_sheets(f))
        except Exception as e:
            all_warnings.append('%s 打开失败 %s' % (base_name, e))
            continue
        for sn, sheet_rows in sheet_iter:
            code = sn.strip()                       # 有的 sheet 名带前导空格（Y103 / Y203）
            m = re.fullmatch(r'([A-Z]{1,2})(\d)(\d{2})', code)
            if not m:
                continue                            # 非台账 sheet（Sheet1、F2总表 等）
            bl, un, seq = m.group(1), int(m.group(2)), int(m.group(3))
            if bl not in BASE_NAME:
                all_warnings.append('未知基地码 %s (%s)' % (bl, code))
                continue
            unit_code = '%s%d' % (bl, un)
            records, warns = parse_sheet(sheet_rows)
            if not records:
                all_warnings.append('%s :: %s 无有效行' % (base_name, code))
                continue
            for w in warns[:5]:
                all_warnings.append('%s :: %s  %s' % (base_name, code, w))

            u = units.setdefault(unit_code, OrderedDict([
                ('code', unit_code), ('base', bl), ('baseName', BASE_NAME[bl]),
                ('unitNo', un), ('name', '%s%d号机' % (BASE_NAME[bl], un)),
                ('outages', []), ('posConflicts', []),
                ('_recs', OrderedDict()), ('_src', OrderedDict()),
            ]))
            u['_recs'][code] = records
            u['_src'][code] = base_name
            total_records += len(records)

    # ---------- 「通道↔堆芯位置」权威校验（奇偶两套标准映射，自举） ----------
    posmap = resolve_pos_conflicts(units)

    # ---------- 汇总（须在位置修正之后） ----------
    for uc, u in units.items():
        for code, records in u['_recs'].items():
            agg = summarize(records)
            m = re.fullmatch(r'([A-Z]{1,2})(\d)(\d{2})', code)
            u['outages'].append(OrderedDict([
                ('code', code), ('seq', int(m.group(3))), ('label', outage_label(int(m.group(3)))),
                ('year', None), ('source', u['_src'][code]), ('sheet', code),
                ('summary', agg['summary']), ('channels', agg['channels']),
            ]))
        u['outages'].sort(key=lambda o: o['seq'])

    # ---------- 基地分组 ----------
    bases_map = OrderedDict()
    for uc, u in units.items():
        bases_map.setdefault(u['base'], []).append(uc)
    bases = [OrderedDict([('code', b), ('name', BASE_NAME.get(b, b)),
                          ('units', sorted(bases_map[b], key=lambda x: int(x[1:])))])
             for b in sorted(bases_map, key=lambda x: (-len(bases_map[x]), x))]

    # ---------- 写 index.json（不含逐条明细的 channels 明细，只保留汇总） ----------
    index = OrderedDict([
        ('meta', OrderedDict([
            ('source', '指套管数据测试 202007/ 全量机组台账（xlsx 逐条原始涡流明细）'),
            ('generated', '2026-08-28'),
            ('bases', len(bases)), ('units', len(units)),
            ('outages', sum(len(u['outages']) for u in units.values())),
            ('records', total_records),
            ('thresholds', OrderedDict([('watch', 30), ('limit', 50)])),
            ('note', '深度单位为壁厚百分比 %；WAR=磨损显示，NDD=无降质显示；≥30% 关注，>50% 超标'),
        ])),
        # 通道↔堆芯位置标准映射（按机组号奇偶分两套），可用于录入校验
        ('posMap', OrderedDict([
            ('odd', OrderedDict((str(k), posmap[1][k]) for k in sorted(posmap[1]))),
            ('even', OrderedDict((str(k), posmap[0][k]) for k in sorted(posmap[0]))),
        ])),
        ('bases', bases),
        ('units', OrderedDict(
            (uc, OrderedDict([(k, v) for k, v in u.items() if not k.startswith('_')]))
            for uc, u in sorted(units.items())
        )),
    ])
    with open(os.path.join(DST, 'index.json'), 'w', encoding='utf-8') as fp:
        json.dump(index, fp, ensure_ascii=False, separators=(',', ':'))

    # ---------- 写 ledger-<UNIT>.json ----------
    for uc, u in units.items():
        payload = OrderedDict([
            ('code', uc), ('name', u['name']), ('base', u['base']), ('baseName', u['baseName']),
            ('outages', OrderedDict((c, u['_recs'][c]) for c in sorted(u['_recs']))),
        ])
        with open(os.path.join(DST, 'ledger-%s.json' % uc), 'w', encoding='utf-8') as fp:
            json.dump(payload, fp, ensure_ascii=False, separators=(',', ':'))

    # ---------- 报告 ----------
    print('=' * 78)
    print('基地 %d / 机组 %d / 大修 %d / 明细 %d 条'
          % (len(bases), len(units), sum(len(u['outages']) for u in units.values()), total_records))
    print('-' * 78)
    for b in bases:
        print('  %-6s %s' % (b['name'], ' '.join(b['units'])))
    print('-' * 78)
    print('%-8s %-10s %5s %5s %5s %5s %5s %7s' % ('机组', '大修', '管数', '处数', '≥30', '>50', '最深', '均值'))
    for uc in sorted(units):
        u = units[uc]
        for o in u['outages']:
            s = o['summary']
            print('%-8s %-10s %5d %5d %5d %5d %5.1f %7.1f'
                  % (u['name'], o['code'], s['tubes'], s['findings'],
                     s['ge30'], s['over50'], s['maxDepth'], s['avgDepth']))
    print('-' * 78)
    conflicts = [(uc, c) for uc, u in units.items() for c in u['posConflicts']]
    if conflicts:
        print('⚠ 堆芯位置录入错误 %d 处（已按奇偶标准映射修正，原值保留在 posConflicts）：'
              % len(conflicts))
        for uc, c in conflicts:
            print('  ! %-3s %s  通道%-3d  %-4s → %-4s   共 %d 条记录，出现于 %s'
                  % (uc, units[uc]['name'], c['ch'], c['wrong'], c['authoritative'],
                     len(c['outages']), ','.join(c['outages'][:6])
                     + ('…' if len(c['outages']) > 6 else '')))
    else:
        print('通道↔位置映射无冲突')
    print('  标准映射：奇数机组通道1=%s / 偶数机组通道1=%s（各 50 通道，见 index.posMap）'
          % (posmap[1].get(1), posmap[0].get(1)))
    print('-' * 78)
    if all_warnings:
        print('警告 %d 条（前 25）：' % len(all_warnings))
        for w in all_warnings[:25]:
            print('  !', w)
    else:
        print('无警告')
    print('输出目录：', DST)


if __name__ == '__main__':
    main()
