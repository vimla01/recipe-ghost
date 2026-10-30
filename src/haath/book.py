"""The kitchen book: every recipe, one per printed page.

Served live at /book, and written by `haath book` as a single self-contained
book.html (CSS and fonts inlined) that links each recording relatively, so it
opens offline with a double-click from the archive folder.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable
from datetime import datetime
from html import escape
from importlib.resources import files
from pathlib import Path

from haath.models import Meta, Recipe
from haath.storage import Archive, atomic_write_bytes

STATIC = Path(str(files("haath") / "static"))

BOOK_CSS = """
:root { --ink:#3b2417; --soft:#6e5442; --muted:#9a8270; --red:#8f1d21; --mari:#e8890c; --mari2:#f5b324; --rule:#e6d3b3; --leaf:#5d7a33;
  --serif:"Tiro Devanagari Hindi",Georgia,serif; --hand:"Kalam","Tiro Devanagari Hindi",cursive; --sans:"Mukta",system-ui,sans-serif; }
* { box-sizing:border-box; }
body { margin:0; background:#efe1c6; color:var(--ink); font-family:var(--sans); font-size:16.5px; line-height:1.5; }
.page { background:#fffaf0; max-width:820px; margin:28px auto; padding:48px 56px 40px 72px; position:relative;
  box-shadow:0 10px 30px -12px rgba(85,45,10,.35); border-radius:4px; }
.page::before { content:""; position:absolute; top:0; bottom:0; left:46px; border-left:2px solid rgba(179,40,45,.25); }
.cover { text-align:center; padding:90px 40px; }
.cover h1 { font-family:var(--serif); font-weight:400; font-size:54px; color:var(--red); margin:10px 0 0; }
.cover .en { font-family:var(--serif); font-style:italic; font-size:22px; color:var(--soft); }
.cover .tag { font-family:var(--hand); font-size:24px; color:var(--mari); margin-top:26px; }
.cover .flowers { font-size:0; }
.cover svg { width:44px; height:44px; margin:0 3px; }
.toc { list-style:none; padding:0; margin:40px auto 0; max-width:440px; text-align:left; }
.toc li { display:flex; gap:8px; padding:5px 0; border-bottom:1px dotted var(--rule); }
.toc a { color:var(--ink); text-decoration:none; font-family:var(--serif); font-size:19px; }
.toc span { margin-left:auto; color:var(--muted); font-size:14px; }
h2 { font-family:var(--serif); font-weight:400; font-size:38px; color:var(--red); margin:0; line-height:1.15; }
h3 { font-family:var(--serif); font-weight:400; font-size:21px; color:var(--red); margin:26px 0 8px; }
.by { font-family:var(--hand); font-size:19px; color:var(--soft); }
.by b { color:var(--mari); }
.story { font-family:var(--serif); font-style:italic; font-size:18px; margin:10px 0 0; }
ul.ing { list-style:none; padding:0; margin:0; columns:2; column-gap:30px; }
ul.ing li { break-inside:avoid; padding:5px 0; border-bottom:1px dotted var(--rule); }
.her { font-family:var(--hand); font-size:20px; line-height:1.3; }
.name { color:var(--soft); font-size:15px; }
.approx { color:var(--muted); font-size:13px; }
ol.steps { padding-left:0; list-style:none; counter-reset:s; margin:0; }
ol.steps li { counter-increment:s; display:grid; grid-template-columns:34px 1fr; gap:8px; padding:7px 0; border-bottom:1px dotted var(--rule); break-inside:avoid; }
ol.steps li::before { content:counter(s); width:26px; height:26px; border-radius:50%; background:var(--red); color:#fff; display:grid; place-items:center; font-size:13px; font-weight:600; margin-top:2px; }
.cue { font-family:var(--hand); color:var(--red); font-size:18px; }
.cue::before { content:"“"; } .cue::after { content:"”"; }
.play { display:inline-block; margin-left:6px; font-size:13px; color:var(--mari); text-decoration:none; border:1px solid var(--mari); border-radius:99px; padding:0 9px; cursor:pointer; background:none; }
.notes { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:20px; }
.note { padding:10px 14px; border-radius:10px; break-inside:avoid; }
.note.t { background:rgba(245,179,36,.15); } .note.w { background:rgba(143,29,33,.07); }
.note h4 { margin:0 0 4px; font-family:var(--serif); font-weight:400; font-size:17px; }
.note ul { margin:0; padding-left:18px; }
blockquote { margin:12px 0 0; padding-left:16px; border-left:4px solid var(--mari2); font-family:var(--hand); font-size:21px; break-inside:avoid; }
.asks li { padding:2px 0; }
.foot { color:var(--muted); font-size:12.5px; margin-top:26px; }
.bar { position:sticky; top:0; z-index:2; background:#3b2417; color:#fff3dc; text-align:center; padding:8px; font-size:14px; }
.bar button { margin-left:10px; background:var(--mari); color:#fff; border:none; border-radius:99px; padding:4px 14px; font:inherit; cursor:pointer; }
@media (max-width:640px) { .page { padding:28px 20px 28px 34px; margin:12px 6px; } .page::before { left:20px; } ul.ing { columns:1; } .notes { grid-template-columns:1fr; } }
@page { size:A4; margin:16mm 14mm; }
@media print {
  body { background:#fff; font-size:12pt; }
  .page { box-shadow:none; margin:0; max-width:none; padding:0 0 0 22px; break-after:page; }
  .page::before { left:4px; }
  .bar, .play { display:none !important; }
  a { color:inherit; text-decoration:none; }
}
"""

BOOK_JS = """
const a = new Audio(); let stopAt = null;
a.addEventListener('timeupdate', () => { if (stopAt != null && a.currentTime >= stopAt) { a.pause(); stopAt = null; } });
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-src]'); if (!b) return;
  e.preventDefault();
  const src = b.dataset.src, t = parseFloat(b.dataset.t || 0), u = b.dataset.until ? parseFloat(b.dataset.until) : null;
  const go = () => { a.currentTime = t; stopAt = u; a.play().catch(err => alert('Could not play: ' + err.message + '\\nKeep book.html next to the recipes/ folder.')); };
  if (a.getAttribute('src') !== src) { a.setAttribute('src', src); a.addEventListener('loadedmetadata', go, { once: true }); a.load(); } else go();
});
"""

MARIGOLD = (
    '<svg viewBox="0 0 40 40" aria-hidden="true"><g fill="#e8890c"><circle cx="20" cy="9" r="7"/><circle cx="31" cy="15" r="7"/>'
    '<circle cx="29" cy="28" r="7"/><circle cx="16" cy="31" r="7"/><circle cx="9" cy="19" r="7"/></g><g fill="#f5b324">'
    '<circle cx="20" cy="13" r="5"/><circle cx="27" cy="17" r="5"/><circle cx="25" cy="25" r="5"/><circle cx="17" cy="26" r="5"/>'
    '<circle cx="13" cy="19" r="5"/></g><circle cx="20" cy="20" r="4.5" fill="#c9600a"/></svg>'
)


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"


def _inline_fonts() -> str:
    css = (STATIC / "fonts.css").read_text(encoding="utf-8")

    def data_uri(m: re.Match) -> str:
        data = (STATIC / m.group(1)).read_bytes()
        return f'url("data:font/woff2;base64,{base64.b64encode(data).decode()}")'

    return re.sub(r'url\("([^"]+\.woff2)"\)', data_uri, css)


def render_recipe(meta: Meta, r: Recipe, audio_src: str) -> str:
    e = escape
    who = e(r.cook or meta.cook or "her")
    steps = r.steps
    out = [f'<section class="page" id="{e(meta.id)}">', f"<h2>{e(r.dish or meta.dish or 'Untitled')}</h2>"]
    out.append(f'<div class="by">as told by <b>{who}</b>' + (f" · {_fmt(meta.duration)} of her voice" if meta.duration else "") + "</div>")
    if r.story:
        out.append(f'<p class="story">{e(r.story)}</p>')
    if r.ingredients:
        out.append('<h3>Ingredients</h3><ul class="ing">')
        for g in r.ingredients:
            out.append("<li>")
            if g.her_words:
                out.append(f'<div class="her">{e(g.her_words)}</div>')
            out.append(f'<div class="name">{e(g.name)}</div>')
            if g.approx:
                out.append(f'<div class="approx">{e(g.approx)} approx.</div>')
            out.append("</li>")
        out.append("</ul>")
    if steps:
        out.append('<h3>Method</h3><ol class="steps">')
        for i, s in enumerate(steps):
            later = [x.start_sec for x in steps[i + 1 :] if x.start_sec > s.start_sec]
            until = f' data-until="{min(later) + 0.5:.2f}"' if later else ""
            play = f'<button class="play" data-src="{e(audio_src)}" data-t="{s.start_sec:.2f}"{until}>▶ {_fmt(s.start_sec)}</button>'
            cue = f'<div class="cue">{e(s.her_cue)}</div>' if s.her_cue else ""
            out.append(f"<li><div>{e(s.text)} {play}{cue}</div></li>")
        out.append("</ol>")
    if r.tips or r.warnings:
        out.append('<div class="notes">')
        if r.tips:
            out.append('<div class="note t"><h4>Her tips</h4><ul>' + "".join(f"<li>{e(t)}</li>" for t in r.tips) + "</ul></div>")
        if r.warnings:
            out.append('<div class="note w"><h4>Careful!</h4><ul>' + "".join(f"<li>{e(t)}</li>" for t in r.warnings) + "</ul></div>")
        out.append("</div>")
    for q in r.quotes:
        out.append(f"<blockquote>{e(q)} <small>— {who}</small></blockquote>")
    if r.ask_next_time:
        out.append('<h3>Ask her next time</h3><ul class="asks">' + "".join(f"<li>{e(q)}</li>" for q in r.ask_next_time) + "</ul>")
    out.append(f'<p class="foot">Recorded {e(meta.created[:10])} · kept in recipes/{e(meta.id)}/</p></section>')
    return "\n".join(out)


def render_book(archive: Archive, audio_url: Callable[[str], str], inline_assets: bool) -> str:
    entries = []
    for meta in sorted(archive.list(), key=lambda m: (m.dish or "").lower()):
        r = archive.load_recipe(meta.id) if meta.status == "done" else None
        if r:
            entries.append((meta, r))
    fonts = f"<style>{_inline_fonts()}</style>" if inline_assets else '<link rel="stylesheet" href="/static/fonts.css">'
    cooks = sorted({(r.cook or m.cook) for m, r in entries if (r.cook or m.cook)})
    toc = "".join(f'<li><a href="#{escape(m.id)}">{escape(r.dish or m.dish or "Untitled")}</a><span>{escape(r.cook or m.cook)}</span></li>' for m, r in entries)
    cover = (
        '<section class="page cover">'
        f'<div class="flowers">{MARIGOLD * 5}</div>'
        '<h1 lang="hi">हाथ का स्वाद</h1><div class="en">Haath ka Swaad — the family kitchen book</div>'
        '<div class="tag">For every recipe that only exists in her hands.</div>'
        + (f'<p class="by">with {escape(", ".join(cooks))}</p>' if cooks else "")
        + (f'<ul class="toc">{toc}</ul>' if entries else '<p class="by">No finished recipes yet — record one with <b>haath ui</b>.</p>')
        + f'<p class="foot">Made {datetime.now():%d %B %Y} · everything in this book stayed on the family laptop</p></section>'
    )
    pages = "\n".join(render_recipe(m, r, audio_url(m.id)) for m, r in entries)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Haath ka Swaad — Kitchen book</title>{fonts}<style>{BOOK_CSS}</style></head><body>"
        '<div class="bar">The family kitchen book · ▶ plays her voice · <button onclick="print()">Print / save as PDF</button></div>'
        f"{cover}\n{pages}<script>{BOOK_JS}</script></body></html>"
    )


def write_book(archive: Archive, out: Path | None = None) -> Path:
    out = (out or archive.root / "book.html").resolve()

    def rel_audio(rid: str) -> str:
        return Path(os.path.relpath(archive.audio_path(rid), out.parent)).as_posix()

    html = render_book(archive, audio_url=rel_audio, inline_assets=True)
    atomic_write_bytes(out, html.encode("utf-8"))
    return out
