"""Bounded background readback and revocation. Never retries a charge."""

import logging
import os
import threading

from authority_errors import AuthorityError
from db import get_conn
from execution import locked, rail
from mandate_service import utc_now
from payment_operations import finish
from purchase_execution import reconcile

logger = logging.getLogger("uvicorn.error")


def reconcile_run(run_id):
  with get_conn() as conn:
    run, lease = locked(conn, run_id, current=False)
    inactive = lease["deadline"] <= utc_now() or (
      lease["lease_until"] is not None and lease["lease_until"] <= utc_now())
    try:
      locked(conn, run_id)
    except AuthorityError:
      inactive = True
    if inactive and not lease["rail_stopped_at"]:
      # Commit cancellation before network I/O. All new tools fail closed even
      # while the rail's independent revocation acknowledgement is pending.
      conn.execute("INSERT INTO run_cancellations(run_id,user_id,requested_at) VALUES (%s,%s,now()) ON CONFLICT DO NOTHING",
                   (run_id,run["user_id"]))
      conn.commit()
      ack = rail("POST", "/internal/execution/stop", {"run_id":run_id,"user_id":run["user_id"]})
      if (ack.get("run_id"),ack.get("user_id"),ack.get("financial_revocation")) != (run_id,run["user_id"],"enforced"):
        raise AuthorityError(503,"Rail revocation is not acknowledged")
      run, lease = locked(conn, run_id, current=False)
      conn.execute("UPDATE run_executions SET rail_stopped_at=COALESCE(rail_stopped_at,now()) WHERE run_id=%s",(run_id,))
      from execution import event
      event(conn,run,"rail_stopped",reason="authority_expired_or_stopped",graph_acknowledged=bool(lease["graph_ack_at"]))
    operations = conn.execute("SELECT * FROM payment_operations WHERE run_id=%s AND state IN ('prepared','activating','ready','authorizing','reconciling') ORDER BY id FOR UPDATE",(run_id,)).fetchall()
    for op in operations:
      if op["state"] == "prepared":
        if inactive:
          finish(conn,op,"cancelled","authority_expired_before_activation")
      else:
        reconcile(conn,op)


def tick():
  # No provider mutation occurs here. An epoch change remains unresolved rather
  # than inferring that a missing cache means an earlier charge never happened.
  with get_conn() as conn:
    rows = conn.execute("""SELECT e.run_id FROM run_executions e
      WHERE (e.rail_stopped_at IS NULL AND (e.deadline<=now()
        OR e.lease_until<=now() OR e.state='terminal'
        OR EXISTS (SELECT 1 FROM run_cancellations c WHERE c.run_id=e.run_id)))
      OR EXISTS (SELECT 1 FROM payment_operations p WHERE p.run_id=e.run_id
        AND p.state IN ('activating','ready','authorizing','reconciling'))
      ORDER BY e.deadline LIMIT 20""").fetchall()
  for row in rows:
    try:
      reconcile_run(row["run_id"])
    except Exception as error:
      logger.warning("Outcome readback pending (%s)",type(error).__name__)


class Reconciler:
  def __init__(self):
    self.stop_event = threading.Event()
    self.thread = threading.Thread(target=self.run,name="leash-outcome-readback",daemon=True)

  def start(self):
    self.thread.start()

  def run(self):
    while not self.stop_event.wait(5):
      try:
        tick()
      except Exception as error:
        logger.warning("Outcome readback unavailable (%s)",type(error).__name__)

  def stop(self):
    self.stop_event.set()
    self.thread.join(timeout=10)


def start():
  if os.getenv("LEASH_EXECUTION_ENABLED") != "1":
    return None
  worker = Reconciler()
  worker.start()
  return worker
