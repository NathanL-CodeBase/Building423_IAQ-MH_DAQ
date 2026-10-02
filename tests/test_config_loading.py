#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for config file loading.

Purpose: Confirm load_config accepts config files saved with a UTF-8
    byte-order mark, as written by Windows PowerShell 5.1 and older Notepad,
    and still rejects files that are not valid JSON. Works on copies of the
    session test config, never the committed files.
Author: Nathan Lima
Created: 2026-10-02
Update log:
    2026-10-02: Initial version.
"""

import os
from pathlib import Path

import pytest

from src.mh_daq.config import ConfigError, load_config

_BOM = b"\xef\xbb\xbf"


def _copy_config(dst, bom):
    src = Path(os.environ["MH_DAQ_CONFIG_DIR"])
    for name in ("daq_config.json", "daq_local.json"):
        data = (src / name).read_bytes()
        (dst / name).write_bytes((_BOM if bom else b"") + data)


@pytest.mark.parametrize("bom", [False, True])
def test_loads_with_and_without_bom(tmp_path, bom):
    _copy_config(tmp_path, bom)
    cfg = load_config(config_dir=tmp_path)
    assert len(cfg.channels) == 42
    assert cfg.local.machine_name == "pytest"


def test_invalid_json_still_rejected(tmp_path):
    _copy_config(tmp_path, bom=True)
    (tmp_path / "daq_local.json").write_bytes(_BOM + b"{ not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(config_dir=tmp_path)
