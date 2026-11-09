#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the 2026-11 web additions: weather era join, wind averaging, the
stale-heartbeat watchdog, and the channel_status and legacy_outdoor config.

Purpose: Confirm that outdoor reads take LabVIEW-era rows before the cutover
    and rebuilt rows from it on, with the legacy trailing tab parsed into the
    right columns; that wind direction averages as a vector across 0/360 and
    gust is the bucket maximum; that the watchdog emails on trip, reminder,
    and recovery, and still trips when the heartbeat cannot be read; and that
    config validation rejects an offline tag on an unknown channel. Every file
    is written under pytest's tmp_path; no email leaves the process.
Author: Nathan Lima
Created: 2026-11-09
Update log:
    2026-11-09: Initial version.
"""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.mh_daq.alarms import RecordingEmailSender
from src.mh_daq.config import ConfigError, load_config
from web import data_access
from web.watchdog import StaleWatchdog, format_age

_NEW_HEADER = (
    "Date\tTime\tWind_Speed_m/s\tWind_Direction_deg\tAmbient_Temperature_degC\t"
    "Relative_Humidity_%\tBarometric_Pressure_mb\tRain_mm\tSolar_Radiation_W/m2\t"
    "Battery_Voltage_V\tCompass_Heading_deg\n"
)
_OLD_HEADER = (
    "Date\tTime\tWind_Speed_m/s\tWind_Direction_deg\tAmbient_Temperature_degC\t"
    "Relative_Humidity_%\tBarometric_Pressure_mb\n"
)


# ---------------------------------------------------------------------------
# Era join
# ---------------------------------------------------------------------------
@pytest.fixture
def two_eras(monkeypatch, tmp_path):
    """Write one cutover-day file per era and point the reader at them."""
    monkeypatch.delenv("MH_DAQ_SOURCE", raising=False)
    monkeypatch.setenv("MH_DAQ_DATA_ROOT", str(tmp_path / "new"))
    new_dir = tmp_path / "new" / "2026"
    old_dir = tmp_path / "old" / "2026"
    new_dir.mkdir(parents=True)
    old_dir.mkdir(parents=True)

    # Rebuilt file: 12:11:00 is before the cutover (test data) and is dropped.
    (new_dir / "20261007-MH_Outdoor.txt").write_text(
        _NEW_HEADER
        + "10/07/2026\t12:11:00\t9.9\t999\t99.9\t99\t999.9\t0\t0\t23.2\t32\n"
        + "10/07/2026\t12:11:35\t2.0\t180\t20.0\t50\t1000.0\t000.00\t0000\t23.2\t32\n",
        encoding="utf-8",
    )
    # LabVIEW file with the trailing tab on data rows; 12:20:00 is after the
    # cutover and is dropped.
    (old_dir / "20261007-Daily_MHOutdoor_Data.txt").write_text(
        _OLD_HEADER
        + "10/07/2026\t12:06:25\t1.5\t90\t19.5\t48\t1001.0\t\n"
        + "10/07/2026\t12:20:00\t8.8\t888\t88.8\t88\t888.8\t\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_access,
        "_legacy_outdoor_path",
        lambda d: old_dir / f"{d:%Y%m%d}-Daily_MHOutdoor_Data.txt",
    )


def test_outdoor_read_joins_eras_at_cutover(two_eras):
    df = data_access.read_span(
        "outdoor", datetime(2026, 10, 7, 12, 0), datetime(2026, 10, 7, 12, 30)
    )
    assert [t.strftime("%H:%M:%S") for t in df["dt"]] == ["12:06:25", "12:11:35"]
    # Trailing tab did not shift the legacy columns.
    assert df["Wind_Direction_deg"].tolist() == [90, 180]
    assert df["Barometric_Pressure_mb"].tolist() == [1001.0, 1000.0]
    # Columns the legacy file lacks are NaN on its rows.
    assert pd.isna(df["Battery_Voltage_V"].iloc[0])
    assert df["Battery_Voltage_V"].iloc[1] == 23.2


def test_indoor_read_ignores_legacy(two_eras, tmp_path):
    # No indoor files exist; the outdoor legacy path must not leak into indoor.
    df = data_access.read_span(
        "indoor_si", datetime(2026, 10, 7, 12, 0), datetime(2026, 10, 7, 12, 30)
    )
    assert df.empty


# ---------------------------------------------------------------------------
# Downsampling
# ---------------------------------------------------------------------------
def _wind_frame(sentinel=True):
    """Four 1 s wind records from midnight.

    downsample sets the bucket to span / target_points, so the last record
    starts a new bucket. With sentinel, a trailing all-NaN record takes that
    place and its bucket is dropped, leaving the four records in one bucket.
    """
    t0 = datetime(2026, 11, 9, 0, 0)
    speed = [2.0, 2.0, 1.0, 5.0]
    direction = [350.0, 10.0, 350.0, 10.0]
    n = 4
    if sentinel:
        speed.append(float("nan"))
        direction.append(float("nan"))
        n = 5
    return pd.DataFrame(
        {"dt": [t0 + timedelta(seconds=s) for s in range(n)], "speed": speed, "dir": direction}
    )


def test_direction_vector_mean_wraps_north():
    out = data_access.downsample(
        _wind_frame(), target_points=1, direction_col="dir", speed_col="speed", max_cols=["speed"]
    )
    assert len(out) == 1
    d = out["dir"].iloc[0]
    # The arithmetic mean would be 180 deg; the vector mean is near north.
    assert min(d, 360.0 - d) < 10.0
    assert out["speed_max"].iloc[0] == 5.0
    assert out["speed"].iloc[0] == pytest.approx(2.5)


def test_calm_bucket_direction_is_nan():
    df = _wind_frame().assign(speed=0.0)
    out = data_access.downsample(df, target_points=1, direction_col="dir", speed_col="speed")
    assert pd.isna(out["dir"].iloc[0])


def test_small_frame_still_gets_max_column():
    out = data_access.downsample(_wind_frame(sentinel=False), target_points=100, max_cols=["speed"])
    assert out["speed_max"].tolist() == out["speed"].tolist()


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------
def _write_hb(path, written_at):
    path.write_text(json.dumps({"written_at": written_at.isoformat(timespec="seconds")}))


def test_watchdog_trip_renotify_clear(tmp_path):
    hb = tmp_path / "heartbeat.json"
    t0 = datetime(2026, 11, 9, 8, 0)
    _write_hb(hb, t0)
    sender = RecordingEmailSender()
    wd = StaleWatchdog(lambda: hb, sender, alarm_s=86400, renotify_s=86400, machine="appleseed")

    assert wd.check(t0 + timedelta(hours=23)) is None
    assert "No DAQ update" in wd.check(t0 + timedelta(hours=24, minutes=5))
    assert wd.check(t0 + timedelta(hours=30)) is None
    assert "Still no DAQ update" in wd.check(t0 + timedelta(hours=48, minutes=10))

    _write_hb(hb, t0 + timedelta(hours=49))
    assert "resumed" in wd.check(t0 + timedelta(hours=49, minutes=1))
    assert not wd.tripped
    assert len(sender.sent) == 3
    # Default recipients (smtp to_addrs): to_addrs is not overridden.
    assert all(to is None for _, _, to in sender.sent)


def test_watchdog_trips_when_heartbeat_unreadable(tmp_path):
    hb = tmp_path / "missing" / "heartbeat.json"
    sender = RecordingEmailSender()
    wd = StaleWatchdog(lambda: hb, sender, alarm_s=3600, renotify_s=86400, machine="appleseed")
    t0 = datetime(2026, 11, 9, 8, 0)
    assert wd.check(t0) is None
    assert wd.check(t0 + timedelta(hours=1, minutes=1)) is not None
    assert "could not be read from appleseed" in sender.sent[0][1]


def test_format_age():
    assert format_age(7 * 60) == "7 min"
    assert format_age(5 * 3600 + 12 * 60) == "5 h 12 min"
    assert format_age(3 * 86400 + 4 * 3600) == "3 d 4 h"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def test_committed_channel_status_and_legacy_load():
    cfg = load_config()
    offline = {o.channel for o in cfg.offline_channels}
    assert len(offline) == 7
    assert "dP_Fam-W-Hi_M1_C6" not in offline
    assert any(e.channel == "dP_Fam-W-Hi_M1_C6" for e in cfg.channel_events)
    assert cfg.legacy_outdoor.cutover_local == datetime(2026, 10, 7, 12, 11, 23)
    present = {c.field: c.present for c in cfg.aio2.output_columns}
    assert present["rain"] is False and present["solar_radiation"] is False
    assert present["wind_speed"] is True


def test_offline_unknown_channel_rejected(tmp_path):
    src = Path(os.environ["MH_DAQ_CONFIG_DIR"])
    shutil.copy(src / "daq_local.json", tmp_path / "daq_local.json")
    committed = json.loads((src / "daq_config.json").read_text(encoding="utf-8"))
    committed["channel_status"]["offline"].append({"channel": "dP_Nowhere_M9_C9"})
    (tmp_path / "daq_config.json").write_text(json.dumps(committed), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown channel 'dP_Nowhere_M9_C9'"):
        load_config(config_dir=tmp_path)
