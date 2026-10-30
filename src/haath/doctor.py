"""`haath doctor`: check every dependency and say exactly how to fix what's missing."""

from __future__ import annotations

import shutil
import sys
from dataclasses import asdict, dataclass

from haath.config import Settings
from haath.storage import Archive


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    required: bool = True


def check_ollama(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    try:
        import ollama

        client = ollama.Client(host=settings.ollama_host, timeout=5)
        resp = client.list()
    except ImportError:
        return [Check("Ollama Python package", False, "not installed", "run: pip install ollama")]
    except Exception as e:
        fix = "run: ollama serve"
        if not shutil.which("ollama"):
            fix = "install Ollama from https://ollama.com/download, then run: ollama serve"
        return [Check("Ollama server", False, f"not reachable at {settings.ollama_host} ({type(e).__name__})", fix)]
    checks.append(Check("Ollama server", True, settings.ollama_host))

    models = resp.get("models", []) if isinstance(resp, dict) else resp.models
    names = {(m.get("model") or m.get("name")) if isinstance(m, dict) else m.model for m in models}
    want = settings.model if ":" in settings.model else settings.model + ":latest"
    if want in names:
        checks.append(Check(f"Model {settings.model}", True, "pulled"))
    else:
        have = ", ".join(sorted(n for n in names if n)) or "none"
        checks.append(Check(f"Model {settings.model}", False, f"not pulled (have: {have})", f"run: ollama pull {settings.model}"))
    return checks


def check_whisper(settings: Settings, download: bool = False) -> list[Check]:
    checks: list[Check] = []
    try:
        import faster_whisper  # noqa: F401
        import av

        checks.append(Check("faster-whisper + PyAV", True, f"PyAV {av.__version__} decodes webm/m4a/opus/mp3 — no ffmpeg needed"))
    except ImportError as e:
        return [Check("faster-whisper", False, str(e), "run: pip install faster-whisper   (or reinstall: uv tool install .)")]

    from haath.transcribe import download_whisper, pick_device, whisper_cached

    device, compute = pick_device()
    checks.append(Check("Compute device", True, f"{device} ({compute})" + ("" if device == "cuda" else " — fine; a GPU is just faster"), required=False))

    if not whisper_cached(settings.whisper_model) and download:
        print(f"  … downloading Whisper '{settings.whisper_model}' (one time, ~1.6 GB for large-v3-turbo, ~0.5 GB for small)", flush=True)
        try:
            download_whisper(settings.whisper_model)
        except Exception as e:
            checks.append(Check(f"Whisper model {settings.whisper_model}", False, f"download failed: {e}", "check the internet connection and run: haath doctor --download"))
            return checks
    if whisper_cached(settings.whisper_model):
        checks.append(Check(f"Whisper model {settings.whisper_model}", True, "downloaded (works offline)"))
    else:
        checks.append(Check(f"Whisper model {settings.whisper_model}", False, "not downloaded yet", "run once with internet: haath doctor --download"))
    return checks


def run_checks(settings: Settings, download: bool = False) -> list[Check]:
    checks = [Check("Python", sys.version_info >= (3, 11), sys.version.split()[0], "install Python 3.11 or newer")]
    try:
        Archive(settings.archive).ensure()
        checks.append(Check("Archive", True, str(settings.archive)))
    except Exception as e:
        checks.append(Check("Archive", False, str(e), "pass a writable folder: haath ui /path/to/folder"))
    checks += check_whisper(settings, download)
    checks += check_ollama(settings)
    return checks


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]


def print_report(checks: list[Check]) -> bool:
    all_ok = True
    for c in checks:
        mark = "✓" if c.ok else ("✗" if c.required else "!")
        print(f"  {mark} {c.name}: {c.detail}")
        if not c.ok:
            print(f"      → {c.fix}")
            all_ok = all_ok and not c.required
    print()
    print("  All set. Run: haath ui" if all_ok else "  Fix the ✗ items above, then run: haath doctor")
    return all_ok
