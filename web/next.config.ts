import type { NextConfig } from "next";

// In-cluster defaults (LKE). For local Next → local MCP/api, override at `pnpm dev`:
//   API_ORIGIN=http://127.0.0.1:8000
//   MCP_LEASH_ORIGIN=http://127.0.0.1:8002
//   MCP_STORE_ORIGIN=http://127.0.0.1:8003
//   RAIL_ORIGIN=http://127.0.0.1:8005
const apiOrigin = process.env.API_ORIGIN ?? "http://api:8000";
const mcpLeashOrigin = process.env.MCP_LEASH_ORIGIN ?? "http://mcp-leash:8002";
const mcpStoreOrigin = process.env.MCP_STORE_ORIGIN ?? "http://mcp-store:8003";
const railOrigin = process.env.RAIL_ORIGIN ?? "http://webhook:8000";

const nextConfig: NextConfig = {
  output: "standalone",
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
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${apiOrigin}/:path*`,
      },
      {
        source: "/mcp-leash/:path*",
        destination: `${mcpLeashOrigin}/:path*`,
      },
      {
        source: "/mcp-store/:path*",
        destination: `${mcpStoreOrigin}/:path*`,
      },
      {
        // Public Lithic ASA + rail health: http://<NB>/rail/lithic/asa
        source: "/rail/:path*",
        destination: `${railOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
