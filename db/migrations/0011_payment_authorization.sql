-- Enable durable grant authorization (still local-rail charge at the merchant).
-- prepared -> authorized is additive; blocked/cancelled/reconciling unchanged.

ALTER TABLE payment_operations DROP CONSTRAINT IF EXISTS payment_operations_state_check;
ALTER TABLE payment_operations ADD CONSTRAINT payment_operations_state_check
  CHECK (state IN ('prepared', 'blocked', 'cancelled', 'reconciling', 'authorized'));

CREATE OR REPLACE FUNCTION leash_guard_payment_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Payment operations cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(OLD) - ARRAY['state','revision','reason','error_status','error_detail','updated_at'])
     IS DISTINCT FROM
     (to_jsonb(NEW) - ARRAY['state','revision','reason','error_status','error_detail','updated_at']) THEN
    RAISE EXCEPTION 'Payment operation identity is immutable' USING ERRCODE='23514';
  END IF;
  IF OLD.state <> 'prepared'
     OR NEW.state NOT IN ('blocked', 'cancelled', 'reconciling', 'authorized')
     OR NEW.revision <> OLD.revision + 1 THEN
    RAISE EXCEPTION 'Invalid preflight operation transition' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION leash_guard_preflight_result() RETURNS trigger LANGUAGE plpgsql AS $$
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
  IF NOT FOUND THEN
    RETURN NEW;
  END IF;
  IF (NEW.user_id,NEW.agent_id,NEW.run_id,NEW.mandate_id,NEW.mandate_version,NEW.checkout_id)
      IS DISTINCT FROM
     (operation.user_id,operation.agent_id,operation.run_id,operation.mandate_id,operation.mandate_version,operation.checkout_id)
     OR operation.state <> 'prepared'
     OR NEW.verification_id IS NULL
     OR NEW.checkout_hash IS NULL
     OR NEW.record->>'id' IS DISTINCT FROM NEW.id
     OR NEW.record->>'verification_id' IS DISTINCT FROM NEW.verification_id THEN
    RAISE EXCEPTION 'Invalid payment attempt scope or evidence' USING ERRCODE='23514';
  END IF;
  IF NEW.status = 'blocked' THEN
    IF NEW.grant_id IS NOT NULL OR NEW.instrument_token IS NOT NULL
       OR NEW.record->>'status' IS DISTINCT FROM 'blocked'
       OR NEW.record->'grant_id' IS DISTINCT FROM 'null'::jsonb
       OR NEW.record->'payment_result' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE EXCEPTION 'Invalid blocked preflight result' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.status = 'approved' THEN
    IF NEW.grant_id IS NULL OR NEW.instrument_token IS NULL
       OR NEW.record->>'status' IS DISTINCT FROM 'approved'
       OR NEW.record->>'grant_id' IS DISTINCT FROM NEW.grant_id
       OR NEW.record->'payment_result' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE EXCEPTION 'Invalid authorized payment result' USING ERRCODE='23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'Unsupported payment attempt status for ledger operations' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

-- Merchant-owned frozen evidence is allowed; spending still recorded separately.
ALTER TABLE checkout_observations DROP CONSTRAINT IF EXISTS checkout_observations_evidence_assessment_check;
ALTER TABLE checkout_observations ADD CONSTRAINT checkout_observations_evidence_assessment_check
  CHECK (
    jsonb_typeof(evidence_assessment) = 'object'
    AND evidence_assessment ? 'status'
    AND evidence_assessment ? 'financial_authority'
    AND (evidence_assessment->>'status') IN ('observed_unverified', 'merchant_owned_frozen')
    AND (evidence_assessment->>'financial_authority') IN ('true', 'false')
  );
