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
"""

import logging
import smtplib
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

        self._state = {self._key(r): RuleState() for r in self._rules}
        self._history = defaultdict(lambda: deque(maxlen=max(1, self._q.frozen_count)))
        self._frozen = set()
        self._last_record_time = None
        self._dropout_active = False

    @staticmethod
    def _key(rule):
        return f"{rule.channel}|{rule.description}"

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
        self._last_record_time = now
        for ch, v in si_values.items():
            self._history[ch].append(v)

        events = []
        for rule in self._rules:
            events += self._check_rule(rule, si_values, now)
        events += self._check_frozen(now)
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
        return {
            "tripped_rules": [
                self._key(r) for r in self._rules if self._state[self._key(r)].tripped
            ],
            "frozen_channels": sorted(self._frozen),
            "dropout": self._dropout_active,
        }

    # -- rule evaluation --
    def _check_rule(self, rule, si_values, now):
        st = self._state[self._key(rule)]
        value = si_values.get(rule.channel)
        if value is None:
            return []

        cond = False
        if rule.high is not None and value > rule.high:
            cond = True
        if rule.low is not None and value < rule.low:
            cond = True

        events = []
        if cond:
            if st.condition_since is None:
                st.condition_since = now
            dwell_ok = (now - st.condition_since).total_seconds() >= rule.dwell_s
            if dwell_ok and not st.tripped:
                st.tripped = True
                st.last_email = now
                events.append(
                    self._emit(
                        f"ALARM: {rule.description}",
                        self._trip_body(rule, value, now),
                        to_addrs=rule.email_to,
                    )
                )
            elif (
                st.tripped
                and st.last_email is not None
                and (now - st.last_email).total_seconds() >= self._min_interval_s
            ):
                st.last_email = now
                events.append(
                    self._emit(
                        f"ALARM ONGOING: {rule.description}",
                        self._trip_body(rule, value, now, ongoing=True),
                        to_addrs=rule.email_to,
                    )
                )
        else:
            if st.tripped:
                st.tripped = False
                events.append(
                    self._emit(
                        f"CLEARED: {rule.description}",
                        f"{rule.description} cleared at {now:%Y-%m-%d %H:%M:%S}. "
                        f"{rule.channel} = {value:.2f} {rule.unit} on {self._machine}.",
                        to_addrs=rule.email_to,
                    )
                )
            st.condition_since = None
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

    def _trip_body(self, rule, value, now, ongoing=False):
        state = "still tripped" if ongoing else "tripped"
        return (
            f"{rule.description} {state} at {now:%Y-%m-%d %H:%M:%S}.\n"
            f"{rule.channel} = {value:.2f} {rule.unit}, "
            f"threshold {self._threshold_text(rule)}, "
            f"dwell {rule.dwell_s:.0f} s.\n"
            f"Machine {self._machine}."
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
