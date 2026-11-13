[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$PackageRoot
)

$ErrorActionPreference = 'Stop'
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $scriptRoot
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)

function Require-Path([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "缺少发布必需项：$Description`n路径：$Path"
    }
}

$required = @(
    @{ Path = Join-Path $ProjectRoot 'build\shell\在役检查系统-指套管数据管理工具'; Description = 'Qt 冻结程序目录' },
    @{ Path = Join-Path $ProjectRoot 'build\backend\thimble-backend.exe'; Description = '冻结后端程序' },
    @{ Path = Join-Path $ProjectRoot 'docs\使用手册'; Description = '用户手册目录' },
    @{ Path = Join-Path $ProjectRoot 'assets\report-templates'; Description = '报告模板目录' },
    @{ Path = Join-Path $ProjectRoot 'assets\app-icon.ico'; Description = '应用图标' }
)
foreach ($item in $required) {
    Require-Path $item.Path $item.Description
}

$iss = Get-Content -Raw -LiteralPath (Join-Path $ProjectRoot 'scripts\thimble-installer.iss')
foreach ($forbiddenSource in @(
    'Source:\s*"\.\.\\src\\\*"',
    'Source:\s*"\.\.\\docs\\\*"',
    'Source:\s*"\.\.\\assets\\\*"',
    'Source:\s*"\.\.\\\.vendor\\\*"',
    'Source:\s*"\.\.\\user-data\\'
)) {
    if ($iss -match $forbiddenSource) {
        throw "安装脚本仍包含宽泛或用户数据来源：$forbiddenSource"
    }
}

foreach ($allowedSource in @(
    '..\docs\使用手册\*',
    '..\assets\report-templates\*',
    '..\assets\app-icon.ico'
)) {
    if ($iss -notlike "*$allowedSource*") {
        throw "安装脚本缺少白名单来源：$allowedSource"
    }
}

if ($PackageRoot) {
    $PackageRoot = [IO.Path]::GetFullPath($PackageRoot)
    Require-Path $PackageRoot '待检查的发布目录'
    foreach ($runtimePath in @(
        '在役检查系统-指套管数据管理工具.exe',
        'build\backend\thimble-backend.exe',
        'assets\app-icon.ico',
        'assets\report-templates\inspection.docx',
        'assets\report-templates\comparison.docx',
        'docs\使用手册'
    )) {
        Require-Path (Join-Path $PackageRoot $runtimePath) "运行时必需文件或目录：$runtimePath"
    }
    $forbiddenNames = @(
        'user-data', '验证', 'tests', 'tmp', '05_测试与验证', '.venv-qt',
        '.git', '打包', 'src', 'qt_shell', 'scripts', '开发与验收记录'
    )
    $forbiddenExtensions = @(
        '.db', '.sqlite', '.sqlite3', '.log', '.csv', '.xls', '.xlsx',
        '.xlsm', '.py', '.pyc', '.map'
    )
    $violations = @(
        Get-ChildItem -LiteralPath $PackageRoot -Recurse -File -Force |
            Where-Object {
                $parts = $_.FullName.Substring($PackageRoot.Length).TrimStart('\').Split('\')
                ($parts.Length -gt 0 -and $forbiddenNames -contains $parts[0]) -or
                $forbiddenExtensions -contains $_.Extension.ToLowerInvariant()
            }
    )
    if ($violations.Count -gt 0) {
        $details = ($violations | ForEach-Object { $_.FullName }) -join "`n"
        throw "发布目录包含禁止打包内容：`n$details"
    }
}

Write-Output '发布包白名单检查通过：未发现数据库、用户数据、测试资料或源码目录。'
