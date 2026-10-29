import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from moviepy.editor import ColorClip
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import footage
import script_gen
import uploader
import video
from utils import normalized_topic, read_json, write_json
from video import _caption_clips, _fit_clip, _scene_durations, create_thumbnail
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
