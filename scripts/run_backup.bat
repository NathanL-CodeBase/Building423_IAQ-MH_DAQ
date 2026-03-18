@echo off
REM =========================================================================
REM MH IAQ DAQ Backup - Task Scheduler Wrapper
REM =========================================================================
REM This batch file ensures the conda environment is properly activated
REM and captures any output/errors to a local log file.
REM
REM For Task Scheduler:
REM   Program/script: <repo_path>\scripts\run_backup.bat
REM   Start in:       <repo_path>\scripts
REM =========================================================================

REM =========================================================================
REM CONFIGURATION — Update CONDA_ACTIVATE for your installation
REM   Run: conda info --base    to find your conda base directory.
REM   Then set CONDA_ACTIVATE to: <your_conda_base>\Scripts\activate.bat
REM =========================================================================
set CONDA_ACTIVATE=<conda_base>\Scripts\activate.bat

REM Script and log paths are resolved relative to this batch file's location.
REM No edits needed here unless the repo structure changes.
set SCRIPT_PATH=%~dp0..\src\mh_daq_file_backup.py
set SCRIPT_PATH2=%~dp0..\src\epa_shower_file_backup.py
set SCRIPT_PATH3=%~dp0..\src\ecobee_thermostat_backup.py
set LOG_PATH=%~dp0batch_output.log

REM Log start time
echo =========================================== >> "%LOG_PATH%"
echo Backup started: %date% %time% >> "%LOG_PATH%"
echo =========================================== >> "%LOG_PATH%"

REM Activate conda base environment
call "%CONDA_ACTIVATE%" >> "%LOG_PATH%" 2>&1

REM Run the first Python script (MH DAQ indoor + weather station backup)
python "%SCRIPT_PATH%" >> "%LOG_PATH%" 2>&1

REM Run the second Python script (EPA shower backup)
python "%SCRIPT_PATH2%" >> "%LOG_PATH%" 2>&1

REM Run the third Python script (Ecobee thermostat data backup)
python "%SCRIPT_PATH3%" >> "%LOG_PATH%" 2>&1

REM Log completion
echo Backup finished: %date% %time% >> "%LOG_PATH%"
echo. >> "%LOG_PATH%"
