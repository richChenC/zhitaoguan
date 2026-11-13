"""Ensure every native test imports application paths after isolation is active."""
import os
from pathlib import Path
import tempfile
import atexit
import logging
import sys

artifact_root = Path(__file__).resolve().parents[3] / "05_测试与验证" / "03_自动化临时产物"
artifact_root.mkdir(parents=True, exist_ok=True)
test_data = tempfile.TemporaryDirectory(prefix="native-unittest-", dir=artifact_root)
atexit.register(logging.shutdown)
os.environ["THIMBLE_QT_TEST_DATA_ROOT"] = test_data.name
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
loaded_constants = sys.modules.get("qt_shell.constants")
if loaded_constants and loaded_constants.USER_DATA != Path(test_data.name).resolve():
    raise RuntimeError("Import native_test_env before application modules to isolate all test preferences.")
