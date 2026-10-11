"""One append-only write path; commit-ordered sequences are safe SSE cursors."""

from psycopg.types.json import Jsonb


def append_event(conn, record: dict, *, duplicate_ok: bool = False) -> bool:
  # BIGSERIAL alone is allocation-ordered, not commit-ordered. Without this
  # transaction lock a slow earlier insert can commit behind a replay cursor.
  conn.execute("SELECT pg_advisory_xact_lock(781202606)")
  suffix = " ON CONFLICT (event_id) DO NOTHING" if duplicate_ok else ""
  row = conn.execute(
    "INSERT INTO audit_events (event_id, user_id, record) VALUES (%s, %s, %s)"
    + suffix
    + " RETURNING event_id",
    (record["event_id"], record["user_id"], Jsonb(record)),
  ).fetchone()
  if row is None:
    return False
  conn.execute(
    "INSERT INTO audit_deliveries (event_id) VALUES (%s)", (record["event_id"],)
  )
  namespace = conn.execute("SELECT id,operator_user_id FROM attack_lab_namespaces WHERE demo_user_id=%s",
                           (record["user_id"],)).fetchone() if record["user_id"].startswith("usr_lab_") else None
  if namespace:
    import hashlib
    mirrored = {**record, "event_id": "evt_"+hashlib.sha256(("lab:"+record["event_id"]).encode()).hexdigest(),
      "user_id": namespace["operator_user_id"],
      "data": {**record.get("data", {}), "lab_namespace_id": namespace["id"],
               "demo_user_id": record["user_id"], "source_event_id": record["event_id"]}}
    append_event(conn, mirrored, duplicate_ok=True)
  return True
