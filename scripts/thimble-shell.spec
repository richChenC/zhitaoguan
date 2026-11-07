﻿﻿# -*- mode: python ; coding: utf-8 -*-
"""Qt 桌面壳 PyInstaller 配置（onedir，窗口化）。

资源目录（src/ docs/ assets/ config/ .vendor/ build/backend/）不由本 spec 内嵌，
由安装包脚本布放到 exe 同级目录，与 constants.QT_ROOT 的冻结布局一致。
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent.resolve()

datas = [
    (str(ROOT / "qt_shell" / "bridge_shim.js"), "qt_shell"),
    (str(ROOT / "qt_shell" / "vendor" / "qwebchannel.js"), "qt_shell/vendor"),
]

a = Analysis(
    [str(ROOT / "scripts" / "shell_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    excludes=["numpy", "pandas", "PIL"],
)
# A transitive Poppler dependency may contribute ICU 78 DLLs whose exports
# are incompatible with Qt's ICU imports. Windows supplies the compatible ICU
# implementation used by this application, so do not bundle those DLLs.
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
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
