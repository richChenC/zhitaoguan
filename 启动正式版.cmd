@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
call "启动Qt版.cmd"
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%
