@echo off
rem Opens the Bot Scape hub (run scripts, see your group, bank and map).
rem In an installed copy it goes through BotScape.exe, which installs any update first; a development folder
rem (it has SERVER.bat) opens LAUNCHER.pyw directly, as does a copy that couldn't get BotScape.exe.
set "ROOT=%~dp0"
cd /d "%ROOT%"
rem A copy from GitHub has no BotScape.exe (no binaries there): fetch it from zazuosu.com, so it installs and
rem updates like the download does (user-requested 2026-11-13: the updater window, and updates, for GitHub copies).
if not exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" (
    echo Getting the Bot Scape updater from zazuosu.com...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; Invoke-WebRequest -UseBasicParsing 'https://zazuosu.com/downloads/botscape/BotScape.exe' -OutFile '%ROOT%BotScape.exe.part'; Move-Item -Force '%ROOT%BotScape.exe.part' '%ROOT%BotScape.exe' } catch { exit 1 }"
)
if exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" (
    start "" "%ROOT%BotScape.exe" %*
    exit /b
)
set "PYW=%ROOT%runtime\python\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%ROOT%LAUNCHER.pyw" %*
