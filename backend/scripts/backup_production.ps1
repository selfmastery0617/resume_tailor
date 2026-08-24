# Daily backup: production Postgres dump + secrets/corpora snapshot.
# Registered as a scheduled task by the deployment runbook (Phase 7).
#
# No password here on purpose -- pg_dump reads it from
# %APPDATA%\postgresql\pgpass.conf, which lives outside this repo and is
# never committed. Keeping the credential out of a tracked file is the whole
# point; don't reintroduce it here.
#
# Two retention windows, deliberately different: postgres dumps are cheap and
# small, kept 14 days. The secrets snapshot copies the whole Chromium profile
# each run, which adds up fast, so it only keeps 7.

$ErrorActionPreference = "Stop"
$date = Get-Date -Format "yyyy-MM-dd"

& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h localhost -U jobtailor_prod -Fc -f "D:\Backups\postgres\jobtailor_prod_$date.dump" jobtailor_prod

$dest = "D:\Backups\secrets-snapshot\$date"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "D:\Resume Tailor\backend\secrets" -Destination "$dest\secrets" -Recurse -Force
Copy-Item -Path "D:\Resume Tailor\backend\data\corpora" -Destination "$dest\corpora" -Recurse -Force

Get-ChildItem "D:\Backups\postgres\*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
    Remove-Item -Force

Get-ChildItem "D:\Backups\secrets-snapshot" -Directory |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Recurse -Force
