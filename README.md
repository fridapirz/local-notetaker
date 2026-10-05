# Notetaker

A local meeting note taker for Apple Silicon Macs. It lives in the menu bar and records any call (Teams,
Zoom, Meet in any browser, Slack huddles), with headphones or speakers. Transcription runs on-device, then
you get a summary in Markdown.

- **Recording:** ScreenCaptureKit captures system audio (*Them*) and the microphone (*Me*) as separate
  tracks, so there's no BlackHole or virtual audio device and no speaker diarization step.
- **Transcription:** Whisper large-v3 on MLX, fully local. Language is detected per ~28-second chunk and
  restricted to **Latvian / English**, so switching languages mid-call works.
- **Summary:** **Claude** (through your Claude Code login; only the transcript text is sent) or **local**
  Qwen3-14B (nothing leaves the laptop). You choose when you stop the recording.
- **Follow-ups:** the `/meeting` skill in Claude Code / Cowork answers questions across past meetings and
  drafts Jira tickets, Confluence pages and Slack recaps.

## Install

```bash
scripts/build-app.sh            # builds + installs ~/Applications/Notetaker.app
open ~/Applications/Notetaker.app
```

Requirements: macOS 15+, Xcode Command Line Tools, [uv](https://docs.astral.sh/uv/), and a logged-in
`claude` CLI for Claude summaries. The first run downloads about 3 GB for Whisper; the first local summary
downloads about 8 GB.

Permissions: macOS asks for **Microphone** and **Screen & System Audio Recording**. Quit and reopen the app
after granting the second one.

## Use

Click the waveform icon → **Start Recording** → **Stop & Summarize with Claude** (or **Locally**). The note
opens when it's ready. Notes go to `~/Notes/meetings/<date time> – <title>/notes.md`.

Scriptable: `open notetaker://start`, `open "notetaker://stop?mode=claude|local"`, `open notetaker://discard`.

Config (`~/.config/notetaker/`):
- `config.json`: `notes_dir`, `summary_language` (English / Latvian), `vocabulary` (names Whisper should
  spell correctly)
- `context.md`: your team, projects and people; passed to the summarizer

Re-process a session: `uv run --project pipeline notetaker process "<session dir>" [--mode local] [--language Latvian] [--retranscribe]`

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
