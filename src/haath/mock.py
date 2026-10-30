"""--mock: a fixture transcript and fixture model reply, so the whole pipeline and UI
can be demoed and tested without Whisper or Ollama."""

from __future__ import annotations

import math
import random
import struct
import wave
from importlib.resources import files
from pathlib import Path

from haath.models import Transcript

_FIXTURES = files("haath") / "fixtures"


def fixture_transcript() -> Transcript:
    return Transcript.model_validate_json((_FIXTURES / "transcript.json").read_bytes())


def fixture_reply_text() -> str:
    return (_FIXTURES / "reply.json").read_text(encoding="utf-8")


def write_demo_audio(path: Path, transcript: Transcript | None = None, rate: int = 16000) -> Path:
    """A stand-in recording: soft kitchen hiss with a two-note bell at every segment start,
    so ▶ visibly (audibly) jumps to the right moment."""
    t = transcript or fixture_transcript()
    starts = [s.start for s in t.segments]
    n = int((t.duration or 60) * rate)
    rng = random.Random(7)
    frames = bytearray()
    bell = int(0.6 * rate)
    marks = sorted(int(s * rate) for s in starts)
    mi = 0
    for i in range(n):
        while mi + 1 < len(marks) and i >= marks[mi + 1]:
            mi += 1
        v = rng.uniform(-1, 1) * 0.015
        d = i - marks[mi] if marks and i >= marks[mi] else bell
        if d < bell:
            env = math.exp(-d / (0.15 * rate))
            f = 660 if d < bell // 2 else 880
            v += 0.25 * env * math.sin(2 * math.pi * f * d / rate)
        frames += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path
