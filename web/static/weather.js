// MH weather page: 24 h outdoor plot and CSV download.
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
