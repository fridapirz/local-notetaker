# Notetaker

![Notetaker demo](docs/demo/notetaker-demo.gif)

[▶ Full-quality video (MP4)](docs/demo/notetaker-demo.mp4)

A local meeting note taker for Apple Silicon Macs. It lives in the menu bar and records any call (Teams,
Zoom, Meet in any browser, Slack huddles), with headphones or speakers. Transcription runs on-device, then
you get a summary in Markdown.

- **Recording:** ScreenCaptureKit captures system audio (*Them*) and the microphone (*Me*) as separate
  tracks, so there's no BlackHole or virtual audio device and no speaker diarization step.
- **Transcription:** Whisper large-v3 on MLX, fully local. Language is detected per ~28-second chunk and
  restricted to **Latvian / English / Russian**, so switching languages mid-call works. Notes are always
  written in **English**.
- **Summary:** **Claude** (through your Claude Code login; only the transcript text is sent) or **local**
  Qwen3-14B (nothing leaves the laptop). You choose when you stop the recording.
- **Claude Desktop:** if the `claude` CLI isn't logged in, the transcript is queued. The "Meeting notes"
  scheduled task in the Claude desktop app writes the summary within 15 minutes (weekdays 9–19).
- **Follow-ups:** the `/meeting` skill in Claude Code / Cowork answers questions across past meetings and
  drafts Jira tickets, Confluence pages and Slack recaps.

## Install with Claude (easiest)

Open the **Claude desktop app → Code**, and paste:

> Install Notetaker from https://github.com/fridapirz/local-notetaker (follow INSTALL.md)

Claude downloads the app, installs the `/meeting` plugin, sets up Claude summaries and the speech engine,
and walks you through the two permission clicks. Steps it follows: [INSTALL.md](INSTALL.md).

## Install from source

```bash
scripts/build-app.sh            # builds + installs ~/Applications/Notetaker.app
open ~/Applications/Notetaker.app
```

**Manual install (without Claude):** download `Notetaker.zip` from the
[latest release](https://github.com/fridapirz/local-notetaker/releases/latest), unzip it, and drag
**Notetaker** to Applications. The first time you open it, macOS says it "can't be opened" because the app
isn't notarized by Apple. Go to **System Settings › Privacy & Security**, scroll down, click **Open
Anyway**, and confirm with your password. You only need to do this once. Installing through Claude avoids
the warning altogether.

Build requirements: macOS 15+, Xcode Command Line Tools, [uv](https://docs.astral.sh/uv/), and a logged-in
`claude` CLI for Claude summaries. The first run downloads about 3 GB for Whisper; the first local summary
downloads about 8 GB.

Permissions: macOS asks for **Microphone** and **Screen & System Audio Recording**. Quit and reopen the app
after granting the second one.

## Use

**Meeting detection:** when a call app (Teams, Zoom, Slack, Webex, FaceTime, or a browser for Meet) uses the
mic for more than 8 seconds, a notification asks *"Meeting detected in Teams — take notes?"*. Click
**Start Notes**. When the call app releases the mic for a minute, recording stops and notes are made
automatically. It works by checking which apps hold the microphone, which needs no extra permission. Turn it
off with **Detect Meetings** in the menu. Tip: set Notetaker's notification style to **Alerts** in System
Settings › Notifications so the prompt stays on screen until you answer.

Click the waveform icon → **Start Recording** → **Stop & Summarize with Claude** (or **Locally**). The note
opens when it's ready. Notes go to `~/Notes/meetings/<date time> – <title>/notes.md`.

Scriptable: `open notetaker://start`, `open "notetaker://stop?mode=claude|local"`, `open notetaker://discard`.

Config (`~/.config/notetaker/`):
- `config.json`: `notes_dir`, `summary_language` (default English), `vocabulary` (names Whisper should
  spell correctly)
- `context.md`: your team, projects and people; passed to the summarizer

Re-process a session: `uv run --project pipeline notetaker process "<session dir>" [--mode local] [--retranscribe]`

## Stable signing (keep permissions across rebuilds)

Ad-hoc signed builds look like a new app to macOS each time, so it asks for Microphone / Screen & System
Audio permission again. Fix it once: open **Keychain Access › Certificate Assistant › Create a
Certificate…**, set Name `Notetaker Local Signing`, Identity Type **Self Signed Root**, Certificate Type
**Code Signing**, and click Create. `scripts/build-app.sh` picks it up automatically.

## Claude Code / Cowork plugin

`plugin/` contains the `meeting` and `notetaker-setup` skills. This repo is also a plugin marketplace:

```bash
claude plugin marketplace add <repo URL or path>
claude plugin install notetaker@local-notetaker
```

`build/notetaker.plugin` (made by `scripts/package-plugin.sh`) is the same plugin as a single file for
Cowork.

## Layout

```
app/        Swift menu bar app (ScreenCaptureKit recorder, pipeline runner)
pipeline/   Python: VAD + Whisper (MLX) transcription, Claude / local summaries
plugin/     Claude Code / Cowork plugin (skills)
scripts/    build-app.sh, package-plugin.sh
```
