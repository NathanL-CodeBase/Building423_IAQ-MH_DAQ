#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Continuous Weather Station DAQ Generator
========================================

Purpose: Read live data from Met One AIO2 sonic weather sensor via RS-485
serial connection and generate a daily DAQ file in the format expected by
the MH IAQ backup system. The script runs continuously, appending new
measurements to the current day's file and rotating at midnight.

The weather station DAQ system is currently offline, so this script provides
a direct serial-to-file bridge to maintain the expected data file format.

Author: Nathan Lima
Institution: NIST
Created: 2026-09-17
Update log:
    2026-09-17: Initial version.
    2026-09-17: Add rotating file handler alongside console logging, throttle
        repeated malformed-line warnings, and back off on repeated unexpected
        errors, so the process is safe to leave running unattended for months.

Output:
    - <outdoor_weather_path>/<year>/<date>-Daily_MHOutdoor_Data.txt
    Tab-delimited with columns: Date, Time, Wind_Speed_m/s,
    Wind_Direction_deg, Ambient_Temperature_degC, Relative_Humidity_%,
    Barometric_Pressure_mb
"""

import json
import logging
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import serial


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------
def load_config(config_file="data_config.json"):
    """
    Load configuration from data_config.json file.

    Parameters
    ----------
    config_file : str
        Path to configuration file. Searches in script directory and parent
        directories if relative.

    Returns
    -------
    dict
        Configuration dictionary.

    Raises
    ------
    FileNotFoundError
        If config file not found.
    """
    search_paths = [
        Path(config_file),
        Path(__file__).parent / config_file,
        Path(__file__).parent.parent / config_file,
    ]

    for config_path in search_paths:
        if config_path.exists():
            with open(config_path, "r") as f:
                return json.load(f)

    raise FileNotFoundError(
        f"Configuration file '{config_file}' not found. "
        f"Searched: {[str(p) for p in search_paths]}. "
        f"Create data_config.json from data_config.template.json."
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_PATH = Path(__file__).parent / "weather_daq.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# How often to summarize repeated malformed-line warnings, and the backoff
# schedule (seconds) applied to repeated unexpected errors, so a persistent
# fault (e.g. a full disk) cannot spin the loop and flood the log.
MALFORMED_LOG_INTERVAL_S = 60
ERROR_BACKOFF_SCHEDULE_S = [5, 10, 20, 40, 60]


# ---------------------------------------------------------------------------
# Serial parsing
# ---------------------------------------------------------------------------
FIELD_NAMES = [
    "wind_speed",
    "wind_direction",
    "air_temp",
    "relative_humidity",
    "barometric_pressure",
    "rain",
    "solar_radiation",
    "battery_voltage",
    "compass_heading",
    "config",
    "checksum",
]


def parse_line(raw_line):
    """
    Parse one AIO 2 output line into labeled fields.

    Parameters
    ----------
    raw_line : str
        Decoded line from sensor.

    Returns
    -------
    dict or None
        Mapping of field name to value, or None if field count mismatches.
    """
    parts = raw_line.strip().split(",")
    if len(parts) != len(FIELD_NAMES):
        return None
    return dict(zip(FIELD_NAMES, parts))


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------
def get_output_path(base_dir, date_str, file_template):
    """
    Build output file path for current date.

    Parameters
    ----------
    base_dir : Path
        Base directory for weather data.
    date_str : str
        Date string YYYYMMDD.
    file_template : str
        Template with {date_str} placeholder.

    Returns
    -------
    Path
        Full path to output file. The year directory is created if needed.
    """
    filename = file_template.format(date_str=date_str)
    year_dir = base_dir / date_str[:4]
    year_dir.mkdir(parents=True, exist_ok=True)
    return year_dir / filename


def write_header(file_handle):
    """
    Write header line to new DAQ file.

    Parameters
    ----------
    file_handle : file object
        Open file handle.
    """
    header = "\t".join(
        [
            "Date",
            "Time",
            "Wind_Speed_m/s",
            "Wind_Direction_deg",
            "Ambient_Temperature_degC",
            "Relative_Humidity_%",
            "Barometric_Pressure_mb",
        ]
    )
    file_handle.write(header + "\n")
    file_handle.flush()


def write_row(file_handle, timestamp, fields):
    """
    Write one measurement row.

    Parameters
    ----------
    file_handle : file object
        Open file handle.
    timestamp : datetime
        Current timestamp.
    fields : dict
        Parsed sensor fields.
    """
    date_str = timestamp.strftime("%m/%d/%Y")
    time_str = timestamp.strftime("%H:%M:%S")
    row = [
        date_str,
        time_str,
        fields.get("wind_speed", ""),
        fields.get("wind_direction", ""),
        fields.get("air_temp", ""),
        fields.get("relative_humidity", ""),
        fields.get("barometric_pressure", ""),
    ]
    file_handle.write("\t".join(row) + "\n")
    file_handle.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)

    logger = logging.getLogger("weather_daq")
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    # Load config
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Paths
    local_sources = config.get("local_sources", {})
    outdoor_cfg = local_sources.get("outdoor_weather", {})
    outdoor_path_str = outdoor_cfg.get("path")
    if not outdoor_path_str:
        logger.error("outdoor_weather path not configured in data_config.json")
        sys.exit(1)
    outdoor_path = Path(outdoor_path_str).expanduser()

    instruments = config.get("instruments", {})
    aio2_cfg = instruments.get("AIO2", {})
    file_template = aio2_cfg.get("file_template", "{date_str}-Daily_MHOutdoor_Data.txt")

    # Serial settings
    COM_PORT = "COM5"
    BAUD_RATE = 9600
    SERIAL_TIMEOUT_S = 2.0

    logger.info(f"Output directory: {outdoor_path}")
    logger.info(f"Serial port: {COM_PORT} @ {BAUD_RATE} baud")

    # Ensure output directory exists
    outdoor_path.mkdir(parents=True, exist_ok=True)

    current_date_str = None
    file_handle = None
    malformed_count = 0
    malformed_window_start = time.monotonic()
    consecutive_errors = 0

    def open_new_file(date_str):
        nonlocal file_handle
        if file_handle:
            file_handle.close()
        out_path = get_output_path(outdoor_path, date_str, file_template)
        file_handle = open(out_path, "a", encoding="utf-8", newline="")
        # Write header if file is new
        if file_handle.tell() == 0:
            write_header(file_handle)
            logger.info(f"Created new file: {out_path}")
        else:
            logger.info(f"Appending to existing file: {out_path}")
        return out_path

    # Open serial connection with retry
    ser = None
    while True:
        try:
            if ser is None:
                logger.info(f"Opening {COM_PORT}...")
                ser = serial.Serial(
                    port=COM_PORT,
                    baudrate=BAUD_RATE,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=SERIAL_TIMEOUT_S,
                )
                logger.info(f"{COM_PORT} opened")

            while True:
                # Rotate file at midnight
                now = datetime.now()
                date_str = now.strftime("%Y%m%d")
                if date_str != current_date_str:
                    current_date_str = date_str
                    open_new_file(date_str)

                raw_bytes = ser.readline()
                if not raw_bytes:
                    logger.debug("No data received in timeout window")
                    continue

                raw_line = raw_bytes.decode("ascii", errors="replace").strip()
                if not raw_line:
                    continue

                fields = parse_line(raw_line)
                if fields is None:
                    malformed_count += 1
                    elapsed_s = time.monotonic() - malformed_window_start
                    if elapsed_s >= MALFORMED_LOG_INTERVAL_S:
                        logger.warning(
                            f"{malformed_count} malformed line(s) in the last "
                            f"{elapsed_s:.0f}s (most recent field count "
                            f"{len(raw_line.split(','))}, expected "
                            f"{len(FIELD_NAMES)})"
                        )
                        malformed_count = 0
                        malformed_window_start = time.monotonic()
                    continue

                write_row(file_handle, now, fields)
                logger.debug(f"Wrote row at {now}")
                consecutive_errors = 0

        except serial.SerialException as e:
            logger.error(f"Serial error: {e}")
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
            logger.info("Retrying serial connection in 5 seconds...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            backoff_s = ERROR_BACKOFF_SCHEDULE_S[
                min(consecutive_errors, len(ERROR_BACKOFF_SCHEDULE_S) - 1)
            ]
            consecutive_errors += 1
            logger.error(f"Unexpected error: {e}. Retrying in {backoff_s}s.")
            time.sleep(backoff_s)

    # Cleanup
    if ser and ser.is_open:
        ser.close()
        logger.info(f"{COM_PORT} closed")
    if file_handle:
        file_handle.close()
        logger.info("File closed")


if __name__ == "__main__":
    main()
