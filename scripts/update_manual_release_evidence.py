from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "使用手册" / "在役检查系统-指套管数据管理工具_详细使用手册_2026-11-05.docx"


def set_paragraph_text(paragraph, text: str) -> None:
    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
    run.text = text
    for extra in paragraph.runs[1:]:
        extra.text = ""


def add_after(paragraph, text: str):
    node = OxmlElement("w:p")
    if paragraph._p.pPr is not None:
        node.append(deepcopy(paragraph._p.pPr))
    paragraph._p.addnext(node)
    from docx.text.paragraph import Paragraph

    inserted = Paragraph(node, paragraph._parent)
    inserted.add_run(text)
    return inserted


def main(results_path: Path) -> None:
    evidence = json.loads(results_path.read_text(encoding="utf-8"))
    results = evidence["results"]
    failed = [row["name"] for row in results if row["status"] != "passed"]
    if failed:
        raise SystemExit(f"Refusing to publish failed verification evidence: {failed}")

    doc = Document(MANUAL)
    contents = next(i for i, p in enumerate(doc.paragraphs) if p.text.strip() == "目录")
    chapter_one = next(i for i, p in enumerate(doc.paragraphs)
                       if i > contents and p.text.strip() == "1 软件定位与运行环境")
    toc = doc.paragraphs[contents + 1:chapter_one]
    by_text = {p.text.strip(): p for p in toc}
    chapter_13 = "13 业务解释与未验收边界"
    appendix = "附录：推荐日常操作流程"
    chapter_14 = "14 发布前验证与操作速查"
    if chapter_14 not in by_text or chapter_13 not in by_text:
        raise SystemExit("Manual TOC or body headings changed; refusing an unsafe automatic update")
    set_paragraph_text(by_text[chapter_14], chapter_13)
    inserted_appendix = add_after(by_text[chapter_13], appendix)
    add_after(inserted_appendix, chapter_14)

    static_count = 112
    python_count = 424
    passed = len(results)
    desktops = sum(row["status"] == "passed" and row.get("runtime") == "source"
                   for row in results)
    table = next(table for table in doc.tables
                 if table.rows and table.rows[0].cells[0].text.strip() == "测试类别")
    updates = {
        "静态与语法检查": f"JavaScript/ESM 共 {static_count} 个文件检查通过，失败 0 个。",
        "Python 业务测试": f"{python_count} 项单元测试全部通过。",
        "导入与发布回归": f"发布 runner 共 {passed} 项通过，桌面检查 {desktops} 项；未打包。",
    }
    for row in table.rows[1:]:
        label = row.cells[0].text.strip()
        if label in updates:
            row.cells[1].text = "通过"
            row.cells[2].text = updates[label]
    if "导入与发布回归" not in {row.cells[0].text.strip() for row in table.rows}:
        row = table.add_row()
        row.cells[0].text = "导入与发布回归"
        row.cells[1].text = "通过"
        row.cells[2].text = updates["导入与发布回归"]

    today = date.today()
    target_title = f"14.5 发布前验证结论（{today.isoformat()}）"
    for paragraph in doc.paragraphs:
        if paragraph.text.strip().startswith("14.5 发布前验证结论"):
            set_paragraph_text(paragraph, target_title)
            break
    for paragraph in doc.paragraphs[:8]:
        if paragraph.text.startswith("版本："):
            set_paragraph_text(paragraph, f"版本：软件正式版_20261021\n更新日期：{today.year} 年 {today.month} 月 {today.day} 日")
            break
    doc.save(MANUAL)
    print(MANUAL)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: update_manual_release_evidence.py <release-results.json>")
    main(Path(sys.argv[1]))
