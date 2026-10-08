#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Acquisition daemon core for the MH DAQ system.

Purpose: Drive one acquisition cycle per record interval: read a raw record
    from the backend, scale it to SI, write indoor raw and SI rows, run the
    alarm checks, and update the snapshot. Outdoor (AIO 2) acquisition runs on
    its own thread; its latest values arrive through an outdoor provider
    callable. A testable single-cycle method keeps timing and I/O separable
    from logic.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. run_once for a single cycle (used by tests),
        and run_loop with a monotonic-clock pace and graceful stop.
    2026-10-02: Run alarms inside run_once so the snapshot carries the
        current alarm state. Public hooks (set_outdoor_provider, set_alarms,
        writer, last_record_time) replace the supervisor's private patching.
    2026-10-08: A snapshot write failure logs a warning and keeps the cycle.
        The data rows are already written, and the next cycle rewrites the
        snapshot, so it is not an acquisition failure.
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
    outdoor_provider : callable, optional
        Returns the latest outdoor fields dict for the snapshot. Defaults to an
        empty dict, for indoor-only runs and tests.
    alarms : AlarmEngine, optional
        Checked once per record. Omit to skip alarms.
    """

    def __init__(self, config, backend, writer, outdoor_provider=None, alarms=None):
        self._config = config
        self._backend = backend
        self._writer = writer
        self._outdoor_provider = outdoor_provider or dict
        self._alarms = alarms
        self._stop = threading.Event()
        self.last_record_time = None

    @property
    def writer(self):
        """The DailyWriter this daemon writes to (shared with the outdoor path)."""
        return self._writer

    def set_outdoor_provider(self, provider):
        """Set the callable that returns the latest outdoor fields."""
        self._outdoor_provider = provider

    def set_alarms(self, alarms):
        """Set the AlarmEngine checked on each record."""
        self._alarms = alarms

    def run_once(self):
        """Run one acquisition cycle. Returns the SI values written.

        Reads a raw record, scales it, writes indoor rows, runs alarms, and
        updates the snapshot. Alarms run before the snapshot write so the
        snapshot reports the state that includes this record. Kept separate
        from timing so tests can drive single cycles.
        """
        rec = self._backend.read_record()
        si = scale_record(rec.values, self._config)
        self._writer.write_indoor(rec.timestamp, rec.values, si)

        alarm_state = None
        if self._alarms is not None:
            for event in self._alarms.check(si, rec.timestamp):
                logger.info("Indoor alarm event: %s", event)
            alarm_state = self._alarms.current_state()

        try:
            self._writer.write_snapshot(rec.timestamp, si, self._outdoor_provider(), alarm_state)
        except OSError as e:
            logger.warning("Snapshot write failed; next cycle rewrites it: %s", e)
        self.last_record_time = rec.timestamp
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
