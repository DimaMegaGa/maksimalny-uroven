@echo off
cd /d "%~dp0"
python start.py --site ministry
if errorlevel 1 pause
