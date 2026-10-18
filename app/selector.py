"""Score catalog tracks against a vibe spec. Returns a URI."""
import json
import random
import time
from pathlib import Path

from app.env import ROOT
from app.schemas import VibeSpec

CATALOG = ROOT / "data" / "catalog.json"
KEPT = ROOT / "data" / "catalog_kept.json"
EXCLUDE_WINDOW_S = 2 * 3600
RECENT_N = 30
TOP_K = 5


def _load() -> list[dict]:
    tracks = json.loads(CATALOG.read_text())
    if KEPT.exists():
        keep = set(json.loads(KEPT.read_text()))
        tracks = [t for t in tracks if t["uri"] in keep]
    return tracks


_cache: list[dict] | None = None


def _tracks() -> list[dict]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def pick(spec: VibeSpec, play_log: list[dict]) -> dict | None:
    now = time.time()
    recent_uris = {p["uri"] for p in play_log[-RECENT_N:]}
    skipped_recent = {p["uri"] for p in play_log
                      if p["outcome"] in ("skip", "strong_skip") and now - p["ts"] < EXCLUDE_WINDOW_S}
    bpm_mid_spec = (spec.bpm_min + spec.bpm_max) / 2
    want_tags = set(spec.tags)

    scored = []
    for t in _tracks():
        if t["uri"] in recent_uris or t["uri"] in skipped_recent:
            continue
        de = abs(t["energy"] - spec.energy)
        dv = abs(t["valence"] - spec.valence)
        dbpm = abs(((t["bpm_min"] + t["bpm_max"]) / 2 - bpm_mid_spec)) / 60.0
        tag_bonus = 0.25 * len(want_tags & set(t["tags"]))
        score = -(de + dv + dbpm) + tag_bonus
        scored.append((score, t))

    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    return random.choice([t for _, t in scored[:TOP_K]])
