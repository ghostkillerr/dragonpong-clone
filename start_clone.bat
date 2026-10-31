@echo off
cd /d "%~dp0"
if not defined DRAGONPONG_CLONE_HOST set "DRAGONPONG_CLONE_HOST=ekransizoyuncular.gen.tr"
if exist "%~dp0DragonPongClone.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_launcher.ps1"
  if errorlevel 1 pause
  exit /b
)
python run_offline.py
if errorlevel 1 pause
