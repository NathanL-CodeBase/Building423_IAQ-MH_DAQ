#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real NI-DAQmx acquisition backend.

Purpose: Read the cDAQ-9178 through one DAQmx task combining voltage channels
    (NI 9201, RSE) and thermocouple channels (NI 9213, Type J, built-in CJC).
    Oversample at the configured rate, average to one record per output cycle,
    and return raw values: volts for voltage channels, degC for thermocouples.
    Scaling to SI is done downstream. This is the only module that touches
    hardware, so it is validated in the supervised cutover, not in pytest.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Task built in config (channel) order so the
        returned data columns align with config.channels. Finite acquisition
        per cycle, matching the NI MAX task (1 kHz, 100 samples).
"""

import logging
from datetime import datetime

import nidaqmx
import numpy as np
from nidaqmx.constants import (
    AcquisitionType,
    CJCSource,
    TerminalConfiguration,
    ThermocoupleType,
)

from ..config import ThermocoupleChannel, VoltageChannel
from .base import AcquisitionBackend, BackendError, RawRecord

logger = logging.getLogger("mh_daq.nidaqmx")

_TC_TYPE = {
    "J": ThermocoupleType.J,
    "K": ThermocoupleType.K,
    "T": ThermocoupleType.T,
    "E": ThermocoupleType.E,
    "N": ThermocoupleType.N,
    "R": ThermocoupleType.R,
    "S": ThermocoupleType.S,
    "B": ThermocoupleType.B,
}

_CJC = {
    "BUILT_IN": CJCSource.BUILT_IN,
    "CONSTANT_USER_VALUE": CJCSource.CONSTANT_USER_VALUE,
    "SCANNABLE_CHANNEL": CJCSource.SCANNABLE_CHANNEL,
}

_TERM = {
    "RSE": TerminalConfiguration.RSE,
    "NRSE": TerminalConfiguration.NRSE,
    "DIFF": TerminalConfiguration.DIFF,
    "PSEUDO_DIFF": TerminalConfiguration.PSEUDO_DIFF,
    "DEFAULT": TerminalConfiguration.DEFAULT,
}


class NiDaqmxBackend(AcquisitionBackend):
    """Reads the cDAQ through one mixed voltage-plus-thermocouple DAQmx task.

    Parameters
    ----------
    config : SystemConfig
    """

    def __init__(self, config):
        self._config = config
        self._task = None
        # Names in the exact order channels are added, so the returned sample
        # rows map back to channel names positionally.
        self._order = [c.name for c in config.channels]

    def open(self):
        if self._task is not None:
            return
        acq = self._config.acquisition
        term = _TERM[self._config.voltage_terminal_config]
        vmin = self._config.voltage_range["min"]
        vmax = self._config.voltage_range["max"]

        try:
            task = nidaqmx.Task()
            # Add channels in config order. DAQmx returns data in the order
            # channels were added, so this keeps rows aligned with self._order.
            for ch in self._config.channels:
                if isinstance(ch, VoltageChannel):
                    task.ai_channels.add_ai_voltage_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=ch.name,
                        terminal_config=term,
                        min_val=vmin,
                        max_val=vmax,
                    )
                elif isinstance(ch, ThermocoupleChannel):
                    task.ai_channels.add_ai_thrmcpl_chan(
                        ch.physical_channel,
                        name_to_assign_to_channel=ch.name,
                        min_val=ch.t_min,
                        max_val=ch.t_max,
                        thermocouple_type=_TC_TYPE[ch.thermocouple_type],
                        cjc_source=_CJC[ch.cjc_source],
                    )
                else:
                    raise BackendError(f"Unhandled channel type for '{ch.name}'.")

            # Finite acquisition each cycle: oversample then average.
            task.timing.cfg_samp_clk_timing(
                rate=acq.oversample_rate_hz,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=acq.samples_per_record,
            )
            self._task = task
            logger.info(
                "DAQmx task open: %d channels, %d Hz x %d samples per cycle.",
                len(self._order),
                acq.oversample_rate_hz,
                acq.samples_per_record,
            )
        except nidaqmx.DaqError as e:
            self._safe_close_task()
            raise BackendError(f"Failed to open DAQmx task: {e}") from e

    def read_record(self):
        if self._task is None:
            raise BackendError("read_record called before open().")
        acq = self._config.acquisition
        n = acq.samples_per_record
        # Timeout gives the finite acquisition time to complete plus margin.
        timeout = (n / acq.oversample_rate_hz) + 5.0
        try:
            data = self._task.read(number_of_samples_per_channel=n, timeout=timeout)
        except nidaqmx.DaqError as e:
            raise BackendError(f"DAQmx read failed: {e}") from e

        # data is a list of per-channel lists (one row per channel), in add
        # order. A single-channel task would return a flat list; guard for that.
        arr = np.asarray(data, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        means = arr.mean(axis=1)
        if len(means) != len(self._order):
            raise BackendError(
                f"Channel count mismatch: read {len(means)}, expected {len(self._order)}."
            )
        values = {name: float(m) for name, m in zip(self._order, means)}
        return RawRecord(timestamp=datetime.now(), values=values)

    def close(self):
        self._safe_close_task()

    def _safe_close_task(self):
        if self._task is not None:
            try:
                self._task.close()
            except Exception:
                pass
            self._task = None
