# MH DAQ

Data acquisition, logging, alarms, and live web display for the NIST Building 423 IAQ Manufactured House. This system reads a National Instruments cDAQ-9178 chassis (indoor temperature, relative humidity, differential pressure, HVAC airflow and power, blower-motor thermocouples) and a Met One AIO 2 sonic weather sensor, scales readings to SI units, writes daily data files, mirrors them to network storage, raises email alarms, and serves a live dashboard and a weather download page.

It replaces three earlier pieces: a LabVIEW cDAQ acquisition VI, a LabVIEW AIO 2 VI, and a temporary Python weather-logging script.

## Status

The acquisition daemon and the web layer are complete and tested in simulation. The daemon has been validated against the prior LabVIEW system on real hardware, reading the same channels to the same values within sensor accuracy. As of this writing the daemon is not yet the system of record; the switch from LabVIEW is planned for a period when the house is not in an active measurement campaign. See `doc/mh-daq-plan.md` for the full plan and current state.

## Repository contents

- `src/mh_daq/` reusable modules: config loading and validation, voltage-to-SI scaling, the AIO 2 serial parser, the daily file writer, the acquisition daemon, the Mission mirror, the alarm engine, the threading supervisor, and the acquisition backends (`backends/`: shared interface, simulation, NI-DAQmx, and a simulated AIO 2 serial source).
- `config/` the committed channel map, scales, alarm rules, and dashboard card color ranges (`daq_config.json`) and a template for the machine-specific local config (`daq_local.template.json`).
- `web/` the FastAPI dashboard (`dashboard.py`), shared data access and downsampling (`data_access.py`), and front-end files (`static/`: the group page `index.html`/`index.js`, the weather page `weather.html`/`weather.js`, and vendored Plotly).
- `tests/` the pytest suite (config, scaling, parser, writer, daemon, mirror, alarms, supervisor).
- `run_daq.py` entry point for the acquisition daemon (`--sim` or `--hardware`).
- `status.py` a read-only status view for confirming a running daemon over Remote Desktop.
- `compare_cutover.py` a helper for comparing daemon output against reference values during the hardware switch.
- `start_mh_daq.bat` a launcher for autostart via Splinterware System Scheduler.
- `environment.yaml` the acquisition conda environment; `environment-web.yaml` the web environment.
- `doc/` the planning document.

## Data flow

The acquisition machine writes locally first, then mirrors to network storage. Everything downstream reads from network storage, never from the acquisition machine. The daemon acquires the cDAQ and the AIO 2 on independent threads, so a fault on one does not stop the other. It writes three daily files (raw volts, SI-scaled values, and outdoor weather), a per-day metadata sidecar describing every column, and a latest-values snapshot. A separate mirror thread copies completed and in-progress files to network storage and self-heals after any outage.

## Requirements

- Windows 11 on the acquisition machine. Python is managed with conda (conda-forge).
- The NI-DAQmx driver must be installed on the acquisition machine for hardware runs. The `nidaqmx` Python package imports without it, and the simulation backend runs without it, but real acquisition needs the driver.
- The web app can run on any machine that can read the network storage location. It has no hardware dependency.

## Installation

Acquisition environment:

```
conda env create -f environment.yaml
conda activate iaqmh_daq
```

Web environment (only needed where the dashboard runs):

```
conda env create -f environment-web.yaml
conda activate mh_daq_web
```

Then create the machine-specific config from the template and edit it:

```
Copy-Item config\daq_local.template.json daq_local.json
```

Edit `daq_local.json` to set `machine_name`, the local and network storage paths, the serial port (leave `AUTO` to auto-detect the AIO 2), the SMTP sender and recipients, and the retention window. This file is gitignored and must not be committed.

## Usage

Run the daemon with the simulation backend (no hardware, safe on any machine):

```
conda activate iaqmh_daq
python run_daq.py --sim
```

Run the daemon on real hardware (acquisition machine only, and only when no other program owns the cDAQ):

```
python run_daq.py --hardware
```

Check a running daemon's health, for example over Remote Desktop:

```
python status.py
python status.py --watch
```

Run the dashboard (from the repository root, so the package is importable):

```
conda activate mh_daq_web
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000` for the group dashboard and `http://127.0.0.1:8000/weather` for the weather page. By default the dashboard reads the local data directory from `daq_local.json`, which only holds live data on the DAQ PC itself. On any other machine, read the Mission copies instead:

```
$env:MH_DAQ_SOURCE = "mission"
python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
```

On Windows, `start_dashboard_mission.bat` does the same: it activates `mh_daq_web` from `%USERPROFILE%\miniforge3` (override with `MH_DAQ_CONDA_PATH`), sets `MH_DAQ_SOURCE`, and starts the server from the repository root.

Mission mode takes the daily files from `mission_data_dir/mh_daq` and the snapshot and heartbeat from `mission_snapshot_dir`, both set in `daq_local.json`. Trends for the current day lag by up to `mirror.inprogress_interval_s` (300 s), and the health indicator allows for the 60 s snapshot mirror.

Run the tests:

```
conda activate iaqmh_daq
pytest -v
```

## Configuration

Configuration is split into two files. `config/daq_config.json` is committed and shared across machines: it holds the channel map, the per-channel scales (with the NI MAX coefficients chained to SI), the acquisition timing, the alarm rules, and the mirror settings. `daq_local.json` is per-machine and gitignored: it holds file-system paths, the serial port, SMTP details, and the retention window. The loader validates cross-references at startup (every channel's scale exists, every alarm targets a real channel) and fails with a clear message if the local config is missing or still holds template placeholders.

Units follow SI in the output files, with the unit in each column name. Differential pressure is reported in Pa, airflow in m3/h, temperature in degC, relative humidity in percent, and power in W. Timestamps in the data files are local time.

## Contact

Nathan Lima, National Institute of Standards and Technology, Engineering Laboratory, Energy and Environment Division, Indoor Air Quality and Ventilation Group. Contact: nathan.lima@nist.gov.

## Citation

See `CITATION.md` for citation text.

## License

See `LICENSE.md`. NIST-developed software is provided as a public service and expressly provided "AS IS." This software is not intended for use in any situation where failure could cause risk of injury or damage to property.
