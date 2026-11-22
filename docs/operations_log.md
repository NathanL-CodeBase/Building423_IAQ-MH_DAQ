# MH DAQ operations log

Restarts, outages, clock changes, and sensor changes on the acquisition machine, in local time (America/New_York). Add a row for every daemon restart, with the stop and start times from `mh_daq.log`. Sensor connections and offline tags are also kept in `config/daq_config.json` under `channel_status`, which the daemon copies into each day's `{YYYYMMDD}-MH_metadata.json`.

| Date and time (local) | Event | Effect on the data |
|---|---|---|
| 2026-10-07 12:06:22 to 12:11:23 | Cutover from the LabVIEW VIs to this daemon. Last LabVIEW indoor record 12:06:22 (weather 12:06:25); first rebuilt record 12:11:23 (weather 12:11:35). | No data between those times. The rebuilt files have a second hole, 12:12:08 to 12:26:57 (weather to 12:27:10). |
| 2026-10-10 | Slot 1 (NI 9201) confirmed logged with no Setra 264 envelope sensors attached. | Slot 1 columns hold an open-input voltage, about -24.8 Pa after scaling. Not a pressure. |
| 2026-10-17 06:54:18 to 2026-10-26 12:50:55 | Power lost at the house. The DAQ PC stayed off until it was turned on and the daemon was started by hand. The dashboard heartbeat age rose the whole time, but nobody was notified. | No data for 9 d 5 h 56 min. The appleseed stale-heartbeat email (added 2026-11-09) now covers this case. |
| 2026-11-04 18:02:44 (approximate) | Setra 264 (+/-0.1 in WC) reattached on `dP_Fam-W-Hi_M1_C6`. Sign positive in the logged convention. | Column holds a pressure from this time on. |
| 2026-11-08 23:29:24 to 2026-11-09 08:33:47 | Mission share unreachable from the DAQ PC (`Access is denied` at 23:29:24, unavailable from 23:36:37). Returned after a remote login. | None. Files logged locally and copied to Mission at 08:33:47. Mission readers saw stale data for 9 h. Question sent to IT. |
| 2026-11-09 12:46:25 | NetTime 3.1.4.220 installed as a service (starts at boot). Initial correction +126 ms. | No repeated or skipped seconds between 12:40 and 13:05 in `20261109-MH_Indoor_SI.txt`. |
| 2026-11-09 12:55:58 | NetTime set to `time.nist.gov` and `time.windows.com` (SNTP, port 123), hourly updates, server mode off. Manual sync +11 ms. Stripchart at 13:00 showed +0.0012 to +0.0015 s against `time.nist.gov`. Windows Time service (W32Time) still running, start type Manual; question to IT pending. | Same check as above. |
| 2026-11-10 10:34:56 to 10:36:40 | Daemon restart to deploy temporary alarm windows, live reload of alarm rules and channel status, the Mission-outage email, the background email queue, and `channel_status` in the metadata sidecar. | No data for 1 min 44 s. |
| 2026-11-10 | HMP sensors confirmed unplugged: `T_Attic_M5_C5`, `RH_Attic_M4_C1`, `T_Ba1_M5_C2`, `RH_Ba1_M3_C6`, `T_UR_M5_C3`, `RH_UR_M3_C7`, `T_HVAC-S_M5_C7`, `RH_HVAC-S_M4_C3`. Tagged offline on the dashboard. | Columns hold the 0 V scaled value (about -40 degC and 0 %). Not measurements. Date unplugged not known. |
