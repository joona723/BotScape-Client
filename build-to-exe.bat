@echo off
rem Builds BotScape.exe (the launcher: checks for updates, then opens the hub) from its source in this folder,
rem launcher\stub\Program.cs and launcher\HubWindow.cs, so you can check the exe is made from the code you see here.
rem Needs the .NET SDK (free, 8 or newer): https://dotnet.microsoft.com/download
rem The exe targets .NET Framework 4.8, which is built into Windows 10/11, so running it needs nothing extra.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

where dotnet >nul 2>nul
if errorlevel 1 (
    echo The .NET SDK isn't installed. Get it from https://dotnet.microsoft.com/download and run this again.
    pause
    exit /b 1
)

tasklist /fi "imagename eq BotScape.exe" 2>nul | find /i "BotScape.exe" >nul
if not errorlevel 1 (
    echo BotScape.exe is running: close the hub and the updater first, then run this again.
    pause
    exit /b 1
)

echo Building BotScape.exe...
dotnet build "%ROOT%launcher\stub\BotScape.csproj" -c Release -o "%ROOT%build" -nologo -v quiet
if errorlevel 1 (
    echo The build failed: see the messages above.
    pause
    exit /b 1
)

copy /y "%ROOT%build\BotScape.exe" "%ROOT%BotScape.exe" >nul
copy /y "%ROOT%build\BotScape.exe.config" "%ROOT%BotScape.exe.config" >nul
echo.
echo Done: %ROOT%BotScape.exe
echo (the build's other files are in the build folder)
pause
