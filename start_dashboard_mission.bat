@echo off
REM MH DAQ dashboard for a remote read-only machine (desktop, AppleSeed).
REM Reads the Mission copies of the daily files, snapshot, and heartbeat, using
REM the paths in this machine's daq_local.json. Open http://127.0.0.1:8000.
REM
REM Conda is looked up at %USERPROFILE%\miniforge3. If it lives elsewhere, set
REM MH_DAQ_CONDA_PATH to the install folder before running this file.

if defined MH_DAQ_CONDA_PATH (set CONDA_PATH=%MH_DAQ_CONDA_PATH%) else (set CONDA_PATH=%USERPROFILE%\miniforge3)
if not exist "%CONDA_PATH%\Scripts\activate.bat" (
    echo Conda not found at %CONDA_PATH%. Set MH_DAQ_CONDA_PATH to the conda install folder.
    pause
    exit /b 1
)

call "%CONDA_PATH%\Scripts\activate.bat" mh_daq_web
REM The repo root is this file's folder, so no machine path is written here.
cd /d "%~dp0"
set MH_DAQ_SOURCE=mission
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
pause
