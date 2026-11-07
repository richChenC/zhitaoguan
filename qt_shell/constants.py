"""Qt 壳全局常量与运行时状态。

对应 Electron 侧 ``src/desktop/main.cjs`` 的顶部常量段（34-61 行）。
正常运行的写入路径都落在 08_Qt移植版/ 内；显式隔离测试可重定向到测试数据目录。
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """PyInstaller 冻结运行时（安装版/便携 exe）。"""
    return getattr(sys, "frozen", False)


# 冻结运行时以 exe 所在目录为应用根（资源目录与 exe 同级布放）；
# 开发模式保持源码目录布局。
QT_ROOT = (
    Path(sys.executable).resolve().parent
    if _is_frozen()
    else Path(__file__).resolve().parents[1]
)


def _default_user_data() -> Path:
    """数据目录解析优先级：配置文件 > 系统默认（AppData）。

    仅冻结运行时允许重定向；开发模式固定使用 QT_ROOT/user-data，
    避免误读写正式开发库。配置文件 data-location.json 由安装程序
    根据用户选择写入，格式：{"user_data_dir": "D:/..."}。
    """
    if not _is_frozen():
        return QT_ROOT / "user-data"
    config_path = QT_ROOT / "data-location.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        custom = payload.get("user_data_dir")
        if isinstance(custom, str) and custom.strip():
            return Path(custom).expanduser().resolve()
    except (OSError, ValueError):
        pass
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "ThimbleInspection" / "user-data"


_TEST_DATA_ROOT = os.environ.get("THIMBLE_QT_TEST_DATA_ROOT")
if _TEST_DATA_ROOT:
    if os.environ.get("THIMBLE_ALLOW_MULTI_INSTANCE") != "1":
        raise RuntimeError("隔离测试数据目录仅可用于多实例测试进程")
    USER_DATA = Path(_TEST_DATA_ROOT).expanduser().resolve()
else:
    USER_DATA = _default_user_data()
DATA_DIR = USER_DATA / "data"
OUTPUT_DIR = USER_DATA / "output" / "excel"
REPORT_DIR = USER_DATA / "output" / "reports"
LOG_DIR = USER_DATA / "logs"
WEBENGINE_DIR = USER_DATA / "qtwebengine"
SERVICE_LOG_PATH = LOG_DIR / "desktop-service.log"
SERVER_LOG_PATH = LOG_DIR / "server.log"
BACKEND_EXE = QT_ROOT / "build" / "backend" / "thimble-backend.exe"
BACKEND_SOURCE = QT_ROOT / "src" / "backend" / "server.py"
VENDOR_DIR = QT_ROOT / ".vendor"
UI_DIR = QT_ROOT / "src" / "desktop-ui"
DOCS_DIR = QT_ROOT / "docs"
APP_ICON = QT_ROOT / "assets" / "app-icon.ico"
CONFIG_DIR = QT_ROOT / "config"
VERIFY_DIR = USER_DATA / "verify" if _TEST_DATA_ROOT else QT_ROOT / "验证"

PRODUCT_NAME = "在役检查系统-指套管数据管理工具"
SERVICE_NAME = "thimble-local"
SERVICE_VERSION = "2026.10.26.1"
BUILD_QUERY = "build=20261102-release-review"
PREFERRED_PORT = int(os.environ.get("THIMBLE_PORT", "18767"))
SERVICE_INSTANCE = secrets.token_hex(24)  # 48 hex，与 randomBytes(24) 一致

# Chromium 开关：复刻 main.cjs:15-25 + 追加离线相关项
CHROMIUM_FLAGS = [
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
    "--no-first-run",
    "--disable-breakpad",
    "--in-process-gpu",
    "--disable-gpu-compositing",
    "--high-dpi-support=1",
]

MAIN_WINDOW_SIZE = (1480, 960)
MAIN_WINDOW_MIN = (800, 600)
SETTINGS_WINDOW_SIZE = (1180, 860)
SETTINGS_WINDOW_MIN = (820, 620)
VISUALIZATION_WINDOW_SIZE = (1100, 780)
VISUALIZATION_WINDOW_MIN = (640, 480)
BACKGROUND = "#f3f5f6"
SETTINGS_BACKGROUND = "#f4f7f8"

SETTINGS_SECTIONS = frozenset({
    "settingsDataPane", "settingsPreferencesPane", "settingsImportPane",
    "settingsRulesPane", "settingsAccountsPane", "settingsMaintenancePane",
})
VISUALIZATION_PANELS = frozenset({
    "chart31", "chart32", "chart34", "chartTubeTrend", "chartDistHistogram",
    "chartDistScatter", "vwCoverage", "vwDepthDistribution", "vwFrequencyChart",
    "vwUnitOverview", "vwRiskContent", "c32PositionShare",
})

EXCEL_EXTENSIONS = frozenset({".xls", ".xlsx", ".xlsm"})
EXCEL_SCAN_LIMIT = 500
OFFICE_MAX_BYTES = 50 * 1024 * 1024
CORE_IMAGE_MAX_BYTES = 20 * 1024 * 1024
VIS_IMAGE_MAX_BYTES = 24 * 1024 * 1024
HEADER_MAX_BYTES = 256 * 1024
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
ZIP_SIGNATURE = bytes.fromhex("504b0304")
LOW_SPACE_BYTES = 128 * 1024 * 1024


class _Runtime:
    """端口回退后全局替换 BASE_URL（对应 main.cjs:41,53,195-196）。"""

    def __init__(self) -> None:
        self.port = PREFERRED_PORT
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.start_url = f"{self.base_url}/?{BUILD_QUERY}"

    def set_port(self, port: int) -> None:
        self.port = int(port)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.start_url = f"{self.base_url}/?{BUILD_QUERY}"

    def settings_url(self, section: str) -> str:
        return f"{self.start_url}&window=settings&section={quote(section)}"

    def visualization_url(self, panel: str, state_json: str) -> str:
        return (
            f"{self.start_url}&visualization={quote(panel)}"
            f"&visualizationState={quote(state_json)}"
        )


from urllib.parse import quote  # noqa: E402  (供 _Runtime 方法使用)

RUNTIME = _Runtime()
