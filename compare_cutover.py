#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cutover comparison helper.

Purpose: Print the key SI values from the running daemon's snapshot in a compact
    table, with simple sanity flags, so they can be compared against the last
    LabVIEW readings during the supervised cutover. Reads only latest_snapshot
    .json; no hardware, no open-file access.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version for the Monday cutover.

Usage:
    python compare_cutover.py            # one snapshot
    python compare_cutover.py --watch    # refresh every 5 s
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from src.mh_daq.config import load_config

# (snapshot key, label, expected low, expected high, unit). Expected ranges are
# rough plausibility bounds for a serviced, occupied-ish test house in fall, not
# calibration limits. A value outside the range is a prompt to look, not a fault.
_CHECKS = [
    ("6V_Test_M2_C7", "6V reference", 5.8, 6.2, "V"),
    ("T_Liv_M4_C7", "Living T", 10.0, 32.0, "degC"),
    ("T_Gar_M5_C4", "Garage T", 5.0, 40.0, "degC"),
    ("T_HVAC-S_M5_C7", "HVAC supply T", 5.0, 50.0, "degC"),
    ("T_Out_M5_C6", "Outdoor T", -15.0, 45.0, "degC"),
    ("RH_Liv_M3_C3", "Living RH", 5.0, 95.0, "percent"),
    ("RH_Out_M4_C2", "Outdoor RH", 5.0, 100.0, "percent"),
    ("T_blowermtr1_M6_C0", "Blower TC1", 5.0, 90.0, "degC"),
    ("T_blowermtr2_M6_C1", "Blower TC2", 5.0, 90.0, "degC"),
    ("dP_Liv-Hi_M1_C0", "Living dP Hi", -50.0, 50.0, "Pa"),
    ("cfm_return_duct_M2_C1", "Return flow", 0.0, 3400.0, "m3/h"),
    ("watts_blowermtr_M2_C2", "Blower power", 0.0, 1000.0, "W"),
]


def _read_snapshot(data_dir):
    p = Path(data_dir) / "latest_snapshot.json"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def render(data_dir):
    snap = _read_snapshot(data_dir)
    out = []
    out.append("=" * 60)
    out.append(f"  Cutover comparison  {datetime.now():%H:%M:%S}")
    out.append("=" * 60)
    if not snap or not snap.get("indoor_si"):
        out.append("  No snapshot yet. Is run_daq.py --hardware running?")
        out.append("=" * 60)
        return "\n".join(out)

    si = snap["indoor_si"]
    out.append(f"  Snapshot time: {snap.get('timestamp')}")
    out.append(f"  {'Channel':<16}{'Value':>12}  {'Unit':<8}Flag")
    out.append("-" * 60)
    for key, label, lo, hi, unit in _CHECKS:
        v = si.get(key)
        if v is None:
            out.append(f"  {label:<16}{'MISSING':>12}  {unit:<8}!!")
            continue
        flag = "ok" if lo <= v <= hi else "CHECK"
        out.append(f"  {label:<16}{v:>12.3f}  {unit:<8}{flag}")

    out.append("-" * 60)
    o = snap.get("outdoor", {})
    out.append(f"  AIO2 wind (m/s):  {o.get('wind_speed', 'n/a')}")
    out.append(f"  AIO2 air T (degC):{o.get('air_temp', 'n/a')}")
    out.append(f"  AIO2 batt (V):    {o.get('battery_voltage', 'n/a')}")
    out.append(f"  AIO2 RH (%):      {o.get('relative_humidity', 'n/a')}")
    out.append(f"  AIO2 BP (mb):     {o.get('barometric_pressure', 'n/a')}")
    out.append("=" * 60)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Cutover comparison.")
    ap.add_argument("--watch", action="store_true", help="Refresh every 5 s.")
    args = ap.parse_args()
    data_dir = load_config().local.local_data_dir
    if not args.watch:
        print(render(data_dir))
        return
    try:
        while True:
            print("\033[2J\033[H", end="")
            print(render(data_dir))
            time.sleep(5.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
