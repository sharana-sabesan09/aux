"""M4: convert labels (data/labels.jsonl) + pairs (data/pairs.jsonl) into DPO train/eval JSONL."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.env import ROOT  # noqa: E402
from app.schemas import TAG_VOCAB  # noqa: E402

PAIRS = ROOT / "data" / "pairs.jsonl"
LABELS = ROOT / "data" / "labels.jsonl"
TRAIN = ROOT / "data" / "dpo.jsonl"
EVAL = ROOT / "data" / "prefs_eval.jsonl"
HOLDOUT = 40

SYSTEM = ("You are a DJ. Given the listener's context, output only JSON describing the music that fits right now. "
          f"Tags must be from this vocabulary only: {', '.join(TAG_VOCAB)}. Use at most 3 tags. "
          "bpm_max >= bpm_min, both plausible (60-180). dj_line is max 15 words, casual, no quotes.")


def main():
    pairs = {json.loads(l)["context"]: json.loads(l) for l in PAIRS.read_text().splitlines() if l.strip()}
    labels = [json.loads(l) for l in LABELS.read_text().splitlines() if l.strip()]
    labels = [x for x in labels if x["choice"] in ("A", "B")]
    print(f"{len(labels)} A/B labels, {len(pairs)} pairs")

    rows = []
    for lab in labels:
        p = pairs.get(lab["context"])
        if not p:
            continue
        chosen = p["a"] if lab["choice"] == "A" else p["b"]
        rejected = p["b"] if lab["choice"] == "A" else p["a"]
        # chosen/rejected must be message lists too (matching prompt's shape) — TRL's
        # conversational DPOTrainer does `prompt + chosen`, which crashes if chosen is a bare str.
        rows.append({
            "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": lab["context"]}],
            "chosen": [{"role": "assistant", "content": json.dumps(chosen["spec"], separators=(",", ":"))}],
            "rejected": [{"role": "assistant", "content": json.dumps(rejected["spec"], separators=(",", ":"))}],
        })
    random.seed(42)
    random.shuffle(rows)
    eval_rows, train_rows = rows[:HOLDOUT], rows[HOLDOUT:]
    TRAIN.write_text("\n".join(json.dumps(r) for r in train_rows))
    EVAL.write_text("\n".join(json.dumps(r) for r in eval_rows))
    print(f"{len(train_rows)} train -> {TRAIN}\n{len(eval_rows)} eval -> {EVAL}")


if __name__ == "__main__":
    main()
