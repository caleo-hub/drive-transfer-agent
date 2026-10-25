@echo off
cd /d "%~dp0"
uv run --locked drive-transfer-agent
if errorlevel 1 pause
