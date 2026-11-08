param([switch]$Incremental)

$ErrorActionPreference = 'Stop'

# Build the native Qt onedir executable with the dedicated PySide6 environment.
$projectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$venvPython = Join-Path $projectRoot '.venv-qt/Scripts/python.exe'
$python = if ($env:THIMBLE_BUILD_PYTHON) { $env:THIMBLE_BUILD_PYTHON } elseif (Test-Path $venvPython) { $venvPython } else { 'python' }
$tools = if ($env:THIMBLE_BUILD_TOOLS) { $env:THIMBLE_BUILD_TOOLS } else { Join-Path $projectRoot '.build_tools' }
$dist = if ($env:THIMBLE_BUILD_SHELL_DIST) { $env:THIMBLE_BUILD_SHELL_DIST } else { Join-Path $projectRoot 'build/shell' }
$work = if ($env:THIMBLE_BUILD_SHELL_WORK) { $env:THIMBLE_BUILD_SHELL_WORK } else { Join-Path $projectRoot 'build/pyinstaller-shell' }

if (-not (Test-Path (Join-Path $tools 'PyInstaller'))) {
    throw 'Missing build tools; install scripts/requirements-build-tools.txt into .build_tools.'
}

$previousPythonPath = $env:PYTHONPATH
$pythonPaths = @($tools, $projectRoot, $previousPythonPath) | Where-Object { $_ }
$env:PYTHONPATH = [string]::Join(';', $pythonPaths)
try {
    # Windows PowerShell treats PyInstaller stderr INFO output as errors.
    $ErrorActionPreference = 'Continue'
    $buildArguments = @('-s', '-m', 'PyInstaller', '--noconfirm', '--distpath', $dist, '--workpath', $work)
    if (-not $Incremental) { $buildArguments += '--clean' }
    $buildArguments += (Join-Path $projectRoot 'scripts/thimble-shell.spec')
    & $python @buildArguments
    $buildExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($buildExitCode -ne 0) { throw "PyInstaller failed: $buildExitCode" }

    # Match the app-root VC runtime to the newer copy required by PySide6.
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
    & $python (Join-Path $projectRoot 'scripts/verify_native_bundle.py') (Join-Path $shellDir '在役检查系统-指套管数据管理工具.exe') --output (Join-Path $dist 'source-verification.json')
    if ($LASTEXITCODE -ne 0) { throw 'Native Qt source/resource verification failed.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
