// MH DAQ group live page: value cards, health indicator, trend plots.

// Group-page health thresholds, in seconds. Filled from /api/channels, which
// picks them for the data source (Mission reads lag the snapshot mirror). The
// values here are the local ones, used until that call returns.
let HEALTH_DELAYED_S = 5;
let HEALTH_DOWN_S = 60;
// Heartbeat age past which the full-width red banner shows (web.stale_banner_s).
let BANNER_S = 3600;
// Channel name to {reason, since} for channels tagged offline; cards grey out.
let OFFLINE = {};

// Wong (2011) colorblind-safe order, without black (invisible on this dark
// background). Dash styles add a second channel so traces in one panel stay
// distinct in greyscale and for color-vision deficiency.
const WONG = ["#56B4E9","#E69F00","#009E73","#F0E442","#CC79A7","#D55E00","#0072B2"];
const DASHES = ["solid","dash","dot","dashdot","longdash","longdashdot"];
// Channel name to SI unit, filled from /api/channels (config is the source).
let UNITS = {};
function unitFor(k){
  const u = UNITS[k] || "";
  return u === "percent" ? "%" : u;
}

// Channel name to {low, high}, filled from /api/channels (daq_config.json
// display_ranges). Channels without a range are never colored.
let RANGES = {};
// Class for a card value: "below", "above", or "" inside the band. Compares the
// displayed (2-decimal) value, so 39.996 shown as 40.00 is not colored. Limits
// themselves count as normal.
function rangeClass(k, shown){
  const r = RANGES[k];
  const n = Number(shown);
  if (!r || !Number.isFinite(n)) return "";
  if (r.low != null && n < r.low) return "below";
  if (r.high != null && n > r.high) return "above";
  return "";
}

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

// Refresh the value cards. Health status is shown by refreshHealth().
async function refresh(){
  try {
    const r = await fetch("/api/snapshot");
    const s = await r.json();
    if (!s.available) return;
    if (s.offline) OFFLINE = s.offline;  // follows config edits without a reload

    // Weather cards. The snapshot holds the AIO 2's fixed-width strings
    // ("+020.2", "005"), so parse and print at the sensor's own resolution.
    const w = s.outdoor || {};
    const wmap = [["wind_speed","Wind","m/s",1],["wind_direction","Dir","deg",0],
      ["air_temp","Air T","degC",1],["relative_humidity","RH","%",0],
      ["barometric_pressure","Pressure","mb",1],["battery_voltage","Battery","V",1]];
    const fmtOutdoor = (raw, dp) => {
      if (raw == null || raw === "") return "n/a";
      const n = Number(raw);
      return Number.isFinite(n) ? n.toFixed(dp) : raw;
    };
    document.getElementById("weather").innerHTML = wmap.map(([k,lab,u,dp])=>
      `<div class="card"><div class="label">${lab}</div>`+
      `<div class="value">${fmtOutdoor(w[k],dp)}<span class="unit">${u}</span></div></div>`).join("");

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
        const off = OFFLINE[k];
        if (off){
          const title = (off.reason || "Tagged offline") + (off.since ? " Since "+off.since+"." : "");
          return `<div class="card offline" title="${title.replace(/"/g,"&quot;")}"><div class="label">${k}</div>`+
            `<div class="value">${val}<span class="unit">${unitFor(k)}</span></div>`+
            `<div class="tag">offline</div></div>`;
        }
        return `<div class="card"><div class="label">${k}</div>`+
          `<div class="value ${rangeClass(k, val)}">${val}<span class="unit">${unitFor(k)}</span></div></div>`;
      }).join("");
      html += `</div>`;
    }
    document.getElementById("indoor-groups").innerHTML = html;
  } catch(e){ console.error("snapshot error:", e); }
}

// Drive the header indicator from the heartbeat. Worst applicable condition
// wins: red beats yellow beats green. The heartbeat holds status only, so this
// reads no measurement values. #status is owned here, not by refresh().
// "3 d 4 h", "5 h 12 min", or "7 min", matching the watchdog email.
function formatAge(s){
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  if (d) return d+" d "+h+" h";
  if (h) return h+" h "+m+" min";
  return m+" min";
}

// Full-width banner for a heartbeat older than BANNER_S, so an outage is not
// missed in the small header text. Hidden when text is null.
function setBanner(text, sub){
  const b = document.getElementById("banner");
  if (text == null){ b.style.display = "none"; return; }
  b.innerHTML = text + (sub ? `<span class="sub">${sub}</span>` : "");
  b.style.display = "block";
}

function updateBanner(h){
  if (!h.available){
    setBanner("No DAQ heartbeat found.",
      "The dashboard cannot read heartbeat.json. The DAQ computer may be off, or this machine cannot reach the data folder.");
    return;
  }
  if (h.age_s != null && h.age_s > BANNER_S){
    setBanner("No update from the DAQ computer for "+formatAge(h.age_s)+".",
      "Last heartbeat "+String(h.written_at||"").replace("T"," ")+
      ". The DAQ computer may be off or unable to reach Mission. Values and trends below are not current.");
    return;
  }
  setBanner(null);
}

async function refreshHealth(){
  const st = document.getElementById("status");
  try{
    const r = await fetch("/api/heartbeat");
    const h = await r.json();
    updateBanner(h);

    // Red: no heartbeat at all, or so old the daemon is presumed dead.
    if(!h.available){ st.textContent = "System down (no heartbeat)"; st.className="down"; return; }
    const age = h.age_s==null ? null : Math.round(h.age_s);
    if(h.age_s==null || h.age_s > HEALTH_DOWN_S){
      st.textContent = "System down" + (age==null ? "" : " ("+formatAge(age)+")");
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
let OUTDOOR_CHANNELS = [];  // AIO 2 column headers with a sensor
let SELECTED = new Set();  // seeded from the API defaults in loadChannels()
let DETAIL_RANGE = null;  // [startISO, endISO] or null = follow overview
const OVERVIEW_TARGET = 500;
const DETAIL_TARGET = 4000;

async function loadChannels(){
  try{
    const r = await fetch("/api/channels");
    const d = await r.json();
    ALL_CHANNELS = d.channels || [];
    OUTDOOR_CHANNELS = d.outdoor_channels || [];
    UNITS = Object.fromEntries([...ALL_CHANNELS, ...OUTDOOR_CHANNELS].map(c => [c.channel, c.unit]));
    RANGES = d.display_ranges || {};
    OFFLINE = d.offline || {};
    SELECTED = new Set(d.defaults || []);
    if (d.health){
      HEALTH_DELAYED_S = d.health.delayed_s; HEALTH_DOWN_S = d.health.down_s;
      if (d.health.banner_s != null) BANNER_S = d.health.banner_s;
    }
    buildPicker(); updatePickerCount();
  }catch(e){ console.error("channels error:", e); }
}

function pickerItems(chs){
  return chs.map(ch=>{
    const on = SELECTED.has(ch) ? "checked" : "";
    return `<label><input type="checkbox" value="${ch}" ${on} onchange="toggleChannel(this.value,this.checked)"> ${ch}</label>`;
  }).join("");
}

function buildPicker(){
  const byUnit = {};
  for(const c of ALL_CHANNELS){ (byUnit[c.unit] ||= []).push(c.channel); }
  let html = "";
  for(const unit of Object.keys(byUnit).sort()){
    html += `<div class="grp">${unit}</div>` + pickerItems(byUnit[unit]);
  }
  if (OUTDOOR_CHANNELS.length){
    html += `<div class="grp">Weather (AIO 2)</div>` + pickerItems(OUTDOOR_CHANNELS.map(c=>c.channel));
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

// Keys of a /api/trend payload that are not channel series.
const TREND_META = ["available","time","time_outdoor","x_of","markers","units","start","end"];

// Stable color per channel, so a channel keeps its color when others are
// added or removed. Fixed order of selection in the picker's channel list.
function colorFor(ch){
  const all = [...ALL_CHANNELS, ...OUTDOOR_CHANNELS].map(c=>c.channel);
  const sel = all.filter(c => SELECTED.has(c));
  const i = Math.max(0, sel.indexOf(ch));
  return {color: WONG[i % WONG.length], dash: DASHES[Math.floor(i / WONG.length) % DASHES.length]};
}

// Build stacked-by-unit traces and layout for a given data payload + div.
function buildFigure(d){
  const units = d.units || {};
  const xOf = d.x_of || {};
  const markers = new Set(d.markers || []);
  const groups = {};
  for(const ch of Object.keys(d)){
    if(TREND_META.includes(ch)) continue;
    const u = units[ch] || "";
    (groups[u] ||= []).push(ch);
  }
  const unitList = Object.keys(groups).sort();
  const n = Math.max(1, unitList.length);
  const traces = [];
  const layout = {
    paper_bgcolor:"#161a22", plot_bgcolor:"#161a22", font:{color:"#c8ccd4"},
    margin:{l:56,r:16,t:6,b:30}, showlegend:true, legend:{orientation:"h"},
    hovermode:"x unified",
    grid:{rows:n, columns:1, pattern:"independent", roworder:"top to bottom"}
  };
  unitList.forEach((u,i)=>{
    const xa=i===0?"x":"x"+(i+1), ya=i===0?"y":"y"+(i+1);
    groups[u].forEach((ch, j)=>{
      // Within one panel, alternate dash so two traces never differ by color alone.
      const c = colorFor(ch);
      const dash = DASHES[j % DASHES.length] === "solid" ? c.dash : DASHES[j % DASHES.length];
      const x = d[xOf[ch] || "time"];
      // uid keeps legend visibility tied to the channel across refreshes.
      if (markers.has(ch)){
        traces.push({x, y:d[ch], name:ch, uid:ch, mode:"markers", xaxis:xa, yaxis:ya,
          marker:{color:c.color, size:4}});
      } else {
        traces.push({x, y:d[ch], name:ch, uid:ch, mode:"lines", xaxis:xa, yaxis:ya,
          line:{color:c.color, width:2, dash}});
      }
    });
    const xkey=i===0?"xaxis":"xaxis"+(i+1), ykey=i===0?"yaxis":"yaxis"+(i+1);
    layout[ykey]={title:{text:u}, gridcolor:"#262b36"};
    if (u === "deg") Object.assign(layout[ykey], {range:[0,360], tickvals:[0,90,180,270,360]});
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
    if(!d.available){ Plotly.purge("overview"); return; }
    const {traces,layout}=buildFigure(d);
    layout.dragmode="select";
    // Same uirevision across refreshes keeps legend toggles and the brush box;
    // a new window starts fresh.
    layout.uirevision="overview-"+windowMinutes();
    Plotly.react("overview",traces,layout,{displayModeBar:false,responsive:true});
    // Plotly.react keeps listeners across renders, so clear before re-wiring;
    // otherwise each 15 s refresh stacks another handler on the brush.
    const ov=document.getElementById("overview");
    ov.removeAllListeners("plotly_selected");
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
        document.getElementById("reset-detail").style.display="";
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
    if(!d.available){ Plotly.purge("detail"); return; }
    const {traces,layout}=buildFigure(d);
    // Keeps zoom and legend toggles through the 15 s live refresh; a new
    // brushed range (or Back to live) changes the key and resets the view.
    layout.uirevision = DETAIL_RANGE ? "detail-"+DETAIL_RANGE.join("|") : "detail-live";
    Plotly.react("detail",traces,layout,{displayModeBar:true,responsive:true,
      modeBarButtonsToRemove:["lasso2d","select2d"]});
  }catch(e){ console.error("detail error:", e); }
}

// Return the detail plot to the live last-30-min view it opens with.
function resetDetail(){
  DETAIL_RANGE=null;
  document.getElementById("detail-label").textContent="";
  document.getElementById("reset-detail").style.display="none";
  try{ Plotly.relayout("overview", {selections: []}); }catch(e){}
  refreshDetail();
}

// Cards and trends need units and the default selection, so load channels first.
loadChannels().then(()=>{ refreshHealth(); refresh(); refreshOverview(); refreshDetail(); });
document.getElementById("window").addEventListener("change", ()=>{
  resetDetail();  // new overview window resets the detail to default
  refreshOverview();
});
setInterval(refresh, 3000);
setInterval(refreshHealth, 3000);
// Overview and detail follow "now" when not brushed; refresh periodically.
setInterval(()=>{ refreshOverview(); if(!DETAIL_RANGE) refreshDetail(); }, 15000);
