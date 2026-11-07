import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from openpyxl import load_workbook

from src.backend import reference_report, server


class SourceReportTests(unittest.TestCase):
    def test_preview_uses_the_unified_song_font_for_legacy_source_fonts(self):
        properties={"rFonts":{"ascii":"仿宋_GB2312","eastAsia":"仿宋_GB2312"}}
        self.assertEqual(reference_report._css_font(properties), '"宋体", "SimSun"')
        self.assertEqual(properties["rFonts"]["eastAsia"], "仿宋_GB2312")

    def setUp(self):
        self.root = Path(server.ROOT)
        # 导出走每测试临时目录，避免写真实用户输出目录（Roaming profile）。
        # 真实目录上的瞬时拒访会让 tempfile 重试，拖垮整套测试。
        sandbox = Path(tempfile.mkdtemp(prefix="thimble-test-reference-"))
        self.addCleanup(shutil.rmtree, sandbox, True)
        excel_dir = sandbox / "excel"
        report_dir = sandbox / "reports"
        excel_dir.mkdir(parents=True)
        report_dir.mkdir(parents=True)
        self.addCleanup(setattr, server, "REPORT_DIR", server.REPORT_DIR)
        self.addCleanup(setattr, server, "EXCEL_DIR", server.EXCEL_DIR)
        server.EXCEL_DIR = excel_dir
        server.REPORT_DIR = report_dir

    def snapshot(self, count=121):
        values = [
            [index, 1, "L11", "WAR", 1.25, 25, "P1+42", "M1", "TEST"]
            for index in range(1, count + 1)
        ]
        return {
            "kind": "inspection", "site": "N", "unit": 1, "outage": "N108",
            "old": "", "title": "指套管检验结果", "rows": len(values),
            "values": values, "warnings": [], "sources": [],
            "source_headers": [], "summary": {},
            "metadata": {"电厂名称": "测试电厂", "检查类型": "定期检验"},
        }

    def comparison_snapshot(self):
        return {
            "kind": "comparison", "site": "N", "unit": 1, "outage": "N108",
            "old": "N107", "title": "历次大修检验结果对比",
            "rows": 1, "values": [[1, 1, "L11", 1.78, 28, "P1+127", 2.09, 29, "P1+127", "R"]],
            "warnings": [], "sources": [], "source_headers": [], "summary": {},
            "metadata": {},
        }

    def test_catalog_exposes_only_result_and_outage_comparison_reports(self):
        result = reference_report.catalog(server)
        self.assertEqual([item["id"] for item in result["templates"]], ["comparison", "inspection"])
        self.assertTrue(all({"docx", "xlsx"} <= set(row["formats"]) for row in result["templates"]))

    def test_other_source_form_templates_are_not_exportable(self):
        with self.assertRaisesRegex(ValueError, "仅支持检验报告单"):
            reference_report.prepare(server, self.snapshot(1), {"template_id": "core_map"})

    def test_multiline_edits_preserve_paragraphs_and_verbatim_excel_text(self):
        value = "第一行\n  保留原文空格，-2 与 4-6 不变  \n\n末行"
        with patch.object(reference_report, "_selected_rows", return_value=[]):
            initial = reference_report.prepare(server, self.snapshot(1), {"template_id": "inspection"})
            key = next(cell["key"] for cell in initial["editable_cells"] if cell["value"].startswith("备注："))
            snapshot = reference_report.prepare(server, self.snapshot(1), {
                "template_id": "inspection", "draft_edits": [{"key": key, "value": value}],
            })
        parts = reference_report._selected_table_documents(server, snapshot)
        document = ET.fromstring(parts["word/document.xml"])
        self.assertTrue(any(reference_report._text(cell) == value for cell in document.findall(".//w:tc", reference_report.NS)))
        result = reference_report.workbook(server, snapshot, "test-reference-multiline.xlsx")
        output = Path(result["file_path"])
        try:
            book = load_workbook(output)
            try:
                self.assertTrue(any(cell.value == value for sheet in book for row in sheet for cell in row))
            finally:
                book.close()
        finally:
            output.unlink(missing_ok=True)

    def test_selected_metadata_and_current_channel_merges(self):
        source = self.snapshot(4)
        source["metadata"].update({
            "设备/部件编号": "COMP-1", "报告单编码": "REPORT-2",
            "涡流仪出厂编号": "SERIAL-3", "标定管编号": "CAL-4",
        })
        source["values"][2][1:3] = [2, "G14"]
        source["values"][3][1:3] = [3, "N7"]
        with patch.object(reference_report, "_selected_rows", return_value=[]):
            snapshot = reference_report.prepare(server, source, {"template_id": "inspection"})
        parts = reference_report._selected_table_documents(server, snapshot)
        document = ET.fromstring(parts["word/document.xml"])
        table = document.find("w:body/w:tbl", reference_report.NS)
        rows = table.findall("w:tr", reference_report.NS)
        roles = [reference_report._text(cell) for cell in rows[31].findall("w:tc", reference_report.NS)]
        self.assertEqual(roles[1:], ["分析人员/级别", "审核/级别", "批准", "业主"])
        note = rows[30].find("w:tc", reference_report.NS)
        note_paragraphs = note.findall("w:p", reference_report.NS)
        self.assertEqual(len(note_paragraphs), 2)
        self.assertEqual(reference_report._attr(note_paragraphs[0].find("w:pPr/w:jc", reference_report.NS), "val"), None)
        self.assertEqual(reference_report._attr(note_paragraphs[1].find("w:pPr/w:ind", reference_report.NS), "firstLine"), "420")
        note_font = note_paragraphs[1].find("w:r/w:rPr/w:rFonts", reference_report.NS)
        self.assertEqual(reference_report._attr(note_font, "eastAsia"), "宋体")
        self.assertEqual(reference_report._attr(note_paragraphs[1].find("w:r/w:rPr/w:sz", reference_report.NS), "val"), "21")
        self.assertEqual(reference_report._text(rows[0].findall("w:tc", reference_report.NS)[0]), "COMP-1")
        self.assertEqual(reference_report._text(rows[0].findall("w:tc", reference_report.NS)[2]), "REPORT-2")
        for column, expected in ((3, "SERIAL-3"), (5, "CAL-4")):
            self.assertEqual(reference_report._text(rows[4].findall("w:tc", reference_report.NS)[column]), expected)
        for column in (1, 2):
            first = rows[10].findall("w:tc", reference_report.NS)[column]
            second = rows[11].findall("w:tc", reference_report.NS)[column]
            self.assertEqual(reference_report._attr(first.find("w:tcPr/w:vMerge", reference_report.NS), "val"), "restart")
            self.assertEqual(reference_report._attr(second.find("w:tcPr/w:vMerge", reference_report.NS), "val"), "continue")
            for index in (12, 13, 14):
                cell = rows[index].findall("w:tc", reference_report.NS)[column]
                self.assertIsNone(cell.find("w:tcPr/w:vMerge", reference_report.NS))

        preview = reference_report.preview(server, snapshot)
        self.assertIn("text-align:justify", preview)
        self.assertIn("text-indent:21pt", preview)
        self.assertIn('font-family:"宋体", "SimSun"', preview)
        signature_label = rows[32].findall("w:tc", reference_report.NS)[0]
        signature_run = signature_label.find("w:p/w:r", reference_report.NS)
        self.assertEqual(reference_report._text(signature_label), "签名")
        self.assertEqual(
            reference_report._attr(signature_run.find("w:rPr/w:rFonts", reference_report.NS), "eastAsia"),
            "宋体",
        )

    def test_comparison_footer_keeps_source_indent_and_uses_unified_font(self):
        with patch.object(reference_report, "_selected_rows", return_value=[]):
            snapshot = reference_report.prepare(
                server, self.comparison_snapshot(), {"template_id": "comparison"}
            )
        preview = reference_report.preview(server, snapshot)
        self.assertIn("text-align:left", preview)
        self.assertIn("text-indent:21pt", preview)
        self.assertIn('font-family:"宋体", "SimSun"', preview)

        result = reference_report.write(server, snapshot, "test-reference-comparison.docx")
        output = Path(result["file_path"])
        source = Path(server.ROOT) / "assets" / "report-templates" / "宁德综合报告" / "reference.docx"
        try:
            with ZipFile(source) as original, ZipFile(output) as generated:
                source_document = ET.fromstring(original.read("word/document.xml"))
                generated_document = ET.fromstring(generated.read("word/document.xml"))
                source_table = source_document.find("w:body", reference_report.NS).findall(
                    "w:tbl", reference_report.NS
                )[7]
                generated_table = generated_document.find("w:body/w:tbl", reference_report.NS)
                source_footer = source_table.findall("w:tr", reference_report.NS)[-1].find("w:tc", reference_report.NS)
                generated_footer = generated_table.findall("w:tr", reference_report.NS)[-1].find("w:tc", reference_report.NS)
            source_paragraphs = source_footer.findall("w:p", reference_report.NS)
            generated_paragraphs = generated_footer.findall("w:p", reference_report.NS)
            self.assertEqual(len(generated_paragraphs), 2)
            source_indent = source_paragraphs[1].find("w:pPr/w:ind", reference_report.NS)
            generated_indent = generated_paragraphs[1].find("w:pPr/w:ind", reference_report.NS)
            self.assertEqual(generated_indent.attrib, source_indent.attrib)
            generated_runs = generated_paragraphs[1].findall("w:r", reference_report.NS)
            self.assertTrue(generated_runs)
            for run in generated_runs:
                generated_font = run.find("w:rPr/w:rFonts", reference_report.NS)
                self.assertEqual(reference_report._attr(generated_font, "eastAsia"), "宋体")
        finally:
            output.unlink(missing_ok=True)

    def test_inspection_pages_keep_template_geometry_and_export_all_pages(self):
        with patch.object(reference_report, "_selected_rows", return_value=[]):
            snapshot = reference_report.prepare(
                server, self.snapshot(), {"template_id": "inspection"}
            )
        self.assertEqual(len(snapshot["reference_page_rows"]), 7)
        self.assertEqual(snapshot["reference_page_rows"][0][1][1], "测试电厂")
        self.assertEqual(snapshot["reference_page_rows"][0][1][3], "1")
        self.assertEqual(snapshot["reference_page_rows"][0][1][5], "定期检验")
        self.assertGreater(len(snapshot["editable_cells"]), 7 * 34 * 4)
        page_cells = [cell for cell in snapshot["editable_cells"] if cell["key"].startswith("t15p7:")]
        self.assertTrue(page_cells)

        preview = reference_report.preview(server, snapshot)
        self.assertEqual(preview.count('class="report-sheet source-form"'), 7)
        self.assertIn('data-edit-key="t15p7:r10:c0"', preview)
        self.assertIn("<colgroup>", preview)

        result = reference_report.write(server, snapshot, "test-reference-report.docx")
        output = Path(result["file_path"])
        try:
            with ZipFile(output) as archive:
                names = set(archive.namelist())
                document = ET.fromstring(archive.read("word/document.xml"))
                tables = document.findall("w:body/w:tbl", reference_report.NS)
                text = "".join(document.itertext())
                run_fonts = [
                    run.find("w:rPr/w:rFonts", reference_report.NS)
                    for run in document.findall(".//w:r", reference_report.NS)
                ]
            self.assertEqual(len(tables), 7)
            self.assertTrue(run_fonts)
            for fonts in run_fonts:
                self.assertIsNotNone(fonts)
                for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                    self.assertEqual(reference_report._attr(fonts, attribute), "宋体")
            self.assertEqual(names & {
                "word/header1.xml", "word/footer1.xml", "word/media/image1.jpeg",
            }, set())
            self.assertNotIn("N108ET632", text)
            self.assertIn("定期检验", text)
            self.assertNotIn("检查类型N108", text)
        finally:
            output.unlink(missing_ok=True)

        result = reference_report.workbook(server, snapshot, "test-reference-report.xlsx")
        output = Path(result["file_path"])
        try:
            book = load_workbook(output)
            try:
                self.assertEqual(len(book.worksheets), 7)
                self.assertTrue(book.worksheets[0].merged_cells.ranges)
                self.assertEqual(str(book.worksheets[0].page_setup.paperSize), book.worksheets[0].PAPERSIZE_A4)
                self.assertEqual(book.worksheets[-1].max_row, 34)
                self.assertTrue(all(
                    cell.font.name == "宋体"
                    for sheet in book.worksheets
                    for row in sheet
                    for cell in row
                    if cell.value is not None
                ))
            finally:
                book.close()
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
