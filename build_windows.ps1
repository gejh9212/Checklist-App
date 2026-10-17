$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows executable on Windows.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name ChecklistApp --collect-all keyring --collect-all supabase --collect-all supabase_auth --collect-all realtime --collect-all tzdata windows_entry.py
if ($LASTEXITCODE -ne 0) { throw 'The build failed. Read the error above; your checklist database was not changed.' }
Write-Host 'Created dist\ChecklistApp.exe. User data remains in Local AppData.'
