# Agents service

Separate FastAPI process for LEASH Strands shopper/guardian agents.

## Local

```bash
cd services/agents
uv sync
uv run uvicorn main:app --reload --port 8001
```

Health: `curl http://127.0.0.1:8001/health`

On LKE this runs as Deployment `agents` at `http://agents:8000` (ClusterIP only).
