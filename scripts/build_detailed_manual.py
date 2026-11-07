# -*- coding: utf-8 -*-
"""Build the detailed Chinese Word manual for the native Windows desktop app.

The manual is generated from the current desktop test evidence. Screenshots are
annotated on an expanded canvas so callouts stay outside the controls rather
than covering the UI.
"""
from __future__ import annotations

from pathlib import Path
from datetime import date
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(r"D:\work-projects\在役检查系统-指套管数据管理工具")
QT_ROOT = ROOT / "08_Qt移植版"
TMP = ROOT / "05_测试与验证" / "03_自动化临时产物" / "manual-qt-20261106"
OUT_DIR = ROOT / "07_软件发布包"
OUT = OUT_DIR / "在役检查系统-指套管数据管理工具_详细使用手册_2026-11-06.docx"
FIG_DIR = TMP / "figures"
FONT_PATH = Path(r"C:\Windows\Fonts\simsun.ttc")
FONT_BOLD_PATH = Path(r"C:\Windows\Fonts\simsun.ttc")


def pil_font(size: int):
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


def set_run_font(run, size: float = 12, bold: bool | None = None, color: str = "000000"):
    run.font.name = "宋体"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "SimSun")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "SimSun")
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    run._element.get_or_add_rPr().rFonts.set(qn("w:cs"), "SimSun")
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold


def set_style_font(style, size=12, bold=False, color="000000"):
    style.font.name = "宋体"
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "SimSun")
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "SimSun")
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    style._element.get_or_add_rPr().rFonts.set(qn("w:cs"), "SimSun")
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold


def shade(cell, fill="F4F6F7"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def cell_margins(cell, top=90, start=120, bottom=90, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths_dxa):
    total = sum(widths_dxa)
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    ind = tbl_pr.find(qn("w:tblInd"))
    if ind is None:
        ind = OxmlElement("w:tblInd")
        tbl_pr.append(ind)
    ind.set(qn("w:w"), "0")
    ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            cell.width = Inches(widths_dxa[idx] / 1440)
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths_dxa[idx]))
            tc_w.set(qn("w:type"), "dxa")
            cell_margins(cell)


def add_table(doc, headers, rows, widths_dxa=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for idx, value in enumerate(headers):
        cell = table.rows[0].cells[idx]
        shade(cell, "E8EEF5")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(value))
        set_run_font(r, 10.5, True)
    for row in rows:
        cells = table.add_row().cells
        for idx, value in enumerate(row):
            cell = cells[idx]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(value))
            set_run_font(r, 10.5)
    if widths_dxa:
        set_table_geometry(table, widths_dxa)
    return table


def add_para(doc, text="", style=None, bold=False, align=None, before=0, after=6, first_indent=True):
    p = doc.add_paragraph(style=style)
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.5
    if first_indent and style not in ("List Bullet", "List Number"):
        p.paragraph_format.first_line_indent = Cm(0.74)
    if text:
        r = p.add_run(text)
        set_run_font(r, 12, bold)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    r = p.add_run(text)
    set_run_font(r, 12)
    return p


def add_number(doc, text):
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    r = p.add_run(text)
    set_run_font(r, 12)
    return p


def add_note(doc, title, text, fill="F4F6F9"):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    shade(cell, fill)
    cell_margins(cell, 130, 170, 130, 170)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(f"{title}：")
    set_run_font(r, 12, True)
    r = p.add_run(text)
    set_run_font(r, 12)
    set_table_geometry(table, [9600])
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.line_spacing = 1.3
    p.paragraph_format.first_line_indent = None
    for run in p.runs:
        set_run_font(run, 14 if level == 1 else 12.5, True)
    return p


def add_caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    set_run_font(r, 10.5)
    return p


def add_figure(doc, path: Path, caption: str, width=6.45):
    if not path.exists():
        add_note(doc, "截图缺失", f"未找到截图：{path}", "FFF4F2")
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Inches(width))
    add_caption(doc, caption)


def page_break(doc):
    doc.add_page_break()


def annotate(src: Path, dst: Path, title: str, callouts, left=290, right=30, top=64):
    """Expand the screenshot and place numbered callouts outside the UI."""
    src_im = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (src_im.width + left + right, src_im.height + top), "white")
    canvas.paste(src_im, (left, top))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.width, top), fill="#EEF3F6")
    draw.text((20, 17), title, font=pil_font(27), fill="#000000")
    draw.text((20, 43), "编号说明位于截图外侧，未遮挡软件控件", font=pil_font(15), fill="#000000")
    for idx, item in enumerate(callouts, 1):
        label, x, y, side, row = item
        tx = left + x
        ty = top + y
        pin_r = 9
        draw.ellipse((tx - pin_r, ty - pin_r, tx + pin_r, ty + pin_r), fill="#B53B35", outline="white", width=2)
        draw.text((tx - 5, ty - 8), str(idx), font=pil_font(14), fill="white")
        box_h = 48
        box_w = max(185, min(left - 28, 24 + len(label) * 16))
        by = top + row
        if side == "left":
            bx = 16
            anchor = (bx + box_w, by + box_h // 2)
            line_end = (left - 5, by + box_h // 2)
        else:
            bx = left + src_im.width + 8
            box_w = min(right - 16, max(185, 24 + len(label) * 16))
            anchor = (bx, by + box_h // 2)
            line_end = (left + src_im.width + 5, by + box_h // 2)
        draw.line((tx, ty, line_end[0], line_end[1]), fill="#B53B35", width=3)
        draw.rounded_rectangle((bx, by, bx + box_w, by + box_h), radius=7, fill="#FFFDF6", outline="#B53B35", width=2)
        draw.text((bx + 10, by + 9), f"{idx}. {label}", font=pil_font(16), fill="#000000")
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG", optimize=True)


def build_figures():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    evidence = ROOT / "05_测试与验证" / "03_自动化临时产物" / "qt-audit-20261105-234104" / "artifacts"
    professional = QT_ROOT / "验证" / "04_界面截图"
    settings = evidence
    states = professional
    ref = evidence
    viz = evidence
    night = evidence
    pairs = [
        (
            professional / "审计-01-workspace-light.png",
            "01_数据工作台_标注.png",
            "数据工作台总览",
            [
                ("主导航栏", 160, 28, "left", 82),
                ("筛选条件区", 450, 93, "left", 145),
                ("导入与导出操作", 120, 174, "left", 208),
                ("检测记录表", 430, 262, "left", 272),
                ("管板分布", 1080, 370, "left", 336),
                ("本地连接状态与设置", 1375, 30, "left", 400),
            ],
        ),
        (
            evidence / "审计-03-analytics-light.png",
            "02_数据可视化_标注.png",
            "数据可视化总览与页签导航",
            [
                ("基地范围筛选", 220, 130, "left", 80),
                ("机组/大修筛选", 360, 180, "left", 144),
                ("总体概况、磨损趋势", 370, 290, "left", 208),
                ("管板分布、变化与状态", 590, 290, "left", 272),
                ("概况图表与管板排行", 500, 600, "left", 336),
            ],
        ),
        (
            professional / "审计-04-reports-light.png",
            "03_报告中心_标注.png",
            "报告中心总览",
            [
                ("结果报告入口", 70, 90, "left", 78),
                ("历次大修对比入口", 190, 90, "left", 142),
                ("报告范围选择", 470, 165, "left", 206),
                ("导出格式与生成按钮", 1250, 284, "left", 270),
                ("报告预览与缩放", 760, 410, "left", 334),
            ],
        ),
        (
            professional / "审计-05-states-light.png",
            "04_状态维护_标注.png",
            "管状态维护总览",
            [
                ("管板状态网格", 430, 173, "left", 76),
                ("当前管编辑区", 1070, 210, "left", 140),
                ("备注原文与来源", 1090, 420, "left", 204),
                ("已维护记录筛选", 520, 510, "left", 268),
                ("批量删除与分页", 1230, 675, "left", 332),
            ],
        ),
        (
            ref / "审计-02-threeD-click.png",
            "05_三维模型_标注.png",
            "三维模型与画布交互验证界面",
            [
                ("视图切换与方向控制", 410, 130, "left", 75),
                ("管板与管束模型", 400, 420, "left", 140),
                ("检测数据详情（选中后显示）", 570, 180, "left", 205),
                ("管号选择与模型控制", 400, 735, "left", 270),
            ],
        ),
    ]
    for src, name, title, callouts in pairs:
        if src.exists():
            annotate(src, FIG_DIR / name, title, callouts)
    # Direct copies used where the screenshot itself is already self-explanatory.
    direct = {
        "06_设置_数据存储_标注.png": settings / "审计-07-settings-01-settingsDataPane.png",
        "09_设置_导入与显示.png": settings / "审计-07-settings-03-settingsImportPane.png",
        "10_设置_备份与维护.png": settings / "审计-07-settings-06-settingsMaintenancePane.png",
        "11_设置_界面与工作流.png": settings / "审计-07-settings-02-settingsPreferencesPane.png",
        "12_设置_对比规则.png": settings / "审计-07-settings-04-settingsRulesPane.png",
        "13_设置_账户与权限.png": settings / "审计-07-settings-05-settingsAccountsPane.png",
    }
    for name, src in direct.items():
        if src.exists():
            image = Image.open(src).convert("RGB")
            draw = ImageDraw.Draw(image)
            if name == "06_设置_数据存储_标注.png":
                draw.rectangle((267, 232, 1050, 293), fill="#F3F6F8")
                draw.text((278, 253), "（安装时指定的数据目录）\\thimble.db", font=pil_font(15), fill="#334155")
            elif name == "10_设置_备份与维护.png":
                draw.rectangle((264, 235, 1050, 271), fill="white")
                draw.text((267, 244), "（由用户选择的本地备份目录）", font=pil_font(15), fill="#334155")
            elif name == "13_设置_账户与权限.png":
                draw.rectangle((264, 158, 449, 194), fill="white")
                draw.rectangle((702, 158, 909, 194), fill="white")
                draw.text((267, 166), "当前用户", font=pil_font(15), fill="#13243A")
                draw.text((705, 166), "本地账户", font=pil_font(15), fill="#13243A")
            image.save(FIG_DIR / name, "PNG", optimize=True)
    return FIG_DIR


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("第 ")
    set_run_font(run, 10.5)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)
    run = paragraph.add_run(" 页")
    set_run_font(run, 10.5)


def configure_document(doc):
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)
    styles = doc.styles
    for name in ("Normal", "Body Text", "Caption", "List Bullet", "List Number"):
        if name in styles:
            set_style_font(styles[name], 12, False)
            styles[name].paragraph_format.line_spacing = 1.5
            styles[name].paragraph_format.space_after = Pt(6)
    for name, size in (("Title", 20), ("Heading 1", 14), ("Heading 2", 12.5), ("Heading 3", 12)):
        if name in styles:
            set_style_font(styles[name], size, True)
            styles[name].paragraph_format.space_before = Pt(12 if name != "Title" else 0)
            styles[name].paragraph_format.space_after = Pt(6)
            styles[name].paragraph_format.line_spacing = 1.25
    # Real list indentation, keeping wrapped lines aligned beneath the text.
    for name in ("List Bullet", "List Number"):
        if name in styles:
            styles[name].paragraph_format.left_indent = Cm(0.95)
            styles[name].paragraph_format.first_line_indent = Cm(-0.48)
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = header.add_run("在役检查系统-指套管数据管理工具｜本地 Windows 版")
    set_run_font(hr, 9.5)
    footer = section.footer.paragraphs[0]
    add_page_number(footer)


def build_document(fig_dir: Path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document()
    configure_document(doc)

    # Cover
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(45)
    r = p.add_run("在役检查系统-指套管数据管理工具")
    set_run_font(r, 20, True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("软件详细操作说明书")
    set_run_font(r, 18, True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("图文并茂版｜本地 Windows 桌面软件")
    set_run_font(r, 12)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(22)
    r = p.add_run("发布版本：2026.11.06.5\n编制日期：2026 年 11 月 6 日")
    set_run_font(r, 12)
    add_note(doc, "适用对象", "数据录入人员、检查分析人员、状态维护人员、报告编制人员和软件管理员。")
    add_note(doc, "文档说明", "本说明书以当前 Qt 主版本和项目内隔离测试数据为依据，覆盖可见界面、弹窗、导入导出、可视化、三维模型、设置、审计及异常反馈。")
    page_break(doc)

    # Contents
    add_heading(doc, "目录", 1)
    for item in [
        "0 安装与卸载",
        "1 软件定位与运行环境",
        "2 启动、导航与通用交互",
        "3 数据工作台",
        "4 管状态维护",
        "5 数据可视化",
        "6 三维缺陷模型",
        "7 报告中心与导出",
        "8 软件设置",
        "9 审计、通知与动态反馈",
        "10 数据字段、状态规则与文件命名",
        "11 常见问题与处理建议",
        "12 功能测试与验收记录",
        "附录：推荐日常操作流程",
    ]:
        add_para(doc, item, first_indent=False, after=4)
    add_note(doc, "阅读方式", "正文中的截图编号与标注编号一一对应；操作步骤按“先筛选范围、再查看数据、最后编辑或导出”的顺序编排。")
    page_break(doc)

    add_heading(doc, "0 安装与卸载", 1)
    add_para(doc, "本节适用于 Windows x64 安装包“在役检查系统-指套管数据管理工具-安装包-2026.11.06.5-x64.exe”。安装程序无需管理员权限，安装位置和业务数据位置可分别选择。")
    add_number(doc, "双击安装包启动向导，按提示继续；在“选择安装位置”页可修改程序目录。默认目录为当前 Windows 用户的 LocalAppData\\Programs\\在役检查系统-指套管数据管理工具。")
    add_number(doc, "在“选择数据存放目录”页指定业务数据目录。默认值为 %LOCALAPPDATA%\\ThimbleInspection\\user-data；可改到其他有读写权限的本机磁盘目录。程序目录与数据目录分离。")
    add_number(doc, "按需勾选创建桌面快捷方式，完成安装后从桌面快捷方式或开始菜单启动。首次运行会按所选数据目录初始化本地运行数据。")
    add_number(doc, "卸载时从 Windows“设置→应用→已安装的应用”找到本软件并选择卸载，也可使用开始菜单中的卸载入口。卸载会移除程序，不会自动删除独立数据目录。")
    add_note(doc, "数据保留", "卸载或更换电脑前先确认数据库和备份已妥善保存。若要彻底清除本机数据，需在卸载完成后自行检查并删除安装时指定的数据目录；重装前也应确认继续使用正确的数据目录。", "FFF4F2")
    page_break(doc)

    add_heading(doc, "1 软件定位与运行环境", 1)
    add_para(doc, "本软件是面向指套管在役检查数据的本地 Windows 桌面工具，采用 Qt 原生桌面壳承载界面，默认使用本机 SQLite 数据库。软件不要求联网，正式数据库、导出文件和备份文件均保存在本机。")
    add_para(doc, "软件将检测记录、缺陷信息、管状态维护信息、历次大修、可视化分析和报告输出集中到同一数据链路中。所有界面共享统一的基地、机组和大修范围，范围变化后相关表格、图表、模型和报告预览同步更新。")
    add_table(doc, ["项目", "当前版本说明"], [
        ["发布版本", "Windows x64 安装版 2026.11.06.5；另可在开发环境使用“启动Qt主版本.cmd”。"],
        ["数据存储", "本地 SQLite；设置中可查看当前数据库位置、大小和校验状态。"],
        ["主要对象", "检测记录、通道/堆芯位置、幅值、相位、磨损深度、磨损位置、备注、状态、移位距离和来源。"],
        ["基地接口", "已为大亚湾、岭澳、惠州（HZ）、陆丰（LF）、苍南（CN）等基地预留筛选与识别接口。"],
        ["报告类型", "结果报告、历次大修对比报告；报告纸张和导出图片保持白色背景。"],
        ["安全原则", "批量删除、数据库恢复、清空数据库等破坏性操作必须经过中文确认；测试使用隔离副本。"],
    ], [2500, 7100])
    add_note(doc, "重要提示", "不要直接在资源管理器中替换正在使用的数据库文件。升级、清空或大量导入前，应先在“软件设置→备份与维护”中创建备份。", "FFF4F2")

    add_heading(doc, "2 启动、导航与通用交互", 1)
    add_para(doc, "启动后首先进入“数据工作台”。顶部导航统一包含数据工作台、三维缺陷模型、数据可视化、报告中心和状态处理；右上角设置图标用于打开独立的软件设置窗口，通知图标用于查看导入、保存、导出和异常反馈。")
    add_figure(doc, fig_dir / "01_数据工作台_标注.png", "图 2-1 数据工作台与主导航标注")
    add_table(doc, ["通用操作", "具体行为", "使用建议"], [
        ["导航切换", "点击顶部工作区即可切换；已加载的数据和筛选状态尽量保留，避免重复加载。", "先在数据工作台确认范围，再切换到可视化或报告。"],
        ["设置", "点击右上角齿轮图标打开独立设置窗口；关闭只关闭设置窗口，不影响主工作区。", "数据库、颜色和对比规则修改后立即在本机保存。"],
        ["通知", "右上角铃铛显示未读数量；导入、导出、保存、失败重试等操作会显示动态反馈。", "出现错误时先看通知文本，再决定重试或检查文件。"],
        ["窗口与缩放", "支持窗口缩放、最大化和 125%/150% Windows 显示缩放。", "窗口过窄时使用页面滚动；表格和报告预览支持内部滚动或缩放。"],
        ["夜间模式", "设置中切换日间/夜间；数据语义颜色仍保持可读，导出的报告和 PNG 保持白底。", "夜间模式用于长时间浏览，不改变数据库内容。"],
    ], [2300, 4500, 2800])
    add_note(doc, "操作习惯", "界面中下拉框、按钮和表头均采用中文；带图标的按钮在鼠标悬停时会给出功能提示。遇到灰色按钮，通常表示尚未完成必要的范围选择或当前没有可操作记录。")
    page_break(doc)

    add_heading(doc, "3 数据工作台", 1)
    add_para(doc, "数据工作台是所有检测数据进入软件后的主入口，承担导入、筛选、浏览、选择、单元格编辑、导出和数据清理功能。左侧为检测记录表，右侧为管板分布；表格选择和管板高亮互相联动。")
    add_heading(doc, "3.1 筛选与记录浏览", 2)
    add_number(doc, "先选择基地，再选择机组和大修；可补充分析人员、通道编号或套管编号等条件。")
    add_number(doc, "点击“应用筛选”后，检测记录、记录总数和右侧管板分布按同一范围刷新。")
    add_number(doc, "使用表头复选框选择当前页，或逐行选择；选择不会因为翻页而丢失。")
    add_number(doc, "滚动表格查看完整字段；长备注在单元格中保留原文，必要时横向滚动查看。")
    add_heading(doc, "3.2 导入检测数据", 2)
    add_para(doc, "点击“导入数据”后进入导入向导。向导支持 Excel、CSV 等结构化文件，也支持从原始采集数据目录读取并转换为统一字段。导入过程包含选择文件、识别字段、预览校验、执行入库和结果反馈五个阶段。")
    add_table(doc, ["阶段", "系统行为", "用户应检查的内容"], [
        ["选择文件", "显示文件名、大小和来源路径。", "确认选择的是原始检测数据或维护表格，不要误选报告输出文件。"],
        ["识别字段", "自动识别基地、机组、大修、管号、堆芯位置、幅值、相位、深度、备注等字段。", "检查字段映射；表头名称不同但含义相同的字段会进入同一标准字段。"],
        ["预览校验", "显示有效行、缺失字段、重复记录、异常数值和可识别状态。", "重点检查备注原文、状态、移位距离和来源列。"],
        ["执行入库", "显示解析、校验、入库进度；成功后刷新统计。", "不要在进度反馈未结束前重复点击导入。"],
        ["结果反馈", "显示新增、更新、跳过、失败和可下载的审计清单。", "失败记录可按提示修正后重试，成功记录不会重复导入。"],
    ], [1900, 4000, 3700])
    add_note(doc, "导入截图说明", "本说明书未采集系统原生文件选择框和逐行导入预览画面；上述步骤依据隔离数据库的检测数据、CSV 状态批量预览和提交测试编写。")
    add_note(doc, "备注保留规则", "备注字段按原始文件原文保存，不删减、不改写、不把来源拼入备注。结构化识别出的状态、方向和距离单独写入对应字段；来源文件、工作表、行号单独写入来源列。", "FFF4F2")
    add_heading(doc, "3.3 表格实时编辑、选择与导出", 2)
    add_bullet(doc, "允许编辑的单元格可双击进入编辑状态，修改后按“保存”或回车提交；不需要另开编辑窗口。")
    add_bullet(doc, "编辑后软件即时更新数据库记录、操作审计和相关可视化；重新筛选可验证修改已经写入。")
    add_bullet(doc, "“导出综合台账”用于导出当前筛选范围的标准数据；导出字段与数据库标准表头保持一致。")
    add_bullet(doc, "“删除所选”只对已勾选记录生效；“回收站”用于查看可恢复记录，永久删除需要二次确认。")
    add_bullet(doc, "右侧管板支持点击位置查看数量、管号、深度和状态；导出图片使用当前视图和当前筛选范围。")
    page_break(doc)

    add_heading(doc, "4 管状态维护", 1)
    add_para(doc, "状态维护用于管理每根指套管的当前生命周期状态和历次维护记录。页面按照“范围选择→状态网格→当前管编辑→已维护记录”的顺序组织。状态颜色明显区分，备注原文和来源列分开保存。")
    add_figure(doc, fig_dir / "04_状态维护_标注.png", "图 4-1 状态维护主界面标注")
    add_heading(doc, "4.1 状态及复合处理的业务含义", 2)
    add_table(doc, ["状态", "业务含义", "识别同义词/处理规则"], [
        ["正常", "当前范围内未发现需要维护的异常状态，或经人工确认正常。", "正常、完好、未见异常等。"],
        ["堵管", "管子被封堵或堵管处理，表示已采取封堵维护。", "封堵、堵管、堵塞等统一识别为堵管。"],
        ["移位", "管子发生移位；“割管移位”整体按移位处理。", "割管移位、移位、移位后保留等；距离有则单独记录，无则保留状态。"],
        ["换管", "管子已更换或整管替换。", "换管、更换、替换、重换等。累计换管次数按机组统计，不要求绑定某一次大修。"],
        ["复合处理", "同一管在一次维护中同时发生两项或多项处理。", "按页面勾选各项处理；涉及换管时还需确认其他处理发生在换管前或后，顺序不明则保留待核对。"],
    ], [1200, 3600, 4800])
    add_note(doc, "识别优先级", "状态识别先理解原始语义，再确定结构化状态；不能只靠固定表头或单个关键词。出现“封堵”按堵管处理，出现“割管移位”按移位处理，距离数据写入移位距离字段。")
    add_heading(doc, "4.2 导入维护表格", 2)
    add_number(doc, "点击“导入维护表格”，选择 Excel、CSV 或 Word 维护资料。无需提前选择基地。")
    add_number(doc, "系统从文件名、工作表、表头和内容中自动识别基地、机组、大修、通道编号、状态、距离、备注和来源。")
    add_number(doc, "在预览中核对状态、距离、备注原文和来源列；默认勾选可安全识别记录。")
    add_number(doc, "确认导入后写入状态维护数据库，并刷新状态网格、已维护记录和审计清单。")
    add_note(doc, "预览截图说明", "状态维护导入预览由所选文件动态生成；当前配图展示状态维护主界面与批量维护入口，不将主界面误标为预览结果。")
    add_heading(doc, "4.3 筛选、编辑与批量操作", 2)
    add_bullet(doc, "选择基地、机组、大修和状态后，已维护记录按范围更新；可使用管号/备注关键字进一步筛选。")
    add_bullet(doc, "点击管子网格中的管号，右侧显示状态、移位距离、备注原文、来源和历史记录。")
    add_bullet(doc, "修改状态、距离或备注后点击“保存状态”；保存成功会显示动态反馈并记录审计。")
    add_bullet(doc, "勾选多条记录后可批量删除；删除确认框使用中文说明，避免误操作。")
    add_bullet(doc, "使用“一键全部正常”可将当前完整范围内尚未维护的管子补齐为正常；该操作不会覆盖已有异常维护记录。")
    add_bullet(doc, "批量维护支持导入预览、批量确认、跳过异常行、导出 Excel 汇总和再次导入。")
    page_break(doc)

    add_heading(doc, "5 数据可视化", 1)
    add_para(doc, "数据可视化用于把检测结果从“记录表”转换为可分析的趋势、分布、状态和位置视图。页面主次顺序为：基地范围→质量提示→关键指标→趋势/管板/状态→单管详情。所有图表使用同一范围，不再重复要求选择不必要的检测范围。")
    add_figure(doc, fig_dir / "02_数据可视化_标注.png", "图 5-1 数据可视化总览、当前概况及四个页签导航")
    add_heading(doc, "5.1 基地和机组范围", 2)
    add_bullet(doc, "基地卡片支持单选或多选；惠州显示 HZ，陆丰显示 LF，苍南显示 CN。大亚湾与岭澳可按同一基地位置进行汇总展示。")
    add_bullet(doc, "机组和大修下拉框随基地范围联动；“全部机组”用于群厂概览，“全部大修”用于历史汇总。")
    add_bullet(doc, "累计换管次数属于机组级指标，只按所选机组统计，不要求选择具体大修。")
    add_heading(doc, "5.2 四个可视化页签", 2)
    add_table(doc, ["子界面", "展示内容", "适合回答的问题"], [
        ["总体概况", "基地覆盖、WAR/NDD/无检测记录、深度分布和管板排行摘要。", "当前范围的数据覆盖与总体分布如何？"],
        ["磨损趋势", "群厂、机组/大修以及 P 位层级的深度趋势和可比变化。", "哪些机组或位置值得查看历史变化？"],
        ["管板分布", "按所选范围呈现通道位置、深度或维护信息；支持查看选中管详情。", "高深度或已记录维护集中在哪里？"],
        ["变化与状态", "历次变化、状态构成与可比性提示；不把资料缺失推断为零。", "哪些变化需要进一步核实？"],
    ], [1800, 4200, 3600])
    add_note(doc, "页签截图范围", "现有验证截图记录了总体概况页和四个页签名称，未逐一采集各页签展开后的画面；各页签的图表会随范围、数据和选项变化。")
    add_heading(doc, "5.3 管板图、悬浮和高亮", 2)
    add_bullet(doc, "鼠标悬浮在图表或管板孔位上，可查看该数据点支持的统计信息；实际字段随图表类型而异。")
    add_bullet(doc, "单击可选择的管板位置会高亮该管，并显示与当前页签和范围对应的记录详情。")
    add_bullet(doc, "图表工具栏提供的全屏或 PNG 导出操作作用于当前图表；PNG 使用白底以便放入报告。")
    add_bullet(doc, "颜色按设置中的磨损深度色阶和状态颜色表达数据含义，不再使用奇数/偶数机组外圈颜色。")
    add_heading(doc, "5.4 统计口径说明", 2)
    add_note(doc, "深度颜色", "颜色表示本次范围内的报告磨损深度分级，不直接等同于风险等级；无量化深度、NDD、待核查和无检测记录应分别显示。")
    add_note(doc, "检测覆盖", "无检测记录不等于 NDD；覆盖率、WAR 记录、有效深度和状态记录分别统计。")
    add_note(doc, "换管次数", "统计该机组全部已记录大修中的明确换管事件；移位和割管移位不计入换管次数。")

    heading_3d = add_heading(doc, "6 三维缺陷模型", 1)
    heading_3d.paragraph_format.page_break_before = True
    add_para(doc, "三维模型用于理解管板、管束、管座和缺陷位置的空间关系。模型页与可视化筛选范围联动，选中管子后右侧信息栏实时显示当前记录。")
    add_figure(doc, fig_dir / "05_三维模型_标注.png", "图 6-1 三维模型、视图切换与画布控制")
    add_table(doc, ["操作", "结果"], [
        ["鼠标中键按住拖动", "平移模型；用于查看被遮挡的管板区域。"],
        ["滚轮", "缩放模型；缩放后仍保持当前选中管。"],
        ["双击模型", "恢复最默认、居中的视角和缩放。"],
        ["点击管子/孔位", "高亮当前管，右侧信息栏同步刷新缺陷、状态、距离、备注和来源。"],
        ["俯视/管板视图", "管板孔位与管板图保持一致，便于从二维位置核对三维模型。"],
        ["模型设置图标", "切换管板、整体、接口、透明度和显示选项；设置图标保留在模型工具区域。"],
    ], [3000, 6600])
    add_note(doc, "查看建议", "先用基地/机组/大修范围缩小数据，再进入三维模型；模型只显示当前范围内的有效记录，避免在全库数据上查找单管。")

    add_heading(doc, "7 报告中心与导出", 1)
    add_para(doc, "报告中心只保留“结果报告”和“历次大修对比报告”两个入口。审计功能已经放入设置中的“导入与显示”或“备份与维护”区域，不再额外占用报告中心导航。")
    add_figure(doc, fig_dir / "03_报告中心_标注.png", "图 7-1 报告入口、范围选择与尚未生成时的预览区域")
    add_heading(doc, "7.1 结果报告", 2)
    add_number(doc, "选择基地、机组和本次大修；可使用“工作台范围”直接继承当前筛选。")
    add_number(doc, "检查报告表头：电厂名称、机组、检验类型、设备/部件、安全等级、房间号、材料、尺寸、探头信息等。")
    add_number(doc, "检查结果表：序号、通道编号、堆芯位置、显示类型、幅值、磨损深度、磨损位置、测量通道、备注。")
    add_number(doc, "在报告预览中使用“适配、缩放、上一页/下一页”；表格单元格可双击编辑，保存后再导出。")
    add_number(doc, "选择 Excel、Word 或报告单格式导出；导出后检查表头、字体、列宽和备注是否完整。")
    add_heading(doc, "7.2 历次大修对比报告", 2)
    add_para(doc, "对比报告按同一基地、同一机组的第一次大修开始编号（001、002、003……），展示历次深度、状态、位置和变化。对比规则只用于判断两次大修是否属于同一位置/同一管号，不会改变原始检测数据。")
    add_table(doc, ["对比项目", "规则说明"], [
        ["范围", "同一基地、同一机组；不跨机组直接匹配。"],
        ["大修顺序", "按该机组历史最早大修开始连续编号。"],
        ["位置匹配", "以通道编号、管号、堆芯位置和位置容差为依据。"],
        ["容差", "默认 0.01 mm，可在设置→对比规则中建立新版本。"],
        ["输出", "展示新增、延续、消失、深度变化、状态变化和备注。"],
    ], [2300, 7300])
    add_note(doc, "编辑原则", "报告在线编辑只在报告表格上双击完成，不打开另一个独立编辑窗口。编辑内容保存后才会进入后续导出文件。")
    page_break(doc)

    add_heading(doc, "8 软件设置", 1)
    add_para(doc, "设置窗口是独立的本地配置窗口，顶部显示软件设置、本地 SQLite 状态和关闭按钮。左侧六个分类分别对应数据存储、界面与工作流、导入与显示、对比规则、账户与权限、备份与维护。")
    add_figure(doc, fig_dir / "06_设置_数据存储_标注.png", "图 8-1 设置窗口与数据存储标注")
    add_figure(doc, fig_dir / "09_设置_导入与显示.png", "图 8-2 设置：导入与显示")
    add_figure(doc, fig_dir / "10_设置_备份与维护.png", "图 8-3 设置：备份与维护")
    add_figure(doc, fig_dir / "11_设置_界面与工作流.png", "图 8-4 设置：界面与工作流")
    add_figure(doc, fig_dir / "12_设置_对比规则.png", "图 8-5 设置：对比规则")
    add_figure(doc, fig_dir / "13_设置_账户与权限.png", "图 8-6 设置：本地账户、角色与密码管理")
    add_table(doc, ["设置分类", "功能覆盖", "修改后影响"], [
        ["数据存储", "查看数据库引擎、数据库大小、路径；刷新状态；校验数据库。", "决定当前本地数据读写位置。"],
        ["界面与工作流", "日间/夜间、工作区密度、交互动画、启动工作区、记住上次工作区、无符号移位默认方向。", "影响界面显示和操作反馈，不改变业务数据。"],
        ["导入与显示", "Report 使用策略、磨损深度色阶、质量与导入审计。", "影响识别提示、颜色、质量检查与审计清单。"],
        ["对比规则", "查看当前版本、容差、创建并激活新规则版本。", "只改变后续对比匹配，不改变原始数据和既有报告。"],
        ["账户与权限", "查看当前账户；创建/停用账户、配置角色、修改或重置密码、退出登录。", "账户权限及会话状态影响可执行的操作；角色变更会使旧会话失效。"],
        ["备份与维护", "数据库备份、恢复、操作审计、数据库去重和状态检查。", "影响数据安全维护；恢复和清理均需确认。"],
    ], [2100, 4300, 3200])
    add_note(doc, "服务器预留", "当前版本仍以本地 SQLite 为准；设置中保留数据源接口和校验逻辑，为后续接入服务器数据做好准备，但不会自动启用远程连接。", "FFF4F2")

    add_heading(doc, "9 审计、通知与动态反馈", 1)
    add_para(doc, "软件在导入、保存、删除、恢复、导出和数据库校验等操作中提供动态反馈，避免用户误以为软件卡死。反馈包括按钮忙碌状态、进度阶段、成功提示、失败原因、重试入口和审计记录。")
    add_table(doc, ["反馈类型", "示例", "处理方式"], [
        ["短反馈", "“管状态已保存”“已导出 Excel”。", "继续当前工作；必要时在通知中心查看详情。"],
        ["长任务", "导入解析、批量状态维护、数据库校验。", "等待进度结束，不重复点击；可查看阶段和预计数量。"],
        ["失败反馈", "文件格式错误、字段缺失、服务暂不可用。", "按提示修正文件或点击重试；失败不会静默写入数据库。"],
        ["审计记录", "导入批次、文件、工作表、行号、编辑、删除、导出。", "在设置中筛选批次和异常类型，导出审计清单。"],
    ], [2200, 3600, 3800])
    add_note(doc, "异常判断", "如果导入按钮点击后没有立即变化，先查看进度反馈和通知中心；系统通常正在解析或校验大文件。超过预览上限时请按机组或大修拆分。")

    add_heading(doc, "10 数据字段、状态规则与文件命名", 1)
    add_heading(doc, "10.1 统一数据表头", 2)
    add_table(doc, ["字段", "含义", "录入/导出要求"], [
        ["通道编号", "检测通道或记录通道编号。", "保留原始编号；报告中统一用“/”分隔复合信息。"],
        ["堆芯位置", "管子在堆芯/管板中的位置。", "用于管板定位、报告和历次对比。"],
        ["幅值（V）", "检测信号幅值。", "保留数值和单位。"],
        ["相位", "检测相位数据。", "保留原始值。"],
        ["磨损深度", "缺陷深度或壁厚百分比。", "无量化值显示“/”或待核查，不改写备注。"],
        ["三字符", "原始报告中的三字符标识。", "按源表原样保留。"],
        ["测量通道", "测量通道/记录通道。", "表头不同但含义相同可自动映射。"],
        ["磨损位置", "P 位、轴向位置或距离。", "用于 P 位趋势和单管展开。"],
        ["探头类型", "检测探头类型。", "原样保存。"],
        ["分析人员", "分析/复核人员。", "用于筛选和审计。"],
        ["数据、数据组", "原始采集数据及分组信息。", "按原始文件保留，可导出查看。"],
        ["备注", "原始文本说明。", "必须原文完整保留。"],
        ["堵管移位信息", "结构化维护状态、移位距离等。", "状态与来源单独列，备注不拼接来源。"],
    ], [1900, 3900, 3800])
    add_heading(doc, "10.2 文件命名规则", 2)
    add_para(doc, "软件导出的文件按“数据类型_基地_机组_大修范围_输出时间_唯一标识.扩展名”组织。名称中不使用模糊的“新建文件”或重复覆盖名称，便于归档、检索和再次导入。")
    add_table(doc, ["文件类型", "示例命名结构"], [
        ["检测数据台账", "检测数据_宁德_N1_全部大修_20261030-123000_xxxxx.xlsx"],
        ["状态维护表", "管状态维护_大亚湾_D1_第009次大修_20261030-123000_xxxxx.xlsx"],
        ["结果报告", "结果报告_防城港_F2_第003次大修_20261030-123000_xxxxx.docx"],
        ["历次对比报告", "历次大修对比_宁德_N1_001-009_20261030-123000_xxxxx.xlsx"],
        ["图表 PNG", "TH_最新检测深度分布_全部基地_全部机组_各机组最新轮次_时间_唯一标识.png"],
        ["数据库备份", "TH_数据库备份_manual_YYYYMMDD-HHMMSS_唯一标识.db"],
    ], [2400, 7200])
    page_break(doc)

    add_heading(doc, "11 常见问题与处理建议", 1)
    add_table(doc, ["问题现象", "原因判断", "处理方法"], [
        ["软件打不开", "启动入口、端口或本地服务未正常启动。", "使用正式版启动入口；检查是否残留旧进程；查看本地日志后重新启动。"],
        ["导入后没有反应", "文件较大，仍在解析/校验；或字段无法识别。", "等待进度反馈；检查是否存在管号、基地、机组、大修或状态字段；按大修拆分后重试。"],
        ["备注不完整", "误把备注与来源拼接，或编辑后未保存。", "检查预览中的备注原文和来源独立列；保存后再导出。"],
        ["地图/管板不更新", "筛选范围未应用，或正在读取数据。", "点击“应用筛选/刷新数据”，等待动态反馈；查看当前范围文本。"],
        ["颜色太浅或不一致", "使用了旧缓存或未读取设置色阶。", "进入设置→导入与显示，检查磨损深度颜色；切换工作区后重新查看。"],
        ["模型看不清", "窗口过小、视角偏移或未选中目标。", "双击模型回归居中；用中键拖动和滚轮调整；点击管子查看右侧详情。"],
        ["导出文件没有信息", "范围未选择、导出格式不匹配或预览数据为空。", "先确认基地/机组/大修范围，再在报告预览中检查记录数后导出。"],
        ["对比结果不理解", "对比规则只用于位置匹配，不是风险等级。", "在设置→对比规则查看当前容差和版本；同一机组按 001、002 顺序比较。"],
        ["夜间模式仍有白底", "报告纸张和导出图片设计为白底。", "软件界面应为暗色；报告纸张、报告导出和 PNG 白底属于预期效果。"],
    ], [2400, 3200, 4000])

    add_heading(doc, "12 功能测试与验收记录", 1)
    add_para(doc, "本手册使用当前软件的隔离测试数据库和实际项目资料结构进行验证。测试重点覆盖业务逻辑、交互、窗口尺寸、夜间模式、导入导出、报告预览、三维模型和设置。")
    add_table(doc, ["测试类别", "结果", "验证内容"], [
        ["静态与语法检查", "通过", "npm run check 通过；Qt 主界面及设置审计未报告控制台或客户端错误。"],
        ["Python 业务测试", "通过", "435 个用例均有通过证据；包含分组补测，非单次完整全量运行。"],
        ["设置工作区", "通过", "6 个设置分区均可进入；覆盖 SQLite 状态、备份/恢复、对比规则和账户权限界面。"],
        ["UI 视图审计", "通过", "5 个主视图、6 个设置分区、5 个主视图暗色画面通过；无水平溢出，报错列表为空。"],
        ["数据库导入/导出", "通过", "隔离库导入 9,795 条检测记录、8,750 条状态记录；台账与报告文件结构有效。"],
        ["生命周期批量导入", "通过", "模拟数据含 14,025 条检测记录及 12,600 条维护状态；重复导入幂等，超限预览零写入。"],
        ["报告与三维交互", "通过", "报告两个页签可切换；三维画布事件可触发；DOCX/XLSX/对比 DOCX 结构有效。"],
        ["安装包启动", "通过", "2026.11.06.5 x64 安装器已在当前 Windows 11 x64 环境完成隔离安装、启动与卸载验证；首次管理员页可达，Qt bridgeReady/QWebChannel 与主路由、设置窗口可达，卸载后安装目录清理且选定数据目录数据库保留；不代表其他 Windows 版本均已验证。"],
        ["未覆盖范围", "说明", "未逐一自动化点击所有按钮；原生文件对话框及各可视化页签展开画面未逐张采集。"],
    ], [2600, 1400, 5600])
    add_note(doc, "测试数据安全", "测试使用 tmp 目录下的隔离数据库副本，不直接修改正式 data/thimble.db；正式数据库操作前仍建议执行一次备份。")

    add_heading(doc, "附录：推荐日常操作流程", 1)
    for text in [
        "启动软件后进入数据工作台，确认右上角显示本地 SQLite 已连接。",
        "导入检测数据，完成字段识别、备注原文和来源列核对，再确认入库。",
        "使用基地、机组、大修筛选查看检测记录；必要时双击单元格编辑并保存。",
        "进入状态维护导入维护表格，检查状态或复合处理、移位距离、备注原文和来源。",
        "进入数据可视化，按基地/机组范围查看群厂趋势、P 位、管板和状态分布。",
        "选中重点管后进入三维模型，核对空间位置、缺陷位置和历史维护。",
        "进入报告中心生成结果报告或历次大修对比报告；在预览表格上双击修订后导出。",
        "回到设置检查审计和备份，按日期和版本保留数据库、报告和导出文件。",
    ]:
        add_number(doc, text)
    add_para(doc, "导出前核对：范围、记录数、备注原文、状态、距离、来源、报告表头、字体、列宽、文件名和输出目录。", first_indent=False, after=0)

    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    figures = build_figures()
    path = build_document(figures)
    print(path)
