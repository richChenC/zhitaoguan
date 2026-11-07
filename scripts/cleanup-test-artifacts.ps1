param(
    [switch]$Apply,
    [string]$ManifestDirectory,
    [ValidateRange(1, 168)][int]$Hours = 24
)
$ErrorActionPreference = 'Stop'
$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workspace = [IO.Path]::GetFullPath((Join-Path $appRoot '..'))
$started = [DateTime]::UtcNow
$cutoff = $started.AddHours(-$Hours)
$scopes = [Collections.Generic.List[object]]::new()
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

function Add-Scope([string]$Path, [string]$Kind) {
    if (-not [IO.Directory]::Exists($Path)) { return }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (([IO.File]::GetAttributes($full) -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing scope through a junction: $full"
    }
    if ($seen.Add($full)) { $scopes.Add([pscustomobject]@{Path=$full; Kind=$Kind}) }
}

Add-Scope (Join-Path $workspace '05_测试与验证\03_自动化临时产物') 'test-output'
Add-Scope (Join-Path $workspace '06_软件运行数据\开发导出\playwright') 'screenshots'
$testPrefixPattern = '^thimble-(audit(?:-|$)|codex-tests$|qa$|test-output$|visualization-tests$|release-check$|wizard-|report-wizard-|rpt-regression-|desktop-|service-isolation-|outcomes-|live-progress-|double-click-|reference-|scope-plate-)'
foreach ($drive in Get-PSDrive -PSProvider FileSystem | Where-Object {$_.Name -match '^[C-G]$'}) {
    foreach ($dir in Get-ChildItem -LiteralPath $drive.Root -Directory -Force) {
        if ($dir.Name -match $testPrefixPattern) {
            Add-Scope $dir.FullName 'sandbox'
        }
    }
}
$tempRoot = 'C:\Users\22234\AppData\Local\Temp'
foreach ($dir in Get-ChildItem -LiteralPath $tempRoot -Directory -Force) {
    if ($dir.Name -match '^thimble-(audit-|codex-tests$|qa$|test-output$|visualization-tests$|release-check|wizard-|report-wizard-|rpt-regression-|desktop-|service-isolation-|outcomes-|live-progress-|double-click-|reference-|scope-plate-)') {
        Add-Scope $dir.FullName 'sandbox'
    }
}
foreach ($name in 'src', 'tests', 'scripts') {
    Add-Scope (Join-Path $appRoot $name) 'bytecode'
}

# Never follow reparse points, including links inside a test sandbox.
function Get-PlainFiles([string]$Root) {
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($Root)
    while ($stack.Count) {
        $dir = $stack.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $dir -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            if ($item.PSIsContainer) { $stack.Push($item.FullName) }
            else { $item }
        }
    }
}

function Test-DeleteCandidate($File, [string]$Relative, [string]$Kind) {
    if ($File.LastWriteTimeUtc -ge $cutoff) { return $false }
    if ($File.CreationTimeUtc -ge $cutoff) { return $false }
    if ($Kind -eq 'screenshots') { return $File.Extension -in '.png', '.jpg', '.jpeg', '.webp' }
    if ($Kind -eq 'bytecode') {
        return $Relative -match '(^|\\)__pycache__\\' -and $File.Extension -eq '.pyc'
    }
    # Keep source snapshots, installer/build binaries, archives and concise evidence.
    if ($Relative -match '(^|\\)(\.git|node_modules|\.venv|src|scripts|tests|source|source-final|\.vendor)(\\|$)') {
        return $false
    }
    if ($Relative -match '(^|\\)profile(\\|$)') { return $true }
    if ($File.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$') { return $true }
    if ($File.Extension -in '.png', '.jpg', '.jpeg', '.webp', '.bdic', '.cache', '.pyc') { return $true }
    if ($Relative -match '(^|\\)(Cache|Code Cache|GPUCache|DawnGraphiteCache|DawnWebGPUCache|ShaderCache|GrShaderCache)(\\|$)') {
        return $true
    }
    if ($Kind -in 'test-output', 'sandbox' -and $File.Extension -in '.xlsx', '.docx', '.csv', '.json', '.log') {
        return $true
    }
    return $false
}

$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(python|python3|node|electron|在役检查系统).*\.exe$'
})
$candidates = [Collections.Generic.List[object]]::new()
$summary = [Collections.Generic.List[object]]::new()
if ($ManifestDirectory) {
    if (-not $Apply) { throw 'ManifestDirectory requires Apply.' }
    $expectedParent = [IO.Path]::GetFullPath((Join-Path $workspace '04_开发归档\05_整理记录')).TrimEnd('\') + '\'
    $manifestRoot = [IO.Path]::GetFullPath($ManifestDirectory)
    if (-not $manifestRoot.StartsWith($expectedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest is outside the cleanup records folder: $manifestRoot"
    }
    foreach ($row in Import-Csv -LiteralPath (Join-Path $manifestRoot 'candidates.csv')) {
        if (-not $seen.Contains($row.Scope)) { throw "Unrecognized scope in manifest: $($row.Scope)" }
        if ($processes | Where-Object {$_.CommandLine -and $_.CommandLine.IndexOf($row.Scope, [StringComparison]::OrdinalIgnoreCase) -ge 0}) {
            throw "Active process references a manifest scope: $($row.Scope)"
        }
        $row.Bytes = [long]$row.Bytes
        $candidates.Add($row)
    }
    foreach ($group in $candidates | Group-Object Scope) {
        $summary.Add([pscustomobject]@{Path=$group.Name; Files=$group.Count; Bytes=($group.Group | Measure-Object Bytes -Sum).Sum})
    }
} else {
foreach ($scope in $scopes) {
    if ($processes | Where-Object {$_.CommandLine -and $_.CommandLine.IndexOf($scope.Path, [StringComparison]::OrdinalIgnoreCase) -ge 0}) {
        Write-Warning "Active process references scope; skipped: $($scope.Path)"
        continue
    }
    $count = 0
    [long]$bytes = 0
    foreach ($file in Get-PlainFiles $scope.Path) {
        $relative = $file.FullName.Substring($scope.Path.Length).TrimStart('\')
        if (Test-DeleteCandidate $file $relative $scope.Kind) {
            $candidates.Add([pscustomobject]@{
                Path=$file.FullName; Scope=$scope.Path; Bytes=$file.Length
                CreatedUtc=$file.CreationTimeUtc.ToString('o')
                ModifiedUtc=$file.LastWriteTimeUtc.ToString('o')
            })
            $count++
            $bytes += $file.Length
        }
    }
    if ($count) {
        $summary.Add([pscustomobject]@{Path=$scope.Path; Files=$count; Bytes=$bytes})
        Write-Output ("SCAN {0}: {1} files, {2:N2} GiB" -f $scope.Path,$count,($bytes/1GB))
    }
}
}

$reportDir = Join-Path $workspace ('04_开发归档\05_整理记录\清理_' + $started.ToString('yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $reportDir | Out-Null
$candidates | Export-Csv -LiteralPath (Join-Path $reportDir 'candidates.csv') -NoTypeInformation -Encoding utf8
$before = @(Get-PSDrive -PSProvider FileSystem | Where-Object {$_.Name -match '^[C-G]$'} |
    Select-Object Name,Free)
$deleted = 0
[long]$deletedBytes = 0
$failures = [Collections.Generic.List[object]]::new()
if ($Apply) {
    foreach ($file in $candidates) {
        try {
            $full = [IO.Path]::GetFullPath($file.Path)
            if (-not $full.StartsWith($file.Scope + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "File escaped explicit scope: $full"
            }
            # Recheck every ancestor just before removing each individual file.
            $parent = [IO.Path]::GetDirectoryName($full)
            while ($parent) {
                if ([IO.File]::GetAttributes($parent) -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Path contains a reparse point: $parent"
                }
                $parent = [IO.Path]::GetDirectoryName($parent)
            }
            $current = Get-Item -LiteralPath $full -Force
            if ($current.Length -ne $file.Bytes -or $current.LastWriteTimeUtc.ToString('o') -ne $file.ModifiedUtc) {
                throw "File changed after inventory: $full"
            }
            if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "File became a reparse point: $full"
            }
            Remove-Item -LiteralPath $full -Force
            $deleted++
            $deletedBytes += $file.Bytes
            if ($deleted % 5000 -eq 0) {
                Write-Output ("DELETE {0}/{1} files, {2:N2} GiB" -f $deleted,$candidates.Count,($deletedBytes/1GB))
            }
        } catch {
            $failures.Add([pscustomobject]@{Path=$file.Path; Error=$_.Exception.Message})
        }
    }
}
$after = @(Get-PSDrive -PSProvider FileSystem | Where-Object {$_.Name -match '^[C-G]$'} |
    Select-Object Name,Free)
$report = [pscustomobject]@{
    StartedUtc=$started.ToString('o'); CutoffUtc=$cutoff.ToString('o'); Apply=[bool]$Apply
    CandidateFiles=$candidates.Count; DeletedFiles=$deleted; DeletedBytes=$deletedBytes
    DeletedGiB=[math]::Round($deletedBytes/1GB,3); Failures=@($failures.ToArray())
    Scopes=@($summary.ToArray()); FreeBefore=$before; FreeAfter=$after
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportDir 'result.json') -Encoding utf8
Write-Output ("DONE apply={0} candidates={1} deleted={2} GiB={3} failures={4} report={5}" -f [bool]$Apply,$candidates.Count,$deleted,$report.DeletedGiB,$failures.Count,$reportDir)
