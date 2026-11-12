@echo off
cd /d "%~dp0"
start "" "http://127.0.0.1:8765/?mode=personal"
python server.py
pause
