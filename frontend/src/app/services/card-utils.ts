/**
 * Card-URL + Typ-Helpers.
 *
 * Die edu-sharing/Redaktion-Plattform hat drei Detail-URL-Schemas, je
 * nachdem, was man anzeigt:
 *   - Themenseite:      /components/topic-pages?collectionId={id}
 *   - Sammlungsseite:   /components/collections?id={id}&scope=TYPE_EDITORIAL
 *   - Inhalt (render):  /components/render/{id}
 *
 * Zusätzlich bringen Inhalte meistens eine externe `url` (das ist die
 * eigentliche WWW-URL der Ressource). Lehrer:innen wollen in Ausdrucken
 * bevorzugt diese externe Quelle — nur wenn die fehlt, fällt man auf
 * die Render-Detailseite im edu-sharing zurueck.
 */
import { WloCard } from './api.service';

const EDU_SHARING_BASE = 'https://redaktion.openeduhub.net/edu-sharing/components';

export function isTopicPage(c: WloCard | null | undefined): boolean {
  return !!c && c.node_type === 'collection' &&
    Array.isArray(c.topic_pages) && c.topic_pages.length > 0;
}

/** Any collection (also topic pages). Used as a superset check. */
export function isCollection(c: WloCard | null | undefined): boolean {
  return !!c && c.node_type === 'collection';
}

/** "Pure" collection — a Sammlung that is NOT a Themenseite. */
export function isPureCollection(c: WloCard | null | undefined): boolean {
  return isCollection(c) && !isTopicPage(c);
}

export function isContent(c: WloCard | null | undefined): boolean {
  return !!c && c.node_type !== 'collection';
}

/**
 * Primary external URL for a card.
 * - Topic page → topic_pages[0].url (server-supplied) OR /topic-pages?collectionId=…
 * - Collection (not a topic page) → /collections?id=…&scope=TYPE_EDITORIAL
 * - Content → external www url (c.url) preferred, otherwise the render detail page
 */
export function getCardPrimaryUrl(c: WloCard | null | undefined): string {
  if (!c) return '#';

  // Topic page: use the server-supplied URL when present (it already
  // encodes the right scope/params), otherwise synthesize one.
  if (isTopicPage(c)) {
    const tp = c.topic_pages?.[0]?.url;
    if (tp) return tp;
    if (c.node_id) {
      return `${EDU_SHARING_BASE}/topic-pages?collectionId=${encodeURIComponent(c.node_id)}`;
    }
  }

  // Plain collection (no topic page): use the collections-view URL so the
  // user lands on the sub-collections + contents, not on a generic render.
  if (isCollection(c) && c.node_id) {
    return `${EDU_SHARING_BASE}/collections?id=${encodeURIComponent(c.node_id)}&scope=TYPE_EDITORIAL`;
  }

  // Content: prefer the real www URL; fall back to the edu-sharing
  // render detail page if no external URL is known.
  return c.url || c.wlo_url || '#';
}
