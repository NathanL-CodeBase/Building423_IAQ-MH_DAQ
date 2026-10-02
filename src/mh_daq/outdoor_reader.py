#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIO 2 outdoor acquisition reader.

Purpose: Read AIO 2 lines from a LineSource, checksum-validate and parse each,
    write the outdoor daily file with the line's own arrival timestamp, and
    publish the latest outdoor fields for the snapshot. Runs on its own thread
    and retries its serial resource independently, so a weather-sensor fault
    never stops indoor acquisition.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Threaded read loop with malformed-line
        throttling and independent reconnect, mirroring the resilience of the
        temp weather script.
    2026-10-02: Add set_publish so the supervisor wires the publish callback
        without touching a private attribute. Add LatestFields, a locked
        holder for the latest outdoor fields shared across threads.
"""

import logging
import threading
import time
from datetime import datetime

from .aio2 import Aio2ParseError, parse_line

logger = logging.getLogger("mh_daq.outdoor")

_MALFORMED_LOG_INTERVAL_S = 60


class LatestFields:
    """Thread-safe holder for the most recent parsed outdoor fields.

    The outdoor thread calls set; the indoor loop and heartbeat call get. Both
    sides work on copies, so neither sees the other's dict mid-update.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._fields = {}

    def set(self, fields):
        with self._lock:
            self._fields = dict(fields)

    def get(self):
        with self._lock:
            return dict(self._fields)


class OutdoorReader:
    """Threaded AIO 2 reader.

    Parameters
    ----------
    config : SystemConfig
    writer : DailyWriter
        Provides write_outdoor.
    source_factory : callable
        Returns a fresh LineSource. Called on start and on each reconnect, so a
        dropped port can be reopened. In production this wraps PySerialSource on
        the resolved port; in tests it returns a canned source.
    publish : callable, optional
        Called with the latest parsed fields dict after each valid line, so the
        indoor snapshot can include current weather. Defaults to a no-op.
    """

    def __init__(self, config, writer, source_factory, publish=None):
        self._config = config
        self._writer = writer
        self._source_factory = source_factory
        self._publish = publish or (lambda fields: None)
        self._stop = threading.Event()
        self._reconnect_wait_s = 5.0

    def set_publish(self, publish):
        """Set the callable that receives each valid line's parsed fields."""
        self._publish = publish

    def run_loop(self):
        """Read, parse, write, and publish until stopped. Reconnects on error."""
        logger.info("Outdoor reader started.")
        malformed = 0
        window = time.monotonic()
        src = None
        try:
            while not self._stop.is_set():
                if src is None:
                    src = self._open_source()
                    if src is None:
                        self._stop.wait(self._reconnect_wait_s)
                        continue
                try:
                    line = src.readline()
                except Exception as e:
                    logger.error("Serial read error: %s; reconnecting.", e)
                    self._safe_close(src)
                    src = None
                    self._stop.wait(self._reconnect_wait_s)
                    continue

                if not line:
                    continue
                try:
                    fields = parse_line(line)
                except Aio2ParseError:
                    malformed += 1
                    elapsed = time.monotonic() - window
                    if elapsed >= _MALFORMED_LOG_INTERVAL_S:
                        logger.warning(
                            "%d malformed AIO 2 line(s) in %.0f s.",
                            malformed,
                            elapsed,
                        )
                        malformed = 0
                        window = time.monotonic()
                    continue

                now = datetime.now()  # outdoor path uses its own arrival time
                self._writer.write_outdoor(now, fields)
                self._publish(fields)
        finally:
            self._safe_close(src)
            logger.info("Outdoor reader stopped.")

    def _open_source(self):
        try:
            return self._source_factory()
        except Exception as e:
            logger.error("Could not open AIO 2 source: %s; will retry.", e)
            return None

    @staticmethod
    def _safe_close(src):
        if src is not None:
            try:
                src.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
