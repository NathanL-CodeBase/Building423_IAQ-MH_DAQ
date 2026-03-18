@echo off
REM =========================================================================
REM MH IAQ DAQ Backup - Task Scheduler Wrapper
REM =========================================================================
REM This batch file ensures the conda environment is properly activated
REM and captures any output/errors to a local log file.
REM
REM For Task Scheduler:
REM   Program/script: C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\run_backup.bat
REM   Start in:       C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts
REM =========================================================================

REM Set the script locations (modify these paths as needed)
set SCRIPT_PATH=C:\Users\iaq\Building423_IAQ-MH_DAQ\src\mh_daq_file_backup.py
set SCRIPT_PATH2=C:\Users\iaq\Building423_IAQ-MH_DAQ\src\epa_shower_file_backup.py
set SCRIPT_PATH3=C:\Users\iaq\Building423_IAQ-MH_DAQ\src\ecobee_thermostat_backup.py
set LOG_PATH=C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log

REM Log start time
echo =========================================== >> "%LOG_PATH%"
echo Backup started: %date% %time% >> "%LOG_PATH%"
echo =========================================== >> "%LOG_PATH%"

REM Activate conda base environment
call C:\Users\iaq\AppData\Local\miniforge3\Scripts\activate.bat >> "%LOG_PATH%" 2>&1

REM Run the first Python script (MH DAQ indoor + weather station backup)
python "%SCRIPT_PATH%" >> "%LOG_PATH%" 2>&1

REM Run the second Python script (EPA shower backup)
python "%SCRIPT_PATH2%" >> "%LOG_PATH%" 2>&1

REM Run the third Python script (Ecobee thermostat data backup)
python "%SCRIPT_PATH3%" >> "%LOG_PATH%" 2>&1

REM Log completion
echo Backup finished: %date% %time% >> "%LOG_PATH%"
echo. >> "%LOG_PATH%"
