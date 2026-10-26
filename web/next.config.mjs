/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // NEXT_DIST_DIR lets a production build run beside `next dev`, which owns .next.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  // The proxy's default 30-second limit cut off the research library's AI
  // drafts (2026-10-17): a free model can take minutes, and the API may try
  // several. Ten minutes covers its worst case (`chat.complete_any`).
  experimental: { proxyTimeout: 600_000 },
  // The Python API runs on :8000. Proxying through Next means the browser only
  // ever talks to one origin, so there is no CORS surface and no API URL baked
  // into the client bundle.
  async rewrites() {
    return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }];
  },
};
export default nextConfig;
