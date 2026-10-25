"""Generate a vertical YouTube Short and review or upload it."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from footage import configured_clip_count, download_clips
from script_gen import generate_script, generate_topic
from uploader import upload_video
from utils import PROJECT_DIR, load_config, load_list, read_json, require_api_key, write_json
from video import assemble_video
from voice import available_voices, generate_voice

LOGGER = logging.getLogger("shorts")
DAILY_UPLOAD_LIMIT = 6
HOOK_STYLE_ROTATION = ["myth_vs_fact", "did_you_know", "top_3", "story", "question"]


def _project_path(relative_path: str | Path) -> Path:
    path = Path(relative_path)
    return path if path.is_absolute() else PROJECT_DIR / path


def _state_path(name: str) -> Path:
    return PROJECT_DIR / name


def _setup_logging() -> None:
    log_path = PROJECT_DIR / "runs.log"
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def _daily_uploads() -> int:
    data = read_json(_state_path("quota.json"), {"date": date.today().isoformat(), "uploads": 0})
    if not isinstance(data, dict):
        raise RuntimeError("quota.json must contain an object.")
    if data.get("date") != date.today().isoformat():
        return 0
    uploads = data.get("uploads", 0)
    if not isinstance(uploads, int) or uploads < 0:
        raise RuntimeError("quota.json uploads must be a non-negative integer.")
    return uploads


def ensure_upload_capacity(config: dict[str, Any]) -> None:
    limit = config.get("daily_upload_limit", DAILY_UPLOAD_LIMIT)
    if not isinstance(limit, int) or not 1 <= limit <= DAILY_UPLOAD_LIMIT:
        raise RuntimeError(f"daily_upload_limit must be an integer from 1 to {DAILY_UPLOAD_LIMIT}.")
    count = _daily_uploads()
    if count >= limit:
        raise RuntimeError(
            f"Daily upload limit reached ({count}/{limit}). Try again after the quota date resets."
        )


def record_upload() -> None:
    count = _daily_uploads()
    write_json(
        _state_path("quota.json"),
        {"date": date.today().isoformat(), "uploads": count + 1},
    )


def _append_history(metadata: dict[str, Any]) -> None:
    entries = load_list(_state_path("history.json"), "generation history")
    entries.append(metadata)
    write_json(_state_path("history.json"), entries)


def _choose_voice(config: dict[str, Any]) -> tuple[str, int]:
    voices = available_voices(config)
    voice_state = read_json(_state_path("voice_state.json"), {"index": 0})
    if not isinstance(voice_state, dict) or not isinstance(voice_state.get("index", 0), int):
        raise RuntimeError("voice_state.json must contain an integer index.")
    index = voice_state.get("index", 0) % len(voices)
    return voices[index], index


def _next_hook_style(history: list[Any]) -> str:
    prior_styles = [
        entry.get("hook_style")
        for entry in history
        if isinstance(entry, dict) and entry.get("hook_style") in HOOK_STYLE_ROTATION
    ]
    if not prior_styles:
        return HOOK_STYLE_ROTATION[0]
    next_index = (HOOK_STYLE_ROTATION.index(prior_styles[-1]) + 1) % len(HOOK_STYLE_ROTATION)
    return HOOK_STYLE_ROTATION[next_index]


def run(dry_run: bool) -> Path:
    load_dotenv(PROJECT_DIR / ".env")
    config = load_config()
    pexels_key = require_api_key(config, "pexels")
    if not dry_run and not config.get("review_mode", True):
        ensure_upload_capacity(config)
    topics = load_list(_state_path("topics.json"), "topic history")
    history = load_list(_state_path("history.json"), "generation history")
    if not all(isinstance(topic, str) for topic in topics):
        raise RuntimeError("topics.json must contain only topic strings.")
    topic = generate_topic(config, topics)
    LOGGER.info("Selected new topic: %s", topic)

    script_data = generate_script(topic, config, _next_hook_style(history))
    topics.append(topic)
    write_json(_state_path("topics.json"), topics)
    voice, voice_index = _choose_voice(config)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    if dry_run:
        output_dir = _project_path(config.get("output_folder", "output")) / "dry-run" / run_id
        status = "dry_run"
    elif config.get("review_mode", True):
        output_dir = _project_path(config.get("pending_folder", "pending")) / run_id
        status = "pending_review"
    else:
        ensure_upload_capacity(config)
        output_dir = _project_path(config.get("output_folder", "output")) / run_id
        status = "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "script.json"
    write_json(
        script_path,
        {"topic": topic, **script_data, "voice": voice, "generated_at": datetime.now(timezone.utc).isoformat()},
    )

    voice_path = output_dir / "voice.mp3"
    generate_voice(script_data["script"], voice, config, voice_path)
    used_ids = load_list(_state_path("used_clip_ids.json"), "Pexels clip history")
    clip_count = configured_clip_count(config)
    keywords = script_data["keywords"][:clip_count]
    clips_dir = output_dir / "clips"
    footage_paths, clip_ids = download_clips(keywords, pexels_key, used_ids, clips_dir)
    all_used = set(used_ids)
    all_used.update(clip_ids)
    write_json(_state_path("used_clip_ids.json"), sorted(all_used))
    video_path = output_dir / "final.mp4"
    duration = assemble_video(script_data["script"], voice_path, footage_paths, video_path, config)
    write_json(
        _state_path("voice_state.json"),
        {"index": (voice_index + 1) % len(available_voices(config))},
    )
    metadata = {
        "id": run_id,
        "topic": topic,
        "title": script_data["title"],
        "description": script_data["description"],
        "tags": script_data["tags"],
        "script": script_data["script"],
        "keywords": keywords,
        "hook_style": script_data["hook_style"],
        "voice": voice,
        "clip_ids": clip_ids,
        "video_path": str(video_path.relative_to(PROJECT_DIR)),
        "duration_seconds": round(duration, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    write_json(output_dir / "metadata.json", metadata)
    _append_history(metadata)
    if dry_run:
        LOGGER.info("Dry run complete; video saved to %s and was not uploaded.", video_path)
    elif status == "pending_review":
        LOGGER.info(
            "Review required: script and video saved to %s. Approve with: python approve.py %s",
            output_dir,
            run_id,
        )
    else:
        ensure_upload_capacity(config)
        youtube_id = upload_video(metadata, video_path, config)
        metadata["status"] = "uploaded"
        metadata["youtube_video_id"] = youtube_id
        write_json(output_dir / "metadata.json", metadata)
        entries = load_list(_state_path("history.json"), "generation history")
        entries[-1] = metadata
        write_json(_state_path("history.json"), entries)
        record_upload()
        LOGGER.info("Uploaded Short: https://www.youtube.com/shorts/%s", youtube_id)
    return video_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the script and video but never upload it.",
    )
    args = parser.parse_args()
    _setup_logging()
    try:
        run(args.dry_run)
    except Exception as exc:
        LOGGER.exception("Short generation failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
