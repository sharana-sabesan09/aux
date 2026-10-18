"""Teacher-label contexts with a vibe spec. Writes data/sft.jsonl (train) and data/sft_eval.jsonl (100 held out)."""
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic  # noqa: E402

from app.env import ROOT  # noqa: E402
from app.schemas import TAG_VOCAB, VibeSpec  # noqa: E402

CONTEXTS = ROOT / "data" / "contexts.jsonl"
TRAIN = ROOT / "data" / "sft.jsonl"
EVAL = ROOT / "data" / "sft_eval.jsonl"
HOLDOUT = 100
MODEL = os.environ.get("TEACHER_MODEL", "claude-sonnet-4-6")
CONCURRENCY = 10

SYSTEM = ("You are a DJ. Given the listener's context, output only JSON describing the music that fits right now. "
          f"Tags must be from this vocabulary only: {', '.join(TAG_VOCAB)}. Use at most 3 tags. "
          "bpm_max >= bpm_min, both plausible (60-180). dj_line is max 15 words, casual, no quotes.")

client = anthropic.Anthropic()


def label(ctx: str) -> dict | None:
    try:
        resp = client.messages.parse(
            model=MODEL, max_tokens=400, system=SYSTEM, output_config={"effort": "low"},
            messages=[{"role": "user", "content": ctx}], output_format=VibeSpec,
        )
        v = resp.parsed_output
        if v.bpm_max < v.bpm_min or not v.tags:
            return None
        return {
            "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ctx}],
            "answer": json.dumps(v.model_dump(), separators=(",", ":")),
        }
    except Exception as e:
        print(f"  drop: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        return None


def main():
    contexts = [json.loads(l)["context"] for l in CONTEXTS.read_text().splitlines() if l.strip()]
    print(f"{len(contexts)} contexts, labeling with {MODEL} ({CONCURRENCY} concurrent)")
    rows: list[dict] = []
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        futs = [pool.submit(label, c) for c in contexts]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r:
                rows.append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(contexts)} ({len(rows)} valid)")
    random.seed(42)
    random.shuffle(rows)
    eval_rows, train_rows = rows[:HOLDOUT], rows[HOLDOUT:]
    TRAIN.write_text("\n".join(json.dumps(r) for r in train_rows))
    EVAL.write_text("\n".join(json.dumps(r) for r in eval_rows))
    print(f"\n{len(train_rows)} train -> {TRAIN}\n{len(eval_rows)} eval -> {EVAL}")


if __name__ == "__main__":
    main()
