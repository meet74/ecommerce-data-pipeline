"""Run the dbt project as a subprocess and summarise run_results.json."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import ROOT, Settings

DBT_DIR = ROOT / "dbt_project"


def dbt_executable() -> list[str]:
    found = shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")
    return [found] if Path(found).exists() else [sys.executable, "-m", "dbt.cli.main"]


def dbt_env(settings: Settings, target: str) -> dict[str, str]:
    env = dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS="false", DBT_PROFILES_DIR=str(DBT_DIR))
    if target == "duckdb":
        env["DUCKDB_PATH"] = str(settings.path(settings.duckdb_path))
    else:
        from sqlalchemy.engine import make_url
        url = make_url(settings.database_url)
        env.update(PGHOST=url.host or "localhost", PGPORT=str(url.port or 5432), PGUSER=url.username or "",
                   PGPASSWORD=url.password or "", PGDATABASE=url.database or "")
    return env


def run_dbt(settings: Settings, target: str, command: str, extra: list[str] | None = None) -> dict:
    cmd = dbt_executable() + [command, "--project-dir", str(DBT_DIR), "--target", target, "--no-version-check"] + (extra or [])
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=DBT_DIR, env=dbt_env(settings, target), capture_output=True, text=True)
    duration = time.perf_counter() - t0
    results_file = DBT_DIR / "target" / "run_results.json"
    counts: dict[str, int] = {}
    failures: list[dict] = []
    if results_file.exists():
        for r in json.loads(results_file.read_text())["results"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] in ("fail", "error", "warn"):
                failures.append({"node": r["unique_id"].split(".")[2],
                                 "status": r["status"], "rows": r.get("failures"), "message": (r.get("message") or "")[:200]})
    return {"command": command, "returncode": proc.returncode, "duration_s": round(duration, 2),
            "counts": counts, "problems": failures, "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-800:]}


def transform(settings: Settings, target: str) -> list[dict]:
    seed = run_dbt(settings, target, "seed")
    if seed["returncode"] != 0:
        return [seed]
    return [seed, run_dbt(settings, target, "run")]


def test(settings: Settings, target: str) -> dict:
    return run_dbt(settings, target, "test")
