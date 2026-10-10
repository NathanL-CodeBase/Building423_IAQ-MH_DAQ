# Project Conventions: MH DAQ

This file adds to the global preferences in `~/.claude/CLAUDE.md` and does not replace them. Shared DAQ and instrument conventions live in the `iaq-field-data` skill (see its `references/daq-acquisition.md` and `references/test-house-facility.md`). If the skill is missing on this machine, stop and tell me.

## This project
- Purpose: data acquisition, logging, alarms, and live web display for the NIST Building 423 IAQ Manufactured House. It replaces a LabVIEW cDAQ VI, a LabVIEW AIO 2 VI, and a temporary Python weather script.
- Hardware: NI cDAQ-9178 (five NI 9201 voltage modules, one NI 9213 thermocouple module) and a Met One AIO 2 on RS-485 to USB (9600 baud, 8N1, 1 Hz).
- Conda environments: `iaqmh_daq` for acquisition, `mh_daq_web` for the dashboard.
- Status (2026-10-10): running on the acquisition machine since 2026-10-07 12:11:23 local, in a week-long test. The house and the PM instruments are logging background while the campaign does gas-phase chamber work for the next few weeks.
- `README.md` and `doc/mh-daq-plan.md` (last updated 2026-10-02) predate the cutover and still call LabVIEW the system of record. Update them when I ask.
- This repository will be folded into `Building423_IAQ-MH_DAQ`, which works on the same hardware.

## When to load a skill
- `iaq-field-data`: before changing acquisition, scaling, writer, mirror, or config code, and before reading an output file.
- `no-ai-slop` and `nist-science-voice`: before writing or editing prose (global rule).

## Commands
| Purpose | Command | Needs hardware |
|---|---|---|
| Tests | `pytest -v` | No |
| Simulated daemon | `python run_daq.py --sim` | No |
| Daemon status | `python status.py` | No (reads a running daemon) |
| Dashboard | `python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000` | No |
| Hardware daemon | `python run_daq.py --hardware` | Yes |

## Rules that always apply
- Never run `python run_daq.py --hardware`. It runs on the acquisition machine only, and only when no other program owns the cDAQ. If a hardware run is needed, tell me and stop.
- The daemon on the acquisition machine is live. Do not stop it, restart it, or change files it reads without my explicit go-ahead.
- `daq_local.json` is gitignored and holds paths, the serial port, and SMTP details. Never commit it, and never copy its values into a tracked file or a log.
- `config/daq_config.json` holds the channel map, scales, timing, and alarm rules. The scale coefficients come from the NI MAX export. Ask before changing a coefficient, a channel, or an alarm rule.
- Output is SI with the unit in each column name: Pa, m3/h, degC, percent, W. Timestamps in the data files are local time.
- The acquisition machine writes locally first, then mirrors to network storage. Downstream code reads the network copy. Do not write to the network storage from tests or from a development machine.
- `retention_days` is read but not enforced. Enforcing it deletes local data, so do not add deletion code without my decision on the rule.
- Do not install or update the NI-DAQmx driver, and do not change a registry key. Tell me what is needed.

## Data knowledge lives in `NIST_wui-smoke-iaq-mitigation`
That repository is the current reader of these files and holds the evaluation of current and historical DAQ data. Before a change that affects what is written, read there:
1. `docs/data_files_reference.md`, section "Test House Facility (Indoor DAQ and Weather)".
2. `src/environmental_loader.py` (reads both file eras and joins them at the cutover).
3. `data_config.template.json`, the notes under `instruments.mh_daq_indoor` and `instruments.mh_daq_weather`.
4. `docs/instruments/INSTRUMENT_DOCUMENTATION.md`, the Facility and HVAC sections.

The skill's `references/test-house-facility.md` is an extract dated 2026-10-10. The repository is newer whenever the two differ. If that repository is not on this machine, say so and ask.

What that evaluation found, and what it means here:
- The loader reads `{YYYYMMDD}-MH_Indoor_SI.txt`, `{YYYYMMDD}-MH_Outdoor.txt`, and `{YYYYMMDD}-MH_metadata.json` and maps columns by name. A change to a file name, a column name, a unit, or the timestamp format breaks it. Ask first.
- The LabVIEW files changed header five times between 2026-07-06 and 2026-10-06. Do not rename a column in place. Add a column, and record the date in the metadata file.
- The filter dP sensors were swapped on 2026-09-01 13:45:01 while LabVIEW kept the old channel names until 2026-09-09. When a sensor on a channel changes, record the swap time and the new range in config, and name the column by sensor range.
- The LabVIEW files repeated about 300 timestamps per day and skipped about as many. Check new files for repeated or skipped seconds after any change to the acquisition loop or the writer.
- Both eras put a trailing tab on every data row, and the loader reads with `index_col=False`. Keep the row format unless I ask for a change.
- The cutover left about 20 minutes with no data on 2026-10-07 (last LabVIEW record 12:06:22, first rebuilt record 12:11:23, a further hole 12:12:08 to 12:26:57). Log every restart with its start and stop time.
- New-format files dated before the cutover are test data (2026-09-28 holds a 23 minute snippet).
- Rain and solar read zero with no sensor attached. Wind direction is referenced to magnetic north.
- Slot 1 (NI 9201) is installed and logged, but the Setra 264 envelope dP sensors are not connected to it (confirmed 2026-10-10). Its channels report an open-input voltage, not a pressure. The sensors are still in the house with their wires run to the DAQ, so they can be reattached. Treat the slot 1 columns as no data, keep the channels in the channel map, and when I say a sensor is reconnected, record the date and time in config and in the metadata file.

## Differences from the repository standard
- Documentation is in `doc/`, not `docs/`.
- The local config is `daq_local.json`, created from `config/daq_local.template.json`. There is no `data_config.json`.
- Entry points (`run_daq.py`, `status.py`, `compare_cutover.py`) sit in the repository root, not in `scripts/`.
- The citation file is `CITATION.md`, not `CITATION.cff`.
- Leave these as they are. The layout will be settled when the code moves into `Building423_IAQ-MH_DAQ`.
