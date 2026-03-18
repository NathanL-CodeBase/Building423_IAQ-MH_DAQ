# Installation & Quick Start Guide

This guide provides step-by-step instructions for deploying the MH DAQ backup system on the DAQ computer. Follow each step carefully, and refer to the [Troubleshooting Guide](TROUBLESHOOTING.md) if you encounter any issues.

---

## Prerequisites

Before you begin, confirm that:

- You have **administrator access** to the DAQ desktop computer in Building 423
- The machine is on the **NIST network**
- You can reach the **mission network drive** (`\\mission.el.nist.gov\...`)  
  > Test this by opening **File Explorer** and typing `\\mission.el.nist.gov\Programs\energy_netzero\ventilation_iaq\` in the address bar. You should see folders. There should also be a shortcut on the desktop, as using it may resolve issues with accessing the drive through File Explorer.
- You can reach the **elwood network drive** (`\\elwood.nist.gov\...`)  
  > Test this by opening **File Explorer** and typing `\\elwood.nist.gov\732_EL\732\internal\` in the address bar. You should see folders.

If either network drive is not accessible, **stop** and contact eldst on slack before proceeding.

---

## Step 1: Verify Python and Pandas

The backup system requires **Python 3.x** and the **pandas** library. Check if these are already installed on the DAQ computer:

### Check Python Installation

1. Open **Command Prompt** or **PowerShell** on the DAQ computer
2. Type the following command:
   ```
   conda --version
   ```
3. If you see a version number (e.g., `conda 23.5.0`), Python and conda are installed
4. If you see `conda is not recognized...`, contact Nathan Lima or eldst for help

### Check Pandas Installation

1. In the same Command Prompt/PowerShell, type:
   ```
   conda list pandas
   ```
2. If you see `pandas` listed with a version, it is installed
3. If pandas is not listed, install it with:
   ```
   conda install pandas
   ```

---

## Step 2: Clone the Repository

On the **DAQ desktop computer**, clone the repository from GitHub:

1. Open **Command Prompt** or **PowerShell** on the DAQ computer
2. Navigate to the user directory:
   ```
   cd C:\Users\iaq\
   ```
3. Clone the repository:
   ```
   git clone https://github.com/usnistgov/Building423_IAQ-MH_DAQ
   ```
4. This creates: `C:\Users\iaq\Building423_IAQ-MH_DAQ\`

> **Note:** If `git` is not installed, contact your Nathan Lima or eldest support or see the [Troubleshooting Guide](TROUBLESHOOTING.md) for installation instructions.

---

## Step 3: Verify the Repository Structure

After cloning, verify that all files are in place:

1. Open **File Explorer** and navigate to `C:\Users\iaq\Building423_IAQ-MH_DAQ\`
2. You should see:
   ```
   Building423_IAQ-MH_DAQ/
   ├── docs/                    (documentation)
   ├── src/                     (Python scripts)
   ├── scripts/                 (batch files)
   ├── README.md
   ├── LICENSE.md
   ├── CODEMETA.yaml
   └── data_config.template.json  (copy this to data_config.json and edit paths)
   ```
3. The Python backup scripts are in: `C:\Users\iaq\Building423_IAQ-MH_DAQ\src\`
4. The batch file is in: `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\`

---

## Step 4: Verify Python Installation Path

The batch file needs to match your Python installation path. Follow these steps:

1. On the DAQ computer, open **Command Prompt** and type:
   ```
   conda info --base
   ```
   > This shows where conda is installed. You should see something like: `C:\Users\iaq\AppData\Local\miniforge3`

2. The paths in `run_backup.bat` should already be correct and point to:
   - Python scripts in: `C:\Users\iaq\Building423_IAQ-MH_DAQ\src\`
   - Log file in: `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log`

3. If you cloned the repository to a different location, or if you need to verify/update the paths:
   - Using **Notepad**, open `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\run_backup.bat`
   - Verify that `SCRIPT_PATH`, `SCRIPT_PATH2`, and `SCRIPT_PATH3` point to `C:\Users\iaq\Building423_IAQ-MH_DAQ\src\`
   - Verify that `LOG_PATH` points to `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log`
   - If changes are needed, edit the file, then save it (**File** → **Save**)
   - **Close Notepad** when done

---

## Step 5: Run Your First Test Backup

Now run the backup manually to make sure everything works. Choose one of the two options below:

### Option A: Using Command Prompt

1. On the DAQ computer, open **Command Prompt**
2. Navigate to the scripts folder:
   ```
   cd C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts
   ```
3. Run the batch file:
   ```
   run_backup.bat
   ```
4. The command prompt window will appear briefly while the scripts run, then close automatically. All output is written to `batch_output.log` — there is no console output displayed.

5. Open `batch_output.log` immediately after to confirm the scripts ran:
   ```
   C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log
   ```

### Option B: Using File Explorer

1. On the DAQ computer, open **File Explorer**
2. Navigate to: `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\`
3. Find the file named **`run_backup.bat`**
4. **Double-click** on `run_backup.bat` to run it
5. A command prompt window will appear showing the backup progress
6. The window will close automatically when finished

### Check the Log

1. Open **File Explorer** and navigate to `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\`
2. Open the file **`batch_output.log`** in **Notepad**
3. Look for these messages (one for each backup):
   - `ALL BACKUPS COMPLETED SUCCESSFULLY` (from `mh_daq_file_backup.py`)
   - `ALL EPA SHOWER BACKUPS COMPLETED SUCCESSFULLY` (from `epa_shower_file_backup.py`)
   - `ECOBEE BACKUP COMPLETED SUCCESSFULLY` (from `ecobee_thermostat_backup.py`)

4. **Check for errors:**
   - Look for lines containing `ERROR` or `NOT accessible`
   - If errors appear, see the [Troubleshooting Guide](TROUBLESHOOTING.md)

---

## Step 6: Next Steps

Once the first test backup is successful, you have two options:

### Option A: Manual Backups (Temporary)

Run the batch file manually every few days:
- Open Command Prompt on the DAQ computer
- Run: `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\run_backup.bat`
- Check `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log` for success

### Option B: Automatic Nightly Backups (Planned)

Schedule the backup to run automatically every night using Splinterware System Scheduler:
- See the [Configuration Guide](CONFIGURATION.md) for detailed scheduler setup instructions  
- This is the **long-term approach** for unattended operation

---

## Verification Checklist

Before considering deployment complete, confirm:

- Python and pandas are installed
- Repository is cloned to `C:\Users\iaq\Building423_IAQ-MH_DAQ\`
- `run_backup.bat` paths are correct (references scripts in the cloned repo)
- `data_config.json` created from template with correct local and network paths
- Manual backup test completed successfully
- Log file shows no errors
- DAQ data appeared on mission network drive
- EPA Shower data appeared on elwood network drive (if used)
- Ecobee token file created and first thermostat backup succeeded

---

## Getting Help

If you encounter any issues:

1. **Check the log file:** `C:\Users\iaq\Building423_IAQ-MH_DAQ\scripts\batch_output.log`
2. **Read the error message** and look it up in the [Troubleshooting Guide](TROUBLESHOOTING.md)
3. **Contact Nathan Lima** with the error message and log file contents

---

## Next: Configuration (Optional)

Once installation is complete:

- To set up **Ecobee thermostat data backup**, see [Configuration Guide](CONFIGURATION.md)
- To **automate with Splinterware Scheduler**, see [Configuration Guide](CONFIGURATION.md)
- To troubleshoot issues, see [Troubleshooting Guide](TROUBLESHOOTING.md)
