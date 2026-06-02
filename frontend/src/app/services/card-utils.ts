/**
 * Card-URL + Typ-Helpers.
 *
 * Alle URLs kommen fertig vom Backend — das Frontend konstruiert keine
 * Repo-URLs mehr. ``card.link`` ist die Single Source of Truth (gesetzt
 * via ``build_card_link`` im Backend, berücksichtigt REPO_BASE_URL,
 * Lotsen-Modus, Search-Query-Params usw.). Fallback-Kette für ältere
 * Backends: ``guide_url → wlo_url → url``.
 */
import { WloCard } from './api.service';

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
 * Primary URL for a card — alle Varianten kommen vom Backend.
 *
 * Fallback-Kette (alle Felder werden serverseitig befüllt):
 *   0. ``topic_pages[0].url`` — wenn die Card eine Themenseiten-Card
 *      ist (variants-Array non-empty), zeigt der Primary-Link
 *      direkt auf die kuratierte Themenseite — NICHT auf die
 *      zugrundeliegende Sammlung. Eine TP-Card ist semantisch eine
 *      Themenseite, kein Sammlungs-Wrapper; entsprechend muss die
 *      ``Box: Themenseiten`` im Chat-Widget zur Themenseite linken.
 *   1. ``link``      — Card-Pipeline v2 Single Source of Truth
 *   2. ``guide_url`` — Lotsen-Modus Repo-Render-Link
 *   3. ``wlo_url``   — Stabiler Repo-Permalink
 *   4. ``url``       — Externe Provider-URL (wwwurl)
 */
export function getCardPrimaryUrl(c: WloCard | null | undefined): string {
  if (!c) return '#';
  if (Array.isArray(c.topic_pages) && c.topic_pages.length > 0) {
    const tpUrl = c.topic_pages[0]?.url;
    if (tpUrl) return tpUrl;
  }
  return c.link || c.guide_url || c.wlo_url || c.url || '#';
}
