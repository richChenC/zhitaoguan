﻿﻿$ErrorActionPreference = 'Stop'

# 构建 Qt 桌面壳主程序 exe（onedir，窗口化）。
# 产物：build\shell\在役检查系统-指套管数据管理工具\ 下的 exe 与 _internal。
$projectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
# 桌面壳依赖 PySide6，只有 .venv-qt 环境具备；系统 Python 无 PySide6，
# 用它打包会在启动时因缺模块直接退出。
$venvPython = Join-Path $projectRoot '.venv-qt\Scripts\python.exe'
$python = if ($env:THIMBLE_BUILD_PYTHON) { $env:THIMBLE_BUILD_PYTHON } elseif (Test-Path $venvPython) { $venvPython } else { 'python' }
$tools = if ($env:THIMBLE_BUILD_TOOLS) { $env:THIMBLE_BUILD_TOOLS } else { Join-Path $projectRoot '.build_tools' }
$dist = if ($env:THIMBLE_BUILD_SHELL_DIST) { $env:THIMBLE_BUILD_SHELL_DIST } else { Join-Path $projectRoot 'build\shell' }
$work = if ($env:THIMBLE_BUILD_SHELL_WORK) { $env:THIMBLE_BUILD_SHELL_WORK } else { Join-Path $projectRoot 'build\pyinstaller-shell' }

if (-not (Test-Path (Join-Path $tools 'PyInstaller'))) {
    throw '缺少 .build_tools 构建工具，请先执行：python -m pip install -r scripts/requirements-build-tools.txt --target .build_tools'
}

$previousPythonPath = $env:PYTHONPATH
$pythonPaths = @($tools, $projectRoot, $previousPythonPath) | Where-Object { $_ }
$env:PYTHONPATH = [string]::Join(';', $pythonPaths)

try {
# PS 5.1 会把 PyInstaller 写到 stderr 的 INFO 日志当作错误流终止脚本，
# 调用期间临时放宽，结束后以 $LASTEXITCODE 判断成败。
$ErrorActionPreference = 'Continue'
& $python -s -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $dist `
    --workpath $work `
    (Join-Path $projectRoot 'scripts\thimble-shell.spec')

$buildExitCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($buildExitCode -ne 0) {
    throw "PyInstaller 桌面壳构建失败，退出码：$buildExitCode"
}

# PyInstaller may collect an older VC runtime from the base Python runtime
# into _internal while PySide6 ships a newer runtime beside its Qt modules.
# Keep one version at the application root so QtCore cannot bind to the older
# DLL first when loading its dependent modules.
$shellDir = Join-Path $dist '在役检查系统-指套管数据管理工具'
$internalDir = Join-Path $shellDir '_internal'
$pysideRuntimeDir = Join-Path $internalDir 'PySide6'
foreach ($runtimeName in @(
    'MSVCP140.dll', 'MSVCP140_1.dll', 'MSVCP140_2.dll',
    'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll'
)) {
    $runtimeSource = Join-Path $pysideRuntimeDir $runtimeName
    if (Test-Path $runtimeSource) {
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $internalDir $runtimeName) -Force
    }
}
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
