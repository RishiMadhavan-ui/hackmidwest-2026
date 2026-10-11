-- Forward-only V2 migration: preserve historical PAUSE intents and evidence.
-- Emergency stops now require CLOSED; PAUSED is not confirmation of closure.
ALTER TABLE card_control_operations
  DROP CONSTRAINT card_control_operations_requested_state_check;
ALTER TABLE card_control_operations
  ADD CONSTRAINT card_control_operations_requested_state_check
  CHECK (requested_state IN ('PAUSED','CLOSED'));
