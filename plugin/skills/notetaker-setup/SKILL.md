---
name: notetaker-setup
description: Install or update the Notetaker menu bar app (local meeting recorder + Whisper transcription) on this Mac. Use when the user wants to set up the meeting note taker, when ~/Applications/Notetaker.app is missing, or when they ask to update or rebuild it.
---

# Install Notetaker

Requirements: an Apple Silicon Mac on macOS 15 or later, and about 12 GB of free disk space for the models.

1. **Check prerequisites.** Run each check yourself, and ask the user before installing anything:
   - Apple Silicon: `uname -m` must print `arm64`. macOS: `sw_vers -productVersion` must be ≥ 15.
   - Xcode Command Line Tools: `xcode-select -p`. If missing, the user runs `xcode-select --install`.
   - uv: check `~/.local/bin/uv` or `command -v uv`. If missing, ask, then run
     `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   - Claude summaries: if `echo ok | claude -p` works, summaries happen immediately. If it doesn't, offer to
     create a Claude Desktop scheduled task named "Meeting notes" (`*/15 9-19 * * 1-5`) that summarizes pending
     sessions using the procedure in the `meeting` skill ("Pending summaries"). This uses the desktop app's
     login, so the user never needs a terminal.
2. **Get the source.** If `~/code/local-notetaker` doesn't exist, ask the user for the repository URL and
   clone it there. If it exists, run `git -C ~/code/local-notetaker pull`.
3. **Build and install:** `~/code/local-notetaker/scripts/build-app.sh`. This builds the app and installs it
   to `~/Applications/Notetaker.app`.
4. **Warm up the models.** Optional, but it makes the first meeting fast. Run in the background:
   ```
   uv run --project ~/code/local-notetaker/pipeline python -c "from huggingface_hub import snapshot_download as d; d('mlx-community/whisper-large-v3-mlx'); d('mlx-community/Qwen3-14B-4bit')"
   ```
5. **First run:** `open ~/Applications/Notetaker.app`. A waveform icon appears in the menu bar. Tell the
   user:
   - Click it, then choose **Start Recording**. macOS asks for **Microphone** and **Screen & System Audio
     Recording** permission. After granting the second one, quit and reopen Notetaker (macOS requires a
     restart).
   - Each rebuild changes the app's signature, so macOS may ask for permissions again.
   - Open **Edit Context & Names…** to describe their team and projects. Add names that Whisper misspells to
     `vocabulary` in `~/.config/notetaker/config.json`.
   - Turn on **Launch at Login** if they want the app always available.
6. Do a 20-second test: play any video with speech, talk over it, then **Stop & Summarize**. The note opens
   automatically when it's done.
