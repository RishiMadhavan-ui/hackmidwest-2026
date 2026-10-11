-- Preflight ledger only: reserved references confer no payment authority.
ALTER TABLE mandate_versions ADD CONSTRAINT mandate_version_hash_identity
  UNIQUE (mandate_id,version,payload_hash);
ALTER TABLE agent_runs ADD CONSTRAINT agent_run_owner_authority_identity
  UNIQUE (id,user_id,agent_id,mandate_id,mandate_version);
CREATE TABLE payment_operations (
  id TEXT PRIMARY KEY CHECK (id ~ '^pay_[A-Za-z0-9_-]+$'),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  agent_id TEXT NOT NULL REFERENCES leash_agents(id),
  run_id TEXT NOT NULL REFERENCES agent_runs(id),
  mandate_id TEXT NOT NULL,
  mandate_version INTEGER NOT NULL,
  mandate_hash TEXT NOT NULL CHECK (mandate_hash ~ '^[0-9a-f]{64}$'),
  checkout_id TEXT NOT NULL,
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  grant_reference TEXT NOT NULL UNIQUE,
  instrument_reference UUID NOT NULL UNIQUE,
  issuance_key UUID NOT NULL UNIQUE,
  authorization_event_id UUID NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'prepared' CHECK (state IN ('prepared','blocked','cancelled','reconciling')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  reason TEXT,
  error_status INTEGER CHECK (error_status BETWEEN 400 AND 599),
  error_detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (mandate_id,mandate_version,mandate_hash)
    REFERENCES mandate_versions(mandate_id,version,payload_hash),
  FOREIGN KEY (run_id,user_id,agent_id,mandate_id,mandate_version)
    REFERENCES agent_runs(id,user_id,agent_id,mandate_id,mandate_version),
  UNIQUE (id,user_id,run_id,mandate_id,mandate_version,mandate_hash),
  UNIQUE (user_id,agent_id,run_id,mandate_id,mandate_version,checkout_id),
  CHECK ((error_status IS NULL) = (error_detail IS NULL)),
  CHECK (error_status IS NULL OR state = 'blocked')
);
-- Across mandate versions/runs: an unresolved attempt bars a replacement.
CREATE UNIQUE INDEX payment_operations_unresolved_mandate
  ON payment_operations(user_id,mandate_id) WHERE state IN ('prepared','reconciling');
CREATE UNIQUE INDEX payment_operations_unresolved_run
  ON payment_operations(run_id) WHERE state IN ('prepared','reconciling');

CREATE TABLE checkout_observations (
  payment_id TEXT PRIMARY KEY REFERENCES payment_operations(id),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  run_id TEXT NOT NULL REFERENCES agent_runs(id),
  mandate_id TEXT NOT NULL,
  mandate_version INTEGER NOT NULL,
  mandate_hash TEXT NOT NULL CHECK (mandate_hash ~ '^[0-9a-f]{64}$'),
  source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  checkout_hash TEXT NOT NULL CHECK (checkout_hash ~ '^[0-9a-f]{64}$'),
  source_facts JSONB NOT NULL CHECK (jsonb_typeof(source_facts)='object'),
  snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot)='object'),
  evidence_assessment JSONB NOT NULL CHECK (
    evidence_assessment @> '{"status":"observed_unverified","financial_authority":false}'::jsonb
  ),
  observed_at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (payment_id,user_id,run_id,mandate_id,mandate_version,mandate_hash)
    REFERENCES payment_operations(id,user_id,run_id,mandate_id,mandate_version,mandate_hash),
  CHECK ((snapshot->>'purchase_attempt_id'=payment_id AND snapshot->>'user_id'=user_id) IS TRUE),
  CHECK ((source_facts->>'facts_hash'=source_hash) IS TRUE)
);
CREATE TRIGGER immutable_checkout_observations BEFORE UPDATE OR DELETE ON checkout_observations
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();

CREATE FUNCTION leash_guard_payment_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Payment operations cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(OLD) - ARRAY['state','revision','reason','error_status','error_detail','updated_at'])
     IS DISTINCT FROM
     (to_jsonb(NEW) - ARRAY['state','revision','reason','error_status','error_detail','updated_at']) THEN
    RAISE EXCEPTION 'Payment operation identity is immutable' USING ERRCODE='23514';
  END IF;
  IF OLD.state <> 'prepared' OR NEW.state NOT IN ('blocked','cancelled','reconciling')
     OR NEW.revision <> OLD.revision + 1 THEN
    RAISE EXCEPTION 'Invalid preflight operation transition' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guarded_payment_operations BEFORE UPDATE OR DELETE ON payment_operations
FOR EACH ROW EXECUTE FUNCTION leash_guard_payment_operation();

-- Preserve original decisions for new ledger operations. Historical rows remain
-- untouched; financial activation will require an explicitly reviewed migration.
CREATE FUNCTION leash_guard_preflight_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE operation payment_operations%ROWTYPE;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    IF EXISTS (SELECT 1 FROM payment_operations WHERE id=OLD.id) THEN
      RAISE EXCEPTION 'Preflight results are immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO operation FROM payment_operations WHERE id=NEW.id;
  IF FOUND AND (
    (NEW.user_id,NEW.agent_id,NEW.run_id,NEW.mandate_id,NEW.mandate_version,NEW.checkout_id)
      IS DISTINCT FROM
    (operation.user_id,operation.agent_id,operation.run_id,operation.mandate_id,operation.mandate_version,operation.checkout_id)
    OR operation.state <> 'prepared' OR NEW.status <> 'blocked'
    OR NEW.grant_id IS NOT NULL OR NEW.instrument_token IS NOT NULL
    OR NEW.verification_id IS NULL OR NEW.checkout_hash IS NULL
    OR NEW.record->>'id' IS DISTINCT FROM NEW.id
    OR NEW.record->>'status' IS DISTINCT FROM 'blocked'
    OR NEW.record->'grant_id' IS DISTINCT FROM 'null'::jsonb
    OR NEW.record->'payment_result' IS DISTINCT FROM 'null'::jsonb
    OR NEW.record->>'verification_id' IS DISTINCT FROM NEW.verification_id
  ) THEN
    RAISE EXCEPTION 'Invalid non-spending preflight result' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guarded_preflight_results BEFORE INSERT OR UPDATE OR DELETE ON payment_attempts
FOR EACH ROW EXECUTE FUNCTION leash_guard_preflight_result();
