/**
 * B10 (2026-06-10): Auth-Cookie-Härtung.
 *
 * Vorher lag das STUDIO_PASSWORD im KLARTEXT im Cookie (30 Tage, in den
 * DevTools lesbar, bei jedem Request mitgesendet). Jetzt wandert nur noch
 * ein abgeleitetes HMAC-Token ins Cookie — aus dem Token lässt sich das
 * Passwort nicht rekonstruieren. Bewusst Web-Crypto-only, damit derselbe
 * Code in der Node-Login-Route UND der Edge-Middleware läuft.
 *
 * Hinweis: Bestehende Sessions mit Alt-Cookie (Klartext) werden ungültig —
 * einmaliges Neu-Einloggen nach dem Deploy.
 */

const enc = new TextEncoder();

/** Deterministisches HMAC-SHA256-Token aus dem Studio-Passwort. */
export async function authToken(secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign(
    'HMAC', key, enc.encode('boerdi-studio-auth-v1'),
  );
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Konstantzeit-Vergleich (Edge hat kein crypto.timingSafeEqual). */
export function timingSafeEqualStr(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
