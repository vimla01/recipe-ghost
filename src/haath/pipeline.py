"""Recording → transcript → recipe → verified recipe.

One background worker thread processes one recording at a time, so Whisper and
Gemma never fight over the CPU. Status lives in meta.json for the UI to poll.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from collections.abc import Callable

from haath import llm, mock
from haath.config import Settings
from haath.errors import HaathError
from haath.storage import Archive
from haath.verify import verify_recipe

log = logging.getLogger("haath")

Progress = Callable[[float, str], None]


def _transcribe(archive: Archive, rid: str, settings: Settings, progress: Progress):
    meta = archive.load_meta(rid)
    src = archive.dir(rid) / meta.audio
    if settings.mock:
        for i in range(4):
            progress(i / 4, "listening… (mock)")
            time.sleep(0.4)
        t = mock.fixture_transcript()
        # Timestamps belong to the fixture, so play a stand-in track that matches them.
        demo = mock.write_demo_audio(archive.dir(rid) / "voice-demo.wav", t)
        archive.update_meta(rid, playback=demo.name)
    else:
        from haath.transcribe import make_playable, transcribe

        progress(0.0, "preparing her voice for playback")
        playback = make_playable(src, archive.dir(rid) / "voice.m4a")
        archive.update_meta(rid, playback=playback.name)
        progress(0.0, "loading Whisper (first time can take a minute)")
        t = transcribe(src, settings.whisper_model, meta.lang or settings.lang, progress)
    archive.save_transcript(rid, t)
    archive.update_meta(rid, language=t.language, duration=t.duration, whisper_model=t.whisper_model)
    return t


def _write(archive: Archive, rid: str, settings: Settings, progress: Progress) -> None:
    meta = archive.load_meta(rid)
    t = archive.load_transcript(rid)
    if t is None:
        raise HaathError("No transcript yet for this recording.", f"run: haath redo {rid} --full")
    ask = None
    if settings.mock:

        def ask(_messages):
            time.sleep(1.0)
            return mock.fixture_reply_text()

    recipe = llm.write_recipe(t, meta.cook, meta.dish, settings.model, settings.ollama_host, settings.num_ctx, progress, ask, settings.think)
    progress(0.95, "checking every quote against her recording")
    recipe, report = verify_recipe(recipe, t)
    archive.save_recipe(rid, recipe)
    archive.update_meta(
        rid,
        dish=meta.dish or recipe.dish,
        cook=meta.cook or recipe.cook,
        model="mock" if settings.mock else settings.model,
        dropped=report.dropped_count,
        dropped_items=report.dropped,
        edited=False,
    )


def process(archive: Archive, rid: str, settings: Settings, redo: bool = False, on_progress: Progress | None = None) -> None:
    """Run the pipeline for one recording. `redo` re-runs only Gemma + verify if a transcript exists."""

    def stage(status: str):
        def progress(frac: float, message: str) -> None:
            archive.update_meta(rid, status=status, progress=round(frac, 3), message=message)
            if on_progress:
                on_progress(frac, message)

        return progress

    try:
        archive.update_meta(rid, error="", fix="")
        if not (redo and archive.load_transcript(rid)):
            _transcribe(archive, rid, settings, stage("transcribing"))
        _write(archive, rid, settings, stage("writing"))
        archive.update_meta(rid, status="done", progress=1.0, message="")
    except HaathError as e:
        archive.update_meta(rid, status="error", error=e.message, fix=e.fix, message="")
        raise
    except Exception as e:
        log.error("pipeline failed for %s:\n%s", rid, traceback.format_exc())
        archive.update_meta(rid, status="error", error=f"Unexpected error: {e}", fix="run: haath doctor   then: haath redo " + rid, message="")
        raise


class Worker:
    """A single background thread draining a job queue."""

    def __init__(self, archive: Archive, settings: Settings):
        self.archive = archive
        self.settings = settings
        self.q: queue.Queue[tuple[str, bool]] = queue.Queue()
        self.current: str | None = None
        self._thread = threading.Thread(target=self._run, name="haath-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()
        # Resume anything interrupted by a closed laptop lid or Ctrl-C.
        for meta in reversed(self.archive.list()):
            if meta.status in ("queued", "transcribing", "writing"):
                self.submit(meta.id, redo=meta.status == "writing")

    def submit(self, rid: str, redo: bool = False) -> None:
        self.archive.update_meta(rid, status="queued", progress=0.0, message="waiting for the kitchen to be free", error="", fix="")
        self.q.put((rid, redo))

    def _run(self) -> None:
        while True:
            rid, redo = self.q.get()
            self.current = rid
            try:
                process(self.archive, rid, self.settings, redo=redo)
            except Exception as e:
                log.warning("recipe %s failed: %s", rid, e)
            finally:
                self.current = None
                self.q.task_done()
