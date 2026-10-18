"""M6: eval SFT vs DPO vs teacher (base Qwen omitted for now -- see note in
results/metrics.json if present). See PRD.md section 10.

Targets are driven by env vars so this can run with whatever deployments are
actually up at the time:
  TEACHER_MODEL   default claude-sonnet-4-6 (always available via Anthropic)
  VERI_DEP_SFT    deployment id for ssabesan9009/aux-sft (optional)
  VERI_DEP_DPO    deployment id for ssabesan9009/aux-dpo (optional)
  VERI_DEP_BASE   deployment id for raw Qwen/Qwen3-1.7B (optional)
A target with no deployment id set is skipped and noted in the output.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic  # noqa: E402
from openai import OpenAI  # noqa: E402

from app.env import ROOT  # noqa: E402
from app.schemas import VibeSpec  # noqa: E402

SFT_EVAL = ROOT / "data" / "sft_eval.jsonl"
PREFS_EVAL = ROOT / "data" / "prefs_eval.jsonl"
OUT = ROOT / "results" / "metrics.json"

SFT_SAMPLE = int(os.environ.get("EVAL_SFT_SAMPLE", "50"))   # of 99 rows, cap teacher $ cost
CONCURRENCY = 6
TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "claude-sonnet-4-6")

anthropic_client = anthropic.Anthropic()


def _targets() -> dict[str, str | None]:
    t = {"teacher": None}  # teacher needs no dep id, handled separately
    for name, env in [("aux-sft", "VERI_DEP_SFT"), ("aux-dpo", "VERI_DEP_DPO"),
                       ("aux-dpo-v2", "VERI_DEP_DPO2"), ("base", "VERI_DEP_BASE")]:
        dep = os.environ.get(env)
        if dep:
            t[name] = dep
    return t


def call_teacher(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    resp = anthropic_client.messages.parse(
        model=TEACHER_MODEL, max_tokens=400, system=system, output_config={"effort": "low"},
        messages=[{"role": "user", "content": user}], output_format=VibeSpec,
    )
    return resp.parsed_output.model_dump_json(), time.time() - t0


def call_veri(dep_id: str, system: str, user: str) -> tuple[str, float]:
    client = OpenAI(base_url=f"https://api.veri.studio/v1/deployments/{dep_id}", api_key=os.environ["VERI_API_KEY"])
    t0 = time.time()
    resp = client.chat.completions.create(
        model="any", temperature=0.0, max_tokens=400,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},  # see app/model.py note
    )
    return resp.choices[0].message.content, time.time() - t0


def call(name: str, dep_id: str | None, system: str, user: str) -> tuple[VibeSpec | None, float]:
    try:
        raw, dt = (call_teacher(system, user) if name == "teacher" else call_veri(dep_id, system, user))
        return VibeSpec.model_validate_json(raw), dt
    except Exception as e:
        print(f"  [{name}] drop: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr)
        return None, 0.0


def fit(got: VibeSpec, cand: VibeSpec) -> float:
    """How well `got` matches `cand` -- mirrors app/selector.py's scoring exactly, since that's what
    actually decides which track plays. A metric that only looks at energy/valence/bpm (and ignores
    tags) can't tell chosen from rejected on the ~1/3 of pairs that are tag-only contrasts."""
    de = abs(got.energy - cand.energy)
    dv = abs(got.valence - cand.valence)
    dbpm = abs((got.bpm_min + got.bpm_max) / 2 - (cand.bpm_min + cand.bpm_max) / 2) / 60.0
    tag_bonus = 0.25 * len(set(got.tags) & set(cand.tags))
    return -(de + dv + dbpm) + tag_bonus


def eval_sft(name: str, dep_id: str | None, rows: list[dict]) -> dict:
    valid, mae_e, mae_v, mae_b, lat = 0, [], [], [], []
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        futs = {pool.submit(call, name, dep_id, r["messages"][0]["content"], r["messages"][1]["content"]): r
                for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            spec, dt = f.result()
            lat.append(dt)
            if not spec:
                continue
            valid += 1
            truth = VibeSpec.model_validate_json(r["messages"][2]["content"])
            mae_e.append(abs(spec.energy - truth.energy))
            mae_v.append(abs(spec.valence - truth.valence))
            mae_b.append(abs((spec.bpm_min + spec.bpm_max) / 2 - (truth.bpm_min + truth.bpm_max) / 2))
    return {
        "json_validity_pct": round(100 * valid / len(rows), 1),
        "teacher_agreement_mae": {
            "energy": round(mean(mae_e), 3) if mae_e else None,
            "valence": round(mean(mae_v), 3) if mae_v else None,
            "bpm_mid": round(mean(mae_b), 1) if mae_b else None,
        },
        "latency_s": _lat_stats(lat),
        "n": len(rows),
    }


def eval_prefs(name: str, dep_id: str | None, rows: list[dict]) -> dict:
    agree, total = 0, 0
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        futs = {pool.submit(call, name, dep_id, r["prompt"][0]["content"], r["prompt"][1]["content"]): r
                for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            spec, _ = f.result()
            if not spec:
                continue
            total += 1
            chosen = VibeSpec.model_validate_json(r["chosen"][0]["content"])
            rejected = VibeSpec.model_validate_json(r["rejected"][0]["content"])
            if fit(spec, chosen) > fit(spec, rejected):
                agree += 1
    return {"preference_agreement_pct": round(100 * agree / total, 1) if total else None, "n": total}


def _lat_stats(lat: list[float]) -> dict:
    if not lat:
        return {"p50": None, "p95": None}
    s = sorted(lat)
    return {"p50": round(s[len(s) // 2], 3), "p95": round(s[int(len(s) * 0.95)], 3)}


def main():
    targets = _targets()
    print(f"targets: {list(targets.keys())} (skipped: {[n for n in ('aux-sft', 'aux-dpo', 'aux-dpo-v2', 'base') if n not in targets]})")

    sft_rows = [json.loads(l) for l in SFT_EVAL.read_text().splitlines() if l.strip()][:SFT_SAMPLE]
    prefs_rows = [json.loads(l) for l in PREFS_EVAL.read_text().splitlines() if l.strip()]
    print(f"{len(sft_rows)} sft_eval rows, {len(prefs_rows)} prefs_eval rows per target")

    results = {}
    for name, dep_id in targets.items():
        print(f"\n== {name} ==")
        t0 = time.time()
        sft_res = eval_sft(name, dep_id, sft_rows)
        pref_res = eval_prefs(name, dep_id, prefs_rows)
        results[name] = {**sft_res, **pref_res, "wall_s": round(time.time() - t0, 1)}
        print(json.dumps(results[name], indent=2))

    skipped = [n for n in ("aux-sft", "aux-dpo", "aux-dpo-v2", "base") if n not in targets]
    OUT.write_text(json.dumps({"results": results, "skipped_targets": skipped,
                               "note": "skipped targets had no deployment id set (VERI_DEP_SFT/VERI_DEP_DPO/VERI_DEP_BASE)"},
                              indent=2))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
