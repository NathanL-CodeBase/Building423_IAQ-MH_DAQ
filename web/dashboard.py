#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MH DAQ group live dashboard (FastAPI).

Purpose: Serve a group-private live view of the acquisition data. Reads the
    latest snapshot for current values and the recent SI daily file for trend
    plots. Reads from a configurable data root: the local --sim output now, the
    Mission share later (one path change). No hardware, no database, read-only.
Author: Nathan Lima
Created: 2026-09-28
Update log:
    2026-09-28: Initial version. Snapshot endpoint, trend endpoint, one HTML
        page that polls and plots.

Usage (from repo root, mh_daq_web env):
    # Local sim output (default): reads config.local.local_data_dir
    python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
    # then open http://127.0.0.1:8000

Data source override by environment variable:
    MH_DAQ_DATA_ROOT   Folder holding latest_snapshot.json and YYYY/ daily files.
                       Defaults to config.local.local_data_dir. Set to the
                       Mission raw_data/mh_daq path (plus a snapshot path) later.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import Path as _Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.mh_daq.config import load_config

app = FastAPI(title="MH DAQ Group Dashboard")

# Serve vendored assets (Plotly) locally so the page has no external CDN
# dependency, which also matters on an internal server with no outbound web.
_STATIC = _Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

_config = load_config()


def _data_root():
    """Folder holding latest_snapshot.json and the YYYY/ daily-file tree."""
    override = os.environ.get("MH_DAQ_DATA_ROOT")
    if override:
        return Path(override)
    return Path(_config.local.local_data_dir)


def _snapshot_path():
    return _data_root() / "latest_snapshot.json"


def _si_file_for(date):
    name = _config.local.file_naming["indoor_si"].format(date=date.strftime("%Y%m%d"))
    return _data_root() / date.strftime("%Y") / name


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/snapshot")
def api_snapshot():
    """Return the latest snapshot, or a status if none is present yet."""
    p = _snapshot_path()
    try:
        with open(p, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return JSONResponse({"available": False, "reason": f"No snapshot at {p}"}, status_code=200)
    snap["available"] = True
    # Age in seconds, so the page can flag stale data.
    try:
        ts = datetime.fromisoformat(snap.get("timestamp"))
        snap["age_s"] = (datetime.now() - ts).total_seconds()
    except (TypeError, ValueError):
        snap["age_s"] = None
    return JSONResponse(snap)


@app.get("/api/trend")
def api_trend(minutes: int = 30, channels: str = ""):
    """Return recent time series for selected SI channels.

    Parameters
    ----------
    minutes : int
        Lookback window.
    channels : str
        Comma-separated plain channel names (for example T_Liv_M4_C7). Empty
        returns a small default set.

    Returns
    -------
    JSON with 'time' (ISO strings) and one array per requested channel.
    """
    default = ["T_Liv_M4_C7", "T_Gar_M5_C4", "RH_Liv_M3_C3", "6V_Test_M2_C7"]
    wanted = [c.strip() for c in channels.split(",") if c.strip()] or default

    now = datetime.now()
    frames = []
    # Read today and, if the window crosses midnight, yesterday too.
    for day in {now.date(), (now - timedelta(minutes=minutes)).date()}:
        p = _si_file_for(datetime(day.year, day.month, day.day))
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, sep="\t")
        except (OSError, pd.errors.ParserError):
            continue
        frames.append(df)
    if not frames:
        return JSONResponse({"available": False, "time": []})

    df = pd.concat(frames, ignore_index=True)
    # SI columns are named channel_unit; map plain name -> actual column.
    colmap = {}
    for want in wanted:
        match = [c for c in df.columns if c == want or c.startswith(want + "_")]
        if match:
            colmap[want] = match[0]

    # Build a datetime from Date + Time. Try the writer's known format first,
    # then fall back to a flexible parse so a locale or format difference does
    # not silently drop every row.
    combined = df["Date"].astype(str) + " " + df["Time"].astype(str)
    dt = pd.to_datetime(combined, format="%m/%d/%Y %H:%M:%S", errors="coerce")
    if dt.isna().all():
        dt = pd.to_datetime(combined, errors="coerce")
    mask = dt >= (now - timedelta(minutes=minutes))
    dt = dt[mask]
    out = {"available": True, "time": [t.isoformat() for t in dt]}
    for want, col in colmap.items():
        out[want] = df.loc[mask, col].round(3).where(pd.notna(df.loc[mask, col]), None).tolist()
    return JSONResponse(out)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_PAGE)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MH DAQ Live</title>
<script src="/static/plotly.min.js"></script>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
  header { padding: 12px 20px; background: #161a22; border-bottom: 1px solid #262b36;
           display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  #status { font-size: 13px; color: #9aa4b2; }
  #status.stale { color: #e0a030; }
  #status.down { color: #e05050; }
  main { padding: 16px 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 10px; margin-bottom: 20px; }
  .card { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 10px 12px; }
  .card .label { font-size: 11px; color: #9aa4b2; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 20px; font-weight: 600; margin-top: 4px; }
  .card .unit { font-size: 12px; color: #9aa4b2; margin-left: 3px; }
  #plot { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 8px; }
  .section-title { font-size: 13px; color: #9aa4b2; margin: 18px 0 8px; text-transform: uppercase; letter-spacing: .04em; }
</style>
</head>
<body>
<header>
  <h1>MH DAQ Live</h1>
  <span id="status">connecting...</span>
</header>
<main>
  <div class="section-title">Weather (AIO 2)</div>
  <div class="grid" id="weather"></div>
  <div id="indoor-groups"></div>
  <div class="section-title">Trends (last 30 min)</div>
  <div id="plot" style="height:420px;"></div>
</main>
<script>
const UNIT = {
  "6V_Test_M2_C7":"V","cfm_return_duct_M2_C1":"m3/h","watts_blowermtr_M2_C2":"W",
  "T_blowermtr1_M6_C0":"degC","T_blowermtr2_M6_C1":"degC"
};
function unitFor(k){
  if (k in UNIT) return UNIT[k];
  if (k.startsWith("T_")) return "degC";
  if (k.startsWith("RH_")) return "%";
  if (k.startsWith("dP_")) return "Pa";
  return "";
}
function label(k){ return k; }

// Group indoor channels into sections by name pattern, in display order.
// A channel matches the first group whose test returns true.
const GROUPS = [
  ["Temperature", k => k.startsWith("T_") && !k.includes("blowermtr") && k!=="T_HVAC-S_M5_C7"],
  ["Relative Humidity", k => k.startsWith("RH_") && k!=="RH_HVAC-S_M4_C3"],
  ["Differential Pressure", k => k.startsWith("dP_") && !k.includes("HVACfilter")],
  ["HVAC System", k => k==="T_HVAC-S_M5_C7" || k==="RH_HVAC-S_M4_C3" ||
      k.includes("HVACfilter") || k==="cfm_return_duct_M2_C1" ||
      k==="watts_blowermtr_M2_C2" || k.includes("blowermtr")],
  ["Reference / Other", k => k==="6V_Test_M2_C7" || k==="BLANK_M2_C0"],
];

function groupFor(k){
  for (const [name, test] of GROUPS){ if (test(k)) return name; }
  return "Other";
}

async function refresh(){
  const st = document.getElementById("status");
  try {
    const r = await fetch("/api/snapshot");
    const s = await r.json();
    if (!s.available){ st.textContent = "no data: " + (s.reason||""); st.className="down"; return; }
    const age = s.age_s==null ? "?" : Math.round(s.age_s);
    if (s.age_s!=null && s.age_s > 10){ st.textContent = "STALE ("+age+"s old)"; st.className="stale"; }
    else { st.textContent = "live ("+age+"s)"; st.className=""; }

    // Weather cards
    const w = s.outdoor || {};
    const wmap = [["wind_speed","Wind","m/s"],["wind_direction","Dir","deg"],
      ["air_temp","Air T","degC"],["relative_humidity","RH","%"],
      ["barometric_pressure","Pressure","mb"],["battery_voltage","Battery","V"]];
    document.getElementById("weather").innerHTML = wmap.map(([k,lab,u])=>
      `<div class="card"><div class="label">${lab}</div>`+
      `<div class="value">${w[k]??"n/a"}<span class="unit">${u}</span></div></div>`).join("");

    // Indoor cards, grouped into labeled sections.
    const si = s.indoor_si || {};
    const buckets = {};
    for (const [name] of GROUPS) buckets[name] = [];
    buckets["Other"] = [];
    for (const k of Object.keys(si).sort()){ buckets[groupFor(k)].push(k); }

    let html = "";
    for (const name of [...GROUPS.map(g=>g[0]), "Other"]){
      const keys = buckets[name];
      if (!keys || keys.length===0) continue;
      html += `<div class="section-title">${name}</div><div class="grid">`;
      html += keys.map(k=>{
        const v = si[k]; const val = (typeof v==="number") ? v.toFixed(2) : v;
        return `<div class="card"><div class="label">${label(k)}</div>`+
          `<div class="value">${val}<span class="unit">${unitFor(k)}</span></div></div>`;
      }).join("");
      html += `</div>`;
    }
    document.getElementById("indoor-groups").innerHTML = html;
  } catch(e){ st.textContent = "error"; st.className="down"; }
}

async function refreshPlot(){
  try{
    const r = await fetch("/api/trend?minutes=30");
    const d = await r.json();
    if (!d.available || !d.time || d.time.length===0){ return; }
    const traces = [];
    for (const k of Object.keys(d)){
      if (k==="available"||k==="time") continue;
      traces.push({x:d.time, y:d[k], mode:"lines", name:k});
    }
    Plotly.react("plot", traces, {
      margin:{l:48,r:16,t:8,b:36}, paper_bgcolor:"#161a22", plot_bgcolor:"#161a22",
      font:{color:"#c8ccd4"}, xaxis:{gridcolor:"#262b36"}, yaxis:{gridcolor:"#262b36"},
      legend:{orientation:"h"}
    }, {displayModeBar:false, responsive:true});
  } catch(e){ console.error("plot error:", e); }
}

refresh(); refreshPlot();
setInterval(refresh, 3000);
setInterval(refreshPlot, 15000);
</script>
</body>
</html>
"""
