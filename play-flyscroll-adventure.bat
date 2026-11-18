@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] ViZDoom virtual environment not found:
  echo   %PYTHON%
  echo Install it with: py -3.14 -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install vizdoom==1.3.2
  pause
  exit /b 1
)

echo [pilot] Starting the FlyScroll Freedoom adventure pilot...
echo [dashboard] Opening http://127.0.0.1:8765/ in your browser...
echo [pilot] Press Ctrl+C in this window to stop.
"%PYTHON%" -u "%~dp0play_flyscroll_adventure.py" --connectome --god-mode --skill 0 %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [pilot] Adventure pilot exited normally.
) else (
  echo [ERROR] Pilot exited with code %EXIT_CODE%.
)
pause
endlocal
