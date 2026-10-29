"""Fetch recent YouTube performance data to guide the next Short topic."""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from typing import Any

from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from uploader import ANALYTICS_SCOPE, SCOPES, _credentials
from utils import PROJECT_DIR, load_config, load_list

LOGGER = logging.getLogger("shorts")
ANALYTICS_SCOPES = [*SCOPES, ANALYTICS_SCOPE]
LOOKBACK_DAYS = 28
REPORT_DELAY_DAYS = 2
MAX_INSIGHTS = 3


def fetch_performance_insights(
    history: list[Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    uploaded = {
        entry["youtube_video_id"]: entry
        for entry in history
        if isinstance(entry, dict)
        and entry.get("status") == "uploaded"
        and isinstance(entry.get("youtube_video_id"), str)
        and entry["youtube_video_id"]
    }
    if not uploaded:
        return []

    end_date = date.today() - timedelta(days=REPORT_DELAY_DAYS)
    start_date = end_date - timedelta(days=LOOKBACK_DAYS - 1)
    try:
        credentials = _credentials(config, ANALYTICS_SCOPES)
        service = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
        report = (
            service.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date.isoformat(),
                endDate=end_date.isoformat(),
                metrics="views,averageViewDuration,averageViewPercentage",
                dimensions="video",
                sort="-averageViewPercentage",
                maxResults=200,
            )
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(
            f"YouTube Analytics API request failed with HTTP {exc.resp.status}: "
            f"{exc.reason}. Enable the YouTube Analytics API and authorize its read-only scope."
        ) from exc
    except GoogleAuthError as exc:
        raise RuntimeError(f"YouTube Analytics authorization failed: {exc}") from exc

    headers = [
        column.get("name")
        for column in report.get("columnHeaders", [])
        if isinstance(column, dict)
    ]
    required = ["video", "views", "averageViewDuration", "averageViewPercentage"]
    if not all(name in headers for name in required):
        raise RuntimeError(
            f"YouTube Analytics returned unexpected columns: {headers!r}."
        )
    indexes = {name: headers.index(name) for name in required}
    insights: list[dict[str, Any]] = []
    for row in report.get("rows", []):
        if not isinstance(row, list) or len(row) < len(headers):
            raise RuntimeError("YouTube Analytics returned a malformed video row.")
        video_id = row[indexes["video"]]
        metadata = uploaded.get(video_id)
        if metadata is None:
            continue
        try:
            insight = {
                "topic": str(metadata.get("topic", "")),
                "title": str(metadata.get("title", "")),
                "views": int(row[indexes["views"]]),
                "average_view_duration_seconds": round(
                    float(row[indexes["averageViewDuration"]]), 1
                ),
                "average_view_percentage": round(
                    float(row[indexes["averageViewPercentage"]]), 1
                ),
            }
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"YouTube Analytics returned invalid metrics for video {video_id!r}."
            ) from exc
        insights.append(insight)
    insights.sort(
        key=lambda item: (
            item["average_view_percentage"],
            item["views"],
        ),
        reverse=True,
    )
    LOGGER.info(
        "Fetched performance data for %s uploaded Shorts (%s through %s).",
        len(insights),
        start_date.isoformat(),
        end_date.isoformat(),
    )
    return insights[:MAX_INSIGHTS]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        insights = fetch_performance_insights(
            load_list(PROJECT_DIR / "history.json", "generation history"),
            load_config(),
        )
    except RuntimeError as exc:
        LOGGER.error("Could not fetch YouTube analytics: %s", exc)
        return 1
    if not insights:
        print("No recent analytics are available for this channel's uploaded Shorts yet.")
        return 0
    for rank, insight in enumerate(insights, start=1):
        print(
            f"{rank}. {insight['title']} — {insight['views']} views, "
            f"{insight['average_view_percentage']}% average viewed "
            f"({insight['average_view_duration_seconds']}s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
