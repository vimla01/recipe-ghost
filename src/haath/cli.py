"""`haath` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from haath import __version__
from haath.config import DEFAULT_PORT, Settings
from haath.errors import HaathError
from haath.storage import Archive


def _common(p: argparse.ArgumentParser, archive_positional: bool = False) -> None:
    if archive_positional:
        p.add_argument("archive_pos", nargs="?", metavar="archive", help="archive folder (default ~/HaathKaSwaad or $HAATH_ARCHIVE)")
    p.add_argument("--archive", help="archive folder (default ~/HaathKaSwaad or $HAATH_ARCHIVE)")
    p.add_argument("--model", help="Ollama model (default gemma4:e4b)")
    p.add_argument("--whisper-model", help="faster-whisper model: large-v3-turbo (default) or small for slow laptops")
    p.add_argument("--lang", help="force the spoken language: hi, mr, gu, en (default: auto-detect)")
    p.add_argument("--num-ctx", type=int, help="Gemma context window in tokens (default 16384)")
    p.add_argument("--think", action="store_true", default=None, help="let Gemma reason before answering (slower, rarely needed)")
    p.add_argument("--mock", action="store_true", default=None, help="use a fixture transcript + reply (no Whisper/Ollama needed)")


def _settings(args) -> Settings:
    archive = getattr(args, "archive_pos", None) or args.archive
    return Settings.from_env(
        archive=Path(archive) if archive else None,
        model=args.model,
        whisper_model=args.whisper_model,
        lang=args.lang,
        num_ctx=args.num_ctx,
        think=args.think,
        mock=args.mock,
    )


def cmd_ui(args) -> int:
    from haath.server import serve

    serve(_settings(args), port=args.port, open_browser=not args.no_browser, lan=args.lan)
    return 0


def cmd_add(args) -> int:
    from haath import mock, pipeline

    s = _settings(args)
    archive = Archive(s.archive)
    archive.ensure()
    if args.audio:
        src = Path(args.audio).expanduser()
        if not src.is_file():
            raise HaathError(f"No such audio file: {src}", "check the path; phone voice notes are usually .m4a, .opus or .ogg")
    elif s.mock:
        src = mock.write_demo_audio(s.archive / ".demo-voice.wav")
    else:
        raise HaathError("Which recording?", 'run: haath add path/to/voice-note.m4a --cook "Mummy" --dish "Dal Baati"')

    meta = archive.create(src, src.name, cook=args.cook or "", dish=args.dish or "", lang=s.lang)
    print(f"Saved {src.name} as {meta.id}")
    last = [""]

    def show(frac: float, msg: str) -> None:
        if msg != last[0]:
            print(f"  … {msg}", flush=True)
            last[0] = msg

    pipeline.process(archive, meta.id, s, on_progress=show)
    _print_done(archive, meta.id)
    return 0


def _print_done(archive: Archive, rid: str) -> None:
    meta = archive.load_meta(rid)
    recipe = archive.load_recipe(rid)
    print(f"\n  {recipe.dish or 'Recipe'}, as told by {recipe.cook or 'the cook'}")
    print(f"  {len(recipe.ingredients)} ingredients, {len(recipe.steps)} steps, {len(recipe.ask_next_time)} questions for next time")
    if meta.dropped:
        print(f"  Guard removed {meta.dropped} line(s) the model wrote that were never said:")
        for d in meta.dropped_items:
            print(f"    – {d}")
    print(f"  Saved in {archive.dir(rid)}\n  Open it with: haath ui")


def cmd_list(args) -> int:
    archive = Archive(_settings(args).archive)
    metas = archive.list()
    if not metas:
        print('No recipes yet. Record one with: haath ui   or: haath add voice.m4a --cook "Mummy" --dish "Poha"')
        return 0
    for m in metas:
        mins = f"{int(m.duration // 60)}:{int(m.duration % 60):02d}" if m.duration else "–"
        status = m.status + (f" ({m.error})" if m.status == "error" else "")
        print(f"{m.id:40}  {(m.dish or '?')[:24]:24}  {(m.cook or '?')[:12]:12}  {mins:>6}  {status}")
    return 0


def cmd_redo(args) -> int:
    from haath import pipeline

    s = _settings(args)
    archive = Archive(s.archive)
    meta = archive.load_meta(args.id)
    if meta.edited and not args.yes:
        raise HaathError("This recipe was edited by hand; redo would overwrite those edits.", f"run: haath redo {args.id} --yes")
    print(f"Re-writing {args.id} with {'mock' if s.mock else s.model}" + (" (re-transcribing too)" if args.full else ""))
    pipeline.process(archive, args.id, s, redo=not args.full, on_progress=lambda f, m: print(f"  … {m}", flush=True))
    _print_done(archive, args.id)
    return 0


def cmd_book(args) -> int:
    from haath.book import write_book

    s = _settings(args)
    out = write_book(Archive(s.archive), Path(args.out).expanduser() if args.out else None)
    print(f"Wrote {out}\nDouble-click it to open; it works offline. Keep it next to the recipes/ folder so the recordings play.")
    return 0


def cmd_doctor(args) -> int:
    from haath.doctor import print_report, run_checks

    s = _settings(args)
    print(f"haath {__version__}: checking what's needed to run fully offline\n")
    return 0 if print_report(run_checks(s, download=args.download)) else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="haath", description="Haath ka Swaad: for every recipe that only exists in her hands.")
    ap.add_argument("--version", action="version", version=f"haath {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ui", help="open the kitchen in your browser (main way to use it)")
    _common(p, archive_positional=True)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.add_argument("--lan", action="store_true", help="also listen on your Wi-Fi network (for a phone on the counter)")
    p.set_defaults(fn=cmd_ui)

    p = sub.add_parser("add", help="add an existing voice note")
    p.add_argument("audio", nargs="?", help="audio file (.m4a .opus .ogg .mp3 .wav .webm); optional with --mock")
    p.add_argument("--cook", help='who is cooking, e.g. "Mummy"')
    p.add_argument("--dish", help='dish name, e.g. "Dal Baati"')
    _common(p)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("list", help="list saved recipes")
    _common(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("redo", help="re-run Gemma on a recording (e.g. after changing --model)")
    p.add_argument("id")
    p.add_argument("--full", action="store_true", help="also re-transcribe the audio")
    p.add_argument("--yes", action="store_true", help="overwrite hand edits")
    _common(p)
    p.set_defaults(fn=cmd_redo)

    p = sub.add_parser("book", help="write book.html: every recipe, printable, opens offline")
    p.add_argument("--out", help="output file (default <archive>/book.html)")
    _common(p)
    p.set_defaults(fn=cmd_book)

    p = sub.add_parser("doctor", help="check Whisper model, Ollama and Gemma")
    p.add_argument("--download", action="store_true", help="download the Whisper model if missing (needs internet once)")
    _common(p)
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except HaathError as e:
        print(f"\n✗ {e.message}", file=sys.stderr)
        if e.fix:
            print(f"  → {e.fix}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
