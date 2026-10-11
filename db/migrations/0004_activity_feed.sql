-- Profile activity feed reads audit_events by user + sequence cursor.
CREATE INDEX IF NOT EXISTS audit_events_user_sequence_idx
  ON audit_events (user_id, sequence);
