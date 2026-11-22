#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for QueuedEmailSender.

Purpose: Confirm send() returns at once while the inner sender is slow, so an
    SMTP stall cannot hold up the indoor loop; that messages go out in order;
    that a failed send is logged and does not stop later ones; that close()
    flushes the queue; and that a full queue drops and logs instead of
    blocking. The inner senders are in-memory stand-ins; nothing touches the
    network.
Author: Nathan Lima
Created: 2026-11-09
Update log:
    2026-11-09: Initial version.
"""

import logging
import threading
import time

from src.mh_daq.alarms import EmailSender, QueuedEmailSender


class SlowSender(EmailSender):
    """Records messages after a delay; raises for subjects starting 'FAIL'."""

    def __init__(self, delay_s=0.0, gate=None):
        self.sent = []
        self._delay = delay_s
        self._gate = gate

    def send(self, subject, body, to_addrs=None):
        if self._gate is not None:
            self._gate.wait(5.0)
        time.sleep(self._delay)
        if subject.startswith("FAIL"):
            raise OSError("smtp down")
        self.sent.append((subject, body, to_addrs))


def test_send_returns_without_waiting_for_smtp():
    inner = SlowSender(delay_s=0.5)
    q = QueuedEmailSender(inner)
    t0 = time.monotonic()
    q.send("a", "body", to_addrs=["x@example.invalid"])
    assert time.monotonic() - t0 < 0.05
    q.close()
    assert inner.sent == [("a", "body", ["x@example.invalid"])]


def test_order_kept_and_failure_does_not_stop_queue(caplog):
    inner = SlowSender()
    q = QueuedEmailSender(inner)
    with caplog.at_level(logging.ERROR, logger="mh_daq.alarms"):
        for s in ("one", "FAIL two", "three"):
            q.send(s, "b")
        q.close()
    assert [m[0] for m in inner.sent] == ["one", "three"]
    assert "Failed to send alarm email: FAIL two" in caplog.text


def test_full_queue_drops_and_logs(caplog):
    gate = threading.Event()
    inner = SlowSender(gate=gate)
    q = QueuedEmailSender(inner, maxsize=2)
    with caplog.at_level(logging.ERROR, logger="mh_daq.alarms"):
        q.send("first", "b")  # taken by the worker, which waits on the gate
        time.sleep(0.1)
        q.send("second", "b")
        q.send("third", "b")
        q.send("fourth", "b")  # queue holds 2; this one is dropped
        gate.set()
        q.close()
    assert [m[0] for m in inner.sent] == ["first", "second", "third"]
    assert "Email queue full; dropped: fourth" in caplog.text
