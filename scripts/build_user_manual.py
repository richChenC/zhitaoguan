# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.section import WD_SECTION
from pathlib import Path
from datetime import date

ROOT = Path(r'D:\\work-projects\\在役检查系统-指套管数据管理工具\\01_当前软件\\软件正式版_20261021')
OUT = ROOT / 'docs' / '在役检查系统-指套管数据管理工具_软件使用说明与功能测试报告_2026-10-24.docx'
TMP = ROOT / 'tmp'

def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:fill'), fill); tcPr.append(shd)

def set_cell_text(cell, text, bold=False, color='1F2937', size=9):
    cell.text = ''
    p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(0)
    r = p.add_run(str(text)); r.bold = bold; r.font.name = 'Microsoft YaHei'; r.font.size = Pt(size); r.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

def add_table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers)); t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.style = 'Table Grid'
    for i,h in enumerate(headers):
        c=t.rows[0].cells[i]; shade(c,'0F4C81'); set_cell_text(c,h,True,'FFFFFF',9)
    for row in rows:
        cells=t.add_row().cells
        for i,v in enumerate(row): set_cell_text(cells[i],v,False,'1F2937',8.5)
    if widths:
        for row in t.rows:
            for i,w in enumerate(widths): row.cells[i].width=Inches(w)
    return t

def add_image(doc, path, caption, width=6.2):
    if Path(path).exists():
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run().add_picture(str(path), width=Inches(width))
        c=doc.add_paragraph(caption); c.alignment=WD_ALIGN_PARAGRAPH.CENTER; c.style='Caption'

def heading(doc, text, level=1):
    p=doc.add_heading(text, level=level); return p

doc=Document()
sec=doc.sections[0]; sec.top_margin=Inches(0.65); sec.bottom_margin=Inches(0.65); sec.left_margin=Inches(0.75); sec.right_margin=Inches(0.75)
styles=doc.styles
styles['Normal'].font.name='Microsoft YaHei'; styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei'); styles['Normal'].font.size=Pt(10.5)
for name,size,color in [('Title',26,'0F4C81'),('Heading 1',17,'0F4C81'),('Heading 2',13,'1F6B8F'),('Heading 3',11,'374151')]:
    s=styles[name]; s.font.name='Microsoft YaHei'; s._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei'); s.font.size=Pt(size); s.font.color.rgb=RGBColor.from_string(color); s.font.bold=True

# cover
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.space_after=Pt(12)
r=p.add_run('在役检查系统-指套管数据管理工具'); r.bold=True; r.font.name='Microsoft YaHei'; r.font.size=Pt(25); r.font.color.rgb=RGBColor(15,76,129)
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run('软件使用说明与功能测试报告'); r.font.size=Pt(18); r.font.color.rgb=RGBColor(55,65,81)
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run('Windows 本地版  |  版本：软件正式版_20261021  |  2026-10-24'); r.font.size=Pt(10); r.font.color.rgb=RGBColor(107,114,128)
doc.add_paragraph('本手册面向数据录入、检查分析、状态维护和报告编制人员，既用于日常操作，也用于本地版本验收。所有示例均使用项目内的模拟数据或隔离副本，正式数据库不会被测试流程改写。')
add_table(doc,['内容','说明'],[['运行方式','Windows 本地 Electron 桌面软件，双击启动脚本即可运行，不依赖网页入口'],['数据范围','检测记录、历次大修、管状态维护、可视化、三维模型、报告导出'],['本次验证','静态检查 + 桌面交互 + 真实格式样例 + 窗口尺寸与多视图验证']], [1.3,5.1])
doc.add_page_break()

heading(doc,'1. 快速开始')
doc.add_paragraph('1. 在项目根目录双击“启动软件正式版_20261021.cmd”。软件以本地窗口启动，数据保存在本机数据库；关闭窗口后可再次启动。')
doc.add_paragraph('2. 首次使用建议先进入“数据工作台”导入检测数据，再进入“状态处理”校核状态，最后在“数据可视化”和“报告中心”查看或导出结果。')
doc.add_paragraph('3. 测试时请使用项目提供的模拟数据目录，不要直接覆盖正式数据库。自动化测试会在 tmp 目录创建 test.db 副本。', style='Intense Quote')

heading(doc,'2. 数据工作台')
doc.add_paragraph('数据工作台用于导入检测记录、查看备注原文、按基地/机组/大修筛选，并为后续状态识别和报告生成提供数据来源。')
for s in ['选择“导入检测数据”，选择 Excel/CSV 文件；导入向导会识别基地、机组、大修和检测字段。','使用基地、机组、大修筛选器缩小范围；筛选变化后表格、统计和选中项会同步刷新。','备注字段按原文保存，不在导入时删减；状态识别只从备注中提取结构化状态，来源单独保存。','在表格中双击可编辑允许编辑的字段；保存后重新筛选确认值已写入数据库。']: doc.add_paragraph(s, style='List Bullet')
add_image(doc, TMP/'manual-annotated'/'状态导入预览_标注.png', '图 2-1 数据导入/状态预览界面标注图', 6.2)
add_table(doc,['编号','界面区域','作用'],[['1','识别结果摘要','显示识别基地、大修数量和已选记录'],['2','批量确认策略','统一处理没有方向信息的移位记录'],['3','勾选列','选择需要导入的记录'],['4','状态列','显示正常、堵管、移位、换管'],['5','位移量','显示距离与方向'],['6','备注原文','保留源表备注，可直接复核'],['7','来源列','记录原始文件和行号'],['8','确认导入','将勾选记录写入数据库']], [0.55,1.5,4.3])
add_image(doc, TMP/'manual-figures'/'01_导入进度.png', '图 2-2 导入进度与动态反馈', 6.2)
add_image(doc, TMP/'manual-figures'/'02_状态导入失败重试.png', '图 2-3 状态导入失败后的重试路径', 6.2)

heading(doc,'3. 管状态处理')
doc.add_paragraph('状态处理是维护管子生命周期状态的主界面。软件支持自动识别基地，不要求先手工选择基地；支持导入、预览、确认、筛选批量删除、一键全部正常和导出。')
add_table(doc,['状态','业务含义','识别提示'],[['正常','未发现需要维护的异常状态','正常、完好等'],['堵管','封堵/堵管，表示管道被封堵处理','封堵、堵管'],['移位','割管移位或位置发生迁移','割管移位、移位；距离可保留在备注'],['换管','更换管子或整管替换','换管、更换']], [1.0,2.7,2.7])
doc.add_paragraph('操作步骤：')
for s in ['点击“导入状态表”，选择维护表格；系统自动识别基地、机组、大修、管号和状态。','先查看预览，再确认导入；备注原文完整保留，来源文件/来源列单独显示。','用状态、基地、机组、大修筛选后勾选记录，可执行批量删除；删除前会弹出中文确认框。','需要批量复位时使用“一键全部正常”；修改后导出状态维护表，用于归档或再次导入。']: doc.add_paragraph(s, style='List Number')
doc.add_paragraph('重要限制：一次预览的安全识别记录最多 2000 条。跨多个大修的全量表超过上限时，请按机组或大修拆分后分别导入；出现该提示不代表软件无响应。')
add_image(doc, TMP/'state-maintenance-1792773680557'/'import-1480.png', '图 3-1 状态表导入预览界面', 6.2)
add_image(doc, TMP/'state-maintenance-1792773680557'/'delete-confirm.png', '图 3-2 筛选后的批量删除确认', 5.4)

heading(doc,'4. 数据可视化')
doc.add_paragraph('数据可视化用于从基地、机组、大修和状态分布等维度分析检查结果。筛选栏与图表联动，支持基地多选；鼠标悬浮可查看数量，切换导航后数据保持缓存，避免重复加载。')
doc.add_paragraph('可视化页面按“筛选范围→数据质量→实时指标→主趋势→P位/管板→状态/热力→单管→历次大修台账”组织。每个子界面的用途如下：')
add_table(doc,['子界面','主要内容','适用问题'],[['实时分析','当前范围、覆盖率、异常数量、状态数量','当前筛选范围是否完整'],['群厂磨损趋势','大修轮次与报告磨损量合计','哪些机组/轮次较高'],['P1-P5分层趋势','P位深度与相邻大修增量','磨损集中在哪个轴向位置'],['管板更换分布','50通道管板、颜色编码更换次数','更换是否集中'],['机组排行','割管、累计更换、堵管、重换率','群厂对比与优先级'],['P位集中度/偏度','集中度、偏度和加速点','判断局部集中或加速'],['管子四态分布','正常、堵管、移位、换管','生命周期状态构成'],['F2管位热力','深度颜色和同期增量','定位高深度/高增量管位'],['单管轴向展开','真实缺陷位置、P1-P6','核对管长位置'],['C1-C8演变','历次矩阵和单通道曲线','追踪长期变化'],['机组台账','历次趋势、管板、矩阵、摘要','形成机组结论']], [1.35,2.7,2.3])
for s in ['累计换管次数按机组范围统计，不要求绑定具体大修。','悬浮图表或管板位置可查看数量、深度、管号和同期增量。','颜色采用设置中的磨损深度/状态色阶；不额外使用奇数/偶数外圈颜色。']: doc.add_paragraph(s, style='List Bullet')
for s in ['先选基地范围，再按需要选择机组或大修；累计换管次数按机组范围统计，不要求绑定某一次大修。','优先阅读总览、趋势和管板状态分布，再下钻到单管明细。相同机组记录按机组聚合排列。','颜色采用设置中的磨损深度/状态颜色；颜色只表达数据含义，不再额外强调奇数或偶数机组。']: doc.add_paragraph(s, style='List Bullet')
add_image(doc, TMP/'manual-annotated'/'可视化总览_标注.png', '图 4-1 数据可视化总览界面标注图', 6.2)
add_image(doc, TMP/'manual-figures'/'05_可视化_磨损趋势.png', '图 4-2 群厂磨损趋势：悬浮查看与统计口径', 6.2)
add_image(doc, TMP/'manual-figures'/'06_可视化_P位趋势.png', '图 4-3 P1-P5 分层趋势与图例', 6.2)
add_image(doc, TMP/'manual-figures'/'07_可视化_管板详情.png', '图 4-4 管板分布与单管详情联动', 6.2)
add_image(doc, TMP/'manual-figures'/'08_可视化_小窗口.png', '图 4-5 小窗口下的双列卡片布局', 6.2)
add_table(doc,['编号','界面区域','阅读方法'],[['1','基地范围','支持群厂/多基地筛选'],['2','机组/大修筛选','控制当前统计口径'],['3','关键指标卡','显示记录、机组/大修和覆盖率'],['4','机组检查概览','按机组聚合最大深度和记录数'],['5','P位构成','显示P1-P5报告深度与记录数量'],['6','通道磨损次数','按通道查看超过阈值的次数']], [0.55,1.5,4.3])
add_image(doc, TMP/'visualization-1792773681518'/'plate-fullscreen.png', '图 4-2 管板分布全窗口查看', 6.2)

heading(doc,'5. 三维缺陷模型')
doc.add_paragraph('三维模型用于查看整体布置、管板和缺陷位置。模型设置图标可切换视图；俯视管板图与管板孔位保持对齐，选中管子后会高亮并在右侧显示实时信息。')
add_table(doc,['操作','效果'],[['鼠标中键按住拖动','平移模型'],['滚轮','缩放'],['双击模型','回归默认居中视角'],['点击管子/孔位','高亮选中并更新右侧信息栏'],['模型设置/视图按钮','切换整体、管板、接头等视角']], [2.3,4.1])
add_image(doc, TMP/'manual-annotated'/'三维模型_标注.png', '图 5-1 三维缺陷模型界面标注图', 6.2)
add_image(doc, TMP/'manual-figures'/'03_三维_管板视图.png', '图 5-2 三维模型管板视图', 6.2)
add_image(doc, TMP/'manual-figures'/'04_三维_整体装配.png', '图 5-3 三维模型整体装配视图', 6.2)
add_table(doc,['编号','界面区域','操作说明'],[['1','模型视图切换','整体、接口、整管、管座、管板平面'],['2','检测记录筛选','按当前范围筛选缺陷记录'],['3','模型设置','控制管板、透明度和显示选项'],['4','三维方向标','辅助理解空间方向'],['5','视角与管号','切换视角与当前管号'],['6','选中管子信息','显示状态、位置、缺陷和备注']], [0.55,1.5,4.3])
add_image(doc, TMP/'reference-model'/'top-plate-aligned.png', '图 5-2 俯视管板与孔位对齐', 6.2)

heading(doc,'6. 报告中心')
doc.add_paragraph('报告中心仅保留“结果报告”和“历次大修对比报告”两个主要入口，避免重复选择。报告范围由当前筛选条件决定，导出文件的名称按基地、机组、大修、报告类型和时间生成，便于归档。')
add_table(doc,['界面区域','字段/按钮','功能'],[['报告表头设置','基地、机组、大修','决定数据库结果范围'],['人工信息','电厂名称、报告单编号、检查类型','写入当前报告表头'],['设备信息','设备/部件、安全等级、方向号、材料、尺寸','还原原版报告字段'],['输出文件','标准数据表、历次演变、检验报告单','按类型生成文件'],['配置对比','历史大修/本次大修','仅比较同基地同机组'],['生成报告单','生成检验报告单','合并表头与数据库结果']], [1.25,2.0,3.1])
for s in ['结果报告：输出当前筛选范围的检查结果、状态、缺陷和备注。','历次大修对比报告：按同一机组的历次大修顺序（001、002……）对比变化。','导出前先确认基地/机组/大修筛选；生成后检查表格字体、列宽、页眉和备注是否完整。','表格支持在界面内双击编辑可编辑字段；编辑后的内容再导出，避免另开编辑窗口。']: doc.add_paragraph(s, style='List Bullet')

heading(doc,'7. 软件设置')
doc.add_paragraph('设置入口位于右上角图标。设置页用于维护本地数据库、状态/磨损颜色、数据源和审计配置，并为后续接入服务器数据保留接口。当前版本默认本地数据库，不上传数据。')
add_table(doc,['设置分类','可配置内容','影响范围'],[['数据存储','本地数据库位置、连接状态、服务器接入预留','决定数据读写来源'],['导入与显示','文件来源、解析方式、管板显示参数','影响导入识别与可视化'],['状态与颜色','四种状态、磨损深度色阶','影响标签和图表颜色'],['审计与日志','导入、编辑、删除、导出记录','用于追溯操作'],['窗口与交互','窗口尺寸、加载反馈','改善大数据量操作']], [1.4,2.8,2.1])

heading(doc,'8. 实测功能测试结果')
add_table(doc,['测试项','结果','说明'],[['静态检查','通过','JavaScript/ESM 共 65 个文件，失败 0 个'],['状态维护导入/筛选/批量删除','关键流程通过','自动识别基地、备注保留、失败重试、筛选删除均有证据'],['数据可视化','通过','筛选联动、多视图、窗口尺寸、HTTP 失败清理通过'],['三维模型','通过','参考模型、管板孔位、选中隔离、视角和响应式尺寸通过'],['设置自动化脚本','待复测','脚本等待旧的 nav[data-view=settings] 选择器超时；当前产品入口为右上角设置图标']], [2.0,1.2,3.2])
doc.add_paragraph('测试证据目录：`tmp/visualization-1792773681518`、`tmp/reference-model`、`tmp/state-maintenance-1792773680557`、`tmp/settings-workspace-1792773681212`。测试数据库均为隔离副本。')

heading(doc,'9. 常见问题')
add_table(doc,['现象','处理方法'],[['导入后没有反应','观察导入进度；检查文件是否包含管号/状态列；超过 2000 条时按大修或机组拆分。'],['备注内容变化','软件应保留备注原文，来源单独列出；若导出不一致，先检查是否编辑后未保存。'],['基地缩写不一致','惠州使用 HZ，陆丰使用 LF，苍南使用 CN；导入时可由系统自动识别。'],['模型未加载','确认使用正式版启动入口，等待资源加载；双击模型可回到默认视角。'],['窗口尺寸过小','最大化窗口后再操作；可视化和报告表格支持滚动/缩放。'],['担心测试影响正式数据','测试使用 tmp 下数据库副本，不直接修改 data/thimble.db。']], [1.8,4.6])

heading(doc,'附录 A：本次测试数据')
doc.add_paragraph('主要测试数据位于 `03_模拟测试数据/管子生命周期模拟数据_v2_非真实`：检测记录及状态 Excel、全量状态维护 Excel、按机组拆分 CSV、模拟数据库和核验截图。真实格式样例来自项目原始资料目录，仅用于验证字段识别与导出流程。')

heading(doc,'附录 B：启动与备份建议')
doc.add_paragraph('日常启动：双击项目根目录的 `启动软件正式版_20261021.cmd`。升级或大量导入前，先复制 `01_当前软件/软件正式版_20261021/data/thimble.db` 到备份目录，并以日期+版本命名。')

# footer
for section in doc.sections:
    f=section.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER; rr=f.add_run('在役检查系统-指套管数据管理工具  |  本地版使用说明'); rr.font.size=Pt(8); rr.font.color.rgb=RGBColor(107,114,128)

OUT.parent.mkdir(parents=True, exist_ok=True); doc.save(OUT); print(OUT)
