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
from PIL import Image, ImageDraw, ImageFont, ImageOps

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
    group_size = 3
    max_text_width = width - 120
    segment_duration = duration / len(words)
    for index in range(0, len(words), group_size):
        group = words[index : index + group_size]
        lines: list[str] = []
        line = ""
        for word in group:
            candidate = f"{line} {word}".strip()
            bounds = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox(
                (0, 0), candidate, font=font, stroke_width=2
            )
            while bounds[2] - bounds[0] > max_text_width and font_size > 28:
                font_size -= 2
                font = _caption_font(font_size)
                bounds = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox(
                    (0, 0), candidate, font=font, stroke_width=2
                )
            if line and bounds[2] - bounds[0] > max_text_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        line_bounds = [
            measure.textbbox((0, 0), text, font=font, stroke_width=2)
            for text in lines
        ]
        padding_x = 28
        padding_y = 20
        line_gap = 8
        text_width = max(bounds[2] - bounds[0] for bounds in line_bounds)
        text_height = sum(bounds[3] - bounds[1] for bounds in line_bounds)
        image = Image.new(
            "RGBA",
            (text_width + padding_x * 2, text_height + padding_y * 2 + line_gap * (len(lines) - 1)),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=22,
            fill=(8, 15, 30, 218),
            outline=(65, 205, 255, 255),
            width=3,
        )
        y = padding_y
        for text, bounds in zip(lines, line_bounds):
            line_width = bounds[2] - bounds[0]
            x = (image.width - line_width) / 2 - bounds[0]
            draw.text((x, y - bounds[1]), text, font=font, fill="white", stroke_width=2, stroke_fill=(8, 15, 30))
            y += bounds[3] - bounds[1] + line_gap
        clips.append(
            ImageClip(np.asarray(image), transparent=True)
            .set_start(index * segment_duration)
            .set_duration(len(group) * segment_duration)
            .set_position(("center", int(height * 0.73 - image.height / 2)))
        )
    return clips


def _fit_clip(clip: VideoFileClip, duration: float, width: int, height: int) -> VideoFileClip:
    if clip.w / clip.h < width / height:
        resized_width = width
        resized_height = round(clip.h * width / clip.w)
    else:
        resized_width = round(clip.w * height / clip.h)
        resized_height = height
    clip = clip.fl_image(
        lambda frame: np.asarray(
            Image.fromarray(frame.astype(np.uint8)).resize(
                (resized_width, resized_height),
                resample=Image.Resampling.LANCZOS,
            )
        )
    )
    clip = clip.crop(
        x_center=clip.w / 2,
        y_center=clip.h / 2,
        width=width,
        height=height,
    )
    return clip.fx(video_fx.loop, duration=duration)


def _scene_durations(script: str, duration: float, scene_count: int) -> list[float]:
    word_count = len(script.split())
    if word_count == 0 or duration <= 0 or scene_count <= 0:
        raise RuntimeError("Scene timing requires a non-empty script, positive duration, and scenes.")
    scene_count = min(scene_count, word_count)
    base_words, extra_words = divmod(word_count, scene_count)
    word_counts = [base_words + (index < extra_words) for index in range(scene_count)]
    durations = [duration * count / word_count for count in word_counts]
    durations[-1] = duration - sum(durations[:-1])
    return durations


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


def create_thumbnail(video_path: Path, title: str, output_path: Path) -> None:
    if not title.strip():
        raise RuntimeError("Cannot create a thumbnail for an empty title.")
    clip = VideoFileClip(str(video_path))
    try:
        if clip.duration <= 0:
            raise RuntimeError(f"Cannot create a thumbnail from empty video {video_path}.")
        frame = Image.fromarray(clip.get_frame(min(0.5, clip.duration / 2)).astype(np.uint8))
    finally:
        clip.close()

    image = ImageOps.fit(frame.convert("RGB"), (1080, 1920), method=Image.Resampling.LANCZOS)
    canvas = image.convert("RGBA")
    gradient = Image.new("RGBA", (1080, 1050), (0, 0, 0, 0))
    alpha_values = np.linspace(220, 0, gradient.height, dtype=np.float32)
    alpha_values = np.power(alpha_values / 220, 1.5) * 220
    alpha = Image.fromarray(
        np.tile(alpha_values.astype(np.uint8)[:, np.newaxis], (1, gradient.width))
    )
    gradient.putalpha(alpha)
    canvas.alpha_composite(gradient, (0, 0))
    draw = ImageDraw.Draw(canvas)
    badge_font = _caption_font(38)
    draw.rounded_rectangle((64, 82, 454, 158), radius=30, fill=(67, 211, 255, 255))
    draw.text((88, 98), "FREE AI TOOL  |  QUICK DEMO", font=badge_font, fill=(5, 23, 39, 255))

    clean_title = title.removesuffix(" #Shorts").strip()
    font_size = 100
    title_font = _caption_font(font_size)
    max_width = 950
    lines: list[str] = []
    while True:
        lines = []
        line = ""
        for word in clean_title.split():
            candidate = f"{line} {word}".strip()
            bounds = draw.textbbox((0, 0), candidate, font=title_font, stroke_width=2)
            if line and bounds[2] - bounds[0] > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) <= 4 or font_size <= 68:
            break
        font_size -= 4
        title_font = _caption_font(font_size)

    y = 238
    for line in lines:
        draw.text(
            (68, y),
            line,
            font=title_font,
            fill="white",
            stroke_width=4,
            stroke_fill=(5, 17, 31, 255),
        )
        bounds = draw.textbbox((68, y), line, font=title_font, stroke_width=4)
        y += bounds[3] - bounds[1] + 20
    draw.rounded_rectangle((68, y + 4, 280, y + 20), radius=8, fill=(67, 211, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").resize((2160, 3840), Image.Resampling.LANCZOS).save(
        output_path,
        format="JPEG",
        quality=88,
        optimize=True,
    )


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
        scene_durations = _scene_durations(script, audio_duration, len(footage_paths))
        sequence_parts = []
        for source, scene_duration in zip(footage_paths, scene_durations):
            base = VideoFileClip(str(source))
            opened_video_clips.append(base)
            if base.duration <= 0:
                raise RuntimeError(f"Footage clip {source} has no playable duration.")
            fitted = _fit_clip(base, scene_duration, width, height)
            opened_video_clips.append(fitted)
            sequence_parts.append(fitted)
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
