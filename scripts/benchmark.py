"""Measure a full run, an incremental run and a no-change run against the mock sources.

Writes docs/benchmark.json. The source clock starts one day before the end of the data,
so the incremental run picks up exactly one day of new orders plus every late update that
landed in that day.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
WORK = ROOT / "data" / "bench"
T_FULL, T_INCR = "2026-06-29T23:59:59Z", "2026-06-30T23:59:59Z"

shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
env = dict(os.environ, PYTHONPATH=str(ROOT), SHOPIFY_BASE_URL=BASE + "/shopify", STRIPE_BASE_URL=BASE + "/stripe",
           DUCKDB_PATH=str(WORK / "warehouse.duckdb"), LANDING_DIR=str(WORK / "landing"), REPORT_DIR=str(WORK / "reports"))
env.pop("SLACK_WEBHOOK_URL", None)

server = subprocess.Popen([sys.executable, "-m", "mock_sources", "--port", str(PORT), "--as-of", T_FULL], cwd=ROOT, env=env)


def pipeline(*args):
    t = time.perf_counter()
    rc = subprocess.run([sys.executable, "-m", "pipeline", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    return rc, round(time.perf_counter() - t, 1)


def run_log(run_filter):
    import duckdb
    con = duckdb.connect(env["DUCKDB_PATH"], read_only=True)
    rows = con.execute(f"""SELECT entity, rows_read, rows_inserted, rows_updated, rows_unchanged, rows_written, http_requests,
                                  http_retries, rate_limited, duration_s FROM meta.run_log WHERE source <> 'dbt' AND {run_filter}
                           ORDER BY started_at, entity""").fetchall()
    con.close()
    cols = ["entity", "rows_read", "inserted", "updated", "unchanged", "rows_written", "requests", "retries", "rate_limited", "seconds"]
    return [dict(zip(cols, r)) for r in rows]


def run_ids():
    import duckdb
    con = duckdb.connect(env["DUCKDB_PATH"], read_only=True)
    out = [r[0] for r in con.execute("SELECT run_id FROM meta.run_log WHERE source <> 'dbt' GROUP BY run_id ORDER BY MIN(started_at)").fetchall()]
    con.close()
    return out


try:
    for _ in range(180):
        try:
            if httpx.get(BASE + "/health", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(1)
    else:
        raise SystemExit("mock server did not start")

    result = {}
    rc, secs = pipeline("all")
    assert rc.returncode == 0, rc.stdout[-2000:] + rc.stderr[-2000:]
    summary = json.loads((WORK / "reports" / "summary.json").read_text())
    ids = run_ids()
    result["full_run"] = {"wall_seconds": secs, "stages_seconds": summary["pipeline"]["stages_seconds"], "entities": run_log(f"run_id = '{ids[0]}'"),
                          "data_tests": summary["data_tests"]}

    httpx.post(BASE + "/admin/as_of", json={"as_of": T_INCR})
    rc, secs = pipeline("all")
    assert rc.returncode == 0, rc.stdout[-2000:] + rc.stderr[-2000:]
    summary = json.loads((WORK / "reports" / "summary.json").read_text())
    ids = run_ids()
    result["incremental_run"] = {"wall_seconds": secs, "stages_seconds": summary["pipeline"]["stages_seconds"], "entities": run_log(f"run_id = '{ids[1]}'"),
                                 "data_tests": summary["data_tests"]}

    rc, secs = pipeline("extract-load")
    ids = run_ids()
    result["unchanged_rerun"] = {"wall_seconds": secs, "entities": run_log(f"run_id = '{ids[2]}'")}

    import duckdb
    con = duckdb.connect(env["DUCKDB_PATH"], read_only=True)
    truth = httpx.get(BASE + "/admin/truth").json()
    detected = dict(con.execute("SELECT issue_type, COUNT(*) FROM marts.fct_payment_reconciliation GROUP BY 1").fetchall())
    kinds = ["missing_charge", "orphan_charge", "amount_mismatch", "currency_mismatch", "refund_mismatch"]
    result["reconciliation"] = {k: {"injected": len(truth[k]), "detected": detected.get(k, 0)} for k in kinds}
    flags = con.execute("SELECT SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END), SUM(CASE WHEN is_test THEN 1 ELSE 0 END), "
                        "SUM(CASE WHEN is_cancelled AND NOT is_test AND NOT is_duplicate THEN 1 ELSE 0 END) FROM staging.stg_shopify__orders").fetchone()
    cdup = con.execute("SELECT SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END) FROM staging.stg_shopify__customers").fetchone()[0]
    result["cleaning"] = {
        "duplicate_orders": {"injected": truth["duplicate_orders"], "flagged": int(flags[0])},
        "test_orders": {"injected": truth["test_orders"], "flagged": int(flags[1])},
        "duplicate_customers": {"injected": truth["duplicate_customers"], "merged": int(cdup)},
        "cancelled_orders": {"injected": truth["cancelled_orders"], "flagged": int(flags[2])},
    }
    tables = {}
    for schema, name in con.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN ('raw','marts') "
                                    "AND table_type = 'BASE TABLE' ORDER BY 1, 2").fetchall():
        tables[f"{schema}.{name}"] = con.execute(f"SELECT COUNT(*) FROM {schema}.{name}").fetchone()[0]
    result["table_rows"] = tables
    result["raw_rows_total"] = sum(v for k, v in tables.items() if k.startswith("raw."))
    result["orders_valid"] = con.execute("SELECT COUNT(*) FROM marts.fct_orders").fetchone()[0]
    result["customers"] = con.execute("SELECT COUNT(*) FROM marts.dim_customers").fetchone()[0]
    result["date_range"] = [str(x) for x in con.execute("SELECT MIN(date_day), MAX(date_day) FROM marts.daily_kpis").fetchone()]
    con.close()
    result["mock_server"] = httpx.get(BASE + "/admin/state").json()["faults"]
    out = ROOT / "docs" / "benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: result[k] for k in ("reconciliation", "cleaning", "raw_rows_total", "orders_valid", "customers", "mock_server")}, indent=2))
    for name in ("full_run", "incremental_run", "unchanged_rerun"):
        r = result[name]
        print(name, r["wall_seconds"], r.get("stages_seconds"), "rows_read", sum(e["rows_read"] for e in r["entities"]),
              "rows_written", sum(e["rows_written"] for e in r["entities"]), r.get("data_tests"))
    shutil.copy(WORK / "reports" / "dashboard.html", ROOT / "reports" / "dashboard.html")
    shutil.copy(WORK / "reports" / "summary.json", ROOT / "reports" / "summary.json")
finally:
    server.terminate()
