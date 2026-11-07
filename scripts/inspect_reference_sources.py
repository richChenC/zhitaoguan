"""Read-only inventory of user references for importer and template tests."""
import json
import sys
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.backend import server

W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
base = ROOT.parent / "孔姐发的"
paths = [
    *sorted((ROOT / "tmp/reference-docx-20261020").glob("*.docx")),
    base / "指套管信息/防城港核电厂2号机组指套管磨损速率过大原因分析报告-2026.8.5-3.docx",
    base / "指套管数据测试 202007/指套管割管移位统计（含阳江、防城港、红沿河）.xlsx",
    base / "指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx",
    base / "指套管数据测试 202007/防城港/防城港指套管割管距离统计.docx",
    base / "指套管数据测试 202007/红沿河/红沿河指套管割管距离统计.docx",
    base / "指套管数据测试 202007/宁德/宁德4台机组指套管割管移位信息汇总20200804.xls",
]
result = []
for path in paths:
    item = {"path": str(path)}
    try:
        if path.suffix.lower() == ".docx":
            with ZipFile(path) as z:
                doc = ET.fromstring(z.read("word/document.xml"))
                text = lambda e: "".join(t.text or "" for t in e.findall(".//w:t", W))
                item["paragraphs"] = [text(p) for p in doc.findall("./w:body/w:p", W) if text(p)]
                item["sections"] = [ET.tostring(s, encoding="unicode") for s in doc.findall(".//w:sectPr", W)]
                item["tables"] = [
                    {"index": i, "rows": [[text(c) for c in r.findall("w:tc", W)] for r in t.findall("w:tr", W)],
                     "properties": ET.tostring(t.find("w:tblPr", W), encoding="unicode"),
                     "grid": ET.tostring(t.find("w:tblGrid", W), encoding="unicode")}
                    for i, t in enumerate(doc.findall("./w:body/w:tbl", W))
                ]
        else:
            book = server.open_excel_workbook(path)
            item["sheets"] = [{"name": s.title, "rows": [list(r) for r in s.iter_rows(values_only=True)]} for s in book.worksheets]
            book.close()
    except Exception as error:
        item["error"] = str(error)
    result.append(item)
print(json.dumps(result, ensure_ascii=False, default=str))
