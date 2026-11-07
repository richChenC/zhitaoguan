"""Shared paths for offline data extraction tools."""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = APP_DIR
REFERENCE_DIR = os.path.join(APP_DIR, "项目资料", "02_业务参考资料", "孔姐发的")
TEST_DATA_DIR = os.path.join(APP_DIR, "项目资料", "03_原始验证数据", "测试数据")
DATA_DIR = os.path.join(APP_DIR, "src", "desktop-ui", "modules", "analytics", "data")
LEDGER_DIR = os.path.join(DATA_DIR, "thimble-ledger")
