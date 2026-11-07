param([string]$Destination = 'tmp/reference-docx-20261020')
$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$source = Join-Path (Split-Path -Parent $root) '孔姐发的\指套管信息\宁德一号机历次之套管综合报告word'
$target = [IO.Path]::GetFullPath((Join-Path $root $Destination))
[IO.Directory]::CreateDirectory($target) | Out-Null
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    foreach ($file in Get-ChildItem -LiteralPath $source -Filter '*.doc' | Where-Object { -not $_.Name.StartsWith('~$') }) {
        $copy = Join-Path $target $file.Name
        $inputStream = [IO.File]::Open($file.FullName, 'Open', 'Read', 'ReadWrite')
        try { $outputStream = [IO.File]::Create($copy); try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() } } finally { $inputStream.Dispose() }
        $before = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
        $document = $word.Documents.Open($copy, $false, $true)
        try {
            $output = Join-Path $target ($file.BaseName + '.docx')
            $document.SaveAs2($output, 16)
            Write-Output $output
        } finally { $document.Close(0) }
        if ($before -ne (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash) { throw '副本校验失败' }
    }
} finally { $word.Quit() }
