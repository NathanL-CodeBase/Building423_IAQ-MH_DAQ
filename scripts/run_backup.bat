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

REM Script, config, and log paths are resolved relative to this batch
REM file's location. No edits needed here unless the repo structure changes.
set REPO_ROOT=%~dp0..
set DATA_CONFIG=%REPO_ROOT%\data_config.json
set SCRIPT_PATH=%REPO_ROOT%\src\mh_daq_file_backup.py
set SCRIPT_PATH3=%REPO_ROOT%\src\wui_smoke_file_backup.py
set LOG_PATH=%~dp0batch_output.log

REM Log start time
echo =========================================== >> "%LOG_PATH%"
echo Backup started: %date% %time% >> "%LOG_PATH%"
echo =========================================== >> "%LOG_PATH%"

REM =========================================================================
REM Conda settings come from data_config.json's "conda" key, NOT this file —
REM that keeps machine-specific paths out of a tracked batch file, so a git
REM pull never conflicts with a hand edit here. Set conda.activate_path and
REM conda.env_name in data_config.json (see data_config.template.json).
REM =========================================================================
if not exist "%DATA_CONFIG%" (
    echo ERROR: data_config.json not found at %DATA_CONFIG%. Create it from data_config.template.json. >> "%LOG_PATH%"
    exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%DATA_CONFIG%' | ConvertFrom-Json).conda.activate_path"`) do set CONDA_ACTIVATE=%%A
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%DATA_CONFIG%' | ConvertFrom-Json).conda.env_name"`) do set CONDA_ENV_NAME=%%A

if "%CONDA_ACTIVATE%"=="" (
    echo ERROR: conda.activate_path not set in data_config.json. >> "%LOG_PATH%"
    exit /b 1
)

REM Activate the shared conda environment
call "%CONDA_ACTIVATE%" %CONDA_ENV_NAME% >> "%LOG_PATH%" 2>&1

REM Run the first Python script (MH DAQ indoor + weather station backup)
python "%SCRIPT_PATH%" >> "%LOG_PATH%" 2>&1

REM Run the WUI Smoke campaign backup (deployment date onward, Elwood share)
python "%SCRIPT_PATH3%" >> "%LOG_PATH%" 2>&1

REM Log completion
echo Backup finished: %date% %time% >> "%LOG_PATH%"
echo. >> "%LOG_PATH%"
