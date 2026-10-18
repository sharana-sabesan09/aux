"""M1: pull saved + top tracks, teacher-tag them, write data/catalog.json. Rerunnable: already-tagged URIs are skipped."""
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic  # noqa: E402

from app import spotify  # noqa: E402
from app.env import ROOT  # noqa: E402
from app.schemas import TAG_VOCAB, TrackTagBatch  # noqa: E402

CAP, BATCH, MIN_CATALOG = 600, 25, 200
OUT = ROOT / "data" / "catalog.json"
MODEL = os.environ.get("TEACHER_MODEL", "claude-opus-5-5")

SYSTEM = f"""You tag songs for a DJ app. For each track, estimate:
- energy 0.0-1.0 (intensity, loudness, drive), valence 0.0-1.0 (musical positivity)
- bpm_min/bpm_max: a plausible tempo range, at most 20 BPM wide
- tags: 1-3 from this vocabulary only: {", ".join(TAG_VOCAB)}
- confidence: "high" if you know the song, "medium" if you know the artist well, "low" if you are estimating
from the artist, album, title and era alone. Never skip a track. Return every id you were given."""

client = anthropic.Anthropic()


def fetch_tracks() -> list[dict]:
    seen: dict[str, dict] = {}
    for t in spotify.top_tracks("short_term") + spotify.top_tracks("medium_term") + spotify.saved_tracks(CAP):
        if t.get("uri", "").startswith("spotify:track:") and t["uri"] not in seen:
            seen[t["uri"]] = {
                "uri": t["uri"], "name": t["name"], "artists": [a["name"] for a in t["artists"]],
                "album": t["album"]["name"], "year": (t["album"].get("release_date") or "")[:4],
                "duration_ms": t["duration_ms"], "explicit": t["explicit"],
                "art": (t["album"].get("images") or [{}])[0].get("url"),
            }
    return list(seen.values())[:CAP]


def tag_batch(batch: list[dict]) -> list[dict]:
    lines = "\n".join(f'{i}. "{t["name"]}" - {", ".join(t["artists"])} | album: {t["album"]} ({t["year"]})'
                      for i, t in enumerate(batch))
    resp = client.messages.parse(
        model=MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "low"},
        messages=[{"role": "user", "content": lines}], output_format=TrackTagBatch,
    )
    out = []
    for tag in resp.parsed_output.tracks:
        if 0 <= tag.id < len(batch):
            t = batch[tag.id]
            out.append({**t, **tag.model_dump(exclude={"id"}),
                        "energy": min(max(tag.energy, 0.0), 1.0), "valence": min(max(tag.valence, 0.0), 1.0),
                        "tags": list(dict.fromkeys(tag.tags))[:3]})
    return out


def main():
    existing = {t["uri"]: t for t in json.loads(OUT.read_text())} if OUT.exists() else {}
    tracks = fetch_tracks()
    todo = [t for t in tracks if t["uri"] not in existing]
    print(f"{len(tracks)} unique tracks, {len(todo)} to tag with {MODEL}")

    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    OUT.parent.mkdir(exist_ok=True)
    with ThreadPoolExecutor(5) as pool:
        for n, tagged in enumerate(pool.map(tag_batch, batches), 1):
            existing.update({t["uri"]: t for t in tagged})
            OUT.write_text(json.dumps(list(existing.values()), indent=1))  # save per batch; reruns resume
            print(f"  batch {n}/{len(batches)}: {len(tagged)} tagged")

    catalog = list(existing.values())
    missed = len(tracks) - len(catalog)
    confident = [t for t in catalog if t["confidence"] != "low"]
    kept = confident if len(confident) >= MIN_CATALOG else catalog

    (OUT.parent / "catalog_kept.json").write_text(json.dumps([t["uri"] for t in kept]))

    conf = Counter(t["confidence"] for t in catalog)
    print(f"\ncatalog: {len(catalog)} tagged ({missed} missed), confidence {dict(conf)}")
    print(f"kept for selection: {len(kept)}" + (" (lows dropped)" if kept is confident else " (lows kept: would fall under 200)"))
    cov = Counter(tag for t in kept for tag in t["tags"])
    print("tag coverage:")
    for tag in TAG_VOCAB:
        print(f"  {tag:<11}{cov[tag]:>4}" + ("   <-- under 8" if cov[tag] < 8 else ""))


if __name__ == "__main__":
    main()
