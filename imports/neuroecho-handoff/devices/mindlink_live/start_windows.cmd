@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run setup_windows.cmd first.
 pause
 exit /b 1
)
.venv\Scripts\python.exe app.py --list-ports
set /p EEG_PORT=Enter EEG port from list (for example COM3): 
if not defined EEG_PORT exit /b 1
.venv\Scripts\python.exe app.py --port "%EEG_PORT%"
pause
