@echo off
chcp 65001 >nul
setlocal
set "QT_DIR=%~dp008_Qt移植版"
if not exist "%QT_DIR%\启动正式版.cmd" (
  echo 找不到 Qt 主版本启动文件：
  echo "%QT_DIR%\启动正式版.cmd"
  pause
  exit /b 1
)
call "%QT_DIR%\启动正式版.cmd"
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%
