"""Authorize and verify the YouTube channel selected for a channel profile."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from uploader import SCOPES, _configured_path, _credentials, _save_credentials
from utils import PROJECT_DIR, load_config

LOGGER = logging.getLogger("shorts")
CHANNEL_IDENTITY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def authorize(config_path: str | Path) -> tuple[str, str]:
    load_dotenv(PROJECT_DIR / ".env")
    config = load_config(config_path)
    expected_name = config.get("expected_channel_name")
    if not isinstance(expected_name, str) or not expected_name.strip():
        raise RuntimeError(
            "Set expected_channel_name in this channel profile before authorizing."
        )
    credentials = _credentials(config, [*SCOPES, CHANNEL_IDENTITY_SCOPE], persist=False)
    try:
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = youtube.channels().list(part="snippet", mine=True).execute()
    except HttpError as exc:
        raise RuntimeError(
            f"Could not verify the authorized YouTube channel (HTTP {exc.resp.status}): "
            f"{exc.reason}."
        ) from exc
    except GoogleAuthError as exc:
        raise RuntimeError(f"YouTube channel authorization failed: {exc}") from exc

    channels = response.get("items", [])
    if not isinstance(channels, list) or not channels:
        raise RuntimeError(
            "The authorized Google account has no accessible YouTube channel."
        )
    channel = channels[0]
    channel_id = channel.get("id")
    snippet = channel.get("snippet", {})
    channel_name = snippet.get("title") if isinstance(snippet, dict) else None
    if not isinstance(channel_id, str) or not isinstance(channel_name, str):
        raise RuntimeError("YouTube returned incomplete channel identity information.")
    expected_channel_id = config.get("expected_channel_id")
    if isinstance(expected_channel_id, str) and expected_channel_id.strip():
        if channel_id != expected_channel_id.strip():
            raise RuntimeError(
                f"Authorized channel ID is {channel_id!r}, but this profile expects "
                f"{expected_channel_id.strip()!r}. Reauthorize using the Google "
                "account/channel for the intended channel; the existing channel's "
                "token was not modified."
            )
    if channel_name.casefold() != expected_name.strip().casefold():
        raise RuntimeError(
            f"Authorized channel is {channel_name!r}, but this profile expects "
            f"{expected_name!r}. Reauthorize using the Google account/channel for "
            "the intended new channel; the existing channel's token was not modified."
        )
    token_file = config.get("token_file", "token.json")
    token_file_env = config.get("token_file_env", "YOUTUBE_TOKEN_FILE")
    if not isinstance(token_file_env, str) or not token_file_env.strip():
        raise RuntimeError("token_file_env must be a non-empty environment variable name.")
    _save_credentials(credentials, _configured_path(str(token_file), token_file_env))
    return channel_name, channel_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config_zaiqa.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        channel_name, channel_id = authorize(args.config)
    except Exception as exc:
        LOGGER.error("Channel authorization failed: %s", exc)
        return 1
    print(f"Authorized channel: {channel_name} (ID: {channel_id})")
    print(f"Token saved to the channel-specific path configured in {args.config}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
