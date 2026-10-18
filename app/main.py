import asyncio
import json
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import dj, spotify
from app.env import ROOT

app = FastAPI(title="Auxie")

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
async def start(mode: str = "live", speedup: float = 4.0, trace: str | None = None):
    await dj.start(mode=mode, trace_path=trace, speedup=speedup)
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
                                         "art": (s.last_track.get("album", {}).get("images") or [{}])[0].get("url"),
                                         "progress_ms": s.last_progress_ms, "duration_ms": s.last_track_duration_ms},
        "queued": s.queued_track and {"uri": s.queued_uri, "name": s.queued_track.get("name"),
                                      "art": s.queued_track.get("art"),
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
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><title>Auxie — Label</title>
<style>:root{--green:#1db954}
body{background:#0b0b0d;background:radial-gradient(1200px 600px at 50% -10%,#163a24 0%,#0b0b0d 55%);
color:#eee;font:15px/1.5 -apple-system,ui-sans-serif,system-ui;margin:0;padding:28px 24px 60px;display:flex;
justify-content:center}.inner{width:100%;max-width:900px}
h1{font-weight:800;margin:0 0 14px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--green)}
.ctx{background:#181818;border:1px solid #2a2a2a;border-radius:14px;padding:16px;margin:12px 0;
white-space:pre-wrap;color:#8fc4ff;font-size:12px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#181818;border-radius:14px;padding:16px;cursor:pointer;border:2px solid #2a2a2a;transition:border-color .15s}
.card:hover{border-color:var(--green)}.card img{width:100%;border-radius:10px;margin-bottom:12px;aspect-ratio:1;object-fit:cover}
.name{font-weight:700;font-size:17px;margin-bottom:4px}.art{color:#a7a7a7;margin-bottom:8px;font-size:13px}
.spec{font-size:12px;color:#8a8a8a;margin-top:8px}.tag{display:inline-block;background:rgba(29,185,84,.15);
color:var(--green);border:1px solid rgba(29,185,84,.3);padding:2px 9px;border-radius:999px;margin-right:4px;font-size:11px;font-weight:600}
.bar{height:5px;background:#333;border-radius:3px;margin:4px 0}
.bar>span{display:block;height:100%;background:var(--green);border-radius:3px}
.preview{background:#2a2a2a;color:#eee;border:0;padding:7px 12px;border-radius:999px;cursor:pointer;font-size:12px;
font-weight:600;margin-top:8px}.preview:hover{background:#333}
.hud{color:#a7a7a7;font-size:13px;margin:10px 0}.kbd{background:#2a2a2a;padding:2px 6px;border-radius:4px;font-family:monospace}
.done{text-align:center;padding:60px;color:#a7a7a7}a{color:var(--green);text-decoration:none}a:hover{text-decoration:underline}
</style></head><body><div class="inner">
<h1><span class="dot"></span>Label pairs</h1>
<div class="hud" id="hud">loading...</div>
<div class="ctx" id="ctx"></div>
<div class="cards" id="cards"></div>
<div class="hud">keys: <span class="kbd">1</span> or <span class="kbd">A</span> = left · <span class="kbd">2</span> or <span class="kbd">D</span> = right · <span class="kbd">space</span> = skip · <span class="kbd">P</span> left preview · <span class="kbd">O</span> right preview</div>
<p><a href="/">← back to Auxie</a></p>
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
</script></div></body></html>""")


@app.get("/")
def index():
    if not spotify.logged_in():
        return RedirectResponse("/login")
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><title>Auxie</title>
<style>
:root{--green:#1db954;--green-dk:#169c46;--bg:#0b0b0d;--panel:#181818;--panel2:#1f1f1f;--border:#2a2a2a;--text:#fff;--dim:#a7a7a7;--bad:#f15e5e}
*{box-sizing:border-box}body{background:var(--bg);background:radial-gradient(1200px 600px at 50% -10%,#163a24 0%,var(--bg) 55%);
color:var(--text);font:15px/1.5 -apple-system,ui-sans-serif,system-ui;margin:0;padding:32px 24px 80px;display:flex;justify-content:center}
.wrap{width:100%;max-width:760px}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:36px;height:36px;border-radius:50%;background:var(--green);display:flex;align-items:center;justify-content:center;flex-shrink:0}
.logo svg{width:22px;height:22px}
.brand h1{font-size:21px;margin:0;font-weight:800;letter-spacing:-0.02em}
.pill{display:flex;align-items:center;gap:6px;background:var(--panel);border:1px solid var(--border);border-radius:999px;
padding:6px 12px;font-size:12px;color:var(--dim)}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 0 rgba(29,185,84,.6);animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(29,185,84,.5)}70%{box-shadow:0 0 0 7px rgba(29,185,84,0)}100%{box-shadow:0 0 0 0 rgba(29,185,84,0)}}
.controls{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
button{font:inherit;border:0;cursor:pointer;border-radius:999px;padding:11px 20px;font-weight:700;font-size:13px;
transition:transform .08s,filter .15s}
button:active{transform:scale(.97)}
button.primary{background:var(--green);color:#042b11}button.primary:hover{filter:brightness(1.08)}
button.ghost{background:var(--panel2);color:var(--text);border:1px solid var(--border)}button.ghost:hover{background:#262626}
button.stop{background:transparent;color:var(--dim);border:1px solid var(--border)}button.stop:hover{color:var(--bad);border-color:var(--bad)}
a.labellink{color:var(--dim);font-size:12px;text-decoration:none;align-self:center;margin-left:auto}
a.labellink:hover{color:var(--text)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:16px}
.np-empty{color:var(--dim);font-size:14px;text-align:center;padding:30px 0}
.status{background:rgba(241,94,94,.12);color:var(--bad);border-radius:10px;padding:8px 12px;font-size:13px;margin-bottom:14px}
.np{display:flex;gap:16px}
.art{width:88px;height:88px;border-radius:10px;background:#000;object-fit:cover;flex-shrink:0;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.art.none{display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:10px}
.npinfo{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center}
.eq{display:flex;gap:2px;align-items:flex-end;height:14px;margin-bottom:6px}
.eq span{width:3px;background:var(--green);border-radius:1px;animation:eq 1s ease-in-out infinite}
.eq span:nth-child(1){height:40%;animation-delay:0s}.eq span:nth-child(2){height:100%;animation-delay:.2s}
.eq span:nth-child(3){height:65%;animation-delay:.4s}.eq span:nth-child(4){height:85%;animation-delay:.1s}
@keyframes eq{0%,100%{transform:scaleY(.4)}50%{transform:scaleY(1)}}
.name{font-weight:700;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.artist{color:var(--dim);font-size:13px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.progress-row{display:flex;align-items:center;gap:8px;margin-top:10px}
.pbar{flex:1;height:4px;background:#3a3a3a;border-radius:2px;overflow:hidden}
.pbar>span{display:block;height:100%;background:#fff;border-radius:2px;transition:width 1s linear}
.time{color:var(--dim);font-size:11px;min-width:34px;text-align:center}
.queued{display:flex;align-items:center;gap:10px;margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}
.queued img{width:34px;height:34px;border-radius:6px;object-fit:cover}
.queued .lbl{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.queued .qn{font-size:13px;font-weight:600}
.secrow{display:flex;gap:16px;flex-wrap:wrap}
.card.half{flex:1;min-width:260px}
h3{margin:0 0 14px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);font-weight:700}
.vbar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-size:12px;color:var(--dim)}
.vbar-row .lab{width:54px;flex-shrink:0}
.vbar{flex:1;height:8px;background:#3a3a3a;border-radius:4px;overflow:hidden}
.vbar>span{display:block;height:100%;background:linear-gradient(90deg,var(--green-dk),var(--green));border-radius:4px;transition:width .6s ease}
.bpm{font-size:12px;color:var(--dim);margin:4px 0 10px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.tag{background:rgba(29,185,84,.15);color:var(--green);border:1px solid rgba(29,185,84,.3);padding:3px 10px;
border-radius:999px;font-size:11px;font-weight:600}
.djline{font-size:13px;font-style:italic;color:#ddd;border-left:2px solid var(--green);padding-left:10px}
.empty{color:var(--dim);font-size:13px}
.stats{display:flex;gap:18px;margin-bottom:10px}
.stat b{font-size:20px;display:block;color:var(--text)}
.stat span{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
.logrow{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--border);font-size:13px}
.logrow:last-child{border-bottom:0}
.icon{width:16px;text-align:center;flex-shrink:0}
.icon.finish{color:var(--green)}.icon.skip{color:var(--bad)}
.lname{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#ddd}
details{margin-top:4px}summary{cursor:pointer;color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
pre{white-space:pre-wrap;color:#8fc4ff;font-size:12px;margin:10px 0 0;background:#111;border-radius:8px;padding:10px}
</style></head><body><div class="wrap">
<div class="topbar">
<div class="brand"><div class="logo"><svg viewBox="0 0 24 24" fill="none">
<circle cx="9" cy="10.5" r="1.4" fill="#042b11"/><circle cx="15" cy="10.5" r="1.4" fill="#042b11"/>
<path d="M8 15c1.2 1.3 2.8 2 4 2s2.8-.7 4-2" stroke="#042b11" stroke-width="2" stroke-linecap="round" fill="none"/>
<path d="M12 3.5v2.3M9.7 4.3l.9 1.8M14.3 4.3l-.9 1.8" stroke="#042b11" stroke-width="1.6" stroke-linecap="round"/>
<circle cx="12" cy="3" r="1.1" fill="#042b11"/>
</svg></div><h1>Auxie</h1></div>
<div class="pill"><span class="dot"></span><span id="pillstate">connecting…</span></div>
</div>
<div class="controls">
<button class="primary" onclick="start('live')">▶ Start Live</button>
<button class="ghost" onclick="start('replay')">Replay Demo</button>
<button class="ghost" onclick="start('replay','data/demo/campus_trace.json')">Campus Demo (2 min)</button>
<button class="stop" onclick="stop()">■ Stop</button>
<a class="labellink" href="/label">Label pairs →</a>
</div>
<div class="card" id="np"></div>
<div class="secrow">
<div class="card half" id="vibe"></div>
<div class="card half" id="log"></div>
</div>
<div class="card" id="ctxcard" style="display:none">
<details><summary>Raw context sent to the model</summary><pre id="ctxraw"></pre></details>
</div>
</div>
<script>
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function start(m,trace){
  const q=new URLSearchParams({mode:m});
  if(trace)q.set('trace',trace);
  await fetch('/start?'+q,{method:'POST'});refresh()
}
async function stop(){await fetch('/stop',{method:'POST'});refresh()}
async function refresh(){
  let s; try{ s = await (await fetch('/state')).json(); } catch(e){ document.getElementById('pillstate').textContent='offline'; return; }
  document.getElementById('pillstate').textContent = s.running ? (s.mode==='live'?'live':'replay') : 'idle';

  const np = document.getElementById('np');
  const art = s.now_playing && s.now_playing.art;
  np.innerHTML =
    (s.status?`<div class="status">${esc(s.status)}</div>`:'') +
    (s.now_playing ? `
      <div class="np">
        ${art?`<img class="art" src="${art}">`:'<div class="art none">no art</div>'}
        <div class="npinfo">
          <div class="eq"><span></span><span></span><span></span><span></span></div>
          <div class="name">${esc(s.now_playing.name)}</div>
          <div class="artist">${esc((s.now_playing.artists||[]).join(', '))}</div>
          <div class="progress-row">
            <span class="time">${fmt(s.now_playing.progress_ms)}</span>
            <div class="pbar"><span style="width:${100*s.now_playing.progress_ms/Math.max(1,s.now_playing.duration_ms)}%"></span></div>
            <span class="time">${fmt(s.now_playing.duration_ms)}</span>
          </div>
        </div>
      </div>` : '<div class="np-empty">Nothing playing — hit Start Live and press play on Spotify.</div>') +
    (s.queued ? `<div class="queued">
        ${s.queued.art?`<img src="${s.queued.art}">`:''}
        <div><div class="lbl">Up next</div><div class="qn">${esc(s.queued.name)} — ${esc((s.queued.artists||[]).join(', '))}</div></div>
      </div>` : '');

  const vibe = document.getElementById('vibe');
  if (s.spec) {
    vibe.innerHTML = `<h3>Current vibe</h3>
      <div class="vbar-row"><span class="lab">energy</span><div class="vbar"><span style="width:${100*s.spec.energy}%"></span></div></div>
      <div class="vbar-row"><span class="lab">valence</span><div class="vbar"><span style="width:${100*s.spec.valence}%"></span></div></div>
      <div class="bpm">${s.spec.bpm_min}–${s.spec.bpm_max} BPM</div>
      <div class="tags">${(s.spec.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
      ${s.spec.dj_line?`<div class="djline">${esc(s.spec.dj_line)}</div>`:''}`;
  } else {
    vibe.innerHTML = `<h3>Current vibe</h3><div class="empty">Waiting for the first read on your context…</div>`;
  }

  const log = document.getElementById('log');
  log.innerHTML = `<h3>Session</h3>
    <div class="stats"><div class="stat"><b>${s.plays}</b><span>plays</span></div><div class="stat"><b>${s.skips}</b><span>skips</span></div></div>
    ${(s.recent && s.recent.length) ? s.recent.slice().reverse().map(p=>{
      const ok = p.outcome==='finish';
      return `<div class="logrow"><span class="icon ${ok?'finish':'skip'}">${ok?'✓':'⤫'}</span><span class="lname">${esc(p.name||p.uri)}</span></div>`;
    }).join('') : '<div class="empty">No plays yet this session.</div>'}`;

  const ctxcard = document.getElementById('ctxcard');
  if (s.context) { ctxcard.style.display='block'; document.getElementById('ctxraw').textContent = s.context; }
}
function fmt(ms){const t=Math.floor((ms||0)/1000);return Math.floor(t/60)+':'+String(t%60).padStart(2,'0')}
setInterval(refresh,2000);refresh();
if('geolocation' in navigator){
  navigator.geolocation.watchPosition(p=>{
    const q=new URLSearchParams({lat:p.coords.latitude,lon:p.coords.longitude});
    if(p.coords.speed!=null)q.set('speed_mps',p.coords.speed);
    fetch('/gps?'+q,{method:'POST'});
  },err=>console.log('gps:',err.message),{enableHighAccuracy:true,maximumAge:10000});
}
</script></body></html>""")
