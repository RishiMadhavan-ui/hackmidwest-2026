CREATE TABLE attack_lab_mandates (
  mandate_id text PRIMARY KEY REFERENCES mandate_heads(id),
  namespace_id text NOT NULL REFERENCES attack_lab_namespaces(id),
  scenario text NOT NULL CHECK (scenario IN ('legitimate_charger','signature_attack')),
  mode text NOT NULL CHECK (mode IN ('live','scripted')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE attack_lab_runs (
  run_id text PRIMARY KEY REFERENCES agent_runs(id),
  namespace_id text NOT NULL REFERENCES attack_lab_namespaces(id),
  scenario text NOT NULL CHECK (scenario IN ('legitimate_charger','signature_attack')),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
