import { Injectable } from '@angular/core';

export interface Environment {
  page: string;
  page_context: Record<string, any>;
  device: string;
  locale: string;
  session_duration: number;
  referrer: string;
  /** Welle E (2026-05-23): Lotsen-Modus ist immer aktiv. Das Feld bleibt
   *  als Backend-Echo erhalten — wir senden ``true`` mit, damit alte
   *  Backend-Versionen ohne Welle-E-Default-Flip auch greifen. */
  guide_mode?: boolean;
  /** Hostname of the page the widget is embedded in (e.g.
   *  ``wirlernenonline.de``). Sent so the backend can verify the host is
   *  on its allow-list before annotating cards. */
  host?: string;
  /** Webseiten-Tour: "start" (Button "Web-Tour starten") | "tick"
   *  (unsichtbarer Page-Load-Ping für die Ankunfts-Erkennung). Nur bei
   *  Tour-Requests gesetzt. */
  tour_action?: string;
}

export interface WloCard {
  node_id: string;
  title: string;
  description: string;
  disciplines: string[];
  educational_contexts: string[];
  keywords: string[];
  learning_resource_types: string[];
  url: string;
  wlo_url: string;
  preview_url: string;
  license: string;
  publisher: string;
  node_type: string;
  topic_pages: { url: string; target_group: string; label: string; variant_id: string }[];
  /** Set by the backend when guide-mode is on AND the card points to an
   *  allow-listed host. Empty string means "no guide target" — the
   *  frontend hides the "Bring mich hin"-button in that case.
   *  @deprecated Phase 10 — wird durch `link` ersetzt. */
  guide_url?: string;
  /** Card-Pipeline v2 — Single Source of Truth für den UI-Klick-Link.
   *  Vom Backend via `build_card_link` befüllt:
   *   - Themenseiten: `topic_page_url` (extern, kuratiert)
   *   - Sammlungen:  `{repo}/edu-sharing/components/collections?id=…&q=…`
   *   - Einzelinhalte: `url` (extern) im Normal-Modus, sonst Repo-Render.
   *
   *  Phase 4b: wenn vorhanden, bevorzugen wir es gegenüber der alten
   *  URL-Logik. Phase 10 macht es zum Pflichtfeld und entfernt die Alt-
   *  Auswahl-Logik (`guide_url`, `wlo_url`-Fallbacks). */
  link?: string;
}

export interface ToolOutcome {
  tool: string;
  status: string; // success | empty | error | timeout
  item_count: number;
  error: string;
  latency_ms: number;
}

export interface SafetyDecision {
  risk_level: string; // low | medium | high
  blocked_tools: string[];
  enforced_pattern: string;
  reasons: string[];
  stages_run?: string[];
  categories?: Record<string, number>;
  flagged_categories?: string[];
  legal_flags?: string[];
  escalated?: boolean;
}

export interface PolicyDecision {
  allowed: boolean;
  blocked_tools: string[];
  required_disclaimers: string[];
  matched_rules: string[];
}

export interface ContextSnapshot {
  page: string;
  device: string;
  locale: string;
  session_duration: number;
  turn_count: number;
  entities: Record<string, any>;
  recent_signals: string[];
  memory_keys: string[];
  last_intent: string;
  last_state: string;
}

export interface TraceEntry {
  step: string;
  label: string;
  duration_ms: number;
  data: Record<string, any>;
}

export interface DebugInfo {
  persona: string;
  intent: string;
  state: string;
  turn_type: string;
  signals: string[];
  pattern: string;
  entities: Record<string, any>;
  tools_called: string[];
  phase1_eliminated: string[];
  phase2_scores: Record<string, number>;
  phase3_modulations: Record<string, any>;
  // Triple-Schema v2
  outcomes?: ToolOutcome[];
  safety?: SafetyDecision | null;
  confidence?: number;
  policy?: PolicyDecision | null;
  context?: ContextSnapshot | null;
  trace?: TraceEntry[];
  // Phase-1 Pattern-Hint (Shadow-Mode telemetry from the LLM classifier)
  pattern_id_hint?: string | null;
  pattern_reasoning?: string | null;
  llm_engine_match?: boolean | null;
  // Phase A2 Token-Cost-Tracking (per-turn aggregator across all LLM calls)
  // ``per_phase`` (A2.1) keys: classify, tool_loop, response, quick_replies, ...
  token_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    cached_tokens?: number;
    calls?: number;
    models?: Record<string, { prompt: number; completion: number; cached: number; calls: number; hit_rate?: number }>;
    per_phase?: Record<string, { prompt: number; completion: number; cached: number; calls: number; hit_rate?: number }>;
  };
  // Welle C Sprint 6 — Conversation-State-Plausibilität.
  // plausible=false zeigt einen vom Classifier gewählten Übergang, der
  // nicht in der next_likely-Liste des prev-States stand. Telemetrie-only,
  // State wird nicht automatisch korrigiert.
  state_transition?: {
    prev: string;
    next: string;
    plausible: boolean | null;
    reason: string;
    expected_next_likely: string[];
  } | null;
}

export interface PaginationInfo {
  total_count: number;
  skip_count: number;
  page_size: number;
  has_more: boolean;
  collection_id: string;
  collection_title: string;
}

export interface QueryMetaEntry {
  tool_name: string;
  query_type: string;
  search_term: string;
  criteria: Array<{ property: string; values: string[]; label?: string }>;
  pagination: { maxItems: number; skipCount: number; totalResults: number };
  repository_url: string;
  search_url: string;
}

/** Strukturierter Web-Link aus dem Bot-Antwort-Text — typischerweise
 *  RAG-Quellen die das Backend per ``_extract_web_links_from_text`` aus
 *  dem ``content`` rausgezogen hat. Frontend rendert sie im Grouping-
 *  Modus in einer eigenen Box statt im Fließtext.
 *  ``cards``-URLs werden vom Backend ausgeschlossen, sodass Treffer nicht
 *  doppelt erscheinen. */
export interface WebLink {
  title: string;
  url: string;
}

/**
 * Gerahmtes Inline-Dokument im Chat-Verlauf — Lernpfade (M09),
 * KI-generierte Materialien (M10), iterative Edits (M11). Ersetzt
 * das frühere Canvas-Pane: Markdown wird direkt im Verlauf gerendert,
 * aber in einer optisch konsistenten Box (gleicher Rahmen wie die
 * Webseiten-Inhalte-Box, kleinere Schrift).
 *
 * Welle E (2026-05-23).
 */
export interface InlineDocument {
  /** "lernpfad" | "ki_material" | "edit" | "bericht" | "remix" */
  kind: string;
  /** Box-Header über dem Markdown. */
  title: string;
  /** Markdown-Body — wird via existierendem renderMarkdown gerendert. */
  content: string;
  /** Optional: material_type, source_node_id, discipline, etc. */
  meta?: Record<string, any>;
}

/** Eine Schwimmlinie (Abschnitt) einer Themenseite als eigene Box (M16).
 *  Box-Titel im Chat = ``heading`` + „(Auszug)"; max. 3 Karten. */
export interface SwimlaneBox {
  heading: string;
  type?: string;
  cards: WloCard[];
  has_more?: boolean;
}

/** Inhalte EINER Themenseite, nach Schwimmlinien gruppiert (Pattern M16).
 *  Wird ANSTELLE der normalen Boxen gerendert; ``topic_page_url`` ist der
 *  Absprung-Button auf die vollständige Themenseite. */
export interface TopicPageView {
  variant_title: string;
  topic_page_url: string;
  swimlanes: SwimlaneBox[];
}

export interface ChatResponse {
  session_id: string;
  content: string;
  cards: WloCard[];
  follow_up: string;
  quick_replies: string[];
  debug: DebugInfo;
  page_action: { action: string; payload: any } | null;
  pagination: PaginationInfo | null;
  query_metas?: QueryMetaEntry[];
  /** Strukturierte Web-Links die das Backend aus dem ``content`` rausgezogen
   *  hat (RAG-Quellen etc.). Frontend rendert sie im Grouping-Modus in
   *  der separaten Webseiten-Inhalte-Box. Leer = keine Quellen-Links in
   *  dieser Antwort. */
  web_links?: WebLink[];
  /** Lernpfade / KI-Materialien / Edits werden als gerahmte Box im Chat
   *  gerendert (Welle E). Leer = klassische Bot-Bubble. */
  inline_documents?: InlineDocument[];
  /** M16 — Themenseiten-Inhalte (Schwimmlinien-Boxen). Wenn gesetzt, rendert
   *  das Frontend NUR diese Boxen (+ Absprung-Button) statt der normalen. */
  topic_page?: TopicPageView | null;
  /** Echo der Studio-pflegbaren Display-Regeln (01-base/display-rules.yaml).
   *  Frontend stylet Boxen/Schriften anhand dieses Blocks ohne Hard-Coding. */
  display_rules?: Record<string, any>;
  /** Webseiten-Tour-Status. Nur bei Tour-Antworten gesetzt: {active, step,
   *  group}. active=false → Frontend löscht das Tour-Flag (keine Ticks mehr). */
  tour?: { active: boolean; step: string; group: string } | null;
}

/**
 * Server-Sent-Event payload from POST /api/chat/stream.
 *
 * - ``event: 'connected'``  — initial flush, no useful data
 * - ``event: 'phase'``      — Tracer step (start/end/record); ``data`` has
 *                              ``{kind, step, label, data}``
 * - ``event: 'text_delta'`` — Phase-2 token chunk during the final LLM
 *                              call; ``data`` has ``{text}`` (the chunk
 *                              to append to the bot bubble)
 * - intermediate keepalive comments (``: keepalive``) are dropped by the
 *   SSE reader and never reach this callback
 * - ``event: 'result'`` and ``event: 'error'`` are consumed by the
 *   ``sendMessageStream`` Promise — they don't surface here.
 */
export interface ChatStreamEvent {
  event: string;
  data: any;
}

export interface ChatMessage {
  id: string;
  sender: 'bot' | 'user';
  content: string;
  cards?: WloCard[];
  quickReplies?: string[];
  debug?: DebugInfo;
  isLoading?: boolean;
  /** Live status from POST /api/chat/stream while ``isLoading`` is true.
   *  Set by ChatComponent on each tracer ``phase`` event so the UI can
   *  show what the backend is currently doing instead of a static spinner. */
  loadingPhase?: string;
  pagination?: PaginationInfo | null;
  visibleCardCount?: number;  // how many cards to show (for client-side paging)
  queryMetas?: QueryMetaEntry[];
  webLinks?: WebLink[];
  /** Lernpfade / KI-Materialien / Edits als gerahmte Box im Chat (Welle E). */
  inlineDocuments?: InlineDocument[];
  /** M16 — Themenseiten-Inhalte (Schwimmlinien-Boxen) statt normaler Boxen. */
  topicPage?: TopicPageView | null;
  /** Echo der aktiven Display-Regeln aus dem Backend. Per Message
   *  übertragen, damit die jeweilige Bubble auch nach späterem
   *  Studio-Edit ihre Render-Settings behält. */
  displayRules?: Record<string, any>;
  timestamp: Date;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private baseUrl = '/api';
  private startTime = Date.now();
  /** Lotsen-Modus state — set by the widget when the user toggles the
   *  header button. Both fields are forwarded as part of every chat
   *  request's ``environment`` so the backend can attach ``guide_url`` to
   *  cards. Defaults are off / empty until ``setGuideEnv`` is called. */
  private guideMode = false;
  private guideHost = '';

  constructor() {
    // Allow the hosting page to override the backend URL at runtime by
    // setting `window.BOERDI_API_URL` in a small inline script. Useful for
    // a single deployed bundle that talks to a remote backend without a
    // dev-proxy. Falls back to '/api' (the dev proxy / same-origin path).
    try {
      const w: any = typeof window !== 'undefined' ? window : null;
      if (w && typeof w.BOERDI_API_URL === 'string' && w.BOERDI_API_URL.trim()) {
        this.setBaseUrl(w.BOERDI_API_URL.trim());
      }
    } catch { /* ignore */ }
  }

  /** Allow widget host to override the API base URL at runtime. */
  setBaseUrl(url: string) {
    if (!url) return;
    // Strip trailing slash, append /api if missing
    let u = url.replace(/\/$/, '');
    if (!u.endsWith('/api')) u = u + '/api';
    this.baseUrl = u;
  }

  /** Welle E (2026-05-23): host nur als Echo-Feld nötig (Backend nutzt es
   *  fürs ``guide_url``-Annotieren im Repo-Render-Pfad). Der Lotsen-
   *  Mode-Bool ist immer ``true`` und wird vom Widget beim Boot einmal
   *  gesetzt. */
  setGuideEnv(guideMode: boolean, host: string): void {
    this.guideMode = !!guideMode;
    this.guideHost = (host || '').trim().toLowerCase();
  }

  // 2026-06-10: Embed-Modi vollständig entfernt (auch ai-content-enabled) —
  // KI-Inhalte sind immer zugelassen, Layout liegt im Studio.

  async sendMessage(
    sessionId: string,
    message: string,
    env?: Partial<Environment>,
    action?: string,
    actionParams?: Record<string, any>,
  ): Promise<ChatResponse> {
    const environment: Environment = {
      page: env?.page || window.location.pathname,
      page_context: env?.page_context || this.extractPageContext(),
      device: env?.device || this.detectDevice(),
      locale: env?.locale || navigator.language || 'de-DE',
      session_duration: Math.floor((Date.now() - this.startTime) / 1000),
      referrer: env?.referrer || document.referrer || 'direkt',
      guide_mode: env?.guide_mode ?? this.guideMode,
      host: env?.host ?? this.guideHost,
      tour_action: env?.tour_action,
    };

    const body: Record<string, any> = {
      session_id: sessionId,
      message,
      environment,
    };
    if (action) body['action'] = action;
    if (actionParams) body['action_params'] = actionParams;

    const resp = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!resp.ok) throw new Error(`Chat error: ${resp.status}`);
    return resp.json();
  }

  /**
   * Streaming variant of sendMessage. Same payload as POST /api/chat,
   * but listens to the SSE response.
   *
   * The single ``onEvent`` callback receives EVERY non-result SSE event
   * — ``connected``, ``phase`` (tracer step), and ``text_delta`` (Phase-2
   * token chunk). Callers branch on ``evt.event`` to route deltas to a
   * streaming bubble while phase events drive the loading status text.
   *
   * Resolves with the final ChatResponse when the ``result`` event
   * arrives. Rejects on ``error`` events or stream cutoff.
   */
  async sendMessageStream(
    sessionId: string,
    message: string,
    onEvent: (evt: ChatStreamEvent) => void,
    env?: Partial<Environment>,
    action?: string,
    actionParams?: Record<string, any>,
  ): Promise<ChatResponse> {
    const environment: Environment = {
      page: env?.page || window.location.pathname,
      page_context: env?.page_context || this.extractPageContext(),
      device: env?.device || this.detectDevice(),
      locale: env?.locale || navigator.language || 'de-DE',
      session_duration: Math.floor((Date.now() - this.startTime) / 1000),
      referrer: env?.referrer || document.referrer || 'direkt',
      guide_mode: env?.guide_mode ?? this.guideMode,
      host: env?.host ?? this.guideHost,
      tour_action: env?.tour_action,
    };

    const body: Record<string, any> = {
      session_id: sessionId,
      message,
      environment,
    };
    if (action) body['action'] = action;
    if (actionParams) body['action_params'] = actionParams;

    // B9 (2026-06-10): Idle-Watchdog gegen hängende Streams — verbindet
    // der Server, sendet dann aber nie wieder Bytes, blockierte
    // reader.read() vorher unbegrenzt und die Loading-Bubble stand für
    // immer. Abbruch nach 90 s ohne Daten → AbortError → der Aufrufer
    // fällt auf seinen bestehenden Fehlerpfad (Fehler-Bubble) zurück.
    //
    // B10 (2026-06-11): Stale-Timer gegen "Leitung lebt, Server wird aber
    // nicht fertig" — SSE-Keepalive-Kommentare resetten den Byte-Watchdog,
    // d.h. ein hängender LLM-Call hinter dem Stream lief unbegrenzt weiter
    // (beobachtet: 504-Hänger der Staging-B-API, >2 min Spinner). Kommt
    // 100 s lang kein BENANNTES Event (connected/phase/result/error) mehr,
    // brechen wir ab und werfen StreamStaleError — der Aufrufer zeigt dann
    // eine ehrliche Meldung statt still auf POST /chat zu fallen (was die
    // Wartezeit verdoppeln würde). 100 s = Backend-LLM_READ_TIMEOUT (75 s)
    // + Puffer für den OpenAI-SDK-Retry, damit gerettete Antworten den
    // Cut nicht knapp verpassen.
    const abort = new AbortController();
    const IDLE_MS = 90_000;
    const STALE_MS = 100_000;
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setTimeout> | null = null;
    let staleFired = false;
    const armWatchdog = () => {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(() => abort.abort(), IDLE_MS);
    };
    const armStale = () => {
      if (staleTimer) clearTimeout(staleTimer);
      staleTimer = setTimeout(() => { staleFired = true; abort.abort(); }, STALE_MS);
    };
    const clearTimers = () => {
      if (watchdog) clearTimeout(watchdog);
      if (staleTimer) clearTimeout(staleTimer);
    };
    const makeStaleError = () => {
      const err = new Error('Stream stale: keine Server-Events seit 100 s');
      err.name = 'StreamStaleError';
      return err;
    };
    armWatchdog();
    armStale();

    let resp: Response;
    try {
      resp = await fetch(`${this.baseUrl}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(body),
        signal: abort.signal,
      });
    } catch (e) {
      clearTimers();
      throw staleFired ? makeStaleError() : e;
    }
    if (!resp.ok || !resp.body) {
      clearTimers();
      throw new Error(`Chat stream error: ${resp.status}`);
    }

    // SSE parsing — read raw bytes, split on blank-line event boundaries,
    // dispatch by ``event:`` field. Comment lines (``: keepalive``) are
    // ignored. We never trust event payloads beyond the loose JSON shape.
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResult: ChatResponse | null = null;
    let streamError: Error | null = null;

    const dispatchBlock = (rawBlock: string) => {
      let evtName = 'message';
      const dataLines: string[] = [];
      for (const ln of rawBlock.split('\n')) {
        if (!ln || ln.startsWith(':')) continue;  // ignore keepalive comments
        if (ln.startsWith('event:')) {
          evtName = ln.slice(6).trim();
        } else if (ln.startsWith('data:')) {
          dataLines.push(ln.slice(5).trim());
        }
      }
      const dataStr = dataLines.join('\n');
      let parsed: any = {};
      if (dataStr) {
        try { parsed = JSON.parse(dataStr); } catch { parsed = { raw: dataStr }; }
      }
      if (evtName === 'result') {
        finalResult = parsed as ChatResponse;
      } else if (evtName === 'error') {
        streamError = new Error(parsed?.message || 'stream error');
      } else {
        // 'connected' or 'phase' — surface to UI
        try { onEvent({ event: evtName, data: parsed }); } catch { /* never break stream */ }
      }
      // B10: nur BENANNTE Events zählen als Server-Fortschritt. Blöcke aus
      // reinen Keepalive-Kommentaren landen hier als 'message' mit leeren
      // Daten — die halten die Leitung offen, beweisen aber nicht, dass
      // der Server noch arbeitet.
      if (evtName !== 'message') armStale();
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        armWatchdog();  // B9: jede Daten-Lieferung resettet den Idle-Timer
        buffer += decoder.decode(value, { stream: true });
        // SSE event boundary is a blank line (\n\n). Process every full
        // block; keep the (potentially partial) tail in the buffer.
        let idx;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (block.trim()) dispatchBlock(block);
        }
      }
    } catch (e) {
      // B10: Abort durch den Stale-Timer → als StreamStaleError ausweisen,
      // damit der Aufrufer NICHT auf POST /chat zurückfällt.
      throw staleFired ? makeStaleError() : e;
    } finally {
      clearTimers();
    }
    // Flush any trailing block (server closed without final \n\n).
    if (buffer.trim()) dispatchBlock(buffer);

    if (streamError) throw streamError;
    if (!finalResult) throw new Error('Stream ended without a result event');
    return finalResult;
  }

  /**
   * Load message history for an existing session (used to restore the
   * conversation when the widget loads on a new page).
   */
  async loadHistory(
    sessionId: string,
    limit = 20,
  ): Promise<Array<{
    role: string;
    content: string;
    cards?: any[];
    debug?: Record<string, any>;
    /** Aus ``debug._web_links`` (Backend persistiert seit Welle C.5 die
     *  vom Bot-Text extrahierten RAG-/Quellen-Links). Reicht aus, damit
     *  das Frontend nach Restore die ``Webseiten-Inhalte``-Box ohne
     *  Regex-Fallback rendern kann. */
    webLinks?: Array<{ title: string; url: string }>;
    /** Aus ``debug._query_metas`` — enthält ``search_url`` + ``search_term``,
     *  ohne die die Search-CTA ("Alle Treffer in der Suche anzeigen") nach
     *  Restore unsichtbar bleibt (groupedSearchUrl() würde leer liefern). */
    queryMetas?: QueryMetaEntry[];
  }>> {
    try {
      const resp = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`);
      if (!resp.ok) return [];
      const data = await resp.json();
      if (!Array.isArray(data)) return [];
      // Backend persistiert webLinks/queryMetas in ``debug_json`` (siehe
      // chat.py: ``_debug_for_save["_web_links"]`` /
      // ``_debug_for_save["_query_metas"]``). Wir packen sie hier auf die
      // Top-Level der zurückgegebenen Message-Objekte, damit Caller (z.B.
      // ``ChatComponent.restoreHistory``) sie ohne zweites Mapping direkt
      // an ``addBotMessage`` übergeben können.
      return data.map((m: any) => {
        const dbg = m && typeof m === 'object' ? (m.debug || {}) : {};
        // Type-Focus-Marker: wenn die Bot-Antwort im inline-grouping-Mode
        // eine Material-Typ-Antwort war (z.B. "Für Videos zu …"), darf
        // KEINE Webseiten-Inhalte-Box gerendert werden — selbst wenn das
        // alte ``debug._web_links`` aus pre-patch-Zeiten noch Inhalt hat.
        // Wir überstimmen die Stale-Daten hier mit einer leeren Liste.
        const isTypeFocus = !!dbg._type_focus;
        const wl = isTypeFocus
          ? []
          : (Array.isArray(dbg._web_links) ? dbg._web_links : undefined);
        const qm = Array.isArray(dbg._query_metas) ? dbg._query_metas : undefined;
        return { ...m, webLinks: wl, queryMetas: qm };
      });
    } catch {
      return [];
    }
  }

  /** Welle E v4+13: Backend-Capability-Probe für Sprachfunktion.
   *  Bei B-API-Anbindung ist Audio (STT/TTS) deaktiviert — das Widget
   *  blendet dann Mikro-/Lautsprecher-Buttons aus. Fehler/Timeout →
   *  optimistisch ``true`` (Buttons bleiben sichtbar, einzelne Calls
   *  schlagen dann ggf. fehl, aber wir sperren die UI nicht grundlos). */
  async getSpeechEnabled(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.baseUrl}/speech/status`);
      if (!resp.ok) return true;
      const data = await resp.json();
      return data?.enabled !== false;
    } catch {
      return true;
    }
  }

  async transcribe(audioBlob: Blob): Promise<string> {
    const form = new FormData();
    form.append('audio', audioBlob, 'recording.webm');
    form.append('language', 'de');

    const resp = await fetch(`${this.baseUrl}/speech/transcribe`, {
      method: 'POST',
      body: form,
    });

    if (!resp.ok) throw new Error('Transcription failed');
    const data = await resp.json();
    return data.text;
  }

  async synthesize(text: string, signal?: AbortSignal): Promise<Blob> {
    const form = new FormData();
    form.append('text', text);
    form.append('voice', 'nova');

    const resp = await fetch(`${this.baseUrl}/speech/synthesize`, {
      method: 'POST',
      body: form,
      signal,
    });

    if (!resp.ok) throw new Error('Synthesis failed');
    return resp.blob();
  }

  private detectDevice(): string {
    const w = window.innerWidth;
    if (w < 768) return 'mobile';
    if (w < 1024) return 'tablet';
    return 'desktop';
  }

  private extractPageContext(): Record<string, any> {
    // The chat component is ALWAYS embedded as a widget — flag this so the
    // backend's page_action builder routes card-bearing responses to the
    // canvas (canvas_show_cards) instead of the legacy host-page
    // ``show_results`` branch. Without this, /-rooted demo pages like
    // localhost:4200/ trigger ``show_results``, which the widget doesn't
    // handle → cards never reach the canvas.
    const ctx: Record<string, any> = { widget: true };
    const url = new URL(window.location.href);
    const params = url.searchParams;

    // Query params (höchste Priorität — explizit vom Host gesetzt)
    if (params.get('q')) ctx['search_query'] = params.get('q');
    if (params.get('node')) ctx['node_id'] = params.get('node');
    if (params.get('collection')) ctx['collection_id'] = params.get('collection');

    const path = url.pathname;

    // edu-sharing Render-Pattern: /edu-sharing/components/render/<uuid>
    // Wird auf edu-sharing-Instanzen (inkl. Themenseiten-Einbindung) genutzt.
    const renderMatch = path.match(
      /\/components\/render\/([a-f0-9-]{8,})/i
    );
    if (renderMatch && !ctx['node_id']) ctx['node_id'] = renderMatch[1];

    // WLO /sammlung/<id> und /material/<id> (häufigste WLO-Patterns)
    const collMatch = path.match(/\/sammlung\/([^/?#]+)/);
    if (collMatch && !ctx['collection_id']) ctx['collection_id'] = collMatch[1];
    const matMatch = path.match(/\/material\/([^/?#]+)/);
    if (matMatch && !ctx['node_id']) ctx['node_id'] = matMatch[1];

    // WLO Themenseiten: /themenseite/<slug> oder /fachportal/<fach>/<slug>
    // Hier hat die URL nur einen Slug, keine node_id — der Slug wird als
    // Hinweis mitgegeben, das Backend kann daraus einen Lookup machen.
    const themenMatch = path.match(/\/themenseite\/([^/?#]+)/);
    if (themenMatch) {
      ctx['topic_page_slug'] = themenMatch[1];
      ctx['page_type'] = 'themenseite';
    }
    const fachMatch = path.match(/\/fachportal\/([^/?#]+)(?:\/([^/?#]+))?/);
    if (fachMatch) {
      ctx['subject_slug'] = fachMatch[1];
      if (fachMatch[2]) ctx['topic_page_slug'] = fachMatch[2];
      ctx['page_type'] = ctx['page_type'] || 'fachportal';
    }

    // Dokumenten-Titel als zusätzlicher Kontext (semantisch — hilft LLM,
    // wenn node_id nicht auflösbar)
    if (typeof document !== 'undefined' && document.title) {
      ctx['document_title'] = document.title.slice(0, 200);
    }

    return ctx;
  }
}
