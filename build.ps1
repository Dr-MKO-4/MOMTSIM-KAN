<#
.SYNOPSIS
    Build MoMTSim en application Electron + NSIS installer (Windows x64).

.DESCRIPTION
    Etapes :
      1. npm run build  dans frontend/   -> frontend/dist/
      2. pyinstaller momtsim.spec        -> dist/momtsim_server/
      3. npm install + npm run build     -> dist-electron/  (installeur .exe)

.EXAMPLE
    .\build.ps1
    .\build.ps1 -SkipFrontend    # si frontend/dist/ est deja a jour
    .\build.ps1 -SkipPyInstaller # si dist/momtsim_server/ est deja a jour
#>
param(
    [switch]$SkipFrontend,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Write-Step($label) {
    Write-Host ''
    Write-Host '=======================================' -ForegroundColor DarkBlue
    Write-Host "  $label" -ForegroundColor Cyan
    Write-Host '=======================================' -ForegroundColor DarkBlue
}

function Assert-Command($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "'$cmd' introuvable. Veuillez l'installer et l'ajouter au PATH."
        exit 1
    }
}

# -- Prerequis -
Assert-Command 'node'
Assert-Command 'npm'
Assert-Command 'python'
Assert-Command 'pyinstaller'

# -- 1. Build frontend React --
if (-not $SkipFrontend) {
    Write-Step '1/3 -- Build frontend React (Vite)'
    Push-Location (Join-Path $Root 'frontend')
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Error 'npm run build a echoue.'; exit 1 }
    Pop-Location
    Write-Host '  OK frontend/dist/ genere' -ForegroundColor Green
} else {
    Write-Host '  (frontend skippe)' -ForegroundColor Yellow
}

# -- 2. Bundle backend Python (PyInstaller) --
if (-not $SkipPyInstaller) {
    Write-Step '2/3 -- Bundle backend Python (PyInstaller)'
    Push-Location $Root
    pyinstaller momtsim.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { Write-Error 'PyInstaller a echoue.'; exit 1 }
    Pop-Location
    Write-Host '  OK dist/momtsim_server/ genere' -ForegroundColor Green
} else {
    Write-Host '  (PyInstaller skippe)' -ForegroundColor Yellow
}

# Verifier que le dossier PyInstaller existe
$BackendDir = Join-Path $Root 'dist\momtsim_server'
if (-not (Test-Path $BackendDir)) {
    Write-Error 'dist\momtsim_server\ introuvable. Relancez sans -SkipPyInstaller.'
    exit 1
}

# -- 3. Build Electron + installeur NSIS -
Write-Step '3/3 -- Build Electron + installeur NSIS'
Push-Location (Join-Path $Root 'electron')
npm install
if ($LASTEXITCODE -ne 0) { Write-Error 'npm install (electron) a echoue.'; exit 1 }
npm run build
if ($LASTEXITCODE -ne 0) { Write-Error 'electron-builder a echoue.'; exit 1 }
Pop-Location

# -- Resultat --
Write-Host ''
Write-Host '=======================================' -ForegroundColor DarkGreen
Write-Host '  BUILD TERMINE' -ForegroundColor Green
Write-Host '=======================================' -ForegroundColor DarkGreen
$installer = Get-ChildItem (Join-Path $Root 'dist-electron\*.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installer) {
    Write-Host ('  Installeur : ' + $installer.FullName) -ForegroundColor White
    Write-Host ('  Taille     : {0:N0} Mo' -f ($installer.Length / 1MB)) -ForegroundColor White
} else {
    Write-Host '  Installeur : dist-electron\' -ForegroundColor White
}
Write-Host ''
