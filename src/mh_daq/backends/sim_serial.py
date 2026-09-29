#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulated AIO 2 serial source.

Purpose: Produce realistic AIO 2 output lines with valid checksums so the full
    outdoor path (parser, checksum validation, writer, snapshot, weather page)
    can run without a real sensor. Matches the AIO 2-9800 Rev E standard string
    with BV and CV enabled: WS,WD,AT,RH,BP,RN,SR,BV,CV,CONFIG,*CHECKSUM.
Author: Nathan Lima
Created: 2026-09-29
Update log:
    2026-09-29: Initial version. One line per readline call at ~1 Hz, with
        slow drift on wind, temperature, RH, and pressure.
"""

import math
import random
import time
from datetime import datetime

from ..serial_source import LineSource
from .base import BackendError  # noqa: F401  (kept for parity; not required)


def _checksum(body):
    """AIO 2 checksum: decimal sum of all characters before the asterisk."""
    return sum(ord(c) for c in body)


class SimSerialSource(LineSource):
    """Emit one synthetic AIO 2 line per readline call.

    Values drift slowly so trend plots show motion. Fields match the real
    device with BV and CV enabled. Rain and solar read zero (no external
    sensors), consistent with the real install.

    Parameters
    ----------
    seed : int, optional
        Seeds the RNG for reproducible output.
    rate_hz : float
        Lines per second. readline sleeps to approximate this.
    """

    def __init__(self, seed=None, rate_hz=1.0):
        self._rng = random.Random(seed)
        self._period = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self._t0 = time.monotonic()

    def readline(self):
        if self._period:
            time.sleep(self._period)
        secs = time.monotonic() - self._t0
        diurnal = math.sin(2 * math.pi * secs / 86400.0)

        wind = max(0.0, 2.0 + 1.5 * math.sin(secs / 120.0) + self._rng.gauss(0, 0.2))
        wdir = int((180 + 60 * math.sin(secs / 300.0) + self._rng.gauss(0, 3)) % 360)
        temp = 18.0 + 5.0 * diurnal + self._rng.gauss(0, 0.1)
        rh = min(99.0, max(10.0, 55.0 - 10.0 * diurnal + self._rng.gauss(0, 0.5)))
        bp = 1000.0 + 3.0 * math.sin(secs / 3600.0) + self._rng.gauss(0, 0.1)
        batt = 23.2 + self._rng.gauss(0, 0.02)
        compass = 32

        # Fixed-width fields matching the manual's format.
        body = (
            f"{wind:05.1f},{wdir:03d},{temp:+06.1f},{int(round(rh)):03d},"
            f"{bp:06.1f},000.00,0000,{batt:04.1f},{compass:03d},M0"
        )
        return f"{body}*{_checksum(body)}"

    def close(self):
        pass
