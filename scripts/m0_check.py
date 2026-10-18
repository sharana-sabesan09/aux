"""M0: read saved tracks, read playback state, queue one track. Run after logging in at /login."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import spotify  # noqa: E402

tracks = spotify.saved_tracks(cap=50)
print(f"saved tracks (first page): {len(tracks)}")
for t in tracks[:3]:
    print(f"  {t['name']} - {', '.join(a['name'] for a in t['artists'])}")

state = spotify.playback()
if not state or not state.get("device"):
    sys.exit("no active device: open Spotify on your phone or laptop and play something, then rerun")
item = state.get("item") or {}
print(f"playback: device={state['device']['name']} playing={state['is_playing']} "
      f"track={item.get('name')} progress={state.get('progress_ms')}/{item.get('duration_ms')}")

if "--queue" in sys.argv:
    spotify.queue(tracks[0]["uri"])
    print(f"queued: {tracks[0]['name']}")
