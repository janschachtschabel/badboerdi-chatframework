/**
 * Page-Context-Detector
 *
 * Inspects the host page's URL + DOM and produces structured fields the
 * backend can resolve via MCP (node_id, collection_id, topic_page_slug,
 * subject_slug) plus a heuristic `page_text` snippet so the LLM has a
 * grounding anchor even when the URL doesn't match a known WLO pattern.
 *
 * Runs entirely in the browser — no backend round-trip. The actual
 * resolution to platform metadata happens server-side in
 * `backend/app/services/page_context_service.py` via MCP tools.
 *
 * Recognized URL patterns (in priority order):
 *   1. /components/render/<uuid>            → node_id
 *   2. ?node=<uuid> | ?collection=<uuid>    → node_id / collection_id
 *   3. /themenseite/<slug>                  → topic_page_slug
 *   4. /fachportal/<subject>[/<slug>]       → subject_slug + optional topic_page_slug
 *
 * DOM markers (host pages can opt-in by adding any of):
 *   <meta name="boerdi:node-id" content="<uuid>">
 *   <meta name="boerdi:collection-id" content="<uuid>">
 *   <meta name="boerdi:topic-slug" content="<slug>">
 *   <body data-edu-node-id="<uuid>">
 *   <body data-edu-topic-slug="<slug>">
 */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SLUG_RE = /^[a-z0-9-]{2,80}$/i;

export interface DetectedContext {
  /** edu-sharing UUID of the rendered node (if detected). */
  node_id?: string;
  /** edu-sharing UUID of a collection (if detected). */
  collection_id?: string;
  /** WLO theme-page slug (e.g. "klimawandel"). */
  topic_page_slug?: string;
  /** Subject slug (e.g. "biologie", "mathematik"). */
  subject_slug?: string;
  /** Active search term shown on the host page (if extractable). */
  search_query?: string;
  /** Raw extracted page text — title + first ~3KB of visible content. */
  page_text?: string;
  /** What kind of page this is — useful for prompt construction. */
  page_kind?: 'topic' | 'collection' | 'content' | 'subject' | 'search' | 'other';
  /** Origin of the detection — for trace/debug. */
  detection_source?: string;
}

/* ── URL pattern parsing ─────────────────────────────────────────── */

function _detectFromUrl(url: URL): Partial<DetectedContext> {
  const path = url.pathname.toLowerCase();
  const sp = url.searchParams;

  // 1. Render path: /components/render/<uuid>[/...]
  const renderMatch = path.match(/\/components\/render\/([0-9a-f-]{36})(?:\/|$)/i);
  if (renderMatch && UUID_RE.test(renderMatch[1])) {
    return { node_id: renderMatch[1], page_kind: 'content', detection_source: 'url:components/render' };
  }

  // 2. Query-param node / collection ids
  const qNode = sp.get('node') || sp.get('node_id') || sp.get('nodeId');
  if (qNode && UUID_RE.test(qNode)) {
    return { node_id: qNode, page_kind: 'content', detection_source: 'url:?node' };
  }
  const qCol = sp.get('collection') || sp.get('collection_id') || sp.get('collectionId');
  if (qCol && UUID_RE.test(qCol)) {
    return { collection_id: qCol, page_kind: 'collection', detection_source: 'url:?collection' };
  }

  // 3. Theme page: /themenseite/<slug>[/...]
  const themeMatch = path.match(/\/themenseite\/([a-z0-9-]+)(?:\/|$)/i);
  if (themeMatch && SLUG_RE.test(themeMatch[1])) {
    return { topic_page_slug: themeMatch[1], page_kind: 'topic', detection_source: 'url:/themenseite' };
  }

  // 4. Subject portal: /fachportal/<subject>[/<slug>]
  const subjectMatch = path.match(/\/fachportal\/([a-z0-9-]+)(?:\/([a-z0-9-]+))?(?:\/|$)/i);
  if (subjectMatch && SLUG_RE.test(subjectMatch[1])) {
    const out: Partial<DetectedContext> = {
      subject_slug: subjectMatch[1],
      page_kind: 'subject',
      detection_source: 'url:/fachportal',
    };
    if (subjectMatch[2] && SLUG_RE.test(subjectMatch[2])) {
      out.topic_page_slug = subjectMatch[2];
      out.detection_source = 'url:/fachportal/<slug>';
    }
    return out;
  }

  // 5. Search results: any URL with ?q= / ?search=
  const q = sp.get('q') || sp.get('search') || sp.get('query');
  if (q && q.length >= 2 && q.length <= 200) {
    return { search_query: q, page_kind: 'search', detection_source: 'url:?q' };
  }

  return {};
}

/* ── DOM marker parsing ──────────────────────────────────────────── */

function _readMeta(name: string): string | null {
  try {
    const el = document.querySelector(`meta[name="${name}"]`);
    return el?.getAttribute('content')?.trim() || null;
  } catch {
    return null;
  }
}

function _detectFromDom(): Partial<DetectedContext> {
  const out: Partial<DetectedContext> = {};

  // Opt-in meta tags that the host page can add
  const metaNode = _readMeta('boerdi:node-id');
  if (metaNode && UUID_RE.test(metaNode)) {
    out.node_id = metaNode;
    out.detection_source = 'meta:boerdi:node-id';
  }
  const metaCol = _readMeta('boerdi:collection-id');
  if (metaCol && UUID_RE.test(metaCol)) {
    out.collection_id = metaCol;
    out.detection_source = 'meta:boerdi:collection-id';
  }
  const metaSlug = _readMeta('boerdi:topic-slug');
  if (metaSlug && SLUG_RE.test(metaSlug)) {
    out.topic_page_slug = metaSlug;
    out.detection_source = 'meta:boerdi:topic-slug';
  }

  // body data-attrs (alternative escape hatch)
  try {
    const ds = document.body?.dataset;
    if (ds) {
      if (!out.node_id && ds['eduNodeId'] && UUID_RE.test(ds['eduNodeId'])) {
        out.node_id = ds['eduNodeId'];
        out.detection_source = 'body[data-edu-node-id]';
      }
      if (!out.topic_page_slug && ds['eduTopicSlug'] && SLUG_RE.test(ds['eduTopicSlug'])) {
        out.topic_page_slug = ds['eduTopicSlug'];
        out.detection_source = 'body[data-edu-topic-slug]';
      }
    }
  } catch { /* ignore */ }

  return out;
}

/* ── Visible-text extraction ──────────────────────────────────── */

const _MAX_TEXT_BYTES = 3000;

function _extractVisibleText(): string {
  // Prefer semantic containers; fall back to <body>.
  const candidates = ['main', 'article', '[role="main"]', '#content', '.content', 'body'];
  let root: Element | null = null;
  for (const sel of candidates) {
    try {
      const el = document.querySelector(sel);
      if (el) { root = el; break; }
    } catch { /* ignore bad selectors */ }
  }
  if (!root) return '';

  // Pull H1 + meta-description first (they're the highest-signal anchors)
  const parts: string[] = [];
  const h1 = root.querySelector('h1');
  if (h1?.textContent) parts.push(h1.textContent.trim());

  const metaDesc = _readMeta('description') || _readMeta('og:description');
  if (metaDesc) parts.push(metaDesc);

  // Then walk visible text — strip widget area, scripts, navigation.
  const clone = root.cloneNode(true) as Element;
  clone.querySelectorAll(
    'boerdi-chat, script, style, nav, header, footer, [aria-hidden="true"], .visually-hidden',
  ).forEach(el => el.remove());

  const raw = (clone.textContent || '').replace(/\s+/g, ' ').trim();
  if (raw) parts.push(raw);

  let combined = parts.join('\n').trim();
  if (combined.length > _MAX_TEXT_BYTES) {
    combined = combined.slice(0, _MAX_TEXT_BYTES) + ' …';
  }
  return combined;
}

/* ── Public API ──────────────────────────────────────────────── */

/**
 * Run all detectors and return whatever fields could be inferred.
 * Safe to call from any context — never throws, never blocks.
 */
export function detectPageContext(): DetectedContext {
  const out: DetectedContext = {};

  try {
    const urlHits = _detectFromUrl(new URL(window.location.href));
    Object.assign(out, urlHits);
  } catch { /* ignore */ }

  try {
    const domHits = _detectFromDom();
    // DOM markers override URL hits when present (they're explicit).
    for (const k of Object.keys(domHits) as (keyof DetectedContext)[]) {
      const v = domHits[k];
      if (v !== undefined && v !== null && v !== '') {
        (out as Record<string, unknown>)[k] = v;
      }
    }
  } catch { /* ignore */ }

  // Page text is best-effort — only attach when the page seems to be a
  // *content* host (i.e. we either detected something specific OR the
  // host page is clearly more than a search shell). Skip search-shell
  // pages so we don't paste search-input text back as "context".
  try {
    if (out.page_kind && out.page_kind !== 'search') {
      const text = _extractVisibleText();
      if (text) out.page_text = text;
    }
  } catch { /* ignore */ }

  if (!out.page_kind) {
    out.page_kind = 'other';
  }
  return out;
}
