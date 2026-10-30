"""Local web UI on 127.0.0.1:8767. Nothing here talks to the internet."""

from __future__ import annotations

import threading
import webbrowser
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from haath import __version__
from haath.config import DEFAULT_PORT, Settings
from haath.errors import HaathError
from haath.models import Recipe
from haath.pipeline import Worker
from haath.review import all_keys, prune, review_summary
from haath.storage import Archive

STATIC = Path(str(files("haath") / "static"))


def create_app(settings: Settings, start_worker: bool = True) -> FastAPI:
    archive = Archive(settings.archive)
    archive.ensure()
    worker = Worker(archive, settings)

    @asynccontextmanager
    async def lifespan(_app):
        if start_worker:
            worker.start()
        yield

    app = FastAPI(title="Haath ka Swaad", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.worker = worker
    app.state.archive = archive

    @app.exception_handler(HaathError)
    async def _haath_error(_request, exc: HaathError):
        return JSONResponse({"error": exc.message, "fix": exc.fix}, status_code=400)

    def _get(rid: str):
        if not archive.exists(rid):
            raise HTTPException(404, "No such recipe")
        return archive.load_meta(rid)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/status")
    def status():
        return {
            "version": __version__,
            "mock": settings.mock,
            "model": settings.model,
            "whisper_model": settings.whisper_model,
            "archive": str(settings.archive),
            "busy": worker.current,
            "queued": worker.q.qsize(),
        }

    @app.get("/api/doctor")
    def doctor():
        from haath.doctor import as_dicts, check_ollama, check_whisper

        if settings.mock:
            return {"checks": [], "mock": True}
        return {"checks": as_dicts(check_whisper(settings) + check_ollama(settings))}

    @app.get("/api/recipes")
    def list_recipes():
        out = []
        for m in archive.list():
            r = archive.load_recipe(m.id) if m.status == "done" else None
            rv = review_summary(r, m)
            out.append({**m.model_dump(), "n_ingredients": len(r.ingredients) if r else 0, "n_steps": len(r.steps) if r else 0,
                        "review_done": rv["done"], "review_total": rv["total"]})
        return out

    @app.post("/api/recipes")
    def add_recipe(audio: UploadFile = File(...), cook: str = Form(""), dish: str = Form(""), lang: str = Form("")):
        name = audio.filename or "recording.webm"
        if Path(name).suffix == "" and audio.content_type:
            ext = {"audio/webm": ".webm", "audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/wav": ".wav"}
            name += ext.get(audio.content_type.split(";")[0], ".webm")
        meta = archive.create(audio.file, name, cook=cook, dish=dish, lang=lang or settings.lang)
        worker.submit(meta.id)
        return archive.load_meta(meta.id).model_dump()

    @app.get("/api/recipes/{rid}")
    def get_recipe(rid: str):
        meta = _get(rid)
        r = archive.load_recipe(rid)
        t = archive.load_transcript(rid)
        return {
            "meta": meta.model_dump(),
            "recipe": r.model_dump() if r else None,
            "transcript": t.model_dump(exclude={"segments": {"__all__": {"words"}}}) if t else None,
            "review": review_summary(r, meta),
        }

    @app.put("/api/recipes/{rid}")
    def save_recipe(rid: str, body: dict):
        meta = _get(rid)
        if meta.status not in ("done", "error"):
            raise HaathError("Still being written. Wait until it's done before editing.", "")
        try:
            r = Recipe.model_validate(body)
        except ValidationError as e:
            raise HaathError(f"That edit doesn't fit the recipe card: {e.errors()[0]['msg']}", "check the fields and save again") from e
        archive.save_recipe(rid, r)
        archive.update_meta(rid, edited=True, dish=r.dish or meta.dish, cook=r.cook or meta.cook, status="done", error="", fix="",
                            reviewed=prune(r, meta.reviewed))  # edited lines need a fresh check
        return {"meta": archive.load_meta(rid).model_dump(), "recipe": r.model_dump()}

    @app.put("/api/recipes/{rid}/review")
    def review(rid: str, body: dict):
        """Tick (ok=true) or untick one line: {"key": "...", "ok": true}, or {"keys": [...], "ok": true}."""
        meta = _get(rid)
        r = archive.load_recipe(rid)
        if r is None or meta.status != "done":
            raise HaathError("There is no finished card to review yet.", "wait until it says ready")
        keys = body.get("keys") or [body.get("key")]
        valid = set(all_keys(r))
        unknown = [k for k in keys if k not in valid]
        if unknown:
            raise HaathError("That line has changed since the page loaded.", "refresh the page and tick it again")
        current = [k for k in meta.reviewed if k in valid]
        if body.get("ok", True):
            current += [k for k in keys if k not in current]
        else:
            current = [k for k in current if k not in keys]
        meta = archive.update_meta(rid, reviewed=current)
        return review_summary(r, meta)

    @app.post("/api/recipes/{rid}/redo")
    def redo(rid: str, full: bool = False):
        _get(rid)
        worker.submit(rid, redo=not full)
        return archive.load_meta(rid).model_dump()

    @app.delete("/api/recipes/{rid}")
    def delete(rid: str):
        _get(rid)
        if worker.current == rid:
            raise HaathError("This one is being processed right now.", "wait for it to finish, then delete")
        dest = archive.trash(rid)
        return {"trashed": str(dest)}

    @app.get("/api/recipes/{rid}/audio")
    def audio(rid: str):
        _get(rid)
        path = archive.audio_path(rid)
        if not path.exists():
            raise HTTPException(404, "Audio missing")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/book", response_class=HTMLResponse)
    def book():
        from haath.book import render_book

        return render_book(archive, audio_url=lambda rid: f"/api/recipes/{rid}/audio", inline_assets=False)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve(settings: Settings, port: int = DEFAULT_PORT, open_browser: bool = True, lan: bool = False) -> None:
    import uvicorn

    import socket

    host = "0.0.0.0" if lan else "127.0.0.1"
    with socket.socket() as probe:
        # Same option uvicorn uses, so a just-closed haath ui (port in TIME_WAIT) isn't "busy".
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as e:
            raise HaathError(f"Port {port} is already in use (is haath ui already open?).", f"open http://127.0.0.1:{port}/  or run: haath ui --port {port + 1}") from e
    app = create_app(settings)
    ssl: dict = {}
    ip = ""
    if lan:
        ip = lan_ip()
        cert, key = lan_cert(settings.archive, ip)
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    url = f"{'https' if lan else 'http'}://127.0.0.1:{port}/"
    print(f"\n  Haath ka Swaad is open at {url}")
    print(f"  Recipes are kept in {settings.archive}")
    if settings.mock:
        print("  Mock mode: recordings use a sample transcript + reply (no Whisper/Ollama).")
    if lan:
        print(f"  On your Wi-Fi (phone on the kitchen counter): https://{ip}:{port}/")
        print("  The phone will warn about the certificate once; it's this laptop's own, made just now.")
        print("  Tap Advanced → Proceed, then the Record button works on the phone too.")
        print("  Anyone on this Wi-Fi can open the page while it runs; stop with Ctrl+C when done.")
    print("  Press Ctrl+C to close.\n", flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning", **ssl)


def lan_ip() -> str:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the Wi-Fi interface
            return s.getsockname()[0]
    except OSError as e:
        raise HaathError("Could not find this laptop's Wi-Fi address.", "connect to Wi-Fi, or run without --lan") from e


def lan_cert(archive: Path, ip: str) -> tuple[Path, Path]:
    """A self-signed certificate for --lan, so phone browsers treat the page as secure and allow
    the microphone. Made once with the system openssl; remade if the Wi-Fi address changes."""
    import shutil
    import subprocess

    d = archive / ".lan-cert"
    cert, key, stamp = d / "cert.pem", d / "key.pem", d / "ip.txt"
    if cert.exists() and key.exists() and stamp.exists() and stamp.read_text().strip() == ip:
        return cert, key
    if not shutil.which("openssl"):
        raise HaathError(
            "--lan needs openssl to make a local https certificate (phones only allow the mic on https).",
            "install it (Ubuntu: sudo apt install openssl · macOS: already installed · Windows: winget install ShiningLight.OpenSSL)",
        )
    d.mkdir(parents=True, exist_ok=True)
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=Haath ka Swaad (this laptop)",
        "-addext", f"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{ip}",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        err = getattr(e, "stderr", b"") or b""
        raise HaathError(f"openssl could not make the certificate: {err.decode(errors='replace').strip()[:200]}", "update openssl (1.1.1 or newer), or run without --lan") from e
    key.chmod(0o600)
    stamp.write_text(ip)
    return cert, key
