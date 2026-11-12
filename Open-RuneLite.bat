@echo off
rem Opens the Bot Scape client: RuneLite (for the server's revision 233) with the Bot Scape plugin.
rem The first time, it downloads RuneLite from RuneLite's own servers and patches it for Bot Scape.
rem Usage: Open-RuneLite.bat [main-character] [log-in-as] [server-address]
rem Anything not given comes from launcher\settings.json (as the hub uses), so double-clicking works too.
set "ROOT=%~dp0"
set "MAIN=%~1"
set "LOGIN=%~2"
set "SERVER=%~3"
set "JAVA=%ROOT%runtime\jre\bin\javaw.exe"
if not exist "%JAVA%" set "JAVA=javaw"
set "PY=%ROOT%runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

if exist "%ROOT%launcher\settings.json" for /f "usebackq tokens=1,* delims==" %%A in (`call "%PY%" -c "import json,sys; s=json.load(open(sys.argv[1],encoding='utf-8')); print('S_MAIN='+str(s.get('main') or '')); print('S_SERVER='+str(s.get('server') or ''))" "%ROOT%launcher\settings.json"`) do set "%%A=%%B"
if "%MAIN%"=="" set "MAIN=%S_MAIN%"
if "%SERVER%"=="" set "SERVER=%S_SERVER%"
rem Same default as the hub: the local server if this PC hosts one, otherwise the public one.
if "%SERVER%"=="" if exist "%ROOT%SERVER.bat" set "SERVER=127.0.0.1"
if "%SERVER%"=="" set "SERVER=botscape.zazuosu.com"

if not exist "%ROOT%tools\runelite\lib\botscape-injected-anyhost-client.jar" (
    "%PY%" "%ROOT%launcher\fetch_runelite.py"
)
rem A copy cloned from the BotScape-Client repository has the plugin's source only: build it (or download it).
if not exist "%ROOT%tools\runelite\lib\botscape-plugin.jar" if exist "%ROOT%launcher\build_plugin.py" (
    "%PY%" "%ROOT%launcher\build_plugin.py"
)

cd /d "%ROOT%"
start "" "%JAVA%" -XX:+DisableAttachMechanism -Xmx768m -Xss2m -XX:CompileThreshold=1500 ^
    "-Duser.home=%ROOT%.botscape-client" "-Dbotscape.root=%ROOT%." "-Dbotscape.main=%MAIN%" "-Dbotscape.login=%LOGIN%" ^
    "-Dbotscape.gateway=http://%SERVER%:7780" ^
    -cp "%ROOT%tools\runelite\lib\*" net.runelite.client.RuneLite ^
    --jav_config=http://%SERVER%:8080/jav_config.ws
