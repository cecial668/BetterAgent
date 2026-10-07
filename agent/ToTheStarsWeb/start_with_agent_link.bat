@echo off
cd /d "%~dp0"
set "BA=%~dp0..\..\..\..\BetterAgent-main\BetterAgent-main\BetterAgent-main"
for /f "usebackq tokens=1,* delims==" %%a in ("%BA%\.env") do if /i "%%a"=="WEBGATEWAY_TOKEN" set "AGENT_WS_TOKEN=%%b"
set "AGENT_WS_URL=ws://127.0.0.1:8080/ws"
set "AGENT_CHAT_ID=1001"
"%~dp0.venv\Scripts\python.exe" -u main.py
