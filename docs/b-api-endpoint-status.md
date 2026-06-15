# B-API Endpunkt-Status — Staging vs. Prod

**Stand:** 2026-06-09 (Retest 2) · Ersttest 2026-05-31
**Methode:** OpenAI-Passthrough unter `/api/v1/llm/openai/*`, Auth via Header `X-API-KEY`

| | Staging | Prod |
|---|---|---|
| **Base-URL** | `https://b-api.staging.openeduhub.net/api/v1/llm/openai` | `https://b-api.prod.openeduhub.net/api/v1/llm/openai` |
| **Test-Key (Env)** | `B_API_KEY_STAGING` (`bb6cdf84…`) | `B_API_KEY_PROD` (`d50ea5f9…`) |
| **App-Key (zentral)** | `B_API_KEY` | `B_API_KEY` |
| **Modell-Katalog** | 126 Modelle, korrektes OpenAI-Envelope | 126 Modelle, **bare-list** (bricht SDK `models.list()`) |
| **Build-Stand** | neuerer Build (Erweiterung deployed) | älterer Build (Erweiterung fehlt) |

---

## Endpunkt-Matrix

| Endpunkt | Unsere Nutzung | Staging | Prod |
|---|---|---|---|
| `GET /models` | Katalog-Discovery | ✅ 200 | ⚠️ 200 (bare-list) |
| `POST /chat/completions` | Haupt-Chat, Klassifikation, Judge (inkl. GPT-5) | ✅ 200 | ✅ 200 |
| `POST /embeddings` | RAG-Vektoren (text-embedding-3-small) | ✅ 200 | ✅ 200 |
| `POST /moderations` | Safety-Floor (omni-moderation-latest) | ✅ 200 | ❌ 401 |
| `POST /responses` | GPT-5 reasoning+verbosity (neuer Endpunkt) | ✅ 200 | ❌ 401 |
| `POST /audio/speech` | TTS — Sprachausgabe | ✅ 200 ⚠️ *Cache-Bug* | ❌ 401 |
| `POST /audio/transcriptions` | STT — Spracheingabe | ✅ 200 | ❌ 401 |

**Legende:**
- ✅ funktioniert
- ⚠️ funktioniert, aber mit Abweichung
- ❌ 401 = Route nicht deployed (Prod: Erweiterung fehlt)
- ❌ 500/415 = Route deployed, aber defekt
- ⚠️ Cache-Bug = Erst-Request korrekt, Folge-Requests mit identischem Text liefern korrupte Binaerdaten (siehe `b-api-audio-bug-report.md`)

---

## Interpretation

### Staging — Alle Endpunkte funktionieren, TTS mit Cache-Einschraenkung
Alle Endpunkte funktionieren (chat, embeddings, moderations, responses, **STT, TTS**).
Die urspruenglichen Audio-Bugs (TTS 406/500, STT 415) wurden zwischen 03.06. und 09.06.
gefixt. **Verbleibendes Problem:** Der Prompt-Cache der B-API speichert TTS-Responses
als UTF-8-Strings statt Bytes — bei Cache-Hit (gleicher Input-Text) wird korruptes Audio
mit `Content-Type: application/json` ausgeliefert. Erst-Requests sind immer korrekt.
→ Details + Reproduktion + Fix: `docs/b-api-audio-bug-report.md`

### Prod — nur klassischer Satz
Nur `chat/completions`, `embeddings`, `models` sind geroutet. Moderations, responses
und Audio liefern **401** (Gateway-Route nicht provisioniert — Erweiterung noch nicht
nach Prod promoted). Zusätzlich liefert `/models` eine bare-list statt OpenAI-Envelope.

---

## Konsequenzen für den App-Code

Aktueller Stand in `app/services/llm_provider.py` ist **korrekt und muss so bleiben**,
bis die Erweiterung auf Prod live und der Audio-Bug gefixt ist:

| Feature | Aktueller Pfad | Wann auf B-API umstellbar |
|---|---|---|
| Chat / Embeddings | B-API (`get_client`) | bereits B-API |
| Moderation | nativer OpenAI-Seitenkanal (`get_moderation_client`) | wenn Erweiterung auf Prod live |
| STT (`speech.py`) | nativer OpenAI-Client | wenn Erweiterung auf Prod live (Staging funktioniert bereits) |
| TTS (`speech.py`) | nativer OpenAI-Client | wenn Cache-Bug gefixt **und** Prod-deployed |
| GPT-5 reasoning (`/responses`) | aktuell via `/chat/completions` + `verbosity`/`effort` | optional via B-API `/responses` (auf Staging schon nutzbar) |

Die App nutzt zentral `B_API_KEY` — die getrennten Test-Keys (`B_API_KEY_STAGING`,
`B_API_KEY_PROD`) existieren nur fürs Test-Harness und ändern daran nichts.

---

## Offene Punkte (B-API-Team)

1. ~~**Audio-Bug auf Staging fixen**~~ — **Erledigt** (gefixt zwischen 03.06. und 09.06.).
   TTS-Binär-Response + STT-Multipart + text/plain-Response funktionieren jetzt.
2. **Prompt-Cache fuer TTS fixen** — Binaere Audio-Responses werden als UTF-8-String
   gecacht und dabei korruptiert. Empfehlung: `/audio/speech` vom Cache ausnehmen.
   Details + Reproduktion: `b-api-audio-bug-report.md`.
3. **Erweiterung nach Prod promoten** — moderations / responses / audio sind dort
   noch nicht verfuegbar.
4. **`/models`-Format auf Prod angleichen** — OpenAI-Envelope (`{object,data}`)
   statt bare-list, damit das offizielle SDK `models.list()` nicht bricht. Staging
   macht es bereits korrekt.
