@echo off
rem Stops everything Bot Scape runs from THIS folder: the hub, its window, the game clients and any running scripts.
rem User-requested (2026-11-12): deleting a Bot Scape folder said "in use" while something from it still ran.
rem Only programs started from this folder stop (a Bot Scape in another folder keeps running); a game server never.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo Stopping everything Bot Scape runs from:
echo   %ROOT%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = $env:ROOT; $names = 'python.exe','pythonw.exe','java.exe','javaw.exe','msedge.exe','powershell.exe','BotScape.exe';" ^
  "$found = Get-CimInstance Win32_Process | Where-Object { $names -contains $_.Name -and $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine -notlike '*GameServerKt*' -and $_.CommandLine -notlike '*config_server.py*' -and $_.CommandLine -notlike '*STOP-ALL.bat*' };" ^
  "$labels = @{ 'pythonw.exe' = 'hub or script'; 'python.exe' = 'script'; 'javaw.exe' = 'game client'; 'java.exe' = 'game client'; 'msedge.exe' = 'hub window'; 'powershell.exe' = 'helper'; 'BotScape.exe' = 'BotScape' };" ^
  "$stopped = 0; foreach ($p in $found) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $stopped++; Write-Host ('  stopped ' + $labels[$p.Name] + ' (' + $p.Name + ', ' + $p.ProcessId + ')') } catch { } };" ^
  "if ($stopped -eq 0) { Write-Host '  Nothing from this folder was running.' } else { Write-Host ''; Write-Host ('Stopped ' + $stopped + '. The folder can be deleted now.') }"
echo.
pause
