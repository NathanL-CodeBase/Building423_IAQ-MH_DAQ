#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Met One AIO 2 serial line parsing and checksum validation.

Purpose: Parse one AIO 2 output line into labeled fields and verify its
    checksum, per AIO 2-9800 Rev E. Battery voltage (BV) and compass heading
    (CV) appear in the string only when enabled at the sensor, so the field
    count varies. This parser maps by count rather than assuming a fixed width,
    and rejects lines whose checksum does not match.
Author: Nathan Lima
Created: 2026-09-25
Update log:
    2026-09-25: Initial version. Supports 8, 9, and 10 numeric-field layouts
        (BV and CV off, one on, both on) plus the trailing config token and
        checksum.
"""

# Field layouts keyed by the number of comma-separated tokens BEFORE the
# checksum token. The standard Met record is:
#   WS, WD, AT, RH, BP, RN, SR, [BV], [CV], CONFIG, *CHECKSUM
# CONFIG is a status token (for example "U0" or "M0"). BV and CV are optional.
_BASE_FIELDS = [
    "wind_speed",
    "wind_direction",
    "air_temp",
    "relative_humidity",
    "barometric_pressure",
    "rain",
    "solar_radiation",
]


class Aio2ParseError(Exception):
    """Raised when a line cannot be parsed or fails its checksum."""


def compute_checksum(message):
    """Return the AIO 2 checksum for the message body.

    Per the manual, the checksum is the decimal sum of all character codes from
    the start of the message through the character immediately preceding the
    asterisk.

    Parameters
    ----------
    message : str
        The full line including the trailing "*NNNNN" checksum token.

    Returns
    -------
    int
        Computed checksum over the body before the asterisk.

    Raises
    ------
    Aio2ParseError
        If no asterisk is present.
    """
    star = message.rfind("*")
    if star < 0:
        raise Aio2ParseError("No checksum delimiter '*' found in line.")
    body = message[:star]
    return sum(ord(c) for c in body)


def parse_line(raw_line):
    """Parse and checksum-validate one AIO 2 line.

    Parameters
    ----------
    raw_line : str
        One decoded line, with or without trailing CR/LF.

    Returns
    -------
    dict
        Field name to string value. Includes the numeric fields present, plus
        "config". Optional fields absent from the string are not included.

    Raises
    ------
    Aio2ParseError
        If the checksum is missing, malformed, or does not match, or if the
        field count is not a recognized layout.
    """
    line = raw_line.strip()
    if not line:
        raise Aio2ParseError("Empty line.")

    star = line.rfind("*")
    if star < 0:
        raise Aio2ParseError("No checksum delimiter '*' found.")

    checksum_token = line[star + 1 :].strip()
    if not checksum_token.isdigit():
        raise Aio2ParseError(f"Checksum token not numeric: '{checksum_token}'.")
    stated = int(checksum_token)
    computed = compute_checksum(line)
    if stated != computed:
        raise Aio2ParseError(f"Checksum mismatch: stated {stated}, computed {computed}.")

    # Tokens before the checksum. The last is CONFIG; those before it are the
    # numeric measurements plus optional BV and CV.
    body = line[:star].rstrip(",").strip()
    tokens = [t.strip() for t in body.split(",")]
    if len(tokens) < len(_BASE_FIELDS) + 1:
        raise Aio2ParseError(
            f"Too few fields: got {len(tokens)}, need at least "
            f"{len(_BASE_FIELDS) + 1} (base plus config)."
        )

    config_token = tokens[-1]
    numeric = tokens[:-1]

    n_optional = len(numeric) - len(_BASE_FIELDS)
    if n_optional == 0:
        names = list(_BASE_FIELDS)
    elif n_optional == 1:
        # One optional field present. Per the manual, BV precedes CV, and CV is
        # only present with BV, so a single optional field is battery voltage.
        names = _BASE_FIELDS + ["battery_voltage"]
    elif n_optional == 2:
        names = _BASE_FIELDS + ["battery_voltage", "compass_heading"]
    else:
        raise Aio2ParseError(f"Unrecognized field count: {len(numeric)} numeric fields.")

    fields = dict(zip(names, numeric))
    fields["config"] = config_token
    return fields
