import {
  Component, Input, Output, EventEmitter, ViewChild, ElementRef, OnInit, AfterViewInit, OnDestroy, OnChanges, SimpleChanges,
  NgZone, signal, ChangeDetectorRef, HostBinding,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatComponent } from '../chat/chat.component';
import { detectPageContext } from './page-context-detector';
import { ApiService } from '../services/api.service';
import { BOERDI_LOGO_DATA_URL } from '../shared/boerdi-logo';
import { ICONS } from '../shared/icons';
import { SafeSvgPipe } from '../shared/safe-svg.pipe';

/** Optionaler Kopfzeilen-Nav-Button (aus 01-base/header-nav.yaml, vom Backend
 *  über /api/config/guide-mode → ``header_nav`` geliefert). */
interface HeaderNavButton {
  id: string;
  label: string;
  icon: string;
  url: string;
  new_tab: boolean;
}

/**
 * BoerdiChatWidget — Floating Action Button + expandable chat panel.
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
 * Panel-Layout: 420×820 (Chat einspaltig), responsive bis Vollbild auf Mobile.
 */
@Component({
  selector: 'boerdi-chat-widget',
  standalone: true,
  imports: [CommonModule, ChatComponent, SafeSvgPipe],
  template: `
    <div class="boerdi-widget"
         [class.expanded]="expanded"
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
            <!-- Boerdi-Kopf = klickbarer Web-Tour-Starter. Hover/Focus:
                 Kopf wackelt + Sprechblase. aria-label + Button (Tastatur)
                 als a11y-Fallback. startTour() ist no-op solange er lädt. -->
            <button type="button" class="boerdi-owl-tour"
                    [class.is-hinting]="hintActive()"
                    (click)="chatRef?.startTour()"
                    aria-label="Web-Tour starten">
              <img class="boerdi-owl-mini"
                   [class.is-thinking]="chatRef?.isLoading"
                   [class.is-speaking]="chatRef?.autoSpeak && chatRef?.isSpeaking"
                   [src]="boerdiLogo" alt="" />
              <span class="boerdi-owl-bubble" aria-hidden="true">Klick mich — ich zeig dir die Seite</span>
            </button>
            <div class="boerdi-title-text">
              <span class="boerdi-title">BOERDi</span>
              <span class="boerdi-status" *ngIf="chatRef?.isLoading">denkt nach …</span>
              <span class="boerdi-status" *ngIf="!chatRef?.isLoading && chatRef?.autoSpeak && chatRef?.isSpeaking">spricht …</span>
            </div>
          </div>

          <!-- Welle E (2026-05-23): Mobile-Tab-Switch entfällt — Canvas-Pane
               wurde entfernt, Material/Lernpfade landen als gerahmte
               InlineDocument-Box direkt im Chat-Verlauf. -->

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
            <!-- Welle E (2026-05-23): Lotsen-Toggle dauerhaft entfernt.
                 Lotsen-Modus ist immer aktiv — der Bot leitet auf
                 Repo-/Themenseiten-Links statt externer URLs. -->
            <!-- Optionale Kopfzeilen-Nav-Buttons (Studio: header-nav.yaml),
                 links vom Neustart-Button, gleiches outlined-neutrales Design.
                 ?bsid= wird in headerNavHref dynamisch an Trusted-Links gehängt. -->
            <a *ngFor="let b of headerNavButtons()"
               class="boerdi-action-btn boerdi-action-btn--neutral"
               [href]="headerNavHref(b)"
               [attr.target]="b.new_tab ? '_blank' : null"
               [attr.rel]="b.new_tab ? 'noopener noreferrer' : null"
               [title]="b.label"
               [attr.aria-label]="b.label">
              <span class="boerdi-icon" [innerHTML]="headerNavIcon(b) | safeSvg"></span>
            </a>
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
          <!-- Welle E (2026-05-23): Canvas-Pane entfernt. Lernpfade /
               KI-Materialien werden als gerahmte InlineDocument-Box
               direkt im Chat-Verlauf gerendert. -->
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
              [trustedHosts]="parsedTrustedHostList"
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

    /* ── Owl als Web-Tour-Starter ──────────────────────────────
       Der Kopf oben links ist ein Button → startet die Web-Tour.
       Hover/Focus: Kopf wackelt (nur wenn er nicht gerade denkt/spricht)
       + eine Sprechblase erscheint darunter. Tooltip + Tastatur kommen
       vom nativen <button>. */
    .boerdi-owl-tour {
      background: transparent;
      border: 0;
      padding: 0;
      margin: 0;
      cursor: pointer;
      position: relative;
      display: inline-flex;
      line-height: 0;
      flex-shrink: 0;
      border-radius: 50%;
    }
    .boerdi-owl-tour:focus-visible {
      outline: 2px solid #ffffff;
      outline-offset: 2px;
    }
    .boerdi-owl-tour:hover .boerdi-owl-mini:not(.is-thinking):not(.is-speaking) {
      animation: boerdi-wiggle 0.6s ease-in-out;
    }
    @keyframes boerdi-wiggle {
      0%, 100% { transform: rotate(0deg); }
      20% { transform: rotate(-9deg) scale(1.06); }
      45% { transform: rotate(7deg); }
      70% { transform: rotate(-4deg); }
    }
    .boerdi-owl-bubble {
      position: absolute;
      top: calc(100% + 8px);
      left: 0;
      background: #ffffff;
      color: #1e293b;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
      box-shadow: 0 6px 18px rgba(0,0,0,0.22);
      opacity: 0;
      transform: translateY(-4px);
      pointer-events: none;
      transition: opacity .15s ease, transform .15s ease;
      z-index: 20;
    }
    .boerdi-owl-bubble::before {
      content: '';
      position: absolute;
      bottom: 100%;
      left: 14px;
      border: 6px solid transparent;
      border-bottom-color: #ffffff;
    }
    .boerdi-owl-tour:hover .boerdi-owl-bubble,
    .boerdi-owl-tour:focus-visible .boerdi-owl-bubble {
      opacity: 1;
      transform: translateY(0);
    }
    /* Einmaliger Auto-Hinweis beim ersten Öffnen (is-hinting): Kopf wackelt +
       Sprechblase sichtbar; nach 3s entfernt JS die Klasse → Bubble blendet aus. */
    .boerdi-owl-tour.is-hinting .boerdi-owl-mini:not(.is-thinking):not(.is-speaking) {
      animation: boerdi-wiggle 0.6s ease-in-out 2;
    }
    .boerdi-owl-tour.is-hinting .boerdi-owl-bubble {
      opacity: 1;
      transform: translateY(0);
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
      text-decoration: none;
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

    /* ── Body (Chat) ───────────────────────── */
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
    @media (max-width: 480px) {
      .boerdi-panel {
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
  /** Show the 🔍 debug-toggle button in the chat header. Default true. */
  @Input() showDebugButton: boolean | string = true;
  /** Show the 🔊 TTS and 🎤 mic buttons. Default true. */
  @Input() showLanguageButtons: boolean | string = true;

  // ── Widget-Embed-Modi (Welle E, 2026-05-23 — reduziert) ─────────
  // Frühere Modi (cards-enabled, canvas-enabled, inline-result-grouping,
  // quick-replies-enabled, show-guide-button, guide-mode-default) sind
  // ersatzlos entfernt. Layout-Steuerung liegt jetzt zentral im Studio
  // (display-rules.yaml, Tab „🎨 Anzeige"). Lotsen-Modus ist immer aktiv.
  // Canvas-Pane existiert nicht mehr — KI-Material/Lernpfade landen als
  // gerahmte InlineDocument-Box direkt im Chat-Verlauf.
  //
  // 2026-06-10: auch das letzte Embed-Flag ``ai-content-enabled`` wurde
  // entfernt — KI-generierte Inhalte sind immer zugelassen. Ein von Alt-
  // Embeds noch gesendetes HTML-Attribut wird schlicht ignoriert
  // (unbekannte Attribute sind bei Custom Elements wirkungslos).
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

  // ── Lotsen-Modus ────────────────────────────────────────────────
  // Welle E (2026-05-23): Lotsen-Toggle dauerhaft entfernt. Modus ist
  // immer aktiv — Backend leitet Card-Links auf Repo-Render-Targets.
  // Die alten Inputs ``show-guide-button`` und ``guide-mode-default``
  // existieren nicht mehr; Hosts können den Modus nicht mehr pro Embed
  // deaktivieren (war redundant zur Allow-List-Logik im Backend).

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

  // ── Webseiten-Guide-Modus (Lotsen-Modus, Welle E) ──────────────
  // Toggle ist entfernt — Lotsen-Modus ist immer aktiv. Der host-allow-
  // list-Check bleibt im Backend als Sicherheitsnetz: auf nicht-allow-
  // listed Hosts fällt das Backend automatisch auf externe URLs zurück.
  // ``guideMode`` als Signal-Compatibility-Hülle: einige Pfade lesen es
  // (Cross-TLD-Handoff in maybeRewriteOutgoingLink), wir setzen es einmal
  // beim Bootstrap und lassen es konstant.
  guideMode = signal(true);
  guideModeAvailable = signal(true);
  /** Hostname snapshot we send to the backend so it knows whether to
   *  attach ``guide_url`` to outgoing cards. Filled at init. */
  private guideHost = '';
  private static readonly GUIDE_LS_KEY = 'boerdi.guide_mode';
  /** Bot-initiated navigation target — set when the backend sends a
   *  ``page_action: navigate`` payload. The widget shows a banner with
   *  "Bring mich hin" / "Hier bleiben"; the user must explicitly confirm
   *  before we leave the host page. ``null`` hides the banner. */
  guideNavTarget = signal<{ url: string; label: string } | null>(null);

  /** Optionale Kopfzeilen-Nav-Buttons (Home/Fachportale/Suche). Quelle:
   *  Backend ``/api/config/guide-mode`` → ``header_nav`` (Studio-pflegbar via
   *  01-base/header-nav.yaml). Leer = keine Buttons. */
  headerNavButtons = signal<HeaderNavButton[]>([]);

  /** Einmaliger „Hallo"-Hinweis am Owl-Kopf beim ersten Öffnen pro Session:
   *  Kopf wackelt + Sprechblase erscheinen automatisch, nach 3s wieder weg.
   *  Danach reagiert der Kopf nur noch auf Maus-Over. */
  hintActive = signal(false);
  private _owlHintDone = false;
  private _owlHintTries = 0;
  private static readonly OWL_HINT_KEY = 'boerdi_owl_hint_session';

  // Auto-Open-Policy (Welle E): Das Widget öffnet sich von selbst NUR bei
  // ``?bsid=`` (Cross-TLD-/Tour-Handoff) ODER laufender Web-Tour
  // (localStorage ``boerdi_tour_active``). Die frühere generische Same-Tab-
  // Persistenz (öffnete bei JEDER Same-Tab-Navigation erneut) ist bewusst
  // entfernt — ohne bsid und ohne aktive Tour bleibt das Widget bei einer
  // Seiten-Navigation geschlossen. Siehe ngOnInit.

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

    // Auto-Open NUR bei aktiver Web-Tour (localStorage-Flag von der
    // ChatComponent, überlebt den WP-Full-Page-Reload). Die Tour navigiert
    // same-origin (kein ?bsid=) und würde sonst auf jeder Tour-Seite
    // zuklappen. Ohne bsid UND ohne aktive Tour bleibt das Widget zu.
    try {
      if (localStorage.getItem('boerdi_tour_active') === '1') {
        this.expanded = true;
      }
    } catch { /* ignore */ }

    // Lazy-Mount-Flag setzen, nachdem ALLE Open-Entscheidungen
    // (initialState, bsid, aktive Tour) ausgewertet wurden. Wenn das
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
    // Mark this session as widget-driven so the backend treats it as an
    // embedded widget regardless of env.page (important for dev on localhost:4200,
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
    // Panel beim Boot schon offen (initial-state / ?bsid= / aktive Tour)?
    // → einmaligen Owl-Hinweis anstoßen (wartet intern auf chatRef.sessionId).
    if (this.everExpanded) this._maybeShowOwlHint();
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
      // Erstes Öffnen pro Session → einmaliger Owl-Hinweis.
      this._maybeShowOwlHint();
      try {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try { this.chatRef?.scrollToLatest?.(); } catch { /* ignore */ }
          });
        });
      } catch { /* ignore */ }
    }
  }

  /** Einmaliger Owl-Hinweis beim ersten Öffnen einer Session: Kopf wackelt +
   *  Sprechblase 3s, dann weg. Pro Session genau einmal — das localStorage-Flag
   *  ist an die sessionId gekoppelt: „Neuer Chat" (neue sessionId) hintet
   *  erneut, Reopen/Reload/Seitenwechsel derselben Session nicht. */
  private _maybeShowOwlHint(): void {
    if (this._owlHintDone) return;
    const sid = this.chatRef?.sessionId;
    if (!sid) {
      // chatRef/sessionId noch nicht bereit → kurz später erneut (max ~4s).
      if (this._owlHintTries++ < 20) setTimeout(() => this._maybeShowOwlHint(), 200);
      return;
    }
    this._owlHintDone = true;
    let last = '';
    try { last = localStorage.getItem(WidgetComponent.OWL_HINT_KEY) || ''; } catch { /* ignore */ }
    if (last === sid) return;  // diese Session schon gehinted
    try { localStorage.setItem(WidgetComponent.OWL_HINT_KEY, sid); } catch { /* ignore */ }
    this.zone.run(() => {
      this.hintActive.set(true);
      setTimeout(() => this.zone.run(() => this.hintActive.set(false)), 3000);
    });
  }

  /**
   * Handle backend page_actions. The widget only consumes ``navigate``
   * (Lotsen-Banner); all other actions are dispatched by the chat
   * component as CustomEvents on `window` for host-page integration.
   */
  handlePageAction(pa: { action: string; payload: any }) {
    if (!pa || !pa.action) return;
    switch (pa.action) {
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
  /** Welle E (2026-05-23): Lotsen-Toggle entfernt. Beim Boot holen wir
   *  trotzdem die Backend-Konfig (trusted_domains für Cross-TLD-Brücke),
   *  setzen aber ``guideMode`` immer auf ``true`` — Lotsen ist Standard.
   *  Auf nicht-allow-listed Hosts ignoriert das Backend den Lotsen-Modus
   *  ohnehin (Sicherheitsnetz in card_pipeline.build_card_link). */
  private async initGuideMode(): Promise<void> {
    try {
      const apiBase = (this.apiUrl || '').replace(/\/+$/, '');
      const resp = await fetch(`${apiBase}/api/config/guide-mode`);
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data?.trusted_domains)) {
          this._backendTrustedDomains = data.trusted_domains
            .map((d: unknown) => this._normalizeDomain(String(d || '')))
            .filter((d: string) => d.length > 0);
          this._trustedDomainsCache = null;
        }
        // Optionale Kopfzeilen-Nav-Buttons (Studio: header-nav.yaml).
        if (Array.isArray(data?.header_nav)) {
          this.headerNavButtons.set(
            data.header_nav
              .filter((b: any) => b && b.url)
              .map((b: any) => ({
                id: String(b.id || ''),
                label: String(b.label || ''),
                icon: String(b.icon || 'explore'),
                url: String(b.url),
                new_tab: !!b.new_tab,
              })),
          );
        }
      }
    } catch {
      // Backend nicht erreichbar — kein Show-Stopper, nur die Cross-TLD-
      // Brücke arbeitet dann ohne Backend-Trusted-Domains.
    }
    this.guideMode.set(true);
    this.guideModeAvailable.set(true);
    this.api.setGuideEnv(true, this.guideHost);
    // Die Trusted-Domains kamen async an — evtl. NACHDEM die ChatComponent
    // ihr ``[trustedHosts]``-Input initial (leer) gelesen hat. CD anstoßen,
    // damit ``parsedTrustedHostList`` neu ausgewertet und durchgereicht wird;
    // sonst bliebe externalLinkWarning auf der leeren Liste hängen und würde
    // „Achtung! Externe URL." auch für Whitelist-Hosts zeigen.
    try { this.cdr?.markForCheck?.(); } catch { /* ignore */ }
  }

  /** Icon-SVG für einen Kopfzeilen-Nav-Button (Name → shared/icons.ts).
   *  Unbekannter Name → Fallback ``explore``. */
  headerNavIcon(b: HeaderNavButton): string {
    const set = ICONS as Record<string, string>;
    return set[b?.icon] || set['explore'] || '';
  }

  /** Ziel-URL eines Kopfzeilen-Nav-Buttons mit dynamisch angehängter bsid.
   *  Für Trusted-WLO-Hosts (auch same-origin) wird ``?bsid=<sid>`` ergänzt,
   *  damit die Chat-Session auf der Zielseite weiterläuft (sofern das Widget
   *  dort eingebettet ist). Die bsid wird dort beim Laden wieder aus der URL
   *  gestrippt. Untrusted/externe Hosts bleiben unverändert (kein Leak). */
  headerNavHref(b: HeaderNavButton): string {
    const url = (b?.url || '').trim();
    if (!url) return '#';
    const sid = this.chatRef?.sessionId || '';
    if (!/^bb-[0-9a-f-]{32,40}$/i.test(sid)) return url;
    try {
      const u = new URL(url, window.location.href);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return url;
      if (!this._isTrustedHost(u.hostname.toLowerCase())) return url;
      if (!u.searchParams.has('bsid')) u.searchParams.set('bsid', sid);
      return u.toString();
    } catch {
      return url;
    }
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

}
