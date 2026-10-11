-- Operator control plane only. No scenario, grant, instrument or charge is enabled.
CREATE TABLE attack_lab_namespaces (
  id TEXT PRIMARY KEY CHECK (id ~ '^lab_[0-9a-f]{32}$'),
  operator_user_id TEXT NOT NULL UNIQUE REFERENCES leash_users(id),
  demo_user_id TEXT NOT NULL UNIQUE REFERENCES leash_users(id)
    CHECK (demo_user_id ~ '^usr_lab_[0-9a-f]{32}$'),
  enabled BOOLEAN NOT NULL DEFAULT false,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  rail TEXT NOT NULL DEFAULT 'local_payment_rail_simulator'
    CHECK (rail = 'local_payment_rail_simulator'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (operator_user_id <> demo_user_id)
);
CREATE TABLE attack_lab_rate_windows (
  operator_user_id TEXT PRIMARY KEY REFERENCES leash_users(id),
  started_at TIMESTAMPTZ NOT NULL,
  used INTEGER NOT NULL CHECK (used BETWEEN 0 AND 5)
);
CREATE FUNCTION leash_guard_lab_namespace() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Lab scope and history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(OLD) - ARRAY['enabled','revision','updated_at']) IS DISTINCT FROM
     (to_jsonb(NEW) - ARRAY['enabled','revision','updated_at'])
     OR NEW.revision <> OLD.revision + 1 THEN
    RAISE EXCEPTION 'Invalid Lab scope mutation' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guarded_attack_lab_namespaces BEFORE UPDATE OR DELETE ON attack_lab_namespaces
FOR EACH ROW EXECUTE FUNCTION leash_guard_lab_namespace();
