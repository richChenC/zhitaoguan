# -*- coding: utf-8 -*-
r"""
把全量机组台账 JSON 导成一份「标准检查表 Excel」，供 server.py 的 /api/import-excel 入库。

为什么需要这一步
----------------------------------------------------------
数据库里目前只有 6 次大修 / 3 个基地 / 584 条（约真实台账的 12%），
导致数据工作台、三维视图、数据大屏、报告导出这些**原有功能**只能看到一小部分真实数据。
台账 JSON 里有 6 基地 / 20 机组 / 72 次大修 / 4867 条逐条原始涡流明细。
本脚本把 JSON 翻成 server.py 认得的中文表头，导入后原有功能无需改一行代码即可用上全量数据。

列名严格对应 server.py::import_excel_file 的 aliases（不要用同义自造名）：
  大修号 / 电站名称 / 机组号 / 通道编号 / 在堆芯内的位置 / 幅值 / 相位 / 磨损深度 /
  三字码 / 测量通道 / 磨损位置 / 分析人员 / 数据组 / 备注 / 堵管移位信息

用法（抽取期脚本，运行时零依赖）：
  C:/Users/22234/.workbuddy/binaries/python/envs/default/Scripts/python.exe _build_import_xlsx.py
产出：
  <软件根目录>/output/ledgers/导入台账_全量72次大修.xlsx
"""
import json, io, os, glob
from collections import OrderedDict

from _paths import APP_DIR, LEDGER_DIR
ROOT = APP_DIR  # 软件目录（tools/ 下由 _paths 统一解析）
SRC = LEDGER_DIR
DST = os.path.join(APP_DIR, 'output', 'ledgers', '导入台账_全量72次大修.xlsx')

# 与 server.py aliases 一一对应（顺序即列顺序）
COLUMNS = [
    ('大修号', 'outage'), ('电站名称', 'baseName'), ('机组号', 'unitNo'),
    ('通道编号', 'ch'), ('在堆芯内的位置', 'pos'), ('幅值', 'amp'), ('相位', 'ph'),
    ('磨损深度', 'depth'), ('三字码', 'state'), ('测量通道', 'mch'),
    ('磨损位置', 'wpos'), ('分析人员', 'analyst'), ('数据组', 'grp'),
    ('备注', 'note'), ('堵管移位信息', 'shift'),
]


def main():
    from openpyxl import Workbook

    idx = json.load(io.open(os.path.join(SRC, 'index.json'), encoding='utf-8'))
    wb = Workbook()
    ws = wb.active
    ws.title = '标准检查表'
    ws.append([c for c, _ in COLUMNS])

    n = 0
    skipped = []
    for path in sorted(glob.glob(os.path.join(SRC, 'ledger-*.json'))):
        d = json.load(io.open(path, encoding='utf-8'))
        unit_no = None
        for uc, u in idx['units'].items():
            if u['name'] == d['name']:
                unit_no = u['unitNo']
                break
        for code, recs in d['outages'].items():
            for r in recs:
                row = []
                for _, key in COLUMNS:
                    if key == 'outage':
                        v = code
                    elif key == 'baseName':
                        v = d['baseName']
                    elif key == 'unitNo':
                        v = unit_no
                    else:
                        v = r.get(key)
                    row.append(v)
                # 至少要能定位到「大修 + 机组 + 通道」，否则入库也是脏数据
                if not row[0] or row[3] is None:
                    skipped.append((code, r))
                    continue
                ws.append(row)
                n += 1

    # 冻结首行 + 列宽
    ws.freeze_panes = 'A2'
    widths = {'大修号': 10, '电站名称': 10, '机组号': 8, '通道编号': 10,
              '在堆芯内的位置': 14, '幅值': 8, '相位': 8, '磨损深度': 10,
              '三字码': 8, '测量通道': 10, '磨损位置': 12, '分析人员': 10,
              '数据组': 20, '备注': 24, '堵管移位信息': 16}
    for i, (c, _) in enumerate(COLUMNS, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = widths.get(c, 12)

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    wb.save(DST)
    size = os.path.getsize(DST)
    print('=' * 62)
    print('标准检查表已生成：', DST)
    print('  行数（不含表头）：%d    跳过脏行：%d    文件大小：%.1f KB'
          % (n, len(skipped), size / 1024))
    print('  覆盖：%d 基地 · %d 机组 · %d 次大修（台账 meta：%s 条）'
          % (idx['meta']['bases'], idx['meta']['units'], idx['meta']['outages'],
             idx['meta']['records']))
    print('=' * 62)
    print('下一步：在软件「报告与导出 → Excel 导入」选择本文件即可入库；')
    print('        或用 /api/import-excel 的 check 模式先试运行（不写库）。')


if __name__ == '__main__':
    main()
