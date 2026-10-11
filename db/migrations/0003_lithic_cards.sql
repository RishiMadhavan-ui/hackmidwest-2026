-- Lithic sandbox account/card columns on auth users + issued-card metadata.
-- PAN/CVV are never stored; only tokens and last-four.

ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS postal_code TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_account_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_account_holder_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_financial_account_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_card_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_card_last_four TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lithic_spend_limit_cents INTEGER;

CREATE TABLE IF NOT EXISTS lithic_cards (
  card_token TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_token TEXT NOT NULL,
  last_four TEXT,
  spend_limit_cents INTEGER NOT NULL,
  spend_limit_duration TEXT NOT NULL,
  card_type TEXT NOT NULL,
  state TEXT,
  memo TEXT,
  correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lithic_cards_user_id_idx ON lithic_cards (user_id);
