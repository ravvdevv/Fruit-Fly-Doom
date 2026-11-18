@echo off
REM Run Fruitfly DOOM with Neural Visualization Dashboard
REM This launches: 1) Neural Viz Server, 2) GZDoom, 3) Connectome Pilot

cd /d "%~dp0"

echo.
echo ============================================================
echo  FRUITFLY DOOM + NEURAL VISUALIZATION
echo  MaleCNS Visual Connectome driving DOOM with live dashboard
echo ============================================================
echo.

REM Check requirements
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    pause
    exit /b 1
)

if not exist "freedoom-0.13.0\freedoom1.wad" (
    echo [ERROR] freedoom1.wad not found
    pause
    exit /b 1
)

if not exist "gzdoom-4-14-2-windows\gzdoom.exe" (
    echo [ERROR] GZDoom not found
    pause
    exit /b 1
)

echo [1/3] Starting Neural Visualization Server...
start "Fruitfly Neural Viz" cmd /k "launch-neural-viz.bat"

echo [2/3] Waiting for server to start...
timeout /t 3 /nobreak >nul

echo [3/3] Launching GZDoom + Connectome Pilot...
echo.
echo The pilot will connect to the viz server automatically.
echo Open http://127.0.0.1:8765/viz in your browser to see the live dashboard.
echo.
echo Press Ctrl+C in the pilot window to stop everything.
echo.

REM Launch the connectome pilot (which launches GZDoom internally)
.venv\Scripts\python.exe connectome_doom.py --viz-server http://127.0.0.1:8765 %*

echo.
echo [INFO] Pilot stopped. Don't forget to close the viz server window.
pause