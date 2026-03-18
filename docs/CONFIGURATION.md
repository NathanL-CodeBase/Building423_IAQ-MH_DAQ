# Configuration & Setup Guide

This guide provides detailed instructions for configuring the MH DAQ backup system using the `data_config.json` configuration file, including optional Ecobee thermostat data integration and automatic scheduling.

---

## Table of Contents

1. [Quick Start — Creating Configuration](#quick-start--creating-configuration)
2. [Network Paths Configuration](#network-paths-configuration)
3. [Data Backup Configuration](#data-backup-configuration)
4. [Ecobee Thermostat Setup](#ecobee-thermostat-setup) — **Coming Soon**
5. [Splinterware System Scheduler](#splinterware-system-scheduler)
6. [Verifying Your Setup](#verifying-your-setup)

---

## Quick Start — Creating Configuration

All backup scripts load their configuration from **`data_config.json`** in the repository root. This file is **not committed to GitHub** — each user creates their own copy from the provided template.

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

Find the `"remote_destinations"` section. You likely need to configure one or both of the following:

#### **Mission Network (Primary)**

```json
"mission": {
  "base_path": "\\\\YOUR_SERVER\\YOUR_SHARE\\...\\DAQ_Data\\raw_data",
  "folders": {
    "indoor_daq": "indoor_daq",
    "weather_station": "weather_station"
  }
}
```

**Change:**
- `YOUR_SERVER` → Replace with your actual server name (e.g., `mission.el.nist.gov`)
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

### Step 4: Save Configuration

1. After updating all paths, **save** the file
2. **Do NOT commit** `data_config.json` to Git — it's in `.gitignore` to protect your paths
3. Each user/machine maintains their own copy

---

## Network Paths Configuration

### Understanding the Data Flow

All backup scripts use the same configuration file with these data flows:

| Script | Data Source | Mission Destination | EPA Shower Destination |
|--------|-------------|---------------------|----------------------|
| `mh_daq_file_backup.py` | `C:\Users\iaq\Desktop\Task_Logger_Data` | `\\mission\...\indoor_daq\` | ❌ Not backed up |
| `mh_daq_file_backup.py` | `C:\Users\iaq\Desktop\Outdoor_Data` | `\\mission\...\weather_station\` | ❌ Not backed up |
| `epa_shower_file_backup.py` | `C:\Users\iaq\Desktop\Task_Logger_Data\2026` | ❌ Not backed up | `\\elwood\...\indoor_daq\2026\` |
| `epa_shower_file_backup.py` | `C:\Users\iaq\Desktop\Outdoor_Data\2026` | ❌ Not backed up | `\\elwood\...\weather_station\2026\` |

### Network Path Format

Windows network paths in JSON must use **double backslashes** (`\\\\`):

```json
"base_path": "\\\\mission.el.nist.gov\\Programs\\energy_netzero\\ventilation_iaq\\Manufactured House\\DAQ_Data\\raw_data"
```

This represents the actual path:
```
\\mission.el.nist.gov\Programs\energy_netzero\ventilation_iaq\Manufactured House\DAQ_Data\raw_data
```

---

## Data Backup Configuration

The `"backup_sources"` section in `data_config.json` clarifies which instruments are backed up to which destinations. **You do not need to modify this section** — it's informational:

```json
"backup_sources": {
  "mission_drive": {
    "description": "All indoor and outdoor data",
    "indoor_daq": ["Setra_264", "Vaisala_HMP155", "Vaisala_HMP45A"],
    "outdoor_weather": ["AIO2"]
  },
  "epa_shower_drive": {
    "description": "2026 data only (temporary)",
    "archive_year": 2026,
    "indoor_daq": ["Setra_264", "Vaisala_HMP155", "Vaisala_HMP45A"],
    "outdoor_weather": ["AIO2"]
  }
}
```

**Key Instruments:**
- **AIO2** — Outdoor weather station (5 channels: wind speed, direction, temperature, humidity, pressure)
- **Setra_264** — Indoor differential pressure (currently disconnected)
- **Vaisala_HMP155** — Indoor humidity/temperature (4 locations)
- **Vaisala_HMP45A** — Indoor humidity/temperature (8 locations)

---

## Ecobee Thermostat Setup

**Status:** **In Development** — The Ecobee integration is currently being finalized. Follow these steps to prepare for the eventual deployment.

### Overview

The Ecobee system automatically downloads 5-minute interval thermostat data (temperature, humidity, HVAC runtime, etc.) each day and saves it as a CSV file on the mission network drive. The thermostat ID for the MH test facility is **511879526877**.

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

> **IMPORTANT:** Contact Nathan Lima (nathan.lima@nist.gov) with the API key. It will be stored securely in environment variables (NOT in the repository).

### Step 2: Token Setup (First Time on DAQ Computer)

After obtaining the API key, run the interactive token setup script on the DAQ computer:

1. Open **Command Prompt** on the **DAQ computer** in Building 423
2. Navigate to the scripts folder:
   ```
   cd C:\Users\iaq\Scripts
   ```
3. Run the setup script:
   ```
   python ecobee_token_setup.py
   ```
4. Paste your API Key when prompted
5. The script will display a **4-digit PIN**
6. Go to **ecobee.com → My Apps** and enter the PIN
7. Return to Command Prompt — tokens will be automatically saved to:
   ```
   C:\Users\iaq\scripts\ecobee_tokens.json
   ```

### Token Lifetime and Refresh

- **Access Token:** Valid for ~2 hours (automatically refreshed by the script)
- **Refresh Token:** Valid for ~1 year (requires re-authorization after 1 year)

If the script logs show `Token refresh failed`:
1. Re-run: `python ecobee_token_setup.py`
2. Follow the authorization steps again

### Ecobee Data Structure

Once set up, Ecobee data will be organized as:

```
\\mission.el.nist.gov\Programs\energy_netzero\ventilation_iaq\Manufactured House\DAQ_Data\raw_data\
└── thermostat\
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

### Setup Steps

1. Open **Splinterware System Scheduler** on the DAQ computer
2. Click **Add Task**
3. Configure:
   - **Program/Script:** `C:\Users\iaq\Scripts\run_backup.bat`
   - **Working Directory:** `C:\Users\iaq\Scripts`
   - **Description:** `MH IAQ DAQ Backup`
4. Set **Schedule:**
   - **Frequency:** Daily
   - **Time:** 6:00 AM (or when DAQ computer is most reliably available)
5. Click **Save** and enable the task

### Verifying the Scheduled Task

1. Check `batch_output.log` at the scheduled time to confirm it ran
2. Manual test: Right-click the task → **Run Now**
3. Monitor log files for errors (see Troubleshooting Guide)

---

## Verifying Your Setup

### Pre-Deployment Checklist

Before considering the system fully configured, verify:

- Network drives are accessible (see [Installation Guide](INSTALLATION.md))
- Manual backup test succeeds (`run_backup.bat` runs without errors)
- DAQ data appears on mission network drive
- EPA Shower data appears on elwood network drive (if configured)
- Log file shows no error messages
- (Optional) Ecobee token is created and first backup succeeds
- (Future) Splinterware scheduler task is configured and runs automatically

### Manual Testing

To test the backup system:

1. On the **DAQ computer**, open **Command Prompt**
2. Run:
   ```
   C:\Users\iaq\Scripts\run_backup.bat
   ```
3. Wait for the command prompt to close
4. Open `batch_output.log` to verify all backups succeeded

### Viewing Backed-Up Data

To verify data is being backed up correctly:

1. Open **File Explorer** on the DAQ computer
2. Navigate to the configured mission network path
3. Check for:
   - `indoor_daq\` folder with `.txt` files (newest files should have today's date)
   - `weather_station\` folder with data files
   - `thermostat\` folder (after Ecobee is configured) with daily CSV files

### Log File Analysis

The `batch_output.log` file contains detailed information about each backup run:

**Success indicators:**
- `[SUCCESS]` tags
- File counts: `Backed up X new files`
- Timestamps: `Backup completed at HH:MM:SS`

**Error indicators:**
- `[ERROR]` or `[FAILED]` tags
- `Network path not accessible`
- Permission denied messages

See the [Troubleshooting Guide](TROUBLESHOOTING.md) for common errors and solutions.

---

## Next Steps

- **Troubleshooting issues?** See the [Troubleshooting Guide](TROUBLESHOOTING.md)
- **Need help?** Contact Nathan Lima with your log file and error message

## Splinterware System Scheduler

To run backups automatically every night (long-term operation), use **Splinterware System Scheduler**. This application will be installed on the DAQ computer in the future.

### Why Splinterware?

The DAQ computer requires **PIV smart card login**, which prevents standard Windows Task Scheduler from running tasks under the `iaq` account. Splinterware System Scheduler works around this limitation.

### Setup Steps

1. On the **DAQ computer**, open **Splinterware System Scheduler** (search the Start menu or find it in the taskbar)

2. Click **Add Task** (or the **`+`** button)

3. Configure the task with these settings:

   **General Tab:**
   - **Task type:** `Run a Program / Script`
   - **Program / Script:** `C:\Users\iaq\Scripts\run_backup.bat`
   - **Start in (working directory):** `C:\Users\iaq\Scripts`
   - **Description:** `MH IAQ DAQ Backup`
   - **Run with highest privileges:** (leave at default)

4. Click the **Schedule** tab or **Scheduling** section

5. Configure the schedule:
   - **Frequency:** `Daily`
   - **Time:** Choose a time when:
     - The DAQ computer is reliably powered on
     - No active experiments are running (to avoid contention)
     - **Recommended:** `6:00 AM` (early morning)

6. (Optional) Set additional options:
   - **Repeating:** No (run once daily)
   - **Retry on failure:** Enable (with reasonable intervals)
   - **Stop if still running:** Set a timeout (e.g., 30 minutes)

7. Click **Save** and enable the task (you may need to confirm with administrator credentials)

### Verifying the Scheduled Task

Once the task is configured:

1. **First verification:** Wait until the scheduled time and check `batch_output.log` to confirm it ran automatically
   > Look for a timestamp matching your scheduled time, and success messages for each backup

2. **Manual test:** Right-click the task in Splinterware and select **Run Now** to verify it works

3. **Monitor:** Check `batch_output.log` after each scheduled run to ensure no errors are occurring

### Editing or Disabling the Task

If you need to change the schedule time or disable backups temporarily:

1. Open **Splinterware System Scheduler**
2. Find the **MH IAQ DAQ Backup** task
3. Right-click and select **Edit** or **Properties**
4. Make your changes
5. Click **Save**

---

## Verifying Your Setup

### Pre-Deployment Checklist

Before considering the system fully configured, verify:

- Network drives are accessible (see [Installation Guide](INSTALLATION.md))
- Manual backup test succeeds (`run_backup.bat` runs without errors)
- DAQ data appears on mission network drive
- EPA Shower data appears on elwood network drive
- Log file shows no error messages
- (Optional) Ecobee token is created and first backup succeeds
- (Future) Splinterware scheduler task is configured and runs automatically

### Manual Testing

To test the backup system:

1. On the **DAQ computer**, open **Command Prompt**
2. Run:
   ```
   C:\Users\iaq\Scripts\run_backup.bat
   ```
3. Wait for the command prompt to close
4. Open `batch_output.log` to verify all backups succeeded

### Viewing Backed-Up Data

To verify data is being backed up correctly:

1. Open **File Explorer** on the DAQ computer
2. Navigate to `\\mission.el.nist.gov\Programs\energy_netzero\ventilation_iaq\Manufactured House\DAQ_Data\raw_data\`
3. Check for:
   - `indoor_daq\` folder with `.csv` or `.xlsx` files (newest files should have today's date or recent date)
   - `weather_station\` folder with data files
   - `thermostat\` folder (after Ecobee is configured) with daily CSV files

### Log File Analysis

The `batch_output.log` file contains detailed information about each backup run. Here's what to look for:

**Success indicators:**
- `[SUCCESS]` tags
- File counts: `Backed up X new files`
- Timestamps: `Backup completed at HH:MM:SS`

**Error indicators:**
- `[ERROR]` or `[FAILED]` tags
- `Network path not accessible`
- Permission denied messages

See the [Troubleshooting Guide](TROUBLESHOOTING.md) for common errors and solutions.

---

## Next Steps

- **Troubleshooting issues?** See the [Troubleshooting Guide](TROUBLESHOOTING.md)
- **Need help?** Contact Nathan Lima with your log file and error message
