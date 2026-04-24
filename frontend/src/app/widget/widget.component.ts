import {
  Component, Input, ViewChild, ElementRef, OnInit, AfterViewInit, OnDestroy,
  NgZone, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatComponent } from '../chat/chat.component';
import { CanvasComponent, CanvasViewMode, CanvasCardAction } from '../canvas/canvas.component';
import { WloCard, PaginationInfo } from '../services/api.service';

/** Snapshot of the canvas state — pushed onto history when the user
 *  drills down (e.g. Sammlung -> Inhalte, Kachel -> Preview) so the
 *  back-button can restore the previous view.
 */
interface CanvasSnapshot {
  markdown: string;
  title: string;
  materialTypeLabel: string;
  cards: WloCard[];
  query: string;
  previewCard: WloCard | null;
  preferredView: 'material' | 'cards' | 'preview';
}

/**
 * BoerdiChatWidget — Floating Action Button + expandable chat panel + Canvas.
 *
 * Used as a Custom Element <boerdi-chat>:
 *   <boerdi-chat
 *     api-url="https://api.wlo.de"
 *     page-context='{"thema":"eiszeit"}'
 *     position="bottom-right"
 *     initial-state="collapsed"
 *     primary-color="#1c4587">
 *   </boerdi-chat>
 *
 * Panel-Layout:
 *   - Canvas zu → 420×820 (Chat einspaltig)
 *   - Canvas auf → 900×820 Desktop, Tab-Switch auf Mobile
 *   - Canvas liegt immer gegenueber der FAB-Kante (bottom-right FAB → Canvas links)
 */
@Component({
  selector: 'boerdi-chat-widget',
  standalone: true,
  imports: [CommonModule, ChatComponent, CanvasComponent],
  template: `
    <div class="boerdi-widget"
         [class.expanded]="expanded"
         [class.with-canvas]="canvasOpen()"
         [class.mobile-canvas-active]="canvasOpen() && mobileTab() === 'canvas'"
         [attr.data-position]="position"
         [style.--boerdi-primary]="primaryColor">

      <!-- Chat panel -->
      <div class="boerdi-panel" *ngIf="expanded">
        <div class="boerdi-panel-header">
          <span class="boerdi-title">
            <span class="boerdi-owl-mini">🦉</span> BOERDi
          </span>

          <!-- Mobile-only tab switcher (hidden on desktop) -->
          <div class="boerdi-tabs" *ngIf="canvasOpen()">
            <button type="button"
                    class="boerdi-tab"
                    [class.active]="mobileTab() === 'chat'"
                    (click)="mobileTab.set('chat')">Chat</button>
            <button type="button"
                    class="boerdi-tab"
                    [class.active]="mobileTab() === 'canvas'"
                    (click)="mobileTab.set('canvas')">Canvas</button>
          </div>

          <button class="boerdi-close" (click)="toggle()" aria-label="Schließen">×</button>
        </div>

        <div class="boerdi-panel-body">
          <!-- Canvas pane (if open). Order depends on FAB position: canvas lives
               on the opposite side so it expands toward the page center. -->
          <div class="boerdi-canvas-pane" *ngIf="canvasOpen()">
            <badboerdi-canvas
              [title]="canvasTitle()"
              [materialTypeLabel]="canvasMaterialLabel()"
              [materialTypeCategory]="canvasMaterialCategory()"
              [markdown]="canvasMarkdown()"
              [cards]="canvasCards()"
              [viewMode]="canvasMode()"
              [query]="canvasQuery()"
              [showTabs]="canvasHasBothPanes()"
              [previewCard]="canvasPreviewCard()"
              [canGoBack]="canvasHistory().length > 0"
              [pagination]="canvasPagination()"
              [visibleCount]="canvasVisibleCount()"
              [loadingMore]="canvasLoadingMore()"
              (closeCanvas)="closeCanvas()"
              (cardAction)="onCanvasCardAction($event)"
              (switchView)="onCanvasViewSwitch($event)"
              (goBack)="onCanvasGoBack()"
              (showMore)="onCanvasShowMore()"
              (loadMore)="onCanvasLoadMoreFromServer()"
              (markdownEdited)="onCanvasMarkdownEdited($event)">
            </badboerdi-canvas>
          </div>

          <div class="boerdi-chat-pane">
            <badboerdi-chat
              #chat
              [apiUrl]="apiUrl"
              [pageContext]="resolvedPageContext"
              [persistSession]="persistSession"
              [sessionKey]="sessionKey"
              [greeting]="greeting"
              [canvasActiveMarkdown]="canvasMode() === 'content' ? canvasMarkdown() : ''"
              [hideCards]="canvasOpen()"
              [canvasShowingCards]="canvasOpen() && canvasMode() === 'cards'"
              [canvasState]="canvasStateForBackend()"
              (pageAction)="handlePageAction($event)">
            </badboerdi-chat>
          </div>
        </div>
      </div>

      <!-- Floating button -->
      <button class="boerdi-fab"
              *ngIf="!expanded"
              (click)="toggle()"
              aria-label="Chat öffnen">
        <span class="boerdi-owl">🦉</span>
        <span class="boerdi-fab-pulse"></span>
      </button>
    </div>
  `,
  styles: [`
    :host {
      display: block;
      position: fixed;
      z-index: 999999;
      pointer-events: none;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --boerdi-primary: #1c4587;
    }
    .boerdi-widget { pointer-events: auto; }
    :host { bottom: 20px; right: 20px; }
    :host([data-position="bottom-left"]) { left: 20px; right: auto; }
    :host([data-position="top-right"]) { top: 20px; bottom: auto; }
    :host([data-position="top-left"]) { top: 20px; left: 20px; right: auto; bottom: auto; }

    /* ── FAB ──────────────────────────────────────────────── */
    .boerdi-fab {
      width: 64px; height: 64px;
      border-radius: 50%;
      border: none;
      background: var(--boerdi-primary);
      color: #fff;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25);
      display: flex; align-items: center; justify-content: center;
      position: relative;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      animation: boerdi-bob 4s ease-in-out infinite;
    }
    .boerdi-fab:hover {
      transform: scale(1.1) rotate(-5deg);
      box-shadow: 0 6px 20px rgba(0,0,0,0.35);
    }
    .boerdi-owl {
      font-size: 32px;
      display: inline-block;
      animation: boerdi-blink 8s ease-in-out infinite;
    }
    .boerdi-fab-pulse {
      position: absolute; inset: 0;
      border-radius: 50%;
      border: 3px solid var(--boerdi-primary);
      opacity: 0;
      animation: boerdi-pulse 3s ease-out infinite;
    }
    @keyframes boerdi-bob {
      0%, 100% { transform: translateY(0); }
      50%      { transform: translateY(-6px); }
    }
    @keyframes boerdi-pulse {
      0%   { opacity: 0.6; transform: scale(1); }
      100% { opacity: 0;   transform: scale(1.6); }
    }
    @keyframes boerdi-blink {
      0%, 92%, 100% { transform: scaleY(1); }
      94%           { transform: scaleY(0.1); }
    }

    /* ── Panel ────────────────────────────────────────────── */
    .boerdi-panel {
      width: 420px;
      height: min(820px, calc(100vh - 40px));
      max-width: calc(100vw - 40px);
      max-height: calc(100vh - 40px);
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 12px 48px rgba(0,0,0,0.3);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      animation: boerdi-slidein 0.25s ease-out;
      transition: width 0.25s ease;
    }
    .boerdi-widget.with-canvas .boerdi-panel {
      width: 900px;
      max-width: calc(100vw - 40px);
    }
    @keyframes boerdi-slidein {
      from { opacity: 0; transform: translateY(20px) scale(0.95); }
      to   { opacity: 1; transform: translateY(0)    scale(1); }
    }

    .boerdi-panel-header {
      background: var(--boerdi-primary);
      color: #fff;
      padding: 10px 14px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px;
      flex-shrink: 0;
    }
    .boerdi-title {
      font-weight: 600;
      font-size: 15px;
      white-space: nowrap;
    }
    .boerdi-owl-mini { margin-right: 6px; }
    .boerdi-close {
      background: transparent;
      border: none;
      color: #fff;
      font-size: 28px;
      line-height: 1;
      cursor: pointer;
      padding: 0 4px;
      opacity: 0.85;
    }
    .boerdi-close:hover { opacity: 1; }

    /* Mobile tab switcher — hidden on desktop */
    .boerdi-tabs {
      display: none;
      gap: 4px;
      background: rgba(255,255,255,0.12);
      padding: 2px;
      border-radius: 8px;
    }
    .boerdi-tab {
      background: transparent;
      border: 0;
      color: rgba(255,255,255,0.7);
      padding: 4px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
    }
    .boerdi-tab.active {
      background: rgba(255,255,255,0.95);
      color: var(--boerdi-primary);
    }

    /* ── Body (Flex: Canvas | Chat) ───────────────────────── */
    .boerdi-panel-body {
      flex: 1;
      overflow: hidden;
      display: flex;
    }
    .boerdi-chat-pane {
      flex: 1 1 420px;
      min-width: 0;
      display: flex;
      min-height: 0;
    }
    .boerdi-chat-pane badboerdi-chat {
      flex: 1;
      display: block;
      min-height: 0;
      width: 100%;
    }
    .boerdi-canvas-pane {
      flex: 1 1 480px;
      min-width: 0;
      display: flex;
      min-height: 0;
      /* Canvas lives on the side OPPOSITE to the FAB anchor so it
         expands toward the page center instead of off-screen. */
      order: 0;
    }
    .boerdi-canvas-pane badboerdi-canvas {
      flex: 1;
      display: flex;
      min-height: 0;
      min-width: 0;
    }

    /* FAB on the right → Canvas on the left (order 0 < chat-order 1) */
    :host([data-position="bottom-right"]) .boerdi-canvas-pane,
    :host([data-position="top-right"])    .boerdi-canvas-pane { order: 0; }
    :host([data-position="bottom-right"]) .boerdi-chat-pane,
    :host([data-position="top-right"])    .boerdi-chat-pane   { order: 1; }

    /* FAB on the left → Canvas on the right */
    :host([data-position="bottom-left"]) .boerdi-canvas-pane,
    :host([data-position="top-left"])    .boerdi-canvas-pane { order: 1; }
    :host([data-position="bottom-left"]) .boerdi-chat-pane,
    :host([data-position="top-left"])    .boerdi-chat-pane   { order: 0; }

    /* ── Responsive: narrow window → collapse to Tab-mode ─ */
    @media (max-width: 1200px) {
      .boerdi-widget.with-canvas .boerdi-panel {
        width: 420px; /* fall back to single-pane */
      }
      .boerdi-widget.with-canvas .boerdi-tabs { display: inline-flex; }
      .boerdi-widget.with-canvas .boerdi-canvas-pane { display: none; }
      .boerdi-widget.with-canvas.mobile-canvas-active .boerdi-canvas-pane { display: flex; }
      .boerdi-widget.with-canvas.mobile-canvas-active .boerdi-chat-pane { display: none; }
    }

    @media (max-width: 480px) {
      .boerdi-panel,
      .boerdi-widget.with-canvas .boerdi-panel {
        width: 100vw;
        height: 100vh;
        max-width: 100vw;
        max-height: 100vh;
        border-radius: 0;
        position: fixed;
        inset: 0;
      }
    }
  `],
})
export class WidgetComponent implements OnInit, AfterViewInit, OnDestroy {
  // ChatComponent instance — we need public methods like browseCollection
  // and generateLearningPath, so this is the actual component, not an ElementRef.
  @ViewChild('chat') chatRef!: ChatComponent;

  @Input() apiUrl = '';
  @Input() pageContext: string | Record<string, any> = '';
  @Input() position: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left' = 'bottom-right';
  @Input() initialState: 'collapsed' | 'expanded' = 'collapsed';
  @Input() primaryColor = '#1c4587';
  @Input() persistSession: boolean | string = true;
  @Input() sessionKey = 'boerdi_session_id';
  @Input() greeting = '';
  @Input() autoContext: boolean | string = true;

  expanded = false;
  resolvedPageContext: Record<string, any> = {};

  // ── Canvas state (signals) ──
  // Beide Signals (Markdown und Cards) leben parallel. Der User kann im
  // Canvas-Header zwischen "Material" und "Treffer" wechseln, ohne den
  // jeweils anderen Inhalt zu verlieren.
  canvasOpen = signal(false);
  canvasMarkdown = signal('');
  canvasTitle = signal('');
  canvasMaterialLabel = signal('');
  /** 'analytisch' (blau) oder 'didaktisch' (grün). Null für Default/Fallback. */
  canvasMaterialCategory = signal<'analytisch' | 'didaktisch' | null>(null);
  canvasCards = signal<WloCard[]>([]);
  canvasQuery = signal('');
  canvasPagination = signal<PaginationInfo | null>(null);
  /** How many cards are initially rendered in the canvas cards pane.
   *  Chat stays at 5; canvas has more space and should show more upfront. */
  canvasVisibleCount = signal(10);
  canvasLoadingMore = signal(false);
  // Single-card preview mode (when user clicks "Anschauen" on a content card).
  canvasPreviewCard = signal<WloCard | null>(null);
  // User-preferred tab ('material' oder 'cards'). Wird beim Eintreffen
  // eines neuen Payloads automatisch umgeschaltet, kann aber per Tab-Klick
  // manuell uebersteuert werden.
  canvasPreferredView = signal<'material' | 'cards' | 'preview'>('material');
  // Navigation history — lets the user go "back" from a drill-down (e.g.
  // clicked "Inhalte" on a collection, or opened a content preview) to
  // whatever was in the canvas before.
  canvasHistory = signal<CanvasSnapshot[]>([]);
  mobileTab = signal<'chat' | 'canvas'>('chat');

  // Effective canvas viewMode abgeleitet aus dem Preview-Slot, dem
  // Preferred-Tab und den verfuegbaren Signals.
  canvasMode = computed<CanvasViewMode>(() => {
    if (this.canvasPreferredView() === 'preview' && this.canvasPreviewCard()) return 'preview';
    const preferred = this.canvasPreferredView();
    const hasMd = this.canvasMarkdown().trim().length > 0;
    const hasCards = this.canvasCards().length > 0;
    if (preferred === 'cards' && hasCards) return 'cards';
    if (preferred === 'material' && hasMd) return 'content';
    if (hasMd) return 'content';
    if (hasCards) return 'cards';
    return 'empty';
  });

  // Beide Panes haben Inhalt → Tab-Switch im Canvas-Header anzeigen
  canvasHasBothPanes = computed(() =>
    this.canvasMarkdown().trim().length > 0 && this.canvasCards().length > 0
  );

  // Snapshot for the backend so the LLM knows what's on the canvas.
  // Sent with every chat request (via ChatComponent -> ApiService).
  canvasStateForBackend = computed<Record<string, any> | null>(() => {
    if (!this.canvasOpen()) return null;
    const mode = this.canvasMode();
    if (mode === 'empty') return null;
    return {
      mode: mode === 'content' ? 'material' : 'cards',
      title: this.canvasTitle(),
      material_type: this.canvasMaterialLabel(),
      markdown: mode === 'content' ? this.canvasMarkdown() : '',
      cards_count: this.canvasCards().length,
    };
  });

  private readonly OPEN_KEY = 'boerdi_widget_open';
  private readonly OPEN_TTL_MS = 30 * 60 * 1000; // 30 min

  // Fallback window listener — if the Angular @Output() binding on
  // <badboerdi-chat> doesn't propagate (e.g. when the widget is mounted
  // as a Custom Element that re-wraps the event flow), we still catch
  // the same page_action via the CustomEvent the chat component dispatches.
  private _onWindowPageAction?: (e: Event) => void;

  constructor(private zone: NgZone) {}

  ngOnInit() {
    this.expanded = this.initialState === 'expanded';

    // Restore expanded state across pages (within TTL)
    try {
      const raw = localStorage.getItem(this.OPEN_KEY);
      if (raw) {
        const ts = parseInt(raw, 10);
        if (!isNaN(ts) && Date.now() - ts < this.OPEN_TTL_MS) {
          this.expanded = true;
        } else {
          localStorage.removeItem(this.OPEN_KEY);
        }
      }
    } catch { /* ignore */ }

    // Merge automatic + manual page context
    const auto = this.autoContext === true || this.autoContext === 'true';
    if (auto) {
      try {
        const query: Record<string, string> = {};
        const sp = new URL(window.location.href).searchParams;
        sp.forEach((value, key) => { query[key] = value; });
        this.resolvedPageContext = {
          path: window.location.pathname,
          query,
          title: document.title,
          referrer: document.referrer || '',
        };
      } catch { /* ignore */ }
    }
    // Mark this session as widget-driven so the backend routes cards to
    // the canvas regardless of env.page (important for dev on localhost:4200,
    // where env.page='/' would otherwise be treated as a host-page integration).
    this.resolvedPageContext = { ...this.resolvedPageContext, widget: true };
    if (typeof this.pageContext === 'string' && this.pageContext.trim()) {
      try {
        const manual = JSON.parse(this.pageContext);
        this.resolvedPageContext = { ...this.resolvedPageContext, ...manual };
      } catch {
        this.resolvedPageContext = { ...this.resolvedPageContext, raw: this.pageContext };
      }
    } else if (typeof this.pageContext === 'object' && this.pageContext) {
      this.resolvedPageContext = { ...this.resolvedPageContext, ...(this.pageContext as Record<string, any>) };
    }
  }

  ngAfterViewInit() {
    // Robust fallback: listen for the CustomEvent the chat always dispatches.
    // Runs inside Angular zone so signal updates trigger change detection.
    this._onWindowPageAction = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail && detail.action) {
        this.zone.run(() => this.handlePageAction(detail));
      }
    };
    window.addEventListener('badboerdi:page-action', this._onWindowPageAction);
  }

  ngOnDestroy() {
    if (this._onWindowPageAction) {
      window.removeEventListener('badboerdi:page-action', this._onWindowPageAction);
    }
  }

  toggle() {
    this.expanded = !this.expanded;
    try {
      if (this.expanded) {
        localStorage.setItem(this.OPEN_KEY, String(Date.now()));
      } else {
        localStorage.removeItem(this.OPEN_KEY);
      }
    } catch { /* ignore */ }
  }

  /**
   * Handle backend page_actions.
   * Canvas-relevant actions (canvas_open/update/show_cards/close) are
   * consumed locally; others (show_results, navigate, ...) are ignored
   * here — the chat component already dispatches them as CustomEvents
   * on `window` for host-page integration.
   */
  handlePageAction(pa: { action: string; payload: any }) {
    if (!pa || !pa.action) return;
    switch (pa.action) {
      case 'canvas_open': {
        const p = pa.payload || {};
        this.canvasTitle.set(p.title || 'Canvas');
        this.canvasMaterialLabel.set(p.material_type_label || '');
        const cat = p.material_type_category;
        this.canvasMaterialCategory.set(
          cat === 'analytisch' ? 'analytisch' : cat === 'didaktisch' ? 'didaktisch' : null
        );
        this.canvasMarkdown.set(p.markdown || '');
        this.canvasPreferredView.set('material');
        this.canvasPreviewCard.set(null);
        this.canvasOpen.set(true);
        // Note: history is preserved — pre-push in drill-down handlers
        // already set it, and losing it would defeat the back button.
        this.mobileTab.set('canvas');
        break;
      }
      case 'canvas_update': {
        const p = pa.payload || {};
        if (typeof p.markdown === 'string') {
          this.canvasMarkdown.set(p.markdown);
        }
        this.canvasPreferredView.set('material');
        this.canvasPreviewCard.set(null);
        this.canvasOpen.set(true);
        break;
      }
      case 'canvas_show_cards': {
        const p = pa.payload || {};
        const fromCollection = p.source === 'collection';
        const appendMode = p.append === true;
        // If the user drilled down from an existing card list into a
        // collection's contents, remember where they came from so Back
        // can restore the outer grid.
        if (fromCollection && !appendMode && this.canvasCards().length > 0) {
          this.pushCanvasHistory();
        }
        const incoming: WloCard[] = Array.isArray(p.cards) ? (p.cards as WloCard[]) : [];
        if (appendMode) {
          // Append for "load more" — keep the existing list, dedupe by node_id
          const existing = this.canvasCards();
          const seen = new Set(existing.map(c => c.node_id).filter(Boolean));
          const merged: WloCard[] = [
            ...existing,
            ...incoming.filter((c: WloCard) => !seen.has(c.node_id)),
          ];
          this.canvasCards.set(merged);
        } else {
          this.canvasCards.set(incoming);
          this.canvasVisibleCount.set(10);
        }
        this.canvasQuery.set(p.query || '');
        this.canvasTitle.set(p.title || '');
        this.canvasPagination.set(p.pagination || null);
        this.canvasPreferredView.set('cards');
        this.canvasPreviewCard.set(null);
        this.canvasOpen.set(true);
        this.canvasLoadingMore.set(false);
        if (window.innerWidth <= 1200 && !appendMode) {
          this.mobileTab.set('chat');
        }
        break;
      }
      case 'canvas_close': {
        this.closeCanvas();
        break;
      }
      default:
        break;
    }
  }

  /** User clicked a tab in the canvas header — switch preferred view. */
  onCanvasViewSwitch(view: 'material' | 'cards'): void {
    this.canvasPreferredView.set(view);
  }

  /** Open a single-card metadata preview inside the canvas. */
  openCanvasPreview(card: WloCard): void {
    if (!card) return;
    this.pushCanvasHistory();
    this.canvasPreviewCard.set(card);
    this.canvasPreferredView.set('preview');
    this.canvasOpen.set(true);
    this.mobileTab.set('canvas');
  }

  /** Push the current canvas state onto the history stack. */
  private pushCanvasHistory(): void {
    const snap: CanvasSnapshot = {
      markdown: this.canvasMarkdown(),
      title: this.canvasTitle(),
      materialTypeLabel: this.canvasMaterialLabel(),
      cards: this.canvasCards(),
      query: this.canvasQuery(),
      previewCard: this.canvasPreviewCard(),
      preferredView: this.canvasPreferredView(),
    };
    // Cap history at 10 levels to avoid unbounded growth.
    const next = [...this.canvasHistory(), snap].slice(-10);
    this.canvasHistory.set(next);
  }

  /** Pop the most recent history entry and restore that canvas state. */
  onCanvasGoBack(): void {
    const hist = this.canvasHistory();
    if (hist.length === 0) return;
    const prev = hist[hist.length - 1];
    this.canvasHistory.set(hist.slice(0, -1));
    this.canvasMarkdown.set(prev.markdown);
    this.canvasTitle.set(prev.title);
    this.canvasMaterialLabel.set(prev.materialTypeLabel);
    this.canvasCards.set(prev.cards);
    this.canvasQuery.set(prev.query);
    this.canvasPreviewCard.set(prev.previewCard);
    this.canvasPreferredView.set(prev.preferredView);
  }

  /** User has saved a direct markdown edit from the canvas editor. Push the
   *  new text into the canvas signal so the next chat turn sees it via
   *  `canvasStateForBackend` and the backend treats it as the new
   *  current_markdown. NO server round-trip — this is purely local state.
   */
  onCanvasMarkdownEdited(newMarkdown: string): void {
    this.canvasMarkdown.set(newMarkdown || '');
  }

  closeCanvas() {
    // canvasMode is computed; clearing the underlying signals below
    // naturally pushes mode back to 'empty'.
    this.canvasOpen.set(false);
    this.canvasMarkdown.set('');
    this.canvasCards.set([]);
    this.canvasPreviewCard.set(null);
    this.canvasHistory.set([]);
    this.canvasPagination.set(null);
    this.canvasVisibleCount.set(10);
    this.canvasPreferredView.set('material');
    this.mobileTab.set('chat');
  }

  /** "Weitere anzeigen" — reveal more client-side cached cards. */
  onCanvasShowMore(): void {
    const total = this.canvasCards().length;
    this.canvasVisibleCount.set(Math.min(total, this.canvasVisibleCount() + 10));
  }

  /** "Mehr laden" — fetch next page from the same collection. */
  async onCanvasLoadMoreFromServer(): Promise<void> {
    const p = this.canvasPagination();
    const chat = this.chatRef;
    if (!p || !p.has_more || !p.collection_id || !chat || this.canvasLoadingMore()) return;
    this.canvasLoadingMore.set(true);
    try {
      // Reuse ChatComponent's isLoading gating is ok — this is a foreground
      // action. The response arrives via page_action=canvas_show_cards
      // with append=true and gets merged in handlePageAction.
      await chat.browseCollectionPage(
        p.collection_id,
        p.collection_title || '',
        p.skip_count + p.page_size,
      );
    } catch {
      this.canvasLoadingMore.set(false);
    }
  }

  /** Bridge: the canvas just wants to emit user-intent, the chat owns
   *  session + API. We forward each action to the matching ChatComponent
   *  public method so behaviour stays identical to in-chat card actions.
   */
  onCanvasCardAction(ev: { action: CanvasCardAction; card: WloCard }): void {
    const chat = this.chatRef;
    // Diagnostic log so we can see in DevTools what a card contains —
    // helpful when 'Inhalte'/'Lernpfad' seem to do nothing.
    // eslint-disable-next-line no-console
    console.debug('[canvas] card action', ev?.action, {
      node_id: ev?.card?.node_id,
      title: ev?.card?.title,
      node_type: ev?.card?.node_type,
      topic_pages: ev?.card?.topic_pages?.length ?? 0,
      chat_ready: !!chat,
    });
    if (!ev?.card) return;
    const c = ev.card;
    if (!chat) {
      // Chat component not mounted yet — shouldn't happen once the panel is
      // open, but log so it's visible instead of silently dropped.
      console.warn('[canvas] action dropped: chat component not ready');
      return;
    }
    switch (ev.action) {
      case 'preview':
        // Stay inside the canvas — show metadata-driven preview.
        this.openCanvasPreview(c);
        return;   // no chat-roundtrip, don't switch mobile tab
      case 'browse': {
        // Resolve a collection-id: card.node_id first, then extract from
        // any topic-page URL (WLO topic-page URLs always carry
        // `collectionId=<uuid>` or `/render/<uuid>`).
        const collId = c.node_id || this.extractCollectionIdFromCard(c);
        if (!collId) {
          console.warn('[canvas] browse: no collection id resolvable from card');
          return;
        }
        chat.browseCollection(collId, c.title);
        break;
      }
      case 'learning_path': {
        const collId = c.node_id || this.extractCollectionIdFromCard(c);
        if (!collId) {
          console.warn('[canvas] learning_path: no collection id resolvable');
          chat.sendMessage(
            `Bitte erstelle einen Lernpfad zum Thema "${c.title}".`,
          );
          return;
        }
        this.pushCanvasHistory();
        chat.generateLearningPath(collId, c.title);
        break;
      }
      case 'remix': {
        // Remix needs the richest card possible — if node_id is empty but
        // we can recover it from a topic-page URL, patch it in so the
        // backend's remix handler can reference the collection.
        const collId = c.node_id || this.extractCollectionIdFromCard(c);
        const enriched = collId && !c.node_id ? { ...c, node_id: collId } : c;
        chat.remixCard(enriched);
        break;
      }
      case 'open':
        window.open(c.url || c.wlo_url || '#', '_blank', 'noopener');
        return;
    }
    this.mobileTab.set('chat');
  }

  /** Pull a UUID (collection id) out of any URL the card exposes.
   *  Topic-page URLs look like:
   *    .../topic-pages?collectionId=<uuid>
   *    .../render/<uuid>
   *    .../collections?id=<uuid>
   *  We accept any of those as the collection id for browse/lp/remix.
   */
  private extractCollectionIdFromCard(c: WloCard): string {
    const urls: string[] = [];
    if (c.url) urls.push(c.url);
    if (c.wlo_url) urls.push(c.wlo_url);
    for (const tp of c.topic_pages || []) {
      if (tp?.url) urls.push(tp.url);
    }
    const uuidRe = /[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/i;
    for (const u of urls) {
      const m = u.match(uuidRe);
      if (m) return m[0];
    }
    return '';
  }
}
