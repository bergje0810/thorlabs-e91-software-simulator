@echo off
title Thorlabs E91 QKD Simulator
cd /d "%~dp0"

echo ========================================================
echo   Thorlabs EDU-QOP1 / E91 QKD Simulator
echo ========================================================
echo.
echo Starting server and opening http://localhost:8000 in your browser...
echo Keep this window open while using the simulator.
echo Press Ctrl+C to stop the server.
echo.

start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:8000'"

if exist .\.venv\Scripts\python.exe (
    .\.venv\Scripts\python.exe server.py
) else (
    python server.py
)

if errorlevel 1 (
    echo.
    echo Server stopped with error.
    pause
)
