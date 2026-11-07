@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0" || exit /b 1
set "THIMBLE_USER_DATA_DIR=%~dp0user-data"
set "THIMBLE_PORT=18767"
set "THIMBLE_NATIVE_QT=1"
set "QT_PYTHONW=%~dp0.venv-qt\Scripts\pythonw.exe"
if not exist "%QT_PYTHONW%" (
  echo Qt Python runtime was not found:
  echo "%QT_PYTHONW%"
  echo Repair or recreate the .venv-qt environment before launching.
  pause
  exit /b 1
)
start "" "%QT_PYTHONW%" -m qt_shell.main
if errorlevel 1 (
  echo Qt 主程序启动失败，请检查 Qt 运行环境。
  pause
  exit /b 1
)
endlocal
exit /b 0
