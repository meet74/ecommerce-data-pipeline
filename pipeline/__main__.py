"""Command line entry point: python -m pipeline <command>."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime

from . import ingest, report, slack, summary as summary_mod, transform
from .config import Settings
from .warehouse import connect


def log_dbt(settings: Settings, target: str, run_id: str, entity: str, res: dict, ok: bool) -> None:
    with connect(settings, target) as wh:
        wh.init_schema()
        now = ingest.utcnow()
        ingest.log_run(wh, run_id, "dbt", entity, started_at=now, finished_at=now, duration_s=res["duration_s"],
                       status="success" if ok else "failed", rows_read=None, rows_written=res["counts"].get("success", res["counts"].get("pass")),
                       detail=json.dumps({"counts": res["counts"], "problems": res["problems"][:20]}))


def cmd_extract_load(settings, args, run_id) -> list[dict]:
    with connect(settings, args.target) as wh:
        results = ingest.extract_load(wh, settings, run_id, args.entities, args.full_refresh)
    for r in results:
        print(f"{r['entity']:<20} {r['status']:<8} read={r['rows_read']:>6} inserted={r['inserted']:>6} updated={r['updated']:>5} "
              f"unchanged={r['unchanged']:>5} stale={r['stale']:>3} written={r['rows_written']:>6} "
              f"requests={r['http_requests']:>4} retries={r['http_retries']:>3} {r['duration_s']:>6.2f}s")
    return results


def cmd_transform(settings, args, run_id) -> bool:
    ok = True
    for res in transform.transform(settings, args.target):
        good = res["returncode"] == 0
        print(f"dbt {res['command']:<5} {'ok' if good else 'FAILED'} {res['counts']} {res['duration_s']}s")
        if not good:
            print(res["stdout_tail"], res["stderr_tail"], sep="\n")
            ok = False
        log_dbt(settings, args.target, run_id, res["command"], res, good)
    return ok


def cmd_test(settings, args, run_id) -> tuple[bool, dict]:
    res = transform.test(settings, args.target)
    c = res["counts"]
    tests = {"passed": c.get("pass", 0), "warned": c.get("warn", 0), "failed": c.get("fail", 0) + c.get("error", 0),
             "duration_s": res["duration_s"]}
    print(f"dbt test: {tests['passed']} passed, {tests['warned']} warnings, {tests['failed']} failed ({res['duration_s']}s)")
    for p in res["problems"]:
        print(f"  {p['status']:<5} {p['node']} {p['message'].splitlines()[0] if p['message'] else ''}")
    ok = res["returncode"] == 0 and tests["failed"] == 0
    log_dbt(settings, args.target, run_id, "test", res, ok)
    return ok, tests


def cmd_report(settings, args, run_id, tests=None) -> dict:
    report_date = date.fromisoformat(args.date) if getattr(args, "date", None) else None
    with connect(settings, args.target) as wh:
        s = summary_mod.build_summary(wh, report_date, run_id, tests)
        out = settings.path(settings.report_dir)
        report.write_summary(s, out / "summary.json")
        path = report.build_dashboard(wh, s, out / "dashboard.html")
    print(f"wrote {path} and {out / 'summary.json'}")
    return s


def cmd_slack(settings, args, s=None) -> None:
    if s is None:
        s = json.loads((settings.path(settings.report_dir) / "summary.json").read_text())
    payload = slack.build_payload(s)
    if args.dry_run or not settings.slack_webhook_url:
        if not args.dry_run:
            print("SLACK_WEBHOOK_URL is not set, printing the payload instead", file=sys.stderr)
        print(slack.render(payload))
        return
    print("slack:", slack.send(settings.slack_webhook_url, payload))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    p.add_argument("command", choices=["extract-load", "transform", "test", "report", "slack", "all", "status"])
    p.add_argument("--target", choices=["duckdb", "postgres"], default=None)
    p.add_argument("--db-url", help="SQLAlchemy URL for --target postgres (overrides DATABASE_URL)")
    p.add_argument("--entities", nargs="*", help="e.g. orders charges")
    p.add_argument("--full-refresh", action="store_true", help="ignore the stored watermarks and re-read everything")
    p.add_argument("--date", help="report date, default is the latest day with orders")
    p.add_argument("--dry-run", action="store_true", help="slack: print the payload instead of posting")
    p.add_argument("--notify", action="store_true", help="all: post the Slack summary at the end")
    args = p.parse_args(argv)

    settings = Settings.from_env()
    if args.db_url:
        settings.database_url = args.db_url
        args.target = args.target or "postgres"
    args.target = args.target or settings.target
    settings.target = args.target
    run_id = ingest.new_run_id()

    if args.command == "extract-load":
        return 0 if all(r["status"] == "success" for r in cmd_extract_load(settings, args, run_id)) else 2
    if args.command == "transform":
        return 0 if cmd_transform(settings, args, run_id) else 2
    if args.command == "test":
        return 0 if cmd_test(settings, args, run_id)[0] else 1
    if args.command == "report":
        cmd_report(settings, args, None)
        return 0
    if args.command == "slack":
        cmd_slack(settings, args)
        return 0
    if args.command == "status":
        with connect(settings, args.target) as wh:
            print(wh.query_df("SELECT * FROM meta.watermarks ORDER BY source, entity").to_string(index=False))
            print(wh.query_df("SELECT run_id, source, entity, status, rows_read, rows_written, duration_s FROM meta.run_log "
                              "ORDER BY started_at DESC LIMIT 15").to_string(index=False))
        return 0

    # all: extract -> load -> transform -> test -> report
    stages: dict[str, float] = {}
    t0 = time.perf_counter()
    t = time.perf_counter()
    results = cmd_extract_load(settings, args, run_id)
    stages["extract_load"] = round(time.perf_counter() - t, 2)
    if any(r["status"] != "success" for r in results):
        print("extract/load failed, stopping before transform", file=sys.stderr)
        return 2
    t = time.perf_counter()
    if not cmd_transform(settings, args, run_id):
        return 2
    stages["transform"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    ok, tests = cmd_test(settings, args, run_id)
    stages["test"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    s = cmd_report(settings, args, run_id, tests)
    stages["report"] = round(time.perf_counter() - t, 2)
    stages["total"] = round(time.perf_counter() - t0, 2)
    s["pipeline"]["stages_seconds"] = stages
    s["pipeline"]["status"] = "success" if ok else "failed"
    report.write_summary(s, settings.path(settings.report_dir) / "summary.json")
    print("stages (s):", stages)
    if args.notify:
        cmd_slack(settings, args, s)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
