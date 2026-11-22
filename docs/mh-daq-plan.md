# MH DAQ Rebuild: Status and Remaining Work

Author: Nathan Lima (NIST)
Created: 2026-09-25
Last updated: 2026-11-22

The build history, resolved open items, and earlier status notes were removed on 2026-10-02 and 2026-11-10. They remain in git history before those dates. Dated events (restarts, outages, clock and sensor changes) are in `operations_log.md`.

## Purpose

One Python system replaces three pieces: the LabVIEW cDAQ acquisition VI, the broken LabVIEW AIO 2 VI, and the temporary `generate_weather_station_daq.py` bridge. It acquires from an NI cDAQ-9178 and a Met One AIO 2, scales to SI, logs raw and SI daily files, mirrors to Mission, sends alarm email, and feeds the group and weather webpages.

## Status (2026-11-10)

The daemon is the system of record. It replaced LabVIEW at 2026-10-07 12:11:23 and has run on the DAQ PC since, apart from the gaps in `operations_log.md`. It is still run as an extended test setup, started by hand, until the DAQ PC runs from a clone of `Building423_IAQ-MH_DAQ` (item 7). The old Mission backup script is retired. The dashboard runs on the DAQ PC in local mode and on appleseed in mission mode.

Added 2026-11-09 to 11-10:

- **Alarms:**
  - Temporary alarm rules with an active window.
  - Live reload of alarm rules, channel status, and per-rule recipients, with no restart.
  - Mission-outage email from the DAQ PC.
  - A background email queue, so SMTP never blocks acquisition.
- **Dashboard:**
  - Stale-heartbeat email watchdog and banner, from appleseed.
  - Offline tags that grey dashboard cards.
  - AIO 2 fields on the group trends.
  - A "Back to live" control.
- **Weather page:**
  - Rebuilt as a weather-station layout.
  - The download reaches the LabVIEW-era files back to 2025-02-24.
- **Clock:** NetTime on the DAQ PC.

## Remaining work

Ordered roughly by when each should happen.

1. **Ozone remediation alarm dates.** The rule on `dP_Fam-W-Hi_M1_C6` (below 15 Pa, 60 s dwell) is staged in `daq_config.json` for 2026-11-18 00:00 to 11-21 23:59. The ozone work is not scheduled yet. Before 11-18 00:00, either set the real window or remove the rule; `dP_Fam-W-Hi_M1_C6` read 0.58 Pa on 2026-11-10, so the staged window trips at its start. The DAQ PC's `daq_local.json` needs an `alarm_rule_email` entry for the rule's description to use the garage recipients.

2. **Mission access overnight (IT).** On 2026-11-08 to 11-09 the DAQ PC lost access to Mission from 23:36 to 08:33 and regained it after a remote login. The functional IAQ account shows no Kerberos tickets (`klist`: no credentials cache). The question is with IT. Until it is resolved, expect a `MISSION UNREACHABLE` email after 2 h of each outage. Raise `alarms.quality.mission_outage_s` (restart needed) if that is too frequent.

3. **Windows Time service (IT).** NetTime runs as a service, and W32Time is still running (start type Manual). Ask IT whether to disable W32Time so only one program sets the clock. Then read the hourly NetTime corrections to get the DAQ PC drift rate and compare it with the Ecobee offset.

4. **Recovery after a power loss.** The house lost power at 2026-10-17 06:54:18, and the daemon did not run again until 2026-10-26 12:50:55. That is 9 d 6 h with no data.
   - **BIOS:** set the power-restore setting (named "AC power recovery", "Restore on AC power loss", or similar) to power on, so the PC boots when power returns.
   - **Autostart:** the daemon is still started by hand as a test setup. Splinterware autostart through `start_mh_daq.bat` waits until the DAQ PC runs from the `Building423_IAQ-MH_DAQ` clone (item 7). Until then, a reboot leaves the daemon stopped.
   - **`.bat` paths:** fixed 2026-11-22. `start_mh_daq.bat` now finds the repository from its own folder and conda the same way `start_dashboard_mission.bat` does.
   - **Backstop:** the appleseed watchdog (added 2026-11-09) emails after 24 h without a heartbeat. It covers a stopped daemon as well as a dead PC.

5. **Local retention window.** `retention_days` is 90 in `daq_local.template.json`. The config loader reads it, but nothing deletes old local files. Enforcing it deletes local data, so decide the window and the rule (for example, delete only files already confirmed on Mission) before coding it.

6. **Access separation.** The group-private page shows all channels; the NIST-internal weather page shows AIO 2 only. Two routes on one app with different scopes is the simplest layout. Choose the auth mechanism once the web box is on a reachable network. The box runs Windows 11 now and may move to a Linux VM through IT; uvicorn runs the same on both.

7. **Fold into `Building423_IAQ-MH_DAQ`.** Merged with full history as v2.0.0 on 2026-11-22 in `NathanL-CodeBase/Building423_IAQ-MH_DAQ`. Remaining, in order: push to `usnistgov/Building423_IAQ-MH_DAQ` as NathanL-NIST over SSH; move the DAQ PC daemon to a clone of this repository (copy `daq_local.json` by hand, log the stop and start in `operations_log.md`); set up Splinterware autostart; then archive `NIST_mh-daq-rebuild` on GitHub.

8. **Smaller items:**
   - **Disconnected sensors.** Reattach or retire the sensors tagged offline in `channel_status`, and record the date in config and `operations_log.md`. These are seven slot 1 Setra 264 envelope channels and the Attic, Ba1, UR, and HVAC supply HMP T and RH probes.
   - **Card grouping.** HVAC supply T and RH sit in their own HVAC System section. Confirm, or fold them back into Temperature and Relative Humidity.
   - **Web endpoint tests.** `web/data_access.py` and the watchdog have tests. The FastAPI routes (snapshot present and absent, trend, weather series, CSV download, cache headers) do not.
   - **Email queue limit.** The DAQ PC queues up to 200 alarm emails. If SMTP is down long enough to fill it, new messages are dropped and logged.
   - **`status.py`.** It does not yet show the `mission_outage` alarm state.
   - **NI MAX watts scale.** Its description still carries a leftover self-note. Clean it when convenient.
   - **6V reference battery.** It reads about 5.71 V on both systems. Swap it; not urgent.
   - **AIO 2 supply.** Confirm it is 24 V. Battery voltage reads 23.2 V, inside the 8 to 36 VDC spec.

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

The system was rolled back to LabVIEW by choice that day. The permanent cutover followed on 2026-10-07 at 12:11:23.

Later checks changed two of these readings. The HVAC supply RH channel also reads 0 V as of 2026-11-10, so both HVAC supply probes are now tagged offline. `dP_Fam-W-Hi_M1_C6` has had a Setra 264 attached since about 2026-11-04 18:02:44.

### Timestamps are local and naive

The daemon writes local-time, timezone-naive timestamps. Every consumer (dashboard, weather page, Mission readers) must treat them that way. JS `toISOString()` returns UTC with a `Z`. Comparing tz-aware to tz-naive datetimes raises, and the endpoint returns a 500. The web layer sends local naive ISO and strips any tzinfo it receives.

### Architecture

Acquisition is split from everything that displays or serves, so a failing page never touches acquisition.

- **DAQ PC daemon** (headless, autostart): writes the local daily files first, mirrors them to Mission on its own thread, publishes the snapshot and heartbeat, runs alarms. It is the only writer of archival files, which removes the LabVIEW two-writer crash.
- **RDP status tool** (`status.py`): run on demand over Remote Desktop. It reads the heartbeat and snapshot only.
- **Dashboard in mission mode** (appleseed now; a web box later): reads Mission only, never the DAQ PC. It serves the group-private page and the NIST-internal weather page, and runs the stale-heartbeat email watchdog. Indoor data is absent from the weather feed by construction, not filtered out.

### Machines and environments

- **Dev box, NISTTeleworkSys:** development and simulation testing, no cDAQ attached. Keep the repo off OneDrive; OneDrive locks caused a stale bytecode cache and a `.pytest_cache` WinError 5.
- **DAQ PC:** Windows 11, i5-1245U, 16 GB RAM, 500 GB disk, NI-DAQmx driver installed. Keep installs minimal. Do not put the repo, data, or log folders under OneDrive.
- **Environments:** `iaqmh_daq` from `environment.yaml` for the daemon and tests; `mh_daq_web` from `environment-web.yaml` for the web layer, which keeps web dependencies off the DAQ PC. The conda package is `nidaqmx-python`; the import is `import nidaqmx`. The bare `nidaqmx` conda package is dead.
- **appleseed:** always-on desktop running `start_dashboard_mission.bat` (mission mode, stale-heartbeat watchdog on).
- Splinterware System Scheduler runs the `.bat` autostart; Windows Task Scheduler is not available on the DAQ PC.
- **Clock:** NetTime 3.1.4 runs as a service on the DAQ PC, syncing hourly from `time.nist.gov` and `time.windows.com` (installed 2026-11-09).

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
- **Standing alarm rules:** garage temperature (`T_Gar_M5_C4`) above 28 degC or below 15 degC for 60 s. Blower thermocouple and other thresholds come later.
- **Test-specific limits:** these go in as temporary rules with an active window, not as edits to the standing rules.
- **Offline tags:** a channel tagged offline is greyed on the dashboard only. It stays in the channel map, the files, the picker, and the alarms, so a reattached sensor shows its data before the tag is removed.
