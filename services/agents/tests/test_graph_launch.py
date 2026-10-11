import pytest
from fastapi import HTTPException

from shopper.runs import RunManager, StartRun, run_shopper


def test_static_service_credential_cannot_autonomously_register_a_replacement_run():
  manager = RunManager()
  with pytest.raises(HTTPException) as error:
    manager.start(StartRun(task="buy again", mandate_id="mnd_1"))
  assert error.value.status_code == 409
  assert manager.runs == {}
  manager._pool.shutdown()


def test_direct_runner_also_requires_human_launch():
  with pytest.raises(RuntimeError, match="human launch"):
    run_shopper("run_1", StartRun(task="buy", mandate_id="mnd_1"), [])
