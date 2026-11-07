$ErrorActionPreference = 'Stop'

$projectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$python = if ($env:THIMBLE_BUILD_PYTHON) { $env:THIMBLE_BUILD_PYTHON } else { 'python' }
$tools = if ($env:THIMBLE_BUILD_TOOLS) { $env:THIMBLE_BUILD_TOOLS } else { Join-Path $projectRoot '.build_tools' }
$vendor = if ($env:THIMBLE_BUILD_VENDOR) { $env:THIMBLE_BUILD_VENDOR } else { Join-Path $projectRoot '.build_vendor' }
if (-not $env:THIMBLE_BUILD_VENDOR -and -not (Test-Path (Join-Path $vendor 'openpyxl'))) {
    $vendor = Join-Path $projectRoot '.vendor'
}
$dist = if ($env:THIMBLE_BUILD_DIST) { $env:THIMBLE_BUILD_DIST } else { Join-Path $projectRoot 'build\backend' }
$work = if ($env:THIMBLE_BUILD_WORK) { $env:THIMBLE_BUILD_WORK } else { Join-Path $projectRoot 'build\pyinstaller' }
$name = 'thimble-backend'

if (-not (Test-Path (Join-Path $vendor 'openpyxl'))) {
    throw '缺少 .build_vendor 构建依赖，请先执行：python -m pip install -r scripts/requirements-backend.txt --target .build_vendor'
}
if (-not (Test-Path (Join-Path $tools 'PyInstaller'))) {
    throw '缺少 .build_tools 构建工具，请先执行：python -m pip install -r scripts/requirements-build-tools.txt --target .build_tools'
}

$previousPythonPath = $env:PYTHONPATH
$pythonPaths = @($tools, $vendor, $previousPythonPath) | Where-Object { $_ }
$env:PYTHONPATH = [string]::Join(';', $pythonPaths)

try {
& $python -s -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $name `
    --paths $vendor `
    --exclude-module numpy `
    --exclude-module pandas `
    --exclude-module PIL `
    --exclude-module lxml `
    --add-data "$(Join-Path $projectRoot 'src\desktop-ui');src\desktop-ui" `
    --add-data "$(Join-Path $projectRoot 'docs\使用手册');docs\使用手册" `
    --add-data "$(Join-Path $projectRoot 'assets\report-templates');assets\report-templates" `
    --distpath $dist `
    --workpath $work `
    --specpath $work `
    (Join-Path $projectRoot 'src\backend\server.py')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 后端构建失败，退出码：$LASTEXITCODE"
}

& $python (Join-Path $PSScriptRoot 'verify_backend_bundle.py') `
    --ui (Join-Path $projectRoot 'src\desktop-ui') `
    --exe (Join-Path $dist "$name.exe")
if ($LASTEXITCODE -ne 0) {
    throw "Backend UI resource verification failed; build output is invalid."
}
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
