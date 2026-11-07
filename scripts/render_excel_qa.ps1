param([string]$Folder = 'tmp/source-form-qa-20261020')
$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$target = Join-Path $root $Folder
$evidence = Get-Content -LiteralPath (Join-Path $target 'evidence.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    foreach ($item in $evidence.exports | Where-Object { $_.filename.EndsWith('.xlsx') }) {
        $file = Join-Path $target $item.filename
        $book = $excel.Workbooks.Open($file, 0, $true)
        try {
            $sheet = $book.Worksheets.Item(1)
            $sheet.ExportAsFixedFormat(0, [IO.Path]::ChangeExtension($file, '.pdf'))
            Write-Output $item.filename
        } finally { $book.Close($false) }
    }
} finally { $excel.Quit() }
