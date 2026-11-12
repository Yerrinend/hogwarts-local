@echo off
cd /d "%~dp0"
python -m pip install pyinstaller
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name HogwartsLocal --add-data "web;web" --add-data "starter;starter" launch.py
pause
