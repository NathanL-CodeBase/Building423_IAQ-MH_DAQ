#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Acquisition daemon core for the MH DAQ system.

Purpose: Drive one acquisition cycle per record interval: read a raw record
    from the backend, scale it to SI, write indoor raw and SI rows, and update
    the snapshot. Outdoor (AIO 2) acquisition runs on its own path and is wired
    in a later step; the core here focuses on the cDAQ loop and a clean,
    testable single-cycle method so timing and I/O are separable from logic.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. run_once for a single cycle (used by tests),
        and run_loop with a monotonic-clock pace and graceful stop.
"""

import logging
import threading
import time
from datetime import datetime

from .scaling import scale_record

logger = logging.getLogger("mh_daq.daemon")


class AcquisitionDaemon:
    """Coordinates backend, scaling, and writer for the indoor cDAQ path.

    Parameters
    ----------
    config : SystemConfig
    backend : AcquisitionBackend
        Already-constructed backend (simulation or nidaqmx). The daemon opens
        and closes it.
    writer : DailyWriter
    """

    def __init__(self, config, backend, writer):
        self._config = config
        self._backend = backend
        self._writer = writer
        self._stop = threading.Event()
        self._latest_outdoor = {}  # updated by the outdoor path when wired in

    def run_once(self):
        """Run one acquisition cycle. Returns the SI values written.

        Reads a raw record, scales it, writes indoor rows, and updates the
        snapshot. Kept separate from timing so tests can drive single cycles.
        """
        rec = self._backend.read_record()
        si = scale_record(rec.values, self._config)
        self._writer.write_indoor(rec.timestamp, rec.values, si)
        self._writer.write_snapshot(rec.timestamp, si, self._latest_outdoor)
        return si

    def run_loop(self):
        """Run cycles at the configured record rate until stopped.

        Paces with a monotonic clock so drift does not accumulate. Opens the
        backend on entry and closes it and the writer on exit.
        """
        period = 1.0 / self._config.acquisition.record_rate_hz
        self._backend.open()
        logger.info("Acquisition loop started at %.3f s period.", period)
        try:
            next_t = time.monotonic()
            while not self._stop.is_set():
                start = time.monotonic()
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Acquisition cycle failed; continuing.")
                next_t += period
                sleep = next_t - time.monotonic()
                if sleep > 0:
                    self._stop.wait(sleep)
                else:
                    # Fell behind; resync to now to avoid a tight catch-up loop.
                    logger.warning("Cycle overran by %.3f s; resyncing.", -sleep)
                    next_t = time.monotonic()
        finally:
            self._backend.close()
            # The writer is shared with the outdoor reader and owned by the
            # supervisor, which closes it after all threads join. Do not close
            # it here.
            logger.info("Acquisition loop stopped.")

    def stop(self):
        """Signal the loop to stop after the current cycle."""
        self._stop.set()
