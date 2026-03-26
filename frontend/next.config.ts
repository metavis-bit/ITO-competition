import type { NextConfig } from 'next';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:9527';

const nextConfig: NextConfig = {
  output: process.env.VERCEL ? undefined : 'standalone',
  transpilePackages: ['mathml2omml', 'pptxgenjs'],
  serverExternalPackages: [],
  experimental: {
    proxyClientMaxBodySize: '200mb',
  },
  async rewrites() {
    return [
      // Proxy backend biology images to avoid CORS
      {
        source: '/v1/assets/images/:path*',
        destination: `${BACKEND_URL}/v1/assets/images/:path*`,
      },
      // Proxy backend image management APIs
      {
        source: '/v1/images/:path*',
        destination: `${BACKEND_URL}/v1/images/:path*`,
      },
    ];
  },
};

export default nextConfig;
