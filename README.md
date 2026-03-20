# Building 423 IAQ Manufactured House (MH) DAQ — Automated Data Acquisition and Backup System

Automated backup and data collection scripts for the **NIST IAQ Manufactured House (MH) test facility** Data Acquisition (DAQ) system at Building 423. This repository contains Python scripts and deployment documentation for copying instrument data from the DAQ desktop computer to secure network storage and downloading thermostat data from the Ecobee4 smart thermostat.

---

## Quick Links

- **[Installation Guide](docs/INSTALLATION.md)** — Step-by-step instructions for initial setup
- **[Configuration Guide](docs/CONFIGURATION.md)** — Detailed configuration and Ecobee API setup
- **[Troubleshooting Guide](docs/TROUBLESHOOTING.md)** — Common issues and solutions
- **[License](LICENSE.md)** — Software licensing information

---

## Purpose and Scope

This repository supports the **continued development** of the MH DAQ backup infrastructure and **deployment/maintenance instructions** for technical personnel. All network paths are **managed in `data_config.json`** to prevent hardcoded paths from being visible in the GitHub repository.

The system:

1. **Backs up indoor DAQ data** from the Task Logger to the mission network drive (all data)
2. **Backs up outdoor weather station data** (AIO2) to the mission network drive (all data)  
3. **Backs up selected 2026 data** to the EPA Shower project share (temporary — will be deprecated)
4. **Downloads thermostat data** from the Ecobee4 thermostat via the Ecobee API (daily 5-minute interval runtime data)

**Note:** All three backup scripts reference the same configuration file (`data_config.json`). The EPA Shower backup is a separate project-specific target that will be removed after the EPA project concludes.

---

## What's in This Repository

```
Building423_IAQ-MH_DAQ/
├── docs/                              # Documentation (read these first!)
│   ├── INSTALLATION.md               # Quick start guide & deployment steps
│   ├── CONFIGURATION.md              # Detailed setup & Ecobee configuration
│   ├── TROUBLESHOOTING.md            # Common issues and solutions
│   └── instruments/                  # Instrument manuals, data sheets, and wiring docs
├── src/                               # Python source code (for development)
│   ├── mh_daq_file_backup.py         # Main DAQ data backup
│   ├── epa_shower_file_backup.py     # EPA Shower project backup
│   ├── ecobee_thermostat_backup.py   # Ecobee thermostat data download
│   └── ecobee_token_setup.py         # Ecobee API setup (one-time)
├── scripts/                           # Deployment scripts
│   └── run_backup.bat                # Batch file to run all backups in sequence
├── README.md                          # This file
├── LICENSE.md                         # Public domain license
├── CODEMETA.yaml                     # NIST metadata
└── CODEOWNERS                        # Repository maintainers
```

---

## System Status and Deployment Timeline

| Component | Status | Notes |
|-----------|--------|-------|
| **DAQ Backup** (Task Logger) | **Operational** | Running via `run_backup.bat`, deployed to DAQ computer |
| **Weather Station Backup** | **Operational** | Running via `run_backup.bat`, deployed to DAQ computer |
| **EPA Shower Backup** | **Operational** | Running via `run_backup.bat`, deployed to DAQ computer |
| **Ecobee Thermostat Data** | **Operational** | Running via `run_backup.bat`, deployed to DAQ computer |
| **Splinterware Scheduler** | **Planned** | Currently running backups manually; will automate with nightly scheduling |

---

## Getting Started

### For End Users (Operators and Technicians)

1. **Read first:** [Installation Guide](docs/INSTALLATION.md) for deployment steps
2. **Configure paths:** 
   - Copy `data_config.template.json` to `data_config.json`
   - Edit `data_config.json` to set your local and network paths (no hardcoded paths in scripts!)
   - See [Configuration Guide](docs/CONFIGURATION.md) for detailed instructions
3. **Deploy:** Clone the repository to the DAQ computer and run test backup  
4. **Monitor:** Check `batch_output.log` for successful backups
5. **Troubleshoot:** See [Troubleshooting Guide](docs/TROUBLESHOOTING.md) if issues arise

### For Developers

- Scripts are located in `src/` and are ready for continued development
- All scripts load configuration from `data_config.json` — no hardcoded paths!
- All backup functions are modular; new data sources can be added following the existing pattern
- Python 3.x with `pandas` library is required (see [Configuration Guide](docs/CONFIGURATION.md))

---

## Key Features

**Incremental Backups** — Only copies files that have changed (compares modification times)
**Safe Live-File Handling** — DAQ backup scripts skip today's data file by default (the DAQ system is still writing to it; copying an open file can produce a corrupt backup). Run with `--include-today` to override when needed.
**Ecobee Integration** — Automatic download of 5-minute interval thermostat data via Ecobee API (always fetches the previous completed day — no live-file risk)
**Error Logging** — Detailed logs for troubleshooting and audit trails
**Manual & Automated** — Run manually on-demand or schedule with Splinterware System Scheduler
**Smart Retry Logic** — Handles token refresh and network timeouts gracefully

---

## System Requirements

### Hardware & Network
- **Machine:** DAQ desktop computer (Building 423)
- **Network access:** NIST mission network
- **Storage:** Access to the mission network drive (path configured in `data_config.json` → `remote_destinations.mission.base_path`)
- **Additional access:** Elwood network drive (path configured in `data_config.json` → `remote_destinations.epa_shower.base_path`, for EPA Shower backup)

### Software
- **Python 3.x** (installed via Miniforge/Conda — run `conda info --base` to find your install path)
- **pandas library** (install once in base conda environment)
- **Windows command prompt/PowerShell** to run batch files

### For Ecobee Thermostat Data
- **Ecobee account** with thermostat (thermostat ID configured in `data_config.json`)
- **Ecobee API key** and authorized token file (see [Configuration Guide](docs/CONFIGURATION.md))
- **Internet access** from the DAQ computer to reach `api.ecobee.com`

---

## Data Organization

All backed-up data is organized by source and date:

```
<remote_destinations.mission.base_path>\        ← configured in data_config.json
    ├── indoor_daq\          ← Task Logger files
    ├── weather_station\     ← Outdoor weather station files
    └── thermostat\          ← Ecobee4 runtime CSVs
        └── YYYY\
            └── YYYY-MM-DD_thermostat.csv
```

EPA Shower data also copies to:
```
<remote_destinations.epa_shower.base_path>\     ← configured in data_config.json
    ├── indoor_daq\2026\
    └── weather_station\2026\
```

---

## Instrumentation

Documentation for all instruments and hardware is in [docs/instruments/](docs/instruments/).

### Active Instruments

| Instrument | Type | Measurement | Documentation |
|------------|------|-------------|---------------|
| **Met One AIO 2** | Outdoor weather station (10m MET Tower) | Wind speed/direction, temperature, humidity, barometric pressure | [Manual](docs/instruments/AIO-2-9800-Manual-Rev-G.pdf), [Supplement](docs/instruments/AIO2-1.pdf) |
| **Vaisala HMP155** | High-accuracy RH/T probe (×4) | Relative humidity, temperature | [User Guide](docs/instruments/Vaisala%20HMP155_User_Guide_in_English.pdf) |
| **Vaisala HMP45A** | RH/T probe (×8, legacy) | Relative humidity, temperature | [User Guide](docs/instruments/Vaisala%20HMP45AD-User-Guide-U274EN.pdf) |
| **ecobee4** | Smart Wi-Fi thermostat | Temperature, humidity, HVAC runtime | [Fact Sheet](docs/instruments/FactSheet-ecobee4.pdf) |
| **NI cDAQ-9178** | 8-slot USB DAQ chassis | — | [User Manual](docs/instruments/NI%20cDAQ-9171_9174_9178%20User%20Manual%20-%20National%20Instruments.pdf) |
| **NI 9201** | 8-ch analog input module (×5) | ±10V analog inputs | [Getting Started](docs/instruments/ni-9201_getting_started_2-1-2024.pdf) |
| **Setra Model 264** | Differential pressure transducer | Differential pressure (currently disconnected) | [Data Sheet](docs/instruments/Setra_Model_264_Data_Sheet.pdf) |

### Project-Specific Wiring Documents

| Document | Description |
|----------|-------------|
| [MH cDAQ channels MAP and wiring notes 123125.xlsx](docs/instruments/MH%20cDAQ%20channels%20MAP%20and%20wiring%20notes%20123125.xlsx) | cDAQ-9178 channel mapping and wiring notes (updated 12/31/25) |
| [MH weather station to DAQ connections sketch](docs/instruments/MH_weather_sta_to_DAQ_connections%20sketch.pdf) | Wiring diagram for the outdoor AIO2 weather station serial connection |

Full instrument specifications (ranges, accuracy, channel assignments, serial numbers) are documented in `data_config.json` under the `instruments` key.

---

## Contact & Support

**Maintained by:**  
Nathan Lima, NIST  
Email: [nathan.lima@nist.gov]

**Related NIST Resources:**
- [Buildings and Construction](https://www.nist.gov/buildings-construction)
- [Energy and Environment Division](https://www.nist.gov/el)

---

## License

This software is in the public domain and provided "as is" according to the [LICENSE.md](LICENSE.md) file.

---

## How to Cite

If you use this software in your research, please cite as:

```
Lima, Nathan M. (2026). Building 423 IAQ Manufactured House DAQ — Automated Data Acquisition and Backup System (Version 1.0) [Source code]. National Institute of Standards and Technology. https://github.com/usnistgov/Building423_IAQ-MH_DAQ
```

<!-- References -->

[18f-guide]: https://github.com/18F/open-source-guide/blob/18f-pages/pages/making-readmes-readable.md
[cornell-meta]: https://data.research.cornell.edu/content/readme
[gh-cdo]: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
[gh-mdn]: https://github.github.com/gfm/
[gh-nst]: https://github.com/usnistgov
[gh-odi]: https://odiwiki.nist.gov/ODI/GitHub.html
[gh-osr]: https://github.com/usnistgov/opensource-repo/
[gh-ost]: https://github.com/orgs/usnistgov/teams/opensource-team
[gh-rob]: https://odiwiki.nist.gov/pub/ODI/GitHub/GHROB.pdf
[gh-tpl]: https://github.com/usnistgov/carpentries-development/discussions/3
[li-bsd]: https://opensource.org/licenses/bsd-license
[li-gpl]: https://opensource.org/licenses/gpl-license
[li-mit]: https://opensource.org/licenses/mit-license
[nist-code]: https://code.nist.gov
[nist-disclaimer]: https://www.nist.gov/open/license
[nist-s-1801-02]: https://inet.nist.gov/adlp/directives/review-data-intended-publication
[nist-open]: https://www.nist.gov/open/license#software
[wk-rdm]: https://en.wikipedia.org/wiki/README
