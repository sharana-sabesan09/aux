"""Reward function. Edit me.

The TRL format signature: (prompts, completions, **kwargs) -> list[float].
Return one score per completion. Score range is typically 0.0 - 1.0 but is
not enforced — your training loop weights this however it wants.
"""

from __future__ import annotations


def reward(prompts: list[str], completions: list[str], **kwargs) -> list[float]:
    """Score each completion. Replace this with your actual reward logic."""
    return [1.0 if completion.strip() else 0.0 for completion in completions]
