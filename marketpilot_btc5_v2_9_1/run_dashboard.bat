@echo off
cd /d "%~dp0"
set PORT=8765
py webapp.py
pause
