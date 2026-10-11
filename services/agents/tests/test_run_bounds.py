"""Submission limits reject excess work rather than unbounded queued execution."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from shopper.runs import RunManager, StartRun


def test_simultaneous_submissions_cannot_exceed_pending_work_limit():
  manager = RunManager()
  def submit(index):
    try:
      manager.start(StartRun(task="Buy a charger", mandate_id="mnd_test",
        run_id=f"run_test_{index}", launch_id=f"launch_test_{index}"))
      return 202
    except HTTPException as error:
      return error.status_code
  try:
    with patch.object(manager._pool, "submit") as work, ThreadPoolExecutor(max_workers=8) as callers:
      results = list(callers.map(submit, range(32)))
      assert results.count(202) == work.call_count == len(manager.runs) == 16
      assert results.count(429) == 16
  finally:
    manager._pool.shutdown(wait=True)


@pytest.mark.parametrize("body", [
  {"task": "x" * 4001},
  {"task": "Buy a charger", "arbitrary_provider_key": "not allowed"},
  {"task": "Buy a charger", "agent_id": "agt_test"},
])
def test_unbounded_or_ambiguous_worker_inputs_are_rejected(body):
  with pytest.raises(ValidationError):
    StartRun.model_validate(body)
