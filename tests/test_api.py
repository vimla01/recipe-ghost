import time

import pytest
from fastapi.testclient import TestClient

from haath import mock, pipeline
from haath.book import write_book
from haath.config import Settings
from haath.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    app = create_app(Settings.from_env(archive=tmp_path, mock=True))
    with TestClient(app) as c:
        c.archive_root = tmp_path
        yield c


def wait_done(c, rid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        meta = c.get(f"/api/recipes/{rid}").json()["meta"]
        if meta["status"] in ("done", "error"):
            return meta
        time.sleep(0.05)
    raise AssertionError("pipeline did not finish")


def upload(c, tmp_path, dish="Dal Baati"):
    wav = mock.write_demo_audio(tmp_path / "in.wav")
    with wav.open("rb") as f:
        r = c.post("/api/recipes", files={"audio": ("blob", f, "audio/webm")}, data={"cook": "Mummy", "dish": dish})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_index_and_static_are_local(client):
    html = client.get("/").text
    assert "/static/app.js" in html and "http" not in html.split("<body>")[0].replace("http-equiv", "")
    assert client.get("/static/fonts.css").status_code == 200
    assert client.get("/static/fonts/kalam-devanagari-400-normal.woff2").status_code == 200


def test_upload_process_edit_redo_delete(client, tmp_path):
    rid = upload(client, tmp_path)
    assert (client.archive_root / "recipes" / rid / "original.webm").exists()  # extension from content-type
    meta = wait_done(client, rid)
    assert meta["status"] == "done" and meta["dropped"] == 2

    data = client.get(f"/api/recipes/{rid}").json()
    assert data["recipe"]["cook"] == "Mummy" and data["transcript"]["segments"]
    assert "words" not in data["transcript"]["segments"][0]

    listed = client.get("/api/recipes").json()
    assert listed[0]["id"] == rid and listed[0]["n_steps"] == 11

    recipe = data["recipe"]
    recipe["ingredients"][0]["approx"] = "~2½ cups"
    r = client.put(f"/api/recipes/{rid}", json=recipe)
    assert r.status_code == 200 and r.json()["meta"]["edited"] is True
    assert client.put(f"/api/recipes/{rid}", json={"steps": "nope"}).status_code == 400

    assert client.post(f"/api/recipes/{rid}/redo").status_code == 200
    assert wait_done(client, rid)["edited"] is False

    assert client.delete(f"/api/recipes/{rid}").status_code == 200
    assert client.get(f"/api/recipes/{rid}").status_code == 404
    assert (client.archive_root / ".trash" / rid).exists()  # never hard-deleted


def test_audio_supports_range_for_seeking(client, tmp_path):
    rid = upload(client, tmp_path)
    wait_done(client, rid)
    r = client.get(f"/api/recipes/{rid}/audio", headers={"Range": "bytes=1000-1999"})
    assert r.status_code == 206 and len(r.content) == 1000


def test_bad_ids_rejected(client):
    assert client.get("/api/recipes/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/recipes/NOPE").status_code == 404


def test_book_live_and_offline_file(client, tmp_path):
    rid = upload(client, tmp_path)
    wait_done(client, rid)
    live = client.get("/book").text
    assert "Dal Baati" in live and f"/api/recipes/{rid}/audio" in live

    out = write_book(client.app.state.archive)
    html = out.read_text(encoding="utf-8")
    assert f'data-src="recipes/{rid}/voice-demo.wav"' in html  # relative, opens offline
    assert "data:font/woff2;base64," in html and "/static/" not in html
    assert "Dal baati is the taste of Rajasthan" not in html  # the invented quote never reaches the book
