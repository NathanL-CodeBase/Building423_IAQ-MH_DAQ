#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ecobee4 Thermostat Data Backup
================================

This script downloads daily runtime report data from the Ecobee4 thermostat
in the NIST IAQ Manufactured House test facility and saves it as CSV files
to the mission network drive. It is designed to run as a scheduled daily task
alongside the other MH DAQ backup scripts.

Data is retrieved via the Ecobee Runtime Report API, which provides complete
5-minute interval historical data. Each run fetches the previous day's full
24-hour dataset (288 five-minute intervals), ensuring gapless data archiving
even if the script fails on a given day and is re-run manually with a
backfill date.

Key Data Collected:
    - zoneAveTemp:        Indoor average temperature (°F)
    - zoneHeatTemp:       Heating setpoint (°F)
    - zoneCoolTemp:       Cooling setpoint (°F)
    - zoneHumidity:       Indoor relative humidity (%)
    - zoneHumidityHigh:   Humidity high setpoint (%)
    - zoneHumidityLow:    Humidity low setpoint (%)
    - zoneHVACmode:       Active HVAC mode (heat, cool, auto, off, etc.)
    - zoneCalendarEvent:  Active schedule or event name
    - zoneOccupancy:      Occupancy state (true/false)
    - outdoorTemp:        Outdoor temperature from Ecobee weather service (°F)
    - outdoorHumidity:    Outdoor relative humidity (%)
    - fan:                Fan runtime per interval (seconds, max 300)
    - compHeat1/2:        Compressor heating runtime per interval (seconds)
    - compCool1/2:        Compressor cooling runtime per interval (seconds)
    - auxHeat1/2/3:       Auxiliary/electric heat runtime per interval (seconds)
    - humidifier:         Humidifier runtime per interval (seconds)
    - dehumidifier:       Dehumidifier runtime per interval (seconds)
    - ventilator:         Ventilator runtime per interval (seconds)
    - economizer:         Economizer runtime per interval (seconds)
    - dmOffset:           Demand management temperature offset (tenths of °F)

Methodology:
    1. Load OAuth2 tokens from local JSON file (created by ecobee_token_setup.py)
    2. Refresh access token if expired (access tokens last ~2 hours)
    3. Determine target date (yesterday by default; override with TARGET_DATE)
    4. Skip if destination CSV already exists (incremental, safe to re-run)
    5. Request runtime report from Ecobee API for all 288 five-minute intervals
    6. Parse response rows, convert temperatures from tenths-of-°F to °F
    7. Save as dated CSV in a year-based subdirectory on the mission drive
    8. Log result to network backup log file

Output Files:
    - <dest>/YYYY/YYYY-MM-DD_thermostat.csv: Daily 5-minute interval runtime data
    - <dest>/backup_log_thermostat.txt:       Running backup log on network drive

Applications:
    - Continuous thermostat monitoring during IAQ experiments
    - Correlation of HVAC runtime with indoor air quality measurements
    - Documentation of thermal comfort and temperature setpoint compliance

Author: Nathan Lima
Institution: NIST
Date: 2026
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------
def load_config(config_file="data_config.json"):
    """
    Load configuration from data_config.json file.

    Args:
        config_file (str): Path to configuration file. If relative, searches
                          in script directory and parent directories.

    Returns:
        dict: Configuration dictionary

    Raises:
        FileNotFoundError: If config file not found in expected locations
    """
    # Check multiple locations for config file
    search_paths = [
        Path(config_file),  # Current directory
        Path(__file__).parent / config_file,  # Script directory
        Path(__file__).parent.parent / config_file,  # Parent of script directory
    ]

    for config_path in search_paths:
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file {config_path}: {e}")

    raise FileNotFoundError(
        f"Configuration file '{config_file}' not found. "
        f"Searched in: {[str(p) for p in search_paths]}"
    )


# Load configuration
config = load_config()

# ---------------------------------------------------------------------------
# CONFIGURATION — Load from data_config.json or environment variables
# ---------------------------------------------------------------------------

# Token file from environment variable or default location.
# Default uses Path.home() / "scripts" / "ecobee_tokens.json" (cross-platform).
# Override by setting the ECOBEE_TOKEN_FILE environment variable.
TOKEN_FILE_PATH = Path(
    os.getenv("ECOBEE_TOKEN_FILE", Path.home() / "scripts" / "ecobee_tokens.json")
)

# Destination directory from config — no hardcoded fallback, fail clearly if missing
thermostat_config = config.get("remote_destinations", {}).get("thermostat", {})
THERMOSTAT_DEST = thermostat_config.get("base_path")
if not THERMOSTAT_DEST:
    raise ValueError(
        "Configuration missing required value: remote_destinations.thermostat.base_path. "
        "Add this path to data_config.json."
    )
THERMOSTAT_LOG = os.path.join(
    THERMOSTAT_DEST, thermostat_config.get("log_file", "backup_log_thermostat.txt")
)

# Thermostat identifier — from environment variable (takes priority) or data_config.json
# Environment variable: set ECOBEE_THERMOSTAT_ID before running to override the config value
THERMOSTAT_ID = os.getenv("ECOBEE_THERMOSTAT_ID") or thermostat_config.get("thermostat_id")
if not THERMOSTAT_ID:
    raise ValueError(
        "Thermostat ID not configured. Set ECOBEE_THERMOSTAT_ID environment variable "
        "or add remote_destinations.thermostat.thermostat_id to data_config.json."
    )

# Target date override — set to a specific date string "YYYY-MM-DD" to backfill
# a missed day, or leave as None to always fetch yesterday.
TARGET_DATE_OVERRIDE = os.getenv("TARGET_DATE_OVERRIDE", None)  # e.g., "2026-01-15"

# ---------------------------------------------------------------------------
# ECOBEE API CONSTANTS
# ---------------------------------------------------------------------------
ECOBEE_TOKEN_URL = "https://api.ecobee.com/token"
ECOBEE_REPORT_URL = "https://api.ecobee.com/1/runtimeReport"

# All available runtime report columns for an Ecobee4 with no remote sensors.
# Accessories not installed (humidifier, dehumidifier, ventilator, economizer)
# will return 0 for every interval and can be dropped during analysis.
REPORT_COLUMNS = (
    "auxHeat1,auxHeat2,auxHeat3,"
    "compCool1,compCool2,"
    "compHeat1,compHeat2,"
    "dehumidifier,dmOffset,economizer,fan,humidifier,"
    "outdoorHumidity,outdoorTemp,"
    "ventilator,"
    "zoneAveTemp,zoneCalendarEvent,zoneCoolTemp,zoneHeatTemp,"
    "zoneHumidity,zoneHumidityHigh,zoneHumidityLow,"
    "zoneHVACmode,zoneOccupancy"
)

# Columns the Ecobee API returns as integer tenths of °F — divide by 10 to get °F.
TEMP_COLUMNS = ["outdoorTemp", "zoneAveTemp", "zoneCoolTemp", "zoneHeatTemp"]

# String-valued columns that should not be cast to numeric.
STRING_COLUMNS = {"datetime", "zoneHVACmode", "zoneCalendarEvent", "zoneOccupancy"}

# Total 5-minute intervals in a 24-hour day (0 through 287).
INTERVALS_PER_DAY = 288

# ---------------------------------------------------------------------------
# Console logging setup (output captured by batch file or cron)
# ---------------------------------------------------------------------------
local_logger = logging.getLogger("ecobee_backup")
local_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
local_logger.addHandler(console_handler)

local_logger.info("=" * 60)
local_logger.info("Ecobee Thermostat Backup Script started")


# ============================================================================
# NETWORK UTILITY FUNCTIONS
# ============================================================================


def check_network_path(path):
    """Check if a network path is accessible by walking up the directory tree.

    Parameters:
        path (str): Network or local path to check

    Returns:
        bool: True if any ancestor directory is reachable, False otherwise
    """
    try:
        current = path
        while current:
            if os.path.exists(current):
                return True
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return False
    except Exception as e:
        local_logger.error(f"Error checking network path {path}: {e}")
        return False


def setup_network_logger(name, log_path):
    """Set up a logger that appends to a file on the network drive.

    Parameters:
        name (str): Logger name
        log_path (str): Full path to the log file on the network

    Returns:
        logging.Logger or None: Configured logger, or None if setup fails
    """
    try:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        logger.addHandler(handler)
        return logger
    except Exception as e:
        local_logger.error(f"Failed to set up network logger at {log_path}: {e}")
        return None


# ============================================================================
# TOKEN MANAGEMENT FUNCTIONS
# ============================================================================


def load_tokens(token_file):
    """Load OAuth2 token data from the local JSON file.

    Parameters:
        token_file (Path): Path to the token JSON file

    Returns:
        dict or None: Token data, or None if the file cannot be loaded
    """
    try:
        with open(token_file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        local_logger.error(f"Token file not found: {token_file}")
        local_logger.error("Run ecobee_token_setup.py to create the token file.")
        return None
    except Exception as e:
        local_logger.error(f"Failed to load token file: {str(e)[:100]}")
        return None


def save_tokens(token_file, token_data):
    """Save updated token data back to the JSON token file.

    Parameters:
        token_file (Path): Path to the token JSON file
        token_data (dict): Updated token data to save

    Returns:
        bool: True if saved successfully
    """
    try:
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        return True
    except Exception as e:
        local_logger.error(f"Failed to save tokens: {str(e)[:100]}")
        return False


def refresh_access_token(token_data, token_file):
    """Refresh the access token using the stored refresh token.

    Parameters:
        token_data (dict): Current token data with refresh_token and api_key
        token_file (Path): Path to the token file for saving the update

    Returns:
        str or None: New access token, or None on failure
    """
    local_logger.info("Access token expired — refreshing...")
    params = {
        "grant_type": "refresh_token",
        "code": token_data["refresh_token"],
        "client_id": token_data["api_key"],
    }
    try:
        response = requests.post(ECOBEE_TOKEN_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        token_data["access_token"] = data["access_token"]
        token_data["refresh_token"] = data["refresh_token"]
        token_data["token_expiry"] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        save_tokens(token_file, token_data)
        local_logger.info("Access token refreshed successfully.")
        return data["access_token"]

    except requests.exceptions.HTTPError:
        error_data = response.json() if response.content else {}
        error_type = error_data.get("error", "")
        desc = error_data.get("error_description", "Unknown error")
        local_logger.error(f"Token refresh failed: {desc}")
        if "token_expired" in error_type or "invalid_grant" in error_type:
            local_logger.error(
                "Refresh token has expired. Re-run ecobee_token_setup.py to re-authorize."
            )
        return None
    except Exception as e:
        local_logger.error(f"Token refresh request failed: {str(e)[:100]}")
        return None


def get_valid_access_token(token_file):
    """Load tokens and return a valid access token, refreshing if necessary.

    Parameters:
        token_file (Path): Path to the token JSON file

    Returns:
        str or None: Valid access token, or None on failure
    """
    token_data = load_tokens(token_file)
    if not token_data:
        return None

    # Parse expiry and check validity with a 5-minute safety buffer
    expiry = datetime.fromisoformat(token_data["token_expiry"])
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) < expiry - timedelta(minutes=5):
        local_logger.info("Access token is valid.")
        return token_data["access_token"]

    return refresh_access_token(token_data, token_file)


# ============================================================================
# ECOBEE API FUNCTIONS
# ============================================================================


def fetch_runtime_report(access_token, target_date):
    """Fetch a full day's runtime report for the configured thermostat.

    Requests all 288 five-minute intervals for the given date from the
    Ecobee Runtime Report API (GET /1/runtimeReport).

    Parameters:
        access_token (str): Valid OAuth2 access token
        target_date (date): The calendar date to fetch

    Returns:
        dict or None: Parsed JSON response body, or None on failure
    """
    date_str = target_date.strftime("%Y-%m-%d")
    request_body = {
        "startDate": date_str,
        "startInterval": 0,
        "endDate": date_str,
        "endInterval": INTERVALS_PER_DAY - 1,
        "columns": REPORT_COLUMNS,
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": THERMOSTAT_ID,
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(
            ECOBEE_REPORT_URL,
            headers=headers,
            params={"json": json.dumps(request_body)},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        # Ecobee embeds its own status code inside the JSON body
        status = data.get("status", {})
        if status.get("code", 0) != 0:
            local_logger.error(
                f"Ecobee API error {status.get('code')}: {status.get('message', '')}"
            )
            return None

        return data

    except requests.exceptions.HTTPError as e:
        local_logger.error(f"HTTP error fetching runtime report: {e}")
        if response.status_code == 401:
            local_logger.error("Authorization failed. Token may be invalid.")
        return None
    except Exception as e:
        local_logger.error(f"Failed to fetch runtime report: {str(e)[:100]}")
        return None


# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================


def parse_report_to_dataframe(report_response):
    """Parse the Ecobee runtime report API response into a DataFrame.

    The API returns each row as a comma-separated string with implicit
    'date' and 'time' fields prepended before the requested columns.
    Temperatures are stored as integers in tenths of °F and are converted
    to decimal °F during parsing.

    Parameters:
        report_response (dict): JSON response from the Ecobee runtime report API

    Returns:
        pandas.DataFrame or None: Parsed and converted data, or None on failure
    """
    try:
        report_list = report_response.get("reportList", [])
        if not report_list:
            local_logger.error("No report data in API response.")
            return None

        row_list = report_list[0].get("rowList", [])
        if not row_list:
            local_logger.error(
                "Report returned an empty rowList — thermostat may have been offline."
            )
            return None

        # The API always prepends 'date' and 'time' before the requested columns
        col_names = ["date", "time"] + REPORT_COLUMNS.split(",")
        expected_cols = len(col_names)

        records = []
        skipped = 0
        for row in row_list:
            values = row.split(",")
            if len(values) == expected_cols:
                records.append(values)
            else:
                skipped += 1

        if skipped > 0:
            local_logger.warning(f"Skipped {skipped} rows with unexpected column count.")

        if not records:
            local_logger.error("No valid rows parsed from runtime report.")
            return None

        df = pd.DataFrame(records, columns=col_names)

        # Combine date and time into a single datetime column
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], errors="coerce")
        df = df.drop(columns=["date", "time"])
        df = df[["datetime"] + [c for c in df.columns if c != "datetime"]]

        # Cast numeric columns (all except known string columns)
        numeric_cols = [c for c in df.columns if c not in STRING_COLUMNS]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")

        # Convert temperature columns from tenths of °F to °F
        for col in TEMP_COLUMNS:
            if col in df.columns:
                df[col] = df[col] / 10.0

        local_logger.info(f"Parsed {len(df)} intervals from runtime report.")
        return df

    except Exception as e:
        local_logger.error(f"Failed to parse report data: {str(e)[:100]}")
        return None


# ============================================================================
# FILE SAVE FUNCTIONS
# ============================================================================


def save_report_csv(df, dest_dir, target_date, network_logger=None):
    """Save a runtime report DataFrame as a dated CSV file.

    Creates a year-based subdirectory under dest_dir and writes the CSV.
    Skips silently if the file already exists (safe to re-run).

    Parameters:
        df (pandas.DataFrame): Runtime report data
        dest_dir (str): Root thermostat destination directory
        target_date (date): Date of the data (used for filename and subdirectory)
        network_logger (logging.Logger, optional): Logger for network log file

    Returns:
        bool: True if saved (or already existed), False on error
    """
    date_str = target_date.strftime("%Y-%m-%d")
    year_str = target_date.strftime("%Y")

    def log(level, msg):
        getattr(local_logger, level)(msg)
        if network_logger:
            getattr(network_logger, level)(msg)

    try:
        year_dir = os.path.join(dest_dir, year_str)
        if not os.path.exists(year_dir):
            os.makedirs(year_dir)
            log("info", f"Created directory: {year_dir}")

        csv_path = os.path.join(year_dir, f"{date_str}_thermostat.csv")

        if os.path.exists(csv_path):
            log("warning", f"File already exists, skipping: {csv_path}")
            return True

        df.to_csv(csv_path, index=False)
        log("info", f"Saved: {csv_path} ({len(df)} rows, {len(df.columns)} columns)")
        return True

    except Exception as e:
        log("error", f"Failed to save CSV for {date_str}: {str(e)[:100]}")
        return False


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Main execution block for Ecobee thermostat runtime report backup."""
    all_successful = True

    local_logger.info("-" * 40)
    local_logger.info("ECOBEE THERMOSTAT BACKUP")
    local_logger.info("-" * 40)

    # -----------------------------------------------------------------------
    # Check network path accessibility
    # -----------------------------------------------------------------------
    if check_network_path(THERMOSTAT_DEST):
        local_logger.info(f"Network path accessible: {THERMOSTAT_DEST}")
        network_logger = setup_network_logger("ecobee_thermostat", THERMOSTAT_LOG)
        if not network_logger:
            local_logger.warning(
                "Network logger setup failed — backup will proceed with local logging only."
            )
    else:
        local_logger.error(f"Network path NOT accessible: {THERMOSTAT_DEST}")
        local_logger.error("Backup skipped. Check network connection and drive mapping.")
        local_logger.warning("ECOBEE BACKUP SKIPPED — network unavailable.")
        local_logger.info("=" * 60)
        return

    # -----------------------------------------------------------------------
    # Authenticate
    # -----------------------------------------------------------------------
    local_logger.info(f"Loading Ecobee credentials from: {TOKEN_FILE_PATH}")
    access_token = get_valid_access_token(TOKEN_FILE_PATH)
    if not access_token:
        local_logger.error(
            "Authentication failed. Run ecobee_token_setup.py to create/renew tokens."
        )
        if network_logger:
            network_logger.error("Backup FAILED — authentication error.")
        local_logger.warning("ECOBEE BACKUP FAILED — authentication error.")
        local_logger.info("=" * 60)
        if network_logger:
            for handler in network_logger.handlers[:]:
                handler.close()
                network_logger.removeHandler(handler)
        return

    local_logger.info("Authentication successful.")

    # -----------------------------------------------------------------------
    # Determine target date
    # -----------------------------------------------------------------------
    if TARGET_DATE_OVERRIDE:
        target_date = datetime.strptime(TARGET_DATE_OVERRIDE, "%Y-%m-%d").date()
        local_logger.info(f"Using override target date: {target_date}")
    else:
        target_date = date.today() - timedelta(days=1)
        local_logger.info(f"Fetching runtime report for yesterday: {target_date}")

    if network_logger:
        network_logger.info(f"Ecobee thermostat backup started for {target_date}.")

    # -----------------------------------------------------------------------
    # Fetch runtime report from Ecobee API
    # -----------------------------------------------------------------------
    report_response = fetch_runtime_report(access_token, target_date)
    if not report_response:
        local_logger.error("Failed to retrieve runtime report from Ecobee API.")
        if network_logger:
            network_logger.error(f"Backup FAILED for {target_date} — API fetch error.")
        all_successful = False
    else:
        # -------------------------------------------------------------------
        # Parse response and save CSV
        # -------------------------------------------------------------------
        df = parse_report_to_dataframe(report_response)
        if df is None:
            all_successful = False
            if network_logger:
                network_logger.error(f"Backup FAILED for {target_date} — parse error.")
        else:
            success = save_report_csv(df, THERMOSTAT_DEST, target_date, network_logger)
            if not success:
                all_successful = False

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    if all_successful:
        local_logger.info("ECOBEE BACKUP COMPLETED SUCCESSFULLY")
        if network_logger:
            network_logger.info("Backup completed successfully.")
    else:
        local_logger.warning("ECOBEE BACKUP COMPLETED WITH ERRORS — Review log for details.")
        if network_logger:
            network_logger.warning("Backup completed with errors.")
    local_logger.info("=" * 60)

    # Close network logger handlers
    if network_logger:
        for handler in network_logger.handlers[:]:
            handler.close()
            network_logger.removeHandler(handler)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        local_logger.info("Backup interrupted by user.")
        local_logger.info("=" * 60)
    except Exception as e:
        # Catch any unexpected exception so the batch file always continues cleanly
        local_logger.error(f"Unexpected error in ecobee backup: {str(e)[:200]}")
        local_logger.warning("ECOBEE BACKUP FAILED — unexpected error. See log for details.")
        local_logger.info("=" * 60)
