import { NextRequest, NextResponse } from 'next/server';

const COOKIE_NAME = 'boerdi_studio_auth';

/**
 * POST /api/auth/login
 * Body: { password: string }
 *
 * Compares against the server-side env var STUDIO_PASSWORD. On match, sets
 * an httpOnly cookie that the middleware checks. The cookie value IS the
 * password — it never reaches the browser JS (httpOnly), and over HTTPS it
 * is encrypted in transit. For higher assurance use a reverse-proxy in
 * front of the studio.
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

  if (!body.password || body.password !== expected) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const resp = NextResponse.json({ ok: true });
  resp.cookies.set(COOKIE_NAME, expected, {
    httpOnly: true,
    sameSite: 'strict',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });
  return resp;
}
