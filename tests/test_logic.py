import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from moviepy.editor import ColorClip
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analytics
import authorize_channel
import main
import footage
import script_gen
import uploader
import voice
import video
import runner_gameplay
from utils import PROJECT_DIR, load_config, normalized_topic, read_json, write_json
from video import _caption_clips, _fit_clip, _scene_durations, create_thumbnail
from voice import _tempo_adjustment


class TopicAndFormatTests(unittest.TestCase):
    def test_topic_normalization_ignores_case_and_punctuation(self):
        self.assertEqual(normalized_topic("  Why?!  Bees—Dance "), "why bees dance")

    def test_topic_generation_retries_duplicate_topics(self):
        config = {"niche": "science", "gemini": {"model": "test"}}
        with (
            patch.object(script_gen, "require_api_key", return_value="test-key"),
            patch.object(script_gen, "_generate_json", side_effect=[
                {"topic": "Known Topic!"},
                {"topic": "A different discovery"},
            ]) as generate_json,
        ):
            topic = script_gen.generate_topic(config, ["Known Topic"])
        self.assertEqual(topic, "A different discovery")
        prompt = generate_json.call_args.args[0]
        self.assertIn("phone and PC tricks", prompt)
        self.assertIn("must not dominate every topic", prompt)

    def test_topic_generation_uses_performance_insights(self):
        response = {"topic": "A fresh browser AI demo"}
        insight = {
            "title": "Run Any AI Model in Your Browser",
            "views": 321,
            "average_view_percentage": 45.6,
        }
        with (
            patch.object(script_gen, "require_api_key", return_value="test-key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            topic = script_gen.generate_topic(
                {"niche": "AI tools", "gemini": {"model": "test"}},
                [],
                [insight],
            )
        self.assertEqual(topic, "A fresh browser AI demo")
        prompt = generate_json.call_args.args[0]
        self.assertIn("Run Any AI Model in Your Browser", prompt)
        self.assertNotIn("45.6", prompt)
        self.assertIn("do not copy", prompt)

    def test_food_profile_generates_roman_urdu_food_topics(self):
        response = {"topic": "Peshawar ke chapli kebab ki kahani"}
        config = {
            "niche": "Pakistan regional food stories",
            "content_language": "Roman Urdu",
            "gemini": {"model": "test"},
        }
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            topic = script_gen.generate_topic(config, [])
        self.assertEqual(topic, response["topic"])
        prompt = generate_json.call_args.args[0]
        self.assertIn("region-specific food", prompt)
        self.assertIn("Roman Urdu", prompt)
        self.assertNotIn("phone and PC tricks", prompt)

    def test_comedy_profile_generates_roman_urdu_sketch_prompts(self):
        config = {
            "niche": "Pakistani everyday comedy",
            "content_language": "Roman Urdu",
            "content_style": "comedy",
            "pexels": {"footage_style": "gameplay"},
            "gemini": {"model": "test"},
        }
        response = {"topic": "Ammi aur mehmaan aane se pehle ki safai"}
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            topic = script_gen.generate_topic(config, [])
        self.assertEqual(topic, response["topic"])
        self.assertIn("narrated comedy story", generate_json.call_args.args[0])
        self.assertIn("endless-runner game footage", generate_json.call_args.args[0])

        script = " ".join(["aaj ghar mein funny scene hua"] * 9)
        narration = " ".join(["آج گھر میں مزاحیہ بات ہوئی۔"] * 9)
        response = {
            "title": "Ammi Aur Mehmaan Ki Funny Safai",
            "description": "Mehmaan aane se pehle ghar ki funny safai.",
            "tags": ["desi comedy", "Pakistani funny", "family humor"],
            "script": script,
            "narration_script": narration,
            "keywords": [
                "mobile racing gameplay",
                "parkour jumping gameplay",
                "obstacle course gameplay",
                "arcade game gameplay",
            ],
            "hook_style": "myth_vs_fact",
        }
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            script_gen.generate_script("Ammi aur mehmaan", config, "myth_vs_fact")
        prompt = generate_json.call_args.args[0]
        self.assertIn("funny and relatable fictional comedy Short", prompt)
        self.assertIn("clear setup, quick escalation, and punchline", prompt)
        self.assertIn("natural Urdu script", prompt)
        self.assertIn("four visual keywords", prompt)
        self.assertIn("not be described as if it depicts the story", prompt)
        self.assertIn("no profanity, abusive language, slurs, insults", prompt)
        self.assertIn("or double meanings", prompt)

    def test_channel_profile_has_isolated_state_and_oauth_paths(self):
        config = load_config("config_zaiqa.yaml")
        self.assertEqual(
            main._state_path("history.json", config),
            PROJECT_DIR / "state" / "zaiqa" / "history.json",
        )
        self.assertEqual(main._state_path("history.json"), PROJECT_DIR / "history.json")
        self.assertEqual(config["token_file"], "credentials/zaiqa_token.json")
        self.assertEqual(config["token_file_env"], "ZAIQA_YOUTUBE_TOKEN_FILE")
        self.assertFalse(config["analytics_enabled"])

    def test_pagal_panti_profile_has_isolated_state_and_oauth(self):
        config = load_config("config_pagal_panti.yaml")
        self.assertEqual(config["expected_channel_name"], "Pagal Panti Plus")
        self.assertEqual(config["expected_channel_id"], "UC65G5hn9N39ReTO_kpg3enw")
        self.assertEqual(config["token_file"], "credentials/pagal_panti_token.json")
        self.assertEqual(config["token_file_env"], "PAGAL_PANTI_YOUTUBE_TOKEN_FILE")
        self.assertEqual(config["pexels"]["footage_style"], "original_runner")
        self.assertEqual(config["voice"]["voices"], ["ur-PK-AsadNeural"])
        self.assertEqual(config["voice"]["pitch"], "+5Hz")
        self.assertEqual(
            main._state_path("history.json", config),
            PROJECT_DIR / "state" / "pagal_panti" / "history.json",
        )
        self.assertFalse(config["analytics_enabled"])
        self.assertNotIn("api_key_env", config["pexels"])

    def test_original_runner_profile_does_not_require_pexels_key(self):
        config = {
            "review_mode": True,
            "pexels": {"footage_style": "original_runner"},
        }
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            with (
                patch.object(main, "load_dotenv"),
                patch.object(main, "load_config", return_value=config),
                patch.object(main, "require_api_key", return_value="gemini-key") as require_key,
                patch.object(main, "generate_topic", return_value="A clean comedy topic"),
                patch.object(
                    main,
                    "generate_script",
                    side_effect=RuntimeError("stop after key validation"),
                ),
                patch.object(
                    main,
                    "_state_path",
                    side_effect=lambda name, config=None: state_dir / name,
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop after key validation"):
                    main.run(dry_run=True)
        require_key.assert_not_called()

    def test_channel_token_uses_profile_specific_environment_override(self):
        class FakeCredentials:
            valid = True
            expired = False
            refresh_token = None

        with tempfile.TemporaryDirectory() as directory:
            zaiqa_path = Path(directory) / "zaiqa-token.json"
            zaiqa_path.write_text(json.dumps({"scopes": uploader.SCOPES}), encoding="utf-8")
            config = {
                "oauth_client_secrets": "unused-client.json",
                "token_file": "credentials/zaiqa_token.json",
                "token_file_env": "ZAIQA_YOUTUBE_TOKEN_FILE",
            }
            with (
                patch.dict(
                    uploader.os.environ,
                    {
                        "YOUTUBE_TOKEN_FILE": "token.json",
                        "ZAIQA_YOUTUBE_TOKEN_FILE": str(zaiqa_path),
                        "YOUTUBE_INTERACTIVE_LOGIN": "0",
                    },
                ),
                patch.object(
                    uploader.Credentials,
                    "from_authorized_user_file",
                    return_value=FakeCredentials(),
                ) as read_token,
            ):
                credentials = uploader._credentials(config)

        self.assertIsInstance(credentials, FakeCredentials)
        self.assertEqual(read_token.call_args.args[0], str(zaiqa_path))

    def test_channel_authorization_rejects_the_wrong_channel(self):
        class FakeRequest:
            def execute(self):
                return {
                    "items": [
                        {
                            "id": "tech-channel-id",
                            "snippet": {"title": "Tech Buzz Daily"},
                        }
                    ]
                }

        class FakeChannels:
            def list(self, **kwargs):
                self.request_args = kwargs
                return FakeRequest()

        class FakeYouTube:
            def __init__(self):
                self.channel_api = FakeChannels()

            def channels(self):
                return self.channel_api

        youtube = FakeYouTube()
        with (
            patch.object(authorize_channel, "load_dotenv"),
            patch.object(
                authorize_channel,
                "load_config",
                return_value={"expected_channel_name": "Zaiqa Ki Kahani"},
            ),
            patch.object(authorize_channel, "_credentials", return_value=object()),
            patch.object(authorize_channel, "build", return_value=youtube),
        ):
            with self.assertRaisesRegex(RuntimeError, "expects 'Zaiqa Ki Kahani'"):
                authorize_channel.authorize("config_zaiqa.yaml")
        self.assertTrue(youtube.channel_api.request_args["mine"])

    def test_channel_authorization_rejects_the_wrong_channel_id(self):
        response = {
            "items": [
                {"id": "different-channel-id", "snippet": {"title": "Pagal Panti Plus"}}
            ]
        }

        class FakeRequest:
            def execute(self):
                return response

        class FakeChannels:
            def list(self, **kwargs):
                return FakeRequest()

        class FakeYouTube:
            def channels(self):
                return FakeChannels()

        with (
            patch.object(authorize_channel, "load_dotenv"),
            patch.object(
                authorize_channel,
                "load_config",
                return_value={
                    "expected_channel_name": "Pagal Panti Plus",
                    "expected_channel_id": "expected-channel-id",
                },
            ),
            patch.object(authorize_channel, "_credentials", return_value=object()),
            patch.object(authorize_channel, "build", return_value=FakeYouTube()),
            patch.object(authorize_channel, "_save_credentials") as save_credentials,
        ):
            with self.assertRaisesRegex(RuntimeError, "expects 'expected-channel-id'"):
                authorize_channel.authorize("config_pagal_panti.yaml")
        save_credentials.assert_not_called()

    def test_channel_authorization_saves_token_after_channel_id_matches(self):
        response = {
            "items": [
                {
                    "id": "expected-channel-id",
                    "snippet": {"title": "Pagal Panti Plus"},
                }
            ]
        }

        class FakeRequest:
            def execute(self):
                return response

        class FakeChannels:
            def list(self, **kwargs):
                return FakeRequest()

        class FakeYouTube:
            def channels(self):
                return FakeChannels()

        credentials = object()
        config = {
            "expected_channel_name": "Pagal Panti Plus",
            "expected_channel_id": "expected-channel-id",
            "token_file": "credentials/pagal_panti_token.json",
            "token_file_env": "PAGAL_PANTI_YOUTUBE_TOKEN_FILE",
        }
        with (
            patch.object(authorize_channel, "load_dotenv"),
            patch.object(authorize_channel, "load_config", return_value=config),
            patch.object(authorize_channel, "_credentials", return_value=credentials),
            patch.object(authorize_channel, "build", return_value=FakeYouTube()),
            patch.object(authorize_channel, "_save_credentials") as save_credentials,
        ):
            result = authorize_channel.authorize("config_pagal_panti.yaml")

        self.assertEqual(result, ("Pagal Panti Plus", "expected-channel-id"))
        save_credentials.assert_called_once_with(
            credentials,
            PROJECT_DIR / "credentials" / "pagal_panti_token.json",
        )

    def test_analytics_returns_recent_metrics_for_uploaded_videos_only(self):
        class FakeRequest:
            def execute(self):
                return {
                    "columnHeaders": [
                        {"name": "video"},
                        {"name": "views"},
                        {"name": "averageViewDuration"},
                        {"name": "averageViewPercentage"},
                    ],
                    "rows": [
                        ["winning-video", 321, 14.2, 45.6],
                        ["untracked-video", 999, 19.0, 70.0],
                        ["other-video", 50, 5.0, 20.0],
                    ],
                }

        class FakeReports:
            def query(self, **kwargs):
                self.query_args = kwargs
                return FakeRequest()

        class FakeService:
            def __init__(self):
                self.report_api = FakeReports()

            def reports(self):
                return self.report_api

        service = FakeService()
        history = [
            {
                "status": "uploaded",
                "youtube_video_id": "winning-video",
                "title": "Browser AI Demo",
                "topic": "Use a free browser AI model",
            },
            {
                "status": "pending_review",
                "youtube_video_id": "other-video",
                "title": "Pending Short",
                "topic": "Not uploaded",
            },
        ]
        with (
            patch.object(analytics, "_credentials", return_value=object()),
            patch.object(analytics, "build", return_value=service),
        ):
            insights = analytics.fetch_performance_insights(history, {})

        self.assertEqual(
            insights,
            [
                {
                    "topic": "Use a free browser AI model",
                    "title": "Browser AI Demo",
                    "views": 321,
                    "average_view_duration_seconds": 14.2,
                    "average_view_percentage": 45.6,
                }
            ],
        )
        self.assertEqual(service.report_api.query_args["ids"], "channel==MINE")
        self.assertEqual(
            service.report_api.query_args["metrics"],
            "views,averageViewDuration,averageViewPercentage",
        )

    def test_script_generation_enforces_short_word_count(self):
        script = (
            "Turn a sketch into a working page with Excalidraw. Open the canvas, draw a "
            "simple layout, then use the export option to get a starting point for your "
            "code. Keep the drawing clear and label the main sections. You can refine the "
            "result in your editor. Check which export features are currently available "
            "before relying on them."
        )
        response = {
            "title": "Excalidraw to Code",
            "description": "A quick Excalidraw demo.",
            "tags": ["Excalidraw", "beginner coding", "AI tools"],
            "script": script,
            "keywords": ["draw layout", "canvas", "code editor", "web page"],
            "hook_style": "question",
        }
        config = {"niche": "AI tools", "gemini": {"api_key_env": "TEST_KEY"}}
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            generated = script_gen.generate_script("Excalidraw demo", config, "question")
        self.assertEqual(generated["script"], script)
        self.assertIn(
            "required hook_style value is exactly 'question'",
            generate_json.call_args.args[0],
        )
        response["script"] = " ".join(["word"] * 61)
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "expected 45-60"):
                script_gen.generate_script("Excalidraw demo", config, "question")

    def test_roman_urdu_script_uses_urdu_voiceover_text(self):
        roman_script = (
            "Peshawar ka chapli kebab apne masalay daar zaiqay ke liye mashhoor hai. "
            "Qeema, hara dhania, piyaz aur khushk anar dana milakar iska khaas mixture "
            "tayyar hota hai. Phir ise chapti tikki ki shakal de kar taway par pakaya "
            "jata hai. Iska naam chapli, yani chapta, iski isi shakal ki taraf ishara karta hai."
        )
        narration_script = " ".join(["یہ پشاوری کھانا بہت مشہور ہے۔"] * 10)
        response = {
            "title": "Peshawar Chapli Kebab Ki Kahani",
            "description": "Peshawar ke chapli kebab ki kahani aur zaiqa.",
            "tags": ["Peshawar food", "chapli kebab", "Pakistani food"],
            "script": roman_script,
            "narration_script": narration_script,
            "keywords": ["chapli kebab cooking", "minced meat spices", "kebab patty frying", "Peshawar food"],
            "hook_style": "story",
        }
        config = {
            "niche": "Pakistan regional food",
            "content_language": "Roman Urdu",
            "gemini": {"api_key_env": "TEST_KEY"},
        }
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(script_gen, "_generate_json", return_value=response) as generate_json,
        ):
            generated = script_gen.generate_script("Chapli kebab story", config, "story")
        prompt = generate_json.call_args.args[0]
        self.assertIn("natural, easy Roman Urdu", prompt)
        self.assertIn("narration_script", prompt)
        self.assertEqual(generated["narration_script"], narration_script)

    def test_roman_urdu_script_retries_when_voiceover_is_too_short(self):
        script = " ".join(["desi ghar ka yeh scene bohat funny hota hai"] * 6)
        valid_narration = " ".join(["یہ مزاحیہ بات گھر میں اکثر ہوتی ہے۔"] * 6)
        response = {
            "title": "Ghar Ka Funny Scene",
            "description": "Ghar ke rozmarra scene ki funny kahani.",
            "tags": ["desi comedy", "Pakistani humor", "family funny"],
            "script": script,
            "narration_script": "یہ چھوٹا جملہ ہے۔",
            "keywords": [
                "mobile game gameplay",
                "racing game gameplay",
                "parkour game gameplay",
                "arcade game gameplay",
            ],
            "hook_style": "story",
        }
        config = {
            "niche": "Pakistani everyday comedy",
            "content_language": "Roman Urdu",
            "content_style": "comedy",
            "pexels": {"footage_style": "gameplay"},
            "gemini": {"api_key_env": "TEST_KEY"},
        }
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(
                script_gen,
                "_generate_json",
                side_effect=[
                    response,
                    {**response, "narration_script": valid_narration},
                ],
            ) as generate_json,
        ):
            generated = script_gen.generate_script("A funny desi scene", config, "story")

        self.assertEqual(generated["narration_script"], valid_narration)
        self.assertEqual(generate_json.call_count, 2)
        self.assertIn("Urdu narration_script had 4 words", generate_json.call_args.args[0])

    def test_script_generation_retries_hook_style_mismatch(self):
        response = {
            "title": "Excalidraw to Code",
            "description": "A quick Excalidraw demo.",
            "tags": ["Excalidraw", "beginner coding", "AI tools"],
            "script": (
                "Turn a sketch into a working page with Excalidraw. Open the canvas, draw a "
                "simple layout, then use the export option to get a starting point for your "
                "code. Keep the drawing clear and label the main sections. You can refine the "
                "result in your editor. Check which export features are currently available "
                "before relying on them."
            ),
            "keywords": ["draw layout", "canvas", "code editor", "web page"],
            "hook_style": "story",
        }
        config = {"niche": "AI tools", "gemini": {"api_key_env": "TEST_KEY"}}
        with (
            patch.object(script_gen, "require_api_key", return_value="key"),
            patch.object(
                script_gen,
                "_generate_json",
                side_effect=[{**response, "hook_style": "question"}, response],
            ) as generate_json,
        ):
            generated = script_gen.generate_script("Excalidraw demo", config, "story")
        self.assertEqual(generated["hook_style"], "story")
        self.assertEqual(generate_json.call_count, 2)
        self.assertIn("must be 'story'", generate_json.call_args.args[0])

    def test_hook_style_rotation_advances_and_wraps(self):
        self.assertEqual(main._next_hook_style([]), "myth_vs_fact")
        self.assertEqual(
            main._next_hook_style([{"hook_style": "myth_vs_fact"}]),
            "did_you_know",
        )
        self.assertEqual(
            main._next_hook_style([{"hook_style": "question"}]),
            "myth_vs_fact",
        )

    def test_failed_script_generation_does_not_consume_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            config = {"review_mode": True}
            with (
                patch.object(main, "load_dotenv"),
                patch.object(main, "load_config", return_value=config),
                patch.object(main, "require_api_key", return_value="test-key"),
                patch.object(
                    main,
                    "_state_path",
                    side_effect=lambda name, config=None: state_dir / name,
                ),
                patch.object(main, "generate_topic", return_value="Retry this topic"),
                patch.object(
                    main,
                    "generate_script",
                    side_effect=RuntimeError("script generation failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "script generation failed"):
                    main.run(dry_run=False)
            self.assertEqual(read_json(state_dir / "topics.json", []), [])

    def test_footage_search_uses_fallback_when_keyword_has_no_portrait_results(self):
        class SearchResponse:
            def __init__(self, videos):
                self.videos = videos

            def json(self):
                return {"videos": self.videos}

        portrait_video = {
            "id": 123,
            "video_files": [{"link": "https://example.com/video.mp4", "width": 720, "height": 1280}],
        }
        with patch.object(
            footage,
            "request_with_retry",
            side_effect=[SearchResponse([]), SearchResponse([portrait_video])],
        ) as search:
            result = footage._find_video("typing text prompt v0.dev", "test-key", set())
        self.assertEqual(result, (123, "https://example.com/video.mp4"))
        self.assertEqual(search.call_args_list[0].kwargs["params"]["query"], "typing text prompt v0.dev")
        self.assertEqual(search.call_args_list[1].kwargs["params"]["query"], "coding laptop programming")

    def test_original_runner_footage_is_generated_without_pexels(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "clips"
            with patch.object(
                footage,
                "generate_original_runner_clip",
                side_effect=lambda path: path,
            ) as generate_clip:
                paths, clip_ids = footage.download_clips(
                    [],
                    "",
                    [],
                    output_dir,
                    "original_runner",
                )
        self.assertEqual(paths, [output_dir / "original-runner.mp4"])
        self.assertEqual(clip_ids, [])
        generate_clip.assert_called_once_with(output_dir / "original-runner.mp4")

    def test_original_runner_video_is_portrait_and_playable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runner.mp4"
            runner_gameplay.generate_original_runner_clip(
                path,
                duration_seconds=0.5,
                fps=2,
            )
            clip = video.VideoFileClip(str(path))
            try:
                self.assertGreater(clip.duration, 0)
                self.assertEqual((clip.w, clip.h), (432, 768))
                self.assertGreater(clip.get_frame(0.25).mean(), 0)
            finally:
                clip.close()

    def test_gameplay_footage_search_uses_only_gameplay_queries(self):
        class SearchResponse:
            def __init__(self, videos):
                self.videos = videos

            def json(self):
                return {"videos": self.videos}

        portrait_video = {
            "id": 456,
            "video_files": [{"link": "https://example.com/game.mp4", "width": 720, "height": 1280}],
        }
        with patch.object(
            footage,
            "request_with_retry",
            side_effect=[SearchResponse([]), SearchResponse([portrait_video])],
        ) as search:
            result = footage._find_video(
                "mobile racing gameplay",
                "test-key",
                set(),
                "gameplay",
            )
        self.assertEqual(result, (456, "https://example.com/game.mp4"))
        queries = [
            call.kwargs["params"]["query"] for call in search.call_args_list
        ]
        self.assertEqual(queries[0], "video game gameplay mobile racing gameplay")
        self.assertEqual(queries[1], "mobile game gameplay vertical")
        self.assertTrue(all("game" in query or "gameplay" in query for query in queries))

    def test_edge_tts_receives_configured_playful_pitch(self):
        class FakeCommunicate:
            async def save(self, output_path):
                self.output_path = output_path

        communicate = FakeCommunicate()
        with patch.object(voice.edge_tts, "Communicate", return_value=communicate) as create:
            import asyncio

            asyncio.run(
                voice._save_speech(
                    "اردو میں مزاحیہ بات",
                    "ur-PK-AsadNeural",
                    "+8%",
                    "+5Hz",
                    Path("voice.mp3"),
                )
            )
        create.assert_called_once_with(
            "اردو میں مزاحیہ بات",
            "ur-PK-AsadNeural",
            rate="+8%",
            pitch="+5Hz",
        )

    def test_description_gets_three_relevant_unique_hashtags(self):
        result = uploader._description_with_hashtags(
            "Learn beginner Python coding.",
            ["python", "coding tips", "Python"],
        )
        self.assertEqual(
            result,
            "Learn beginner Python coding.\n\n#Shorts #Python #CodingTips",
        )

    def test_description_does_not_duplicate_existing_hashtags(self):
        result = uploader._description_with_hashtags(
            "Learn coding. #Shorts",
            ["coding tricks", "AI tools"],
        )
        self.assertEqual(result, "Learn coding. #Shorts\n\n#CodingTricks #AITools")

    def test_description_caps_total_relevant_hashtags_at_three(self):
        result = uploader._description_with_hashtags(
            "Learn AI tools.\n\n#Shorts #AITools #Beginners",
            ["AI tools", "coding", "Python"],
        )
        self.assertEqual(result, "Learn AI tools.\n\n#Shorts #AITools #Beginners")

    def test_description_trims_excess_generated_hashtags(self):
        result = uploader._description_with_hashtags(
            "Learn Raycast.\n\n#Shorts #Raycast #Coding\n\n#MacLauncher",
            ["Raycast", "coding", "Mac launcher"],
        )
        self.assertEqual(result, "Learn Raycast.\n\n#Shorts #Raycast #Coding")

    def test_video_upload_sets_custom_thumbnail(self):
        class FakeRequest:
            def next_chunk(self, num_retries):
                return None, {"id": "video-id"}

            def execute(self):
                return {"items": []}

        class FakeResource:
            def insert(self, **kwargs):
                self.insert_args = kwargs
                return FakeRequest()

            def set(self, **kwargs):
                self.set_args = kwargs
                return FakeRequest()

        class FakeYouTube:
            def __init__(self):
                self.video_resource = FakeResource()
                self.thumbnail_resource = FakeResource()

            def videos(self):
                return self.video_resource

            def thumbnails(self):
                return self.thumbnail_resource

        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "final.mp4"
            thumbnail_path = Path(directory) / "thumbnail.jpg"
            video_path.touch()
            thumbnail_path.touch()
            youtube = FakeYouTube()
            metadata = {
                "title": "Quick AI demo",
                "description": "A useful tool.",
                "tags": ["AI tools", "beginners", "coding"],
                "thumbnail_path": str(thumbnail_path),
            }
            with (
                patch.object(uploader, "_credentials", return_value=object()),
                patch.object(uploader, "build", return_value=youtube),
                patch.object(uploader, "MediaFileUpload", return_value="media") as media_upload,
            ):
                video_id = uploader.upload_video(metadata, video_path, {"privacy_status": "public"})

        self.assertEqual(video_id, "video-id")
        self.assertEqual(metadata["thumbnail_status"], "uploaded")
        self.assertEqual(youtube.thumbnail_resource.set_args["videoId"], "video-id")
        self.assertEqual(youtube.thumbnail_resource.set_args["media_body"], "media")
        self.assertEqual(media_upload.call_count, 2)

    def test_analytics_requires_a_token_with_read_only_scope(self):
        class FakeCredentials:
            valid = True
            expired = False
            refresh_token = None

        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.json"
            token_path.write_text(
                json.dumps({"scopes": uploader.SCOPES}),
                encoding="utf-8",
            )
            with (
                patch.object(
                    uploader.Credentials,
                    "from_authorized_user_file",
                    return_value=FakeCredentials(),
                ),
                patch.dict(uploader.os.environ, {"YOUTUBE_INTERACTIVE_LOGIN": "0"}),
            ):
                with self.assertRaisesRegex(RuntimeError, "missing required OAuth scope"):
                    uploader._credentials(
                        {"token_file": str(token_path)},
                        analytics.ANALYTICS_SCOPES,
                    )


class PersistenceAndQuotaTests(unittest.TestCase):
    def test_json_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            value = {"topics": ["One"], "uploads": 2}
            write_json(path, value)
            self.assertEqual(read_json(path, None), value)

    def test_daily_upload_cap_is_enforced(self):
        with patch.object(main, "_daily_uploads", return_value=5):
            main.ensure_upload_capacity({"daily_upload_limit": 6})
        with patch.object(main, "_daily_uploads", return_value=6):
            with self.assertRaisesRegex(RuntimeError, "Daily upload limit reached"):
                main.ensure_upload_capacity({"daily_upload_limit": 6})
        with self.assertRaisesRegex(RuntimeError, "from 1 to 6"):
            main.ensure_upload_capacity({"daily_upload_limit": 7})
        with patch.object(main, "_daily_uploads", return_value=1):
            main.ensure_upload_capacity({"daily_upload_limit": 1}, allow_one_extra=True)
        with patch.object(main, "_daily_uploads", return_value=2):
            with self.assertRaisesRegex(RuntimeError, "Daily upload limit reached"):
                main.ensure_upload_capacity({"daily_upload_limit": 1}, allow_one_extra=True)


class CaptionTests(unittest.TestCase):
    def test_thumbnail_uses_video_frame_and_recommended_shorts_dimensions(self):
        class FakeVideo:
            duration = 2

            def get_frame(self, timestamp):
                self.timestamp = timestamp
                return np.full((192, 108, 3), (25, 70, 120), dtype=np.uint8)

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "thumbnail.jpg"
            clip = FakeVideo()
            with patch.object(video, "VideoFileClip", return_value=clip):
                create_thumbnail(Path("video.mp4"), "Generate AI Images Fast", output_path)
            with Image.open(output_path) as thumbnail:
                self.assertEqual(thumbnail.size, (2160, 3840))
                self.assertEqual(thumbnail.format, "JPEG")
            self.assertEqual(clip.timestamp, 0.5)

    def test_word_captions_divide_the_audio_duration_evenly(self):
        clips = _caption_clips("One useful example for a beginner", 6, 1080, 1920, 72)
        try:
            self.assertEqual([clip.start for clip in clips], [0, 3])
            self.assertEqual([clip.duration for clip in clips], [3, 3])
            self.assertTrue(all(clip.w < 960 and clip.h < 250 for clip in clips))
        finally:
            for clip in clips:
                clip.close()

    def test_footage_scenes_follow_even_spoken_word_sections(self):
        durations = _scene_durations("one two three four five six seven eight nine", 18, 4)
        self.assertEqual(durations, [6, 4, 4, 4])
        self.assertEqual(sum(durations), 18)

    def test_scene_timing_rejects_empty_inputs(self):
        with self.assertRaisesRegex(RuntimeError, "Scene timing"):
            _scene_durations("", 18, 4)

    def test_fit_clip_resizes_without_legacy_pillow_antialias(self):
        source = ColorClip(size=(100, 200), color=(255, 0, 0), duration=1)
        fitted = _fit_clip(source, 1, 108, 192)
        try:
            self.assertEqual((fitted.w, fitted.h), (108, 192))
            np.testing.assert_allclose(
                fitted.get_frame(0.5).mean(axis=(0, 1)),
                [255, 0, 0],
                atol=2,
            )
        finally:
            fitted.close()
            source.close()


class VoiceTests(unittest.TestCase):
    def test_duration_only_changes_tempo_when_outside_shorts_range(self):
        self.assertIsNone(_tempo_adjustment(36, 30, 45))
        self.assertAlmostEqual(_tempo_adjustment(25, 30, 45), 25 / 31)
        self.assertAlmostEqual(_tempo_adjustment(50, 30, 45), 50 / 44)
        with self.assertRaisesRegex(RuntimeError, "too far outside"):
            _tempo_adjustment(10, 30, 45)


if __name__ == "__main__":
    unittest.main()
