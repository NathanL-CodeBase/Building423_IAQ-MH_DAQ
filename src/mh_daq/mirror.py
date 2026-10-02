#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mission mirror for the MH DAQ system.

Purpose: Copy locally written files to the Mission network share. Completed
    daily files (dated before today) are copied whenever Mission is reachable,
    comparing local to Mission so a missed day self-heals. The current day's
    still-open files are copied on an optional interval. The latest-values
    snapshot is copied on its own interval for the future webpage. Local disk
    is always the primary write; the mirror never blocks acquisition and never
    raises out of its tick, so a Mission outage degrades to catch-up later.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Filesystem-diff sync (no in-memory queue),
        atomic copy via temp file plus replace on the destination.
    2026-10-02: Record each tick's reachability in last_available, so the
        heartbeat reports it without probing the share itself.
"""

import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("mh_daq.mirror")


class MissionMirror:
    """Copies local DAQ files to Mission, resilient to Mission being down.

    Parameters
    ----------
    config : SystemConfig
    local_base : Path, optional
        Local output root. Defaults to config.local.local_data_dir.
    mission_data_dir : Path, optional
        Mission root for daily files. Defaults to config.local.mission_data_dir.
    mission_snapshot_dir : Path, optional
        Mission root for the snapshot. Defaults to
        config.local.mission_snapshot_dir.
    """

    def __init__(self, config, local_base=None, mission_data_dir=None, mission_snapshot_dir=None):
        self._config = config
        self._local = Path(local_base or config.local.local_data_dir)
        self._mission = Path(mission_data_dir or config.local.mission_data_dir)
        self._mission_snap = Path(mission_snapshot_dir or config.local.mission_snapshot_dir)
        self._snap_interval = config.mirror.snapshot_interval_s
        self._inprogress_interval = config.mirror.inprogress_interval_s
        self._retry_interval = config.mirror.retry_interval_s
        self._stop = threading.Event()
        self._last_snap = 0.0
        self._last_inprogress = 0.0
        # Result of the most recent tick's reachability check; None before the
        # first tick. Read by the heartbeat, because probing a dead UNC share
        # can block for tens of seconds on Windows.
        self.last_available = None

    def mission_available(self):
        """Return True if the Mission data root is reachable.

        A network share that is down raises OSError on access; that is treated
        as unavailable rather than fatal.
        """
        try:
            return self._mission.exists()
        except OSError:
            return False

    # -- copy primitives --
    @staticmethod
    def _should_copy(src, dst):
        """Copy if dst is missing, a different size, or older than src."""
        if not dst.exists():
            return True
        s, d = src.stat(), dst.stat()
        return s.st_size != d.st_size or s.st_mtime > d.st_mtime

    @staticmethod
    def _copy_atomic(src, dst):
        """Copy src to dst via a temp file on the destination, then replace.

        A reader on Mission never sees a partially written file. copy2 keeps the
        source mtime so the size and mtime comparison stays meaningful.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    def _mission_daily_path(self, local_file):
        """Map a local daily file to its Mission path under the system subdir.

        Files land in mission_data_dir/<mission_subdir>/<year>/, keeping this
        system's data separate from the LabVIEW-era indoor_daq and
        weather_station folders. Local layout is unaffected.
        """
        year = local_file.parent.name
        return self._mission / self._config.mirror.mission_subdir / year / local_file.name

    def _iter_local_daily(self):
        """Yield local daily .txt files under year folders."""
        if not self._local.exists():
            return
        for year_dir in self._local.iterdir():
            if not year_dir.is_dir():
                continue
            for f in year_dir.glob("*-MH_*.txt"):
                yield f

    @staticmethod
    def _file_date_str(local_file):
        """Return the YYYYMMDD prefix from a daily file name, or None."""
        prefix = local_file.name.split("-", 1)[0]
        return prefix if len(prefix) == 8 and prefix.isdigit() else None

    # -- sync operations --
    def sync_completed(self, now):
        """Copy daily files dated before today when they differ from Mission.

        Returns the count copied. Also copies each day's metadata sidecar.
        """
        today = now.strftime("%Y%m%d")
        copied = 0
        for f in self._iter_local_daily():
            fd = self._file_date_str(f)
            if fd is None or fd >= today:
                continue
            dst = self._mission_daily_path(f)
            if self._should_copy(f, dst):
                self._copy_atomic(f, dst)
                copied += 1
        copied += self._sync_sidecars(now, before_today=True)
        return copied

    def sync_inprogress(self, now):
        """Copy the current day's still-open daily files. Returns count copied."""
        today = now.strftime("%Y%m%d")
        copied = 0
        for f in self._iter_local_daily():
            if self._file_date_str(f) != today:
                continue
            dst = self._mission_daily_path(f)
            if self._should_copy(f, dst):
                self._copy_atomic(f, dst)
                copied += 1
        copied += self._sync_sidecars(now, before_today=False)
        return copied

    def _sync_sidecars(self, now, before_today):
        """Copy per-day metadata JSON files, gated by the same date rule."""
        today = now.strftime("%Y%m%d")
        copied = 0
        if not self._local.exists():
            return 0
        for year_dir in self._local.iterdir():
            if not year_dir.is_dir():
                continue
            for f in year_dir.glob("*-MH_metadata.json"):
                fd = self._file_date_str(f)
                if fd is None:
                    continue
                is_before = fd < today
                if is_before != before_today:
                    continue
                dst = self._mission / self._config.mirror.mission_subdir / year_dir.name / f.name
                if self._should_copy(f, dst):
                    self._copy_atomic(f, dst)
                    copied += 1
        return copied

    def sync_snapshot(self):
        """Copy the snapshot and heartbeat to the Mission snapshot dir.

        Both are small status files the web layer reads; mirroring them lets the
        web box judge system health without touching the DAQ PC. Returns True if
        the snapshot was copied.
        """
        copied = False
        src = self._local / "latest_snapshot.json"
        if src.exists():
            self._copy_atomic(src, self._mission_snap / "latest_snapshot.json")
            copied = True
        hb = self._local / "heartbeat.json"
        if hb.exists():
            self._copy_atomic(hb, self._mission_snap / "heartbeat.json")
        return copied

    def tick(self, now=None):
        """Run one mirror pass. Never raises; logs and returns on failure.

        Completed files sync every tick when Mission is reachable. In-progress
        files and the snapshot sync on their intervals.
        """
        now = now or datetime.now()
        self.last_available = self.mission_available()
        if not self.last_available:
            logger.warning("Mission unavailable; will retry.")
            return
        try:
            n = self.sync_completed(now)
            if n:
                logger.info("Mirrored %d completed file(s).", n)

            wall = time.monotonic()
            if (
                self._inprogress_interval > 0
                and wall - self._last_inprogress >= self._inprogress_interval
            ):
                self._last_inprogress = wall
                m = self.sync_inprogress(now)
                if m:
                    logger.info("Mirrored %d in-progress file(s).", m)

            if wall - self._last_snap >= self._snap_interval:
                self._last_snap = wall
                if self.sync_snapshot():
                    logger.debug("Snapshot mirrored.")
        except OSError as e:
            logger.warning("Mirror tick failed: %s; will retry.", e)

    def run_loop(self):
        """Tick at retry_interval until stopped. Runs on its own thread."""
        logger.info(
            "Mission mirror started (retry %ds, snapshot %ds).",
            self._retry_interval,
            self._snap_interval,
        )
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(self._retry_interval)
        finally:
            logger.info("Mission mirror stopped.")

    def stop(self):
        """Signal the loop to stop after the current tick."""
        self._stop.set()
