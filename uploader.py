"""OAuth authentication and YouTube Data API resumable video uploads."""

from __future__ import annotations

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
    existing = {tag.lower() for tag in re.findall(r"#[\w]+", description)}
    hashtags = [tag for tag in _hashtags(tags) if tag.lower() not in existing]
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


def _credentials(config: dict[str, Any]) -> Credentials:
    oauth = config.get("oauth_client_secrets", "credentials/client_secret.json")
    token = config.get("token_file", "token.json")
    client_path = _configured_path(str(oauth), "YOUTUBE_OAUTH_CLIENT_FILE")
    token_path = _configured_path(str(token), "YOUTUBE_TOKEN_FILE")
    credentials: Credentials | None = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Could not read YouTube token at {token_path}. Remove the invalid token "
                "and run python main.py once to authenticate again."
            ) from exc
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            _save_credentials(credentials, token_path)
        except (GoogleAuthError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"Could not refresh YouTube OAuth token: {exc}. Reauthorize with python main.py."
            ) from exc
    if credentials and credentials.valid:
        return credentials
    interactive = os.getenv("YOUTUBE_INTERACTIVE_LOGIN", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if not interactive:
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
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
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
        return video_id
    except HttpError as exc:
        raise RuntimeError(
            f"YouTube upload failed with HTTP {exc.resp.status}: {exc.reason}. "
            "Check OAuth permissions, API quota, and YouTube project audit status."
        ) from exc
