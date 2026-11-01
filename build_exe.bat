@echo off
cd /d "%~dp0"
set "DRAGONPONG_BUILD_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "DRAGONPONG_BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
"%DRAGONPONG_BUILD_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
"%DRAGONPONG_BUILD_PYTHON%" -m pip install pyinstaller
if errorlevel 1 exit /b 1
"%DRAGONPONG_BUILD_PYTHON%" -m PyInstaller --noconfirm --onefile --windowed --name DragonPongClone --add-data "assets/mit-kemar-compact.zip;assets" --add-data "licenses;licenses" --add-data "THIRD_PARTY_NOTICES.md;." --distpath dist --workpath build run_offline.py
if errorlevel 1 pause
