"""Whole pipeline through the CLI against the mock sources: extract, load, dbt, tests, report."""
import json
import os

import pytest

from pipeline.__main__ import main
from pipeline.config import Settings
from pipeline.warehouse import connect

T0 = "2025-03-15T23:59:59Z"
PG_URL = os.environ.get("TEST_POSTGRES_URL")
TARGETS = ["duckdb"] + (["postgres"] if PG_URL else [])


def reset_postgres(settings):
    with connect(settings, "postgres") as wh:
        for schema in ("raw", "meta", "staging", "intermediate", "marts"):
            wh.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(params=TARGETS)
def env(request, tmp_path, monkeypatch, server):
    target = request.param
    monkeypatch.setenv("SHOPIFY_BASE_URL", server.base + "/shopify")
    monkeypatch.setenv("STRIPE_BASE_URL", server.base + "/stripe")
    monkeypatch.setenv("LANDING_DIR", str(tmp_path / "landing"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "wh.duckdb"))
    monkeypatch.setenv("BACKOFF_BASE_SECONDS", "0.01")
    if target == "postgres":
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        reset_postgres(Settings.from_env())
    return target, tmp_path


def issue_counts(settings, target):
    with connect(settings, target) as wh:
        return dict(wh.query("SELECT issue_type, COUNT(*) FROM marts.fct_payment_reconciliation GROUP BY issue_type"))


def test_full_then_incremental_run(env, server, small_ds, capsys):
    target, tmp = env
    server.set_as_of(T0)
    main(["all", "--target", target])                       # first run on a half-loaded source
    first_report = json.loads((tmp / "reports" / "summary.json").read_text())

    server.set_as_of("2025-03-31T23:59:59Z")                # the rest of the quarter arrives
    assert main(["all", "--target", target]) == 0
    settings = Settings.from_env()

    with connect(settings, target) as wh:
        runs = [r[0] for r in wh.query("SELECT run_id FROM meta.run_log WHERE source <> 'dbt' GROUP BY run_id ORDER BY MIN(started_at)")]
        read = {r[0]: r[1] for r in wh.query("SELECT run_id, SUM(rows_read) FROM meta.run_log WHERE source <> 'dbt' GROUP BY run_id")}
    assert len(runs) == 2
    assert read[runs[1]] > 0
    # the second run still has to read everything that changed after the watermark, but not the whole source
    total_ids = sum(small_ds.stats["distinct_ids"].values())
    assert read[runs[0]] + read[runs[1]] >= total_ids

    # every planted mismatch is found, and nothing else
    truth = small_ds.truth
    got = issue_counts(settings, target)
    for kind in ("missing_charge", "orphan_charge", "amount_mismatch", "currency_mismatch", "refund_mismatch"):
        assert got.get(kind, 0) == len(truth[kind]), kind
    assert got.get("pending_charge", 0) == 0

    # outputs
    summary = json.loads((tmp / "reports" / "summary.json").read_text())
    assert summary["report_date"] == "2025-03-31" and summary["data_tests"]["failed"] == 0
    assert summary["report_date"] != first_report["report_date"]
    assert summary["reconciliation"]["issues"] == sum(len(truth[k]) for k in ("missing_charge", "orphan_charge", "amount_mismatch", "currency_mismatch", "refund_mismatch"))
    html = (tmp / "reports" / "dashboard.html").read_text()
    assert "Cohort retention" in html and "Payment reconciliation" in html


def test_rerun_with_no_source_changes_writes_nothing(env, server):
    target, tmp = env
    assert main(["all", "--target", target]) == 0
    assert main(["extract-load", "--target", target]) == 0
    settings = Settings.from_env()
    with connect(settings, target) as wh:
        last = wh.scalar("SELECT run_id FROM meta.run_log WHERE source <> 'dbt' ORDER BY started_at DESC, run_id DESC LIMIT 1")
        written = wh.scalar("SELECT SUM(rows_written) FROM meta.run_log WHERE run_id = ?", [last])
        read = wh.scalar("SELECT SUM(rows_read) FROM meta.run_log WHERE run_id = ?", [last])
    assert written == 0
    assert read < 50
