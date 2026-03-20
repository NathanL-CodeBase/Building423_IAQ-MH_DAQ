# Configuration & Setup Guide

This guide provides detailed instructions for configuring the MH DAQ backup system using the `data_config.json` configuration file, including Ecobee thermostat data integration and automatic scheduling.

---

## Table of Contents

1. [Quick Start — Creating Configuration](#quick-start--creating-configuration)
2. [Network Paths Configuration](#network-paths-configuration)
3. [Data Backup Configuration](#data-backup-configuration)
4. [Ecobee Thermostat Setup](#ecobee-thermostat-setup)
5. [Splinterware System Scheduler](#splinterware-system-scheduler)
6. [Verifying Your Setup](#verifying-your-setup)

---

## Quick Start — Creating Configuration

All backup scripts load their configuration from **`data_config.json`** in the repository root. This file is **not committed to GitHub** — each deployment creates its own copy from the provided template.

### Step 1: Create Configuration File from Template

1. In the repository root, find **`data_config.template.json`**
2. **Copy** this file and name the copy **`data_config.json`**
3. Open **`data_config.json`** in a text editor (Notepad, VSCode, etc.)

### Step 2: Configure Local Source Paths

Find the `"local_sources"` section and update the paths for your system:

```json
"local_sources": {
  "indoor_daq": {
    "path": "C:\\Users\\YOUR_USERNAME\\Desktop\\Task_Logger_Data",
    "description": "Task Logger output"
  },
  "outdoor_weather": {
    "path": "C:\\Users\\YOUR_USERNAME\\Desktop\\Outdoor_Data",
    "description": "Met One AIO2 weather station data"
  }
}
```

**Change:**
- `YOUR_USERNAME` → Your actual Windows username (e.g., `iaq`, `operator`)
- Verify these folders exist on your local machine

### Step 3: Configure Network Destination Paths

Find the `"remote_destinations"` section. Configure one or more of the following:

#### **Mission Network (Primary)**

```json
"mission": {
  "base_path": "\\\\YOUR_SERVER\\YOUR_SHARE\\...\\DAQ_Data\\raw_data",
  "folders": {
    "indoor_daq": "indoor_daq",
    "weather_station": "weather_station"
  },
  "log_file": "backup_log.txt"
}
```

**Change:**
- `YOUR_SERVER` → Your actual server name (e.g., `mission.el.nist.gov`)
- `YOUR_SHARE` and path structure → Match your network drive's actual path

#### **EPA Shower Network (Temporary — Optional)**

```json
"epa_shower": {
  "base_path": "\\\\YOUR_SERVER\\YOUR_SHARE\\EPA_Shower\\MH DAQ",
  "folders": {
    "indoor_daq": "indoor_daq",
    "weather_station": "weather_station"
  },
  "archive_year": 2026
}
```

**Change:**
- `YOUR_SERVER` and `YOUR_SHARE` → Your actual network location
- `archive_year` → The year of data to back up (currently `2026`)

#### **Thermostat (Ecobee)**

```json
"thermostat": {
  "base_path": "\\\\YOUR_SERVER\\YOUR_SHARE\\...\\thermostat",
  "log_file": "backup_log_thermostat.txt",
  "thermostat_id": "YOUR_THERMOSTAT_ID"
}
```

**Change:**
- `YOUR_THERMOSTAT_ID` → Your Ecobee thermostat's numeric ID
- The thermostat ID can also be set via the `ECOBEE_THERMOSTAT_ID` environment variable (takes priority over the config value)

### Step 4: Save Configuration

1. After updating all paths, **save** the file
2. **Do NOT commit** `data_config.json` to Git — it's in `.gitignore` to protect your paths
3. Each deployment maintains its own copy

---

## Network Paths Configuration

### Understanding the Data Flow

All backup scripts use the same configuration file with these data flows:

| Script | Data Source | Mission Destination | EPA Shower Destination |
|--------|-------------|---------------------|----------------------|
| `mh_daq_file_backup.py` | `local_sources.indoor_daq.path` | `remote_destinations.mission.base_path\indoor_daq\` | ❌ Not backed up |
| `mh_daq_file_backup.py` | `local_sources.outdoor_weather.path` | `remote_destinations.mission.base_path\weather_station\` | ❌ Not backed up |
| `epa_shower_file_backup.py` | `local_sources.indoor_daq.path\<archive_year>` | ❌ Not backed up | `remote_destinations.epa_shower.base_path\indoor_daq\<archive_year>\` |
| `epa_shower_file_backup.py` | `local_sources.outdoor_weather.path\<archive_year>` | ❌ Not backed up | `remote_destinations.epa_shower.base_path\weather_station\<archive_year>\` |
| `ecobee_thermostat_backup.py` | Ecobee API (internet) | `remote_destinations.thermostat.base_path\YYYY\` | ❌ Not backed up |

All source and destination paths are configured in `data_config.json`.

### Network Path Format

Windows network paths in JSON must use **double backslashes** (`\\\\`):

```json
"base_path": "\\\\YOUR_SERVER\\YOUR_SHARE\\...\\DAQ_Data\\raw_data"
```

This represents the actual UNC path:
```
\\YOUR_SERVER\YOUR_SHARE\...\DAQ_Data\raw_data
```

---

## Data Backup Configuration

The `"instruments"` section in `data_config.json` documents which sensors are installed and what variables they produce. **You do not need to modify this section** — it is informational reference only. The backup scripts copy entire data files and do not filter by instrument or variable.

**Active instruments being backed up:**
- **AIO2** — Outdoor weather station (5 channels: wind speed, direction, temperature, humidity, pressure)
- **Vaisala_HMP155** — Indoor RH/temperature at 4 locations (high-accuracy probes)
- **Vaisala_HMP45A** — Indoor RH/temperature at 8 locations
- **Ecobee4** — Smart thermostat (temperature, humidity, HVAC runtime — downloaded via Ecobee API)

**Instruments present in data files but currently disconnected:**
- **Setra_264** — Differential pressure transducers (channels are logged as zero or noise — disconnected as of 12/31/25)

### Live-File Safety (DAQ Backup Scripts)

`mh_daq_file_backup.py` and `epa_shower_file_backup.py` skip the current day's data file by default. The DAQ system writes to today's file continuously throughout the day, and copying a file that is still being written to can produce a **truncated or corrupt backup copy**.

Each scheduled daily run captures only completed files (previous days). The current day's partial file is left alone and will be backed up at the next scheduled run after midnight, once the DAQ system has finished writing to it.

**To include today's partial file** (e.g., when running manually to verify recent data is visible on the network):

```bat
python <repo_path>\src\mh_daq_file_backup.py --include-today
python <repo_path>\src\epa_shower_file_backup.py --include-today
```

> **Note:** The Ecobee thermostat script (`ecobee_thermostat_backup.py`) is not affected by this — it always fetches the previous day's data from the Ecobee cloud API. The API only provides complete, finalized interval data for finished days, so there is no live-file risk for thermostat data.

---

## Ecobee Thermostat Setup

The Ecobee integration automatically downloads 5-minute interval thermostat runtime data each day and saves it as a CSV file on the mission network drive.

### Overview

Each daily run fetches the previous day's full 24-hour dataset (288 five-minute intervals). Data includes indoor temperature, humidity, HVAC runtime, setpoints, and equipment state. See `ecobee_thermostat_backup.py` module docstring for the full list of columns.

### Step 1: Enable Developer Access (One-Time)

This step requires access to the Ecobee web portal. **Only one person needs to do this.**

1. Go to **[ecobee.com](https://www.ecobee.com)** and log in with the MH project account
2. Click **your account icon** in the **top-right corner**
3. From the dropdown menu, select **Developer**
4. Click **Create New App** and fill in the form:
   - **Application Name:** `NIST MH DAQ`
   - **Application Summary:** `Automated data collection for NIST IAQ research`
   - **Authorization Method:** Select **ecobee PIN**
5. Click **Create** — you'll see your **32-character API Key**

> **IMPORTANT:** The API key is sensitive. Store it securely and do not commit it to the repository. It is used only during token setup (Step 2) and does not need to be stored in `data_config.json`.

### Step 2: Token Setup (First Time on DAQ Computer)

After obtaining the API key, run the interactive token setup script on the DAQ computer:

1. Open **Command Prompt** on the **DAQ computer** in Building 423
2. Navigate to the scripts folder:
   ```
   cd <repo_path>\src
   ```
3. Run the setup script:
   ```
   python ecobee_token_setup.py
   ```
4. Paste your API Key when prompted
5. The script will display a **4-character PIN**
6. Go to **ecobee.com → My Apps** → **Add Application** and enter the PIN
7. Return to Command Prompt and press Enter — tokens will be saved to the path shown on screen (default: `%USERPROFILE%\scripts\ecobee_tokens.json`, or the path set in the `ECOBEE_TOKEN_FILE` environment variable)

### Token Lifetime and Refresh

- **Access Token:** Valid for ~2 hours (automatically refreshed by the script)
- **Refresh Token:** Valid for ~1 year (requires re-authorization after 1 year)

If the script logs show `Token refresh failed`:
1. Re-run: `python ecobee_token_setup.py`
2. Follow the authorization steps again

### Backfilling Missed Days

If the script fails on a given day, you can retrieve that day's data later using the `TARGET_DATE_OVERRIDE` environment variable:

```bat
set TARGET_DATE_OVERRIDE=2026-03-15
python <repo_path>\src\ecobee_thermostat_backup.py
```

The script skips dates where the CSV file already exists, so re-running it is always safe.

### Ecobee Data Structure

Thermostat data is organized under the path configured in `data_config.json` → `remote_destinations.thermostat.base_path`:

```
<remote_destinations.thermostat.base_path>\
    ├── backup_log_thermostat.txt
    └── 2026\
        ├── 2026-01-01_thermostat.csv
        ├── 2026-01-02_thermostat.csv
        └── ...
```

Each CSV contains 288 rows of 5-minute interval data per day.

---

## Splinterware System Scheduler

To run backups automatically every night, use **Splinterware System Scheduler** (required due to PIV smart card login on the DAQ computer).

### Why Splinterware?

The DAQ computer requires **PIV smart card login**, which prevents standard Windows Task Scheduler from running tasks under the `iaq` account. Splinterware System Scheduler works around this limitation.

### Setup Steps

1. On the **DAQ computer**, open **Splinterware System Scheduler**

2. Click **Add Task** (or the **`+`** button)

3. Configure the task with these settings:

   **General Tab:**
   - **Task type:** `Run a Program / Script`
   - **Program / Script:** `<repo_path>\scripts\run_backup.bat`
   - **Start in (working directory):** `<repo_path>\scripts`
   - **Description:** `MH IAQ DAQ Backup`

4. Click the **Schedule** tab

5. Configure the schedule:
   - **Frequency:** `Daily`
   - **Time:** Choose a time when the DAQ computer is reliably powered on and no active experiments are running
   - **Recommended:** `6:00 AM`

6. Optional additional options:
   - **Retry on failure:** Enable with reasonable intervals
   - **Stop if still running:** Set a timeout (e.g., 30 minutes)

7. Click **Save** and enable the task

### Verifying the Scheduled Task

1. **Manual test:** Right-click the task → **Run Now** to verify it works before relying on the schedule
2. **First scheduled run:** Check `batch_output.log` at the scheduled time to confirm it ran automatically
3. **Ongoing monitoring:** Check `batch_output.log` after each scheduled run to ensure no errors

### Editing or Disabling the Task

1. Open **Splinterware System Scheduler**
2. Find the **MH IAQ DAQ Backup** task
3. Right-click → **Edit** or **Properties**
4. Make your changes and click **Save**

---

## Verifying Your Setup

### Pre-Deployment Checklist

Before considering the system fully configured, verify:

- [ ] Network drives are accessible (see [Installation Guide](INSTALLATION.md))
- [ ] Manual backup test succeeds (`run_backup.bat` runs without errors)
- [ ] DAQ data appears on mission network drive (`indoor_daq\` and `weather_station\` folders)
- [ ] EPA Shower data appears on elwood network drive (if configured)
- [ ] Ecobee token is created and first backup succeeds
- [ ] Splinterware scheduler task is configured and runs automatically

### Manual Testing

To test the backup system:

1. On the **DAQ computer**, open **Command Prompt**
2. Run:
   ```
   <repo_path>\scripts\run_backup.bat
   ```
3. Open `<repo_path>\scripts\batch_output.log` to verify all backups succeeded

### Viewing Backed-Up Data

1. Open **File Explorer** on the DAQ computer
2. Navigate to the configured mission network path
3. Check for:
   - `indoor_daq\` folder with `.txt` files (newest files should match recent dates)
   - `weather_station\` folder with data files
   - `thermostat\YYYY\` folder with daily CSV files

### Log File Analysis

The `batch_output.log` file captures console output from each script run. Look for:

**Success indicators:**
- `ALL BACKUPS COMPLETED SUCCESSFULLY`
- `ECOBEE BACKUP COMPLETED SUCCESSFULLY`
- File counts: `X copied, Y unchanged, 0 errors`

**Error indicators:**
- `Network path NOT accessible`
- `ERROR` lines
- Error counts greater than 0

See the [Troubleshooting Guide](TROUBLESHOOTING.md) for common errors and solutions.

---

## Next Steps

- **Troubleshooting issues?** See the [Troubleshooting Guide](TROUBLESHOOTING.md)
- **Need help?** Contact Nathan Lima with your log file and error message
