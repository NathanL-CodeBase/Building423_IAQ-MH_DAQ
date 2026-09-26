#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Supervisor for the MH DAQ system.

Purpose: Run the indoor cDAQ loop, the outdoor AIO 2 reader, the Mission mirror,
    and the dropout watchdog as independent threads under one process. Each
    acquisition path retries its own resource, so an indoor fault never stops
    outdoor logging and vice versa. Wires the shared latest-outdoor value into
    the indoor snapshot and the alarm engine into the indoor cycle. Provides a
    single start and a clean stop for autostart via a .bat.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Thread orchestration, shared outdoor value,
        alarm hook on the indoor cycle, and a watchdog thread.
"""

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger("mh_daq.supervisor")


class Supervisor:
    """Owns and coordinates all worker threads.

    Parameters
    ----------
    config : SystemConfig
    indoor_daemon : AcquisitionDaemon
        Its run_once is wrapped so each cycle also runs alarms and injects the
        latest outdoor values into the snapshot.
    outdoor_reader : OutdoorReader
    mirror : MissionMirror
    alarms : AlarmEngine
    """

    def __init__(self, config, indoor_daemon, outdoor_reader, mirror, alarms):
        self._config = config
        self._indoor = indoor_daemon
        self._outdoor = outdoor_reader
        self._mirror = mirror
        self._alarms = alarms
        self._stop = threading.Event()
        self._threads = []
        self._latest_outdoor = {}
        self._outdoor_lock = threading.Lock()

        # Wire shared state: outdoor reader publishes here, indoor loop reads it.
        self._outdoor._publish = self._set_latest_outdoor
        self._indoor._latest_outdoor = {}  # replaced per-cycle via the wrapper

        # Wrap the indoor cycle to add alarms and current outdoor values.
        self._indoor_run_once = self._indoor.run_once
        self._indoor.run_once = self._indoor_cycle

    def _set_latest_outdoor(self, fields):
        with self._outdoor_lock:
            self._latest_outdoor = dict(fields)

    def _indoor_cycle(self):
        """One indoor cycle plus alarms, with current outdoor values in view."""
        with self._outdoor_lock:
            self._indoor._latest_outdoor = dict(self._latest_outdoor)
        si = self._indoor_run_once()
        now = datetime.now()
        events = self._alarms.check(si, now)
        for e in events:
            logger.info("Indoor alarm event: %s", e)
        return si

    def _watchdog_loop(self):
        """Check acquisition dropout on a timer independent of the read loop."""
        interval = max(5.0, self._config.quality.dropout_s / 2.0)
        while not self._stop.is_set():
            for e in self._alarms.check_dropout(datetime.now()):
                logger.warning("Watchdog: %s", e)
            self._stop.wait(interval)

    def start(self):
        """Start all threads."""
        logger.info("Supervisor starting.")
        self._threads = [
            threading.Thread(target=self._indoor.run_loop, name="indoor", daemon=True),
            threading.Thread(target=self._outdoor.run_loop, name="outdoor", daemon=True),
            threading.Thread(target=self._mirror.run_loop, name="mirror", daemon=True),
            threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True),
        ]
        for t in self._threads:
            t.start()
        logger.info("Supervisor started %d threads.", len(self._threads))

    def stop(self):
        """Signal all workers to stop and join them."""
        logger.info("Supervisor stopping.")
        self._stop.set()
        self._indoor.stop()
        self._outdoor.stop()
        self._mirror.stop()
        for t in self._threads:
            t.join(timeout=10.0)
        logger.info("Supervisor stopped.")

    def run_forever(self):
        """Start and block until interrupted, then stop cleanly."""
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Interrupted; stopping.")
        finally:
            self.stop()
