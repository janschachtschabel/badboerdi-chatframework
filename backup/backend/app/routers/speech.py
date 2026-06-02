"""Speech router — STT (gpt-4o-mini-transcribe) and TTS (OpenAI) endpoints."""

from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

router = APIRouter()

# Speech always talks directly to an OpenAI-compatible endpoint (STT/TTS
# are OpenAI-native features; the B-API proxies don't forward them). The
# base URL can be overridden via OPENAI_BASE_URL for Azure/LiteLLM/LocalAI,
# which must provide /v1/audio/{transcriptions,speech} too.
#
# Empty ``OPENAI_BASE_URL=`` (common in Docker setups using ``${VAR:-}``
# substitution) must NOT reach the SDK — the OpenAI client reads the
# env var itself when ``base_url=None`` is passed, and an empty string
# crashes httpx with ``UnsupportedProtocol``. Always pass an explicit
# fallback URL.
_openai_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
_openai_base = (
    (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
    or "https://api.openai.com/v1"
)
client = AsyncOpenAI(
    api_key=_openai_key,
    base_url=_openai_base,
)

# ── Speech-to-text configuration ────────────────────────────────────
# Primary model: gpt-4o-mini-transcribe (OpenAI 2025) — notably better than
# the legacy whisper-1 on domain vocabulary, short utterances, and German.
# Env override via STT_MODEL (e.g. "gpt-4o-transcribe" for top quality,
# "whisper-1" as fallback).
STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
# Fallback chain used when the primary model errors out (e.g. unsupported
# audio format, quota, or model access). Ordered most→least capable.
STT_FALLBACKS = ["gpt-4o-transcribe", "whisper-1"]

# Text-to-speech model override. Defaults to tts-1 (fast, cheap). Set
# TTS_MODEL=tts-1-hd for higher-quality synthesis at 2× the cost.
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")

# Domain prompt biases the model towards WLO / OER / German school
# vocabulary. Keeps wrong transcriptions like "Bord-Rechnung" →
# "Bruchrechnung", "Wie loh online" → "WirLernenOnline" etc. in check.
# Keep this under ~224 tokens (OpenAI's hard limit for the prompt field).
WLO_DOMAIN_PROMPT = (
    "Thema: Bildung, Schule, Unterricht, offene Bildungsressourcen (OER). "
    "Plattformen: WLO, WirLernenOnline, edu-sharing, Klexikon, Serlo, ZUM, "
    "Khan Academy, Wikipedia. Rollen: Lehrkraft, Lehrer, Lehrerin, "
    "Lernende, Schüler, Schülerin, Eltern. Inhaltstypen: Arbeitsblatt, "
    "Video, Bild, Quiz, Kurs, Interaktives Medium, Unterrichtsplan, "
    "Audio, Podcast. Bildungsstufen: Grundschule, Sekundarstufe I, "
    "Sekundarstufe II, Hochschule, Berufliche Bildung, Primarstufe, "
    "Elementarbereich. Fächer: Mathematik, Bruchrechnung, Algebra, "
    "Deutsch, Englisch, Französisch, Biologie, Photosynthese, "
    "Zellteilung, Chemie, Physik, Informatik, Geschichte, Erdkunde, "
    "Geographie, Politik, Kunst, Musik, Sport, Religion, Ethik."
)


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("de"),
):
    """Transcribe audio to text.

    Uses gpt-4o-mini-transcribe by default (newer, higher accuracy than
    whisper-1, especially on domain vocabulary). Falls back to
    gpt-4o-transcribe, then whisper-1 on error.
    """
    suffix = os.path.splitext(audio.filename or ".webm")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    last_error: Exception | None = None
    try:
        for model in [STT_MODEL, *STT_FALLBACKS]:
            try:
                with open(tmp_path, "rb") as f:
                    transcript = await client.audio.transcriptions.create(
                        model=model,
                        file=f,
                        language=language,
                        prompt=WLO_DOMAIN_PROMPT,
                        response_format="text",
                    )
                # response_format="text" makes .create() return a str directly
                text = transcript if isinstance(transcript, str) else getattr(transcript, "text", "")
                if model != STT_MODEL:
                    logger.info("STT fell back to %r (primary %r failed)", model, STT_MODEL)
                return {"text": text, "model": model}
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning("STT model %r failed: %s — trying next", model, e)
                continue
        raise HTTPException(status_code=500, detail=f"All STT models failed: {last_error}")
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
            model=TTS_MODEL,
            voice=voice,
            input=text,
            speed=speed,
        )

        audio_bytes = response.read()
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
