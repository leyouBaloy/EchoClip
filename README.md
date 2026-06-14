# EchoClip

EchoClip is a mobile-first web app for English listening practice. Upload an English video, transcribe it with an OpenAI Whisper-style API, then tap any word or sentence to jump the video to that moment and replay tricky connected speech.

## MVP Features

- Upload a local English video.
- Configure an OpenAI-compatible transcription endpoint.
- Generate sentence and word-level timestamps.
- Tap words or transcript lines to seek the video.
- Practice sentence by sentence or play continuously.
- Save uploaded videos and transcripts in a local history library.
- Keep provider settings in the browser, with no login.

## Project Structure

```text
backend/   FastAPI API for uploads, media serving, and transcription
frontend/  Vue 3 + Vite mobile-first practice UI
```

## Data Storage

EchoClip stores uploaded media on disk and saves project history in SQLite:

```text
backend/storage/uploads/
backend/storage/echoclip.sqlite3
```

The history directory page uses this database to reopen previous videos and transcripts. Future features such as vocabulary, translation cache, and imported-video records should also use SQLite.

## Quick Start

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL on your phone or desktop. The default API URL is `http://localhost:8000`.

## Whisper-Compatible API

EchoClip calls:

```text
POST {base_url}/audio/transcriptions
```

with multipart fields:

- `file`
- `model`
- `response_format=verbose_json`
- `timestamp_granularities[]=word`
- `timestamp_granularities[]=segment`
- optional `language`

Your current local model endpoint:

```text
Base URL: http://192.168.2.172:8000/v1
Model: whisper-1
```

For OpenAI, use `https://api.openai.com/v1` with model `whisper-1`.

Some third-party Whisper-compatible providers use slightly different response shapes. The backend normalizes common `words` and `segments` fields into EchoClip's transcript format.
