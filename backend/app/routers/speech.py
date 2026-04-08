"""Speech router — STT (Whisper) and TTS (OpenAI) endpoints."""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("de"),
):
    """Transcribe audio to text using OpenAI Whisper."""
    suffix = os.path.splitext(audio.filename or ".webm")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=language,
            )
        return {"text": transcript.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    voice: str = Form("nova"),
    speed: float = Form(1.0),
):
    """Synthesize text to speech using OpenAI TTS."""
    try:
        response = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=speed,
        )

        async def audio_stream():
            async for chunk in response.aiter_bytes(1024):
                yield chunk

        return StreamingResponse(
            audio_stream(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
