-- Durable payment attempts for POST /payments (grant approval ≠ charge).
CREATE TABLE payment_attempts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  agent_id TEXT,
  mandate_id TEXT NOT NULL,
  mandate_version INTEGER NOT NULL,
  checkout_id TEXT NOT NULL,
  run_id TEXT,
  status TEXT NOT NULL,
  verification_id TEXT,
  grant_id TEXT,
  instrument_token TEXT,
  checkout_hash TEXT,
  verification JSONB,
  record JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX payment_attempts_user_created_idx
  ON payment_attempts (user_id, created_at DESC);
CREATE INDEX payment_attempts_checkout_idx
  ON payment_attempts (checkout_id, created_at DESC);
