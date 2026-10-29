"""Topic and original short-form script generation using Gemini REST."""

from __future__ import annotations

import json
from typing import Any

from utils import normalized_topic, request_with_retry, require_api_key

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
HOOK_STYLES = {"myth_vs_fact", "did_you_know", "top_3", "story", "question"}


def _generate_json(prompt: str, config: dict[str, Any], api_key: str) -> Any:
    gemini_config = config.get("gemini", {})
    model = gemini_config.get("model")
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("Set gemini.model in config.yaml to a supported Gemini model.")
    response = request_with_retry(
        "Gemini",
        "POST",
        GEMINI_URL.format(model=model.strip()),
        headers={"x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
        },
    )
    try:
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Gemini returned an invalid response instead of the required JSON. "
            "Check the configured model and try again."
        ) from exc


def generate_topic(
    config: dict[str, Any],
    previous_topics: list[str],
    performance_insights: list[dict[str, Any]] | None = None,
) -> str:
    api_key = require_api_key(config, "gemini")
    niche = str(config.get("niche", "")).strip()
    if not niche:
        raise RuntimeError("Set a non-empty niche in config.yaml.")
    previous_set = {normalized_topic(topic) for topic in previous_topics}
    history = json.dumps(previous_topics, ensure_ascii=False)
    insights = performance_insights or []
    performance_guidance = ""
    if insights:
        examples = [
            {
                key: insight[key]
                for key in ("title", "topic")
                if isinstance(insight.get(key), str) and insight[key]
            }
            for insight in insights
        ]
        performance_guidance = (
            "These recent public video topics were the strongest performers in the "
            "channel's analytics (use them only to infer useful formats; do not copy "
            "their topics): "
            f"{json.dumps(examples, ensure_ascii=False)}. Prefer a fresh tool or demo "
            "with similar practical qualities. "
        )
    for _ in range(3):
        result = _generate_json(
            "Choose one specific, practical topic for a 20-25 second beginner YouTube Short "
            f"in this niche: {niche!r}. Strongly prefer a named AI tool or open-source model "
            "that viewers can try in a web browser using a genuinely available free demo or "
            "free tier. Focus on one useful result a beginner can get quickly and that can "
            "be illustrated with specific footage. Avoid vague AI news, broad tool lists, "
            "unsupported 'free/unlimited' claims, and tools whose free access is unclear. "
            "Do not repeat or closely rephrase any prior topic. "
            f"{performance_guidance}"
            f"Prior topics (avoid all): {history}. Return only JSON {{\"topic\":\"...\"}}.",
            config,
            api_key,
        )
        topic = result.get("topic") if isinstance(result, dict) else None
        if isinstance(topic, str) and topic.strip():
            topic = topic.strip()
            if normalized_topic(topic) not in previous_set:
                return topic
    raise RuntimeError(
        "Gemini failed to suggest a new topic after three attempts. "
        "Check topics.json and try again."
    )


def generate_script(
    topic: str,
    config: dict[str, Any],
    preferred_hook_style: str,
) -> dict[str, Any]:
    api_key = require_api_key(config, "gemini")
    if preferred_hook_style not in HOOK_STYLES:
        raise RuntimeError(f"Unsupported preferred hook style: {preferred_hook_style!r}.")
    prompt = (
        "Write an original, factual YouTube Short script about this topic: "
        f"{topic!r}. Niche: {config.get('niche', '')!r}. Return only a JSON object with "
        "exactly these fields: title (string), description (string), tags (array of 3-8 "
        "strings), script (string), keywords (array of exactly 4 concise visual search "
        "phrases in chronological narration order), hook_style (one of myth_vs_fact, "
        "did_you_know, top_3, story, question). Each keyword must describe a distinct, "
        "specific visual for its corresponding consecutive quarter of the script. Use "
        "concrete subjects and actions from the narration; avoid generic browser, laptop, "
        "or typing footage unless that is what the current scene actually describes. "
        "Make the title concise, accurate, compelling, and naturally include the tool or "
        "topic's main search phrase near the beginning; do not use misleading clickbait. "
        "Write a natural 1-2 sentence description that explains the exact beginner "
        "takeaway and includes the main search phrase once. Provide 5-8 specific, relevant "
        "YouTube search tags including the tool/topic name, beginner intent, and closely "
        "related terms; do not include hashtag symbols in tags. Avoid keyword stuffing. "
        f"The required hook_style value is exactly {preferred_hook_style!r}; set it to "
        "that exact value, not another style. Prioritize an immediate result-first opening "
        "over a slow setup or abstract question. The first spoken sentence must state or "
        "show the specific outcome. Script must be 45-60 spoken words and take about "
        "20-25 seconds. For tool tutorials, name the exact tool, give at most 2-3 concise "
        "steps in the order a beginner would follow, and end with the visible result. "
        "Keep only information needed to achieve that one result; cut greetings, repeated "
        "claims, long setup, generic filler, unsupported pricing/feature claims, and calls "
        "to subscribe. "
        "Make it sound natural when spoken aloud. Do not include stage directions."
    )
    for attempt in range(3):
        result = _generate_json(prompt, config, api_key)
        if not isinstance(result, dict):
            break
        corrections = []
        script = result.get("script")
        if isinstance(script, str):
            word_count = len(script.split())
            if not 45 <= word_count <= 60:
                corrections.append(
                    f"the script had {word_count} words, but must have 45-60"
                )
        hook_style = result.get("hook_style")
        if isinstance(hook_style, str) and hook_style in HOOK_STYLES:
            if hook_style != preferred_hook_style:
                corrections.append(
                    f"hook_style was {hook_style!r}, but must be {preferred_hook_style!r}"
                )
        if not corrections or attempt == 2:
            break
        prompt += (
            "\nCorrection: The previous draft did not meet these requirements: "
            + "; ".join(corrections)
            + ". Rewrite it to satisfy them exactly."
        )
    if not isinstance(result, dict):
        raise RuntimeError("Gemini returned a script that is not a JSON object.")
    required = {"title", "description", "tags", "script", "keywords", "hook_style"}
    if not required.issubset(result):
        raise RuntimeError(f"Gemini script JSON is missing fields: {sorted(required - set(result))}.")
    if not all(
        isinstance(result[key], str) and result[key].strip()
        for key in ("title", "description", "script")
    ):
        raise RuntimeError("Gemini script title, description, and script must be non-empty strings.")
    if (
        not isinstance(result["tags"], list)
        or not 3 <= len(result["tags"]) <= 8
        or not all(isinstance(tag, str) and tag.strip() for tag in result["tags"])
    ):
        raise RuntimeError("Gemini script tags must contain 3-8 non-empty strings.")
    if not isinstance(result["keywords"], list) or len(result["keywords"]) != 4 or not all(
        isinstance(keyword, str) and keyword.strip() for keyword in result["keywords"]
    ):
        raise RuntimeError("Gemini script keywords must contain exactly four non-empty strings.")
    if result["hook_style"] not in HOOK_STYLES:
        raise RuntimeError(f"Gemini returned an unsupported hook_style: {result['hook_style']!r}.")
    if result["hook_style"] != preferred_hook_style:
        raise RuntimeError(
            f"Gemini returned hook_style {result['hook_style']!r}, but "
            f"{preferred_hook_style!r} was requested."
        )
    if len(result["tags"]) > 8 or sum(len(tag) for tag in result["tags"]) > 500:
        raise RuntimeError("Gemini script tags must fit YouTube's eight-tag, 500-character limit.")
    word_count = len(result["script"].split())
    if not 45 <= word_count <= 60:
        raise RuntimeError(
            f"Gemini script has {word_count} words; expected 45-60 for a 20-25 second Short. "
            "Regenerate the script."
        )
    return result
