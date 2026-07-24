#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prepare = load_module("video_to_notes_prepare", "scripts/prepare_video.py")
transcribe = load_module("video_to_notes_transcribe", "scripts/transcribe_audio.py")


class ParsingTests(unittest.TestCase):
    def test_url_detection_is_http_only(self):
        self.assertTrue(prepare.is_url("https://example.com/watch?v=1"))
        self.assertTrue(prepare.is_url("http://localhost/video"))
        self.assertFalse(prepare.is_url("ftp://example.com/video"))
        self.assertFalse(prepare.is_url("C:/videos/demo.mp4"))

    def test_safe_stem_removes_path_and_shell_punctuation(self):
        self.assertEqual(prepare.safe_stem("demo video; $(bad).mp4"), "demo-video-bad")
        self.assertEqual(prepare.safe_stem("..."), "video")
        self.assertLessEqual(len(prepare.safe_stem("x" * 500)), 120)

    def test_timestamps(self):
        self.assertAlmostEqual(prepare.parse_timestamp("01:02:03,250"), 3723.25)
        self.assertAlmostEqual(prepare.parse_timestamp("02:03.500"), 123.5)
        self.assertEqual(prepare.format_timecode(3723.9), "01:02:03")
        self.assertEqual(transcribe.format_vtt_timestamp(1.9996), "00:00:02.000")

    def test_vtt_parsing_strips_tags_and_merges_exact_duplicates(self):
        text = """WEBVTT

1
00:00:01.000 --> 00:00:02.000
<v Speaker>Hello &amp; <b>world</b>

2
00:00:02.000 --> 00:00:03.500
Hello &amp; world

3
00:00:04.000 --> 00:00:05.000
Next line
"""
        segments = prepare.parse_vtt(text)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "Hello & world")
        self.assertEqual(segments[0].start, 1)
        self.assertEqual(segments[0].end, 3.5)

    def test_srt_and_json_parsing(self):
        srt = "1\n00:00:01,000 --> 00:00:02,000\nПривет\n"
        self.assertEqual(prepare.parse_srt(srt)[0].text, "Привет")
        payload = json.dumps({"segments": [{"start": 1, "end": 2, "text": " code  shown "}]})
        self.assertEqual(prepare.parse_json_transcript(payload)[0].text, "code shown")

    def test_even_sampling_keeps_endpoints(self):
        sampled = prepare.evenly_spaced(list(range(20)), 5)
        self.assertEqual(sampled[0], 0)
        self.assertEqual(sampled[-1], 19)
        self.assertEqual(len(sampled), 5)
        with self.assertRaises(ValueError):
            prepare.evenly_spaced([1], 0)

    def test_hamming_distance(self):
        self.assertEqual(prepare.hamming_distance(0b1010, 0b1111), 2)


class FileAndProcessTests(unittest.TestCase):
    def test_choose_transcript_prefers_vtt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "long-name.srt").write_text("", encoding="utf-8")
            preferred = root / "captions.vtt"
            preferred.write_text("", encoding="utf-8")
            unrelated = root / "other.json"
            unrelated.write_text("{}", encoding="utf-8")
            self.assertEqual(prepare.choose_transcript(None, root, "captions"), preferred)

    def test_ytdlp_command_is_bounded_and_uses_argument_array(self):
        command = prepare.build_ytdlp_command(
            "https://example.com/watch?v=1",
            Path("work/source"),
            ["en", "ru"],
            512,
            60,
        )
        self.assertEqual(command[0], "yt-dlp")
        self.assertIn("--no-playlist", command)
        self.assertEqual(command[command.index("--max-filesize") + 1], "512M")
        self.assertEqual(command[-2:], ["--", "https://example.com/watch?v=1"])

    def test_run_command_uses_argument_array_no_shell(self):
        completed = subprocess.CompletedProcess(["tool", "arg"], 0, "ok", "")
        with mock.patch.object(prepare.subprocess, "run", return_value=completed) as runner:
            result = prepare.run_command(["tool", "arg"], 12, "test")
        self.assertEqual(result.stdout, "ok")
        kwargs = runner.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertEqual(runner.call_args.args[0], ["tool", "arg"])

    def test_difference_hash_and_frame_deduplication(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "one.jpg"
            duplicate = root / "two.jpg"
            changed = root / "three.jpg"
            Image.new("RGB", (32, 32), "black").save(first)
            Image.new("RGB", (32, 32), "black").save(duplicate)
            image = Image.new("RGB", (32, 32), "black")
            for x in range(16):
                for y in range(32):
                    image.putpixel((x, y), (255, 255, 255))
            image.save(changed)
            selected = prepare.select_frames([first, duplicate, changed], threshold=0, max_frames=10)
            self.assertEqual([index for index, _ in selected], [0, 2])

    def test_transcript_outputs_and_manifest_update(self):
        segments = [transcribe.TranscriptSegment(0.5, 2.0, "Привет, code")]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"transcript": {"needs_transcription": True}}), encoding="utf-8")
            outputs = transcribe.write_outputs(segments, root)
            transcribe.update_manifest(manifest, segments, outputs)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(data["transcript"]["needs_transcription"])
            self.assertEqual(data["transcript"]["segment_count"], 1)
            self.assertIn("WEBVTT", Path(outputs["vtt"]).read_text(encoding="utf-8"))
            self.assertIn("Привет", Path(outputs["text"]).read_text(encoding="utf-8"))

    def test_transcription_rejects_missing_media(self):
        args = mock.Mock()
        args.input = Path("missing.mp4")
        with self.assertRaisesRegex(transcribe.TranscriptionError, "media not found"):
            transcribe.transcribe(args)

    def test_transcription_requires_explicit_model_download(self):
        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / "sample.mp4"
            media.write_bytes(b"not-real-media")
            args = mock.Mock(input=media, model="remote-model-name", allow_model_download=False)
            with self.assertRaisesRegex(transcribe.TranscriptionError, "--allow-model-download"):
                transcribe.transcribe(args)


if __name__ == "__main__":
    unittest.main()
