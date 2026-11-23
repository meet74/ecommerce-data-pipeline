"""Single-file HTML dashboard (Plotly). Opens from disk, no server needed."""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from .warehouse import Warehouse

NAVY, TEAL, TEAL_DARK, SLATE, AMBER, GRID = "#0d1b2a", "#2ec4b6", "#178f84", "#6b7c8f", "#d9822b", "#e4e9ee"
FONT = "Inter, Helvetica, Arial, sans-serif"


def _layout(fig: go.Figure, height: int, **kw) -> go.Figure:
    margin = kw.pop("margin", dict(l=56, r=20, t=24, b=44))
    fig.update_layout(template="plotly_white", height=height, margin=margin,
                      font=dict(family=FONT, size=12, color=NAVY), paper_bgcolor="white", plot_bgcolor="white",
                      legend=dict(orientation="h", y=1.12, x=0), **kw)
    fig.update_xaxes(gridcolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, linecolor=GRID)
    return fig


def revenue_trend(kpi: pd.DataFrame) -> go.Figure:
    kpi = kpi.sort_values("date_day").copy()
    kpi["net_7d"] = kpi["net_revenue_cad"].astype(float).rolling(7, min_periods=1).mean()
    fig = go.Figure()
    fig.add_bar(x=kpi["date_day"], y=kpi["gross_revenue_cad"].astype(float), name="Daily revenue", marker_color="#a8e6df",
                hovertemplate="%{x|%b %d, %Y}<br>$%{y:,.0f}<extra>Revenue</extra>")
    fig.add_scatter(x=kpi["date_day"], y=kpi["net_7d"], name="Net revenue, 7-day average", line=dict(color=TEAL_DARK, width=2.5),
                    hovertemplate="%{x|%b %d, %Y}<br>$%{y:,.0f}<extra>Net, 7d avg</extra>")
    peak = kpi.loc[kpi["gross_revenue_cad"].astype(float).idxmax()]
    fig.add_annotation(x=peak["date_day"], y=float(peak["gross_revenue_cad"]), text=f"Peak {pd.Timestamp(peak['date_day']):%b %d}",
                       showarrow=True, arrowhead=0, ax=-50, ay=-12, font=dict(size=11, color=NAVY))
    return _layout(fig, 340, yaxis=dict(title="CAD", tickprefix="$", tickformat=",.0f"), bargap=0.1)


def new_vs_returning(kpi: pd.DataFrame) -> go.Figure:
    k = kpi.copy()
    k["week"] = pd.to_datetime(k["date_day"]).dt.to_period("W-SUN").dt.start_time
    days = k.groupby("week")["date_day"].count()
    w = k.groupby("week")[["new_orders", "returning_orders", "guest_orders"]].sum()
    w = w[days == 7]   # drop partial weeks at either end
    fig = go.Figure()
    for col, name, color in (("new_orders", "New customers", TEAL), ("returning_orders", "Returning customers", NAVY), ("guest_orders", "Unidentified", "#b9c4cf")):
        fig.add_bar(x=w.index, y=w[col], name=name, marker_color=color)
    return _layout(fig, 340, barmode="stack", yaxis=dict(title="Orders per week"))


def cohort_heatmap(c: pd.DataFrame) -> go.Figure:
    c = c.copy()
    c["cohort"] = pd.to_datetime(c["cohort_month"]).dt.strftime("%Y-%m")
    pivot = c.pivot(index="cohort", columns="month_number", values="retention_rate").astype(float) * 100
    sizes = c.drop_duplicates("cohort").set_index("cohort")["cohort_size"]
    labels = [f"{i}  (n={int(sizes[i])})" for i in pivot.index]
    text = pivot.map(lambda v: "" if pd.isna(v) else f"{v:.0f}")
    fig = go.Figure(go.Heatmap(z=pivot.values, x=[int(m) for m in pivot.columns], y=labels, text=text.values, texttemplate="%{text}",
                               colorscale=[[0, "#eef9f7"], [0.5, "#7fd8cd"], [1, TEAL_DARK]], zmin=0, zmax=60, xgap=2, ygap=2,
                               colorbar=dict(title="% active", ticksuffix="%"),
                               hovertemplate="Cohort %{y}<br>Month %{x}: %{z:.1f}% ordered<extra></extra>"))
    fig.update_yaxes(autorange="reversed", gridcolor="white")
    fig.update_xaxes(title="Months since first order", dtick=1, side="top", gridcolor="white")
    return _layout(fig, 520, margin=dict(l=130, r=20, t=60, b=20))


def top_products(p: pd.DataFrame) -> go.Figure:
    p = p.sort_values("net_revenue_cad", ascending=False).head(10).iloc[::-1]
    fig = go.Figure(go.Bar(x=p["net_revenue_cad"].astype(float), y=p["title"], orientation="h", marker_color=TEAL,
                           text=[f"${v:,.0f}" for v in p["net_revenue_cad"].astype(float)], textposition="outside", cliponaxis=False,
                           customdata=p[["units_sold", "gross_margin_pct"]].astype(float).values,
                           hovertemplate="%{y}<br>Net revenue $%{x:,.0f}<br>%{customdata[0]:.0f} units, margin %{customdata[1]:.0%}<extra></extra>"))
    return _layout(fig, 380, xaxis=dict(title="Net revenue after refunds, CAD", tickprefix="$", tickformat=",.0f"), margin=dict(l=190, r=90, t=16, b=44))


def issue_chart(by_type: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=by_type["n"], y=by_type["issue_type"].str.replace("_", " "), orientation="h", marker_color=AMBER,
                           text=by_type["n"], textposition="outside"))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, 240, margin=dict(l=130, r=40, t=10, b=30), xaxis=dict(title="Rows"))


def tile(label: str, value: str, delta: float | None = None, note: str = "") -> str:
    d = ""
    if delta is not None:
        cls = "up" if delta >= 0 else "down"
        d = f'<div class="delta {cls}">{"+" if delta >= 0 else ""}{delta:.1f}% vs 7-day avg</div>'
    elif note:
        d = f'<div class="delta flat">{html.escape(note)}</div>'
    return f'<div class="tile"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div>{d}</div>'


CSS = f"""
*{{box-sizing:border-box}}body{{margin:0;font-family:{FONT};background:#f3f6f9;color:{NAVY}}}
header{{background:{NAVY};color:#fff;padding:22px 40px;display:flex;justify-content:space-between;align-items:baseline}}
header h1{{margin:0;font-size:22px;font-weight:650}}header span{{color:{TEAL};font-size:14px}}
main{{max-width:1280px;margin:0 auto;padding:24px 28px 48px}}
.tiles{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:20px}}
.tile{{background:#fff;border-radius:10px;padding:14px 16px;border:1px solid {GRID}}}
.tile .label{{font-size:12px;color:{SLATE};text-transform:uppercase;letter-spacing:.04em}}
.tile .value{{font-size:26px;font-weight:650;margin-top:4px}}
.delta{{font-size:12px;margin-top:2px}}.delta.up{{color:{TEAL_DARK}}}.delta.down{{color:#b4452a}}.delta.flat{{color:{SLATE}}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}}.card{{min-width:0;background:#fff;border-radius:10px;border:1px solid {GRID};padding:16px 18px}}
.card.wide{{grid-column:1/3}}h2{{font-size:15px;margin:0 0 4px}}p.sub{{margin:0 0 8px;font-size:12px;color:{SLATE}}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{text-align:left;padding:6px 6px;border-bottom:1px solid {GRID}}}
th{{color:{SLATE};font-weight:600}}td,th{{white-space:nowrap}}td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.pill{{background:#fdf0e3;color:#9a5412;border-radius:99px;padding:1px 8px;font-size:11.5px}}
footer{{color:{SLATE};font-size:12px;margin-top:18px}}
"""


def build_dashboard(wh: Warehouse, summary: dict, out_path: Path, inline_js: bool = True) -> Path:
    kpi = wh.query_df("SELECT * FROM marts.daily_kpis ORDER BY date_day")
    cohort = wh.query_df("SELECT * FROM marts.monthly_cohort_retention")
    products = wh.query_df("SELECT * FROM marts.product_performance")
    by_type = wh.query_df("SELECT issue_type, COUNT(*) AS n FROM marts.fct_payment_reconciliation "
                          "WHERE issue_type NOT IN ('none', 'pending_charge') GROUP BY issue_type ORDER BY n DESC")
    issues = wh.query_df("""SELECT issue_type, order_number, charge_id, created_at, order_currency, charge_currency,
                                   order_total, charge_amount, store_refund_total, stripe_refund_total
                            FROM marts.fct_payment_reconciliation WHERE issue_type NOT IN ('none', 'pending_charge')
                            ORDER BY created_at DESC LIMIT 14""")
    d, vs = summary["day"], summary["vs_prev_7d_avg_pct"]
    repeat_share = d["returning_orders"] / d["orders"] * 100 if d["orders"] else 0
    tiles = "".join([
        tile("Revenue", f"${d['gross_revenue_cad']:,.0f}", vs["gross_revenue"]),
        tile("Orders", f"{d['orders']:,}", vs["orders"]),
        tile("Avg order value", f"${d['aov_cad']:,.2f}", vs["aov"]),
        tile("Net revenue", f"${d['net_revenue_cad']:,.0f}", vs["net_revenue"]),
        tile("Returning share", f"{repeat_share:.0f}%", note=f"{d['new_orders']} new, {d['returning_orders']} returning"),
        tile("Refund rate", f"{(d['refund_rate'] or 0) * 100:.1f}%", note=f"${d['refunds_cad']:,.0f} refunded today"),
    ])
    rows = ""
    for r in issues.itertuples():
        def n(v): return "" if pd.isna(v) else f"{float(v):,.2f}"
        ref = f"#{int(r.order_number)}" if not pd.isna(r.order_number) else "no order"
        cur = lambda v: "-" if pd.isna(v) or not v else v
        rows += (f"<tr><td><span class='pill'>{r.issue_type.replace('_', ' ')}</span></td><td>{ref}</td><td>{'-' if pd.isna(r.charge_id) else html.escape(str(r.charge_id)[:10]) + '…'}</td>"
                 f"<td>{pd.Timestamp(r.created_at):%Y-%m-%d}</td>"
                 f"<td class='num'>{n(r.order_total)} {'' if pd.isna(r.order_currency) else r.order_currency}</td>"
                 f"<td class='num'>{n(r.charge_amount)} {'' if pd.isna(r.charge_currency) else r.charge_currency}</td>"
                 f"<td class='num'>{n(r.store_refund_total)} / {n(r.stripe_refund_total)}</td></tr>")
    figs = {
        "trend": revenue_trend(kpi), "mix": new_vs_returning(kpi), "cohort": cohort_heatmap(cohort),
        "products": top_products(products), "issues": issue_chart(by_type) if not by_type.empty else go.Figure(),
    }
    div = {k: f.to_html(full_html=False, include_plotlyjs=False, default_width="100%", config={"displayModeBar": False, "responsive": True}) for k, f in figs.items()}
    js = f"<script>{get_plotlyjs()}</script>" if inline_js else '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
    rec = summary["reconciliation"]
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>E-commerce KPI dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{CSS}</style>{js}</head><body>
<header><h1>Maple &amp; Pine Supply Co. - daily KPIs</h1><span>Report date {summary['report_date']} | all money in CAD, excluding tax</span></header>
<main><div class="tiles">{tiles}</div>
<div class="grid">
<div class="card wide"><h2>Revenue trend</h2><p class="sub">Daily revenue and 7-day average of net revenue (after refunds and processor fees). Black Friday is the tall bar.</p>{div['trend']}</div>
<div class="card"><h2>New vs returning customers</h2><p class="sub">Orders per week by customer type.</p>{div['mix']}</div>
<div class="card"><h2>Top products</h2><p class="sub">Net revenue after refunds, all time.</p>{div['products']}</div>
<div class="card wide"><h2>Cohort retention</h2><p class="sub">Share of each first-order-month cohort that ordered again N months later.</p>{div['cohort']}</div>
<div class="card"><h2>Payment reconciliation</h2><p class="sub">{rec['issues']} of {rec['rows_checked']:,} order/charge rows disagree between the store and the payment provider.</p>{div['issues']}</div>
<div class="card"><h2>Most recent mismatches</h2><p class="sub">Order total vs charge amount, store vs Stripe refunds.</p>
<table><tr><th>Issue</th><th>Order</th><th>Charge</th><th>Date</th><th class="num">Order total</th><th class="num">Charge</th><th class="num">Refunds</th></tr>{rows}</table></div>
</div><footer>Generated {summary['generated_at']} from the marts schema. Source data is synthetic.</footer></main></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def write_summary(summary: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))
    return path
