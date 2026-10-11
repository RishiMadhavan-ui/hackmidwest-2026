import type { NextConfig } from "next";

// In-cluster defaults (LKE). For local Next → local services, override at `pnpm dev`:
//   API_ORIGIN=http://127.0.0.1:8000
//   MCP_LEASH_ORIGIN=http://127.0.0.1:8002
//   MCP_STORE_ORIGIN=http://127.0.0.1:8003
//   RAIL_ORIGIN=http://127.0.0.1:8005
//   STORE_ORIGIN=http://127.0.0.1:8004
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
    return {
      // Filesystem guards (including dynamic /backend/internal/*) must run
      // before the broad backend adapter.
      fallback: [{ source: "/backend/:path*", destination: `${apiOrigin}/:path*` }],
      afterFiles: [
      // Build-time flags (Next bakes rewrites into the standalone server).
      // LEASH-only: safe external connector path; does not expose Store MCP.
      // Both: legacy ENABLE_PUBLIC_MCP_PROXY=1 still opens leash + store.
      ...((process.env.ENABLE_PUBLIC_MCP_LEASH_PROXY === "1"
        || process.env.ENABLE_PUBLIC_MCP_PROXY === "1") ? [{
        source: "/mcp-leash/:path*",
        destination: `${mcpLeashOrigin}/:path*`,
      }] : []),
      ...(process.env.ENABLE_PUBLIC_MCP_PROXY === "1" ? [{
        source: "/mcp-store/:path*",
        destination: `${mcpStoreOrigin}/:path*`,
      }] : []),
      {
        // Only the signed ASA responder is public; control routes stay private.
        source: "/rail/lithic/asa",
        destination: `${railOrigin}/lithic/asa`,
      },
      ],
    };
  },
};

export default nextConfig;
