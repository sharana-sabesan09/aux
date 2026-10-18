import asyncio
import json
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import dj, spotify
from app.env import ROOT

app = FastAPI(title="Aux")

PAIRS_PATH = ROOT / "data" / "pairs.jsonl"
LABELS_PATH = ROOT / "data" / "labels.jsonl"


@app.get("/login")
def login():
    return RedirectResponse(spotify.auth_url())


@app.get("/callback")
def callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"Spotify login failed: {error}", status_code=400)
    spotify.exchange_code(code, state)
    return RedirectResponse("/")


@app.post("/start")
async def start(mode: str = "live", speedup: float = 4.0):
    await dj.start(mode=mode, speedup=speedup)
    return {"running": True, "mode": mode}


@app.post("/stop")
async def stop():
    await dj.stop()
    return {"running": False}


@app.post("/gps")
def gps(lat: float, lon: float, speed_mps: float | None = None):
    dj.state.lat, dj.state.lon = lat, lon
    dj.state.speed_mps = speed_mps
    dj.state.gps_at = time.time()
    return {"ok": True}


@app.get("/state")
def get_state():
    s = dj.state
    return JSONResponse({
        "running": s.running, "mode": s.mode, "status": s.status,
        "context": s.ctx_text, "spec": s.spec,
        "now_playing": s.last_track and {"uri": s.last_track_uri, "name": s.last_track.get("name"),
                                         "artists": [a["name"] for a in s.last_track.get("artists", [])],
                                         "progress_ms": s.last_progress_ms, "duration_ms": s.last_track_duration_ms},
        "queued": s.queued_track and {"uri": s.queued_uri, "name": s.queued_track.get("name"),
                                      "artists": [a if isinstance(a, str) else a.get("name") for a in s.queued_track.get("artists", [])]},
        "plays": len(s.play_log),
        "skips": sum(1 for p in s.play_log if p["outcome"] in ("skip", "strong_skip")),
        "recent": s.play_log[-5:],
    })


def _pairs() -> list[dict]:
    if not PAIRS_PATH.exists():
        return []
    return [json.loads(l) for l in PAIRS_PATH.read_text().splitlines() if l.strip()]


def _labeled_contexts() -> set[str]:
    if not LABELS_PATH.exists():
        return set()
    return {json.loads(l)["context"] for l in LABELS_PATH.read_text().splitlines() if l.strip()}


@app.get("/label/next")
def label_next():
    done = _labeled_contexts()
    total = _pairs()
    for p in total:
        if p["context"] not in done:
            return {"pair": p, "done": len(done), "total": len(total)}
    return {"pair": None, "done": len(done), "total": len(total)}


@app.post("/label/preview")
async def label_preview(uri: str, seconds: float = 15.0):
    try:
        dev = spotify.active_device_id()
        if not dev:
            return JSONResponse({"ok": False, "error": "no active device"}, status_code=409)
        spotify.queue(uri)
        spotify.next_track()
        await asyncio.sleep(seconds)
        try:
            spotify.pause()
        except Exception:
            pass
        return {"ok": True}
    except spotify.NoActiveDevice:
        return JSONResponse({"ok": False, "error": "no active device"}, status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/label")
def label_choice(context: str, choice: str):
    if choice not in ("A", "B", "skip"):
        return JSONResponse({"ok": False, "error": "choice must be A|B|skip"}, status_code=400)
    LABELS_PATH.parent.mkdir(exist_ok=True)
    with LABELS_PATH.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "context": context, "choice": choice}) + "\n")
    return {"ok": True}


@app.get("/label")
def label_page():
    if not spotify.logged_in():
        return RedirectResponse("/login")
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><title>Aux Label</title>
<style>body{background:#0b0b0d;color:#eee;font:16px/1.4 ui-sans-serif,system-ui;margin:24px;max-width:900px}
h1{font-weight:600;margin:0 0 12px}.ctx{background:#17171b;border-radius:12px;padding:16px;margin:12px 0;
white-space:pre-wrap;color:#9ad;font-size:13px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#17171b;border-radius:12px;padding:16px;cursor:pointer;border:2px solid transparent}
.card:hover{border-color:#2b7}.card img{width:100%;border-radius:8px;margin-bottom:12px}
.name{font-weight:600;font-size:18px;margin-bottom:4px}.art{color:#aaa;margin-bottom:8px}
.spec{font-size:12px;color:#789;margin-top:8px}.tag{display:inline-block;background:#2a2a30;padding:2px 8px;
border-radius:10px;margin-right:4px;font-size:12px}.bar{height:5px;background:#333;border-radius:3px;margin:4px 0}
.bar>span{display:block;height:100%;background:#2b7;border-radius:3px}
.preview{background:#333;color:#eee;border:0;padding:6px 10px;border-radius:6px;cursor:pointer;font-size:12px;margin-top:8px}
.hud{color:#888;font-size:13px;margin:8px 0}.kbd{background:#333;padding:2px 6px;border-radius:4px;font-family:monospace}
.done{text-align:center;padding:60px;color:#aaa}a{color:#2b7}</style></head><body>
<h1>Label pairs</h1>
<div class="hud" id="hud">loading...</div>
<div class="ctx" id="ctx"></div>
<div class="cards" id="cards"></div>
<div class="hud">keys: <span class="kbd">1</span> or <span class="kbd">A</span> = left · <span class="kbd">2</span> or <span class="kbd">D</span> = right · <span class="kbd">space</span> = skip · <span class="kbd">P</span> left preview · <span class="kbd">O</span> right preview</div>
<p><a href="/">← back to DJ</a></p>
<script>
let cur = null;
let previewBusy = false;
async function load(){
  const r = await (await fetch('/label/next')).json();
  document.getElementById('hud').textContent = `${r.done} / ${r.total} labeled`;
  if (!r.pair){ document.getElementById('ctx').style.display='none'; document.getElementById('cards').innerHTML='<div class="done">All done. Run <code>python scripts/pairs_to_dpo.py</code>.</div>'; cur=null; return;}
  cur = r.pair;
  document.getElementById('ctx').textContent = cur.context;
  document.getElementById('cards').innerHTML = ['a','b'].map((k,i)=>{
    const s=cur[k].spec, t=cur[k].track;
    return `<div class="card" onclick="choose('${i===0?'A':'B'}')">
      ${t.art?`<img src="${t.art}">`:''}
      <div class="name">${t.name}</div><div class="art">${t.artists.join(', ')}</div>
      <div>energy <div class="bar"><span style="width:${100*s.energy}%"></span></div></div>
      <div>valence <div class="bar"><span style="width:${100*s.valence}%"></span></div></div>
      <div class="spec">BPM ${s.bpm_min}-${s.bpm_max}<br>${s.tags.map(x=>`<span class="tag">${x}</span>`).join('')}</div>
      <button class="preview" onclick="event.stopPropagation();preview('${t.uri}',this)">▶ 15s preview</button>
    </div>`;
  }).join('');
}
async function choose(c){
  if(!cur)return;
  await fetch(`/label?context=${encodeURIComponent(cur.context)}&choice=${c}`,{method:'POST'});
  load();
}
async function preview(uri,btn){
  if(previewBusy)return;
  previewBusy=true;
  document.querySelectorAll('.preview').forEach(b=>b.disabled=true);
  if(btn)btn.textContent='▶ playing...';
  try{
    await fetch(`/label/preview?uri=${encodeURIComponent(uri)}`,{method:'POST'});
  } finally {
    previewBusy=false;
    document.querySelectorAll('.preview').forEach(b=>b.disabled=false);
    if(btn)btn.textContent='▶ 15s preview';
  }
}
document.addEventListener('keydown',e=>{
  if(!cur)return;
  if(e.key==='1'||e.key.toLowerCase()==='a')choose('A');
  else if(e.key==='2'||e.key.toLowerCase()==='d')choose('B');
  else if(e.key===' '){e.preventDefault();choose('skip');}
  else if(e.key.toLowerCase()==='p')preview(cur.a.track.uri);
  else if(e.key.toLowerCase()==='o')preview(cur.b.track.uri);
  // preview() itself ignores calls while previewBusy, so rapid A/O or B/P presses no longer cut each other off
});
load();
</script></body></html>""")


@app.get("/")
def index():
    if not spotify.logged_in():
        return RedirectResponse("/login")
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><title>Aux</title>
<style>body{background:#0b0b0d;color:#eee;font:16px/1.4 ui-sans-serif,system-ui;margin:24px;max-width:720px}
h1{font-weight:600;margin:0 0 12px}.card{background:#17171b;border-radius:12px;padding:16px;margin:12px 0}
pre{white-space:pre-wrap;color:#9ad;font-size:13px}button{background:#2b7;color:#000;border:0;padding:10px 16px;
border-radius:8px;font-weight:600;cursor:pointer;margin-right:8px}button.g{background:#333;color:#eee}
.row{display:flex;gap:8px;align-items:center}.bar{flex:1;height:6px;background:#333;border-radius:3px;overflow:hidden;min-width:120px}
.bar>span{display:block;height:100%;background:#2b7}.tag{display:inline-block;background:#2a2a30;padding:2px 8px;
border-radius:10px;margin-right:4px;font-size:12px}.status{color:#f85;font-size:13px}.dim{color:#888;font-size:12px}</style>
</head><body><h1>Aux</h1>
<div>
<button onclick="start('replay')">Start Replay</button>
<button onclick="start('live')">Start Live</button>
<button class="g" onclick="stop()">Stop</button>
<a href="/label" style="color:#2b7;margin-left:12px">→ label pairs</a>
</div>
<div class="card" id="np">Not running.</div>
<div class="card" id="ctx"></div>
<div class="card" id="log"></div>
<script>
async function start(m){await fetch('/start?mode='+m,{method:'POST'});refresh()}
async function stop(){await fetch('/stop',{method:'POST'});refresh()}
async function refresh(){
  const s=await (await fetch('/state')).json();
  document.getElementById('np').innerHTML=
    (s.status?`<div class="status">${s.status}</div>`:'')+
    (s.now_playing?`<div><b>${s.now_playing.name}</b> — ${s.now_playing.artists.join(', ')}</div>
     <div class="row"><div class="bar"><span style="width:${100*s.now_playing.progress_ms/Math.max(1,s.now_playing.duration_ms)}%"></span></div>
     <span class="dim">${Math.floor(s.now_playing.progress_ms/1000)}s / ${Math.floor(s.now_playing.duration_ms/1000)}s</span></div>`:'<div class="dim">no playback</div>')+
    (s.queued?`<div class="dim">queued next: ${s.queued.name}</div>`:'');
  document.getElementById('ctx').innerHTML=
    (s.spec?`<div class="row">energy <div class="bar"><span style="width:${100*s.spec.energy}%"></span></div></div>
     <div class="row">valence <div class="bar"><span style="width:${100*s.spec.valence}%"></span></div></div>
     <div>BPM ${s.spec.bpm_min}-${s.spec.bpm_max}<br>${s.spec.tags.map(t=>`<span class="tag">${t}</span>`).join('')}</div>
     <div class="dim" style="margin-top:6px">${s.spec.dj_line}</div>`:'<div class="dim">no vibe yet</div>')+
    `<pre>${s.context||''}</pre>`;
  document.getElementById('log').innerHTML=
    `<div><b>${s.plays}</b> plays · <b>${s.skips}</b> skips</div>`+
    (s.recent||[]).map(p=>`<div class="dim">${p.outcome.padEnd(12)} ${p.name||p.uri}</div>`).join('');
}
setInterval(refresh,2000);refresh();
if('geolocation' in navigator){
  navigator.geolocation.watchPosition(p=>{
    const q=new URLSearchParams({lat:p.coords.latitude,lon:p.coords.longitude});
    if(p.coords.speed!=null)q.set('speed_mps',p.coords.speed);
    fetch('/gps?'+q,{method:'POST'});
  },err=>console.log('gps:',err.message),{enableHighAccuracy:true,maximumAge:10000});
}
</script></body></html>""")
