#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MH DAQ group live dashboard (FastAPI).

Purpose: Serve a group-private live view of the acquisition data. Reads the
    latest snapshot for current values and the recent SI daily file for trend
    plots. Reads from a configurable data root: the local --sim output now, the
    Mission share later (one path change). No hardware, no database, read-only.
Author: Nathan Lima
Created: 2026-09-28
Update log:
    2026-09-28: Initial version. Snapshot endpoint, trend endpoint, one HTML
        page that polls and plots.
    2026-10-01: Remove dead refreshPlot() and duplicate updatePickerCount,
        togglePicker, and windowMinutes definitions from the group page script.
    2026-10-02: Use shared data_root and parse_iso_naive from data_access.
        Serve units and default trend channels from /api/channels so the page
        holds no copy of config. Leave #status to the heartbeat indicator.
        Move page HTML and JS to web/static/ (index.*, weather.*).
    2026-10-02: Serve display_ranges from config through /api/channels for
        the living-space T and RH card colors.
    2026-10-08: Read from Mission when MH_DAQ_SOURCE=mission, with the
        snapshot and heartbeat from mission_snapshot_dir. Serve health
        thresholds per source through /api/channels.

Usage (from repo root, mh_daq_web env, PowerShell):
    # DAQ PC or sim machine (default): reads config.local.local_data_dir
    python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
    # Remote read-only machine: reads the Mission copies
    $env:MH_DAQ_SOURCE = "mission"
    python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
    # then open http://127.0.0.1:8000

Data source by environment variable:
    MH_DAQ_SOURCE      'local' (default) or 'mission'. Mission mode reads the
                       dailies from mission_data_dir/<mirror.mission_subdir> and
                       the snapshot and heartbeat from mission_snapshot_dir, all
                       from daq_local.json.
    MH_DAQ_DATA_ROOT   Local mode only: a folder holding latest_snapshot.json,
                       heartbeat.json, and YYYY/ daily files. Defaults to
                       config.local.local_data_dir.
"""

import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.mh_daq.config import load_config
from src.mh_daq.scaling import si_units_by_channel
from web.data_access import (
    data_source,
    downsample,
    numeric_columns,
    parse_iso_naive,
    read_span,
    snapshot_root,
)

app = FastAPI(title="MH DAQ Group Dashboard")

# Pages, their scripts, and vendored Plotly are all served locally, so the
# site has no external CDN dependency on an internal server with no outbound web.
_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

_config = load_config()
_UNITS = dict(si_units_by_channel(_config))
_DISPLAY_RANGES = {
    ch: {"low": dr.low, "high": dr.high} for dr in _config.display_ranges for ch in dr.channels
}

# Trend channels shown before the user picks any. Served to the page through
# /api/channels so the page and the API share one list.
_DEFAULT_TREND_CHANNELS = ["T_Liv_M4_C7", "T_Gar_M5_C4", "RH_Liv_M3_C3", "6V_Test_M2_C7"]

# Heartbeat age, in seconds, past which the page shows yellow (delayed) and red
# (down). Local reads see the heartbeat within seconds. Mission reads lag the
# snapshot mirror (mirror.snapshot_interval_s, 60 s) plus the mirror tick, so
# tighter limits would hold the indicator at yellow or red on a healthy system.
# Resolved at import so a bad MH_DAQ_SOURCE fails at startup.
_SOURCE = data_source()
_HEALTH = {
    "local": {"delayed_s": 5, "down_s": 60},
    "mission": {"delayed_s": 90, "down_s": 300},
}[_SOURCE]


def _snapshot_path():
    return snapshot_root() / "latest_snapshot.json"


def _heartbeat_path():
    return snapshot_root() / "heartbeat.json"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/snapshot")
def api_snapshot():
    """Return the latest snapshot, or a status if none is present yet."""
    p = _snapshot_path()
    try:
        with open(p, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return JSONResponse({"available": False, "reason": f"No snapshot at {p}"}, status_code=200)
    snap["available"] = True
    # Age in seconds, so the page can flag stale data.
    try:
        ts = datetime.fromisoformat(snap.get("timestamp"))
        snap["age_s"] = (datetime.now() - ts).total_seconds()
    except (TypeError, ValueError):
        snap["age_s"] = None
    return JSONResponse(snap)


@app.get("/api/heartbeat")
def api_heartbeat():
    """Return the daemon heartbeat with an age, or available=false if missing.

    The heartbeat holds system status only (thread liveness, alarm state,
    Mission reachability, record timestamps), no indoor measurement values. The
    group page reads it to drive the health indicator. age_s is seconds since
    written_at, so the page can flag a stale or dead daemon.
    """
    p = _heartbeat_path()
    try:
        with open(p, encoding="utf-8") as f:
            hb = json.load(f)
    except (OSError, json.JSONDecodeError):
        return JSONResponse({"available": False, "reason": f"No heartbeat at {p}"}, status_code=200)
    hb["available"] = True
    try:
        ts = datetime.fromisoformat(hb.get("written_at"))
        hb["age_s"] = (datetime.now() - ts).total_seconds()
    except (TypeError, ValueError):
        hb["age_s"] = None
    return JSONResponse(hb)


@app.get("/api/channels")
def api_channels():
    """Return all indoor channels with SI units, the default trend set, the
    card color ranges, and the health thresholds.

    Used to build the picker and to label and color the cards. Units come
    from the config scales, in task order. display_ranges maps a channel name
    to {"low", "high"} (either may be null); channels without a range are
    absent. health holds the heartbeat ages {"delayed_s", "down_s"} for the
    active data source.
    """
    items = [{"channel": name, "unit": unit} for name, unit in _UNITS.items()]
    return JSONResponse(
        {
            "channels": items,
            "defaults": _DEFAULT_TREND_CHANNELS,
            "display_ranges": _DISPLAY_RANGES,
            "source": _SOURCE,
            "health": _HEALTH,
        }
    )


@app.get("/api/trend")
def api_trend(start: str = "", end: str = "", channels: str = "", target: int = 1000):
    """Return SI series for channels over [start, end], downsampled to ~target.

    Parameters
    ----------
    start, end : str
        ISO datetimes. If empty, end defaults to now and start to 30 min before.
    channels : str
        Comma-separated plain channel names. Empty returns a small default set.
    target : int
        Approximate number of points to return per channel. The span is bucketed
        to hit this, so any window (a month or a minute) returns about this many.

    Returns
    -------
    JSON: 'time' (ISO), one array per channel, 'units' per channel, and the
    actual 'start'/'end' covered.
    """
    e = parse_iso_naive(end, datetime.now())
    s = parse_iso_naive(start, e - timedelta(minutes=30))

    wanted = [c.strip() for c in channels.split(",") if c.strip()] or _DEFAULT_TREND_CHANNELS

    df = read_span("indoor_si", s, e)
    if df.empty:
        return JSONResponse(
            {
                "available": False,
                "time": [],
                "units": {},
                "start": s.isoformat(),
                "end": e.isoformat(),
            }
        )

    df = downsample(df, target_points=max(50, min(target, 10000)))

    colmap = {}
    for want in wanted:
        match = [c for c in df.columns if c == want or c.startswith(want + "_")]
        if match:
            colmap[want] = match[0]

    out = {
        "available": True,
        "time": [t.isoformat() for t in df["dt"]],
        "units": {},
        "start": s.isoformat(),
        "end": e.isoformat(),
    }
    for want, col in colmap.items():
        series = df[col].round(4).where(pd.notna(df[col]), None)
        out[want] = series.tolist()
        out["units"][want] = _UNITS.get(want, "")
    return JSONResponse(out)


@app.get("/api/weather/columns")
def api_weather_columns():
    """Return the outdoor data column names available for selection."""
    cols = [c.header for c in _config.aio2.output_columns]
    return JSONResponse({"columns": cols})


@app.get("/api/weather/series")
def api_weather_series(hours: int = 24):
    """Return recent outdoor data for plotting, downsampled for long spans."""
    now = datetime.now()
    start = now - timedelta(hours=hours)
    df = read_span("outdoor", start, now)
    if df.empty:
        return JSONResponse({"available": False, "time": []})
    df = downsample(df, target_points=3000)
    out = {"available": True, "time": [t.isoformat() for t in df["dt"]]}
    for c in numeric_columns(df):
        out[c] = df[c].round(3).where(pd.notna(df[c]), None).tolist()
    return JSONResponse(out)


@app.get("/api/weather/health")
def api_weather_health():
    """Return outdoor-feed freshness only: {available, age_s}.

    Drives the public weather page indicator. Reads the last 10 minutes of
    outdoor data and reports the age of the most recent record. Does not read
    the heartbeat or any indoor data, so no system internals reach the public
    page. age_s is null when no recent record exists.
    """
    now = datetime.now()
    df = read_span("outdoor", now - timedelta(minutes=10), now)
    if df.empty:
        return JSONResponse({"available": False, "age_s": None})
    last_dt = df["dt"].max()
    age_s = (now - last_dt).total_seconds()
    return JSONResponse({"available": True, "age_s": age_s})


@app.get("/api/weather/download")
def api_weather_download(start: str = "", end: str = "", vars: str = ""):
    """Return a CSV of outdoor data for a date range with selected variables.

    Parameters
    ----------
    start, end : str
        ISO dates (YYYY-MM-DD) or datetimes. Empty start/end defaults to today.
    vars : str
        Comma-separated column headers to include. Empty means all.

    Returns
    -------
    CSV with a single ISO 'datetime' column plus the selected data columns.
    """
    now = datetime.now()
    s = parse_iso_naive(start, datetime(now.year, now.month, now.day))
    e = parse_iso_naive(end, now)
    # If end is a bare date, include the whole day.
    if end and len(end) <= 10:
        e = e + timedelta(days=1) - timedelta(seconds=1)

    df = read_span("outdoor", s, e)
    if df.empty:
        return PlainTextResponse("datetime\n", media_type="text/csv")

    all_cols = numeric_columns(df)
    wanted = [c.strip() for c in vars.split(",") if c.strip()] or all_cols
    keep = [c for c in wanted if c in df.columns]

    out = pd.DataFrame({"datetime": df["dt"].map(lambda t: t.isoformat())})
    for c in keep:
        out[c] = df[c]

    buf = io.StringIO()
    out.to_csv(buf, index=False)
    fname = f"MH_weather_{s:%Y%m%d}_{e:%Y%m%d}.csv"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/weather", response_class=FileResponse)
def weather_page():
    return FileResponse(_STATIC / "weather.html")
