from typing import Literal

from pydantic import BaseModel

TAG_VOCAB = ["chill", "focus", "hype", "warm", "dreamy", "dark", "acoustic", "electronic", "hip-hop",
             "r&b", "indie", "lo-fi", "jazz", "ambient", "pop", "rock", "funk", "soul", "latin", "k-pop",
             "cinematic", "sad", "romantic", "nostalgic", "party"]
Tag = Literal[tuple(TAG_VOCAB)]


class TrackTags(BaseModel):
    id: int
    energy: float
    valence: float
    bpm_min: int
    bpm_max: int
    tags: list[Tag]
    confidence: Literal["high", "medium", "low"]


class TrackTagBatch(BaseModel):
    tracks: list[TrackTags]


class VibeSpec(BaseModel):
    energy: float
    valence: float
    bpm_min: int
    bpm_max: int
    tags: list[Tag]
    dj_line: str
