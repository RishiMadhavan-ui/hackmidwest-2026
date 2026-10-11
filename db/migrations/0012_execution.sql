-- Forward-only execution scopes; existing signed authority/history is unchanged.
CREATE TABLE run_executions (
  run_id TEXT PRIMARY KEY REFERENCES agent_runs(id),
  launch_hash TEXT NOT NULL UNIQUE,
  worker_id TEXT,
  generation INTEGER NOT NULL DEFAULT 1 CHECK (generation > 0),
  leash_token_hash TEXT UNIQUE,
  store_token_hash TEXT UNIQUE,
  claimed_at TIMESTAMPTZ,
  lease_until TIMESTAMPTZ,
  deadline TIMESTAMPTZ NOT NULL,
  state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','terminal')),
  progress JSONB NOT NULL DEFAULT '{}'::jsonb,
  graph_ack_at TIMESTAMPTZ,
  rail_epoch TEXT,
  rail_stopped_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((worker_id IS NULL) = (claimed_at IS NULL))
);
CREATE TABLE merchant_checkouts (
  checkout_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  run_id TEXT NOT NULL REFERENCES run_executions(run_id),
  generation INTEGER NOT NULL,
  session_id TEXT NOT NULL UNIQUE,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision=1),
  expires_at TIMESTAMPTZ NOT NULL,
  facts JSONB NOT NULL,
  facts_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_merchant_checkouts BEFORE UPDATE OR DELETE ON merchant_checkouts
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
ALTER TABLE payment_operations DROP CONSTRAINT IF EXISTS payment_operations_state_check;
ALTER TABLE payment_operations ADD CONSTRAINT payment_operations_state_check CHECK
  (state IN ('prepared','blocked','cancelled','reconciling','activating','ready','authorizing','authorized','declined'));
DROP INDEX IF EXISTS payment_operations_unresolved_mandate;
DROP INDEX IF EXISTS payment_operations_unresolved_run;
CREATE UNIQUE INDEX payment_operations_unresolved_mandate ON payment_operations(user_id,mandate_id)
  WHERE state IN ('prepared','reconciling','activating','ready','authorizing','authorized');
CREATE UNIQUE INDEX payment_operations_unresolved_run ON payment_operations(run_id)
  WHERE state IN ('prepared','reconciling','activating','ready','authorizing','authorized');
CREATE OR REPLACE FUNCTION leash_guard_payment_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Payment operations cannot be deleted' USING ERRCODE='23514'; END IF;
  IF (to_jsonb(OLD)-ARRAY['state','revision','reason','error_status','error_detail','updated_at']) IS DISTINCT FROM
     (to_jsonb(NEW)-ARRAY['state','revision','reason','error_status','error_detail','updated_at']) THEN
    RAISE EXCEPTION 'Payment operation identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.revision <> OLD.revision+1 OR NOT (
    -- 'authorized' straight from 'prepared' is main's local-rail grant path (0011).
    (OLD.state='prepared' AND NEW.state IN ('blocked','cancelled','reconciling','activating','authorized')) OR
    (OLD.state='activating' AND NEW.state IN ('ready','reconciling','cancelled')) OR
    (OLD.state='ready' AND NEW.state IN ('authorizing','reconciling','cancelled')) OR
    (OLD.state='authorizing' AND NEW.state IN ('authorized','declined','reconciling')) OR
    (OLD.state='reconciling' AND NEW.state IN ('authorized','declined','cancelled','ready'))
  ) THEN RAISE EXCEPTION 'Invalid payment operation transition' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TABLE payment_activations (
  payment_id TEXT PRIMARY KEY REFERENCES payment_operations(id),
  run_id TEXT NOT NULL REFERENCES run_executions(run_id),
  generation INTEGER NOT NULL,
  rail_epoch TEXT NOT NULL,
  grant_record JSONB NOT NULL,
  verification JSONB NOT NULL,
  checkout_snapshot JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_payment_activations BEFORE UPDATE OR DELETE ON payment_activations
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
CREATE TABLE payment_outcomes (
  payment_id TEXT PRIMARY KEY REFERENCES payment_activations(payment_id),
  event_id TEXT NOT NULL UNIQUE,
  record JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER immutable_payment_outcomes BEFORE UPDATE OR DELETE ON payment_outcomes
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
