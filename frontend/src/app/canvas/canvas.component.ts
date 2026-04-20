import {
  Component, Input, Output, EventEmitter, computed, signal, HostListener,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { WloCard, PaginationInfo } from '../services/api.service';
import {
  getCardPrimaryUrl, isCollection, isContent, isPureCollection, isTopicPage,
} from '../services/card-utils';

export type CanvasViewMode = 'empty' | 'content' | 'cards' | 'preview';

/** Actions the canvas can trigger on a card. The WidgetComponent forwards
 *  these to the underlying ChatComponent methods so behaviour matches the
 *  in-chat card actions exactly.
 */
export type CanvasCardAction = 'browse' | 'learning_path' | 'remix' | 'open' | 'preview';

/**
 * BadBoerdi Canvas — ausklappbare Arbeitsfläche neben dem Chat.
 *
 * Drei Betriebsmodi:
 *  - 'empty'   → Empty-State mit Hinweis ("Erstelle ...", "Zeig mir ...")
 *  - 'content' → rendert Markdown (via marked + DOMPurify) + Print/Download
 *  - 'cards'   → zeigt WLO-Kacheln als Grid
 */
@Component({
  selector: 'badboerdi-canvas',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './canvas.component.html',
  styleUrls: ['./canvas.component.scss'],
})
export class CanvasComponent {
  @Input() set markdown(value: string) {
    this._markdown.set(value || '');
  }
  get markdown(): string { return this._markdown(); }

  @Input() title = '';
  @Input() materialTypeLabel = '';
  /** 'analytisch' (für Politik/Verwaltung/Presse/Beratung) oder 'didaktisch'. */
  @Input() materialTypeCategory: 'analytisch' | 'didaktisch' | null = null;
  @Input() cards: WloCard[] = [];
  @Input() viewMode: CanvasViewMode = 'empty';
  @Input() query = '';
  /** Whether both panes (material + cards) have content — show tab switch. */
  @Input() showTabs = false;
  /** Card shown in preview mode (when viewMode === 'preview'). */
  @Input() previewCard: WloCard | null = null;
  /** Whether the canvas has a "back" target in its navigation history. */
  @Input() canGoBack = false;
  /** Pagination info for card lists (from Backend). */
  @Input() pagination: PaginationInfo | null = null;
  /** How many cards of `cards[]` to actually render (client-side paging). */
  @Input() visibleCount = 5;
  /** Disable the load-more button while a server fetch is in flight. */
  @Input() loadingMore = false;

  @Output() closeCanvas = new EventEmitter<void>();
  @Output() cardAction = new EventEmitter<{ action: CanvasCardAction; card: WloCard }>();
  @Output() switchView = new EventEmitter<'material' | 'cards'>();
  @Output() goBack = new EventEmitter<void>();
  @Output() showMore = new EventEmitter<void>();
  @Output() loadMore = new EventEmitter<void>();

  private _markdown = signal<string>('');

  renderedHtml = computed<SafeHtml>(() => {
    const md = this._markdown();
    if (!md) return this.sanitizer.bypassSecurityTrustHtml('');
    const html = marked.parse(md, { async: false, gfm: true, breaks: true }) as string;
    const clean = DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'rel'] });
    return this.sanitizer.bypassSecurityTrustHtml(clean);
  });

  constructor(private sanitizer: DomSanitizer) {}

  onClose(): void {
    this.closeCanvas.emit();
  }

  onSwitchView(view: 'material' | 'cards'): void {
    this.switchView.emit(view);
  }

  onGoBack(): void {
    this.goBack.emit();
  }

  get visibleCards(): WloCard[] {
    // Sorted: topic pages first, then pure collections, then content items.
    // Inside each group the original order is preserved.
    const all = this.cards || [];
    const sorted = [
      ...all.filter(isTopicPage),
      ...all.filter(isPureCollection),
      ...all.filter(isContent),
    ];
    return sorted.slice(0, this.visibleCount);
  }

  /** Themenseiten-slice (collections that expose topic-page variants). */
  get visibleTopicPageCards(): WloCard[] {
    return this.visibleCards.filter(isTopicPage);
  }

  /** Plain-Sammlung-slice (collections WITHOUT topic-page variants). */
  get visiblePureCollectionCards(): WloCard[] {
    return this.visibleCards.filter(isPureCollection);
  }

  /** Content-slice of the currently visible cards. */
  get visibleContentCards(): WloCard[] {
    return this.visibleCards.filter(isContent);
  }

  /** Back-compat alias: old template sections that used all collections. */
  get visibleCollectionCards(): WloCard[] {
    return this.visibleCards.filter(isCollection);
  }

  /** Currently selected variant-ID per topic-page card (keyed by node_id).
   *  First variant (persona-preferred, backend-sorted) is the default. */
  selectedVariantId: Record<string, string> = {};

  /** Which topic-page card has its variant-dropdown menu open. */
  openVariantMenuId: string | null = null;

  /** Resolve the selected variant for a topic-page card (defaults to first). */
  selectedVariant(card: WloCard): { url: string; target_group: string; label: string; variant_id: string } | null {
    const tps = card?.topic_pages || [];
    if (!tps.length) return null;
    const vid = this.selectedVariantId[card.node_id];
    if (vid) {
      const hit = tps.find(v => v.variant_id === vid);
      if (hit) return hit;
    }
    return tps[0];
  }

  onVariantChange(card: WloCard, ev: Event): void {
    const sel = (ev.target as HTMLSelectElement)?.value;
    if (sel) this.selectedVariantId = { ...this.selectedVariantId, [card.node_id]: sel };
  }

  /** Pick a variant from the dropdown menu and open its URL in a new tab. */
  onPickVariant(card: WloCard, variantId: string, ev: Event): void {
    ev.preventDefault();
    ev.stopPropagation();
    this.selectedVariantId = { ...this.selectedVariantId, [card.node_id]: variantId };
    this.openVariantMenuId = null;
    const v = card.topic_pages?.find(t => t.variant_id === variantId);
    if (v?.url) window.open(v.url, '_blank', 'noopener,noreferrer');
  }

  toggleVariantMenu(card: WloCard, ev: Event): void {
    ev.preventDefault();
    ev.stopPropagation();
    this.openVariantMenuId = this.openVariantMenuId === card.node_id ? null : card.node_id;
  }

  closeVariantMenu(): void {
    this.openVariantMenuId = null;
  }

  /** Close the variant dropdown when clicking outside of it. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(ev: MouseEvent): void {
    if (!this.openVariantMenuId) return;
    const target = ev.target as HTMLElement | null;
    if (!target?.closest('.card-btn-split')) {
      this.openVariantMenuId = null;
    }
  }

  /** Escape-key closes the variant menu. */
  @HostListener('document:keydown.escape')
  onEscape(): void { this.openVariantMenuId = null; }

  /** URL for the topic-page card (uses currently selected variant). */
  topicPageUrl(card: WloCard): string {
    return this.selectedVariant(card)?.url || getCardPrimaryUrl(card);
  }

  get hasHiddenCards(): boolean {
    return (this.cards?.length || 0) > this.visibleCount;
  }

  /** Typ-aware link resolver — used by the template. */
  cardUrl(card: WloCard | null | undefined): string {
    return getCardPrimaryUrl(card);
  }

  onShowMore(): void { this.showMore.emit(); }
  onLoadMore(): void { this.loadMore.emit(); }

  onCardAction(action: CanvasCardAction, card: WloCard, ev?: Event): void {
    // Prevent the wrapping <a class="wlo-card"> from navigating when a
    // nested button is clicked.
    ev?.preventDefault();
    ev?.stopPropagation();
    this.cardAction.emit({ action, card });
  }

  trackByNodeId(_index: number, c: WloCard): string {
    return c?.node_id || String(_index);
  }

  onPrint(): void {
    const md = this._markdown();
    if (!md) return;
    // NOTE: do NOT use 'noopener' here — Chrome returns null from
    // window.open() when either noopener or noreferrer is set, which
    // breaks our document.write / print calls. The new window is
    // blank (no untrusted opener context), so omitting it is safe.
    const w = window.open('', '_blank', 'width=900,height=1200');
    if (!w) {
      alert('Bitte erlaube Popups fuer den Druck.');
      return;
    }
    const html = marked.parse(md, { async: false, gfm: true, breaks: true }) as string;
    const clean = DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'rel'] });
    const title = this.escapeHtml(this.title || 'BadBoerdi Canvas');
    const typeBadge = this.materialTypeLabel ? ` &middot; ${this.escapeHtml(this.materialTypeLabel)}` : '';
    const today = new Date().toLocaleDateString('de-DE', {
      year: 'numeric', month: 'long', day: 'numeric',
    });

    w.document.write(`<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>${title} &ndash; BadBoerdi</title>
<style>
  @media print { body { margin: 15mm; } .no-print { display: none; } }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 210mm; margin: 20mm auto; padding: 0 12mm; line-height: 1.55; color: #1a1a1a; }
  h1 { font-size: 1.7em; color: #1c4587; border-bottom: 2px solid #1c4587; padding-bottom: 0.25em; }
  h2 { font-size: 1.25em; color: #1c4587; margin-top: 1.5em; }
  h3 { font-size: 1.05em; color: #374151; }
  blockquote { border-left: 4px solid #bfdbfe; margin: 1em 0; padding: 0.4em 1em;
               background: #eff6ff; color: #1e3a8a; border-radius: 4px; }
  ul, ol { margin: 0.5em 0 0.5em 1.5em; }
  li { margin: 0.25em 0; }
  code { background: #f3f4f6; padding: 0.1em 0.35em; border-radius: 3px;
         font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 0.92em; }
  pre { background: #f3f4f6; padding: 0.8em 1em; border-radius: 6px; overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #d1d5db; padding: 0.5em 0.8em; text-align: left; }
  th { background: #f9fafb; font-weight: 600; }
  hr { border: 0; border-top: 1px solid #e5e7eb; margin: 2em 0; }
  .meta { font-size: 0.85em; color: #6b7280; margin-top: 2em;
          border-top: 1px solid #e5e7eb; padding-top: 0.8em; }
  .meta strong { color: #1c4587; }
</style>
</head>
<body>
${clean}
<div class="meta"><strong>BOERDi</strong> &middot; Erstellt am ${today}${typeBadge}</div>
</body>
</html>`);
    w.document.close();
    setTimeout(() => {
      try { w.focus(); w.print(); } catch { /* ignore */ }
    }, 300);
  }

  onDownload(): void {
    const md = this._markdown();
    if (!md) return;
    const safeName = (this.title || 'canvas')
      .replace(/[^\w.\-äöüÄÖÜß ]+/g, '')
      .replace(/\s+/g, '_')
      .slice(0, 80) || 'canvas';
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${safeName}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  private escapeHtml(s: string): string {
    return (s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c] as string));
  }
}
