@echo off
rem Opens the Bot Scape hub (run scripts, see your group, bank and map).
rem In an installed copy it goes through BotScape.exe, which installs any update first; a development folder
rem (it has SERVER.bat, or no BotScape.exe) opens LAUNCHER.pyw directly.
set "ROOT=%~dp0"
cd /d "%ROOT%"
if exist "%ROOT%BotScape.exe" if not exist "%ROOT%SERVER.bat" (
    start "" "%ROOT%BotScape.exe" %*
    exit /b
)
set "PYW=%ROOT%runtime\python\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%ROOT%LAUNCHER.pyw" %*
