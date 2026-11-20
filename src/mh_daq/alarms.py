#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alarm engine for the MH DAQ system.

Purpose: Evaluate per-channel threshold rules with a dwell time, detect frozen
    (unchanging) channels, and watch for acquisition dropout. Send email on
    trip, on clear, and periodically while a rule stays tripped. The email
    sender is injectable so tests use a recording sender and never touch the
    network; production uses SMTP through smtp.nist.gov:25.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Threshold rules (dwell, trip/clear/re-notify),
        frozen detection, dropout watchdog, SMTP and recording senders.
    2026-11-09: Rules honor an active window; a rule tripped when its window
        ends gets a closing email. set_rules swaps rules and recipients under
        a lock for live reload, keeping state for unchanged rules.
        check_mission emails once when Mission stays unreachable past
        quality.mission_outage_s and once when it returns. notify sends a
        plain system message (config reload errors).
    2026-11-09: Add QueuedEmailSender, which sends on a background thread
        so a slow or hung SMTP server never stalls the 1 Hz indoor loop.
    2026-11-20: A tripped rule clears only after the value is the rule's
        deadband inside the limit for clear_dwell_s, so a value at the limit
        no longer sends a burst of ALARM and CLEARED emails. No ONGOING email
        while a clear is pending.
"""

import logging
import queue
import smtplib
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger("mh_daq.alarms")


# ---------------------------------------------------------------------------
# Email senders
# ---------------------------------------------------------------------------
class EmailSender:
    """Interface for sending alarm emails."""

    def send(self, subject, body, to_addrs=None):
        raise NotImplementedError


class SmtpEmailSender(EmailSender):
    """Send via an SMTP relay. Used in production.

    Parameters
    ----------
    host, port : str, int
    from_addr : str
    to_addrs : list of str
    timeout : float
    """

    def __init__(self, host, port, from_addr, to_addrs, timeout=30.0):
        self._host = host
        self._port = port
        self._from = from_addr
        self._to = list(to_addrs)
        self._timeout = timeout

    def send(self, subject, body, to_addrs=None):
        recipients = to_addrs if to_addrs is not None else self._to
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as s:
            s.send_message(msg)


class QueuedEmailSender(EmailSender):
    """Send through another sender on a background thread.

    send() only enqueues, so the caller (the indoor loop, holding the alarm
    lock) returns at once even when the SMTP server takes its full timeout.
    Messages go out in order on one worker thread. A failed send is logged
    and dropped, as before. If the queue fills (the server down through a
    long burst of alarms), the newest message is dropped and logged.

    Parameters
    ----------
    inner : EmailSender
        Does the actual sending (SmtpEmailSender in production).
    maxsize : int
        Queue limit.
    """

    _STOP = object()

    def __init__(self, inner, maxsize=200):
        self._inner = inner
        self._q = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="email", daemon=True)
        self._thread.start()

    def send(self, subject, body, to_addrs=None):
        try:
            self._q.put_nowait((subject, body, to_addrs))
        except queue.Full:
            logger.error("Email queue full; dropped: %s", subject)

    def pending(self):
        """Approximate number of messages waiting to send."""
        return self._q.qsize()

    def _run(self):
        while True:
            item = self._q.get()
            try:
                if item is self._STOP:
                    return
                subject, body, to_addrs = item
                try:
                    self._inner.send(subject, body, to_addrs=to_addrs)
                except Exception:
                    logger.exception("Failed to send alarm email: %s", subject)
            finally:
                self._q.task_done()

    def close(self, timeout=60.0):
        """Send what is queued, then stop the worker. Waits up to timeout s.

        Called at shutdown so a final alarm or clear email is not lost.
        """
        try:
            self._q.put(self._STOP, timeout=1.0)
        except queue.Full:
            logger.error("Email queue full at shutdown; %d message(s) dropped.", self._q.qsize())
            return
        self._thread.join(timeout)
        if self._thread.is_alive():
            logger.warning("Email worker still sending after %.0f s at shutdown.", timeout)


class RecordingEmailSender(EmailSender):
    """Capture emails in memory for tests. Sends nothing."""

    def __init__(self):
        self.sent = []

    def send(self, subject, body, to_addrs=None):
        self.sent.append((subject, body, to_addrs))


# ---------------------------------------------------------------------------
# Rule state
# ---------------------------------------------------------------------------
@dataclass
class RuleState:
    tripped: bool = False
    condition_since: Optional[datetime] = None
    clear_since: Optional[datetime] = None
    last_email: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class AlarmEngine:
    """Evaluates alarm rules and quality checks, sending email on state change.

    Parameters
    ----------
    config : SystemConfig
    sender : EmailSender
    """

    def __init__(self, config, sender):
        self._config = config
        self._sender = sender
        self._rules = config.alarm_rules
        self._email_enabled = config.alarm_email.get("enabled", True)
        self._min_interval_s = float(config.alarm_email.get("min_interval_s", 300))
        self._q = config.quality
        self._machine = config.local.machine_name
        self._rule_email_map = config.local.alarm_rule_email

        self._state = {self._key(r): RuleState() for r in self._rules}
        self._history = defaultdict(lambda: deque(maxlen=max(1, self._q.frozen_count)))
        self._frozen = set()
        self._last_record_time = None
        self._dropout_active = False
        self._mission_down_since = None
        self._mission_alarm_active = False
        # check() runs on the indoor thread and set_rules() on the config
        # watcher thread; the lock keeps a rule list and its state in step.
        self._lock = threading.RLock()

    @staticmethod
    def _key(rule):
        return f"{rule.channel}|{rule.description}"

    def set_rules(self, rules, rule_email_map=None):
        """Replace the threshold rules and per-rule recipients (live reload).

        A rule whose key and definition are unchanged keeps its trip state and
        dwell timer, so a reload in the middle of an alarm does not resend the
        trip email. A changed or new rule starts clear. A removed rule that was
        tripped gets a closing email.

        Returns
        -------
        list of str
            Event descriptions for the log.
        """
        pending = []
        with self._lock:
            old = {self._key(r): r for r in self._rules}
            new_state = {}
            for r in rules:
                k = self._key(r)
                if k in old and old[k] == r:
                    new_state[k] = self._state[k]
                else:
                    new_state[k] = RuleState()
            for k, r in old.items():
                st = self._state.get(k)
                if st and st.tripped and new_state.get(k) is not st:
                    pending.append((r, self._rule_email_map.get(r.description)))
            self._rules = list(rules)
            self._state = new_state
            if rule_email_map is not None:
                self._rule_email_map = dict(rule_email_map)
        # Send outside the lock: SMTP can block up to its 30 s timeout, and the
        # indoor loop needs the lock every second.
        return [
            self._emit(
                f"ALARM RULE CHANGED: {r.description}",
                f"{r.description} was tripped when its rule was edited or removed "
                f"from config on {self._machine}. It restarts from clear.",
                to_addrs=to,
            )
            for r, to in pending
        ]

    def notify(self, subject_suffix, body):
        """Send a system message to the default recipients. Returns the subject."""
        return self._emit(subject_suffix, body)

    # -- public API --
    def check(self, si_values, now):
        """Evaluate all threshold rules and frozen detection for one record.

        Parameters
        ----------
        si_values : dict
            Channel name to SI value.
        now : datetime

        Returns
        -------
        list of str
            Human-readable event descriptions for logging and the snapshot.
        """
        with self._lock:
            self._last_record_time = now
            for ch, v in si_values.items():
                self._history[ch].append(v)

            events = []
            for rule in self._rules:
                events += self._check_rule(rule, si_values, now)
            events += self._check_frozen(now)
            return events

    def check_mission(self, available, now):
        """Email when Mission stays unreachable past quality.mission_outage_s.

        One email when the outage passes the limit and one when Mission comes
        back; short outages send nothing. available is the mirror's last
        reachability result; None (no tick yet) is ignored.

        Returns event descriptions.
        """
        limit = self._q.mission_outage_s
        if available is None or limit <= 0:
            return []
        events = []
        if not available:
            if self._mission_down_since is None:
                self._mission_down_since = now
            down_s = (now - self._mission_down_since).total_seconds()
            if down_s >= limit and not self._mission_alarm_active:
                self._mission_alarm_active = True
                events.append(
                    self._emit(
                        "MISSION UNREACHABLE",
                        f"{self._machine} has not reached Mission since "
                        f"{self._mission_down_since:%Y-%m-%d %H:%M:%S} ({down_s / 3600:.1f} h, "
                        f"limit {limit / 3600:.1f} h). Data keeps logging locally and "
                        f"copies to Mission when access returns. The dashboard shows "
                        f"stale values until then.",
                    )
                )
        else:
            if self._mission_alarm_active:
                down_s = (now - self._mission_down_since).total_seconds()
                events.append(
                    self._emit(
                        "MISSION REACHABLE AGAIN",
                        f"{self._machine} reached Mission at {now:%Y-%m-%d %H:%M:%S} after "
                        f"{down_s / 3600:.1f} h (unreachable from "
                        f"{self._mission_down_since:%Y-%m-%d %H:%M:%S}). The backlog copies "
                        f"on the next mirror ticks.",
                    )
                )
            self._mission_alarm_active = False
            self._mission_down_since = None
        return events

    def check_dropout(self, now):
        """Watchdog: alarm if no record has arrived within dropout_s.

        Call from a separate timer, not the acquisition loop, so a hung read is
        still caught. Returns event descriptions.
        """
        if self._last_record_time is None:
            return []
        gap = (now - self._last_record_time).total_seconds()
        events = []
        if gap > self._q.dropout_s and not self._dropout_active:
            self._dropout_active = True
            events.append(
                self._emit(
                    "DROPOUT",
                    f"No data for {gap:.0f} s (threshold {self._q.dropout_s:.0f} s) "
                    f"on {self._machine}.",
                )
            )
        elif gap <= self._q.dropout_s and self._dropout_active:
            self._dropout_active = False
            events.append(
                self._emit(
                    "DROPOUT CLEARED",
                    f"Data resumed on {self._machine}.",
                )
            )
        return events

    def current_state(self):
        """Return a small dict of current alarm state for the snapshot."""
        with self._lock:
            return {
                "tripped_rules": [
                    self._key(r) for r in self._rules if self._state[self._key(r)].tripped
                ],
                "frozen_channels": sorted(self._frozen),
                "dropout": self._dropout_active,
                "mission_outage": self._mission_alarm_active,
            }

    # -- rule evaluation --
    def _check_rule(self, rule, si_values, now):
        st = self._state[self._key(rule)]
        to_addrs = self._rule_email_map.get(rule.description)

        if not rule.is_active(now):
            events = []
            if st.tripped:
                events.append(
                    self._emit(
                        f"ALARM WINDOW ENDED: {rule.description}",
                        f"{rule.description} was still tripped when its window ended at "
                        f"{now:%Y-%m-%d %H:%M:%S} ({rule.window_text()}) on {self._machine}.",
                        to_addrs=to_addrs,
                    )
                )
            st.tripped = False
            st.condition_since = None
            return events

        value = si_values.get(rule.channel)
        if value is None:
            return []

        events = []
        if not st.tripped:
            tripping = (rule.high is not None and value > rule.high) or (
                rule.low is not None and value < rule.low
            )
            if not tripping:
                st.condition_since = None
                return events
            if st.condition_since is None:
                st.condition_since = now
            if (now - st.condition_since).total_seconds() >= rule.dwell_s:
                st.tripped = True
                st.clear_since = None
                st.last_email = now
                events.append(
                    self._emit(
                        f"ALARM: {rule.description}",
                        self._trip_body(rule, value, now),
                        to_addrs=to_addrs,
                    )
                )
            return events

        # Tripped: clear only once the value is deadband inside the limit and
        # holds there for clear_dwell, so noise at the limit sends no emails.
        clearing = not (
            (rule.high is not None and value > rule.high - rule.deadband)
            or (rule.low is not None and value < rule.low + rule.deadband)
        )
        if clearing:
            if st.clear_since is None:
                st.clear_since = now
            if (now - st.clear_since).total_seconds() >= rule.clear_dwell:
                st.tripped = False
                st.condition_since = None
                st.clear_since = None
                events.append(
                    self._emit(
                        f"CLEARED: {rule.description}",
                        f"{rule.description} cleared at {now:%Y-%m-%d %H:%M:%S}. "
                        f"{rule.channel} = {value:.2f} {rule.unit} on {self._machine}.",
                        to_addrs=to_addrs,
                    )
                )
            return events

        st.clear_since = None
        if (
            st.last_email is not None
            and (now - st.last_email).total_seconds() >= self._min_interval_s
        ):
            st.last_email = now
            events.append(
                self._emit(
                    f"ALARM ONGOING: {rule.description}",
                    self._trip_body(rule, value, now, ongoing=True),
                    to_addrs=to_addrs,
                )
            )
        return events

    def _check_frozen(self, now):
        """Flag channels whose value has not changed for frozen_count records."""
        events = []
        for ch, hist in self._history.items():
            if len(hist) < hist.maxlen:
                continue
            is_frozen = len(set(hist)) == 1
            if is_frozen and ch not in self._frozen:
                self._frozen.add(ch)
                events.append(
                    self._emit(
                        f"FROZEN: {ch}",
                        f"{ch} unchanged for {hist.maxlen} records "
                        f"(value {hist[-1]}) on {self._machine}.",
                    )
                )
            elif not is_frozen and ch in self._frozen:
                self._frozen.discard(ch)
                events.append(
                    self._emit(
                        f"FROZEN CLEARED: {ch}",
                        f"{ch} changing again on {self._machine}.",
                    )
                )
        return events

    # -- helpers --
    def _threshold_text(self, rule):
        parts = []
        if rule.high is not None:
            parts.append(f"above {rule.high} {rule.unit}")
        if rule.low is not None:
            parts.append(f"below {rule.low} {rule.unit}")
        return " or ".join(parts)

    def _clear_text(self, rule):
        parts = []
        if rule.low is not None:
            parts.append(f"at or above {rule.low + rule.deadband:g} {rule.unit}")
        if rule.high is not None:
            parts.append(f"at or below {rule.high - rule.deadband:g} {rule.unit}")
        return " and ".join(parts)

    def _trip_body(self, rule, value, now, ongoing=False):
        state = "still tripped" if ongoing else "tripped"
        window = rule.window_text()
        return (
            f"{rule.description} {state} at {now:%Y-%m-%d %H:%M:%S}.\n"
            f"{rule.channel} = {value:.2f} {rule.unit}, "
            f"threshold {self._threshold_text(rule)}, "
            f"dwell {rule.dwell_s:.0f} s.\n"
            f"Clears after {rule.clear_dwell:.0f} s {self._clear_text(rule)}.\n"
            + (f"Temporary rule, {window}.\n" if window else "")
            + f"Machine {self._machine}."
        )

    def _emit(self, subject_suffix, body, to_addrs=None):
        subject = f"[MH DAQ] {subject_suffix}"
        if self._email_enabled:
            try:
                self._sender.send(subject, body, to_addrs=to_addrs)
            except Exception:
                logger.exception("Failed to send alarm email: %s", subject)
        logger.info("Alarm event: %s", subject)
        return subject
