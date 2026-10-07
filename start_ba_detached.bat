@echo off
cd /d "%~dp0"
start "BetterAgent" "%~dp0.venv\Scripts\python.exe" -u runner.py
