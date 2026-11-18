@echo off
REM Launch Neural Visualization Server for Fruitfly DOOM
REM This starts the WebSocket server that receives neural telemetry and serves the dashboard

cd /d "%~dp0"

echo.
echo ============================================================
echo  FRUITFLY NEURAL VISUALIZATION SERVER
echo  MaleCNS Visual Connectome Dashboard
echo ============================================================
echo.

REM Check if Python venv exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo Please create a venv and install requirements:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install fastapi uvicorn websockets numpy pillow
    pause
    exit /b 1
)

echo [INFO] Starting neural visualization server on http://127.0.0.1:8765
echo [INFO] Open http://127.0.0.1:8765/viz in your browser to see the dashboard
echo [INFO] Press Ctrl+C to stop
echo.

.venv\Scripts\python.exe neural_viz_server.py --host 127.0.0.1 --port 8765

echo.
echo [INFO] Server stopped.
pause