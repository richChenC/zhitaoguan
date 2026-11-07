$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\scripts\cleanup-test-artifacts.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count) { throw "Cleanup script parse errors: $($parseErrors -join '; ')" }
$definition = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] `
        -and $node.Name -eq 'Test-DeleteCandidate'
}, $true)
if (-not $definition) { throw 'Test-DeleteCandidate function not found' }
. ([scriptblock]::Create($definition.Extent.Text))

$cutoff = [DateTime]::UtcNow.AddHours(-24)
$oldFile = [pscustomobject]@{
    LastWriteTimeUtc = $cutoff.AddMinutes(-1)
    CreationTimeUtc = $cutoff.AddHours(-1)
    Extension = '.xlsx'
    Name = 'generated.xlsx'
}
$recentFile = [pscustomobject]@{
    LastWriteTimeUtc = [DateTime]::UtcNow
    CreationTimeUtc = [DateTime]::UtcNow
    Extension = '.xlsx'
    Name = 'generated.xlsx'
}

if (-not (Test-DeleteCandidate $oldFile 'generated.xlsx' 'test-output')) {
    throw 'Stale generated test output should be eligible for cleanup'
}
if (Test-DeleteCandidate $recentFile 'generated.xlsx' 'test-output') {
    throw 'Recent generated test output must be retained'
}
if (Test-DeleteCandidate $oldFile 'source.xlsx' 'source') {
    throw 'Unclassified files must not be eligible for cleanup'
}
Write-Output 'CLEANUP POLICY PASS'
