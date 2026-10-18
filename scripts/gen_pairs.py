"""M4: build 250 A/B preference pairs. A = teacher spec. B = deliberately shifted spec.
Each spec is resolved to a catalog track via selector. Writes data/pairs.jsonl."""
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic  # noqa: E402

from app import context as ctx_builder  # noqa: E402
from app import selector  # noqa: E402
from app.env import ROOT  # noqa: E402
from app.schemas import TAG_VOCAB, VibeSpec  # noqa: E402

CONTEXTS = ROOT / "data" / "contexts.jsonl"
OUT = ROOT / "data" / "pairs.jsonl"
N = 250
MODEL = os.environ.get("TEACHER_MODEL", "claude-sonnet-4-6")
CONCURRENCY = 10

SYSTEM = ("You are a DJ. Given the listener's context, output only JSON describing the music that fits right now. "
          f"Tags must be from this vocabulary only: {', '.join(TAG_VOCAB)}. Use at most 3 tags. "
          "bpm_max >= bpm_min, both plausible (60-180). dj_line is max 15 words, casual, no quotes.")

client = anthropic.Anthropic()
random.seed(7)


def _flip(x: float, delta: float) -> float:
    return max(0.0, min(1.0, x + delta if random.random() < 0.5 else x - delta))


def shifted(spec: VibeSpec) -> VibeSpec:
    """Deliberate contrast: push energy and valence 0.3+, or swap tags for near-opposites."""
    mode = random.choice(["ev", "ev", "tags"])
    if mode == "ev":
        return VibeSpec(
            energy=_flip(spec.energy, 0.4), valence=_flip(spec.valence, 0.4),
            bpm_min=max(60, spec.bpm_min - 30) if spec.energy > 0.5 else min(170, spec.bpm_max + 20),
            bpm_max=max(80, spec.bpm_max - 20) if spec.energy > 0.5 else min(180, spec.bpm_max + 40),
            tags=spec.tags, dj_line=spec.dj_line,
        )
    pool = [t for t in TAG_VOCAB if t not in spec.tags]
    return VibeSpec(energy=spec.energy, valence=spec.valence,
                    bpm_min=spec.bpm_min, bpm_max=spec.bpm_max,
                    tags=random.sample(pool, k=min(3, len(spec.tags))), dj_line=spec.dj_line)


def label_a(ctx_text: str) -> VibeSpec | None:
    try:
        resp = client.messages.parse(
            model=MODEL, max_tokens=400, system=SYSTEM, output_config={"effort": "low"},
            messages=[{"role": "user", "content": ctx_text}], output_format=VibeSpec,
        )
        v = resp.parsed_output
        if v.bpm_max >= v.bpm_min and v.tags:
            return v
    except Exception as e:
        print(f"  drop: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
    return None


def build_pair(ctx_text: str) -> dict | None:
    a = label_a(ctx_text)
    if not a:
        return None
    b = shifted(a)
    track_a = selector.pick(a, [])
    track_b = selector.pick(b, [])
    if not track_a or not track_b or track_a["uri"] == track_b["uri"]:
        return None
    return {
        "context": ctx_text,
        "a": {"spec": a.model_dump(), "track": track_a},
        "b": {"spec": b.model_dump(), "track": track_b},
    }


def main():
    pool = [json.loads(l)["context"] for l in CONTEXTS.read_text().splitlines() if l.strip()]
    random.shuffle(pool)
    pool = pool[: N * 2]
    print(f"building up to {N} pairs from {len(pool)} candidate contexts ({MODEL})")

    pairs: list[dict] = []
    with ThreadPoolExecutor(CONCURRENCY) as pool_x:
        futs = [pool_x.submit(build_pair, c) for c in pool]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r:
                pairs.append(r)
            if i % 25 == 0:
                print(f"  {i}/{len(pool)} ({len(pairs)} valid)")
            if len(pairs) >= N:
                break
    pairs = pairs[:N]
    OUT.write_text("\n".join(json.dumps(p) for p in pairs))
    print(f"\nwrote {len(pairs)} pairs -> {OUT}")


if __name__ == "__main__":
    main()
