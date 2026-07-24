#!/usr/bin/env python3
"""Optional local transcription for video-to-notes using faster-whisper."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class TranscriptionError(RuntimeError):
    """User-facing transcription failure."""


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def format_vtt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    millis = round((seconds - whole) * 1000)
    if millis == 1000:
        whole += 1
        millis = 0
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def write_outputs(segments: Sequence[TranscriptSegment], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "transcript.json"
    vtt_path = output_dir / "transcript.vtt"
    text_path = output_dir / "transcript.txt"

    json_path.write_text(
        json.dumps({"segments": [asdict(segment) for segment in segments]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    vtt_lines = ["WEBVTT", ""]
    for index, segment in enumerate(segments, start=1):
        vtt_lines.extend(
            [
                str(index),
                f"{format_vtt_timestamp(segment.start)} --> {format_vtt_timestamp(segment.end)}",
                segment.text,
                "",
            ]
        )
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    text_path.write_text(
        "\n".join(f"[{format_vtt_timestamp(segment.start)[:8]}] {segment.text}" for segment in segments)
        + ("\n" if segments else ""),
        encoding="utf-8",
    )
    return {"json": str(json_path), "vtt": str(vtt_path), "text": str(text_path)}


def update_manifest(path: Path, segments: Sequence[TranscriptSegment], outputs: dict[str, str]) -> None:
    if not path.is_file():
        raise TranscriptionError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptionError(f"cannot read manifest: {exc}") from exc
    root = path.resolve().parent

    def relative_or_absolute(value: str) -> str:
        resolved = Path(value).resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return str(resolved)

    data["transcript"] = {
        "source": "faster-whisper",
        "segment_count": len(segments),
        "normalized_json": relative_or_absolute(outputs["json"]),
        "timestamped_text": relative_or_absolute(outputs["text"]),
        "vtt": relative_or_absolute(outputs["vtt"]),
        "needs_transcription": not bool(segments),
        "error": None,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transcribe(args: argparse.Namespace) -> dict[str, Any]:
    media = args.input.expanduser().resolve()
    if not media.is_file():
        raise TranscriptionError(f"media not found: {media}")
    model_path = Path(args.model).expanduser()
    if not model_path.exists() and not args.allow_model_download:
        raise TranscriptionError(
            "the named Whisper model may require a network download; rerun with --allow-model-download "
            "or pass a local model directory"
        )
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise TranscriptionError(
            "faster-whisper is required; run with `uv run --with faster-whisper ...`"
        ) from exc

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    raw_segments, info = model.transcribe(
        str(media),
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=not args.no_vad,
        condition_on_previous_text=True,
    )
    segments: list[TranscriptSegment] = []
    for raw in raw_segments:
        text = clean_text(str(raw.text))
        if text:
            segments.append(TranscriptSegment(float(raw.start), float(raw.end), text))
        if len(segments) >= args.max_segments:
            raise TranscriptionError(
                f"transcription exceeded --max-segments={args.max_segments}; increase the explicit bound to continue"
            )
    outputs = write_outputs(segments, args.output_dir.resolve())
    if args.manifest:
        update_manifest(args.manifest.expanduser().resolve(), segments, outputs)
    return {
        "segments": len(segments),
        "language": getattr(info, "language", args.language),
        "language_probability": getattr(info, "language_probability", None),
        "outputs": outputs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe media locally with faster-whisper.")
    parser.add_argument("input", type=Path, help="local audio or video file")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="optional prepare_video manifest to update with the transcript")
    parser.add_argument("--model", default="small", help="model name or local model directory")
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="explicitly permit faster-whisper to download a named model",
    )
    parser.add_argument("--language", help="optional ISO language code; auto-detect when omitted")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--compute-type", default="default")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--max-segments", type=int, default=10000)
    parser.add_argument("--no-vad", action="store_true", help="disable voice-activity filtering")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.beam_size < 1 or args.max_segments < 1:
        parser.error("--beam-size and --max-segments must be positive")
    try:
        result = transcribe(args)
    except (TranscriptionError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
