@echo off
setlocal
cd /d "%~dp0"

set "FLYSCROLL_PY=D:\Experimental-projects\Fucking-fruitfly\Fruitfly-Doomscroller\.venv\Scripts\python.exe"

if not exist "%FLYSCROLL_PY%" (
  echo [ERROR] FlyScroll Python environment was not found:
  echo   %FLYSCROLL_PY%
  pause
  exit /b 1
)

echo [test] Make sure Freedoom is open at an active level, not a menu.
echo [test] The controller will hold Up Arrow for 2.5 seconds, then compare frames.
"%FLYSCROLL_PY%" -u "%~dp0connectome_doom.py" --input-test
echo.
echo [test] Finished with exit code %ERRORLEVEL%.
pause
endlocal
