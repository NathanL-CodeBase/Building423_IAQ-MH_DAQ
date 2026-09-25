# MH DAQ Rebuild: Planning Document

Author: Nathan Lima (NIST)
Created: 2026-09-25
Status: Planning. No code written yet. First build increment is the config, scaling, validation, and simulation core with no hardware.

## Purpose

Replace three separate pieces (the LabVIEW cDAQ acquisition VI, the broken LabVIEW AIO 2 VI, and the temporary `generate_weather_station_daq.py` bridge) with one Python system. The system acquires from a National Instruments cDAQ-9178, scales to SI, logs raw and SI values, mirrors to network storage, runs alarms with email, and feeds future internal webpages. Goal is a clean break from the NI software: clean, understandable, robust, reliable for months of unattended operation.

## Hardware

cDAQ-9178 chassis, 8 slots, USB. Serial `0x219A8FA`.

| Slot | Module | Type | Use |
|---|---|---|---|
| 1 | NI 9201 | 8-ch AI +/-10V | Setra 264 dP pairs (Liv, Bed3-E, Fam-S, Fam-W) |
| 2 | NI 9201 | 8-ch AI +/-10V | BLANK, cfm return duct, watts blower, 4x HVAC filter dP, 6V ref |
| 3 | NI 9201 | 8-ch AI +/-10V | RH channels |
| 4 | NI 9201 | 8-ch AI +/-10V | RH + T channels |
| 5 | NI 9201 | 8-ch AI +/-10V | T channels |
| 6 | NI 9213 | 16-ch thermocouple | 2x blower motor thermocouples, Type J |
| 7 | open | | future |
| 8 | open | | future |

Channel map can evolve, so the channel list must be data-driven from config, not hardcoded.

Met One AIO 2 sonic weather sensor: RS-485 to USB adapter, 9600 baud, 8N1, ASCII lines at 1 Hz, comma-delimited. Separate from the cDAQ. COM port on the current machine is COM6 but must auto-detect with manual override.

### Serial mouse driver note

The RS-485 to USB adapter can be grabbed by Windows as a "Microsoft Serial BallPoint" mouse, which blocks the COM port. Already fixed on the DAQ PC by disabling the sermouse driver. Record here in case the machine is rebuilt: set `HKLM\SYSTEM\CurrentControlSet\Services\sermouse\Start` to 4 and reboot. Verify the key exists before changing it.

## Machines

Two distinct machines. Do not conflate them.

Dev and test box: NISTTeleworkSys. Where all development and simulation-backed testing happens. No cDAQ hardware attached. Its `daq_local.json` has `machine_name = NISTTeleworkSys` and non-hardware placeholder paths. Steps 1 to 4 (config, scaling, tests, simulator) run and are validated here.

DAQ PC (acquisition machine): Windows 11, i5-1245U (12th gen), 16 GB RAM, 500 GB storage. Keep installs minimal. NI-DAQmx driver already installed. Runs the headless daemon against real hardware. Gets its own `daq_local.json` with its own hostname, real Mission and desktop paths, and the actual COM port. Only the supervised cutover in the validation phase happens here.

Both machines: Python via conda-forge, environment `iaqmh_daq`. PowerShell is the shell. Splinterware System Scheduler triggers `.bat` files for autostart on the DAQ PC (Windows Task Scheduler is not available for this). The committed `daq_config.json` is shared across both machines; only the local file differs.

### Environment

Env `iaqmh_daq` built from `environment.yaml` (conda-forge): python 3.13, pandas, requests, pyserial, pytest, and `nidaqmx-python`. Note the conda package is `nidaqmx-python` (import stays `import nidaqmx`); the bare `nidaqmx` conda package is dead (last upload 2019, no files). `nidaqmx-python 1.6.0` confirmed importing on NISTTeleworkSys. The NI-DAQmx runtime driver is only needed for real-hardware calls, so the import and the simulation backend run fine on the driverless dev box.

## Coefficients from NI MAX export

DAQmx task ran 1000 Hz sample clock, 100 samples per channel, finite. Effective output rate 1 Hz (100-sample average). Reproduce this: oversample at 1 kHz, average 100 samples to one record per second.

All linear scales below are raw volts to the NI MAX scaled unit. The new system chains these to SI and logs raw volts separately.

| NI MAX scale | Slope | Y-intercept | Raw range | NI MAX unit |
|---|---|---|---|---|
| Setra 264 (-01 to 01 WC) | 0.04 | -0.1 | 0-5 V | inch WC |
| Setra 264 (-025 to 025 WC) | 0.1 | -0.25 | 0-5 V | inch WC |
| Setra 264 (-05 to 05 WC) | 0.2 | -0.5 | 0-5 V | inch WC |
| Setra 264 (-1 to 1 WC) | 0.4 | -1.0 | 0-5 V | inch WC |
| Setra 264 (-15 to 15 WC) | 0.6 | -1.5 | 0-5 V | inch WC |
| Electra-Flo G5 | 200 | 0 | 0-10 V | ACFM |
| W-002E-T watts | 125 | -250 | 2-10 V | Watts |
| HMP155s_RH | 10 | 0 | 0-10 V | Percent |
| HMP155s_T | 10 | -40 | 0-10 V | Deg C |
| HMP45a_RH | 100 | 0 | 0-1 V | Percent |
| HMP45a_T | 100 | -40 | 0-1 V | Deg C |

Thermocouples: Type J, built-in CJC, Deg C, configured through the 9213 in nidaqmx (driver returns temperature directly, not voltage).

## SI conversion policy

Log both raw volts and SI. Write two daily files: an immutable raw-volts file and a derived SI file. Units named in every SI column header.

Conversions to SI:
- Differential pressure: inch WC to Pa, factor 248.84. So a Setra scale to Pa is (slope x V + intercept) x 248.84.
- Return duct flow: ACFM to m3/h, factor 1.699. Electra-Flo to m3/h: (200 x V) x 1.699, so 0-10 V maps 0 to about 3398 m3/h.
- Watts: already SI.
- RH: percent, already SI.
- Temperature: Deg C, already SI.

Standing IAQ unit conventions for reference (not all present on this DAQ): PM as ug/m3, CO2 as ppm, CO as ppm, O3 as ppb.

## Architecture

Split always-on acquisition from everything that displays or serves. The UI or a webpage failing must never touch acquisition.

### DAQ PC: acquisition daemon (headless, autostart)

Owns the hardware. One DAQmx task for the cDAQ (1 kHz oversample, average 100 to 1 Hz record). Second thread reads AIO 2 over serial. Scales to raw and SI. Responsibilities:
- Write local daily files first (primary, so a network outage never drops a sample). Local desktop folder.
- Mirror completed and in-progress files to Mission on a separate thread. Queue and retry when Mission is unavailable. Never block acquisition.
- Publish a near-live snapshot to Mission for the future webpages (latest values plus a rolling recent window). Target cadence 1 minute.
- Run the alarm engine.
- Maintain a local heartbeat and status file for the RDP status tool.
- Local retention window so the 500 GB disk never fills. Mission holds history.

Only the daemon writes the archival files. This removes the LabVIEW two-writer crash: no second process ever opens the live file.

### DAQ PC: RDP status tool (launched on demand)

Lightweight. A person connects by Remote Desktop, runs it, checks, closes. Reads the daemon heartbeat and status file. Shows: daemon alive and last sample time, cDAQ task state, serial and COM state, per-channel latest values, current alarm state, Mission mirror health including queued unsent files. Keep dependencies minimal. Full plotting lives on the group webpage, not here. pyqtgraph can be added later if on-site plots are wanted.

### Separate web box (future, not built yet): reads Mission only

Never touches the DAQ PC. Serves two independent pages:
- Group-private page: all data (indoor and AIO 2), live view.
- NIST-internal weather page: AIO 2 only, for download by NIST people outside the IAQ and V group. Indoor data is structurally absent from this feed, not filtered.

"Live" means as fresh as the Mission publish cadence (1 minute). Feed format designed now, page built later.

## Data flow summary

DAQ PC writes local, then mirrors to Mission and publishes a snapshot to Mission. Web box reads Mission. UI and both webpages read Mission, never the DAQ PC. Mission is the boundary between acquisition and everything downstream.

## Config

Desktop JSON config on the DAQ PC, editable and re-created on each machine from a committed template. Holds: channel map (from NI MAX export), per-channel raw-to-SI scales, COM port with auto-detect and manual override, local and Mission paths, alarm rules, SMTP settings, retention window. Same pattern as the existing `data_config.json`. Fail clearly if the config is missing, pointing to the template.

## Alarms

Per-channel high and low thresholds with dwell time. Dropout, stale, and frozen-value detection. Email through smtp.nist.gov port 25.

Active rule for now: garage temperature above 28 C for more than 1 minute. HVAC blower motor thermocouple thresholds and others to be set later by Nathan. Validation takes priority over adding rules.

## Repository and naming

Package name: `mh_daq`. Test repo for now: `mh-daq-rebuild` under NathanL-CodeBase as `origin` (confirm). Later folded into `usnistgov/Building423_IAQ-MH_DAQ` as a major update, pushed as NathanL-NIST. SSH remotes only. No auto-commit or auto-push. Stage, show diff, wait.

## Build order

1. Config schema and loader, plus committed template. Channel map and scales baked in from the NI MAX export. DONE, validated on NISTTeleworkSys (42 channels, 12 scales, 1 alarm rule). Delivered: `config/daq_config.json`, `config/daq_local.template.json`, `src/mh_daq/__init__.py`, `src/mh_daq/config.py`, `.gitignore`, `environment.yaml`.
2. Scaling module (raw volts to SI, both retained). DONE, validated on NISTTeleworkSys (18 pytest cases pass). Delivered: `src/mh_daq/scaling.py`, `tests/test_scaling.py`, `pytest.ini`, and the nine-column AIO 2 schema in `config/daq_config.json`. SI endpoints proven: Setra +/-0.1 in WC maps 0-5 V to -24.88 to +24.88 Pa; Electra-Flo maps 0-10 V to 0 to 3398 m3/h; HMP155 T maps 0-10 V to -40 to +60 degC. inch WC to Pa uses 248.84 (60 degF basis).
3. Offline validation tests (pytest), no hardware. DONE (folded into step 2).
4. Simulation backend producing realistic channel data, so the whole system runs with no hardware. Plus the AIO 2 line parser with checksum validation and resilient field-count handling (BV and CV may be off, so field count varies).
5. Acquisition daemon: cDAQ task, serial reader, scaling, local daily file writer with SI units in headers.
6. Mission mirror with offline queue and retry.
7. Alarm engine and SMTP.
8. Snapshot publish layer for future webpages (Mission).
9. RDP status tool.
10. Splinterware autostart of the daemon via `.bat`. Status tool launched manually from the desktop.
11. Web box and pages: later, out of current scope.

Steps 1 to 4 touch no hardware and no network. That is the current priority: prove the SI math before scheduling a cutover.

## Validation and cutover

The DAQmx task reserves the channels, so LabVIEW and the Python task cannot both own them. This forces a clean hand-off and gives an immediate rollback (restart LabVIEW).

Sequence:
1. Offline math validation (step 3 above), no hardware.
2. Use the 6V reference channel (6V_Test_M2_C7, lantern battery, constant) to confirm the AD path reads what LabVIEW read.
3. Supervised cutover window: stop LabVIEW, start the Python daemon, capture a few minutes, compare scaled values and the reference channel against the last LabVIEW output for the same sensors. Agree within sensor accuracy: proceed. Disagree: roll back to LabVIEW.

Build and test against the simulation backend before the daemon ever holds the real cDAQ.

## Working constraints (from user preferences)

- Ask before every action. Plan, wait for OK, execute. No chaining.
- No hardcoded paths. All machine-specific paths through the desktop config, re-created from a committed template.
- Raw data immutable. Never overwrite output silently; version or ask. Never delete without confirmation.
- Windows 11, PowerShell syntax, conda-forge. Ask before installing packages.
- Python style: pandas for data, matplotlib for static publication figures, pyqtgraph for live display. Header docstring on every script (purpose, author Nathan Lima, created date, update log). NumPy or Google docstrings. Comments explain why. Scripts under about 1000 lines, refactor to `src/` beyond that. f-strings.
- Prose: no em dashes, no ampersands in prose, no intensifiers or AI filler, claims end on checkable detail with units.

## Open items to confirm

1. Test repo under NathanL-CodeBase as `origin`, name `mh-daq-rebuild`. Confirm or rename.
2. Target `iaqmh_daq` conda env, add `nidaqmx`, `pyserial`, `pytest`. Confirm before install.
3. Local retention window length on the DAQ PC (for example, keep 30 or 90 days locally).
4. Mission publish cadence for the snapshot (planning assumption: 1 minute).
5. New file naming and folder for the SI and raw files, to mark the new system era. Still saved to Mission. Old name was `{date}-Daily_MHIndoor_Data.txt` and `{date}-Daily_MHOutdoor_Data.txt`.
6. Whether the AIO 2 stays in one combined system or the weather feed is packaged for the separate NIST-internal page. Planning assumes one daemon acquires both; web box handles separation.

## Decisions locked

- Thermocouples are Type J (matches NI MAX export).
- Output units are SI, with units in file headers. inch WC to Pa at 248.84 (60 degF basis).
- Log both raw volts and SI, in two indoor files. Outdoor is one file (AIO 2 outputs engineering units, no raw split).
- Outdoor file carries nine measurement columns: wind_speed, wind_direction, air_temp, relative_humidity, barometric_pressure, rain, solar_radiation, battery_voltage, compass_heading. config and checksum are metadata, not logged; checksum used for line validation.
- Rain and solar external sensors not currently connected; columns annotated present=false, may read 0 until added.
- Wind direction referenced to magnetic north; no declination set. True north would require the MD command at the sensor.
- battery_voltage and compass_heading appear in the serial string only if BV and CV are enabled at the sensor. Parser handles variable field count. One-time terminal check (BV1, CV1, Q) needed if those columns should be populated.
- Serial mouse driver already disabled on the DAQ PC.
- Headless autostart daemon plus an on-demand RDP status tool.
- UI and webpages read Mission, never the DAQ PC. Web serving runs on a separate box.
- Local write first, then mirror to Mission with graceful handling of Mission being unavailable.

## Known environment friction

The dev repo currently lives under `C:/Users/nml/OneDrive - NIST/Documents/GitHub/...`. OneDrive sync locks paths and caused two issues so far: a stale bytecode cache, and pytest failing to write `.pytest_cache` (WinError 5). Neither affects correctness. Plan: move the repo to a plain local path (for example `C:/Users/nml/dev/`) and let git and GitHub handle sync. On the DAQ PC, do NOT place the repo or the data and log folders under OneDrive; continuous writes and OneDrive do not mix. This aligns with the user preference against OneDrive - NIST paths.
