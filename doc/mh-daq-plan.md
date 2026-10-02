# MH DAQ Rebuild: Status and Remaining Work

Author: Nathan Lima (NIST)
Created: 2026-09-25
Last updated: 2026-10-02

The build history, resolved open items, and earlier status notes were removed on 2026-10-02. They remain in git history before that date.

## Purpose

One Python system replaces three pieces: the LabVIEW cDAQ acquisition VI, the broken LabVIEW AIO 2 VI, and the temporary `generate_weather_station_daq.py` bridge. It acquires from an NI cDAQ-9178 and a Met One AIO 2, scales to SI, logs raw and SI daily files, mirrors to Mission, sends alarm email, and feeds the group and weather webpages.

## Status (2026-10-02)

Acquisition and the web layer are built and tested in simulation. The daemon ran once on real hardware, in the supervised cutover on 2026-09-28, and matched LabVIEW channel for channel. LabVIEW is still the system of record, by choice. The full switch waits for the lab-test lull, when the MH DAQ is least needed.

## Remaining work

Ordered roughly by when each should happen.

1. **Mission layout decision (before the full move).** The daemon writes to `raw_data/mh_daq/YYYY/` (`mission_subdir` = `mh_daq`, already coded). The LabVIEW-era `raw_data/indoor_daq` and `raw_data/weather_station` folders stay until moved to `old/` or left in place. Confirm what currently reads those folders so nothing is orphaned when the old backup is retired. Also decide where the snapshot lives: `mission_snapshot_dir` (`live_snapshot`) does not exist on Mission yet and is created on the first copy. Nathan owns this call; downstream projects (WUI and others) update their own readers.

2. **Hardware cutover (lab-test lull).** Stop the LabVIEW cDAQ VI and the temp weather script, run `run_daq.py --hardware`, and watch `status.py --watch` and `compare_cutover.py`. Compare the 6V reference, RH and T, blower TCs, and AIO 2 against the last LabVIEW values, then keep or roll back. Rollback: Ctrl+C, restart the LabVIEW VI and the temp script. Use that day's LabVIEW file as the baseline; the January 2026 file had module 2 wired differently.

3. **Retire the old Mission backup script** as an explicit cutover step. It copies `C:/Users/iaq/Desktop/Outdoor_Data` and `Task_Logger_Data` wholesale to `raw_data`. Running it alongside the daemon would copy stale LabVIEW folders and miss the new files.

4. **Local retention window.** `retention_days` is 90 in `daq_local.template.json`. The config loader reads it, but nothing deletes old local files yet. Enforcing it means automatic deletion of local data, so decide the window and the rule (for example, delete only files already confirmed on Mission) before coding it.

5. **Deploy the web layer to the web box.** The box runs Windows 11 now and may move to a Linux VM through IT; uvicorn runs the same on both. Point `MH_DAQ_DATA_ROOT` at `raw_data/mh_daq`. Mission keeps the snapshot and heartbeat in `live_snapshot` and the dailies in `raw_data/mh_daq`, so the web layer needs a second environment variable for the snapshot root. Raise the group-page health thresholds in `web/static/index.js` at the same time: `HEALTH_DELAYED_S` from 5 s to about 90 s and `HEALTH_DOWN_S` from 60 s to about 300 s. Mission reads lag the 60 s snapshot mirror, so the local values would show yellow, then red, all the time.

6. **Access separation.** The group-private page shows all channels; the NIST-internal weather page shows AIO 2 only. Two routes on one app with different scopes is the simplest layout. Choose the auth mechanism once the box is on a reachable network.

7. **Splinterware autostart** through `start_mh_daq.bat`, only after the daemon has run attended for a day or two.

8. **Fold into `usnistgov/Building423_IAQ-MH_DAQ`** as a major update, pushed as NathanL-NIST over SSH.

9. **Smaller items:**
   - Weather channels in the group picker. The picker is indoor-only; decide whether to add AIO 2 fields so indoor and outdoor trend on one plot.
   - Card grouping. HVAC supply T and RH sit in their own HVAC System section. Confirm, or fold them back into Temperature and Relative Humidity.
   - Web endpoint tests: snapshot present and absent, trend parsing, CSV download.
   - The watts scale description in NI MAX still carries a leftover self-note. Clean it when convenient.
   - The 6V reference battery reads about 5.71 V on both systems. Swap it; not urgent.
   - Confirm the AIO 2 supply is 24 V. Battery voltage reads 23.2 V, inside the 8 to 36 VDC spec.

## Reference

### Hardware

cDAQ-9178 chassis, 8 slots, USB, serial `0x219A8FA`.

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

The channel map lives in `config/daq_config.json`, not in code.

Met One AIO 2 sonic weather sensor: RS-485 to USB adapter, 9600 baud, 8N1, comma-delimited ASCII at 1 Hz. It is on COM6 on the DAQ PC; `com_port` = `AUTO` scans for it, with a manual override.

**Serial mouse driver.** Windows can claim the RS-485 adapter as a "Microsoft Serial BallPoint" mouse and block the port. This is already fixed on the DAQ PC. If the machine is rebuilt, set `HKLM\SYSTEM\CurrentControlSet\Services\sermouse\Start` to 4 and reboot. Verify the key exists before changing it.

### Confirmed on the DAQ PC (2026-09-25, read-only checks)

- Devices match config: cDAQ1 (cDAQ-9178), cDAQ1Mod1 to Mod5 (NI 9201), cDAQ1Mod6 (NI 9213).
- nidaqmx 1.6.0 is installed. Repo clone: `C:/Users/iaq/Documents/building423_iaq-mh_daq`.
- COM ports: COM1 (built-in), COM3 (Intel AMT SOL), COM6 (USB Serial Port, the AIO 2).
- AIO 2 checksum, confirmed on 5 live lines: decimal sum of every character before the asterisk, including the comma just before it.
- AIO 2 line format: `WS,WD,AT,RH,BP,RN,SR,BV,CV,CONFIG,*CHECKSUM`, for example `002.3,005,+020.2,037,1000.2,000.00,0000,23.2,032,M0,*02509`. BV and CV are both enabled.
- Rain reads `000.00` and solar reads `0000` (flickering to `0002`) with no external sensors connected. Treat both as unpopulated.

### First hardware cutover (2026-09-28)

The DAQmx task opened 42 channels at 1 kHz x 100 samples, the loop ran at 1 Hz, the AIO 2 auto-detected on COM6, all five threads stayed alive, and Mission was reachable.

- 6V reference: LabVIEW 5.707 to 5.733 V, new system 5.716 V.
- `T_HVAC-S_M5_C7` reads about -40 degC (0 V) on both systems; the HVAC supply HMP155 T probe is disconnected. `RH_HVAC-S` reads about 81 % on both, so only the T side is off.
- House dP channels sit at the 0 V floor on both: -0.100 in WC in LabVIEW, -24.878 Pa in the new system. The house Setras are disconnected on purpose; the HVAC filter Setras are connected and reading.

The system was rolled back to LabVIEW by choice. That week's test differed from past tests, and the full move fits better in the lab-test lull.

### Timestamps are local and naive

The daemon writes local-time, timezone-naive timestamps. Every consumer (dashboard, weather page, Mission readers) must treat them that way. JS `toISOString()` returns UTC with a `Z`. Comparing tz-aware to tz-naive datetimes raises, and the endpoint returns a 500. The web layer sends local naive ISO and strips any tzinfo it receives.

### Architecture

Acquisition is split from everything that displays or serves, so a failing page never touches acquisition.

- **DAQ PC daemon** (headless, autostart): writes the local daily files first, mirrors them to Mission on its own thread, publishes the snapshot and heartbeat, runs alarms. It is the only writer of archival files, which removes the LabVIEW two-writer crash.
- **RDP status tool** (`status.py`): run on demand over Remote Desktop. It reads the heartbeat and snapshot only.
- **Web box** (not deployed): reads Mission only, never the DAQ PC. It serves the group-private page and the NIST-internal weather page. Indoor data is absent from the weather feed by construction, not filtered out.

### Machines and environments

- **Dev box, NISTTeleworkSys:** development and simulation testing, no cDAQ attached. Keep the repo off OneDrive; OneDrive locks caused a stale bytecode cache and a `.pytest_cache` WinError 5.
- **DAQ PC:** Windows 11, i5-1245U, 16 GB RAM, 500 GB disk, NI-DAQmx driver installed. Keep installs minimal. Do not put the repo, data, or log folders under OneDrive.
- **Environments:** `iaqmh_daq` from `environment.yaml` for the daemon and tests; `mh_daq_web` from `environment-web.yaml` for the web layer, which keeps web dependencies off the DAQ PC. The conda package is `nidaqmx-python`; the import is `import nidaqmx`. The bare `nidaqmx` conda package is dead.
- Splinterware System Scheduler runs the `.bat` autostart; Windows Task Scheduler is not available on the DAQ PC.

### NI MAX coefficients

The NI MAX task ran a 1000 Hz sample clock, 100 samples per channel, finite, for an effective 1 Hz output. Linear scales below map raw volts to the NI MAX unit. `daq_config.json` chains each to SI and logs raw volts separately.

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

Thermocouples are Type J with built-in CJC; the NI 9213 driver returns degC directly.

SI conversions: inch WC to Pa at 248.84 (60 degF basis); ACFM to m3/h at 1.699, so 0 to 10 V maps to 0 to about 3398 m3/h. Watts, percent RH, and degC are already SI.

### Decisions locked

- Output is SI, with the unit in each column header. Raw volts and SI go to two indoor files; outdoor is one file, since the AIO 2 already reports engineering units.
- The outdoor file has nine measurement columns: wind_speed, wind_direction, air_temp, relative_humidity, barometric_pressure, rain, solar_radiation, battery_voltage, compass_heading. `config` and the checksum are metadata and are not logged.
- Rain and solar are flagged `present=false` until external sensors are added.
- Wind direction is referenced to magnetic north. True north needs the MD command at the sensor.
- The parser handles a variable field count, because BV and CV appear only when enabled at the sensor.
- The local write comes first, then the Mission mirror. A Mission outage never blocks acquisition.
- Active alarm rule: garage temperature (`T_Gar_M5_C4`) above 28 degC for 60 s. Blower thermocouple and other thresholds come later.
