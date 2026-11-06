@echo off
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0portable-launcher.py"
if errorlevel 1 (
    echo.
    echo Omnis stopped with an error. Read the message above before trying again.
    pause
)
