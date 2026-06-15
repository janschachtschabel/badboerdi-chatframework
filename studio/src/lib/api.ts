/**
 * C (2026-06-10): zentraler Fetch-Helper fürs Studio.
 *
 * Hintergrund: 74 rohe fetch()-Aufrufe in 17 Komponenten zeigten drei
 * wiederkehrende Defekte — (a) stilles Verschlucken (`catch {}` → der
 * Nutzer sieht nichts), (b) `r.json()` ohne vorherigen `r.ok`-Check,
 * (c) kein Abort-/Out-of-order-Handling. Neue Views nutzen fetchJson();
 * Bestands-Views werden schrittweise umgestellt.
 */
export async function fetchJson<T = unknown>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.text()).slice(0, 200); } catch { /* ignore */ }
    throw new Error(`HTTP ${r.status} ${url}${detail ? ` — ${detail}` : ''}`);
  }
  return r.json() as Promise<T>;
}
