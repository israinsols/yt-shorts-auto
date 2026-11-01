"""Generate original portrait endless-runner footage without third-party game assets."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from moviepy.config import get_setting
from PIL import Image, ImageDraw

WIDTH = 432
HEIGHT = 768
FPS = 24
HORIZON = 245


def _draw_frame(frame_number: int, fps: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (18, 30, 45))
    draw = ImageDraw.Draw(image)
    for band in range(36):
        y0 = band * HORIZON // 36
        y1 = (band + 1) * HORIZON // 36
        color = (18 + band, 69 + band * 2, 102 + band * 2)
        draw.rectangle((0, y0, WIDTH, y1), fill=color)
    draw.polygon(
        ((0, 226), (74, 164), (132, 218), (205, 178), (287, 223), (351, 160), (432, 218), (432, 270), (0, 270)),
        fill=(38, 95, 78),
    )
    draw.polygon(
        ((0, 236), (68, 196), (140, 238), (232, 190), (323, 236), (391, 196), (432, 221), (432, 275), (0, 275)),
        fill=(46, 111, 77),
    )
    draw.rectangle((0, HORIZON, WIDTH, HEIGHT), fill=(24, 75, 52))

    seconds = frame_number / fps
    motion = (seconds * 0.7) % 1
    gate_shade = (108, 99, 78)
    draw.rectangle((177, 194, 193, 276), fill=(119, 108, 83))
    draw.rectangle((239, 194, 255, 276), fill=(91, 83, 68))
    draw.rectangle((168, 181, 264, 201), fill=(145, 127, 91))
    draw.rectangle((176, 171, 256, 184), fill=gate_shade)
    draw.rectangle((184, 203, 190, 273), fill=(164, 143, 101))
    draw.rectangle((244, 203, 250, 273), fill=(126, 111, 84))
    road_left = (178, HORIZON)
    road_right = (254, HORIZON)
    road_points = [road_left, road_right, (WIDTH + 35, HEIGHT), (-35, HEIGHT)]
    draw.polygon(road_points, fill=(126, 91, 62))
    draw.line((road_left, (-35, HEIGHT)), fill=(208, 171, 108), width=5)
    draw.line((road_right, (WIDTH + 35, HEIGHT)), fill=(208, 171, 108), width=5)

    for side in (-1, 1):
        for index in range(5):
            depth = (index / 5 + motion) % 1
            y = int(HORIZON + depth * depth * (HEIGHT - HORIZON))
            scale = 0.2 + depth * 0.8
            center_x = int(WIDTH / 2 + side * (62 + depth * 175))
            trunk_width = max(3, int(8 * scale))
            trunk_height = max(8, int(48 * scale))
            draw.rectangle(
                (center_x - trunk_width // 2, y - trunk_height, center_x + trunk_width // 2, y),
                fill=(86, 59, 39),
            )
            canopy = max(8, int(24 * scale))
            draw.ellipse(
                (center_x - canopy, y - trunk_height - canopy, center_x + canopy, y - trunk_height + canopy),
                fill=(35, 111 + index * 3, 64),
            )
            leaf_shade = (46, 132 + index * 2, 72)
            draw.ellipse(
                (center_x - canopy // 2, y - trunk_height - canopy * 2, center_x + canopy * 1.4, y - trunk_height),
                fill=leaf_shade,
            )

    def road_x(y: float, lane: float) -> int:
        progress = max(0.0, min(1.0, (y - HORIZON) / (HEIGHT - HORIZON)))
        half_width = 38 + progress * 175
        return int(WIDTH / 2 + lane * half_width)

    for lane in (-1 / 3, 1 / 3):
        draw.line(
            (road_x(HORIZON, lane), HORIZON, road_x(HEIGHT, lane), HEIGHT),
            fill=(208, 171, 108),
            width=2,
        )

    for index in range(1, 10):
        depth = (index / 9 + motion) % 1
        y = int(HORIZON + depth * depth * (HEIGHT - HORIZON))
        half_width = 38 + depth * 175
        tile_color = (151, 111, 75) if index % 2 else (139, 101, 69)
        draw.line((WIDTH / 2 - half_width, y, WIDTH / 2 + half_width, y), fill=tile_color, width=max(1, int(1 + depth * 5)))

    for index in range(8):
        depth = ((index / 8 + motion * 0.65) % 1)
        y = int(HORIZON + depth * depth * (HEIGHT - HORIZON))
        lane = (-1 / 3, 0, 1 / 3)[index % 3]
        x = road_x(y, lane)
        radius = max(3, int(3 + depth * 9))
        draw.ellipse(
            (x - radius, y - radius * 2, x + radius, y + radius * 2),
            fill=(255, 195, 53),
            outline=(255, 230, 142),
            width=max(1, radius // 4),
        )

    for index in range(3):
        depth = ((index / 3 + motion * 0.45) % 1)
        y = int(HORIZON + depth * depth * (HEIGHT - HORIZON))
        lane = (-1 / 3, 0, 1 / 3)[(index + 1) % 3]
        x = road_x(y, lane)
        obstacle_width = max(5, int(8 + depth * 20))
        obstacle_height = max(3, int(3 + depth * 8))
        draw.rounded_rectangle(
            (
                x - obstacle_width,
                y - obstacle_height,
                x + obstacle_width,
                y + obstacle_height,
            ),
            radius=max(1, obstacle_height // 3),
            fill=(174, 84, 48),
            outline=(224, 145, 75),
            width=max(1, obstacle_height // 4),
        )

    runner_y = 465
    stride = math.sin(seconds * 11)
    runner_x = WIDTH // 2 + int(math.sin(seconds * 1.7) * 9)
    draw.ellipse((runner_x - 37, 582, runner_x + 37, 599), fill=(28, 43, 35))
    draw.ellipse((runner_x - 13, runner_y - 67, runner_x + 13, runner_y - 41), fill=(48, 39, 34))
    draw.arc((runner_x - 15, runner_y - 71, runner_x + 15, runner_y - 43), 180, 355, fill=(231, 184, 114), width=4)
    draw.polygon(
        (
            (runner_x - 18, runner_y - 39),
            (runner_x + 18, runner_y - 39),
            (runner_x + 23, runner_y + 12),
            (runner_x - 23, runner_y + 12),
        ),
        fill=(235, 133, 57),
    )
    draw.line(
        (runner_x - 15, runner_y - 27, runner_x + 15, runner_y - 27),
        fill=(248, 197, 107),
        width=4,
    )
    draw.line(
        (runner_x - 12, runner_y - 27, runner_x - 34, runner_y - 2 + int(stride * 9)),
        fill=(48, 39, 34),
        width=9,
    )
    draw.line(
        (runner_x + 12, runner_y - 27, runner_x + 34, runner_y - 2 - int(stride * 9)),
        fill=(48, 39, 34),
        width=9,
    )
    draw.line(
        (runner_x - 9, runner_y + 9, runner_x - 19 + int(stride * 12), runner_y + 56),
        fill=(39, 49, 59),
        width=11,
    )
    draw.line(
        (runner_x + 9, runner_y + 9, runner_x + 19 - int(stride * 12), runner_y + 56),
        fill=(39, 49, 59),
        width=11,
    )
    draw.line(
        (runner_x - 19 + int(stride * 12), runner_y + 56, runner_x - 7 + int(stride * 12), runner_y + 59),
        fill=(225, 214, 188),
        width=7,
    )
    draw.line(
        (runner_x + 19 - int(stride * 12), runner_y + 56, runner_x + 31 - int(stride * 12), runner_y + 59),
        fill=(225, 214, 188),
        width=7,
    )
    return image


def generate_original_runner_clip(
    output_path: Path,
    duration_seconds: float = 12,
    fps: int = FPS,
) -> Path:
    if duration_seconds <= 0 or fps <= 0:
        raise RuntimeError("Runner footage duration and frame rate must be positive.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        get_setting("FFMPEG_BINARY"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if process.stdin is None:
            raise RuntimeError("Could not open FFmpeg input for runner footage.")
        frame_count = math.ceil(duration_seconds * fps)
        for frame_number in range(frame_count):
            process.stdin.write(_draw_frame(frame_number, fps).tobytes())
        process.stdin.close()
        process.stdin = None
        _, error_output = process.communicate(timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            if process.poll() is None:
                process.kill()
            _, error_output = process.communicate()
        else:
            error_output = b""
        output_path.unlink(missing_ok=True)
        detail = error_output.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Could not generate original runner gameplay: {detail or exc}"
        ) from exc
    if process.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        detail = error_output.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"FFmpeg failed to generate original runner gameplay: {detail or 'empty output'}"
        )
    return output_path
