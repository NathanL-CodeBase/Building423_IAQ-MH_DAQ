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
    2026-10-01: Remove dead refreshPlot() and duplicate updatePickerCount,
        togglePicker, and windowMinutes definitions from the group page script.

Usage (from repo root, mh_daq_web env):
    # Local sim output (default): reads config.local.local_data_dir
    python -m uvicorn web.dashboard:app --host 127.0.0.1 --port 8000
    # then open http://127.0.0.1:8000

Data source override by environment variable:
    MH_DAQ_DATA_ROOT   Folder holding latest_snapshot.json and YYYY/ daily files.
                       Defaults to config.local.local_data_dir. Set to the
                       Mission raw_data/mh_daq path (plus a snapshot path) later.
"""

import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import Path as _Path

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.mh_daq.config import load_config
from web.data_access import downsample, numeric_columns, read_span

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


def _heartbeat_path():
    return _data_root() / "heartbeat.json"


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


@app.get("/api/heartbeat")
def api_heartbeat():
    """Return the daemon heartbeat with an age, or available=false if missing.

    The heartbeat holds system status only (thread liveness, alarm state,
    Mission reachability, record timestamps), no indoor measurement values. The
    group page reads it to drive the health indicator. age_s is seconds since
    written_at, so the page can flag a stale or dead daemon.
    """
    p = _heartbeat_path()
    try:
        with open(p, encoding="utf-8") as f:
            hb = json.load(f)
    except (OSError, json.JSONDecodeError):
        return JSONResponse({"available": False, "reason": f"No heartbeat at {p}"}, status_code=200)
    hb["available"] = True
    try:
        ts = datetime.fromisoformat(hb.get("written_at"))
        hb["age_s"] = (datetime.now() - ts).total_seconds()
    except (TypeError, ValueError):
        hb["age_s"] = None
    return JSONResponse(hb)


@app.get("/api/channels")
def api_channels():
    """Return all plottable indoor channels with their SI units and groups.

    Used to build the picker. Units come from the config scales; groups reuse
    the same categories as the card sections.
    """
    from src.mh_daq.scaling import si_units_by_channel

    units = dict(si_units_by_channel(_config))
    items = []
    for name, unit in units.items():
        items.append({"channel": name, "unit": unit})
    return JSONResponse({"channels": items})


@app.get("/api/trend")
def api_trend(start: str = "", end: str = "", channels: str = "", target: int = 1000):
    """Return SI series for channels over [start, end], downsampled to ~target.

    Parameters
    ----------
    start, end : str
        ISO datetimes. If empty, end defaults to now and start to 30 min before.
    channels : str
        Comma-separated plain channel names. Empty returns a small default set.
    target : int
        Approximate number of points to return per channel. The span is bucketed
        to hit this, so any window (a month or a minute) returns about this many.

    Returns
    -------
    JSON: 'time' (ISO), one array per channel, 'units' per channel, and the
    actual 'start'/'end' covered.
    """
    from src.mh_daq.scaling import si_units_by_channel

    unit_map = dict(si_units_by_channel(_config))

    now = datetime.now()

    def _parse_naive(text, default):
        """Parse an ISO string to a tz-naive local datetime, or return default.

        Accepts a trailing Z or offset and drops it, so comparisons against the
        tz-naive file timestamps never mix aware and naive datetimes.
        """
        if not text:
            return default
        t = text.replace("Z", "")
        try:
            d = datetime.fromisoformat(t)
        except ValueError:
            return default
        return d.replace(tzinfo=None)

    e = _parse_naive(end, now)
    s = _parse_naive(start, e - timedelta(minutes=30))

    default = ["T_Liv_M4_C7", "T_Gar_M5_C4", "RH_Liv_M3_C3", "6V_Test_M2_C7"]
    wanted = [c.strip() for c in channels.split(",") if c.strip()] or default

    df = read_span("indoor_si", s, e)
    if df.empty:
        return JSONResponse(
            {
                "available": False,
                "time": [],
                "units": {},
                "start": s.isoformat(),
                "end": e.isoformat(),
            }
        )

    df = downsample(df, target_points=max(50, min(target, 10000)))

    colmap = {}
    for want in wanted:
        match = [c for c in df.columns if c == want or c.startswith(want + "_")]
        if match:
            colmap[want] = match[0]

    out = {
        "available": True,
        "time": [t.isoformat() for t in df["dt"]],
        "units": {},
        "start": s.isoformat(),
        "end": e.isoformat(),
    }
    for want, col in colmap.items():
        series = df[col].round(4).where(pd.notna(df[col]), None)
        out[want] = series.tolist()
        out["units"][want] = unit_map.get(want, "")
    return JSONResponse(out)


@app.get("/api/weather/columns")
def api_weather_columns():
    """Return the outdoor data column names available for selection."""
    cols = [c.header for c in _config.aio2.output_columns]
    return JSONResponse({"columns": cols})


@app.get("/api/weather/series")
def api_weather_series(hours: int = 24):
    """Return recent outdoor data for plotting, downsampled for long spans."""
    now = datetime.now()
    start = now - timedelta(hours=hours)
    df = read_span("outdoor", start, now)
    if df.empty:
        return JSONResponse({"available": False, "time": []})
    df = downsample(df, target_points=3000)
    out = {"available": True, "time": [t.isoformat() for t in df["dt"]]}
    for c in numeric_columns(df):
        out[c] = df[c].round(3).where(pd.notna(df[c]), None).tolist()
    return JSONResponse(out)


@app.get("/api/weather/health")
def api_weather_health():
    """Return outdoor-feed freshness only: {available, age_s}.

    Drives the public weather page indicator. Reads the last 10 minutes of
    outdoor data and reports the age of the most recent record. Does not read
    the heartbeat or any indoor data, so no system internals reach the public
    page. age_s is null when no recent record exists.
    """
    now = datetime.now()
    df = read_span("outdoor", now - timedelta(minutes=10), now)
    if df.empty:
        return JSONResponse({"available": False, "age_s": None})
    last_dt = df["dt"].max()
    age_s = (now - last_dt).total_seconds()
    return JSONResponse({"available": True, "age_s": age_s})


@app.get("/api/weather/download")
def api_weather_download(start: str = "", end: str = "", vars: str = ""):
    """Return a CSV of outdoor data for a date range with selected variables.

    Parameters
    ----------
    start, end : str
        ISO dates (YYYY-MM-DD) or datetimes. Empty start/end defaults to today.
    vars : str
        Comma-separated column headers to include. Empty means all.

    Returns
    -------
    CSV with a single ISO 'datetime' column plus the selected data columns.
    """
    now = datetime.now()

    def _pn(text, default):
        if not text:
            return default
        try:
            return datetime.fromisoformat(text.replace("Z", "")).replace(tzinfo=None)
        except ValueError:
            return default

    s = _pn(start, datetime(now.year, now.month, now.day))
    e = _pn(end, now)
    # If end is a bare date, include the whole day.
    if end and len(end) <= 10:
        e = e + timedelta(days=1) - timedelta(seconds=1)

    df = read_span("outdoor", s, e)
    if df.empty:
        return PlainTextResponse("datetime\n", media_type="text/csv")

    all_cols = numeric_columns(df)
    wanted = [c.strip() for c in vars.split(",") if c.strip()] or all_cols
    keep = [c for c in wanted if c in df.columns]

    out = pd.DataFrame({"datetime": df["dt"].map(lambda t: t.isoformat())})
    for c in keep:
        out[c] = df[c]

    buf = io.StringIO()
    out.to_csv(buf, index=False)
    fname = f"MH_weather_{s:%Y%m%d}_{e:%Y%m%d}.csv"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/weather", response_class=HTMLResponse)
def weather_page():
    return HTMLResponse(_WEATHER_PAGE)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_PAGE)


_PAGE = r"""<!doctype html>
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
  #status.ok { color: #40b060; }
  main { padding: 16px 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 10px; margin-bottom: 20px; }
  .card { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 10px 12px; }
  .card .label { font-size: 11px; color: #9aa4b2; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 20px; font-weight: 600; margin-top: 4px; }
  .card .unit { font-size: 12px; color: #9aa4b2; margin-left: 3px; }
  #plot { background: #161a22; border: 1px solid #262b36; border-radius: 8px; padding: 8px; }
  .section-title { font-size: 13px; color: #9aa4b2; margin: 18px 0 8px; text-transform: uppercase; letter-spacing: .04em; }
  .controls { display:flex; align-items:center; gap:14px; margin-bottom:8px; }
  .controls select { background:#0f1115; color:#e6e6e6; border:1px solid #2a3140;
                     border-radius:5px; padding:5px 7px; }
  .controls button.secondary { background:#2a3140; color:#fff; border:none;
                     border-radius:6px; padding:6px 12px; cursor:pointer; font-size:13px; }
  #picker-count { font-size:12px; color:#9aa4b2; }
  .picker { background:#161a22; border:1px solid #262b36; border-radius:8px;
            padding:12px; margin-bottom:10px; max-height:260px; overflow:auto; }
  .picker .grp { font-size:11px; color:#9aa4b2; text-transform:uppercase;
                 letter-spacing:.04em; margin:8px 0 4px; }
  .picker label { display:inline-flex; align-items:center; gap:5px; margin:0 14px 6px 0; font-size:13px; }
  .plot-label { font-size:12px; color:#9aa4b2; margin:10px 0 4px; }
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
  <div class="section-title">Trends</div>
  <div class="controls">
    <label>Overview window
      <select id="window">
        <option value="180">3 hours</option>
        <option value="1440" selected>1 day</option>
        <option value="10080">1 week</option>
        <option value="43200">1 month</option>
      </select>
    </label>
    <button class="secondary" onclick="togglePicker()">Choose channels</button>
    <span id="picker-count"></span>
    <span id="detail-label" style="font-size:12px;color:#9aa4b2;"></span>
  </div>
  <div id="picker" class="picker" style="display:none;"></div>
  <div class="plot-label">Overview (drag to select a detail range)</div>
  <div id="overview" style="height:180px;"></div>
  <div class="plot-label">Detail</div>
  <div id="detail" style="height:420px;"></div>
</main>
<script>
const UNIT = {
  "6V_Test_M2_C7":"V","cfm_return_duct_M2_C1":"m3/h","watts_blowermtr_M2_C2":"W",
  "T_blowermtr1_M6_C0":"degC","T_blowermtr2_M6_C1":"degC"
};
// Group-page health thresholds, in seconds. Correct for near-real-time LOCAL
// reads. RAISE THESE at Mission deployment (reads lag the snapshot/mirror
// cadence, up to 60 s): green to about 90 s, down to about 300 s, or the light
// reads yellow then red constantly. See doc/mh-daq-plan.md.
const HEALTH_DELAYED_S = 5;
const HEALTH_DOWN_S = 60;
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

// Drive the header indicator from the heartbeat. Worst applicable condition
// wins: red beats yellow beats green. The heartbeat holds status only, so this
// reads no measurement values. #status is owned here, not by refresh().
async function refreshHealth(){
  const st = document.getElementById("status");
  try{
    const r = await fetch("/api/heartbeat");
    const h = await r.json();

    // Red: no heartbeat at all, or so old the daemon is presumed dead.
    if(!h.available){ st.textContent = "System down (no heartbeat)"; st.className="down"; return; }
    const age = h.age_s==null ? null : Math.round(h.age_s);
    if(h.age_s==null || h.age_s > HEALTH_DOWN_S){
      st.textContent = "System down" + (age==null ? "" : " ("+age+"s)");
      st.className="down"; return;
    }

    // Red: a worker thread has died, or acquisition dropped out.
    const threads = h.threads_alive || {};
    const dead = Object.keys(threads).find(k => !threads[k]);
    if(dead){ st.textContent = "Thread down: "+dead; st.className="down"; return; }
    const alarms = h.alarms || {};
    if(alarms.dropout){ st.textContent = "Acquisition dropout"; st.className="down"; return; }

    // Yellow: delayed, Mission unreachable, or an alarm/freeze is active.
    if(h.age_s > HEALTH_DELAYED_S){ st.textContent = "Delayed ("+age+"s)"; st.className="stale"; return; }
    if(h.mission_available===false){ st.textContent = "Mission unreachable"; st.className="stale"; return; }
    const tripped = alarms.tripped_rules || [];
    if(tripped.length){ st.textContent = "Alarm: "+tripped.join(", "); st.className="stale"; return; }
    const frozen = alarms.frozen_channels || [];
    if(frozen.length){ st.textContent = "Frozen: "+frozen.join(", "); st.className="stale"; return; }

    // Green.
    st.textContent = "System OK · updated "+age+"s ago";
    st.className="ok";
  }catch(e){ st.textContent = "System down (error)"; st.className="down"; }
}

let ALL_CHANNELS = [];
let SELECTED = new Set(["T_Liv_M4_C7","T_Gar_M5_C4","RH_Liv_M3_C3","6V_Test_M2_C7"]);
let DETAIL_RANGE = null;  // [startISO, endISO] or null = follow overview
const OVERVIEW_TARGET = 500;
const DETAIL_TARGET = 4000;

async function loadChannels(){
  try{
    const r = await fetch("/api/channels");
    const d = await r.json();
    ALL_CHANNELS = d.channels || [];
    buildPicker(); updatePickerCount();
  }catch(e){ console.error("channels error:", e); }
}

function buildPicker(){
  const byUnit = {};
  for(const c of ALL_CHANNELS){ (byUnit[c.unit] ||= []).push(c.channel); }
  let html = "";
  for(const unit of Object.keys(byUnit).sort()){
    html += `<div class="grp">${unit}</div>`;
    html += byUnit[unit].map(ch=>{
      const on = SELECTED.has(ch) ? "checked" : "";
      return `<label><input type="checkbox" value="${ch}" ${on} onchange="toggleChannel('${ch}',this.checked)"> ${ch}</label>`;
    }).join("");
  }
  document.getElementById("picker").innerHTML = html;
}

function toggleChannel(ch,on){
  if(on) SELECTED.add(ch); else SELECTED.delete(ch);
  updatePickerCount(); refreshOverview(); refreshDetail();
}
function updatePickerCount(){
  document.getElementById("picker-count").textContent = SELECTED.size + " channel(s) selected";
}
function togglePicker(){
  const p=document.getElementById("picker");
  p.style.display = p.style.display==="none" ? "block" : "none";
}
function windowMinutes(){ return parseInt(document.getElementById("window").value,10); }
// Local naive ISO (no Z, no offset), so it matches the local-time data files.
function toLocalISO(d){
  const p = n => String(n).padStart(2,"0");
  return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+"T"+
         p(d.getHours())+":"+p(d.getMinutes())+":"+p(d.getSeconds());
}
function isoNow(){ return toLocalISO(new Date()); }
function isoAgo(mins){ return toLocalISO(new Date(Date.now()-mins*60000)); }

// Build stacked-by-unit traces and layout for a given data payload + div.
function buildFigure(d){
  const units = d.units || {};
  const groups = {};
  for(const ch of Object.keys(d)){
    if(["available","time","units","start","end"].includes(ch)) continue;
    const u = units[ch] || "";
    (groups[u] ||= []).push(ch);
  }
  const unitList = Object.keys(groups).sort();
  const n = Math.max(1, unitList.length);
  const traces = [];
  const layout = {
    paper_bgcolor:"#161a22", plot_bgcolor:"#161a22", font:{color:"#c8ccd4"},
    margin:{l:56,r:16,t:6,b:30}, showlegend:true, legend:{orientation:"h"},
    grid:{rows:n, columns:1, pattern:"independent", roworder:"top to bottom"}
  };
  unitList.forEach((u,i)=>{
    const xa=i===0?"x":"x"+(i+1), ya=i===0?"y":"y"+(i+1);
    for(const ch of groups[u]){
      traces.push({x:d.time, y:d[ch], name:ch, mode:"lines", xaxis:xa, yaxis:ya});
    }
    const xkey=i===0?"xaxis":"xaxis"+(i+1), ykey=i===0?"yaxis":"yaxis"+(i+1);
    layout[ykey]={title:{text:u}, gridcolor:"#262b36"};
    layout[xkey]={gridcolor:"#262b36", matches:i===0?undefined:"x"};
  });
  return {traces, layout};
}

async function fetchTrend(startISO, endISO, target){
  const chans=[...SELECTED].join(",");
  const q=new URLSearchParams({start:startISO,end:endISO,channels:chans,target:String(target)});
  const r=await fetch("/api/trend?"+q.toString());
  return r.json();
}

async function refreshOverview(){
  try{
    if(SELECTED.size===0){ Plotly.purge("overview"); return; }
    const start=isoAgo(windowMinutes()), end=isoNow();
    const d=await fetchTrend(start,end,OVERVIEW_TARGET);
    if(!d.available||!d.time||d.time.length===0){ Plotly.purge("overview"); return; }
    const {traces,layout}=buildFigure(d);
    layout.dragmode="select";
    Plotly.react("overview",traces,layout,{displayModeBar:false,responsive:true});
    // Wire brush selection once per render.
    const ov=document.getElementById("overview");
    ov.on("plotly_selected", ev=>{
        if(!ev || !ev.range) return;
        // The selection range is keyed by whichever subplot x-axis was brushed
        // (x, x2, x3, ...). All x-axes are linked, so any of them gives the same
        // time span. Take the first x-axis key present.
        const xkey = Object.keys(ev.range).find(k => k === "x" || /^x\d+$/.test(k));
        if(!xkey) return;
        const r = ev.range[xkey];
        DETAIL_RANGE=[r[0], r[1]];
        document.getElementById("detail-label").textContent =
          "detail: "+String(r[0]).slice(0,19)+" to "+String(r[1]).slice(0,19);
        refreshDetail();
      });
  }catch(e){ console.error("overview error:", e); }
}

async function refreshDetail(){
  try{
    if(SELECTED.size===0){ Plotly.purge("detail"); return; }
    let start, end;
    if(DETAIL_RANGE){ start=DETAIL_RANGE[0]; end=DETAIL_RANGE[1]; }
    else { start=isoAgo(30); end=isoNow(); }  // default detail: last 30 min
    const d=await fetchTrend(start,end,DETAIL_TARGET);
    if(!d.available||!d.time||d.time.length===0){ Plotly.purge("detail"); return; }
    const {traces,layout}=buildFigure(d);
    Plotly.react("detail",traces,layout,{displayModeBar:true,responsive:true,
      modeBarButtonsToRemove:["lasso2d","select2d"]});
  }catch(e){ console.error("detail error:", e); }
}

refresh(); refreshHealth(); loadChannels(); refreshOverview(); refreshDetail();
document.getElementById("window").addEventListener("change", ()=>{
  DETAIL_RANGE=null;  // new overview window resets the detail to default
  document.getElementById("detail-label").textContent="";
  refreshOverview(); refreshDetail();
});
setInterval(refresh, 3000);
setInterval(refreshHealth, 3000);
// Overview and detail follow "now" when not brushed; refresh periodically.
setInterval(()=>{ refreshOverview(); if(!DETAIL_RANGE) refreshDetail(); }, 15000);
</script>
</body>
</html>
"""
_WEATHER_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MH Weather</title>
<script src="/static/plotly.min.js"></script>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
  header { padding: 12px 20px; background: #161a22; border-bottom: 1px solid #262b36; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  main { padding: 16px 20px; max-width: 1100px; }
  #plot { background:#161a22; border:1px solid #262b36; border-radius:8px; padding:8px; height:460px; }
  .panel { background:#161a22; border:1px solid #262b36; border-radius:8px; padding:14px; margin-top:16px; }
  .panel h2 { font-size:13px; margin:0 0 10px; color:#9aa4b2; text-transform:uppercase; letter-spacing:.04em; }
  label { font-size:13px; color:#c8ccd4; margin-right:12px; }
  input[type=date] { background:#0f1115; color:#e6e6e6; border:1px solid #2a3140; border-radius:5px; padding:5px 7px; }
  .vars { display:flex; flex-wrap:wrap; gap:6px 16px; margin:10px 0; }
  .vars label { display:flex; align-items:center; gap:5px; }
  button { background:#2b6cb0; color:#fff; border:none; border-radius:6px; padding:8px 16px;
           font-size:14px; cursor:pointer; margin-top:6px; }
  button.secondary { background:#2a3140; }
  .row { margin:8px 0; }
</style>
</head>
<body>
<header><h1>Manufactured House Weather (AIO 2)</h1></header>
<main>
  <div id="plot"></div>
  <div class="panel">
    <h2>Download data</h2>
    <div class="row">
      <label>Start <input type="date" id="start"></label>
      <label>End <input type="date" id="end"></label>
    </div>
    <div class="row">
      <label style="display:block;margin-bottom:6px;">Variables (default all)</label>
      <div class="vars" id="vars"></div>
    </div>
    <div class="row">
      <button onclick="downloadRange()">Download CSV</button>
      <button class="secondary" onclick="downloadToday()">Today only</button>
    </div>
  </div>
</main>
<script>
async function loadPlot(){
  try{
    const r = await fetch("/api/weather/series?hours=24");
    const d = await r.json();
    if(!d.available || !d.time || d.time.length===0){
      document.getElementById("plot").innerHTML =
        "<div style='padding:20px;color:#9aa4b2'>No weather data yet.</div>";
      return;
    }
    const traces=[];
    for(const k of Object.keys(d)){
      if(k==="available"||k==="time") continue;
      traces.push({x:d.time, y:d[k], mode:"lines", name:k});
    }
    Plotly.react("plot", traces, {
      margin:{l:52,r:16,t:10,b:40}, paper_bgcolor:"#161a22", plot_bgcolor:"#161a22",
      font:{color:"#c8ccd4"}, xaxis:{gridcolor:"#262b36",rangeslider:{visible:true}},
      yaxis:{gridcolor:"#262b36"}, legend:{orientation:"h"}
    }, {responsive:true});
  }catch(e){ console.error("weather plot error:", e); }
}

async function loadVars(){
  const r = await fetch("/api/weather/columns");
  const d = await r.json();
  const box = document.getElementById("vars");
  box.innerHTML = d.columns.map(c=>
    `<label><input type="checkbox" value="${c}" checked> ${c}</label>`).join("");
}

function selectedVars(){
  return [...document.querySelectorAll('#vars input:checked')].map(el=>el.value);
}

function isoDate(d){ return d.toISOString().slice(0,10); }

function doDownload(start, end){
  const vars = selectedVars().join(",");
  const q = new URLSearchParams({start, end, vars});
  window.location = "/api/weather/download?" + q.toString();
}

function downloadRange(){
  const s = document.getElementById("start").value;
  const e = document.getElementById("end").value;
  if(!s || !e){ alert("Pick a start and end date."); return; }
  doDownload(s, e);
}

function downloadToday(){
  const t = isoDate(new Date());
  doDownload(t, t);
}

// Default the date inputs to today.
const today = isoDate(new Date());
window.addEventListener("DOMContentLoaded", ()=>{
  document.getElementById("start").value = today;
  document.getElementById("end").value = today;
});

loadVars(); loadPlot();
setInterval(loadPlot, 30000);
</script>
</body>
</html>
"""
