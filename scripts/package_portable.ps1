param(
    [string]$Version = "0.1.0",
    [string]$PortableDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) "..\KnowNexus-portable"),
    [string]$OutputDirectory = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $PortableDirectory "KnowNexus.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Portable directory is incomplete: $exe was not found."
}
$requiredPaths = @(
    "backend\knownexus-backend.exe",
    "resources\app.asar",
    "tesseract\tesseract.exe",
    "model\whisper-small",
    "source-code\README.md",
    "使用说明.txt"
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $PortableDirectory $relativePath))) {
        throw "Portable directory is incomplete: $relativePath was not found."
    }
}

$archiveName = "KnowNexus-$Version-Windows-x64-portable.zip"
$archivePath = Join-Path $OutputDirectory $archiveName
$checksumPath = Join-Path $OutputDirectory "SHA256SUMS.txt"
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }

# Compress-Archive preserves non-ASCII filenames on Windows. The portable staging
# directory is already curated, so its children can be archived directly and the
# launch executables remain at the ZIP root.
Compress-Archive -Path (Join-Path $PortableDirectory "*") -DestinationPath $archivePath -CompressionLevel Optimal

$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  $archiveName" -Encoding ascii
Write-Output "Created: $archivePath"
Write-Output "Checksum: $checksumPath"
