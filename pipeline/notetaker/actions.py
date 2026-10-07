"""Action items across meetings: the `- [ ]` lines under "## Action items" in each notes.md.

notes.md stays the source of truth. Ticking an item rewrites its line as `- [x] … ✅ YYYY-MM-DD`
(the Obsidian Tasks convention); the done date is what moves it to the archive later.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from pathlib import Path

ITEM = re.compile(r"^- \[([ xX])\] (.+?)\s*$")
DONE_ON = re.compile(r"\s*✅\s*(\d{4}-\d{2}-\d{2})$")
# "Me: task", "**Me**: task" and "**Me:** task" (colon inside or outside the bold)
OWNER = re.compile(r"^\*{0,2}([^:*]{1,40}?)(?::\*{0,2}|\*{0,2}:)\s+(.+)$")
ARCHIVE_AFTER_DAYS = 7


def item_id(text: str, nth: int = 0) -> str:
    """Hash of the text; repeats of the same text in one note get their occurrence number mixed in."""
    return hashlib.sha1((text if nth == 0 else f"{text}#{nth}").encode()).hexdigest()[:10]


def _valid_date(s: str | None) -> str | None:
    try:
        return date.fromisoformat(s).isoformat() if s else None
    except ValueError:  # hand-edited "✅ 2026-02-30": treat as done without a date
        return None


def _section(lines: list[str]) -> range:
    """Line numbers of the "## Action items" section (empty if the note has none)."""
    start = next((i for i, l in enumerate(lines) if re.match(r"^##\s+Action items\s*$", l, re.I)), None)
    if start is None:
        return range(0)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ") or lines[i] == "---"),
               len(lines))
    return range(start + 1, end)


def is_mine(owner: str | None, my_names: list[str]) -> bool:
    if not owner:
        return False
    names = {n.lower() for n in my_names}
    return any(part.strip().lower() in names for part in re.split(r"[,&/+]| and ", owner))


def parse(notes: Path, my_names: list[str]) -> list[dict]:
    lines = notes.read_text().splitlines()
    items, seen = [], {}
    for i in _section(lines):
        m = ITEM.match(lines[i])
        if not m:
            continue
        text = m.group(2)
        d = DONE_ON.search(text)
        text = DONE_ON.sub("", text)
        nth = seen[text] = seen.get(text, -1) + 1
        o = OWNER.match(text)
        owner, task = (o.group(1).strip(), o.group(2)) if o else (None, text)
        items.append({
            "id": item_id(text, nth),
            "folder": notes.parent.name,
            "owner": owner,
            "task": task,
            "mine": is_mine(owner, my_names),
            "done": m.group(1) != " ",
            "done_on": _valid_date(d.group(1)) if d else None,
        })
    return items


def archived(item: dict, today: date | None = None) -> bool:
    """Done more than ARCHIVE_AFTER_DAYS ago (done without a date counts as long done)."""
    if not item["done"]:
        return False
    if not item["done_on"]:
        return True
    return (today or date.today()) - date.fromisoformat(item["done_on"]) > timedelta(days=ARCHIVE_AFTER_DAYS)


def set_done(session: Path, wanted_id: str, done: bool, today: date | None = None) -> dict | None:
    """Tick or untick one item in notes.md; returns the updated item, or None if it wasn't found."""
    notes = session / "notes.md"
    lines = notes.read_text().splitlines()
    seen: dict[str, int] = {}
    for i in _section(lines):
        m = ITEM.match(lines[i])
        if not m:
            continue
        text = DONE_ON.sub("", m.group(2))
        nth = seen[text] = seen.get(text, -1) + 1
        if item_id(text, nth) != wanted_id:
            continue
        stamp = (today or date.today()).isoformat()
        lines[i] = f"- [x] {text} ✅ {stamp}" if done else f"- [ ] {text}"
        notes.write_text("\n".join(lines) + "\n")
        return {"id": wanted_id, "done": done, "done_on": stamp if done else None}
    return None
