"""OAuth authentication and YouTube Data API resumable video uploads."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from utils import PROJECT_DIR

LOGGER = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _hashtags(tags: list[str]) -> list[str]:
    result = ["#Shorts"]
    seen = {"shorts"}
    for tag in tags:
        words = re.findall(r"[^\W_]+", tag, flags=re.UNICODE)
        if not words:
            continue
        key = "".join(word.lower() for word in words)
        if key in seen:
            continue
        hashtag = "#" + "".join(
            word.upper() if len(word) <= 2 else word.capitalize() for word in words
        )
        if len(hashtag) > 30:
            continue
        seen.add(key)
        result.append(hashtag)
        if len(result) == 3:
            break
    return result


def _description_with_hashtags(description: str, tags: list[str]) -> str:
    description = description.strip()
    lines = description.splitlines()
    suffix_end = len(lines)
    while suffix_end > 0 and not lines[suffix_end - 1].strip():
        suffix_end -= 1
    suffix_start = suffix_end
    while suffix_start > 0:
        line = lines[suffix_start - 1].strip()
        if not line or all(word.startswith("#") for word in line.split()):
            suffix_start -= 1
        else:
            break
    if suffix_start < suffix_end:
        suffix_tags = list(
            dict.fromkeys(re.findall(r"#[\w]+", "\n".join(lines[suffix_start:suffix_end])))
        )
        if len(suffix_tags) > 3:
            prefix = "\n".join(lines[:suffix_start]).rstrip()
            description = f"{prefix}\n\n{' '.join(suffix_tags[:3])}".strip()
    existing_tags = list(
        dict.fromkeys(tag.lower() for tag in re.findall(r"#[\w]+", description))
    )
    existing = set(existing_tags)
    remaining = max(0, 3 - len(existing_tags))
    if remaining == 0:
        return description
    hashtags = [tag for tag in _hashtags(tags) if tag.lower() not in existing]
    hashtags = hashtags[:remaining]
    if not hashtags:
        return description
    return f"{description}\n\n{' '.join(hashtags)}"


def _configured_path(config_value: str, environment_variable: str) -> Path:
    value = os.getenv(environment_variable, config_value)
    path = Path(value)
    return path if path.is_absolute() else PROJECT_DIR / path


def _save_credentials(credentials: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not save YouTube OAuth token to {token_path}: {exc}") from exc


def _set_thumbnail(
    youtube: Any,
    video_id: str,
    thumbnail_path: Path,
    metadata: dict[str, Any],
) -> None:
    if not thumbnail_path.is_file():
        metadata["thumbnail_status"] = "failed"
        metadata["thumbnail_error"] = f"Thumbnail image not found: {thumbnail_path}"
        LOGGER.warning(metadata["thumbnail_error"])
        return
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(
                str(thumbnail_path),
                mimetype="image/jpeg",
            ),
        ).execute()
        metadata["thumbnail_status"] = "uploaded"
        metadata.pop("thumbnail_error", None)
        LOGGER.info("Set custom thumbnail for video %s.", video_id)
    except HttpError as exc:
        metadata["thumbnail_status"] = "failed"
        metadata["thumbnail_error"] = (
            f"YouTube rejected the custom thumbnail with HTTP "
            f"{exc.resp.status}: {exc.reason}."
        )
        LOGGER.warning("%s", metadata["thumbnail_error"])


def set_video_thumbnail(video_id: str, thumbnail_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    credentials = _credentials(config)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    metadata: dict[str, Any] = {}
    _set_thumbnail(youtube, video_id, thumbnail_path, metadata)
    return metadata


def _credentials(
    config: dict[str, Any],
    required_scopes: list[str] | None = None,
) -> Credentials:
    scopes = required_scopes or SCOPES
    oauth = config.get("oauth_client_secrets", "credentials/client_secret.json")
    token = config.get("token_file", "token.json")
    token_environment = config.get("token_file_env", "YOUTUBE_TOKEN_FILE")
    if not isinstance(token_environment, str) or not token_environment.strip():
        raise RuntimeError("token_file_env must be a non-empty environment variable name.")
    client_path = _configured_path(str(oauth), "YOUTUBE_OAUTH_CLIENT_FILE")
    token_path = _configured_path(str(token), token_environment)
    credentials: Credentials | None = None
    missing_scopes: set[str] = set()
    if token_path.exists():
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
            if not isinstance(token_data, dict):
                raise ValueError("OAuth token must contain a JSON object.")
            stored_scopes = token_data.get("scopes")
            if isinstance(stored_scopes, list):
                missing_scopes = set(scopes) - set(stored_scopes)
            elif ANALYTICS_SCOPE in scopes:
                missing_scopes = set(scopes)
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Could not read YouTube token at {token_path}. Remove the invalid token "
                "and run python main.py once to authenticate again."
            ) from exc
    if credentials and credentials.expired and credentials.refresh_token and not missing_scopes:
        try:
            credentials.refresh(Request())
            _save_credentials(credentials, token_path)
        except (GoogleAuthError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"Could not refresh YouTube OAuth token: {exc}. Reauthorize with python main.py."
            ) from exc
    if credentials and credentials.valid and not missing_scopes:
        return credentials
    interactive = os.getenv("YOUTUBE_INTERACTIVE_LOGIN", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if not interactive:
        if missing_scopes:
            missing = ", ".join(sorted(missing_scopes))
            raise RuntimeError(
                f"The saved YouTube token is missing required OAuth scope(s): {missing}. "
                "Run python analytics.py locally to authorize analytics, then update "
                "YOUTUBE_TOKEN_JSON_B64 in GitHub Actions."
            )
        raise RuntimeError(
            "YouTube token is missing or expired and interactive login is disabled. "
            "Set YOUTUBE_TOKEN_JSON_B64 in GitHub Actions or authenticate locally first."
        )
    if not client_path.is_file():
        raise RuntimeError(
            f"YouTube OAuth client file not found: {client_path}. Download a Desktop app "
            "OAuth client JSON from Google Cloud and save it there; see README.md."
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
        credentials = flow.run_local_server(port=0, prompt="consent")
    except (OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"YouTube OAuth login failed: {exc}") from exc
    _save_credentials(credentials, token_path)
    return credentials


def upload_video(metadata: dict[str, Any], video_path: Path, config: dict[str, Any]) -> str:
    credentials = _credentials(config)
    snippet = {
        "title": (str(metadata["title"]).removesuffix(" #Shorts") + " #Shorts")[:100],
        "description": _description_with_hashtags(
            str(metadata["description"]),
            metadata["tags"],
        ),
        "tags": metadata["tags"],
        "categoryId": str(config.get("category_id", "27")),
    }
    privacy = config.get("privacy_status", "private")
    if privacy not in {"private", "unlisted", "public"}:
        raise RuntimeError("privacy_status must be private, unlisted, or public.")
    body = {
        "snippet": snippet,
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )
    try:
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=3)
        video_id = response.get("id")
        if not isinstance(video_id, str) or not video_id:
            raise RuntimeError("YouTube reported upload success without returning a video ID.")
        LOGGER.info("Uploaded video %s (privacy: %s).", video_id, privacy)
        thumbnail_value = metadata.get("thumbnail_path")
        if thumbnail_value:
            thumbnail_path = Path(str(thumbnail_value))
            if not thumbnail_path.is_absolute():
                thumbnail_path = PROJECT_DIR / thumbnail_path
            _set_thumbnail(youtube, video_id, thumbnail_path, metadata)
        return video_id
    except HttpError as exc:
        raise RuntimeError(
            f"YouTube upload failed with HTTP {exc.resp.status}: {exc.reason}. "
            "Check OAuth permissions, API quota, and YouTube project audit status."
        ) from exc
