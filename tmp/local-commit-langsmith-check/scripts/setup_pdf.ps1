# Install the pinned portable PDF tools inside this repository (Windows x64).
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitOperatingSystem) {
    throw 'The portable PDF toolchain requires 64-bit Windows.'
}
$projectDirectory = Split-Path -Parent $PSScriptRoot
$toolsDirectory = Join-Path $projectDirectory '.tools\pdf'
$downloadsDirectory = Join-Path $toolsDirectory 'downloads'
New-Item -ItemType Directory -Path $downloadsDirectory -Force | Out-Null

function Install-PortablePdfTool {
    param([string]$Name, [string]$Version, [string]$Url, [string]$Sha256, [string]$ArchiveExecutable)
    $destination = Join-Path $toolsDirectory $Name
    $executable = Join-Path $destination "$Name.exe"
    if (Test-Path -LiteralPath $executable) {
        Write-Host "$Name is already installed: $executable"
        return
    }
    $archive = Join-Path $downloadsDirectory "$Name-$Version.zip"
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host "Downloading $Name $Version from its official GitHub release..."
        Invoke-WebRequest -Uri $Url -OutFile $archive -UseBasicParsing
    }
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $Sha256) {
        throw "Checksum mismatch for $archive. Expected $Sha256, got $actualHash."
    }
    $expanded = Join-Path $downloadsDirectory "$Name-$Version"
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $expanded $ArchiveExecutable) -Destination $executable
    Write-Host "Installed $Name ${Version}: $executable"
}

Install-PortablePdfTool -Name 'pandoc' -Version '3.13' `
    -Url 'https://github.com/jgm/pandoc/releases/download/3.13/pandoc-3.13-windows-x86_64.zip' `
    -Sha256 '23e1f2e978a3df80db8bf65c9c59534f41a23140480cfb4f783a882ab7dc6a4e' `
    -ArchiveExecutable 'pandoc-3.13\pandoc.exe'

Install-PortablePdfTool -Name 'tectonic' -Version '0.17.0' `
    -Url 'https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip' `
    -Sha256 'f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f' `
    -ArchiveExecutable 'tectonic.exe'

Write-Host 'PDF tools are ready. The application discovers them automatically; no global PATH change is needed.'
Write-Host 'Tectonic downloads LaTeX packages on the first build and reuses its local cache.'
