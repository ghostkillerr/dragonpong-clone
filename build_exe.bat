@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name DragonPongClone --add-data "assets/mit-kemar-compact.zip;assets" --distpath dist --workpath build run_offline.py
if errorlevel 1 pause
