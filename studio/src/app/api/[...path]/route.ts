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
  const target = `${BACKEND_URL}/api/${path.join('/')}${search}`;

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
  };

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    return NextResponse.json(
      { error: 'Backend unreachable', detail: String(err), backend: BACKEND_URL },
      { status: 502 },
    );
  }

  // Strip hop-by-hop headers, return everything else.
  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (['transfer-encoding', 'connection', 'content-encoding'].includes(k)) return;
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
