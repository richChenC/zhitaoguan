"""PyInstaller 打包入口：等价于 python -m qt_shell.main。

环境变量配置在 qt_shell.main 模块顶层完成，导入即生效。
退出沿用 os._exit，避免 QWebEngineProfile 在解释器析构阶段挂起。
"""
import os

from qt_shell.main import main

os._exit(main())
