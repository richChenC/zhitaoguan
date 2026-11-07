"""Inventory every source table and retain source OOXML without rebuilding styles.

The input must be a read-only DOCX conversion of the specified legacy Word
reference. This script never modifies the input or the original DOC file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ROLES = {
    0: ("contract_cover", "合同与文控封面", "manual"),
    1: ("approval_cover", "报告封面与审批", "manual"),
    2: ("revisions", "版次修改记录", "manual"),
    3: ("equipment", "检验设备清单", "manual"),
    4: ("qualifications", "检验人员资质", "manual"),
    5: ("dose", "人员剂量统计", "manual"),
    6: ("data_groups", "数据标识与数据组清单", "database"),
    7: ("comparison", "历次大修检验结果对比表", "database"),
    8: ("core_cover", "附录Ⅰ封面", "manual"),
    9: ("core_map", "堆芯位置示意图", "database-and-graphic"),
    10: ("inspection_cover", "附录Ⅱ封面", "manual"),
    11: ("inspection", "涡流检验报告单", "database"),
    12: ("inspection_continuation_2", "涡流检验报告单续页2", "database"),
    13: ("inspection_continuation_3", "涡流检验报告单续页3", "database"),
    14: ("inspection_continuation_4", "涡流检验报告单续页4", "database"),
    15: ("inspection_continuation_5", "涡流检验报告单续页5", "database"),
    16: ("signals_cover", "超标显示信号图附录封面", "manual"),
    17: ("quality_plan_cover", "质量计划附件封面", "manual"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def xml(node) -> str | None:
    return ET.tostring(node, encoding="unicode") if node is not None else None


def attrs(node) -> dict:
    return {key.split("}")[-1]: value for key, value in node.attrib.items()} if node is not None else {}


def plain(node) -> str:
    result = []
    for child in node.iter():
        if child.tag == f"{{{W}}}t":
            result.append(child.text or "")
        elif child.tag in (f"{{{W}}}br", f"{{{W}}}cr"):
            result.append("\n")
        elif child.tag == f"{{{W}}}tab":
            result.append("\t")
    return "".join(result)


def inherited_properties(styles: dict, style_id: str, tag: str, visited=None) -> dict:
    visited = set() if visited is None else visited
    if not style_id or style_id in visited or style_id not in styles:
        return {}
    visited.add(style_id)
    style = styles[style_id]
    base = style.find("w:basedOn", NS)
    result = inherited_properties(styles, base.get(f"{{{W}}}val") if base is not None else "", tag, visited)
    properties = style.find(f"w:{tag}", NS)
    if properties is not None:
        for child in properties:
            result[child.tag.split("}")[-1]] = attrs(child)
    return result


def inspect(source: Path, destination: Path, legacy_sha256: str = "", legacy_path: str = "", page_count: int | None = None) -> dict:
    source_bytes = source.read_bytes()
    with ZipFile(source) as archive:
        raw = archive.read("word/document.xml")
        document = ET.fromstring(raw)
        body = document.find("w:body", NS)
        styles_root = ET.fromstring(archive.read("word/styles.xml"))
        styles = {style.get(f"{{{W}}}styleId"): style for style in styles_root.findall("w:style", NS)}
        default = next((key for key, node in styles.items() if node.get(f"{{{W}}}type") == "paragraph" and node.get(f"{{{W}}}default") == "1"), "Normal")
        default_rpr = styles_root.find("w:docDefaults/w:rPrDefault/w:rPr", NS)
        defaults = {node.tag.split("}")[-1]: attrs(node) for node in default_rpr} if default_rpr is not None else {}
        children = list(body)
        sections, tables = [], []
        for section in document.findall(".//w:sectPr", NS):
            sections.append({
                "index": len(sections), "xml": xml(section),
                "page_size_twips": attrs(section.find("w:pgSz", NS)),
                "margins_twips": attrs(section.find("w:pgMar", NS)),
                "columns": attrs(section.find("w:cols", NS)),
            })
        fonts = Counter()
        for table in body.findall("w:tbl", NS):
            index = len(tables)
            key, label, mode = ROLES.get(index, (f"table_{index}", f"表格{index}", "manual"))
            following = children[children.index(table) + 1:]
            section = next((part if part.tag == f"{{{W}}}sectPr" else part.find("w:pPr/w:sectPr", NS) for part in following if part.tag == f"{{{W}}}sectPr" or part.find("w:pPr/w:sectPr", NS) is not None), None)
            previous_text = []
            for element in children[max(0, children.index(table) - 4):children.index(table)]:
                if element.tag == f"{{{W}}}p" and plain(element).strip():
                    previous_text.append(plain(element))
            rows = []
            for ri, row in enumerate(table.findall("w:tr", NS)):
                cells = []
                for ci, cell in enumerate(row.findall("w:tc", NS)):
                    paragraphs = []
                    for paragraph in cell.findall("w:p", NS):
                        pstyle = paragraph.find("w:pPr/w:pStyle", NS)
                        style_id = pstyle.get(f"{{{W}}}val") if pstyle is not None else default
                        ppr = inherited_properties(styles, style_id, "pPr")
                        direct_ppr = paragraph.find("w:pPr", NS)
                        if direct_ppr is not None:
                            ppr.update({node.tag.split("}")[-1]: attrs(node) for node in direct_ppr})
                        runs = []
                        for run in paragraph.findall("w:r", NS):
                            rpr = dict(defaults)
                            rpr.update(inherited_properties(styles, style_id, "rPr"))
                            rstyle = run.find("w:rPr/w:rStyle", NS)
                            if rstyle is not None:
                                rpr.update(inherited_properties(styles, rstyle.get(f"{{{W}}}val"), "rPr"))
                            direct_rpr = run.find("w:rPr", NS)
                            if direct_rpr is not None:
                                rpr.update({node.tag.split("}")[-1]: attrs(node) for node in direct_rpr})
                            font = rpr.get("rFonts", {})
                            size = rpr.get("sz", {}).get("val")
                            font_key = (font.get("eastAsia", ""), font.get("ascii", ""), size or "")
                            fonts[font_key] += 1
                            runs.append({"text": plain(run), "effective_properties": rpr, "source_rPr": xml(direct_rpr)})
                        paragraphs.append({"text": plain(paragraph), "style": style_id, "effective_properties": ppr, "source_pPr": xml(direct_ppr), "runs": runs})
                    cells.append({"column_index": ci, "text": "\n".join(p["text"] for p in paragraphs), "properties": xml(cell.find("w:tcPr", NS)), "paragraphs": paragraphs})
                rows.append({"row_index": ri, "properties": xml(row.find("w:trPr", NS)), "cells": cells})
            tables.append({
                "source_index": index, "key": key, "title": label, "data_mode": mode,
                "source_locator": f"word/document.xml:/w:document/w:body/w:tbl[{index + 1}]",
                "preceding_paragraphs": previous_text, "row_count": len(rows),
                "grid_widths_twips": [int(node.get(f"{{{W}}}w")) for node in table.findall("w:tblGrid/w:gridCol", NS)],
                "properties": xml(table.find("w:tblPr", NS)), "section": xml(section),
                "raw_table_xml_sha256": digest(ET.tostring(table)),
                "drawing_count": len(table.findall(".//w:drawing", NS)),
                "legacy_picture_count": len(table.findall(".//w:pict", NS)), "rows": rows,
            })
        manifest = {
            "schema_version": 1, "authority": "user-supplied-ningde-unit1-outage8",
            "legacy_source": {"path": legacy_path, "sha256": legacy_sha256},
            "conversion": {"engine": "Microsoft Word SaveAs2 wdFormatDocumentDefault(16)", "source_docx_name": source.name, "sha256": digest(source_bytes), "page_count": page_count},
            "units": {"geometry": "twips", "font_size": "half-points"},
            "sections": sections, "table_count": len(tables), "tables": tables,
            "font_usage": [{"eastAsia": item[0], "ascii": item[1], "size_half_points": item[2], "runs": count} for item, count in fonts.most_common()],
            "package_parts": [{"path": name, "size": len(archive.read(name)), "sha256": digest(archive.read(name)), "policy": "editable-table-content" if name == "word/document.xml" else "preserve"} for name in archive.namelist() if not name.endswith("/")],
            "fidelity_policy": {
                "reference_immutable": True, "build_from_blank": False,
                "clone_original_table_styles": True,
                "original_business_values_are_not_defaults": True,
                "missing_database_fields_require_explicit_user_input": True,
                "table_display_missing_value": "/",
                "do_not_replace_hyphens_inside_identifiers_dates_or_signed_numbers": True,
                "render_qa_required": True,
            },
        }
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination / "reference.docx")
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "source-document.xml").write_bytes(raw)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--legacy-sha256", default="")
    parser.add_argument("--legacy-path", default="")
    parser.add_argument("--page-count", type=int)
    args = parser.parse_args()
    result = inspect(args.source.resolve(), args.destination.resolve(), args.legacy_sha256, args.legacy_path, args.page_count)
    print(json.dumps({"table_count": result["table_count"], "sections": len(result["sections"]), "destination": str(args.destination), "tables": [{"index": table["source_index"], "key": table["key"], "title": table["title"], "rows": table["row_count"]} for table in result["tables"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
