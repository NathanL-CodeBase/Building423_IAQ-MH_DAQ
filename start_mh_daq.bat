@echo off
REM MH DAQ autostart. Launched by Splinterware System Scheduler.
REM Edit CONDA_PATH and REPO_PATH for the DAQ PC.

set CONDA_PATH=C:\Users\iaq\AppData\Local\miniforge3
set REPO_PATH=C:\Users\iaq\Documents\nist_mh-daq-rebuild

call "%CONDA_PATH%\Scripts\activate.bat" iaqmh_daq
cd /d "%REPO_PATH%"
python run_daq.py --hardware