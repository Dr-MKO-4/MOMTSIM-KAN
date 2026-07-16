<#
.SYNOPSIS
    Build MoMTSim en application Electron + NSIS installer (Windows x64).

.DESCRIPTION
    Étapes :
      1. npm run build  dans frontend/   → frontend/dist/
      2. pyinstaller momtsim.spec        → dist/momtsim_server/
      3. npm install + npm run build     → dist-electron/  (installeur .exe)

.EXAMPLE
    .\build.ps1
    .\build.ps1 -SkipFrontend   # si frontend/dist/ est déjà à jour
    .\build.ps1 -SkipPyInstaller # si dist/momtsim_server/ est déjà à jour
#>
param(
    [switch]$SkipFrontend,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Step($label) {
    Write-Host ""
    Write-Host "═══════════════════════════════════════" -ForegroundColor DarkBlue
    Write-Host "  $label" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════" -ForegroundColor DarkBlue
}

function Check-Cmd($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "'$cmd' introuvable. Veuillez l'installer et l'ajouter au PATH."
        exit 1
    }
}

# ── Prérequis ─────────────────────────────────────────────────────────────────
Check-Cmd "node"
Check-Cmd "npm"
Check-Cmd "python"
Check-Cmd "pyinstaller"

# ── 1. Build frontend React ───────────────────────────────────────────────────
if (-not $SkipFrontend) {
    Step "1/3 — Build frontend React (Vite)"
    Push-Location "$Root\frontend"
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Error "npm run build a échoué."; exit 1 }
    Pop-Location
    Write-Host "  ✓ frontend/dist/ généré" -ForegroundColor Green
} else {
    Write-Host "  (frontend skippé)" -ForegroundColor Yellow
}

# ── 2. Bundle backend Python (PyInstaller) ────────────────────────────────────
if (-not $SkipPyInstaller) {
    Step "2/3 — Bundle backend Python (PyInstaller)"
    Push-Location $Root
    pyinstaller momtsim.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller a échoué."; exit 1 }
    Pop-Location
    Write-Host "  ✓ dist/momtsim_server/ généré" -ForegroundColor Green
} else {
    Write-Host "  (PyInstaller skippé)" -ForegroundColor Yellow
}

# Vérifier que le dossier PyInstaller existe
$BackendDir = "$Root\dist\momtsim_server"
if (-not (Test-Path $BackendDir)) {
    Write-Error "dist\momtsim_server\ introuvable. Relancez sans -SkipPyInstaller."
    exit 1
}

# ── 3. Build Electron + installeur NSIS ──────────────────────────────────────
Step "3/3 — Build Electron + installeur NSIS"
Push-Location "$Root\electron"
npm install
if ($LASTEXITCODE -ne 0) { Write-Error "npm install (electron) a échoué."; exit 1 }
npm run build
if ($LASTEXITCODE -ne 0) { Write-Error "electron-builder a échoué."; exit 1 }
Pop-Location

# ── Résultat ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor DarkGreen
Write-Host "  BUILD TERMINÉ" -ForegroundColor Green
Write-Host "═══════════════════════════════════════" -ForegroundColor DarkGreen
$installer = Get-ChildItem "$Root\dist-electron\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installer) {
    Write-Host "  Installeur : $($installer.FullName)" -ForegroundColor White
    Write-Host ("  Taille     : {0:N0} Mo" -f ($installer.Length / 1MB)) -ForegroundColor White
} else {
    Write-Host "  Installeur : dist-electron\" -ForegroundColor White
}
Write-Host ""
