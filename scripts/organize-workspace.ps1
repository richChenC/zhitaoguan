[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$providerPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($WorkspaceRoot)
$root = [IO.Path]::GetFullPath($providerPath).TrimEnd('\')
if (-not [IO.Directory]::Exists((Join-Path $root '.git'))) {
    throw 'Expected the original project workspace with its Git metadata.'
}
$logDir = Join-Path $root '04_开发归档\05_整理记录'
[IO.Directory]::CreateDirectory($logDir) | Out-Null
$log = Join-Path $logDir ("目录整理_{0}.jsonl" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Resolve-WorkspacePath([string]$relative) {
    $full = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes workspace: $relative"
    }
    return $full
}

function Record-Result($row) {
    $row.time = (Get-Date).ToString('o')
    $line = $row | ConvertTo-Json -Compress -Depth 6
    [IO.File]::AppendAllText($log, $line + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false))
    Write-Output $line
}

# Relative old/new paths are explicit; no recursive copy, deletion or overwrite.
# Junctions keep stored database source paths and active processes working.
$moves = @(
    @('记忆', '02_项目原始资料\01_需求与记忆\记忆', $true),
    @('对话记录与记忆导出_2026-08-26.md', '02_项目原始资料\01_需求与记忆\对话记录与记忆导出_2026-08-26.md', $false),
    @('孔姐发的', '02_项目原始资料\02_业务参考资料\孔姐发的', $true),
    @('测试数据', '02_项目原始资料\03_原始检测数据\测试数据', $true),
    @('指套管模型工程', '02_项目原始资料\04_三维模型工程\指套管模型工程', $true),
    @('指套管三维模型_完整工程', '02_项目原始资料\04_三维模型工程\指套管三维模型_完整工程', $true),
    @('导入台账_全量72次大修.xlsx', '02_项目原始资料\05_台账与计划\导入台账_全量72次大修.xlsx', $false),
    @('~$导入台账_全量72次大修.xlsx', '02_项目原始资料\05_台账与计划\~$导入台账_全量72次大修.xlsx', $false),
    @('指套管数据管理工具_年度计划表.xlsx', '02_项目原始资料\05_台账与计划\指套管数据管理工具_年度计划表.xlsx', $false),
    @('岭澳核电厂_报告表头设置.json', '02_项目原始资料\05_台账与计划\岭澳核电厂_报告表头设置.json', $false),
    @('软件版本历史', '03_历史版本备份\整理前版本与完整备份', $true),
    @('软件部分0828', '03_历史版本备份\软件部分0828_归档原件_20261021', $true),
    @('启动本地指套管软件.cmd', '03_历史版本备份\旧启动入口\启动本地指套管软件.cmd', $false),
    @('wy', '04_开发归档\01_网页原型与采集\wy', $true),
    @('新建 文本文档.html', '04_开发归档\01_网页原型与采集\新建 文本文档.html', $false),
    @('tmp_pylibs', '04_开发归档\02_调试脚本与临时依赖\tmp_pylibs', $true),
    @('_check.mjs', '04_开发归档\02_调试脚本与临时依赖\_check.mjs', $false),
    @('tmp_check.mjs', '04_开发归档\02_调试脚本与临时依赖\tmp_check.mjs', $false),
    @('--full-page', '04_开发归档\03_历史导出与截图\历史界面截图.png', $false),
    @('TH_三字符缺失记录_20261016_101108.xlsx', '04_开发归档\03_历史导出与截图\TH_三字符缺失记录_20261016_101108.xlsx', $false),
    @('.workbuddy', '04_开发归档\04_开发过程记录\.workbuddy', $true),
    @('软件正式版_20261021', '01_当前软件\软件正式版_20261021', $true)
)
foreach ($entry in $moves) {
    $old = Resolve-WorkspacePath $entry[0]
    $new = Resolve-WorkspacePath $entry[1]
    $compat = [bool]$entry[2]
    $row = @{ old = $entry[0]; new = $entry[1]; compatibility = $compat; status = 'planned' }
    $item = Get-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        $target = [IO.Path]::GetFullPath([string]$item.Target)
        if (-not $target.Equals($new, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected existing link: $old -> $target"
        }
        $row.status = 'already_organized'
        Record-Result $row
        continue
    }
    if (-not $item) {
        if (Test-Path -LiteralPath $new) { $row.status = 'already_organized' }
        elseif ([IO.Path]::GetFileName($old).StartsWith('~$')) { $row.status = 'temporary_lock_gone' }
        else { $row.status = 'missing_source' }
        Record-Result $row
        continue
    }
    $existingTarget = Get-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
    if ($existingTarget) {
        if (($existingTarget.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
            ([IO.Path]::GetFullPath([string]$existingTarget.Target)).Equals(
                $old, [StringComparison]::OrdinalIgnoreCase)) {
            if ($Apply) {
                # Delete only this verified junction, never its contents/target.
                [IO.Directory]::Delete($new)
            }
        } else {
            throw "Refusing to overwrite: $new"
        }
    }
    if (-not $Apply) { Record-Result $row; continue }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($new)) | Out-Null
    $wasDirectory = $item.PSIsContainer
    $hash = $null
    try {
        if (-not $wasDirectory) {
            $hash = (Get-FileHash -LiteralPath $old -Algorithm SHA256).Hash
        }
        if ($wasDirectory) { [IO.Directory]::Move($old, $new) }
        else { [IO.File]::Move($old, $new) }
    } catch {
        # A running executable or an Office lock may prevent renaming.
        # Keep the data physically in place and expose a classified entry.
        $row.status = 'classified_in_use'
        $row.error = $_.Exception.Message
        if ($wasDirectory) {
            New-Item -ItemType Junction -Path $new -Target $old | Out-Null
            & attrib.exe '-H' '/L' $new
            if ($LASTEXITCODE -ne 0) { throw "Could not show classified junction: $new" }
            $row.entry = $entry[1]
        } elseif (-not $item.Name.StartsWith('~$')) {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($new + '.lnk')
            $shortcut.TargetPath = $old
            $shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($old)
            $shortcut.Description = '原文件正在使用，保留原位；关闭文件后可再次执行整理脚本。'
            $shortcut.Save()
            $row.entry = $entry[1] + '.lnk'
        }
        & attrib.exe '+H' '/L' $old
        if ($LASTEXITCODE -ne 0) { throw "Could not hide occupied compatibility path: $old" }
        Record-Result $row
        continue
    }
    if ($wasDirectory -or -not $item.Name.StartsWith('~$')) {
        & attrib.exe '-H' '/L' $new
        if ($LASTEXITCODE -ne 0) { throw "Could not show organized target: $new" }
    }
    if (-not $wasDirectory -and (Test-Path -LiteralPath ($new + '.lnk'))) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($new + '.lnk')
        if (-not $shortcut.TargetPath.Equals($old, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected shortcut, refusing to delete: $new.lnk"
        }
        [IO.File]::Delete($new + '.lnk')
    }
    if ($compat) {
        try {
            New-Item -ItemType Junction -Path $old -Target $new | Out-Null
        } catch {
            [IO.Directory]::Move($new, $old)
            throw "Compatibility link failed; directory restored: $old. $_"
        }
        # /L applies the hidden attribute to the link, not its target.
        & attrib.exe '+H' '/L' $old
        if ($LASTEXITCODE -ne 0) { throw "Could not hide compatibility junction: $old" }
        $targetInfo = Get-Item -LiteralPath $new -Force
        if ($targetInfo.Attributes -band [IO.FileAttributes]::Hidden) {
            throw "Unexpected hidden target; inspect before continuing: $new"
        }
    } elseif ($hash -ne (Get-FileHash -LiteralPath $new -Algorithm SHA256).Hash) {
        throw "Post-move hash mismatch: $new"
    }
    $row.status = 'moved'
    if ($hash) { $row.sha256 = $hash }
    Record-Result $row
}
$qtVersion = Resolve-WorkspacePath '08_Qt移植版'
$launcherTemplate = Join-Path $qtVersion 'scripts\start-current-version.cmd'
if ($Apply -and (Test-Path -LiteralPath $launcherTemplate)) {
    [IO.File]::Copy($launcherTemplate, (Join-Path $root '启动Qt主版本.cmd'), $true)
}
Write-Output "Operation log: $log"
