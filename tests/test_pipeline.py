import json

from haath import mock, pipeline
from haath.config import Settings
from haath.storage import Archive, atomic_write_json


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "x" / "recipe.json"
    atomic_write_json(p, {"dish": "पोहा"})
    atomic_write_json(p, {"dish": "Poha"})
    assert json.loads(p.read_text())["dish"] == "Poha"
    assert [f.name for f in p.parent.iterdir()] == ["recipe.json"]


def test_full_mock_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    settings = Settings.from_env(archive=tmp_path, mock=True)
    archive = Archive(tmp_path)
    audio = mock.write_demo_audio(tmp_path / "voice.wav")
    meta = archive.create(audio, "voice.wav", cook="Nani", dish="Dal Baati")

    pipeline.process(archive, meta.id, settings)

    meta = archive.load_meta(meta.id)
    recipe = archive.load_recipe(meta.id)
    assert meta.status == "done" and meta.language == "hi" and meta.duration == 143.0
    assert meta.dropped == 2  # the fixture reply contains one invented quote and one invented measure
    assert recipe.cook == "Nani"  # the family's label wins over the model's
    assert "Dal baati is the taste of Rajasthan." not in recipe.quotes
    assert [s.start_sec for s in recipe.steps][:3] == [19.5, 33.4, 40.1]
    d = archive.dir(meta.id)
    assert {"original.wav", "transcript.json", "recipe.json", "meta.json"} <= {f.name for f in d.iterdir()}


def test_redo_keeps_transcript_and_resets_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    settings = Settings.from_env(archive=tmp_path, mock=True)
    archive = Archive(tmp_path)
    meta = archive.create(mock.write_demo_audio(tmp_path / "v.wav"), "v.wav", dish="Dal Baati")
    pipeline.process(archive, meta.id, settings)
    archive.update_meta(meta.id, edited=True)
    calls = []
    monkeypatch.setattr(pipeline, "_transcribe", lambda *a: calls.append(a))
    pipeline.process(archive, meta.id, settings, redo=True)
    assert calls == []  # Whisper not re-run
    assert archive.load_meta(meta.id).edited is False
