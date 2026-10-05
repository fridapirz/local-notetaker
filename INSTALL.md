# Installing Notetaker (instructions for Claude)

A person gave you this repository and asked you to install Notetaker. Do the whole setup for them, step
by step, in plain language. They may not be technical. Do every step you can yourself. Some steps only the
person can do: macOS permission dialogs, the browser sign-in, and clicking around in the app. Tell them
exactly what to click, and wait for them to confirm.

Repository: `fridapirz/local-notetaker`. App command used below: `N=/Applications/Notetaker.app/Contents/Resources/notetaker`

## 1. Check the Mac

- `uname -m` must print `arm64` (Apple Silicon), and `sw_vers -productVersion` must be 15 or higher. If not,
  stop and explain that Notetaker needs an M1-or-newer Mac on macOS 15+.
- At least 15 GB free: `df -h ~`.

## 2. Install the app from the latest release

```bash
TMP=$(mktemp -d)
# gh works for private repos if the person is signed in; otherwise use the public download URL.
gh release download --repo fridapirz/local-notetaker --pattern 'Notetaker.dmg' --dir "$TMP" 2>/dev/null \
  || curl -fL -o "$TMP/Notetaker.dmg" https://github.com/fridapirz/local-notetaker/releases/latest/download/Notetaker.dmg
osascript -e 'quit app "Notetaker"' 2>/dev/null; sleep 1
MNT=$(hdiutil attach -nobrowse -readonly "$TMP/Notetaker.dmg" | tail -1 | awk -F'\t' '{print $NF}')
rm -rf /Applications/Notetaker.app && ditto "$MNT/Notetaker.app" /Applications/Notetaker.app
hdiutil detach "$MNT" -quiet; rm -rf "$TMP"
xattr -dr com.apple.quarantine /Applications/Notetaker.app 2>/dev/null || true
```

If an older copy exists at `~/Applications/Notetaker.app`, ask before deleting it. Two copies would show
two menu bar icons.

If both downloads fail, the repo is probably private and the person has no access. Ask them to get invited
to the repo, or to send you the `Notetaker.dmg` file.

## 3. Speech engine (~3 GB, runs in the background)

Start this now; it takes a few minutes: `"$N" warmup` (run it in the background). The first run also
installs Python by itself.

## 4. Claude plugin (`/meeting`)

Find the `claude` CLI: `command -v claude`. Failing that, use the newest one bundled with Claude Desktop:
`ls -d ~/Library/Application\ Support/Claude/claude-code/*/ | sort -V | tail -1`, then look for
`claude.app/Contents/MacOS/claude` inside it, possibly one folder deeper. Then:

```bash
"$CLAUDE" plugin marketplace add fridapirz/local-notetaker
"$CLAUDE" plugin install notetaker@local-notetaker --scope user
```

If the repo isn't reachable, use a `notetaker.plugin` file the person has, or skip this step and say so.
Tell them to quit and reopen the Claude app (⌘Q) later so `/meeting` appears.

## 5. Claude summaries

Run `"$N" doctor`.
- If `claude_logged_in` is `true`, summaries already work. Skip to step 6.
- Otherwise, recommend a one-time sign-in so summaries happen right after each meeting. Write a script
  `~/Desktop/Sign in to Claude.command` containing `"$CLAUDE" auth login`, `chmod +x` it, `open` it, and
  tell the person to sign in in the browser window that opens. Afterwards check `"$N" doctor` again.
- If they'd rather not sign in, nothing breaks. Notes are then summarized on the Mac itself (it downloads
  an extra ~8 GB model the first time).

## 6. Start the app and grant permissions (the person does this)

`open /Applications/Notetaker.app`, then tell them:

1. A **waveform icon** appears in the menu bar, near the clock. If the menu bar is full, it can hide behind
   the camera notch; ⌘-drag a few other icons off the bar to make room.
2. Click it → **Start Recording**. Allow **Microphone**. For **Screen & System Audio Recording**, click
   **Open System Settings** and switch **Notetaker** on (it records audio only, never the screen).
3. Click the icon → **Quit Notetaker**, then open it again from Applications.
4. In the icon's menu, turn on **Launch at Login** so it can spot calls automatically.

## 7. Finish

Wait for the warmup from step 3 to finish, then run `"$N" doctor` once more. Tell the person, briefly:

- When a call starts in Teams, Zoom, Slack, Meet or similar, a card appears at the top right: **Start notes**.
- About a minute after the call ends, the notes open in their browser. They're saved in `~/Notes/meetings`.
- In Claude, `/meeting` shows the latest notes and can draft Jira tickets or Slack recaps from them.
- **Edit Context & Names…** in the menu helps it spell their team's names and projects correctly.
