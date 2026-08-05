@echo off
setlocal
cd /d "%~dp0"
set "ELECTRON=node_modules\electron\dist\electron.exe"
set "LOG=%~dp0desktop-startup.log"

rem Resolve runtimes without requiring npm/python to be on PATH.
set "NPM="
set "NODE_DIR="
set "NODE="
if exist "D:\CodeApps\env\nodejs\npm.cmd" set "NPM=D:\CodeApps\env\nodejs\npm.cmd"
if exist "D:\CodeApps\env\nodejs\node.exe" (
  set "NODE_DIR=D:\CodeApps\env\nodejs"
  set "NODE=D:\CodeApps\env\nodejs\node.exe"
)
if not defined NPM for /f "delims=" %%N in ('where npm.cmd 2^>nul') do if not defined NPM set "NPM=%%N"
if not defined NODE for /f "delims=" %%N in ('where node.exe 2^>nul') do if not defined NODE set "NODE=%%N"
if not defined NODE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" (
  set "NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
  set "NODE_DIR=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
)
if defined NODE_DIR set "PATH=%NODE_DIR%;%PATH%"
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" if exist "D:\CodeApps\env\python\python.exe" set "PYTHON=D:\CodeApps\env\python\python.exe"
if not exist "%PYTHON%" if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON%" "%PYTHON%" -c "import sys" >nul 2>&1
if errorlevel 1 if exist "D:\CodeApps\env\python\python.exe" set "PYTHON=D:\CodeApps\env\python\python.exe"

if not exist "%ELECTRON%" (
  echo Installing desktop dependencies...
  if not defined NPM (
    echo npm runtime was not found. Install Node.js or place it at D:\CodeApps\env\nodejs.
    goto dependency_failed
  )
  call "%NPM%" install
  if errorlevel 1 goto dependency_failed
  if not exist "%ELECTRON%" if exist "node_modules\electron\install.js" (
    if not defined NODE goto dependency_failed
    "%NODE%" "node_modules\electron\install.js"
    if errorlevel 1 goto dependency_failed
  )
  if not exist "%ELECTRON%" goto dependency_failed
)

if not exist "%PYTHON%" (
  echo Creating the local Python environment...
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python runtime was not found. Install Python 3.11 or newer.
    goto dependency_failed
  )
  python -m venv .venv
  if errorlevel 1 goto dependency_failed
)

"%PYTHON%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Installing the local data service...
  "%PYTHON%" -m pip install flask
  if errorlevel 1 goto dependency_failed
)

set "THIMBLE_PYTHON=%PYTHON%"
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
