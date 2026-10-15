@echo off
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" steam_syncer_gui.py %*
