"""Speech → timestamped transcript with faster-whisper, plus a seekable playback copy.

faster-whisper decodes webm/m4a/opus/mp3/wav itself through PyAV (FFmpeg libraries
bundled in the wheel), so no separate ffmpeg install is needed.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from pathlib import Path

from haath.errors import HaathError
from haath.models import Segment, Transcript, Word


def pick_device() -> tuple[str, str]:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def whisper_cached(model_name: str) -> bool:
    if Path(model_name).is_dir():
        return True
    try:
        from faster_whisper.utils import download_model

        download_model(model_name, local_files_only=True)
        return True
    except Exception:
        return False


def download_whisper(model_name: str) -> str:
    from faster_whisper.utils import download_model

    return download_model(model_name)


def load_model(model_name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise HaathError("faster-whisper is not installed.", "run: pip install faster-whisper   (or reinstall: uv tool install .)") from e
    device, compute = pick_device()
    try:
        return WhisperModel(model_name, device=device, compute_type=compute, cpu_threads=0)
    except Exception as e:
        if device == "cuda":  # broken CUDA/cuDNN install: fall back to CPU rather than fail
            return WhisperModel(model_name, device="cpu", compute_type="int8")
        if not whisper_cached(model_name):
            raise HaathError(
                f"Whisper model '{model_name}' is not downloaded yet and could not be fetched ({e}).",
                "connect to the internet once and run: haath doctor --download",
            ) from e
        raise HaathError(f"Could not load Whisper model '{model_name}': {e}", "try a smaller one: --whisper-model small") from e


SENTENCE_END = ("।", "॥", ".", "?", "!")
CLAUSE_END = (",", ";", ":", "،")


def dur(words: list[Word]) -> float:
    return words[-1].end - words[0].start if words else 0.0


def cut_at_pauses(words: list[Word], max_sec: float, min_sec: float = 1.5) -> list[list[Word]]:
    """Split at the longest silence between two words (keeping both sides >= min_sec), and repeat
    until every piece is short enough. Pauses are where a speaker naturally ends a thought."""
    if dur(words) <= max_sec or len(words) < 4:
        return [words]
    ks = [k for k in range(1, len(words)) if dur(words[:k]) >= min_sec and dur(words[k:]) >= min_sec]
    if not ks:
        return [words]
    k = max(ks, key=lambda k: (words[k].start - words[k - 1].end, -abs(k - len(words) / 2)))
    return cut_at_pauses(words[:k], max_sec, min_sec) + cut_at_pauses(words[k:], max_sec, min_sec)


def split_long_segments(segments: list[Segment], max_sec: float = 8.0) -> list[Segment]:
    """Whisper (with VAD) often returns 20–30 s segments holding several steps, so ▶ would start
    every one of those steps at the same moment. Re-cut them at sentence ends (then, if still
    long, at commas, then at pauses) using the word timestamps, so each line starts where it's said."""
    out: list[Segment] = []

    def cut(words: list[Word], marks: tuple[str, ...]) -> list[list[Word]]:
        pieces, cur = [], []
        for w in words:
            cur.append(w)
            if w.word.strip().endswith(marks):
                pieces.append(cur)
                cur = []
        if cur:
            pieces.append(cur)
        return pieces

    for seg in segments:
        if seg.end - seg.start <= max_sec or len(seg.words) < 2:
            out.append(seg)
            continue
        pieces: list[list[Word]] = []
        for sentence in cut(seg.words, SENTENCE_END):
            for clause in cut(sentence, CLAUSE_END) if dur(sentence) > max_sec else [sentence]:
                # Whisper often writes Hindi with no punctuation at all: cut at the speaker's pauses.
                pieces.extend(cut_at_pauses(clause, max_sec) if dur(clause) > max_sec else [clause])
        # Glue tiny fragments ("बस इतना,") onto the previous piece so lines stay readable.
        merged: list[list[Word]] = []
        for p in pieces:
            if merged and (len(p) < 3 or p[-1].end - p[0].start < 0.8):
                merged[-1] = merged[-1] + p
            else:
                merged.append(p)
        for p in merged:
            text = "".join(w.word for w in p).replace("\ufffd", "").strip()
            if text:
                out.append(Segment(id=0, start=p[0].start, end=p[-1].end, text=text, words=p))
    for i, s in enumerate(out):
        s.id = i
    return out


def transcribe(
    audio: Path,
    model_name: str,
    lang: str | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> Transcript:
    model = load_model(model_name)
    try:
        try:
            segments, info = model.transcribe(
                str(audio),
                language=lang or None,
                task="transcribe",
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,  # skip the long silent stirring bits; timestamps stay absolute
                vad_parameters={"min_silence_duration_ms": 700},
                condition_on_previous_text=False,  # avoids repetition loops on 30+ min audio
            )
        except Exception as e:
            raise HaathError(
                f"Could not read the audio file {audio.name}: {e}",
                "re-export it as .m4a, .mp3 or .wav from the phone and try again",
            ) from e

        duration = float(info.duration or 0.0)
        out: list[Segment] = []
        for seg in segments:  # generator: decoding happens here
            words = [Word(start=round(w.start, 2), end=round(w.end, 2), word=w.word) for w in (seg.words or [])]
            # "\ufffd" appears when Whisper splits one Devanagari character across two tokens.
            text = seg.text.replace("\ufffd", "").strip()
            out.append(Segment(id=len(out), start=round(seg.start, 2), end=round(seg.end, 2), text=text, words=words))
            if progress and duration:
                progress(min(0.99, seg.end / duration), f"listening… {int(seg.end // 60)}:{int(seg.end % 60):02d} of {int(duration // 60)}:{int(duration % 60):02d}")
        return Transcript(
            language=info.language or (lang or ""),
            language_probability=round(float(info.language_probability or 0.0), 3),
            duration=round(duration, 2),
            whisper_model=model_name,
            segments=split_long_segments([s for s in out if s.text]),
        )
    finally:
        # Free RAM for Gemma: Whisper and a 4B model at once is too much for many laptops.
        del model
        gc.collect()


def make_playable(src: Path, dest: Path) -> Path:
    """Browser MediaRecorder webm has no duration/cue index, so seeking (▶ from 1:23) is
    unreliable. Re-encode once to AAC .m4a, which every browser (incl. iPhone) can seek.
    Returns `src` unchanged if it is already a seekable format or conversion fails."""
    if src.suffix.lower() in {".m4a", ".mp3", ".wav", ".aac"}:
        return src
    try:
        import av

        with av.open(str(src)) as inp:
            in_stream = inp.streams.audio[0]
            tmp = dest.with_name(f".{dest.name}.tmp")
            with av.open(str(tmp), "w", format="ipod") as out:
                rate = in_stream.codec_context.sample_rate or 48000
                rate = rate if rate in (16000, 22050, 24000, 32000, 44100, 48000) else 48000
                ost = out.add_stream("aac", rate=rate)
                ost.bit_rate = 96000
                ost.layout = "mono"
                resampler = av.AudioResampler(format="fltp", layout="mono", rate=rate)
                for frame in inp.decode(in_stream):
                    frame.pts = None
                    for f in resampler.resample(frame):
                        for pkt in ost.encode(f):
                            out.mux(pkt)
                for f in resampler.resample(None):
                    for pkt in ost.encode(f):
                        out.mux(pkt)
                for pkt in ost.encode(None):
                    out.mux(pkt)
        tmp.replace(dest)
        return dest
    except Exception:
        dest.with_name(f".{dest.name}.tmp").unlink(missing_ok=True)
        return src
