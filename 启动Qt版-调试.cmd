@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0" || exit /b 1
set "THIMBLE_USER_DATA_DIR=%~dp0user-data"
set "QT_PYTHON=%~dp0.venv-qt\Scripts\python.exe"
if not exist "%QT_PYTHON%" (
  echo Qt Python runtime was not found:
  echo "%QT_PYTHON%"
  pause
  exit /b 1
)
"%QT_PYTHON%" -m qt_shell.main
set "RESULT=%ERRORLEVEL%"
echo.
echo Qt 版退出码：%RESULT%
pause
endlocal & exit /b %RESULT%
