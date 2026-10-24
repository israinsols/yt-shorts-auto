"""Upload a generated review item after explicit human approval."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

from main import _project_path, _setup_logging, ensure_upload_capacity, record_upload
from uploader import upload_video
from utils import PROJECT_DIR, load_config, load_list, read_json, write_json

LOGGER = logging.getLogger("shorts")


def approve(run_id: str) -> str:
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise RuntimeError("Invalid review id. Pass the id printed after video generation.")
    load_dotenv(PROJECT_DIR / ".env")
    config = load_config()
    pending_dir = _project_path(config.get("pending_folder", "pending")) / run_id
    metadata_path = pending_dir / "metadata.json"
    metadata = read_json(metadata_path, None)
    if not isinstance(metadata, dict) or metadata.get("id") != run_id:
        raise RuntimeError(f"No pending review item with id {run_id!r} was found.")
    if metadata.get("status") != "pending_review":
        raise RuntimeError(
            f"Review item {run_id!r} is not awaiting approval (status: {metadata.get('status')!r})."
        )
    video_path = _project_path(metadata.get("video_path", ""))
    try:
        video_path.resolve().relative_to(pending_dir.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Review video path must stay inside {pending_dir}.") from exc
    if not video_path.is_file():
        raise RuntimeError(f"Review video is missing: {video_path}.")
    history = load_list(PROJECT_DIR / "history.json", "generation history")
    matching = [
        index
        for index, entry in enumerate(history)
        if isinstance(entry, dict) and entry.get("id") == run_id
    ]
    if len(matching) != 1:
        raise RuntimeError(
            f"Expected exactly one matching history entry for {run_id!r}; found {len(matching)}."
        )
    ensure_upload_capacity(config)
    video_id = upload_video(metadata, video_path, config)
    metadata["status"] = "uploaded"
    metadata["youtube_video_id"] = video_id
    write_json(metadata_path, metadata)
    history[matching[0]] = metadata
    write_json(PROJECT_DIR / "history.json", history)
    record_upload()
    LOGGER.info("Approved and uploaded Short: https://www.youtube.com/shorts/%s", video_id)
    return video_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id", help="Review id printed by main.py")
    args = parser.parse_args()
    _setup_logging()
    try:
        approve(args.id)
    except Exception as exc:
        LOGGER.exception("Approval failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
