#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live reload of the alarm rules and channel status for the MH DAQ daemon.

Purpose: Let a temporary alarm (for example a dP limit during a test) or an
    offline tag be added by editing config, with no daemon restart and so no
    gap in the data. Polls the modified time of daq_config.json and
    daq_local.json; on a change it re-reads alarms.rules, channel_status, and
    alarm_rule_email, validates them against the running channel map, and
    applies them. A file that fails validation leaves the running rules in
    place, is logged, and is emailed once. Edits to sections that need a
    restart (channel map, scales, timing, AIO 2, mirror) are logged as a
    warning and not applied.
Author: Nathan Lima
Created: 2026-11-09
Update log:
    2026-11-09: Initial version.
"""

import logging
import threading

from .config import ConfigError, load_dynamic

logger = logging.getLogger("mh_daq.config_watch")


class ConfigWatcher:
    """Re-read reloadable config sections when their files change.

    Parameters
    ----------
    config : SystemConfig
        The startup config; supplies the file paths and the channel map.
    alarms : AlarmEngine
    writer : DailyWriter
    """

    def __init__(self, config, alarms, writer):
        self._config = config
        self._alarms = alarms
        self._writer = writer
        self._stop = threading.Event()
        self._mtimes = self._read_mtimes()
        self._static = config.static_fingerprint
        self._restart_warned = False
        self._failed_mtimes = None
        self._offline = list(config.offline_channels)
        self._events = list(config.channel_events)

    def _read_mtimes(self):
        out = []
        for p in (self._config.committed_path, self._config.local_path):
            try:
                out.append(p.stat().st_mtime if p is not None else None)
            except OSError:
                out.append(None)
        return tuple(out)

    def poll(self):
        """Check once for a change and apply it. Returns True if applied."""
        mtimes = self._read_mtimes()
        if mtimes == self._mtimes:
            return False
        self._mtimes = mtimes
        try:
            dyn = load_dynamic(self._config)
        except ConfigError as e:
            logger.error("Config reload rejected; keeping running rules. %s", e)
            # One email per bad edit, not one per poll.
            if self._failed_mtimes != mtimes:
                self._failed_mtimes = mtimes
                self._alarms.notify(
                    "CONFIG RELOAD REJECTED",
                    "An edit to daq_config.json or daq_local.json failed validation, "
                    "so the daemon kept the rules it was running.\n\n" + str(e),
                )
            return False
        self._failed_mtimes = None

        for event in self._alarms.set_rules(dyn.alarm_rules, dyn.alarm_rule_email):
            logger.info("Alarm event on reload: %s", event)
        if dyn.offline_channels != self._offline or dyn.channel_events != self._events:
            self._offline = list(dyn.offline_channels)
            self._events = list(dyn.channel_events)
            self._writer.set_channel_status(self._offline, self._events)
            logger.info(
                "channel_status reloaded: %d offline, %d events.",
                len(self._offline),
                len(self._events),
            )
        logger.info(
            "Alarm rules reloaded: %s.",
            "; ".join(
                f"{r.description} ({r.window_text() or 'always'})" for r in dyn.alarm_rules
            ),
        )

        if dyn.static_fingerprint != self._static and not self._restart_warned:
            self._restart_warned = True
            logger.warning(
                "daq_config.json changed outside alarms.rules and channel_status. "
                "Those edits take effect only after a daemon restart."
            )
        elif dyn.static_fingerprint == self._static:
            self._restart_warned = False
        return True

    def run_loop(self, interval_s=30.0):
        """Poll every interval_s until stopped. Never raises."""
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:
                logger.exception("Config watch failed; continuing.")
            self._stop.wait(interval_s)

    def stop(self):
        self._stop.set()
