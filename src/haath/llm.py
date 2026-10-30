"""Transcript → Recipe with a local Gemma model through Ollama.

Long recordings (20–40 min) can exceed the context window, so the transcript is
split into overlapping chunks of segments, each chunk is extracted separately,
and the partial recipes are merged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from difflib import SequenceMatcher

from pydantic import ValidationError

from haath.errors import HaathError
from haath.models import Ingredient, Recipe, Segment, Step, Transcript
from haath.verify import normalize

SYSTEM_PROMPT = """\
You turn a home cook's spoken explanation into a family recipe card. She speaks \
Hindi, Marathi, Gujarati, English or a mix (Hinglish). The transcript comes from \
speech-to-text, one line per segment, each starting with its time in seconds: [83.4] ...

RULES (follow all of them):
1. Use ONLY what is in the transcript. Never invent an ingredient, step, tip, story or quote. \
If she did not say it, leave it out.
2. Her measures stay exactly as she said them, in `her_words`, copied character-for-character \
from the transcript in the same script (Devanagari stays Devanagari, Roman stays Roman). \
Examples: "ek mutthi atta", "andaaz se namak", "थोड़ा सा हल्दी".
3. Your estimate goes ONLY in `approx`: a NUMBER with a kitchen unit, starting with "~", \
e.g. "~1 cup / 120 g", "~1/2 tsp", "~2 tbsp", "~1 pinch". Never write "to taste", "a little" \
or "plenty"; that is what her_words is for; turn it into your best numeric guess for a family \
of four. `confidence` is "high" ONLY if she said a number ("do cup", "teen seeti"); "med" for a \
known household measure ("ek katori", "do mutthi"); "low" for andaaz/thoda sa/khoob sara. \
If she gave one amount for several things together ("teeno mila ke ek katori"), make ONE \
ingredient for the mix; do not repeat the amount for each.
4. `name` is the ingredient in simple English with her word in brackets: "Turmeric (haldi)", \
"Semolina (sooji)".
5. `steps[].text` is a short, clear instruction in simple English, in the order she does \
them. Combine consecutive lines about the same action into one step. A warning is not a \
step; put it in `warnings`. `her_cue` is her sensory \
cue copied exactly from the transcript ("jab tak tel chhod de", "khushboo aane tak"), \
or "" if she gave none. `start_sec` is copied exactly from the [time] label of the line where \
she explains that step.
6. `quotes`: up to 3 memorable lines copied exactly from the transcript: warmth, wisdom, humour.
7. `tips` and `warnings`: only ones she actually said ("dhakkan mat kholna"). English is fine, \
keep her phrase in brackets. Each goes in one list only; a warning is not also a tip.
8. `story`: one line about the dish's origin, occasion or who loved it, only if she said so, else "".
9. `ask_next_time`: what SHE skipped or left unclear in THIS transcript, as short questions to ask \
her: missing times, amounts, temperatures, how many it serves. The style, for a different dish: \
{examples}. Never copy these; never ask about something she already said.
10. Speech-to-text makes mistakes. In `name`, `text`, tips you may fix an obvious mistake \
(e.g. a misheard spice name). Do not guess beyond that. Never change her_words, her_cue or quotes.
Reply with JSON only."""

# Style examples for ask_next_time, deliberately about another dish. Small models sometimes
# copy prompt examples verbatim, so any reply that does is filtered out in write_recipe().
EXAMPLE_QUESTIONS = ["How long did you roast the sooji for the halwa?", "How much sugar for one katori of sooji?"]
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{examples}", ", ".join(f'"{q}"' for q in EXAMPLE_QUESTIONS))

CHUNK_NOTE = (
    "\nThis is PART {i} of {n} of a long recording. Extract only what is in this part; "
    "the parts will be merged afterwards. Leave `story` empty unless this part contains it."
)

# Devanagari tokenizes at roughly 2-3 chars/token for Gemma; be conservative.
CHARS_PER_TOKEN = 2.2
RESERVED_TOKENS = 5000  # system prompt + JSON reply


def format_segments(segments: list[Segment]) -> str:
    return "\n".join(f"[{s.start:.1f}] {s.text.strip()}" for s in segments if s.text.strip())


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def chunk_segments(segments: list[Segment], num_ctx: int, overlap: int = 2) -> list[list[Segment]]:
    """Greedy split into chunks that fit `num_ctx`, repeating `overlap` segments at each seam
    so a step that straddles two chunks is seen whole at least once."""
    budget = max(1000, num_ctx - RESERVED_TOKENS)
    if estimate_tokens(format_segments(segments)) <= budget:
        return [segments] if segments else []
    chunks: list[list[Segment]] = []
    cur: list[Segment] = []
    cur_tokens = 0
    for seg in segments:
        t = estimate_tokens(f"[{seg.start:.1f}] {seg.text}") + 1
        if cur and cur_tokens + t > budget:
            chunks.append(cur)
            cur = cur[-overlap:] if overlap else []
            cur_tokens = sum(estimate_tokens(f"[{s.start:.1f}] {s.text}") + 1 for s in cur)
        cur.append(seg)
        cur_tokens += t
    if cur:
        chunks.append(cur)
    return chunks


def build_messages(segments: list[Segment], cook: str, dish: str, language: str, part: tuple[int, int] | None = None) -> list[dict]:
    header = []
    if dish:
        header.append(f"Dish (given by the family): {dish}")
    if cook:
        header.append(f"Cook: {cook}")
    if language:
        header.append(f"Detected language: {language}")
    user = "\n".join(header) + "\n\nTRANSCRIPT:\n" + format_segments(segments)
    system = SYSTEM_PROMPT + (CHUNK_NOTE.format(i=part[0], n=part[1]) if part and part[1] > 1 else "")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_reply(text: str) -> Recipe:
    """Parse a model reply into a Recipe. Tolerates code fences and chatter around the JSON."""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    if not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise HaathError("The model did not reply with a recipe (no JSON found).", "run: haath redo <id>   or try another model with --model")
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HaathError(f"The model's reply was not valid JSON ({e.msg}).", "run: haath redo <id>   (a larger --num-ctx helps if the reply was cut off)") from e
    if isinstance(data, dict) and "recipe" in data and isinstance(data["recipe"], dict):
        data = data["recipe"]
    try:
        return Recipe.model_validate(data)
    except ValidationError as e:
        raise HaathError(f"The model's reply did not match the recipe shape: {e.errors()[0]['msg']}", "run: haath redo <id>") from e


# ---- merging ----------------------------------------------------------------

_CONF_RANK = {"low": 0, "med": 1, "high": 2}


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b, autojunk=False).ratio() >= threshold


def _dedupe(items: list[str], threshold: float = 0.85) -> list[str]:
    out: list[str] = []
    for item in items:
        if item.strip() and not any(_similar(item, o, threshold) for o in out):
            out.append(item.strip())
    return out


def _ingredient_key(ing: Ingredient) -> str:
    name = re.sub(r"\(.*?\)", " ", ing.name)  # "Turmeric (haldi)" and "Turmeric" are one thing
    return normalize(name) or normalize(ing.her_words)


def merge_recipes(parts: list[Recipe]) -> Recipe:
    if not parts:
        return Recipe()
    if len(parts) == 1:
        return parts[0]
    merged = Recipe(
        dish=next((p.dish for p in parts if p.dish), ""),
        cook=next((p.cook for p in parts if p.cook), ""),
        story=next((p.story for p in parts if p.story), ""),
    )

    by_key: dict[str, Ingredient] = {}
    for p in parts:
        for ing in p.ingredients:
            key = _ingredient_key(ing)
            if not key:
                continue
            have = by_key.get(key)
            if have is None:
                by_key[key] = ing.model_copy()
                continue
            # Same ingredient mentioned in two chunks: keep the better-informed version.
            if not have.her_words and ing.her_words:
                have.her_words = ing.her_words
            if _CONF_RANK[ing.confidence] > _CONF_RANK[have.confidence] and ing.approx:
                have.approx, have.confidence = ing.approx, ing.confidence
            elif not have.approx and ing.approx:
                have.approx, have.confidence = ing.approx, ing.confidence
    merged.ingredients = list(by_key.values())

    steps: list[Step] = []
    for p in parts:
        for st in p.steps:
            dup = next(
                (
                    s
                    for s in steps[-4:]  # duplicates only happen around chunk seams, close in time
                    if abs(s.start_sec - st.start_sec) <= 60
                    and (_similar(s.text, st.text, 0.8) or (st.her_cue and normalize(s.her_cue) == normalize(st.her_cue)))
                ),
                None,
            )
            if dup is None:
                steps.append(st.model_copy())
            elif not dup.her_cue and st.her_cue:
                dup.her_cue = st.her_cue
    merged.steps = sorted(steps, key=lambda s: s.start_sec)

    merged.tips = _dedupe([t for p in parts for t in p.tips])
    merged.warnings = _dedupe([w for p in parts for w in p.warnings])
    quotes = _dedupe([q for p in parts for q in p.quotes], 0.9)
    merged.quotes = sorted(quotes, key=len, reverse=True)[:3] if len(quotes) > 3 else quotes
    merged.ask_next_time = _dedupe([q for p in parts for q in p.ask_next_time], 0.8)
    return merged


# ---- Ollama -----------------------------------------------------------------


def _ollama_error(e: Exception, host: str, model: str) -> HaathError:
    msg = str(e)
    status = getattr(e, "status_code", None)
    if status == 404 or "not found" in msg.lower():
        return HaathError(f"The model {model} is not pulled in Ollama.", f"run: ollama pull {model}")
    if isinstance(e, ConnectionError) or "connect" in msg.lower() or "refused" in msg.lower():
        return HaathError(f"Ollama is not running at {host}.", "run: ollama serve   (install from https://ollama.com/download if missing)")
    if "memory" in msg.lower():
        return HaathError(f"Ollama ran out of memory loading {model}: {msg}", "close other apps, or use a smaller context: --num-ctx 8192, or a smaller model: --model gemma4:e2b")
    return HaathError(f"Ollama error: {msg}", "run: haath doctor")


def make_client(host: str):
    try:
        import ollama
    except ImportError as e:
        raise HaathError("The `ollama` Python package is missing.", "run: pip install ollama   (or reinstall: uv tool install .)") from e
    return ollama.Client(host=host, timeout=1800)


def ask_model(client, model: str, messages: list[dict], num_ctx: int, host: str, think: bool = False) -> str:
    kwargs = dict(
        model=model,
        messages=messages,
        format=Recipe.llm_schema(),
        options={"temperature": 0.1, "num_ctx": num_ctx, "num_predict": 4096},
        keep_alive="10m",
        # Gemma 4 thinks by default; for copying her words out of a transcript that hidden
        # reasoning only costs minutes on a laptop CPU. --think turns it back on.
        think=think,
    )
    try:
        try:
            resp = client.chat(**kwargs)
        except Exception as e:
            if "think" not in str(e).lower():
                raise
            kwargs.pop("think")  # model without a thinking mode
            resp = client.chat(**kwargs)
    except Exception as e:  # ollama raises ResponseError / httpx errors / ConnectionError
        raise _ollama_error(e, host, model) from e
    return resp["message"]["content"] if isinstance(resp, dict) else resp.message.content


def write_recipe(
    transcript: Transcript,
    cook: str,
    dish: str,
    model: str,
    host: str,
    num_ctx: int,
    progress: Callable[[float, str], None] | None = None,
    ask: Callable[[list[dict]], str] | None = None,
    think: bool = False,
) -> Recipe:
    """Run Gemma over the transcript (chunked if needed) and return the merged, un-verified Recipe."""
    if not transcript.segments:
        raise HaathError("The transcript is empty: no speech was heard in the recording.", "check the mic, then record again closer to her (phone ~1 m away)")
    chunks = chunk_segments(transcript.segments, num_ctx)
    if ask is None:
        client = make_client(host)

        def ask(msgs: list[dict]) -> str:
            return ask_model(client, model, msgs, num_ctx, host, think)

    parts = []
    for i, chunk in enumerate(chunks, 1):
        if progress:
            progress((i - 1) / len(chunks), f"writing the card (part {i} of {len(chunks)})" if len(chunks) > 1 else "writing the card")
        parts.append(parse_reply(ask(build_messages(chunk, cook, dish, transcript.language, (i, len(chunks))))))
    recipe = merge_recipes(parts)
    copied = {normalize(q) for q in EXAMPLE_QUESTIONS}
    recipe.ask_next_time = [q for q in recipe.ask_next_time if normalize(q) not in copied]
    # The family's own labels win over whatever the model heard.
    recipe.dish = dish or recipe.dish
    recipe.cook = cook or recipe.cook
    return recipe
