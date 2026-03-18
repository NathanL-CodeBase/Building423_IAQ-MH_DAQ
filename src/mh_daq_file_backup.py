# %%
"""
Instrument Data Backup Script
==============================

This script performs automated backups of instrument data from local desktop folders
to network storage locations. It backs up two types of data:
    1. Indoor DAQ data from Task Logger (cDAQ-9178 chassis)
    2. Outdoor weather station data (Met One AIO2 serial logger)

The script performs incremental backups by comparing file modification times,
only copying files that are new or have been updated since the last backup.
A single consolidated backup log is maintained at the mission network root.

All source and destination paths are loaded from data_config.json (not hardcoded).
See data_config.template.json for the expected configuration structure.

Output Files:
    - <mission_base>/backup_log.txt:              Consolidated backup activity log
    - <mission_base>/indoor_daq/:                 Incremental copy of Task Logger output
    - <mission_base>/weather_station/:            Incremental copy of AIO2 weather data

Author: Nathan Lima
Institution: NIST
Last Modified: 2026-01-05
"""

import json
import logging
import os
import shutil
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


# ---------------------------------------------------------------------------
# Console logging setup (output captured by batch file)
# ---------------------------------------------------------------------------
local_logger = logging.getLogger("local_backup")
local_logger.setLevel(logging.INFO)

# Print to console (captured by batch file's log redirection)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
local_logger.addHandler(console_handler)

local_logger.info("=" * 60)
local_logger.info("Script started")

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
mission_config = remote_destinations.get("mission", {})

indoor_source = local_sources.get("indoor_daq", {}).get("path")
weather_source = local_sources.get("outdoor_weather", {}).get("path")

mission_base = mission_config.get("base_path")
mission_folders = mission_config.get("folders", {})

indoor_dest = (
    os.path.join(mission_base, mission_folders.get("indoor_daq", "indoor_daq"))
    if mission_base
    else None
)
weather_dest = (
    os.path.join(mission_base, mission_folders.get("weather_station", "weather_station"))
    if mission_base
    else None
)

# Consolidated backup log at the mission network root (filename from config)
mission_log_filename = mission_config.get("log_file", "backup_log.txt")
mission_log = os.path.join(mission_base, mission_log_filename) if mission_base else None

# Validate required paths are configured
required_paths = {
    "indoor_source": indoor_source,
    "weather_source": weather_source,
    "indoor_dest": indoor_dest,
    "weather_dest": weather_dest,
    "mission_log": mission_log,
}

local_logger.info("Validating configuration paths...")
for path_name, path_value in required_paths.items():
    if not path_value:
        raise ValueError(f"Configuration missing required path: {path_name}")
    local_logger.info(f"  {path_name}: {path_value}")


def check_network_path(path):
    """
    Check if a network path is accessible.

    Args:
        path (str): Network path to check

    Returns:
        bool: True if accessible, False otherwise
    """
    try:
        # For network paths, check if the parent directory exists
        # This avoids issues if the specific folder hasn't been created yet
        parent = os.path.dirname(path)
        if os.path.exists(parent):
            return True
        # If parent doesn't exist, try the path itself
        return os.path.exists(path)
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


def backup_files(src, dest, network_logger=None):
    """
    Perform incremental backup of files from source to destination directory.

    This function recursively walks through the source directory and copies files
    to the destination, preserving the directory structure. Only files that are
    new or have been modified (based on modification time) are copied to minimize
    unnecessary transfers.

    Args:
        src (str): Source directory path to backup from
        dest (str): Destination directory path to backup to
        network_logger (logging.Logger, optional): Logger for network log file

    Returns:
        tuple: (files_copied, files_skipped, errors)
    """
    files_copied = 0
    files_skipped = 0
    errors = 0

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
    Main execution block for instrument data backup.

    Sets up a single consolidated network logger at the mission base path, then
    performs sequential backups of both the indoor DAQ and weather station data.
    Both operations write to the same network log file (backup_log.txt at the
    mission root, as configured in data_config.json).
    """

    # Track overall success across both backup operations
    all_successful = True

    # -----------------------------------------------------------------------
    # Set up consolidated mission network logger
    # -----------------------------------------------------------------------
    if check_network_path(mission_base):
        local_logger.info(f"Mission network path accessible: {mission_base}")
        network_logger = setup_network_logger("mission_backup", mission_log)
        if not network_logger:
            local_logger.warning(
                "Network logger setup failed — backup will proceed with local logging only."
            )
    else:
        local_logger.error(f"Mission network path NOT accessible: {mission_base}")
        local_logger.error("All backups will be skipped. Check network connection.")
        local_logger.warning("BACKUPS SKIPPED — network unavailable.")
        local_logger.info("=" * 60)
        return

    network_logger.info("=" * 40)
    network_logger.info("MH DAQ backup session started.")

    # -----------------------------------------------------------------------
    # Indoor DAQ Backup
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("INDOOR DAQ BACKUP")
    local_logger.info("-" * 40)
    network_logger.info("Indoor DAQ backup started.")

    copied, skipped, errs = backup_files(indoor_source, indoor_dest, network_logger)
    local_logger.info(
        f"Indoor DAQ complete: {copied} copied, {skipped} unchanged, {errs} errors"
    )
    network_logger.info(
        f"Indoor DAQ complete: {copied} copied, {skipped} unchanged, {errs} errors"
    )
    if errs > 0:
        all_successful = False

    # -----------------------------------------------------------------------
    # Weather Station Backup
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("WEATHER STATION BACKUP")
    local_logger.info("-" * 40)
    network_logger.info("Weather station backup started.")

    copied, skipped, errs = backup_files(weather_source, weather_dest, network_logger)
    local_logger.info(
        f"Weather station complete: {copied} copied, {skipped} unchanged, {errs} errors"
    )
    network_logger.info(
        f"Weather station complete: {copied} copied, {skipped} unchanged, {errs} errors"
    )
    if errs > 0:
        all_successful = False

    # -----------------------------------------------------------------------
    # Final Summary
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    if all_successful:
        local_logger.info("ALL BACKUPS COMPLETED SUCCESSFULLY")
        network_logger.info("Backup session completed successfully.")
    else:
        local_logger.warning("BACKUPS COMPLETED WITH ERRORS — Review log for details.")
        network_logger.warning("Backup session completed with errors.")
    network_logger.info("=" * 40)
    local_logger.info("=" * 60)

    # -----------------------------------------------------------------------
    # Cleanup — Close network logger handlers
    # -----------------------------------------------------------------------
    for handler in network_logger.handlers[:]:
        handler.close()
        network_logger.removeHandler(handler)


if __name__ == "__main__":
    main()
