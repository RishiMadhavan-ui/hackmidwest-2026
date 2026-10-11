-- Mutable control projections are separate from immutable mandate/run history.
CREATE TABLE user_workflow_controls (
  user_id TEXT PRIMARY KEY REFERENCES leash_users(id),
  stopped BOOLEAN NOT NULL DEFAULT false,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  rail_enforced_at TIMESTAMPTZ
);
CREATE TABLE run_cancellations (
  run_id TEXT PRIMARY KEY REFERENCES agent_runs(id),
  user_id TEXT NOT NULL REFERENCES leash_users(id),
  requested_at TIMESTAMPTZ NOT NULL
);
CREATE TRIGGER immutable_run_cancellations BEFORE UPDATE OR DELETE ON run_cancellations
FOR EACH ROW EXECUTE FUNCTION leash_reject_history_mutation();
