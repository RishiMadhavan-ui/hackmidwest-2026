"""CLI: python -m shopper "Buy a USB-C laptop charger under $40" --mandate mnd_..."""

import argparse
import json
import logging

from provenance.outbox import OutboxSink
from provenance.redact import redact_text
from provenance.sink import MemorySink
from shopper.runs import StartRun, run_shopper, trace_sinks


def main() -> None:
  parser = argparse.ArgumentParser(prog="shopper", description="Run the Leash demo shopper once.")
  parser.add_argument("task", help="What to buy, in plain words")
  parser.add_argument("--mandate", required=True, help="Leash mandate id to use")
  parser.add_argument("--run-id", required=True, help="Run id from a fresh human launch")
  parser.add_argument("--launch-id", required=True, help="One-use human launch reference")
  parser.add_argument("--start-url", help="Store page to start from")
  parser.add_argument(
    "--scripted-sku",
    help="Labeled fixture mode: script the shopper to check out this SKU (real tools)",
  )
  parser.add_argument("--claim-sku", help="Scripted mode: the SKU to claim to Leash")
  args = parser.parse_args()
  req = StartRun(
    task=args.task,
    mandate_id=args.mandate,
    start_url=args.start_url,
    agent_mode="scripted" if args.scripted_sku else "live",
    sku=args.scripted_sku,
    claim_sku=args.claim_sku,
    run_id=args.run_id,
    launch_id=args.launch_id,
  )
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

  run_id = req.run_id
  trace = MemorySink()
  label = "SCRIPTED FIXTURE (simulated agent)" if req.agent_mode == "scripted" else "live model"
  print(f"run {run_id} [{label}]")
  sinks = [trace, *trace_sinks(req)]
  output = run_shopper(run_id, req, sinks)
  for sink in sinks:
    if isinstance(sink, OutboxSink) and not sink.flush(timeout=15):
      print(f"  {sink.pending_count()} trace events still spooled; they'll be sent on next start")

  # Everything printed here already went through redact().
  for event in trace.events:
    if event["type"] == "agent.tool.after":
      decision = event.get("policy_decision") or event["status"]
      print(f"  {event['tool_name']:<18} {decision:<12} {event['tool_result_summary'][:100]!r}")
    elif event["type"] == "provenance.source":
      flags = ", ".join(event["hidden_suspicious_phrases"]) or "none"
      print(f"  source {event['url']} hidden={event['hidden_text_detected']} phrases={flags}")
  print()
  print(redact_text(output))
  print(json.dumps({"run_id": run_id, "events": len(trace.events)}))


if __name__ == "__main__":
  main()
