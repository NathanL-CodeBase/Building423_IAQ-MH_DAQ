#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MH DAQ status tool.

Purpose: Show whether the acquisition daemon is healthy, for someone who has
    remoted into the DAQ PC. Reads the heartbeat and latest snapshot written by
    the daemon; does not touch the open daily files or the hardware. Prints
    daemon uptime, last indoor record age, thread liveness, Mission
    availability, alarm state, and a few key live values.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. One-shot and --watch modes.

Usage:
    python status.py            # one snapshot
    python status.py --watch    # refresh every 2 s until Ctrl+C
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from src.mh_daq.config import load_config

# A few channels worth showing at a glance. Reference, an RH, a T, and the
# blower thermocouple. Names match config channel names; SI columns add units.
# Snapshot indoor_si keys are plain channel names (from scale_record), not the
# unit-suffixed names used in the SI file header. Match the plain names here.
_KEY_CHANNELS = [
    ("6V_Test_M2_C7", "6V ref (V)"),
    ("T_Gar_M5_C4", "Garage T (degC)"),
    ("T_HVAC-S_M5_C7", "HVAC supply T (degC)"),
    ("RH_Liv_M3_C3", "Living RH (%)"),
    ("T_blowermtr1_M6_C0", "Blower TC1 (degC)"),
    ("T_blowermtr2_M6_C1", "Blower TC2 (degC)"),
]
]


def _age_s(iso_str):
    if not iso_str:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(iso_str)).total_seconds()
    except ValueError:
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def render(data_dir):
    hb = _read_json(Path(data_dir) / "heartbeat.json")
    snap = _read_json(Path(data_dir) / "latest_snapshot.json")

    lines = []
    lines.append("=" * 52)
    lines.append(f"  MH DAQ status  {datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append("=" * 52)

    if hb is None:
        lines.append("  HEARTBEAT: not found. Daemon not running, or wrong")
        lines.append(f"  data dir: {data_dir}")
        return "\n".join(lines)

    hb_age = _age_s(hb.get("written_at"))
    alive = hb_age is not None and hb_age < 5.0
    lines.append(
        f"  Heartbeat: {'ALIVE' if alive else 'STALE'} (written {hb_age:.0f} s ago)"
        if hb_age is not None
        else "  Heartbeat: unknown age"
    )
    lines.append(f"  Started:   {hb.get('started_at')}")

    rec_age = _age_s(hb.get("last_indoor_record"))
    if rec_age is not None:
        flag = "OK" if rec_age < 5.0 else "LATE"
        lines.append(f"  Last indoor record: {rec_age:.0f} s ago  [{flag}]")
    else:
        lines.append("  Last indoor record: none yet")

    threads = hb.get("threads_alive", {})
    dead = [n for n, a in threads.items() if not a]
    if threads:
        status = "all alive" if not dead else f"DEAD: {', '.join(dead)}"
        lines.append(f"  Threads: {status}")

    lines.append(f"  Mission: {'reachable' if hb.get('mission_available') else 'UNREACHABLE'}")

    alarms = hb.get("alarms", {})
    tripped = alarms.get("tripped_rules", [])
    frozen = alarms.get("frozen_channels", [])
    dropout = alarms.get("dropout", False)
    lines.append(
        f"  Alarms: {'DROPOUT' if dropout else 'no dropout'}, "
        f"{len(tripped)} tripped, {len(frozen)} frozen"
    )
    for r in tripped:
        lines.append(f"    tripped: {r}")
    for fch in frozen:
        lines.append(f"    frozen:  {fch}")

    lines.append("-" * 52)
    if snap and snap.get("indoor_si"):
        si = snap["indoor_si"]
        for col, label in _KEY_CHANNELS:
            v = si.get(col)
            if v is not None:
                lines.append(f"  {label:<16} {v:>10.3f}")
        out = snap.get("outdoor", {})
        ws = out.get("wind_speed")
        at = out.get("air_temp")
        bv = out.get("battery_voltage")
        lines.append(f"  {'AIO2 wind m/s':<16} {ws if ws is not None else 'n/a':>10}")
        lines.append(f"  {'AIO2 air T degC':<16} {at if at is not None else 'n/a':>10}")
        lines.append(f"  {'AIO2 batt V':<16} {bv if bv is not None else 'n/a':>10}")
    else:
        lines.append("  Snapshot: not found or empty.")
    lines.append("=" * 52)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="MH DAQ status.")
    ap.add_argument("--watch", action="store_true", help="Refresh every 2 s.")
    args = ap.parse_args()

    config = load_config()
    data_dir = config.local.local_data_dir

    if not args.watch:
        print(render(data_dir))
        return
    try:
        while True:
            print("\033[2J\033[H", end="")  # clear screen
            print(render(data_dir))
            time.sleep(2.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
