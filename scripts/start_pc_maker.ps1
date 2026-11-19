# Start the HookHouse PC video maker hidden (no window), unless it is already running.
$root = Split-Path -Parent $PSScriptRoot
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*cloud helper --videos-only*' }
if ($running) { "PC video maker already running (pid $($running.ProcessId -join ','))"; exit 0 }
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$root\scripts\pc_maker.cmd`"" -WorkingDirectory $root -WindowStyle Hidden
"PC video maker started (hidden). Log: $root\data\logs\pc_maker.log"
