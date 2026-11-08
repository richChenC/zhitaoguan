"""Ensure every native test imports application paths after isolation is active."""
import os
from pathlib import Path
import tempfile

artifact_root = Path(__file__).resolve().parents[3] / "05_测试与验证" / "03_自动化临时产物"
artifact_root.mkdir(parents=True, exist_ok=True)
test_data = tempfile.TemporaryDirectory(prefix="native-unittest-", dir=artifact_root)
os.environ["THIMBLE_QT_TEST_DATA_ROOT"] = test_data.name
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
