# Troubleshooting Guide

This guide provides solutions for common issues encountered when running the MH DAQ backup system. Start by checking the `batch_output.log` file to identify the error, then find the matching solution below.

> **Path placeholders used in this guide:**
> - `<repo_path>` — the folder where the repository was cloned
> - `<conda_path>` — your conda base directory (run `conda info --base` to find it)
> - Source and destination paths are configured in `data_config.json`

---

## Quick Start: Finding Your Error

1. Open `<repo_path>\scripts\batch_output.log` in **Notepad**
2. Look for lines containing `ERROR` or `NOT accessible`
3. Find that error message in the table below
4. Follow the solution steps

---

## Common Issues

### Network Drive Access

#### Error: "Network path NOT accessible" OR "Network path does not exist"

**Cause:** The DAQ computer cannot reach the mission or elwood network drives.

**Solutions:**

1. **Check network connection:**
   - Verify the DAQ computer is physically connected to the NIST network
   - If using VPN, verify the connection is active
   - Open **File Explorer** and type the mission base path (from `data_config.json` → `remote_destinations.mission.base_path`) in the address bar
   - You should see folders; if not, network access is the problem

2. **Check IP address and DNS:**
   - Open **Command Prompt** and type:
     ```
     ipconfig /all
     ```
   - Verify you have an IP address in the `192.168.x.x` range (NIST network) or VPN range
   - If IP is `169.254.x.x` (APIPA), network is not connected properly

3. **Contact eldest Support:**
   - If network drives are still unreachable, contact eldest support on slack
   - Provide: Computer name, IP address, and which drives are unreachable
   - They may need to reset network permissions or VPN credentials

---

### Ecobee Token Issues

#### Error: "Token file not found"

**Cause:** The Ecobee token setup has never been run, or the token file is missing.

**Solution:**

1. On the **DAQ computer**, open **Command Prompt**
2. Navigate to the `src` folder:
   ```
   cd <repo_path>\src
   ```
3. Run the token setup script:
   ```
   python ecobee_token_setup.py
   ```
4. Follow the prompts to authorize the Ecobee API (see [Configuration Guide](CONFIGURATION.md) for detailed steps)
5. The script will print the token file path when setup is complete. Verify the file was created:
   ```
   dir %USERPROFILE%\scripts\ecobee_tokens.json
   ```
   > If the file exists, setup was successful. If you used a custom `ECOBEE_TOKEN_FILE` path, check that location instead.

---

#### Error: "Token refresh failed" OR "invalid_grant"

**Cause:** The Ecobee refresh token has expired (valid for ~1 year) or is corrupted.

**Solution:**

1. Open **Command Prompt** on the **DAQ computer**
2. Navigate to the `src` folder:
   ```
   cd <repo_path>\src
   ```
3. Re-run the token setup script:
   ```
   python ecobee_token_setup.py
   ```
4. Follow the authorization steps again (see [Configuration Guide](CONFIGURATION.md))
5. Run a manual test backup:
   ```
   run_backup.bat
   ```
6. Check the log to confirm Ecobee data was fetched successfully

---

#### Error: "HTTP 401" OR "Authorization failed"

**Cause:** The API key is invalid, the token is corrupted, or the app was revoked on the Ecobee portal.

**Solution:**

1. Check if the app still exists on Ecobee:
   - Go to **[ecobee.com](https://www.ecobee.com)** and log in
   - Navigate to **My Apps** or **Developer** → **My Apps**
   - Verify the **NIST MH DAQ** app is listed

2. If the app is missing, create a new one (see [Configuration Guide](CONFIGURATION.md), Step 1)

3. Re-run token setup with the new API key:
   ```
   python ecobee_token_setup.py
   ```

4. Test the backup:
   ```
   run_backup.bat
   ```

---

### Ecobee Data Issues

#### Error: "Ecobee script timed out" or "Request timed out after 90 seconds"

**Cause:** The DAQ computer lost internet connectivity while fetching Ecobee data, or the Ecobee API servers are slow.

**What happens:** The Ecobee script will timeout gracefully after ~90 seconds (30s for token refresh + 60s for report fetch). The other backup scripts (DAQ and EPA Shower) are **unaffected** and continue normally.

**Solution:**

1. Verify the DAQ computer has **internet access:**
   - Open a web browser and visit **[www.google.com](https://www.google.com)**
   - If the page loads, internet is working
   - If not, contact IT

2. Check the mission drive for the Ecobee data that **did** get backed up:
   - Navigate to: `<remote_destinations.thermostat.base_path>\YYYY\` (from `data_config.json`)
   - Look for CSV files with today's date
   - If they exist, the backup partially succeeded

3. Re-run the backup manually:
   ```
   run_backup.bat
   ```

4. Check the log; if still timing out and internet is confirmed working, contact Nathan Lima

---

#### Problem: "CSV has fewer than 288 rows"

**Cause:** The thermostat was offline or rebooted during part of the day, so some 5-minute intervals are missing.

**What this means:** Not an error — this is normal if the thermostat was powered off, rebooting, or lost network connectivity. The CSV will have gaps in the datetime column but is still valid.

**Action required:** None — the data is correct as captured. Contact the MH facility manager if you're concerned about the thermostat's availability.

**To backfill:** If the thermostat data is later retrieved from Ecobee's cloud storage, you can backfill a missed date by editing `ecobee_thermostat_backup.py` (see [Configuration Guide](CONFIGURATION.md), "Backfilling Missed Days").

---

### Python and Library Errors

#### Error: "Python not found" OR "python: command not found"

**Cause:** Python environment not in system PATH, or Python is not installed.

**Solution:**

1. Verify Python is installed:
   ```
   conda --version
   ```
   - If you see a version, Python is installed but not in PATH

2. Find your conda base path and try the full python path:
   ```
   conda info --base
   ```
   Then run:
   ```
   <conda_path>\Scripts\python --version
   ```

3. If this works, you may need to re-add Python to your PATH:
   - Contact eldest or Nathan Lima for help

4. If neither command works, Python is not installed:
   - Contact Nathan Lima to install Miniforge/Conda

---

#### Error: "No module named 'pandas'" OR "ImportError: pandas"

**Cause:** The `pandas` library is not installed in your Python environment.

**Solution:**

1. Open **Command Prompt**
2. Install pandas:
   ```
   conda install pandas
   ```
3. Wait for the installation to complete
4. Test the backup again:
   ```
   <repo_path>\scripts\run_backup.bat
   ```

---

### File and Folder Errors

#### Error: "Permission denied" or "Access denied"

**Cause:** The `iaq` user account does not have read/write permissions on network drives or source folders.

**Solution:**

1. **For source folders** (paths configured in `data_config.json` → `local_sources`):
   - Verify these folders exist and contain data
   - Right-click the folder → **Properties** → **Security**
   - Ensure the current user has **Read** and **Read & Execute** permissions

2. **For network drives** (paths configured in `data_config.json` → `remote_destinations`):
   - Verify you can access these drives manually (see [Installation Guide](INSTALLATION.md))
   - If accessible, contact IT to add account permissions
   - Provide: Computer name, network drive path, and request **Write** access

3. Test the backup after permissions are updated:
   ```
   run_backup.bat
   ```

---

#### Error: "Source folder not found" OR "No input file"

**Cause:** The source DAQ data folders don't exist at the expected location or contain no data.

**Solution:**

1. Verify the source folders exist:
   - Open **File Explorer** on the DAQ computer
   - Navigate to the paths configured in `data_config.json` → `local_sources.indoor_daq.path` and `local_sources.outdoor_weather.path`
   - Check that the folders are present and contain data

2. If the folders don't exist or are in a different location:
   - Update the paths in `data_config.json` under `local_sources`
   - Contact Nathan Lima if you're unsure of the correct paths

3. If folders exist but are empty:
   - Verify the DAQ instruments (Task Logger, weather station) are running and saving data
   - Check the DAQ logs to see if data collection is active
   - Contact the MH facility manager if data collection has stopped

---

#### Error: "Destination folder not found" OR "Cannot write to destination"

**Cause:** The destination network path doesn't exist or the user account lacks write permissions.

**Solution:**

1. Verify the destination paths are correct:
   - Open `data_config.json` and check the `remote_destinations` section
   - Confirm the `base_path` values match the actual network share structure

2. Manually access the network drives:
   - Open **File Explorer** → **Map network drive**
   - Try mapping the path from `data_config.json` → `remote_destinations.mission.base_path`
   - If this fails, the path is wrong or network is unreachable

3. Request IT assistance:
   - Provide the network path and your computer name
   - Request **Read/Write** access for the user account

---

### Batch File Issues

#### Error: "run_backup.bat is not recognized" OR Cannot find batch file

**Cause:** The batch file paths don't match your actual installation location.

**Solution:**

1. Verify the batch file exists:
   ```
   dir <repo_path>\scripts\run_backup.bat
   ```
   > If no file is listed, the batch file is not in that folder

2. Find the batch file:
   - Open **File Explorer**
   - Search for `run_backup.bat` on the C: drive
   - Note the location

3. Update your command to use the correct path:
   ```
   <actual_path>\run_backup.bat
   ```

4. If the batch file doesn't exist anywhere:
   - Download it from GitHub again (see [Installation Guide](INSTALLATION.md), Step 3)

---

#### Error: `%CONDA_PATH%` is not set OR Cannot find conda

**Cause:** The batch file's `CONDA_ACTIVATE` variable is incorrect or conda is not installed.

**Solution:**

1. Find your conda path:
   ```
   conda info --base
   ```
   > Note the path — this is `<conda_path>`

2. Edit `<repo_path>\scripts\run_backup.bat`:
   - Open in **Notepad**
   - Find the line: `set CONDA_ACTIVATE=...`
   - Update it to:
     ```batch
     set CONDA_ACTIVATE=<conda_path>\Scripts\activate.bat
     ```
   - Save the file

3. Test the batch file:
   ```
   run_backup.bat
   ```

---

### Splinterware Scheduler Issues

#### Problem: Scheduled task doesn't run at the expected time

**Cause:** Scheduler configuration is incorrect, or the computer was powered off at the scheduled time.

**Solutions:**

1. **Verify the computer is powered on at the scheduled time:**
   - Check if the DAQ computer automatically powers down at night
   - If so, configure it to stay powered on or change the schedule time

2. **Verify the schedule in Splinterware:**
   - Open **Splinterware System Scheduler**
   - Right-click the **MH IAQ DAQ Backup** task
   - Select **Properties** or **Edit**
   - Confirm the time is set correctly

3. **Test the task manually:**
   - Right-click the task
   - Select **Run Now**
   - Check `batch_output.log` to verify it ran

4. **Check if the task is enabled:**
   - The task should have a **checkmark** next to it in Splinterware
   - If not, right-click and select **Enable**

---

#### Problem: Scheduled task runs but doesn't complete (hangs or takes too long)

**Cause:** The backup is taking longer than expected, or there's a blocking network issue.

**Solution:**

1. Monitor the log file while the task runs:
   - Open `<repo_path>\scripts\batch_output.log` in a text editor
   - Keep the window open and refresh periodically (F5)
   - Look for messages that indicate where it's stuck

2. Increase the timeout in Splinterware:
   - Open **Splinterware System Scheduler**
   - Right-click the task → **Properties**
   - Look for **Stop if still running after X minutes**
   - Increase the timeout (e.g., 30 to 60 minutes)
   - Save the task

3. If specific backups are failing:
   - Run each script manually to identify the problem:
     ```
     cd <repo_path>\src
     python mh_daq_file_backup.py
     python epa_shower_file_backup.py
     python ecobee_thermostat_backup.py
     ```
   - Running scripts directly prints output to the console, making errors easier to spot
   - Check `batch_output.log` for the full output from scheduled runs

---

## Still Need Help?

If you can't find your error in this guide:

1. **Gather information:**
   - Copy the entire contents of `batch_output.log`
   - Note the date/time the error occurred
   - Note what you were doing when the error happened (manual run, scheduled run, etc.)

2. **Contact Nathan Lima**
   - Provide the log file contents
   - Include the error message (exact text)
   - Describe what you tried so far

---

## Testing and Verification

### Quick Test Procedure

To verify the system is working correctly:

1. **Test manual backup:**
   ```
   <repo_path>\scripts\run_backup.bat
   ```
   > Wait for the command prompt to close

2. **Check the log:**
   - Open `<repo_path>\scripts\batch_output.log`
   - Look for `COMPLETED SUCCESSFULLY` messages for each script
   - Verify timestamps are recent (within the last few minutes)

3. **Verify data was backed up:**
   - Open **File Explorer**
   - Navigate to the path in `data_config.json` → `remote_destinations.mission.base_path`
   - Check that `indoor_daq\` and `weather_station\` folders contain files
   - Look at **Date Modified** to confirm files are from today

4. **If scheduled:** Check that the task runs automatically the next morning

---

## Log File Format

The `batch_output.log` file captures all Python script console output. Lines are formatted as:

```
Backup started: Wed 03/17/2026  6:00:00.00
============================================================
2026-03-17 06:00:01,123 - INFO - Script started
2026-03-17 06:00:01,124 - INFO - Loading configuration...
2026-03-17 06:00:01,456 - INFO - ----------------------------------------
2026-03-17 06:00:01,457 - INFO - INDOOR DAQ BACKUP
2026-03-17 06:00:01,458 - INFO - ----------------------------------------
2026-03-17 06:00:02,100 - INFO - Copied (new file): 20260317-Daily_MHIndoor_Data.txt
2026-03-17 06:00:03,200 - INFO - Indoor DAQ complete: 1 copied, 42 unchanged, 0 errors
...
2026-03-17 06:00:10,000 - INFO - ALL BACKUPS COMPLETED SUCCESSFULLY
============================================================
Backup finished: Wed 03/17/2026  6:00:10.12
```

- **`- INFO -`** = Normal progress messages
- **`- WARNING -`** = Potential issue but backup continued (review if recurring)
- **`- ERROR -`** = Something failed (investigate this)
- Lines with `NOT accessible` = Network path unreachable
- Lines with `COMPLETED SUCCESSFULLY` = That script finished without errors
- Lines with `COMPLETED WITH ERRORS` = That script had failures — check surrounding `ERROR` lines
