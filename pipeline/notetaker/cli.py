"""notetaker process <session_dir> — transcribe the recorded tracks and write notes.md.

Session dir (written by the menu bar app):
    meta.json   {"started": ISO8601, "tracks": {"mic": {"file": "mic.caf", "offset": 0.0}, "system": {...}}}
    mic.caf / system.caf

Prints `STATUS: ...` lines for the app and finally `DONE: <path to notes.md>`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/notetaker"))
DEFAULT_CONFIG = {
    "notes_dir": "~/Notes/meetings",
    "summary_language": "English",
    "vocabulary": [],
    "languages": ["lv", "en", "ru"],
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = CONFIG_DIR / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    else:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    context = CONFIG_DIR / "context.md"
    cfg["context"] = context.read_text().strip() if context.exists() else ""
    return cfg


def status(msg: str) -> None:
    print(f"STATUS: {msg}", flush=True)


def ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_transcript(segments: list[dict]) -> str:
    """Group consecutive same-speaker segments into paragraphs."""
    lines, cur = [], None
    for s in segments:
        if cur and cur["speaker"] == s["speaker"] and s["start"] - cur["end"] < 4:
            cur["text"] += " " + s["text"]
            cur["end"] = s["end"]
        else:
            if cur:
                lines.append(cur)
            cur = dict(s)
    if cur:
        lines.append(cur)
    return "\n\n".join(f"**[{ts(l['start'])}] {l['speaker']}:** {l['text']}" for l in lines)


def transcribe_session(session: Path, vocabulary: list[str], languages: list[str] | None = None) -> list[dict]:
    from .transcribe import drop_echo, transcribe_track

    meta = json.loads((session / "meta.json").read_text())
    by_track: dict[str, list[dict]] = {}
    for name, speaker in (("system", "Them"), ("mic", "Me")):
        track = meta.get("tracks", {}).get(name)
        if not track or not (session / track["file"]).exists():
            continue
        if (session / track["file"]).stat().st_size < 8192:
            continue

        def progress(i, n, speaker=speaker):
            status(f"Transcribing {speaker.lower()} {i + 1}/{n}")

        by_track[name] = transcribe_track(str(session / track["file"]), speaker, track.get("offset", 0.0),
                                          progress, vocabulary, languages)
    if "mic" in by_track and "system" in by_track:
        by_track["mic"] = drop_echo(by_track["mic"], by_track["system"])
    segments = sorted((s for segs in by_track.values() for s in segs), key=lambda s: s["start"])
    (session / "transcript.json").write_text(json.dumps(segments, ensure_ascii=False, indent=1))
    return segments


def safe_title(title: str) -> str:
    title = re.sub(r"[/:\\\n\r\t]", "-", title).strip(" .-")
    return title[:70] or "Meeting"


def notify(title: str, body: str) -> None:
    script = f'display notification {json.dumps(body)} with title {json.dumps(title)}'
    subprocess.run(["osascript", "-e", script], capture_output=True)


PENDING_MARKER = "<!-- notetaker:pending-summary -->"


def load_segments(session: Path, cfg: dict) -> list[dict]:
    transcript_file = session / "transcript.json"
    if transcript_file.exists():
        return json.loads(transcript_file.read_text())
    status("Transcribing…")
    return transcribe_session(session, cfg.get("vocabulary", []), cfg.get("languages"))


def write_notes(session: Path, notes: str, summary_by: str, segments: list[dict], rename: bool) -> Path:
    """Assemble notes.md (frontmatter + summary + transcript); optionally rename folder to the title."""
    m = re.search(r"^#\s+(.+)$", notes, re.M)
    title = safe_title(m.group(1) if m else "Meeting")
    meta = json.loads((session / "meta.json").read_text())
    started = datetime.fromisoformat(meta["started"].replace("Z", "+00:00")).astimezone()
    duration = max(s["end"] for s in segments)
    langs = sorted({s["lang"] for s in segments})
    doc = (
        "---\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"date: {started.isoformat(timespec='minutes')}\n"
        f"duration_min: {round(duration / 60)}\n"
        f"languages: [{', '.join(langs)}]\n"
        f"summary_by: {summary_by}\n"
        "---\n\n"
        f"{notes}\n\n---\n\n## Transcript\n\n{render_transcript(segments)}\n"
    )
    (session / "notes.md").write_text(doc)

    # Rename the session folder to "<date time> – <title>" so the archive is browsable.
    target = session.parent / f"{started:%Y-%m-%d %H%M} – {title}"
    if rename and session.name == f"{started:%Y-%m-%d %H%M}" and not target.exists():
        session.rename(target)
        session = target
    from .html import render
    render(session)  # notes.html next to notes.md: what the app opens for humans
    return session / "notes.md"


def process(session: Path, mode: str, language: str | None) -> tuple[Path, bool]:
    """Returns (notes.md, finished). finished=False means the summary was handed to Claude Desktop."""
    from .summarize import build_prompt, summarize_claude, summarize_local

    cfg = load_config()
    language = language or cfg["summary_language"]
    t0 = time.time()
    segments = load_segments(session, cfg)
    if not segments:
        raise RuntimeError("No speech detected in the recording")

    prompt = build_prompt(render_transcript(segments), language, cfg["context"])
    status("Summarizing with Claude…" if mode == "claude" else "Summarizing locally…")
    try:
        notes = summarize_claude(prompt) if mode == "claude" else summarize_local(prompt)
    except Exception as e:
        print(f"summary failed: {e}", file=sys.stderr)
        if mode != "claude":
            raise RuntimeError(f"Local summary failed: {e}") from e
        # CLI not logged in / unavailable: queue for the Claude Desktop scheduled task.
        (session / "summary_request.md").write_text(prompt)
        notes = (f"# Meeting\n\n{PENDING_MARKER}\n> Summary pending — Claude Desktop will add it shortly "
                 "(scheduled task \"Meeting notes\"). The transcript is below.")
        path = write_notes(session, notes, "pending", segments, rename=False)
        status("Transcript ready — Claude Desktop will summarize")
        notify("Transcript ready", "Claude Desktop will add the summary shortly")
        return path, False

    path = write_notes(session, notes, mode, segments, rename=True)
    status(f"Done in {int(time.time() - t0)}s")
    notify("Meeting notes ready", path.parent.name)
    return path, True


def finish(session: Path, summary_file: Path, summary_by: str) -> Path:
    """Insert a summary written elsewhere (e.g. by Claude Desktop) into a pending session."""
    segments = json.loads((session / "transcript.json").read_text())
    summary = summary_file.read_text().strip()
    path = write_notes(session, summary, summary_by, segments, rename=True)
    (path.parent / "summary_request.md").unlink(missing_ok=True)
    (path.parent / summary_file.name).unlink(missing_ok=True) if summary_file.parent == session else None
    notify("Meeting notes ready", path.parent.name)
    return path


def sessions(notes_dir: Path) -> list[dict]:
    """All meetings, newest first (by the date in the folder name, not file mtime)."""
    out = []
    for d in notes_dir.iterdir() if notes_dir.exists() else []:
        notes = d / "notes.md"
        if not d.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2} \d{4}", d.name):
            continue
        fm = {}
        if notes.exists():
            head = notes.read_text().split("\n---\n", 1)[0]
            for line in head.splitlines():
                if ":" in line and not line.startswith("---"):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
        out.append({
            "folder": str(d),
            "notes": str(notes) if notes.exists() else None,
            "title": fm.get("title", d.name[16:] or "(untitled)"),
            "date": fm.get("date", d.name[:15]),
            "duration_min": fm.get("duration_min"),
            "summary_by": fm.get("summary_by", "not processed"),
            "pending": (d / "summary_request.md").exists(),
        })
    return sorted(out, key=lambda s: Path(s["folder"]).name[:15], reverse=True)


def pending(notes_dir: Path) -> list[Path]:
    return sorted(p.parent for p in notes_dir.glob("*/summary_request.md"))


def main() -> None:
    p = argparse.ArgumentParser(prog="notetaker")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("process", help="transcribe + summarize a recorded session folder")
    pr.add_argument("session")
    pr.add_argument("--mode", choices=["claude", "local"], default="claude")
    pr.add_argument("--language", help="summary language, e.g. English, Latvian or Russian")
    pr.add_argument("--retranscribe", action="store_true", help="ignore cached transcript.json")
    fi = sub.add_parser("finish", help="insert an externally written summary into a pending session")
    fi.add_argument("session")
    fi.add_argument("--summary-file", required=True)
    fi.add_argument("--by", default="claude-desktop")
    sub.add_parser("pending", help="list sessions waiting for a summary")
    ls = sub.add_parser("list", help="list meetings newest first as JSON lines")
    ls.add_argument("-n", type=int, default=20)
    sub.add_parser("latest", help="print the newest meeting's notes.md path")
    ht = sub.add_parser("html", help="(re)render notes.html from notes.md, e.g. after editing notes.md")
    ht.add_argument("session", nargs="?", help="session folder; omit with --all")
    ht.add_argument("--all", action="store_true")
    sub.add_parser("config", help="print config paths")
    args = p.parse_args()

    if args.cmd == "config":
        cfg = load_config()
        print(f"config:  {CONFIG_DIR / 'config.json'}\ncontext: {CONFIG_DIR / 'context.md'}\nnotes:   {cfg['notes_dir']}")
        return

    notes_dir = Path(os.path.expanduser(load_config()["notes_dir"]))
    if args.cmd == "list":
        for s in sessions(notes_dir)[: args.n]:
            print(json.dumps(s, ensure_ascii=False))
        return
    if args.cmd == "latest":
        done = [s for s in sessions(notes_dir) if s["notes"]]
        print(done[0]["notes"] if done else "")
        return
    if args.cmd == "html":
        from .html import render
        targets = [Path(x["folder"]) for x in sessions(notes_dir) if x["notes"]] if args.all \
            else [Path(args.session).expanduser()]
        for t in targets:
            print(render(t))
        return
    if args.cmd == "pending":
        for d in pending(Path(os.path.expanduser(load_config()["notes_dir"]))):
            print(d)
        return
    session = Path(args.session).expanduser().resolve()
    if args.cmd == "finish":
        print(f"DONE: {finish(session, Path(args.summary_file).expanduser(), args.by)}")
        return
    if args.retranscribe:
        (session / "transcript.json").unlink(missing_ok=True)
    try:
        notes, finished = process(session, args.mode, args.language)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
    print(f"{'DONE' if finished else 'PENDING'}: {notes}", flush=True)


if __name__ == "__main__":
    main()
