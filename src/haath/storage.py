"""The archive: ~/HaathKaSwaad/recipes/<id>/{original audio, transcript.json, recipe.json, meta.json}.

Every write goes to a temp file in the same folder and is then renamed over the
target, so a crash or power cut never leaves a half-written recipe behind.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel

from haath.errors import HaathError
from haath.models import Meta, Recipe, Transcript

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
AUDIO_EXTS = {".webm", ".m4a", ".mp4", ".mp3", ".ogg", ".opus", ".oga", ".wav", ".aac", ".flac", ".amr", ".3gp", ".caf"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: BaseModel | dict | list) -> None:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    atomic_write_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:40].strip("-") or "recipe"


class Archive:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.recipes_dir = self.root / "recipes"
        self._lock = threading.RLock()

    def ensure(self) -> None:
        try:
            self.recipes_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HaathError(f"Cannot create the archive at {self.root}: {e}", "pass a writable folder: haath ui /path/to/folder") from e

    def dir(self, rid: str) -> Path:
        if not ID_RE.match(rid):
            raise HaathError(f"Not a valid recipe id: {rid!r}", "run: haath list   to see ids")
        return self.recipes_dir / rid

    def exists(self, rid: str) -> bool:
        return ID_RE.match(rid) is not None and (self.recipes_dir / rid / "meta.json").exists()

    # ---- create -------------------------------------------------------------

    def create(self, src: BinaryIO | Path, filename: str, cook: str = "", dish: str = "", lang: str | None = None) -> Meta:
        self.ensure()
        ext = Path(filename).suffix.lower()
        if ext not in AUDIO_EXTS:
            ext = ".webm" if not ext else ext
        rid = f"{datetime.now():%Y%m%d}-{slugify(dish or cook or 'recipe')}-{secrets.token_hex(2)}"
        d = self.recipes_dir / rid
        d.mkdir(parents=True)
        target = d / f"original{ext}"
        tmp = d / f".original{ext}.tmp"
        if isinstance(src, Path):
            shutil.copyfile(src, tmp)
        else:
            with open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
        os.replace(tmp, target)
        meta = Meta(id=rid, cook=cook.strip(), dish=dish.strip(), created=now_iso(), updated=now_iso(), audio=target.name, playback=target.name, lang=lang)
        self.save_meta(meta)
        return meta

    # ---- read/write ---------------------------------------------------------

    def load_meta(self, rid: str) -> Meta:
        p = self.dir(rid) / "meta.json"
        if not p.exists():
            raise HaathError(f"No recipe with id {rid}", "run: haath list   to see ids")
        return Meta.model_validate_json(p.read_bytes())

    def save_meta(self, meta: Meta) -> None:
        with self._lock:
            meta.updated = now_iso()
            atomic_write_json(self.dir(meta.id) / "meta.json", meta)

    def update_meta(self, rid: str, **fields) -> Meta:
        with self._lock:
            meta = self.load_meta(rid)
            for k, v in fields.items():
                setattr(meta, k, v)
            self.save_meta(meta)
            return meta

    def load_transcript(self, rid: str) -> Transcript | None:
        p = self.dir(rid) / "transcript.json"
        return Transcript.model_validate_json(p.read_bytes()) if p.exists() else None

    def save_transcript(self, rid: str, t: Transcript) -> None:
        atomic_write_json(self.dir(rid) / "transcript.json", t)

    def load_recipe(self, rid: str) -> Recipe | None:
        p = self.dir(rid) / "recipe.json"
        return Recipe.model_validate_json(p.read_bytes()) if p.exists() else None

    def save_recipe(self, rid: str, r: Recipe) -> None:
        atomic_write_json(self.dir(rid) / "recipe.json", r)

    def audio_path(self, rid: str, playback: bool = True) -> Path:
        meta = self.load_meta(rid)
        return self.dir(rid) / ((meta.playback or meta.audio) if playback else meta.audio)

    def list(self) -> list[Meta]:
        if not self.recipes_dir.exists():
            return []
        metas = []
        for p in self.recipes_dir.glob("*/meta.json"):
            try:
                metas.append(Meta.model_validate_json(p.read_bytes()))
            except Exception:
                continue
        return sorted(metas, key=lambda m: m.created, reverse=True)

    def trash(self, rid: str) -> Path:
        """Never hard-delete a grandmother's voice: move it to .trash instead."""
        src = self.dir(rid)
        dest = self.root / ".trash" / rid
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return dest
