import re
import unittest

from src.backend.artifact_naming import filename


class ArtifactNamingTests(unittest.TestCase):
    def test_names_are_scoped_safe_and_unique_for_bursts(self):
        names = [filename("历次大修对比报告", "机组1_N107/N108", "docx") for _ in range(200)]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(re.fullmatch(
            r"TH_历次大修对比报告_机组1_N107-N108_\d{8}-\d{6}_[0-9a-f]{8}\.docx",
            name,
        ) for name in names))
        self.assertTrue(all(not re.search(r'[<>:"/\\|?*]', name) for name in names))

    def test_rejects_invalid_extensions(self):
        for extension in ("", "../xlsx", "xlsm?"):
            with self.subTest(extension=extension), self.assertRaises(ValueError):
                filename("测试", "范围", extension)

    def test_collapses_redundant_all_scope_labels(self):
        name = filename("图表", "全部基地_全部机组_全部大修_最新轮次", "png")
        self.assertIn("_全范围_最新轮次_", name)
        self.assertNotIn("全部基地", name)
        self.assertNotIn("全部机组", name)
        self.assertNotIn("全部大修", name)


if __name__ == "__main__":
    unittest.main()
