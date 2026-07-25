@echo off
setlocal
cd /d "%~dp0"
set "ELECTRON=node_modules\electron\dist\electron.exe"
set "LOG=%~dp0desktop-startup.log"
if not exist "%ELECTRON%" goto missing
start "" "%ELECTRON%" . 1>>"%LOG%" 2>&1
if errorlevel 1 goto failed
exit /b 0

:missing
echo Electron runtime is missing.
echo Electron runtime is missing.>>"%LOG%"
pause
exit /b 1

:failed
echo Desktop application failed to start. See desktop-startup.log.
pause
exit /b 1
