#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NIST WUI Smoke IAQ Mitigation Project Data Backup Script
=========================================================

This script performs a targeted backup of indoor DAQ and outdoor weather data
from local desktop folders to the NIST WUI Smoke IAQ Mitigation project network
share (Elwood drive). It backs up two types of data:
    1. Indoor DAQ data from Task Logger (cDAQ-9178 chassis)
    2. Outdoor weather station data (Met One AIO2 serial logger)

Unlike mh_daq_file_backup.py (which copies all data to the mission drive), this
script copies only files dated on or after a configurable start_date. The WUI
smoke campaign deployed with its first burn on 2026-07-31; pre-deployment files
are moved manually and are not handled here. The project has no set end date, so
there is no end-date filter.

The backup destination feeds the data processing in the
NIST_wui-smoke-iaq-mitigation repository.

The script performs incremental backups by comparing file modification times,
only copying files that are new or have been updated since the last backup.

Start-Date Filter:
    Files are selected by the YYYYMMDD date prefix in their filename (the DAQ
    and weather loggers both name files with a leading date, see
    docs/instruments/INSTRUMENT_DOCUMENTATION.md). Only files whose date prefix
    is on or after remote_destinations.wui_smoke.start_date are copied. Files
    without a parseable YYYYMMDD prefix are copied (to avoid silently dropping
    metadata or config files); log this behavior so nothing is missed.

Live-File Safety:
    Data files for the current calendar day are skipped by default. The DAQ
    system writes to the current day's file continuously throughout the day,
    and copying an open/active file can produce a truncated or corrupt backup.
    Each scheduled run therefore captures only completed files (previous days).

    To include today's partial file (e.g., for manual troubleshooting or to
    verify recent data is present on the network drive), run with the flag:

        python wui_smoke_file_backup.py --include-today

All source and destination paths are loaded from data_config.json (not hardcoded).
See data_config.template.json for the expected configuration structure.

Output Files:
    - <wui_base>/MH_DAQ_indoor/:                    Incremental copy of Task Logger output
    - <wui_base>/MH_DAQ_weather/:                   Incremental copy of AIO2 weather data
    - <wui_base>/MH_DAQ_indoor/backup_log_indoor.txt:    Indoor backup activity log
    - <wui_base>/MH_DAQ_weather/backup_log_weather.txt:  Weather backup activity log

Author: Nathan Lima
Institution: NIST
Date: 2026
"""

import argparse
import json
import logging
import os
import shutil
from datetime import date, datetime
from pathlib import Path


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
        Path(__file__).parent.parent / config_file,  # Repo root
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


# ---------------------------------------------------------------------------
# Console logging setup (output captured by batch file)
# ---------------------------------------------------------------------------
local_logger = logging.getLogger("wui_smoke_backup")
local_logger.setLevel(logging.INFO)

# Print to console (captured by batch file's log redirection)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
local_logger.addHandler(console_handler)

local_logger.info("=" * 60)
local_logger.info("WUI Smoke Backup Script started")

# ---------------------------------------------------------------------------
# File path definitions from configuration
# ---------------------------------------------------------------------------
local_logger.info("Loading configuration...")
try:
    config = load_config()
    local_logger.info(f"Loaded configuration: {config.get('project_name', 'Unknown Project')}")
except Exception as e:
    local_logger.error(f"Failed to load configuration: {e}")
    raise

# Extract paths from config
local_sources = config.get("local_sources", {})
remote_destinations = config.get("remote_destinations", {})
wui_config = remote_destinations.get("wui_smoke", {})

# start_date bounds the copy (deployment date onward). Parsed once here so an
# invalid value fails fast rather than silently copying everything.
start_date_str = wui_config.get("start_date")
start_date = None
if start_date_str:
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(
            f"Invalid start_date '{start_date_str}' in remote_destinations.wui_smoke "
            f"(expected YYYY-MM-DD): {e}"
        )

# Construct WUI smoke backup paths
wui_base = wui_config.get("base_path")
wui_folders = wui_config.get("folders", {})

indoor_source = local_sources.get("indoor_daq", {}).get("path")
weather_source = local_sources.get("outdoor_weather", {}).get("path")

indoor_dest = (
    os.path.join(wui_base, wui_folders.get("indoor_daq", "MH_DAQ_indoor")) if wui_base else None
)
weather_dest = (
    os.path.join(wui_base, wui_folders.get("weather_station", "MH_DAQ_weather"))
    if wui_base
    else None
)

indoor_log = (
    os.path.join(wui_base, wui_folders.get("indoor_daq", "MH_DAQ_indoor"), "backup_log_indoor.txt")
    if wui_base
    else None
)
weather_log = (
    os.path.join(
        wui_base, wui_folders.get("weather_station", "MH_DAQ_weather"), "backup_log_weather.txt"
    )
    if wui_base
    else None
)

# Validate required paths are configured
required_paths = {
    "indoor_source": indoor_source,
    "weather_source": weather_source,
    "indoor_dest": indoor_dest,
    "weather_dest": weather_dest,
}

local_logger.info("Validating configuration paths...")
for path_name, path_value in required_paths.items():
    if not path_value:
        raise ValueError(f"Configuration missing required path: {path_name}")
    local_logger.info(f"  {path_name}: {path_value}")

if start_date:
    local_logger.info(f"WUI Smoke backup start_date filter: {start_date.isoformat()} (inclusive)")
else:
    local_logger.warning(
        "No start_date configured in remote_destinations.wui_smoke — copying ALL files. "
        "Set start_date (YYYY-MM-DD) to bound the copy to the campaign period."
    )


def file_date_prefix(filename):
    """
    Parse the leading YYYYMMDD date from a data filename.

    The DAQ Task Logger and Met One AIO2 weather logger both name output files
    with a leading YYYYMMDD date (see INSTRUMENT_DOCUMENTATION.md, Date Format
    %Y%m%d). This reads the first 8 characters and interprets them as a date.

    Args:
        filename (str): The bare filename (not a full path)

    Returns:
        datetime.date or None: The parsed date, or None if the first 8
            characters are not a valid YYYYMMDD date.
    """
    prefix = filename[:8]
    if len(prefix) < 8 or not prefix.isdigit():
        return None
    try:
        return datetime.strptime(prefix, "%Y%m%d").date()
    except ValueError:
        return None


def check_network_path(path):
    """
    Check if a network path is accessible.

    Walks up the directory tree to find any existing parent directory,
    which indicates the network share is reachable. This allows the
    backup to proceed and create missing subdirectories.

    Args:
        path (str): Network path to check

    Returns:
        bool: True if accessible, False otherwise
    """
    try:
        # Walk up the path tree to find any existing parent
        # This proves the network is reachable even if subdirectories don't exist yet
        current = path
        while current:
            if os.path.exists(current):
                return True
            parent = os.path.dirname(current)
            # Stop if we've reached the root (path stops changing)
            if parent == current:
                break
            current = parent
        return False
    except Exception as e:
        local_logger.error(f"Error checking network path {path}: {e}")
        return False


def setup_network_logger(name, log_path):
    """
    Set up a logger that writes to a network location.

    Args:
        name (str): Logger name
        log_path (str): Path to the log file on the network

    Returns:
        logging.Logger or None: Configured logger, or None if setup fails
    """
    try:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        # Clear existing handlers to prevent accumulation
        logger.handlers.clear()
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        logger.addHandler(handler)
        return logger
    except Exception as e:
        local_logger.error(f"Failed to set up network logger at {log_path}: {e}")
        return None


def backup_files(src, dest, network_logger=None, skip_today=True, start=None):
    """
    Perform incremental backup of files from source to destination directory.

    This function recursively walks through the source directory and copies files
    to the destination, preserving the directory structure. Only files that are
    new or have been modified (based on modification time) are copied to minimize
    unnecessary transfers.

    Two selection filters run before the incremental check:

    1. start_date: files whose leading YYYYMMDD prefix is before `start` are
       skipped. Files without a parseable date prefix are kept (and logged) so
       metadata/config files are not silently dropped.

    2. Live-file safety: files whose name begins with today's date string
       (YYYYMMDD) are excluded by default. The DAQ system is actively writing to
       the current day's file, and copying it mid-write can produce a truncated
       or corrupt backup copy. Pass skip_today=False (via --include-today) to
       override.

    Args:
        src (str): Source directory path to backup from
        dest (str): Destination directory path to backup to
        network_logger (logging.Logger, optional): Logger for network log file
        skip_today (bool): If True (default), silently skip files whose name
            starts with today's date (YYYYMMDD). Set False via --include-today
            to copy the current day's in-progress file.
        start (datetime.date, optional): If set, skip files whose YYYYMMDD name
            prefix is before this date.

    Returns:
        tuple: (files_copied, files_skipped, errors)
    """
    files_copied = 0
    files_skipped = 0
    errors = 0

    today_prefix = date.today().strftime("%Y%m%d") if skip_today else None

    def log_message(level, message):
        """Log to both local and network loggers."""
        if level == "info":
            local_logger.info(message)
            if network_logger:
                network_logger.info(message)
        elif level == "error":
            local_logger.error(message)
            if network_logger:
                network_logger.error(message)

    try:
        # Validate source directory exists
        if not os.path.exists(src):
            log_message("error", f"Source folder does not exist: {src}")
            return (0, 0, 1)

        # Create destination directory if it doesn't exist
        if not os.path.exists(dest):
            os.makedirs(dest)
            log_message("info", f"Created destination folder: {dest}")

        # Walk through source directory tree
        for root, _dirs, files in os.walk(src):
            # Recreate source directory structure in destination
            dest_dir = os.path.join(dest, os.path.relpath(root, src))
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
                log_message("info", f"Created directory: {dest_dir}")

            # Process each file in current directory
            for file in files:
                # Skip today's live file — the DAQ system is still writing to it
                if today_prefix and file.startswith(today_prefix):
                    continue

                # Apply start_date filter using the file's YYYYMMDD name prefix
                if start is not None:
                    fdate = file_date_prefix(file)
                    if fdate is None:
                        log_message(
                            "info", f"No date prefix, copying anyway: {file}"
                        )
                    elif fdate < start:
                        files_skipped += 1
                        continue

                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_dir, file)

                # Perform incremental backup based on modification time
                if os.path.exists(dest_file):
                    # Compare modification times
                    src_mtime = os.path.getmtime(src_file)
                    dest_mtime = os.path.getmtime(dest_file)

                    # Copy only if source file is newer
                    if src_mtime > dest_mtime:
                        try:
                            shutil.copy2(src_file, dest_file)
                            log_message("info", f"Copied (updated): {file}")
                            files_copied += 1
                        except Exception as e:
                            log_message("error", f"Error copying {src_file}: {e}")
                            errors += 1
                    else:
                        files_skipped += 1
                else:
                    # File doesn't exist in destination, copy it
                    try:
                        shutil.copy2(src_file, dest_file)
                        log_message("info", f"Copied (new file): {file}")
                        files_copied += 1
                    except Exception as e:
                        log_message("error", f"Error copying {src_file}: {e}")
                        errors += 1

    except Exception as e:
        log_message("error", f"An error occurred during the backup process: {e}")
        errors += 1

    return (files_copied, files_skipped, errors)


def main():
    """
    Main execution block for WUI Smoke data backup.

    Parses the --include-today command-line flag, then sets up separate loggers
    for indoor DAQ and weather station data and performs sequential backups of
    both data sources to their respective network locations on the Elwood drive.
    Only files dated on or after remote_destinations.wui_smoke.start_date are
    copied.

    By default, today's data files are excluded from backup because the DAQ
    system is still writing to them. Pass --include-today to override.
    """
    parser = argparse.ArgumentParser(
        description="Incremental backup of MH DAQ data (deployment date onward) to the WUI Smoke network share."
    )
    parser.add_argument(
        "--include-today",
        action="store_true",
        default=False,
        help=(
            "Include today's data files in the backup. By default these are skipped "
            "because the DAQ system is still writing to them — copying an open file "
            "can produce a truncated or corrupt backup copy."
        ),
    )
    args = parser.parse_args()
    skip_today = not args.include_today

    # Track overall success
    all_successful = True

    # -----------------------------------------------------------------------
    # Indoor DAQ Backup
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("INDOOR DAQ BACKUP")
    local_logger.info("-" * 40)

    # Check network accessibility
    if check_network_path(indoor_dest):
        local_logger.info(f"Network path accessible: {indoor_dest}")
        indoor_logger = setup_network_logger("wui_indoor_daq", indoor_log)
        if not indoor_logger:
            local_logger.warning(
                "Network logger setup failed, but backup will proceed with local logging only"
            )
    else:
        local_logger.error(f"Network path NOT accessible: {indoor_dest}")
        local_logger.error("Backup will be skipped. Check network connection.")
        indoor_logger = None
        all_successful = False

    # Perform backup if network is accessible
    if check_network_path(indoor_dest):
        if indoor_logger:
            indoor_logger.info("Indoor DAQ backup started.")
        copied, skipped, errs = backup_files(
            indoor_source, indoor_dest, indoor_logger, skip_today, start_date
        )
        local_logger.info(
            f"Indoor DAQ complete: {copied} copied, {skipped} skipped, {errs} errors"
        )
        if indoor_logger:
            indoor_logger.info(
                f"Backup completed: {copied} copied, {skipped} skipped, {errs} errors"
            )
        if errs > 0:
            all_successful = False

    # -----------------------------------------------------------------------
    # Weather Station Backup
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("WEATHER STATION BACKUP")
    local_logger.info("-" * 40)

    # Check network accessibility
    if check_network_path(weather_dest):
        local_logger.info(f"Network path accessible: {weather_dest}")
        weather_logger = setup_network_logger("wui_weather_station", weather_log)
        if not weather_logger:
            local_logger.warning(
                "Network logger setup failed, but backup will proceed with local logging only"
            )
    else:
        local_logger.error(f"Network path NOT accessible: {weather_dest}")
        local_logger.error("Backup will be skipped. Check network connection.")
        weather_logger = None
        all_successful = False

    # Perform backup if network is accessible
    if check_network_path(weather_dest):
        if weather_logger:
            weather_logger.info("Weather station backup started.")
        copied, skipped, errs = backup_files(
            weather_source, weather_dest, weather_logger, skip_today, start_date
        )
        local_logger.info(
            f"Weather station complete: {copied} copied, {skipped} skipped, {errs} errors"
        )
        if weather_logger:
            weather_logger.info(
                f"Backup completed: {copied} copied, {skipped} skipped, {errs} errors"
            )
        if errs > 0:
            all_successful = False

    # -----------------------------------------------------------------------
    # Final Summary
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    if all_successful:
        local_logger.info("ALL WUI SMOKE BACKUPS COMPLETED SUCCESSFULLY")
    else:
        local_logger.warning("BACKUPS COMPLETED WITH ERRORS - Review log for details")
    local_logger.info("=" * 60)

    # -----------------------------------------------------------------------
    # Cleanup - Close all logger handlers
    # -----------------------------------------------------------------------
    for logger in [indoor_logger, weather_logger]:
        if logger:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)


if __name__ == "__main__":
    main()
