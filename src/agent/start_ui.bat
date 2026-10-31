@echo off
cd /d "%~dp0"
py -3.13 -B scripts\start_ui.py %*
if errorlevel 1 pause
