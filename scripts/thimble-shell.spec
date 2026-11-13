# -*- mode: python ; coding: utf-8 -*-
"""Qt 桌面壳 PyInstaller 配置（onedir，窗口化）。

原生模型、图标和参考数据随壳冻结。业务后端、报告模板和使用手册由安装包脚本
布放到 exe 同级目录，与 constants.QT_ROOT 的冻结布局一致。
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent.resolve()

datas = [
    (str(ROOT / "qt_shell" / "native_model.qml"), "qt_shell"),
    (str(ROOT / "qt_shell" / "model_assets"), "qt_shell/model_assets"),
    (str(ROOT / "qt_shell" / "shaders"), "qt_shell/shaders"),
    (str(ROOT / "qt_shell" / "assets"), "qt_shell/assets"),
    (str(ROOT / "src/desktop-ui/assets/app-icon.png"), "native_resources/assets"),
    (str(ROOT / "src/desktop-ui/assets/icons"), "native_resources/assets/icons"),
    (str(ROOT / "src/desktop-ui/visualizations/reference-thimble/data"),
     "native_resources/visualizations/reference-thimble/data"),
]

a = Analysis(
    [str(ROOT / "scripts" / "shell_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    excludes=["numpy", "pandas", "PIL", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "qt_shell.web_profile",
              "qt_shell.windows", "qt_shell.desktop_api"],
)
# A transitive Poppler dependency may contribute ICU 78 DLLs whose exports
# are incompatible with Qt's ICU imports. Windows supplies the compatible ICU
# implementation used by this application, so do not bundle those DLLs.
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
    and not any(part in entry[0].lower() for part in ("webengine", "webchannel", "chromium"))
]
# QtQuick's hook scans all installed QML modules, including unrelated browser
# plugins. Filter the collected payload as well as the Python import graph.
a.datas = [
    entry for entry in a.datas
    if not any(part in entry[0].lower() for part in ("webengine", "webchannel", "chromium"))
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="在役检查系统-指套管数据管理工具",
    console=False,
    icon=str(ROOT / "assets" / "app-icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="在役检查系统-指套管数据管理工具",
)
