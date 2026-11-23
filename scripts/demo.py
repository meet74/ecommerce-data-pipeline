"""Start the mock sources, run the whole pipeline once, print the Slack payload (dry run)."""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PORT = os.environ.get("MOCK_PORT", "8100")
env = dict(os.environ, PYTHONPATH=str(ROOT))

server = subprocess.Popen([sys.executable, "-m", "mock_sources", "--port", PORT], cwd=ROOT, env=env)
try:
    for _ in range(120):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(1)
    else:
        raise SystemExit("mock server did not start")
    env.update(SHOPIFY_BASE_URL=f"http://127.0.0.1:{PORT}/shopify", STRIPE_BASE_URL=f"http://127.0.0.1:{PORT}/stripe")
    rc = subprocess.run([sys.executable, "-m", "pipeline", "all"], cwd=ROOT, env=env).returncode
    subprocess.run([sys.executable, "-m", "pipeline", "slack", "--dry-run"], cwd=ROOT, env=env)
    sys.exit(rc)
finally:
    server.terminate()
