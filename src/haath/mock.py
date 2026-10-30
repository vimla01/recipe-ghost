"""--mock: a fixture transcript and fixture model reply, so the whole pipeline and UI
can be demoed and tested without Whisper or Ollama."""

from __future__ import annotations

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
    import numpy as np  # installed with faster-whisper

    t = transcript or fixture_transcript()
    n = int((t.duration or 60) * rate)
    v = np.random.default_rng(7).uniform(-1, 1, n) * 0.015
    bell = int(0.6 * rate)
    d = np.arange(bell)
    chime = 0.25 * np.exp(-d / (0.15 * rate)) * np.sin(2 * np.pi * np.where(d < bell // 2, 660, 880) * d / rate)
    for seg in t.segments:
        i = int(seg.start * rate)
        k = min(bell, n - i)
        if k > 0:
            v[i : i + k] += chime[:k]
    frames = (np.clip(v, -1, 1) * 32767).astype("<i2").tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path
