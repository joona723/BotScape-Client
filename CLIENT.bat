@echo off
rem Opens the Bot Scape client: RuneLite (for the server's revision 233) with the Bot Scape plugin.
rem The first time, it downloads RuneLite from RuneLite's own servers and patches it for Bot Scape.
rem Usage: CLIENT.bat [main-character] [log-in-as] [server-address]
set "ROOT=%~dp0"
set "MAIN=%~1"
set "LOGIN=%~2"
set "SERVER=%~3"
if "%SERVER%"=="" set "SERVER=127.0.0.1"
set "JAVA=%ROOT%runtime\jre\bin\javaw.exe"
if not exist "%JAVA%" set "JAVA=javaw"
set "PY=%ROOT%runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%ROOT%tools\runelite\lib\botscape-injected-anyhost-client.jar" (
    "%PY%" "%ROOT%launcher\fetch_runelite.py"
)

cd /d "%ROOT%"
start "" "%JAVA%" -XX:+DisableAttachMechanism -Xmx768m -Xss2m -XX:CompileThreshold=1500 ^
    "-Duser.home=%ROOT%.botscape-client" "-Dbotscape.root=%ROOT%." "-Dbotscape.main=%MAIN%" "-Dbotscape.login=%LOGIN%" ^
    "-Dbotscape.gateway=http://%SERVER%:7780" ^
    -cp "%ROOT%tools\runelite\lib\*" net.runelite.client.RuneLite ^
    --jav_config=http://%SERVER%:8080/jav_config.ws
