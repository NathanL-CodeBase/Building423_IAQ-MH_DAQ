#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the display_ranges config block.

Purpose: Confirm the committed living-space T and RH ranges load with the
    expected limits and channels, and that validation rejects an unknown
    channel, a unit mismatch, inverted limits, and a channel listed twice.
    Each failure case edits a copy of the session test config, never the
    committed file.
Author: Nathan Lima
Created: 2026-10-02
Update log:
    2026-10-02: Initial version.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from src.mh_daq.config import ConfigError, load_config


@pytest.fixture(scope="module")
def config():
    return load_config()


def test_committed_ranges_load(config):
    by_name = {dr.name: dr for dr in config.display_ranges}
    t = by_name["Living-space temperature"]
    rh = by_name["Living-space relative humidity"]
    assert (t.low, t.high, t.unit) == (18.0, 25.0, "degC")
    assert (rh.low, rh.high, rh.unit) == (40.0, 60.0, "percent")
    assert len(t.channels) == 8 and len(rh.channels) == 8
    # Non-living-space zones stay uncolored.
    colored = set(t.channels) | set(rh.channels)
    for ch in ("T_Gar_M5_C4", "T_Attic_M5_C5", "T_Out_M5_C6", "T_HVAC-S_M5_C7",
               "T_blowermtr1_M6_C0", "RH_Gar_M4_C0", "RH_Out_M4_C2", "RH_HVAC-S_M4_C3"):
        assert ch not in colored


def _load_with(tmp_path, edit):
    """Copy the session config to tmp_path, apply edit to daq_config, load it."""
    src = Path(os.environ["MH_DAQ_CONFIG_DIR"])
    shutil.copy(src / "daq_local.json", tmp_path / "daq_local.json")
    committed = json.loads((src / "daq_config.json").read_text(encoding="utf-8"))
    edit(committed["display_ranges"]["rules"])
    (tmp_path / "daq_config.json").write_text(json.dumps(committed), encoding="utf-8")
    return load_config(config_dir=tmp_path)


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda rules: rules[0]["channels"].append("T_Nowhere_M9_C9"), "unknown channel"),
        (lambda rules: rules[0].update(unit="degF"), "does not match"),
        (lambda rules: rules[0].update(low=26.0), "not below high"),
        (lambda rules: rules[0].update(low=None, high=None), "neither low nor high"),
        (lambda rules: rules[1]["channels"].append("T_Liv_M4_C7"), "is in display ranges"),
    ],
)
def test_bad_ranges_rejected(tmp_path, edit, message):
    with pytest.raises(ConfigError, match=message):
        _load_with(tmp_path, edit)


def test_ranges_optional(tmp_path):
    cfg = _load_with(tmp_path, lambda rules: rules.clear())
    assert cfg.display_ranges == []
