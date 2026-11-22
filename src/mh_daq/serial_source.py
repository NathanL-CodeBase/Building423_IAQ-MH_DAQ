#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serial line sources for the AIO 2 reader.

Purpose: Provide a small interface over "give me the next line" so the AIO 2
    reader can run against a real serial port in production and a canned source
    in tests. Also provides COM port auto-detection that identifies the AIO 2 by
    reading a line and checksum-validating it.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. PySerialSource, auto_detect_port, and an
        abstract LineSource. Detection validates a candidate port by parsing a
        real line rather than trusting the port description.
"""

import logging
from abc import ABC, abstractmethod

import serial
import serial.tools.list_ports

from .aio2 import Aio2ParseError, parse_line

logger = logging.getLogger("mh_daq.serial")


class LineSource(ABC):
    """A source of decoded text lines."""

    @abstractmethod
    def readline(self):
        """Return the next decoded line (may be empty on timeout)."""

    @abstractmethod
    def close(self):
        """Release the underlying resource."""


class PySerialSource(LineSource):
    """Read newline-terminated ASCII from a serial port.

    Parameters
    ----------
    port : str
    baud, bytesize, parity, stopbits : serial params
    timeout_s : float
    """

    def __init__(self, port, baud=9600, bytesize=8, parity="N", stopbits=1, timeout_s=2.0):
        self._ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS if bytesize == 8 else bytesize,
            parity=serial.PARITY_NONE if parity == "N" else parity,
            stopbits=serial.STOPBITS_ONE if stopbits == 1 else stopbits,
            timeout=timeout_s,
        )
        self.port = port

    def readline(self):
        raw = self._ser.readline()
        if not raw:
            return ""
        return raw.decode("ascii", errors="replace").strip()

    def close(self):
        try:
            self._ser.close()
        except Exception:
            pass


def auto_detect_port(baud=9600, timeout_s=2.0, attempts=3):
    """Find the COM port emitting valid AIO 2 lines.

    Opens each candidate port, reads a few lines, and accepts the first port
    that yields a checksum-valid AIO 2 line. Validating by content, not by the
    port's description, avoids the Windows serial-mouse mislabeling problem and
    picks the right adapter even if several USB serial ports are present.

    Parameters
    ----------
    baud : int
    timeout_s : float
    attempts : int
        Lines to read per candidate before giving up on it.

    Returns
    -------
    str or None
        The detected port name, or None if no port produced a valid line.
    """
    for info in serial.tools.list_ports.comports():
        port = info.device
        try:
            src = PySerialSource(port, baud=baud, timeout_s=timeout_s)
        except (serial.SerialException, OSError) as e:
            logger.debug("Port %s not openable: %s", port, e)
            continue
        try:
            for _ in range(attempts):
                line = src.readline()
                if not line:
                    continue
                try:
                    parse_line(line)
                    logger.info("AIO 2 detected on %s.", port)
                    return port
                except Aio2ParseError:
                    continue
        finally:
            src.close()
    logger.warning("No AIO 2 port detected.")
    return None


def resolve_port(config):
    """Resolve the configured COM port, auto-detecting if set to AUTO.

    Returns the port string or None if AUTO detection found nothing.
    """
    configured = config.local.com_port
    if configured and configured.upper() != "AUTO":
        return configured
    return auto_detect_port(baud=config.local.auto_detect_baud)
