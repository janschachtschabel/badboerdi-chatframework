import { Injectable } from '@angular/core';

export interface Environment {
  page: string;
  page_context: Record<string, any>;
  device: string;
  locale: string;
  session_duration: number;
  referrer: string;
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
}

export interface PaginationInfo {
  total_count: number;
  skip_count: number;
  page_size: number;
  has_more: boolean;
  collection_id: string;
  collection_title: string;
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
}

export interface ChatMessage {
  id: string;
  sender: 'bot' | 'user';
  content: string;
  cards?: WloCard[];
  quickReplies?: string[];
  debug?: DebugInfo;
  isLoading?: boolean;
  pagination?: PaginationInfo | null;
  visibleCardCount?: number;  // how many cards to show (for client-side paging)
  timestamp: Date;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private baseUrl = '/api';
  private startTime = Date.now();

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
   * Load message history for an existing session (used to restore the
   * conversation when the widget loads on a new page).
   */
  async loadHistory(sessionId: string, limit = 20): Promise<Array<{ role: string; content: string }>> {
    try {
      const resp = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`);
      if (!resp.ok) return [];
      const data = await resp.json();
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
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
    const ctx: Record<string, any> = {};
    const url = new URL(window.location.href);
    const params = url.searchParams;
    if (params.get('q')) ctx['search_query'] = params.get('q');
    if (params.get('node')) ctx['node_id'] = params.get('node');
    if (params.get('collection')) ctx['collection_id'] = params.get('collection');

    // Try to extract from WLO URL patterns
    const path = url.pathname;
    const collMatch = path.match(/\/sammlung\/([^/]+)/);
    if (collMatch) ctx['collection_id'] = collMatch[1];
    const matMatch = path.match(/\/material\/([^/]+)/);
    if (matMatch) ctx['node_id'] = matMatch[1];

    return ctx;
  }
}
