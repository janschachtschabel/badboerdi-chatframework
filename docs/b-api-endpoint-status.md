# B-API Endpunkt-Status — Staging vs. Prod

**Stand:** 2026-05-31 · getestet mit `backend/scripts/test_b_api_endpoints.py`
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
| `POST /audio/speech` | TTS — Sprachausgabe | ❌ 500 *(Bug)* | ❌ 401 |
| `POST /audio/transcriptions` | STT — Spracheingabe | ❌ 415 *(Bug)* | ❌ 401 |

**Legende:**
- ✅ funktioniert
- ⚠️ funktioniert, aber mit Abweichung
- ❌ 401 = Route nicht deployed (Prod: Erweiterung fehlt)
- ❌ 500/415 = Route deployed, aber defekt (Staging: Binär/Multipart-Bug)

---

## Interpretation

### Staging — Erweiterung live, JSON komplett, Audio defekt
Der erweiterte Build ist da. Alle **JSON↔JSON-Endpunkte funktionieren** (chat,
embeddings, moderations, responses inkl. GPT-5 `/responses` mit reasoning+verbosity).
**Nur die beiden Audio-Endpunkte brechen** — der Spring/Kotlin-Proxy reicht binäre
Responses (TTS → 500) und Multipart-Requests (STT → 415) nicht durch.
→ Details + Fix: `docs/b-api-audio-bug-report.md`

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
| TTS / STT (`speech.py`) | nativer OpenAI-Client | wenn Audio-Bug gefixt **und** Prod-deployed |
| GPT-5 reasoning (`/responses`) | aktuell via `/chat/completions` + `verbosity`/`effort` | optional via B-API `/responses` (auf Staging schon nutzbar) |

Die App nutzt zentral `B_API_KEY` — die getrennten Test-Keys (`B_API_KEY_STAGING`,
`B_API_KEY_PROD`) existieren nur fürs Test-Harness und ändern daran nichts.

---

## Offene Punkte (B-API-Team)

1. **Audio-Bug auf Staging fixen** — TTS-Binär-Response + STT-Multipart-Request
   durchreichen (siehe `b-api-audio-bug-report.md`, Lösung: transparenter
   Byte-Stream-Pass-Through).
2. **Erweiterung nach Prod promoten** — moderations / responses / audio sind dort
   noch nicht verfügbar.
3. **`/models`-Format auf Prod angleichen** — OpenAI-Envelope (`{object,data}`)
   statt bare-list, damit das offizielle SDK `models.list()` nicht bricht. Staging
   macht es bereits korrekt.
4. **Eigener Staging-Key fehlte in der Standard-Env** — `B_API_KEY` enthielt einen
   Prod-Key; der Staging-Key musste separat als `B_API_KEY_STAGING` bereitgestellt
   werden.
