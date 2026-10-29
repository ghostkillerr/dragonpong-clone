@echo off
cd /d "%~dp0"
if not defined DRAGONPONG_CLONE_HOST set "DRAGONPONG_CLONE_HOST=ekransizoyuncular.gen.tr"
if exist "%~dp0DragonPongClone.exe" (
  start "" "%~dp0DragonPongClone.exe"
  exit /b
)
python run_offline.py
if errorlevel 1 pause
