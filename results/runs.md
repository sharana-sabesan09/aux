# Veri job log

| Milestone | Job id | Base | Dataset | Method | GPU | Status | HF repo |
|---|---|---|---|---|---|---|---|
| M2 SFT | `53927cfc068a` | Qwen/Qwen3-1.7B | `fcf6d7b6cea4` (aux-sft-chat, 899 rows) | sft_text, 2 ep, LoRA r=16 | 1x L4-24GB (aws) | completed ($0.58) | `ssabesan9009/aux-sft` (merged, public) |
| M4 DPO r1 (attempt 1) | `911873452893` | ssabesan9009/aux-sft | `da09bd52344f` (aux-dpo, wrong chosen/rejected shape) | dpo, 2 ep, LoRA r=16, beta=0.1 | 1x L4-24GB (aws) | **failed** ($0.34) — `training_error`: TRL `prompt`(list) + `chosen`(str) TypeError | `ssabesan9009/aux-dpo` |
| M4 DPO r1 (attempt 2) | `47eb49878460` | ssabesan9009/aux-sft | `e1ddfb7b1f42` (aux-dpo-v2, 158 rows, chosen/rejected as message lists) | dpo, 2 ep, LoRA r=16, beta=0.1 | 1x L4-24GB (aws) | **completed ($0.41)** | `ssabesan9009/aux-dpo` (merged, public) |

## Datasets
- `125dd4bf12ec` aux-sft (prompt+answer, wrong format, kept for reference)
- `fcf6d7b6cea4` aux-sft-chat (messages, 899 rows)
- `da09bd52344f` aux-dpo (prompt/chosen/rejected, 158 rows, chosen/rejected as plain strings — broke TRL, superseded)
- `e1ddfb7b1f42` aux-dpo-v2 (prompt/chosen/rejected, 158 rows, chosen/rejected as message lists; `data/prefs_eval.jsonl` holds the 40-row eval split)

## Deployments
| Name | Id | Model | Purpose | Status | Cost |
|---|---|---|---|---|---|
| aux-dpo | `aadf1250fda7` | ssabesan9009/aux-dpo | live app (`MODEL=veri`, `VERI_DEP_ID`) | **serving**, min_replicas=0 | ~$1.05/hr while up |
| aux-sft-eval | `95cd0a6328fa` | ssabesan9009/aux-sft | one-off, for the eval comparison only | stopped | $0.35 total, 130 requests |

**Bug found + fixed during eval:** Qwen3 defaults to "thinking mode," wrapping JSON output in
`<think>...</think>` which breaks strict parsing — 89/90 raw calls failed before the fix. Fixed by
passing `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` on every chat-completions
call in both `app/model.py` and `scripts/eval.py`. Would have broken the live demo if caught late.

## M6 Eval (`scripts/eval.py`, `results/metrics.json`)
50 `sft_eval.jsonl` rows + all 40 `prefs_eval.jsonl` rows per target, teacher = claude-sonnet-4-6.

| Target | JSON validity | Teacher-agreement MAE (e/v/bpm_mid) | Preference agreement | Latency p50/p95 |
|---|---|---|---|---|
| teacher | 100% | 0.018 / 0.013 / 2.0 | 45.0% (18/40) | 1.88s / 2.28s |
| aux-sft | 100% | 0.087 / 0.048 / 8.6 | 45.0% (18/40) | 1.12s / 1.23s |
| aux-dpo | 100% | 0.075 / 0.041 / 8.3 | 45.0% (18/40) | 1.12s / 1.17s |

**Honest finding:** all three tie on preference agreement. Row-by-row verification (38/40 rows) shows
this isn't a bug — the three models give genuinely different numeric specs per row, but land on the
same side of the chosen/rejected split almost every time. All three derive from the same Qwen3-1.7B
base and share a "stay sensible, context-appropriate" prior; 158 DPO pairs didn't clearly shift that
prior toward the user's actual (sometimes more extreme) picks on this held-out set. Per PRD §16's own
risk note: SFT gains (validity, 5-8x lower latency and far cheaper than the teacher API) still stand
on their own; DPO round 1 needs either more pairs, more epochs, or a higher `beta`/lr to show a
measurable lift — worth trying if there's time before the deadline.

## DPO v2 experiment (stretch attempt at a measurable lift)
Tried `beta=0.3` + 4 epochs (vs. round 1's `beta=0.1` + 2 epochs) on the *same* 158 synthetic pairs,
to see if a stronger push could break the 45% tie. Job `60d284f1def7`, completed ($0.45), published to
`ssabesan9009/aux-dpo-v2`. Deployed a temporary eval-only endpoint (`c4b9f0a174c5`, $0.65 total,
90 requests), ran `scripts/eval.py` against it, then stopped (not deleted) it.

| Target | JSON validity | Teacher-agreement MAE (e/v/bpm_mid) | Preference agreement | Latency p50/p95 |
|---|---|---|---|---|
| aux-dpo-v2 | 100% | 0.101 / 0.063 / 9.4 | 45.0% (18/40) | 1.16s / 1.44s |

**Result: still ties at 45.0%, with slightly worse teacher-agreement MAE than round 1's aux-dpo
(0.075/0.041/8.3).** Confirms the earlier finding — the ceiling here isn't a beta/epoch tuning problem,
it's that all 158 training pairs are synthetic (teacher-valid spec vs. a programmatically shifted
"wrong" one), so there's no real taste signal beyond what SFT already captured, no matter how hard DPO
pushes on them. Round 2 (real skips) is the only path likely to move this number. Not pursuing further
hyperparameter sweeps on synthetic data — diminishing returns given the deadline.

## M7 Round 2 (blocked)
`scripts/skips_to_pairs.py` written and tested — correctly finds **0 usable pairs** right now.
`data/play_log.jsonl` has 7 plays, but all `queued_by_aux: false` (self-started, not Aux's picks),
which per PRD §8.3 are never used as training negatives. Round 2 needs the live app actually running
with `MODEL=veri` while Spotify plays, so Aux queues its own tracks and some get skipped. This can't
be faked or run unattended — needs the user there with Spotify active.
