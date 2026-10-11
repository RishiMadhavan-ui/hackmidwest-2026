"""Built Next + real local store containment smoke; no DB, models or provider."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]


def free_port():
  with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    return sock.getsockname()[1]


class AttackLabHttpTests(unittest.TestCase):
  def test_lab_001_003_004_built_web_and_direct_store_deny_attack_selection(self):
    standalone = ROOT / "web/.next/standalone"
    self.assertTrue((standalone / "server.js").exists(), "Run pnpm build first")
    node = shutil.which("node")
    self.assertIsNotNone(node)
    ports = [free_port(), free_port()]
    while ports[0] == ports[1]:
      ports[1] = free_port()
    origins = [f"http://127.0.0.1:{port}" for port in ports]
    base = {key: value for key, value in os.environ.items() if key.upper() in {
      "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "PATHEXT",
    }}
    children = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryFile() as logs:
      try:
        children.append(subprocess.Popen([
          sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
          "--port", str(ports[0]), "--log-level", "error",
        ], cwd=ROOT / "services/store", env={
          **base, "STORE_API_TOKEN": "isolated-smoke-" + "s" * 32,
          "STORE_EVIL_MODE": "1", "ATTACK_LAB_ENABLED": "1",
        }, stdout=logs, stderr=logs, creationflags=flags))
        children.append(subprocess.Popen([node, "server.js"], cwd=standalone, env={
          **base, "PORT": str(ports[1]), "HOSTNAME": "127.0.0.1",
          "STORE_ORIGIN": origins[0], "API_ORIGIN": "http://127.0.0.1:1",
        }, stdout=logs, stderr=logs, creationflags=flags))
        with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
          for origin, path in zip(origins, ["/products/chg-65w", "/store/products/chg-65w"]):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
              try:
                if client.get(origin + path).status_code == 200:
                  break
              except httpx.HTTPError:
                pass
              if any(child.poll() is not None for child in children):
                self.fail("Owned local service exited before readiness")
              time.sleep(0.1)
            else:
              self.fail("Owned local service not ready")
            clean = client.get(origin + path)
            self.assertEqual(clean.status_code, 200)
            self.assertNotIn("fulfillmentNote", clean.text)
            self.assertEqual(clean.headers["cache-control"], "no-store")
            for query in ["evil=1", "evil=true", "evil=0&evil=1", "evil=1&evil=0"]:
              with self.subTest(origin=origin, query=query):
                denied = client.get(origin + path + "?" + query)
                self.assertEqual(denied.status_code, 403)
                self.assertEqual(denied.json()["detail"], "Attack Lab execution is disabled")
      finally:
        for child in reversed(children):
          child.terminate()
          try:
            child.wait(timeout=5)
          except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


if __name__ == "__main__":
  unittest.main(verbosity=2)
