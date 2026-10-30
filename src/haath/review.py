"""Family review: someone goes through the card with the cook and ticks each line as correct.

A tick is stored as a key derived from the line's content, so editing a line (or re-writing the
card) automatically makes it "unchecked" again: the family only ever vouches for what they saw.
"""

from __future__ import annotations

import hashlib

from haath.models import Meta, Recipe
from haath.verify import normalize

KINDS = ("ingredients", "steps", "tips", "warnings", "quotes")


def _key(kind: str, *parts: str) -> str:
    digest = hashlib.sha1(normalize(" | ".join(parts)).encode()).hexdigest()[:12]
    return f"{kind[:3]}-{digest}"


def review_keys(r: Recipe) -> dict[str, list[str]]:
    return {
        "ingredients": [_key("ingredients", i.name, i.her_words, i.approx) for i in r.ingredients],
        "steps": [_key("steps", s.text, s.her_cue) for s in r.steps],
        "tips": [_key("tips", t) for t in r.tips],
        "warnings": [_key("warnings", w) for w in r.warnings],
        "quotes": [_key("quotes", q) for q in r.quotes],
    }


def all_keys(r: Recipe) -> list[str]:
    return [k for kind in KINDS for k in review_keys(r)[kind]]


def review_summary(r: Recipe | None, meta: Meta) -> dict:
    if r is None:
        return {"keys": {k: [] for k in KINDS}, "checked": [], "done": 0, "total": 0}
    keys = review_keys(r)
    valid = set(all_keys(r))
    checked = [k for k in meta.reviewed if k in valid]
    return {"keys": keys, "checked": checked, "done": len(set(checked)), "total": len(valid)}


def prune(r: Recipe, reviewed: list[str]) -> list[str]:
    """Keep ticks only for lines that still exist unchanged."""
    valid = set(all_keys(r))
    return [k for k in dict.fromkeys(reviewed) if k in valid]
