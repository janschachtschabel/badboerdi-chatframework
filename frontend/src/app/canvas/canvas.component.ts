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
    const next = value || '';
    // If this value comes from outside (i.e. bot-generated content replacing
    // the previous doc), accept it as the current bot-snapshot. User-edits
    // go through saveEdit() which calls _markdown.set() directly — bypassing
    // this setter — so the snapshot stays aligned with the last bot version.
    if (next !== this._markdown()) {
      this._markdown.set(next);
      this._botSnapshot = next;
      // Cancel any pending edit if the bot pushed a new doc underneath us
      if (this.editMode()) {
        this.editMode.set(false);
      }
    }
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
  /** User hat den Canvas-Markdown manuell editiert und gespeichert. Das Widget
   *  fängt das Event ab und propagiert den neuen Text zurück in das
   *  `markdown`-Signal, damit der nächste Chat-Edit auf der neuen Version aufsetzt. */
  @Output() markdownEdited = new EventEmitter<string>();

  private _markdown = signal<string>('');

  /** Edit-Mode: zeigt eine Textarea anstelle der gerenderten Markdown-Ansicht. */
  editMode = signal<boolean>(false);
  /** Lokaler Draft während des Editierens. Wird beim Speichern nach _markdown gepusht. */
  editDraft = signal<string>('');
  /** Letzte bot-generierte Version — für den Undo-Button. Null = User hat noch nichts verändert. */
  private _botSnapshot: string | null = null;

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

  /** Toggle between rendered view and editable textarea. */
  onToggleEdit(): void {
    if (this.editMode()) {
      // Ignore — Save/Cancel buttons handle exit
      return;
    }
    this.editDraft.set(this._markdown());
    this.editMode.set(true);
  }

  onEditInput(ev: Event): void {
    const ta = ev.target as HTMLTextAreaElement | null;
    this.editDraft.set(ta?.value ?? '');
  }

  onSaveEdit(): void {
    const next = this.editDraft();
    this._markdown.set(next);
    this.editMode.set(false);
    // Bot-Snapshot is preserved unchanged — it represents the last bot
    // version, not the user's working copy. That way "Restore" always
    // returns to the last bot output, not the user's previous edit.
    this.markdownEdited.emit(next);
  }

  onCancelEdit(): void {
    this.editDraft.set('');
    this.editMode.set(false);
  }

  /** Revert to the last bot-generated version (pre-user-edit). */
  onRestoreBotVersion(): void {
    if (this._botSnapshot == null) return;
    if (this._botSnapshot === this._markdown()) return;
    if (!confirm('Deine Änderungen verwerfen und zur Bot-Version zurückkehren?')) return;
    this._markdown.set(this._botSnapshot);
    this.editMode.set(false);
    this.markdownEdited.emit(this._botSnapshot);
  }

  /** True if the user has edited the canvas and a bot-version exists to restore. */
  get userEditedSinceBot(): boolean {
    return this._botSnapshot != null && this._botSnapshot !== this._markdown();
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

  /** DEBUG: Print variant data when dropdown opens. Hilft beim Diagnostizieren
   *  warum Labels gleich aussehen. Kann später entfernt werden. */
  private _debugVariants(card: WloCard): void {
    if (!card?.topic_pages?.length) return;
    // eslint-disable-next-line no-console
    console.log('[canvas] Variants for', card.title, '→', card.topic_pages.map(v => ({
      label: v.label,
      target_group: v.target_group,
      variant_id: v.variant_id,
      url: v.url,
      computed_label: this.variantLabel(card, v),
    })));
  }

  toggleVariantMenu(card: WloCard, ev: Event): void {
    ev.preventDefault();
    ev.stopPropagation();
    const willOpen = this.openVariantMenuId !== card.node_id;
    this.openVariantMenuId = willOpen ? card.node_id : null;
    if (willOpen) this._debugVariants(card);
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

  /** Map target-group code → human label (frontend-side fallback, mirrors
   *  backend's _tp_label()). Keeps the dropdown readable even when the
   *  MCP response only carries a generic "Themenseite" label.
   */
  private static readonly _TG_LABELS: Record<string, string> = {
    teacher: 'Lehrkräfte',
    learner: 'Lernende',
    general: 'Allgemein',
    parent: 'Eltern',
    pupil: 'Lernende',
    student: 'Lernende',
  };

  /** Wenn die Redaktion keine Zielgruppe (`targetGroup`) gepflegt hat,
   *  liefert die MCP "nicht gesetzt" und wir müssen die Varianten anhand
   *  ihrer URL unterscheidbar machen. Mapping deutscher URL-Slug-Tokens
   *  auf Anzeige-Labels — wenn ein Slug-Segment einem dieser Schlüssel
   *  entspricht, nehmen wir die längere Bezeichnung. */
  private static readonly _SLUG_LABELS: Record<string, string> = {
    'lehrer': 'Lehrkräfte',
    'lehrkraft': 'Lehrkräfte',
    'lehrkraefte': 'Lehrkräfte',
    'lehrer-in': 'Lehrkräfte',
    'lehrerinnen': 'Lehrkräfte',
    'lk': 'Lehrkräfte',
    'schueler': 'Schüler:innen',
    'schueler-in': 'Schüler:innen',
    'schuelerinnen': 'Schüler:innen',
    'lernende': 'Lernende',
    'lerner': 'Lernende',
    'sus': 'Schüler:innen',
    'eltern': 'Eltern',
    'family': 'Eltern',
    'familie': 'Eltern',
    'allgemein': 'Allgemein',
    'general': 'Allgemein',
    // Bildungsstufen — auch valider Diskriminator
    'grundschule': 'Grundschule',
    'primarstufe': 'Grundschule',
    'sek1': 'Sek I',
    'sek-1': 'Sek I',
    'sek-i': 'Sek I',
    'sek2': 'Sek II',
    'sek-2': 'Sek II',
    'sek-ii': 'Sek II',
    'sekundarstufe-i': 'Sek I',
    'sekundarstufe-ii': 'Sek II',
    'berufsbildung': 'Berufliche Bildung',
    'beruflich': 'Berufliche Bildung',
    'hochschule': 'Hochschule',
    'erwachsenenbildung': 'Erwachsene',
    'erwachsene': 'Erwachsene',
    'kita': 'Elementar',
    'elementar': 'Elementar',
  };

  /** Versuche aus URL-Pfaden ein sprechendes Label zu extrahieren — der
   *  letzte Pfad-Bestandteil enthält oft Stufe/Zielgruppe als Slug-Token.
   *  Beispiele:
   *    /themenseite/mathematik-grundschule  → "Grundschule"
   *    /themenseite/mathe-sek1             → "Sek I"
   *    /themenseite/mathe                  → null (kein Diskriminator)
   *    /themenseite/mathematik-lehrer      → "Lehrkräfte"
   */
  private static _labelFromUrl(url: string, collectionTitle: string): string | null {
    if (!url) return null;
    let path: string;
    try {
      path = new URL(url).pathname.toLowerCase();
    } catch { return null; }
    // Last non-empty path segment
    const segments = path.split('/').filter(Boolean);
    if (segments.length === 0) return null;
    const slug = segments[segments.length - 1].replace(/\.[a-z]+$/, '');

    // Strip the collection-name prefix from the slug if present, so
    // "mathematik-grundschule" reduces to "grundschule".
    const titleSlug = (collectionTitle || '')
      .toLowerCase()
      .replace(/[äöüß]/g, c => ({ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss'}[c] || c))
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '');
    let remainder = slug;
    if (titleSlug && remainder.startsWith(titleSlug)) {
      remainder = remainder.substring(titleSlug.length).replace(/^-+/, '');
    }
    if (!remainder) return null;

    // Direct lookup
    if (CanvasComponent._SLUG_LABELS[remainder]) {
      return CanvasComponent._SLUG_LABELS[remainder];
    }
    // Try splitting on "-" and look up each token
    for (const tok of remainder.split('-')) {
      if (CanvasComponent._SLUG_LABELS[tok]) {
        return CanvasComponent._SLUG_LABELS[tok];
      }
    }
    // Fallback: humanize remainder ("klassen-3-4" → "Klassen 3 4")
    if (remainder.length <= 30) {
      return remainder
        .split('-')
        .map(t => t.charAt(0).toUpperCase() + t.slice(1))
        .join(' ');
    }
    return null;
  }

  /** Pick the most informative label we can build for a variant.
   *  Priority:
   *    1. backend-label if it's something other than the generic "Themenseite"
   *    2. localised target-group name ("Lehrkräfte" / "Lernende" / "Allgemein")
   *    3. raw target_group value
   *    4. trimmed variant_id as a last resort (so multiple variants are
   *       at least distinguishable in the dropdown)
   */
  variantLabel(card: WloCard, v: { url: string; target_group: string; label: string; variant_id: string }): string {
    // Auto-collide-detection: wenn das Backend-Label generisch ist und
    // mehrere Varianten dasselbe liefern (z.B. alle drei "Topic Pages"),
    // ist es als Diskriminator wertlos — durchfallen lassen.
    const allVariants = card?.topic_pages || [];
    const myLbl = (v?.label || '').trim();
    const myLblLower = myLbl.toLowerCase();
    const sameLabelCount = allVariants.filter(
      x => (x?.label || '').trim().toLowerCase() === myLblLower
    ).length;
    const labelIsDuplicated = sameLabelCount > 1;

    // Hardcoded uninformative labels — WLO-Standardplatzhalter. Plus
    // "Topic Pages" / "Topic Page" (englischer Default in v2). Wenn das
    // Label hier matcht ODER dupliziert ist, fallen wir durch zu Schritt 1+.
    const UNINFORMATIVE_LABELS = new Set([
      'themenseite', 'themenseiten', 'topic page', 'topic pages',
      'nicht gesetzt', 'unbekannt', 'allgemein', '-', '—', '',
    ]);
    const isUninformative = UNINFORMATIVE_LABELS.has(myLblLower)
      || labelIsDuplicated;
    if (myLbl && !isUninformative) return myLbl;

    // 1. Strukturierte target_group ("teacher" / "learner" / "general")
    const tg = (v?.target_group || '').toLowerCase().trim();
    if (tg && tg !== 'nicht gesetzt') {
      return CanvasComponent._TG_LABELS[tg] || (v.target_group as string);
    }

    // 2. URL-Query-Param — alle bekannten WLO/Edu-Sharing-Param-Varianten
    if (v?.url) {
      try {
        const u = new URL(v.url);
        const q = u.searchParams.get('targetGroup')
          || u.searchParams.get('target_group')
          || u.searchParams.get('target')
          || u.searchParams.get('zielgruppe')
          || u.searchParams.get('variant')
          || u.searchParams.get('audience');
        if (q) return CanvasComponent._TG_LABELS[q.toLowerCase()] || q;
      } catch { /* ignore */ }
    }

    // 3. URL-Pfad-Slug — wenn die URLs sich im Pfad unterscheiden, nutze
    //    das letzte Pfadsegment als Diskriminator.
    if (v?.url) {
      const fromUrl = CanvasComponent._labelFromUrl(v.url, card?.title || '');
      if (fromUrl) return fromUrl;
    }

    // 4. variant_id als Fallback — wenn er kurz und sprechend ist
    if (v?.variant_id) {
      const vid = v.variant_id;
      if (vid.length <= 20) return vid;
      return vid.slice(0, 8) + '…';
    }

    // 5. Letzter Notnagel: nummerieren
    const idx = allVariants.indexOf(v);
    return idx >= 0 ? `Variante ${idx + 1}` : 'Themenseite';
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

  // ── Tile-Design Helper (gespiegelt aus chat.component.ts, damit
  //    Canvas-Kacheln dasselbe Look-and-feel haben) ─────────────────────
  getCardIcon(card: WloCard): string {
    if (card.node_type === 'collection') return '📚';
    const types = card.learning_resource_types || [];
    if (types.some(t => t.toLowerCase().includes('video'))) return '🎬';
    if (types.some(t => t.toLowerCase().includes('arbeitsblatt'))) return '📄';
    if (types.some(t => t.toLowerCase().includes('interaktiv'))) return '🎮';
    if (types.some(t => t.toLowerCase().includes('audio'))) return '🎧';
    if (types.some(t => t.toLowerCase().includes('quiz') || t.toLowerCase().includes('test'))) return '❓';
    if (types.some(t => t.toLowerCase().includes('präsent') || t.toLowerCase().includes('praesent'))) return '🖼️';
    if (types.some(t => t.toLowerCase().includes('übung') || t.toLowerCase().includes('uebung'))) return '✏️';
    if (types.some(t => t.toLowerCase().includes('kurs'))) return '🎓';
    if (types.some(t => t.toLowerCase().includes('webseite') || t.toLowerCase().includes('website'))) return '🌍';
    return '📖';
  }

  /** Lesbares Label für den Inhaltstyp (über dem Bild). */
  getContentTypeLabel(card: WloCard): string {
    if (card.node_type === 'collection') {
      if (card.topic_pages && card.topic_pages.length) return 'Themenseite';
      return 'Sammlung';
    }
    const types = (card.learning_resource_types || []).filter(
      t => t && t.toLowerCase() !== 'sammlung' && t.toLowerCase() !== 'collection',
    );
    if (types.length) return types[0];
    return 'Inhalt';
  }

  isThemenseiteCard(card: WloCard): boolean {
    return card.node_type === 'collection'
      && Array.isArray(card.topic_pages) && card.topic_pages.length > 0;
  }
  isSammlungCard(card: WloCard): boolean {
    return card.node_type === 'collection'
      && !(Array.isArray(card.topic_pages) && card.topic_pages.length > 0);
  }
  isInhaltCard(card: WloCard): boolean {
    return card.node_type !== 'collection';
  }

  /** Kompakte Lizenz-Anzeige für das Footer-Badge auf dem Vorschaubild. */
  getLicenseShort(license: string): string {
    if (!license) return '';
    const l = license.trim();
    if (/^cc\b/i.test(l)) {
      return l.replace(/\s*\d(\.\d+)?\s*$/, '').toUpperCase();
    }
    if (/individuelle|custom|copyright/i.test(l)) return '©';
    if (/public\s*domain|gemeinfrei|cc\s*0|pdm/i.test(l)) return 'PD';
    if (l.length > 12) return 'Lizenz';
    return l;
  }
}
