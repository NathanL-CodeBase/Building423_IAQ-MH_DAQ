// MH weather page: current-condition tiles, stacked weather panels, and CSV download.

// Wong (2011) colorblind-safe colors, one per variable. Each variable has its
// own panel and axis title, so identity never rests on color alone.
const PANELS = [
  {field:"air_temp",            title:"Temperature (degC)", color:"#E69F00", name:"Temperature"},
  {field:"relative_humidity",   title:"RH (%)",             color:"#56B4E9", name:"Relative humidity"},
  {field:"barometric_pressure", title:"Pressure (hPa)",     color:"#009E73", name:"Pressure"},
  {field:"wind_speed",          title:"Wind (m/s)",         color:"#CC79A7", name:"Wind speed"},
  {field:"wind_direction",      title:"Direction (deg)",    color:"#F0E442", name:"Wind direction"},
];

let COLUMNS = [];       // [{header, field, unit, plot}] from /api/weather/columns
let MAX_DAYS = 31;

function hours(){ return parseInt(document.getElementById("hours").value, 10); }

function cardinal(deg){
  const names = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
  return names[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
}

// Index of the newest non-null value in arr, or -1.
function lastIndex(arr){
  if (!arr) return -1;
  for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return i;
  return -1;
}

function tile(label, value, unit, sub){
  return `<div class="tile"><div class="label">${label}</div>`+
    `<div class="value">${value}<span class="unit">${unit}</span></div>`+
    (sub ? `<div class="sub">${sub}</div>` : "")+`</div>`;
}

// Arrow pointing downwind (the direction the air moves toward).
function arrowSvg(fromDeg){
  const rot = (fromDeg + 180) % 360;
  return `<svg width="26" height="26" viewBox="-13 -13 26 26" aria-hidden="true">`+
    `<circle r="12" fill="none" stroke="#2a3140"/>`+
    `<g transform="rotate(${rot})"><path d="M0,-10 L5,4 L0,1 L-5,4 Z" fill="#e6e6e6"/></g></svg>`;
}

function renderTiles(d){
  const f = d.fields || {};
  const t = d.time.map(s => new Date(s).getTime());
  const val = (field, dp) => {
    const a = d[f[field]]; const i = lastIndex(a);
    return i < 0 ? null : {v: a[i], i, s: a[i].toFixed(dp)};
  };
  let html = "";

  const temp = val("air_temp", 1);
  html += tile("Air temperature", temp ? temp.s : "n/a", "degC");

  const rh = val("relative_humidity", 0);
  html += tile("Relative humidity", rh ? rh.s : "n/a", "%");

  const bp = val("barometric_pressure", 1);
  let bpSub = "";
  if (bp){
    // Change over the last 3 h, from the first point at or after now - 3 h.
    const target = t[bp.i] - 3*3600*1000;
    const a = d[f.barometric_pressure];
    const j = t.findIndex((x, k) => x >= target && a[k] != null);
    if (j >= 0 && j < bp.i && t[bp.i] - t[j] >= 2.5*3600*1000){
      const dp = bp.v - a[j];
      const word = Math.abs(dp) < 0.5 ? "steady" : (dp > 0 ? "rising" : "falling");
      bpSub = `${word}, ${dp >= 0 ? "+" : ""}${dp.toFixed(1)} hPa in 3 h`;
    }
  }
  html += tile("Pressure", bp ? bp.s : "n/a", "hPa", bpSub);

  const ws = val("wind_speed", 1);
  let wsSub = "";
  if (ws && d.gust){
    // Highest 1 s speed over the last 10 min of plotted intervals.
    const since = t[ws.i] - 10*60*1000;
    let g = null;
    for (let k = 0; k < t.length; k++) if (t[k] >= since && d.gust[k] != null) g = Math.max(g ?? -1, d.gust[k]);
    if (g != null) wsSub = `gust ${g.toFixed(1)} m/s (10 min)`;
  }
  html += tile("Wind speed", ws ? ws.s : "n/a", "m/s", wsSub);

  const wd = val("wind_direction", 0);
  html += wd
    ? tile("Wind from", `${arrowSvg(wd.v)}${cardinal(wd.v)}`, `${wd.s} deg`, "magnetic north")
    : tile("Wind from", "n/a", "", "");

  document.getElementById("tiles").innerHTML = html;
}

function renderPlot(d){
  const f = d.fields || {};
  const panels = PANELS.filter(p => f[p.field]);
  const n = panels.length;
  const traces = [];
  const layout = {
    margin:{l:60,r:16,t:10,b:36}, paper_bgcolor:"#161a22", plot_bgcolor:"#161a22",
    font:{color:"#c8ccd4"}, showlegend:true, legend:{orientation:"h", y:1.04},
    hovermode:"x unified",
    grid:{rows:n, columns:1, pattern:"coupled", roworder:"top to bottom"},
    xaxis:{gridcolor:"#262b36"},
    // Constant per window: legend toggles and zoom survive the 30 s refresh.
    uirevision:"weather-"+hours(),
  };
  panels.forEach((p, i) => {
    const ya = i === 0 ? "y" : "y"+(i+1);
    const ykey = i === 0 ? "yaxis" : "yaxis"+(i+1);
    layout[ykey] = {title:{text:p.title, font:{size:12}}, gridcolor:"#262b36"};
    if (p.field === "wind_direction"){
      // Points, not lines: a line from 350 to 10 deg would sweep the whole axis.
      traces.push({x:d.time, y:d[f[p.field]], name:p.name, uid:p.field, mode:"markers",
        xaxis:"x", yaxis:ya, marker:{color:p.color, size:4}});
      Object.assign(layout[ykey], {range:[0,360], tickvals:[0,90,180,270,360],
        ticktext:["N","E","S","W","N"]});
    } else {
      traces.push({x:d.time, y:d[f[p.field]], name:p.name, uid:p.field, mode:"lines",
        xaxis:"x", yaxis:ya, line:{color:p.color, width:2}});
    }
    if (p.field === "wind_speed" && d.gust){
      traces.push({x:d.time, y:d.gust, name:"Gust", uid:"gust", mode:"lines",
        xaxis:"x", yaxis:ya, line:{color:p.color, width:1, dash:"dot"}});
      layout[ykey].rangemode = "tozero";
    }
  });
  Plotly.react("plot", traces, layout, {responsive:true});
}

async function loadPlot(){
  try{
    const r = await fetch("/api/weather/series?hours="+hours());
    const d = await r.json();
    if(!d.available || !d.time || d.time.length===0){
      Plotly.purge("plot");
      document.getElementById("plot").innerHTML =
        "<div style='padding:20px;color:#9aa4b2'>No weather data in this window.</div>";
      document.getElementById("tiles").innerHTML = "";
      return;
    }
    renderTiles(d);
    renderPlot(d);
  }catch(e){ console.error("weather plot error:", e); }
}

async function loadHealth(){
  const el = document.getElementById("health");
  try{
    const r = await fetch("/api/weather/health");
    const h = await r.json();
    if (!h.available || h.age_s == null){ el.textContent = "No data in the last 10 min"; el.className = "stale"; return; }
    const a = Math.round(h.age_s);
    el.textContent = a < 120 ? `Updated ${a} s ago` : `Updated ${Math.round(a/60)} min ago`;
    el.className = a < 600 ? "ok" : "stale";
  }catch(e){ el.textContent = "Status unavailable"; el.className = "stale"; }
}

async function loadVars(){
  const r = await fetch("/api/weather/columns");
  const d = await r.json();
  COLUMNS = d.columns || [];
  MAX_DAYS = d.max_download_days || MAX_DAYS;
  document.getElementById("vars").innerHTML = COLUMNS.map(c=>
    `<label><input type="checkbox" value="${c.header}" checked> ${c.header}</label>`).join("");
  let note = `Up to ${MAX_DAYS} days per download.`;
  if (d.first_date){
    note = `Data from ${d.first_date}. ` + note;
    document.getElementById("start").min = d.first_date;
    document.getElementById("end").min = d.first_date;
  }
  if (d.cutover_local){
    note += ` Before ${d.cutover_local} the files hold wind speed, wind direction, temperature, RH, and pressure only.`;
  }
  document.getElementById("dl-note").textContent = note;
}

function selectedVars(){
  return [...document.querySelectorAll('#vars input:checked')].map(el=>el.value);
}

// Local calendar date. toISOString() is UTC, which rolls to tomorrow in the
// evening for US time zones and would request an empty day.
function isoDate(d){
  const p = n => String(n).padStart(2,"0");
  return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());
}

function doDownload(start, end){
  const vars = selectedVars().join(",");
  const q = new URLSearchParams({start, end, vars});
  window.location = "/api/weather/download?" + q.toString();
}

function downloadRange(){
  const s = document.getElementById("start").value;
  const e = document.getElementById("end").value;
  if(!s || !e){ alert("Pick a start and end date."); return; }
  const days = (new Date(e+"T00:00:00") - new Date(s+"T00:00:00")) / 86400000 + 1;
  if (days < 1){ alert("End date is before start date."); return; }
  if (days > MAX_DAYS){ alert(`Pick at most ${MAX_DAYS} days per download (selected ${Math.round(days)}).`); return; }
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

document.getElementById("hours").addEventListener("change", loadPlot);
loadVars(); loadPlot(); loadHealth();
setInterval(loadPlot, 30000);
setInterval(loadHealth, 10000);
