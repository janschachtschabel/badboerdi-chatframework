import { Injectable } from '@angular/core';

export interface Environment {
  page: string;
  page_context: Record<string, any>;
  device: string;
  locale: string;
  session_duration: number;
  referrer: string;
  /** True when the user has the Lotsen-Modus toggle active. The backend
   *  uses this together with ``host`` to decide whether to attach
   *  ``guide_url`` to outgoing cards. */
  guide_mode?: boolean;
  /** Hostname of the page the widget is embedded in (e.g.
   *  ``wirlernenonline.de``). Sent so the backend can verify the host is
   *  on its allow-list before annotating cards. */
  host?: string;
  /** Widget-Embed-Modi: vier Schalter, die der einbettende Host setzt,
   *  damit das Widget feature-by-feature minimaler auftritt.
   *  ``undefined`` = Feld nicht mitgeschickt → Backend behält das
   *  Default-Verhalten (alles an). Nur explizites ``false`` schaltet
   *  ein Feature ab. */
  cards_enabled?: boolean;
  canvas_enabled?: boolean;
  ai_content_enabled?: boolean;
  quick_replies_enabled?: boolean;
  /** Welle C.5: Host nutzt gruppierte Treffer-Darstellung (separate Boxen
   *  für Themenseiten/Sammlungen/Webseiten-Inhalte/CTA). Backend zieht
   *  dann Inline-Markdown-Links aus dem Bot-Text in ``web_links``, damit
   *  sie nicht doppelt erscheinen. Default ``undefined``/``false`` → Text
   *  behält seine Inline-Links (Lotsen-Bullets bleiben sichtbar). */
  inline_result_grouping?: boolean;
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
  /** Widget-Embed-Modi — gesetzt vom WidgetComponent aus den HTML-Attributen
   *  ``cards-enabled``, ``canvas-enabled``, ``ai-content-enabled``,
   *  ``quick-replies-enabled``. ``undefined`` heisst "Attribut nicht
   *  gesetzt" — wir schicken das Feld dann gar nicht erst mit, damit das
   *  Backend sein Default-Verhalten beibehält (alles an). Nur explizites
   *  ``false`` wird durchgereicht und schaltet das Feature backend-seitig
   *  ab. */
  private widgetModes: {
    cards?: boolean;
    canvas?: boolean;
    ai?: boolean;
    qr?: boolean;
    inlineResultGrouping?: boolean;
  } = {};

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

  /** Updated by ``WidgetComponent`` whenever the user toggles the
   *  Lotsen-Modus or the page reports its hostname. Both values are
   *  appended to ``environment`` on every outgoing chat request so the
   *  backend (``_attach_guide_urls``) can decide whether to enrich
   *  outgoing cards with a ``guide_url``. */
  setGuideEnv(guideMode: boolean, host: string): void {
    this.guideMode = !!guideMode;
    this.guideHost = (host || '').trim().toLowerCase();
  }

  /** Updated by ``WidgetComponent`` whenever one of the four embed-mode
   *  Inputs is set (or its absence is detected). Pass ``undefined`` for
   *  any flag the host did not set explicitly — that field is then NOT
   *  included in the outgoing ``environment`` block, so older backends
   *  and the default-on flow remain unaffected.
   */
  setWidgetModes(
    cards: boolean | undefined,
    canvas: boolean | undefined,
    ai: boolean | undefined,
    qr: boolean | undefined,
    inlineResultGrouping?: boolean | undefined,
  ): void {
    this.widgetModes = { cards, canvas, ai, qr, inlineResultGrouping };
  }

  /** Build the optional widget-mode fields for the environment block.
   *  Only writes a key when the value is an explicit boolean — undefined
   *  is treated as "host didn't say", and we don't ship that field at all.
   */
  private widgetModeEnv(): Partial<Environment> {
    const m = this.widgetModes;
    const out: Partial<Environment> = {};
    if (typeof m.cards === 'boolean') out.cards_enabled = m.cards;
    if (typeof m.canvas === 'boolean') out.canvas_enabled = m.canvas;
    if (typeof m.ai === 'boolean') out.ai_content_enabled = m.ai;
    if (typeof m.qr === 'boolean') out.quick_replies_enabled = m.qr;
    if (typeof m.inlineResultGrouping === 'boolean') {
      out.inline_result_grouping = m.inlineResultGrouping;
    }
    return out;
  }

  async sendMessage(
    sessionId: string,
    message: string,
    env?: Partial<Environment>,
    action?: string,
    actionParams?: Record<string, any>,
    canvasState?: Record<string, any> | null,
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
      ...this.widgetModeEnv(),
    };

    const body: Record<string, any> = {
      session_id: sessionId,
      message,
      environment,
    };
    if (action) body['action'] = action;
    if (actionParams) body['action_params'] = actionParams;
    if (canvasState) body['canvas_state'] = canvasState;

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
    canvasState?: Record<string, any> | null,
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
      ...this.widgetModeEnv(),
    };

    const body: Record<string, any> = {
      session_id: sessionId,
      message,
      environment,
    };
    if (action) body['action'] = action;
    if (actionParams) body['action_params'] = actionParams;
    if (canvasState) body['canvas_state'] = canvasState;

    const resp = await fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(body),
    });
    if (!resp.ok || !resp.body) {
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
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
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
  ): Promise<Array<{ role: string; content: string; cards?: any[]; debug?: Record<string, any> }>> {
    try {
      const resp = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`);
      if (!resp.ok) return [];
      const data = await resp.json();
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  /** Fetch the last canvas snapshot for a session so the widget can
   *  rehydrate the canvas pane after a page refresh. Backend returns
   *  ``{}`` when no canvas content has been persisted for the session;
   *  the caller treats that as "nothing to restore". */
  async loadCanvas(sessionId: string): Promise<{
    title?: string;
    material_type?: string;
    material_type_label?: string;
    material_type_category?: string;
    markdown?: string;
  }> {
    try {
      const resp = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/canvas`);
      if (!resp.ok) return {};
      const data = await resp.json();
      return (data && typeof data === 'object') ? data : {};
    } catch {
      return {};
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
