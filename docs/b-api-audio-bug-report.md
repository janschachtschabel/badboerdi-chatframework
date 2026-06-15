# B-API Bug-Report: Audio-Endpunkte (TTS + STT) auf Staging

**Erstellt:** 2026-05-31 · **Retest 1:** 2026-06-03 · **Retest 2:** 2026-06-09
**Reporter:** BadBoerdi-Team (WLO-Chatbot)
**Umgebung:** `https://b-api.staging.openeduhub.net/api/v1/llm/openai`
**Auth:** Header `X-API-KEY: <staging-key>`

---

## Status-Zusammenfassung

| Bug | 29.05. | 03.06. | 09.06. | Status |
|---|---|---|---|---|
| TTS: `Accept: audio/mpeg` blockiert (406) | **406** | **406** | **200** | **Gefixt** |
| TTS: `Accept: */*` blockiert (500) | **500** | 200 | 200 | **Gefixt** |
| TTS: wav/opus falscher Content-Type | _(maskiert)_ | `application/json` | `audio/wav` / `audio/opus` | **Gefixt** |
| STT: Multipart-Request abgelehnt (415) | **415** | 200 | 200 | **Gefixt** |
| STT: `text/plain`-Response blockiert (500) | _(maskiert)_ | **500** | **200** | **Gefixt** |
| STT: `srt`/`vtt`-Response blockiert (500) | _(maskiert)_ | **500** | **200** | **Gefixt** |
| **TTS: Prompt-Cache korruptiert Binaer-Responses** | _(unbekannt)_ | _(verdeckt)_ | **Nachgewiesen** | **Offen** |

> **Fazit 09.06.:** Alle urspruenglichen Proxy-Bugs (Content-Type-Allow-List,
> `produces`-Annotation, Multipart-Binding) sind behoben. Es verbleibt ein
> **Cache-Bug**, der TTS-Audio ab dem zweiten Abruf desselben Textes zerstoert.

---

## Retest-Ergebnisse (09.06.)

### TTS (`POST /audio/speech`) — Alle Formate und Modelle funktionieren

| Modell | Accept | response_format | HTTP | Response-CT | Valide? |
|---|---|---|---|---|---|
| `gpt-4o-mini-tts` | `audio/mpeg` | mp3 | **200** | `audio/mpeg` | MPEG III, 24 kHz |
| `gpt-4o-mini-tts` | `*/*` | mp3 | **200** | `audio/mpeg` | MPEG III |
| `gpt-4o-mini-tts` | `audio/*` | mp3 | **200** | `audio/mpeg` | MPEG III |
| `gpt-4o-mini-tts` | `*/*` | wav | **200** | `audio/wav` | RIFF/WAVE PCM 16-bit |
| `gpt-4o-mini-tts` | `*/*` | opus | **200** | `audio/opus` | Ogg/Opus |
| `gpt-4o-mini-tts` | `*/*` | aac | **200** | `audio/aac` | MPEG ADTS AAC LC |
| `gpt-4o-mini-tts` | `*/*` | flac | **200** | `audio/flac` | FLAC 16-bit |
| `gpt-4o-mini-tts` | `*/*` | pcm | **200** | `audio/pcm` | Raw PCM |
| `tts-1` | `audio/mpeg` | mp3 | **200** | `audio/mpeg` | MPEG III, 160 kbps |
| `tts-1-hd` | `audio/mpeg` | mp3 | **200** | `audio/mpeg` | MPEG III |

### STT (`POST /audio/transcriptions`) — Alle Modelle und Formate funktionieren

| Modell | response_format | HTTP | Ergebnis |
|---|---|---|---|
| `whisper-1` | `json` | **200** | `{"text":"Hallo, Welt! Dies ist ein Test..."}` |
| `whisper-1` | `text` | **200** | Plaintext-Transkription |
| `whisper-1` | `verbose_json` | **200** | JSON mit Segmenten + Timestamps |
| `whisper-1` | `srt` | **200** | SubRip-Untertitel |
| `whisper-1` | `vtt` | **200** | WebVTT-Untertitel |
| `gpt-4o-mini-transcribe` | `json` | **200** | JSON mit Token-Usage |
| `gpt-4o-mini-transcribe` | `text` | **200** | Plaintext-Transkription |
| `gpt-4o-transcribe` | `json` | **200** | JSON mit Token-Usage |
| `gpt-4o-transcribe` | `text` | **200** | Plaintext-Transkription |

> Hinweis: `verbose_json` liefert 400 bei `gpt-4o-mini-transcribe` und
> `gpt-4o-transcribe` — das ist ein **OpenAI-seitiges** Limit (diese Modelle
> unterstuetzen nur `json` und `text`), kein B-API-Bug.

---

## Verbleibender Bug: Prompt-Cache korruptiert TTS-Audio

### Symptom

Der **erste** TTS-Request fuer einen gegebenen Input-Text liefert korrektes Audio.
**Jeder weitere** Request mit identischem Text liefert eine korrupte, unabspielbare
Datei mit falschem Content-Type.

| | Erster Request (Cache-Miss) | Folge-Requests (Cache-Hit) |
|---|---|---|
| **HTTP** | 200 | 200 |
| **Content-Type** | `audio/mpeg` | `application/json` |
| **Latenz** | 1,0–2,0 s (Upstream-Call) | 0,2–0,3 s (aus Cache) |
| **Datei** | Valides MPEG III | Unabspielbar (`file: data`) |
| **Groesse** (gleicher Text) | 54.528 Bytes | 95.043 Bytes (+74%) |
| **Header `Content-Security-Policy`** | vorhanden | fehlt |
| **Header `Vary: Accept-Encoding`** | fehlt | vorhanden |

### Root-Cause

Der Prompt-Cache der B-API speichert Response-Bodies als **UTF-8-Strings** statt
als rohe Bytes. Binaere Audio-Daten enthalten Bytes >0x7F, die kein valides UTF-8
sind. Der UTF-8-Decoder ersetzt diese durch den Unicode-Replacement-Character
**U+FFFD** (`ef bf bd`, 3 Bytes). Dadurch waechst die Datei (~74%) und die
Binaerstruktur wird **unwiederbringlich zerstoert**.

```
Original-MP3 (Hex):  ff fb 90 00 ... (MPEG-Sync-Header)
Cache-Hit (Hex):     ef bf bd ef bf bd ef bf bd ef bf bd 00 5a ...
                     ^^^^^^^^ ^^^^^^^^ ^^^^^^^^ ^^^^^^^^
                     U+FFFD   U+FFFD   U+FFFD   U+FFFD   (4 Bytes → 12 Bytes)
```

In der gecachten Response aus dem Test: **20.561 Replacement-Characters** in einer
54-KB-Datei.

### Beweisfuehrung (systematische Tests 09.06.)

| Test | Aufbau | Ergebnis |
|---|---|---|
| **T1** — 6x identischer Input, `Accept: audio/mpeg` | Gleicher JSON-Body | #1 korrekt (1,3 s), **#2–6 kaputt** (0,2 s, identischer MD5) |
| **T2** — 6x identischer Input, `Accept: */*` | Gleicher JSON-Body | **6/6 kaputt** (Cache war von T1 warm) |
| **T3** — Identischer Input, Accept wechselnd | audio/mpeg → */* → audio/mpeg → ... | #1 korrekt, **#2–6 kaputt** (Cache ignoriert Accept-Header) |
| **T4** — 6x **einzigartiger** Input | Jeder Request anderer Text | **6/6 korrekt** (1–9 s, kein Cache-Hit) |
| **T5** — MD5-Vergleich der Cache-Hits | #2–6 aus T1 | Alle **bitidentisch** (`6b55c0...`) |
| **T7** — STT 3x identischer Request | Gleiche Audio-Datei | **3/3 korrekt** (auch Cache-Hits) |
| **T8** — Cache-TTL pruefen | T1-Input nach ~3 Min abrufen | Immer noch gecacht, gleicher MD5 |

**Schlussfolgerung:** Der Cache-Key ist der Request-Body (Input-Text + Modell).
Bei Cache-Hit wird die gespeicherte (korrupte) Response zurueckgegeben,
**unabhaengig vom Accept-Header**. Der Cache betrifft **nur TTS**, weil STT-
Responses (JSON/Text) UTF-8-sicher sind und die Serialisierung ueberleben.

### Warum nicht alle Endpunkte betroffen sind

| Endpunkt | Response-Typ | UTF-8-sicher? | Cache-Problem? |
|---|---|---|---|
| `POST /chat/completions` | JSON | Ja | Nein |
| `POST /embeddings` | JSON | Ja | Nein |
| `POST /moderations` | JSON | Ja | Nein |
| `POST /responses` | JSON | Ja | Nein |
| `POST /audio/transcriptions` (STT) | JSON / Text | Ja | **Nein** (getestet) |
| `POST /audio/speech` (TTS) | **Binaer** (MP3/WAV/...) | **Nein** | **Ja** |

### Reproduktion (Copy-Paste)

```bash
KEY="$B_API_KEY_STAGING"
URL="https://b-api.staging.openeduhub.net/api/v1/llm/openai/audio/speech"
BODY='{"model":"gpt-4o-mini-tts","voice":"nova","input":"Identischer Text zum Testen."}'

# Request 1 — Cache-Miss, korrekt:
curl -s -o first.mp3 -w "HTTP %{http_code} | CT: %{content_type} | %{size_download}B\n" \
  -X POST "$URL" -H "X-API-KEY: $KEY" \
  -H "Content-Type: application/json" -H "Accept: audio/mpeg" -d "$BODY"
file first.mp3
# → MPEG ADTS, layer III, v2, 128 kbps, 24 kHz, Monaural

# Request 2 — Cache-Hit, kaputt:
curl -s -o second.mp3 -w "HTTP %{http_code} | CT: %{content_type} | %{size_download}B\n" \
  -X POST "$URL" -H "X-API-KEY: $KEY" \
  -H "Content-Type: application/json" -H "Accept: audio/mpeg" -d "$BODY"
file second.mp3
# → data (NICHT MPEG! Content-Type: application/json)

md5sum first.mp3 second.mp3
# → unterschiedliche Hashes, second.mp3 ist ~74% groesser
```

### Fix-Empfehlung

**Option A (empfohlen):** TTS-Pfad (`/audio/speech`) vom Prompt-Cache **ausnehmen**.
TTS-Responses sind nicht idempotent (OpenAI generiert jedes Mal leicht anderes Audio)
und binaer — Caching bringt hier keinen Vorteil und korruptiert die Daten.

**Option B:** Den Cache-Speicher fuer binaere Responses auf `byte[]` umstellen statt
UTF-8-String. Dann muss der Cache pruefen, ob der Response-Content-Type `audio/*`
oder `application/octet-stream` ist, und die Bytes roh speichern.

**Option C (Workaround, Client-seitig):** Jedem TTS-Request ein einzigartiges
Element hinzufuegen (z.B. nicht-hoerbaren Unicode-Suffix im Input), damit der
Cache-Key nie kollidiert. Ist ein Hack, kein Fix.

### Verifikation nach Fix

```bash
# Zweimal denselben Text — beide muessen valides MPEG sein:
for i in 1 2; do
  curl -s -o "test_${i}.mp3" -w "Run $i: HTTP %{http_code} | CT: %{content_type}\n" \
    -X POST "$URL" -H "X-API-KEY: $KEY" \
    -H "Content-Type: application/json" -H "Accept: audio/mpeg" \
    -d '{"model":"gpt-4o-mini-tts","voice":"nova","input":"Fix-Verifikation."}'
  file "test_${i}.mp3"
done
# Beide: MPEG ADTS, layer III
# Beide: Content-Type: audio/mpeg
```

---

## Referenz: Urspruengliche Bugs (gefixt seit 09.06.)

<details>
<summary>Bug 1 — TTS 406/500 (gefixt)</summary>

### Verhalten (29.05.–03.06.)

| `Accept` (Client) | HTTP | Root-Cause |
|---|---|---|
| `audio/mpeg` (SDK-Standard) | **406 Not Acceptable** | Controller `produces = application/json` |
| `*/*` | **500 Internal Server Error** | `ProxyService.kt:201` Allow-List ohne `audio/*` |

### Stacktrace (500)
```
java.lang.IllegalStateException: Response content type audio/mpeg is not allowed
    at o.e.b.proxy.service.ProxyService.processProxyRequest$lambda$32$lambda$28(ProxyService.kt:201)
```

**Fix (deployed ~06.06.):** Allow-List erweitert, `produces`-Annotation entfernt/erweitert.

</details>

<details>
<summary>Bug 2 — STT 415 (gefixt)</summary>

### Verhalten (29.05.)

```
HTTP 415 — Content-Type 'multipart/form-data;...' is not supported
org.springframework.web.HttpMediaTypeNotSupportedException
```

Der Controller band via `@RequestBody` mit nur JSON-Converter. Multipart wurde nicht akzeptiert.

**Fix (deployed ~03.06.):** Multipart-Binding implementiert, Request wird an OpenAI durchgereicht.

</details>

<details>
<summary>Bug 3 — STT text/plain 500 (gefixt)</summary>

### Verhalten (03.06.)

Multipart-Upload funktionierte, aber bei `response_format=text` blockte
`ProxyService.kt:175` den Response-Content-Type `text/plain;charset=utf-8`.

```
java.lang.IllegalStateException: Response content type text/plain;charset=utf-8 is not allowed
    at o.e.b.proxy.service.ProxyService.processProxyRequest$lambda$1$9(ProxyService.kt:175)
```

**Fix (deployed ~06.06.):** `text/*` zur Allow-List hinzugefuegt.

</details>

---

## Was funktioniert (zur Abgrenzung)

JSON-basierte Endpunkte auf Staging laufen einwandfrei:

| Endpunkt | Status |
|---|---|
| `GET /models` | ✅ (korrektes OpenAI-Envelope) |
| `POST /chat/completions` (inkl. GPT-5) | ✅ |
| `POST /embeddings` | ✅ |
| `POST /moderations` (omni-moderation-latest) | ✅ |
| `POST /responses` (GPT-5 reasoning+verbosity) | ✅ |
| `POST /audio/speech` (TTS) — Erst-Request | ✅ |
| `POST /audio/speech` (TTS) — Cache-Hit | **Korrupt** (siehe oben) |
| `POST /audio/transcriptions` (STT) — alle Formate | ✅ (auch Cache-Hits) |

## Sekundaer-Befund (Prod)

`b-api.prod.openeduhub.net` liefert auf `GET /models` eine **bare JSON-Liste** statt
des OpenAI-`{object,data}`-Envelopes → bricht das offizielle OpenAI-SDK
(`client.models.list()` wirft `AttributeError`). Staging liefert bereits das korrekte
Envelope; Prod ist hier ein aelterer Build. Die erweiterten Endpunkte (moderations,
responses, audio) sind auf Prod noch nicht deployed (alle 401).
