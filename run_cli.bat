@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" steam_syncer.py %*
pause
