import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { test } from "node:test";
import { GET } from "../src/app/store/products/[productId]/route.ts";

// Actual server-handler invocation and HTTP fetch against an isolated legacy
// store double. This is containment evidence, not Next deployment/operator auth.
test("LAB-001/002/003/004: public proxy denies attack selectors before upstream access", async () => {
  const previous = process.env.STORE_ORIGIN;
  process.env.STORE_ORIGIN = "http://127.0.0.1:1";
  try {
    for (const query of ["evil=1", "evil=true", "evil=", "evil=0&evil=1", "evil=1&evil=0"]) {
      for (const headers of [{}, { Authorization: "Bearer ordinary-user", Cookie: "session=claimed-admin" }]) {
        const response = await GET(new Request(`http://localhost/store/products/chg-65w?${query}`, { headers }), {
          params: Promise.resolve({ productId: "chg-65w" }),
        });
        assert.equal(response.status, 403);
        assert.equal((await response.json()).detail, "Attack Lab execution is disabled");
      }
    }
  } finally {
    if (previous === undefined) delete process.env.STORE_ORIGIN;
    else process.env.STORE_ORIGIN = previous;
  }
});

test("clean browsing forces evil=0 even against a legacy store with poison enabled", async () => {
  const seen = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://localhost");
    seen.push(url);
    response.setHeader("content-type", "text/html");
    response.end(url.searchParams.get("evil") === "0" ? "clean charger" : "poisoned listing");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const previous = process.env.STORE_ORIGIN;
  process.env.STORE_ORIGIN = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const suffix of ["", "?evil=0", "?evil=false", "?evil=off", "?evil=no"]) {
      const response = await GET(new Request(`http://localhost/store/products/chg-65w${suffix}`), {
        params: Promise.resolve({ productId: "chg-65w" }),
      });
      assert.equal(response.status, 200);
      assert.equal(await response.text(), "clean charger");
      assert.equal(response.headers.get("cache-control"), "no-store");
    }
    assert.equal(seen.length, 5);
    assert.ok(seen.every((url) => url.pathname === "/products/chg-65w" && url.searchParams.get("evil") === "0"));
  } finally {
    if (previous === undefined) delete process.env.STORE_ORIGIN;
    else process.env.STORE_ORIGIN = previous;
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
