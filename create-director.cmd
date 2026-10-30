@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python backend\manage_access.py create-director --interactive
if errorlevel 1 pause
