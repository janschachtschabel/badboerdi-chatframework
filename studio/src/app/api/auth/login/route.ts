import { NextRequest, NextResponse } from 'next/server';
import { authToken, timingSafeEqualStr } from '@/lib/auth-token';

const COOKIE_NAME = 'boerdi_studio_auth';

/**
 * POST /api/auth/login
 * Body: { password: string }
 *
 * Compares against the server-side env var STUDIO_PASSWORD. On match, sets
 * an httpOnly cookie that the middleware checks.
 *
 * B10 (2026-06-10): das Cookie enthält nicht mehr das Klartext-Passwort,
 * sondern ein HMAC-Token (siehe lib/auth-token.ts); Vergleiche laufen
 * konstantzeitig.
 */
export async function POST(req: NextRequest) {
  const expected = process.env.STUDIO_PASSWORD;
  if (!expected) {
    // No password configured → studio is open, login is meaningless.
    return NextResponse.json({ ok: true, open: true });
  }

  let body: { password?: string } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false }, { status: 400 });
  }

  const provided = body.password || '';
  // Beide Seiten durch HMAC schicken → Längen-/Inhaltsvergleich verrät
  // nichts über das echte Passwort (konstantzeitig auf den Digests).
  const [providedTok, expectedTok] = await Promise.all([
    authToken(provided), authToken(expected),
  ]);
  if (!provided || !timingSafeEqualStr(providedTok, expectedTok)) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const resp = NextResponse.json({ ok: true });
  resp.cookies.set(COOKIE_NAME, expectedTok, {
    httpOnly: true,
    sameSite: 'strict',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  return resp;
}
