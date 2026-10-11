import assert from "node:assert/strict";
import { test } from "node:test";
import nextConfig from "../next.config.ts";

async function rewritesWith(leash, both) {
  const names = ["ENABLE_PUBLIC_MCP_LEASH_PROXY", "ENABLE_PUBLIC_MCP_PROXY"];
  const prior = names.map((name) => process.env[name]);
  try {
    for (const [index, value] of [leash, both].entries()) {
      if (value === undefined) delete process.env[names[index]];
      else process.env[names[index]] = value;
    }
    return await nextConfig.rewrites();
  } finally {
    for (const [index, value] of prior.entries()) {
      if (value === undefined) delete process.env[names[index]];
      else process.env[names[index]] = value;
    }
  }
}

test("default and malformed flags expose neither MCP service nor rail controls", async () => {
  for (const [leash, both] of [[undefined, undefined], ["0", "0"], ["true", "yes"]]) {
    const config = await rewritesWith(leash, both);
    assert.ok(!config.afterFiles.some((route) => route.source.startsWith("/mcp-")));
    assert.deepEqual(config.afterFiles.map((route) => route.source), ["/rail/lithic/asa"]);
    assert.deepEqual(config.fallback.map((route) => route.source), ["/backend/:path*"]);
    assert.equal(config.beforeFiles, undefined);
  }
});

test("Leash-only opt-in exposes the financial adapter and keeps Store MCP private", async () => {
  const config = await rewritesWith("1", undefined);
  assert.deepEqual(config.afterFiles.map((route) => route.source), ["/mcp-leash/:path*", "/rail/lithic/asa"]);
  assert.ok(config.afterFiles[0].destination.endsWith(":8002/:path*"));
});

test("legacy both-server opt-in is explicitly broader and exposes no private rail wildcard", async () => {
  const config = await rewritesWith(undefined, "1");
  assert.deepEqual(config.afterFiles.map((route) => route.source), ["/mcp-leash/:path*", "/mcp-store/:path*", "/rail/lithic/asa"]);
});
