#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared pytest setup for the MH DAQ tests.

Purpose: Build a throwaway config directory for the whole test session, so
    tests run on a fresh clone without a machine-specific daq_local.json and
    never write to a real data folder. The committed daq_config.json is copied
    as-is; daq_local.json is made from daq_local.template.json with the
    placeholders filled and every path pointed into the temp directory.
    MH_DAQ_CONFIG_DIR tells load_config to read from there.
Author: Nathan Lima
Created: 2026-10-02
Update log:
    2026-10-02: Initial version.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

_REPO_CONFIG = Path(__file__).resolve().parent.parent / "config"
_session_dir = None


def pytest_configure(config):
    global _session_dir
    _session_dir = Path(tempfile.mkdtemp(prefix="mh_daq_tests_"))
    cfg_dir = _session_dir / "config"
    cfg_dir.mkdir()
    shutil.copy(_REPO_CONFIG / "daq_config.json", cfg_dir / "daq_config.json")

    with open(_REPO_CONFIG / "daq_local.template.json", encoding="utf-8") as f:
        local = json.load(f)
    local["machine_name"] = "pytest"
    local["paths"] = {
        "local_data_dir": str(_session_dir / "local"),
        "mission_data_dir": str(_session_dir / "mission"),
        "mission_snapshot_dir": str(_session_dir / "mission_snapshot"),
    }
    local["smtp"]["from_addr"] = "pytest-sender@example.invalid"
    local["smtp"]["to_addrs"] = ["pytest-recipient@example.invalid"]
    with open(cfg_dir / "daq_local.json", "w", encoding="utf-8") as f:
        json.dump(local, f, indent=2)

    os.environ["MH_DAQ_CONFIG_DIR"] = str(cfg_dir)


def pytest_unconfigure(config):
    # Only the directory this module created is removed.
    if _session_dir is not None:
        shutil.rmtree(_session_dir, ignore_errors=True)
