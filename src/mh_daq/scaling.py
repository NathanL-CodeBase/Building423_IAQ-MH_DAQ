#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voltage-to-SI scaling for the MH DAQ system.

Purpose: Convert raw cDAQ voltage readings to SI engineering units using the
    linear scales in daq_config.json, chained to an SI factor and offset.
    Thermocouple channels are returned in degC by the NI 9213 driver, so they
    pass through unchanged. Both raw and SI values are retained upstream; this
    module computes only the SI side.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. scale_voltage, scale_nominal, scale_record,
        and header-unit helpers. SI chain is (slope, intercept) then
        (si_factor, si_offset).
"""

from .config import SystemConfig, ThermocoupleChannel, VoltageChannel


def scale_voltage(volts, scale):
    """Convert a raw voltage to SI using a linear scale chained to SI.

    The nominal step reproduces the NI MAX custom scale
    (nominal = slope * volts + intercept), which keeps the original NI MAX
    coefficients verifiable against the export. The SI step applies a unit
    conversion (si = nominal * si_factor + si_offset). Where the NI MAX unit is
    already SI (degC, percent, W), si_factor is 1.0 and si_offset is 0.0.

    Parameters
    ----------
    volts : float
        Raw voltage from a cDAQ analog input.
    scale : ScaleDef
        Scale definition with slope, intercept, si_factor, and si_offset.

    Returns
    -------
    float
        Value in the scale's SI unit.
    """
    nominal = scale.slope * volts + scale.intercept
    return nominal * scale.si_factor + scale.si_offset


def scale_nominal(volts, scale):
    """Return the NI MAX nominal value before SI conversion.

    Kept for verification and troubleshooting against the original NI MAX
    scaled units (for example inch WC or ACFM).

    Parameters
    ----------
    volts : float
    scale : ScaleDef

    Returns
    -------
    float
        Value in the scale's nominal unit.
    """
    return scale.slope * volts + scale.intercept


def scale_record(raw_values, config):
    """Convert one raw record to SI, channel by channel, in task order.

    Voltage channels are scaled with their named ScaleDef. Thermocouple
    channels arrive already in degC from the NI 9213 driver and pass through.
    A channel missing from raw_values raises KeyError, so a dropped channel is
    caught rather than written as a silent null.

    Parameters
    ----------
    raw_values : dict
        Channel name to raw reading. Voltage channels in volts, thermocouple
        channels in degC.
    config : SystemConfig

    Returns
    -------
    dict
        Channel name to SI value, in channel (task) order.
    """
    si = {}
    for ch in config.channels:
        raw = raw_values[ch.name]
        if isinstance(ch, VoltageChannel):
            si[ch.name] = scale_voltage(raw, config.scales[ch.scale])
        elif isinstance(ch, ThermocoupleChannel):
            si[ch.name] = raw  # already degC from the 9213 driver
        else:
            raise TypeError(f"Unhandled channel type for '{ch.name}'.")
    return si


def si_unit_for_channel(channel, config):
    """Return the SI unit string for one channel, for file headers.

    Parameters
    ----------
    channel : VoltageChannel or ThermocoupleChannel
    config : SystemConfig

    Returns
    -------
    str
    """
    if isinstance(channel, VoltageChannel):
        return config.scales[channel.scale].si_unit
    if isinstance(channel, ThermocoupleChannel):
        return channel.si_unit
    raise TypeError(f"Unhandled channel type for '{channel.name}'.")


def si_units_by_channel(config):
    """Return (channel_name, si_unit) pairs in task order for the SI header.

    Parameters
    ----------
    config : SystemConfig

    Returns
    -------
    list of tuple
    """
    return [(ch.name, si_unit_for_channel(ch, config)) for ch in config.channels]
