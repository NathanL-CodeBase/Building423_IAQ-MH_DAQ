@echo off
REM MH DAQ dashboard for a remote read-only machine (desktop, AppleSeed).
REM Reads the Mission copies of the daily files, snapshot, and heartbeat, using
REM the paths in this machine's daq_local.json. Open http://127.0.0.1:8000.
REM
REM Conda is looked up at %USERPROFILE%\miniforge3, then at
REM %LOCALAPPDATA%\miniforge3 (the per-user installer default). If it lives
REM elsewhere, set MH_DAQ_CONDA_PATH to the install folder before running this.

if defined MH_DAQ_CONDA_PATH (
    set "CONDA_PATH=%MH_DAQ_CONDA_PATH%"
) else if exist "%USERPROFILE%\miniforge3\Scripts\activate.bat" (
    set "CONDA_PATH=%USERPROFILE%\miniforge3"
) else (
    set "CONDA_PATH=%LOCALAPPDATA%\miniforge3"
)
if not exist "%CONDA_PATH%\Scripts\activate.bat" (
    echo Conda not found at %CONDA_PATH%.
    echo Checked MH_DAQ_CONDA_PATH, %USERPROFILE%\miniforge3, and %LOCALAPPDATA%\miniforge3.
    echo Set MH_DAQ_CONDA_PATH to the conda install folder.
    pause
    exit /b 1
)

call "%CONDA_PATH%\Scripts\activate.bat" mh_daq_web
REM The repo root is this file's folder, so no machine path is written here.
cd /d "%~dp0"
set MH_DAQ_SOURCE=mission
REM Open the default browser once the server has had time to start. uvicorn
REM blocks this window, so the open runs in a separate hidden process first.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 8; Start-Process 'http://127.0.0.1:8000'"
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
pause
