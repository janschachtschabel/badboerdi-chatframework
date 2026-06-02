# B-API Bug-Report: Audio-Endpunkte (TTS + STT) auf Staging defekt

**Datum:** 2026-05-31
**Reporter:** BadBoerdi-Team (WLO-Chatbot)
**Umgebung:** `https://b-api.staging.openeduhub.net/api/v1/llm/openai`
**Auth:** Header `X-API-KEY: <staging-key>`
**Betroffene Komponente:** `org.edusharing.bildungsapi.proxy.service.ProxyService` (Spring/Kotlin, WebFlux + Servlet-MVC)

---

## TL;DR

Die erweiterte B-API leitet **JSON↔JSON-Endpunkte korrekt durch** (chat/completions,
embeddings, moderations, responses — alle getestet, ✅). Die beiden **Audio-Endpunkte
brechen**, weil der Proxy Bodies als JSON deserialisiert/reserialisiert statt sie als
Bytes durchzureichen:

| Endpunkt | Richtung | HTTP | Root-Cause |
|---|---|---|---|
| `POST /audio/speech` (TTS) | Binär-**Response** | **406** / **500** | Proxy erlaubt nur `application/json` als Response-Content-Type |
| `POST /audio/transcriptions` (STT) | Multipart-**Request** | **415** | Proxy konsumiert nur `application/json` (`@RequestBody`) |

---

## Bug 1 — TTS `/audio/speech`

OpenAI liefert die Sprachsynthese als **binären Audio-Stream** (`Content-Type: audio/mpeg`).
Der Proxy lässt diesen Content-Type nicht durch.

### Verhalten je nach `Accept`-Header

| `Accept` (Client) | HTTP | Body |
|---|---|---|
| `audio/mpeg` (das, was das OpenAI-SDK sendet) | **406 Not Acceptable** | leer; Response-Header zeigt `accept: application/json` |
| `*/*` oder kein Accept | **500 Internal Server Error** | Spring-Error-JSON mit Stacktrace |

### Stacktrace (Accept: */* → 500)

```
java.lang.IllegalStateException: Response content type audio/mpeg is not allowed
    at org.edusharing.bildungsapi.proxy.service.ProxyService.processProxyRequest$lambda$32$lambda$28(ProxyService.kt:201)
    at org.edusharing.bildungsapi.proxy.service.ProxyService.processProxyRequest$lambda$32$lambda$29(ProxyService.kt:161)
    at reactor.core.publisher.FluxMapFuseable$MapFuseableSubscriber.onNext(FluxMapFuseable.java:114)
    ... (reactor/WebFlux-Pipeline)
```

→ Bei `ProxyService.kt:201` existiert eine **Allow-List für Response-Content-Types**,
die `audio/mpeg` (und vermutlich `audio/*`, `application/octet-stream`) nicht enthält.
Die 406-Variante ist Spring-Content-Negotiation: der Controller deklariert
`produces = application/json`, daher lehnt er `Accept: audio/mpeg` vorab ab.

### cURL-Repro

```bash
# → 406 (SDK-typischer Accept-Header)
curl -i -X POST "https://b-api.staging.openeduhub.net/api/v1/llm/openai/audio/speech" \
  -H "X-API-KEY: $B_API_KEY_STAGING" \
  -H "Content-Type: application/json" \
  -H "Accept: audio/mpeg" \
  -d '{"model":"gpt-4o-mini-tts","voice":"nova","input":"Hallo Welt"}'

# → 500 (IllegalStateException: audio/mpeg is not allowed)
curl -i -X POST "https://b-api.staging.openeduhub.net/api/v1/llm/openai/audio/speech" \
  -H "X-API-KEY: $B_API_KEY_STAGING" \
  -H "Content-Type: application/json" \
  -H "Accept: */*" \
  -d '{"model":"gpt-4o-mini-tts","voice":"nova","input":"Hallo Welt"}'
```

---

## Bug 2 — STT `/audio/transcriptions`

OpenAI-Transkription erwartet einen **`multipart/form-data`-Request** (Audio-Datei +
Felder `model`, `language`, …). Der Proxy konsumiert nur JSON.

### Stacktrace (415)

```
HTTP 415 — message: Content-Type 'multipart/form-data;boundary=...;charset=UTF-8' is not supported.

org.springframework.web.HttpMediaTypeNotSupportedException: Content-Type 'multipart/form-data;...' is not supported
    at o.s.w.servlet.mvc.method.annotation.AbstractMessageConverterMethodArgumentResolver.readWithMessageConverters(...:235)
    at o.s.w.servlet.mvc.method.annotation.RequestResponseBodyMethodProcessor.readWithMessageConverters(...:181)
    at o.s.w.servlet.mvc.method.annotation.RequestResponseBodyMethodProcessor.resolveArgument(...:156)
    at o.s.w.method.support.InvocableHandlerMethod.invokeForRequest(...:174)
    ... (Servlet-MVC-Pipeline)
```

→ Der Controller bindet den Body via `@RequestBody`
(`RequestResponseBodyMethodProcessor`), für den nur ein **JSON-`HttpMessageConverter`**
registriert ist. Multipart wird gar nicht erst angenommen.

> Hinweis: TTS läuft über die **reaktive** (WebFlux), STT über die **Servlet-MVC**-
> Pipeline. Der Proxy hat also gemischte Stacks bzw. unterschiedliche Controller je
> Pfad — beide aber JSON-zentriert.

### cURL-Repro

```bash
# Test-MP3 vorbereiten (z.B. über natives OpenAI-TTS oder beliebige speech.mp3)
curl -i -X POST "https://b-api.staging.openeduhub.net/api/v1/llm/openai/audio/transcriptions" \
  -H "X-API-KEY: $B_API_KEY_STAGING" \
  -F "file=@speech.mp3;type=audio/mpeg" \
  -F "model=gpt-4o-mini-transcribe" \
  -F "language=de" \
  -F "response_format=text"
# → 415 Unsupported Media Type
```

---

## Lösungsvorschläge

### Empfohlen: Transparenter Byte-Stream-Pass-Through für `/audio/*` (und idealerweise generell)

Die sauberste Lösung: Der Proxy sollte Bodies **nicht deserialisieren/reserialisieren**,
sondern Request- und Response-Bytes verbatim weiterleiten — inklusive Original-
`Content-Type`. Dann funktionieren alle OpenAI-Endpunkte (JSON, Multipart, Binär,
SSE-Streaming) uniform, ohne pro-Content-Type-Sonderbehandlung.

WebFlux-Skizze (reaktiv, ein Handler für alle Pfade):

```kotlin
// Request-Body als DataBuffer/ByteArray durchreichen, Original-Content-Type behalten
webClient.method(request.method)
    .uri(upstreamUri)
    .headers { it.addAll(forwardableRequestHeaders(request)) }   // inkl. Content-Type
    .body(BodyInserters.fromDataBuffers(request.body))           // KEIN JSON-Binding
    .exchangeToMono { resp ->
        resp.bodyToMono(ByteArray::class.java).defaultIfEmpty(ByteArray(0)).map { bytes ->
            ResponseEntity
                .status(resp.statusCode())
                .headers(forwardableResponseHeaders(resp))        // inkl. Original-Content-Type
                .body(bytes)
        }
    }
```

Wichtig: keine `produces`/`consumes`-Restriktion am Controller, keine Content-Type-
Allow-List für die Response (die aktuelle Prüfung in `ProxyService.kt:201` entfällt
bzw. wird auf „alles durchreichen" umgestellt).

### Minimal-Fix (falls der generische Pass-Through zu groß ist)

1. **TTS (`ProxyService.kt:201`):** Die Response-Content-Type-Allow-List um
   `audio/mpeg`, `audio/wav`, `audio/opus`, `audio/aac`, `audio/flac`,
   `application/octet-stream` erweitern. Zusätzlich am Controller `produces`
   so erweitern (oder entfernen), dass `Accept: audio/mpeg` nicht 406 wirft.

2. **STT (Servlet-Controller):** Einen Endpunkt mit
   `consumes = MediaType.MULTIPART_FORM_DATA_VALUE` bereitstellen, der den
   Multipart-Request (Datei + Form-Felder) entgegennimmt und 1:1 an OpenAI
   weiterreicht (z.B. via `MultipartFile` + Re-Assembly oder RestTemplate/WebClient-
   Multipart-Body).

### Verifikation nach Fix

Unser Test-Harness deckt beide Endpunkte ab (TTS→STT-Round-Trip):
`badboerdi/backend/scripts/test_b_api_endpoints.py`. Nach dem Fix sollten in der
Staging-Spalte `tts:*` und `stt:*` auf PASS springen.

---

## Was funktioniert (zur Abgrenzung)

JSON-basierte Endpunkte auf Staging laufen einwandfrei — der Pass-Through-Bug betrifft
ausschließlich Binär/Multipart:

| Endpunkt | Status |
|---|---|
| `GET /models` | ✅ (korrektes OpenAI-Envelope) |
| `POST /chat/completions` (inkl. gpt-5.4-mini) | ✅ |
| `POST /embeddings` | ✅ |
| `POST /moderations` (omni-moderation-latest) | ✅ |
| `POST /responses` (GPT-5 reasoning+verbosity) | ✅ |

## Sekundär-Befund (Prod)

`b-api.prod.openeduhub.net` liefert auf `GET /models` eine **bare JSON-Liste** statt
des OpenAI-`{object,data}`-Envelopes → bricht das offizielle OpenAI-SDK
(`client.models.list()` wirft `AttributeError`). Staging liefert bereits das korrekte
Envelope; Prod ist hier ein älterer Build. Die erweiterten Endpunkte (moderations,
responses, audio) sind auf Prod noch nicht deployed (alle 401).
