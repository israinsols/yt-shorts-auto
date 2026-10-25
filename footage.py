"""Search, download, and de-duplicate portrait footage from Pexels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils import request_with_retry

SEARCH_URL = "https://api.pexels.com/videos/search"
FALLBACK_QUERIES = (
    "coding laptop programming",
    "person typing on laptop",
    "computer technology workspace",
)


def _portrait_file(video: dict[str, Any]) -> str | None:
    files = video.get("video_files")
    if not isinstance(files, list):
        return None
    portrait_files = [
        item
        for item in files
        if isinstance(item, dict)
        and isinstance(item.get("link"), str)
        and item.get("width", 0) > 0
        and item.get("height", 0) > item.get("width", 0)
    ]
    if not portrait_files:
        return None
    portrait_files.sort(
        key=lambda item: (item.get("width", 0) * item.get("height", 0), item.get("quality") == "hd"),
        reverse=True,
    )
    return portrait_files[0]["link"]


def _find_video(keyword: str, api_key: str, excluded_ids: set[int]) -> tuple[int, str]:
    queries = list(dict.fromkeys((keyword, *FALLBACK_QUERIES)))
    for query in queries:
        for page in range(1, 4):
            response = request_with_retry(
                "Pexels",
                "GET",
                SEARCH_URL,
                headers={"Authorization": api_key},
                params={"query": query, "orientation": "portrait", "per_page": 15, "page": page},
            )
            try:
                videos = response.json().get("videos", [])
            except (ValueError, AttributeError) as exc:
                raise RuntimeError("Pexels returned an invalid video-search response.") from exc
            if not videos:
                break
            for video in videos:
                if not isinstance(video, dict):
                    continue
                video_id = video.get("id")
                link = _portrait_file(video)
                if isinstance(video_id, int) and video_id not in excluded_ids and link:
                    return video_id, link
    raise RuntimeError(
        f"Pexels had no unused portrait footage for keyword {keyword!r} or its fallback searches. "
        "Try again later or review used_clip_ids.json."
    )


def download_clips(
    keywords: list[str],
    api_key: str,
    used_ids: list[int],
    output_dir: Path,
) -> tuple[list[Path], list[int]]:
    if not all(isinstance(video_id, int) and video_id > 0 for video_id in used_ids):
        raise RuntimeError("used_clip_ids.json must contain only positive integer Pexels video IDs.")
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded = set(used_ids)
    paths: list[Path] = []
    selected_ids: list[int] = []
    for index, keyword in enumerate(keywords):
        video_id, link = _find_video(keyword, api_key, excluded)
        response = request_with_retry("Pexels video download", "GET", link, stream=True, timeout=120)
        path = output_dir / f"pexels-{video_id}.mp4"
        try:
            with path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        except OSError as exc:
            response.close()
            raise RuntimeError(f"Could not save Pexels footage {video_id} to {path}: {exc}") from exc
        finally:
            response.close()
        if path.stat().st_size == 0:
            raise RuntimeError(f"Pexels returned an empty video download for clip {video_id}.")
        excluded.add(video_id)
        paths.append(path)
        selected_ids.append(video_id)
    return paths, selected_ids


def configured_clip_count(config: dict[str, Any]) -> int:
    count = config.get("pexels", {}).get("clip_count", 4)
    if not isinstance(count, int) or not 1 <= count <= 4:
        raise RuntimeError("pexels.clip_count must be an integer from 1 to 4.")
    return count
