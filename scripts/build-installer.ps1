﻿$ErrorActionPreference = 'Stop'

# 编译 Inno Setup 安装包。前置条件：
#   1. 已构建后端 exe：scripts\build-backend.ps1
#   2. 已构建桌面壳 exe：scripts\build-shell.ps1
#   3. 已安装 Inno Setup 6（https://jrsoftware.org/isdl.php）
# 产物：07_软件发布包\installer\在役检查系统-指套管数据管理工具-安装包-<版本>-x64.exe

$projectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "未找到 Inno Setup 6（ISCC.exe）。请先从 https://jrsoftware.org/isdl.php 安装，再重新执行本脚本。"
}

$shellExe = Join-Path $projectRoot 'build\shell\在役检查系统-指套管数据管理工具\在役检查系统-指套管数据管理工具.exe'
$backendExe = Join-Path $projectRoot 'build\backend\thimble-backend.exe'
foreach ($required in @($shellExe, $backendExe)) {
    if (-not (Test-Path $required)) {
        throw "缺少构建产物：$required`n请先依次执行 scripts\build-backend.ps1 与 scripts\build-shell.ps1。"
    }
}

$verify = Join-Path $projectRoot 'scripts\verify-package-payload.ps1'
$shellSource = if ($env:THIMBLE_INSTALLER_SHELL_SOURCE) { $env:THIMBLE_INSTALLER_SHELL_SOURCE } else { Split-Path -Parent $shellExe }
$backendSource = if ($env:THIMBLE_INSTALLER_BACKEND_SOURCE) { $env:THIMBLE_INSTALLER_BACKEND_SOURCE } else { $backendExe }
& $verify -ProjectRoot $projectRoot -PackageRoot $shellSource

$python = if ($env:THIMBLE_BUILD_PYTHON) { $env:THIMBLE_BUILD_PYTHON } else { Join-Path $projectRoot '.venv-qt\Scripts\python.exe' }
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = @((Join-Path $projectRoot '.build_tools'), $oldPythonPath) -join ';'
    & $python (Join-Path $projectRoot 'scripts\verify-release-backend.py') $backendSource
    if ($LASTEXITCODE -ne 0) {
        throw '后端构建内容不符合发布要求，请重新执行 scripts\build-backend.ps1。'
    }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}

$iss = Join-Path $projectRoot 'scripts\thimble-installer.iss'
$isccArgs = @($iss)
# Release verification can point Inno Setup at an isolated build without
# replacing a running development executable.
if ($env:THIMBLE_INSTALLER_SHELL_SOURCE) {
    $isccArgs += "/DTHIMBLE_SHELL_SOURCE=$($env:THIMBLE_INSTALLER_SHELL_SOURCE)"
}
if ($env:THIMBLE_INSTALLER_BACKEND_SOURCE) {
    $isccArgs += "/DTHIMBLE_BACKEND_SOURCE=$($env:THIMBLE_INSTALLER_BACKEND_SOURCE)"
}
if ($env:THIMBLE_INSTALLER_OUTPUT_DIR) {
    $isccArgs += "/DTHIMBLE_OUTPUT_DIR=$($env:THIMBLE_INSTALLER_OUTPUT_DIR)"
}
& $iscc @isccArgs
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup 编译失败，退出码：$LASTEXITCODE"
}
Write-Output "安装包已输出到：$(Join-Path $projectRoot '..\07_软件发布包\installer')"
