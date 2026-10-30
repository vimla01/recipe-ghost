# हाथ का स्वाद · Haath ka Swaad

**For every recipe that only exists in her hands.**

Record Mummy, Nani or Dadi cooking while she explains in Hindi, Marathi, Gujarati or Hinglish
(*"thoda sa haldi, jab tak khushboo na aaye"*), and get back a recipe card that keeps **her words**,
adds **approximate measures** beside them, and lets you press ▶ on any step to **hear her voice**
explain it. Everything runs on your laptop. Nothing leaves it.

---

## The problem

The best food in most Indian families was never written down. It lives in *andaaz*: "ek mutthi atta",
"namak andaaz se", "jab tak tel chhod de". When you ask for the recipe you get a shrug and
"bas, dekh ke seekh lo" (just watch and learn). And one day there is no one left to watch.

Recording a video helps, but a 40-minute video is not a recipe. Typing it up loses her voice.
Cloud transcription apps want an account, a subscription and your grandmother's voice on their servers.

## The solution

1. **Record** her cooking in the browser (or drop in a WhatsApp/phone voice note).
2. **faster-whisper** transcribes it on your laptop with timestamps, auto-detecting Hindi/Marathi/Gujarati/English.
3. **Gemma** (via **Ollama**, also on your laptop) turns the transcript into a recipe card:
   ingredients in her words + approximate measures, steps with her sensory cues, tips, warnings,
   memorable quotes, and a list of questions to *ask her next time*. Every phrase kept in
   Hindi/Marathi/Gujarati also gets a small English meaning underneath, for family who can't read the script.
4. An **anti-hallucination guard** checks every quote, measure and cue against the transcript and
   removes anything she never said. Each step is snapped to the moment she said it.
5. The **recipe card** shows her words big, the estimates small, and a ▶ button on every step that
   plays *her voice* from that moment. The **kitchen book** prints every recipe, one per page.
6. **Review** it together: tick each line once she confirms it. The card shows how much the family
   has checked, and changing a line takes its tick away, so a "family-checked" card means exactly that.

## Screenshots

| | |
|---|---|
| <img src="docs/screenshots/card-top.png" alt="Recipe card, top: her words in handwriting with English meanings and approximate measures"> | <img src="docs/screenshots/card-method.png" alt="Recipe card, method: a play button on every step and her cue in her own words"> |
| **The recipe card.** Her words are big, in her own script, with a small English meaning underneath. Gemma's estimates sit beside them, marked `~`. | **The method.** Every step has a ▶ that plays her voice from that moment, with her cue ("jab tak tel na chhod de") in her own words. |

| | |
|---|---|
| <img src="docs/screenshots/recording.png" alt="Recording in progress: the button becomes Stop and the timer runs"> | <img src="docs/screenshots/playing.png" alt="Playing a step: the step is highlighted and the player bar shows her voice"> |
| **Recording.** The heading follows the cook's name; the screen stays awake. | **▶ Her voice.** The step lights up while it plays, and stops at the next step. |
| <img src="docs/screenshots/notes.png" alt="Tips, warnings, her quotes, questions to ask next time and the full transcript"> | <img src="docs/screenshots/review.png" alt="Review mode: a tick on every line and a progress bar of lines checked by the family"> |
| **Tips, quotes, "Ask Nani next time"** and the full transcript with tap-to-play times. | **Review with her.** Go through the card together and tick every line that's right. Edited lines need a fresh tick. |
| <img src="docs/screenshots/edit.png" alt="Edit mode: every field can be fixed by hand"> | <img src="docs/screenshots/book.png" alt="Kitchen book: cover with contents and one recipe per printed page"> |
| **Edit.** Fix anything Whisper or Gemma got wrong. | **Kitchen book.** One recipe per page, prints to PDF, opens offline. Fully checked recipes say so. |
| <img src="docs/screenshots/mobile.png" alt="The recipe card on a phone" width="320"> | |
| **On a phone** on the kitchen counter (`haath ui --lan`). | |

<p align="center"><img src="docs/screenshots/home.png" alt="Home page: the marigold toran, the record panel and the family kitchen with live status for each recipe" width="900"></p>

<p align="center"><b>The family kitchen.</b> Record (or upload a voice note) on the left; every recipe on the right, with live status while Whisper and Gemma work.</p>

<sub>Screenshots use the built-in sample recipe (`haath ui --mock`), not a real family recording.</sub>

## How it works

![How Haath ka Swaad works: her voice → Whisper → Gemma → guard → recipe card, all on your laptop](docs/how-it-works.svg)

<details>
<summary>Text version</summary>

```
   🎙  browser MediaRecorder / phone voice note
    │
    ▼
 ┌─────────────────────────────── your laptop ────────────────────────────────┐
 │                                                                            │
 │  original audio ──► faster-whisper (large-v3-turbo, CPU int8 / CUDA)       │
 │        │               segments + word timestamps + detected language      │
 │        │               long segments re-cut at sentence ends (। . ? !)     │
 │        │                          │                                        │
 │        │                          ▼                                        │
 │        │          Gemma via Ollama (format = Recipe JSON schema)           │
 │        │          long recordings: chunk → extract each → merge            │
 │        │                          │                                        │
 │        │                          ▼                                        │
 │        │          guard: every quote / her_words / her_cue must appear     │
 │        │          in the transcript (Devanagari + Hinglish normalized);    │
 │        │          steps snapped to the segment that contains them          │
 │        │                          │                                        │
 │        ▼                          ▼                                        │
 │  voice.m4a (seekable)      recipe.json ──► recipe card ▶ ──► book.html     │
 │                                                                            │
 └──────────────────── no network calls · works with Wi-Fi off ───────────────┘
```

</details>

One background worker handles one recording at a time, so Whisper and Gemma never fight over the CPU.
Each recipe lives in its own folder:

```
~/HaathKaSwaad/
├── book.html                    # haath book: opens offline by double-click
└── recipes/20261030-dal-baati-a734/
    ├── original.webm            # her voice, untouched
    ├── voice.m4a                # seekable copy for ▶ playback
    ├── transcript.json          # segments with timestamps
    ├── recipe.json              # the card (edit by hand in the UI)
    └── meta.json                # status, model used, what the guard removed
```

All writes are atomic (temp file + rename), so a closed laptop lid never leaves a broken recipe.

## Setup

You need Python 3.11+ and about 8 GB of free disk (models). No ffmpeg needed: audio decoding
comes bundled with faster-whisper (PyAV).

```bash
# 1. Ollama: https://ollama.com/download  (Linux: curl -fsSL https://ollama.com/install.sh | sh)
ollama pull gemma4:e4b

# 2. Haath ka Swaad (from this folder)
pipx install .               # or: uv tool install .
# Ubuntu/Debian: plain `pip install .` is blocked (PEP 668), use pipx (sudo apt install pipx)
# Then run once and open a new terminal so `haath` is on your PATH: pipx ensurepath

# 3. One-time Whisper download (~1.6 GB), then check everything
haath doctor --download

# 4. Open the kitchen
haath ui
```

After step 3 you can turn Wi-Fi off. `haath doctor` tells you exactly what's missing and how to fix it:

```
  ✓ faster-whisper + PyAV: PyAV 15.1.0 decodes webm/m4a/opus/mp3, no ffmpeg needed
  ✓ Whisper model large-v3-turbo: downloaded (works offline)
  ✗ Ollama server: not reachable at http://localhost:11434
      → run: ollama serve
```

**Try it without any models:** `haath ui --mock` (sample Dal Baati transcript + model reply).

## Using it

| Command | What it does |
|---|---|
| `haath ui [archive]` | Opens http://127.0.0.1:8767: record, watch status, read and edit cards |
| `haath ui --lan` | Also serves https on your Wi-Fi, so the phone on the kitchen counter can record too |
| `haath add voice.m4a --cook "Mummy" --dish "Dal Baati"` | Add an existing phone voice note |
| `haath list` | All recipes with status |
| `haath redo <id>` | Re-run Gemma (e.g. after `--model` change); `--full` also re-transcribes |
| `haath book` | Writes `book.html`: every recipe, printable, plays her voice offline |
| `haath doctor` | Checks Whisper model, Ollama and the Gemma model |

Useful flags (any command): `--lang hi|mr|gu|en` to force the language, `--whisper-model small` for
slow laptops, `--model gemma4:e2b` for a smaller/faster Gemma, `--num-ctx 8192` to use less RAM,
`--archive PATH`. Environment: `OLLAMA_HOST`, `HAATH_ARCHIVE`, `HAATH_MODEL`, `HAATH_WHISPER_MODEL`.

**Tips for a good recording**

- Not just Mummy and Nani: Dad, Dadu, Chachi, anyone. The card uses the cook's name everywhere
  ("Hear Dad from the start", "Ask Dad next time").
- *Ask her first.* Tell her what it's for. Most nanis love this once they understand.
- Phone on the counter? Run `haath ui --lan`, open the `https://192.168.…` address it prints on the
  phone, accept the one-time certificate warning (it's your laptop's own), and press Record.
- Put the phone/laptop about a metre away, not next to the pressure cooker or exhaust fan.
- Ask her to *say* what she's doing: "ab kitna daala?", "kab tak?" The card can only use what she says.
- Long is fine. 20–40 minute recordings are split into parts and merged.
- Afterwards, read the **Ask her next time** list, and actually ask her.

**How long does it take?** Measured on a CPU-only laptop (Intel i5-1334U, 16 GB RAM, already
deep in swap from other apps), for an 85-second Hindi recording: Whisper large-v3-turbo took
~1 min to load plus ~2.3 min to transcribe; Gemma 4 e4b took ~12 min to write the card.
Gemma needs several GB of *free* RAM; on a laptop that isn't swapping it is much faster. If it's slow:
close heavy apps (browsers with many tabs, Docker/Kubernetes), or use `--model gemma4:e2b`,
`--num-ctx 8192` and `--whisper-model small`. A GPU makes both much faster. You can close the
browser tab while it works; the status shows when it's done.

## Privacy: why local and open matters

- **Her voice never touches a server.** Recordings of elders, family stories, a grandmother laughing
  at her own joke: that is about as personal as data gets. Here it stays in a folder on your disk.
- **Works with Wi-Fi off.** After the one-time model downloads, there is no network access at all.
  The UI binds to 127.0.0.1 and uses no CDNs; fonts are bundled.
- **No subscription that can disappear.** No account, no API key, no company that can shut down and
  take the family recipes with it. The archive is plain JSON + audio files you can copy anywhere.
- **Swap models freely.** Whisper and Gemma are open models. Use a newer Gemma, a regional
  fine-tune, or a bigger model on a better laptop: `--model …`, then `haath redo <id>`.

## Limitations

- **Accents and dialects.** Whisper is good at Hindi and decent at Marathi/Gujarati, but strong
  regional dialects, Marwari/Bhojpuri words and fast code-switching will produce mistakes.
  Use **Edit** to fix them. You know her better than the machine does.
- **Noisy kitchens.** Pressure-cooker whistles, mixer-grinders and exhaust fans hurt accuracy.
- **Shared amounts.** "Teeno dal mila ke ek katori" is one katori for the mix. The guard merges
  such items into one line ("~1 cup all together") when she says a "together" word (mila ke,
  teeno, dono…); if she doesn't, they may show as ~1 cup each, but her words beside them show the truth.
- **Approximate measures are estimates.** "Ek mutthi" depends on whose fist. The `approx` column is
  Gemma's guess and is always marked `~`. Her words come first.
- **The guard checks wording, not meaning.** It removes quotes and measures that aren't in the
  transcript, but it can't know whether a step's English summary is perfect. That's what **Review** is
  for: read the card with her and tick each line.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest           # verification, snapping, parsing, merging, pipeline, API
.venv/bin/haath ui --mock  # full UI without Whisper or Ollama
```

## License

MIT, see [LICENSE](LICENSE). Bundled fonts (Kalam, Tiro Devanagari Hindi, Mukta) are under the
SIL Open Font License 1.1, see `src/haath/static/fonts/`.
