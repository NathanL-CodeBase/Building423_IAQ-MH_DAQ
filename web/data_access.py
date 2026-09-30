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
        output, and min/mean/max bucket downsampling for long windows.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.mh_daq.config import load_config

_config = load_config()


def data_root():
    """Root holding latest_snapshot.json and the YYYY/ daily-file tree."""
    override = os.environ.get("MH_DAQ_DATA_ROOT")
    return Path(override) if override else Path(_config.local.local_data_dir)


def _daily_path(kind, date):
    """Path to an indoor SI or outdoor daily file for a date.

    kind is 'indoor_si' or 'outdoor'; both keys exist in file_naming.
    """
    name = _config.local.file_naming[kind].format(date=date.strftime("%Y%m%d"))
    return data_root() / date.strftime("%Y") / name


def _parse_datetime(df):
    """Return a datetime Series from the Date and Time columns, robustly."""
    combined = df["Date"].astype(str) + " " + df["Time"].astype(str)
    dt = pd.to_datetime(combined, format="%m/%d/%Y %H:%M:%S", errors="coerce")
    if dt.isna().all():
        dt = pd.to_datetime(combined, errors="coerce")
    return dt


def read_span(kind, start, end):
    """Read rows of one file kind between start and end (inclusive).

    Reads each daily file whose date falls in the span, concatenates, parses
    timestamps, and filters to the window. Returns a DataFrame with a 'dt'
    datetime column plus the original data columns (Date and Time dropped).

    Parameters
    ----------
    kind : str
        'indoor_si' or 'outdoor'.
    start, end : datetime

    Returns
    -------
    pandas.DataFrame
        Empty if no data found.
    """
    frames = []
    day = start.date()
    last = end.date()
    while day <= last:
        p = _daily_path(kind, datetime(day.year, day.month, day.day))
        if p.exists():
            try:
                frames.append(pd.read_csv(p, sep="\t"))
            except (OSError, pd.errors.ParserError):
                pass
        day += timedelta(days=1)
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["dt"] = _parse_datetime(df)
    df = df.dropna(subset=["dt"])
    df = df[(df["dt"] >= start) & (df["dt"] <= end)]
    return df.drop(columns=["Date", "Time"], errors="ignore").reset_index(drop=True)


def downsample(df, target_points=1000):
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

    Returns
    -------
    DataFrame with 'dt' and the mean of each numeric column per bucket.
    """
    if df.empty or len(df) <= target_points:
        return df
    span_s = (df["dt"].iloc[-1] - df["dt"].iloc[0]).total_seconds()
    if span_s <= 0:
        return df
    bucket_s = max(1.0, span_s / target_points)
    g = df.set_index("dt")
    numeric = g.select_dtypes("number")
    res = numeric.resample(f"{int(bucket_s)}s").mean().dropna(how="all").reset_index()
    return res


def numeric_columns(df):
    """Return the numeric (data) column names, excluding dt."""
    return [c for c in df.select_dtypes("number").columns if c != "dt"]
