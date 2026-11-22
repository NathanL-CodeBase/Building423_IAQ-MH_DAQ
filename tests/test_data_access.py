#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the web data-access roots.

Purpose: Check that MH_DAQ_SOURCE selects where the web layer reads. Local mode
    reads the daemon's own folder (or MH_DAQ_DATA_ROOT); mission mode reads the
    dailies from mission_data_dir/<mission_subdir> and the snapshot and
    heartbeat from mission_snapshot_dir, matching where MissionMirror copies
    them. A wrong source name must fail rather than silently read local.
Author: Nathan Lima
Created: 2026-10-08
Update log:
    2026-10-08: Initial version.
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.mh_daq.config import load_config
from src.mh_daq.mirror import MissionMirror
from web import data_access


@pytest.fixture
def cfg():
    return load_config()


def test_local_mode_reads_local_dir(monkeypatch, cfg):
    monkeypatch.delenv("MH_DAQ_SOURCE", raising=False)
    monkeypatch.delenv("MH_DAQ_DATA_ROOT", raising=False)
    assert data_access.daily_root() == Path(cfg.local.local_data_dir)
    assert data_access.snapshot_root() == Path(cfg.local.local_data_dir)


def test_local_mode_honors_data_root_override(monkeypatch, tmp_path):
    monkeypatch.delenv("MH_DAQ_SOURCE", raising=False)
    monkeypatch.setenv("MH_DAQ_DATA_ROOT", str(tmp_path))
    assert data_access.daily_root() == tmp_path
    assert data_access.snapshot_root() == tmp_path


def test_mission_mode_matches_mirror_layout(monkeypatch, cfg):
    monkeypatch.setenv("MH_DAQ_SOURCE", "Mission")
    # The override is for local copies only; it must not redirect mission reads.
    monkeypatch.setenv("MH_DAQ_DATA_ROOT", "ignored")
    local_file = Path(cfg.local.local_data_dir) / "2026" / "20261008-MH_Indoor_SI.txt"
    mirrored = MissionMirror(cfg)._mission_daily_path(local_file)
    assert data_access._daily_path("indoor_si", datetime(2026, 10, 8)) == mirrored
    assert data_access.snapshot_root() == Path(cfg.local.mission_snapshot_dir)


def test_unknown_source_raises(monkeypatch):
    monkeypatch.setenv("MH_DAQ_SOURCE", "elwood")
    with pytest.raises(ValueError, match="MH_DAQ_SOURCE"):
        data_access.daily_root()
