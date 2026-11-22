#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for voltage-to-SI scaling.

Purpose: Assert that every scale in daq_config.json converts its raw voltage
    endpoints to the expected SI values, so a wrong coefficient is caught
    before any hardware run. Endpoints derived from the NI MAX coefficients
    chained to SI, with inch WC to Pa at 248.84 (60 degF basis).
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.
"""

import pytest

from src.mh_daq.config import load_config
from src.mh_daq.scaling import (
    scale_record,
    scale_voltage,
    si_units_by_channel,
)


@pytest.fixture(scope="module")
def config():
    return load_config()


# scale name -> list of (volts, expected_si)
ENDPOINTS = {
    "setra_264_01": [(0.0, -24.884), (2.5, 0.0), (5.0, 24.884)],
    "setra_264_025": [(0.0, -62.21), (5.0, 62.21)],
    "setra_264_05": [(0.0, -124.42), (5.0, 124.42)],
    "setra_264_1": [(0.0, -248.84), (5.0, 248.84)],
    "setra_264_15": [(0.0, -373.26), (5.0, 373.26)],
    "electra_flo_g5": [(0.0, 0.0), (10.0, 3398.02)],
    "watts_w002et": [(2.0, 0.0), (10.0, 1000.0)],
    "hmp155_rh": [(0.0, 0.0), (10.0, 100.0)],
    "hmp155_t": [(0.0, -40.0), (10.0, 60.0)],
    "hmp45a_rh": [(0.0, 0.0), (1.0, 100.0)],
    "hmp45a_t": [(0.0, -40.0), (1.0, 60.0)],
    "volts": [(0.0, 0.0), (6.0, 6.0)],
}


@pytest.mark.parametrize("scale_name", list(ENDPOINTS.keys()))
def test_scale_endpoints(config, scale_name):
    scale = config.scales[scale_name]
    for volts, expected in ENDPOINTS[scale_name]:
        result = scale_voltage(volts, scale)
        assert result == pytest.approx(expected, abs=0.01), (
            f"{scale_name} at {volts} V gave {result}, expected {expected}"
        )


def test_all_scales_covered(config):
    # A newly added scale with no endpoint test should fail here, so no scale
    # ships unverified.
    assert set(config.scales.keys()) == set(ENDPOINTS.keys())


def test_thermocouple_passthrough(config):
    tc = config.thermocouple_channels()[0]
    raw = {ch.name: 0.0 for ch in config.channels}
    raw[tc.name] = 47.3
    si = scale_record(raw, config)
    assert si[tc.name] == pytest.approx(47.3)


def test_scale_record_voltage(config):
    # HMP155 T at 6.5 V is 10 * 6.5 - 40 = 25.0 degC.
    raw = {ch.name: 0.0 for ch in config.channels}
    raw["T_Gar_M5_C4"] = 6.5
    si = scale_record(raw, config)
    assert si["T_Gar_M5_C4"] == pytest.approx(25.0, abs=0.01)


def test_missing_channel_raises(config):
    raw = {ch.name: 0.0 for ch in config.channels}
    del raw["T_Gar_M5_C4"]
    with pytest.raises(KeyError):
        scale_record(raw, config)


def test_si_units(config):
    units = dict(si_units_by_channel(config))
    assert units["dP_Liv-Hi_M1_C0"] == "Pa"
    assert units["cfm_return_duct_M2_C1"] == "m3/h"
    assert units["watts_blowermtr_M2_C2"] == "W"
    assert units["RH_Bed1_M3_C0"] == "percent"
    assert units["T_Gar_M5_C4"] == "degC"
    assert units["T_blowermtr1_M6_C0"] == "degC"
    assert units["6V_Test_M2_C7"] == "V"


def test_record_length(config):
    raw = {ch.name: 0.0 for ch in config.channels}
    si = scale_record(raw, config)
    assert len(si) == 42
