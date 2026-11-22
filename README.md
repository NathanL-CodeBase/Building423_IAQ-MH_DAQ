# MH DAQ

Data acquisition, logging, alarms, and live web display for the NIST Building 423 IAQ Manufactured House. This system reads a National Instruments cDAQ-9178 chassis (indoor temperature, relative humidity, differential pressure, HVAC airflow and power, blower-motor thermocouples) and a Met One AIO 2 sonic weather sensor, scales readings to SI units, writes daily data files, mirrors them to network storage (Mission), sends alarm email, and serves a live dashboard and a weather page with data download.

It replaces three earlier pieces: a LabVIEW cDAQ acquisition VI, a LabVIEW AIO 2 VI, and a temporary Python weather-logging script.

## Status

The daemon has been the system of record since 2026-10-07 12:11:23 local time, when it replaced the LabVIEW VIs. It runs on the DAQ PC in the house as an extended test setup, started by hand. The dashboard runs on the DAQ PC (local mode) and on appleseed, an always-on desktop that reads the Mission copies. Restarts, outages, clock changes, and sensor changes are listed in `doc/operations_log.md`. Remaining work is in `doc/mh-daq-plan.md`.

This repository will be folded into `usnistgov/Building423_IAQ-MH_DAQ`.

## Repository contents

- `src/mh_daq/` reusable modules: config loading and validation (`config.py`), live reload of alarm rules and channel status (`config_watch.py`), voltage-to-SI scaling, the AIO 2 serial parser, the daily file writer, the acquisition daemon, the Mission mirror, the alarm engine and email senders (`alarms.py`), the threading supervisor, and the acquisition backends (`backends/`: shared interface, simulation, NI-DAQmx, and a simulated AIO 2 serial source).
- `config/` the committed channel map, scales, alarm rules, channel status, and dashboard settings (`daq_config.json`) and a template for the machine-specific local config (`daq_local.template.json`).
- `web/` the FastAPI dashboard (`dashboard.py`), shared data access and downsampling (`data_access.py`), the stale-heartbeat email watchdog (`watchdog.py`), and front-end files (`static/`: the group page `index.html`/`index.js`, the weather page `weather.html`/`weather.js`, and vendored Plotly).
- `tests/` the pytest suite: config, scaling, parser, writer, daemon, mirror, alarms (including temporary windows, live reload, and the email queue), supervisor, web data access, and the watchdog.
- `run_daq.py` entry point for the acquisition daemon (`--sim` or `--hardware`).
- `status.py` a read-only status view for confirming a running daemon over Remote Desktop.
- `compare_cutover.py` a helper for comparing daemon output against reference values, used at the hardware cutover.
- `start_mh_daq.bat` daemon launcher for Splinterware System Scheduler autostart. Not in use yet: the daemon is started by hand until the fold into `Building423_IAQ-MH_DAQ`.
- `start_dashboard_mission.bat` dashboard launcher for a read-only machine; reads Mission and opens the default browser.
- `environment.yaml` the acquisition conda environment (`iaqmh_daq`); `environment-web.yaml` the web environment (`mh_daq_web`).
- `doc/` the plan and remaining work (`mh-daq-plan.md`) and the operations log (`operations_log.md`).

## Data flow

The DAQ PC writes locally first, then mirrors to Mission. Everything downstream reads Mission, never the DAQ PC. The daemon acquires the cDAQ and the AIO 2 on independent threads, so a fault on one does not stop the other.

Each day it writes, under `YYYY/` in the local data folder:

| File | Contents |
|---|---|
| `{YYYYMMDD}-MH_Indoor_raw.txt` | Indoor channels in volts (thermocouples in degC) |
| `{YYYYMMDD}-MH_Indoor_SI.txt` | Indoor channels in SI, unit in each column name |
| `{YYYYMMDD}-MH_Outdoor.txt` | AIO 2 weather fields |
| `{YYYYMMDD}-MH_metadata.json` | Every column with its channel, scale, and units, plus `channel_status` (offline tags and sensor events) |

All three data files are tab-delimited with one header row, `Date` (`MM/DD/YYYY`) and `Time` (`HH:MM:SS`) columns in naive local time, and one record per second. The daemon also rewrites `latest_snapshot.json` (current values) every record and `heartbeat.json` (thread, alarm, and Mission status) every second.

The mirror thread copies completed days, the current day every 300 s, and the snapshot and heartbeat every 60 s to Mission, under `raw_data/mh_daq/YYYY/` and `live_snapshot/`. After an outage it copies the backlog on its own. The LabVIEW-era files stay in `raw_data/indoor_daq/` and `raw_data/weather_station/`.

`NIST_wui-smoke-iaq-mitigation/src/environmental_loader.py` reads both eras and joins them at the cutover. A change to a file name, a column name, a unit, or the timestamp format breaks that reader.

## Requirements

- Windows 11 on the DAQ PC. Python is managed with conda (conda-forge).
- The NI-DAQmx driver on the DAQ PC for hardware runs. The `nidaqmx` Python package imports without it, and the simulation backend runs without it, but real acquisition needs the driver.
- The dashboard runs on any machine that can read Mission. It has no hardware dependency.
- The DAQ PC clock is kept by NetTime (see Timekeeping).

## Installation

Acquisition environment:

```
conda env create -f environment.yaml
conda activate iaqmh_daq
```

Web environment (only where the dashboard runs):

```
conda env create -f environment-web.yaml
conda activate mh_daq_web
```

Then create the machine-specific config from the template and edit it:

```
Copy-Item config\daq_local.template.json daq_local.json
```

The loader looks for `daq_local.json` in the working folder, then in `config/`; both locations are gitignored.

Set `machine_name`, the local and Mission paths, the serial port (leave `AUTO` to find the AIO 2), the SMTP sender and recipients, and `alarm_rule_email` (recipients per alarm rule). This file is gitignored and must not be committed.

## Usage

Run the daemon with the simulation backend (no hardware, safe on any machine):

```
conda activate iaqmh_daq
python run_daq.py --sim
```

Run the daemon on real hardware (DAQ PC only, and only when no other program owns the cDAQ):

```
python run_daq.py --hardware
```

Record every restart, with the stop and start times from `mh_daq.log`, in `doc/operations_log.md`.

Check a running daemon, for example over Remote Desktop:

```
python status.py
python status.py --watch
```

Run the dashboard from the repository root:

```
conda activate mh_daq_web
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for the group dashboard and `http://127.0.0.1:8000/weather` for the weather page. By default the dashboard reads the local data folder from `daq_local.json`, which holds live data only on the DAQ PC. On any other machine, read the Mission copies:

```
$env:MH_DAQ_SOURCE = "mission"
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
```

`start_dashboard_mission.bat` does the same and opens the default browser after 8 s. It activates `mh_daq_web` from `%USERPROFILE%\miniforge3` or `%LOCALAPPDATA%\miniforge3` (override with `MH_DAQ_CONDA_PATH`).

In mission mode, trends for the current day lag by up to 300 s and the health indicator allows for the 60 s snapshot mirror.

Run the tests:

```
conda activate iaqmh_daq
pytest -v
```

## Dashboard

The group page (`/`) shows:

- Value cards for the AIO 2 and every indoor channel. Living-space T and RH cards turn blue below and red above `display_ranges`. Channels tagged offline in `channel_status` show greyed out.
- A header status: green when healthy; yellow when the heartbeat is delayed, Mission is unreachable, or an alarm or frozen channel is active; red when the heartbeat is missing or too old, a daemon thread has stopped, or acquisition dropped out.
- A red banner across the page when the heartbeat is older than `web.stale_banner_s` (1 h).
- Trend plots: an overview (3 h to 1 month) and a detail plot. Drag on the overview to inspect a range; "Back to live" returns the detail plot to the last 30 min. Any indoor channel or AIO 2 field can be plotted; the defaults are `T_Liv_M4_C7` and `RH_Liv_M3_C3`. Zoom and legend toggles survive the refresh.

The weather page (`/weather`) shows current temperature, RH, pressure with its 3 h change, wind speed with the 10 min gust, and wind direction, above stacked plots for 24 h, 3 d, or 7 d. Wind direction is averaged as a speed-weighted vector and is referenced to magnetic north. Rain and solar are hidden (no sensors).

The weather download covers 2025-02-24 on, up to `web.max_download_days` (31) per request. Before 2026-10-07 12:11:23 it reads the LabVIEW-era files in `weather_station/`, which hold wind speed, wind direction, temperature, RH, and pressure only. About 20 min around the cutover have no data. Rows keep file order and repeated timestamps, so the repeated hour at the fall daylight saving change is not lost.

Pages and static files are sent with `Cache-Control: no-cache`, so browsers load new page scripts after an update.

## Alarms and notification email

All email goes to the SMTP settings in `daq_local.json`. On the DAQ PC it is sent from a background queue, so a slow SMTP server never holds up acquisition.

| Email | Sent by | When | Recipients |
|---|---|---|---|
| `ALARM`, `ALARM ONGOING`, `CLEARED` | DAQ PC | A rule's condition holds for its dwell time; repeats every `alarms.email.min_interval_s` (3600 s) while tripped; clears per the rule's `deadband` and `clear_dwell_s` | `alarm_rule_email[description]`, else `to_addrs` |
| `ALARM WINDOW ENDED` | DAQ PC | A temporary rule is still tripped when its window ends | Same as the rule |
| `FROZEN` | DAQ PC | A channel repeats one value for `frozen_count` (60) records | `to_addrs` |
| `DROPOUT` | DAQ PC | No indoor record for `dropout_s` (30 s) | `to_addrs` |
| `MISSION UNREACHABLE`, `MISSION REACHABLE AGAIN` | DAQ PC | Mission unreachable for `mission_outage_s` (7200 s), then on recovery | `to_addrs` |
| `CONFIG RELOAD REJECTED` | DAQ PC | An edit to the reloadable config fails validation | `to_addrs` |
| `No DAQ update on Mission` | Dashboard in mission mode (appleseed) | Heartbeat on Mission older than `web.stale_alarm_s` (24 h); repeats every 24 h; one email on recovery | `to_addrs` of that machine |

The last row covers the case the DAQ PC cannot report: a power loss or a stopped daemon. It runs only in mission mode; set `MH_DAQ_WATCHDOG=1` or `0` to force it on or off.

### Adding or changing an alarm without a restart

The daemon re-reads `alarms.rules` and `channel_status` in `config/daq_config.json`, and `alarm_rule_email` in `daq_local.json`, every 30 s. To add a temporary rule, for example a pressure limit during a test:

1. Add the rule to `alarms.rules` in this repository. Give it a unique `description`, `"category": "temporary"`, and `active_from` and `active_until` in local time (`YYYY-MM-DD HH:MM:SS`). Outside that window the rule never trips.
2. Commit, push, and pull on the DAQ PC. Edit the repository, not the DAQ PC copy, so the next pull does not conflict.
3. To send the rule to specific people, add its description to `alarm_rule_email` in the DAQ PC's `daq_local.json`. Without an entry it goes to `to_addrs`.
4. Within 30 s `mh_daq.log` shows `Alarm rules reloaded:` with each rule and its window. A bad edit leaves the running rules in place and sends `CONFIG RELOAD REJECTED`.

Example:

```json
{
  "channel": "dP_Fam-W-Hi_M1_C6",
  "description": "Family room west dP low (ozone remediation)",
  "category": "temporary",
  "active_from": "2026-11-18 00:00:00",
  "active_until": "2026-11-21 23:59:59",
  "high": null,
  "low": 15.0,
  "dwell_s": 60,
  "deadband": 1.0,
  "clear_dwell_s": 300,
  "unit": "Pa"
}
```

The rule trips after the value stays below 15.0 Pa for 60 s. It clears only after the value stays at or above 16.0 Pa (`low + deadband`) for 300 s, so a reading that wanders across 15.0 Pa sends one `ALARM`, not an `ALARM` and `CLEARED` pair each minute. `deadband` is in the rule's unit and defaults to 0. `clear_dwell_s` defaults to `dwell_s`. Both reload live; `min_interval_s` needs a restart.

Changes to any other section (channel map, scales, timing, AIO 2, mirror, quality limits) need a daemon restart; the log says so when it sees one.

### Tagging a channel offline

Add the channel to `channel_status.offline` with a reason, and record connections and swaps in `channel_status.events`. The dashboard greys the card; logging, plotting, and alarms are unchanged, so a sensor reattached before the tag is removed still shows its data. The tag reloads on the DAQ PC and on each dashboard without a restart, and the daemon copies it into that day's metadata file. Also add a row to `doc/operations_log.md`.

## Configuration

`config/daq_config.json` is committed and shared:

| Section | Holds | Reloads live |
|---|---|---|
| `acquisition` | 1 kHz sampling, 100 samples per 1 s record | No |
| `scales`, `cdaq` | NI MAX coefficients chained to SI, and the channel map | No |
| `aio2` | Serial settings and output columns (`present: false` for rain and solar) | No |
| `mirror` | Snapshot, in-progress, and retry intervals; Mission subfolder | No |
| `alarms.email`, `alarms.quality` | Email throttle, dropout, frozen, and Mission-outage limits | No |
| `alarms.rules` | Threshold rules, standing or temporary | Yes |
| `channel_status` | Offline tags and sensor events | Yes |
| `legacy_outdoor` | LabVIEW-era weather folder, file name, cutover time, first date | No |
| `web` | Stale banner and watchdog ages, download cap | No |
| `display_ranges` | Living-space T and RH card colors | No |

`daq_local.json` is per machine and gitignored: paths, serial port, SMTP, `alarm_rule_email`, and `retention_days`. `retention_days` is read but not enforced; nothing deletes local files.

The loader validates cross-references at startup (every channel's scale exists, every rule and tag targets a real channel, rule descriptions are unique, windows are in order) and fails with a message that names the bad key.

Output is SI with the unit in each column name: differential pressure in Pa, airflow in m3/h, temperature in degC, relative humidity in percent, and power in W. Timestamps are local time.

## Timekeeping

The DAQ PC clock is set by NetTime 3.1.4, installed 2026-11-09 as a service that starts at boot. It syncs hourly from `time.nist.gov` and `time.windows.com` (SNTP, port 123). Each correction steps the clock; the hourly corrections are milliseconds, below the 1 s record spacing. The daemon paces its loop on the monotonic clock, so a correction moves timestamps but does not disturb the 1 s cycle.

## Contact

Nathan Lima, National Institute of Standards and Technology, Engineering Laboratory, Energy and Environment Division, Indoor Air Quality and Ventilation Group. Contact: nathan.lima@nist.gov.

## Citation

See `CITATION.md` for citation text.

## License

See `LICENSE.md`. NIST-developed software is provided as a public service and expressly provided "AS IS." This software is not intended for use in any situation where failure could cause risk of injury or damage to property.
