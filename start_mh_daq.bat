@echo off
REM MH DAQ autostart on the DAQ PC. Launched by Splinterware System Scheduler.
REM Starts the acquisition daemon on real hardware. Run it only on the DAQ PC,
REM and only when no other program owns the cDAQ.
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
    exit /b 1
)

call "%CONDA_PATH%\Scripts\activate.bat" iaqmh_daq
REM The repo root is this file's folder, so no machine path is written here.
cd /d "%~dp0"
python run_daq.py --hardware
