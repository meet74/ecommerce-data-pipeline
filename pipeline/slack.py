"""Slack message built from summary.json. The webhook URL comes from SLACK_WEBHOOK_URL."""
from __future__ import annotations

import json
import time

import httpx


def _money(v) -> str:
    return "n/a" if v is None else f"${v:,.0f}"


def _delta(p) -> str:
    if p is None:
        return ""
    arrow = "up" if p >= 0 else "down"
    return f" ({arrow} {abs(p):.1f}% vs 7-day avg)"


def build_payload(s: dict) -> dict:
    d, vs = s["day"], s["vs_prev_7d_avg_pct"]
    rec, pipe, tests = s["reconciliation"], s.get("pipeline", {}), s.get("data_tests", {})
    new_share = d["new_orders"] / d["orders"] * 100 if d["orders"] else 0
    top = "\n".join(f"{i}. {p['title']} - {_money(p['revenue_cad'])} ({p['units']} units)" for i, p in enumerate(s["top_products_30d"], 1))
    recon_line = "no mismatches" if not rec["issues"] else ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in rec["by_type"].items())
    status = "OK" if pipe.get("status", "success") == "success" and not tests.get("failed") else "NEEDS ATTENTION"
    foot = f"Pipeline {status}"
    if pipe:
        foot += f" | {pipe['rows_read']:,} rows read, {pipe['rows_written']:,} written"
    if tests:
        foot += f" | tests: {tests.get('passed', 0)} passed, {tests.get('warned', 0)} warning, {tests.get('failed', 0)} failed"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Store summary for {s['report_date']}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Revenue (CAD, ex tax)*\n{_money(d['gross_revenue_cad'])}{_delta(vs['gross_revenue'])}"},
            {"type": "mrkdwn", "text": f"*Net revenue*\n{_money(d['net_revenue_cad'])}"},
            {"type": "mrkdwn", "text": f"*Orders*\n{d['orders']:,}{_delta(vs['orders'])}"},
            {"type": "mrkdwn", "text": f"*Average order value*\n${d['aov_cad'] or 0:,.2f}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*Customers:* {d['new_orders']} new, {d['returning_orders']} returning ({new_share:.0f}% new)\n"
            f"*Refunds today:* {_money(d['refunds_cad'])} | *Processor fees:* {_money(d['fees_cad'])}\n"
            f"*Last 7 days:* {_money(s['last_7_days']['gross_revenue_cad'])} from {s['last_7_days']['orders']:,} orders"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Top products, last 30 days*\n{top}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*Payment reconciliation:* {rec['issues']} of {rec['rows_checked']:,} rows flagged - {recon_line}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": foot}]},
    ]
    return {"text": f"Store summary {s['report_date']}: {_money(d['gross_revenue_cad'])} revenue, {d['orders']} orders", "blocks": blocks}


def send(url: str, payload: dict, attempts: int = 3) -> int:
    for i in range(attempts):
        try:
            r = httpx.post(url, json=payload, timeout=10)
            if r.status_code < 300:
                return r.status_code
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 1)))
                continue
            r.raise_for_status()
        except httpx.TransportError:
            time.sleep(2 ** i)
    raise RuntimeError("Slack webhook delivery failed")


def render(payload: dict) -> str:
    return json.dumps(payload, indent=2)
