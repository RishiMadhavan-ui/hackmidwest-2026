import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { test } from "node:test";
import { GET } from "../src/app/attack-lab/operator-view/route.ts";

test("LAB-001/002/009: operator HTML requires backend-verified Bearer authority", async () => {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(request.headers.authorization);
    response.setHeader("content-type", "application/json");
    if (request.headers.authorization === "Bearer ordinary-user") {
      response.writeHead(403).end('{"detail":"Forbidden"}');
    } else if (request.headers.authorization === "Bearer expired") {
      response.writeHead(401).end('{"detail":"Expired"}');
    } else {
      response.end(JSON.stringify({ operator_authorized: true, execution_available: false,
        server_enabled: false, namespace: null }));
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const previous = process.env.API_ORIGIN;
  process.env.API_ORIGIN = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const headers of [{}, { Cookie: "session=claimed-admin" }]) {
      assert.equal((await GET(new Request("http://localhost/attack-lab", { headers }))).status, 401);
    }
    assert.equal(requests.length, 0);
    for (const [token, status] of [["ordinary-user", 403], ["expired", 401]]) {
      assert.equal((await GET(new Request("http://localhost/attack-lab", {
        headers: { Authorization: `Bearer ${token}` },
      }))).status, status);
    }
    const verified = await GET(new Request("http://localhost/attack-lab", {
      headers: { Authorization: "Bearer verified-operator" },
    }));
    assert.equal(verified.status, 200);
    assert.equal(verified.headers.get("cache-control"), "no-store");
    assert.match(verified.headers.get("content-security-policy"), /default-src 'none'/);
    assert.match(await verified.text(), /Scenario execution is unavailable/);
  } finally {
    if (previous === undefined) delete process.env.API_ORIGIN;
    else process.env.API_ORIGIN = previous;
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
