from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

UPLOAD_DIR = Path(os.getenv("ECHOCLIP_UPLOAD_DIR", "./storage/uploads")).resolve()
SAMPLE_DIR = Path(os.getenv("ECHOCLIP_SAMPLE_DIR", "../test-assets")).resolve()
DEFAULT_BASE_URL = os.getenv("ECHOCLIP_DEFAULT_BASE_URL", "http://192.168.2.172:8000/v1").rstrip("/")
DEFAULT_MODEL = os.getenv("ECHOCLIP_DEFAULT_MODEL", "whisper-1")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="EchoClip API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(UPLOAD_DIR)), name="media")
if SAMPLE_DIR.exists():
    app.mount("/samples", StaticFiles(directory=str(SAMPLE_DIR)), name="samples")


class Word(BaseModel):
    text: str
    start: float
    end: float


class Segment(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word] = Field(default_factory=list)


class TranscriptResponse(BaseModel):
    id: str
    filename: str
    media_url: str
    language: Optional[str] = None
    duration: Optional[float] = None
    text: str
    segments: list[Segment]
    words: list[Word]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/transcriptions", response_model=TranscriptResponse)
async def transcribe_video(
    request: Request,
    file: UploadFile = File(...),
    api_key: str = Form(""),
    base_url: str = Form(DEFAULT_BASE_URL),
    model: str = Form(DEFAULT_MODEL),
    language: Optional[str] = Form(None),
) -> TranscriptResponse:
    project_id = uuid.uuid4().hex
    extension = Path(file.filename or "video.mp4").suffix or ".mp4"
    stored_filename = f"{project_id}{extension}"
    stored_path = UPLOAD_DIR / stored_filename

    try:
        with stored_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
    finally:
        await file.close()

    raw = await request_transcription(
        stored_path=stored_path,
        original_filename=file.filename or stored_filename,
        api_key=api_key,
        base_url=base_url,
        model=model,
        language=language,
    )

    normalized = normalize_transcript(raw)
    return TranscriptResponse(
        id=project_id,
        filename=file.filename or stored_filename,
        media_url=str(request.url_for("media", path=stored_filename)),
        language=raw.get("language") or language,
        duration=coerce_float(raw.get("duration")),
        text=normalized["text"],
        segments=normalized["segments"],
        words=normalized["words"],
    )


async def request_transcription(
    *,
    stored_path: Path,
    original_filename: str,
    api_key: str,
    base_url: str,
    model: str,
    language: Optional[str],
) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/audio/transcriptions"
    headers = {}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    with stored_path.open("rb") as media:
        multipart = [
            ("file", (original_filename, media, "application/octet-stream")),
            ("model", (None, model)),
            ("response_format", (None, "verbose_json")),
            ("timestamp_granularities[]", (None, "word")),
            ("timestamp_granularities[]", (None, "segment")),
        ]
        if language:
            multipart.append(("language", (None, language)))
        try:
            with httpx.Client(timeout=300) as client:
                response = client.post(endpoint, headers=headers, files=multipart)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach transcription API: {exc}",
            ) from exc

    if response.status_code >= 400:
        detail = response.text[:1000]
        raise HTTPException(status_code=response.status_code, detail=detail)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Transcription API returned non-JSON data.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Unexpected transcription API response.")
    return payload


def normalize_transcript(raw: dict[str, Any]) -> dict[str, Any]:
    words = []
    for item in raw.get("words", []):
        word = normalize_word(item)
        if word:
            words.append(word)

    segments = []
    for item in raw.get("segments", []):
        segment = normalize_segment(item)
        if segment:
            segments.append(segment)

    if segments and words:
        attach_words_to_segments(segments, words)
    elif not segments and words:
        segments = build_segments_from_words(words)
    elif segments and not words:
        words = build_words_from_segments(segments)
        attach_words_to_segments(segments, words)

    text = str(raw.get("text") or " ".join(segment.text for segment in segments)).strip()
    return {"text": text, "segments": segments, "words": words}


def normalize_word(item: Any) -> Optional[Word]:
    if not isinstance(item, dict):
        return None
    text = str(item.get("word") or item.get("text") or "").strip()
    start = coerce_float(item.get("start"))
    end = coerce_float(item.get("end"))
    if not text or start is None or end is None:
        return None
    return Word(text=text, start=start, end=end)


def normalize_segment(item: Any) -> Optional[Segment]:
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()
    start = coerce_float(item.get("start"))
    end = coerce_float(item.get("end"))
    if not text or start is None or end is None:
        return None
    return Segment(text=text, start=start, end=end)


def attach_words_to_segments(segments: list[Segment], words: list[Word]) -> None:
    for segment in segments:
        segment.words = [
            word
            for word in words
            if word.start >= segment.start - 0.05 and word.start <= segment.end + 0.05
        ]


def build_segments_from_words(words: list[Word]) -> list[Segment]:
    segments: list[Segment] = []
    current: list[Word] = []
    for word in words:
        if current and word.start - current[-1].end > 0.8:
            segments.append(segment_from_words(current))
            current = []
        current.append(word)
    if current:
        segments.append(segment_from_words(current))
    return segments


def segment_from_words(words: list[Word]) -> Segment:
    return Segment(
        text=" ".join(word.text for word in words),
        start=words[0].start,
        end=words[-1].end,
        words=words,
    )


def build_words_from_segments(segments: list[Segment]) -> list[Word]:
    words: list[Word] = []
    for segment in segments:
        tokens = segment.text.split()
        if not tokens:
            continue
        step = max((segment.end - segment.start) / len(tokens), 0.01)
        for index, token in enumerate(tokens):
            start = segment.start + index * step
            words.append(Word(text=token, start=start, end=min(start + step, segment.end)))
    return words


def coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
