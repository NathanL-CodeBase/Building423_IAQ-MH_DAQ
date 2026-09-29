#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MH DAQ entry point.

Purpose: Assemble config, backend, writer, outdoor reader, mirror, and alarms
    into the supervisor and run until interrupted. Backend is selected by flag:
    --sim for the simulation backend (any machine), --hardware for the real
    cDAQ (DAQ PC only). Writes to the local data dir from daq_local.json.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version.

Usage:
    python run_daq.py --sim         # simulator, safe anywhere
    python run_daq.py --hardware    # real cDAQ, DAQ PC only
"""

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.mh_daq.alarms import AlarmEngine, SmtpEmailSender
from src.mh_daq.backends import NiDaqmxBackend, SimulationBackend
from src.mh_daq.config import load_config
from src.mh_daq.daemon import AcquisitionDaemon
from src.mh_daq.mirror import MissionMirror
from src.mh_daq.outdoor_reader import OutdoorReader
from src.mh_daq.serial_source import PySerialSource, resolve_port
from src.mh_daq.supervisor import Supervisor
from src.mh_daq.writer import DailyWriter


def setup_logging(local_data_dir):
    log_path = Path(local_data_dir) / "mh_daq.log"
    Path(local_data_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    fileh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fileh.setFormatter(fmt)
    root = logging.getLogger("mh_daq")
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(fileh)
    return root


def build_serial_factory(config, sim=False):
    """Return a callable that opens a fresh serial source.

    In sim mode, returns a synthetic AIO 2 source so the outdoor path runs with
    no hardware. Otherwise opens the real port (auto-detected or configured).
    """
    if sim:
        from src.mh_daq.backends.sim_serial import SimSerialSource

        def factory():
            return SimSerialSource()

        return factory

    def factory():
        port = resolve_port(config)
        if port is None:
            raise RuntimeError("No AIO 2 serial port resolved.")
        a = config.aio2
        return PySerialSource(
            port,
            baud=a.baud_rate,
            bytesize=a.bytesize,
            parity=a.parity,
            stopbits=a.stopbits,
            timeout_s=2.0,
        )

    return factory


def main():
    ap = argparse.ArgumentParser(description="MH DAQ daemon.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true", help="Use the simulation backend.")
    g.add_argument("--hardware", action="store_true", help="Use the real cDAQ.")
    args = ap.parse_args()

    config = load_config()
    log = setup_logging(config.local.local_data_dir)

    if args.hardware:
        if NiDaqmxBackend is None:
            log.error("nidaqmx backend unavailable; is the NI driver installed?")
            sys.exit(1)
        backend = NiDaqmxBackend(config)
        log.info("Using real nidaqmx backend.")
    else:
        backend = SimulationBackend(config)
        log.info("Using simulation backend.")

    writer = DailyWriter(config)
    indoor = AcquisitionDaemon(config, backend, writer)
    outdoor = OutdoorReader(
        config, writer, source_factory=build_serial_factory(config, sim=args.sim)
    )
    mirror = MissionMirror(config)
    sender = SmtpEmailSender(
        config.local.smtp_host,
        config.local.smtp_port,
        config.local.smtp_from,
        config.local.smtp_to,
    )
    alarms = AlarmEngine(config, sender)

    sup = Supervisor(config, indoor, outdoor, mirror, alarms)
    log.info("Starting MH DAQ. Ctrl+C to stop.")
    sup.run_forever()


if __name__ == "__main__":
    main()
