import { NextRequest, NextResponse } from 'next/server';

/**
 * Studio access gate.
 *
 * Activated by setting the env var `STUDIO_PASSWORD` (server-side only —
 * NOT prefixed with NEXT_PUBLIC_, so it never reaches the browser).
 *
 *   STUDIO_PASSWORD=mysecret npm run dev
 *
 * If the variable is empty/unset, the studio is open (current behaviour) —
 * convenient for local development.
 *
 * On the first visit, the user is redirected to /login. After entering the
 * correct password, an httpOnly cookie is set and all subsequent requests
 * are allowed through. The browser never sees the actual password value.
 *
 * NOTE: With a `src/` project layout this file MUST live at `src/middleware.ts`.
 * Next.js silently ignores a `middleware.ts` in the project root when `src/`
 * is present.
 */

const COOKIE_NAME = 'boerdi_studio_auth';
const PUBLIC_PATHS = ['/login', '/api/auth/login', '/api/auth/logout'];

export function middleware(req: NextRequest) {
  const expected = process.env.STUDIO_PASSWORD;

  // No password configured → studio is open (dev default).
  if (!expected) return NextResponse.next();

  const { pathname } = req.nextUrl;

  // Always allow login page + auth endpoints + Next.js internals.
  if (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/')) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon')
  ) {
    return NextResponse.next();
  }

  const cookie = req.cookies.get(COOKIE_NAME)?.value;
  if (cookie === expected) return NextResponse.next();

  // Redirect to login (preserve the intended path for nicer UX).
  const url = req.nextUrl.clone();
  url.pathname = '/login';
  url.searchParams.set('from', pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Protect everything except Next.js static assets.
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
