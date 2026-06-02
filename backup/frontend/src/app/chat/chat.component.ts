import {
  Component, ElementRef, HostListener, NgZone, ViewChild, AfterViewChecked, OnInit, OnDestroy, signal, Input,
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
export class ChatComponent implements OnInit, AfterViewChecked, OnDestroy {
  /** Material-Symbols-Icon-Set, im Template referenzierbar. */
  readonly ICONS = ICONS;
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
  /** When the canvas is showing markdown, next user message becomes an edit request. */
  @Input() canvasActiveMarkdown = '';
  /** When true, card lists in the chat are hidden (canvas shows them instead). */
  @Input() hideCards = false;
  /** True when the canvas is currently showing the *cards* pane.
   *  Used to suppress the compact collection-shortcuts row that would
   *  otherwise duplicate the buttons already on the canvas cards. */
  @Input() canvasShowingCards = false;
  /** Snapshot of current canvas state — forwarded to backend so the LLM
   *  can reference what the user sees on the right pane.
   *  Shape: {mode, title, material_type, markdown, cards_count}
   */
  @Input() canvasState: Record<string, any> | null = null;
  /** Lotsen-Modus aktiv? Frontend-defense-in-depth: das Backend filtert
   *  Guide-QRs aus, wenn der Toggle aus ist; aber falls doch mal einer
   *  durchschlägt (alter Cache, Race-Condition), rendern wir ihn HIER
   *  zusätzlich nicht als hervorgehobenen blauen Button. Stattdessen:
   *  wir blenden den ``__guide__|...``-Eintrag komplett aus, weil die
   *  Lotsen-Funktion bewusst deaktiviert wurde. */
  @Input() guideModeActive = false;
  /** Widget-Embed-Modi — vom WidgetComponent forwarded. Steuern, ob
   *  Cards/Canvas/KI-Content/Quick-Replies dieser Embed-Instanz
   *  überhaupt angezeigt werden. Default jeweils ``true`` — bestehende
   *  Integrationen sehen keine Änderung.
   *  Bei ``cardsEnabled=false`` werden Kacheln im Template ausgeblendet;
   *  das Backend liefert dann ohnehin Inline-Markdown-Links im Bot-Text. */
  @Input() cardsEnabled: boolean | string = true;
  @Input() canvasEnabled: boolean | string = true;
  @Input() aiContentEnabled: boolean | string = true;
  @Input() quickRepliesEnabled: boolean | string = true;
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
   *  strings) into a true boolean. Default = true, so an absent attribute
   *  preserves the legacy "all features on" behaviour. Only the explicit
   *  string ``"false"`` (or the literal boolean ``false``) toggles off. */
  private modeFlag(v: boolean | string): boolean {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.toLowerCase() !== 'false';
    return true;
  }
  get cardsEnabledBool(): boolean { return this.modeFlag(this.cardsEnabled); }
  get canvasEnabledBool(): boolean { return this.modeFlag(this.canvasEnabled); }
  get aiContentEnabledBool(): boolean { return this.modeFlag(this.aiContentEnabled); }
  get quickRepliesEnabledBool(): boolean { return this.modeFlag(this.quickRepliesEnabled); }

  ngOnInit() {
    // Configure API base URL if provided as attribute
    if (this.apiUrl) {
      this.api.setBaseUrl(this.apiUrl);
    }

    // Tell ApiService which embed modes the host has configured — only
    // explicit ``false`` values are forwarded to the backend; everything
    // else is left as undefined so older backends and Bestandsintegrationen
    // continue to behave exactly as before.
    this.api.setWidgetModes(
      this.cardsEnabledBool ? undefined : false,
      this.canvasEnabledBool ? undefined : false,
      this.aiContentEnabledBool ? undefined : false,
      this.quickRepliesEnabledBool ? undefined : false,
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
      // Try to restore the conversation from the backend.
      this.restoreHistory();
    } else {
      this.showGreeting();
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
      'Was ist WirLernenOnline?',
      'Erstell mir ein neues Material.',
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
    for (const m of history) {
      const content = (m.content || '').trim();
      if (!content) continue;
      if (m.role === 'user') {
        this.addUserMessage(content);
      } else if (m.role === 'assistant') {
        this.addBotMessage(content);
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

      // Edit-routing: only when the canvas shows markdown AND the user
      // sent an explicit edit command. Search/browse questions ("Zeig mir",
      // "Suche ...", "Was ist ...") must stay unrouted so the backend
      // classifier can decide. Otherwise we'd hijack every message as an
      // edit against the current canvas document.
      const isEdit = !!(this.canvasActiveMarkdown && this.canvasActiveMarkdown.length > 0
                        && this.isEditCommand(msg));

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
        resp = isEdit
          ? await this.api.sendMessageStream(this.sessionId, msg, onEvent, envOverride,
              'canvas_edit', {
                current_markdown: this.canvasActiveMarkdown,
                edit_instruction: msg,
              }, this.canvasState)
          : await this.api.sendMessageStream(this.sessionId, msg, onEvent, envOverride,
              undefined, undefined, this.canvasState);
      } catch (streamErr) {
        // Stream-API failed (network, proxy, parser) → silent fallback to
        // the legacy non-streaming endpoint so the user still gets an
        // answer. This also covers older backends without the /stream route.
        // eslint-disable-next-line no-console
        console.warn('chat stream failed, falling back to POST /chat:', streamErr);
        resp = isEdit
          ? await this.api.sendMessage(this.sessionId, msg, envOverride, 'canvas_edit', {
              current_markdown: this.canvasActiveMarkdown,
              edit_instruction: msg,
            }, this.canvasState)
          : await this.api.sendMessage(this.sessionId, msg, envOverride,
              undefined, undefined, this.canvasState);
      }

      // Remove loading, add real response
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
      this.scrollTargetId = botMsgId;

      this.latestDebug = resp.debug;

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

  /** Heuristic: is the user message an explicit EDIT instruction for
   *  the currently-open canvas document?
   *
   *  Positive signals (edit): "mach es einfacher", "füge ... hinzu",
   *  "ergänze ...", "kürzer fassen", "ersetze ...", "lösche ...",
   *  "mehr beispiele", "als ... umwandeln", plus the hard-coded
   *  quick-reply labels from the edit handler.
   *
   *  Negative signals (NOT edit — will go to classifier): "zeig mir",
   *  "suche", "finde", "welche/welches/welcher", "gibt es", "was ist",
   *  "wer war", "erstelle", "generiere", "mach mir ein neues ...",
   *  any question starting with a Fragewort.
   *
   *  When neither side matches, default to NON-edit — safer: the backend
   *  classifier can still route to INT-W-11 if it really is an edit.
   */
  private isEditCommand(msg: string): boolean {
    if (!msg) return false;
    const low = msg.trim().toLowerCase();

    // Hard negative: clear search / browse / create / question → never edit
    const negativeStart = [
      'zeig mir', 'zeige mir', 'zeig ', 'zeige ',
      'suche', 'such ', 'finde', 'gibt es', 'hast du', 'hat wlo',
      'welche', 'welches', 'welcher',
      'was ist', 'was sind', 'wer ist', 'wer war', 'wie ',
      'warum', 'wozu', 'wo ',
      'erstelle', 'erstell ', 'generiere', 'generier', 'bau mir',
      'schreib mir ein', 'schreib ein', 'schreib eine',
      'mach mir ein ', 'mach mir eine ', 'mach ein ', 'mach eine ',
      'neues thema', 'neuer lernpfad', 'neuer pfad',
    ];
    if (negativeStart.some(t => low.startsWith(t))) return false;

    // Positive edit signals: verb or explicit edit phrase
    const positiveAny = [
      'einfacher', 'schwieriger', 'schwerer', 'kürzer', 'laenger', 'länger',
      'mehr beispiele', 'mehr aufgaben', 'mehr uebungen', 'mehr übungen',
      'weniger ',
      'ergänze', 'ergaenze', 'füge ', 'fuege ', 'hinzu',
      'entferne', 'lösche', 'loesche', 'streiche',
      'ersetze', 'tausche', 'ändere', 'aendere', 'passe an', 'anpassen',
      'korrigiere', 'korrektur', 'formuliere um', 'umformulieren',
      'mit lösungen', 'mit loesungen', 'ohne lösungen', 'ohne loesungen',
      'für klasse', 'fuer klasse',
      'als arbeitsblatt umwandeln', 'als quiz umwandeln', 'als infoblatt umwandeln',
      'zurück zum original', 'zurueck zum original',
      'noch einfacher', 'noch schwerer',
    ];
    if (positiveAny.some(t => low.includes(t))) return true;

    // Default: not an edit — let the backend classifier decide.
    return false;
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
    if (msg.sender !== 'bot' || !msg.content) return false;
    if (this.isLearningPath(msg)) return false;
    return this.PRINTABLE_CANVAS_RE.test(msg.content);
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
      // Card-Pipeline v2: ``link`` bevorzugen, sonst alter Fallback.
      const href = c.link || c.url || c.wlo_url || '#';
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
    // Card-Pipeline v2: ``link`` ist die Single Source of Truth, vom Backend
    // via build_card_link befüllt. Wenn vorhanden, nutzen wir es; sonst
    // fallback auf die alte Auswahl-Reihenfolge (Phase 10 zieht diesen
    // Fallback dann ganz raus).
    const url = card.link || card.wlo_url || card.url;
    if (url) window.open(url, '_blank');
  }

  /**
   * Liefert das passende Material-Symbol-Inline-SVG für den Inhaltstyp einer
   * Kachel. Template-Verwendung:
   *   <span class="card-content-icon" [innerHTML]="getCardIcon(card) | safeSvg"></span>
   */
  getCardIcon(card: WloCard): string {
    if (card.node_type === 'collection') {
      // Themenseiten bekommen ihr eigenes Icon — sie sind kuratierte
      // Webseiten, keine reinen Sammlungen, und unterscheiden sich
      // visuell vom "Stapel"-Symbol der klassischen Sammlung.
      if (Array.isArray(card.topic_pages) && card.topic_pages.length) return ICONS.topic;
      return ICONS.auto_stories;
    }
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
    if (card.node_type === 'collection') {
      // Sammlungen unterscheiden wir über das Kind-Badge rechts;
      // hier zeigen wir konkretere Info, falls vorhanden.
      if (card.topic_pages && card.topic_pages.length) return 'Themenseite';
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
    return card.node_type === 'collection'
      && Array.isArray(card.topic_pages) && card.topic_pages.length > 0;
  }
  isSammlung(card: WloCard): boolean {
    return card.node_type === 'collection'
      && !(Array.isArray(card.topic_pages) && card.topic_pages.length > 0);
  }
  isInhalt(card: WloCard): boolean {
    return card.node_type !== 'collection';
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
    try {
      window.location.href = url;
    } catch {
      window.open(url, '_self', 'noopener');
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
        this.canvasState,
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
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

  /** Fetch a further page of a collection's contents. Called by the
   *  canvas's "Mehr laden"-button. Response is merged by the widget
   *  via append-mode in handlePageAction(canvas_show_cards).
   */
  async browseCollectionPage(nodeId: string, title: string, skipCount: number) {
    if (this.isLoading) return;
    this.isLoading = true;
    try {
      const resp = await this.api.sendMessage(
        this.sessionId,
        `Weitere Inhalte von "${title}"`,
        undefined,
        'browse_collection',
        { collection_id: nodeId, title, skip_count: skipCount },
        this.canvasState,
      );
      // No chat bubble for load-more; the canvas handles the merge.
      this.latestDebug = resp.debug;
      this.dispatchPageAction(resp.page_action);
    } catch (err) {
      // swallow — widget resets loading state
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
        this.canvasState,
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
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

  /** Remix a card — create a new material of the same type based on the
   *  chosen resource. Sends the full metadata set + source URL to the
   *  backend, which pulls the full text (text-extraction service) before
   *  calling the LLM so the new material is actually grounded in the
   *  original content.
   */
  async remixCard(card: WloCard): Promise<void> {
    if (!card || this.isLoading) return;
    const title = (card.title || '').trim() || 'dem Inhalt';

    // User-visible chat bubble so the interaction is transparent. The
    // actual remix runs via the canvas_remix action below — no classifier
    // roundtrip needed, the backend goes straight into the remix handler.
    this.addUserMessage(`🔄 Remix: „${title}"`);
    this.isLoading = true;
    const loadingId = this.addBotMessage('', true);
    this.scrollTargetId = loadingId;

    try {
      const envOverride = Object.keys(this.parsedPageContext).length
        ? { page_context: this.parsedPageContext }
        : undefined;
      const resp = await this.api.sendMessage(
        this.sessionId,
        `Remix: ${title}`,
        envOverride,
        'canvas_remix',
        {
          title: card.title || '',
          url: card.url || card.wlo_url || '',
          description: card.description || '',
          keywords: card.keywords || [],
          disciplines: card.disciplines || [],
          educational_contexts: card.educational_contexts || [],
          learning_resource_types: card.learning_resource_types || [],
          publisher: card.publisher || '',
          license: card.license || '',
        },
        this.canvasState,
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(
        resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination,
      );
      this.scrollTargetId = botMsgId;
      this.latestDebug = resp.debug;
      this.dispatchPageAction(resp.page_action);
    } catch (err) {
      this.removeMessage(loadingId);
      this.addBotMessage(
        `Den Remix für „${title}" konnte ich leider nicht erstellen. Versuch es nochmal.`,
      );
    }
    this.isLoading = false;
  }

  // ── Visible cards helper ────────────────────────────────
  getVisibleCards(msg: ChatMessage): WloCard[] {
    if (!msg.cards) return [];
    const limit = msg.visibleCardCount || 5;
    return msg.cards.slice(0, limit);
  }

  /** Collection cards from a message — used by the compact action-bar
   *  that stays in the chat even when the full card grid lives in the canvas.
   */
  getCollectionCards(msg: ChatMessage): WloCard[] {
    if (!msg.cards) return [];
    return msg.cards.filter(c => c.node_type === 'collection' && c.node_id);
  }

  hasCollectionCards(msg: ChatMessage): boolean {
    return this.getCollectionCards(msg).length > 0;
  }

  /** Exposed helper so the template can use the typ-aware URL resolver. */
  cardUrl(card: WloCard | null | undefined): string {
    return getCardPrimaryUrl(card);
  }

  hasHiddenCards(msg: ChatMessage): boolean {
    if (!msg.cards) return false;
    return msg.cards.length > (msg.visibleCardCount || 5);
  }

  showMoreCards(msgId: string) {
    this.messages.update(all => all.map(m => {
      if (m.id !== msgId || !m.cards) return m;
      const newCount = (m.visibleCardCount || 5) + 5;
      return { ...m, visibleCardCount: newCount };
    }));
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

      // Append new cards to existing message
      this.messages.update(all => all.map(m => {
        if (m.id !== msgId) return m;
        const merged: WloCard[] = [...(m.cards || []), ...(resp.cards || [])];
        return {
          ...m,
          cards: merged,
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
  /** Whether the 🔊 TTS toggle and 🎤 mic-record buttons should render. */
  get languageButtonsVisible(): boolean {
    return this.showLanguageButtons === true || this.showLanguageButtons === 'true';
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
      'safety_classify': 'Klassifiziere die Anfrage …',
      'context': 'Lade Sitzungs-Kontext …',
      'policy': 'Prüfe Datenschutz-Policy …',
      'pattern': 'Wähle Antwort-Pattern …',
      'response': 'Formuliere Antwort …',
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
  ): string {
    const id = this.uid();
    const pageSize = pagination?.page_size || 5;
    const msg: ChatMessage = {
      id, sender: 'bot', content, isLoading, cards, quickReplies, debug,
      pagination: pagination || undefined,
      visibleCardCount: pageSize,
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
    const cacheKey = sender + '|' + text;
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
    const withIcons = withoutLatex.replace(/@@ICON:([a-z_]+)@@/g, (_match, name) => {
      const key = name as keyof typeof ICONS;
      const svg = ICONS[key];
      if (!svg) return '';
      return `<span class="bb-inline-icon">${svg}</span>`;
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
      ADD_ATTR: ['target', 'rel'],
      USE_PROFILES: { html: true, svg: true, svgFilters: true },
    });
    // Post-Process: bei Inline-Card-Links den Titel in ``.bb-link-title``
    // wrappen. CSS setzt dann ``text-decoration: none`` auf das ``<a>`` und
    // ``text-decoration: underline`` auf das Title-Span — damit der
    // Underline NICHT durch den ``margin-right``-Gap zwischen Icon und
    // Titel zieht (das war optisch unschön: Underline begann vor dem
    // Titel-Text). Wirkt nur auf Links die ein ``.bb-inline-icon``-Span
    // als ersten Child haben (= Backend-Inline-Card-Links). Regulär
    // Markdown-Links bleiben durchgehend unterstrichen wie bisher.
    let final = clean;
    if (clean.includes('bb-inline-icon')) {
      try {
        const tmp = document.createElement('div');
        tmp.innerHTML = clean;
        tmp.querySelectorAll('a').forEach(a => {
          const iconSpan = a.querySelector(':scope > .bb-inline-icon');
          if (!iconSpan) return;
          // Alle Nodes nach dem Icon einsammeln und in eine Title-Span wrappen.
          const titleSpan = document.createElement('span');
          titleSpan.className = 'bb-link-title';
          let node = iconSpan.nextSibling;
          while (node) {
            const next = node.nextSibling;
            titleSpan.appendChild(node);
            node = next;
          }
          // Leerzeichen vom Anfang abschneiden (marked.js fügt manchmal
          // welche zwischen Inline-HTML-Element und Folge-Text ein).
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
