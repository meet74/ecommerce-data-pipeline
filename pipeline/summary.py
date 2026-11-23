"""Collect the numbers shown in the Slack message and on the dashboard header."""
from __future__ import annotations

from datetime import date, datetime, timezone

from .warehouse import Warehouse


def _f(v, nd=2):
    return None if v is None else round(float(v), nd)


def _pct_change(now, base):
    if now is None or not base:
        return None
    return round((float(now) - float(base)) / float(base) * 100, 1)


def run_stats(wh: Warehouse, run_id: str | None) -> dict:
    if not run_id:
        return {}
    rows = wh.query(
        "SELECT COALESCE(SUM(rows_read),0), COALESCE(SUM(rows_written),0), COALESCE(SUM(rate_limited),0), "
        "COALESCE(SUM(http_retries),0), COALESCE(SUM(duration_s),0), "
        "SUM(CASE WHEN status <> 'success' THEN 1 ELSE 0 END) FROM meta.run_log WHERE run_id = ? AND source <> 'dbt'", [run_id])[0]
    return {"run_id": run_id, "rows_read": int(rows[0]), "rows_written": int(rows[1]), "rate_limited": int(rows[2]),
            "http_retries": int(rows[3]), "extract_load_seconds": round(float(rows[4]), 1),
            "status": "failed" if (rows[5] or 0) else "success"}


def build_summary(wh: Warehouse, report_date: date | None = None, run_id: str | None = None, tests: dict | None = None) -> dict:
    last = wh.scalar("SELECT MAX(date_day) FROM marts.daily_kpis WHERE orders > 0")
    day = report_date or last
    k = wh.query_df("SELECT * FROM marts.daily_kpis WHERE date_day = ?", [day])
    if k.empty:
        raise SystemExit(f"no KPI row for {day}")
    row = k.iloc[0]
    prev = wh.query(
        "SELECT AVG(gross_revenue_cad), AVG(orders), AVG(aov_cad), AVG(net_revenue_cad) FROM marts.daily_kpis "
        "WHERE date_day < ? AND date_day >= ? - 7", [day, day])[0]
    totals = wh.query(
        "SELECT SUM(gross_revenue_cad), SUM(orders), SUM(net_revenue_cad) FROM marts.daily_kpis WHERE date_day > ? - 7 AND date_day <= ?",
        [day, day])[0]
    top = wh.query_df("""
        SELECT p.title, SUM(l.line_net_cad) AS revenue_cad, SUM(l.quantity) AS units
        FROM intermediate.int_order_lines l JOIN marts.product_performance p ON p.product_id = l.product_id
        WHERE l.order_date > ? - 30 AND l.order_date <= ?
        GROUP BY p.title ORDER BY revenue_cad DESC LIMIT 3""", [day, day])
    recon = wh.query_df("SELECT issue_type, COUNT(*) AS n FROM marts.fct_payment_reconciliation "
                        "WHERE issue_type NOT IN ('none', 'pending_charge') GROUP BY issue_type ORDER BY n DESC")
    checked = int(wh.scalar("SELECT COUNT(*) FROM marts.fct_payment_reconciliation WHERE issue_type <> 'pending_charge'") or 0)
    issues = int(recon["n"].sum()) if not recon.empty else 0
    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_date": str(day),
        "day": {
            "orders": int(row["orders"]), "gross_revenue_cad": _f(row["gross_revenue_cad"]), "aov_cad": _f(row["aov_cad"]),
            "new_orders": int(row["new_orders"]), "returning_orders": int(row["returning_orders"]),
            "refund_rate": _f(row["refund_rate"], 4), "refunds_cad": _f(row["refunds_cad"]),
            "fees_cad": _f(row["fees_cad"]), "net_revenue_cad": _f(row["net_revenue_cad"]),
        },
        "vs_prev_7d_avg_pct": {
            "gross_revenue": _pct_change(row["gross_revenue_cad"], prev[0]), "orders": _pct_change(row["orders"], prev[1]),
            "aov": _pct_change(row["aov_cad"], prev[2]), "net_revenue": _pct_change(row["net_revenue_cad"], prev[3]),
        },
        "last_7_days": {"gross_revenue_cad": _f(totals[0]), "orders": int(totals[1] or 0), "net_revenue_cad": _f(totals[2])},
        "top_products_30d": [{"title": r.title, "revenue_cad": _f(r.revenue_cad), "units": int(r.units)} for r in top.itertuples()],
        "reconciliation": {"rows_checked": checked, "issues": issues, "issue_rate": round(issues / checked, 5) if checked else 0,
                           "by_type": {r.issue_type: int(r.n) for r in recon.itertuples()}},
        "pipeline": run_stats(wh, run_id),
        "data_tests": tests or {},
    }
    return summary
