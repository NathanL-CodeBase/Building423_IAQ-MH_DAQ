#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the simulation backend and the AIO 2 parser.

Purpose: Confirm the simulator produces in-range raw records that scale to
    plausible SI, respects lifecycle, and is reproducible by seed. Confirm the
    AIO 2 parser validates checksums and handles variable field counts.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.
"""

import pytest

from src.mh_daq.aio2 import Aio2ParseError, compute_checksum, parse_line
from src.mh_daq.backends import BackendError, SimulationBackend
from src.mh_daq.config import load_config
from src.mh_daq.scaling import scale_record


@pytest.fixture(scope="module")
def config():
    return load_config()


# ---- Simulation backend ----
def test_sim_record_has_all_channels(config):
    with SimulationBackend(config, seed=1) as be:
        rec = be.read_record()
    assert set(rec.values.keys()) == set(config.channel_names())


def test_sim_scales_to_plausible_si(config):
    with SimulationBackend(config, seed=1) as be:
        rec = be.read_record()
    si = scale_record(rec.values, config)
    # Room RH channel in a sane range.
    assert 20.0 <= si["RH_Bed1_M3_C0"] <= 70.0
    # Room temperature channel near the simulated midpoint.
    assert 15.0 <= si["T_Gar_M5_C4"] <= 30.0
    # Blower thermocouple warmer than room.
    assert 25.0 <= si["T_blowermtr1_M6_C0"] <= 45.0
    # Reference channel near 6 V.
    assert 5.9 <= si["6V_Test_M2_C7"] <= 6.1


def test_sim_reproducible_by_seed(config):
    with SimulationBackend(config, seed=42) as a:
        ra = a.read_record()
    with SimulationBackend(config, seed=42) as b:
        rb = b.read_record()
    # Same seed gives same first-sample noise for a given channel.
    assert ra.values["RH_Bed1_M3_C0"] == pytest.approx(rb.values["RH_Bed1_M3_C0"])


def test_sim_read_before_open_raises(config):
    be = SimulationBackend(config, seed=1)
    with pytest.raises(BackendError):
        be.read_record()


def test_sim_values_within_voltage_range(config):
    lo = config.voltage_range["min"]
    hi = config.voltage_range["max"]
    with SimulationBackend(config, seed=7) as be:
        rec = be.read_record()
    for ch in config.voltage_channels():
        assert lo <= rec.values[ch.name] <= hi


# ---- AIO 2 parser ----
def _line_with_checksum(body):
    """Build a valid line by appending the correct checksum to a body."""
    cs = sum(ord(c) for c in body)
    return f"{body}*{cs}"


def test_parse_both_optional_present():
    # WS,WD,AT,RH,BP,RN,SR,BV,CV,CONFIG
    body = "000.6,272,+023.6,022,0974.3,000.00,0000,12.7,240,U0"
    line = _line_with_checksum(body)
    f = parse_line(line)
    assert f["wind_speed"] == "000.6"
    assert f["battery_voltage"] == "12.7"
    assert f["compass_heading"] == "240"
    assert f["config"] == "U0"


def test_parse_bv_only():
    # WS,WD,AT,RH,BP,RN,SR,BV,CONFIG
    body = "000.0,000,+024.5,045,0970.5,000.00,0000,12.0,M0"
    line = _line_with_checksum(body)
    f = parse_line(line)
    assert f["battery_voltage"] == "12.0"
    assert "compass_heading" not in f
    assert f["config"] == "M0"


def test_parse_neither_optional():
    # WS,WD,AT,RH,BP,RN,SR,CONFIG
    body = "000.0,000,+024.5,045,0970.5,000.00,0000,M0"
    line = _line_with_checksum(body)
    f = parse_line(line)
    assert "battery_voltage" not in f
    assert "compass_heading" not in f
    assert f["config"] == "M0"


def test_checksum_mismatch_rejected():
    body = "000.6,272,+023.6,022,0974.3,000.00,0000,12.7,240,U0"
    bad = f"{body}*99999"
    with pytest.raises(Aio2ParseError):
        parse_line(bad)


def test_no_checksum_delimiter_rejected():
    with pytest.raises(Aio2ParseError):
        parse_line("000.6,272,+023.6,022,0974.3,000.00,0000,M0")


def test_empty_line_rejected():
    with pytest.raises(Aio2ParseError):
        parse_line("   ")


def test_compute_checksum_matches_manual_shape():
    # Any body: checksum is the decimal sum of character codes before '*'.
    body = "000.0,000,+024.5,045,0970.5,000.00,0000,M0"
    line = _line_with_checksum(body)
    assert compute_checksum(line) == sum(ord(c) for c in body)


def test_sim_serial_lines_parse():
    from src.mh_daq.aio2 import parse_line
    from src.mh_daq.backends.sim_serial import SimSerialSource

    src = SimSerialSource(seed=1, rate_hz=0)  # rate 0 = no sleep, for tests
    for _ in range(5):
        line = src.readline()
        fields = parse_line(line)  # raises if checksum or format is wrong
        assert "wind_speed" in fields
        assert "battery_voltage" in fields
        assert "compass_heading" in fields
    src.close()
