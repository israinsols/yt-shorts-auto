"""Vertical video assembly, burned-in word captions, and optional music."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.audio.fx import all as audio_fx
from moviepy.video.fx import all as video_fx
from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger(__name__)


def _caption_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _caption_clips(script: str, duration: float, width: int, height: int, font_size: int) -> list[ImageClip]:
    words = script.split()
    if not words:
        raise RuntimeError("Cannot create captions for an empty script.")
    font = _caption_font(font_size)
    clips: list[ImageClip] = []
    segment_duration = duration / len(words)
    for index, word in enumerate(words):
        text = word
        bounds = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox(
            (0, 0), text, font=font, stroke_width=3
        )
        while bounds[2] - bounds[0] > width - 100 and font_size > 28:
            font_size -= 2
            font = _caption_font(font_size)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        padding = 12
        image = Image.new(
            "RGBA",
            (text_width + padding * 2, text_height + padding * 2),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(image)
        x = padding - bounds[0]
        y = padding - bounds[1]
        draw.text((x, y), text, font=font, fill="white", stroke_width=3, stroke_fill="black")
        clips.append(
            ImageClip(np.asarray(image), transparent=True)
            .set_start(index * segment_duration)
            .set_duration(segment_duration)
            .set_position(("center", int(height * 0.76 - image.height / 2)))
        )
    return clips


def _fit_clip(clip: VideoFileClip, duration: float, width: int, height: int) -> VideoFileClip:
    if clip.w / clip.h < width / height:
        clip = clip.resize(width=width)
    else:
        clip = clip.resize(height=height)
    clip = clip.crop(
        x_center=clip.w / 2,
        y_center=clip.h / 2,
        width=width,
        height=height,
    )
    return clip.fx(video_fx.loop, duration=duration)


def _background_track(config: dict[str, Any], duration: float) -> AudioFileClip | None:
    music_config = config.get("music", {})
    if not music_config.get("enabled", True):
        return None
    music_dir = Path(music_config.get("folder", "music"))
    if not music_dir.is_absolute():
        music_dir = Path(__file__).resolve().parent / music_dir
    tracks = sorted(
        path
        for pattern in ("*.mp3", "*.wav", "*.m4a", "*.aac")
        for path in music_dir.glob(pattern)
    )
    if not tracks:
        LOGGER.info("No local music found in %s; rendering with narration only.", music_dir)
        return None
    track = AudioFileClip(str(tracks[0]))
    volume = float(music_config.get("volume", 0.1))
    if not 0 <= volume <= 1:
        track.close()
        raise RuntimeError("music.volume must be between 0 and 1.")
    return track.fx(audio_fx.audio_loop, duration=duration).volumex(volume)


def assemble_video(
    script: str,
    voice_path: Path,
    footage_paths: list[Path],
    output_path: Path,
    config: dict[str, Any],
) -> float:
    video_config = config.get("video", {})
    width = int(video_config.get("width", 1080))
    height = int(video_config.get("height", 1920))
    fps = int(video_config.get("fps", 30))
    minimum = float(video_config.get("minimum_seconds", 30))
    maximum = float(video_config.get("maximum_seconds", 45))
    if width != 1080 or height != 1920 or fps != 30:
        raise RuntimeError("This project requires video.width=1080, height=1920, and fps=30.")
    if not footage_paths:
        raise RuntimeError("No footage was downloaded, so the video cannot be assembled.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    narration = AudioFileClip(str(voice_path))
    audio_duration = narration.duration
    if audio_duration < minimum or audio_duration > maximum:
        narration.close()
        raise RuntimeError(
            f"Generated narration is {audio_duration:.1f}s; Shorts must be "
            f"{minimum:.0f}-{maximum:.0f}s. Adjust the script word count or voice rate and retry."
        )
    opened_video_clips: list[VideoFileClip] = []
    caption_clips: list[ImageClip] = []
    music_track: AudioFileClip | None = None
    final_video: CompositeVideoClip | None = None
    try:
        sequence_parts = []
        elapsed = 0.0
        clip_index = 0
        while elapsed < audio_duration:
            source = footage_paths[clip_index % len(footage_paths)]
            base = VideoFileClip(str(source))
            opened_video_clips.append(base)
            remaining = audio_duration - elapsed
            part_duration = min(base.duration, remaining)
            if part_duration <= 0:
                raise RuntimeError(f"Footage clip {source} has no playable duration.")
            fitted = _fit_clip(base, part_duration, width, height)
            opened_video_clips.append(fitted)
            sequence_parts.append(fitted)
            elapsed += part_duration
            clip_index += 1
        video_sequence = concatenate_videoclips(sequence_parts, method="compose").set_duration(audio_duration)
        music_track = _background_track(config, audio_duration)
        audio_tracks = [narration]
        if music_track is not None:
            audio_tracks.append(music_track)
        video_sequence = video_sequence.set_audio(CompositeAudioClip(audio_tracks))
        caption_clips = _caption_clips(
            script,
            audio_duration,
            width,
            height,
            int(video_config.get("caption_font_size", 72)),
        )
        final_video = CompositeVideoClip([video_sequence, *caption_clips], size=(width, height))
        final_video.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=2,
            temp_audiofile=str(output_path.with_suffix(".temp-audio.m4a")),
            remove_temp=True,
            logger=None,
        )
        return audio_duration
    finally:
        if final_video is not None:
            final_video.close()
        elif "video_sequence" in locals():
            video_sequence.close()
        narration.close()
        if music_track is not None:
            music_track.close()
        for clip in caption_clips:
            clip.close()
        for clip in opened_video_clips:
            clip.close()
