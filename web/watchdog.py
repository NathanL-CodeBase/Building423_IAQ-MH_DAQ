#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stale-data watchdog for the MH DAQ dashboard machine.

Purpose: Email when the DAQ heartbeat on Mission stops advancing. The DAQ PC
    cannot report its own power loss, so an always-on machine (appleseed) runs
    this beside the dashboard and treats the heartbeat age on Mission as a
    proxy for "DAQ computer offline". The heartbeat also stops advancing when
    the DAQ PC cannot reach Mission, so the email names both causes. Sends one
    email on trip, a reminder every stale_renotify_s while stale, and one on
    recovery. The sender is injectable so tests never touch the network.
Author: Nathan Lima
Created: 2026-11-09
Update log:
    2026-11-09: Initial version.
"""

import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger("mh_daq.web.watchdog")


def format_age(seconds):
    """Return an age as '3 d 4 h', '5 h 12 min', or '7 min'."""
    s = int(max(0, seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


class StaleWatchdog:
    """Track heartbeat age and email on stale, still stale, and recovered.

    Parameters
    ----------
    heartbeat_path : callable
        Returns the Path of heartbeat.json; called on every check so a change
        of data source is picked up.
    sender : EmailSender
        From src.mh_daq.alarms. Sends to its default recipients (smtp to_addrs).
    alarm_s, renotify_s : float
        Age that trips the alarm, and the reminder interval while tripped.
    machine : str
        Name of the machine running the check, for the email body.
    """

    def __init__(self, heartbeat_path, sender, alarm_s, renotify_s, machine):
        self._path = heartbeat_path
        self._sender = sender
        self._alarm_s = float(alarm_s)
        self._renotify_s = float(renotify_s)
        self._machine = machine
        self._started = None
        self._last_written = None
        self._tripped = False
        self._tripped_at = None
        self._last_email = None
        self._stop = threading.Event()

    @property
    def tripped(self):
        return self._tripped

    def _read_written_at(self):
        """Return (written_at, error_text). written_at is None on failure."""
        try:
            with open(self._path(), encoding="utf-8") as f:
                hb = json.load(f)
            return datetime.fromisoformat(hb["written_at"]), None
        except (OSError, ValueError, KeyError, TypeError) as e:
            return None, f"{type(e).__name__}: {e}"

    def check(self, now):
        """Run one check. Returns the email subject sent, or None."""
        if self._started is None:
            self._started = now
        written, err = self._read_written_at()
        if written is not None:
            self._last_written = written
        # An unreadable heartbeat ages from the last good read, or from
        # watchdog start, so a share outage still trips after alarm_s.
        ref = self._last_written or self._started
        age = (now - ref).total_seconds()

        if age >= self._alarm_s:
            if not self._tripped:
                self._tripped = True
                self._tripped_at = now
                return self._send(f"[MH DAQ] No DAQ update on Mission for {format_age(age)}",
                                  self._stale_body(age, err), now)
            if (now - self._last_email).total_seconds() >= self._renotify_s:
                return self._send(f"[MH DAQ] Still no DAQ update on Mission ({format_age(age)})",
                                  self._stale_body(age, err), now)
            return None

        if self._tripped:
            self._tripped = False
            body = (
                f"The DAQ heartbeat on Mission is updating again. Newest heartbeat "
                f"written {self._last_written:%Y-%m-%d %H:%M:%S} (DAQ computer clock), "
                f"checked from {self._machine} at {now:%Y-%m-%d %H:%M:%S}. "
                f"The first stale email went out at {self._tripped_at:%Y-%m-%d %H:%M:%S}."
            )
            return self._send("[MH DAQ] DAQ updates on Mission resumed", body, now)
        return None

    def _stale_body(self, age, err):
        if self._last_written is not None:
            last = f"The newest heartbeat on Mission was written {self._last_written:%Y-%m-%d %H:%M:%S} (DAQ computer clock), {format_age(age)} ago."
        else:
            last = f"No heartbeat has been read since this check started at {self._started:%Y-%m-%d %H:%M:%S}."
        lines = [
            last,
            f"Alarm threshold: {format_age(self._alarm_s)}.",
            "",
            "Either the DAQ computer is off or the DAQ program is stopped, or the "
            "DAQ computer cannot reach Mission. Data recorded while Mission is "
            "unreachable stays on the DAQ computer and copies over when access returns.",
        ]
        if err:
            lines += [
                "",
                f"The heartbeat file could not be read from {self._machine} at this check "
                f"({err}). Mission may also be unreachable from {self._machine}.",
            ]
        lines += ["", f"Checked from {self._machine}."]
        return "\n".join(lines)

    def _send(self, subject, body, now):
        self._last_email = now
        try:
            self._sender.send(subject, body)
        except Exception:
            logger.exception("Failed to send watchdog email: %s", subject)
        logger.warning("Watchdog event: %s", subject)
        return subject

    def run_loop(self, interval_s):
        """Check every interval_s until stop() is called. Never raises."""
        while not self._stop.is_set():
            try:
                self.check(datetime.now())
            except Exception:
                logger.exception("Watchdog check failed; continuing.")
            self._stop.wait(interval_s)

    def stop(self):
        self._stop.set()
