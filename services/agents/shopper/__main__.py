"""CLI: python -m shopper "Buy a USB-C laptop charger under $40" --mandate mnd_..."""

import argparse
import json
import logging

from provenance.redact import redact_text
from provenance.sink import MemorySink, default_sinks
from shopper.agent import task_prompt
from shopper.runs import new_run_id, run_shopper


def main() -> None:
  parser = argparse.ArgumentParser(prog="shopper", description="Run the Leash demo shopper once.")
  parser.add_argument("task", help="What to buy, in plain words")
  parser.add_argument("--mandate", help="Leash mandate id to use")
  parser.add_argument("--start-url", help="Store page to start from")
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

  run_id = new_run_id()
  trace = MemorySink()
  print(f"run {run_id}")
  output = run_shopper(
    run_id, task_prompt(args.task, args.mandate, args.start_url), [trace, *default_sinks()]
  )

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
