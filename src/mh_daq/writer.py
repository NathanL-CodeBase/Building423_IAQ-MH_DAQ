#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily file writer for the MH DAQ system.

Purpose: Write the indoor raw file, the indoor SI file, and the outdoor weather
    file as tab-delimited daily files with a single header row carrying units.
    Write a per-day JSON metadata sidecar describing each column, and a
    latest-values JSON snapshot rewritten every record for the status tool and
    the future Mission publish. Local disk is the primary write; files are
    flushed each record and rotate at local midnight.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Single-header SI columns with units baked into
        names, plain names in the raw file, thermocouple raw columns labeled
        degC. Snapshot written atomically via a temp file and replace.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from .config import ThermocoupleChannel, VoltageChannel
from .scaling import si_unit_for_channel

_DATE_FMT = "%m/%d/%Y"
_TIME_FMT = "%H:%M:%S"
_FILE_DATE_FMT = "%Y%m%d"


def _raw_unit_for_channel(channel):
    """Raw-file unit for a channel.

    Voltage channels are volts. Thermocouple channels have no voltage form
    through the NI 9213 driver, so their raw value is degC. Labeled so the raw
    file is not misread as pure volts.
    """
    if isinstance(channel, VoltageChannel):
        return "V"
    if isinstance(channel, ThermocoupleChannel):
        return "degC"
    raise TypeError(f"Unhandled channel type for '{channel.name}'.")


def _si_header_name(channel, config):
    """SI column name with unit suffix, for example T_Gar_M5_C4_degC."""
    unit = si_unit_for_channel(channel, config)
    return f"{channel.name}_{_sanitize_unit(unit)}"


def _raw_header_name(channel):
    """Raw column name with unit suffix, for example dP_Liv-Hi_M1_C0_V."""
    return f"{channel.name}_{_sanitize_unit(_raw_unit_for_channel(channel))}"


def _sanitize_unit(unit):
    """Make a unit safe for a column name: no slashes or spaces.

    m3/h -> m3h, W/m2 -> Wm2, percent stays percent. Keeps a single header row
    parseable without quoting.
    """
    return unit.replace("/", "").replace(" ", "")


class DailyWriter:
    """Writes the three daily files, the sidecar, and the snapshot.

    Parameters
    ----------
    config : SystemConfig
    base_dir : Path, optional
        Root for output. Defaults to the local_data_dir from config. Files are
        placed under base_dir/YYYY/.
    """

    def __init__(self, config, base_dir=None):
        self._config = config
        self._base = Path(base_dir) if base_dir else config.local.local_data_dir
        self._naming = config.local.file_naming
        self._current_date = None
        self._fh = {}  # key -> open file handle
        self._lock = threading.Lock()  # serializes roll and writes across threads

        # Precompute header column lists in task order.
        self._si_cols = [_si_header_name(c, config) for c in config.channels]
        self._raw_cols = [_raw_header_name(c) for c in config.channels]
        self._out_cols = [col.header for col in config.aio2.output_columns]
        self._out_fields = [col.field for col in config.aio2.output_columns]

    # -- paths --
    def _day_dir(self, date_str):
        d = self._base / date_str[:4]
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, key, date_str):
        name = self._naming[key].format(date=date_str)
        return self._day_dir(date_str) / name

    def _snapshot_path(self):
        self._base.mkdir(parents=True, exist_ok=True)
        return self._base / "latest_snapshot.json"

    # -- lifecycle --
    def _roll(self, now):
        """Rotate to a new day: close old handles, open new files, write headers."""
        date_str = now.strftime(_FILE_DATE_FMT)
        if date_str == self._current_date:
            return
        self._close_handles()
        self._current_date = date_str

        raw_path = self._path("indoor_raw", date_str)
        si_path = self._path("indoor_si", date_str)
        out_path = self._path("outdoor", date_str)

        self._fh["raw"] = self._open_with_header(raw_path, ["Date", "Time"] + self._raw_cols)
        self._fh["si"] = self._open_with_header(si_path, ["Date", "Time"] + self._si_cols)
        self._fh["out"] = self._open_with_header(out_path, ["Date", "Time"] + self._out_cols)
        self._write_sidecar(date_str)

    def _open_with_header(self, path, header_cols):
        """Open in append mode; write the header only if the file is new."""
        fh = open(path, "a", encoding="utf-8", newline="")
        if fh.tell() == 0:
            fh.write("\t".join(header_cols) + "\n")
            fh.flush()
        return fh

    def _write_sidecar(self, date_str):
        """Write a JSON sidecar describing every column for this day's files."""
        cols = []
        for ch in self._config.channels:
            entry = {
                "channel": ch.name,
                "physical_channel": ch.physical_channel,
                "raw_unit": _raw_unit_for_channel(ch),
                "si_unit": si_unit_for_channel(ch, self._config),
                "si_column": _si_header_name(ch, self._config),
                "raw_column": _raw_header_name(ch),
            }
            if isinstance(ch, VoltageChannel):
                s = self._config.scales[ch.scale]
                entry["scale"] = ch.scale
                entry["slope"] = s.slope
                entry["intercept"] = s.intercept
                entry["si_factor"] = s.si_factor
                entry["si_offset"] = s.si_offset
            elif isinstance(ch, ThermocoupleChannel):
                entry["thermocouple_type"] = ch.thermocouple_type
            cols.append(entry)

        sidecar = {
            "date": date_str,
            "config_version": self._config.config_version,
            "note": (
                "Raw file: volts for voltage channels, degC for "
                "thermocouples (NI 9213 returns temperature). SI file: "
                "units in each column name. inch WC to Pa at 248.84."
            ),
            "indoor_channels": cols,
            "outdoor_columns": [
                {"field": c.field, "header": c.header, "si_unit": c.si_unit}
                for c in self._config.aio2.output_columns
            ],
        }
        path = self._day_dir(date_str) / f"{date_str}-MH_metadata.json"
        if not path.exists():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, indent=2)

    def _close_handles(self):
        for fh in self._fh.values():
            try:
                fh.close()
            except Exception:
                pass
        self._fh = {}

    # -- writing --
    def write_indoor(self, timestamp, raw_values, si_values):
        """Append one indoor record to both raw and SI files.

        Parameters
        ----------
        timestamp : datetime
        raw_values : dict
            Channel name to raw reading, in the units the backend returns.
        si_values : dict
            Channel name to SI value.
        """
        d = timestamp.strftime(_DATE_FMT)
        t = timestamp.strftime(_TIME_FMT)
        raw_row = [d, t] + [_fmt(raw_values[c.name]) for c in self._config.channels]
        si_row = [d, t] + [_fmt(si_values[c.name]) for c in self._config.channels]
        with self._lock:
            self._roll(timestamp)
            self._fh["raw"].write("\t".join(raw_row) + "\n")
            self._fh["raw"].flush()
            self._fh["si"].write("\t".join(si_row) + "\n")
            self._fh["si"].flush()

    def write_outdoor(self, timestamp, fields):
        """Append one outdoor record.

        Parameters
        ----------
        timestamp : datetime
        fields : dict
            Parsed AIO 2 fields (field name to string). Missing optional fields
            (BV or CV off, or rain/solar absent) are written as empty.
        """
        d = timestamp.strftime(_DATE_FMT)
        t = timestamp.strftime(_TIME_FMT)
        row = [d, t] + [fields.get(f, "") for f in self._out_fields]
        with self._lock:
            self._roll(timestamp)
            self._fh["out"].write("\t".join(row) + "\n")
            self._fh["out"].flush()

    def write_snapshot(self, timestamp, si_values, outdoor_fields, alarm_state=None):
        """Rewrite the latest-values snapshot atomically.

        The snapshot is a small JSON file the status tool and future Mission
        publish read without touching the open daily files. Written to a temp
        file then replaced, so a reader never sees a half-written file.

        Parameters
        ----------
        timestamp : datetime
        si_values : dict
            Latest indoor SI values by channel.
        outdoor_fields : dict
            Latest parsed outdoor fields.
        alarm_state : dict, optional
            Current alarm state by rule, if available.
        """
        snap = {
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "indoor_si": si_values,
            "outdoor": outdoor_fields,
            "alarms": alarm_state or {},
        }
        path = self._snapshot_path()
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, indent=2)
            os.replace(tmp, path)  # atomic on Windows and POSIX

    def close(self):
        """Close all open daily files. Safe to call more than once."""
        with self._lock:
            self._close_handles()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def _fmt(value):
    """Format a numeric value for the file, or pass through a string.

    Numbers use up to 4 decimal places without trailing-zero padding, so the
    files stay compact and readable.
    """
    if isinstance(value, str):
        return value
    return f"{value:.4f}".rstrip("0").rstrip(".") if value == value else ""
