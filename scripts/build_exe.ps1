# Build a single-file wavc.exe with PyInstaller.
# Usage (from the repo root, with your venv active):  .\scripts\build_exe.ps1
$ErrorActionPreference = "Stop"

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed (exit code $LASTEXITCODE) - see the messages above."
    }
}

Invoke-Step "Upgrade pip" { python -m pip install --upgrade pip }
Invoke-Step "Install wavc-viz + PyInstaller" { python -m pip install -e ".[build]" }
Invoke-Step "Build dist\wavc.exe" {
    python -m PyInstaller --noconfirm --clean --onefile `
        --name wavc `
        --paths src `
        --collect-all pyaudiowpatch `
        --hidden-import _portaudiowpatch `
        scripts/entry.py
}

if (-not (Test-Path "dist\wavc.exe")) {
    throw "dist\wavc.exe was not created - read the PyInstaller output above."
}
$size = [math]::Round((Get-Item "dist\wavc.exe").Length / 1MB, 1)
Write-Host "`nBuilt: dist\wavc.exe ($size MB)" -ForegroundColor Green
& .\dist\wavc.exe --version