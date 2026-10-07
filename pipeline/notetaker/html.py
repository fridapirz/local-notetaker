"""Render the meetings site: notes.html per meeting and index.html (action items).

Both share one shell: a meetings sidebar on the left, the page on the right. Links are relative, so the
pages work opened as files (read-only) and served by `notetaker serve` (action items can be ticked).
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import markdown

LANG_CODES = {"lv": "LV", "en": "EN", "ru": "RU"}
BY_NAMES = {"claude": "Claude", "claude-desktop": "Claude", "local": "on-device", "pending": "pending"}

CSS = """
:root {
  --bg: #ffffff; --side: #f7f6fa; --ink: #1d1b2e; --ink-2: #47445a; --muted: #77748a;
  --line: #e7e5ef; --line-2: #f0eff5; --hover: #efedf6;
  --accent: #5b4cf0; --accent-ink: #4a3bd9; --accent-tint: rgb(91 76 240 / .09);
  --them: #0f8a7e; --warn: oklch(66% 0.13 75); --bad: oklch(58% 0.15 25);
  --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15141b; --side: #1b1a23; --ink: #ecebf5; --ink-2: #c3c1d3; --muted: #8e8ba2;
    --line: #2b2937; --line-2: #22202c; --hover: #24223a;
    --accent: #a59bff; --accent-ink: #b8b0ff; --accent-tint: rgb(165 155 255 / .13); --them: #5fd0c3;
  }
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 13px/1.5 var(--sans); -webkit-font-smoothing: antialiased; }
a { color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; border-radius: 4px; }
kbd { font: 10.5px/1 var(--mono); color: var(--muted); border: 1px solid var(--line); border-bottom-width: 2px;
      border-radius: 4px; padding: 1px 4px; background: var(--bg); }
.mono, time { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.hidden { display: none !important; }

/* shell */
.app { display: grid; grid-template-columns: 264px minmax(0, 1fr); height: 100vh; }
.side { background: var(--side); border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; }
.side-top { padding: 12px 8px 4px; display: flex; flex-direction: column; gap: 2px; }
.brand { font-weight: 600; padding: 0 8px 8px; display: flex; align-items: center; gap: 8px; }
.brand svg { color: var(--accent); }
.nav { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 6px; text-decoration: none; }
.nav svg { color: var(--muted); flex: none; }
.nav .count, .mt .n { margin-left: auto; font: 11px/1 var(--mono); font-variant-numeric: tabular-nums; color: var(--muted); }
.search { position: relative; margin: 6px 0 2px; }
.search input { width: 100%; font: inherit; font-size: 12.5px; color: inherit; background: var(--bg);
                border: 1px solid var(--line); border-radius: 6px; padding: 4px 28px 4px 8px; }
.search input:focus-visible { outline-offset: -1px; }
.search kbd { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); pointer-events: none; }
.side-list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 8px 12px; }
.day { font-size: 11.5px; font-weight: 600; color: var(--muted); padding: 12px 8px 2px; }
.mt { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 8px; padding: 4px 8px; border-radius: 6px; text-decoration: none; }
.mt .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mt .n { align-self: center; color: var(--accent-ink); }
.mt .s { grid-column: 1 / -1; font: 11px/1.45 var(--mono); font-variant-numeric: tabular-nums; color: var(--muted);
         display: flex; align-items: center; gap: 6px; }
.mt.empty .t { color: var(--muted); }
.nav, .mt { transition: background-color 80ms ease-out; }
@media (hover: hover) { .nav:hover, a.mt:hover { background: var(--hover); } }
.nav[aria-current="page"], .mt[aria-current="page"] { background: var(--accent-tint); color: var(--accent-ink); }
.dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
.dot.warn { background: var(--warn); }
.dot.none { border: 1px solid var(--muted); }
.side-foot { border-top: 1px solid var(--line); padding: 8px 16px; font-size: 11px; color: var(--muted);
             display: flex; flex-wrap: wrap; gap: 4px 10px; }
.main { overflow-y: auto; min-width: 0; scrollbar-gutter: stable; }
.page { padding: 14px 24px 48px; max-width: 1360px; }

/* page header */
.head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
h1 { font-size: 18px; line-height: 1.3; margin: 0; font-weight: 600; letter-spacing: -.01em; text-wrap: balance; flex-basis: 100%; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; font: 11.5px/1.6 var(--mono);
        font-variant-numeric: tabular-nums; color: var(--muted); }
.meta a { color: var(--muted); text-underline-offset: 2px; }
.talk { display: inline-flex; align-items: center; gap: 6px; }
.talk .bar { display: inline-flex; width: 64px; height: 5px; border-radius: 3px; overflow: hidden; background: var(--them); }
.talk .bar i { background: var(--accent); }
.talk .me { color: var(--accent-ink); } .talk .them { color: var(--them); }
.spacer { flex: 1; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 6px; padding: 1px; }
.seg button { font: inherit; font-size: 12px; color: var(--muted); background: none; border: 0; border-radius: 5px; padding: 2px 10px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--accent-tint); color: var(--accent-ink); font-weight: 600; }
.hint { font-size: 12px; color: var(--ink-2); border: 1px solid var(--line); border-left: 3px solid var(--warn);
        border-radius: 6px; padding: 6px 10px; margin: 10px 0 0; }

/* meeting body */
.cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0 28px; }
@media (min-width: 1180px) { .cols { grid-template-columns: minmax(0, 1fr) minmax(340px, 34%); } }
.doc { max-width: 820px; }
h2 { font-size: 12.5px; font-weight: 600; margin: 18px 0 6px; display: flex; align-items: baseline; gap: 8px; }
h2 .c { font: 11px/1 var(--mono); color: var(--muted); font-weight: 400; }
.doc p { margin: 0 0 8px; color: var(--ink-2); }
.doc .lead p { font-size: 13.5px; color: var(--ink); }
.doc ul { margin: 0 0 8px; padding-left: 18px; color: var(--ink-2); }
.doc li { margin: 2px 0; }
.doc li::marker { color: var(--muted); }
.doc ul ul { margin: 2px 0 0; }
.doc strong { color: var(--ink); font-weight: 600; }
.doc code, .ref { font: 11.5px var(--mono); }
.pending { border: 1px solid var(--line); border-left: 3px solid var(--warn); border-radius: 6px; padding: 8px 12px; margin-top: 14px; }

/* transcript */
.tx { border-left: 1px solid var(--line); padding-left: 20px; min-width: 0; }
@media (min-width: 1180px) { .tx { position: sticky; top: 0; max-height: 100vh; overflow-y: auto; overscroll-behavior: contain; padding-bottom: 24px; } }
@media (max-width: 1179px) { .tx { border-left: 0; padding-left: 0; border-top: 1px solid var(--line); margin-top: 18px; } }
.tx h2 { position: sticky; top: 0; background: var(--bg); margin: 0; padding: 18px 0 6px; z-index: 1; }
.line { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 8px; padding: 3px 0; font-size: 12.5px; color: var(--ink-2); }
.line time { font-size: 11px; color: var(--muted); line-height: 1.75; }
.line b { font-weight: 600; font-size: 11.5px; margin-right: 4px; }
.line.me b { color: var(--accent-ink); } .line.them b { color: var(--them); }
.line .lang { font: 10px var(--mono); color: var(--muted); margin-left: 4px; }

/* action items */
.ai-head, .ai { display: grid; grid-template-columns: 16px 72px minmax(0, 1fr) minmax(0, 220px) 64px; gap: 10px; align-items: baseline; padding: 4px 8px; }
.only-mine .ai-head, .only-mine .ai { grid-template-columns: 16px minmax(0, 1fr) minmax(0, 220px) 64px; }
.only-mine .who, .only-mine .h-who { display: none; }
.ai-head { font-size: 11.5px; color: var(--muted); border-bottom: 1px solid var(--line); padding-top: 12px; }
.ai-head span:last-child, .ai .when { text-align: right; }
.ai { border-bottom: 1px solid var(--line-2); border-radius: 4px; transition: background-color 80ms ease-out; }
@media (hover: hover) { .ai:hover { background: var(--hover); } }
.ai input { width: 14px; height: 14px; margin: 0; accent-color: var(--accent); cursor: pointer; align-self: center; }
.ai input:disabled { cursor: default; }
.ai .task { color: var(--ink); }
.ai .who { font-size: 12px; font-weight: 600; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ai.mine .who { color: var(--accent-ink); }
.ai .src { font-size: 12px; color: var(--muted); text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ai .src:hover { color: var(--accent-ink); }
.ai .when { font: 11px var(--mono); font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; }
.ai.done .task { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--line); }
.ai.saving { opacity: .55; }
.ai .err { grid-column: 2 / -1; color: var(--bad); font-size: 12px; }
.in-meeting .ai { grid-template-columns: 16px 72px minmax(0, 1fr) 64px; }
.only-mine .ai:not(.mine) { display: none; }
.empty-note { color: var(--muted); padding: 10px 8px; margin: 0; }
details.archive { margin-top: 16px; }
details.archive summary { cursor: pointer; font-size: 12.5px; font-weight: 600; padding: 4px 0; }
details.archive summary .c { font: 11px var(--mono); color: var(--muted); font-weight: 400; margin-left: 6px; }

@media (max-width: 800px) {
  .app { grid-template-columns: 1fr; height: auto; }
  html, body { height: auto; }
  .side { border-right: 0; border-bottom: 1px solid var(--line); max-height: 48vh; }
  .main { overflow: visible; }
  .side-foot { display: none; }
  .page { padding: 12px 16px 40px; }
  .ai-head, .ai, .in-meeting .ai { grid-template-columns: 16px 56px minmax(0, 1fr) 52px; }
  .only-mine .ai-head, .only-mine .ai { grid-template-columns: 16px minmax(0, 1fr) 52px; }
  .ai .src, .ai-head .h-src { display: none; }
}
@media print { .side { display: none; } .app { display: block; height: auto; } .tx { position: static; max-height: none; } }
"""

ICON_WAVE = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" aria-hidden="true"><path d="M2 12h2M6 8v8M10 4v16M14 7v10M18 10v4M22 12h0"/></svg>')
ICON_CHECK = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" '
              'rx="3"/><path d="m8 12 3 3 5-6"/></svg>')

JS = r"""
const served = location.protocol.startsWith("http");
const $ = (s, el = document) => el.querySelector(s), $$ = (s, el = document) => [...el.querySelectorAll(s)];
const box = $("#actions");

// Mine / Everyone (home only)
const views = $$(".seg button");
function setView(v) {
  if (!box) return;
  box.classList.toggle("only-mine", v === "mine");
  views.forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  try { localStorage.setItem("notetaker.view", v); } catch (e) {}
  counts();
}
function counts() {
  if (!box) return;
  const mineOnly = box.classList.contains("only-mine");
  const shown = $$("#ai-open .ai", box).filter(el => !mineOnly || el.classList.contains("mine"));
  const open = shown.filter(el => !el.classList.contains("done")).length;
  const n = $("#open-n"); if (n) n.textContent = open;
  const empty = $("#ai-empty"); if (empty) empty.classList.toggle("hidden", shown.length > 0);
}
views.forEach(b => b.addEventListener("click", () => setView(b.dataset.view)));
if (views.length) { let v = "mine"; try { v = localStorage.getItem("notetaker.view") || "mine"; } catch (e) {} setView(v); }

// Ticking: only when served by the app
if (!served) {
  $$(".file-hint").forEach(el => el.classList.remove("hidden"));
  $$(".ai input").forEach(i => i.disabled = true);
} else {
  $$(".file-only").forEach(el => el.classList.add("hidden"));
}
function bump(sel, d) { const el = $(sel); if (el) { const v = (+el.textContent || 0) + d; el.textContent = v > 0 ? v : ""; } }
document.addEventListener("change", async e => {
  const input = e.target, row = input.closest(".ai");
  if (!row || !served) return;
  row.classList.add("saving");
  row.querySelector(".err")?.remove();
  try {
    const r = await fetch("/api/done", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Notetaker": "1" },
      body: JSON.stringify({ folder: row.dataset.folder, id: row.dataset.id, done: input.checked }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    row.classList.toggle("done", input.checked);
    if (row.classList.contains("mine")) {
      const d = input.checked ? -1 : 1;
      bump("#nav-open", d);
      bump(`.mt[data-folder="${CSS.escape(row.dataset.folder)}"] .n`, d);
    }
  } catch (err) {
    input.checked = !input.checked;
    row.insertAdjacentHTML("beforeend", `<span class="err">Couldn't save: ${err.message}</span>`);
  } finally {
    row.classList.remove("saving");
    counts();
  }
});

// Search: filters the sidebar, and the action list on the home page
const q = $("#q");
q?.addEventListener("input", () => {
  const s = q.value.trim().toLowerCase();
  let day = null, any = false;
  const flush = () => day && day.classList.toggle("hidden", !any);
  for (const el of $$(".side-list > *")) {
    if (el.classList.contains("day")) { flush(); day = el; any = false; continue; }
    const hit = !s || el.textContent.toLowerCase().includes(s);
    el.classList.toggle("hidden", !hit);
    any = any || hit;
  }
  flush();
  if (box) $$(".ai", box).forEach(el => el.classList.toggle("hidden", !!s && !el.textContent.toLowerCase().includes(s)));
});

// Keyboard: / search, j/k next/previous meeting, h action items
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (e.key === "Escape" && typing) { document.activeElement.blur(); return; }
  if (typing) return;
  if (e.key === "/") { e.preventDefault(); q?.focus(); return; }
  if (e.key === "h") { location.href = $(".nav[data-home]").getAttribute("href"); return; }
  if (e.key === "j" || e.key === "k") {
    const links = $$("a.mt:not(.hidden)"), cur = links.findIndex(a => a.getAttribute("aria-current") === "page");
    const next = links[cur < 0 ? 0 : cur + (e.key === "j" ? 1 : -1)];
    if (next) location.href = next.getAttribute("href");
  }
});
$(".mt[aria-current=page]")?.scrollIntoView({ block: "nearest" });
"""


# ---------- helpers ----------

def parse_notes(md_text: str) -> tuple[dict, str]:
    """Split frontmatter and return (meta, summary markdown without the transcript)."""
    meta: dict = {}
    body = md_text
    if md_text.startswith("---\n"):
        head, _, body = md_text[4:].partition("\n---\n")
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
    summary = re.split(r"\n---\n+## Transcript\b", body, maxsplit=1)[0]
    return meta, summary.strip()


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def started_at(folder_name: str) -> datetime | None:
    try:
        return datetime.strptime(folder_name[:15], "%Y-%m-%d %H%M")
    except ValueError:
        return None


def day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a %-d %b %Y" if d.year != today.year else "%a %-d %b")


def inline(text: str) -> str:
    """Escape, keep **bold**, and set ticket keys (CHAT-1234) in mono."""
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))
    return re.sub(r"\b([A-Z][A-Z0-9]+-\d+)\b", r'<span class="ref">\1</span>', out)


def gist(notes: Path, limit: int = 180) -> str:
    """First sentence or two of the summary."""
    _, summary_md = parse_notes(notes.read_text())
    m = re.search(r"^## Summary\s*\n+(.+?)(?:\n\n|\n#|$)", summary_md, re.S | re.M)
    text = " ".join(m.group(1).split()) if m else ""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def site(notes_dir: Path) -> dict:
    """Everything the shell needs: meetings (newest first), action items, server port."""
    from .cli import all_actions, load_config, sessions
    cfg = load_config()
    return {"meetings": sessions(notes_dir), "items": all_actions(notes_dir, cfg["my_names"]),
            "port": cfg["server_port"]}


# ---------- shell ----------

def sidebar(ctx: dict, prefix: str, current: str | None) -> str:
    """Meetings by day. prefix is the relative path from the page to the notes folder ("" or "../")."""
    today = date.today()
    open_mine: dict[str, int] = {}
    for i in ctx["items"]:
        if i["mine"] and not i["done"]:
            open_mine[i["folder"]] = open_mine.get(i["folder"], 0) + 1
    rows, last = [], None
    for m in ctx["meetings"]:
        name = Path(m["folder"]).name
        started = started_at(name)
        if not started:
            continue
        if started.date() != last:
            last = started.date()
            rows.append(f'<div class="day">{day_label(last, today)}</div>')
        bits = [f"<time>{started:%H:%M}</time>"]
        if m.get("duration_min"):
            bits.append(f'<span>{m["duration_min"]}m</span>')
        if m.get("pending"):
            bits.append('<span class="dot warn"></span><span>summary pending</span>')
        elif not m.get("notes"):
            bits.append('<span class="dot none"></span><span>no notes</span>')
        n = open_mine.get(name, 0)
        inner = (f'<span class="t">{html.escape(m["title"])}</span>'
                 f'<span class="n" title="Your open action items">{n or ""}</span>'
                 f'<span class="s">{"".join(bits)}</span>')
        attrs = f'data-folder="{html.escape(name)}"' + (' aria-current="page"' if name == current else "")
        if (Path(m["folder"]) / "notes.html").exists() or name == current:
            rows.append(f'<a class="mt" {attrs} href="{prefix}{quote(name)}/notes.html">{inner}</a>')
        else:
            rows.append(f'<div class="mt empty" {attrs}>{inner}</div>')
    mine_open = sum(open_mine.values())
    home = ' aria-current="page"' if current is None else ""
    return f"""<aside class="side" aria-label="Meetings">
<div class="side-top">
<div class="brand">{ICON_WAVE}Notetaker</div>
<a class="nav" data-home href="{prefix}index.html"{home}>{ICON_CHECK}Action items<span class="count" id="nav-open">{mine_open or ""}</span></a>
<label class="search"><input id="q" type="search" placeholder="Search meetings" autocomplete="off" aria-label="Search meetings"><kbd>/</kbd></label>
</div>
<nav class="side-list" aria-label="Meetings">
{"".join(rows) or '<p class="empty-note">No meetings yet. Start one from the waveform menu.</p>'}
</nav>
<div class="side-foot"><span><kbd>/</kbd> search</span><span><kbd>j</kbd> <kbd>k</kbd> meetings</span><span><kbd>h</kbd> action items</span></div>
</aside>"""


def page(title: str, side: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="app">
{side}
<main class="main"><div class="page">
{body}
</div></main>
</div>
<script>{JS}</script></body></html>
"""


# ---------- action items ----------

def action_row(item: dict, meeting: dict | None) -> str:
    cls = "ai" + (" mine" if item["mine"] else "") + (" done" if item["done"] else "")
    who = f'<span class="who">{html.escape(item["owner"] or "")}</span>'
    if item["done_on"]:
        when = f'<span class="when" title="Done">✓ {date.fromisoformat(item["done_on"]):%-d %b}</span>'
    else:
        started = started_at(item["folder"]) if meeting else None  # on its own meeting page the date is a given
        when = f'<span class="when">{started:%-d %b}</span>' if started else '<span class="when"></span>'
    src = (f'<a class="src" href="{quote(item["folder"])}/notes.html">{html.escape(meeting["title"])}</a>'
           if meeting else "")
    return (f'<div class="{cls}" data-folder="{html.escape(item["folder"])}" data-id="{item["id"]}">'
            f'<input type="checkbox" aria-label="Done"{" checked" if item["done"] else ""}>'
            f'{who}<span class="task">{inline(item["task"])}</span>{src}{when}</div>')


def file_hint(port: int) -> str:
    return (f'<p class="hint file-hint hidden">Read-only as a file. To tick items, open '
            f'<a href="http://127.0.0.1:{port}/">Meetings &amp; Action Items</a> from the Notetaker menu.</p>')


def render_index(notes_dir: Path, ctx: dict | None = None) -> Path:
    """index.html: every action item across meetings in one list, recent done ones, then the archive."""
    from .actions import archived

    ctx = ctx or site(notes_dir)
    by_folder = {Path(m["folder"]).name: m for m in ctx["meetings"]}
    items = [i for i in ctx["items"] if i["folder"] in by_folder]
    open_ = sorted((i for i in items if not i["done"]), key=lambda i: i["folder"])
    recent = sorted((i for i in items if i["done"] and not archived(i)), key=lambda i: i["done_on"] or "", reverse=True)
    old = sorted((i for i in items if archived(i)), key=lambda i: i["done_on"] or "", reverse=True)
    rows = lambda group: "\n".join(action_row(i, by_folder[i["folder"]]) for i in group)  # noqa: E731
    head = ('<div class="ai-head" aria-hidden="true"><span></span><span class="h-who">Owner</span><span>Task</span>'
            '<span class="h-src">Meeting</span><span>Date</span></div>')
    archive = (f'<details class="archive"><summary>Archive<span class="c">{len(old)}</span></summary>'
               f'{head}{rows(old)}</details>') if old else ""
    body = f"""<div class="head">
<h1>Action items</h1>
<div class="meta"><span><span id="open-n"></span> open</span><span>{len(recent)} done in the last 7 days</span><span>{len(old)} archived</span><span>from {sum(1 for m in ctx["meetings"] if m.get("notes"))} meetings</span></div>
<span class="spacer"></span>
<div class="seg" role="group" aria-label="Whose items"><button type="button" data-view="mine" aria-pressed="true">Mine</button><button type="button" data-view="all" aria-pressed="false">Everyone</button></div>
</div>
{file_hint(ctx["port"])}
<div id="actions" class="only-mine">
{head}
<div id="ai-open">{rows(open_ + recent)}</div>
<p class="empty-note hidden" id="ai-empty">Nothing open. Done items move to the archive after 7 days.</p>
{archive}
</div>"""
    out = notes_dir / "index.html"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(page("Action items · Notetaker", sidebar(ctx, "", None), body))
    tmp.replace(out)  # atomic: the server and the pipeline both rebuild it
    return out


# ---------- meeting page ----------

def transcript_html(segments: list[dict]) -> str:
    rows, cur = [], None
    for s in segments:  # merge consecutive lines of the same speaker, like notes.md
        if cur and cur["speaker"] == s["speaker"] and s["start"] - cur["end"] < 4:
            cur["text"] += " " + s["text"]
            cur["end"] = s["end"]
        else:
            if cur:
                rows.append(cur)
            cur = dict(s)
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        who = "me" if r["speaker"] == "Me" else "them"
        lang = f'<span class="lang">{html.escape(r["lang"])}</span>' if r.get("lang") and r["lang"] != "en" else ""
        out.append(f'<div class="line {who}"><time>{fmt_time(r["start"])}</time>'
                   f'<span><b>{html.escape(r["speaker"])}</b>{html.escape(r["text"])}{lang}</span></div>')
    return "\n".join(out)


def talk_share(segments: list[dict]) -> str:
    """Signature detail: how much of the call was you vs everyone else."""
    me = sum(s["end"] - s["start"] for s in segments if s["speaker"] == "Me")
    them = sum(s["end"] - s["start"] for s in segments if s["speaker"] != "Me")
    if me + them <= 0:
        return ""
    pct = round(100 * me / (me + them))
    return (f'<span class="talk" title="Share of speaking time"><span class="bar"><i style="width:{pct}%"></i></span>'
            f'<span class="me">Me {pct}%</span><span class="them">Them {100 - pct}%</span></span>')


def nest_lists(md: str) -> str:
    """Summaries indent sub-bullets by 2 spaces; Python-Markdown needs 4, or it flattens them."""
    if not re.search(r"^ {2}[-*] ", md, re.M):
        return md
    return re.sub(r"^( +)(?=[-*] )", lambda m: m.group(1) * 2, md, flags=re.M)


def sections(summary_md: str) -> list[tuple[str, str]]:
    """Split the summary into (heading, markdown body) pairs; heading "" for text before the first ##."""
    parts = re.split(r"^##\s+(.+?)\s*$", summary_md, flags=re.M)
    out = [("", parts[0].strip())] if parts[0].strip() else []
    out += [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return out


def render(session: Path, ctx: dict | None = None) -> Path:
    from .actions import parse

    ctx = ctx or site(session.parent)
    md_text = (session / "notes.md").read_text()
    meta, summary_md = parse_notes(md_text)
    summary_md = re.sub(r"^#\s+.+\n?", "", summary_md, count=1).strip()  # title comes from the frontmatter
    pending = "notetaker:pending-summary" in summary_md
    from .cli import load_config
    items = {i["id"]: i for i in parse(session / "notes.md", load_config()["my_names"])}

    blocks = []
    if pending:
        blocks.append('<div class="pending">Summary is on its way: Claude Desktop will add it shortly. '
                      "The transcript is on the right.</div>")
    else:
        for heading, body in sections(summary_md):
            if heading.lower() == "action items" and items:
                open_n = sum(1 for i in items.values() if not i["done"])
                rows = "\n".join(action_row(i, None) for i in items.values())
                blocks.append(f'<h2>Action items<span class="c">{open_n} open · {len(items)}</span></h2>'
                              f'{file_hint(ctx["port"])}<div class="in-meeting">{rows}</div>')
                continue
            content = markdown.markdown(nest_lists(body), extensions=["sane_lists"])
            content = re.sub(r"\b([A-Z][A-Z0-9]+-\d+)\b(?![^<]*>)", r'<span class="ref">\1</span>', content)
            if heading:
                count = len(re.findall(r"^[-*] ", body, re.M))
                c = f'<span class="c">{count}</span>' if count > 1 else ""
                blocks.append(f"<h2>{html.escape(heading)}{c}</h2>")
            cls = ' class="lead"' if heading.lower() == "summary" else ""
            blocks.append(f"<div{cls}>{content}</div>")

    seg_file = session / "transcript.json"
    segments = json.loads(seg_file.read_text()) if seg_file.exists() else []

    bits = []
    if meta.get("date"):
        try:
            bits.append(f'<time>{datetime.fromisoformat(meta["date"]):%a %-d %b %Y · %H:%M}</time>')
        except ValueError:
            bits.append(f"<span>{html.escape(meta['date'])}</span>")
    if meta.get("duration_min"):
        bits.append(f'<span>{meta["duration_min"]} min</span>')
    langs = [LANG_CODES.get(l.strip(), l.strip()) for l in meta.get("languages", "").strip("[]").split(",") if l.strip()]
    if langs:
        bits.append(f'<span>{" ".join(langs)}</span>')
    if meta.get("summary_by") and not pending:
        bits.append(f'<span>summary: {BY_NAMES.get(meta["summary_by"], meta["summary_by"])}</span>')
    if segments:
        bits.append(talk_share(segments))
    bits.append(f'<a class="file-only" href="{(session / "notes.md").as_uri()}">notes.md</a>')

    title = meta.get("title", "Meeting")
    transcript = (f'<aside class="tx" aria-label="Transcript"><h2>Transcript<span class="c">{len(segments)} lines</span></h2>'
                  f"{transcript_html(segments)}</aside>") if segments else ""
    body = f"""<div class="head"><h1>{html.escape(title)}</h1><div class="meta">{"".join(bits)}</div></div>
<div class="cols"><article class="doc">{"".join(blocks)}</article>{transcript}</div>"""
    out = session / "notes.html"
    out.write_text(page(title, sidebar(ctx, "../", session.name), body))
    return out
