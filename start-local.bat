@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0python\python.exe" (
  echo Omnis bundled Python runtime is missing from "%~dp0python".
  pause
  exit /b 1
)
if not exist "%~dp0launcher.py" (
  echo Omnis launcher is missing from "%~dp0".
  pause
  exit /b 1
)
"%~dp0python\python.exe" "%~dp0launcher.py"
if errorlevel 1 (
  echo Omnis stopped with an error. Read the message above before trying again.
  pause
)
