@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0" || exit /b 1
set "THIMBLE_PORT=18767"
call "启动正式版.cmd"
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%
