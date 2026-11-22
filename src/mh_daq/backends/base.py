#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared acquisition backend interface.

Purpose: Define the contract every backend implements, so the daemon reads the
    cDAQ the same way whether the source is real hardware (nidaqmx) or the
    simulator. Backends return raw values only (volts for voltage channels,
    degC for thermocouples). Scaling to SI is a separate concern handled by the
    daemon via scaling.scale_record.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Abstract base with lifecycle (open, close,
        context manager) and read_record returning a raw record.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class BackendError(Exception):
    """Raised on backend acquisition or lifecycle failures."""


@dataclass
class RawRecord:
    """One acquired record before scaling.

    Attributes
    ----------
    timestamp : datetime
        Local time the record was produced.
    values : dict
        Channel name to raw reading. Voltage channels in volts, thermocouple
        channels in degC (the NI 9213 driver returns temperature directly).
    """

    timestamp: datetime
    values: dict


class AcquisitionBackend(ABC):
    """Interface for a cDAQ acquisition source.

    Lifecycle: construct, then open() to reserve resources and configure the
    task, call read_record() once per record interval, and close() to release.
    Supports use as a context manager so resources are always released.
    """

    @abstractmethod
    def open(self):
        """Reserve hardware and configure the acquisition task.

        Raises
        ------
        BackendError
            If the task cannot be created or channels cannot be reserved.
        """

    @abstractmethod
    def read_record(self):
        """Acquire and return one averaged raw record.

        The record represents one output-rate sample (1 Hz), averaged from the
        oversampled acquisition per the config. Values are raw: volts for
        voltage channels, degC for thermocouples.

        Returns
        -------
        RawRecord

        Raises
        ------
        BackendError
            On read timeout or acquisition error.
        """

    @abstractmethod
    def close(self):
        """Release hardware and clear the task. Safe to call more than once."""

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
