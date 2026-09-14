@echo off
setlocal
set "PERSONAL_AGENT_PROJECT_ROOT=%~dp0"
cd /d "%~dp0frontend"
call npm run desktop
if errorlevel 1 pause
