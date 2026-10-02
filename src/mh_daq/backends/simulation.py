#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulation acquisition backend.

Purpose: Produce realistic raw records with no hardware, so the full
    acquisition path (daemon, scaling, file writing, alarms) can be developed
    and tested on a machine without a cDAQ. Raw values are generated in the
    same units the real backend returns: volts for voltage channels chosen so
    the scaled SI value lands in a plausible range, and degC for thermocouples.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Per-scale plausible midpoints plus small
        deterministic-by-seed noise, and a diurnal drift on temperatures.
    2026-10-02: Import BackendError at module level.
"""

import math
import random
from datetime import datetime

from ..config import ThermocoupleChannel, VoltageChannel
from .base import AcquisitionBackend, BackendError, RawRecord

# Target SI midpoints per scale, used to back out a plausible raw voltage.
# These are illustrative operating points for simulation only, not calibration.
_SI_MIDPOINT = {
    "setra_264_01": 0.0,  # Pa, near zero dP
    "setra_264_025": 0.0,
    "setra_264_05": 0.0,
    "setra_264_1": 0.0,
    "setra_264_15": 0.0,
    "electra_flo_g5": 1200.0,  # m3/h return flow
    "watts_w002et": 400.0,  # W blower draw
    "hmp155_rh": 45.0,  # percent
    "hmp155_t": 21.0,  # degC
    "hmp45a_rh": 45.0,
    "hmp45a_t": 21.0,
    "volts": 6.0,  # reference channel sits near 6 V
}


def _volts_for_si(scale, si_target):
    """Invert the SI chain to find the raw volts that yield si_target.

    si = (slope * V + intercept) * si_factor + si_offset
    Solves for V. Used only by the simulator to place raw voltages so scaled
    values look realistic.
    """
    nominal = (si_target - scale.si_offset) / scale.si_factor
    return (nominal - scale.intercept) / scale.slope


class SimulationBackend(AcquisitionBackend):
    """Generate raw records without hardware.

    Parameters
    ----------
    config : SystemConfig
    seed : int, optional
        Seeds the RNG for reproducible test runs. Omit for varied output.
    """

    def __init__(self, config, seed=None):
        self._config = config
        self._rng = random.Random(seed)
        self._is_open = False
        self._t0 = datetime.now()

    def open(self):
        self._is_open = True
        self._t0 = datetime.now()

    def read_record(self):
        if not self._is_open:
            raise BackendError("read_record called before open().")

        now = datetime.now()
        # Slow diurnal term on temperatures, one cycle per simulated day.
        secs = (now - self._t0).total_seconds()
        diurnal = math.sin(2 * math.pi * secs / 86400.0)

        values = {}
        for ch in self._config.channels:
            if isinstance(ch, VoltageChannel):
                scale = self._config.scales[ch.scale]
                si_mid = _SI_MIDPOINT[ch.scale]
                # Add a small diurnal shift to temperature-like channels.
                if scale.si_unit == "degC":
                    si_mid = si_mid + 3.0 * diurnal
                base_v = _volts_for_si(scale, si_mid)
                noise = self._rng.gauss(0.0, 0.002)  # ~2 mV noise
                v = base_v + noise
                lo = self._config.voltage_range["min"]
                hi = self._config.voltage_range["max"]
                values[ch.name] = max(lo, min(hi, v))
            elif isinstance(ch, ThermocoupleChannel):
                # Blower motor thermocouple, warmer than room, in degC.
                values[ch.name] = 35.0 + 5.0 * diurnal + self._rng.gauss(0.0, 0.1)
            else:
                raise BackendError(f"Unhandled channel type for '{ch.name}'.")

        return RawRecord(timestamp=now, values=values)

    def close(self):
        self._is_open = False
