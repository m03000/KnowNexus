@echo off
setlocal
set "PERSONAL_AGENT_PROJECT_ROOT=%~dp0"
set "PACKAGED_EXE=%~dp0frontend\release\win-unpacked\KnowNexus.exe"
if exist "%PACKAGED_EXE%" (
  start "" "%PACKAGED_EXE%"
  exit /b 0
)
cd /d "%~dp0frontend"
call npm run desktop
if errorlevel 1 pause
