# Completed Measurement Campaign Scripts

This directory holds backup scripts for measurement campaigns that have ended.
The scripts are retained for reference and reproducibility. They are no longer
run by `scripts/run_backup.bat` and are not part of the active nightly backup.

## Scripts

### `epa_shower_file_backup.py`

Targeted backup of a single year's indoor DAQ and outdoor weather station data
to the EPA Shower project share on the elwood network drive. It ran alongside
the main MH DAQ backup during the EPA Shower measurement campaign, copying only
the year set by `remote_destinations.epa_shower.archive_year` in
`data_config.json` (2026).

- Campaign ended: 2026-07-16
- Removed from the nightly `run_backup.bat` sequence on 2026-07-17
- The `epa_shower` block remains in `data_config.json` and
  `data_config.template.json` so the script still runs if invoked manually for
  a one-off re-copy.

To run it manually against the configured archive year:

```
python src/completed_campaigns/epa_shower_file_backup.py
```
