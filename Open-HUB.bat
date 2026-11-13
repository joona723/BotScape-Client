@echo off
rem Opens the Bot Scape hub (run scripts, see your group, bank and map).
rem In an installed copy it goes through BotScape.exe, which installs any update first; a development folder
rem (it has SERVER.bat) opens LAUNCHER.pyw directly, as does a copy that couldn't get BotScape.exe.
set "ROOT=%~dp0"
cd /d "%ROOT%"
rem A git clone of the GitHub repo updates from GitHub (its tracked files made to match main; bots/, runtime/ and
rem settings are untracked and kept), never through BotScape.exe (user-requested 2026-11-13); the hub then does the
rem same by itself while it runs.
if exist "%ROOT%.git" if not exist "%ROOT%SERVER.bat" (
    where git >nul 2>nul && git -C "%ROOT%." fetch -q origin main && git -C "%ROOT%." reset -q --hard origin/main
    if exist "%ROOT%runtime\python\pythonw.exe" goto hub
    where pythonw >nul 2>nul && goto hub
    rem No Python on this PC: BotScape.exe installs the bundled one (once), then starts the hub.
)
rem A copy without BotScape.exe (a GitHub ZIP, or a clone on a PC without Python): fetch it from zazuosu.com, so it
rem installs and updates like the download does.
if not exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" (
    echo Getting the Bot Scape updater from zazuosu.com...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; Invoke-WebRequest -UseBasicParsing 'https://zazuosu.com/downloads/botscape/BotScape.exe' -OutFile '%ROOT%BotScape.exe.part'; Move-Item -Force '%ROOT%BotScape.exe.part' '%ROOT%BotScape.exe' } catch { exit 1 }"
)
if exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" if not exist "%ROOT%.git" (
    start "" "%ROOT%BotScape.exe" %*
    exit /b
)
if exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" if not exist "%ROOT%runtime\python\pythonw.exe" (
    start "" "%ROOT%BotScape.exe" %*
    exit /b
)
:hub
set "PYW=%ROOT%runtime\python\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%ROOT%LAUNCHER.pyw" %*
