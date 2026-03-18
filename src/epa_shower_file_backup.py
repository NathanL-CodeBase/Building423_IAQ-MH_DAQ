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
local_logger = logging.getLogger("epa_shower_backup")
local_logger.setLevel(logging.INFO)

# Print to console (captured by batch file's log redirection)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
local_logger.addHandler(console_handler)

local_logger.info("=" * 60)
local_logger.info("EPA Shower Backup Script started")

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
epa_config = remote_destinations.get("epa_shower", {})

archive_year = epa_config.get("archive_year", 2026)

# Construct EPA shower backup paths with year subdirectory
epa_base = epa_config.get("base_path")
epa_folders = epa_config.get("folders", {})

# Local sources should point to year subdirectory
indoor_source = (
    os.path.join(local_sources.get("indoor_daq", {}).get("path", ""), str(archive_year))
    if local_sources.get("indoor_daq", {}).get("path")
    else None
)

weather_source = (
    os.path.join(local_sources.get("outdoor_weather", {}).get("path", ""), str(archive_year))
    if local_sources.get("outdoor_weather", {}).get("path")
    else None
)

# Remote destinations should point to year subdirectory
indoor_dest = (
    os.path.join(epa_base, epa_folders.get("indoor_daq", "indoor_daq"), str(archive_year))
    if epa_base
    else None
)
weather_dest = (
    os.path.join(epa_base, epa_folders.get("weather_station", "weather_station"), str(archive_year))
    if epa_base
    else None
)

indoor_log = (
    os.path.join(epa_base, epa_folders.get("indoor_daq", "indoor_daq"), "backup_log_indoor.txt")
    if epa_base
    else None
)
weather_log = (
    os.path.join(
        epa_base, epa_folders.get("weather_station", "weather_station"), "backup_log_weather.txt"
    )
    if epa_base
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

local_logger.info(f"EPA Shower backup operating on archive year: {archive_year}")


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
    Main execution block for EPA Shower data backup.

    Sets up separate loggers for indoor DAQ and weather station data, then
    performs sequential backups of both data sources (2026 only) to their
    respective network locations. Each backup operation is logged independently.
    """

    # Track overall success
    all_successful = True

    # -----------------------------------------------------------------------
    # Indoor DAQ Backup (2026)
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("INDOOR DAQ BACKUP (2026)")
    local_logger.info("-" * 40)

    # Check network accessibility
    if check_network_path(indoor_dest):
        local_logger.info(f"Network path accessible: {indoor_dest}")
        indoor_logger = setup_network_logger("epa_indoor_daq", indoor_log)
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
    if indoor_logger:
        indoor_logger.info("Indoor DAQ backup (2026) started.")
        copied, skipped, errs = backup_files(indoor_source, indoor_dest, indoor_logger)
        local_logger.info(
            f"Indoor DAQ complete: {copied} copied, {skipped} unchanged, {errs} errors"
        )
        if indoor_logger:
            indoor_logger.info(
                f"Backup completed: {copied} copied, {skipped} unchanged, {errs} errors"
            )
        if errs > 0:
            all_successful = False

    # -----------------------------------------------------------------------
    # Weather Station Backup (2026)
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    local_logger.info("WEATHER STATION BACKUP (2026)")
    local_logger.info("-" * 40)

    # Check network accessibility
    if check_network_path(weather_dest):
        local_logger.info(f"Network path accessible: {weather_dest}")
        weather_logger = setup_network_logger("epa_weather_station", weather_log)
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
    if weather_logger:
        weather_logger.info("Weather station backup (2026) started.")
        copied, skipped, errs = backup_files(weather_source, weather_dest, weather_logger)
        local_logger.info(
            f"Weather station complete: {copied} copied, {skipped} unchanged, {errs} errors"
        )
        if weather_logger:
            weather_logger.info(
                f"Backup completed: {copied} copied, {skipped} unchanged, {errs} errors"
            )
        if errs > 0:
            all_successful = False

    # -----------------------------------------------------------------------
    # Final Summary
    # -----------------------------------------------------------------------
    local_logger.info("-" * 40)
    if all_successful:
        local_logger.info("ALL EPA SHOWER BACKUPS COMPLETED SUCCESSFULLY")
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
