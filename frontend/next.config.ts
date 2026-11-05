import type { NextConfig } from "next";

// The browser never calls the FastAPI backend directly: /api/v1/* is served
// by the route handler in src/app/api/v1/[...path]/route.ts, which forwards to
// BACKEND_INTERNAL_URL at request time.
const nextConfig: NextConfig = {
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
