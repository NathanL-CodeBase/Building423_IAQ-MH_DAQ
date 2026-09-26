#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the Mission mirror and the alarm engine.

Purpose: Confirm the mirror copies completed files, respects the in-progress
    interval, copies the snapshot, and degrades gracefully when Mission is
    unavailable. Confirm the alarm engine trips after dwell, clears, re-notifies
    on interval, detects frozen channels, and watches dropout, using a recording
    email sender so no network is touched.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.
"""

from datetime import datetime, timedelta

import pytest

from src.mh_daq.alarms import AlarmEngine, RecordingEmailSender
from src.mh_daq.config import load_config
from src.mh_daq.mirror import MissionMirror


@pytest.fixture(scope="module")
def config():
    return load_config()


# ---- Mirror ----
def _make_daily(local, date_str, name, content="x\n"):
    year = local / date_str[:4]
    year.mkdir(parents=True, exist_ok=True)
    f = year / f"{date_str}-MH_{name}.txt"
    f.write_text(content, encoding="utf-8")
    return f


def test_mirror_copies_completed(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"
    snap = tmp_path / "mission_snap"
    mission.mkdir()
    now = datetime(2026, 9, 25, 10, 0, 0)
    _make_daily(local, "20260924", "Indoor_SI")  # yesterday, completed
    mir = MissionMirror(config, local, mission, snap)
    n = mir.sync_completed(now)
    assert n == 1
    assert (mission / "2026" / "20260924-MH_Indoor_SI.txt").exists()


def test_mirror_inprogress_gated(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"
    snap = tmp_path / "mission_snap"
    mission.mkdir()
    now = datetime(2026, 9, 25, 10, 0, 0)
    _make_daily(local, "20260925", "Indoor_SI")  # today, in progress
    mir = MissionMirror(config, local, mission, snap)
    # Completed sync must not touch today's file.
    assert mir.sync_completed(now) == 0
    # In-progress sync copies it.
    assert mir.sync_inprogress(now) == 1
    assert (mission / "2026" / "20260925-MH_Indoor_SI.txt").exists()


def test_mirror_snapshot(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"
    snap = tmp_path / "mission_snap"
    local.mkdir()
    (local / "latest_snapshot.json").write_text("{}", encoding="utf-8")
    mir = MissionMirror(config, local, mission, snap)
    assert mir.sync_snapshot() is True
    assert (snap / "latest_snapshot.json").exists()


def test_mirror_unavailable_then_recovers(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"  # does not exist yet
    snap = tmp_path / "mission_snap"
    now = datetime(2026, 9, 25, 10, 0, 0)
    _make_daily(local, "20260924", "Indoor_SI")
    mir = MissionMirror(config, local, mission, snap)
    assert mir.mission_available() is False
    mir.tick(now)  # must not raise, copies nothing
    assert not (mission / "2026").exists()
    # Mission comes back
    mission.mkdir()
    mir.tick(now)
    assert (mission / "2026" / "20260924-MH_Indoor_SI.txt").exists()


def test_mirror_recopies_changed(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"
    snap = tmp_path / "mission_snap"
    mission.mkdir()
    now = datetime(2026, 9, 25, 10, 0, 0)
    f = _make_daily(local, "20260924", "Indoor_SI", "a\n")
    mir = MissionMirror(config, local, mission, snap)
    assert mir.sync_completed(now) == 1
    # Grow the file; next sync should recopy.
    f.write_text("a\nb\n", encoding="utf-8")
    assert mir.sync_completed(now) == 1


# ---- Alarms ----
def _si_zero(config, overrides=None):
    vals = {ch.name: 0.0 for ch in config.channels}
    if overrides:
        vals.update(overrides)
    return vals


def test_garage_trips_after_dwell(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    # 29 degC, above the 28 threshold, but dwell is 60 s.
    hot = _si_zero(config, {"T_Gar_M5_C4": 29.0})
    eng.check(hot, t0)
    assert sender.sent == []  # not yet, dwell not met
    eng.check(hot, t0 + timedelta(seconds=61))
    assert len(sender.sent) == 1
    assert "ALARM" in sender.sent[0][0]


def test_garage_clears(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    hot = _si_zero(config, {"T_Gar_M5_C4": 29.0})
    eng.check(hot, t0)
    eng.check(hot, t0 + timedelta(seconds=61))
    cool = _si_zero(config, {"T_Gar_M5_C4": 20.0})
    eng.check(cool, t0 + timedelta(seconds=90))
    assert any("CLEARED" in s[0] for s in sender.sent)


def test_garage_renotifies(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    hot = _si_zero(config, {"T_Gar_M5_C4": 29.0})
    eng.check(hot, t0)
    eng.check(hot, t0 + timedelta(seconds=61))  # trip
    eng.check(hot, t0 + timedelta(seconds=120))  # < 300 s, no re-notify
    assert len(sender.sent) == 1
    eng.check(hot, t0 + timedelta(seconds=61 + 301))  # past min_interval
    assert len(sender.sent) == 2
    assert "ONGOING" in sender.sent[1][0]


def test_frozen_detection(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    # frozen_count is 60 by default; feed identical values that many times.
    vals = _si_zero(config, {"T_Liv_M4_C7": 21.5})
    for i in range(config.quality.frozen_count):
        eng.check(vals, t0 + timedelta(seconds=i))
    assert any("FROZEN" in s[0] for s in sender.sent)


def test_dropout_watchdog(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    eng.check(_si_zero(config), t0)
    # No new record; check dropout past the threshold.
    events = eng.check_dropout(t0 + timedelta(seconds=config.quality.dropout_s + 5))
    assert any("DROPOUT" in e for e in events)


def test_email_disabled_still_reports(config):
    # Copy config and disable email; events still returned, sender not called.
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    eng._email_enabled = False
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    hot = _si_zero(config, {"T_Gar_M5_C4": 29.0})
    eng.check(hot, t0)
    events = eng.check(hot, t0 + timedelta(seconds=61))
    assert events  # event reported
    assert sender.sent == []  # but nothing emailed
