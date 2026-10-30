import json

import pytest

from haath.errors import HaathError
from haath.llm import parse_reply
from haath.mock import fixture_reply_text
from haath.models import Recipe


def test_parse_fixture_reply():
    r = parse_reply(fixture_reply_text())
    assert r.dish == "Dal Baati"
    assert r.ingredients and r.steps
    assert all(i.confidence in ("low", "med", "high") for i in r.ingredients)


def test_parse_tolerates_fences_chatter_and_loose_values():
    reply = """Sure! Here is the recipe:
```json
{"recipe": {"dish": "Poha", "ingredients": [{"name": "Poha", "her_words": "do mutthi", "approx": "~1 cup", "confidence": "Medium"}],
 "steps": [{"text": "Rinse poha", "her_cue": "", "start_sec": "1:05"}], "tips": "Use thick poha"}}
```"""
    r = parse_reply(reply)
    assert r.dish == "Poha"
    assert r.ingredients[0].confidence == "med"
    assert r.steps[0].start_sec == 65.0
    assert r.tips == ["Use thick poha"]
    assert r.quotes == [] and r.story == ""  # missing fields default


def test_parse_rejects_non_json_with_fix():
    with pytest.raises(HaathError) as e:
        parse_reply("I could not understand the audio.")
    assert "redo" in e.value.fix


def test_schema_requires_every_field():
    s = Recipe.llm_schema()
    assert set(s["required"]) == set(s["properties"])
    for d in s["$defs"].values():
        assert set(d["required"]) == set(d["properties"])
    json.dumps(s)  # serializable for Ollama's `format`
