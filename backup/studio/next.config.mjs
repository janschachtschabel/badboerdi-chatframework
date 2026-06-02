/** @type {import('next').NextConfig} */
const nextConfig = {
  // Backend communication is handled by the server-side proxy at
  // src/app/api/[...path]/route.ts so we can inject the X-Studio-Key
  // header from BACKEND_URL + STUDIO_API_KEY env vars. The Next.js
  // rewrite has been removed because rewrites cannot add headers.
  httpAgentOptions: {
    keepAlive: true,
  },
  experimental: {
    proxyTimeout: 180_000, // 3 minutes
  },
};

export default nextConfig;
