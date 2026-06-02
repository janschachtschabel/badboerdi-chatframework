import {
  Component, ElementRef, HostListener, NgZone, ViewChild, AfterViewChecked, OnInit, OnChanges, OnDestroy, signal, Input,
  Output, EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import {
  ApiService, ChatMessage, ChatResponse, ChatStreamEvent,
  WloCard, DebugInfo, PaginationInfo,
} from '../services/api.service';
import { getCardPrimaryUrl } from '../services/card-utils';
import { BOERDI_LOGO_SVG, BOERDI_LOGO_DATA_URL } from '../shared/boerdi-logo';
import { ICONS } from '../shared/icons';
import { SafeSvgPipe } from '../shared/safe-svg.pipe';

/** Mapping vom ``@@ICON:NAME@@``-Sentinel auf das deutsche Material-Label.
 *  Wird als Hover-Tooltip auf Inline-Card-Link-Icons gesetzt, damit User
 *  sehen ob ein Inline-Treffer eine Themenseite, eine Sammlung oder ein
 *  konkreter Material-Typ (Video / Arbeitsblatt / Quiz / …) ist.
 *  Quelle der Namen: ``backend/app/routers/chat.py::_icon_name_for_card``. */
const INLINE_ICON_LABEL: Record<string, string> = {
  topic: 'Themenseite',
  auto_stories: 'Sammlung',
  play_circle: 'Video',
  article: 'Arbeitsblatt',
  videogame_asset: 'Interaktiver Inhalt',
  headphones: 'Audio',
  quiz: 'Quiz',
  image: 'Präsentation',
  edit_note: 'Übung',
  school: 'Kurs',
  language: 'Webseite',
  menu_book: 'Material',
};

/** Payload shape for the ``badboerdi:guide-suggestion`` CustomEvent and the
 *  ``(guideSuggestion)`` Output. Emitted at most once per bot-turn, when the
 *  host page has ``emit-guide-suggestion="true"`` and the response contains
 *  at least one Lotsen-eligible target (``card.link`` or ``card.guide_url``).
 *
 *  Hosts can listen via:
 *
 *  ```js
 *  window.addEventListener('badboerdi:guide-suggestion', (e) => {
 *    const s = e.detail; // GuideSuggestionPayload
 *    // show banner / switch iframe / etc.
 *  });
 *  ```
 *
 *  Or via Angular ``(guideSuggestion)`` Output when not consuming as Custom
 *  Element. Same payload either way.
 */
export interface GuideSuggestionPayload {
  /** Repo-aware target URL — for collections ``…/components/collections?id=…``,
   *  for content ``…/components/render/<uuid>``, for topic-pages the curated
   *  external page URL. Identical to ``card.link``. */
  url: string;
  /** Card title (display label). */
  title: string;
  /** edu-sharing node-ID (UUID). Empty when the card has no node_id. */
  node_id: string;
  /** Three-way classification: ``'topic_page'`` | ``'collection'`` | ``'content'``. */
  node_type: string;
  /** User query that produced this result — useful for context-aware host
   *  reactions (e.g. logging, analytics, pre-filling adjacent UIs). */
  query: string;
  /** All Lotsen-eligible cards from this turn, in display order. Lets hosts
   *  build their own ranked UI instead of being limited to the top-1. Max
   *  length equals the number of cards in the response. */
  alternatives: Array<Pick<GuideSuggestionPayload, 'url' | 'title' | 'node_id' | 'node_type'>>;
}

/** Welle C.4 (2026-05): Payload für ``badboerdi:routing-debug``.
 *  Auf ``window`` gefeuert nach jedem Bot-Turn, wenn der Host
 *  ``emit-routing-debug="true"`` gesetzt hat. Quellen-Daten kommen aus
 *  dem ``DebugInfo``-Block der ChatResponse — keine zusätzlichen
 *  Backend-Calls nötig.
 *
 *  Hosts können das Routing live beobachten und z.B. ein Routing-Panel
 *  oder A/B-Logging implementieren:
 *
 *  ```js
 *  window.addEventListener('badboerdi:routing-debug', (e) => {
 *    const d = e.detail; // RoutingDebugPayload
 *    console.log(d.pattern, d.intent, d.state, d.tools);
 *  });
 *  ```
 */
export interface RoutingDebugPayload {
  /** User-Nachricht, die den Turn ausgelöst hat. */
  message: string;
  /** Gewählter Pattern-ID (z.B. ``PAT-07``). */
  pattern: string;
  /** Classifier-Intent (z.B. ``INT-W-03``). */
  intent: string;
  /** Conversation-State (z.B. ``state-5``). */
  state: string;
  /** Persona-ID (z.B. ``P-W-LK``). */
  persona: string;
  /** Tatsächlich aufgerufene MCP-Tools für diesen Turn. */
  tools_called: string[];
  /** RAG-Areas, die in den Kontext geflossen sind (Pattern-gesteuert ab Welle B.4). */
  rag_areas: string[];
  /** Pattern.sources (``mcp``, ``rag``, ``web``). */
  sources: string[];
  /** Modulator-Ergebnis: tone/length/formality/card_text_mode aus tone-modifiers.yaml. */
  modifier: {
    tone: string;
    length: string;
    formality: string;
    card_text_mode: string;
    /** True wenn der Modifier den Pattern-Default überschrieben hat. */
    override: boolean;
  };
  /** Classifier-Signale (z.B. ``["orientierungssuchend", "neugierig"]``). */
  signals: string[];
}

@Component({
  selector: 'badboerdi-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, SafeSvgPipe],
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
})
export class ChatComponent implements OnInit, OnChanges, AfterViewChecked, OnDestroy {
  /** Material-Symbols-Icon-Set, im Template referenzierbar. */
  readonly ICONS = ICONS;
  /** Template kann ``Math.max(...)`` nicht direkt aufrufen — daher exposen.
   *  Wird für die Debug-Trace-Parallel-Bars gebraucht (Welle E). */
  readonly Math = Math;
  @ViewChild('messagesContainer') messagesContainer!: ElementRef;
  @ViewChild('inputField') inputField!: ElementRef;

  messages = signal<ChatMessage[]>([]);
  userInput = '';
  isLoading = false;
  sessionId = '';
  showDebug = false;
  latestDebug: DebugInfo | null = null;

  // Topic page dropdown
  openTopicDropdown: string | null = null;

  // Speech
  isRecording = false;
  isSpeaking = false;
  autoSpeak = false;
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private currentAudio: HTMLAudioElement | null = null;
  /** Monotonically increasing token for the active speakChunked call.
   *  Each new call bumps it; older callers compare against this on exit
   *  and skip resetting ``isSpeaking`` if they've been superseded. Stops
   *  the "spricht …" indicator from sticking when a sentence's audio
   *  ``onended`` fires unusually late or when speakChunked is overlapped
   *  by a new turn's auto-speak. */
  private speakingToken = 0;

  // Page action callback (for host page integration)
  onPageAction: ((action: any) => void) | null = null;

  // ── Widget integration inputs ──────────────────────────────────
  /** API base URL (e.g. "https://api.wlo.de"). Will be normalized to /api. */
  @Input() apiUrl = '';
  /** Optional explicit page context, JSON string or object. */
  @Input() pageContext: string | Record<string, any> = '';
  /** Persist session in localStorage so chat continues across page loads. */
  @Input() persistSession: boolean | string = true;
  /** Storage key for the persisted session id. */
  @Input() sessionKey = 'boerdi_session_id';
  /** Cookie domain for cross-subdomain session sharing.
   *  Set to e.g. ".wirlernenonline.de" to share the session-id cookie
   *  between suche.wirlernenonline.de, wp-test.wirlernenonline.de etc.
   *  Empty string (default) = pure localStorage, no cookie written
   *  (origin-isolated, sameas before).
   */
  @Input() sessionCookieDomain = '';
  /** Cookie lifetime in seconds. Default 30 days.
   *  Only meaningful when sessionCookieDomain is set.
   */
  @Input() sessionCookieMaxAge: number | string = 30 * 24 * 60 * 60;
  /** Override the initial greeting. */
  @Input() greeting = '';
  /** Show the debug-toggle (🔍) button in the header. Default true.
   *  Set to false to hide the developer debug panel toggle in production. */
  @Input() showDebugButton: boolean | string = true;
  /** Show the language/voice buttons in header (🔊 TTS) and footer (🎤 STT).
   *  Default true. Set to false to disable speech features in the UI. */
  @Input() showLanguageButtons: boolean | string = true;
  /** Welle E (2026-05-23): KI-Content abschaltbar pro Embed (Host-Override).
   *  Bei ``false`` lehnt der Bot Material/Lernpfad-Erstellung mit der
   *  Alt-Response aus ``widget-modes.yaml`` ab. Das Studio-Default
   *  ist ``true``. */
  @Input() aiContentEnabled: boolean | string = true;
  /** Vom Widget durchgereichte Trusted-Hosts-Whitelist (Backend-Default
   *  aus ``guide-mode.yaml`` + ``trusted-domains``-HTML-Attribut, mergiert).
   *  Verwendung: Inline-Markdown-Links zu Hosts auf dieser Liste öffnen
   *  same-tab (damit das Outgoing-Rewrite ``?bsid=`` greift und die
   *  Session erhalten bleibt); externe Hosts öffnen target="_blank". */
  @Input() trustedHosts: string[] = [];
  /** Lotsen-Modus: passive Top-Result-Emission an die Host-Seite.
   *  Bei ``true`` wird bei JEDEM Bot-Turn, der Cards mit Lotsen-Link enthält,
   *  ein ``badboerdi:guide-suggestion``-CustomEvent auf ``window`` gefeuert
   *  (Payload siehe ``maybeDispatchGuideSuggestion``). Damit kann der Host
   *  (Edu-Sharing-Sidebar, WP-Theme, etc.) auf den Top-1-Treffer reagieren,
   *  ohne dass der User explizit "lotse mich" sagt.
   *  Default ``false`` — Hosts ohne Listener-Setup sehen keinen Unterschied. */
  @Input() emitGuideSuggestion: boolean | string = false;
  /** Welle C.4 (2026-05): Wenn ``true``, wird nach jedem Bot-Turn
   *  ein ``badboerdi:routing-debug``-CustomEvent auf ``window`` gefeuert
   *  mit Routing-Telemetrie (Pattern, Intent, State, Persona, Tools,
   *  Tonalitäts-Modifier). Gedacht für Embed-Hosts, die das Routing live
   *  beobachten wollen (Studio-Debug-Panel, Demo-Inspector, A/B-Logging).
   *  Default ``false`` — keine zusätzlichen Events ohne Opt-In. */
  @Input() emitRoutingDebug: boolean | string = false;
  /** Emitted for every page_action from the backend (host + widget integration). */
  @Output() pageAction = new EventEmitter<{ action: string; payload: any }>();
  /** Emitted on the host page whenever the bot's response contains at least
   *  one allow-listed Lotsen-target — same payload as the
   *  ``badboerdi:guide-suggestion`` CustomEvent. Gated by ``emitGuideSuggestion``. */
  @Output() guideSuggestion = new EventEmitter<GuideSuggestionPayload>();
  /** Emitted nach jedem Bot-Turn mit Routing-Telemetrie. Gated durch
   *  ``emitRoutingDebug``. Payload: ``RoutingDebugPayload``. */
  @Output() routingDebug = new EventEmitter<RoutingDebugPayload>();

  private parsedPageContext: Record<string, any> = {};

  // Scroll target: ID of the message to scroll into view
  private scrollTargetId: string | null = null;
  /** Flag: scroll messages-Container ans Ende bei der nächsten gerenderten
   *  View. Wird beim Wiederherstellen der History (``restoreHistory``) und
   *  auf externen ``scrollToLatest()``-Aufruf (z.B. WidgetComponent beim
   *  ``openChatbot()``) gesetzt. Konsumiert in ``ngAfterViewChecked``, sodass
   *  der Scroll erst NACH Angular's CD + Browser-Paint passiert (wenn
   *  ``messagesContainer.scrollHeight`` die finale Höhe hat). */
  private scrollToBottomOnNextRender = false;

  /** Logo als Data-URL — funktioniert in Web-Components zuverlässig.
   *  Quelle: shared/boerdi-logo.ts */
  readonly boerdiLogo = BOERDI_LOGO_DATA_URL;

  constructor(private api: ApiService, private zone: NgZone, private sanitizer: DomSanitizer) {}

  /** Coerces a boolean | string input (HTML attributes always arrive as
   *  strings) into a true boolean. */
  private modeFlag(v: boolean | string): boolean {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.toLowerCase() !== 'false';
    return true;
  }
  get aiContentEnabledBool(): boolean { return this.modeFlag(this.aiContentEnabled); }
  // Welle E (2026-05-23) — Compat-Hüllen: alte Pfade lesen diese Bools
  // immer noch. Statt jede Stelle anzufassen, geben wir konstantes ``true``
  // zurück. Die View-Conditionals werden separat aufgeräumt.
  get cardsEnabledBool(): boolean { return true; }
  get quickRepliesEnabledBool(): boolean { return true; }
  get inlineResultGroupingBool(): boolean { return true; }
  // Welle E: hideCards/guideModeActive sind Compat-Hüllen (Toggle entfernt).
  readonly hideCards: boolean = false;
  readonly guideModeActive: boolean = true;

  /** Wird vom Angular-Bindings-Layer aufgerufen wenn ein ``@Input()`` neu
   *  gesetzt wird. Wir nutzen es, um den ``_renderCache`` zu invalidieren
   *  wenn die Trusted-Hosts-Liste ankommt — Backend's ``guide-mode``-
   *  Config lädt async beim Bootstrap, daher kann ein erstes Render mit
   *  leerer Liste cached werden bevor die echte Liste eintrifft. Ohne
   *  Cache-Reset würden Links zu Trusted-Hosts trotzdem ``target="_blank"``
   *  zeigen, weil der Cache-Hit das Re-Rendering überspringt. */
  ngOnChanges(changes: { trustedHosts?: { previousValue?: string[]; currentValue?: string[]; firstChange?: boolean } }) {
    const c = changes.trustedHosts;
    if (!c || c.firstChange) return;
    const prev = JSON.stringify(c.previousValue || []);
    const curr = JSON.stringify(c.currentValue || []);
    if (prev !== curr) {
      this._renderCache.clear();
    }
  }

  /** Check ob ein Hostname auf der vom Widget durchgereichten Trusted-Hosts-
   *  Liste steht. Match-Logik wie ``WidgetComponent._isTrustedHost``:
   *  exakter Match ODER Subdomain (entry "openeduhub.net" matched alle
   *  ``*.openeduhub.net``). Empty list → returns false → all hosts open
   *  in new tab. */
  /** Such-CTA target=_self wenn URL auf trusted Host zeigt (Welle E,
   *  2026-05-24) — Repo-Search-Links sollen im selben Tab öffnen, da
   *  der User danach üblicherweise auf der Treffer-Seite weiterarbeitet
   *  und nicht den Chat-Kontext verliert. Externe Hosts bleiben _blank. */
  isTrustedSearchUrl(msg: ChatMessage): boolean {
    const url = this.groupedSearchUrl(msg);
    if (!url) return false;
    try {
      const u = new URL(url, window.location.href);
      if (u.origin === window.location.origin) return true;
      return this.isHostTrusted(u.hostname.toLowerCase());
    } catch {
      return false;
    }
  }

  /** Kern-WLO-Domains, die IMMER als vertrauenswürdig gelten — unabhängig
   *  davon, ob die dynamische Trusted-Liste (vom Widget via guide-mode-Config
   *  ins ``[trustedHosts]``-Input) zum Render-Zeitpunkt schon geladen ist.
   *  Verhindert, dass „Achtung! Externe URL." fälschlich bei WLO-Repo-/
   *  Themenseiten-Links erscheint (alle auf ``*.openeduhub.net``), wenn die
   *  Backend-Liste noch nicht angekommen ist. Die dynamische Liste ergänzt
   *  zusätzliche Hosts (Dev, localhost, *.nip.io …) on top. */
  private static readonly CORE_TRUSTED_DOMAINS = [
    'openeduhub.net', 'wirlernenonline.de', 'openeduhub.de', 'wissenlebtonline.de',
  ];

  isHostTrusted(host: string): boolean {
    const h = (host || '').toLowerCase();
    if (!h) return false;
    const dynamic = Array.isArray(this.trustedHosts) ? this.trustedHosts : [];
    // ``*.example.com`` und ``example.com`` gleichwertig: ``*.`` strippen,
    // der ``endsWith('.X')``-Check deckt Subdomains automatisch ab.
    for (const t of [...ChatComponent.CORE_TRUSTED_DOMAINS, ...dynamic]) {
      const tn = (t || '').toLowerCase().replace(/^\*\./, '');
      if (!tn) continue;
      if (h === tn || h.endsWith('.' + tn)) return true;
    }
    return false;
  }

  ngOnInit() {
    // Configure API base URL if provided as attribute
    if (this.apiUrl) {
      this.api.setBaseUrl(this.apiUrl);
    }

    // Welle E v4+13: Sprachfunktion-Capability vom Backend abfragen. Bei
    // B-API-Anbindung ist Audio (STT/TTS) deaktiviert → Buttons ausblenden.
    // Fire-and-forget; UI startet optimistisch mit Buttons sichtbar.
    this.api.getSpeechEnabled()
      .then((ok) => { this.speechBackendEnabled = ok; })
      .catch(() => { /* optimistisch sichtbar lassen */ });

    // Welle E (2026-05-23): einziger Embed-Override ist aiContentEnabled.
    // Wir setzen ihn nur dann explizit ``false``, wenn der Host es
    // aktiv abgeschaltet hat — sonst Backend-Default greift.
    this.api.setWidgetModes(
      this.aiContentEnabledBool ? undefined : false,
    );

    // Parse page-context attribute (JSON string or already an object)
    if (typeof this.pageContext === 'string' && this.pageContext.trim()) {
      try { this.parsedPageContext = JSON.parse(this.pageContext); }
      catch { this.parsedPageContext = { raw: this.pageContext }; }
    } else if (typeof this.pageContext === 'object' && this.pageContext) {
      this.parsedPageContext = this.pageContext as Record<string, any>;
    }

    // Session persistence — 3-Stufen-Kaskade:
    //   A) URL-?bsid=… (Cross-TLD-Handoff von einer anderen Domain)
    //   B) Cookie     (Cross-Subdomain via sessionCookieDomain)
    //   C) localStorage (Origin-spezifischer Fallback / Default)
    // Ergebnis: erste Stufe, die einen validen "bb-<uuid>"-String findet,
    // gewinnt. Schreibt dann zurück in alle aktiven Storages, damit der
    // nächste Page-Load egal welcher Stufe folgt.
    const persist = this.persistSession === true || this.persistSession === 'true';
    let resumed = false;
    if (persist) {
      try {
        const found = this._resolvePersistedSessionId();
        if (found) {
          this.sessionId = found;
          resumed = true;
        } else {
          this.sessionId = this.generateSessionId();
        }
        // In ALLE aktiven Storages schreiben — damit der nächste Page-Load
        // (egal von welcher Stufe getrieben) die ID findet.
        this._writeSessionEverywhere(this.sessionId);
      } catch {
        this.sessionId = this.generateSessionId();
      }
    } else {
      this.sessionId = this.generateSessionId();
    }

    if (resumed) {
      // Try to restore the conversation from the backend, then — falls eine
      // Web-Tour läuft — den Ankunfts-Tick feuern (Bot erkennt die Seite).
      this.restoreHistory().then(() => this._maybeStartTourTick());
    } else {
      this.showGreeting();
      this._maybeStartTourTick();
    }
  }

  /** Zentrale Begruessung mit Quick-Reply-Einstiegspunkten.
   *  Wird bei neuem Widget-Start, leerer Session-History und nach Restart
   *  aufgerufen, damit der User immer das gleiche freundliche Onboarding
   *  sieht. Das `greeting`-Input ueberschreibt den Default-Text.
   */
  private showGreeting(): void {
    const text = this.greeting
      ||
      'Hey, schön dass du da bist! Ich bin Boerdi, die schlaue Eule von '
      + 'WirLernenOnline. Suchst du etwas Bestimmtes oder willst du erstmal '
      + 'schauen, was du hier machen kannst?';
    // Einstiegspunkte: werden bei Klick als normale User-Message gesendet
    // und vom Classifier in die passenden Intents (INT-W-01, -02, -03, -11)
    // geroutet — kein extra Backend-Code noetig.
    const replies = [
      'Wie kannst du mir helfen?',
      'Ich suche etwas zu einem Thema.',
      'Was ist WissenLebtOnline?',
      ChatComponent.TOUR_START_LABEL,
    ];
    this.addBotMessage(text, false, undefined, replies);
  }

  /** Fetch message history for the current session and render it. */
  private async restoreHistory() {
    const history = await this.api.loadHistory(this.sessionId, 20);
    if (!history || history.length === 0) {
      // Empty session — show greeting like a fresh chat.
      this.showGreeting();
      return;
    }
    // Hardcodierte Anfangs-Begrüßung IMMER an den Anfang setzen — sie
    // wird vom Backend NICHT persistiert (kein User-Turn → kein
    // ``save_message``), würde nach Reopen/Cross-TLD-Handoff also
    // verschwinden. Hier prepended, damit der Verlauf konsistent wirkt
    // (Welle C.5, 2026-05).
    this.showGreeting();
    // Die Greeting-QR-Pillen sollen NUR am ganz frischen Chat-Anfang
    // klickbar bleiben — sobald echte Konversation folgt (also: History
    // hat irgendeine User- oder Assistant-Nachricht), strippen wir die
    // QRs der gerade prepended Greeting-Bubble. Sonst hätte der User
    // mitten im Verlauf plötzlich wieder die Einstiegs-Buttons.
    this.messages.update(msgs => {
      if (!msgs.length) return msgs;
      const head = msgs[0];
      return [{ ...head, quickReplies: undefined }, ...msgs.slice(1)];
    });
    for (const m of history) {
      const content = (m.content || '').trim();
      if (!content) continue;
      if (m.role === 'user') {
        this.addUserMessage(content);
      } else if (m.role === 'assistant') {
        // Cards / Web-Links / Query-Metas aus dem persistierten Backend-
        // State mit-restoren, damit Bot-Antworten nach Refresh/Page-Nav
        // nicht als nackter Text ohne ihre Kacheln, ohne die Webseiten-
        // Inhalte-Box und ohne den "Treffer zur Suche"-CTA dastehen.
        // Backend persistiert ``cards`` direkt + ``web_links`` /
        // ``query_metas`` in ``debug_json`` (siehe chat.py:
        // ``_debug_for_save["_web_links"]`` / ``["_query_metas"]``).
        const cards = Array.isArray(m.cards) ? m.cards : undefined;
        const webLinks = Array.isArray((m as any).webLinks) ? (m as any).webLinks : undefined;
        const queryMetas = Array.isArray((m as any).queryMetas) ? (m as any).queryMetas : undefined;
        // debug mitgeben (enthält pattern="TOUR:…" + _type_focus): so werden
        // auch wiederhergestellte Tour-Nachrichten als solche erkannt und die
        // Result-Group-Boxen unterdrückt (siehe isTourMessage).
        this.addBotMessage(content, false, cards, undefined, (m as any).debug, undefined, queryMetas, webLinks);
      }
    }
    // Nach dem Wiederherstellen ans Ende scrollen. Wir delegieren komplett
    // an den Auto-Follow-Mechanismus aus ``scrollToLatest()`` — der setzt
    // den permanenten MutationObserver auf, der jede zukünftige DOM-Änderung
    // im Messages-Container am Tail hält (bis der User aktiv hochscrollt).
    // So ist's egal wann genau die History-Bubbles fertig gerendert sind:
    // jede einzelne Mutation triggert einen erneuten Scroll.
    this.scrollToLatest();
  }

  /** Public API: clear current session and start fresh. Callable from host page. */
  resetSession() {
    try { localStorage.removeItem(this.sessionKey); } catch { /* ignore */ }
    this._deleteCookie(this.sessionKey);
    this.sessionId = this.generateSessionId();
    this._writeSessionEverywhere(this.sessionId);
    this.messages.set([]);
    this.latestDebug = null;
    this.addBotMessage(this.greeting || 'Hallo! Wie kann ich dir helfen?');
  }

  /** Public API: update page context at runtime (for SPAs without reload). */
  updateContext(ctx: Record<string, any>) {
    this.parsedPageContext = { ...this.parsedPageContext, ...ctx };
  }

  ngAfterViewChecked() {
    if (this.scrollTargetId) {
      this.scrollToMessage(this.scrollTargetId);
      this.scrollTargetId = null;
    }
    if (this.scrollToBottomOnNextRender) {
      this.scrollToBottom();
      this.scrollToBottomOnNextRender = false;
    }
  }

  ngOnDestroy(): void {
    // Auto-Follow-Tail-Observer aufräumen. Beim Schließen des Panels
    // wird die Chat-Component via *ngIf zerstört — wenn wir den Observer
    // hier nicht trennen, behält er Referenzen auf das zerstörte DOM und
    // wird erst beim GC eingesammelt.
    try { this._autoFollowObserver?.disconnect(); } catch { /* ignore */ }
    this._autoFollowObserver = null;
    try {
      if (this._autoFollowScrollListener && this.messagesContainer?.nativeElement) {
        this.messagesContainer.nativeElement.removeEventListener('scroll', this._autoFollowScrollListener);
      }
    } catch { /* ignore */ }
    this._autoFollowScrollListener = null;
  }

  async sendMessage(text?: string) {
    const msg = text || this.userInput.trim();
    if (!msg || this.isLoading) return;

    this.userInput = '';
    this.addUserMessage(msg);
    this.isLoading = true;

    // Add loading indicator and scroll to it
    const loadingId = this.addBotMessage('', true);
    this.scrollTargetId = loadingId;

    try {
      const envOverride = Object.keys(this.parsedPageContext).length
        ? { page_context: this.parsedPageContext }
        : undefined;

      // Phase-1 streaming — uses POST /api/chat/stream which emits SSE
      // ``phase`` events live during classify + tool-loop, so the loading
      // bubble shows what the bot is doing instead of a static spinner.
      // Falls back to non-streaming sendMessage on any stream error.
      //
      // (Phase-2 token streaming was rolled back — it only kicked in for
      // the final ~1-2 seconds and the per-token re-render flickered. The
      // backend's Streaming-Helper stays in place but is not wired up;
      // ``text_delta`` events therefore never arrive and the conditional
      // below is a defensive no-op kept for future reuse.)
      const onEvent = (evt: { event: string; data: any }) => {
        if (evt.event === 'text_delta') return;
        const label = this.formatPhaseLabel(evt);
        if (!label) return;
        this.updateLoadingPhase(loadingId, label);
      };
      let resp: ChatResponse;
      try {
        resp = await this.api.sendMessageStream(this.sessionId, msg, onEvent, envOverride);
      } catch (streamErr) {
        // Stream-API failed (network, proxy, parser) → silent fallback to
        // the legacy non-streaming endpoint so the user still gets an
        // answer. This also covers older backends without the /stream route.
        // eslint-disable-next-line no-console
        console.warn('chat stream failed, falling back to POST /chat:', streamErr);
        resp = await this.api.sendMessage(this.sessionId, msg, envOverride);
      }

      // Remove loading, add real response
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination, resp.query_metas, resp.web_links, resp.inline_documents, resp.display_rules, resp.topic_page);
      this.scrollTargetId = botMsgId;
      // Die Web-Tour kann auch per getippter Trigger-Phrase starten — dann
      // kommt die Tour-Antwort über DIESEN Normalpfad (nicht startTour()).
      // Flag pflegen, damit der unsichtbare Tick nach dem nächsten
      // Seitenwechsel feuert und die Tour weiterläuft.
      this._applyTourState(resp);

      this.latestDebug = resp.debug;

      // Emit query metadata as custom event for the hosting page / widget
      if (resp.query_metas?.length) {
        window.dispatchEvent(new CustomEvent('badboerdi:query-meta', {
          detail: { queries: resp.query_metas },
        }));
      }

      // Handle page action (share with host page / widget parent)
      this.dispatchPageAction(resp.page_action);

      // Lotsen-Modus: if the user explicitly asked to be brought somewhere
      // (z.B. „bring mich hin zur Themenseite Photosynthese") AND the
      // response has at least one allow-listed card, ALSO dispatch a
      // ``navigate`` page-action so the widget shows the confirmation
      // banner. ``guide_url`` is only set when guide-mode is on and the
      // host is on the allow-list, so the presence of one is the gate.
      this.maybeDispatchGuideNavigate(msg, resp.cards);

      // Passive Top-1-Anzeige für externe Hosts (opt-in via
      // ``emit-guide-suggestion="true"``). Wird bei JEDEM Bot-Turn mit
      // mindestens einer Lotsen-eligiblen Card gefeuert, damit Embed-Hosts
      // (Edu-Sharing, WP-Sidebar, Drittsysteme) automatisch reagieren
      // können — ohne dass der User explizit "lotse mich" sagen muss.
      this.maybeDispatchGuideSuggestion(msg, resp.cards);

      // Welle C.4: Routing-Telemetrie für Debug-Inspektion (opt-in via
      // ``emit-routing-debug="true"``). Zeigt Pattern/Intent/State/Tools
      // jedem Embed-Host, der das Routing nachvollziehen will.
      this.maybeDispatchRoutingDebug(msg, resp.debug);

      // Auto-speak if enabled — always interrupt any previous playback
      // so a new response after a quick user follow-up is also spoken.
      if (this.autoSpeak && resp.content) {
        this.autoSpeakText(resp.content);
      }
    } catch (err) {
      this.removeMessage(loadingId);
      const errId = this.addBotMessage('Entschuldigung, es ist ein Fehler aufgetreten. Bitte versuche es erneut.');
      this.scrollTargetId = errId;
    }

    this.isLoading = false;
    setTimeout(() => this.inputField?.nativeElement?.focus(), 100);
  }

  onQuickReply(reply: string) {
    // Web-Tour-Startbutton: kein normaler Chat-Turn, sondern Tour-Einstieg.
    if (reply === ChatComponent.TOUR_START_LABEL) {
      this.startTour();
      return;
    }
    this.sendMessage(reply);
  }

  /** Magic-prefix für Backend → Frontend Konvention. Backend signalisiert
   *  einen "Bring mich hin"-Quick-Reply mit dieser Marker-Form:
   *
   *    __guide__|<Anzeige-Label>|<vollständige URL>
   *
   *  Frontend rendert den Eintrag als dunkelblauen Button (siehe HTML),
   *  Klick navigiert im aktuellen Tab statt eine Folgenachricht zu senden. */
  private static readonly GUIDE_QR_PREFIX = '__guide__|';

  isGuideQuickReply(qr: string): boolean {
    if (!this.guideModeActive) return false;   // toggle off → never a guide button
    return typeof qr === 'string' && qr.startsWith(ChatComponent.GUIDE_QR_PREFIX);
  }

  /** True if a quick-reply should be hidden entirely. The only reason
   *  to hide one is: it's a Guide-QR (magic-prefix) but the user has
   *  Lotsen-Modus disabled — the link wouldn't make sense. */
  shouldHideQuickReply(qr: string): boolean {
    if (this.guideModeActive) return false;
    return typeof qr === 'string' && qr.startsWith(ChatComponent.GUIDE_QR_PREFIX);
  }

  /** Extrahiert den Anzeige-Text aus einem Guide-QR-String. */
  guideQuickReplyLabel(qr: string): string {
    if (!this.isGuideQuickReply(qr)) return qr;
    const rest = qr.slice(ChatComponent.GUIDE_QR_PREFIX.length);
    const sepIdx = rest.indexOf('|');
    if (sepIdx === -1) return rest.trim() || 'Bring mich hin';
    const label = rest.slice(0, sepIdx).trim();
    return label || 'Bring mich hin';
  }

  /** Extrahiert die URL aus einem Guide-QR-String. URLs dürfen das
   *  Trennzeichen ``|`` nicht enthalten — ist Teil der Konvention. */
  private guideQuickReplyUrl(qr: string): string {
    if (!this.isGuideQuickReply(qr)) return '';
    const rest = qr.slice(ChatComponent.GUIDE_QR_PREFIX.length);
    const sepIdx = rest.indexOf('|');
    if (sepIdx === -1) return '';
    return rest.slice(sepIdx + 1).trim();
  }

  /** User klickt einen Guide-QR — Same-Tab-Navigation, kein Send. */
  onGuideQuickReply(qr: string): void {
    const url = this.guideQuickReplyUrl(qr);
    if (url) this.onGuideNavigate(url);
  }

  // ── Webseiten-Tour (geführte Besucherführung) ─────────────────────
  // Startbutton (showGreeting) → startTour(). Navigation pro Schritt läuft
  // über die vorhandenen __guide__-Quick-Reply-Buttons (onGuideQuickReply).
  // Nach jedem Seitenwechsel feuert ngOnInit einen unsichtbaren Tick, damit
  // der Bot die Ankunft erkennt und den nächsten Schritt liefert.
  static readonly TOUR_START_LABEL = 'Web-Tour starten';
  private static readonly TOUR_FLAG_KEY = 'boerdi_tour_active';
  /** Verhindert Doppel-Ticks pro Page-Load. */
  private _tourTicked = false;
  /** True, wenn die Session in DIESEM Page-Load per ?bsid= übernommen wurde
   *  (Cross-Origin-Handoff). Dann fehlt das origin-gebundene Tour-Flag hier
   *  (es liegt auf der Quell-Origin) — der Ankunfts-Tick wird trotzdem
   *  gefeuert, weil der Backend-Tour-State die Wahrheit ist. */
  private _resumedViaBsid = false;

  private _isTourFlagSet(): boolean {
    try { return localStorage.getItem(ChatComponent.TOUR_FLAG_KEY) === '1'; }
    catch { return false; }
  }
  private _setTourFlag(on: boolean): void {
    try {
      if (on) localStorage.setItem(ChatComponent.TOUR_FLAG_KEY, '1');
      else localStorage.removeItem(ChatComponent.TOUR_FLAG_KEY);
    } catch { /* ignore */ }
  }
  /** environment-Override für Tour-Requests (tour_action + page_context). */
  private _tourEnv(action: 'start' | 'tick'): any {
    const env: any = { tour_action: action };
    if (Object.keys(this.parsedPageContext).length) {
      env.page_context = this.parsedPageContext;
    }
    return env;
  }
  /** Liest resp.tour und pflegt das localStorage-Flag.
   *  - ``resp.tour`` vorhanden → Flag = ``tour.active``.
   *  - ``resp.tour`` FEHLT → es lief keine Tour mehr in dieser Antwort (z.B.
   *    der Nutzer hat mitten in der Tour etwas anderes getippt → Backend hat
   *    die Tour beendet und normal geantwortet). Flag sofort löschen, sonst
   *    würde das Widget bei der nächsten Navigation noch einmal fälschlich
   *    auto-öffnen. */
  private _applyTourState(resp: ChatResponse): void {
    const tour = (resp as any).tour;
    this._setTourFlag(!!(tour && typeof tour === 'object' && tour.active));
  }
  /** Rendert eine Tour-Bot-Antwort wie eine normale Bot-Bubble. */
  private _renderTourResponse(resp: ChatResponse): void {
    const id = this.addBotMessage(
      resp.content, false, resp.cards, resp.quick_replies, resp.debug,
      resp.pagination, resp.query_metas, resp.web_links,
      resp.inline_documents, resp.display_rules, resp.topic_page,
    );
    this.scrollTargetId = id;
    this.latestDebug = resp.debug;
  }

  /** Startet die geführte Web-Tour (Klick auf den Startbutton). */
  async startTour(): Promise<void> {
    if (this.isLoading) return;
    this.addUserMessage(ChatComponent.TOUR_START_LABEL);
    this.isLoading = true;
    const loadingId = this.addBotMessage('', true);
    this.scrollTargetId = loadingId;
    try {
      const resp = await this.api.sendMessage(this.sessionId, 'Web-Tour starten', this._tourEnv('start'));
      this.removeMessage(loadingId);
      this._setTourFlag(true);
      this._applyTourState(resp);
      this._renderTourResponse(resp);
    } catch {
      this.removeMessage(loadingId);
      this.addBotMessage('Entschuldigung, die Tour konnte gerade nicht gestartet werden. Bitte versuch es nochmal.');
    }
    this.isLoading = false;
  }

  /** Unsichtbarer Tour-Tick beim Page-Load: meldet die aktuelle Seite ohne
   *  User-Bubble. Rendert nur die Bot-Antwort, falls sie Inhalt hat. */
  async sendTourTick(): Promise<void> {
    if (this.isLoading || this._tourTicked) return;
    this._tourTicked = true;
    this.isLoading = true;
    const loadingId = this.addBotMessage('', true);
    this.scrollTargetId = loadingId;
    try {
      const resp = await this.api.sendMessage(this.sessionId, '[tour-tick]', this._tourEnv('tick'));
      this.removeMessage(loadingId);
      this._applyTourState(resp);
      const hasContent = !!(resp.content || '').trim()
        || !!(resp.quick_replies && resp.quick_replies.length);
      if (hasContent) this._renderTourResponse(resp);
    } catch {
      this.removeMessage(loadingId);
      // Tick-Fehler beim Page-Load still schlucken (kein Error-Bubble).
    }
    this.isLoading = false;
  }

  /** Nach dem (Re)Start: läuft eine Tour (localStorage-Flag, überlebt den
   *  WP-Reload), EINEN Tick feuern, sobald der initiale Render durch ist. */
  private _maybeStartTourTick(): void {
    // Tick feuern, wenn (a) lokal eine Tour läuft (Flag, same-origin) ODER
    // (b) die Session gerade per ?bsid= übernommen wurde (Cross-Origin-
    // Handoff — Flag liegt ggf. auf der Quell-Origin und fehlt hier). Das
    // Backend (tour_state der Session) entscheidet dann, ob wirklich eine
    // Tour läuft, und liefert sonst eine leere Inaktiv-Antwort.
    if (this._isTourFlagSet() || this._resumedViaBsid) {
      setTimeout(() => this.sendTourTick(), 0);
    }
  }

  onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  // ── Speech ────────────────────────────────────────────────
  recordingSeconds = 0;
  private recordingTimer: ReturnType<typeof setInterval> | null = null;
  private speechBusy = false; // guard against double-click
  /** Welle E v4+13: Backend meldet, ob STT/TTS verfügbar ist. Bei B-API-
   *  Anbindung ist Audio deaktiviert → Buttons werden ausgeblendet. Start
   *  optimistisch true; ngOnInit fragt /speech/status ab und korrigiert. */
  speechBackendEnabled = true;

  async toggleRecording() {
    if (this.speechBusy) return; // guard
    if (this.isRecording) {
      this.stopRecording();
    } else {
      this.speechBusy = true;
      // Set UI immediately BEFORE async mic request
      this.isRecording = true;
      this.recordingSeconds = 0;
      try {
        await this.startRecording();
      } catch {
        this.isRecording = false;
      }
      this.speechBusy = false;
    }
  }

  private async startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.mediaRecorder = new MediaRecorder(stream);
    this.audioChunks = [];

    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.audioChunks.push(e.data);
    };

    this.mediaRecorder.onstop = () => {
      const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
      stream.getTracks().forEach(t => t.stop());

      this.zone.run(async () => {
        this.isRecording = false;
        this.stopRecordingTimer();

        try {
          const text = await this.api.transcribe(blob);
          if (text) {
            this.userInput = text;
            this.sendMessage();
          }
        } catch (err) {
          console.error('Transcription error:', err);
          this.addBotMessage('Spracheingabe konnte nicht verarbeitet werden. Bitte tippe deine Nachricht.');
        }
      });
    };

    this.mediaRecorder.start();
    // Start timer (isRecording already set in toggleRecording)
    this.recordingTimer = setInterval(() => {
      this.zone.run(() => { this.recordingSeconds++; });
    }, 1000);
  }

  private stopRecording() {
    this.stopRecordingTimer();
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.stop(); // triggers onstop → sets isRecording=false in zone
    } else {
      this.isRecording = false;
    }
  }

  private stopRecordingTimer() {
    if (this.recordingTimer) {
      clearInterval(this.recordingTimer);
      this.recordingTimer = null;
    }
    this.recordingSeconds = 0;
  }

  // Audio queue for sentence-chunked OpenAI TTS
  private audioQueue: Blob[] = [];
  private audioAbort: AbortController | null = null;

  /**
   * Manual toggle (speaker button on a message): click while speaking stops;
   * click while idle starts TTS.
   */
  speakText(text: string) {
    if (this.isSpeaking) {
      this.stopSpeaking();
      return;
    }
    const plain = this.stripMarkdown(text);
    this.isSpeaking = true;
    this.speakChunked(plain);
  }

  /**
   * Auto-speak entry point: always plays the given text. If a prior
   * TTS playback is still running, it is aborted first so the new
   * response is spoken immediately. Used when `autoSpeak` is on and
   * a new bot response arrives (the user may have interrupted the
   * previous response by sending the next message).
   */
  private autoSpeakText(text: string) {
    if (this.isSpeaking) {
      this.stopSpeaking();
    }
    const plain = this.stripMarkdown(text);
    if (!plain) return;
    this.isSpeaking = true;
    this.speakChunked(plain);
  }

  // ── Inline-Document-Box (Welle E, 2026-05-23) ──────────────────
  /**
   * Liest die font_size_percent aus den Display-Regeln, die das Backend
   * mit der Message mitgeschickt hat. Default 85 % (= ~14px bei 16px-
   * Basis) wenn das Feld fehlt. Geclamped auf [70, 100] damit ein
   * verkonfiguriertes Studio-Setting die Box nicht unleserlich macht.
   */
  inlineDocFontSize(msg: ChatMessage): number {
    const raw = msg.displayRules?.['inline_documents']?.['font_size_percent'];
    const n = typeof raw === 'number' ? raw : parseInt(raw, 10);
    if (!Number.isFinite(n)) return 85;
    return Math.max(70, Math.min(100, n));
  }

  /** Icon-Name aus dem Material-Icons-Set für die Inline-Document-Header-Zeile. */
  inlineDocIcon(kind: string): string {
    switch ((kind || '').toLowerCase()) {
      case 'lernpfad':    return this.ICONS.route;
      case 'ki_material': return this.ICONS.article;
      case 'edit':        return this.ICONS.edit;
      case 'bericht':     return this.ICONS.description;
      case 'remix':       return this.ICONS.refresh;
      default:            return this.ICONS.description;
    }
  }

  /** Fallback-Label wenn das Backend keinen Title liefert. */
  inlineDocFallbackLabel(kind: string): string {
    switch ((kind || '').toLowerCase()) {
      case 'lernpfad':    return 'Lernpfad';
      case 'ki_material': return 'Material';
      case 'edit':        return 'Bearbeitete Version';
      case 'bericht':     return 'Bericht';
      case 'remix':       return 'Remix';
      default:            return 'Inhalt';
    }
  }

  // ── Lernpfad: Detektor + Druckfunktion ─────────────────────────
  /**
   * Detects whether a bot message is a Lernpfad. Both markers are produced
   * verbatim by `generate_learning_path_text` (llm_service.py:1178ff):
   * the opening blockquote "> **Lernpfad:" and the "### Schritt 1" header.
   */
  isLearningPath(msg: ChatMessage): boolean {
    if (msg.sender !== 'bot' || !msg.content) return false;
    const c = msg.content;
    return /\*\*Lernpfad:/i.test(c) || /^#{1,3}\s*Schritt\s*\d/mi.test(c);
  }

  // Sentinel-Format vom Backend (chat.py _apply_widget_modes_postprocess):
  //   <!-- boerdi:printable-canvas|<material_type>|<title> -->
  // Wird vor jedes Canvas-Markdown im Inline-Modus (canvas-enabled="false")
  // gestellt, sodass das Frontend den Print-Button anbieten kann.
  private readonly PRINTABLE_CANVAS_RE =
    /<!--\s*boerdi:printable-canvas\|([^|]*)\|([^>]*?)\s*-->/;

  // Unicode-Brüche für die häufigsten Werte aus Mathe-Materialien.
  private readonly _UNI_FRAC: Record<string, string> = {
    '1/2': '½', '1/3': '⅓', '2/3': '⅔', '1/4': '¼', '3/4': '¾',
    '1/5': '⅕', '2/5': '⅖', '3/5': '⅗', '4/5': '⅘',
    '1/6': '⅙', '5/6': '⅚', '1/7': '⅐',
    '1/8': '⅛', '3/8': '⅜', '5/8': '⅝', '7/8': '⅞',
    '1/9': '⅑', '1/10': '⅒',
  };

  /**
   * Konvertiert LaTeX-Fragmente die der LLM trotz Anti-LaTeX-Prompt
   * gelegentlich produziert (vor allem ``\frac12``, ``\frac{1}{2}``,
   * ``\sqrt{2}``, ``$x^2$``) zu lesbarem Unicode-Text. Wird sowohl im
   * Inline-Markdown-Render (Bot-Bubble) als auch in den Print-Views
   * (PDF-Window) benutzt — sonst sieht der User in einem von beiden
   * weiterhin Rohlatex.
   */
  private stripLatex(text: string): string {
    const fr = (n: string, d: string): string =>
      this._UNI_FRAC[`${n}/${d}`] || `${n}⁄${d}`;
    return text
      .replace(/\\frac\s*\{\s*(\d+)\s*\}\s*\{\s*(\d+)\s*\}/g, (_m, n, d) => fr(n, d))
      .replace(/\\frac\s*(\d)\s*(\d)/g, (_m, n, d) => fr(n, d))
      .replace(/\\sqrt\s*\{\s*([^}]+?)\s*\}/g, (_m, x) => `√${x}`)
      .replace(/\$([^$\n]+?)\$/g, '$1');
  }

  /**
   * Detects whether a bot message contains canvas-generated content (Arbeits-
   * blatt, Quiz, Bericht, etc.) that landed inline because the host has
   * ``canvas-enabled="false"``. Lernpfade have their own dedicated detector
   * + button (the opening blockquote acts as the trigger), so we exclude
   * them here to avoid showing two print buttons on the same message.
   */
  isPrintableCanvasMaterial(msg: ChatMessage): boolean {
    if (msg.sender !== 'bot') return false;
    // Welle E (2026-05-24): jede InlineDocument-Box mit kind=ki_material
    // / lernpfad / edit / bericht / remix ist druckbar. Sentinel-im-
    // ``msg.content``-Pfad bleibt als Fallback für ältere Messages.
    const docs = msg.inlineDocuments || [];
    if (docs.length > 0) return true;
    if (!msg.content) return false;
    if (this.isLearningPath(msg)) return false;
    return this.PRINTABLE_CANVAS_RE.test(msg.content);
  }

  /**
   * Welle E (2026-05-24): Druck-Trigger direkt aus der InlineDocument-Box.
   * Nutzt doc.title als Print-Header und doc.content als Markdown-Body —
   * keinen Sentinel-Parse nötig.
   */
  printInlineDocument(doc: { title: string; content: string; kind: string }): void {
    if (!doc || !doc.content) return;
    this._printMarkdown(doc.title || this.inlineDocFallbackLabel(doc.kind), doc.content);
  }

  /** Gemeinsamer Markdown-Print-Helper für InlineDocument + Legacy-Canvas. */
  private _printMarkdown(title: string, markdown: string): void {
    const esc = (s: string) =>
      (s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }[c] as string));
    const stripLatex = (t: string): string => this.stripLatex(t);
    const mdToHtml = (text: string): string => {
      let html = stripLatex(text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/\[(.+?)\]\((https?:[^)]+)\)/g,
          '<a href="$2" target="_blank" rel="noopener">$1</a>');
      const lines = html.split('\n');
      const out: string[] = [];
      for (const raw of lines) {
        const line = raw.trim();
        const h = line.match(/^(#{1,6})\s+(.*)$/);
        if (h) { out.push(`<h${Math.min(h[1].length + 1, 6)}>${h[2]}</h${Math.min(h[1].length + 1, 6)}>`); continue; }
        const ol = line.match(/^(\d+)\.\s+(.*)$/);
        if (ol) { out.push(`<div class="ol"><span class="n">${ol[1]}.</span> ${ol[2]}</div>`); continue; }
        const li = line.match(/^(?:[-•]|\*(?!\*))\s+(.*)/);
        if (li) { out.push(`<div class="li"><span class="b">•</span> ${li[1]}</div>`); continue; }
        if (line) out.push(`<p>${line}</p>`);
      }
      return out.join('\n');
    };
    const body = mdToHtml(markdown || '');
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:780px;margin:32px auto;padding:0 24px;color:#111;line-height:1.5}
h1,h2,h3,h4{color:#1c4587;margin:1em 0 .4em}h1{font-size:1.6em;border-bottom:2px solid #1c4587;padding-bottom:.2em}
p{margin:.4em 0}.li,.ol{margin:.2em 0 .2em 1em}.n,.b{display:inline-block;width:1.5em;color:#1c4587;font-weight:600}
a{color:#1c4587}@media print{a{color:inherit;text-decoration:none}}</style></head>
<body><h1>${esc(title)}</h1>${body}<script>window.onload=function(){setTimeout(function(){window.print()},300)}<\/script></body></html>`;
    const w = window.open('', '_blank');
    if (w) { w.document.write(html); w.document.close(); }
  }

  /**
   * Returns a human-readable label of the canvas material (e.g.
   * "Arbeitsblatt", "Quiz", "Material"). Used as the print-dialog title.
   */
  printableCanvasLabel(msg: ChatMessage): string {
    const m = (msg.content || '').match(this.PRINTABLE_CANVAS_RE);
    if (!m) return 'Material';
    const type = (m[1] || '').trim();
    const title = (m[2] || '').trim();
    return title || type || 'Material';
  }

  /**
   * Render an inline canvas-material message (Arbeitsblatt, Quiz, Bericht,
   * …) into a clean printable window — same pattern as ``printLearningPath``
   * but generic over the material type. The sentinel-comment is stripped
   * from the markdown before rendering so it doesn't show up in print.
   */
  printCanvasMaterial(msg: ChatMessage): void {
    const m = (msg.content || '').match(this.PRINTABLE_CANVAS_RE);
    if (!m) return;
    const materialType = ((m[1] || 'material').trim() || 'material');
    const docTitle = ((m[2] || 'Material').trim() || 'Material');
    // Markdown ohne Sentinel — der ist nur ein Marker, nicht Teil des Inhalts.
    const md = (msg.content || '')
      .replace(this.PRINTABLE_CANVAS_RE, '')
      .trim();

    const esc = (s: string) =>
      (s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }[c] as string));

    // Minimaler Markdown→HTML-Renderer, identisch zu printLearningPath
    // (bewusst duplikat — die Print-Page läuft im neuen Window ohne Angular).
    // LaTeX-Stripping wird vorab angewendet, damit \frac12 etc. nicht roh
    // in den Print landen.
    const stripLatex = (t: string): string => this.stripLatex(t);
    const mdToHtml = (text: string): string => {
      let html = stripLatex(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^&gt;\s?/gm, '> ')
        .replace(/\[(.+?)\]\((https?:[^)]+)\)/g,
          '<a href="$2" target="_blank" rel="noopener">$1</a>');
      const lines = html.split('\n');
      const out: string[] = [];
      for (const raw of lines) {
        const line = raw.trim();
        const h = line.match(/^(#{1,6})\s+(.*)$/);
        if (h) {
          const lvl = Math.min(h[1].length + 1, 6);
          out.push(`<h${lvl}>${h[2]}</h${lvl}>`);
          continue;
        }
        const bq = line.match(/^>\s?(.*)$/);
        if (bq) { out.push(`<blockquote>${bq[1]}</blockquote>`); continue; }
        const ol = line.match(/^(\d+)\.\s+(.*)$/);
        if (ol) { out.push(`<div class="ol"><span class="n">${ol[1]}.</span> ${ol[2]}</div>`); continue; }
        const li = line.match(/^(?:[-•]|\*(?!\*))\s+(.*)/);
        if (li) { out.push(`<div class="li"><span class="b">•</span> ${li[1]}</div>`); continue; }
        if (line) out.push(`<p>${line}</p>`);
      }
      return out.join('\n');
    };

    // Material-Type-Label für Header — capitalize first letter.
    const typeLabel = materialType
      ? materialType.charAt(0).toUpperCase() + materialType.slice(1)
      : 'Material';
    const today = new Date().toLocaleDateString('de-DE', {
      year: 'numeric', month: 'long', day: 'numeric',
    });

    const html = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>${esc(docTitle)} – BadBoerdi</title>
<style>
  /* @page steuert den Druck-Rand (A4 mit komfortabler Marge). Im Browser-
     Modus arbeitet der body mit auto-margin + festem max-width, damit der
     Inhalt zentriert ist und genug Rand-Whitespace zum Fenster bleibt. */
  @page { size: A4; margin: 18mm 16mm 18mm 16mm; }
  html { background: #f1f5f9; }
  body {
    font: 11pt/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    color: #222; max-width: 760px; margin: 32px auto 64px;
    padding: 36px 44px; background: #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
    border-radius: 4px;
  }
  header { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px solid #3b82f6; padding-bottom: 6px; margin-bottom: 14px; }
  header h1 { margin: 0; font-size: 16pt; color: #1e40af; }
  header .meta { font-size: 9pt; color: #6b7280; }
  h1, h2, h3, h4 { color: #1e40af; margin: 14px 0 4px; }
  h2 { font-size: 13pt; }
  h3 { font-size: 12pt; }
  blockquote { border-left: 3px solid #c5cbd6; background: #f6f8fb; margin: 6px 0; padding: 6px 12px; color: #3a4252; }
  p { margin: 4px 0; }
  .ol, .li { display: flex; margin: 3px 0; padding-left: 2px; }
  .ol .n, .li .b { flex-shrink: 0; margin-right: 8px; color: #3b82f6; font-weight: 600; }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #e5e7eb; font-size: 8.5pt; color: #6b7280; text-align: center; }
  .print-bar { position: fixed; top: 0; right: 0; padding: 10px 14px; background: #fff; border-bottom-left-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,.1); z-index: 10; }
  .print-bar button { padding: 6px 14px; background: #3b82f6; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 10pt; }
  .print-bar button:hover { background: #2563eb; }
  /* Im Druck: keine Schatten, keine max-width — die @page-margins über-
     nehmen das Seiten-Layout, sonst verschwendet die feste body-Breite
     Platz auf der Druckseite. Body behält ein Mindest-Padding, falls
     der User in Chrome "Ränder: Minimum" oder "Keine" wählt und damit
     die @page-margins überschreibt — sonst wäre der Druck randlos. */
  @media print {
    html { background: #fff; }
    .print-bar { display: none; }
    body {
      padding: 12mm 14mm;
      margin: 0;
      max-width: none;
      box-shadow: none;
      border-radius: 0;
    }
  }
</style>
</head>
<body>
<div class="print-bar"><button onclick="window.print()">🖨 Drucken / Als PDF speichern</button></div>
<header>
  <h1><img src="${BOERDI_LOGO_DATA_URL}" alt="" style="width:28px;height:28px;vertical-align:-6px;margin-right:6px;"/> ${esc(docTitle || typeLabel)}</h1>
  <span class="meta">BadBoerdi · ${esc(today)}</span>
</header>
<main>
  ${mdToHtml(md)}
</main>
<footer>Erstellt mit BadBoerdi · WirLernenOnline.de · ${esc(today)}</footer>
<!-- Kein auto-print mehr: der User sieht erst die Preview im neuen
     Tab und klickt dann selbst "Drucken / Als PDF speichern". Vorher
     auto-print direkt nach load, was den User vor dem Druck-Dialog
     stranden ließ wenn er ihn versehentlich abbrach. -->
</body>
</html>`;

    const w = window.open('', '_blank', 'width=900,height=1100');
    if (!w) {
      alert('Bitte erlaube Pop-ups für diese Seite, um das Material zu drucken.');
      return;
    }
    w.document.open();
    w.document.write(html);
    w.document.close();
  }

  /**
   * Open a clean, printable Lernpfad view in a new window and trigger the
   * browser print dialog. Users can then "Save as PDF" from the dialog —
   * no server-side PDF rendering needed, works identically on all browsers.
   */
  printLearningPath(msg: ChatMessage): void {
    const esc = (s: string) =>
      (s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }[c] as string));

    // Markdown → simple printable HTML (reuses the same rules as
    // renderMarkdown() but stays independent so we don't drag Angular
    // DomSanitizer into the new window). LaTeX-Stripping via Helper
    // — sonst landet \frac12 roh im PDF.
    const stripLatex = (t: string): string => this.stripLatex(t);
    const mdToHtml = (text: string): string => {
      let html = stripLatex(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        // Restore blockquote markers (we just HTML-escaped them to &gt;)
        .replace(/^&gt;\s?/gm, '> ')
        .replace(/\[(.+?)\]\((https?:[^)]+)\)/g,
          '<a href="$2" target="_blank" rel="noopener">$1</a>');
      const lines = html.split('\n');
      const out: string[] = [];
      for (const raw of lines) {
        const line = raw.trim();
        const h = line.match(/^(#{1,6})\s+(.*)$/);
        if (h) {
          const lvl = Math.min(h[1].length + 1, 6);
          out.push(`<h${lvl}>${h[2]}</h${lvl}>`);
          continue;
        }
        const bq = line.match(/^>\s?(.*)$/);
        if (bq) { out.push(`<blockquote>${bq[1]}</blockquote>`); continue; }
        const ol = line.match(/^(\d+)\.\s+(.*)$/);
        if (ol) { out.push(`<div class="ol"><span class="n">${ol[1]}.</span> ${ol[2]}</div>`); continue; }
        const li = line.match(/^(?:[-•]|\*(?!\*))\s+(.*)/);
        if (li) { out.push(`<div class="li"><span class="b">•</span> ${li[1]}</div>`); continue; }
        if (line) out.push(`<p>${line}</p>`);
      }
      return out.join('\n');
    };

    // Wenn der Lernpfad im Inline-Modus erzeugt wurde, hat das Backend einen
    // ``<!-- boerdi:printable-canvas|... -->``-Sentinel vor das Markdown
    // gestellt (siehe chat.py _apply_widget_modes_postprocess). Im PDF-
    // Render-Pfad würde mdToHtml den Kommentar HTML-escapen und als
    // sichtbaren Text auswerfen — daher hier vorher strippen, identisch
    // zu printCanvasMaterial.
    const lpContent = (msg.content || '').replace(this.PRINTABLE_CANVAS_RE, '').trim();
    const cards = msg.cards || [];
    const cardsHtml = cards.map(c => {
      const types = (c.learning_resource_types || []).filter(
        t => t !== 'Sammlung' && t !== 'collection'
      );
      const meta = [
        ...(c.disciplines || []),
        ...(c.educational_contexts || []),
        ...types,
        c.license,
      ].filter(Boolean).map(x => `<span class="chip">${esc(x!)}</span>`).join('');
      const href = c.link || c.guide_url || c.wlo_url || c.url || '#';
      const desc = c.description
        ? `<div class="desc">${esc(c.description.slice(0, 220))}${c.description.length > 220 ? '…' : ''}</div>`
        : '';
      const thumb = c.preview_url
        ? `<img class="thumb" src="${esc(c.preview_url)}" alt="">`
        : `<div class="thumb thumb-ph">📄</div>`;
      return `
        <div class="card">
          ${thumb}
          <div class="card-body">
            <div class="card-title"><a href="${esc(href)}" target="_blank" rel="noopener">${esc(c.title)}</a></div>
            <div class="chips">${meta}</div>
            ${desc}
            <div class="card-url">${esc(href)}</div>
          </div>
        </div>`;
    }).join('');

    const today = new Date().toLocaleDateString('de-DE', {
      year: 'numeric', month: 'long', day: 'numeric',
    });

    const html = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Lernpfad – BadBoerdi</title>
<style>
  /* Browser-Preview: zentriertes "Papier" auf grauem Hintergrund. Im
     Druck übernehmen die @page-margins, body wird entkleidet. */
  @page { size: A4; margin: 18mm 16mm 18mm 16mm; }
  html { background: #f1f5f9; }
  body {
    font: 11pt/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    color: #222; max-width: 760px; margin: 32px auto 64px;
    padding: 36px 44px; background: #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
    border-radius: 4px;
  }
  header { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px solid #3b82f6; padding-bottom: 6px; margin-bottom: 14px; }
  header h1 { margin: 0; font-size: 16pt; color: #1e40af; }
  header .meta { font-size: 9pt; color: #6b7280; }
  h1, h2, h3, h4 { color: #1e40af; margin: 14px 0 4px; }
  h2 { font-size: 13pt; }
  h3 { font-size: 12pt; }
  blockquote { border-left: 3px solid #c5cbd6; background: #f6f8fb; margin: 6px 0; padding: 6px 12px; color: #3a4252; }
  p { margin: 4px 0; }
  .ol, .li { display: flex; margin: 3px 0; padding-left: 2px; }
  .ol .n, .li .b { flex-shrink: 0; margin-right: 8px; color: #3b82f6; font-weight: 600; }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  section.cards { margin-top: 22px; page-break-before: auto; }
  section.cards h2 { font-size: 12pt; margin-bottom: 8px; }
  .card { display: flex; gap: 10px; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; margin-bottom: 8px; page-break-inside: avoid; }
  .thumb { width: 60px; height: 60px; object-fit: cover; border-radius: 4px; flex-shrink: 0; background: #f3f4f6; display: flex; align-items: center; justify-content: center; font-size: 22pt; color: #9ca3af; }
  .card-body { flex: 1; min-width: 0; }
  .card-title { font-weight: 600; font-size: 10.5pt; }
  .card-title a { color: #1e40af; }
  .chips { margin: 3px 0; }
  .chip { display: inline-block; font-size: 8pt; background: #eef2ff; color: #4338ca; border-radius: 10px; padding: 1px 7px; margin-right: 4px; margin-bottom: 2px; }
  .desc { font-size: 9.5pt; color: #4b5563; margin: 3px 0; }
  .card-url { font-size: 8pt; color: #6b7280; word-break: break-all; }
  footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #e5e7eb; font-size: 8.5pt; color: #6b7280; text-align: center; }
  .print-bar { position: fixed; top: 0; right: 0; padding: 10px 14px; background: #fff; border-bottom-left-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,.1); z-index: 10; }
  .print-bar button { padding: 6px 14px; background: #3b82f6; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 10pt; }
  .print-bar button:hover { background: #2563eb; }
  @media print {
    html { background: #fff; }
    .print-bar { display: none; }
    /* Mindest-Padding, falls der User "Ränder: Minimum/Keine" wählt und
       damit die @page-margins (18/16mm) überschreibt. Sonst randlos. */
    body {
      padding: 12mm 14mm;
      margin: 0;
      max-width: none;
      box-shadow: none;
      border-radius: 0;
    }
  }
</style>
</head>
<body>
<div class="print-bar"><button onclick="window.print()">🖨 Drucken / Als PDF speichern</button></div>
<header>
  <h1><img src="${BOERDI_LOGO_DATA_URL}" alt="" style="width:28px;height:28px;vertical-align:-6px;margin-right:6px;"/> Lernpfad</h1>
  <span class="meta">BadBoerdi · ${esc(today)}</span>
</header>
<main>
  ${mdToHtml(lpContent)}
</main>
${cards.length ? `<section class="cards"><h2>Verwendete Inhalte (${cards.length})</h2>${cardsHtml}</section>` : ''}
<footer>Erstellt mit BadBoerdi · WirLernenOnline.de · ${esc(today)}</footer>
<!-- Kein auto-print mehr: der User sieht erst die Preview im neuen
     Tab und klickt dann selbst "Drucken / Als PDF speichern". Vorher
     auto-print direkt nach load, was den User vor dem Druck-Dialog
     stranden ließ wenn er ihn versehentlich abbrach. -->
</body>
</html>`;

    const w = window.open('', '_blank', 'width=900,height=1100');
    if (!w) {
      alert('Bitte erlaube Pop-ups für diese Seite, um den Lernpfad zu drucken.');
      return;
    }
    w.document.open();
    w.document.write(html);
    w.document.close();
  }

  /**
   * Split text into sentences, fetch OpenAI TTS for each, and play them
   * in sequence — pre-fetching the next sentence while the current one plays.
   * Falls back to browser speechSynthesis if the backend TTS fails.
   */
  private async speakChunked(text: string) {
    // Identify this run so any later overlap (a new auto-speak fired
    // while we were still playing the previous one) can suppress our
    // ``isSpeaking = false`` reset and avoid clobbering its own state.
    const myToken = ++this.speakingToken;
    const finish = () => {
      // Always run inside Angular's zone so the widget header re-renders
      // when the binding ``chatRef?.isSpeaking`` flips. Browser audio
      // events fire outside NgZone, so a plain assignment can leave the
      // ``spricht …`` indicator stuck on screen.
      if (this.speakingToken === myToken) {
        this.zone.run(() => { this.isSpeaking = false; });
      }
    };

    const sentences = this.splitSentences(text);
    if (!sentences.length) { finish(); return; }

    this.audioQueue = [];
    this.audioAbort = new AbortController();
    const signal = this.audioAbort.signal;

    try {
      // Pre-fetch first sentence
      let nextFetch: Promise<Blob | null> = this.fetchTTS(sentences[0], signal);

      for (let i = 0; i < sentences.length; i++) {
        if (signal.aborted) break;

        // Await current sentence audio
        const blob = await nextFetch;
        if (signal.aborted || !blob) break;

        // Start pre-fetching next sentence while current one plays
        if (i + 1 < sentences.length) {
          nextFetch = this.fetchTTS(sentences[i + 1], signal);
        }

        // Play current sentence
        await this.playBlob(blob, signal);
      }
    } finally {
      // Always reset (token-guarded so we don't fight an overlapping run).
      // Without the finally, an early ``break`` from ``signal.aborted`` —
      // or any unexpected exception — would leave isSpeaking stuck true.
      finish();
    }
  }

  private async fetchTTS(text: string, signal: AbortSignal): Promise<Blob | null> {
    try {
      return await this.api.synthesize(text, signal);
    } catch {
      return null;
    }
  }

  private playBlob(blob: Blob, signal: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
      if (signal.aborted) { resolve(); return; }

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.currentAudio = audio;

      // Watchdog: in rare browser bugs ``onended``/``onerror`` may never
      // fire (e.g. lost focus, autoplay throttle). Without this guard the
      // outer speakChunked Promise hangs and ``isSpeaking`` stays true
      // until the next user turn. Cap at ~max(audio.duration, 90s) plus
      // a 5s safety margin; if the metadata isn't loaded yet, a flat 90s
      // is the upper bound — much longer than any single TTS sentence.
      let watchdog: ReturnType<typeof setTimeout> | null = null;
      const armWatchdog = () => {
        const dur = isFinite(audio.duration) && audio.duration > 0
          ? Math.ceil(audio.duration * 1000) + 5000
          : 90_000;
        watchdog = setTimeout(() => { cleanup(); resolve(); }, dur);
      };

      const cleanup = () => {
        if (watchdog != null) { clearTimeout(watchdog); watchdog = null; }
        URL.revokeObjectURL(url);
        this.currentAudio = null;
      };

      audio.onended = () => { cleanup(); resolve(); };
      audio.onerror = () => { cleanup(); resolve(); };
      audio.onloadedmetadata = () => { armWatchdog(); };

      // Listen for abort to stop mid-playback
      const onAbort = () => { audio.pause(); cleanup(); resolve(); };
      signal.addEventListener('abort', onAbort, { once: true });

      audio.play().catch(() => { cleanup(); resolve(); });
      // Arm a coarse watchdog up-front in case loadedmetadata never fires
      // (network issue, malformed blob). Will be replaced by the precise
      // duration-based one once metadata loads.
      if (watchdog == null) {
        watchdog = setTimeout(() => { cleanup(); resolve(); }, 90_000);
      }
    });
  }

  /** Split text into sentence-sized chunks for TTS. */
  private splitSentences(text: string): string[] {
    // Split on sentence-ending punctuation followed by space or end
    const raw = text.match(/[^.!?]+[.!?]+[\s]?|[^.!?]+$/g) || [text];
    // Merge very short fragments (< 20 chars) with the previous sentence
    const merged: string[] = [];
    for (const s of raw) {
      const trimmed = s.trim();
      if (!trimmed) continue;
      if (merged.length > 0 && trimmed.length < 20) {
        merged[merged.length - 1] += ' ' + trimmed;
      } else {
        merged.push(trimmed);
      }
    }
    return merged;
  }

  private stopSpeaking() {
    // Abort any in-flight TTS fetches and queued playback
    if (this.audioAbort) {
      this.audioAbort.abort();
      this.audioAbort = null;
    }
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    this.audioQueue = [];
    // Bump the token so any old speakChunked still unwinding can't undo
    // this hard stop in its ``finally`` cleanup.
    this.speakingToken++;
    this.isSpeaking = false;
  }

  toggleAutoSpeak() {
    this.autoSpeak = !this.autoSpeak;
    // When enabling, immediately speak the last bot message so the user
    // gets audio confirmation that it works.
    if (this.autoSpeak) {
      const msgs = this.messages();
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (m.sender === 'bot' && m.content && !m.isLoading) {
          this.autoSpeakText(m.content);
          break;
        }
      }
    } else {
      // When disabling, stop any currently playing audio
      this.stopSpeaking();
    }
  }

  // ── Cards ────────────────────────────────────────────────
  openCard(card: WloCard) {
    // cardUrl() wendet _withBsid an (Cross-TLD-Handoff). Programmatisches
    // window.open umgeht den globalen <a>-Rewrite, daher hier explizit.
    const url = this.cardUrl(card);
    if (url && url !== '#') window.open(url, '_blank');
  }

  /**
   * Liefert das passende Material-Symbol-Inline-SVG für den Inhaltstyp einer
   * Kachel. Template-Verwendung:
   *   <span class="card-content-icon" [innerHTML]="getCardIcon(card) | safeSvg"></span>
   */
  getCardIcon(card: WloCard): string {
    // Themenseiten bekommen ihr eigenes Icon — sie sind kuratierte
    // Webseiten, keine reinen Sammlungen, und unterscheiden sich
    // visuell vom "Stapel"-Symbol der klassischen Sammlung.
    if (this.isThemenseite(card)) return ICONS.topic;
    if (card.node_type === 'collection') return ICONS.auto_stories;
    const types = card.learning_resource_types || [];
    if (types.some(t => t.toLowerCase().includes('video'))) return ICONS.play_circle;
    if (types.some(t => t.toLowerCase().includes('arbeitsblatt'))) return ICONS.article;
    if (types.some(t => t.toLowerCase().includes('interaktiv'))) return ICONS.videogame_asset;
    if (types.some(t => t.toLowerCase().includes('audio'))) return ICONS.headphones;
    if (types.some(t => t.toLowerCase().includes('quiz') || t.toLowerCase().includes('test'))) return ICONS.quiz;
    if (types.some(t => t.toLowerCase().includes('präsent') || t.toLowerCase().includes('praesent'))) return ICONS.image;
    if (types.some(t => t.toLowerCase().includes('übung') || t.toLowerCase().includes('uebung'))) return ICONS.edit_note;
    if (types.some(t => t.toLowerCase().includes('kurs'))) return ICONS.school;
    if (types.some(t => t.toLowerCase().includes('webseite') || t.toLowerCase().includes('website'))) return ICONS.language;
    return ICONS.menu_book;
  }

  /**
   * Lesbares Label für den Inhaltstyp (über dem Bild). Nutzt den ersten
   * `learning_resource_types`-Eintrag wenn vorhanden, sonst Fallback.
   */
  getContentTypeLabel(card: WloCard): string {
    if (this.isThemenseite(card)) return 'Themenseite';
    if (card.node_type === 'collection') {
      // Sammlungen unterscheiden wir über das Kind-Badge rechts.
      return 'Sammlung';
    }
    const types = (card.learning_resource_types || []).filter(
      t => t && t.toLowerCase() !== 'sammlung' && t.toLowerCase() !== 'collection',
    );
    if (types.length) return types[0];
    return 'Inhalt';
  }

  /** Drei-Wege-Klassifikation für visuelle Unterscheidung. */
  isThemenseite(card: WloCard): boolean {
    // Themenseiten in BEIDEN Repraesentationen erkennen, passend zum
    // Backend (_is_themenseite_card): neu node_type='topic_page'
    // (topic-pages-Renderer-Link), alt node_type='collection' mit
    // topic_pages-Varianten. Sonst landet die Themenseite in der
    // falschen Box (Regression 2026-06-02: topic_page -> Material-Box).
    if (card.node_type === 'topic_page') return true;
    return card.node_type === 'collection'
      && Array.isArray(card.topic_pages) && card.topic_pages.length > 0;
  }
  isSammlung(card: WloCard): boolean {
    return card.node_type === 'collection'
      && !(Array.isArray(card.topic_pages) && card.topic_pages.length > 0);
  }
  isInhalt(card: WloCard): boolean {
    return card.node_type !== 'collection' && card.node_type !== 'topic_page';
  }

  // ── Grouped-Result-Display (Sprint 7) ─────────────────────────
  // Aktiviert via ``[inline-result-grouping]="true"``: separate Boxen
  // für Themenseiten / Sammlungen + Search-CTA statt flacher Liste.

  /** Dedup-Key für Gruppen-Items. Eine Karte gilt als duplikat-gleich
   *  wenn entweder ``node_id`` matched ODER der normalisierte Titel
   *  (lowercase, getrimmt) gleich ist. Hintergrund (User-Feedback
   *  2026-05-21): kombinierte Tool-Calls (search_wlo_collections +
   *  search_wlo_topic_pages + Prefetch) können denselben Datensatz unter
   *  verschiedenen Node-IDs liefern (z.B. "Winkelsummen" 2× nebeneinander
   *  in der Sammlungen-Box). Ein reiner node_id-Dedup wie in der
   *  Backend-Merge-Logik reicht dann nicht. */
  private _dedupKey(c: WloCard): { id: string; title: string } {
    const id = (c.node_id || '').trim();
    const title = (c.title || '').trim().toLowerCase().replace(/\s+/g, ' ');
    return { id, title };
  }

  /** Filtert eine Card-Liste auf max. N Treffer und entfernt Duplikate
   *  per ``node_id`` ODER normalisiertem Titel. Reihenfolge bleibt erhalten,
   *  d.h. der ERSTE Treffer mit einem bestimmten Titel gewinnt — meist
   *  ist das der relevanteste (Sortierung kommt aus dem Backend-Re-Rank). */
  private _dedupTake(cards: WloCard[], n: number): WloCard[] {
    const out: WloCard[] = [];
    const seenIds = new Set<string>();
    const seenTitles = new Set<string>();
    for (const c of cards) {
      const k = this._dedupKey(c);
      if (k.id && seenIds.has(k.id)) continue;
      if (k.title && seenTitles.has(k.title)) continue;
      if (k.id) seenIds.add(k.id);
      if (k.title) seenTitles.add(k.title);
      out.push(c);
      if (out.length >= n) break;
    }
    return out;
  }

  /** Liest einen Box-Limit-Wert aus den Display-Rules der Message.
   *  Welle E (2026-05-23): pro Box-Typ (themenseiten/sammlungen/
   *  materialien/webseiten) konfigurierbar via Studio (display-rules.yaml
   *  → groups). Fallback ist die alte Default-3.
   */
  private _groupLimit(msg: ChatMessage, key: string, fallback = 3): number {
    const v = (msg.displayRules as any)?.['groups']?.[key];
    const n = typeof v === 'number' ? v : parseInt(v, 10);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  /** Top N Themenseiten der Bot-Antwort — dedupliziert per node_id +
   *  normalisiertem Titel (siehe ``_dedupTake``). Default kommt aus
   *  display_rules.groups.themenseiten_max. */
  groupedTopicCards(msg: ChatMessage, n?: number): WloCard[] {
    if (!msg.cards) return [];
    const limit = n ?? this._groupLimit(msg, 'themenseiten_max');
    return this._dedupTake(msg.cards.filter(c => this.isThemenseite(c)), limit);
  }

  /** Top N reine Sammlungen (ohne Themenseiten-Markup) — dedupliziert
   *  per node_id + normalisiertem Titel. Default aus
   *  display_rules.groups.sammlungen_max. */
  groupedCollectionCards(msg: ChatMessage, n?: number): WloCard[] {
    if (!msg.cards) return [];
    const limit = n ?? this._groupLimit(msg, 'sammlungen_max');
    return this._dedupTake(msg.cards.filter(c => this.isSammlung(c)), limit);
  }

  /** Anzahl Einzelinhalte (Content-Cards), die per Search-CTA verfügbar
   *  bleiben würden — fürs UI-Label "X Einzelinhalte in der Suche". */
  groupedContentCardsCount(msg: ChatMessage): number {
    if (!msg.cards) return 0;
    return msg.cards.filter(c => this.isInhalt(c)).length;
  }

  /** Einzelinhalte (Materialien) als eigene Gruppen-Box rendern.
   *  Welle E (2026-05-23): Bisher landeten Einzelinhalte fälschlicherweise
   *  in der Webseiten-Inhalte-Box (web_links), obwohl sie eigene OER-
   *  Ressourcen sind. Default aus display_rules.groups.materialien_max. */
  groupedContentCards(msg: ChatMessage, n?: number): WloCard[] {
    if (!msg.cards) return [];
    const limit = n ?? this._groupLimit(msg, 'materialien_max');
    return this._dedupTake(msg.cards.filter(c => this.isInhalt(c)), limit);
  }

  /** Wählt die "haupt"-relevante MCP-Such-URL aus den Query-Metadata.
   *  Bevorzugt search_wlo_content > search_wlo_collections > erste mit
   *  nicht-leerer search_url. Liefert ``''`` wenn keine vorhanden.
   *
   *  Welle C.5 (2026-05-21): Fallback — wenn KEINE der Metas ein
   *  ``search_url`` mitliefert (kann passieren wenn der Bot nur
   *  ``search_wlo_collections`` / ``search_wlo_topic_pages`` aufgerufen hat
   *  und das MCP für diese Tools die ``searchUrl`` nicht ausspielt), bauen
   *  wir die URL aus ``repository_url`` + ``search_term`` selbst zusammen.
   *  Damit erscheint die Such-CTA auch in Turns ohne Einzelinhalt-Suche.
   *  Reihenfolge (alle bleiben im edu-sharing/openeduhub-Ökosystem —
   *  wirlernenonline.de/?s=… wird NICHT mehr genutzt, der WP-Endpoint
   *  ist instabil und nicht für Such-Targeting gedacht):
   *    1. Erstes ``search_wlo_content``-Meta mit URL
   *    2. Erstes Collections-/Topic-Pages-Meta mit URL
   *    3. Jedes Meta mit nicht-leerem search_url
   *    4. ``repository_url`` aus Metas + ``/components/search?query=<term>``
   *    5. Gar nichts (leerer String → CTA versteckt) */
  groupedSearchUrl(msg: ChatMessage): string {
    const metas = msg.queryMetas || [];
    if (!metas.length) return '';
    const byTool = (t: string) => metas.find(m => m.tool_name === t && m.search_url);
    const direct = (
      byTool('search_wlo_content')?.search_url
      || byTool('search_wlo_collections')?.search_url
      || byTool('search_wlo_topic_pages')?.search_url
      || metas.find(m => m.search_url)?.search_url
      || ''
    );
    if (direct) return this._withBsid(direct);
    // ── Fallback-Komposition (nur edu-sharing) ──────────────────
    // Nimm den ersten nicht-leeren search_term aus den Metas (die Tools
    // schreiben den User-Suchbegriff alle gleich rein, search_wlo_content/
    // collections/topic_pages teilen sich das Schema).
    const termMeta = metas.find(m => m.search_term?.trim());
    const term = (termMeta?.search_term || '').trim();
    if (!term) return '';
    const repoMeta = metas.find(m => m.repository_url?.trim());
    const repo = (repoMeta?.repository_url || '').trim().replace(/\/+$/, '');
    if (!repo) {
      // Ohne repository_url kein Fallback — wir leiten NICHT auf
      // wirlernenonline.de/?s=… um (WP wirft 500). Eher CTA verstecken.
      return '';
    }
    const q = encodeURIComponent(term);
    return this._withBsid(`${repo}/edu-sharing/components/search?query=${q}`);
  }

  /** Such-Begriff für das Search-CTA-Label. Falls in den Metas vorhanden,
   *  zeigen wir ihn an ("Alle Treffer zu „Klimawandel" in der Suche"). */
  groupedSearchTerm(msg: ChatMessage): string {
    const metas = msg.queryMetas || [];
    const m = metas.find(x => x.search_term?.trim());
    return (m?.search_term || '').trim();
  }

  /** Sichtbarer Bot-Text. Bei aktivem ``inline-result-grouping`` werden
   *  jene Markdown-Bullet-Links aus dem ``content`` rausgestrippt, die
   *  bereits in die separate Webseiten-Inhalte-Box gewandert sind —
   *  sonst sähe der User dieselben Links zweimal (einmal als Bullet
   *  im Text, einmal in der Box). Inline-Links MITTEN im Satz bleiben
   *  unangetastet (die liest der User als Teil des Fließtexts; sie
   *  nochmal in der Box zu zeigen wäre Doppelung, aber sie zu strippen
   *  würde den Satz zerreißen — Bullets sind das eindeutige Signal
   *  für "redundante Aufzählung"). */
  displayContent(msg: ChatMessage): string {
    const raw = msg.content || '';
    if (!raw) return raw;
    if (!this.inlineResultGroupingBool) return raw;
    const promoted = this.groupedWebLinks(msg);
    if (!promoted.length) return raw;
    // Promoted-URLs OHNE bsid normalisieren — die Content-Bullets haben
    // die Original-URL (vor _withBsid), Strip-Vergleich muss damit auch
    // bsid-freie und bsid-gesetzte Varianten matchen.
    const stripBsid = (u: string): string => {
      try {
        const x = new URL(u);
        x.searchParams.delete('bsid');
        return x.toString().replace(/\?$/, '');
      } catch { return u; }
    };
    const promotedUrls = new Set(promoted.map(l => stripBsid(l.url)));
    const lines = raw.split('\n');
    // Match nur ganze Bullet-Zeilen — die sind die typische LLM-Output-
    // Form für Quellen-Aufzählung. Inline-Links wie "Schau dir [Faq](…) an"
    // bleiben.
    // Bullet (-, *, +, typografisch) ODER Numbering (1., 1)) am Zeilenanfang,
    // optional Bold/Italic/Quote um den Link, optional Trailing-Punctuation.
    // Parallel zum Backend-Pattern (chat.py:bullet_link_re) — Sicherheitsnetz
    // für alte gespeicherte Messages aus der Zeit vor dem Backend-Fix sowie
    // für LLM-Varianten, die das Backend ausnahmsweise durchlässt.
    const bulletWithLinkRe = /^\s*(?:[-*+•◦▪·‣⁃►▶]|\d+[.)])\s+(?:\*{0,2}|_{0,2}|["'])?\[[^\]\n]+\]\(\s*<?(https?:\/\/[^\s)>]+)>?\s*\)(?:\*{0,2}|_{0,2}|["'])?\s*[.,;:!?]?\s*$/;
    // HTML-Variante: ``- <a href="…">Label</a>`` (auch mit Bold-Wrappern).
    const bulletHtmlLinkRe = /^\s*(?:[-*+•◦▪·‣⁃►▶]|\d+[.)])\s+(?:\*{0,2}|_{0,2})?<a\s+[^>]*?href\s*=\s*["'](https?:\/\/[^"']+)["'][^>]*>[^<]+<\/a>(?:\*{0,2}|_{0,2})?\s*[.,;:!?]?\s*$/i;
    const out: string[] = [];
    for (const line of lines) {
      const m = line.match(bulletWithLinkRe);
      if (m && promotedUrls.has(stripBsid(m[1]))) continue;
      const h = line.match(bulletHtmlLinkRe);
      if (h && promotedUrls.has(stripBsid(h[1]))) continue;
      out.push(line);
    }
    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  /** Web-Links für die ``Webseiten-Inhalte``-Box. Bevorzugt das strukturierte
   *  Feld ``msg.webLinks`` (vom Backend per ``_extract_web_links_from_text``
   *  rausgezogen — der saubere Pfad). Fallback: Markdown-Link-Regex auf
   *  ``msg.content`` für alte gespeicherte Messages aus der Zeit vor dem
   *  strukturierten Feld. ``?bsid=`` wird auf Trusted-Hosts angehängt. */
  groupedWebLinks(msg: ChatMessage, n?: number): Array<{ title: string; url: string }> {
    // Type-Focus-Antworten (Material-Typ-Anfrage „nur Videos / hast du
    // Arbeitsblätter / …") rendern NIEMALS eine Webseiten-Inhalte-Box —
    // der Antwortmodus ist „Klick auf die Such-CTA", alles andere
    // verwirrt. Zwei Detection-Pfade:
    //   1. Backend-Marker ``debug._type_focus`` (auf neuen Antworten +
    //      via api.service.ts auch beim Restore mitgereicht)
    //   2. Content-Pattern-Match (defensiv für alte gespeicherte Messages
    //      die noch keinen Marker haben).
    if ((msg.debug as any)?._type_focus) return [];
    const _tfPattern = /^\s*Für\s+\S.*\bschau\s+in\s+die\s+Suche\s+unten\b/i;
    if (_tfPattern.test(msg.content || '')) return [];
    // Welle E (2026-05-23) — Limit aus display_rules.groups.webseiten_max
    const limit = n ?? this._groupLimit(msg, 'webseiten_max');
    // ── Primärpfad: strukturiertes Backend-Feld ─────────────────
    if (Array.isArray(msg.webLinks) && msg.webLinks.length > 0) {
      return msg.webLinks
        .slice(0, limit)
        .map(l => ({ title: l.title, url: this._withBsid(l.url) }));
    }
    // ── Fallback: ChatMessage hat möglicherweise webLinks im debug-Feld
    // (kommt aus altem ``GET /messages``-Restore via ``_web_links``-Key) ──
    const debugLinks = (msg.debug as any)?._web_links;
    if (Array.isArray(debugLinks) && debugLinks.length > 0) {
      return debugLinks
        .filter((l: any) => l && l.title && l.url)
        .slice(0, limit)
        .map((l: any) => ({ title: String(l.title), url: this._withBsid(String(l.url)) }));
    }
    // ── Letzter Fallback: Regex auf Content ─────────────────────
    // Greift nur bei alten gespeicherten Messages oder bei custom Backends
    // die ``web_links`` noch nicht implementiert haben. Card-URLs werden
    // ausgeschlossen damit nichts doppelt erscheint.
    const content = msg.content || '';
    if (!content) return [];
    const cardUrls = new Set<string>();
    (msg.cards || []).forEach(c => {
      const u = (c.link || c.guide_url || c.wlo_url || c.url || '').trim();
      if (u) cardUrls.add(u);
      (c.topic_pages || []).forEach(tp => {
        if (tp?.url) cardUrls.add(tp.url);
      });
    });
    const re = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
    const seen = new Set<string>();
    const out: Array<{ title: string; url: string }> = [];
    let m: RegExpExecArray | null;
    while ((m = re.exec(content)) !== null) {
      const label = m[1].trim();
      const url = m[2].trim();
      if (!label || !url) continue;
      if (seen.has(url) || cardUrls.has(url)) continue;
      seen.add(url);
      out.push({ title: label, url: this._withBsid(url) });
      if (out.length >= limit) break;
    }
    return out;
  }

  /** Title-Tooltip für ein Result-Group-Item bauen.
   *
   *  - Label (Card-Titel oder Link-Titel) als Basis,
   *  - bei externem/nicht-vertrauenswürdigem Host wird die Warnung
   *    ``"Achtung! Externe URL."`` mit `` — `` angehängt.
   *  - Wenn weder Label noch Warnung vorhanden ist, ``null``-Rückgabe
   *    sorgt dafür, dass Angular das ``title``-Attribut komplett weglässt
   *    (statt literal ``"null"`` ins DOM zu schreiben).
   *
   *  Verwendet vom Template für Themenseiten-/Sammlungen-/Webseiten-Boxen
   *  und für die Search-CTA. Ersetzt den vorherigen
   *  ``externalLinkWarning(url) || null``-Ausdruck, der bei trusted Hosts
   *  ``"null"`` als String anzeigte. */
  itemTooltip(label: string | undefined | null, url: string | undefined | null): string | null {
    const lbl = (label || '').trim();
    const warn = url ? (this.externalLinkWarning(url) || '') : '';
    if (lbl && warn) return `${lbl} — ${warn}`;
    if (lbl) return lbl;
    if (warn) return warn;
    return null;
  }

  /** Tooltip (title-Attribut) für Karten-Links: „Titel (Typ)". Der Typ ist
   *  der konkrete Inhaltstyp bei Einzelmaterialien (z.B. „Video",
   *  „Arbeitsblatt"), „Sammlung" bei Sammlungen, „Themenseite" bei
   *  Themenseiten — geliefert von getContentTypeLabel(). Plus ggf.
   *  Extern-Warnung (wie itemTooltip). */
  cardTooltip(card: WloCard | null | undefined, url?: string | null): string | null {
    if (!card) return null;
    const title = (card.title || '').trim();
    const type = this.getContentTypeLabel(card);
    const label = title && type ? `${title} (${type})` : (title || type);
    return this.itemTooltip(label, url ?? this.cardUrl(card));
  }

  /** Tooltip-Builder für die Search-CTA-Box im Result-Grouping-Modus.
   *  Baut den String ``Alle Treffer in der Suche anzeigen zu „<term>"`` plus
   *  ggf. Extern-Warnung. Im Template aufrufen statt das umständliche
   *  Inline-Escaping mit ``\"`` zu hantieren. */
  searchCtaTooltip(msg: ChatMessage): string | null {
    const term = this.groupedSearchTerm(msg);
    const base = 'Alle Treffer in der Suche anzeigen' + (term ? ` zu „${term}"` : '');
    return this.itemTooltip(base, this.groupedSearchUrl(msg));
  }

  /** True wenn die Gruppierungs-Anzeige für diese Message überhaupt etwas
   *  Sichtbares enthält (Themenseiten / Sammlungen / Web-Links / Search-CTA).
   *  Verhindert leere Wrapper bei Antworten ohne Suche und ohne RAG-Links.
   *
   *  Welle C.5+ (2026-05-22): Type-Focus-Antworten („Für Videos zu …")
   *  haben oft NUR die Such-CTA — keine Cards, keine Web-Links, weil die
   *  Box-Anzeige bewusst minimal sein soll. ``groupedSearchUrl`` ist dann
   *  unser einziger sichtbarer Anker und muss als Trigger zählen.
   */
  /** Tour-Antworten (``debug.pattern`` = „TOUR:…") sind bewusst rein
   *  textbasiert: kuratierte Inline-Links (Angebote/Sublinks/Kontakt) +
   *  ``__guide__``-Nav-Buttons. Sie tragen KEINE RAG-``web_links``. Die
   *  Result-Group-Boxen würden via Content-Scrape-Fallback nur die Tour-
   *  eigenen Links ein zweites Mal in die „Webseiten-Inhalte"-Box spiegeln
   *  → Dopplung. Daher während der Tour komplett unterdrücken. */
  isTourMessage(msg: ChatMessage): boolean {
    const p = (msg?.debug as any)?.pattern;
    return typeof p === 'string' && p.startsWith('TOUR:');
  }

  hasGroupedResults(msg: ChatMessage): boolean {
    if (this.isTourMessage(msg)) return false;
    const hasCards = !!(msg.cards && msg.cards.length);
    const hasWebLinks = this.groupedWebLinks(msg).length > 0;
    const hasSearchCta = !!this.groupedSearchUrl(msg);
    if (!hasCards && !hasWebLinks && !hasSearchCta) return false;
    return (
      (hasCards && (this.groupedTopicCards(msg).length > 0
                    || this.groupedCollectionCards(msg).length > 0
                    || this.groupedContentCards(msg).length > 0
                    || hasSearchCta))
      || hasWebLinks
      || hasSearchCta
    );
  }

  /**
   * Kompakte Lizenz-Anzeige für das Footer-Badge auf dem Vorschaubild.
   * "CC BY-SA 4.0" → "CC BY-SA", "Custom"/"Individuelle Lizenz" → "©",
   * sonstige werden gekürzt.
   */
  getLicenseShort(license: string): string {
    if (!license) return '';
    const l = license.trim();
    if (/^cc\b/i.test(l)) {
      // "CC BY-SA 4.0" → "CC BY-SA"
      return l.replace(/\s*\d(\.\d+)?\s*$/, '').toUpperCase();
    }
    if (/individuelle|custom|copyright/i.test(l)) return '©';
    if (/public\s*domain|gemeinfrei|cc\s*0|pdm/i.test(l)) return 'PD';
    if (l.length > 12) return 'Lizenz';
    return l;
  }

  // ── Collection Actions ─────────────────────────────────────
  @HostListener('document:click')
  closeTopicDropdown() { this.openTopicDropdown = null; }

  toggleTopicDropdown(event: Event, nodeId: string) {
    event.stopPropagation();
    this.openTopicDropdown = this.openTopicDropdown === nodeId ? null : nodeId;
  }

  /** Forward the backend's page_action to all listeners (host page via
   *  window event, widget via @Output, optional host callback). This MUST
   *  be called from every code path that issues an API request — otherwise
   *  the canvas won't update on browse/learning-path/remix clicks.
   */
  private dispatchPageAction(pa: { action: string; payload: any } | null | undefined): void {
    if (!pa) return;
    if (this.onPageAction) this.onPageAction(pa);
    this.pageAction.emit(pa);
    window.dispatchEvent(new CustomEvent('badboerdi:page-action', { detail: pa }));
  }

  /** Lotsen-Modus: user clicked "Bring mich hin" on an inline card. The
   *  click itself is the consent — navigate immediately in the current
   *  tab. ``url`` is set by the backend (only when guide-mode is on AND
   *  the host is on the allow list), so we don't re-validate here.
   */
  onGuideNavigate(url: string | undefined): void {
    if (!url) return;
    // Guide-CTA ist ein <button> (kein <a>), daher greift der globale
    // Outgoing-Link-Rewrite NICHT — wir müssen ``?bsid=`` hier selbst
    // anhängen (Cross-TLD-Session-Handoff zum Trusted-Ziel). Same-origin /
    // untrusted lässt ``_withBsid`` unverändert.
    const finalUrl = this._withBsid(url) || url;
    try {
      window.location.href = finalUrl;
    } catch {
      window.open(finalUrl, '_self', 'noopener');
    }
  }

  /** Phrases that turn a normal chat message into a "lotse mich"-request.
   *  Trigger only when the wording is unambiguous — bot-initiated
   *  navigation should not surprise the user. */
  private static readonly GUIDE_NAV_INTENT_RE =
    /\b(bring(?:\s+du)?\s+mich\s+(?:da)?hin|navigiere\s+(?:mich\s+)?(?:zu|zur|zum)|lotse\s+mich|öffne\s+(?:die|das|den)?\s*(?:themenseite|sammlung|seite)|geh(?:e)?\s+zur|f(?:üh|ueh)re\s+mich|hin\s+zur|bring\s+mich\s+(?:zu|zur|zum))\b/i;

  /** Inspect the just-sent user message; if it expresses a navigation
   *  wish AND the response has at least one card with a usable link,
   *  dispatch a ``navigate`` page-action so the widget banner appears.
   *  Picks the first card with a link (top result by relevance).
   *
   *  Card-Pipeline v2: bevorzugt ``link`` (vom build_card_link gesetzt);
   *  Fallback auf ``guide_url`` für Bestands-Backends.
   */
  private maybeDispatchGuideNavigate(userMessage: string, cards: WloCard[] | undefined): void {
    if (!userMessage || !cards || cards.length === 0) return;
    if (!ChatComponent.GUIDE_NAV_INTENT_RE.test(userMessage)) return;
    const target = cards.find(c => !!((c as WloCard & { link?: string }).link
                                       || (c as WloCard & { guide_url?: string }).guide_url));
    if (!target) return;
    const url = (target as WloCard & { link?: string }).link
                || (target as WloCard & { guide_url?: string }).guide_url
                || '';
    if (!url) return;
    this.dispatchPageAction({
      action: 'navigate',
      payload: { url, label: target.title || url },
    });
  }

  /** Boolean-coercion für die Web-Component-Attribute, die als
   *  ``"true"``/``"false"``-Strings ankommen (Custom-Element-Interop).
   *  Akzeptiert: ``true`` | ``'true'`` | ``''`` (Attribut ohne Wert
   *  bedeutet "an"). */
  private static _attrIsTrue(v: boolean | string | undefined): boolean {
    if (v === true) return true;
    if (typeof v === 'string') {
      const s = v.trim().toLowerCase();
      return s === '' || s === 'true' || s === '1' || s === 'yes';
    }
    return false;
  }

  /** Passive Top-1-Anzeige für Host-Integration.
   *
   *  Im Gegensatz zu :func:`maybeDispatchGuideNavigate` (die NUR bei
   *  expliziter Navigations-Anfrage feuert) wird hier bei JEDEM Bot-Turn
   *  ein ``badboerdi:guide-suggestion``-Event ausgelöst, sobald die
   *  Antwort mindestens eine Lotsen-eligible Card enthält. So kann z.B.
   *  eine Edu-Sharing-Sidebar einen "Bot empfiehlt"-Pin setzen oder ein
   *  WP-Theme einen Banner zeigen, ohne dass der User aktiv navigieren
   *  möchte.
   *
   *  Gated durch ``[emitGuideSuggestion]``. Bei ``false`` (Default) — kein
   *  Event, kein Effekt. Bei ``true`` — Event + Output bei jedem
   *  qualifizierten Turn.
   *
   *  Payload-Aufbau siehe :class:`GuideSuggestionPayload`. ``alternatives``
   *  enthält alle weiteren Lotsen-eligible Cards in Display-Reihenfolge,
   *  damit Hosts auch eine Top-N-UI bauen können.
   */
  private maybeDispatchGuideSuggestion(
    userMessage: string,
    cards: WloCard[] | undefined,
  ): void {
    if (!ChatComponent._attrIsTrue(this.emitGuideSuggestion)) return;
    if (!cards || cards.length === 0) return;

    // Eligible = hat einen ``link`` (Card-Pipeline v2) ODER ``guide_url``
    // (Backward-Compat) — beides sind allow-listed Lotsen-Targets.
    const eligible: Array<{ card: WloCard; url: string }> = [];
    for (const c of cards) {
      const link = (c as WloCard & { link?: string }).link
                 || (c as WloCard & { guide_url?: string }).guide_url
                 || '';
      if (link) eligible.push({ card: c, url: link });
    }
    if (eligible.length === 0) return;

    const top = eligible[0];
    const alternatives = eligible.slice(1).map(e => ({
      url: e.url,
      title: e.card.title || e.url,
      node_id: e.card.node_id || '',
      node_type: e.card.node_type || '',
    }));

    const payload: GuideSuggestionPayload = {
      url: top.url,
      title: top.card.title || top.url,
      node_id: top.card.node_id || '',
      node_type: top.card.node_type || '',
      query: userMessage || '',
      alternatives,
    };

    // Beide Kanäle: globales CustomEvent (Web-Component-Embed-Friendly) +
    // Angular-Output (für direkten Angular-Consumer). Hosts wählen den
    // Kanal, der zu ihrer Integration passt — die Daten sind identisch.
    window.dispatchEvent(new CustomEvent('badboerdi:guide-suggestion', {
      detail: payload,
      bubbles: true,
      composed: true,
    }));
    this.guideSuggestion.emit(payload);
  }

  /** Welle C.4 (2026-05): Dispatch a ``badboerdi:routing-debug`` Custom-
   *  Event with the routing telemetry from the current turn. Gated by
   *  ``emitRoutingDebug`` — hosts opt in explicitly. Data is read from
   *  the existing ``DebugInfo`` block in the response — no additional
   *  backend round-trip.
   *
   *  Use cases:
   *    - Studio-Live-Debug-Panel (welches Pattern wurde aktiv?)
   *    - Embed-Hosts mit Routing-Awareness (z.B. "diese Antwort war
   *      Lotsen-getrieben, nicht Material-Suche")
   *    - A/B-Test-Logging beim Embedder
   */
  private maybeDispatchRoutingDebug(
    userMessage: string,
    debug: DebugInfo | null | undefined,
  ): void {
    if (!ChatComponent._attrIsTrue(this.emitRoutingDebug)) return;
    if (!debug) return;

    const mods = debug.phase3_modulations || {};
    const payload: RoutingDebugPayload = {
      message: userMessage || '',
      pattern: debug.pattern || '',
      intent: debug.intent || '',
      state: debug.state || '',
      persona: debug.persona || '',
      tools_called: Array.isArray(debug.tools_called) ? debug.tools_called : [],
      // rag_areas + sources kommen aus phase3_modulations (Pattern-Engine-Output)
      rag_areas: Array.isArray(mods['rag_areas']) ? mods['rag_areas'] : [],
      sources: Array.isArray(mods['sources']) ? mods['sources'] : [],
      modifier: {
        tone: String(mods['tone'] || ''),
        length: String(mods['length'] || ''),
        formality: String(mods['formality'] || ''),
        card_text_mode: String(mods['card_text_mode'] || ''),
        override: Boolean(mods['_tone_modifier_override']),
      },
      signals: Array.isArray(debug.signals) ? debug.signals : [],
    };

    window.dispatchEvent(new CustomEvent('badboerdi:routing-debug', {
      detail: payload,
      bubbles: true,
      composed: true,
    }));
    this.routingDebug.emit(payload);
  }

  async browseCollection(nodeId: string, title: string) {
    if (this.isLoading) return;
    this.isLoading = true;
    const loadingId = this.addBotMessage('', true);

    try {
      const resp = await this.api.sendMessage(
        this.sessionId,
        `Inhalte der Sammlung "${title}"`,
        undefined,
        'browse_collection',
        { collection_id: nodeId, title },
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination, undefined, resp.web_links, resp.inline_documents, resp.display_rules);
      this.scrollTargetId = botMsgId;
      this.latestDebug = resp.debug;
      this.dispatchPageAction(resp.page_action);
    } catch (err) {
      this.removeMessage(loadingId);
      const errId = this.addBotMessage(`Ich konnte die Inhalte von "${title}" leider nicht laden. Versuch es nochmal!`);
      this.scrollTargetId = errId;
    }
    this.isLoading = false;
  }

  async generateLearningPath(nodeId: string, title: string) {
    if (this.isLoading) return;
    this.isLoading = true;
    const loadingId = this.addBotMessage('', true);

    try {
      const resp = await this.api.sendMessage(
        this.sessionId,
        `Lernpfad für "${title}"`,
        undefined,
        'generate_learning_path',
        { collection_id: nodeId, title },
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination, undefined, resp.web_links, resp.inline_documents, resp.display_rules);
      this.scrollTargetId = botMsgId;
      this.latestDebug = resp.debug;
      this.dispatchPageAction(resp.page_action);
    } catch (err) {
      this.removeMessage(loadingId);
      const errId = this.addBotMessage(`Den Lernpfad für "${title}" konnte ich leider nicht erstellen. Versuch es nochmal!`);
      this.scrollTargetId = errId;
    }
    this.isLoading = false;
  }


  // ── Visible cards helper ────────────────────────────────
  getVisibleCards(msg: ChatMessage): WloCard[] {
    if (!msg.cards) return [];
    const limit = msg.visibleCardCount || 5;
    return msg.cards.slice(0, limit);
  }

  /** Exposed helper so the template can use the typ-aware URL resolver. */
  cardUrl(card: WloCard | null | undefined): string {
    return this._withBsid(getCardPrimaryUrl(card));
  }

  /** URL für Webseiten-Inhalte-Box-Links (RAG-Quellen, web_links).
   *  Welle E (2026-05-23) — Bugfix: Vorher landete der bsid-Rewrite erst
   *  im Capture-Phase-Click-Listener (``_maybeRewriteOutgoingLink``),
   *  was bei Brave-Shield/Privacy-Browsern dazu führt dass der erste Klick
   *  noch dem alten ``href`` folgt (URL ohne ``?bsid``). Jetzt schon beim
   *  Render fertig — kein Doppelklick mehr nötig. */
  webLinkUrl(link: { url: string } | null | undefined): string {
    return this._withBsid(link?.url || '');
  }

  /** Tooltip-Text für Card-Links und Themenseiten-Buttons, falls die
   *  Ziel-URL auf einen Host außerhalb der Trusted-Liste zeigt (öffnet
   *  dann in neuem Tab — siehe HTML target="_blank"). Empty-Return =
   *  kein Warntooltip nötig. Wird auch genutzt für Topic-Page-Links. */
  externalLinkWarning(url: string | null | undefined): string {
    const raw = (url || '').trim();
    if (!raw) return '';
    let host = '';
    try {
      host = new URL(raw, window.location.href).hostname.toLowerCase();
    } catch { return ''; }
    if (!host) return '';
    if (host === window.location.hostname.toLowerCase()) return '';
    if (this.isHostTrusted(host)) return '';
    return 'Achtung! Externe URL.';
  }

  /** Hängt ``?bsid=<sessionId>`` an URLs zu Trusted-Hosts an, damit:
   *   - Right-Click → "Link-Adresse kopieren" die fertige URL liefert
   *   - Middle-Click / Ctrl-Click den Session-Param direkt mitnimmt
   *   - Screen-Reader und User-Skripte die korrekte URL sehen
   *  Der document-level Click-Interceptor ist Fallback für Inline-Links
   *  außerhalb von Angular-Templates, aber für Cards/Themenseiten-Buttons
   *  ist der Render-Time-Rewrite die saubere Variante. Non-trusted Hosts
   *  und Mailto/Tel/etc. bleiben unangetastet. */
  private _withBsid(url: string | null | undefined): string {
    const raw = (url || '').trim();
    if (!raw) return '';
    if (!this.sessionId) return raw;
    if (!/^bb-[0-9a-f-]{32,40}$/i.test(this.sessionId)) return raw;
    let target: URL;
    try {
      target = new URL(raw, window.location.href);
    } catch { return raw; }
    if (target.protocol !== 'http:' && target.protocol !== 'https:') return raw;
    // Konsequent (Welle E): bsid wird AUCH bei same-origin angehängt. Die
    // Session trägt zwar via Cookie/localStorage same-origin ohnehin, aber
    // das Widget-Auto-Open (ngOnInit) und die Tour-Fortsetzung keyen auf
    // ``?bsid=`` — so „folgt" der offene Chat dem Nutzer auch bei seiten-
    // interner Navigation. Die bsid wird beim Laden in
    // ``_resolvePersistedSessionId`` sofort wieder aus der URL gestrippt
    // (history.replaceState) → keine Bookmark-/Referer-Leaks, saubere
    // Adresszeile. Einziger Trade-off: same-origin-Requests tragen ``bsid``
    // (möglicher Cache-Buster) — falls relevant, Cache so konfigurieren,
    // dass der ``bsid``-Param ignoriert wird.
    // Trusted? Sonst kein bsid (keine Daten-Leakage an unbekannte Hosts).
    if (!this.isHostTrusted(target.hostname.toLowerCase())) return raw;
    // Schon vorhanden? Nicht doppelt.
    if (target.searchParams.has('bsid')) return raw;
    target.searchParams.set('bsid', this.sessionId);
    return target.toString();
  }

  /** Public-Helper für Template-Binding: ``[href]="withBsid(card.topic_pages[0].url)"``. */
  withBsid(url: string | null | undefined): string {
    return this._withBsid(url);
  }

  hasHiddenCards(msg: ChatMessage): boolean {
    if (!msg.cards) return false;
    return msg.cards.length > (msg.visibleCardCount || 5);
  }

  showMoreCards(msgId: string) {
    // Old visibleCardCount merken, damit wir nach dem Render zur ERSTEN
    // neu enthüllten Card scrollen können — ohne den Scroll-Hint wirken
    // die zusätzlichen Cards für den User "unsichtbar", weil sie unter
    // der Scroll-Region des Messages-Containers erscheinen und die
    // Pagination-Bar (mit aktualisierter "X von Y"-Zahl) den einzigen
    // sofort sichtbaren Effekt zeigt.
    const msg = this.messages().find(m => m.id === msgId);
    const previousCount = msg?.visibleCardCount || 5;
    this.messages.update(all => all.map(m => {
      if (m.id !== msgId || !m.cards) return m;
      const newCount = previousCount + 5;
      return { ...m, visibleCardCount: newCount };
    }));
    // Nach Angular-Re-Render zur ersten neu enthüllten Card scrollen.
    // setTimeout(0) gibt der Change-Detection eine Tick Zeit, das DOM zu
    // aktualisieren. ``block: 'center'`` sorgt dafür, dass die Card
    // mittig in den Viewport rückt — der User sieht eindeutig dass neue
    // Inhalte aufgetaucht sind.
    setTimeout(() => {
      try {
        const container = this.messagesContainer?.nativeElement as HTMLElement | undefined;
        if (!container) return;
        // Alle wlo-card-wrapper innerhalb der Message finden (per msg.id-Anchor).
        const msgEl = container.querySelector(`#msg-${msgId}`);
        if (!msgEl) return;
        const cards = msgEl.querySelectorAll('.wlo-card-wrapper');
        // Erste neu enthüllte Card = Index previousCount (0-based).
        const target = cards[previousCount] as HTMLElement | undefined;
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      } catch { /* never break a click handler */ }
    }, 0);
  }

  // ── Pagination: Load more cards (collection browse) ────
  async loadMore(msgId: string) {
    const msgs = this.messages();
    const msg = msgs.find(m => m.id === msgId);
    if (!msg?.pagination || !msg.pagination.has_more || this.isLoading) return;

    const p = msg.pagination;
    const newSkip = p.skip_count + p.page_size;

    this.isLoading = true;

    try {
      const resp = await this.api.sendMessage(
        this.sessionId,
        `Weitere Inhalte von "${p.collection_title}"`,
        undefined,
        'browse_collection',
        { collection_id: p.collection_id, title: p.collection_title, skip_count: newSkip },
      );

      // Append new cards to existing message and reveal them immediately
      this.messages.update(all => all.map(m => {
        if (m.id !== msgId) return m;
        const merged: WloCard[] = [...(m.cards || []), ...(resp.cards || [])];
        return {
          ...m,
          cards: merged,
          visibleCardCount: merged.length,
          pagination: resp.pagination || undefined,
          content: resp.content,
        };
      }));
    } catch (err) {
      console.error('Load more failed:', err);
    }

    this.isLoading = false;
  }

  // ── Debug ────────────────────────────────────────────────
  toggleDebug() {
    this.showDebug = !this.showDebug;
  }

  // ── UI-Visibility helpers (web-component attributes coerce to string) ──
  /** Whether the 🔍 debug-toggle button should be rendered in the header. */
  get debugButtonVisible(): boolean {
    return this.showDebugButton === true || this.showDebugButton === 'true';
  }
  /** Whether the 🔊 TTS toggle and 🎤 mic-record buttons should render.
   *  Welle E v4+13: zusätzlich an die Backend-Capability gekoppelt — bei
   *  B-API-Anbindung (Audio deaktiviert) bleiben die Buttons aus, auch wenn
   *  der Host ``show-language-buttons`` nicht explizit gesetzt hat. */
  get languageButtonsVisible(): boolean {
    const hostWants = this.showLanguageButtons === true || this.showLanguageButtons === 'true';
    return hostWants && this.speechBackendEnabled;
  }

  // ── Restart ──────────────────────────────────────────────
  restart() {
    // Generate fresh session and persist it (so the next page-load also
    // continues with the new one, not the old).
    this.sessionId = this.generateSessionId();
    this._writeSessionEverywhere(this.sessionId);
    this.messages.set([]);
    this.latestDebug = null;
    this.showGreeting();
  }

  // ── Helpers ──────────────────────────────────────────────
  private addUserMessage(content: string) {
    const msg: ChatMessage = {
      id: this.uid(), sender: 'user', content, timestamp: new Date(),
    };
    this.messages.update(msgs => [...msgs, msg]);
  }

  /**
   * Map a tracer ``phase`` event into a short human label that's safe to
   * show in the loading bubble. Returns ``null`` for events that should
   * not refresh the UI.
   *
   * Step IDs come from ``tracer.start(...)`` calls in chat.py — they are:
   *   safety_classify  → Safety + Classification (~600ms-2.5s)
   *   context          → record event (snapshot, no UI update)
   *   policy           → Policy evaluation (<50ms, mostly invisible)
   *   pattern          → Pattern selection (<100ms)
   *   response         → LLM response generation incl. tool-loop (1-7s, dominant)
   *
   * We update on BOTH ``start`` and ``record`` events. ``end`` is skipped
   * so the label doesn't briefly flash to the next phase's start before
   * the next start arrives.
   */
  private formatPhaseLabel(evt: ChatStreamEvent): string | null {
    if (!evt) return null;
    if (evt.event === 'connected') return 'Verbinde …';
    if (evt.event !== 'phase') return null;
    const data = evt.data || {};
    if (data.kind === 'end') return null;  // ignore end to avoid flicker
    const step = String(data.step || '');
    const map: Record<string, string> = {
      'safety_classify': 'Verstehe deine Anfrage …',
      'context': 'Lade Sitzungs-Kontext …',
      'policy': 'Prüfe Datenschutz …',
      'pattern': 'Wähle die passende Antwort …',
      'wlo_search': 'Durchsuche WLO-Inhalte …',
      'topic_content': 'Lade Themenseiten-Inhalte …',
      'response': 'Formuliere Antwort …',
      'query_meta': 'Suchergebnisse zusammengestellt',
    };
    return map[step] || null;
  }

  /** Update an in-flight loading message's phase label by id. */
  private updateLoadingPhase(loadingId: string, label: string): void {
    this.messages.update(msgs => msgs.map(m =>
      m.id === loadingId && m.isLoading ? { ...m, loadingPhase: label } : m,
    ));
  }

  private addBotMessage(
    content: string, isLoading = false,
    cards?: WloCard[], quickReplies?: string[], debug?: DebugInfo,
    pagination?: PaginationInfo | null,
    queryMetas?: import('../services/api.service').QueryMetaEntry[],
    webLinks?: import('../services/api.service').WebLink[],
    inlineDocuments?: import('../services/api.service').InlineDocument[],
    displayRules?: Record<string, any>,
    topicPage?: import('../services/api.service').TopicPageView | null,
  ): string {
    const id = this.uid();
    const pageSize = pagination?.page_size || 5;
    const msg: ChatMessage = {
      id, sender: 'bot', content, isLoading, cards, quickReplies, debug,
      pagination: pagination || undefined,
      visibleCardCount: pageSize,
      queryMetas: queryMetas || undefined,
      webLinks: webLinks || undefined,
      inlineDocuments: inlineDocuments && inlineDocuments.length ? inlineDocuments : undefined,
      topicPage: (topicPage && topicPage.swimlanes && topicPage.swimlanes.length) ? topicPage : undefined,
      displayRules: displayRules || undefined,
      timestamp: new Date(),
    };
    this.messages.update(msgs => [...msgs, msg]);
    return id;
  }

  private removeMessage(id: string) {
    this.messages.update(msgs => msgs.filter(m => m.id !== id));
  }

  private scrollToBottom() {
    try {
      const el = this.messagesContainer?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    } catch {}
  }

  /** **Public** — scroll the messages container to the bottom.
   *
   *  Aufrufer (z.B. WidgetComponent beim `openChatbot()`-Call) können den
   *  Chat damit auf die letzte Nachricht setzen, sobald sie sichtbar wird.
   *  Toleriert "Container noch nicht im DOM" — silent No-Op statt Error.
   *
   *  Setzt das Flag, das ``ngAfterViewChecked`` beim nächsten Render
   *  konsumiert — funktioniert deshalb auch wenn die Messages-Liste noch
   *  asynchron geladen wird (History-Restore beim Remount).
   */
  scrollToLatest(): void {
    this.scrollToBottomOnNextRender = true;
    // User-Intention zurücksetzen — wenn er aktiv „öffne den Chat"-
    // Action triggert (Reopen, neue Session, externes ``openChatbot()``),
    // will er die letzten Nachrichten sehen, nicht eine vorherige
    // Scroll-Position im Verlauf.
    this._userScrolledAway = false;
    // Sofort + 0/200ms-Stufen für synchron gerenderte Inhalte:
    this.scrollToBottom();
    setTimeout(() => this.scrollToBottom(), 0);
    setTimeout(() => this.scrollToBottom(), 200);
    setTimeout(() => this.scrollToBottom(), 800);
    // Permanenter Auto-Follow-Observer aufsetzen (idempotent).
    this._setupAutoFollowTail();
  }

  /** Marker: Hat der User aktiv hoch-gescrollt? Dann scrollt der
   *  Auto-Follow NICHT mehr automatisch ans Ende — sonst würde jede
   *  neue Bot-Antwort den User aus der älteren Stelle reißen.
   *  ``scrollToLatest()`` (z.B. beim Reopen) resetted das Flag. */
  private _userScrolledAway = false;
  private _autoFollowObserver: MutationObserver | null = null;
  private _autoFollowScrollListener: (() => void) | null = null;

  /** Permanenter MutationObserver auf dem Messages-Container.
   *  Scrollt bei JEDER DOM-Mutation ans Ende, außer der User hat sich
   *  manuell weggescrollt. So bleibt der Chat während Bot-Streaming-
   *  Antworten am Tail, und nach close+reopen sieht der User immer die
   *  letzten Nachrichten — egal wie lange Backend-Roundtrips dauern.
   *
   *  Idempotent — Setup nur einmal pro Component-Lifecycle. */
  private _setupAutoFollowTail(): void {
    if (this._autoFollowObserver) return;
    const container = this.messagesContainer?.nativeElement;
    if (!container || typeof MutationObserver === 'undefined') return;

    // User-Scroll-Detection: wenn der User wegscrollt → Flag setzen,
    // damit Auto-Follow ihn nicht zurückzieht. Toleranz 60px: solange
    // er im Bereich „nahe Boden" ist, gilt er als „will tail folgen".
    const SCROLL_TOLERANCE_PX = 60;
    this._autoFollowScrollListener = () => {
      const max = container.scrollHeight - container.clientHeight;
      const distFromBottom = max - container.scrollTop;
      this._userScrolledAway = distFromBottom > SCROLL_TOLERANCE_PX;
    };
    container.addEventListener('scroll', this._autoFollowScrollListener, { passive: true });

    this._autoFollowObserver = new MutationObserver(() => {
      if (this._userScrolledAway) return;
      container.scrollTop = container.scrollHeight;
    });
    this._autoFollowObserver.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  private scrollToMessage(msgId: string) {
    try {
      const el = document.getElementById('msg-' + msgId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch {}
  }

  /** Strict format check for our session-IDs — schützt URL-bsid-Pickup vor
   *  Injection durch Drittseiten ("?bsid=evil-tracking-id"). */
  private _isValidSessionId(s: string | null | undefined): boolean {
    if (!s || typeof s !== 'string') return false;
    // Format: "bb-" + 36-char UUID v4 (mit/ohne Bindestriche), max 80 chars
    return /^bb-[0-9a-f-]{32,40}$/i.test(s) && s.length <= 80;
  }

  /** 3-Stufen-Resolution. Returnt null wenn nichts gefunden / alle invalid. */
  private _resolvePersistedSessionId(): string | null {
    // Stufe A: URL-Parameter ?bsid=… (Cross-TLD-Handoff)
    try {
      const url = new URL(window.location.href);
      const fromUrl = url.searchParams.get('bsid');
      if (this._isValidSessionId(fromUrl)) {
        // Aus URL entfernen, damit die ID nicht weiter sichtbar mitwandert
        // (Bookmark-Sharing, Referer-Leaks an Drittseiten).
        url.searchParams.delete('bsid');
        const cleaned = url.pathname + (url.searchParams.toString() ? '?' + url.searchParams.toString() : '') + url.hash;
        try { history.replaceState({}, '', cleaned); } catch { /* ignore */ }
        this._resumedViaBsid = true;
        return fromUrl;
      }
    } catch { /* ignore — never fail boot on URL parse */ }

    // Stufe B: Cookie (Cross-Subdomain)
    const fromCookie = this._readCookie(this.sessionKey);
    if (this._isValidSessionId(fromCookie)) return fromCookie;

    // Stufe C: localStorage (Origin-spezifischer Default)
    try {
      const fromLs = localStorage.getItem(this.sessionKey);
      if (this._isValidSessionId(fromLs)) return fromLs;
    } catch { /* ignore */ }

    return null;
  }

  /** Schreibt die Session-ID in alle aktiven Storages. */
  private _writeSessionEverywhere(id: string): void {
    try { localStorage.setItem(this.sessionKey, id); } catch { /* ignore */ }
    if (this.sessionCookieDomain) {
      this._writeCookie(this.sessionKey, id);
    }
  }

  /** Schreibt ein Session-Cookie mit konfigurierter Domain. */
  private _writeCookie(name: string, value: string): void {
    try {
      const maxAge = typeof this.sessionCookieMaxAge === 'string'
        ? parseInt(this.sessionCookieMaxAge, 10) || 30 * 24 * 60 * 60
        : this.sessionCookieMaxAge;
      // Secure-Flag: nur über HTTPS schicken (Pflicht ab SameSite=None,
      // Best-Practice bei Lax). Lokal über http://localhost ignoriert
      // der Browser das Secure-Flag freundlicherweise.
      const isHttps = location.protocol === 'https:';
      const parts = [
        `${name}=${encodeURIComponent(value)}`,
        `Domain=${this.sessionCookieDomain}`,
        `Path=/`,
        `Max-Age=${maxAge}`,
        `SameSite=Lax`,
      ];
      if (isHttps) parts.push('Secure');
      document.cookie = parts.join('; ');
    } catch { /* ignore */ }
  }

  /** Liest den Wert eines Cookies anhand des Namens. */
  private _readCookie(name: string): string | null {
    try {
      const re = new RegExp('(?:^|;\\s*)' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]+)');
      const m = document.cookie.match(re);
      return m ? decodeURIComponent(m[1]) : null;
    } catch {
      return null;
    }
  }

  /** Löscht das Session-Cookie (nutzt Max-Age=0 unter derselben Domain). */
  private _deleteCookie(name: string): void {
    if (!this.sessionCookieDomain) return;
    try {
      document.cookie = `${name}=; Domain=${this.sessionCookieDomain}; Path=/; Max-Age=0; SameSite=Lax`;
    } catch { /* ignore */ }
  }

  private generateSessionId(): string {
    // Prefer cryptographically strong UUID v4 (122 bits entropy, collision-safe).
    try {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return 'bb-' + crypto.randomUUID();
      }
      if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
        const buf = new Uint8Array(16);
        crypto.getRandomValues(buf);
        return 'bb-' + Array.from(buf, b => b.toString(16).padStart(2, '0')).join('');
      }
    } catch { /* fall through */ }
    // Last-resort fallback for very old browsers
    return 'bb-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  private uid(): string {
    return Math.random().toString(36).slice(2, 10);
  }

  private stripMarkdown(text: string): string {
    return text
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/\[(.*?)\]\(.*?\)/g, '$1')
      .replace(/#{1,6}\s/g, '')
      .replace(/[`~]/g, '');
  }

  /** Cache pro (sender|text) → SafeHtml. Identische Inputs liefern bei
   *  jeder Change-Detection-Auswertung dieselbe Instanz zurück, damit
   *  Angular keinen "Wert geändert"-Diff sieht und das ``innerHTML`` NICHT
   *  neu setzt. Ohne diesen Cache liefert ``bypassSecurityTrustHtml()``
   *  bei jedem CD-Tick ein neues Wrapper-Objekt — Angular ersetzt dann
   *  das DOM zwischen Mousedown und Mouseup, das Click-Event entsteht nicht,
   *  Links brauchen 2 Klicks. WeakMap geht nicht weil der Key ein String ist;
   *  Map mit primitivem Key reicht und altert mit der Component-Lebenszeit
   *  (=> kein Memory-Leak über Page-Wechsel).
   */
  private readonly _renderCache = new Map<string, SafeHtml>();

  renderMarkdown(text: string, sender: 'bot' | 'user' = 'bot'): SafeHtml {
    if (!text) return this.sanitizer.bypassSecurityTrustHtml('');
    // sessionId Teil des Cache-Keys: nach resetSession() ändert sich die
    // bsid, die ``_withBsid`` in die Link-hrefs einbaut — ohne sessionId im
    // Key würde eine gecachte Bubble mit ALTER bsid wiederverwendet.
    const cacheKey = sender + '|' + (this.sessionId || '') + '|' + text;
    const cached = this._renderCache.get(cacheKey);
    if (cached) return cached;
    // Backend-Sentinel ``<!-- boerdi:printable-canvas|... -->`` strippen,
    // bevor marked parsed wird. Diese Marker signalisieren dem Frontend
    // (siehe isPrintableCanvasMaterial + printCanvasMaterial), dass das
    // angehängte Markdown via Print-Button als PDF abgreifbar ist. Im
    // Render-Output sind sie nicht erwünscht — DOMPurify würde HTML-
    // Kommentare zwar grundsätzlich abräumen, aber sicherer ist sie hier
    // schon vor marked.js zu entfernen.
    const withoutCanvasSentinel = text.replace(
      /<!--\s*boerdi:printable-canvas\|[^|]*\|[^>]*?\s*-->\s*/g,
      '',
    );
    // LaTeX-Stripping via gemeinsamen Helper — wandelt ``\frac12``,
    // ``\frac{1}{2}``, ``\sqrt{2}`` und ``$x$`` in lesbaren Text.
    const withoutLatex = this.stripLatex(withoutCanvasSentinel);
    // Backend-Sentinel ``@@ICON:NAME@@`` durch Inline-SVG-Span ersetzen,
    // bevor marked parsed. Backend emittiert das vor jedem Inline-Card-
    // Link in Lotsen/Inline-Modus, damit der User Themenseiten,
    // Sammlungen und Einzel-Inhalte optisch unterscheiden kann.
    // Ersatz passiert VOR marked, damit das Span IN den ``<a>``-Tag
    // wandert (Sentinel steht innerhalb der Link-Klammern beim Backend).
    //
    // ``data-bb-type`` auf dem Icon-Span trägt das deutsche Label
    // (z.B. "Sammlung", "Video"), aus dem der ``<a>``-Post-Process
    // einen ``title``-Tooltip baut — damit User per Maus-Hover sehen,
    // welcher Materialtyp ein Inline-Treffer ist.
    const withIcons = withoutLatex.replace(/@@ICON:([a-z_]+)@@/g, (_match, name) => {
      const key = name as keyof typeof ICONS;
      const svg = ICONS[key];
      if (!svg) return '';
      const label = INLINE_ICON_LABEL[name] || '';
      const attr = label ? ` data-bb-type="${label}"` : '';
      return `<span class="bb-inline-icon"${attr}>${svg}</span>`;
    });
    // Use marked to parse Markdown to HTML, then DOMPurify to defang any
    // injected HTML/JS coming from bot output, persisted history, or tool
    // results. NEVER bypass sanitization on raw text — replace-based regex
    // builders are not safe against `<script>` / `onerror=` injection.
    //
    // For USER messages we use ``parseInline`` instead of ``parse``: users
    // type plain text (no headings/lists/codeblocks), and ``parse`` would
    // wrap the message in a block-level ``<p>`` which adds unwanted
    // vertical padding to user bubbles. ``parseInline`` returns the text
    // with inline markup only — no outer block element.
    let html: string;
    if (sender === 'user') {
      html = marked.parseInline(withIcons, { async: false, gfm: true, breaks: true }) as string;
    } else {
      html = marked.parse(withIcons, { async: false, gfm: true, breaks: true }) as string;
    }
    // Inline-SVG-Icons aus Backend-Sentinels müssen die DOMPurify-Sanitization
    // überleben — der ``svg``-Profile erlaubt die nötigen Tags + Attribute.
    // Sicherheit: trotzdem werden Skript-Tags, on*-Attribute usw. weiter
    // gestripped, weil HTML+SVG-Profile additiv sind.
    const clean = DOMPurify.sanitize(html, {
      ADD_ATTR: ['target', 'rel', 'data-bb-type'],
      USE_PROFILES: { html: true, svg: true, svgFilters: true },
    });
    // Post-Process: (1) Externe Links (NICHT auf der Trusted-Hosts-Liste)
    // in neuem Tab öffnen — Tabnabbing-sicher via ``rel="noopener noreferrer"``.
    // Trusted-Hosts (Lotsen-Liste) bleiben same-tab, damit das Outgoing-
    // Link-Rewrite des Widgets ``?bsid=<sid>`` anhängen kann und die Session
    // über die TLD-Grenze erhalten bleibt. (2) Inline-Card-Title-Wrap für
    // korrektes Icon-Title-CSS. Beide Schritte teilen denselben DOM-Parser.
    let final = clean;
    if (clean.includes('<a ')) {
      try {
        const tmp = document.createElement('div');
        tmp.innerHTML = clean;
        tmp.querySelectorAll('a').forEach(a => {
          // (1) Target-Klassifikation + bsid-Rewrite. Anker (#frag), Mailto,
          // Tel, javascript: und same-origin-Pfad-Links unangetastet lassen.
          const href = a.getAttribute('href') || '';
          if (href && !href.startsWith('#') && !href.startsWith('javascript:')
              && !href.startsWith('mailto:') && !href.startsWith('tel:')) {
            let hostname = '';
            try {
              hostname = new URL(href, window.location.href).hostname.toLowerCase();
            } catch { hostname = ''; }
            const sameOrigin = hostname && hostname === window.location.hostname.toLowerCase();
            const trusted = !!hostname && this.isHostTrusted(hostname);
            // Externe + nicht-vertrauenswürdige Hosts → neuer Tab + Warntooltip.
            // Same-origin und trusted hosts → same tab (für ?bsid=-Handoff).
            if (hostname && !sameOrigin && !trusted) {
              if (!a.hasAttribute('target')) a.setAttribute('target', '_blank');
              if (!a.hasAttribute('rel')) a.setAttribute('rel', 'noopener noreferrer');
              // Warntooltip nur setzen wenn kein anderer (z.B. Material-Typ-
              // Label vom Inline-Card-Link) bereits einen ``title`` gesetzt
              // hat — sonst kombinieren wir den Material-Typ-Tooltip mit
              // der Warnung, damit der User beide Infos sieht.
              const existingTitle = a.getAttribute('title') || '';
              const warn = 'Achtung! Externe URL.';
              if (!existingTitle) {
                a.setAttribute('title', warn);
              } else if (!existingTitle.includes(warn)) {
                a.setAttribute('title', `${existingTitle} — ${warn}`);
              }
            }
            // Bei trusted-Hosts ``?bsid=`` schon im href verankern — dann
            // funktionieren auch Right-Click→Copy-Link, Middle-Click und
            // Screen-Reader, nicht nur Plain-Left-Click via document-handler.
            if (trusted) {
              const rewritten = this._withBsid(href);
              if (rewritten !== href) a.setAttribute('href', rewritten);
            }
          }

          // (2) Inline-Card-Title-Wrap (nur wenn Backend-Inline-Icon-Span
          // als erstes Child vorhanden ist).
          const iconSpan = a.querySelector(':scope > .bb-inline-icon');
          if (!iconSpan) return;
          // (2a) Material-Typ-Label vom Icon-Span auf Parent-<a> als
          // ``title``-Tooltip durchreichen. User-Maus-Hover über das Icon
          // (oder den ganzen Link) zeigt dann "Sammlung", "Video" etc.
          const typeLabel = iconSpan.getAttribute('data-bb-type') || '';
          if (typeLabel && !a.hasAttribute('title')) {
            a.setAttribute('title', typeLabel);
            // Icon-Span selbst kriegt auch ein title-Attribut für den Fall,
            // dass jemand explizit nur das Icon hovert (manche Browser
            // zeigen das Parent-title nicht wenn ein Child eigene Tooltip-
            // Quellen hat).
            iconSpan.setAttribute('title', typeLabel);
          }
          const titleSpan = document.createElement('span');
          titleSpan.className = 'bb-link-title';
          let node = iconSpan.nextSibling;
          while (node) {
            const next = node.nextSibling;
            titleSpan.appendChild(node);
            node = next;
          }
          if (titleSpan.firstChild?.nodeType === 3) {
            const t = titleSpan.firstChild as Text;
            t.textContent = (t.textContent ?? '').replace(/^\s+/, '');
          }
          a.appendChild(titleSpan);
        });
        final = tmp.innerHTML;
      } catch { /* fall back to unprocessed clean */ }
    }
    const safe = this.sanitizer.bypassSecurityTrustHtml(final);
    this._renderCache.set(cacheKey, safe);
    return safe;
  }
}
