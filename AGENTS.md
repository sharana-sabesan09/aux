# AGENTS.md

Project layout for coding agents (Cursor, Claude Code, OpenHands, etc.).

## Directory contract

- `veri.toml`: project marker (name). Configs do not inherit from it.
- `configs/train.toml`: training run config (`kind = "train"`).
- `configs/deploy.toml`: inference deployment config (`kind = "deploy"`).
- `reward.py`: reward function for RL training. See file for the TRL signature.
- `datasets/`: local JSONL datasets (or `veri datasets connect-hf` to register a public
  Hugging Face dataset).

## How to run

```bash
veri datasets connect-hf openai/gsm8k --config main --split train --map question=prompt --name gsm8k-train
veri jobs estimate configs/train.toml   # price the job, nothing submitted
veri run configs/train.toml             # submit a training job (kind dispatches)
veri jobs logs <id> --follow            # tail logs
veri run configs/deploy.toml            # bring up an inference endpoint (set deployment.model first)
```

## Conventions

- All TOML configs start with `kind = "..."` so `veri run` knows what to dispatch.
- Override config values from CLI with `--set <dotted.key>=<value>`. Use `--set-string` to force string type for numeric-looking values.
- A submit that fails validation creates nothing and costs nothing. Use `veri jobs estimate <config>` to price a job before submitting it.
- Default output is a Rich table. Pass `--format json` for machine output, `--quiet` for pipe-friendly ID-only output.
