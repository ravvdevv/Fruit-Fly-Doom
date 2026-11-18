@echo off
setlocal
cd /d "%~dp0"

if not defined FLYSCROLL_ROOT set "FLYSCROLL_ROOT=%~dp0..\Fruitfly-Doomscroller"
set "FLYSCROLL_PY=%FLYSCROLL_ROOT%\.venv\Scripts\python.exe"
set "ENGINE=%~dp0gzdoom-4-14-2-windows\gzdoom.exe"
set "IWAD=%~dp0freedoom-0.13.0\freedoom1.wad"

if not exist "%FLYSCROLL_PY%" (
  echo [ERROR] FlyScroll Python environment was not found:
  echo   %FLYSCROLL_PY%
  echo Set FLYSCROLL_ROOT to the FlyScroll checkout.
  pause
  exit /b 1
)

if not exist "%ENGINE%" (
  echo [ERROR] GZDoom is missing:
  echo   %ENGINE%
  pause
  exit /b 1
)

if not exist "%IWAD%" (
  echo [ERROR] Freedoom Phase 1 WAD is missing:
  echo   %IWAD%
  pause
  exit /b 1
)

echo [game] Launching GZDoom with the Freedoom IWAD...
start "Freedoom Connectome" "%ENGINE%" -iwad "%IWAD%" +map E1M1
echo [game] Waiting for the game window...
timeout /t 8 /nobreak >nul

echo [brain] Starting the connectome controller...
"%FLYSCROLL_PY%" -u "%~dp0connectome_doom.py" --flyscroll-root "%FLYSCROLL_ROOT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [brain] Controller exited normally.
) else (
  echo [ERROR] Controller exited with code %EXIT_CODE%.
)
echo [brain] Press any key to close this window.
pause >nul
endlocal
