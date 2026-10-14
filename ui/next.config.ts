import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // A self-contained server for the container image (ui/Dockerfile): .next/standalone.
  output: "standalone",
  // No "X-Powered-By: Next.js"; the other security headers come from Caddy (docker/Caddyfile).
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
