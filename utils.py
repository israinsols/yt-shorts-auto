"""Shared configuration, persistence, and HTTP retry helpers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
import yaml

PROJECT_DIR = Path(__file__).resolve().parent


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else Path("config.yaml")
    if not path.is_absolute():
        path = PROJECT_DIR / path
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except OSError as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping.")
    return config


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read valid JSON from {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not save {path}: {exc}") from exc


def request_with_retry(
    service: str,
    method: str,
    url: str,
    *,
    retries: int = 3,
    timeout: int = 45,
    **kwargs: Any,
) -> requests.Response:
    retry_statuses = {429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            if attempt == retries:
                raise RuntimeError(
                    f"{service} network request failed after {retries + 1} attempts "
                    f"({type(exc).__name__}: {exc})."
                ) from exc
        else:
            if response.status_code not in retry_statuses:
                if not response.ok:
                    raise RuntimeError(
                        f"{service} returned HTTP {response.status_code} "
                        f"({response.reason}). Check the API key, quota, and request settings."
                    )
                return response
            if attempt == retries:
                raise RuntimeError(
                    f"{service} returned retryable HTTP {response.status_code} "
                    f"after {retries + 1} attempts."
                )
            response.close()
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"{service} request failed unexpectedly.")


def require_api_key(config: dict[str, Any], section: str) -> str:
    section_config = config.get(section)
    if not isinstance(section_config, dict):
        raise RuntimeError(f"Missing the {section} section in config.yaml.")
    env_name = section_config.get("api_key_env")
    if not isinstance(env_name, str) or not env_name:
        raise RuntimeError(f"Set {section}.api_key_env in config.yaml.")
    value = os.getenv(env_name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing {env_name}. Copy .env.example to .env and set this key; "
            "see README.md for where to get it."
        )
    return value


def normalized_topic(topic: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in topic).split())


def load_list(path: Path, label: str) -> list[Any]:
    value = read_json(path, [])
    if not isinstance(value, list):
        raise RuntimeError(f"{path} must contain a JSON array ({label}).")
    return value
