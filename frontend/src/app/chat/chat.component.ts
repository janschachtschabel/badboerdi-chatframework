import {
  Component, ElementRef, HostListener, NgZone, ViewChild, AfterViewChecked, OnInit, signal, Input,
  Output, EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService, ChatMessage, WloCard, DebugInfo, PaginationInfo } from '../services/api.service';
import { getCardPrimaryUrl } from '../services/card-utils';

@Component({
  selector: 'badboerdi-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
})
export class ChatComponent implements OnInit, AfterViewChecked {
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
  /** Override the initial greeting. */
  @Input() greeting = '';
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
  /** Emitted for every page_action from the backend (host + widget integration). */
  @Output() pageAction = new EventEmitter<{ action: string; payload: any }>();

  private parsedPageContext: Record<string, any> = {};

  // Scroll target: ID of the message to scroll into view
  private scrollTargetId: string | null = null;

  constructor(private api: ApiService, private zone: NgZone, private sanitizer: DomSanitizer) {}

  ngOnInit() {
    // Configure API base URL if provided as attribute
    if (this.apiUrl) {
      this.api.setBaseUrl(this.apiUrl);
    }

    // Parse page-context attribute (JSON string or already an object)
    if (typeof this.pageContext === 'string' && this.pageContext.trim()) {
      try { this.parsedPageContext = JSON.parse(this.pageContext); }
      catch { this.parsedPageContext = { raw: this.pageContext }; }
    } else if (typeof this.pageContext === 'object' && this.pageContext) {
      this.parsedPageContext = this.pageContext as Record<string, any>;
    }

    // Session persistence
    const persist = this.persistSession === true || this.persistSession === 'true';
    let resumed = false;
    if (persist) {
      try {
        const stored = localStorage.getItem(this.sessionKey);
        if (stored) {
          this.sessionId = stored;
          resumed = true;
        } else {
          this.sessionId = this.generateSessionId();
          localStorage.setItem(this.sessionKey, this.sessionId);
        }
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
  }

  /** Public API: clear current session and start fresh. Callable from host page. */
  resetSession() {
    try { localStorage.removeItem(this.sessionKey); } catch { /* ignore */ }
    this.sessionId = this.generateSessionId();
    try { localStorage.setItem(this.sessionKey, this.sessionId); } catch { /* ignore */ }
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
      const resp = isEdit
        ? await this.api.sendMessage(this.sessionId, msg, envOverride, 'canvas_edit', {
            current_markdown: this.canvasActiveMarkdown,
            edit_instruction: msg,
          }, this.canvasState)
        : await this.api.sendMessage(this.sessionId, msg, envOverride,
            undefined, undefined, this.canvasState);

      // Remove loading, add real response
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
      this.scrollTargetId = botMsgId;

      this.latestDebug = resp.debug;

      // Handle page action (share with host page / widget parent)
      this.dispatchPageAction(resp.page_action);

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
    // DomSanitizer into the new window).
    const mdToHtml = (text: string): string => {
      let html = text
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
      const href = c.url || c.wlo_url || '#';
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
  @page { size: A4; margin: 18mm 16mm 18mm 16mm; }
  body { font: 11pt/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #222; margin: 0; padding: 24px; max-width: 780px; }
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
  .print-bar { position: fixed; top: 0; right: 0; padding: 10px 14px; background: #fff; border-bottom-left-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,.1); }
  .print-bar button { padding: 6px 14px; background: #3b82f6; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 10pt; }
  .print-bar button:hover { background: #2563eb; }
  @media print { .print-bar { display: none; } body { padding: 0; } }
</style>
</head>
<body>
<div class="print-bar"><button onclick="window.print()">🖨 Drucken / Als PDF speichern</button></div>
<header>
  <h1>🦉 Lernpfad</h1>
  <span class="meta">BadBoerdi · ${esc(today)}</span>
</header>
<main>
  ${mdToHtml(msg.content)}
</main>
${cards.length ? `<section class="cards"><h2>Verwendete Inhalte (${cards.length})</h2>${cardsHtml}</section>` : ''}
<footer>Erstellt mit BadBoerdi · WirLernenOnline.de · ${esc(today)}</footer>
<script>window.addEventListener('load', () => setTimeout(() => window.print(), 250));</script>
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
    const sentences = this.splitSentences(text);
    if (!sentences.length) { this.isSpeaking = false; return; }

    this.audioQueue = [];
    this.audioAbort = new AbortController();
    const signal = this.audioAbort.signal;

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

    if (!signal.aborted) {
      this.zone.run(() => { this.isSpeaking = false; });
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

      const cleanup = () => {
        URL.revokeObjectURL(url);
        this.currentAudio = null;
      };

      audio.onended = () => { cleanup(); resolve(); };
      audio.onerror = () => { cleanup(); resolve(); };

      // Listen for abort to stop mid-playback
      const onAbort = () => { audio.pause(); cleanup(); resolve(); };
      signal.addEventListener('abort', onAbort, { once: true });

      audio.play().catch(() => { cleanup(); resolve(); });
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
    const url = card.wlo_url || card.url;
    if (url) window.open(url, '_blank');
  }

  getCardIcon(card: WloCard): string {
    if (card.node_type === 'collection') return '📚';
    const types = card.learning_resource_types || [];
    if (types.some(t => t.toLowerCase().includes('video'))) return '🎬';
    if (types.some(t => t.toLowerCase().includes('arbeitsblatt'))) return '📄';
    if (types.some(t => t.toLowerCase().includes('interaktiv'))) return '🎮';
    if (types.some(t => t.toLowerCase().includes('audio'))) return '🎧';
    return '📖';
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

  // ── Restart ──────────────────────────────────────────────
  restart() {
    // Generate fresh session and persist it (so the next page-load also
    // continues with the new one, not the old).
    this.sessionId = this.generateSessionId();
    try {
      localStorage.setItem(this.sessionKey, this.sessionId);
    } catch { /* ignore */ }
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

  private scrollToMessage(msgId: string) {
    try {
      const el = document.getElementById('msg-' + msgId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch {}
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

  renderMarkdown(text: string): SafeHtml {
    let html = text
      // Inline formatting first
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Process lines: render list items as styled divs (avoids browser ul/li defaults)
    const lines = html.split('\n');
    const result: string[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      // Headings: ### / ## / #
      const hMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (hMatch) {
        const level = Math.min(hMatch[1].length + 2, 6); // h1→h3 etc.
        result.push(`<h${level} style="margin:10px 0 4px 0;font-weight:600">${hMatch[2]}</h${level}>`);
        continue;
      }
      // Blockquote: "> text"
      const bqMatch = trimmed.match(/^>\s?(.*)$/);
      if (bqMatch) {
        result.push(`<div style="border-left:3px solid #c5cbd6;padding:2px 0 2px 10px;margin:2px 0;color:#3a4252">${bqMatch[1]}</div>`);
        continue;
      }
      // Numbered list: "1. item"
      const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
      if (olMatch) {
        result.push(`<div style="display:flex;align-items:baseline;margin-bottom:4px;padding-left:2px"><span style="flex-shrink:0;margin-right:8px">${olMatch[1]}.</span><span style="flex:1">${olMatch[2]}</span></div>`);
        continue;
      }
      // Match "- item", "• item", "* item" (but not **bold**)
      const listMatch = trimmed.match(/^(?:[-•]|\*(?!\*))\s+(.*)/);
      if (listMatch) {
        result.push(`<div style="display:flex;align-items:baseline;margin-bottom:4px;padding-left:2px"><span style="flex-shrink:0;margin-right:8px">•</span><span style="flex:1">${listMatch[1]}</span></div>`);
      } else if (trimmed) {
        result.push(trimmed + '<br>');
      } else {
        result.push('<br>');
      }
    }

    return this.sanitizer.bypassSecurityTrustHtml(result.join(''));
  }
}
