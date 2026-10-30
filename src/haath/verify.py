"""Anti-hallucination guard.

Gemma is asked to copy her words exactly. This module checks that it did:
every quote / her_words / her_cue must actually occur in the transcript, or it
is dropped. Each step's start_sec is snapped to a segment that really contains
that step's words, so ▶ plays the moment she said it.

Matching works on normalized tokens (Unicode NFKC, casefolded, punctuation and
zero-width characters removed, whitespace collapsed). Devanagari vowel signs and
nukta are combining marks (category M) and are kept. If no exact token match
exists we allow a small fuzzy window (spacing like "thoda sa" vs "thodasa", or
a one-letter Whisper slip) and then replace the phrase with the transcript's own
text, so what is shown is always what was heard.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from haath.models import Recipe, Transcript

FUZZY_THRESHOLD = 0.86


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in "LMN":  # letters, combining marks (matras, nukta, virama), digits
            out.append(ch)
        elif cat == "Cf":  # ZWJ / ZWNJ and friends: invisible, drop
            continue
        else:  # punctuation (incl. danda ।), symbols, whitespace
            out.append(" ")
    return " ".join("".join(out).split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


@dataclass
class _Tok:
    norm: str
    orig: str
    raw: int  # index of the original whitespace token (one raw token may give several parts)
    seg: int  # index into transcript.segments


@dataclass
class Match:
    start: int  # token index, inclusive
    end: int  # token index, exclusive
    score: float
    exact: bool  # token-for-token match after normalization
    text: str  # transcript text for this span (original casing/script)
    seg: int  # segment index where the match starts


class TranscriptIndex:
    def __init__(self, transcript: Transcript):
        self.transcript = transcript
        self.toks: list[_Tok] = []
        raw_i = 0
        for i, seg in enumerate(transcript.segments):
            for raw in seg.text.split():
                for part in normalize(raw).split():  # "haldi," → "haldi"; "a/b" → "a", "b"
                    self.toks.append(_Tok(part, raw, raw_i, i))
                raw_i += 1
        self.norms = [t.norm for t in self.toks]

    def span_text(self, start: int, end: int) -> str:
        words: list[str] = []
        last = -1
        for t in self.toks[start:end]:
            if t.raw != last:
                words.append(t.orig)
                last = t.raw
        text = " ".join(words)
        return text.strip(" ,.;:!?।॥-–—\"'“”‘’()")

    def find_all(self, phrase: str) -> list[Match]:
        """All occurrences of `phrase`, exact token matches first; fuzzy only if none."""
        p = tokens(phrase)
        if not p or not self.norms:
            return []
        n = len(p)
        exact = [
            Match(i, i + n, 1.0, True, self.span_text(i, i + n), self.toks[i].seg)
            for i in range(len(self.norms) - n + 1)
            if self.norms[i : i + n] == p
        ]
        if exact:
            return exact
        return self._fuzzy(p)

    def _fuzzy(self, p: list[str]) -> list[Match]:
        target = "".join(p)
        if len(target) < 4:  # too short to fuzz safely ("tel" vs "teel" is a different word risk)
            return []
        n = len(p)
        best: dict[int, Match] = {}
        sm = SequenceMatcher(autojunk=False)
        sm.set_seq2(target)
        for size in {max(1, n - 1), n, n + 1}:
            for i in range(len(self.norms) - size + 1):
                cand = "".join(self.norms[i : i + size])
                if abs(len(cand) - len(target)) > max(2, len(target) // 5):
                    continue
                sm.set_seq1(cand)
                if sm.real_quick_ratio() < FUZZY_THRESHOLD or sm.quick_ratio() < FUZZY_THRESHOLD:
                    continue
                r = sm.ratio()
                if r >= FUZZY_THRESHOLD and (i not in best or r > best[i].score):
                    best[i] = Match(i, i + size, r, False, self.span_text(i, i + size), self.toks[i].seg)
        if not best:
            return []
        top = max(m.score for m in best.values())
        return sorted((m for m in best.values() if m.score >= top - 0.02), key=lambda m: m.start)

    def find(self, phrase: str) -> Match | None:
        matches = self.find_all(phrase)
        return max(matches, key=lambda m: m.score) if matches else None


@dataclass
class VerifyReport:
    dropped: list[str] = field(default_factory=list)  # human-readable "quote: …"
    corrected: list[str] = field(default_factory=list)  # fuzzy matches replaced with transcript text
    unsnapped_steps: list[int] = field(default_factory=list)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def _check(index: TranscriptIndex, phrase: str, label: str, report: VerifyReport) -> str:
    """Return the phrase to keep ('' if dropped)."""
    phrase = (phrase or "").strip()
    if not phrase:
        return ""
    m = index.find(phrase)
    if m is None:
        report.dropped.append(f"{label}: {phrase}")
        return ""
    if not m.exact:
        report.corrected.append(f"{label}: {phrase} → {m.text}")
        return m.text
    return phrase


def _nearest(start_secs: list[float], target: float) -> int:
    return min(range(len(start_secs)), key=lambda i: abs(start_secs[i] - target))


def snap_step_time(index: TranscriptIndex, text: str, her_cue: str, model_sec: float) -> tuple[float, bool]:
    """Snap to the start of the segment that contains this step's words.

    1. her_cue (already verified) found → that segment; nearest to Gemma's guess if repeated.
    2. Gemma's start_sec is exactly one of the transcript's [time] labels → that segment.
    3. Otherwise segments sharing words with the step text → nearest such segment.
    4. Otherwise the segment around Gemma's guess (returned as not snapped).
    """
    segs = index.transcript.segments
    if not segs:
        return max(0.0, model_sec), False
    starts = [s.start for s in segs]

    if her_cue:
        matches = index.find_all(her_cue)
        if matches:
            m = min(matches, key=lambda m: abs(segs[m.seg].start - model_sec))
            return segs[m.seg].start, True

    # Gemma sees every line as "[83.4] ..." and is told to copy that label. An exact label is a
    # real line in her recording (steps in English rarely share words with Hindi speech).
    for s in segs:
        if abs(s.start - model_sec) < 0.05:
            return s.start, True

    words = {w for w in tokens(text) if len(w) >= 3}
    if words:
        scored = []
        for i, s in enumerate(segs):
            overlap = len(words & set(tokens(s.text)))
            if overlap >= 2 or (overlap and overlap >= len(words) * 0.5):
                scored.append((overlap, i))
        if scored:
            top = max(o for o, _ in scored)
            good = [i for o, i in scored if o >= max(1, top - 1)]
            i = min(good, key=lambda i: abs(starts[i] - model_sec))
            return starts[i], True

    # Fallback: the segment whose span contains Gemma's guess, else the nearest start.
    for s in segs:
        if s.start <= model_sec < s.end:
            return s.start, False
    return starts[_nearest(starts, model_sec)], False


def verify_recipe(recipe: Recipe, transcript: Transcript) -> tuple[Recipe, VerifyReport]:
    index = TranscriptIndex(transcript)
    report = VerifyReport()
    r = recipe.model_copy(deep=True)

    seen: set[str] = set()
    quotes = []
    for q in r.quotes:
        kept = _check(index, q, "quote", report)
        if kept and normalize(kept) not in seen:
            seen.add(normalize(kept))
            quotes.append(kept)
    r.quotes = quotes[:3]

    for ing in r.ingredients:
        ing.her_words = _check(index, ing.her_words, f"her words for {ing.name or 'ingredient'}", report)
        if ing.approx and not ing.approx.lstrip().startswith("~"):
            ing.approx = "~" + ing.approx.strip()

    duration = transcript.duration or (transcript.segments[-1].end if transcript.segments else 0.0)
    for i, step in enumerate(r.steps):
        step.her_cue = _check(index, step.her_cue, f"cue for step {i + 1}", report)
        sec, ok = snap_step_time(index, step.text, step.her_cue, step.start_sec)
        step.start_sec = round(min(max(0.0, sec), duration) if duration else max(0.0, sec), 2)
        if not ok:
            report.unsnapped_steps.append(i)

    return r, report
