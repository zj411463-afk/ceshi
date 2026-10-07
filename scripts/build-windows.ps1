$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this build on Windows 10/11 x64.' }
& "$PSScriptRoot\setup.ps1" -Dev
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name XianyuMonitor --collect-all playwright main.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
Copy-Item README.md dist\XianyuMonitor\README.md
Compress-Archive -Path dist\XianyuMonitor -DestinationPath dist\XianyuMonitor-Windows.zip -Force
Write-Host 'Built: dist\XianyuMonitor\XianyuMonitor.exe'
Write-Host 'Share the entire dist\XianyuMonitor-Windows.zip archive.'
