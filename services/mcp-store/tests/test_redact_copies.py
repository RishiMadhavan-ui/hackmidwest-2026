"""The agents service and this server must redact identically."""

from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_redaction_code_matches_the_agents_service():
  # Both services build from their own folders, so each carries a copy of the
  # redaction rules. They must never drift: change one, change both.
  ours = (HERE / "evidence" / "redact.py").read_text()
  theirs = (HERE.parent / "agents" / "provenance" / "redact.py").read_text()
  assert ours == theirs
