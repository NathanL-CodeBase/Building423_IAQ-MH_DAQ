@echo off
REM =========================================================================
REM Weather Station DAQ Generator - Continuous Process Wrapper
REM =========================================================================
REM Unlike run_backup.bat, this script runs continuously (it does not exit)
REM and should be started once per boot/logon, not run via the nightly
REM Task Scheduler backup cycle. Use Task Scheduler's "At log on" or "At
REM startup" trigger, or leave the window open on the DAQ computer.
REM
REM The Python script owns its own rotating log (weather_daq.log, next to
REM the script) and also prints to the console, so this wrapper does NOT
REM redirect the Python call — run it directly to watch it live, or tail
REM weather_daq.log. This file only records wrapper-level start/stop/
REM activation events, in weather_daq_wrapper.log.
REM
REM For Task Scheduler:
REM   Program/script: <repo_path>\scripts\run_weather_station_daq.bat
REM   Start in:       <repo_path>\scripts
REM =========================================================================

REM Script, config, and log paths are resolved relative to this batch
REM file's location. No edits needed here unless the repo structure changes.
set REPO_ROOT=%~dp0..
set DATA_CONFIG=%REPO_ROOT%\data_config.json
set SCRIPT_PATH=%~dp0generate_weather_station_daq.py
set WRAPPER_LOG_PATH=%~dp0weather_daq_wrapper.log

REM Log start time
echo =========================================== >> "%WRAPPER_LOG_PATH%"
echo Weather station DAQ generator started: %date% %time% >> "%WRAPPER_LOG_PATH%"
echo =========================================== >> "%WRAPPER_LOG_PATH%"

REM =========================================================================
REM Conda settings come from data_config.json's "conda" key, NOT this file —
REM that keeps machine-specific paths out of a tracked batch file, so a git
REM pull never conflicts with a hand edit here. Set conda.activate_path and
REM conda.env_name in data_config.json (see data_config.template.json).
REM =========================================================================
if not exist "%DATA_CONFIG%" (
    echo ERROR: data_config.json not found at %DATA_CONFIG%. Create it from data_config.template.json. >> "%WRAPPER_LOG_PATH%"
    exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%DATA_CONFIG%' | ConvertFrom-Json).conda.activate_path"`) do set CONDA_ACTIVATE=%%A
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%DATA_CONFIG%' | ConvertFrom-Json).conda.env_name"`) do set CONDA_ENV_NAME=%%A

if "%CONDA_ACTIVATE%"=="" (
    echo ERROR: conda.activate_path not set in data_config.json. >> "%WRAPPER_LOG_PATH%"
    exit /b 1
)

REM Activate the dedicated conda environment (see environment.yaml)
call "%CONDA_ACTIVATE%" %CONDA_ENV_NAME% >> "%WRAPPER_LOG_PATH%" 2>&1

REM Run the generator. This call does not return until the process is
REM stopped (Ctrl+C or the window is closed) or it hits an unrecoverable
REM error. Output is NOT redirected here — see the note above.
python "%SCRIPT_PATH%"

echo Weather station DAQ generator exited: %date% %time% >> "%WRAPPER_LOG_PATH%"
echo. >> "%WRAPPER_LOG_PATH%"
