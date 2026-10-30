"""Runtime settings. CLI flags win over environment variables, which win over defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gemma4:e4b"
DEFAULT_WHISPER_MODEL = "large-v3-turbo"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_PORT = 8767
# Gemma's window is much larger, but 16k keeps RAM use sane on an ordinary laptop.
DEFAULT_NUM_CTX = 16384


def default_archive() -> Path:
    env = os.environ.get("HAATH_ARCHIVE")
    return Path(env).expanduser() if env else Path.home() / "HaathKaSwaad"


@dataclass
class Settings:
    archive: Path
    model: str = DEFAULT_MODEL
    whisper_model: str = DEFAULT_WHISPER_MODEL
    lang: str | None = None
    ollama_host: str = DEFAULT_OLLAMA_HOST
    num_ctx: int = DEFAULT_NUM_CTX
    mock: bool = False

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls(
            archive=default_archive(),
            model=os.environ.get("HAATH_MODEL", DEFAULT_MODEL),
            whisper_model=os.environ.get("HAATH_WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
            ollama_host=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
            num_ctx=int(os.environ.get("HAATH_NUM_CTX", DEFAULT_NUM_CTX)),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(s, key, value)
        s.archive = Path(s.archive).expanduser().resolve()
        if not s.ollama_host.startswith("http"):
            s.ollama_host = "http://" + s.ollama_host
        return s
