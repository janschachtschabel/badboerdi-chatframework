# Backend — Performance & Anbindungs-Änderungen (2026-06-01)

Begleitend zu den MCP-Optimierungen (siehe `wlo-mcp-server/PERFORMANCE.md`).

## Provider / Modell
- **Chat:** `LLM_PROVIDER=b-api-openai`, `B_API_BASE_URL=…/b-api.staging…`,
  **`LLM_CHAT_MODEL=gpt-5.4-nano`** (zuvor gpt-5.4-mini).
- **Embeddings:** `LLM_EMBED_MODEL=text-embedding-3-small` (1536 dim, DB-kompatibel),
  läuft über den B-API-`/openai`-Passthrough.
- AcademicCloud-Default (in `llm_provider.py`) ist auf `mistral-large-3-675b-instruct-2512`
  gesetzt (nur relevant, falls `LLM_PROVIDER=b-api-academiccloud`). Tool-Calling
  von mistral-large-3 ist getestet (4/4).
- **Betriebshinweis Key:** Die App liest zentral `B_API_KEY`. Für die Staging-
  Anbindung MUSS das der **Staging-Key** sein (`B_API_KEY_STAGING`). Beim
  Backend-Start: `$env:B_API_KEY = $env:B_API_KEY_STAGING` (außerhalb der App,
  kein Secret in committeten Dateien).

## KRITISCHER Fix — `load_dotenv`-Reihenfolge (`app/main.py`)
`load_dotenv()` lief vorher NACH den Router-Imports. Da `llm_service` seinen
OpenAI-Client + das Modell bereits beim **Import** (lru_cache / Modul-Globals)
baut, cachte er die Defaults **vor** der `.env` → **nativer OpenAI-Provider**.
Folge: der Chatbot lief faktisch immer über `api.openai.com`, NIE über die B-API
— `LLM_PROVIDER`/`B_API_BASE_URL`/`LLM_CHAT_MODEL` aus der `.env` wurden ignoriert.
**Fix:** `load_dotenv()` läuft jetzt VOR den App-Imports. Verifiziert: LLM-Calls
gehen an `b-api.staging…/openai/chat/completions`.

## Thinking-Filter (`llm_service.py`)
`strip_reasoning_markers()` entfernt Chain-of-Thought, die ins sichtbare
`content` leakt (`<think>…</think>` / `<thinking>` / `<reasoning>` / `◁think▷` /
gpt-oss-harmony-Marker), inkl. Live-Streaming-Schutz (`_ThinkSafeStreamer` mit
16-Zeichen-Hold-back). No-op für saubere Modelle (mistral, gemma, gpt-5.4, …);
greift nur, wenn ein Thinking-Modell (z.B. deepseek-r1) inline leakt. Angewandt
an allen LLM-Text-Quellen (respond_to_user, content-Fallback, Summary,
Quick-Replies, Lernpfad, Live-Stream). Test: `scripts/test_strip_reasoning.py` (26 Fälle).

## O3 — Vokabular-Cache (`mcp_client.py` + `main.py`)
`lookup_wlo_vocabulary` liefert statische Daten. TTL 1h → **24h**, plus
**Startup-Prewarm** (`prewarm_vocabularies`, 4 Vokabulare parallel, best-effort)
im `lifespan`-Warmup. Lazy-Fallback bleibt. → spart die Vokabular-Round-Trips
auch im ersten Such-Turn.

## Perf-Schalter (Env)
| Env | Default | Wirkung |
|---|---|---|
| `CHAT_DISABLE_SELECT_TOP_CARDS` | aus | `=1` schaltet den optionalen `select_top_cards`-LLM-Turn ab → ~1 Round-Trip/Such-Turn schneller (~1,5–2,5 s); Backend wählt dann deterministisch nach MCP-Ranking. Zum Messen/Tunen. |
| `WLO_POOL_SIZE` (MCP) | 25 | Kandidaten-Pool je Such-Variante (nicht die Trefferzahl). |

## Gemessene Such-Turn-Latenz (Baseline, vor O1-Verdrahtung)
Inhaltssuchen real **9–18 s** Wall-Clock (Faktenfrage ~4 s). Debug-Trace
unterschätzt das (MCP-Tool-Zeit + Request/Response-Overhead außerhalb der
getrackten Segmente). 4 LLM-Calls/Turn (classify + 3 im Tool-Loop). Quellen:
MCP-Suche (~4 s, größter Block), mehrere sequenzielle LLM-Calls, classify auf
nano ~3 s.

## O1 im Backend verdrahtet (2026-06-01) ✅
Der spekulative Prefetch (`chat.py`) feuert für generische Inhalts-/Sammlungs-
Such-Turns **einen** `search_wlo_all`-Call statt `search_wlo_content` +
`search_wlo_collections` (+ topic_pages) einzeln. Beim Auflösen wird das Envelope
in drei Per-Tool-Payloads (`content`/`collections`/`topicPages`, jeweils als
`{total,count,results}`) gesplittet und über den **unveränderten**
`generate_response`/`parse_wlo_cards`/Box-Pfad verarbeitet — kein Downstream-Umbau.
- **Gate:** `search_wlo_all` greift, wenn der aufgelöste Primary-Tool-Name
  content/collections ist UND der Nutzer **nicht** explizit „Themenseite"/
  „Fachportal" getippt hat (`_wants_topic`). Explizite Themenseiten-Anfragen und
  ein LLM-Tool-Hint `search_wlo_topic_pages` nutzen weiter das dedizierte,
  session-stateful Tool. (Wichtig: der Klassifikator routet viele breite Suchen
  auf I03/M06 — daher Gate auf den Tool-Namen, nicht auf den Pattern-Hint.)
- **Live verifiziert:** „Photosynthese" 12,2 s (3 Calls) → **9,1 s (1 Call)**;
  Split `content=10 collections=5 topicPages=1`, Karten korrekt getrennt
  (3 Sammlungen + 3 Inhalte); explizite „Themenseite Klimawandel" weiter über
  den dedizierten Pfad; Faktenfrage unverändert ~5,5 s; keine Tracebacks.
- Implementierung: `spec_is_search_all`/`_search_all_extras`-Flags, Branch im
  Primary-Launch, Envelope-Split im Resolve, Extras-Seed aus dem Split.

## Noch offen (Backend)
- **Themenseiten-INHALTE** (`get_topic_page_content`) sinnvoll integrieren:
  Präsentation wie Sammlungen/Inhalte, **nach Swimlanes gruppiert** (Box-Titel
  Schwimmlinien-Label + „(Auszug)", je Box max. 3 Items + Absprung-Button auf die
  Themenseite), Trigger via neuem Intent/Pattern UND Card-/Quick-Reply-Action.
  **Befund 2026-06-01:** MCP-`get_topic_page_content` war kaputt (0 Swimlanes) —
  Variantenauflösung gefixt (Variante = page_config-Kind, nicht dessen Inhalte) →
  liefert jetzt echte Swimlanes. ABER die Swimlane-Items sind **dynamische
  WIDGET-Knoten** (`ccm:widget_config` = gespeicherte Abfrage), keine festen
  Inhalte → echte Karten je Swimlane = **Widget-Query ausführen** (offene
  Umfang-/Design-Entscheidung). MCP-`json`-Output liefert vorerst das Layout
  (Swimlane-Überschriften + `topicPageUrl`-Absprung).
- Optional: `select_top_cards` dauerhaft abschalten (nach Messung), classify
  beschleunigen, Trace ehrlich machen (echte Wall-Clock + MCP-Segment).
- **O7** (persistenter MCP-Betrieb + Cache) — siehe `wlo-mcp-server/PERFORMANCE.md`.
