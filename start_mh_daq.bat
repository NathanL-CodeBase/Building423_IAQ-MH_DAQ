@echo off
REM MH DAQ autostart. Launched by Splinterware System Scheduler.
REM Edit CONDA_PATH and REPO_PATH for the DAQ PC.

set CONDA_PATH=C:\Users\iaq\miniforge3
set REPO_PATH=C:\Users\iaq\Documents\building423_iaq-mh_daq

call "%CONDA_PATH%\Scripts\activate.bat" iaqmh_daq
cd /d "%REPO_PATH%"
python run_daq.py --hardware