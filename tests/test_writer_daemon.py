#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the daily writer and daemon core.

Purpose: Confirm the writer produces the three files with correct headers and
    a sidecar, writes rows, and produces a valid atomic snapshot. Confirm the
    daemon single-cycle path reads, scales, and writes. Uses a temp output dir
    and the simulation backend, no hardware.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.
"""

import json

import pytest

from src.mh_daq.backends import SimulationBackend
from src.mh_daq.config import load_config
from src.mh_daq.daemon import AcquisitionDaemon
from src.mh_daq.scaling import scale_record
from src.mh_daq.writer import DailyWriter


@pytest.fixture(scope="module")
def config():
    return load_config()


def test_writer_creates_three_files_with_headers(config, tmp_path):
    with SimulationBackend(config, seed=1) as be:
        rec = be.read_record()
    si = scale_record(rec.values, config)
    with DailyWriter(config, base_dir=tmp_path) as w:
        w.write_indoor(rec.timestamp, rec.values, si)
        w.write_outdoor(rec.timestamp, {"wind_speed": "1.2", "air_temp": "20.1"})

    year = rec.timestamp.strftime("%Y")
    day = rec.timestamp.strftime("%Y%m%d")
    day_dir = tmp_path / year
    raw = (day_dir / f"{day}-MH_Indoor_raw.txt").read_text().splitlines()
    si_f = (day_dir / f"{day}-MH_Indoor_SI.txt").read_text().splitlines()
    out = (day_dir / f"{day}-MH_Outdoor.txt").read_text().splitlines()

    # Header plus one data row each.
    assert len(raw) == 2 and len(si_f) == 2 and len(out) == 2
    # SI header carries units in names.
    assert "T_Gar_M5_C4_degC" in si_f[0]
    assert "dP_Liv-Hi_M1_C0_Pa" in si_f[0]
    # Raw header labels thermocouple as degC, voltage as V.
    assert "T_blowermtr1_M6_C0_degC" in raw[0]
    assert "dP_Liv-Hi_M1_C0_V" in raw[0]
    # Outdoor header has the nine weather columns plus Date, Time.
    assert out[0].split("\t")[0:2] == ["Date", "Time"]
    assert "Battery_Voltage_V" in out[0]


def test_sidecar_written(config, tmp_path):
    with SimulationBackend(config, seed=1) as be:
        rec = be.read_record()
    si = scale_record(rec.values, config)
    with DailyWriter(config, base_dir=tmp_path) as w:
        w.write_indoor(rec.timestamp, rec.values, si)

    day = rec.timestamp.strftime("%Y%m%d")
    sidecar = tmp_path / rec.timestamp.strftime("%Y") / f"{day}-MH_metadata.json"
    data = json.loads(sidecar.read_text())
    assert data["date"] == day
    assert len(data["indoor_channels"]) == 42
    # A Setra entry carries its coefficients.
    setra = next(c for c in data["indoor_channels"] if c["channel"] == "dP_Liv-Hi_M1_C0")
    assert setra["si_unit"] == "Pa"
    assert setra["slope"] == 0.04


def test_snapshot_is_valid_json(config, tmp_path):
    with SimulationBackend(config, seed=1) as be:
        rec = be.read_record()
    si = scale_record(rec.values, config)
    with DailyWriter(config, base_dir=tmp_path) as w:
        w.write_snapshot(rec.timestamp, si, {"wind_speed": "1.2"})

    snap = json.loads((tmp_path / "latest_snapshot.json").read_text())
    assert "timestamp" in snap
    assert len(snap["indoor_si"]) == 42
    assert snap["outdoor"]["wind_speed"] == "1.2"


def test_daemon_run_once(config, tmp_path):
    be = SimulationBackend(config, seed=3)
    be.open()
    with DailyWriter(config, base_dir=tmp_path) as w:
        d = AcquisitionDaemon(config, be, w)
        si = d.run_once()
    be.close()
    assert len(si) == 42
    assert (tmp_path / "latest_snapshot.json").exists()


def test_daemon_multiple_cycles_append(config, tmp_path):
    be = SimulationBackend(config, seed=3)
    be.open()
    with DailyWriter(config, base_dir=tmp_path) as w:
        d = AcquisitionDaemon(config, be, w)
        ts = None
        for _ in range(5):
            d.run_once()
        # Peek the SI file line count.
        import glob

        files = glob.glob(str(tmp_path / "*" / "*-MH_Indoor_SI.txt"))
        lines = open(files[0], encoding="utf-8").read().splitlines()
    be.close()
    # One header plus five rows.
    assert len(lines) == 6
