# External MCP connector (safe path)

Leash-only public MCP for a **separate** live agent credential. Does not expose
Store MCP and does not reuse `AGENT_TOKEN_SHOPPER` / `_SCRIPTED`.

## Prerequisites

1. `AGENT_TOKEN_EXTERNAL` in `.env` (32+ chars), distinct from cluster shopper tokens.
2. Bound to your demo human:
   ```bash
   cd api && set -a && source ../.env && set +a
   PYTHONPATH=../shared:. uv run python manage.py bind-agent \
     --user-id usr_<your_user> \
     --agent-id agt_external \
     --token-env AGENT_TOKEN_EXTERNAL \
     --mode live
   ```
3. Web image built with `ENABLE_PUBLIC_MCP_LEASH_PROXY=1` (deploy reads this from `.env`).
4. Optional: `MCP_ALLOWED_HOSTS` includes your public host if clients bypass Next.

## Connector URL

```text
http://173.255.199.245/mcp-leash/mcp
```

Authorization header on every MCP request:

```text
Authorization: Bearer <AGENT_TOKEN_EXTERNAL>
```

## Tools available

`propose_mandate`, `list_mandates`, `request_payment`, `check_status`.

Human must confirm mandates in Mission Control before `list_mandates` shows them
active. This path does **not** start the Strands Graph; Mission Control Start
shopping still uses the cluster shopper tokens.

## Cursor example (`~/.cursor/mcp.json` fragment)

```json
{
  "mcpServers": {
    "leash": {
      "url": "http://173.255.199.245/mcp-leash/mcp",
      "headers": {
        "Authorization": "Bearer ${AGENT_TOKEN_EXTERNAL}"
      }
    }
  }
}
```

Paste the real token locally; do not commit it.
