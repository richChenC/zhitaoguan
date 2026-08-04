@echo off
setlocal
cd /d "%~dp0"
set "ELECTRON=node_modules\electron\dist\electron.exe"
set "PYTHON=.venv\Scripts\python.exe"
set "LOG=%~dp0desktop-startup.log"

if not exist "%ELECTRON%" (
  echo Installing desktop dependencies...
  call npm.cmd install
  if errorlevel 1 goto dependency_failed
)

if not exist "%PYTHON%" (
  echo Creating the local Python environment...
  python -m venv .venv
  if errorlevel 1 goto dependency_failed
)

"%PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Installing the local data service...
  "%PYTHON%" -m pip install flask
  if errorlevel 1 goto dependency_failed
)

start "" "%ELECTRON%" .
if errorlevel 1 goto failed
exit /b 0

:dependency_failed
echo Failed to install required runtime dependencies.
echo Failed to install required runtime dependencies.>>"%LOG%"
pause
exit /b 1

:failed
echo Desktop application failed to start. See desktop-startup.log.
pause
exit /b 1
