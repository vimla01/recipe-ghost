// Haath ka Swaad: plain JS, no build step, no network beyond 127.0.0.1.

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");

// el("div", {class: "x", onclick: fn}, "text", child). Never uses innerHTML for data.
function el(tag, attrs = {}, ...children) {
  const node = tag === "svg-use" ? svgUse(attrs.href, attrs.class) : document.createElement(tag);
  if (tag !== "svg-use") {
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (k === "class") node.className = v;
      else if (k === "value") node.value = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of children.flat()) if (c != null && c !== false) node.append(c instanceof Node ? c : String(c));
  return node;
}
function svgUse(href, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", href);
  svg.append(use);
  return svg;
}
const icon = (name, cls) => el("svg-use", { href: "#" + name, class: cls });

const norm = (s) => (s || "").normalize("NFKC").toLowerCase().replace(/[\u200b-\u200f\u2060\ufeff]/g, "")
  .replace(/[^\p{L}\p{M}\p{N}]+/gu, " ").trim();
const cap = (s) => (s || "").trim().replace(/^./, (c) => c.toUpperCase());
const fmt = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
};
const LANGS = { hi: "Hindi", mr: "Marathi", gu: "Gujarati", en: "English", ur: "Urdu", pa: "Punjabi", bn: "Bengali", ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam" };
const STATUS = { queued: "waiting", transcribing: "listening", writing: "writing the card", done: "ready", error: "needs attention" };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.detail || res.statusText);
    err.fix = data.fix || "";
    throw err;
  }
  return data;
}

function banner(msg, fix) {
  const b = $("#banner");
  b.replaceChildren();
  if (!msg) return (b.hidden = true);
  b.append(el("strong", {}, msg));
  if (fix) b.append(" → ", el("code", {}, fix));
  b.hidden = false;
}

let STATUS_INFO = { mock: false };
let pollTimer = null;
function poll(fn, ms = 1500) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(fn, ms);
}

// ---- router ----------------------------------------------------------------

async function route() {
  clearTimeout(pollTimer);
  stopRecordingUI?.();
  const hash = location.hash || "#/";
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === "home" && hash === "#/"));
  const m = hash.match(/^#\/r\/([a-z0-9-]+)(\/edit)?$/);
  window.scrollTo(0, 0);
  if (m) return m[2] ? renderEdit(m[1]) : renderRecipe(m[1]);
  return renderHome();
}
window.addEventListener("hashchange", route);

// ---- home ------------------------------------------------------------------

let stopRecordingUI = null;

function renderHome() {
  const listBox = el("div", { class: "recipes" });
  app.replaceChildren(
    el("div", { class: "home" },
      recordPanel(),
      el("section", {},
        el("div", { class: "list-head" },
          el("h2", {}, "The family kitchen"),
          el("a", { href: "/book", target: "_blank", class: "small" }, "Open the kitchen book →")),
        listBox)));
  refreshList(listBox);
}

async function refreshList(box) {
  let items;
  try {
    items = await api("/api/recipes");
  } catch (e) {
    box.replaceChildren(el("p", { class: "muted" }, "Could not load recipes: " + e.message));
    return poll(() => refreshList(box), 4000);
  }
  if (!document.body.contains(box)) return;
  if (!items.length) {
    box.replaceChildren(el("div", { class: "card empty" }, icon("marigold"),
      el("p", {}, "No recipes yet. The first one is always the hardest to ask for."),
      el("p", { class: "small muted" }, "Sit with them while they cook. Press record. Let them talk.")));
  } else {
    box.replaceChildren(...items.map(recipeRow));
  }
  if (items.some((m) => !["done", "error"].includes(m.status))) poll(() => refreshList(box));
}

function recipeRow(m) {
  const busy = !["done", "error"].includes(m.status);
  const when = m.created ? new Date(m.created).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
  const sub = [m.cook && `as told by ${m.cook}`, when, m.duration ? fmt(m.duration) : null, m.status === "done" ? `${m.n_steps} steps` : null,
    m.review_done ? `${m.review_done}/${m.review_total} checked` : null].filter(Boolean).join(" · ");
  const allChecked = m.status === "done" && m.review_total > 0 && m.review_done === m.review_total;
  const chip = el("span", { class: "chip " + (busy ? "busy" : m.status) }, busy ? el("span", { class: "busy-dot" }) : null, allChecked ? "✓ family-checked" : STATUS[m.status] || m.status);
  return el("a", { class: "rcard " + m.status, href: `#/r/${m.id}` },
    icon("marigold", "flower"),
    el("div", {},
      el("div", { class: "title" }, m.dish || "Untitled recipe"),
      el("div", { class: "sub" }, sub),
      busy ? el("div", { class: "sub" }, m.message || "") : null,
      busy ? el("div", { class: "progress" }, el("div", { style: `width:${Math.round((m.progress || 0) * 100)}%` })) : null,
      m.status === "error" ? el("div", { class: "sub", style: "color:var(--red)" }, m.error) : null),
    chip);
}

// ---- record panel ----------------------------------------------------------

function recordPanel() {
  const cook = el("input", { type: "text", id: "cook", placeholder: "Mummy, Nani, Dadi…", autocomplete: "off", value: localStorage.getItem("haath.cook") || "" });
  const heading = el("h2", {});
  const setHeading = () => (heading.textContent = cook.value.trim() ? `Record ${cap(cook.value)} cooking` : "Record the family cook");
  cook.addEventListener("input", setHeading);
  setHeading();
  const dish = el("input", { type: "text", id: "dish", placeholder: "Dal Baati, Poha, Puran Poli…", autocomplete: "off" });
  const lang = el("select", { id: "lang" },
    el("option", { value: "" }, "Detect automatically"),
    ...["hi", "mr", "gu", "en"].map((c) => el("option", { value: c }, LANGS[c])));
  const timer = el("div", { class: "timer" }, "0:00");
  const bars = Array.from({ length: 14 }, () => el("i"));
  const meter = el("div", { class: "meter", "aria-hidden": "true" }, bars);
  const label = el("span", {}, "Record");
  const recbtn = el("button", { class: "recbtn", type: "button", "aria-label": "Start recording" }, el("span", { class: "dot" }), label);
  const wrap = el("div", { class: "recbtn-wrap" }, el("div", { class: "recring" }), recbtn);
  const preview = el("div", { class: "preview", hidden: true });
  const file = el("input", { type: "file", accept: "audio/*,.m4a,.opus,.ogg,.mp3,.wav,.webm,.aac,.amr,.3gp" });
  const upload = el("label", { class: "btn upload" }, "Upload a voice note", file);
  const panel = el("section", { class: "card record-card" },
    el("p", { class: "kicker" }, "Before the recipe is lost"),
    heading,
    el("div", { class: "fields" },
      el("div", { class: "field" }, el("label", { for: "cook" }, "Who is cooking"), cook),
      el("div", { class: "field" }, el("label", { for: "dish" }, "What are they making"), dish),
      el("div", { class: "field", style: "flex-basis:100%" }, el("label", { for: "lang" }, "Language"), lang)),
    wrap, timer, meter,
    el("p", { class: "ask-first" }, el("b", {}, "Ask first."), " This stays on this laptop."),
    preview,
    el("div", { class: "or" }, "or"),
    upload);

  let rec = null, chunks = [], stream = null, ctx = null, raf = 0, t0 = 0, tick = 0, wakeLock = null;

  const send = async (blob, filename) => {
    const fd = new FormData();
    fd.append("audio", blob, filename);
    fd.append("cook", cook.value.trim());
    fd.append("dish", dish.value.trim());
    fd.append("lang", lang.value);
    localStorage.setItem("haath.cook", cook.value.trim());
    preview.replaceChildren(el("p", { class: "muted" }, "Saving to the kitchen…"));
    preview.hidden = false;
    try {
      const meta = await api("/api/recipes", { method: "POST", body: fd });
      location.hash = `#/r/${meta.id}`;
    } catch (e) {
      preview.replaceChildren(el("p", { style: "color:var(--red)" }, "Could not save: " + e.message));
      banner(e.message, e.fix);
    }
  };

  file.addEventListener("change", () => {
    const f = file.files[0];
    if (f) {
      if (!dish.value.trim()) dish.value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
      send(f, f.name);
    }
  });

  const cleanup = () => {
    cancelAnimationFrame(raf);
    clearInterval(tick);
    stream?.getTracks().forEach((t) => t.stop());
    ctx?.close().catch(() => {});
    wakeLock?.release().catch(() => {});
    stream = ctx = wakeLock = null;
    bars.forEach((b) => { b.style.height = "6px"; b.classList.remove("on"); });
    panel.classList.remove("recording-on");
    recbtn.classList.remove("recording");
    label.textContent = "Record";
    recbtn.setAttribute("aria-label", "Start recording");
    window.onbeforeunload = null;
  };
  stopRecordingUI = () => { if (rec && rec.state !== "inactive") rec.stop(); cleanup(); stopRecordingUI = null; };

  const start = async () => {
    banner();
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      banner("This browser can't record here.", window.isSecureContext
        ? "use Chrome, Edge, Firefox or Safari, or upload a voice note"
        : "phones need https: start it with  haath ui --lan  and open the https:// address, or upload a voice note");
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      banner("The microphone is blocked.", "click the 🔒/mic icon in the address bar → Allow microphone, then press Record again");
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 96000 } : undefined);
    chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      const type = rec.mimeType || mime || "audio/webm";
      const blob = new Blob(chunks, { type });
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const secs = (Date.now() - t0) / 1000;
      cleanup();
      showPreview(blob, `recording-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.${ext}`, secs);
    };
    rec.start(1000);
    t0 = Date.now();
    panel.classList.add("recording-on");
    recbtn.classList.add("recording");
    label.textContent = "Stop";
    recbtn.setAttribute("aria-label", "Stop recording");
    preview.hidden = true;
    tick = setInterval(() => (timer.textContent = fmt((Date.now() - t0) / 1000)), 250);
    window.onbeforeunload = () => "Recording in progress";
    try { wakeLock = await navigator.wakeLock?.request("screen"); } catch {}

    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    const draw = () => {
      an.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      const level = Math.min(1, Math.sqrt(sum / buf.length) * 6);
      const lit = Math.round(level * bars.length);
      bars.forEach((b, i) => {
        const on = i < lit;
        b.classList.toggle("on", on);
        b.style.height = (on ? 10 + Math.min(24, (i / bars.length) * 30) : 6) + "px";
      });
      raf = requestAnimationFrame(draw);
    };
    draw();
  };

  const showPreview = (blob, filename, secs) => {
    const url = URL.createObjectURL(blob);
    preview.replaceChildren(
      el("audio", { controls: true, src: url }),
      el("p", { class: "small muted" }, `${fmt(secs)} recorded. Listen back, then save, or record again.`),
      el("div", { class: "row", style: "justify-content:center" },
        el("button", { class: "btn primary", onclick: () => send(blob, filename) }, "Save to the kitchen"),
        el("button", { class: "btn ghost", onclick: () => { preview.hidden = true; timer.textContent = "0:00"; } }, "Discard")));
    preview.hidden = false;
  };

  recbtn.addEventListener("click", () => (rec && rec.state === "recording" ? rec.stop() : start()));
  return panel;
}

// ---- audio player: their voice, from the moment they said it ---------------

const audio = $("#voice");
const player = $("#player");
let audioFor = null, stopAt = null, onTimeHook = null;

function playFrom(rid, sec, title, until = null) {
  if (audioFor !== rid) {
    audio.src = `/api/recipes/${rid}/audio`;
    audioFor = rid;
  }
  stopAt = until;
  $("#player-title").textContent = title;
  player.hidden = false;
  const go = () => {
    audio.currentTime = sec;
    audio.play().catch((e) => banner("Could not play the recording: " + e.message));
  };
  if (audio.readyState >= 1) go();
  else audio.addEventListener("loadedmetadata", go, { once: true });
}
function stopVoice() {
  audio.pause();
  player.hidden = true;
  stopAt = null;
  onTimeHook?.(-1);
}
audio.addEventListener("timeupdate", () => {
  const t = audio.currentTime;
  if (stopAt != null && t >= stopAt) {
    audio.pause();
    stopAt = null;
  }
  $("#player-time").textContent = fmt(t);
  if (audio.duration && isFinite(audio.duration)) $("#player-progress").style.width = (100 * t) / audio.duration + "%";
  onTimeHook?.(audio.paused ? -1 : t);
});
audio.addEventListener("play", () => ($("#player-toggle").replaceChildren(icon("pause")), $("#player-toggle").setAttribute("aria-label", "Pause")));
audio.addEventListener("pause", () => {
  $("#player-toggle").replaceChildren(icon("play"));
  $("#player-toggle").setAttribute("aria-label", "Play");
  onTimeHook?.(-1);
});
$("#player-toggle").addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
$("#player-close").addEventListener("click", stopVoice);

// ---- recipe card -----------------------------------------------------------

const REVIEWING = new Set(); // recipe ids currently in review mode

async function renderRecipe(rid) {
  let data;
  try {
    data = await api(`/api/recipes/${rid}`);
  } catch (e) {
    app.replaceChildren(el("div", { class: "recipe" }, el("a", { class: "back", href: "#/" }, "← Kitchen"), el("div", { class: "card" }, "This recipe is not here: " + e.message)));
    return;
  }
  if (!location.hash.startsWith(`#/r/${rid}`)) return;
  const { meta, recipe, transcript } = data;
  const rv = data.review || { keys: {}, checked: [], done: 0, total: 0 };
  const back = el("a", { class: "back", href: "#/" }, "← All recipes");

  if (!recipe || !["done"].includes(meta.status)) {
    const busy = !["done", "error"].includes(meta.status);
    app.replaceChildren(el("div", { class: "recipe" }, back,
      el("div", { class: "sheet status-panel" },
        el("h1", { class: "dish" }, meta.dish || "New recipe"),
        meta.cook ? el("div", { class: "byline" }, "as told by ", el("span", { class: "who" }, meta.cook)) : null,
        busy
          ? [el("p", { class: "big" }, el("span", { class: "busy-dot" }), STATUS[meta.status] + "…"),
             el("p", { class: "muted" }, meta.message || ""),
             el("div", { class: "progress", style: "max-width:360px;margin:10px auto" }, el("div", { style: `width:${Math.round((meta.progress || 0) * 100)}%` })),
             el("p", { class: "small muted" }, "You can close this page; it keeps working. A 30-minute recording can take a while on a laptop.")]
          : [el("p", { class: "big", style: "color:var(--red)" }, meta.error || "Something went wrong."),
             meta.fix ? el("p", { class: "fix" }, "Fix: ", el("code", {}, meta.fix)) : null,
             el("div", { class: "row", style: "justify-content:center;margin-top:14px" },
               el("button", { class: "btn primary", onclick: () => redo(rid, !transcript) }, "Try again"),
               el("button", { class: "btn ghost", onclick: () => trash(rid, meta) }, "Delete"))])));
    if (busy) poll(() => renderRecipe(rid));
    return;
  }

  const steps = recipe.steps;
  const nextStart = (i) => {
    const later = steps.slice(i + 1).map((s) => s.start_sec).filter((t) => t > steps[i].start_sec);
    return later.length ? Math.min(...later) + 0.5 : null;
  };
  const who = cap(recipe.cook || meta.cook) || "the cook";
  const whose = who === "the cook" ? "the cook's" : `${who}'s`;
  const tr = new Map((recipe.translations || []).map((t) => [norm(t.original), t.english]));
  // Family review: a ✓ per line; ticks are keyed on the line's content (see review.py).
  const reviewing = REVIEWING.has(rid);
  const checked = new Set(rv.checked);
  const counter = el("strong", {});
  const meter = el("div", { class: "rv-progress" }, el("div"));
  const updateCount = () => {
    counter.textContent = `${checked.size} of ${rv.total}`;
    meter.firstChild.style.width = (rv.total ? (100 * checked.size) / rv.total : 0) + "%";
    meter.classList.toggle("all", rv.total > 0 && checked.size === rv.total);
  };
  const tick = (kind, i) => {
    const key = rv.keys[kind]?.[i];
    if (!key) return null;
    if (!reviewing) return checked.has(key) ? el("span", { class: "rv-mark", title: "Checked by the family" }, "✓") : null;
    const b = el("button", { class: "rv" + (checked.has(key) ? " ok" : ""), type: "button", "aria-pressed": String(checked.has(key)),
      "aria-label": "This line is correct", title: "Tap when this line is right" }, "✓");
    b.addEventListener("click", async () => {
      const ok = !checked.has(key);
      try {
        const res = await api(`/api/recipes/${rid}/review`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, ok }) });
        checked.clear();
        res.checked.forEach((k) => checked.add(k));
        b.classList.toggle("ok", ok);
        b.setAttribute("aria-pressed", String(ok));
        updateCount();
      } catch (e) { banner(e.message, e.fix); }
    });
    return b;
  };
  updateCount();
  const mean = (text) => (text && tr.get(norm(text)) ? el("div", { class: "mean" }, tr.get(norm(text))) : null);
  const stepEls = steps.map((s, i) =>
    el("li", { class: "step", "data-start": s.start_sec },
      el("button", { class: "play", type: "button", "aria-label": `Play ${who}'s voice for step ${i + 1}`, title: `Hear ${who} at ${fmt(s.start_sec)}`,
        onclick: () => playFrom(rid, s.start_sec, `${who} · step ${i + 1}`, nextStart(i)) },
        el("span", { class: "num" }, i + 1), icon("play")),
      el("div", {},
        el("div", { class: "text" }, s.text),
        s.her_cue ? el("div", { class: "cue" }, s.her_cue) : null,
        s.her_cue ? mean(s.her_cue) : null,
        el("div", { class: "at" }, fmt(s.start_sec))),
      tick("steps", i)));

  const segEls = (transcript?.segments || []).map((g) =>
    el("div", { class: "seg", "data-start": g.start, "data-end": g.end },
      el("button", { onclick: () => playFrom(rid, g.start, `${who} · ${fmt(g.start)}`) }, fmt(g.start)),
      el("span", {}, g.text)));

  onTimeHook = (t) => {
    if (audioFor !== rid) return;
    let cur = -1;
    if (t >= 0) steps.forEach((s, i) => { if (s.start_sec <= t + 0.05) cur = i; });
    stepEls.forEach((e, i) => e.classList.toggle("playing", i === cur));
    segEls.forEach((e) => e.classList.toggle("playing", t >= 0 && +e.dataset.start <= t && t < +e.dataset.end));
  };

  const lang = LANGS[meta.language] || meta.language;
  const sheet = el("article", { class: "sheet" + (reviewing ? " reviewing" : "") },
    el("p", { class: "kicker" }, "From the family kitchen"),
    el("h1", { class: "dish" }, recipe.dish || meta.dish || "Untitled"),
    el("div", { class: "byline" }, "as told by ", el("span", { class: "who" }, who),
      el("span", { class: "muted" }, [meta.duration ? ` · ${fmt(meta.duration)} recorded` : "", lang ? ` · ${lang}` : ""].join(""))),
    recipe.story ? el("p", { class: "story" }, recipe.story) : null,
    el("div", { class: "toolbar" },
      el("button", { class: "btn primary", onclick: () => playFrom(rid, 0, `${who} · from the start`) }, icon("play"), `Hear ${who} from the start`),
      el("button", { class: reviewing ? "btn primary" : "btn", onclick: () => { reviewing ? REVIEWING.delete(rid) : REVIEWING.add(rid); renderRecipe(rid); } },
        reviewing ? "Done reviewing" : "Review"),
      el("a", { class: "btn", href: `#/r/${rid}/edit` }, "Edit"),
      el("button", { class: "btn ghost", onclick: () => window.print() }, "Print"),
      el("button", { class: "btn ghost", title: `Re-run ${STATUS_INFO.model || "the model"} on the same transcript`, onclick: () => redo(rid, false, meta.edited) }, "Re-write"),
      el("button", { class: "btn ghost", onclick: () => trash(rid, meta) }, "Delete")),
    meta.dropped
      ? el("details", { class: "guard" },
          el("summary", {}, `✓ Checked against the recording: ${meta.dropped} line${meta.dropped > 1 ? "s" : ""} the model wrote but ${who} never said ${meta.dropped > 1 ? "were" : "was"} removed.`),
          el("ul", {}, meta.dropped_items.map((d) => el("li", {}, d))))
      : el("div", { class: "guard" }, "✓ Every quote and measure below was checked against the recording."),
    reviewing
      ? el("div", { class: "review-panel" },
          el("div", {}, el("strong", {}, `Go through the card with ${who}.`),
            " Tap ✓ on every line that's right. Fix anything wrong with Edit; a changed line needs a new tick."),
          el("div", { class: "rv-row" }, "Checked ", counter, meter))
      : rv.total
        ? el("div", { class: "rv-badge" + (rv.done === rv.total ? " all" : "") },
            rv.done === rv.total
              ? `✓ Checked line by line by the family (${rv.total} of ${rv.total}).`
              : `${rv.done} of ${rv.total} lines checked by the family. Press Review to go through the rest with ${who}.`)
        : null,

    section("Ingredients", "marigold",
      el("ul", { class: "ingredients" }, recipe.ingredients.map((g, i) =>
        el("li", { class: "ing" },
          tick("ingredients", i),
          g.her_words ? el("div", { class: "her" }, g.her_words) : null,
          mean(g.her_words),
          el("div", { class: "name" }, g.name),
          g.approx ? el("div", { class: "approx", title: `Approximate, ${g.confidence} confidence` }, g.approx, " approx.", el("span", { class: "conf " + g.confidence })) : null))),
      el("p", { class: "small muted", style: "margin-top:8px" }, `Big writing is how ${who} said it. Small measures are estimates, so trust those words first.`)),

    section("Method", "diya", el("ol", { class: "steps" }, stepEls),
      el("p", { class: "small muted" }, `Press ▶ to hear ${who} explain that step in ${whose} own voice.`)),

    recipe.tips.length || recipe.warnings.length
      ? section(`What ${who} reminded us`, null,
          el("div", { class: "notes" },
            recipe.tips.length ? el("div", { class: "note tips" }, el("h4", {}, "Tips"), el("ul", {}, recipe.tips.map((t, i) => el("li", {}, t, mean(t), tick("tips", i))))) : null,
            recipe.warnings.length ? el("div", { class: "note warn" }, el("h4", {}, "Careful!"), el("ul", {}, recipe.warnings.map((t, i) => el("li", {}, t, tick("warnings", i))))) : null))
      : null,

    recipe.quotes.length
      ? section(`In ${whose} words`, null, el("div", { class: "quotes" }, recipe.quotes.map((q, i) => el("blockquote", {}, q, mean(q), el("cite", {}, "· " + who), tick("quotes", i)))))
      : null,

    recipe.ask_next_time.length
      ? section(`Ask ${who} next time`, null, el("ul", { class: "asks" }, recipe.ask_next_time.map((q) => el("li", {}, q))),
          el("p", { class: "small muted" }, "Little gaps in the recipe. Ask while you still can, then fix the card with Edit."))
      : null,

    transcript
      ? el("details", { class: "transcript" },
          el("summary", {}, `Full transcript (${transcript.segments.length} lines)`),
          el("p", { class: "small muted" }, `Heard by Whisper ${transcript.whisper_model}. Tap a time to hear that moment.`),
          el("div", { class: "segs" }, segEls))
      : null,
    el("p", { class: "small muted", style: "margin-top:24px" },
      `Written by ${meta.model || "a local model"}${meta.edited ? ", corrected by hand" : ""}. Stored only on this laptop.`));

  app.replaceChildren(el("div", { class: "recipe" }, back, sheet));
}

function section(title, ic, ...children) {
  return el("section", { class: "section" }, el("h3", {}, ic ? icon(ic) : null, title), ...children);
}

async function redo(rid, full = false, edited = false) {
  if (edited && !confirm("You edited this card by hand. Re-writing will replace your edits. Continue?")) return;
  try {
    await api(`/api/recipes/${rid}/redo?full=${full}`, { method: "POST" });
    renderRecipe(rid);
  } catch (e) { banner(e.message, e.fix); }
}

async function trash(rid, meta) {
  if (!confirm(`Move “${meta.dish || "this recipe"}” to the trash folder? The recording is kept in the archive's .trash folder.`)) return;
  try {
    await api(`/api/recipes/${rid}`, { method: "DELETE" });
    stopVoice();
    location.hash = "#/";
  } catch (e) { banner(e.message, e.fix); }
}

// ---- edit mode -------------------------------------------------------------

async function renderEdit(rid) {
  let data;
  try { data = await api(`/api/recipes/${rid}`); } catch (e) { banner(e.message); return; }
  const r = structuredClone(data.recipe || { dish: "", cook: "", story: "", ingredients: [], steps: [], tips: [], warnings: [], quotes: [], ask_next_time: [] });

  const input = (obj, key, attrs = {}) => el("input", { type: "text", value: obj[key] ?? "", oninput: (e) => (obj[key] = e.target.value), ...attrs });
  const area = (obj, key, attrs = {}) => el("textarea", { oninput: (e) => (obj[key] = e.target.value), ...attrs }, obj[key] ?? "");
  const listArea = (key, label, hint) => {
    const t = el("textarea", { id: "f-" + key, oninput: (e) => (r[key] = e.target.value.split("\n").map((s) => s.trim()).filter(Boolean)) }, r[key].join("\n"));
    return el("div", { class: "field" }, el("label", { for: "f-" + key }, label, el("span", { class: "muted" }, " · " + hint)), t);
  };

  const ingBox = el("div", { class: "rowset" });
  const drawIngs = () => ingBox.replaceChildren(...r.ingredients.map((g, i) =>
    el("div", { class: "erow ing" },
      input(g, "name", { placeholder: "Ingredient", "aria-label": "Ingredient name" }),
      input(g, "her_words", { placeholder: "Their words (ek mutthi…)", "aria-label": "Their words" }),
      input(g, "approx", { placeholder: "~1 cup / 120 g", "aria-label": "Approximate measure" }),
      el("select", { "aria-label": "Confidence", onchange: (e) => (g.confidence = e.target.value) },
        ...["low", "med", "high"].map((c) => el("option", { value: c, selected: g.confidence === c }, c))),
      el("button", { class: "x", type: "button", "aria-label": "Remove ingredient", onclick: () => { r.ingredients.splice(i, 1); drawIngs(); } }, "✕"))));
  drawIngs();

  const stepBox = el("div", { class: "rowset" });
  const drawSteps = () => stepBox.replaceChildren(...r.steps.map((s, i) =>
    el("div", { class: "erow st" },
      input(s, "her_cue", { placeholder: "Their cue (jab tak tel chhod de…)", "aria-label": `Step ${i + 1} cue` }),
      el("input", { type: "number", min: 0, step: 0.1, value: s.start_sec, "aria-label": `Step ${i + 1} start second`, title: "Starts at (seconds)", oninput: (e) => (s.start_sec = parseFloat(e.target.value) || 0) }),
      el("button", { class: "x", type: "button", "aria-label": "Remove step", onclick: () => { r.steps.splice(i, 1); drawSteps(); } }, "✕"),
      area(s, "text", { placeholder: `Step ${i + 1}`, "aria-label": `Step ${i + 1}` }))));
  drawSteps();

  const save = async () => {
    try {
      await api(`/api/recipes/${rid}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) });
      banner();
      location.hash = `#/r/${rid}`;
    } catch (e) { banner(e.message, e.fix); }
  };

  app.replaceChildren(el("div", { class: "recipe edit" },
    el("a", { class: "back", href: `#/r/${rid}` }, "← Back to the card"),
    el("article", { class: "sheet" },
      el("p", { class: "kicker" }, "Fix anything by hand. You know them better than the machine does"),
      el("h1", { class: "dish" }, "Edit recipe"),
      el("div", { class: "row", style: "margin-top:16px" },
        el("div", { class: "field" }, el("label", {}, "Dish"), input(r, "dish")),
        el("div", { class: "field" }, el("label", {}, "Cook"), input(r, "cook"))),
      el("div", { class: "field", style: "margin-top:10px" }, el("label", {}, "Story (one line)"), input(r, "story")),
      section("Ingredients", "marigold", ingBox,
        el("button", { class: "btn ghost", type: "button", onclick: () => { r.ingredients.push({ name: "", her_words: "", approx: "", confidence: "low" }); drawIngs(); } }, "+ Add ingredient")),
      section("Method", "diya", stepBox,
        el("button", { class: "btn ghost", type: "button", onclick: () => { r.steps.push({ text: "", her_cue: "", start_sec: 0 }); drawSteps(); } }, "+ Add step")),
      section("Notes", null,
        el("div", { class: "lists" },
          listArea("tips", "Tips", "one per line"),
          listArea("warnings", "Warnings", "one per line"),
          listArea("quotes", "Quotes", "up to 3"),
          listArea("ask_next_time", "Ask next time", "one question per line"))),
      el("div", { class: "savebar" },
        el("a", { class: "btn ghost", href: `#/r/${rid}` }, "Cancel"),
        el("button", { class: "btn primary", onclick: save }, "Save card")))));
}

// ---- boot ------------------------------------------------------------------

(async () => {
  try {
    STATUS_INFO = await api("/api/status");
    if (STATUS_INFO.mock) banner("Mock mode: recordings use a sample Dal Baati transcript and reply, no Whisper or Ollama needed.");
    else {
      const { checks } = await api("/api/doctor");
      const bad = checks.find((c) => !c.ok && c.required);
      if (bad) banner(`${bad.name}: ${bad.detail}`, bad.fix);
    }
  } catch {}
})();
route();
