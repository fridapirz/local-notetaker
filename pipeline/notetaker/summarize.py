"""Summaries: Claude (via the `claude` CLI, uses your Claude Code login) or a local MLX model."""

from __future__ import annotations

import os
import shutil
import subprocess

LOCAL_MODEL = os.environ.get("NOTETAKER_LOCAL_MODEL", "mlx-community/Qwen3-14B-4bit")
CLAUDE_MODEL = os.environ.get("NOTETAKER_CLAUDE_MODEL", "")  # empty = Claude Code default

PROMPT = """You are writing meeting notes from an automatic transcript.
The transcript mixes Latvian and English. "Me" is the person who recorded it; "Them" is everyone
else on the call (several people may be merged under "Them"). Transcription errors are likely,
especially for names and product terms — correct them when the context makes it obvious.
{context}
Write the notes in {language}. Output Markdown only, exactly in this structure:

# <short descriptive meeting title, max 8 words>

## Summary
<3-6 sentences: what the meeting was about and where it landed>

## Key points
- ...

## Decisions
- ... (write "None recorded" if there were none)

## Action items
- [ ] <owner if known — "Me" if it was the recorder>: <task> <(due date if mentioned)>

## Open questions
- ... (omit this section if there are none)

Transcript:
{transcript}
"""


def build_prompt(transcript: str, language: str, context: str) -> str:
    ctx = f"\nBackground the recorder gave you (glossary, people, projects):\n{context}\n" if context else ""
    return PROMPT.format(transcript=transcript, language=language, context=ctx)


def claude_cli() -> str | None:
    for candidate in (shutil.which("claude"), "/usr/local/bin/claude", os.path.expanduser("~/.local/bin/claude"),
                      os.path.expanduser("~/.claude/local/claude"), "/opt/homebrew/bin/claude"):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def summarize_claude(prompt: str) -> str:
    cli = claude_cli()
    if not cli:
        raise RuntimeError("`claude` CLI not found — install Claude Code or use local mode")
    cmd = [cli, "-p", "--tools", "", "--no-session-persistence", "--output-format", "text"]
    if CLAUDE_MODEL:
        cmd += ["--model", CLAUDE_MODEL]
    out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"claude failed: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def summarize_local(prompt: str) -> str:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(LOCAL_MODEL)
    messages = [{"role": "user", "content": prompt}]
    try:
        text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False,
                                             enable_thinking=False)
    except TypeError:
        text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    out = generate(model, tokenizer, prompt=text, max_tokens=2500, sampler=make_sampler(temp=0.3))
    if "</think>" in out:
        out = out.split("</think>", 1)[1]
    return out.strip()
