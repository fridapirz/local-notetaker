"""Render notes.md (+ transcript.json) into a readable, self-contained notes.html."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

import markdown

LANG_NAMES = {"lv": "Latvian", "en": "English"}
BY_NAMES = {"claude": "Claude", "claude-desktop": "Claude", "local": "on-device model", "pending": "pending"}

CSS = """
:root {
  --bg: #f7f6fb; --paper: #ffffff; --ink: #1d1b2e; --muted: #6b6880; --line: #e7e5f0;
  --accent: #5b4cf0; --accent-soft: #eeebff; --them: #0f8a7e; --them-soft: #e2f5f2;
  --warn-soft: #fff4e0; --warn: #9a5b00;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14131c; --paper: #1d1c28; --ink: #ecebf5; --muted: #9b98b0; --line: #2e2c3d;
    --accent: #a59bff; --accent-soft: #2b2752; --them: #5fd0c3; --them-soft: #183532;
    --warn-soft: #3a2c12; --warn: #f2c26b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
main { max-width: 780px; margin: 0 auto; padding: 48px 20px 80px; }
.paper { background: var(--paper); border: 1px solid var(--line); border-radius: 18px; padding: 40px 44px; }
.eyebrow { color: var(--accent); font-size: 13px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
h1 { font-size: 30px; line-height: 1.2; margin: 6px 0 14px; letter-spacing: -.01em; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.chip { background: var(--accent-soft); color: var(--ink); border-radius: 999px; padding: 3px 12px; font-size: 13px; }
.pending { background: var(--warn-soft); color: var(--warn); border-radius: 12px; padding: 12px 16px; margin: 20px 0 0; }
h2 { font-size: 13px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted);
     margin: 34px 0 10px; padding-top: 22px; border-top: 1px solid var(--line); }
p { margin: 0 0 12px; }
ul { padding-left: 22px; margin: 0 0 12px; }
li { margin: 4px 0; }
li.task { list-style: none; margin-left: -22px; display: flex; gap: 10px; }
li.task .box { flex: none; width: 18px; height: 18px; margin-top: 3px; border: 2px solid var(--accent); border-radius: 5px; }
strong { font-weight: 650; }
code { background: var(--accent-soft); padding: 1px 6px; border-radius: 6px; font-size: .9em; }
details { margin-top: 34px; border-top: 1px solid var(--line); padding-top: 22px; }
summary { cursor: pointer; font-size: 13px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
summary::marker { color: var(--accent); }
.t { display: grid; grid-template-columns: 52px 62px 1fr; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line); }
.t:last-child { border-bottom: 0; }
.time { color: var(--muted); font: 12px/2 ui-monospace, "SF Mono", Menlo, monospace; }
.who { font-size: 12px; font-weight: 650; border-radius: 999px; text-align: center; height: 22px; line-height: 22px; margin-top: 2px; }
.who.me { background: var(--accent-soft); color: var(--accent); }
.who.them { background: var(--them-soft); color: var(--them); }
.lang { color: var(--muted); font-size: 11px; margin-left: 6px; text-transform: uppercase; }
.transcript { margin-top: 14px; font-size: 15px; }
footer { color: var(--muted); font-size: 13px; margin-top: 18px; text-align: center; }
footer a { color: var(--muted); }
@media (max-width: 600px) { .paper { padding: 26px 20px; } .t { grid-template-columns: 44px 1fr; } .t .who { grid-column: 2; justify-self: start; padding: 0 10px; } .t .text { grid-column: 1 / -1; } }
@media print { body { background: #fff; } .paper { border: 0; padding: 0; } details > *:not(summary) { display: block; } }
"""


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
        out.append(
            f'<div class="t"><span class="time">{fmt_time(r["start"])}</span>'
            f'<span class="who {who}">{html.escape(r["speaker"])}</span>'
            f'<span class="text">{html.escape(r["text"])}{lang}</span></div>'
        )
    return "\n".join(out)


def render(session: Path) -> Path:
    md_text = (session / "notes.md").read_text()
    meta, summary_md = parse_notes(md_text)

    # Title comes from the frontmatter; drop the summary's own "# Title" line.
    summary_md = re.sub(r"^#\s+.+\n?", "", summary_md, count=1).strip()
    pending = "notetaker:pending-summary" in summary_md
    body = markdown.markdown(summary_md, extensions=["sane_lists"])
    body = re.sub(r"<li>\[[ xX]?\]\s*", '<li class="task"><span class="box"></span><span>', body)
    body = re.sub(r'(<li class="task">.*?)</li>', r"\1</span></li>", body, flags=re.S)
    if pending:
        body = ('<div class="pending">Summary is on its way: Claude Desktop will add it shortly. '
                "The transcript is below.</div>")

    chips = []
    if meta.get("date"):
        try:
            chips.append(datetime.fromisoformat(meta["date"]).strftime("%a %-d %b %Y, %H:%M"))
        except ValueError:
            chips.append(meta["date"])
    if meta.get("duration_min"):
        chips.append(f'{meta["duration_min"]} min')
    langs = [LANG_NAMES.get(l.strip(), l.strip()) for l in meta.get("languages", "").strip("[]").split(",") if l.strip()]
    if langs:
        chips.append(" · ".join(langs))
    if meta.get("summary_by") and not pending:
        chips.append("Summary by " + BY_NAMES.get(meta["summary_by"], meta["summary_by"]))

    seg_file = session / "transcript.json"
    segments = json.loads(seg_file.read_text()) if seg_file.exists() else []
    transcript = ""
    if segments:
        transcript = (f'<details><summary>Transcript · {len(segments)} lines</summary>'
                      f'<div class="transcript">{transcript_html(segments)}</div></details>')

    title = html.escape(meta.get("title", "Meeting"))
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{CSS}</style></head>
<body><main><article class="paper">
<div class="eyebrow">Meeting notes</div>
<h1>{title}</h1>
<div class="chips">{"".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)}</div>
{body}
{transcript}
</article>
<footer><a href="{(session / "notes.md").as_uri()}">notes.md</a> · <a href="{session.as_uri()}/">open folder</a></footer>
</main></body></html>
"""
    out = session / "notes.html"
    out.write_text(page)
    return out
