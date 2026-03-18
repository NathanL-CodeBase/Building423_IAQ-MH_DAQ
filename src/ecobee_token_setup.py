#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ecobee4 OAuth2 Token Setup
===========================

One-time interactive script to authorize the Ecobee data collection
application and obtain OAuth2 tokens for use by the automated backup script.

This script implements the Ecobee PIN-based authorization flow, which works
for any device type without requiring a browser redirect. The resulting token
file is read by ecobee_thermostat_backup.py on each scheduled run.

Methodology:
    1. Prompt user for their 32-character Ecobee API key
    2. Request a 4-character authorization PIN from the Ecobee API
    3. Prompt user to enter the PIN in the Ecobee web portal (My Apps)
    4. Exchange the authorized PIN code for access and refresh tokens
    5. Save all credentials to a JSON token file for the backup script

Token Lifecycle:
    - Access token:  Valid for ~2 hours (auto-refreshed by backup script)
    - Refresh token: Valid for ~1 year (re-run this script when it expires)

Output Files:
    - ecobee_tokens.json: API key, access token, refresh token, expiry timestamp

Applications:
    - One-time setup for automated Ecobee4 data collection
    - Re-authorization after refresh token expiry (~annually)

Author: Nathan Lima
Institution: NIST
Date: 2026
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# CONFIGURATION — Edit TOKEN_FILE_PATH for your system before running
# ---------------------------------------------------------------------------
# Default resolves to a "scripts" folder in the current user's home directory.
# Override by setting the ECOBEE_TOKEN_FILE environment variable, or by
# editing the line below to specify a different path.
TOKEN_FILE_PATH = Path(
    os.getenv("ECOBEE_TOKEN_FILE", Path.home() / "scripts" / "ecobee_tokens.json")
)

ECOBEE_AUTH_URL = "https://api.ecobee.com/authorize"
ECOBEE_TOKEN_URL = "https://api.ecobee.com/token"

# smartRead scope: read-only access to thermostat data (sufficient for backup)
ECOBEE_SCOPE = "smartRead"


# ============================================================================
# AUTHENTICATION FUNCTIONS
# ============================================================================

def request_pin(api_key):
    """Request an authorization PIN from the Ecobee API.

    Parameters:
        api_key (str): The 32-character Ecobee API key

    Returns:
        tuple: (pin, auth_code, expires_in_minutes) or (None, None, None) on failure
    """
    params = {
        "response_type": "ecobeePin",
        "client_id": api_key,
        "scope": ECOBEE_SCOPE,
    }
    try:
        response = requests.get(ECOBEE_AUTH_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        expires_minutes = data.get("expires_in", 900) // 60
        return data["ecobeePin"], data["code"], expires_minutes
    except requests.exceptions.HTTPError:
        print(f"ERROR: HTTP {response.status_code} requesting PIN.")
        if response.status_code == 400:
            error_msg = response.json().get("error_description", "")
            print(f"       {error_msg}")
            print("       Verify your API key is correct (32 characters).")
        return None, None, None
    except Exception as e:
        print(f"ERROR: Failed to request PIN: {str(e)[:100]}")
        return None, None, None


def exchange_pin_for_tokens(api_key, auth_code):
    """Exchange an authorized PIN auth code for access and refresh tokens.

    Parameters:
        api_key (str): The 32-character Ecobee API key
        auth_code (str): The authorization code returned with the PIN

    Returns:
        tuple: (access_token, refresh_token) or (None, None) on failure
    """
    params = {
        "grant_type": "ecobeePin",
        "code": auth_code,
        "client_id": api_key,
    }
    try:
        response = requests.post(ECOBEE_TOKEN_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["access_token"], data["refresh_token"]
    except requests.exceptions.HTTPError:
        error_data = response.json() if response.content else {}
        error_type = error_data.get("error", "")
        desc = error_data.get("error_description", "Unknown error")
        print(f"ERROR: Token exchange failed: {desc}")
        if "authorization_pending" in error_type:
            print("       The PIN was not yet authorized in the Ecobee portal.")
        elif "authorization_expired" in error_type:
            print("       The PIN has expired. Please run this script again.")
        elif "invalid_grant" in error_type:
            print("       The authorization code was already used or is invalid.")
        return None, None
    except Exception as e:
        print(f"ERROR: Failed to exchange PIN for tokens: {str(e)[:100]}")
        return None, None


def save_tokens(token_file, api_key, access_token, refresh_token):
    """Save API credentials and OAuth2 tokens to a JSON file.

    Parameters:
        token_file (Path): Destination path for the token JSON file
        api_key (str): The Ecobee API key
        access_token (str): OAuth2 access token (valid ~2 hours)
        refresh_token (str): OAuth2 refresh token (valid ~1 year)

    Returns:
        bool: True if saved successfully, False otherwise
    """
    expiry = datetime.now(timezone.utc) + timedelta(hours=2)
    token_data = {
        "api_key": api_key,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": expiry.isoformat(),
    }
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
        return True
    except Exception as e:
        print(f"ERROR: Failed to save tokens to {token_file}: {str(e)[:100]}")
        return False


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run the interactive Ecobee PIN authorization flow."""
    print("=" * 60)
    print("Ecobee4 Token Setup")
    print("=" * 60)
    print(f"\nToken file will be saved to:\n  {TOKEN_FILE_PATH}\n")

    # Get API key
    api_key = input("Enter your Ecobee API key (32 characters): ").strip()
    if len(api_key) != 32:
        print(f"WARNING: API key is {len(api_key)} characters (expected 32). Continuing.")

    # Request PIN from Ecobee
    print("\nRequesting authorization PIN from Ecobee...")
    pin, auth_code, expires_minutes = request_pin(api_key)
    if not pin:
        print("\nSetup failed. Verify your API key and network connection.")
        sys.exit(1)

    # Display PIN and instructions
    print()
    print("=" * 60)
    print(f"  Your authorization PIN:  {pin}")
    print("=" * 60)
    print(f"\nThis PIN expires in ~{expires_minutes} minutes.")
    print("\nTo authorize this application:")
    print("  1. Go to https://www.ecobee.com and log in to your account")
    print("  2. Click the menu icon (top-right hamburger menu)")
    print("  3. Select 'My Apps'")
    print("  4. Click 'Add Application'")
    print(f"  5. Enter the PIN: {pin}")
    print("  6. Click 'Validate', then 'Add Application'\n")

    input("Press Enter after authorizing in the Ecobee portal... ")

    # Exchange auth code for tokens
    print("\nExchanging authorization code for tokens...")
    access_token, refresh_token = exchange_pin_for_tokens(api_key, auth_code)
    if not access_token:
        print("\nToken exchange failed. Run this script again to get a new PIN.")
        sys.exit(1)

    # Save tokens
    print(f"Saving tokens to: {TOKEN_FILE_PATH}")
    if save_tokens(TOKEN_FILE_PATH, api_key, access_token, refresh_token):
        print()
        print("=" * 60)
        print("Setup complete! Token file saved successfully.")
        print()
        print("Next steps:")
        print("  - Run ecobee_thermostat_backup.py to verify data collection")
        print("  - Add it to Task Scheduler (Windows) or cron (Linux) for daily runs")
        print()
        print("Note: Refresh tokens expire after ~1 year.")
        print("      Re-run this script if authentication errors occur.")
        print("=" * 60)
    else:
        print("Failed to save token file. Check the path and permissions.")
        sys.exit(1)


if __name__ == "__main__":
    main()
