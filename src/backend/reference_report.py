"""Source-form report templates for the Ningde comprehensive report.

This module is intentionally independent from ``analysis_reporting``. It
operates on a retained copy of the original Word package and changes only the
selected table's cell text. The original .doc/.docx is never opened for write.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile
try:
    from .report_forms import fit_form_labels, wrapped_note_height
except ImportError:
    from report_forms import fit_form_labels, wrapped_note_height

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ET.register_namespace("w", W)
FONT_NAME = "宋体"


def _normalize_docx_fonts(parts):
    """Force generated Word runs to use one consistent Chinese font."""
    for name, raw in list(parts.items()):
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        changed = fit_form_labels(root)
        for run in root.findall(".//w:r", NS):
            properties = run.find("w:rPr", NS)
            if properties is None:
                properties = ET.Element(f"{{{W}}}rPr")
                run.insert(0, properties)
            fonts = properties.find("w:rFonts", NS)
            if fonts is None:
                fonts = ET.Element(f"{{{W}}}rFonts")
                style = properties.find("w:rStyle", NS)
                if style is not None:
                    properties.insert(list(properties).index(style) + 1, fonts)
                else:
                    properties.insert(0, fonts)
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                key = f"{{{W}}}{attribute}"
                if fonts.get(key) != FONT_NAME:
                    fonts.set(key, FONT_NAME)
                    changed = True
        if changed:
            parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return parts

TEMPLATE_ROOT_NAME = "宁德综合报告"
MANIFEST_NAME = "manifest.json"
REFERENCE_NAME = "reference.docx"
SCHEMA_VERSION = 1

_LABEL_RE = re.compile(r"^(序号|通道编号|堆芯位置|显示类型|幅值|磨损|测量|备注|设备/部件|电厂名称|机组|检查类型|检验|材料|尺寸|安全等级|房间号|报告|日期|签名|版本|状态|编写|审核|批准|时间|姓名|个人剂量|方法/级别|证书编号|发证机构|有效期至|设备名称|设备型号|设备编号|出厂编号|数据标识号|数据组编号)$")


def _root(service) -> Path:
    return Path(service.ROOT) / "assets" / "report-templates" / TEMPLATE_ROOT_NAME


def _load_manifest(service) -> dict:
    path = _root(service) / MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8"))


def _template_path(service) -> Path:
    return _root(service) / REFERENCE_NAME


def _text(node) -> str:
    paragraphs = node.findall("w:p", NS)
    if paragraphs:
        return "\n".join(_text(paragraph) for paragraph in paragraphs)
    out = []
    for child in node.iter():
        if child.tag == f"{{{W}}}t":
            out.append(child.text or "")
        elif child.tag in (f"{{{W}}}br", f"{{{W}}}cr"):
            out.append("\n")
        elif child.tag == f"{{{W}}}tab":
            out.append("\t")
    return "".join(out)


def _attr(node, name: str, default=None):
    return node.get(f"{{{W}}}{name}", default) if node is not None else default


def _display(value, *, blank="/"):
    if value is None:
        return blank
    value = str(value)
    return blank if not value.strip() or value.strip() == "-" else value


def _set_text(cell, value):
    """Replace cell text without flattening source paragraph/run formatting."""
    value = str(value if value is not None else "")
    if _text(cell) == value:
        return
    source_paragraphs = cell.findall("w:p", NS)
    prototypes = source_paragraphs or [ET.Element(f"{{{W}}}p")]
    for paragraph in source_paragraphs:
        cell.remove(paragraph)
    for index, item in enumerate(value.split("\n")):
        prototype = prototypes[min(index, len(prototypes) - 1)]
        paragraph = deepcopy(prototype)
        run_prototype = paragraph.find("w:r", NS)
        rpr = deepcopy(run_prototype.find("w:rPr", NS)) if run_prototype is not None else None
        for child in list(paragraph):
            if child.tag != f"{{{W}}}pPr":
                paragraph.remove(child)
        if item:
            run = ET.SubElement(paragraph, f"{{{W}}}r")
            if rpr is not None:
                run.append(rpr)
            text = ET.SubElement(run, f"{{{W}}}t")
            text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            text.text = item
        cell.append(paragraph)


def _cell_matrix(table):
    matrix = []
    for ri, row in enumerate(table.findall("w:tr", NS)):
        cells = []
        for ci, cell in enumerate(row.findall("w:tc", NS)):
            cells.append((ri, ci, cell))
        matrix.append(cells)
    return matrix


def _cell_key(table_index: int | str, row: int, col: int) -> str:
    return f"t{table_index}:r{row}:c{col}"


def _find_cell(table, row: int, col: int):
    rows = table.findall("w:tr", NS)
    if 0 <= row < len(rows):
        cells = rows[row].findall("w:tc", NS)
        if 0 <= col < len(cells):
            return cells[col]
    return None


def _table_model(table_index: int, table, *, source_values=True):
    cells = []
    rows = []
    for ri, row in enumerate(table.findall("w:tr", NS)):
        line = []
        for ci, cell in enumerate(row.findall("w:tc", NS)):
            value = _text(cell)
            line.append(value)
            cells.append({
                "key": _cell_key(table_index, ri, ci),
                "label": f"表{table_index} 第{ri + 1}行第{ci + 1}列",
                "value": value if source_values else "",
                "source_value": value,
                "type": "number" if re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", value or "") else "text",
                "editable": True,
            })
        rows.append(line)
    return rows, cells


def catalog(service) -> dict:
    manifest = _load_manifest(service)
    templates = []
    for table in manifest["tables"]:
        index, key = table["source_index"], table["key"]
        if key not in {"inspection", "comparison"}:
            continue
        mode = "comparison" if key == "comparison" else "inspection"
        formats = ["docx", "xlsx"]
        templates.append({
            "id": key, "title": table["title"], "mode": mode, "formats": formats,
            "table_index": index, "rows": table["row_count"],
            "editable": key not in {"core_map"},
        })
    return {"schema_version": SCHEMA_VERSION, "templates": templates}


def _template_for(manifest, template_id: str) -> dict:
    aliases = {"inspection": "inspection", "comparison": "comparison"}
    wanted = aliases.get(template_id, template_id)
    for item in manifest["tables"]:
        if item["key"] == wanted:
            return item
    raise ValueError(f"未知报告模板：{template_id}")


def _inspection_rows(snapshot):
    rows = []
    for index, item in enumerate(snapshot.get("values") or [], 1):
        values = list(item)
        if len(values) >= 9:
            # source table has eight visible columns; the analyst is a report
            # metadata field in the current source form and is not a ninth cell.
            values = values[:8]
        displayed = [_display(value) for value in values]
        for column, spec in ((4, ".2f"), (5, "g")):
            if column < len(values) and isinstance(values[column], (int, float)):
                displayed[column] = format(values[column], spec)
        rows.append(displayed)
    return rows


def _snapshot_rows(snapshot):
    """Return selected database rows without reading any template values."""
    return snapshot.get("rows_data") or []


def _strip_template_values(template, rows, metadata):
    """Clear historical source facts; only report labels survive by default."""
    index = template["source_index"]
    # Fixed-format data tables are populated from the selected report snapshot.
    if template["key"] in {"inspection", "comparison"}:
        return rows
    cleaned = []
    for ri, row in enumerate(rows):
        result = []
        for ci, value in enumerate(row):
            literal = (value or "").strip()
            # Keep clear structural labels in first/header rows, but never
            # mistake old data values, signatories, IDs or dates for labels.
            preserve = bool(_LABEL_RE.match(literal)) and ri == 0
            if template["key"] == "contract_cover":
                preserve = ri in (6, 9, 11, 12, 13, 14, 15) and (
                    not literal or bool(re.search(r"[A-Za-z\u4e00-\u9fff/：:]", literal))
                )
                if ri in (5, 8, 10, 12, 14):
                    preserve = False
            if template["key"] == "approval_cover":
                preserve = (ri in (0, 1, 2, 3, 4, 10, 12) and
                            (not literal or _LABEL_RE.match(literal) or literal in {
                                "内部控制", "CGN Inspection Technology Co.,Ltd.", "中广核检测技术有限公司",
                                "本文件产权属中广核检测技术有限公司所有，未经许可，不得以任何方式外传。"}))
                if ri in (1, 2, 4, 9):
                    preserve = False
            if template["key"] in {"core_cover", "inspection_cover", "signals_cover", "quality_plan_cover"}:
                preserve = literal.startswith(("附录", "附件")) or literal in {
                    "反应堆中子通量测量指套管堆芯位置示意图",
                    "反应堆中子通量测量指套管涡流检验报告单",
                    "超标显示（伤深＞50%壁厚）涡流显示信号图",
                    "已完成的质量计划",
                }
            if template["key"] in {"equipment", "qualifications", "dose", "data_groups", "revisions"}:
                preserve = ri == 0
            if template["key"] == "core_map":
                preserve = literal.startswith("图")
            result.append(value if preserve else "")
        cleaned.append(result)
    if template["key"] == "data_groups":
        groups = sorted({str(item).strip() for item in metadata.get("_calgroups", []) if str(item).strip()})
        out = [cleaned[0] if cleaned else ["序号", "数据标识号", "数据组编号", "备注"]]
        for number, group in enumerate(groups, 1):
            out.append([str(number), "", group, ""])
        return out
    return cleaned


def _comparison_rows(snapshot):
    rows = []
    for item in snapshot.get("values") or []:
        values = list(item)
        # source table: seq, tube, position, current(3), historical(3), result.
        row = [_display(values[i] if i < len(values) else None) for i in range(10)]
        for column in (3, 6):
            if column < len(values) and isinstance(values[column], (int, float)):
                row[column] = f"{values[column]:.2f}"
        for column in (4, 7):
            if column < len(values) and isinstance(values[column], (int, float)):
                row[column] = f"{values[column]:g}"
        rows.append(row)
    return rows


def _core_image(service, snapshot) -> bytes | None:
    """Create a database-driven, non-historical core map for the appendix."""
    import struct
    import zlib
    width, height = 720, 720
    pixels = bytearray([255, 255, 255] * width * height)
    rows = snapshot.get("rows_data") or []
    positions = {str(row.get("position") or "") for row in rows}
    findings = {str(row.get("position") or ""): row for row in rows}
    # Render only selected database coordinates; no sample/reference map image
    # or old inspection state is copied into the generated report.
    xs, ys, cell = 18, 18, 28
    for label in positions:
        match = re.fullmatch(r"([A-R])(\d{1,2})", label.upper())
        if not match:
            continue
        col, row_no = ord(match.group(1)) - ord("A"), int(match.group(2)) - 1
        x0, y0 = xs + col * cell, ys + row_no * cell
        if x0 + cell >= width or y0 + cell >= height:
            continue
        row = findings.get(label, {})
        color = (220, 38, 38) if str(row.get("indication") or "").upper() not in ("", "NDD") else (219, 234, 254)
        for y in range(y0, y0 + cell - 2):
            for x in range(x0, x0 + cell - 2):
                if x in (x0, x0 + cell - 3) or y in (y0, y0 + cell - 3):
                    rgb = (100, 116, 139)
                else:
                    rgb = color
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = bytes(rgb)
    raw = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _selected_rows(service, snapshot):
    try:
        from .analysis_reporting import rows_for
    except ImportError:
        from analysis_reporting import rows_for
    rows = rows_for(service, snapshot.get("site", ""), snapshot.get("unit", 0), snapshot.get("outage", ""))
    selected_ids = {row[0] for row in snapshot.get("sources", []) if row and row[-1] == "是"}
    return [row for row in rows if row["id"] in selected_ids] if selected_ids else rows


def _blank_data_rows(rows, start, end):
    for ri in range(start, min(end, len(rows))):
        for ci in range(len(rows[ri])):
            rows[ri][ci] = ""


def prepare(service, snapshot: dict, payload: dict | None = None) -> dict:
    """Attach a source-form draft to a normal report snapshot before hashing."""
    payload = payload or {}
    template_id = payload.get("template_id")
    if not template_id:
        return snapshot
    manifest = _load_manifest(service)
    if str(template_id) not in {"inspection", "comparison"}:
        raise ValueError("仅支持检验报告单和检验结果比对表")
    template = _template_for(manifest, str(template_id))
    expected = "comparison" if template["key"] == "comparison" else "inspection"
    if snapshot.get("kind") not in (expected, "data", "validation"):
        raise ValueError("报告模板与当前结果类型不一致")
    if snapshot.get("kind") == "comparison" and expected != "comparison":
        raise ValueError("检验结果比对表只能使用比对模板")
    if snapshot.get("kind") == "inspection" and expected == "comparison":
        raise ValueError("检验报告单不能使用比对模板")
    source = _template_path(service)
    database_rows = _selected_rows(service, snapshot)
    with ZipFile(source) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        source_tables = document.find("w:body", NS).findall("w:tbl", NS)
        table = source_tables[template["source_index"]]
        source_rows, cells = _table_model(template["source_index"], table)
    page_models = []
    # Source history is never used as a default for manual personnel/equipment
    # fields. Result/comparison values are explicitly supplied by the snapshot.
    if template["key"] == "inspection":
        values = _inspection_rows(snapshot)
        # Populate one source form per selected record page. Current original
        # report slot capacity is 20, and each continuation is a source table.
        chunks = [values[i:i + 20] for i in range(0, len(values), 20)] or [[]]
        source_rows = []
        cells = []
        page_models = []
        for page_no, chunk in enumerate(chunks):
            # Use each authentic continuation table once, then clone the last
            # continuation form for reports with more than five pages.
            table_index = min(11 + page_no, 15)
            edit_index = table_index if page_no < 5 else f"{table_index}p{page_no + 1}"
            source_table = source_tables[table_index]
            _normalize_inspection_data_rows(source_table)
            rows, page_cells = _table_model(edit_index, source_table)
            # Validation derives from the generated value, never old source data.
            for cell in page_cells:
                cell["type"] = "text"
            # Clear source-specific header metadata/signatures before filling
            # the limited values known from the selected database.
            for ri, row in enumerate(rows):
                for ci in range(len(row)):
                    if ri == 0:
                        row[ci] = ("涡流检验报告单（TH）" if ci == 1 else "")
                    elif ri == 9:
                        row[ci] = row[ci] if ci < 8 else ""
                    elif ri == 31:
                        continue
                    elif ri >= 30:
                        row[ci] = "" if ci != 0 else ("备注：\n/" if ri == 30 else row[ci])
                    elif ri < 8 and ci % 2 == 1:
                        row[ci] = ""
            metadata = snapshot.get("metadata") or {}
            row0 = rows[0]
            for ci in (0, 2):
                if ci < len(row0):
                    label = "设备/部件编号" if ci == 0 else "报告单编码"
                    row0[ci] = f"{label}：{metadata.get(label, '') or ''}"
            meta_fields = {
                1: {1: metadata.get("电厂名称", ""), 3: str(snapshot.get("unit", "")), 5: metadata.get("检查类型", "")},
                2: {1: metadata.get("设备/部件名称", "指套管"), 3: metadata.get("安全等级", ""), 5: metadata.get("房间号", "")},
                3: {1: metadata.get("检验范围", ""), 3: metadata.get("材料", ""), 5: metadata.get("尺寸", "")},
                4: {1: metadata.get("涡流仪型号", ""), 3: metadata.get("涡流仪出厂编号", ""), 5: metadata.get("标定管编号", "")},
                5: {1: metadata.get("探头类型", ""), 3: metadata.get("探头型号", ""), 5: metadata.get("探头规格", "")},
                6: {1: metadata.get("检验速度", ""), 3: metadata.get("采样率", "")},
                7: {1: metadata.get("检验频率", ""), 3: metadata.get("检验程序/版次", "")},
            }
            for mr, cols in meta_fields.items():
                for mc, value in cols.items():
                    if mr < len(rows) and mc < len(rows[mr]):
                        rows[mr][mc] = str(value or "")
            _blank_data_rows(rows, 10, 30)
            for ri, row in enumerate(chunk, 10):
                if ri < len(rows):
                    for ci, value in enumerate(row):
                        if ci < len(rows[ri]):
                            rows[ri][ci] = value
            page_models.append({"table_index": table_index, "edit_index": edit_index, "rows": rows, "cells": page_cells})
            cells.extend(page_cells)
        template = dict(template)
        template["page_tables"] = [model["table_index"] for model in page_models]
    elif template["key"] == "comparison":
        values = _comparison_rows(snapshot)
        for ri, row in enumerate(values, 2):
            if ri < len(source_rows):
                for ci, value in enumerate(row):
                    if ci < len(source_rows[ri]):
                        source_rows[ri][ci] = value
        # Header outage labels are selected scope, not the historical template.
        if source_rows:
            source_rows[0][3] = str(snapshot.get("outage") or "")
            source_rows[0][4] = str(snapshot.get("old") or "")
        _blank_data_rows(source_rows, 2, len(source_rows) - 1)
        values = _comparison_rows(snapshot)
        header, footer = source_rows[:2], source_rows[-1:]
        if footer:
            footer[0][0] = "备注：\n" + service.comparison_note({**(snapshot.get("summary") or {}), "NDD": 0})
        source_rows = header + values + footer
    else:
        groups = sorted({row.get("calgroup") for row in database_rows if row.get("calgroup")})
        source_rows = _strip_template_values(template, source_rows, {**(snapshot.get("metadata") or {}), "_calgroups": groups})
    table_index = template["source_index"]
    by_key = {}
    if template["key"] == "inspection":
        for model in page_models:
            page_index = model["edit_index"]
            for ri, row in enumerate(model["rows"]):
                for ci, value in enumerate(row):
                    by_key[_cell_key(page_index, ri, ci)] = value
    else:
        by_key = {_cell_key(table_index, ri, ci): value for ri, row in enumerate(source_rows) for ci, value in enumerate(row)}
        # Rebuild locators from the sanitized/generated rows. Original source
        # values are not defaults, validation types, or values exposed to UI.
        cells = [{"key": _cell_key(table_index, ri, ci), "label": f"表{table_index + 1} 第{ri + 1}行第{ci + 1}列",
                  "type": "text", "editable": True}
                 for ri, row in enumerate(source_rows) for ci, value in enumerate(row)]
    edits = payload.get("draft_edits") or []
    if not isinstance(edits, list):
        raise ValueError("draft_edits必须是数组")
    edit_keys = [item.get("key") for item in edits if isinstance(item, dict)]
    if len(edit_keys) != len(set(edit_keys)):
        raise ValueError("draft_edits包含重复单元格")
    unknown = [item for item in edits if not isinstance(item, dict) or item.get("key") not in by_key]
    if unknown:
        raise ValueError("存在不属于当前报告模板的编辑项")
    audit, editable = [], []
    for cell in cells:
        key = cell["key"]
        source_value = by_key.get(key, "")
        value = source_value
        edit = next((item for item in edits if item.get("key") == key), None)
        if edit is not None:
            value = "" if edit.get("value") is None else str(edit.get("value"))
            if len(value) > 2000:
                raise ValueError("单元格内容不能超过2000个字符")
            if cell.get("type") == "number" and value.strip() not in {"", "/", "-"} and not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value.strip()):
                raise ValueError(f"{cell['label']}必须填写数字")
        cell["source_value"] = source_value
        cell["value"] = value
        if value != source_value:
            audit.append({"key": key, "label": cell["label"], "before": source_value, "after": value})
        editable.append(cell)
        by_key[key] = value
    # For edit pages such as inspection continuations, keep each original
    # table's values separately so no historical values or page styles leak.
    if template["key"] == "inspection":
        page_rows = []
        for page_no, model in enumerate(page_models):
            page_index = model["table_index"]
            rows = model["rows"]
            for ri, row in enumerate(rows):
                for ci in range(len(row)):
                    row[ci] = by_key.get(_cell_key(model["edit_index"], ri, ci), row[ci])
            page_rows.append(rows)
        source_rows = page_rows[0] if page_rows else []
        result_page_rows = page_rows
    else:
        for ri, row in enumerate(source_rows):
            for ci in range(len(row)):
                row[ci] = by_key.get(_cell_key(template["source_index"], ri, ci), row[ci])
        result_page_rows = []
    if template["key"] == "comparison" and snapshot.get("coverage"):
        expected = _comparison_rows(snapshot)
        actual = source_rows[2:-1]
        if len(actual) != len(expected) or any(row[:3] != original[:3] for row, original in zip(actual, expected)):
            raise ValueError("对比报告序号、通道编号和堆芯位置必须保留当前显示记录，不允许删改管号或行序")
    result = dict(snapshot)
    result.update({
        "template_id": template["key"], "reference_schema_version": SCHEMA_VERSION,
        "reference_table_index": template["source_index"], "reference_page_tables": template.get("page_tables", []),
        "reference_rows": source_rows, "reference_page_rows": result_page_rows,
        "editable_cells": [] if template["key"] == "core_map" else editable,
        "draft_audit": audit, "rows_data": database_rows,
    })
    result["template_source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    return result


def _selected_table_documents(service, snapshot):
    source = _template_path(service)
    index = int(snapshot["reference_table_index"])
    with ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    source_document = ET.fromstring(parts["word/document.xml"])
    tables = source_document.find("w:body", NS).findall("w:tbl", NS)
    document = ET.Element(f"{{{W}}}document")
    body = ET.SubElement(document, f"{{{W}}}body")
    values = snapshot.get("reference_rows") or []
    page_tables = snapshot.get("reference_page_tables") or [index]
    # Existing inspection continuation forms are separate landscape source
    # sections. Fill each from its own authentic original table.
    used = list(page_tables) if snapshot.get("template_id") == "inspection" else [index]
    for page_number in range(len(used)):
        table_index = used[page_number]
        # Reports beyond the five archived pages reuse the final continuation
        # layout, but retain independent data and editing locators.
        source_index = min(table_index, 15) if snapshot.get("template_id") == "inspection" else table_index
        table = deepcopy(tables[source_index])
        if snapshot.get("template_id") == "inspection":
            _normalize_inspection_data_rows(table)
        table_values = values
        if snapshot.get("template_id") == "inspection":
            table_values = (snapshot.get("reference_page_rows") or [])[page_number]
        original_rows = table.findall("w:tr", NS)
        if snapshot.get("template_id") == "comparison":
            # Keep the authentic two-row header and footer, cloning only its
            # data row geometry for the current selection.
            prototype, footer = deepcopy(original_rows[2]), deepcopy(original_rows[-1])
            for old in original_rows[2:]:
                table.remove(old)
            for _ in table_values[2:-1]:
                table.append(deepcopy(prototype))
            table.append(footer)
        elif len(table_values) != len(original_rows) and len(original_rows) > 1:
            for old in original_rows[1:]:
                table.remove(old)
            for _ in table_values[1:]:
                table.append(deepcopy(original_rows[1]))
        for ri, row in enumerate(table.findall("w:tr", NS)):
            for ci, cell in enumerate(row.findall("w:tc", NS)):
                value = table_values[ri][ci] if ri < len(table_values) and ci < len(table_values[ri]) else ""
                if snapshot.get("template_id") != "core_map" or ri != 0:
                    # Data snapshots already normalize missing values to "/".
                    # Leave structural empty cells blank and preserve untouched
                    # source runs/paragraph properties byte-for-byte.
                    _set_text(cell, "/" if value == "-" else value)
        if snapshot.get("template_id") == "inspection":
            _merge_inspection_groups(table, table_values)
            if page_number == len(used) - 1:
                _mark_inspection_blank_rows(table, table_values)
        elif snapshot.get("template_id") == "comparison":
            try:
                from .report_forms import comparison_layout
            except ImportError:
                from report_forms import comparison_layout
            comparison_layout(table, table_values[2:-1])
        if snapshot.get("template_id") == "comparison":
            original_body = source_document.find("w:body", NS)
            siblings = list(original_body)
            caption = deepcopy(siblings[siblings.index(tables[index]) - 1])
            body.append(caption)
        body.append(table)
        if page_number < len(used) - 1:
            p = ET.SubElement(body, f"{{{W}}}p")
            r = ET.SubElement(p, f"{{{W}}}r")
            ET.SubElement(r, f"{{{W}}}br", {f"{{{W}}}type": "page"})
    template = _template_for(_load_manifest(service), snapshot["template_id"])
    section = ET.fromstring(template["section"])
    for child in list(section):
        if child.tag in (f"{{{W}}}headerReference", f"{{{W}}}footerReference", f"{{{W}}}pgNumType"):
            section.remove(child)
    body.append(section)
    parts["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    # The source map contains historical locations; render a replacement map
    # from the selected database rows and swap only the referenced image part.
    if snapshot.get("template_id") == "core_map":
        rels = ET.fromstring(parts.get("word/_rels/document.xml.rels", b""))
        rid = None
        map_table = tables[index]
        data = map_table.find(".//v:imagedata", {"v": "urn:schemas-microsoft-com:vml"})
        if data is not None:
            rid = data.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relationship = next((r for r in rels if r.get("Id") == rid), None)
        if relationship is not None:
            media = "word/" + relationship.get("Target", "").replace("\\", "/")
            generated = _core_image(service, snapshot)
            if generated:
                parts[media] = generated
    # Start a small, valid OPC package; never copy unreferenced source report
    # headers, metadata, signatures, old findings, or signal images.
    keep = {"word/document.xml", "word/styles.xml", "word/fontTable.xml", "word/theme/theme1.xml"}
    out = {name: value for name, value in parts.items() if name in keep}
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    office_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = ET.Element(f"{{{package_rel_ns}}}Relationships")
    for number, (target, role) in enumerate((("styles.xml", "styles"), ("fontTable.xml", "fontTable"), ("theme/theme1.xml", "theme")), 1):
        ET.SubElement(rels, f"{{{package_rel_ns}}}Relationship", Id=f"rStyle{number}", Target=target,
                      Type=office_rel_ns + "/" + role)
    if snapshot.get("template_id") == "core_map" and relationship is not None:
        out[media] = parts[media]
        rels.append(deepcopy(relationship))
    out["word/_rels/document.xml.rels"] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
    roots = ET.Element(f"{{{package_rel_ns}}}Relationships")
    ET.SubElement(roots, f"{{{package_rel_ns}}}Relationship", Id="rId1", Target="word/document.xml",
                  Type=office_rel_ns + "/officeDocument")
    out["_rels/.rels"] = ET.tostring(roots, encoding="utf-8", xml_declaration=True)
    content_types = ET.fromstring(parts["[Content_Types].xml"])
    for item in list(content_types):
        if item.tag.endswith("Override") and item.get("PartName", "").lstrip("/") not in out:
            content_types.remove(item)
    out["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
    return _normalize_docx_fonts(out)


def _normalize_inspection_data_rows(table):
    """Restore standard columns where the archived form used a blank marker."""
    rows = table.findall("w:tr", NS)
    if len(rows) < 30:
        return
    standard = rows[10].findall("w:tc", NS)
    spans = [int(_field(cell, "w:tcPr/w:gridSpan", default="1")) for cell in standard]
    for row in rows[10:30]:
        cells = row.findall("w:tc", NS)
        current_spans = [int(_field(cell, "w:tcPr/w:gridSpan", default="1")) for cell in cells]
        if len(cells) == len(standard) and current_spans == spans:
            continue
        properties = row.find("w:trPr", NS)
        for child in list(row):
            row.remove(child)
        if properties is not None:
            row.append(properties)
        for cell in standard:
            row.append(deepcopy(cell))


def _mark_inspection_blank_rows(table, table_values):
    blank = next((ri for ri in range(10, min(30, len(table_values)))
                  if all(not str(value).strip() for value in table_values[ri])), None)
    if blank is None:
        return
    rows = table.findall("w:tr", NS)
    if blank >= len(rows):
        return
    marker = rows[blank]
    cells = marker.findall("w:tc", NS)
    if len(cells) < 2:
        return
    first, second = cells[:2]
    properties = first.find("w:tcPr", NS)
    if properties is None:
        properties = ET.Element(f"{{{W}}}tcPr")
        first.insert(0, properties)
    span = sum(int(_field(cell, "w:tcPr/w:gridSpan", default="1")) for cell in (first, second))
    grid_span = properties.find("w:gridSpan", NS)
    if grid_span is None:
        grid_span = ET.SubElement(properties, f"{{{W}}}gridSpan")
    grid_span.set(f"{{{W}}}val", str(span))
    width = sum(int(_field(cell, "w:tcPr/w:tcW", "w", "0") or 0) for cell in (first, second))
    tc_width = properties.find("w:tcW", NS)
    if tc_width is None:
        tc_width = ET.SubElement(properties, f"{{{W}}}tcW")
    tc_width.set(f"{{{W}}}w", str(width))
    tc_width.set(f"{{{W}}}type", "dxa")
    marker.remove(second)
    _set_text(first, "以下空白")


def _merge_inspection_groups(table, values):
    """Rebuild channel/position merges from current data, not archived findings."""
    rows = table.findall("w:tr", NS)
    for row in rows[10:30]:
        for cell in row.findall("w:tc", NS):
            properties = cell.find("w:tcPr", NS)
            if properties is not None:
                for merge in properties.findall("w:vMerge", NS):
                    properties.remove(merge)
    start = 10
    while start < min(30, len(values)):
        group = values[start][1:3]
        end = start + 1
        if len(group) == 2 and all(str(value).strip() not in {"", "/", "-"} for value in group):
            while end < min(30, len(values)) and values[end][1:3] == group:
                end += 1
        if end - start > 1:
            for ri in range(start, end):
                cells = rows[ri].findall("w:tc", NS)
                for ci in (1, 2):
                    properties = cells[ci].find("w:tcPr", NS)
                    if properties is None:
                        properties = ET.Element(f"{{{W}}}tcPr")
                        cells[ci].insert(0, properties)
                    ET.SubElement(properties, f"{{{W}}}vMerge",
                                  {f"{{{W}}}val": "restart" if ri == start else "continue"})
                    if ri != start:
                        _set_text(cells[ci], "")
        start = end


def _set_paragraph_alignment(cell, value):
    """Keep free-form notes readable instead of inheriting distributed alignment."""
    paragraph = cell.find("w:p", NS)
    if paragraph is None:
        return
    properties = paragraph.find("w:pPr", NS)
    if properties is None:
        properties = ET.Element(f"{{{W}}}pPr")
        paragraph.insert(0, properties)
    alignment = properties.find("w:jc", NS)
    if alignment is None:
        alignment = ET.SubElement(properties, f"{{{W}}}jc")
    alignment.set(f"{{{W}}}val", value)


def write(service, snapshot: dict, filename: str):
    if not snapshot.get("template_id"):
        raise ValueError("缺少source-form template_id")
    parts = _selected_table_documents(service, snapshot)
    service.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = service.REPORT_DIR / filename
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        try:
            temporary.replace(path)
        except OSError:
            # Some Windows user-data directories reject os.replace even when
            # source and target are siblings (for example encrypted or
            # redirected folders). Move the completed temporary file instead.
            try:
                shutil.move(str(temporary), str(path))
            except OSError:
                # A same-volume move can still be denied by EFS/AV filters.
                # Copy the completed archive, then remove only our temporary.
                shutil.copyfile(str(temporary), str(path))
                temporary.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    return {"filename": filename, "file_path": str(path), "download_url": "/api/download-report?name=" + service.quote(filename)}


def _field(node, path, name="val", default=None):
    return _attr(node.find(path, NS), name, default) if node is not None else default


def _source_cell(manifest, index, ri, ci, snapshot):
    table = manifest["tables"][index]
    if snapshot["template_id"] == "comparison" and ri >= 2:
        ri = len(table["rows"]) - 1 if ri == len(snapshot["reference_rows"]) - 1 else 2
    rows = table["rows"]
    row = rows[min(ri, len(rows) - 1)]
    return row["cells"][min(ci, len(row["cells"]) - 1)]


def _font_properties(source):
    paragraphs = source.get("paragraphs") or []
    paragraph = paragraphs[0] if paragraphs else {}
    runs = paragraph.get("runs") or []
    properties = runs[0].get("effective_properties", {}) if runs else {}
    fonts = properties.get("rFonts", {})
    size = float(properties.get("sz", {}).get("val", 21)) / 2
    family = FONT_NAME
    bold = "b" in properties and properties["b"].get("val", "1") not in {"0", "false"}
    align = paragraph.get("effective_properties", {}).get("jc", {}).get("val", "center")
    return family, size, bold, align


def _css_font(properties):
    return '"宋体", "SimSun"'


def _run_style(properties):
    style = [
        f"font-family:{_css_font(properties)}",
        f"font-size:{float(properties.get('sz', {}).get('val', 21)) / 2:g}pt",
    ]
    if properties.get("b", {}).get("val", "1") not in {"0", "false"} and "b" in properties:
        style.append("font-weight:bold")
    if properties.get("i", {}).get("val", "1") not in {"0", "false"} and "i" in properties:
        style.append("font-style:italic")
    underline = properties.get("u", {}).get("val", "single")
    if "u" in properties and underline != "none":
        style.append("text-decoration:underline")
    color = properties.get("color", {}).get("val")
    if color and color != "auto":
        style.append(f"color:#{color}")
    return ";".join(style)


def _paragraph_style(paragraph):
    properties = paragraph.get("effective_properties") or {}
    style = ["margin:0", "line-height:normal", "min-height:0"]
    alignment = (properties.get("jc") or {}).get("val", "left")
    alignment = {"both": "justify", "distribute": "justify"}.get(alignment, alignment)
    if alignment in {"left", "right", "center", "justify"}:
        style.append(f"text-align:{alignment}")
    indentation = properties.get("ind") or {}
    first_line = indentation.get("firstLine")
    hanging = indentation.get("hanging")
    if first_line is not None:
        style.append(f"text-indent:{float(first_line) / 20:g}pt")
    elif hanging is not None:
        style.append(f"text-indent:{-float(hanging) / 20:g}pt")
    if indentation.get("left") is not None:
        style.append(f"margin-left:{float(indentation['left']) / 20:g}pt")
    if indentation.get("right") is not None:
        style.append(f"margin-right:{float(indentation['right']) / 20:g}pt")
    spacing = properties.get("spacing") or {}
    if spacing.get("before") is not None:
        style.append(f"margin-top:{float(spacing['before']) / 20:g}pt")
    if spacing.get("after") is not None:
        style.append(f"margin-bottom:{float(spacing['after']) / 20:g}pt")
    line = spacing.get("line")
    if line is not None:
        line_rule = spacing.get("lineRule", "auto")
        if line_rule == "exact":
            style.append(f"line-height:{float(line) / 20:g}pt")
        elif line_rule == "atLeast":
            style.append(f"min-height:{float(line) / 20:g}pt")
        else:
            style.append(f"line-height:{float(line) / 240:g}")
    return ";".join(style)


def _paragraph_html(paragraph, text, source_paragraph):
    source_text = source_paragraph.get("text", "")
    runs = source_paragraph.get("runs") or []
    escaped = []
    if text == source_text and runs:
        for run in runs:
            value = html.escape(run.get("text") or "").replace("\n", "<br>").replace("\t", "&#9;")
            if value:
                escaped.append(f'<span style="{_run_style(run.get("effective_properties") or {})}">{value}</span>')
    elif text:
        properties = (runs[0].get("effective_properties") or {}) if runs else {}
        value = html.escape(text).replace("\n", "<br>").replace("\t", "&#9;")
        escaped.append(f'<span style="{_run_style(properties)}">{value}</span>')
    return f'<p style="{_paragraph_style(source_paragraph)}">{"".join(escaped)}</p>'


def _cell_html(source, cell):
    source_paragraphs = source.get("paragraphs") or []
    paragraphs = cell.findall("w:p", NS)
    if not source_paragraphs:
        text = html.escape(_text(cell)).replace("\n", "<br>").replace("\t", "&#9;")
        return text
    rendered = []
    for index, paragraph in enumerate(paragraphs):
        source_paragraph = source_paragraphs[min(index, len(source_paragraphs) - 1)]
        rendered.append(_paragraph_html(source_paragraph, _text(paragraph), source_paragraph))
    return "".join(rendered)


def _tables_with_locators(service, snapshot):
    parts = _selected_table_documents(service, snapshot)
    document = ET.fromstring(parts["word/document.xml"])
    indexes = snapshot.get("reference_page_tables") or [snapshot["reference_table_index"]]
    for page_no, table in enumerate(document.findall("w:body/w:tbl", NS)):
        index = indexes[page_no]
        key_index = f"{index}p{page_no + 1}" if snapshot["template_id"] == "inspection" and page_no >= 5 else index
        yield page_no, index, key_index, table


def _row_cells(table):
    """Resolve physical Word cells onto the common grid, including vMerge."""
    rows = table.findall("w:tr", NS)
    for ri, row in enumerate(rows):
        column = 0
        for ci, cell in enumerate(row.findall("w:tc", NS)):
            span = int(_field(cell, "w:tcPr/w:gridSpan", default="1"))
            merge = cell.find("w:tcPr/w:vMerge", NS)
            continuation = merge is not None and _attr(merge, "val") != "restart"
            rowspan = 1
            if merge is not None and not continuation:
                for following in rows[ri + 1:]:
                    position, matched = 0, False
                    for next_cell in following.findall("w:tc", NS):
                        next_span = int(_field(next_cell, "w:tcPr/w:gridSpan", default="1"))
                        if position == column:
                            next_merge = next_cell.find("w:tcPr/w:vMerge", NS)
                            matched = next_merge is not None and _attr(next_merge, "val") != "restart"
                            break
                        position += next_span
                    if not matched:
                        break
                    rowspan += 1
            yield ri, ci, column, span, rowspan, continuation, row, cell
            column += span


def _html_table(service, snapshot):
    manifest = _load_manifest(service)
    template = _template_for(manifest, snapshot["template_id"])
    section = ET.fromstring(template["section"])
    width = float(_field(section, "w:pgSz", "w", "11906")) / 15
    margins = [float(_field(section, "w:pgMar", side, "1134")) / 15 for side in ("top", "right", "bottom", "left")]
    pages = []
    for page_no, index, key_index, table in _tables_with_locators(service, snapshot):
        grid = [int(_attr(col, "w")) for col in table.findall("w:tblGrid/w:gridCol", NS)]
        rendered = [[] for _ in table.findall("w:tr", NS)]
        for ri, ci, column, span, rowspan, continuation, row, cell in _row_cells(table):
            if continuation:
                continue
            source = _source_cell(manifest, index, ri, ci, snapshot)
            family, size, bold, align = _font_properties(source)
            key = _cell_key(key_index, ri, ci)
            editable = f' data-edit-key="{html.escape(key)}"' if snapshot["template_id"] != "core_map" else ""
            text = _cell_html(source, cell)
            align = {"both": "justify", "distribute": "justify"}.get(align, align)
            font_stack = html.escape(_css_font({"rFonts": {"eastAsia": family}}), quote=True)
            style = f'font-family:{font_stack};font-size:{size}pt;font-weight:{"bold" if bold else "normal"};text-align:{align};white-space:pre-wrap'
            rendered[ri].append(f'<td colspan="{span}" rowspan="{rowspan}"{editable} style="{style}">{text}</td>')
        trs = []
        for ri, row in enumerate(table.findall("w:tr", NS)):
            height = float(_field(row, "w:trPr/w:trHeight", default="0")) / 20
            trs.append(f'<tr style="height:{height}pt">{"".join(rendered[ri])}</tr>')
        cols = "".join(f'<col style="width:{value / sum(grid) * 100:.6f}%">' for value in grid)
        style = f'width:{width}px;min-width:{width}px;padding:{" ".join(f"{v}px" for v in margins)}'
        caption = '<caption>表5 涡流检验结果比对表</caption>' if snapshot["template_id"] == "comparison" else ''
        pages.append(f'<article class="report-sheet source-form" style="{style}"><table>{caption}<colgroup>{cols}</colgroup><tbody>{"".join(trs)}</tbody></table></article>')
    return "".join(pages)


def preview(service, snapshot: dict):
    if not snapshot.get("template_id"):
        raise ValueError("缺少source-form template_id")
    return _html_table(service, snapshot)


def workbook(service, snapshot: dict, filename: str):
    if not snapshot.get("template_id"):
        raise ValueError("缺少source-form template_id")
    book = service.Workbook()
    manifest = _load_manifest(service)
    template = _template_for(manifest, snapshot["template_id"])
    section = ET.fromstring(template["section"])
    for page_no, index, key_index, table in _tables_with_locators(service, snapshot):
        sheet = book.active if page_no == 0 else book.create_sheet()
        sheet.title = f"报告表{page_no + 1}"
        if snapshot["template_id"] == "comparison":
            sheet.print_title_rows = "1:2"
            sheet.oddHeader.center.text = "表5 涡流检验结果比对表"
        sheet.sheet_view.showGridLines = False
        grid = [int(_attr(col, "w")) for col in table.findall("w:tblGrid/w:gridCol", NS)]
        for ci, value in enumerate(grid, 1):
            sheet.column_dimensions[service.get_column_letter(ci)].width = max(.3, value / 20 / 5.3)
        for ri, ci, column, span, rowspan, continuation, row, cell in _row_cells(table):
            sheet.row_dimensions[ri + 1].height = max(1, float(_field(row, "w:trPr/w:trHeight", default="340")) / 20)
            if continuation:
                continue
            text = _text(cell)
            target = sheet.cell(ri + 1, column + 1, text)
            # Explicit string type blocks Excel formulas, including user edits.
            target.data_type = "s"
            family, size, bold, align = _font_properties(_source_cell(manifest, index, ri, ci, snapshot))
            target.font = service.Font(name=family, size=size, bold=bold)
            target.alignment = service.Alignment(horizontal=align if align in {"left", "right", "center", "justify"} else "center", vertical="center", wrap_text=True)
            if snapshot["template_id"] == "comparison" and ri == len(table.findall("w:tr", NS)) - 1:
                sheet.row_dimensions[ri + 1].height = max(
                    sheet.row_dimensions[ri + 1].height,
                    wrapped_note_height(text, sum(grid) / 20, size))
            target.border = service.Border(**{edge: service.Side(style="thin", color="000000") for edge in ("left", "right", "top", "bottom")})
            if span > 1 or rowspan > 1:
                sheet.merge_cells(start_row=ri + 1, end_row=ri + rowspan, start_column=column + 1, end_column=column + span)
        sheet.page_setup.orientation = "landscape" if _field(section, "w:pgSz", "orient") == "landscape" else "portrait"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        for side in ("top", "right", "bottom", "left"):
            setattr(sheet.page_margins, side, float(_field(section, "w:pgMar", side, "1134")) / 1440)
        sheet.print_area = sheet.dimensions
    return service.workbook_result(filename, book)
