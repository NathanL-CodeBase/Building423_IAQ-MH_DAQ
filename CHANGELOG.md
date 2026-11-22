# Changelog

## 2.0.0 (2026-11-22)

Folds the MH DAQ rebuild (`NathanL-CodeBase/NIST_mh-daq-rebuild`, 39 commits from 2026-09-25 to 2026-11-20) into this repository with its commit history. The rebuilt daemon has been the system of record since 2026-10-07 12:11:23 local time, when it replaced the LabVIEW VIs.

Added:

- Acquisition daemon (`run_daq.py`, `src/mh_daq/`): NI cDAQ-9178 and Met One AIO 2 on independent threads, 1 kHz samples averaged into 1 s records, NI MAX scales chained to SI, daily raw, SI, outdoor, and metadata files, and a mirror to Mission.
- Alarm engine with standing and temporary rules, deadband and clear dwell, live reload of rules and `channel_status`, and a background email queue.
- FastAPI dashboard and weather page (`web/`), with a stale-heartbeat email watchdog for mission mode.
- `status.py`, `compare_cutover.py`, the pytest suite (`tests/`), `config/daq_config.json`, and `config/daq_local.template.json`.
- `.gitattributes` for line endings and `CHANGELOG.md`.

Changed:

- README, `environment.yaml`, and `CITATION.cff` describe the daemon. `CITATION.md` from the rebuild is removed; `CITATION.cff` keeps DOI 10.18434/mds2-4154.
- The rebuild's `doc/` folder moved to `docs/`.
- `start_mh_daq.bat` finds conda and the repository without fixed paths.

Removed (available at tag `v1.0.0`):

- File backup scripts: `mh_daq_file_backup.py`, `wui_smoke_file_backup.py`, and `completed_campaigns/epa_shower_file_backup.py`.
- Ecobee scripts: `ecobee_thermostat_backup.py` and `ecobee_token_setup.py`.
- `scripts/` (weather station generator and its launchers), `data_config.template.json`, and the v1 `CONFIGURATION`, `INSTALLATION`, and `TROUBLESHOOTING` docs.

## 1.0 (2026-05-01)

File backup from the DAQ PC to Mission for the indoor DAQ and weather station files, a continuous weather station file generator, and an Ecobee thermostat download (never operational). Tag `v1.0.0` marks the last v1 commit, `eaa827f`.
