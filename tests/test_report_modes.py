import unittest

from src.backend import analysis_reporting


class ReportModeTests(unittest.TestCase):
    def test_report_center_rejects_removed_report_types_before_database_access(self):
        for kind in ("data", "validation", "unknown"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "仅支持检验报告单和检验结果比对表"):
                    analysis_reporting.report_snapshot(None, {"kind": kind})


if __name__ == "__main__":
    unittest.main()
