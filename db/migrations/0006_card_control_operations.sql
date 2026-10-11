-- Durable intent before idempotent non-spending provider PAUSE operations.
-- This does not implement card issuance/charge reconciliation.
CREATE TABLE card_control_operations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  card_token TEXT NOT NULL,
  requested_state TEXT NOT NULL CHECK (requested_state = 'PAUSED'),
  outcome TEXT NOT NULL DEFAULT 'requested' CHECK (outcome IN ('requested','unknown','confirmed')),
  observed_state TEXT CHECK (observed_state IN ('PAUSED','CLOSED')),
  requested_at TIMESTAMPTZ NOT NULL,
  observed_at TIMESTAMPTZ,
  UNIQUE (user_id,card_token,requested_state)
);
