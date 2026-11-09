#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared data access for the MH DAQ web apps.

Purpose: Read indoor and outdoor daily files from the data root, parse their
    timestamps robustly, and downsample long spans so a month of 1 Hz data does
    not ship millions of points to a browser. Used by both the group dashboard
    and the weather public page.
Author: Nathan Lima
Created: 2026-09-29
Update log:
    2026-09-29: Initial version. read_span for indoor and outdoor, ISO time
        output, and mean bucket downsampling for long windows.
    2026-10-02: Add parse_iso_naive, shared by the dashboard endpoints.
    2026-10-08: Add MH_DAQ_SOURCE=mission for remote read-only machines. Split
        the data root into daily_root and snapshot_root, because Mission keeps
        the dailies under raw_data/<mission_subdir> and the snapshot and
        heartbeat under live_snapshot.
    2026-11-09: Outdoor reads join the LabVIEW-era weather files before the
        cutover to the rebuilt files after it. Read with index_col=False for
        the legacy trailing tab. downsample takes a wind-direction column
        (speed-weighted vector mean) and columns to also report as a bucket max.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.mh_daq.config import load_config

_config = load_config()

_SOURCES = ("local", "mission")


def data_source():
    """Return the read source from MH_DAQ_SOURCE: 'local' (default) or 'mission'.

    'local' reads the daemon's own output folder, so it only works on the DAQ
    PC or a sim machine. 'mission' reads the mirrored copies on the Mission
    share, for any remote machine that only views the data.

    Raises
    ------
    ValueError
        If MH_DAQ_SOURCE holds anything other than 'local' or 'mission'.
    """
    source = os.environ.get("MH_DAQ_SOURCE", "local").strip().lower() or "local"
    if source not in _SOURCES:
        raise ValueError(f"MH_DAQ_SOURCE must be one of {_SOURCES}, got {source!r}.")
    return source


def daily_root():
    """Root holding the YYYY/ daily-file tree.

    MH_DAQ_DATA_ROOT overrides it in local mode, for reading a copied folder.
    """
    if data_source() == "mission":
        return Path(_config.local.mission_data_dir) / _config.mirror.mission_subdir
    override = os.environ.get("MH_DAQ_DATA_ROOT")
    return Path(override) if override else Path(_config.local.local_data_dir)


def snapshot_root():
    """Folder holding latest_snapshot.json and heartbeat.json.

    Locally the daemon writes both next to the daily tree; on Mission the
    mirror puts them in mission_snapshot_dir.
    """
    if data_source() == "mission":
        return Path(_config.local.mission_snapshot_dir)
    return daily_root()


def parse_iso_naive(text, default):
    """Parse an ISO string to a tz-naive local datetime, or return default.

    A trailing Z or UTC offset is dropped, so comparisons against the tz-naive
    file timestamps never mix aware and naive datetimes.

    Parameters
    ----------
    text : str
        ISO date or datetime. Empty or unparseable returns default.
    default : datetime

    Returns
    -------
    datetime
    """
    if not text:
        return default
    try:
        return datetime.fromisoformat(text.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return default


def _daily_path(kind, date):
    """Path to an indoor SI or outdoor daily file for a date.

    kind is 'indoor_si' or 'outdoor'; both keys exist in file_naming.
    """
    name = _config.local.file_naming[kind].format(date=date.strftime("%Y%m%d"))
    return daily_root() / date.strftime("%Y") / name


def _parse_datetime(df):
    """Return a datetime Series from the Date and Time columns, robustly."""
    combined = df["Date"].astype(str) + " " + df["Time"].astype(str)
    dt = pd.to_datetime(combined, format="%m/%d/%Y %H:%M:%S", errors="coerce")
    if dt.isna().all():
        dt = pd.to_datetime(combined, errors="coerce")
    return dt


def _legacy_outdoor_path(date):
    """Path to a LabVIEW-era outdoor file on Mission, or None if not configured.

    The legacy files exist only on Mission, so this ignores MH_DAQ_SOURCE: the
    DAQ PC in local mode still finds them when Mission is reachable.
    """
    lo = _config.legacy_outdoor
    if lo is None:
        return None
    name = lo.file_naming.format(date=date.strftime("%Y%m%d"))
    return Path(_config.local.mission_data_dir) / lo.mission_subdir / date.strftime("%Y") / name


def _read_daily(path):
    """Read one tab-delimited daily file and add a parsed 'dt' column.

    index_col=False keeps the legacy files' trailing tab from shifting the
    columns. Returns None when the file is missing or unreadable, so one bad
    day does not blank a whole span.
    """
    if path is None or not path.exists():
        return None
    try:
        df = pd.read_csv(path, sep="\t", index_col=False)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    if "Date" not in df.columns or "Time" not in df.columns:
        return None
    df["dt"] = _parse_datetime(df)
    return df.dropna(subset=["dt"])


def read_span(kind, start, end):
    """Read rows of one file kind between start and end (inclusive).

    Reads each daily file whose date falls in the span, concatenates, parses
    timestamps, and filters to the window. For 'outdoor', times before the
    legacy cutover come from the LabVIEW-era files and times from the cutover
    on come from the rebuilt files; the legacy files carry only the five
    shared columns, so the others are NaN there.

    Rows keep file order and repeated timestamps are kept. The fall-back
    daylight saving hour repeats every naive local time, so dropping repeats
    would delete a real hour of data.

    Parameters
    ----------
    kind : str
        'indoor_si' or 'outdoor'.
    start, end : datetime

    Returns
    -------
    pandas.DataFrame
        A 'dt' column plus the data columns (Date and Time dropped). Empty if
        no data found.
    """
    legacy = _config.legacy_outdoor if kind == "outdoor" else None
    cutover = legacy.cutover_local if legacy else None

    frames = []
    day = start.date()
    last = end.date()
    while day <= last:
        date = datetime(day.year, day.month, day.day)
        # Legacy first, so the cutover day stays in time order.
        if cutover is not None and day <= cutover.date():
            old = _read_daily(_legacy_outdoor_path(date))
            if old is not None:
                frames.append(old[old["dt"] < cutover])
        if cutover is None or day >= cutover.date():
            new = _read_daily(_daily_path(kind, date))
            if new is not None:
                if cutover is not None:
                    new = new[new["dt"] >= cutover]
                frames.append(new)
        day += timedelta(days=1)
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df[(df["dt"] >= start) & (df["dt"] <= end)]
    return df.drop(columns=["Date", "Time"], errors="ignore").reset_index(drop=True)


def downsample(df, target_points=1000, direction_col=None, speed_col=None, max_cols=()):
    """Downsample a time-indexed frame to about target_points rows.

    Buckets the frame's own time span so the result has roughly target_points
    rows regardless of the span: a month and an hour both come back at about the
    same size, at different bucket widths. Returns the frame unchanged when it
    already has target_points or fewer (a narrow window at full resolution).

    Parameters
    ----------
    df : DataFrame
        Must have a 'dt' datetime column.
    target_points : int
    direction_col : str, optional
        A direction in degrees. An arithmetic mean of 350 and 10 gives 180, so
        this column is averaged as a vector, weighted by speed_col when given.
        A bucket with zero mean vector (calm) gets NaN.
    speed_col : str, optional
        Speed column used as the vector weight for direction_col.
    max_cols : sequence of str
        Columns also returned as the bucket maximum, named '<col>_max' (wind
        gust from 1 Hz speed). Present even when no downsampling happens.

    Returns
    -------
    DataFrame with 'dt' and the mean of each numeric column per bucket.
    """
    max_cols = [c for c in max_cols if c in df.columns]
    if df.empty:
        return df
    # resample needs time order; mergesort keeps a repeated DST hour in file order.
    df = df.sort_values("dt", kind="mergesort")
    span_s = (df["dt"].iloc[-1] - df["dt"].iloc[0]).total_seconds()
    if len(df) <= target_points or span_s <= 0:
        out = df.reset_index(drop=True)
        for c in max_cols:
            out[f"{c}_max"] = out[c]
        return out
    bucket = f"{int(max(1.0, span_s / target_points))}s"
    g = df.set_index("dt")
    numeric = g.select_dtypes("number")
    res = numeric.resample(bucket).mean()

    if direction_col and direction_col in numeric.columns:
        theta = np.deg2rad(numeric[direction_col])
        w = numeric[speed_col] if speed_col and speed_col in numeric.columns else 1.0
        vec = pd.DataFrame({"u": w * np.sin(theta), "v": w * np.cos(theta)})
        vm = vec.resample(bucket).mean()
        deg = np.rad2deg(np.arctan2(vm["u"], vm["v"])) % 360.0
        calm = np.hypot(vm["u"], vm["v"]) < 1e-9
        res[direction_col] = deg.mask(calm)

    for c in max_cols:
        res[f"{c}_max"] = numeric[c].resample(bucket).max()

    return res.dropna(how="all").reset_index()


def numeric_columns(df):
    """Return the numeric (data) column names, excluding dt."""
    return [c for c in df.select_dtypes("number").columns if c != "dt"]
