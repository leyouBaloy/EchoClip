from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from app.subtitles import resolve_binary

BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}
BROWSER_AUDIO_CODECS = {"aac", "mp3", "opus", "flac", "vorbis"}
LEGACY_AUDIO_CODECS = {
    "ac3",
    "eac3",
    "dts",
    "truehd",
    "hdmv_dts_ma",
    "dts_hd_ma",
    "pcm_s16le",
    "pcm_s24le",
}


def probe_media_streams(video_path: Path) -> list[dict[str, Any]]:
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

    streams = payload.get("streams", [])
    return streams if isinstance(streams, list) else []


def primary_audio_codec(video_path: Path) -> Optional[str]:
    for stream in probe_media_streams(video_path):
        if stream.get("codec_type") == "audio":
            return str(stream.get("codec_name") or "").lower() or None
    return None


def needs_web_transcode(video_path: Path) -> bool:
    extension = video_path.suffix.lower()
    audio_codec = primary_audio_codec(video_path)

    if extension not in BROWSER_CONTAINERS:
        return True
    if not audio_codec:
        return False
    if audio_codec in LEGACY_AUDIO_CODECS:
        return True
    if audio_codec not in BROWSER_AUDIO_CODECS:
        return True
    return False


def prepare_web_playback(source_path: Path) -> Path:
    if not needs_web_transcode(source_path):
        return source_path

    ffmpeg = resolve_binary("ffmpeg")
    if not ffmpeg:
        return source_path

    target_path = source_path.with_suffix(".web.mp4")
    if target_path.exists() and target_path.stat().st_mtime >= source_path.stat().st_mtime:
        return target_path

    if transcode_for_web(ffmpeg, source_path, target_path, copy_video=True):
        return target_path
    if transcode_for_web(ffmpeg, source_path, target_path, copy_video=False):
        return target_path
    return source_path


def transcode_for_web(
    ffmpeg: str,
    source_path: Path,
    target_path: Path,
    *,
    copy_video: bool,
) -> bool:
    video_codec = ["-c:v", "copy"] if copy_video else ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        *video_codec,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(target_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (subprocess.SubprocessError, OSError):
        return False

    if completed.returncode != 0 or not target_path.exists() or target_path.stat().st_size == 0:
        target_path.unlink(missing_ok=True)
        return False
    return True
