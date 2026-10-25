import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import footage
import script_gen
from utils import normalized_topic, read_json, write_json
from video import _caption_clips
from voice import _tempo_adjustment


class TopicAndFormatTests(unittest.TestCase):
    def test_topic_normalization_ignores_case_and_punctuation(self):
        self.assertEqual(normalized_topic("  Why?!  Bees—Dance "), "why bees dance")

    def test_topic_generation_retries_duplicate_topics(self):
        config = {"niche": "science", "gemini": {"model": "test"}}
        with (
            patch.object(script_gen, "require_api_key", return_value="test-key"),
            patch.object(
                script_gen,
                "_generate_json",
                side_effect=[{"topic": "Known Topic!"}, {"topic": "A different discovery"}],
            ),
        ):
            topic = script_gen.generate_topic(config, ["Known Topic"])
        self.assertEqual(topic, "A different discovery")

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
                patch.object(main, "_state_path", side_effect=lambda name: state_dir / name),
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


class CaptionTests(unittest.TestCase):
    def test_word_captions_divide_the_audio_duration_evenly(self):
        clips = _caption_clips("One useful example", 36, 1080, 1920, 72)
        try:
            self.assertEqual([clip.start for clip in clips], [0, 12, 24])
            self.assertEqual([clip.duration for clip in clips], [12, 12, 12])
            self.assertTrue(all(clip.w < 500 and clip.h < 200 for clip in clips))
        finally:
            for clip in clips:
                clip.close()


class VoiceTests(unittest.TestCase):
    def test_duration_only_changes_tempo_when_outside_shorts_range(self):
        self.assertIsNone(_tempo_adjustment(36, 30, 45))
        self.assertAlmostEqual(_tempo_adjustment(25, 30, 45), 25 / 31)
        self.assertAlmostEqual(_tempo_adjustment(50, 30, 45), 50 / 44)
        with self.assertRaisesRegex(RuntimeError, "too far outside"):
            _tempo_adjustment(10, 30, 45)


if __name__ == "__main__":
    unittest.main()
