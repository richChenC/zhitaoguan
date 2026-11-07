param([string]$Folder = 'tmp/source-form-qa-20261020')
$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$target = Join-Path $root $Folder
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    foreach ($file in Get-ChildItem -LiteralPath $target -Filter '*.docx') {
        $document = $word.Documents.Open($file.FullName, $false, $true)
        try {
            $document.ExportAsFixedFormat([IO.Path]::ChangeExtension($file.FullName, '.pdf'), 17)
            Write-Output "$($file.Name): $($document.ComputeStatistics(2)) pages"
        } finally { $document.Close(0) }
    }
} finally { $word.Quit() }
