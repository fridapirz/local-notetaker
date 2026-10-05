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


def transcribe_session(session: Path, vocabulary: list[str]) -> list[dict]:
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
                                          progress, vocabulary)
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


def process(session: Path, mode: str, language: str | None) -> Path:
    from .summarize import build_prompt, summarize_claude, summarize_local

    cfg = load_config()
    language = language or cfg["summary_language"]
    t0 = time.time()

    transcript_file = session / "transcript.json"
    if transcript_file.exists():
        segments = json.loads(transcript_file.read_text())
    else:
        status("Transcribing…")
        segments = transcribe_session(session, cfg.get("vocabulary", []))
    if not segments:
        raise RuntimeError("No speech detected in the recording")

    transcript = render_transcript(segments)
    status("Summarizing with Claude…" if mode == "claude" else "Summarizing locally…")
    prompt = build_prompt(transcript, language, cfg["context"])
    summary_ok = True
    try:
        notes = summarize_claude(prompt) if mode == "claude" else summarize_local(prompt)
    except Exception as e:  # keep the transcript even if the summary step fails
        print(f"summary failed: {e}", file=sys.stderr)
        summary_ok = False
        notes = f"# Meeting\n\n> Summary failed ({mode}): {e}\n> Retry from the menu bar, or: `notetaker process \"{session}\"`"

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
        f"summary_by: {mode}\n"
        "---\n\n"
        f"{notes}\n\n---\n\n## Transcript\n\n{transcript}\n"
    )
    (session / "notes.md").write_text(doc)

    # Rename the session folder to "<date time> – <title>" so the archive is browsable.
    target = session.parent / f"{started:%Y-%m-%d %H%M} – {title}"
    renameable = session.name == f"{started:%Y-%m-%d %H%M}"
    if summary_ok and renameable and not target.exists():
        session.rename(target)
        session = target
    status(f"Done in {int(time.time() - t0)}s")
    if not summary_ok:
        raise RuntimeError(f"Transcript saved, but the {mode} summary failed — see {session / 'pipeline.log'}")
    notify("Meeting notes ready", title)
    return session / "notes.md"


def main() -> None:
    p = argparse.ArgumentParser(prog="notetaker")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("process", help="transcribe + summarize a recorded session folder")
    pr.add_argument("session")
    pr.add_argument("--mode", choices=["claude", "local"], default="claude")
    pr.add_argument("--language", help="summary language, e.g. English or Latvian")
    pr.add_argument("--retranscribe", action="store_true", help="ignore cached transcript.json")
    sub.add_parser("config", help="print config paths")
    args = p.parse_args()

    if args.cmd == "config":
        cfg = load_config()
        print(f"config:  {CONFIG_DIR / 'config.json'}\ncontext: {CONFIG_DIR / 'context.md'}\nnotes:   {cfg['notes_dir']}")
        return

    session = Path(args.session).expanduser().resolve()
    if args.retranscribe:
        (session / "transcript.json").unlink(missing_ok=True)
    try:
        notes = process(session, args.mode, args.language)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
    print(f"DONE: {notes}", flush=True)


if __name__ == "__main__":
    main()
