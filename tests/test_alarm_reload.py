#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for temporary alarm windows, live config reload, the Mission-outage
email, and channel_status in the sidecar.

Purpose: Confirm a temporary rule is silent outside its window, trips inside
    it, and sends a closing email if still tripped when the window ends; that
    the staged ozone rule on dP_Fam-W-Hi_M1_C6 trips below 15 Pa after its
    60 s dwell; that set_rules keeps state for unchanged rules; that the
    Mission check emails once past the limit and once on recovery; that the
    config watcher applies a valid edit, rejects a bad one with one email and
    keeps the running rules, and warns on a restart-only edit; and that the
    sidecar carries channel_status and updates only that key. Files live
    under tmp_path; no email leaves the process.
Author: Nathan Lima
Created: 2026-11-09
Update log:
    2026-11-09: Initial version.
"""

import json
import logging
import os
import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.mh_daq.alarms import AlarmEngine, RecordingEmailSender
from src.mh_daq.config import ConfigError, OfflineChannel, load_config
from src.mh_daq.config_watch import ConfigWatcher
from src.mh_daq.writer import DailyWriter

OZONE = "Family room west dP low (ozone remediation)"


@pytest.fixture(scope="module")
def config():
    return load_config()


def _si(config, **overrides):
    vals = {ch.name: 20.0 for ch in config.channels}
    vals.update(overrides)
    return vals


def _ozone(config):
    return {"dP_Fam-W-Hi_M1_C6": 10.0, "T_Gar_M5_C4": 20.0}


# ---------------------------------------------------------------------------
# Temporary windows
# ---------------------------------------------------------------------------
def test_ozone_rule_silent_before_window(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 11, 17, 23, 0, 0)
    low = _si(config, **_ozone(config))
    eng.check(low, t0)
    eng.check(low, t0 + timedelta(seconds=120))
    assert not any(OZONE in s[0] for s in sender.sent)


def test_ozone_rule_trips_inside_window(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 11, 19, 10, 0, 0)
    low = _si(config, **_ozone(config))
    eng.check(low, t0)
    eng.check(low, t0 + timedelta(seconds=61))
    trips = [s for s in sender.sent if s[0] == f"[MH DAQ] ALARM: {OZONE}"]
    assert len(trips) == 1
    subject, body, to = trips[0]
    assert "below 15.0 Pa" in body
    assert "Temporary rule, active 2026-11-18 00:00 to 2026-11-21 23:59" in body
    # Recipients come from alarm_rule_email (the template lists the rule).
    assert to == config.local.alarm_rule_email[OZONE]


def test_ozone_rule_at_or_above_limit_is_quiet(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 11, 19, 10, 0, 0)
    ok = _si(config, **{"dP_Fam-W-Hi_M1_C6": 15.0, "T_Gar_M5_C4": 20.0})
    eng.check(ok, t0)
    eng.check(ok, t0 + timedelta(seconds=61))
    assert not any(OZONE in s[0] for s in sender.sent)


def test_window_end_closes_tripped_rule(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 11, 21, 23, 58, 0)
    low = _si(config, **_ozone(config))
    eng.check(low, t0)
    eng.check(low, t0 + timedelta(seconds=61))  # 23:59:01, trips
    eng.check(low, t0 + timedelta(seconds=125))  # 00:00:05 on 11-22, window over
    subjects = [s[0] for s in sender.sent if OZONE in s[0]]
    assert subjects == [f"[MH DAQ] ALARM: {OZONE}", f"[MH DAQ] ALARM WINDOW ENDED: {OZONE}"]
    assert eng.current_state()["tripped_rules"] == []


# ---------------------------------------------------------------------------
# set_rules
# ---------------------------------------------------------------------------
def test_set_rules_keeps_unchanged_state(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    hot = _si(config, T_Gar_M5_C4=29.0)
    eng.check(hot, t0)
    eng.check(hot, t0 + timedelta(seconds=61))  # garage over-temp trips
    assert eng.set_rules(list(config.alarm_rules)) == []
    eng.check(hot, t0 + timedelta(seconds=90))
    # Still tripped: no second trip email after the reload.
    assert [s[0] for s in sender.sent].count("[MH DAQ] ALARM: Garage over-temperature") == 1


def test_set_rules_closes_changed_tripped_rule(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 9, 25, 12, 0, 0)
    hot = _si(config, T_Gar_M5_C4=29.0)
    eng.check(hot, t0)
    eng.check(hot, t0 + timedelta(seconds=61))
    rules = [
        replace(r, high=30.0) if r.description == "Garage over-temperature" else r
        for r in config.alarm_rules
    ]
    events = eng.set_rules(rules)
    assert events == ["[MH DAQ] ALARM RULE CHANGED: Garage over-temperature"]
    assert eng.current_state()["tripped_rules"] == []


# ---------------------------------------------------------------------------
# Mission outage
# ---------------------------------------------------------------------------
def test_mission_outage_emails_once_and_on_recovery(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    limit = config.quality.mission_outage_s
    t0 = datetime(2026, 11, 8, 23, 36, 0)
    assert eng.check_mission(None, t0) == []
    assert eng.check_mission(False, t0) == []
    assert eng.check_mission(False, t0 + timedelta(seconds=limit - 1)) == []
    assert eng.check_mission(False, t0 + timedelta(seconds=limit)) == [
        "[MH DAQ] MISSION UNREACHABLE"
    ]
    assert eng.check_mission(False, t0 + timedelta(hours=8)) == []
    assert eng.current_state()["mission_outage"] is True
    assert eng.check_mission(True, t0 + timedelta(hours=9)) == ["[MH DAQ] MISSION REACHABLE AGAIN"]
    assert "after 9.0 h" in sender.sent[-1][1]
    assert eng.current_state()["mission_outage"] is False


def test_short_mission_outage_is_quiet(config):
    sender = RecordingEmailSender()
    eng = AlarmEngine(config, sender)
    t0 = datetime(2026, 11, 8, 23, 29, 0)
    eng.check_mission(False, t0)
    eng.check_mission(True, t0 + timedelta(minutes=5))
    assert sender.sent == []


# ---------------------------------------------------------------------------
# Config validation and the watcher
# ---------------------------------------------------------------------------
def _copy_config(tmp_path):
    src = Path(os.environ["MH_DAQ_CONFIG_DIR"])
    dst = tmp_path / "cfg"
    dst.mkdir()
    shutil.copy(src / "daq_local.json", dst / "daq_local.json")
    shutil.copy(src / "daq_config.json", dst / "daq_config.json")
    return dst


def _edit(path, fn):
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    # Bump the mtime past any filesystem timestamp granularity.
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 2))


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda r: r.update(active_from="2026-11-22 00:00:00"), "not before active_until"),
        (lambda r: r.update(active_from="11/18/2026"), "is not YYYY-MM-DD HH:MM:SS"),
        (lambda r: r.update(category="sometimes"), "is not one of"),
        (lambda r: r.update(description="Garage over-temperature"), "descriptions repeat"),
    ],
)
def test_bad_temporary_rule_rejected(tmp_path, edit, message):
    cfg_dir = _copy_config(tmp_path)

    def apply(d):
        edit(next(r for r in d["alarms"]["rules"] if r["description"] == OZONE))

    _edit(cfg_dir / "daq_config.json", apply)
    with pytest.raises(ConfigError, match=message):
        load_config(config_dir=cfg_dir)


@pytest.fixture
def watched(tmp_path):
    cfg_dir = _copy_config(tmp_path)
    cfg = load_config(config_dir=cfg_dir)
    sender = RecordingEmailSender()
    eng = AlarmEngine(cfg, sender)
    writer = DailyWriter(cfg, base_dir=tmp_path / "data")
    watcher = ConfigWatcher(cfg, eng, writer)
    yield cfg_dir, eng, sender, writer, watcher
    writer.close()


def test_watcher_applies_new_rule(watched):
    cfg_dir, eng, sender, writer, watcher = watched
    assert watcher.poll() is False  # nothing changed yet

    def add_rule(d):
        d["alarms"]["rules"].append(
            {
                "channel": "T_Attic_M5_C5",
                "description": "Attic over-temperature (test)",
                "category": "temporary",
                "active_from": "2026-11-09 00:00:00",
                "active_until": "2026-11-10 00:00:00",
                "high": 50.0,
                "dwell_s": 0,
                "unit": "degC",
            }
        )

    _edit(cfg_dir / "daq_config.json", add_rule)
    assert watcher.poll() is True
    eng.check({"T_Attic_M5_C5": 55.0}, datetime(2026, 11, 9, 12, 0, 0))
    assert any("Attic over-temperature (test)" in s[0] for s in sender.sent)


def test_watcher_rejects_bad_edit_once(watched):
    cfg_dir, eng, sender, writer, watcher = watched
    before = [r.description for r in eng._rules]

    def bad(d):
        d["alarms"]["rules"].append(
            {"channel": "T_Nowhere_M9_C9", "description": "x", "high": 1, "dwell_s": 0, "unit": "degC"}
        )

    _edit(cfg_dir / "daq_config.json", bad)
    assert watcher.poll() is False
    assert watcher.poll() is False  # no change since; no second email
    rejected = [s for s in sender.sent if "CONFIG RELOAD REJECTED" in s[0]]
    assert len(rejected) == 1
    assert "unknown channel 'T_Nowhere_M9_C9'" in rejected[0][1]
    assert [r.description for r in eng._rules] == before


def test_watcher_warns_on_restart_only_edit(watched, caplog):
    cfg_dir, eng, sender, writer, watcher = watched
    _edit(cfg_dir / "daq_config.json", lambda d: d["acquisition"].update(record_rate_hz=2))
    with caplog.at_level(logging.WARNING, logger="mh_daq.config_watch"):
        assert watcher.poll() is True
    assert "only after a daemon restart" in caplog.text


# ---------------------------------------------------------------------------
# Sidecar channel_status
# ---------------------------------------------------------------------------
def test_sidecar_channel_status_written_and_updated(watched, tmp_path):
    cfg_dir, eng, sender, writer, watcher = watched
    now = datetime(2026, 11, 9, 12, 0, 0)
    writer.write_indoor(now, _si(load_config(config_dir=cfg_dir)), _si(load_config(config_dir=cfg_dir)))
    sidecar = tmp_path / "data" / "2026" / "20261109-MH_metadata.json"
    first = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(first["channel_status"]["offline"]) == 7
    assert first["channel_status"]["events"][0]["channel"] == "dP_Fam-W-Hi_M1_C6"

    writer.set_channel_status([OfflineChannel(channel="dP_Liv-Hi_M1_C0", reason="test")], [])
    second = json.loads(sidecar.read_text(encoding="utf-8"))
    assert [o["channel"] for o in second["channel_status"]["offline"]] == ["dP_Liv-Hi_M1_C0"]
    # Only channel_status changed.
    first.pop("channel_status")
    second.pop("channel_status")
    assert first == second


def test_sidecar_without_status_gets_it_on_restart(tmp_path, config):
    data = tmp_path / "data"
    (data / "2026").mkdir(parents=True)
    old = {"date": "20261109", "note": "older sidecar", "indoor_channels": []}
    path = data / "2026" / "20261109-MH_metadata.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    writer = DailyWriter(config, base_dir=data)
    try:
        writer.write_indoor(datetime(2026, 11, 9, 12, 0, 0), _si(config), _si(config))
    finally:
        writer.close()
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["note"] == "older sidecar"
    assert len(updated["channel_status"]["offline"]) == 7
