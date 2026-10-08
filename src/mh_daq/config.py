#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration loader and validation for the MH DAQ system.

Purpose: Load the committed channel map and scales (daq_config.json) and the
    machine-specific local config (daq_local.json), validate cross-references,
    and expose typed access for the rest of the system.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Split committed and local config, dataclass
        parse, and validation of scale and alarm references.
    2026-10-02: Remove unused local_machine_name helper. Note that
        retention_days is parsed but not yet enforced.
    2026-10-02: Honor MH_DAQ_CONFIG_DIR, so tests use a temporary config.
    2026-10-02: Parse and validate display_ranges (dashboard card colors).
    2026-10-02: Read config files as utf-8-sig so a byte-order mark from a
        Windows editor does not stop the daemon at startup.
    2026-10-08: Flag the SMTP host and port placeholders from the generic
        template with a clear message instead of an int() error.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ConfigError(Exception):
    """Raised when config files are missing, malformed, or inconsistent."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScaleDef:
    """Linear scale from raw volts to a nominal unit, then to SI.

    SI value is computed as (slope * volts + intercept) * si_factor + si_offset.
    Splitting the nominal scale from the SI factor keeps the NI MAX coefficients
    verifiable against the original export while still emitting SI.
    """

    name: str
    slope: float
    intercept: float
    nominal_unit: str
    si_unit: str
    si_factor: float
    si_offset: float
    description: str = ""


@dataclass(frozen=True)
class VoltageChannel:
    """Analog voltage channel scaled in software."""

    name: str
    physical_channel: str
    scale: str
    type: str = "voltage"


@dataclass(frozen=True)
class ThermocoupleChannel:
    """Thermocouple channel read as temperature by the NI 9213 driver.

    The driver applies cold-junction compensation and returns degC directly, so
    there is no voltage scale to apply here.
    """

    name: str
    physical_channel: str
    thermocouple_type: str
    cjc_source: str
    si_unit: str
    t_min: float
    t_max: float
    type: str = "thermocouple"


@dataclass(frozen=True)
class Aio2OutputColumn:
    field: str
    header: str
    si_unit: str


@dataclass
class Aio2Config:
    baud_rate: int
    bytesize: int
    parity: str
    stopbits: int
    field_names: list
    output_columns: list
    description: str = ""


@dataclass(frozen=True)
class AlarmRule:
    channel: str
    description: str
    dwell_s: float
    unit: str
    high: Optional[float] = None
    low: Optional[float] = None
    email_to: Optional[list] = None


@dataclass(frozen=True)
class DisplayRange:
    """Normal band for dashboard card colors. Display only, not an alarm.

    A value below low shows blue, above high shows red. Either limit may be
    None to leave that side uncolored.
    """

    name: str
    unit: str
    channels: tuple
    low: Optional[float] = None
    high: Optional[float] = None


@dataclass
class QualityConfig:
    dropout_s: float
    stale_s: float
    frozen_count: int


@dataclass
class AcquisitionConfig:
    oversample_rate_hz: int
    samples_per_record: int
    record_rate_hz: int


@dataclass
class MirrorConfig:
    snapshot_interval_s: int
    inprogress_interval_s: int
    retry_interval_s: int
    mission_subdir: str


@dataclass
class LocalConfig:
    machine_name: str
    local_data_dir: Path
    mission_data_dir: Path
    mission_snapshot_dir: Path
    com_port: str
    auto_detect_baud: int
    smtp_host: str
    smtp_port: int
    smtp_from: str
    smtp_to: list
    # Parsed but not enforced yet: nothing deletes old local files. Enforcing
    # it is an open decision in doc/mh-daq-plan.md.
    retention_days: int
    file_naming: dict


@dataclass
class SystemConfig:
    """Merged view of committed and local config."""

    config_version: str
    acquisition: AcquisitionConfig
    scales: dict  # name -> ScaleDef
    chassis_name: str
    voltage_terminal_config: str
    voltage_range: dict
    channels: list  # VoltageChannel or ThermocoupleChannel, task order
    aio2: Aio2Config
    quality: QualityConfig
    alarm_email: dict
    alarm_rules: list
    mirror: MirrorConfig
    local: LocalConfig
    display_ranges: list = field(default_factory=list)  # DisplayRange

    def channel_names(self):
        """Return channel names in acquisition (task) order."""
        return [c.name for c in self.channels]

    def voltage_channels(self):
        """Return only the software-scaled voltage channels."""
        return [c for c in self.channels if c.type == "voltage"]

    def thermocouple_channels(self):
        """Return only the thermocouple channels."""
        return [c for c in self.channels if c.type == "thermocouple"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
_COMMITTED_NAME = "daq_config.json"
_LOCAL_NAME = "daq_local.json"
_LOCAL_TEMPLATE_NAME = "daq_local.template.json"


def _find_file(name, search_dirs):
    """Return the first existing path named `name` across search_dirs."""
    for d in search_dirs:
        candidate = Path(d) / name
        if candidate.exists():
            return candidate
    return None


def _default_search_dirs(config_dir):
    """Directories to search for config, in priority order.

    An explicit config_dir wins, then the MH_DAQ_CONFIG_DIR environment
    variable (the test suite sets it to a temporary config). Otherwise search
    the current working directory, then a `config/` folder beside it, then the
    packaged repo `config/` folder two levels up from this module.
    """
    if config_dir is not None:
        return [Path(config_dir)]
    override = os.environ.get("MH_DAQ_CONFIG_DIR")
    if override:
        return [Path(override)]
    here = Path(__file__).resolve()
    repo_config = here.parent.parent.parent / "config"
    return [Path.cwd(), Path.cwd() / "config", repo_config]


def _load_json(path):
    # utf-8-sig accepts files with or without a byte-order mark. Windows
    # PowerShell 5.1 (Out-File, Set-Content -Encoding utf8) and older Notepad
    # write one, and plain utf-8 decoding makes json.load reject the file.
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from e


def load_config(config_dir=None):
    """Load and validate the merged system config.

    Parameters
    ----------
    config_dir : str or Path, optional
        Directory holding both config files. If omitted, standard locations
        are searched (cwd, cwd/config, repo config).

    Returns
    -------
    SystemConfig

    Raises
    ------
    ConfigError
        If either file is missing or the config fails validation. The local
        file message points at the template so a new machine can be set up.
    """
    search_dirs = _default_search_dirs(config_dir)

    committed_path = _find_file(_COMMITTED_NAME, search_dirs)
    if committed_path is None:
        raise ConfigError(
            f"Committed config '{_COMMITTED_NAME}' not found in {[str(d) for d in search_dirs]}."
        )

    local_path = _find_file(_LOCAL_NAME, search_dirs)
    if local_path is None:
        raise ConfigError(
            f"Local config '{_LOCAL_NAME}' not found in "
            f"{[str(d) for d in search_dirs]}. Copy '{_LOCAL_TEMPLATE_NAME}' "
            f"to '{_LOCAL_NAME}' and fill in machine paths, COM port, and SMTP."
        )

    committed = _load_json(committed_path)
    local = _load_json(local_path)

    cfg = _parse(committed, local)
    _validate(cfg)
    return cfg


def _parse(committed, local):
    """Build a SystemConfig from the two raw JSON dicts."""
    scales = {}
    for name, s in committed["scales"].items():
        scales[name] = ScaleDef(
            name=name,
            slope=float(s["slope"]),
            intercept=float(s["intercept"]),
            nominal_unit=s["nominal_unit"],
            si_unit=s["si_unit"],
            si_factor=float(s["si_factor"]),
            si_offset=float(s["si_offset"]),
            description=s.get("description", ""),
        )

    channels = []
    for c in committed["cdaq"]["channels"]:
        if c["type"] == "voltage":
            channels.append(
                VoltageChannel(
                    name=c["name"],
                    physical_channel=c["physical_channel"],
                    scale=c["scale"],
                )
            )
        elif c["type"] == "thermocouple":
            channels.append(
                ThermocoupleChannel(
                    name=c["name"],
                    physical_channel=c["physical_channel"],
                    thermocouple_type=c["thermocouple_type"],
                    cjc_source=c["cjc_source"],
                    si_unit=c["si_unit"],
                    t_min=float(c["t_min"]),
                    t_max=float(c["t_max"]),
                )
            )
        else:
            raise ConfigError(
                f"Channel '{c.get('name', '?')}' has unknown type "
                f"'{c.get('type')}'. Expected 'voltage' or 'thermocouple'."
            )

    a = committed["aio2"]
    aio2 = Aio2Config(
        baud_rate=int(a["baud_rate"]),
        bytesize=int(a["bytesize"]),
        parity=a["parity"],
        stopbits=int(a["stopbits"]),
        field_names=list(a["field_names"]),
        output_columns=[
            Aio2OutputColumn(field=col["field"], header=col["header"], si_unit=col["si_unit"])
            for col in a["output_columns"]
        ],
        description=a.get("description", ""),
    )

    q = committed["alarms"]["quality"]
    quality = QualityConfig(
        dropout_s=float(q["dropout_s"]),
        stale_s=float(q["stale_s"]),
        frozen_count=int(q["frozen_count"]),
    )

    rules = [
        AlarmRule(
            channel=r["channel"],
            description=r["description"],
            dwell_s=float(r["dwell_s"]),
            unit=r["unit"],
            high=r.get("high"),
            low=r.get("low"),
            email_to=r.get("email_to"),
        )
        for r in committed["alarms"]["rules"]
    ]

    def _opt_float(v):
        return None if v is None else float(v)

    display_ranges = [
        DisplayRange(
            name=r["name"],
            unit=r["unit"],
            channels=tuple(r["channels"]),
            low=_opt_float(r.get("low")),
            high=_opt_float(r.get("high")),
        )
        for r in committed.get("display_ranges", {}).get("rules", [])
    ]

    acq = committed["acquisition"]
    acquisition = AcquisitionConfig(
        oversample_rate_hz=int(acq["oversample_rate_hz"]),
        samples_per_record=int(acq["samples_per_record"]),
        record_rate_hz=int(acq["record_rate_hz"]),
    )

    m = committed.get("mirror", {})
    mirror = MirrorConfig(
        snapshot_interval_s=int(m.get("snapshot_interval_s", 60)),
        inprogress_interval_s=int(m.get("inprogress_interval_s", 0)),
        retry_interval_s=int(m.get("retry_interval_s", 30)),
        mission_subdir=m.get("mission_subdir", "mh_daq"),
    )

    lp = local["paths"]
    ls = local["serial"]
    lsm = local["smtp"]
    local_cfg = LocalConfig(
        machine_name=local["machine_name"],
        local_data_dir=Path(lp["local_data_dir"]),
        mission_data_dir=Path(lp["mission_data_dir"]),
        mission_snapshot_dir=Path(lp["mission_snapshot_dir"]),
        com_port=ls["com_port"],
        auto_detect_baud=int(ls["auto_detect_baud"]),
        smtp_host=lsm["host"],
        smtp_port=_parse_smtp_port(lsm["port"]),
        smtp_from=lsm["from_addr"],
        smtp_to=list(lsm["to_addrs"]),
        retention_days=int(local["retention_days"]),
        file_naming=dict(local["file_naming"]),
    )

    return SystemConfig(
        config_version=committed["config_version"],
        acquisition=acquisition,
        scales=scales,
        chassis_name=committed["cdaq"]["chassis_name"],
        voltage_terminal_config=committed["cdaq"]["voltage_terminal_config"],
        voltage_range=committed["cdaq"]["voltage_range"],
        channels=channels,
        aio2=aio2,
        quality=quality,
        alarm_email=committed["alarms"]["email"],
        alarm_rules=rules,
        mirror=mirror,
        local=local_cfg,
        display_ranges=display_ranges,
    )


def _parse_smtp_port(value):
    """Return the SMTP port as an int, or raise ConfigError for a placeholder.

    The template ships the port as REPLACE_WITH_SMTP_PORT, which int() cannot
    read; a plain ValueError would not say which setting to fix.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(
            "Config validation failed:\n  - smtp port in daq_local.json is not a "
            f"number ({value!r}); set it to the SMTP server port."
        ) from None


def _validate(cfg):
    """Check cross-references and flag placeholders that must be edited.

    Raises ConfigError on any structural problem so a misconfigured machine
    fails at startup, not mid-campaign.
    """
    problems = []

    names = cfg.channel_names()
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        problems.append(f"Duplicate channel names: {sorted(dupes)}.")

    phys = [c.physical_channel for c in cfg.channels]
    dupe_phys = {p for p in phys if phys.count(p) > 1}
    if dupe_phys:
        problems.append(f"Duplicate physical channels: {sorted(dupe_phys)}.")

    for c in cfg.voltage_channels():
        if c.scale not in cfg.scales:
            problems.append(f"Channel '{c.name}' references unknown scale '{c.scale}'.")

    valid_channels = set(names)
    for r in cfg.alarm_rules:
        if r.channel not in valid_channels:
            problems.append(f"Alarm rule '{r.description}' targets unknown channel '{r.channel}'.")
        if r.high is None and r.low is None:
            problems.append(f"Alarm rule '{r.description}' sets neither high nor low.")

    problems += _display_range_problems(cfg, valid_channels)

    if "REPLACE" in cfg.local.machine_name.upper():
        problems.append("machine_name in daq_local.json is still a placeholder.")
    if "REPLACE" in cfg.local.smtp_host.upper():
        problems.append("smtp host in daq_local.json is still a placeholder.")
    if "REPLACE" in cfg.local.smtp_from.upper():
        problems.append("smtp from_addr in daq_local.json is still a placeholder.")
    if any("REPLACE" in a.upper() for a in cfg.local.smtp_to):
        problems.append("smtp to_addrs in daq_local.json still has a placeholder.")

    if problems:
        raise ConfigError("Config validation failed:\n  - " + "\n  - ".join(problems))


def _display_range_problems(cfg, valid_channels):
    """Return validation messages for the display_ranges rules.

    Units are checked against each channel's SI unit so a range written in the
    wrong unit (for example degF limits on a degC channel) fails at startup.
    A channel may sit in only one rule, since a card shows one color.
    """
    # Imported here because scaling imports this module.
    from .scaling import si_unit_for_channel

    by_name = {c.name: c for c in cfg.channels}
    problems = []
    seen = {}
    for dr in cfg.display_ranges:
        if dr.low is None and dr.high is None:
            problems.append(f"Display range '{dr.name}' sets neither low nor high.")
        if dr.low is not None and dr.high is not None and dr.low >= dr.high:
            problems.append(f"Display range '{dr.name}' has low {dr.low} not below high {dr.high}.")
        for ch in dr.channels:
            if ch not in valid_channels:
                problems.append(f"Display range '{dr.name}' targets unknown channel '{ch}'.")
                continue
            unit = si_unit_for_channel(by_name[ch], cfg)
            if unit != dr.unit:
                problems.append(
                    f"Display range '{dr.name}' unit '{dr.unit}' does not match "
                    f"channel '{ch}' SI unit '{unit}'."
                )
            if ch in seen:
                problems.append(
                    f"Channel '{ch}' is in display ranges '{seen[ch]}' and '{dr.name}'."
                )
            seen[ch] = dr.name
    return problems
