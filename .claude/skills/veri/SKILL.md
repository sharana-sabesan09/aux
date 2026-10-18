---
name: veri-lahacks
description: Train, deploy, and serve open language models on Veri (api.veri.studio) at LA Hacks 2026. Covers CLI and MCP setup, what GPUs are available this weekend, fine-tuning (SFT, DPO, GRPO), harness-in-the-loop RL, OpenAI-compatible inference deployments, datasets, the REST API, and the pitfalls that cost hackathon teams time and credits. Use whenever the user mentions Veri, veri.toml, the veri CLI, or wants to fine-tune, RL-train, or serve a model.
---

# Veri at LA Hacks 2026

Veri rents GPUs for post-training and serving open models. One CLI (`veri`), one REST API
(`https://api.veri.studio`, Bearer auth with `vk_...` keys), TOML configs. Ids are bare hex
strings. Full docs: https://docs.veri.studio (index: https://docs.veri.studio/llms.txt).

## 1. Setup (do this first)

```bash
uv tool install --upgrade 'veri-sdk[mcp]'   # or: pipx install --force 'veri-sdk[mcp]'  /  pip install 'veri-sdk[mcp]' (Python 3.10+, in a venv)
veri version                                # need sdk_version >= 0.2.44
veri login                                  # opens a browser tab: sign in, click Authorize. Headless: veri login --token vk_...
veri whoami                                 # status must NOT be invalid_or_expired_token
veri doctor                                 # if anything above failed
```

The `[mcp]` extra matters: without it `veri mcp serve` exits and MCP clients only show
"Connection closed". Installing another extra alone (`veri-sdk[attach]`) removes it; use
`'veri-sdk[all]'` if you need more than `mcp`.

Env vars `VERI_API_KEY` / `VERI_API_URL` override the config file
(`~/Library/Application Support/veri/config.toml` on macOS, `~/.config/veri/config.toml` on Linux).
Every command takes `--format json|jsonl|csv|table` and `--quiet`.

### Veri MCP server (optional, lets your agent drive Veri through tools)

Local (uses your `veri login` credentials, no key in config files):

```bash
claude mcp add veri -- veri mcp serve            # Claude Code; add --readonly to drop the 12 write/delete tools
veri mcp serve --readonly </dev/null             # sanity check: exits 0 if the server can start
```

Cursor (`.cursor/mcp.json`): `{"mcpServers": {"veri": {"command": "veri", "args": ["mcp", "serve"]}}}`.

Hosted (no local install): `https://api.veri.studio/mcp` and read-only `https://api.veri.studio/readonly/mcp`,
header `Authorization: Bearer $VERI_API_KEY` (export it first; `veri login` does not set it).
Example: `claude mcp add --transport http veri https://api.veri.studio/mcp --header "Authorization: Bearer $VERI_API_KEY"`.
Never commit a key: in Cursor use `${env:VERI_API_KEY}`.

## 2. What is available this weekend

| Provider | GPU | GPUs per box | $/GPU-hour | Train | Serve | Rough availability |
| --- | --- | --- | --- | --- | --- | --- |
| `aws` (default) | L4-24GB | 1, 4 | $1.05 | yes | yes | 1x: plenty (dozens at once). 4x: scarce, a few at a time, shared by everyone. |
| `aws` | A10G-24GB | 1, 4 | $1.31 | yes | yes | Same pool as L4. |
| `aws` | A100-80GB, H100-80GB | 8 only (you pay for all 8) | $4.46 / $8.94 | yes | yes | Rare: expect `CAPACITY_UNAVAILABLE`. |
| `vast` | A100-80GB, H100-80GB | 1, 2, 4, 8 | about $1.39 / $3.36 (marketplace, varies) | yes | no | Usually free. Boots slower (5 to 15 min). `H100-80GB x2` is the proven harness-RL shape. |
| `digitalocean` | H100-80GB | 1 | $5.73 | yes | yes | Flaps: often none free for long stretches. |
| `digitalocean` | H200-141GB | 1 | $5.81 | yes | yes | Usually free (atl1, nyc2). 141 GB fits 32B in bf16 or 70B in fp8 on one GPU. |
| `gcp` | | | | coming soon | coming soon | Not available (400). |

DigitalOcean is a few droplets shared by every team: when they are all in use, submits fail
with `QUOTA_EXCEEDED`. The availability column is a weekend estimate; live truth beats it:
`veri gpu list` (catalog: shapes and prices), `veri gpu list --provider digitalocean` (live,
also `--provider vast` / `--provider aws --region us-west-2`), `veri gpu describe H200-141GB`,
`veri jobs estimate configs/train.toml` (price before you spend).

Defaults that fit the weekend:

- 1x L4 for SFT, DPO and GRPO on models up to about 4B parameters (`Qwen/Qwen3-0.6B`, `Qwen3-1.7B`, `Qwen3-4B`). Use `lora_rank` or `load_in_4bit` if you OOM.
- Harness RL needs 2+ GPUs on one node: `--gpu-type L4-24GB --gpu-count 4` on AWS (scarce) or `--gpu-type H100-80GB --gpu-count 2 --provider vast`.
- Inference: 1x L4 serves models up to about 4B. Use `--min-replicas 0` so idle deployments scale to zero and stop billing.

### Getting unstuck (capacity, quota, waiting)

Nothing moves between providers or GPU types automatically: you choose, and the errors tell
you what to choose. Work down this list:

1. **Read the code, not just the status.** `veri jobs get <id> --format json` gives
   `error.code` and `error.message`; for a deployment, `veri deployments get <id> --format json`
   gives `failure_code` and `error` (match the code in any case: some are lowercase).
2. **`CAPACITY_UNAVAILABLE`** (no free box for that shape anywhere it can launch) or
   **`QUOTA_EXCEEDED`** (the platform's GPUs on that provider are all in use): nothing booted,
   nothing was billed. The message ends with
   `Alternatives: --provider P --gpu-type G --gpu-count N; ...`, the cheapest live shapes with
   at least as much GPU memory. Resubmit with one of them:
   `veri deploy <model> --provider P --gpu-type G --gpu-count N --no-cache` for serving,
   `veri jobs create configs/train.toml --set provider.name=P --gpu-type G --gpu-count N` for
   training.
3. **Retry the same shape only a few times.** Boxes free up as other teams finish: wait about
   2, then 5, then 10 minutes, at most 3 tries. After `QUOTA_EXCEEDED` skip this step and go
   straight to another provider.
4. **Shrink or move.** 4x to 1x (add `lora_rank` or `load_in_4bit` so it fits); AWS 4x L4 to
   `vast` H100 x2 for harness RL; a big model to `digitalocean` H200 x1; for AWS shapes the
   other region (`--region us-west-2` or `us-east-1`, see `veri regions list`).
5. **Waiting is normal for a while.** A job goes `queued`, `provisioning`, `configuring`,
   `running`: AWS and DigitalOcean usually boot in about 5 minutes, Vast in 5 to 15.
   Stuck past about 20 minutes? Check `veri jobs logs <id>`, then `veri jobs cancel <id>` and
   resubmit on another shape.
6. **Never retry unchanged:** `config_error` or `dependency_error` (fix the config first), a 400
   that says "not currently enabled" or "coming soon" (pick a live provider), a 429 limit code
   (free capacity first, below), a 402 (out of credit). `RATE_LIMITED`: wait
   `retry_after_seconds`. A chat that returns 503 `deployment_waking`: wait `Retry-After`, resend.

Per-account limits: 4 in-flight training jobs, 2 active deployment replicas. Hitting one is a
429 with a code (`CONCURRENT_JOB_LIMIT`, `ACTIVE_DEPLOYMENT_LIMIT`): cancel or stop something,
then resubmit. Retrying alone never clears it.

Credits: DM @daniung in the LA Hacks Discord for a code, redeem it at
https://www.veri.studio/settings/billing. `veri billing balance` shows what is left. A job on
a $0 balance boots and is then killed (`insufficient_credits`).

## 3. The 10-minute path

```bash
veri init myproj && cd myproj                       # configs/train.toml, configs/deploy.toml, reward.py, AGENTS.md
veri datasets check ./train.jsonl                   # local format check
veri datasets upload ./train.jsonl --name my-train  # prints the dataset id; put it in configs/train.toml
veri jobs estimate configs/train.toml               # price; nothing is submitted
veri run configs/train.toml --follow                # submit + stream logs (Ctrl+C detaches, the job keeps running)
veri jobs get <id>                                  # status, error.code if it failed
veri deployments create --model <job_id> --name mymodel --gpu-type L4-24GB --min-replicas 0 --max-replicas 1
veri deployments chat <dep_id> --message "hello"
veri deployments stop <dep_id>                      # when done; stop is immediate and permanent
```

A submit that fails validation (bad method, unknown model, unsellable GPU shape, missing dataset)
returns a 400 and creates nothing. Read the message: it lists the supported values.

## 4. Datasets

JSONL rows with a `prompt` column (a string or an OpenAI-style message list) and usually `answer`.
Use ONE prompt format per file (mixing strings and message lists crashes the trainer after the
GPU boots).

```json
{"prompt": [{"role": "user", "content": "What is 12 + 7?"}], "answer": "19"}
```

Chat, ShareGPT, Alpaca, plain-text, prompt-completion and preference (`prompt`, `chosen`,
`rejected` for DPO) formats are auto-detected.

```bash
veri datasets upload ./train.jsonl --name my-train
veri datasets connect-hf openai/gsm8k --config main --split train --map question=prompt   # public HF datasets only
veri datasets list | veri datasets get <id>
```

`connect-hf` does not validate the repo, config or column names; a typo surfaces when the job
starts. Check the dataset card first. Docs: https://docs.veri.studio/training/datasets

## 5. Training

Methods: `sft_text`, `dpo` (no reward), `grpo` (needs a reward), `grpo_harness` (needs a reward;
submit with `veri run-harness`). `grpo_agentic` is not runnable (400).

```toml
# configs/train.toml
kind = "train"
[job]        name = "my-run"
[model]      base = "Qwen/Qwen3-1.7B"
[dataset]    id = "<dataset id>"
[reward]     file = "./reward.py"              # grpo only
[method]     type = "grpo"; learning_rate = 1e-6; max_steps = 100; rollouts_per_prompt = 4
[resources]  gpu_type = "L4-24GB"; gpu_count = 1
[provider]   name = "aws"                      # or "vast" / "digitalocean"
```

Defaults: grpo lr 1e-6, rollouts_per_prompt 8, max_steps 100 (one prompt per step),
max_response_length 2048; sft_text lr 2e-5, num_epochs 1; dpo lr 5e-6, beta 0.1. LoRA via
`lora_rank`/`lora_alpha`; QLoRA via `load_in_4bit`. Override anything: `--set method.max_steps=50`.

**Training with LoRA? Push merged weights to Hugging Face at the end of the run** (a LoRA job's
final checkpoint is the adapter alone, which `veri deployments create --model <job_id>` cannot
serve yet). Run `veri hf set` once with your HF token, then add to `configs/train.toml`:

```toml
[hf_push]
repo = "<your-hf-username>/my-model"
artifact = "merged"      # standalone weights: serve on Veri or anywhere else
private = false          # Veri serving boxes have no HF token, so keep the repo public
```

When the job completes, `veri deploy <your-hf-username>/my-model --gpu-type L4-24GB --no-cache`
serves it on Veri; the same repo also runs in vLLM, Ollama or `transformers` on your own GPU.
Full fine-tunes (no `lora_rank`) deploy in one step with `--model <job_id>` and need none of this.

```bash
veri jobs create configs/train.toml --follow
veri jobs logs <id> -f
veri jobs download <id> --output-dir ./checkpoints
veri jobs cancel <id>
```

Reward function (GRPO): TRL signature, attached inline as source text. It runs inside the
trainer with no timeout; keep it fast, deterministic, no network. Name it `reward`.

```python
def reward(completions, answer, **kwargs) -> list[float]:
    out = []
    for c, a in zip(completions, answer):
        text = c if isinstance(c, str) else c[-1]["content"]   # completions may be message lists
        out.append(1.0 if a.strip() in text else 0.0)
    return out
```

The scaffolded `reward.py` gives every non-empty completion the same score: GRPO learns nothing
from it. Replace it with a real signal before spending GPU time.

When a job fails, read `error.code` first (`veri jobs get <id>`), then the log:
`oom` lower `micro_batch_size` / sequence length or use `lora_rank`; `config_error` fix the config,
never resubmit unchanged; `CAPACITY_UNAVAILABLE` / `provisioning_*` resubmit or change GPU;
`hardware_error` / `distributed_error` resubmit once, then report the job id to us.

Docs: https://docs.veri.studio/training · https://docs.veri.studio/training/grpo ·
https://docs.veri.studio/training/sft · https://docs.veri.studio/training/dpo

### Harness-in-the-loop RL (train the model inside your own agent)

GRPO-trains a policy while YOUR agent code drives the rollouts, unmodified. Each rollout the
platform injects `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` (the in-training policy),
`VERI_TASK_INPUT` (one dataset row's `prompt`, JSON) and `VERI_POLICY_MODEL` (the model name to
send). Your agent runs, exits, and the reward scores the final assistant message.

```bash
veri run-harness ./harness --entrypoint "python agent.py" \
  --base-model Qwen/Qwen3-4B --dataset-id <dataset id> --reward ./reward.py \
  --gpu-type H100-80GB --gpu-count 2 --provider vast \
  --rollouts-per-prompt 4 --max-steps 20 --requirements ./harness/requirements.txt
```

Rules: `--gpu-count` must be 2 to 8 (the default 1 is rejected); policy ceiling about 7-8B;
every task must be winnable with the agent's tools or it contributes zero signal at full price;
Anthropic-SDK agents use `--harness-protocol anthropic`. Expect queueing: few 2+ GPU boxes exist.
Docs: https://docs.veri.studio/training/harness · https://docs.veri.studio/demos/harness-url-extraction-agent

## 6. Deployments (inference)

```bash
veri deploy Qwen/Qwen3-4B --gpu-type L4-24GB --no-cache                    # one-step HF deploy
veri deployments create --from-hf Qwen/Qwen3-4B --name qwen --gpu-type L4-24GB --min-replicas 0 --max-replicas 1
veri deployments create --model <job_id> --name mine --gpu-type L4-24GB --min-replicas 0
veri deployments list | get <id> | wake <id> | stop <id>
```

- Always pass `--gpu-type`; `veri deploy` prompts for `--cache/--no-cache` on a TTY, so pass one.
- A LoRA-trained job cannot be deployed directly (400): set `[hf_push]` with `artifact = "merged"` and `private = false` at submit (see section 5), then `veri deploy <your-hf-repo>`; or train without `lora_rank`.
- Use ungated HF models (Qwen, Llama-3.2 community mirrors are fine, gated `meta-llama/*` fails after the box boots and bills).
- Serving runs on AWS L4/A10G (1x, 4x). `vast` is training-only. Other serving providers return 400 "not currently enabled".
- `--min-replicas 0` scales to zero after `scale_to_zero_window` (default 3600 s, min 300). A deployment with `min_replicas` 1 bills until you stop it. `stop` is immediate and permanent.
- Tool calling needs vLLM flags: `--vllm-arg=--enable-auto-tool-choice --vllm-arg=--tool-call-parser --vllm-arg=hermes`.

OpenAI-compatible endpoint:

```python
from openai import OpenAI
client = OpenAI(base_url=f"https://api.veri.studio/v1/deployments/{dep_id}", api_key="vk_...")
resp = client.chat.completions.create(model="any", messages=[{"role": "user", "content": "hi"}], stream=True)
```

Anthropic clients: `POST /v1/deployments/{id}/messages`. A scaled-to-zero deployment answers
the first request with 503 + `Retry-After` (`deployment_waking`): retry until warm, or
`veri deployments wake <id>` first. `GET .../models` is not served; call chat directly.
Observability: send `X-Veri-Agent` and `X-Veri-Thread-Id` headers to group requests per agent
and conversation. Docs: https://docs.veri.studio/deployments · https://docs.veri.studio/deployments/openai-compat

## 7. REST API essentials

Base `https://api.veri.studio`, header `Authorization: Bearer vk_...`. Public spec:
`GET https://api.veri.studio/openapi.json` (no auth). Errors are JSON `{"error": {"message", "code"?}}`:
400 invalid or not enabled, 401 bad key, 402 no billing account, 404 not found or not yours,
409 wrong state or still referenced, 429 always with a `code` (a cap, or `RATE_LIMITED` with
`retry_after_seconds`; 120 requests per 60 s per key), 503 + `Retry-After` while a deployment wakes.
Lists take `limit` and an `after` cursor and return `has_more`.

Main resources:

- `GET /v1/me`
- `/v1/datasets` (POST multipart upload, GET, DELETE; `POST /v1/datasets/connect` for HF)
- `/v1/training_jobs` (POST create, GET, `/logs`, `/logs/full`, `/events`, `/metrics`, `/cancel`, `/model`, `/checkpoints`, `/trajectories`, DELETE)
- `/v1/deployments` (POST, GET, `/chat/completions`, `/messages`, `/stop`, `/wake`, `/replicas`, `/requests`, `/traces`, DELETE)
- `/v1/models` (library, `/push-to-hf`), `/v1/volumes`, `/v1/evaluators`, `/v1/experiments`, `/v1/scores`, `/v1/monitors`
- `/v1/environments`, `/v1/sessions`, `/v1/skills`, `/v1/secrets`, `/v1/triggers` (managed agent sandboxes)
- `/v1/webhooks` (lifecycle events, Standard Webhooks signatures), `/v1/metrics/export` (Prometheus)
- `/v1/billing/balance`, `/v1/billing/burn_rate`, `/v1/billing/transactions`, `/v1/credits/redeem`
- `/v1/gpu/catalog`, `/v1/gpu/availability`, `/v1/cost/estimate`, `/v1/cost/rates` (public), `/v1/regions`

Python SDK: `from veri_sdk import Client`; `client.training_jobs.create_from_config(...)`,
`client.deployments.create(...)`, `client.datasets.upload(...)`. Full reference:
https://docs.veri.studio/api-reference/introduction

## 8. Common pitfalls (each one has cost a team time or credits)

1. Installing without `[mcp]`, then wondering why the MCP server shows "Connection closed".
2. No credits redeemed: the job boots, bills for a minute, and dies with `insufficient_credits`.
3. Leaving a deployment with `min_replicas` 1 running overnight. Scale to zero or stop it.
4. Asking for H100/A100 on AWS: those are 8-GPU nodes only. Use L4 (AWS), or H100 on `vast` / `digitalocean`.
5. `veri run-harness` with the default `--gpu-count 1`: rejected, it needs 2+.
6. A mixed-format JSONL (string prompts and message-list prompts in one file): the trainer crashes after the GPU boots.
7. A gated Hugging Face model in a deployment: boots, bills, then fails on download. Use an ungated model.
8. Retry-looping a 429 cap code. Cancel or stop something first.
9. `veri train` (the `@training_job` decorator flow) stays attached: Ctrl+C cancels the job and a dropped connection stops it after 300 s. Use `--detach`, then `veri jobs logs <id> -f`.
10. Reward functions that score everything the same, or that call the network. GRPO needs a real, fast signal.
11. `connect-hf` with the wrong `--config` or column name: nothing checks it until the job starts.
12. Deleting things without looking: `veri jobs|datasets|deployments|models delete` are permanent and do not prompt.

## 9. Ground rules for agents

1. Run `veri whoami` before anything else; fix auth first.
2. Price before you spend: `veri jobs estimate <config>`. GPU time is real money from the team's credits.
3. Never leave deployments running: `--min-replicas 0`, and `veri deployments stop` when done. List deployments at the end of every session.
4. Prefer `--format json --quiet` when parsing output.
5. A 400 that says "not currently enabled" means the provider or feature is off. Pick a live alternative; do not retry.
6. Confirm with the user before deleting anything you did not create in this session.

## 10. When stuck

1. `veri <command> --help` is authoritative for the installed version; `veri doctor` for install, auth and network.
2. Docs: https://docs.veri.studio (quickstart, cli, cli/reference, training, deployments, api-reference). Index for agents: https://docs.veri.studio/llms.txt
3. Read the error body; Veri 400s explain themselves and list supported values.
4. People: DM @daniung in the LA Hacks Discord, or find the Veri table.