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

## Confirmed from the DAQ PC (2026-09-25, read-only checks)

- Device enumeration matches config exactly: cDAQ1 (cDAQ-9178), cDAQ1Mod1 to Mod5 (NI 9201), cDAQ1Mod6 (NI 9213). No physical-channel string changes needed.
- nidaqmx 1.6.0 present on the DAQ PC. Repo cloned at C:/Users/iaq/Documents/building423_iaq-mh_daq.
- COM ports: COM1 (built-in), COM3 (Intel AMT SOL), COM6 (USB Serial Port, the AIO 2). AIO 2 is on COM6.
- AIO 2 checksum formula CONFIRMED against 5 live lines: decimal sum of all characters before the asterisk, including the comma immediately preceding it. Step 4 compute_checksum is correct.
- AIO 2 real line format CONFIRMED: WS,WD,AT,RH,BP,RN,SR,BV,CV,CONFIG,*CHECKSUM. Example: 002.3,005,+020.2,037,1000.2,000.00,0000,23.2,032,M0,*02509. Both BV and CV already enabled; battery_voltage and compass_heading populate with no terminal-mode change.
- Step 4 parser produces correct fields from real lines. No change needed.
- Battery voltage reads 23.2 V (24 V nominal supply, within 8-36 VDC spec). Confirm supply is 24 V.
- Rain (000.00) and solar (0000, flickers to 0002) read as expected with no external sensors connected. Treat as unpopulated.
- Caution: serial capture required COM6 free, so the temp weather script was not holding the port at capture time. Ensure the temp script is running again so no weather data gap opens during the active campaign.

## Current status (2026-09-28, after first hardware cutover attempt)

First hardware cutover ran on the DAQ PC service day. Daemon ran on real hardware: DAQmx task opened 42 channels at 1 kHz x 100 samples, 1 Hz loop, AIO 2 auto-detected on COM6, all five threads alive, Mission reachable. Validated against today's LabVIEW output channel for channel:
- 6V reference: LabVIEW 5.707-5.733, new system 5.716. MATCH. (Battery has aged to ~5.71 on both; not a fault. Both systems agree, confirming the voltage path is faithful.)
- T_HVAC-S_M5_C7: both read ~-40 (0 V). The HVAC supply HMP155 temperature probe is currently disconnected/unpowered; both systems report it identically. RH side (RH_HVAC-S) reads ~81 on both, so only the T probe is off.
- House dP channels (dP_Liv-Hi etc.): both at 0 V floor (LabVIEW -0.100 in WC, new system -24.878 Pa). House dP Setras are intentionally not connected; configured in case they are reconnected. HVAC filter Setras ARE connected and reading.
- Conclusion: new system reads the hardware faithfully. Cutover validated. (Note: an early-session comparison against a stale 01/05/2026 LabVIEW file was misleading because module 2 was wired differently then; the current 09/28/2026 file is the correct baseline and confirms the match.)

Decision: NOT switching yet. Reasons: (1) this week's test differs from past tests; keep data consistent on LabVIEW for the week. (2) A lab-test period follows for a week or two when the MH DAQ is least needed; do the full move then (daemon + UI + web) in one deliberate window. Rolled back to LabVIEW for now.

## Backup replacement (decided 2026-09-28, pending layout choice)

The daemon's Mission mirror is intended to REPLACE the existing Mission backup, not run alongside it. Current state and the open decision:
- Existing backup: blindly copies C:/Users/iaq/Desktop/Outdoor_Data and C:/Users/iaq/Desktop/Task_Logger_Data (and subdirs) wholesale to Mission raw_data. It targets the LabVIEW-era source folders.
- New daemon: writes MH_Indoor_SI.txt, MH_Indoor_raw.txt, MH_Outdoor.txt, metadata, snapshot to C:/Users/iaq/Desktop/MH_DAQ_Data (confirmed present, files appear), and mirrors to Mission raw_data with a year-subfolder layout.
- The two do not align: same Mission root, different file names and folder structure. If the daemon became system of record while the old backup kept running, the old backup would copy stale LabVIEW folders and miss the new data.
- End state: retire the old backup script; the daemon mirror does that job, and better (local-first so outages never block acquisition, filesystem-diff self-heal vs blind recopy).
- OPEN DECISION before the full move: does the daemon write into Mission raw_data with its own year-based layout and new names (and the WUI smoke chain is updated to read those), OR does the daemon match the old folder-and-name layout so nothing downstream changes? Nathan owns this call (he owns downstream analysis).
- mission_data_dir (raw_data) is correct and is where the backup script saves. Confirmed.
- mission_snapshot_dir (live_snapshot) does NOT exist on Mission and was not created (snapshot mirror runs on a 60 s interval; dir is auto-created on first copy). Decide deliberately where the snapshot lives, or defer until the webpage exists.

## Web dashboard (in progress, 2026-09-29)

Group-private live dashboard built and working against sim data on NISTTeleworkSys.
- `web/dashboard.py`: FastAPI app. Endpoints: /api/snapshot (current values), /api/trend (recent SI series). One HTML page polls snapshot every 3 s, plot every 15 s.
- Indoor cards grouped: Temperature, Relative Humidity, Differential Pressure, HVAC System (HVAC supply T and RH, filter dPs, return flow, blower power, blower TCs), Reference/Other. Grouping split of HVAC sensors into their own section is provisional; confirm vs folding HVAC T/RH back with the other temps/humidities.
- Plotly vendored at `web/static/plotly.min.js` (4.56 MB, 2.35.3) so no CDN dependency. The web box will likely have no outbound internet.
- Separate conda env `mh_daq_web` (fastapi, uvicorn, pandas) from `environment-web.yaml`, keeping web deps off the DAQ PC.
- Data root: config.local.local_data_dir by default; MH_DAQ_DATA_ROOT env var override. For Mission later, snapshot (live_snapshot) and dailies (raw_data/mh_daq) are two roots; will need a second env var for the snapshot path then.
- Run: sim daemon in one window (`run_daq.py --sim`), dashboard in another (`python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000`, mh_daq_web env, from repo root).

Open dashboard work, next passes:
- Channel picker for the trend plot (currently fixed 4 channels). Note: channels span very different scales (degC ~21, % ~45, V ~6, Pa ~0); picker needs unit-grouping or a secondary axis so small-range channels are not flattened.
- Weather-only public view (NIST-internal, AIO 2 only, view plus CSV download).
- Access separation: group-private full-data page vs NIST-internal weather page.
- Endpoint tests once the shape settles.
- Deploy to the web box (Windows 11 now; may move to a Linux VM via IT; uvicorn runs the same on both).
- Vendor note: plotly.min.js is committed so the web box needs no internet.

## Remaining before full move
- Decide Mission layout / backup retirement (above).
- RDP status tool: DONE and working (status.py). compare_cutover.py helper added for the cutover.
- Second cutover during the lab-test lull: full startup including UI and webpage feed.
- Splinterware autostart via start_mh_daq.bat, only after the daemon has run attended and trusted for a day or two.
- Retire the old Mission backup script as an explicit cutover step.

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
5. Acquisition daemon: cDAQ task, serial reader, scaling, local daily file writer with SI units in headers. Core DONE (indoor path): `src/mh_daq/writer.py` (three daily files, per-day metadata sidecar, atomic snapshot, SI units in single-row headers), `src/mh_daq/daemon.py` (run_once plus monotonic-paced run_loop), `tests/test_writer_daemon.py`. Outdoor serial reader wired in step 7. Validated on NISTTeleworkSys.
6. Mission mirror with offline queue and retry. DONE, implemented as a filesystem diff (no in-memory queue, self-heals across outages and restarts): `src/mh_daq/mirror.py`, `tests/test_mirror_alarms.py` (mirror portion). Snapshot 60 s, in-progress off by default, retry 30 s.
7. Alarm engine and SMTP. DONE: `src/mh_daq/alarms.py` (threshold rules with dwell, trip/clear/re-notify, frozen detection, dropout watchdog; injectable email sender). Real SMTP send confirmed from NISTTeleworkSys through smtp.nist.gov:25. Tests use a recording sender. 46 tests passing total.
8. Threading supervisor (step 7 in build): cDAQ loop, AIO 2 serial reader, mirror, and dropout watchdog as independent threads, plus COM auto-detect with manual override. DONE: `src/mh_daq/serial_source.py` (LineSource, PySerialSource, auto_detect_port validating by parsed line, resolve_port), `src/mh_daq/outdoor_reader.py` (threaded AIO 2 reader, own arrival timestamp, independent reconnect), `src/mh_daq/supervisor.py` (four independent threads, shared latest-outdoor into snapshot, alarm hook on indoor cycle, dropout watchdog thread), `tests/test_serial_supervisor.py`. Writer made thread-safe with a lock (fixed an intermittent rollover race). 52 tests passing. Only untested-until-hardware piece: PySerialSource opening a real port, already proven when 5 live AIO 2 lines were captured.
9. Snapshot publish layer for future webpages (Mission). Snapshot written by indoor loop, mirrored to Mission every 60 s. Webpage feed format is future work.
10. Real nidaqmx backend implementing the shared AcquisitionBackend interface. DONE: `src/mh_daq/backends/nidaqmx_backend.py` (mixed voltage + Type J thermocouple task, RSE, built-in CJC, added in config order, oversample-and-average), registered lazily in `backends/__init__.py`. Entry point `run_daq.py` (--sim / --hardware), autostart `start_mh_daq.bat`. Written against confirmed nidaqmx 1.6.0 API. Hardware-only, validated in cutover not pytest. Full daemon dry-run in sim confirmed on NISTTeleworkSys.
11. Heartbeat and RDP status tool. DONE: supervisor writes atomic heartbeat.json each second (uptime, last indoor record, thread liveness, Mission availability, alarm state); `status.py` one-shot and --watch reader. Reader only, safe over RDP. Key channel lookups use plain channel names (snapshot indoor_si keys), 6V ref reads ~6.0 in sim. 53 tests passing.
12. Supervised hardware cutover on the DAQ PC (Monday service day). NEXT. Offline math validated; use 6V reference to confirm AD path; stop LabVIEW cDAQ VI and temp weather script, run `run_daq.py --hardware`, watch `status.py --watch`, compare key channels against last LabVIEW values, roll back to LabVIEW if anything is off. Checklist and comparison helper to be delivered before Monday.
13. Splinterware autostart via start_mh_daq.bat (after cutover is trusted).
14. Web box and pages: later, out of current scope.

## Current status (2026-09-25)

Entire acquisition system built and validated in simulation, 53 tests passing on NISTTeleworkSys. All hardware-adjacent facts confirmed on the DAQ PC: device names (cDAQ1, Mod1-6), AIO 2 checksum formula (5 live lines), nidaqmx 1.6.0 API (enums and methods), AIO 2 real line format (BV and CV both on). Remaining: supervised hardware cutover Monday, then autostart, then the future webpage box. Repo pushed to main on NathanL-CodeBase (private), to fold into usnistgov/Building423_IAQ-MH_DAQ later as a major update.

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
