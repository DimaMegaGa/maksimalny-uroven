@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python backend\manage_ministry.py create --interactive
if errorlevel 1 pause
