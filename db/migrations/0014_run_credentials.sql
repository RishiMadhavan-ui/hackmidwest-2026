CREATE TABLE run_credentials (
  token_sha256 text PRIMARY KEY CHECK (length(token_sha256)=64),
  run_id text NOT NULL REFERENCES agent_runs(id),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(run_id)
);
