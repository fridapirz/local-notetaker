"""Local transcription: energy VAD -> <=28s chunks -> per-chunk LV/EN/RU detection -> Whisper (MLX)."""

from __future__ import annotations

import difflib
import os

import mlx.core as mx
import numpy as np
from mlx_whisper import transcribe as whisper_transcribe
import soundfile as sf
from mlx_whisper.audio import N_FRAMES, SAMPLE_RATE, log_mel_spectrogram, pad_or_trim
from mlx_whisper.transcribe import ModelHolder
from scipy.signal import resample_poly

WHISPER_MODEL = os.environ.get("NOTETAKER_WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")
LANGUAGES = os.environ.get("NOTETAKER_LANGUAGES", "lv,en,ru").split(",")

FRAME = int(0.03 * SAMPLE_RATE)  # 30 ms VAD frames
MAX_CHUNK_S = 28.0
MERGE_GAP_S = 0.8
MIN_SPEECH_S = 0.4


def load_audio(path: str) -> np.ndarray:
    """Read any WAV/CAF, downmix to mono, resample to 16 kHz (no ffmpeg needed)."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SAMPLE_RATE:
        g = np.gcd(int(sr), SAMPLE_RATE)
        mono = resample_poly(mono, SAMPLE_RATE // g, int(sr) // g).astype(np.float32)
    return mono


def speech_regions(audio: np.ndarray) -> list[tuple[float, float]]:
    """Return (start, end) seconds of regions louder than an adaptive noise floor."""
    n = len(audio) // FRAME
    if n == 0:
        return []
    rms = np.sqrt(np.mean(audio[: n * FRAME].reshape(n, FRAME) ** 2, axis=1))
    floor = np.percentile(rms, 20)
    threshold = max(floor * 3.0, 0.004)
    active = rms > threshold

    regions: list[list[float]] = []
    for i, on in enumerate(active):
        if not on:
            continue
        t0, t1 = i * FRAME / SAMPLE_RATE, (i + 1) * FRAME / SAMPLE_RATE
        if regions and t0 - regions[-1][1] <= MERGE_GAP_S:
            regions[-1][1] = t1
        else:
            regions.append([t0, t1])
    return [(a, b) for a, b in regions if b - a >= MIN_SPEECH_S]


def chunks_from_regions(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pack speech regions into chunks <= MAX_CHUNK_S, splitting only at silences when possible."""
    chunks: list[list[float]] = []
    for a, b in regions:
        while b - a > MAX_CHUNK_S:  # one long monologue: hard split
            chunks.append([a, a + MAX_CHUNK_S])
            a += MAX_CHUNK_S
        if chunks and b - chunks[-1][0] <= MAX_CHUNK_S and a - chunks[-1][1] < 2.0:
            chunks[-1][1] = b
        else:
            chunks.append([a, b])
    return [(a, b) for a, b in chunks]


def detect_language(audio: np.ndarray, languages: list[str] | None = None) -> str:
    """Pick the most likely language among `languages` (Whisper's own detector, restricted)."""
    model = ModelHolder.get_model(WHISPER_MODEL, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
    mel = pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16)
    _, probs = model.detect_language(mel)
    return max(languages or LANGUAGES, key=lambda lang: probs.get(lang, 0.0))


HALLUCINATIONS = (
    "paldies, ka skatījāties",
    "paldies par skatīšanos",
    "thank you for watching",
    "thanks for watching",
    "subtitles by",
    "subtitri",
    "субтитры сделал",
    "субтитры создавал",
    "редактор субтитров",
    "продолжение следует",
    "спасибо за просмотр",
    "dimatorzok",
)


def transcribe_track(path: str, speaker: str, offset: float, progress=None,
                     vocabulary: list[str] | None = None, languages: list[str] | None = None) -> list[dict]:
    audio = load_audio(path)
    hint = ", ".join(vocabulary) if vocabulary else None
    chunks = chunks_from_regions(speech_regions(audio))
    segments: list[dict] = []
    for i, (a, b) in enumerate(chunks):
        if progress:
            progress(i, len(chunks))
        piece = audio[int(max(0, a - 0.2) * SAMPLE_RATE) : int((b + 0.2) * SAMPLE_RATE)]
        lang = detect_language(piece, languages)
        result = whisper_transcribe(
            piece,
            path_or_hf_repo=WHISPER_MODEL,
            language=lang,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            initial_prompt=hint,
            verbose=None,
        )
        for s in result["segments"]:
            text = s["text"].strip()
            if not text or s.get("no_speech_prob", 0) > 0.8:
                continue
            if any(h in text.lower() for h in HALLUCINATIONS):
                continue
            segments.append(
                {
                    "speaker": speaker,
                    "lang": lang,
                    "start": round(offset + max(0, a - 0.2) + s["start"], 2),
                    "end": round(offset + max(0, a - 0.2) + s["end"], 2),
                    "text": text,
                }
            )
    return segments


def drop_echo(mic: list[dict], system: list[dict]) -> list[dict]:
    """Without headphones the mic hears the speakers; drop mic lines that duplicate system lines."""
    kept = []
    for m in mic:
        echo = any(
            s["start"] - 2 <= m["start"] <= s["end"] + 2
            and difflib.SequenceMatcher(None, m["text"].lower(), s["text"].lower()).ratio() > 0.6
            for s in system
        )
        if not echo:
            kept.append(m)
    return kept
