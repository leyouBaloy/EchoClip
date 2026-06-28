from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

BITMAP_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle",
    "dvb_subtitle",
    "dvd_subtitle",
    "xsub",
}

TEXT_SUBTITLE_CODECS = {
    "subrip",
    "ass",
    "ssa",
    "mov_text",
    "webvtt",
    "text",
}

TIMESTAMP_PATTERN = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
ASS_TAG_PATTERN = re.compile(r"\{[^}]+\}")


@dataclass
class SubtitleStream:
    index: int
    codec: str
    language: str
    title: str

    @property
    def label(self) -> str:
        parts = [part for part in (self.language, self.title) if part]
        return " - ".join(parts) if parts else f"Track {self.index}"


def resolve_binary(name: str) -> Optional[str]:
    env_key = f"ECHOCLIP_{name.upper()}_PATH"
    configured = os.getenv(env_key, "").strip()
    if configured:
        path = Path(configured)
        if path.exists():
            return str(path)
    discovered = shutil.which(name)
    return discovered


def list_subtitle_streams(video_path: Path) -> list[SubtitleStream]:
    ffprobe = resolve_binary("ffprobe")
    if not ffprobe:
        return []

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "s",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return []

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return []

    streams: list[SubtitleStream] = []
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        codec = str(stream.get("codec_name") or "").lower()
        if codec in BITMAP_SUBTITLE_CODECS:
            continue
        tags = stream.get("tags") or {}
        streams.append(
            SubtitleStream(
                index=int(stream["index"]),
                codec=codec,
                language=str(tags.get("language") or tags.get("LANGUAGE") or "").strip(),
                title=str(tags.get("title") or tags.get("TITLE") or "").strip(),
            )
        )
    return streams


def choose_subtitle_stream(
    streams: list[SubtitleStream],
    language: Optional[str] = None,
) -> Optional[SubtitleStream]:
    if not streams:
        return None

    preferred = normalize_language(language)
    if preferred:
        for stream in streams:
            if language_matches(stream.language, preferred):
                return stream
        for stream in streams:
            if language_matches(stream.title, preferred):
                return stream

    for stream in streams:
        if language_matches(stream.language, "en") or language_matches(stream.title, "en"):
            return stream

    return streams[0]


def extract_subtitle_srt(video_path: Path, stream: SubtitleStream) -> Optional[str]:
    ffmpeg = resolve_binary("ffmpeg")
    if not ffmpeg:
        return None

    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as handle:
        output_path = Path(handle.name)

    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-map",
                f"0:{stream.index}",
                "-c:s",
                "srt",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0 or not output_path.exists():
            return None
        return output_path.read_text(encoding="utf-8", errors="replace")
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        output_path.unlink(missing_ok=True)


def parse_srt(content: str) -> list[dict[str, Any]]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", normalized)
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        timestamp_line = lines[1] if lines[0].isdigit() else lines[0]
        text_lines = lines[2:] if lines[0].isdigit() else lines[1:]
        match = TIMESTAMP_PATTERN.search(timestamp_line)
        if not match:
            continue

        start = timestamp_to_seconds(match.group(1, 2, 3, 4))
        end = timestamp_to_seconds(match.group(5, 6, 7, 8))
        text = clean_subtitle_text(" ".join(text_lines))
        if not text or end <= start:
            continue
        segments.append({"text": text, "start": start, "end": end})

    return segments


def try_extract_embedded_subtitles(
    video_path: Path,
    *,
    language: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    streams = list_subtitle_streams(video_path)
    stream = choose_subtitle_stream(streams, language)
    if not stream:
        return None

    srt_content = extract_subtitle_srt(video_path, stream)
    if not srt_content:
        return None

    segments = parse_srt(srt_content)
    if not segments:
        return None

    duration = probe_duration(video_path) or segments[-1]["end"]
    return {
        "text": " ".join(segment["text"] for segment in segments),
        "language": normalize_language(stream.language) or normalize_language(language) or stream.language,
        "duration": duration,
        "segments": segments,
        "words": [],
        "subtitle_track": stream.label,
    }


def probe_duration(video_path: Path) -> Optional[float]:
    ffprobe = resolve_binary("ffprobe")
    if not ffprobe:
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return float((completed.stdout or "").strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def timestamp_to_seconds(parts: tuple[str, str, str, str]) -> float:
    hours, minutes, seconds, millis = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def clean_subtitle_text(text: str) -> str:
    cleaned = HTML_TAG_PATTERN.sub("", text)
    cleaned = ASS_TAG_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("\\N", " ").replace("\\n", " ")
    return " ".join(cleaned.split())


def normalize_language(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lowered = value.strip().lower()
    aliases = {
        "english": "en",
        "eng": "en",
        "en-us": "en",
        "en-gb": "en",
        "chinese": "zh",
        "chi": "zh",
        "zho": "zh",
        "zh-cn": "zh",
        "zh-tw": "zh",
    }
    if lowered in aliases:
        return aliases[lowered]
    if len(lowered) >= 2:
        return lowered[:2]
    return lowered


def language_matches(value: str, preferred: str) -> bool:
    if not value or not preferred:
        return False
    normalized = normalize_language(value) or value.lower()
    preferred = normalize_language(preferred) or preferred.lower()
    if normalized == preferred:
        return True
    return preferred in value.lower() or normalized in value.lower()
