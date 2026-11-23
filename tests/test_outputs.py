import json

from pipeline import slack

SUMMARY = {
    "generated_at": "2026-07-01T07:00:00Z", "report_date": "2026-06-30",
    "day": {"orders": 100, "gross_revenue_cad": 9772.4, "aov_cad": 97.72, "new_orders": 9, "returning_orders": 91,
            "refund_rate": 0.02, "refunds_cad": 227.0, "fees_cad": 376.0, "net_revenue_cad": 9169.0},
    "vs_prev_7d_avg_pct": {"gross_revenue": 18.4, "orders": -3.2, "aov": 4.3, "net_revenue": 20.7},
    "last_7_days": {"gross_revenue_cad": 60531.0, "orders": 638, "net_revenue_cad": 57000.0},
    "top_products_30d": [{"title": "Cedar Burr Grinder", "revenue_cad": 30787.0, "units": 332}],
    "reconciliation": {"rows_checked": 26739, "issues": 2, "issue_rate": 0.0001, "by_type": {"missing_charge": 2}},
    "pipeline": {"status": "success", "rows_read": 500, "rows_written": 120},
    "data_tests": {"passed": 84, "warned": 1, "failed": 0},
}


def test_slack_payload_shape_and_numbers():
    p = slack.build_payload(SUMMARY)
    json.dumps(p)                                              # serialisable
    assert p["blocks"][0]["text"]["text"].endswith("2026-06-30")
    fields = " ".join(f["text"] for f in p["blocks"][1]["fields"])
    assert "$9,772" in fields and "up 18.4%" in fields and "down 3.2%" in fields
    body = json.dumps(p)
    assert "2 missing charge" in body and "84 passed" in body and "Pipeline OK" in body
    assert len(p["blocks"]) <= 50                              # Slack's block limit


def test_slack_payload_flags_failures():
    s = json.loads(json.dumps(SUMMARY))
    s["data_tests"]["failed"] = 2
    assert "NEEDS ATTENTION" in json.dumps(slack.build_payload(s))


def test_slack_payload_with_clean_reconciliation():
    s = json.loads(json.dumps(SUMMARY))
    s["reconciliation"] = {"rows_checked": 10, "issues": 0, "issue_rate": 0, "by_type": {}}
    assert "no mismatches" in json.dumps(slack.build_payload(s))
