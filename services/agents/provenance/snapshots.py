"""Upload redacted page snapshots to Akamai Object Storage (S3-compatible).

Pages are redacted before they leave the process, the same as every trace
event. The key stays bound to the ORIGINAL page hash (the source evidence),
and the record adds stored_sha256 for the bytes actually stored, since
redaction can change them.

If storage isn't configured or the upload fails, the record says so plainly.
The sha256 and excerpt still go out with the provenance event; we never
pretend a snapshot exists when it doesn't.
"""

import hashlib
import logging
import os
from typing import Any

from provenance.redact import redact_text

log = logging.getLogger("leash.provenance")

# Same names and boto3 setup as the Akamai workshop starter
# (akamai-developers/akamai-workshop-hackmidwest, .env.example and
# docs/01_knowledge.md). OBJ_KEY_ID there is for cleanup only, so it's unused.
ENV_ENDPOINT = "OBJ_ENDPOINT"
ENV_BUCKET = "OBJ_BUCKET"
ENV_ACCESS_KEY = "OBJ_ACCESS_KEY"
ENV_SECRET_KEY = "OBJ_SECRET_KEY"


def snapshot_key(run_id: str, source_sha256: str) -> str:
  return f"runs/{run_id}/{source_sha256}.html"


def _s3_client(endpoint: str, access_key: str, secret_key: str):
  import boto3  # imported lazily so tests and local runs don't pay for it

  return boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
  )


def upload_snapshot(run_id: str, source_sha256: str, html: str) -> dict[str, Any]:
  endpoint = os.environ.get(ENV_ENDPOINT)
  bucket = os.environ.get(ENV_BUCKET)
  access_key = os.environ.get(ENV_ACCESS_KEY)
  secret_key = os.environ.get(ENV_SECRET_KEY)
  if not (endpoint and bucket and access_key and secret_key):
    return {"storage": "none", "reason": "object storage not configured"}

  body = redact_text(html).encode()
  key = snapshot_key(run_id, source_sha256)
  try:
    client = _s3_client(endpoint, access_key, secret_key)
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/html")
  except Exception as exc:  # noqa: BLE001 - storage trouble must not crash the run
    log.warning("snapshot upload failed (%s) for %s", type(exc).__name__, key)
    return {"storage": "none", "reason": f"upload failed: {type(exc).__name__}"}
  return {
    "storage": "object_storage",
    "bucket": bucket,
    "key": key,
    "stored_sha256": hashlib.sha256(body).hexdigest(),
  }
