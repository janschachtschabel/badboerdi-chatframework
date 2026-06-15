import { NextRequest, NextResponse } from 'next/server';

/**
 * Server-side proxy for the BadBoerdi backend.
 *
 * Replaces the old Next.js rewrite (next.config.mjs) so we can:
 *   1. Make the backend address configurable via env (BACKEND_URL).
 *   2. Inject the X-Studio-Key header from a server-only env var so the
 *      browser never sees the actual key.
 *   3. Stay compatible with all existing fetch('/api/...') calls in the
 *      studio components — no client changes required.
 *
 * Env vars:
 *   BACKEND_URL       Default http://localhost:8000
 *   STUDIO_API_KEY    Optional. If set, sent as X-Studio-Key on every call.
 */

const BACKEND_URL = (process.env.BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '');
const API_KEY = process.env.STUDIO_API_KEY || '';

// Tell Next this route is fully dynamic (no caching, supports streams).
export const dynamic = 'force-dynamic';

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const search = req.nextUrl.search || '';
  // Preserve the trailing slash from the original request. Next.js's
  // dynamic catch-all (`[...path]`) strips it from the segments array,
  // so without this restoration the proxy would call /api/sessions
  // (no slash) when the studio actually hit /api/sessions/. FastAPI
  // would then 307-redirect to the slashed variant — but `redirect:
  // 'manual'` below stops the proxy from following, and the studio
  // sees an empty redirect response instead of the session list.
  const trailingSlash = req.nextUrl.pathname.endsWith('/') ? '/' : '';
  const target = `${BACKEND_URL}/api/${path.join('/')}${trailingSlash}${search}`;

  // Forward headers EXCEPT host/connection. Add the studio key if configured.
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k === 'host' || k === 'connection' || k === 'content-length') return;
    headers.set(key, value);
  });
  if (API_KEY) headers.set('X-Studio-Key', API_KEY);

  const init: RequestInit = {
    method: req.method,
    headers,
    // Pass body for non-GET/HEAD. Use the raw stream so file uploads work.
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body,
    // @ts-expect-error duplex is required by undici when streaming a body
    duplex: 'half',
    redirect: 'manual',
    // B10 (2026-06-10): Timeout — hängt das Backend (lange LLM-Calls,
    // Eval-Starts), blieb der Studio-Request sonst unbegrenzt offen.
    // 120 s deckt auch träge Endpunkte (Backup/Restore, Golden-Start).
    signal: AbortSignal.timeout(120_000),
  };

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    // B10: keine internen Details (Backend-URL, Roh-Fehlertext) an den
    // Browser leaken; Timeout separat als 504 ausweisen.
    const isTimeout = err instanceof Error && err.name === 'TimeoutError';
    return NextResponse.json(
      { error: isTimeout ? 'Backend timeout' : 'Backend unreachable' },
      { status: isTimeout ? 504 : 502 },
    );
  }

  // Strip hop-by-hop headers, return everything else.
  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (['transfer-encoding', 'connection', 'content-encoding'].includes(k)) return;
    // B10: Backend-Redirects zeigen auf den INTERNEN Host
    // (http://localhost:8000/...) — der Browser würde dem Location-Header
    // am Proxy vorbei folgen (ohne Key/Cookie). Auf den Studio-Origin
    // umschreiben; fremde Ziele strippen.
    if (k === 'location') {
      try {
        const loc = new URL(value, BACKEND_URL);
        const backend = new URL(BACKEND_URL);
        if (loc.host === backend.host) {
          respHeaders.set(key, loc.pathname + loc.search);
        }
        // anderes Ziel → Header weglassen (kein Offsite-Redirect via Proxy)
      } catch { /* unparsebar → weglassen */ }
      return;
    }
    respHeaders.set(key, value);
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
