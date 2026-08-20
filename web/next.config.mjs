/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Python API runs on :8000. Proxying through Next means the browser only
  // ever talks to one origin, so there is no CORS surface and no API URL baked
  // into the client bundle.
  async rewrites() {
    return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }];
  },
};
export default nextConfig;
