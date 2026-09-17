@echo off
REM =========================================================================
REM Weather Station DAQ Generator - Continuous Process Wrapper
REM =========================================================================
REM Unlike run_backup.bat, this script runs continuously (it does not exit)
REM and should be started once per boot/logon, not run via the nightly
REM Task Scheduler backup cycle. Use Task Scheduler's "At log on" or "At
REM startup" trigger, or leave the window open on the DAQ computer.
REM
REM For Task Scheduler:
REM   Program/script: <repo_path>\scripts\run_weather_station_daq.bat
REM   Start in:       <repo_path>\scripts
REM =========================================================================

REM =========================================================================
REM CONFIGURATION — Update CONDA_ACTIVATE for your installation
REM   Run: conda info --base    to find your conda base directory.
REM   Then set CONDA_ACTIVATE to: <your_conda_base>\Scripts\activate.bat
REM =========================================================================
set CONDA_ACTIVATE=<conda_base>\Scripts\activate.bat
set CONDA_ENV_NAME=iaqmh_daq

REM Script and log paths are resolved relative to this batch file's location.
REM No edits needed here unless the repo structure changes.
set SCRIPT_PATH=%~dp0generate_weather_station_daq.py
set LOG_PATH=%~dp0weather_daq_output.log

REM Log start time
echo =========================================== >> "%LOG_PATH%"
echo Weather station DAQ generator started: %date% %time% >> "%LOG_PATH%"
echo =========================================== >> "%LOG_PATH%"

REM Activate the dedicated conda environment (see environment.yaml)
call "%CONDA_ACTIVATE%" "%CONDA_ENV_NAME%" >> "%LOG_PATH%" 2>&1

REM Run the generator. This call does not return until the process is
REM stopped (Ctrl+C or the window is closed) or it hits an unrecoverable
REM error.
python "%SCRIPT_PATH%" >> "%LOG_PATH%" 2>&1

echo Weather station DAQ generator exited: %date% %time% >> "%LOG_PATH%"
echo. >> "%LOG_PATH%"
