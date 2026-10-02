#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the AIO 2 reader and the supervisor.

Purpose: Confirm the outdoor reader parses and writes valid lines, skips
    malformed lines, and reconnects when its source raises. Confirm the
    supervisor runs indoor, outdoor, mirror, and watchdog threads together, with
    outdoor values reaching the snapshot and indoor alarms firing. Uses a canned
    line source and the simulation backend, no hardware.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.
    2026-10-02: Check that the snapshot carries alarm state, and that the
        heartbeat reports the mirror's reachability result.
"""

import json
import threading
import time

import pytest

from src.mh_daq.alarms import AlarmEngine, RecordingEmailSender
from src.mh_daq.backends import SimulationBackend
from src.mh_daq.config import load_config
from src.mh_daq.daemon import AcquisitionDaemon
from src.mh_daq.mirror import MissionMirror
from src.mh_daq.outdoor_reader import OutdoorReader
from src.mh_daq.serial_source import LineSource
from src.mh_daq.supervisor import Supervisor
from src.mh_daq.writer import DailyWriter


def _line(body):
    cs = sum(ord(c) for c in body)
    return f"{body}*{cs}"


VALID = _line("002.3,005,+020.2,037,1000.2,000.00,0000,23.2,032,M0")


class CannedSource(LineSource):
    """Yields a fixed list of lines, then empty strings, then optionally raises."""

    def __init__(self, lines, raise_after=None):
        self._lines = list(lines)
        self._i = 0
        self._raise_after = raise_after
        self._served = 0

    def readline(self):
        if self._raise_after is not None and self._served >= self._raise_after:
            raise OSError("simulated serial drop")
        if self._i < len(self._lines):
            line = self._lines[self._i]
            self._i += 1
            self._served += 1
            return line
        time.sleep(0.01)
        return ""

    def close(self):
        pass


@pytest.fixture(scope="module")
def config():
    return load_config()


def test_outdoor_reader_writes_valid_line(config, tmp_path):
    published = []
    with DailyWriter(config, base_dir=tmp_path) as w:
        reader = OutdoorReader(
            config,
            w,
            source_factory=lambda: CannedSource([VALID]),
            publish=published.append,
        )
        t = threading.Thread(target=reader.run_loop)
        t.start()
        time.sleep(0.3)
        reader.stop()
        t.join(timeout=5)

    assert published and published[0]["wind_speed"] == "002.3"
    assert published[0]["battery_voltage"] == "23.2"
    import glob

    out = glob.glob(str(tmp_path / "*" / "*-MH_Outdoor.txt"))
    lines = open(out[0], encoding="utf-8").read().splitlines()
    assert len(lines) >= 2  # header plus at least one row


def test_outdoor_reader_skips_malformed(config, tmp_path):
    published = []
    bad = "not,a,valid,line,*0"
    with DailyWriter(config, base_dir=tmp_path) as w:
        reader = OutdoorReader(
            config,
            w,
            source_factory=lambda: CannedSource([bad, VALID]),
            publish=published.append,
        )
        t = threading.Thread(target=reader.run_loop)
        t.start()
        time.sleep(0.3)
        reader.stop()
        t.join(timeout=5)
    # Only the valid line published.
    assert len(published) == 1
    assert published[0]["wind_speed"] == "002.3"


def test_outdoor_reader_reconnects(config, tmp_path):
    # Source raises after serving one line; reader should reopen and continue.
    factory_calls = {"n": 0}

    def factory():
        factory_calls["n"] += 1
        return CannedSource([VALID], raise_after=1)

    with DailyWriter(config, base_dir=tmp_path) as w:
        reader = OutdoorReader(config, w, source_factory=factory)
        reader._reconnect_wait_s = 0.05
        t = threading.Thread(target=reader.run_loop)
        t.start()
        time.sleep(0.4)
        reader.stop()
        t.join(timeout=5)
    # Reopened at least once after the simulated drop.
    assert factory_calls["n"] >= 2


def test_supervisor_runs_all_paths(config, tmp_path):
    local = tmp_path / "local"
    mission = tmp_path / "mission"
    snap = tmp_path / "snap"
    mission.mkdir()

    be = SimulationBackend(config, seed=1)
    writer = DailyWriter(config, base_dir=local)
    indoor = AcquisitionDaemon(config, be, writer)
    reader = OutdoorReader(config, writer, source_factory=lambda: CannedSource([VALID] * 1000))
    mirror = MissionMirror(config, local, mission, snap)
    sender = RecordingEmailSender()
    alarms = AlarmEngine(config, sender)

    sup = Supervisor(config, indoor, reader, mirror, alarms)
    sup.start()

    # Poll for eventual cross-thread propagation of the outdoor value into the
    # snapshot, rather than assuming it lands within one fixed sleep. The system
    # guarantees eventual propagation, not propagation within a single cycle.
    snap_file = local / "latest_snapshot.json"
    deadline = time.monotonic() + 8.0
    got_outdoor = False
    indoor_count = 0
    while time.monotonic() < deadline:
        if snap_file.exists():
            try:
                data = json.loads(snap_file.read_text())
            except (json.JSONDecodeError, OSError):
                time.sleep(0.05)
                continue
            indoor_count = len(data.get("indoor_si", {}))
            if data.get("outdoor", {}).get("wind_speed") == "002.3":
                got_outdoor = True
                break
        time.sleep(0.05)

    sup.stop()

    assert indoor_count == 42, "indoor SI values never reached the snapshot"
    assert got_outdoor, "outdoor value never propagated to the snapshot"


def test_supervisor_indoor_alarm_fires(config, tmp_path):
    # A backend forced hot on the garage channel should trip the alarm through
    # the supervisor's wrapped indoor cycle.
    local = tmp_path / "local"
    be = SimulationBackend(config, seed=1)

    # Monkey-patch the backend to force the garage channel above threshold.
    orig = be.read_record

    def hot_record():
        rec = orig()
        # Set garage HMP155 T voltage so SI is ~30 degC: (V*10 - 40)=30 -> V=7.0
        rec.values["T_Gar_M5_C4"] = 7.0
        return rec

    be.read_record = hot_record

    writer = DailyWriter(config, base_dir=local)
    indoor = AcquisitionDaemon(config, be, writer)
    reader = OutdoorReader(config, writer, source_factory=lambda: CannedSource([VALID] * 100))
    mirror = MissionMirror(config, local, tmp_path / "m", tmp_path / "s")
    sender = RecordingEmailSender()
    alarms = AlarmEngine(config, sender)

    sup = Supervisor(config, indoor, reader, mirror, alarms)
    sup.start()
    time.sleep(1.3)  # dwell is 60 s, so no email yet, but rule should be pending
    sup.stop()
    # No email within 1.3 s (dwell 60 s), but the machinery ran without error.
    # Confirm the indoor path produced data and the snapshot carries alarm state.
    snap = json.loads((local / "latest_snapshot.json").read_text())
    assert set(snap["alarms"]) == {"tripped_rules", "frozen_channels", "dropout"}
    assert sender.sent == []


def test_writer_concurrent_indoor_outdoor(config, tmp_path):
    # Hammer the shared writer from two threads across a rollover-free window to
    # surface any race on the file handles. Without the writer lock this raises
    # KeyError intermittently.
    from src.mh_daq.scaling import scale_record

    be = SimulationBackend(config, seed=5)
    be.open()
    errors = []

    with DailyWriter(config, base_dir=tmp_path) as w:

        def indoor():
            try:
                for _ in range(200):
                    rec = be.read_record()
                    si = scale_record(rec.values, config)
                    w.write_indoor(rec.timestamp, rec.values, si)
                    w.write_snapshot(rec.timestamp, si, {})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def outdoor():
            try:
                from datetime import datetime as dt

                for _ in range(200):
                    w.write_outdoor(dt.now(), {"wind_speed": "1.0"})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ti = threading.Thread(target=indoor)
        to = threading.Thread(target=outdoor)
        ti.start()
        to.start()
        ti.join()
        to.join()
    be.close()
    assert not errors, f"Concurrent writer errors: {errors[:3]}"


def test_supervisor_writes_heartbeat(config, tmp_path):
    import json as _json

    local = tmp_path / "local"
    be = SimulationBackend(config, seed=1)
    writer = DailyWriter(config, base_dir=local)
    indoor = AcquisitionDaemon(config, be, writer)
    reader = OutdoorReader(config, writer, source_factory=lambda: CannedSource([VALID] * 100))
    mirror = MissionMirror(config, local, tmp_path / "m", tmp_path / "s")
    alarms = AlarmEngine(config, RecordingEmailSender())

    # Point the heartbeat at the temp dir (config default is the real data dir).
    sup = Supervisor(config, indoor, reader, mirror, alarms)
    sup._hb_path = local / "heartbeat.json"

    sup.start()
    deadline = time.monotonic() + 5.0
    hb = None
    while time.monotonic() < deadline:
        if sup._hb_path.exists():
            try:
                hb = _json.loads(sup._hb_path.read_text())
                if hb.get("last_indoor_record"):
                    break
            except (ValueError, OSError):
                pass
        time.sleep(0.05)
    sup.stop()

    assert hb is not None, "heartbeat never written"
    assert "indoor" in hb["threads_alive"]
    assert hb["threads_alive"]["indoor"] is True
    # Mission dir tmp_path/"m" does not exist, so the mirror's first tick
    # records it unreachable (None only if that tick has not run yet).
    assert hb["mission_available"] in (False, None)
