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
    2026-11-09: Default trends are living-room T and RH. Trends accept AIO 2
        columns beside indoor channels. /api/channels serves offline tags and
        the stale-banner age. Weather endpoints serve only columns with a
        sensor, add a gust (bucket max) series and a wind-direction vector
        mean, and reach the LabVIEW-era files before the cutover. Downloads
        are capped at web.max_download_days. In mission mode a background
        watchdog emails when the Mission heartbeat goes stale.
    2026-11-09: Re-read channel_status when daq_config.json changes and
        send the offline tags with each snapshot.

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
    MH_DAQ_WATCHDOG    '1' or '0' forces the stale-heartbeat email watchdog on
                       or off. Default: on in mission mode only, because in
                       local mode the dashboard sits on the DAQ PC and goes
                       down with it.
"""

import io
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.mh_daq.alarms import SmtpEmailSender
from src.mh_daq.config import ConfigError, load_channel_status, load_config
from src.mh_daq.scaling import si_units_by_channel
from web.data_access import (
    data_source,
    downsample,
    parse_iso_naive,
    read_span,
    snapshot_root,
)
from web.watchdog import StaleWatchdog

logger = logging.getLogger("mh_daq.web")


def _watchdog_enabled():
    flag = os.environ.get("MH_DAQ_WATCHDOG", "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    return data_source() == "mission"


@asynccontextmanager
async def _lifespan(app):
    """Start the stale-heartbeat watchdog thread with the server."""
    wd = None
    if _watchdog_enabled():
        loc = _config.local
        sender = SmtpEmailSender(loc.smtp_host, loc.smtp_port, loc.smtp_from, loc.smtp_to)
        wd = StaleWatchdog(
            _heartbeat_path,
            sender,
            alarm_s=_config.web.stale_alarm_s,
            renotify_s=_config.web.stale_renotify_s,
            machine=loc.machine_name,
        )
        threading.Thread(
            target=wd.run_loop, args=(_config.web.watchdog_check_s,), name="watchdog", daemon=True
        ).start()
    yield
    if wd is not None:
        wd.stop()


app = FastAPI(title="MH DAQ Group Dashboard", lifespan=_lifespan)

# Pages, their scripts, and vendored Plotly are all served locally, so the
# site has no external CDN dependency on an internal server with no outbound web.
_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

_config = load_config()
_UNITS = dict(si_units_by_channel(_config))
_DISPLAY_RANGES = {
    ch: {"low": dr.low, "high": dr.high} for dr in _config.display_ranges for ch in dr.channels
}

def _offline_map(offline):
    return {o.channel: {"reason": o.reason, "since": o.since} for o in offline}


# Offline tags re-read when daq_config.json changes, so tagging a channel on
# this machine needs no dashboard restart. A bad edit keeps the last good map.
_offline_cache = {"mtime": None, "map": _offline_map(_config.offline_channels)}
_offline_lock = threading.Lock()


def _offline():
    """Return the current offline map, re-reading channel_status on file change."""
    try:
        mtime = _config.committed_path.stat().st_mtime
    except (AttributeError, OSError):
        return _offline_cache["map"]
    with _offline_lock:
        if _offline_cache["mtime"] is None:
            _offline_cache["mtime"] = mtime
        elif mtime != _offline_cache["mtime"]:
            _offline_cache["mtime"] = mtime
            try:
                offline, _events = load_channel_status(_config)
                _offline_cache["map"] = _offline_map(offline)
            except ConfigError as e:
                logger.error("channel_status reload rejected; keeping last tags. %s", e)
        return _offline_cache["map"]

# AIO 2 columns with a sensor behind them (rain and solar have none), keyed by
# file header. The header is also the trend channel name for outdoor series.
_OUTDOOR_COLS = [c for c in _config.aio2.output_columns if c.present]
_OUTDOOR_UNITS = {c.header: c.si_unit for c in _OUTDOOR_COLS}
_OUTDOOR_HEADER = {c.field: c.header for c in _OUTDOOR_COLS}
_WIND_DIR = _OUTDOOR_HEADER.get("wind_direction")
_WIND_SPEED = _OUTDOOR_HEADER.get("wind_speed")
# Sensor diagnostics stay in the download but off the weather page plots.
_WEATHER_PLOT_EXCLUDE = {"battery_voltage", "compass_heading"}

# Trend channels shown before the user picks any. Served to the page through
# /api/channels so the page and the API share one list.
_DEFAULT_TREND_CHANNELS = ["T_Liv_M4_C7", "RH_Liv_M3_C3"]

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
_HEALTH["banner_s"] = _config.web.stale_banner_s


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
    # Offline tags ride on the 3 s snapshot poll, so a config edit reaches an
    # open page without a reload.
    snap["offline"] = _offline()
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
    """Return all trend channels with SI units, the default trend set, the
    card color ranges, the offline tags, and the health thresholds.

    Used to build the picker and to label and color the cards. Indoor units
    come from the config scales, in task order; outdoor_channels lists the AIO
    2 columns that have a sensor. display_ranges maps a channel name to
    {"low", "high"} (either may be null); channels without a range are absent.
    offline maps a channel to {"reason", "since"} for greyed cards. health
    holds the heartbeat ages {"delayed_s", "down_s", "banner_s"} for the
    active data source.
    """
    items = [{"channel": name, "unit": unit} for name, unit in _UNITS.items()]
    outdoor = [{"channel": h, "unit": u} for h, u in _OUTDOOR_UNITS.items()]
    return JSONResponse(
        {
            "channels": items,
            "outdoor_channels": outdoor,
            "defaults": _DEFAULT_TREND_CHANNELS,
            "display_ranges": _DISPLAY_RANGES,
            "offline": _offline(),
            "source": _SOURCE,
            "health": _HEALTH,
        }
    )


def _series(df, col, digits):
    return df[col].round(digits).where(pd.notna(df[col]), None).tolist()


def _downsample_outdoor(df, target, max_cols=()):
    return downsample(
        df, target_points=target, direction_col=_WIND_DIR, speed_col=_WIND_SPEED, max_cols=max_cols
    )


@app.get("/api/trend")
def api_trend(start: str = "", end: str = "", channels: str = "", target: int = 1000):
    """Return SI series for channels over [start, end], downsampled to ~target.

    Parameters
    ----------
    start, end : str
        ISO datetimes. If empty, end defaults to now and start to 30 min before.
    channels : str
        Comma-separated channel names: indoor channel names or AIO 2 column
        headers. Empty returns the default set.
    target : int
        Approximate number of points to return per channel. The span is bucketed
        to hit this, so any window (a month or a minute) returns about this many.

    Returns
    -------
    JSON: 'time' (ISO, indoor), 'time_outdoor' (ISO, AIO 2), one array per
    channel, 'x_of' naming the time array of each outdoor channel, 'markers'
    listing channels to draw as points (wind direction), 'units' per channel,
    and the actual 'start'/'end' covered.
    """
    e = parse_iso_naive(end, datetime.now())
    s = parse_iso_naive(start, e - timedelta(minutes=30))
    target = max(50, min(target, 10000))

    wanted = [c.strip() for c in channels.split(",") if c.strip()] or _DEFAULT_TREND_CHANNELS
    wanted_out = [c for c in wanted if c in _OUTDOOR_UNITS]
    wanted_in = [c for c in wanted if c not in _OUTDOOR_UNITS]

    out = {
        "available": False,
        "time": [],
        "time_outdoor": [],
        "x_of": {},
        "markers": [],
        "units": {},
        "start": s.isoformat(),
        "end": e.isoformat(),
    }

    if wanted_in:
        df = read_span("indoor_si", s, e)
        if not df.empty:
            df = downsample(df, target_points=target)
            out["time"] = [t.isoformat() for t in df["dt"]]
            for want in wanted_in:
                match = [c for c in df.columns if c == want or c.startswith(want + "_")]
                if match:
                    out[want] = _series(df, match[0], 4)
                    out["units"][want] = _UNITS.get(want, "")
                    out["available"] = True

    if wanted_out:
        dfo = read_span("outdoor", s, e)
        if not dfo.empty:
            dfo = _downsample_outdoor(dfo, target)
            out["time_outdoor"] = [t.isoformat() for t in dfo["dt"]]
            for want in wanted_out:
                if want in dfo.columns:
                    out[want] = _series(dfo, want, 3)
                    out["units"][want] = _OUTDOOR_UNITS[want]
                    out["x_of"][want] = "time_outdoor"
                    out["available"] = True
                    if want == _WIND_DIR:
                        out["markers"].append(want)
    return JSONResponse(out)


@app.get("/api/weather/columns")
def api_weather_columns():
    """Return the AIO 2 columns that have a sensor, for the download list and plots.

    Each entry is {header, field, unit, plot}; plot is false for sensor
    diagnostics (battery voltage, compass heading), which stay downloadable.
    Also returns the download limits and the earliest data date.
    """
    lo = _config.legacy_outdoor
    cols = [
        {
            "header": c.header,
            "field": c.field,
            "unit": c.si_unit,
            "plot": c.field not in _WEATHER_PLOT_EXCLUDE,
        }
        for c in _OUTDOOR_COLS
    ]
    return JSONResponse(
        {
            "columns": cols,
            "max_download_days": _config.web.max_download_days,
            "first_date": lo.first_date if lo else None,
            "cutover_local": lo.cutover_local.isoformat(sep=" ") if lo else None,
        }
    )


@app.get("/api/weather/series")
def api_weather_series(hours: int = 24):
    """Return recent outdoor data for plotting, downsampled for long spans.

    Returns the plotted columns keyed by header, 'fields' mapping field name to
    header, and 'gust' (bucket max of wind speed). Wind direction is a
    speed-weighted vector mean per bucket. hours is clamped to 1 to 168.
    """
    hours = max(1, min(int(hours), 168))
    now = datetime.now()
    df = read_span("outdoor", now - timedelta(hours=hours), now)
    if df.empty:
        return JSONResponse({"available": False, "time": []})
    max_cols = [_WIND_SPEED] if _WIND_SPEED else []
    df = _downsample_outdoor(df, 3000, max_cols=max_cols)
    out = {"available": True, "time": [t.isoformat() for t in df["dt"]], "fields": {}}
    for c in _OUTDOOR_COLS:
        if c.field in _WEATHER_PLOT_EXCLUDE or c.header not in df.columns:
            continue
        out[c.header] = _series(df, c.header, 3)
        out["fields"][c.field] = c.header
    if _WIND_SPEED and f"{_WIND_SPEED}_max" in df.columns:
        out["gust"] = _series(df, f"{_WIND_SPEED}_max", 3)
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
        Comma-separated column headers to include. Empty means every column
        with a sensor; rain and solar are never included.

    Returns
    -------
    CSV with a single ISO 'datetime' column plus the selected data columns,
    in file order. Before the cutover only the five LabVIEW-era columns hold
    values. A range longer than web.max_download_days returns HTTP 400.
    """
    now = datetime.now()
    s = parse_iso_naive(start, datetime(now.year, now.month, now.day))
    e = parse_iso_naive(end, now)
    # If end is a bare date, include the whole day.
    if end and len(end) <= 10:
        e = e + timedelta(days=1) - timedelta(seconds=1)

    max_days = _config.web.max_download_days
    if (e - s).total_seconds() > max_days * 86400:
        return PlainTextResponse(
            f"Range too long: at most {max_days} days per download.", status_code=400
        )

    df = read_span("outdoor", s, e)
    if df.empty:
        return PlainTextResponse("datetime\n", media_type="text/csv")

    allowed = [h for h in _OUTDOOR_UNITS if h in df.columns]
    wanted = [c.strip() for c in vars.split(",") if c.strip()] or allowed
    keep = [c for c in wanted if c in allowed]

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
