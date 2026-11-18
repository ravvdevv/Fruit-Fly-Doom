@echo off
setlocal
cd /d "%~dp0"

set "ENGINE=%~dp0gzdoom-4-14-2-windows\gzdoom.exe"
set "IWAD=%~dp0freedoom-0.13.0\freedoom1.wad"

if not exist "%ENGINE%" (
  echo [ERROR] GZDoom was not found:
  echo   %ENGINE%
  echo.
  echo Download the Windows build from:
  echo https://github.com/ZDoom/gzdoom/releases
  echo Extract gzdoom.exe and its required files into the runtime folder.
  pause
  exit /b 1
)

if not exist "%IWAD%" (
  echo [ERROR] Freedoom Phase 1 was not found:
  echo   %IWAD%
  echo.
  echo Download Freedoom Phase 1+2 from:
  echo https://freedoom.github.io/download.html
  echo Extract freedoom1.wad into the freedoom folder.
  pause
  exit /b 1
)

start "" "%ENGINE%" -iwad "%IWAD%" +map E1M1
endlocal
