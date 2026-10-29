@echo off
cd /d "%~dp0"
python -m dragonpong.server --host 0.0.0.0 --port 8870
if errorlevel 1 pause
