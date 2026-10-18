"""Background DJ loop: polls Spotify, detects skips, queues one track ahead, logs plays."""
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import context as ctx_builder
from app import model, selector, spotify
from app.env import ROOT

PLAY_LOG = ROOT / "data" / "play_log.jsonl"
POLL_S = 5
VIBE_RECOMPUTE_S = 60
BIG_SHIFT = 0.35
QUEUE_AFTER_MS = 15_000


@dataclass
class State:
    running: bool = False
    mode: str = "live"
    trace: list[dict] = field(default_factory=list)
    trace_start: float = 0.0
    trace_speedup: float = 4.0
    ctx_dict: dict | None = None
    ctx_text: str = ""
    spec: dict | None = None
    last_vibe_at: float = 0.0
    queued_uri: str | None = None
    queued_track: dict | None = None
    last_track_uri: str | None = None
    last_track: dict | None = None
    last_track_duration_ms: int = 0
    last_track_started_at: float = 0.0
    last_progress_ms: int = 0
    play_log: list[dict] = field(default_factory=list)
    status: str = ""
    lat: float | None = None
    lon: float | None = None
    speed_mps: float | None = None
    gps_at: float = 0.0


state = State()


def _append_log(entry: dict) -> None:
    state.play_log.append(entry)
    PLAY_LOG.parent.mkdir(exist_ok=True)
    with PLAY_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_log() -> None:
    if not PLAY_LOG.exists():
        return
    for line in PLAY_LOG.read_text().splitlines():
        if line.strip():
            state.play_log.append(json.loads(line))


def _current_ctx() -> dict | None:
    if state.mode == "replay" and state.trace:
        elapsed = (time.time() - state.trace_start) * state.trace_speedup
        row = state.trace[0]
        for r in state.trace:
            if r["t"] <= elapsed:
                row = r
            else:
                break
        return row["ctx"]
    speed = state.speed_mps if (time.time() - state.gps_at) < 120 else None
    return ctx_builder.live_ctx(lat=state.lat, lon=state.lon, speed_mps=speed, play_log=state.play_log)


def _classify(listened_ms: int, duration_ms: int) -> str:
    if duration_ms <= 0:
        return "finish"
    frac = listened_ms / duration_ms
    remaining = duration_ms - listened_ms
    if listened_ms < 30_000 and remaining > 10_000:
        return "strong_skip"
    if frac < 0.70 and remaining > 10_000:
        return "skip"
    return "finish"


def _recompute_vibe(force: bool = False) -> None:
    ctx = _current_ctx()
    if not ctx:
        return
    txt = ctx_builder.build(ctx)
    if not force and txt == state.ctx_text and (time.time() - state.last_vibe_at) < VIBE_RECOMPUTE_S:
        return
    old = state.spec
    state.ctx_dict, state.ctx_text = ctx, txt
    spec = model.vibe(txt)
    state.spec = spec.model_dump()
    state.last_vibe_at = time.time()
    if old and (abs(old["energy"] - spec.energy) > BIG_SHIFT or abs(old["valence"] - spec.valence) > BIG_SHIFT):
        _queue_pick(jump=True)


def _queue_pick(jump: bool = False) -> None:
    if not state.spec:
        return
    from app.schemas import VibeSpec
    pick = selector.pick(VibeSpec(**state.spec), state.play_log)
    if not pick:
        state.status = "no selector pick"
        return
    try:
        spotify.queue(pick["uri"])
        state.queued_uri, state.queued_track = pick["uri"], pick
        if jump:
            try:
                spotify.next_track()
            except Exception as e:
                state.status = f"next failed: {e}"
    except spotify.NoActiveDevice:
        state.status = "no active device: open Spotify"
    except Exception as e:
        state.status = f"queue failed: {e}"


async def tick() -> None:
    try:
        pb = spotify.playback()
    except spotify.NoActiveDevice:
        state.status = "no active device: open Spotify"
        return
    except Exception as e:
        state.status = f"playback error: {e}"
        return
    if not pb or not pb.get("item"):
        state.status = "nothing playing"
        return
    state.status = ""
    item = pb["item"]
    uri, dur, prog = item["uri"], item.get("duration_ms", 0), pb.get("progress_ms", 0)

    if uri != state.last_track_uri:
        if state.last_track_uri:
            outcome = _classify(state.last_progress_ms, state.last_track_duration_ms)
            _append_log({
                "ts": time.time(), "uri": state.last_track_uri,
                "name": state.last_track["name"] if state.last_track else None,
                "outcome": outcome, "listened_ms": state.last_progress_ms,
                "duration_ms": state.last_track_duration_ms,
                "context_text": state.ctx_text, "spec_at_time": state.spec,
                "queued_by_aux": state.last_track_uri == state.queued_uri,
            })
        state.last_track_uri, state.last_track = uri, item
        state.last_track_duration_ms, state.last_track_started_at = dur, time.time()
        if uri == state.queued_uri:
            state.queued_uri, state.queued_track = None, None

    state.last_progress_ms = prog

    _recompute_vibe()

    # Queue the next track once we're 15s into the current one (based on the context -- calendar
    # event, campus location, speed -- at that moment), instead of waiting for the track to almost
    # end. Still only queues once per track: Spotify's queue can't be reordered/cleared, so we only
    # ever have one track queued ahead (PRD constraint).
    if state.queued_uri is None and prog >= QUEUE_AFTER_MS:
        _queue_pick()


async def loop() -> None:
    _load_log()
    _recompute_vibe(force=True)
    while state.running:
        await tick()
        await asyncio.sleep(POLL_S)


_task: asyncio.Task | None = None


async def start(mode: str = "live", trace_path: str | None = None, speedup: float = 4.0) -> None:
    global _task
    await stop()
    state.mode = mode
    state.trace, state.ctx_dict, state.ctx_text, state.spec = [], None, "", None
    if mode == "replay":
        path = Path(trace_path) if trace_path else ROOT / "data" / "demo" / "drive_trace.json"
        state.trace = json.loads(path.read_text())
        state.trace_start = time.time()
        state.trace_speedup = speedup
    state.running = True
    _task = asyncio.create_task(loop())


async def stop() -> None:
    global _task
    state.running = False
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=POLL_S + 2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
