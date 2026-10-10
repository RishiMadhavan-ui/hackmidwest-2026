"""Upload raw page snapshots to Akamai Object Storage (S3-compatible).

If storage isn't configured or the upload fails, the record says so plainly.
The sha256 and excerpt still go out with the provenance event; we never
pretend a snapshot exists when it doesn't.
"""

import logging
import os
from typing import Any

log = logging.getLogger("leash.provenance")

# TODO: replace with the exact OBJ_* names from the Akamai workshop starter
# once Cameron confirms them (spec section 24, item 4).
ENV_ENDPOINT = "OBJ_ENDPOINT"
ENV_BUCKET = "OBJ_BUCKET"
ENV_ACCESS_KEY = "OBJ_ACCESS_KEY"
ENV_SECRET_KEY = "OBJ_SECRET_KEY"


def snapshot_key(run_id: str, sha256: str) -> str:
  return f"runs/{run_id}/{sha256}.html"


def upload_snapshot(run_id: str, sha256: str, html: str) -> dict[str, Any]:
  endpoint = os.environ.get(ENV_ENDPOINT)
  bucket = os.environ.get(ENV_BUCKET)
  access_key = os.environ.get(ENV_ACCESS_KEY)
  secret_key = os.environ.get(ENV_SECRET_KEY)
  if not (endpoint and bucket and access_key and secret_key):
    return {"storage": "none", "reason": "object storage not configured"}

  key = snapshot_key(run_id, sha256)
  try:
    import boto3  # imported lazily so tests and local runs don't pay for it

    client = boto3.client(
      "s3",
      endpoint_url=endpoint,
      aws_access_key_id=access_key,
      aws_secret_access_key=secret_key,
    )
    client.put_object(Bucket=bucket, Key=key, Body=html.encode(), ContentType="text/html")
  except Exception as exc:  # noqa: BLE001 - storage trouble must not crash the run
    log.warning("snapshot upload failed (%s) for %s", type(exc).__name__, key)
    return {"storage": "none", "reason": f"upload failed: {type(exc).__name__}"}
  return {"storage": "object_storage", "bucket": bucket, "key": key}
