# EchoClip

EchoClip is a mobile-first web app for English listening practice. Upload an English video, transcribe it with an OpenAI Whisper-style API, then tap any word or sentence to jump the video to that moment and replay tricky connected speech.

## MVP Features

- Upload a local English video.
- Configure an OpenAI-compatible transcription endpoint.
- Generate sentence and word-level timestamps.
- Tap words or transcript lines to seek the video.
- Loop the current sentence for repeated listening practice.
- Keep provider settings in the browser, with no login.

## Project Structure

```text
backend/   FastAPI API for uploads, media serving, and transcription
frontend/  Vue 3 + Vite mobile-first practice UI
```

## Data Storage

The MVP does not require a database: uploaded media is stored on disk and the latest transcript/settings are kept in the browser. When EchoClip adds history, vocabulary, translation cache, or imported-video records, use SQLite as the local application database.

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
