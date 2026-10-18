"""Vibe-spec generation. MODEL=teacher -> Anthropic. MODEL=veri -> OpenAI-compat Veri deployment."""
import json
import os

import anthropic
from openai import OpenAI

from app.schemas import TAG_VOCAB, VibeSpec

SYSTEM = ("You are a DJ. Given the listener's context, output only JSON describing the music that fits right now. "
          f"Tags must be from this vocabulary only: {', '.join(TAG_VOCAB)}. Use at most 3 tags. "
          "bpm_max >= bpm_min, both plausible (60-180). dj_line is max 15 words, casual, no quotes.")

_last_good: VibeSpec | None = None


def _teacher(ctx_text: str) -> VibeSpec:
    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=os.environ.get("TEACHER_MODEL", "claude-sonnet-4-6"),
        max_tokens=400, system=SYSTEM, output_config={"effort": "low"},
        messages=[{"role": "user", "content": ctx_text}], output_format=VibeSpec,
    )
    return resp.parsed_output


def _veri(ctx_text: str) -> VibeSpec:
    dep = os.environ["VERI_DEP_ID"]
    client = OpenAI(base_url=f"https://api.veri.studio/v1/deployments/{dep}",
                    api_key=os.environ["VERI_API_KEY"])
    resp = client.chat.completions.create(
        model="any", temperature=0.0, max_tokens=400,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": ctx_text}],
        # Qwen3 defaults to hybrid "thinking" mode, wrapping output in <think>...</think> before the
        # real JSON -- our SFT/DPO data has no think tags, so the trained model is inconsistent about
        # emitting them. Disable at the template level rather than regex-stripping after the fact.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return VibeSpec.model_validate_json(resp.choices[0].message.content)


def vibe(ctx_text: str) -> VibeSpec:
    global _last_good
    backend = os.environ.get("MODEL", "teacher")
    fn = _veri if backend == "veri" else _teacher
    for _ in range(2):
        try:
            spec = fn(ctx_text)
            if spec.bpm_max >= spec.bpm_min and spec.tags:
                _last_good = spec
                return spec
        except Exception as e:
            print(f"vibe retry: {type(e).__name__}: {str(e)[:120]}")
    if _last_good:
        return _last_good
    return VibeSpec(energy=0.5, valence=0.5, bpm_min=90, bpm_max=110, tags=["chill"], dj_line="")
