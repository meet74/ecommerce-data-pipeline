"""Import workflows/ecommerce-daily-summary.json into a throwaway n8n and run it end to end.

The Slack nodes are swapped for HTTP Request nodes that post to a local fake webhook, so no
Slack credentials are needed. Two runs: one against a working pipeline (summary expected),
one with the sources unreachable (failure alert expected).

    N8N_CMD="node /path/to/n8n/bin/n8n" python scripts/check_workflow.py

The mock sources must already be running (make serve) on MOCK_PORT (default 8100).
Note: n8n 2.x ships with the Execute Command node disabled; this script sets NODES_EXCLUDE=[].
"""
import copy
import http.server
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
N8N = shlex.split(os.environ.get("N8N_CMD", "n8n"))
PORT = os.environ.get("MOCK_PORT", "8100")
received = []


class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def variant() -> dict:
    wf = json.loads((ROOT / "workflows" / "ecommerce-daily-summary.json").read_text())
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.scheduleTrigger":      # the CLI can only start from a manual trigger
            n["type"], n["typeVersion"], n["parameters"] = "n8n-nodes-base.manualTrigger", 1, {}
        if n["type"] == "n8n-nodes-base.slack":
            body = "={{ JSON.stringify({ text: $json.text, blocks: $json.blocks ? JSON.parse($json.blocks).blocks : undefined }) }}"
            n["type"], n["typeVersion"] = "n8n-nodes-base.httpRequest", 4.2
            n["parameters"] = {"method": "POST", "url": "http://127.0.0.1:8777/hook", "sendBody": True, "contentType": "raw",
                               "rawContentType": "application/json", "body": body}
            n.pop("credentials", None)
    return wf


def n8n(args, env):
    return subprocess.run(N8N + args, env=env, capture_output=True, text=True, timeout=600)


def run_once(name: str, extra_env: dict) -> tuple[bool, str]:
    folder = tempfile.mkdtemp()
    work = Path(tempfile.mkdtemp())
    env = dict(os.environ, N8N_USER_FOLDER=folder, N8N_DIAGNOSTICS_ENABLED="false", NODES_EXCLUDE="[]", N8N_PORT=os.environ.get("N8N_CHECK_PORT", "5792"),
               N8N_RUNNERS_BROKER_PORT=os.environ.get("N8N_CHECK_BROKER_PORT", "5791"), PIPELINE_DIR=str(ROOT),
               DUCKDB_PATH=str(work / "wh.duckdb"), LANDING_DIR=str(work / "landing"), REPORT_DIR=str(work / "reports"),
               PATH=str(ROOT / ".venv" / "bin") + os.pathsep + os.environ["PATH"], **extra_env)
    wf_file = work / "wf.json"
    wf_file.write_text(json.dumps(variant()))
    imp = n8n(["import:workflow", f"--input={wf_file}"], env)
    if "Successfully imported" not in imp.stdout + imp.stderr:
        return False, "import failed: " + (imp.stdout + imp.stderr)[-500:]
    wid = n8n(["list:workflow"], env).stdout.strip().splitlines()[-1].split("|")[0]
    received.clear()
    res = n8n(["execute", f"--id={wid}"], env)
    return True, res.stdout[-800:] + res.stderr[-800:]


if __name__ == "__main__":
    srv = http.server.HTTPServer(("127.0.0.1", 8777), Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ok = True

    good_env = {"SHOPIFY_BASE_URL": f"http://127.0.0.1:{PORT}/shopify", "STRIPE_BASE_URL": f"http://127.0.0.1:{PORT}/stripe"}
    imported, log = run_once("healthy", good_env)
    summary_posts = [r for r in received if r.get("blocks")]
    print("import ok:", imported, "| healthy run posted Slack blocks:", bool(summary_posts))
    if summary_posts:
        print("   header:", summary_posts[0]["blocks"][0]["text"]["text"])
    ok &= imported and bool(summary_posts)

    imported, log = run_once("broken", {"SHOPIFY_BASE_URL": "http://127.0.0.1:9/shopify", "STRIPE_BASE_URL": "http://127.0.0.1:9/stripe",
                                        "MAX_RETRIES": "1", "BACKOFF_BASE_SECONDS": "0.01"})
    alerts = [r for r in received if "needs attention" in (r.get("text") or "")]
    print("broken run posted failure alert:", bool(alerts))
    if alerts:
        print("   ", alerts[0]["text"].splitlines()[0], "|", alerts[0]["text"].splitlines()[1][:100])
    ok &= bool(alerts)
    sys.exit(0 if ok else 1)
