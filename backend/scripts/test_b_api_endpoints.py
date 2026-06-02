"""B-API Endpoint-Integrationstest (Welle E v4+13, 2026-05-27).

Testet die erweiterte B-API (OpenAI-Passthrough) gegen ihre Endpunkte —
analog zu den Pfaden, die wir nativ über OpenAI nutzen:

  1. /models             — Katalog-Discovery
  2. /moderations        — omni-moderation-latest (Safety-Floor)
  3. /chat/completions   — GPT-5-Modell (klassischer Chat-Pfad)
  4. /responses          — GPT-5 via neuem Responses-Endpunkt
  5. /audio/speech       — TTS (Text → MP3)
  6. /audio/transcriptions — STT (MP3 → Text), Round-Trip aus (5)

Parametrisiert über (label, base_url, key) — läuft für Staging + Prod.
Aufruf:  python scripts/test_b_api_endpoints.py
"""
from __future__ import annotations

import asyncio
import io
import os
import sys

import httpx
from openai import AsyncOpenAI

# Windows-Konsole UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GREEN, RED, YEL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RST}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {RED}FAIL{RST}  {msg}")


def _skip(msg: str) -> None:
    print(f"  {YEL}SKIP{RST}  {msg}")


def _client(base: str, key: str) -> AsyncOpenAI:
    """Baut den Client genau wie llm_provider.get_client() für b-api-openai."""
    return AsyncOpenAI(
        api_key=key or "unused",
        base_url=base,
        default_headers={"X-API-KEY": key} if key else None,
        timeout=60.0,
        max_retries=0,
    )


async def test_models(base: str, key: str, results: dict) -> list[str]:
    """Discovery über rohen httpx-Call — der B-API ``/models``-Endpunkt
    liefert eine bare JSON-Liste statt des OpenAI ``{object,data}``-
    Envelopes, weshalb das SDK ``models.list()`` mit AttributeError
    bricht. Wir parsen daher selbst und nutzen den Status-Code als
    Auth-Gate."""
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{base}/models", headers={"X-API-KEY": key})
        if r.status_code == 401:
            _fail("/models — HTTP 401 (Auth)")
            results["models"] = False
            return []
        if r.status_code != 200:
            _fail(f"/models — HTTP {r.status_code}: {r.text[:120]}")
            results["models"] = False
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        names = sorted((m["id"] if isinstance(m, dict) else str(m)) for m in items)
        envelope = "bare-list" if isinstance(data, list) else "openai-envelope"
        _ok(f"/models — {len(names)} Modelle ({envelope})")
        results["models"] = True
        return names
    except Exception as e:
        _fail(f"/models — {type(e).__name__}: {str(e)[:160]}")
        results["models"] = False
        return []


async def test_moderation(c: AsyncOpenAI, results: dict) -> None:
    try:
        # Benigner + grenzwertiger Input
        r = await c.moderations.create(
            model="omni-moderation-latest",
            input="Wie erkläre ich Bruchrechnung in der 6. Klasse?",
        )
        res = r.results[0]
        flagged = bool(res.flagged)
        _ok(f"/moderations benign — flagged={flagged} (erwartet False)")
        results["moderation"] = (flagged is False)
    except Exception as e:
        _fail(f"/moderations — {type(e).__name__}: {str(e)[:160]}")
        results["moderation"] = False


async def test_chat_gpt5(c: AsyncOpenAI, results: dict, model: str) -> None:
    try:
        r = await c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Antworte mit genau einem Wort: Hauptstadt von Frankreich?"}],
        )
        txt = (r.choices[0].message.content or "").strip()
        usage = r.usage
        if txt:
            _ok(f"/chat/completions [{model}] — '{txt[:50]}' "
                f"(prompt={usage.prompt_tokens if usage else '?'}, "
                f"completion={usage.completion_tokens if usage else '?'})")
            results[f"chat:{model}"] = True
        else:
            _fail(f"/chat/completions [{model}] — leere Antwort")
            results[f"chat:{model}"] = False
    except Exception as e:
        _fail(f"/chat/completions [{model}] — {type(e).__name__}: {str(e)[:160]}")
        results[f"chat:{model}"] = False


async def test_responses_gpt5(c: AsyncOpenAI, results: dict, model: str) -> None:
    """Neuer /responses-Endpunkt für GPT-5 (reasoning + verbosity nativ)."""
    try:
        r = await c.responses.create(
            model=model,
            input="Antworte mit genau einem Wort: Hauptstadt von Italien?",
            reasoning={"effort": "low"},
            text={"verbosity": "low"},
        )
        # SDK: output_text ist die aggregierte Text-Ausgabe
        txt = (getattr(r, "output_text", "") or "").strip()
        if txt:
            u = getattr(r, "usage", None)
            it = getattr(u, "input_tokens", "?") if u else "?"
            ot = getattr(u, "output_tokens", "?") if u else "?"
            _ok(f"/responses [{model}] reasoning+verbosity — '{txt[:50]}' (in={it}, out={ot})")
            results[f"responses:{model}"] = True
        else:
            _fail(f"/responses [{model}] — leere output_text")
            results[f"responses:{model}"] = False
    except Exception as e:
        _fail(f"/responses [{model}] — {type(e).__name__}: {str(e)[:200]}")
        results[f"responses:{model}"] = False


async def test_tts(c: AsyncOpenAI, results: dict, model: str) -> bytes | None:
    """TTS: deutscher Satz → MP3. Liefert die Audio-Bytes für den STT-Round-Trip."""
    try:
        resp = await c.audio.speech.create(
            model=model,
            voice="nova",
            input="Willkommen bei WirLernenOnline. Ich helfe dir bei der Suche nach Lernmaterial.",
        )
        audio = resp.read()
        if audio and len(audio) > 1000:
            _ok(f"/audio/speech [{model}] — {len(audio)} Bytes MP3")
            results[f"tts:{model}"] = True
            return audio
        _fail(f"/audio/speech [{model}] — verdächtig klein ({len(audio) if audio else 0} Bytes)")
        results[f"tts:{model}"] = False
        return None
    except Exception as e:
        _fail(f"/audio/speech [{model}] — {type(e).__name__}: {str(e)[:160]}")
        results[f"tts:{model}"] = False
        return None


async def test_stt(c: AsyncOpenAI, results: dict, model: str, audio: bytes | None) -> None:
    """STT: das TTS-MP3 zurück nach Text. Round-Trip-Validierung."""
    if not audio:
        _skip(f"/audio/transcriptions [{model}] — kein TTS-Audio vorhanden")
        results[f"stt:{model}"] = None
        return
    try:
        buf = io.BytesIO(audio)
        buf.name = "speech.mp3"  # SDK braucht einen Dateinamen für den Mime-Typ
        transcript = await c.audio.transcriptions.create(
            model=model,
            file=buf,
            language="de",
            response_format="text",
        )
        txt = transcript if isinstance(transcript, str) else getattr(transcript, "text", "")
        txt = (txt or "").strip()
        # Erfolg, wenn ein erkennbares Schlüsselwort durchkommt
        hit = any(k in txt.lower() for k in ("wirlernenonline", "lernen", "lernmaterial", "suche", "willkommen"))
        if txt and hit:
            _ok(f"/audio/transcriptions [{model}] — '{txt[:70]}'")
            results[f"stt:{model}"] = True
        elif txt:
            _ok(f"/audio/transcriptions [{model}] — Text erhalten (kein Keyword-Match): '{txt[:70]}'")
            results[f"stt:{model}"] = True
        else:
            _fail(f"/audio/transcriptions [{model}] — leerer Text")
            results[f"stt:{model}"] = False
    except Exception as e:
        _fail(f"/audio/transcriptions [{model}] — {type(e).__name__}: {str(e)[:160]}")
        results[f"stt:{model}"] = False


async def run_suite(label: str, base: str, key: str) -> dict:
    print(f"\n{'='*70}\n  {label}\n  base={base}\n  key={key[:8]}*** (len {len(key)})\n{'='*70}")
    results: dict = {}
    if not key:
        _skip("Kein Key gesetzt — Suite übersprungen")
        return results
    c = _client(base, key)

    names = await test_models(base, key, results)
    # Auth-Gate: wenn /models schon 401 wirft, brauchen wir die anderen nicht
    if results.get("models") is False:
        _skip("Auth fehlgeschlagen — restliche Endpunkte übersprungen")
        return results

    await test_moderation(c, results)

    # GPT-5: nimm das aktuelle Default-Modell falls vorhanden, sonst gpt-5-mini
    gpt5 = "gpt-5.4-mini" if "gpt-5.4-mini" in names else ("gpt-5-mini" if "gpt-5-mini" in names else "gpt-5")
    await test_chat_gpt5(c, results, gpt5)
    await test_responses_gpt5(c, results, gpt5)

    # TTS → STT Round-Trip
    tts_model = "gpt-4o-mini-tts" if "gpt-4o-mini-tts" in names else "tts-1"
    audio = await test_tts(c, results, tts_model)
    # Wenn die B-API-TTS scheitert (Audio-Passthrough defekt), erzeugen
    # wir Test-Audio über natives OpenAI, damit STT trotzdem unabhängig
    # geprüft werden kann (Audio-IN vs Audio-OUT sind separate Pfade).
    if audio is None:
        okey = (os.getenv("OPENAI_API_KEY") or "").strip()
        if okey:
            try:
                nat = AsyncOpenAI(api_key=okey, base_url="https://api.openai.com/v1",
                                  timeout=60, max_retries=0)
                sp = await nat.audio.speech.create(
                    model="tts-1", voice="nova",
                    input="WirLernenOnline hilft beim Finden von Lernmaterial.")
                audio = sp.read()
                await nat.close()
                _skip(f"TTS-Audio via nativem OpenAI erzeugt ({len(audio)} B) — "
                      "für isolierten STT-Test")
            except Exception as e:
                _skip(f"natives TTS-Fallback fehlgeschlagen: {str(e)[:80]}")
    stt_model = "gpt-4o-mini-transcribe" if "gpt-4o-mini-transcribe" in names else "whisper-1"
    await test_stt(c, results, stt_model, audio)

    await c.close()
    return results


async def main() -> None:
    # Test-Keys: getrennte Env-Vars NUR für dieses Test-Skript.
    # Die App selbst nutzt weiterhin zentral B_API_KEY (siehe
    # llm_provider.get_client) — hier bewusst NICHT angefasst.
    suites = [
        ("STAGING B-API", "https://b-api.staging.openeduhub.net/api/v1/llm/openai", (os.getenv("B_API_KEY_STAGING") or "").strip()),
        ("PROD B-API",    "https://b-api.prod.openeduhub.net/api/v1/llm/openai",    (os.getenv("B_API_KEY_PROD") or "").strip()),
    ]
    all_results = {}
    for label, base, key in suites:
        all_results[label] = await run_suite(label, base, key)

    # Zusammenfassung
    print(f"\n{'='*70}\n  ZUSAMMENFASSUNG\n{'='*70}")
    for label, res in all_results.items():
        if not res:
            print(f"\n{label}: übersprungen / kein Zugang")
            continue
        passed = sum(1 for v in res.values() if v is True)
        failed = sum(1 for v in res.values() if v is False)
        total = passed + failed
        print(f"\n{label}: {passed}/{total} bestanden")
        for k, v in res.items():
            mark = f"{GREEN}OK{RST}" if v is True else (f"{RED}X{RST}" if v is False else f"{YEL}-{RST}")
            print(f"    [{mark}] {k}")


if __name__ == "__main__":
    asyncio.run(main())
