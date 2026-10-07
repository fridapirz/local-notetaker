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
    # When the Claude summary fails (not signed in, offline): "local" = summarize on this Mac instead;
    # "desktop" = queue it for the Claude Desktop scheduled task "Meeting notes".
    "claude_fallback": "local",
    "my_names": ["Me"],  # action item owners that count as "mine" on the meetings page
    "server_port": 47821,  # notetaker serve: the meetings page with tickable action items
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


PENDING_MARKER = "<!-- notetaker:pending-summary -->"


def load_segments(session: Path, cfg: dict) -> list[dict]:
    transcript_file = session / "transcript.json"
    if transcript_file.exists():
        return json.loads(transcript_file.read_text())
    status("Transcribing…")
    return transcribe_session(session, cfg.get("vocabulary", []))


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
    try:
        write_index(session.parent)
    except Exception as e:  # another note failing to render must not fail this meeting
        print(f"index not rebuilt: {e}", file=sys.stderr)
    return session / "notes.md"


def all_actions(notes_dir: Path, my_names: list[str], meetings: list[dict] | None = None) -> list[dict]:
    from .actions import parse
    meetings = sessions(notes_dir) if meetings is None else meetings
    items = []
    for s in meetings:
        if not s["notes"]:
            continue
        try:
            items += parse(Path(s["notes"]), my_names)
        except (OSError, UnicodeDecodeError) as e:  # deleted meanwhile, or saved in another encoding
            print(f"skipped action items in {Path(s['folder']).name}: {e}", file=sys.stderr)
    return items


def write_index(notes_dir: Path) -> Path:
    """Refresh index.html (action items + all meetings) in the notes folder."""
    from .html import render_index
    return render_index(notes_dir)


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
        if cfg.get("claude_fallback", "local") == "local":
            status("Claude unavailable — summarizing on this Mac…")
            try:
                notes = summarize_local(prompt)
            except Exception as e2:
                raise RuntimeError(f"Claude failed ({e}) and local summary failed ({e2})") from e2
            path = write_notes(session, notes, "local", segments, rename=True)
            status(f"Done in {int(time.time() - t0)}s")
            notify("Meeting notes ready", path.parent.name + " (summarized on this Mac)")
            return path, True
        # Queue for the Claude Desktop scheduled task.
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
            try:
                head = notes.read_text(errors="replace").split("\n---\n", 1)[0]
            except OSError:  # removed while listing
                continue
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
    pr.add_argument("--language", help="summary language (default English, from config)")
    pr.add_argument("--retranscribe", action="store_true", help="ignore cached transcript.json")
    fi = sub.add_parser("finish", help="insert an externally written summary into a pending session")
    fi.add_argument("session")
    src = fi.add_mutually_exclusive_group(required=True)
    src.add_argument("--summary-file")
    src.add_argument("--summary-stdin", action="store_true", help="read the summary Markdown from stdin")
    fi.add_argument("--by", default="claude-desktop")
    sub.add_parser("pending", help="list sessions waiting for a summary")
    rq = sub.add_parser("request", help="print the summary prompt (incl. transcript) for a pending session")
    rq.add_argument("session")
    ls = sub.add_parser("list", help="list meetings newest first as JSON lines")
    ls.add_argument("-n", type=int, default=20)
    sub.add_parser("latest", help="print the newest meeting's notes.md path")
    ht = sub.add_parser("html", help="(re)render notes.html from notes.md, e.g. after editing notes.md")
    ht.add_argument("session", nargs="?", help="session folder; omit with --all")
    ht.add_argument("--all", action="store_true")
    sub.add_parser("warmup", help="set up the speech engine: download the Whisper model (~3 GB)")
    sub.add_parser("doctor", help="check that everything needed is in place (JSON)")
    sub.add_parser("index", help="(re)build index.html, the list of all meetings, and print its path")
    ac = sub.add_parser("actions", help="action items across meetings as JSON lines, in priority order (open ones unless --all)")
    ac.add_argument("--all", action="store_true", help="include done items")
    ac.add_argument("--mine", action="store_true", help="only items owned by my_names")
    dn = sub.add_parser("done", help="tick (or --undo) an action item by the id from `actions`")
    dn.add_argument("session")
    dn.add_argument("id")
    dn.add_argument("--undo", action="store_true")
    sv = sub.add_parser("serve", help="serve the meetings page on 127.0.0.1 so action items can be ticked")
    sv.add_argument("--port", type=int)
    sv.add_argument("--app-pid", type=int, help="exit when this process (the menu bar app) is gone")
    sub.add_parser("config", help="print config paths")
    args = p.parse_args()

    if args.cmd == "warmup":
        from huggingface_hub import snapshot_download

        from .transcribe import WHISPER_MODEL
        print("STATUS: Downloading speech model (~3 GB, once)…", flush=True)
        print(f"DONE: {snapshot_download(WHISPER_MODEL)}", flush=True)
        return
    if args.cmd == "doctor":
        from .summarize import claude_cli
        cli = claude_cli()
        logged_in = False
        if cli:
            r = subprocess.run([cli, "auth", "status"], capture_output=True, text=True, timeout=30)
            logged_in = '"loggedIn": true' in r.stdout
        hub = Path(os.path.expanduser("~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-mlx"))
        print(json.dumps({
            "speech_model": any(hub.glob("snapshots/*/*.safetensors")) or any(hub.glob("snapshots/*/*.npz")),
            "claude_cli": cli,
            "claude_logged_in": logged_in,
            "claude_fallback": load_config().get("claude_fallback", "local"),
            "notes_dir": os.path.expanduser(load_config()["notes_dir"]),
        }, indent=2))
        return
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
        from .html import render, site
        ctx = site(notes_dir)
        targets = [Path(x["folder"]) for x in ctx["meetings"] if x["notes"]] if args.all \
            else [Path(args.session).expanduser()]
        for t in targets:
            print(render(t, ctx))
        print(write_index(notes_dir))
        return
    if args.cmd == "index":
        print(write_index(notes_dir))
        return
    if args.cmd == "actions":
        from .actions import by_priority
        for i in by_priority(all_actions(notes_dir, load_config()["my_names"]), notes_dir):
            if (args.all or not i["done"]) and (not args.mine or i["mine"]):
                print(json.dumps(i, ensure_ascii=False))
        return
    if args.cmd == "done":
        from .actions import set_done
        from .html import render
        session = Path(args.session).expanduser().resolve()
        result = set_done(session, args.id, not args.undo)
        if not result:
            print(f"ERROR: no action item {args.id} in {session.name}", flush=True)
            sys.exit(1)
        render(session)
        write_index(notes_dir)
        print(json.dumps(result))
        return
    if args.cmd == "serve":
        from .serve import serve
        serve(notes_dir, args.port or load_config()["server_port"], lambda: write_index(notes_dir), args.app_pid)
        return
    if args.cmd == "pending":
        for d in pending(Path(os.path.expanduser(load_config()["notes_dir"]))):
            print(d)
        return
    session = Path(args.session).expanduser().resolve()
    if args.cmd == "request":
        print((session / "summary_request.md").read_text())
        return
    if args.cmd == "finish":
        if args.summary_stdin:
            tmp = session / "summary.md"
            tmp.write_text(sys.stdin.read())
            print(f"DONE: {finish(session, tmp, args.by)}")
        else:
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
