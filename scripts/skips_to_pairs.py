"""M7: mine real skip/finish pairs from data/play_log.jsonl for DPO round 2.
See PRD.md section 9, stage 3.

For each Aux-queued skip, find an Aux-queued finish within WINDOW_S with a
similar context (same place + speed bucket). Pair: prompt = skip's context,
chosen = finished track's catalog spec, rejected = skipped track's catalog
spec. Strong skips are paired first (clearer signal).

If there aren't enough real skips yet, this just writes an empty/short file --
that's the documented fallback (PRD §16): demo "loop ready, here are the
pairs it built" instead of a finished retrain.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.env import ROOT  # noqa: E402

PLAY_LOG = ROOT / "data" / "play_log.jsonl"
CATALOG = ROOT / "data" / "catalog.json"
OUT = ROOT / "data" / "skip_pairs.jsonl"
WINDOW_S = 15 * 60

SYSTEM = ("You are a DJ. Given the listener's context, output only JSON describing the music that fits right now. "
          "Tags must be from this vocabulary only: chill, focus, hype, warm, dreamy, dark, acoustic, electronic, "
          "hip-hop, r&b, indie, lo-fi, jazz, ambient, pop, rock, funk, soul, latin, k-pop, cinematic, sad, romantic, "
          "nostalgic, party. Use at most 3 tags. bpm_max >= bpm_min, both plausible (60-180). "
          "dj_line is max 15 words, casual, no quotes.")


def _place_speed(ctx: str) -> str:
    """First line of the context string carries place + speed bucket; use it as a loose similarity key."""
    first_line = ctx.splitlines()[0] if ctx else ""
    return first_line.split("|")[1].strip() if "|" in first_line else first_line


def spec_for(uri: str, catalog_by_uri: dict) -> dict | None:
    t = catalog_by_uri.get(uri)
    if not t:
        return None
    return {"energy": t["energy"], "valence": t["valence"], "bpm_min": t["bpm_min"],
            "bpm_max": t["bpm_max"], "tags": t["tags"]}


def main():
    plays = [json.loads(l) for l in PLAY_LOG.read_text().splitlines() if l.strip()]
    plays = [p for p in plays if p.get("queued_by_aux")]  # self-started plays are never negatives (PRD §8.3)
    catalog_by_uri = {t["uri"]: t for t in json.loads(CATALOG.read_text())} if CATALOG.exists() else {}

    skips = sorted([p for p in plays if p["outcome"] in ("skip", "strong_skip")], key=lambda p: p["ts"])
    finishes = sorted([p for p in plays if p["outcome"] == "finish"], key=lambda p: p["ts"])
    # strong skips first: clearer signal, PRD asks for this ordering
    skips.sort(key=lambda p: 0 if p["outcome"] == "strong_skip" else 1)

    pairs = []
    for s in skips:
        match = next((f for f in finishes
                      if abs(f["ts"] - s["ts"]) <= WINDOW_S
                      and _place_speed(f["context_text"]) == _place_speed(s["context_text"])), None)
        if not match:
            continue
        rejected = spec_for(s["uri"], catalog_by_uri) or s.get("spec_at_time")
        chosen = spec_for(match["uri"], catalog_by_uri) or match.get("spec_at_time")
        if not chosen or not rejected:
            continue
        pairs.append({
            "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": s["context_text"]}],
            "chosen": [{"role": "assistant", "content": json.dumps(chosen, separators=(',', ':'))}],
            "rejected": [{"role": "assistant", "content": json.dumps(rejected, separators=(',', ':'))}],
        })

    OUT.write_text("\n".join(json.dumps(p) for p in pairs))
    aux_queued = len(plays)
    print(f"{aux_queued} Aux-queued plays in play_log.jsonl ({len(skips)} skips, {len(finishes)} finishes)")
    print(f"wrote {len(pairs)} skip/finish pairs -> {OUT}")
    if not pairs:
        print("not enough real skip data yet for round 2 -- this is the documented fallback (PRD §16): "
              "run the live app with MODEL=veri so Aux queues its own tracks, then re-run this script.")


if __name__ == "__main__":
    main()
