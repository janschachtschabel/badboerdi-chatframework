import {
  Component, Input, Output, EventEmitter, ViewChild, ElementRef, OnInit, AfterViewInit, OnDestroy, OnChanges, SimpleChanges,
  NgZone, signal, computed, ChangeDetectorRef, HostBinding,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatComponent } from '../chat/chat.component';
import { detectPageContext } from './page-context-detector';
import { CanvasComponent, CanvasViewMode, CanvasCardAction } from '../canvas/canvas.component';
import { ApiService, WloCard, PaginationInfo } from '../services/api.service';
import { BOERDI_LOGO_DATA_URL } from '../shared/boerdi-logo';
import { ICONS } from '../shared/icons';
import { SafeSvgPipe } from '../shared/safe-svg.pipe';

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
  imports: [CommonModule, ChatComponent, CanvasComponent, SafeSvgPipe],
  template: `
    <div class="boerdi-widget"
         [class.expanded]="expanded"
         [class.with-canvas]="canvasOpen() && canvasEnabledBool"
         [class.mobile-canvas-active]="canvasOpen() && canvasEnabledBool && mobileTab() === 'canvas'"
         [attr.data-position]="position">

      <!-- Chat panel: lazy mount on first open, then stays in DOM and
           is just hidden via CSS class. Preserves chat component state
           (messages, cards, canvas markdown) across bubble collapse. -->
      <div class="boerdi-panel"
           *ngIf="everExpanded"
           [class.boerdi-panel--hidden]="!expanded">
        <div class="boerdi-panel-header">
          <!-- Linker Bereich: Avatar + Name + Status -->
          <div class="boerdi-title-block">
            <img class="boerdi-owl-mini"
                 [class.is-thinking]="chatRef?.isLoading"
                 [class.is-speaking]="chatRef?.autoSpeak && chatRef?.isSpeaking"
                 [src]="boerdiLogo" alt="" />
            <div class="boerdi-title-text">
              <span class="boerdi-title">BOERDi</span>
              <span class="boerdi-status" *ngIf="chatRef?.isLoading">denkt nach …</span>
              <span class="boerdi-status" *ngIf="!chatRef?.isLoading && chatRef?.autoSpeak && chatRef?.isSpeaking">spricht …</span>
            </div>
          </div>

          <!-- Mitte: Mobile-only tab switcher -->
          <div class="boerdi-tabs" *ngIf="canvasOpen() && canvasEnabledBool">
            <button type="button"
                    class="boerdi-tab"
                    [class.active]="mobileTab() === 'chat'"
                    (click)="mobileTab.set('chat')">Chat</button>
            <button type="button"
                    class="boerdi-tab"
                    [class.active]="mobileTab() === 'canvas'"
                    (click)="mobileTab.set('canvas')">Canvas</button>
          </div>

          <!-- Rechts: Action-Buttons (sound/debug/restart) + Close.
               Icon-Wechsel + solid-vs-outlined-Pill kommunizieren den
               aktiven/inaktiven Zustand klar. -->
          <div class="boerdi-header-actions">
            <button *ngIf="chatRef?.languageButtonsVisible"
                    class="boerdi-action-btn"
                    [class.is-on]="chatRef?.autoSpeak"
                    [class.is-off]="!chatRef?.autoSpeak"
                    (click)="chatRef?.toggleAutoSpeak()"
                    [title]="chatRef?.autoSpeak ? 'Sprachausgabe aus' : 'Sprachausgabe an'">
              <span class="boerdi-icon"
                    [innerHTML]="(chatRef?.autoSpeak ? ICONS.volume_up : ICONS.volume_off) | safeSvg"></span>
            </button>
            <button *ngIf="chatRef?.debugButtonVisible"
                    class="boerdi-action-btn"
                    [class.is-on]="chatRef?.showDebug"
                    [class.is-off]="!chatRef?.showDebug"
                    (click)="chatRef?.toggleDebug()"
                    [title]="chatRef?.showDebug ? 'Debug aus' : 'Debug an'">
              <span class="boerdi-icon" [innerHTML]="ICONS.bug_report | safeSvg"></span>
            </button>
            <!-- Webseiten-Guide-Modus: nur sichtbar auf Allow-Listen-
                 Hosts (wirlernenonline.de etc.) UND wenn show-guide-button
                 nicht abgeschaltet wurde. Auf Drittseiten bleibt der
                 Toggle ausgeblendet (kein Sinn ohne Navigationsziel). -->
            <button *ngIf="guideModeAvailable() && showGuideButtonBool"
                    class="boerdi-action-btn"
                    [class.is-on]="guideMode()"
                    [class.is-off]="!guideMode()"
                    (click)="toggleGuideMode()"
                    [title]="guideMode() ? 'Lotsen-Modus aus (öffnet Links in neuem Tab)' : 'Lotsen-Modus an (führt dich zu den Treffern)'">
              <span class="boerdi-icon" [innerHTML]="ICONS.explore | safeSvg"></span>
            </button>
            <button class="boerdi-action-btn boerdi-action-btn--neutral"
                    (click)="chatRef?.restart()"
                    title="Neuer Chat">
              <span class="boerdi-icon" [innerHTML]="ICONS.refresh | safeSvg"></span>
            </button>
            <button class="boerdi-close"
                    (click)="toggle()"
                    aria-label="Schließen">
              <span class="boerdi-icon" [innerHTML]="ICONS.close | safeSvg"></span>
            </button>
          </div>
        </div>

        <!-- Lotsen-Banner: vom Bot vorgeschlagene Navigation. Wir verlassen
             die Host-Seite NIE ohne explizite Zustimmung — daher zwei
             Buttons und ein klares Label. -->
        <div *ngIf="guideNavTarget()" class="boerdi-nav-banner" role="alert">
          <span class="nav-banner-icon boerdi-icon" aria-hidden="true" [innerHTML]="ICONS.explore | safeSvg"></span>
          <span class="nav-banner-text">
            Soll ich dich zu „<strong>{{ guideNavTarget()!.label }}</strong>" bringen?
          </span>
          <div class="nav-banner-actions">
            <button type="button" class="nav-banner-btn nav-banner-btn--primary"
                    (click)="confirmGuideNav()">
              Bring mich hin
            </button>
            <button type="button" class="nav-banner-btn nav-banner-btn--secondary"
                    (click)="cancelGuideNav()">
              Hier bleiben
            </button>
          </div>
        </div>

        <div class="boerdi-panel-body">
          <!-- Canvas pane (if open). Order depends on FAB position: canvas lives
               on the opposite side so it expands toward the page center. -->
          <div class="boerdi-canvas-pane" *ngIf="canvasOpen() && canvasEnabledBool">
            <badboerdi-canvas
              [title]="canvasTitle()"
              [materialTypeLabel]="canvasMaterialLabel()"
              [materialTypeCategory]="canvasMaterialCategory()"
              [markdown]="canvasMarkdown()"
              [cards]="canvasCards()"
              [trustedHosts]="parsedTrustedHostList"
              [sessionId]="chatRef?.sessionId || ''"
              [inlineResultGrouping]="inlineResultGrouping"
              [searchCtaUrl]="canvasSearchCtaUrl()"
              [searchCtaTerm]="canvasSearchCtaTerm()"
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
              [sessionCookieDomain]="sessionCookieDomain"
              [sessionCookieMaxAge]="sessionCookieMaxAge"
              [greeting]="greeting"
              [showDebugButton]="showDebugButton"
              [showLanguageButtons]="showLanguageButtons"
              [canvasActiveMarkdown]="canvasMode() === 'content' ? canvasMarkdown() : ''"
              [hideCards]="canvasOpen()"
              [canvasShowingCards]="canvasOpen() && canvasMode() === 'cards'"
              [canvasState]="canvasStateForBackend()"
              [guideModeActive]="guideModeAvailable() && guideMode()"
              [cardsEnabled]="cardsEnabled"
              [canvasEnabled]="canvasEnabled"
              [aiContentEnabled]="aiContentEnabled"
              [quickRepliesEnabled]="quickRepliesEnabled"
              [trustedHosts]="parsedTrustedHostList"
              [inlineResultGrouping]="inlineResultGrouping"
              [emitGuideSuggestion]="emitGuideSuggestion"
              [emitRoutingDebug]="emitRoutingDebug"
              (pageAction)="handlePageAction($event)"
              (guideSuggestion)="guideSuggestion.emit($event)"
              (routingDebug)="routingDebug.emit($event)">
            </badboerdi-chat>
          </div>
        </div>
      </div>

      <!-- Floating button -->
      <button class="boerdi-fab"
              *ngIf="!expanded"
              (click)="toggle()"
              aria-label="Chat öffnen">
        <img class="boerdi-owl" [src]="boerdiLogo" alt="" />
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

    /* ── Material-Symbols-Icons (Inline-SVG) ─────────────────────
       Alle Icon-Container nutzen currentColor als Fill — das SVG
       erbt die Schriftfarbe des Buttons. Größe 20px passt in die
       40er-Action-Buttons mit etwas Padding. */
    .boerdi-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      line-height: 0;
    }
    .boerdi-icon > svg {
      width: 20px;
      height: 20px;
      fill: currentColor;
    }

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
    /* Logo als <img>-Tag (Data-URL). Animationen laufen auf dem
       Container, nicht auf SVG-internen Pfaden — das funktioniert in
       Web Components (Custom Elements) zuverlässig. */
    .boerdi-owl {
      width: 38px;
      max-width: unset;
      height: 38px;
      display: block;
      object-fit: contain;
      /* Mehrlagige Animation: dezentes Atmen + gelegentliches Wackeln */
      animation: boerdi-breathe 4s ease-in-out infinite,
                 boerdi-blink 8s ease-in-out infinite;
      /* Keine Color-Inversion auf FAB, weil das Logo seine eigenen
         Farben mitbringt — der weiße Hintergrund-Kreis stellt den
         Kontrast zum brand-blue Body sicher. */
    }
    .boerdi-fab {
      /* FAB hat einen weißen "Hof" damit das blaue Logo gut sichtbar ist */
      background: #fff;
      border: 3px solid var(--boerdi-primary);
    }
    .boerdi-fab:hover { border-color: color-mix(in srgb, var(--boerdi-primary, #1c4587) 70%, white); }
    @keyframes boerdi-breathe {
      0%, 100% { transform: scale(1); }
      50%      { transform: scale(1.06); }
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
    /* Lazy-mount hide: keeps the panel in the DOM (component state
       preserved) but removes it visually and spatially. !important
       overrides the central display:flex rule above. */
    .boerdi-panel.boerdi-panel--hidden {
      display: none !important;
    }
    .boerdi-widget.with-canvas .boerdi-panel {
      width: 900px;
      max-width: calc(100vw - 40px);
    }
    @keyframes boerdi-slidein {
      from { opacity: 0; transform: translateY(20px) scale(0.95); }
      to   { opacity: 1; transform: translateY(0)    scale(1); }
    }

    /* Konsolidierter Header: vereint die früheren outer-panel-header und
       chat-internal-header zu einer Leiste. Avatar+Name+Status links,
       Mobile-Tabs in der Mitte, Action-Buttons + Close rechts. */
    .boerdi-panel-header {
      background: var(--boerdi-primary);
      color: #fff;
      padding: 8px 12px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 10px;
      flex-shrink: 0;
      min-height: 44px;
    }
    .boerdi-title-block {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      flex: 0 1 auto;
    }
    .boerdi-title-text {
      display: flex;
      flex-direction: column;
      line-height: 1.1;
      min-width: 0;
    }
    .boerdi-title {
      font-weight: 600;
      font-size: 15px;
      white-space: nowrap;
    }
    .boerdi-status {
      font-size: 11px;
      opacity: 0.85;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .boerdi-owl-mini {
      width: 32px;
      height: 32px;
      object-fit: contain;
      display: block;
      background: #ffffff;
      border-radius: 50%;
      padding: 2px;
      flex-shrink: 0;
    }
    .boerdi-owl-mini.is-thinking {
      animation: boerdi-thinking-spin 1.4s ease-in-out infinite;
    }
    .boerdi-owl-mini.is-speaking {
      animation: boerdi-speaking-bob .6s ease-in-out infinite;
    }
    @keyframes boerdi-thinking-spin {
      0%, 100% { transform: rotate(-5deg); }
      50% { transform: rotate(5deg); }
    }
    @keyframes boerdi-speaking-bob {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-2px); }
    }

    .boerdi-header-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }

    /* Action-Buttons mit klar kommuniziertem On/Off-State.
       ON  = solider weißer Pill mit vollfarbigem Icon (aktiviert/gedrückt)
       OFF = transparent mit weißem Outline + diagonalem Strich
       NEUTRAL = halbtransparent ohne Toggle-State (z.B. Restart) */
    .boerdi-action-btn {
      position: relative;
      border: 0;
      width: 32px;
      height: 32px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 15px;
      line-height: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: background .15s, color .15s, transform .1s, box-shadow .15s;
      padding: 0;
      /* Default-Icon-Farbe — weiß auf dem dunkelblauen Header. SVG-Icons
         erben currentColor, also wird das Material-Symbol weiß. Wird
         vom is-on-State auf dunkelblau überschrieben (Kontrast auf
         weißem Pill-Background). */
      color: #fff;
    }

    /* ON-State: solider weißer Pill, klar "gedrückt".
       Icon wird dunkelblau, damit Kontrast zum weißen Background passt. */
    .boerdi-action-btn.is-on {
      background: #ffffff;
      color: var(--boerdi-primary, #1c4587);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15),
                  inset 0 -1px 0 rgba(0, 0, 0, 0.06);
    }
    .boerdi-action-btn.is-on:hover {
      background: #f1f5f9;
      transform: translateY(-1px);
    }

    /* OFF-State: transparent + weißer Outline. Der Farbkontrast zum
       solid-weißen ON-Pill reicht aus — kein Slash-Overlay nötig.
       Icon bleibt weiß (vom Default) — auf dem dunklen Header sichtbar. */
    .boerdi-action-btn.is-off {
      background: rgba(255, 255, 255, 0.08);
      border: 1.5px solid rgba(255, 255, 255, 0.45);
      opacity: 0.85;
    }
    .boerdi-action-btn.is-off:hover {
      background: rgba(255, 255, 255, 0.18);
      border-color: rgba(255, 255, 255, 0.7);
      opacity: 1;
    }

    /* NEUTRAL (Restart) — kein Toggle-State, aber sichtbar */
    .boerdi-action-btn--neutral {
      background: rgba(255, 255, 255, 0.18);
      border: 1.5px solid rgba(255, 255, 255, 0.35);
      color: #fff;
    }
    .boerdi-action-btn--neutral:hover {
      background: rgba(255, 255, 255, 0.32);
      border-color: rgba(255, 255, 255, 0.6);
    }

    .boerdi-action-btn:active { transform: translateY(1px); }
    .boerdi-close {
      background: transparent;
      border: none;
      color: #fff;
      font-size: 26px;
      line-height: 1;
      cursor: pointer;
      padding: 0 4px;
      margin-left: 2px;
      opacity: 0.85;
    }
    .boerdi-close:hover { opacity: 1; }

    /* ── Lotsen-Banner ─────────────────────────────────────────
       Vom Bot vorgeschlagene Navigation. Schmaler Streifen über
       dem Body in dezentem Hellgrau-Blau, mit Header-Akzentfarbe
       als Primär-Button. Kein Orange — der Banner soll informieren,
       nicht alarmieren. */
    .boerdi-nav-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      background: #f1f5f9;
      border-bottom: 1px solid #e2e8f0;
      color: #1e293b;
      font-size: 13px;
      flex-wrap: wrap;
    }
    .nav-banner-icon {
      font-size: 16px;
      color: var(--boerdi-primary, #1c4587);
    }
    .nav-banner-text {
      flex: 1 1 220px;
      min-width: 0;
      line-height: 1.3;
    }
    .nav-banner-text strong {
      font-weight: 600;
      word-break: break-word;
      color: var(--boerdi-primary, #1c4587);
    }
    .nav-banner-actions {
      display: flex;
      gap: 6px;
      flex-shrink: 0;
    }
    .nav-banner-btn {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s;
    }
    .nav-banner-btn--primary {
      background: var(--boerdi-primary, #1c4587);
      color: #fff;
    }
    .nav-banner-btn--primary:hover {
      filter: brightness(1.1);
    }
    .nav-banner-btn--secondary {
      background: #ffffff;
      color: #475569;
      border-color: #cbd5e1;
    }
    .nav-banner-btn--secondary:hover {
      background: #f8fafc;
      border-color: #94a3b8;
    }

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
export class WidgetComponent implements OnInit, AfterViewInit, OnDestroy, OnChanges {
  // ChatComponent instance — we need public methods like browseCollection
  // and generateLearningPath, so this is the actual component, not an ElementRef.
  @ViewChild('chat') chatRef!: ChatComponent;

  /** Logo als Data-URL — funktioniert in Web Components zuverlässig
   *  (im Gegensatz zu `[innerHTML]`-Inline-SVG, das in Custom-Elements
   *  vom Browser-Sanitizer-Pfad gestrippt werden kann). Quelle:
   *  shared/boerdi-logo.ts */
  readonly boerdiLogo = BOERDI_LOGO_DATA_URL;
  /** Material Symbols als SVG-Strings — siehe ``shared/icons.ts``. */
  readonly ICONS = ICONS;

  @Input() apiUrl = '';
  @Input() pageContext: string | Record<string, any> = '';
  @Input() position: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left' = 'bottom-right';
  @Input() initialState: 'collapsed' | 'expanded' = 'collapsed';
  /** Akzentfarbe (CSS-Hex/CSS-Color). Wenn leer/unset, greift der
   *  ``:host``-CSS-Default ``#1c4587``. Der Host kann die Farbe auch
   *  per CSS-Variable überschreiben:
   *    ``boerdi-chat { --boerdi-primary: red; }``
   *  → das funktioniert nur sauber, solange ``primary-color`` NICHT
   *  zusätzlich gesetzt ist (Inline-Style wins). Daher: für Themes mit
   *  globalem Brand-Color setze entweder das HTML-Attribut ODER die
   *  CSS-Variable, nicht beides. */
  @Input() primaryColor = '';

  /** Bindet ``--boerdi-primary`` direkt aufs Host-Element — aber nur
   *  wenn der Embedder einen expliziten Wert mitgegeben hat. Ohne Wert
   *  bleibt das Attribut ungesetzt, sodass eine User-CSS-Regel wie
   *  ``boerdi-chat { --boerdi-primary: red }`` ungestört greifen kann.
   *  Mit Wert hat das Attribut Vorrang (Inline-Style schlägt CSS). */
  @HostBinding('style.--boerdi-primary')
  get hostPrimaryColor(): string | null {
    const v = (this.primaryColor || '').trim();
    return v || null;
  }
  @Input() persistSession: boolean | string = true;
  @Input() sessionKey = 'boerdi_session_id';
  /** Cookie domain for cross-subdomain session sharing.
   *  Set to e.g. ".wirlernenonline.de" so the session-id cookie is
   *  visible on suche.wirlernenonline.de, wp-test.wirlernenonline.de
   *  etc. Empty string = pure localStorage (origin-isolated). */
  @Input() sessionCookieDomain = '';
  /** Cookie max-age in seconds (default 30 days). */
  @Input() sessionCookieMaxAge: number | string = 30 * 24 * 60 * 60;
  /** Comma-separated whitelist of trusted hostnames the widget may
   *  pass the session-id to via ?bsid=…  in outgoing-link rewrites.
   *  Use bare domains ("openeduhub.net") or full hostnames
   *  ("redaktion.openeduhub.net"). Subdomain match is automatic
   *  (entry "openeduhub.net" matches any *.openeduhub.net).
   *  Empty (default) = no rewrite, no cross-TLD handoff.
   *
   *  Example: trusted-domains="wirlernenonline.de,openeduhub.net"
   */
  @Input() trustedDomains = '';
  @Input() greeting = '';
  @Input() autoContext: boolean | string = true;
  /** Neue Such-Ergebnis-Darstellung (Sprint 7, 2026-05-19):
   *  Wenn ``true`` zeigt der Chat keine flache Card-Liste mehr, sondern
   *  gruppiert die Treffer pro Bot-Antwort in eigene Boxen:
   *    - Top 3 Themenseiten
   *    - Top 3 Sammlungen
   *    - Search-CTA-Box mit Link zur kompletten Trefferliste
   *      (kein Einzelinhalte-Kachelblock mehr; das LLM darf sie noch
   *      kennen, aber visuell springt der User direkt in die Suche)
   *  Wirkt parallel auf Chat-Cards und Canvas-Cards. Default ``false`` =
   *  Bestehendes Verhalten — kein Bestandsbruch. */
  @Input() inlineResultGrouping: boolean | string = false;
  /** Show the 🔍 debug-toggle button in the chat header. Default true. */
  @Input() showDebugButton: boolean | string = true;
  /** Show the 🔊 TTS and 🎤 mic buttons. Default true. */
  @Input() showLanguageButtons: boolean | string = true;

  // ── Widget-Embed-Modi ──────────────────────────────────────────
  // Vier Schalter, mit denen der einbettende Host (WordPress, Edu-Sharing,
  // Themenseite…) das Widget feature-by-feature minimaler auftreten lässt.
  // Default jeweils ``true`` — Bestandsintegrationen sehen keine Änderung.
  // HTML-Attribute werden in Angular Custom Elements als Strings übergeben,
  // daher akzeptieren wir auch ``"false"``/``"true"`` neben den Booleans.
  /** Canvas-Pane (Material-Erstellung, Lernpfad-Anzeige) deaktivieren.
   *  Bei ``false`` rendert das Backend Material/Lernpfad direkt in den
   *  Chat-Verlauf, das Canvas öffnet sich nicht mehr. */
  @Input() canvasEnabled: boolean | string = true;
  /** KI-generierte Inhalte (Arbeitsblatt, Quiz, Lernpfad, Remix)
   *  deaktivieren. Bei ``false`` lehnt der Bot Erstell-Anfragen mit der
   *  Alt-Response aus ``widget-modes.yaml`` freundlich ab. */
  @Input() aiContentEnabled: boolean | string = true;
  /** Kachel-Anzeige deaktivieren. Bei ``false`` werden Treffer als
   *  Inline-Markdown-Links in der Bot-Antwort gerendert (max. N aus
   *  Studio-Setting ``cards_inline_link_limit``). */
  @Input() cardsEnabled: boolean | string = true;
  /** Gesprächsvorschläge-Pillen deaktivieren. Bei ``false`` werden alle
   *  Quick-Reply-Buttons ausgeblendet — Lotsen-`__guide__|…`-QRs werden
   *  vom Backend stattdessen als Inline-Markdown am Antwort-Ende eingebaut. */
  @Input() quickRepliesEnabled: boolean | string = true;

  /** Boolean-Coercion für die vier Embed-Mode-Inputs.
   *  HTML-Custom-Element-Attribute kommen immer als Strings rein
   *  (``cards-enabled="false"`` → String ``"false"``). Default = true,
   *  damit eine fehlende Attribut-Setzung das Legacy-Verhalten erhält.
   *  Nur die expliziten Werte ``false`` (bool) und ``"false"`` (string,
   *  case-insensitive) deaktivieren das Feature. */
  private modeFlag(v: boolean | string): boolean {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.toLowerCase() !== 'false';
    return true;
  }
  get canvasEnabledBool(): boolean { return this.modeFlag(this.canvasEnabled); }
  get cardsEnabledBool(): boolean { return this.modeFlag(this.cardsEnabled); }
  get aiContentEnabledBool(): boolean { return this.modeFlag(this.aiContentEnabled); }
  get quickRepliesEnabledBool(): boolean { return this.modeFlag(this.quickRepliesEnabled); }
  /** When true, link clicks are intercepted: navigation is suppressed and
   *  `linkClicked` is emitted with the path+search (e.g.
   *  `/components/collections?id=…`). Default false = navigate normally. */
  @Input() interceptEduSharingLinks: boolean | string = false;
  /** Emitted (instead of navigating) when `interceptEduSharingLinks` is true. */
  @Output() linkClicked = new EventEmitter<string>();

  /** Lotsen-Modus: passive Top-Result-Emission. Bei ``true`` feuert das
   *  Widget bei jedem Bot-Turn, der Lotsen-Treffer enthält, ein
   *  ``badboerdi:guide-suggestion``-CustomEvent auf ``window`` + ein
   *  ``(guideSuggestion)``-Output. Default ``false`` — Hosts ohne
   *  Listener sehen keinen Unterschied. Siehe ``docs/javascript-api.md``
   *  für Payload-Schema und Embed-Beispiele. */
  @Input() emitGuideSuggestion: boolean | string = false;
  /** Mirrors the ``badboerdi:guide-suggestion`` CustomEvent for Angular
   *  consumers. Same payload as the global event. Gated by
   *  ``emitGuideSuggestion``. */
  @Output() guideSuggestion = new EventEmitter<any>();
  /** Welle C.4 (2026-05): Wenn ``true``, feuert das Widget bei jedem
   *  Bot-Turn ein ``badboerdi:routing-debug``-CustomEvent auf ``window``
   *  + ``(routingDebug)``-Output mit Pattern/Intent/State/Tools/Persona/
   *  Modifier. Default ``false`` — keine zusätzlichen Events ohne Opt-In.
   *  Siehe ``docs/05-widget-javascript-api.md`` für Payload-Schema. */
  @Input() emitRoutingDebug: boolean | string = false;
  /** Mirrors the ``badboerdi:routing-debug`` CustomEvent for Angular
   *  consumers. Same payload as the global event. Gated by
   *  ``emitRoutingDebug``. */
  @Output() routingDebug = new EventEmitter<any>();
  /** Emits MCP search query metadata (tool name, query type, criteria,
   *  pagination, repository URL) for every bot turn that ran MCP searches.
   *  Dispatched as ``badboerdi:query-meta`` CustomEvent on ``window`` AND
   *  this Angular Output. Always active (no opt-in gate). */
  @Output() queryMeta = new EventEmitter<any>();

  // ── Lotsen-Modus-Inputs ─────────────────────────────────────────
  /** Sichtbarkeit des 🧭-Toggle-Buttons im Header. Default `true`.
   *  Wenn `false`, wird der Button ausgeblendet — der Lotsen-Modus
   *  selbst kann aber trotzdem aktiv sein (per `guide-mode-default` oder
   *  per Backend-Default aus `guide-mode.yaml`). Nützlich für Embeds,
   *  in denen der Host das Toggling selbst steuert (z.B. über einen
   *  globalen Settings-Switch) und das Widget keine eigene UI dafür
   *  anbieten soll. */
  @Input() showGuideButton: boolean | string = true;
  /** Initial-State des Lotsen-Modus. Drei Werte:
   *    - `"true"` / `true`  → an
   *    - `"false"` / `false` → aus
   *    - leer / `"auto"`     → wie heute (URL-Param ?bgm → localStorage →
   *                            Backend-Default aus `guide-mode.yaml`)
   *  Wird ein expliziter Wert gesetzt, überschreibt er URL und
   *  localStorage NICHT — heißt, ein User-Toggle hat weiter Vorrang.
   *  Der Wert dient als Default beim allerersten Boot, wenn weder URL
   *  noch localStorage etwas hergeben. */
  @Input() guideModeDefault: boolean | string = 'auto';

  expanded = false;
  /** Welle C Sprint 7 (2026-05-19): Lazy-Mount-Flag für das Chat-Panel.
   *  Vorher war das Panel ``*ngIf="expanded"`` → bei jedem Collapse wurde
   *  ``<badboerdi-chat>`` aus dem DOM entfernt und ``messages``-Signal,
   *  Canvas-State usw. gingen verloren. Beim Reopen lief ``ngOnInit`` +
   *  ``restoreHistory()`` neu — Bot-Text kam zurück, aber Cards/Canvas-
   *  Content nur soweit der Backend-Restore das wiederherstellen kann
   *  (Cards ja seit A1-Fix, Canvas-Markdown jedoch nicht).
   *
   *  Lösung: ``everExpanded`` wird beim allerersten Open auf ``true``
   *  gesetzt und bleibt das für die Lifetime des Widgets. Das Panel
   *  rendert ab dann **immer** im DOM, nur visuell wird es per CSS
   *  (``.boerdi-panel--hidden``) ein-/ausgeblendet. Component-State
   *  überlebt jedes Collapse-Reopen.
   *
   *  Lazy-Mount bleibt erhalten: User, die das Widget nie öffnen, zahlen
   *  keinen Bootstrap-Cost; erst der erste Click instanziiert ``<badboerdi-chat>``. */
  everExpanded = false;
  resolvedPageContext: Record<string, any> = {};

  // ── Webseiten-Guide-Modus (Lotsen-Modus) ──────────────────────
  /** True when this host is on the backend-configured allow-list. The
   *  toggle is hidden on every other domain — there's nothing to lotse
   *  to. Re-evaluated once at init from /api/config/guide-mode. */
  guideModeAvailable = signal(false);
  /** Toggle state. Persisted in ``localStorage['boerdi.guide_mode']``,
   *  default from backend config (``default_enabled`` in guide-mode.yaml). */
  guideMode = signal(false);

  /** Bool-Coercion für ``show-guide-button``. HTML-Attribute kommen als
   *  String rein — wir erlauben den expliziten ``"false"`` zum Abschalten;
   *  alles andere (true, "true", undefined, leer) ist an. */
  get showGuideButtonBool(): boolean {
    if (typeof this.showGuideButton === 'boolean') return this.showGuideButton;
    if (typeof this.showGuideButton === 'string') {
      return this.showGuideButton.toLowerCase() !== 'false';
    }
    return true;
  }
  /** Tristate für ``guide-mode-default``:
   *    `true`  → Default = an
   *    `false` → Default = aus
   *    `null`  → Backend/URL/localStorage entscheiden (Default-Verhalten)
   */
  get guideModeDefaultTristate(): boolean | null {
    const v = this.guideModeDefault;
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') {
      const s = v.toLowerCase().trim();
      if (s === 'true' || s === '1' || s === 'on') return true;
      if (s === 'false' || s === '0' || s === 'off') return false;
    }
    return null;  // 'auto' / leer / unbekannt → Backend-Default greift
  }
  /** Hostname snapshot we send to the backend so it knows whether to
   *  attach ``guide_url`` to outgoing cards. Filled at init. */
  private guideHost = '';
  private static readonly GUIDE_LS_KEY = 'boerdi.guide_mode';
  /** Bot-initiated navigation target — set when the backend sends a
   *  ``page_action: navigate`` payload. The widget shows a banner with
   *  "Bring mich hin" / "Hier bleiben"; the user must explicitly confirm
   *  before we leave the host page. ``null`` hides the banner. */
  guideNavTarget = signal<{ url: string; label: string } | null>(null);

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
  /** MCP-Search-URL + Begriff aus dem letzten ``badboerdi:query-meta``-
   *  Event. Wird im Grouping-Modus als Search-CTA im Canvas angeboten. */
  canvasSearchCtaUrl = signal('');
  canvasSearchCtaTerm = signal('');
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

  // Welle C Sprint 7 (2026-05-19): Auto-Open-Persistenz auf sessionStorage
  // umgestellt. Der vorherige localStorage-Ansatz hat das Widget auf
  // *jeder* Seite des gleichen Hosts auto-geöffnet wenn der User es 30
  // Minuten vorher mal angeklickt hatte — auf WordPress-Multi-Page-Setups
  // (z.B. wp-test.wirlernenonline.de) wirkte das wie "Chatbot öffnet sich
  // bei jedem Seitenwechsel".
  //
  // sessionStorage löst das sauber: persistiert nur innerhalb DESSELBEN
  // Browser-Tabs (Same-Tab-Navigation bleibt open → User-Erfahrung
  // konsistent), aber jeder neue Tab / Refresh / Cross-Tab-Navigation
  // startet wieder mit closed. Cross-TLD-Handoff per ``?bsid=`` forciert
  // weiterhin open, unabhängig vom Storage.
  //
  // TTL muss damit nicht mehr begrenzt werden — sessionStorage räumt
  // sich beim Tab-Close von selbst auf.
  private readonly OPEN_KEY = 'boerdi_widget_open';

  // Fallback window listener — if the Angular @Output() binding on
  // <badboerdi-chat> doesn't propagate (e.g. when the widget is mounted
  // as a Custom Element that re-wraps the event flow), we still catch
  // the same page_action via the CustomEvent the chat component dispatches.
  private _onWindowPageAction?: (e: Event) => void;
  private _onWindowQueryMeta?: (e: Event) => void;

  constructor(
    private zone: NgZone,
    private api: ApiService,
    private cdr: ChangeDetectorRef,
    private elementRef: ElementRef<HTMLElement>,
  ) {}

  /** Reaktiv auf Attribut-Änderungen zur Laufzeit.
   *
   *  Angular Custom Elements (``createCustomElement``) ruft beim Setzen
   *  eines HTML-Attributs nicht den Eingangs-Setter direkt auf, sondern
   *  delegiert an ``@Input``-Properties → ``ngOnChanges`` läuft. Dadurch
   *  kann die einbettende Seite z.B. ``element.setAttribute('initial-state',
   *  'expanded')`` aufrufen und das Widget öffnet sich automatisch.
   *
   *  Gleicher Mechanismus erlaubt:
   *    - ``setAttribute('initial-state', 'expanded')``  → öffnen
   *    - ``setAttribute('initial-state', 'collapsed')`` → schließen
   *  oder die Public-Methoden ``openChatbot() / closeChatbot()`` (siehe
   *  unten). Beide Wege sind erlaubt und idempotent.
   */
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['initialState'] && !changes['initialState'].firstChange) {
      const next = this.initialState === 'expanded';
      if (next !== this.expanded) {
        this.setExpanded(next);
      }
    }
  }

  ngOnInit() {
    this.expanded = this.initialState === 'expanded';

    // Cross-TLD-Handoff: if the URL contains ?bsid=… the user was
    // navigated here from another page with an active chat session.
    // Auto-open the widget so the conversation continues seamlessly.
    try {
      const sp = new URL(window.location.href).searchParams;
      if (sp.has('bsid')) {
        this.expanded = true;
      }
    } catch { /* ignore */ }

    // Restore expanded state across SAME-TAB page navigation. sessionStorage
    // (statt früher localStorage) bewirkt: Multi-Page-Sites wie WordPress
    // behalten den Open-Zustand wenn der User innerhalb eines Tabs navigiert;
    // ein neuer Tab oder Refresh startet aber wieder mit closed. Cross-TLD-
    // Handoff per ``?bsid=`` (oben) bleibt unabhängig davon der force-open.
    try {
      if (sessionStorage.getItem(this.OPEN_KEY) === '1') {
        this.expanded = true;
      }
    } catch { /* ignore */ }

    // Lazy-Mount-Flag setzen, nachdem ALLE Open-Entscheidungen
    // (initialState, bsid, sessionStorage) ausgewertet wurden. Wenn das
    // Widget mit Panel-Open startet, ist das Lazy-Gate sofort offen
    // — sonst erst beim ersten User-Click (gesetzt in ``setExpanded``).
    if (this.expanded) this.everExpanded = true;

    // ── Webseiten-Guide-Modus initialisieren ────────────────────
    // Allow-Liste + Default-Status vom Backend laden, mit dem aktuellen
    // ``window.location.hostname`` matchen, dann localStorage-Override
    // anwenden. Komplett async und non-blocking — der Toggle bleibt
    // versteckt bis die Antwort da ist (typisch <50 ms).
    this.guideHost = (window?.location?.hostname || '').toLowerCase();
    this.initGuideMode();

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

      // Page-context-detector: recognise WLO topic / collection / content
      // pages and pull the relevant ids + visible text. Backend's
      // page_context_service resolves these via MCP into structured
      // metadata (title, disciplines, keywords, …). Manual `pageContext`
      // input below still wins — it's the explicit override path.
      try {
        const detected = detectPageContext();
        // Only attach non-empty, scalar fields. Drop undefined keys so
        // the backend doesn't store empty strings as "set" values.
        const cleaned: Record<string, any> = {};
        for (const [k, v] of Object.entries(detected)) {
          if (v !== undefined && v !== null && v !== '') cleaned[k] = v;
        }
        this.resolvedPageContext = { ...this.resolvedPageContext, ...cleaned };
      } catch { /* ignore — never fail widget bootstrap on detection */ }
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

    // Forward query-meta events to the Angular Output emitter.
    this._onWindowQueryMeta = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail) {
        this.zone.run(() => {
          this.queryMeta.emit(detail);
          // Search-CTA für Canvas/Chat-Grouping aus den Query-Metas extrahieren.
          // Priorisiere search_wlo_content (breit), dann collections/topic_pages.
          const queries = Array.isArray(detail?.queries) ? detail.queries : [];
          const byTool = (t: string) => queries.find((q: any) => q?.tool_name === t && q?.search_url);
          const meta = byTool('search_wlo_content')
            || byTool('search_wlo_collections')
            || byTool('search_wlo_topic_pages')
            || queries.find((q: any) => q?.search_url);
          if (meta?.search_url) {
            this.canvasSearchCtaUrl.set(String(meta.search_url));
            this.canvasSearchCtaTerm.set(String(meta.search_term || ''));
          }
        });
      }
    };
    window.addEventListener('badboerdi:query-meta', this._onWindowQueryMeta);

    // Outgoing-Link-Rewrite für Cross-TLD-Session-Handoff. Greift Link-
    // Klicks INNERHALB des Widget-Host-Elements ab (Cards, Inline-Markdown,
    // Canvas-Pane, Lotsen-CTAs) und hängt ``?bsid=…`` an, falls das Ziel
    // zu einer Whitelist-Domain führt. Host-Seiten-Links bleiben unberührt
    // — siehe Scope-Kommentar unten und Bug-Fix-Hintergrund.
    //
    // WICHTIG: Handler IMMER registrieren, auch wenn die Trusted-Domain-
    // Liste zum Zeitpunkt von ``ngAfterViewInit`` noch leer ist. Grund:
    // ``initGuideMode()`` lädt die Backend-Liste async — die Liste kann
    // zum AfterViewInit-Zeitpunkt noch nicht da sein. Würden wir den
    // Handler nur installieren wenn die Liste schon voll ist, käme er
    // bei langsamen Backend-Antworten nie zustande, und Inline-Links
    // im Lotsen-Modus müssten erst beim zweiten Klick navigieren
    // (Browser-Default-Pfad statt explizite ``window.location.href``-
    // Navigation). Die Trusted-Host-Prüfung passiert pro Klick im
    // Handler selbst — leere Liste = Handler bailt früh aus = Kosten 0.
    // Scope auf das ``<boerdi-chat>``-Host-Element. Vorher hing der
    // Handler am ``document`` und intercepted JEDEN Klick auf der Host-
    // Seite — was bei Embeds wie WLO normale Navigation kaputt machte
    // (Same-Tab-Links wurden mit ``preventDefault`` + ``window.location.href``
    // explizit navigiert, was z.B. SPA-Routing oder Bound-Click-Handler
    // der Host-Seite umgangen hat). Mit Scope auf die Widget-Wurzel
    // greift der bsid-Rewrite nur noch innerhalb von Card-Grid, Inline-
    // Markdown-Links, Canvas-Pane und Lotsen-CTAs. Externe Host-Page-
    // Links bleiben vom Widget völlig unberührt.
    //
    // Side-Effect: Cross-TLD-Handoff per ``?bsid=`` greift bei nicht-
    // Widget-Links auf der Host-Seite nicht mehr automatisch. Hosts die
    // das brauchen, können den Host weiter selbst per JS ergänzen.
    this._onDocumentLinkClick = (e: Event) => this._maybeRewriteOutgoingLink(e);
    const host = this.elementRef?.nativeElement || document;
    host.addEventListener('click', this._onDocumentLinkClick, true);
    // Host-Referenz merken für sauberes Detach in ngOnDestroy.
    this._clickListenerHost = host;

    // Canvas-Restore nach Page-Refresh: ChatComponent's ngOnInit hat
    // beim ViewInit-Zeitpunkt seine sessionId bereits aus localStorage/
    // Cookie eingelesen. Wir fragen den Backend-Endpoint ab und befüllen
    // die Canvas-Signale, ohne den Pane automatisch zu öffnen — der User
    // sieht den letzten Canvas-Inhalt erst, wenn er das Canvas selbst
    // wieder öffnet (z.B. via "Material anzeigen"-Quick-Reply oder über
    // die Bot-Antwort, die noch auf canvas_open hinweist). Vermeidet
    // unerwünschte UX wenn der User das Canvas vor Refresh geschlossen
    // hatte. Setzt nur, wenn aktuell noch nichts im Canvas liegt
    // (canvasMarkdown leer) — sonst hätte schon ein neueres Event
    // (z.B. canvas_open aus laufender Antwort) Priorität.
    this._restoreCanvasAfterBootstrap();
  }

  private async _restoreCanvasAfterBootstrap(): Promise<void> {
    // ChatComponent's sessionId ist sync verfügbar nach ngOnInit.
    // ngAfterViewInit auf dem Widget läuft NACH ngOnInit auf dem Chat-
    // Child, daher ist chatRef.sessionId hier garantiert gesetzt.
    const sid = this.chatRef?.sessionId;
    if (!sid) return;
    // Schon Canvas-Inhalt da? Nicht überschreiben — andere Pfade
    // (laufende Bot-Antwort, manueller Edit) haben Priorität.
    if (this.canvasMarkdown()) return;
    try {
      const payload = await this.api.loadCanvas(sid);
      if (!payload || !payload.markdown) return;
      // Innerhalb der Angular-Zone aktualisieren, damit Change Detection
      // ausgelöst wird (loadCanvas läuft mit await außerhalb des Click-
      // oder Lifecycle-Trigger-Pfades, das ist hier nicht zonal).
      this.zone.run(() => {
        this.canvasTitle.set(payload.title || 'Canvas');
        this.canvasMaterialLabel.set(payload.material_type_label || '');
        const cat = payload.material_type_category;
        this.canvasMaterialCategory.set(
          cat === 'analytisch' ? 'analytisch'
            : cat === 'didaktisch' ? 'didaktisch' : null,
        );
        this.canvasMarkdown.set(payload.markdown || '');
        this.canvasPreferredView.set('material');
        // ``canvasOpen`` bewusst NICHT auf true setzen — siehe Kommentar
        // im Caller. User muss selbst entscheiden ob Canvas wieder
        // sichtbar wird. Die Signale sind aber für den Moment befüllt.
      });
    } catch { /* never fail bootstrap on this */ }
  }

  ngOnDestroy() {
    if (this._onWindowPageAction) {
      window.removeEventListener('badboerdi:page-action', this._onWindowPageAction);
    }
    if (this._onWindowQueryMeta) {
      window.removeEventListener('badboerdi:query-meta', this._onWindowQueryMeta);
    }
    if (this._onDocumentLinkClick) {
      // Detach vom selben Host, an den ngAfterViewInit den Listener
      // gehängt hatte (Widget-Host-Element, nicht document).
      const host = this._clickListenerHost || document;
      host.removeEventListener('click', this._onDocumentLinkClick, true);
    }
  }

  // ── Cross-TLD-Session-Handoff ─────────────────────────────────────
  private _onDocumentLinkClick?: (e: Event) => void;
  /** Wohin der Click-Listener gehängt wurde — gespeichert damit
   *  ``ngOnDestroy`` ihn am SELBEN Element wieder abnimmt. */
  private _clickListenerHost?: HTMLElement | Document;

  /** Cached parsed list of trusted hostnames (lower-case), merged from
   *  HTML-attribute + backend ``/api/config/guide-mode.trusted_domains``.
   *  Beide Quellen werden zusammengeführt; das HTML-Attribut darf die
   *  Backend-Liste ergänzen (z.B. für lokale Dev-Hosts), kann aber
   *  Backend-Einträge nicht *entfernen* — das verhindert, dass ein
   *  Stored-XSS auf einer Host-Seite die Backend-Allow-Liste umgehen
   *  könnte (Defense-in-Depth). */
  private _trustedDomainsCache: string[] | null = null;
  /** Backend-Liste aus ``initGuideMode`` — wird einmal beim Boot
   *  befüllt; Cache-Invalidierung in ``_parsedTrustedDomains`` schaut
   *  ``trustedDomains``-Attribut UND diese Liste an. */
  private _backendTrustedDomains: string[] = [];

  private _parsedTrustedDomains(): string[] {
    if (this._trustedDomainsCache !== null) return this._trustedDomainsCache;
    const fromAttr = (this.trustedDomains || '')
      .split(/[,\s]+/)
      .map(s => this._normalizeDomain(s))
      .filter(s => s.length > 0);
    const seen = new Set<string>();
    const merged: string[] = [];
    // Backend zuerst (vertrauenswürdige Quelle); Attribut ergänzt
    // additiv für Dev-Hosts (`localhost`, eigene Testdomains).
    for (const list of [this._backendTrustedDomains, fromAttr]) {
      for (const d of list) {
        if (d && !seen.has(d)) {
          seen.add(d);
          merged.push(d);
        }
      }
    }
    this._trustedDomainsCache = merged;
    return merged;
  }

  private _normalizeDomain(input: string): string {
    return (input || '')
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/^\*\./, '')   // *.example.com → example.com (matcher behandelt Subdomains via endsWith)
        .split('/')[0];
  }

  /** Aktuelle Whitelist als Array — wird ans Chat-Component gegeben,
   *  damit dort Inline-Markdown-Links korrekt klassifiziert werden können
   *  (Trusted → same-tab + ?bsid= via Outgoing-Rewrite; External → target=_blank).
   *  Returns die gleiche zusammengeführte Liste wie ``_parsedTrustedDomains()``. */
  get parsedTrustedHostList(): string[] {
    return this._parsedTrustedDomains();
  }

  /** True wenn host zur Whitelist passt — exakter Match ODER Subdomain. */
  private _isTrustedHost(host: string): boolean {
    const h = (host || '').toLowerCase();
    if (!h) return false;
    for (const t of this._parsedTrustedDomains()) {
      if (h === t) return true;
      if (h.endsWith('.' + t)) return true;  // *.t matches t
    }
    return false;
  }

  /** Click-Handler: hängt ?bsid=<sessionId> an Links zu trusted hosts an. */
  private _maybeRewriteOutgoingLink(e: Event): void {
    try {
      // Find the closest <a href="..."> from the click target — manche Sites
      // wrappen Links in span/div, MouseEvent.target ist dann nicht der Anchor.
      let el = e.target as HTMLElement | null;
      while (el && el.tagName !== 'A') {
        el = el.parentElement;
        if (!el || el === document.body) return;
      }
      const anchor = el as HTMLAnchorElement | null;
      if (!anchor || !anchor.href) return;

      // URL parsen — wenn das fehlschlägt (mailto:, javascript:, …), nichts tun.
      let target: URL;
      try { target = new URL(anchor.href, window.location.href); }
      catch { return; }
      if (target.protocol !== 'http:' && target.protocol !== 'https:') return;

      // Intercept mode: suppress navigation, emit the direct link instead.
      if (this.interceptEduSharingLinks === true || this.interceptEduSharingLinks === 'true') {
        const linkTarget: string = target.pathname + (target.search || '');
        if (linkTarget.includes('/edu-sharing')) {
          e.preventDefault();
          this.linkClicked.emit(linkTarget);
          return;
        }
      }

      // Nicht selbst-rewriten: Sprünge auf dieselbe Origin können einfach
      // localStorage / Cookie nutzen — bsid würde nur unnötig die URL füllen.
      if (target.origin === window.location.origin) return;

      // Ziel in Whitelist?
      if (!this._isTrustedHost(target.hostname)) return;

      // Session-ID aus dem Chat-Component holen (ViewChild) — das ist die
      // Quelle der Wahrheit, weil sie Stufe-A-Pickup, Cookie und localStorage
      // bereits konsolidiert hat.
      const sid = this.chatRef?.sessionId;
      if (!sid || !/^bb-[0-9a-f-]{32,40}$/i.test(sid)) return;

      // Schon vorhanden? Nicht doppelt setzen.
      if (target.searchParams.has('bsid')) return;

      target.searchParams.set('bsid', sid);
      const finalUrl = target.toString();
      // Anchor-href IMMER aktualisieren — für Middle-Click und Modifier-Click
      // (Ctrl/Cmd/Shift) nutzt der Browser die Anchor-href, um den Link in
      // einem neuen Tab/Fenster zu öffnen; die sollen ebenfalls den
      // ``bsid``-Param tragen.
      anchor.href = finalUrl;
      // Plain Left-Click ohne Modifier auf same-tab-Links: EXPLIZIT
      // navigieren statt auf den Browser-Default zu hoffen. Manche
      // Tracking-Blocker (Brave Shield, strict-mode Privacy-Erweiterungen)
      // frieren die ``anchor.href`` zum Klick-Start ein und ignorieren
      // spätere Mutationen — der erste Klick verpufft, erst der zweite
      // folgt der neuen URL. Manuelle Navigation via ``window.location.href``
      // umgeht dieses Behavior.
      //
      // Wichtig: NUR für same-tab-Links (kein ``target`` oder ``target="_self"``).
      // Karten-Buttons mit ``target="_blank"`` sollen weiterhin in einem neuen
      // Tab öffnen — das machen sie via Browser-Default mit der (jetzt
      // mutierten) ``anchor.href``. Würden wir hier ``window.location.href``
      // setzen, wäre das eine same-tab-Navigation und der Endnutzer würde
      // die Host-Seite verlieren.
      const tgt = (anchor.target || '').toLowerCase();
      const isSameTab = tgt === '' || tgt === '_self';
      if (
        isSameTab
        && e instanceof MouseEvent
        && e.button === 0
        && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey
      ) {
        e.preventDefault();
        window.location.href = finalUrl;
      }
    } catch { /* never break user clicks */ }
  }

  toggle() {
    this.setExpanded(!this.expanded);
  }

  /** **Public API** — Chat-Panel öffnen.
   *
   *  Wird vom Custom Element exponiert, sodass die einbettende Seite
   *  einfach ``document.querySelector('boerdi-chat').openChatbot()``
   *  aufrufen kann. Kein Shadow-DOM-Hack mehr nötig.
   *
   *  Beim Öffnen scrollt das Widget automatisch ans Ende der Nachrichten-
   *  Liste (siehe ``setExpanded``), damit der User sofort die letzten
   *  Bot-Antworten sieht — auch wenn beim vorherigen Schließen weiter
   *  oben im Verlauf gescrollt war.
   */
  openChatbot(): void {
    this.setExpanded(true);
  }

  /** **Public API** — Chat-Panel schließen (FAB sichtbar). */
  closeChatbot(): void {
    this.setExpanded(false);
  }

  /** **Public API** — Toggle zwischen offen/zu. */
  toggleChatbot(): void {
    this.toggle();
  }

  /** **Public API** — Aktueller Zustand (für Hosts, die nach Click auf
   *  ihren eigenen Trigger wissen wollen, ob das Panel grad offen ist). */
  isChatbotOpen(): boolean {
    return this.expanded;
  }

  /** Zentraler Setter — sorgt dafür, dass alle Öffnen/Schließen-Pfade
   *  (Toggle-Button, Public-API, attributeChangedCallback) konsistent
   *  localStorage pflegen und Angular die View neu rendert. */
  private setExpanded(open: boolean): void {
    // Same-Tab-Persistenz über sessionStorage — überlebt Page-Navigation
    // innerhalb desselben Tabs, nicht aber Tab-Close oder Cross-Tab.
    // Wert ist '1' statt Timestamp (TTL nicht mehr nötig, sessionStorage
    // wird beim Tab-Close von selbst geräumt).
    try {
      if (open) {
        sessionStorage.setItem(this.OPEN_KEY, '1');
      } else {
        sessionStorage.removeItem(this.OPEN_KEY);
      }
    } catch { /* ignore */ }
    if (this.expanded === open) return;
    this.expanded = open;
    if (open) this.everExpanded = true;
    // Angular Change-Detection läuft beim Klick automatisch — bei
    // externen Aufrufen (außerhalb Zone) müssen wir manuell anstoßen,
    // damit die View aktualisiert wird.
    try { this.cdr?.markForCheck?.(); } catch { /* ignore */ }

    // Beim Öffnen: Nachrichten-Liste ans Ende scrollen, damit der User
    // die letzten Bot-Antworten sieht. Wichtig für ``openChatbot()``-
    // Aufrufe vom Host — wenn z.B. ein WordPress-Button das Widget öffnet,
    // soll nicht der oberste (lange zurückliegende) Verlauf-Anfang
    // sichtbar sein. Greift auch für FAB-Click und ``initial-state``-
    // Attribut-Änderung.
    //
    // requestAnimationFrame doppelt-gestapelt: erste rAF lässt Angular
    // die ``expanded=true``-Bindings rendern (das Panel mountet, die
    // Chat-Component initialisiert sich, ``ViewChild chatRef`` wird
    // gefüllt). Zweite rAF wartet auf den Layout-Paint — erst dann hat
    // der ``messagesContainer`` seine echte ``scrollHeight``.
    if (open) {
      try {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try { this.chatRef?.scrollToLatest?.(); } catch { /* ignore */ }
          });
        });
      } catch { /* ignore */ }
    }
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
    // Defense-in-Depth: bei canvasEnabled=false werden Canvas-PageActions
    // ignoriert, falls das Backend doch eine durchgelassen hat (alte
    // Bundle-Version, Race-Condition). Der Backend-Postprocess sollte
    // sie bereits in den Bot-Text gepatcht haben — hier nur zur Sicherheit.
    if (!this.canvasEnabledBool && (
      pa.action === 'canvas_open' ||
      pa.action === 'canvas_update' ||
      pa.action === 'canvas_show_cards'
    )) {
      return;
    }
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
          this.canvasVisibleCount.set(merged.length);
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
      case 'navigate': {
        // Bot recommends an external navigation. We never auto-leave the
        // host page — show a banner and require an explicit user click.
        // Only honoured when guide mode is on AND the URL host is on the
        // configured allow list (the URL is enforced backend-side too).
        if (!this.guideMode()) break;
        const p = pa.payload || {};
        const url = typeof p.url === 'string' ? p.url.trim() : '';
        const label = typeof p.label === 'string' ? p.label : (p.title || '');
        if (!url) break;
        this.guideNavTarget.set({ url, label: label || url });
        break;
      }
      default:
        break;
    }
  }

  /** User clicked "Bring mich hin" on the navigate banner. Leaves the
   *  page in the current tab. */
  confirmGuideNav(): void {
    const t = this.guideNavTarget();
    if (!t) return;
    this.guideNavTarget.set(null);
    this.navigateToGuideUrl(t.url);
  }

  /** User clicked "Hier bleiben" — dismiss the navigate banner. */
  cancelGuideNav(): void {
    this.guideNavTarget.set(null);
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
      case 'guide': {
        // Lotsen-Modus: navigate the current tab to the allow-listed
        // target URL. ``guide_url`` only exists when the backend judged
        // the card eligible — no extra check needed here.
        const url = (c as WloCard & { guide_url?: string }).guide_url || '';
        if (!url) {
          console.warn('[canvas] guide action without guide_url on card');
          return;
        }
        this.navigateToGuideUrl(url);
        return;   // page is leaving — no further state changes
      }
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
        window.open(c.link || c.guide_url || c.wlo_url || c.url || '#', '_blank', 'noopener');
        return;
    }
    this.mobileTab.set('chat');
  }

  // ── Guide-Mode: Init / Allow-Liste / Toggle / Navigation ─────

  /** Match the current host against ``*.example.com``-style patterns.
   *  Same semantics as the backend's ``host_is_allowed`` so allow/deny
   *  decisions stay consistent on both sides. */
  private hostMatchesPattern(host: string, pattern: string): boolean {
    if (!host || !pattern) return false;
    const p = pattern.trim().toLowerCase();
    if (p.startsWith('*.')) {
      const suffix = p.slice(1);          // ".example.com"
      return host.endsWith(suffix) && host !== p.slice(2);
    }
    return host === p;
  }

  /** Fetch the guide-mode allow-list from the backend, decide whether
   *  the toggle should appear here, and apply any saved override from
   *  localStorage. Failures default to "guide off" — never block the
   *  widget. */
  private async initGuideMode(): Promise<void> {
    let allowedHosts: string[] = [];
    let defaultEnabled = true;
    try {
      const apiBase = (this.apiUrl || '').replace(/\/+$/, '');
      const resp = await fetch(`${apiBase}/api/config/guide-mode`);
      if (resp.ok) {
        const data = await resp.json();
        allowedHosts = Array.isArray(data?.allowed_hosts) ? data.allowed_hosts : [];
        defaultEnabled = !!data?.default_enabled;
        // Backend-trusted_domains in den Cache ziehen — werden bei der
        // Cross-TLD-Brücke (?bsid=…) mit der HTML-Attribut-Liste gemerged.
        // Bei späteren Builds liefert das Backend hier optional eine
        // Liste; alte Backends (<= vor diesem Feature) lassen das Feld
        // weg → ``[]`` und Verhalten = exakt wie früher (nur Attribut).
        if (Array.isArray(data?.trusted_domains)) {
          this._backendTrustedDomains = data.trusted_domains
            .map((d: unknown) => this._normalizeDomain(String(d || '')))
            .filter((d: string) => d.length > 0);
          // Cache invalidieren, damit der Merge beim nächsten
          // ``_parsedTrustedDomains()``-Aufruf neu berechnet wird.
          this._trustedDomainsCache = null;
        }
      }
    } catch {
      // Backend nicht erreichbar — Toggle bleibt aus.
    }
    // Strip leading "www." and lowercase the host for matching, same
    // as the backend ``_normalize_host``.
    const h = this.guideHost.replace(/^www\./, '');
    const allowed = allowedHosts.some(p => this.hostMatchesPattern(h, p));
    this.guideModeAvailable.set(allowed);

    if (!allowed) {
      this.guideMode.set(false);
      this.api.setGuideEnv(false, this.guideHost);
      return;
    }

    // Stage A — URL-Param ?bgm=1/0 als Cross-TLD-Handoff. Wenn der User
    // gerade von einer anderen WLO-Domain via "Bring mich hin" hierher
    // navigiert wurde, hängt der Toggle-Wert in der URL. Nach dem Pickup
    // entfernen wir den Param wieder (kein Bookmark-Leak) und persistieren
    // in localStorage, sodass spätere Reloads den Wert behalten.
    let urlOverride: boolean | null = null;
    try {
      const url = new URL(window.location.href);
      const fromUrl = url.searchParams.get('bgm');
      if (fromUrl === '1') urlOverride = true;
      else if (fromUrl === '0') urlOverride = false;
      if (urlOverride !== null) {
        url.searchParams.delete('bgm');
        const cleaned = url.pathname
          + (url.searchParams.toString() ? '?' + url.searchParams.toString() : '')
          + url.hash;
        try { history.replaceState({}, '', cleaned); } catch { /* ignore */ }
        try {
          localStorage.setItem(
            WidgetComponent.GUIDE_LS_KEY, urlOverride ? '1' : '0',
          );
        } catch { /* ignore */ }
      }
    } catch { /* ignore — URL parse failures shouldn't block boot */ }

    // Stage B — localStorage (Origin-spezifisch). Wenn der User auf dieser
    // Origin schon mal getoggelt hat, gewinnt der Wert.
    let stored: string | null = null;
    try { stored = localStorage.getItem(WidgetComponent.GUIDE_LS_KEY); } catch { /* ignore */ }

    // Priorität:
    //   1. URL-Param ?bgm   (Cross-TLD-Handoff hat höchste Priorität)
    //   2. localStorage     (vom User selbst getoggelt)
    //   3. ``guide-mode-default``-Attribut (Embed-spezifischer Default)
    //   4. Backend-``default_enabled`` (globaler Default aus guide-mode.yaml)
    const attrDefault = this.guideModeDefaultTristate;
    let on: boolean;
    if (urlOverride !== null) on = urlOverride;
    else if (stored === '1') on = true;
    else if (stored === '0') on = false;
    else if (attrDefault !== null) on = attrDefault;
    else on = defaultEnabled;

    this.guideMode.set(on);
    // Push into ApiService so subsequent chat requests carry guide_mode
    // and host in the environment payload.
    this.api.setGuideEnv(on, this.guideHost);
  }

  /** Header-Toggle. Persists the new value in localStorage so it
   *  survives reloads and host-page navigation within the same domain. */
  toggleGuideMode(): void {
    const next = !this.guideMode();
    this.guideMode.set(next);
    this.api.setGuideEnv(next, this.guideHost);
    try {
      localStorage.setItem(WidgetComponent.GUIDE_LS_KEY, next ? '1' : '0');
    } catch { /* ignore */ }
  }

  /** Direct same-tab navigation to a card's guide URL.
   *
   *  Cross-Origin-Handoff: wenn das Ziel auf einer anderen Origin liegt
   *  als die aktuelle Host-Seite, hängen wir zwei URL-Parameter an:
   *  - ``bsid=<session-id>`` — damit der Bot-Verlauf auch auf der
   *    Zielseite weiterläuft (Cross-TLD-Session-Bridge, bestehender
   *    Mechanismus aus ``_maybeRewriteOutgoingLink``).
   *  - ``bgm=1/0`` — damit der Lotsen-Modus-Toggle auf der Zielseite
   *    aktiv bleibt; ohne dieses Flag wäre der Toggle-Wert in
   *    localStorage origin-isoliert und auf der neuen Domain weg.
   *
   *  Beide Parameter werden auf der Zielseite vom Widget gelesen,
   *  sofort aus der URL entfernt (kein Bookmark-Leak), und in den
   *  jeweiligen Persistenz-Layer (Cookie/localStorage) übernommen.
   */
  private navigateToGuideUrl(url: string): void {
    if (!url) return;
    let finalUrl = url;
    try {
      const target = new URL(url, window.location.href);
      // Nur Handoff bei echtem Origin-Wechsel — same-origin hat schon
      // Zugriff auf Cookie/localStorage und braucht keine URL-Params.
      if (target.origin !== window.location.origin) {
        const sid = this.chatRef?.sessionId;
        if (sid && /^bb-[0-9a-f-]{32,40}$/i.test(sid)
            && !target.searchParams.has('bsid')) {
          target.searchParams.set('bsid', sid);
        }
        // Toggle-State (1 = an, 0 = aus) — ``bgm`` für "boerdi guide mode".
        // Bewusst auch bei Toggle=aus mitgeschickt, damit ein User der
        // bewusst deaktiviert hat, auf der Zielseite nicht plötzlich
        // wieder den Default sieht.
        if (!target.searchParams.has('bgm')) {
          target.searchParams.set('bgm', this.guideMode() ? '1' : '0');
        }
        finalUrl = target.toString();
      }
    } catch {
      // Bei Parse-Fehler einfach Plain-URL nehmen (kein Cross-TLD-Bridge,
      // aber Navigation klappt trotzdem).
    }
    try {
      window.location.href = finalUrl;
    } catch {
      // Fallback for sandboxed iframes that block direct nav.
      window.open(finalUrl, '_self', 'noopener');
    }
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
