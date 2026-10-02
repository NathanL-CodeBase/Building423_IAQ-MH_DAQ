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
    2026-10-02: Wire components through their public hooks instead of
        patching private attributes. Outdoor values pass through a locked
        LatestFields holder. Heartbeat reads the mirror's last reachability
        result instead of probing Mission every second.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .outdoor_reader import LatestFields

logger = logging.getLogger("mh_daq.supervisor")


class Supervisor:
    """Owns and coordinates all worker threads.

    Parameters
    ----------
    config : SystemConfig
    indoor_daemon : AcquisitionDaemon
        Given the alarm engine and the latest-outdoor provider, so each cycle
        runs alarms and writes current outdoor values into the snapshot.
    outdoor_reader : OutdoorReader
        Given a publish callback that feeds the latest-outdoor holder.
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
        self._latest_outdoor = LatestFields()
        self._started_at = None
        self._hb_path = Path(config.local.local_data_dir) / "heartbeat.json"

        # Outdoor thread publishes into the holder; the indoor loop reads it.
        self._outdoor.set_publish(self._latest_outdoor.set)
        self._indoor.set_outdoor_provider(self._latest_outdoor.get)
        self._indoor.set_alarms(self._alarms)

    def _write_heartbeat(self):
        """Write a small liveness file atomically. Never raises."""
        last_indoor = self._indoor.last_record_time
        hb = {
            "written_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": (
                self._started_at.isoformat(timespec="seconds") if self._started_at else None
            ),
            "last_indoor_record": (
                last_indoor.isoformat(timespec="seconds") if last_indoor else None
            ),
            "latest_outdoor_wind_speed": self._latest_outdoor.get().get("wind_speed"),
            # None until the mirror's first tick finishes its reachability check.
            "mission_available": self._mirror.last_available,
            "alarms": self._alarms.current_state(),
            "threads_alive": {t.name: t.is_alive() for t in self._threads},
        }
        try:
            self._hb_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._hb_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(hb, f, indent=2)
            os.replace(tmp, self._hb_path)
        except OSError as e:
            logger.warning("Heartbeat write failed: %s", e)

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            self._write_heartbeat()
            self._stop.wait(1.0)

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
        self._started_at = datetime.now()
        self._threads = [
            threading.Thread(target=self._indoor.run_loop, name="indoor", daemon=True),
            threading.Thread(target=self._outdoor.run_loop, name="outdoor", daemon=True),
            threading.Thread(target=self._mirror.run_loop, name="mirror", daemon=True),
            threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True),
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
        # Close the shared writer last, after all writing threads have stopped.
        try:
            self._indoor.writer.close()
        except Exception:
            pass
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
