CREATE TABLE leash_users (
  id TEXT PRIMARY KEY CHECK (id ~ '^usr_[A-Za-z0-9_-]+$'),
  auth_user_id UUID UNIQUE REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO leash_users (id, auth_user_id)
SELECT 'usr_' || replace(id::text, '-', ''), id FROM users;

CREATE TABLE leash_agents (
  id TEXT PRIMARY KEY CHECK (id ~ '^agt_[A-Za-z0-9_-]+$'),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  token_sha256 TEXT NOT NULL UNIQUE CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
  allowed_modes JSONB NOT NULL CHECK (
    jsonb_typeof(allowed_modes) = 'array' AND
    jsonb_array_length(allowed_modes) = 1 AND
    allowed_modes <@ '["live", "scripted"]'::jsonb
  ),
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE mandate_heads (
  id TEXT PRIMARY KEY CHECK (id ~ '^mnd_[A-Za-z0-9_-]+$'),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  agent_id TEXT NOT NULL REFERENCES leash_agents(id),
  current_version INTEGER NOT NULL CHECK (current_version > 0)
);
CREATE TABLE mandate_versions (
  mandate_id TEXT NOT NULL REFERENCES mandate_heads(id),
  version INTEGER NOT NULL CHECK (version > 0),
  payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  record JSONB NOT NULL,
  PRIMARY KEY (mandate_id, version)
);
ALTER TABLE mandate_heads ADD CONSTRAINT mandate_current_version
FOREIGN KEY (id, current_version) REFERENCES mandate_versions(mandate_id, version)
DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE mandate_confirmations (
  mandate_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  record JSONB NOT NULL,
  verify_key TEXT NOT NULL,
  PRIMARY KEY (mandate_id, version),
  FOREIGN KEY (mandate_id, version) REFERENCES mandate_versions(mandate_id, version)
);
CREATE TABLE mandate_transitions (
  sequence BIGSERIAL PRIMARY KEY,
  mandate_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('proposed','active','revoked','expired','superseded')),
  at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (mandate_id, version) REFERENCES mandate_versions(mandate_id, version)
);
CREATE INDEX mandate_transitions_latest ON mandate_transitions(mandate_id, version, sequence DESC);

CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY CHECK (id ~ '^run_[A-Za-z0-9_-]+$'),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  agent_id TEXT NOT NULL REFERENCES leash_agents(id),
  mandate_id TEXT NOT NULL,
  mandate_version INTEGER NOT NULL,
  registration JSONB NOT NULL,
  record JSONB NOT NULL,
  FOREIGN KEY (mandate_id, mandate_version) REFERENCES mandate_versions(mandate_id, version)
);

-- Durable backend events commit with the authority change. R06 will relay them
-- to Valkey/SSE; unavailable transport must never discard committed history.
CREATE TABLE audit_events (
  sequence BIGSERIAL PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  record JSONB NOT NULL
);
CREATE TABLE audit_deliveries (
  event_id TEXT PRIMARY KEY REFERENCES audit_events(event_id),
  delivered_at TIMESTAMPTZ,
  stream_id TEXT
);

CREATE FUNCTION leash_reject_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'LEASH history is append-only' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER immutable_mandate_versions BEFORE UPDATE OR DELETE ON mandate_versions
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
CREATE TRIGGER immutable_mandate_confirmations BEFORE UPDATE OR DELETE ON mandate_confirmations
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
CREATE TRIGGER immutable_mandate_transitions BEFORE UPDATE OR DELETE ON mandate_transitions
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
CREATE TRIGGER immutable_agent_runs BEFORE UPDATE OR DELETE ON agent_runs
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
CREATE TRIGGER immutable_audit_events BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
