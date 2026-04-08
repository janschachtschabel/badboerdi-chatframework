import { Component, Input, ViewChild, ElementRef, OnInit, AfterViewInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChatComponent } from '../chat/chat.component';

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
 */
@Component({
  selector: 'boerdi-chat-widget',
  standalone: true,
  imports: [CommonModule, ChatComponent],
  template: `
    <div class="boerdi-widget"
         [class.expanded]="expanded"
         [attr.data-position]="position"
         [style.--boerdi-primary]="primaryColor">

      <!-- Chat panel -->
      <div class="boerdi-panel" *ngIf="expanded">
        <div class="boerdi-panel-header">
          <span class="boerdi-title">
            <span class="boerdi-owl-mini">🦉</span> BOERDi
          </span>
          <button class="boerdi-close" (click)="toggle()" aria-label="Schließen">×</button>
        </div>
        <div class="boerdi-panel-body">
          <badboerdi-chat
            #chat
            [apiUrl]="apiUrl"
            [pageContext]="resolvedPageContext"
            [persistSession]="persistSession"
            [sessionKey]="sessionKey"
            [greeting]="greeting">
          </badboerdi-chat>
        </div>
      </div>

      <!-- Floating button (always rendered, hidden via CSS when expanded) -->
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

    /* ── Floating Action Button ────────────────────────────── */
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

    /* ── Chat Panel ───────────────────────────────────────── */
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
    }
    @keyframes boerdi-slidein {
      from { opacity: 0; transform: translateY(20px) scale(0.95); }
      to   { opacity: 1; transform: translateY(0)    scale(1); }
    }
    .boerdi-panel-header {
      background: var(--boerdi-primary);
      color: #fff;
      padding: 12px 16px;
      display: flex; align-items: center; justify-content: space-between;
      flex-shrink: 0;
    }
    .boerdi-title { font-weight: 600; font-size: 15px; }
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
    .boerdi-panel-body {
      flex: 1;
      overflow: hidden;
      display: flex;
    }
    .boerdi-panel-body badboerdi-chat {
      flex: 1;
      display: block;
      min-height: 0;
    }

    /* Mobile: full-screen overlay */
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
export class WidgetComponent implements OnInit, AfterViewInit {
  @ViewChild('chat') chatRef!: ElementRef;

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

  private readonly OPEN_KEY = 'boerdi_widget_open';
  private readonly OPEN_TTL_MS = 30 * 60 * 1000; // 30 min

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

  ngAfterViewInit() { /* no-op */ }

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
}
