# External Leash MCP connector

Owner Cameron (deployment) and Aditya (MCP). The opt-in Leash-only proxy from #21 is preserved. It is disabled by default, requires an authenticated HTTPS deployment, and does not expose Store MCP. Do not send bearer credentials to the HTTP demo address or treat a proxy flag as financial authority.

## Scope and current limits

`propose_mandate`, `list_mandates`, `request_payment`, `check_status` are available to a separately operator-provisioned agent bound immutably to its intended human. Agents can propose drafts and read their owned data; only the authenticated human confirms authority. An external static bearer has no claimed Graph worker lease or audience/action scope. An unscoped `request_payment` is a blocked observation (`execution_scope_required`), not a grant or charge. This connector does not launch Strands or implement external autonomous purchases.

Mission Control launches the real Graph through API-dispatched private, expiring, account-owned credentials. It does not use or rebind the shared legacy shopper token. See [current execution protocol](../api/full-app-handoff.md). Existing live/scripted legacy bindings must retain their original owners and modes.

## Operator configuration

1. Configure a trusted HTTPS ingress and the intended exact MCP allowed host. Confirm authentication and direct API isolation; inspect actual rollout before making the endpoint available.
2. Generate a distinct server-held `AGENT_TOKEN_EXTERNAL` of at least 32 random characters. Provision only for the intended immutable demo identity, using its real `/identity` value. Do not borrow another user's token or enable idle rebinding. Multiple legacy live agents on an account without a private UI identity can make mandate selection ambiguous; leave that fail-closed error intact and reconcile identity selection explicitly.
3. With the intended operator API environment loaded, run:

   ```bash
   cd api
   PYTHONPATH=../shared:. uv run python manage.py bind-agent \
     --user-id usr_<32_hex_identity> \
     --agent-id agt_external \
     --token-env AGENT_TOKEN_EXTERNAL \
     --mode live
   ```

4. Build web with `ENABLE_PUBLIC_MCP_LEASH_PROXY=1`; both-proxy `ENABLE_PUBLIC_MCP_PROXY=1` also exposes Store MCP and is broader. Leave both unset by default. These flags are baked into Next's standalone build; changing only a running pod variable is insufficient. No deployment was performed during this integration.
5. Configure your client URL as `https://<your-configured-demo-host>/mcp-leash/mcp` and `Authorization: Bearer <AGENT_TOKEN_EXTERNAL>` from its local secret store. Never commit the credential, paste it in the UI, or use it as an operator role. Cursor/Claude credential-loading support is client-specific and unverified here.

Before enabling, test the connector's actual HTTPS SDK round trip, ownership errors and blocked unscoped payment. Local rewrite tests establish which service is exposed by each flag; they do not prove a deployed TLS or external-client integration. No external fixture/reset/provider control is exposed by this connector.
