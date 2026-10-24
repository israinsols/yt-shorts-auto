"""AI narration generation with Edge TTS."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import edge_tts
from moviepy.config import get_setting
from moviepy.editor import AudioFileClip


def available_voices(config: dict[str, Any]) -> list[str]:
    voice_config = config.get("voice", {})
    voices = voice_config.get("voices")
    if not isinstance(voices, list) or not voices or not all(
        isinstance(voice, str) and voice.strip() for voice in voices
    ):
        raise RuntimeError("Set voice.voices to a non-empty list of Edge TTS voice names in config.yaml.")
    return voices


async def _save_speech(text: str, voice: str, rate: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))


def _audio_duration(path: Path) -> float:
    audio = AudioFileClip(str(path))
    try:
        return float(audio.duration)
    finally:
        audio.close()


def _tempo_adjustment(duration: float, minimum: float, maximum: float) -> float | None:
    if minimum <= duration <= maximum:
        return None
    target = minimum + 1 if duration < minimum else maximum - 1
    factor = duration / target
    if not 0.75 <= factor <= 1.25:
        raise RuntimeError(
            f"Generated narration is {duration:.1f}s, too far outside the "
            f"{minimum:.0f}-{maximum:.0f}s target for a natural tempo adjustment. "
            "Adjust the script word count or voice.rate in config.yaml."
        )
    return factor


def generate_voice(text: str, voice: str, config: dict[str, Any], output_path: Path) -> None:
    rate = str(config.get("voice", {}).get("rate", "+0%"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_save_speech(text, voice, rate, output_path))
    except (OSError, asyncio.TimeoutError, edge_tts.exceptions.EdgeTTSError) as exc:
        raise RuntimeError(
            f"Could not generate Edge TTS narration using {voice!r}: {exc}. "
            "Check your internet connection and voice name."
        ) from exc
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Edge TTS completed without producing an audio file.")
    video_config = config.get("video", {})
    minimum = float(video_config.get("minimum_seconds", 30))
    maximum = float(video_config.get("maximum_seconds", 45))
    if minimum <= 0 or maximum <= minimum:
        raise RuntimeError("video.minimum_seconds and maximum_seconds are invalid.")
    duration = _audio_duration(output_path)
    factor = _tempo_adjustment(duration, minimum, maximum)
    if factor is None:
        return
    adjusted_path = output_path.with_name(f"{output_path.stem}.adjusted.mp3")
    result = subprocess.run(
        [
            get_setting("FFMPEG_BINARY"),
            "-y",
            "-i",
            str(output_path),
            "-filter:a",
            f"atempo={factor:.6f}",
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(adjusted_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not adjusted_path.is_file() or adjusted_path.stat().st_size == 0:
        adjusted_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not adjust narration tempo with FFmpeg. "
            f"Install FFmpeg or check the generated audio. {result.stderr[-1000:]}"
        )
    os.replace(adjusted_path, output_path)
