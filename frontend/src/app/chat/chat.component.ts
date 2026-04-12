import {
  Component, ElementRef, HostListener, NgZone, ViewChild, AfterViewChecked, OnInit, signal, Input,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService, ChatMessage, WloCard, DebugInfo, PaginationInfo } from '../services/api.service';

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
      this.addBotMessage(
        this.greeting ||
        'Schoen dass du da bist! Suchst du was Bestimmtes oder willst du erstmal schauen was es hier so gibt?'
      );
    }
  }

  /** Fetch message history for the current session and render it. */
  private async restoreHistory() {
    const history = await this.api.loadHistory(this.sessionId, 20);
    if (!history || history.length === 0) {
      // Empty session — show greeting like a fresh chat.
      this.addBotMessage(
        this.greeting ||
        'Schoen dass du da bist! Suchst du was Bestimmtes oder willst du erstmal schauen was es hier so gibt?'
      );
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
      const resp = await this.api.sendMessage(this.sessionId, msg, envOverride);

      // Remove loading, add real response
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
      this.scrollTargetId = botMsgId;

      this.latestDebug = resp.debug;

      // Handle page action (share with host page)
      if (resp.page_action && this.onPageAction) {
        this.onPageAction(resp.page_action);
      }

      // Dispatch custom event for host page integration
      if (resp.page_action) {
        window.dispatchEvent(new CustomEvent('badboerdi:page-action', {
          detail: resp.page_action,
        }));
      }

      // Auto-speak if enabled
      if (this.autoSpeak && resp.content) {
        this.speakText(resp.content);
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
          this.speakText(m.content);
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
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
      this.scrollTargetId = botMsgId;
      this.latestDebug = resp.debug;
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
        `Lernpfad fuer "${title}"`,
        undefined,
        'generate_learning_path',
        { collection_id: nodeId, title },
      );
      this.removeMessage(loadingId);
      const botMsgId = this.addBotMessage(resp.content, false, resp.cards, resp.quick_replies, resp.debug, resp.pagination);
      this.scrollTargetId = botMsgId;
      this.latestDebug = resp.debug;
    } catch (err) {
      this.removeMessage(loadingId);
      const errId = this.addBotMessage(`Den Lernpfad fuer "${title}" konnte ich leider nicht erstellen. Versuch es nochmal!`);
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
    this.addBotMessage(
      this.greeting ||
      'Schoen dass du da bist! Suchst du was Bestimmtes oder willst du erstmal schauen was es hier so gibt?'
    );
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
