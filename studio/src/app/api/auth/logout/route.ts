import { NextResponse } from 'next/server';

const COOKIE_NAME = 'boerdi_studio_auth';

/** POST /api/auth/logout — clears the studio auth cookie. */
export async function POST() {
  const resp = NextResponse.json({ ok: true });
  resp.cookies.set(COOKIE_NAME, '', { path: '/', maxAge: 0 });
  return resp;
}
