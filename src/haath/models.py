"""Data shapes: the transcript Whisper hears, and the recipe card Gemma writes.

`Recipe.model_json_schema(mode="serialization")` is passed to Ollama as `format`,
so the model's reply is grammar-constrained to valid JSON of exactly this shape.
All fields have defaults (lenient when parsing) but are *required* in that schema.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Confidence = Literal["low", "med", "high"]


class _Strict(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True, extra="ignore")


class Ingredient(_Strict):
    name: str = Field("", description="Ingredient name in simple English, with her word in brackets if different, e.g. 'Turmeric (haldi)'.")
    her_words: str = Field("", description="Her exact phrase for the amount, copied character-for-character from the transcript, e.g. 'ek mutthi atta'. Empty if she gave no amount.")
    approx: str = Field("", description="Your approximate measure, e.g. '~1 cup / 120 g'. Always start with '~'. Empty if you cannot estimate.")
    confidence: Confidence = Field("low", description="How confident the approximate measure is.")

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> str:
        v = str(v or "low").strip().lower()
        if v.startswith("h"):
            return "high"
        if v.startswith("m"):
            return "med"
        return "low"


class Step(_Strict):
    text: str = Field("", description="One clear step in simple English.")
    her_cue: str = Field("", description="The sensory cue in her exact words from the transcript, e.g. 'jab tak tel chhod de'. Empty if none.")
    start_sec: float = Field(0.0, description="Start time in seconds of the transcript line where she explains this step.")

    @field_validator("start_sec", mode="before")
    @classmethod
    def _sec(cls, v: Any) -> float:
        return parse_seconds(v)


class Recipe(_Strict):
    dish: str = Field("", description="Dish name.")
    cook: str = Field("", description="Who is cooking, e.g. 'Mummy', 'Nani'.")
    story: str = Field("", description="One line about the dish's origin, occasion or who loved it — only if she said so. Otherwise empty.")
    ingredients: list[Ingredient] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list, description="Tips she mentioned.")
    warnings: list[str] = Field(default_factory=list, description="Warnings she gave, e.g. 'dhakkan mat kholna'.")
    quotes: list[str] = Field(default_factory=list, description="Up to 3 memorable lines copied exactly from the transcript.")
    ask_next_time: list[str] = Field(default_factory=list, description="Things she skipped or that were unclear, phrased as questions to ask her.")

    @field_validator("tips", "warnings", "quotes", "ask_next_time", mode="before")
    @classmethod
    def _strings(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]

    @classmethod
    def llm_schema(cls) -> dict:
        return cls.model_json_schema(mode="serialization")


def parse_seconds(v: Any) -> float:
    """Accept 83, 83.5, "83", "83s", "1:23", "01:01:23" → seconds."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return max(0.0, float(v))
    s = str(v).strip().lower().rstrip("s").strip()
    if ":" in s:
        total = 0.0
        for part in s.split(":"):
            try:
                total = total * 60 + float(part or 0)
            except ValueError:
                return 0.0
        return total
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else 0.0


class Word(BaseModel):
    start: float
    end: float
    word: str


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0
    whisper_model: str = ""
    segments: list[Segment] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


class Meta(BaseModel):
    """Bookkeeping for one recording: status for the UI, provenance, verification report."""

    id: str
    cook: str = ""
    dish: str = ""
    created: str = ""
    updated: str = ""
    status: Literal["queued", "transcribing", "writing", "done", "error"] = "queued"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    fix: str = ""
    audio: str = ""  # original upload, untouched
    playback: str = ""  # seekable copy for the browser (may equal `audio`)
    lang: str | None = None
    language: str = ""
    duration: float = 0.0
    model: str = ""
    whisper_model: str = ""
    dropped: int = 0
    dropped_items: list[str] = Field(default_factory=list)
    edited: bool = False
