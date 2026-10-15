"""Opt-in, anonymous usage statistics (PostHog, EU cloud).

Sent only when the user said yes (`"telemetry": true` in ~/.config/notetaker/config.json, asked once by the
app) and a PostHog project key is configured. Payloads are counts and buckets only: never audio, transcripts, titles,
names or anything typed. The user is a random install ID, hashed. GeoIP lookup is disabled per event and
person profiles aren't created; also turn on "Discard client IP data" in the PostHog project settings.
Failures are silent and never slow down or break a meeting.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import uuid
from datetime import date
from pathlib import Path

ENDPOINT = "https://eu.i.posthog.com/capture/"
CONFIG_DIR = Path(os.path.expanduser("~/.config/notetaker"))
KEY_FILE = Path(__file__).with_name("telemetry_key")  # PostHog project API key (phc_…): public by design


def app_id() -> str | None:
    env = os.environ.get("NOTETAKER_POSTHOG_KEY")
    if env:
        return env.strip()
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def enabled() -> bool:
    try:
        cfg = json.loads((CONFIG_DIR / "config.json").read_text())
    except (OSError, ValueError):
        return False
    return cfg.get("telemetry") is True and app_id() is not None


def install_id() -> str:
    path = CONFIG_DIR / "install_id"
    try:
        return path.read_text().strip()
    except OSError:
        value = str(uuid.uuid4())
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n")
        return value


def app_version() -> str:
    try:
        from importlib.metadata import version
        return version("notetaker")
    except Exception:
        return "unknown"


def send(signal: str, payload: dict | None = None) -> None:
    if not enabled():
        return
    body = {
        "api_key": app_id(),
        "event": signal,
        "distinct_id": hashlib.sha256(install_id().encode()).hexdigest(),
        "properties": {"appVersion": app_version(), **(payload or {}),
                       "$geoip_disable": True, "$process_person_profile": False},
    }
    try:
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=4).close()
    except Exception:
        pass


def duration_bucket(minutes: float) -> str:
    return "<15" if minutes < 15 else "15-30" if minutes < 30 else "30-60" if minutes < 60 else "60+"


def meeting_processed(duration_min: float, languages: list[str], summary_by: str) -> None:
    send("meeting.processed", {"duration": duration_bucket(duration_min),
                               "languages": "+".join(sorted(languages)) or "none",
                               "summaryBy": summary_by})


def daily_active() -> None:
    """At most once a day (called when the app starts its meetings server)."""
    if not enabled():
        return
    state = CONFIG_DIR / "telemetry_last_active"
    today = date.today().isoformat()
    try:
        if state.read_text().strip() == today:
            return
    except OSError:
        pass
    send("app.active")
    try:
        state.write_text(today + "\n")
    except OSError:
        pass
