"""dbt models on a hand-built fixture. Expected values are computed by hand in the comments."""
import csv
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from pipeline import transform
from pipeline.config import ROOT, Settings
from pipeline.warehouse import DuckDBWarehouse
from tests import fixture_data

FX = {date.fromisoformat(r["rate_date"]): D(r["cad_per_unit"])
      for r in csv.DictReader(open(ROOT / "dbt_project" / "seeds" / "fx_rates.csv")) if r["currency"] == "USD"}


def usd_rate(day: date) -> D:
    """Latest published rate on or before `day` (weekends take Friday's rate)."""
    while day not in FX:
        day -= timedelta(days=1)
    return FX[day]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    path = tmp_path_factory.mktemp("fixture") / "wh.duckdb"
    settings = Settings(duckdb_path=str(path))
    with DuckDBWarehouse(path) as wh:
        fixture_data.load(wh)
    runs = transform.transform(settings, "duckdb")
    assert all(r["returncode"] == 0 for r in runs), runs[-1]["stdout_tail"]
    tests = transform.test(settings, "duckdb")
    wh = DuckDBWarehouse(path, read_only=True)
    yield wh, tests
    wh.close()


def q(wh, sql, *params):
    return wh.query(sql, params)


def near(a, b, tol=0.01):
    assert abs(float(a) - float(b)) <= tol, f"{a} != {b}"


# ------------------------------------------------------------------ staging

def test_staging_normalises_orders(built):
    wh, _ = built
    row = {r[0]: r for r in q(wh, "SELECT order_id, currency, financial_status, is_test, is_duplicate, is_cancelled, email_norm "
                                  "FROM staging.stg_shopify__orders")}
    assert row[1004][1] == "USD"                       # ' usd' -> 'USD'
    assert row[1003][2] == "paid"                      # 'PAID' -> 'paid'
    assert row[1007][2] == "voided" and row[1007][5]   # 'VOIDED ' and cancelled
    assert row[1005][3]                                # test flag
    assert row[1006][4] and not row[1001][4]           # same order number: later one is the duplicate
    assert row[1001][6] == "alice@example.com"         # trimmed, lower-cased
    assert row[1009][6] is None


def test_staging_merges_duplicate_customers(built):
    wh, _ = built
    rows = {r[0]: r for r in q(wh, "SELECT customer_id, customer_key, canonical_customer_id, is_duplicate, country, first_name "
                                   "FROM staging.stg_shopify__customers")}
    assert rows[1][1] == rows[2][1] == "alice@example.com"
    assert rows[1][2] == rows[2][2] == 1
    assert (rows[1][3], rows[2][3]) == (False, True)
    assert (rows[1][4], rows[2][4], rows[3][4]) == ("CA", "CA", "US")
    assert rows[1][5] == "Alice" and rows[2][5] == "Alice"


def test_staging_cleans_products_and_converts_stripe_cents(built):
    wh, _ = built
    assert q(wh, "SELECT title, product_type, vendor FROM staging.stg_shopify__products WHERE product_id = 101")[0] == ("Widget", "Coffee", "Unknown")
    assert q(wh, "SELECT amount, fee, net FROM staging.stg_stripe__charges WHERE charge_id = 'ch_1'")[0] == (D("28.25"), D("1.12"), D("27.13"))


# ------------------------------------------------------------------ marts

def test_fct_orders_excludes_test_duplicate_and_cancelled(built):
    wh, _ = built
    ids = {r[0] for r in q(wh, "SELECT order_id FROM marts.fct_orders")}
    assert ids == {1001, 1002, 1003, 1004, 1008, 1009, 1010, 1011}


def test_customer_types_and_sequence(built):
    wh, _ = built
    got = {r[0]: (r[1], r[2]) for r in q(wh, "SELECT order_id, customer_type, order_seq FROM marts.fct_orders")}
    assert got[1001] == ("new", 1) and got[1003] == ("returning", 2) and got[1008] == ("returning", 3)   # alice, across two customer ids
    assert got[1002] == ("new", 1) and got[1010] == ("returning", 2) and got[1011] == ("returning", 3)   # bob
    assert got[1004] == ("new", 1)                                                                         # guest with an email
    assert got[1009][0] == "guest"                                                                         # no identity at all


def test_usd_order_uses_last_published_rate_on_a_weekend(built):
    wh, _ = built
    saturday = date(2025, 3, 8)
    assert saturday not in FX
    rate = q(wh, "SELECT fx_rate_cad, revenue_cad FROM marts.fct_orders WHERE order_id = 1004")[0]
    near(rate[0], usd_rate(saturday), 1e-6)
    near(rate[1], D("7.00") * usd_rate(saturday))


def test_daily_kpis_match_hand_computed_values(built):
    wh, _ = built
    k = {r[0]: r for r in q(wh, "SELECT date_day, orders, gross_revenue_cad, aov_cad, new_orders, returning_orders, guest_orders, "
                                "refunded_orders, refund_rate, refunds_cad, fees_cad, net_revenue_cad FROM marts.daily_kpis")}
    # 03-03: revenue 25.00 + 20.00; both customers are new; fees 1.12 + 0.96
    d = k[date(2025, 3, 3)]
    assert d[1:8] == (2, D("45.00"), D("22.50"), 2, 0, 0, 0)
    assert (d[10], d[11]) == (D("2.08"), D("42.92"))
    # 03-05: alice's second order, revenue 15.00 (16.95 less 1.95 tax), refunded later; fee 0.79
    d = k[date(2025, 3, 5)]
    assert (d[1], d[2], d[5], d[7], d[8]) == (1, D("15.00"), 1, 1, D("1.0000"))
    near(d[11], 15 - 0.79)
    # 03-06: no orders, refund of 8.50 gross -> 8.50 * (1 - 1.95/16.95) = 7.52 ex tax
    d = k[date(2025, 3, 6)]
    assert d[1] == 0 and d[3] is None
    near(d[9], 8.5 * (1 - 1.95 / 16.95))
    near(d[11], -d[9])
    # 03-08: USD order, revenue and fee converted at the Friday rate
    d = k[date(2025, 3, 8)]
    near(d[2], 7 * usd_rate(date(2025, 3, 8)))
    near(d[10], D("0.50") * usd_rate(date(2025, 3, 8)))
    # 03-10: one returning order (25.00) and one guest order (15.00), average 20.00; only one fee (1.00)
    d = k[date(2025, 3, 10)]
    assert (d[1], d[2], d[3], d[4], d[5], d[6]) == (2, D("40.00"), D("20.00"), 0, 1, 1)
    assert d[11] == D("39.00")
    # 03-12: the full 25.00 refund for order 1010, plus the orphan charge fee of 1.50
    d = k[date(2025, 3, 12)]
    assert (d[9], d[10], d[11]) == (D("25.00"), D("1.50"), D("-26.50"))
    assert len(k) == 31                                   # 03-03 .. 04-02, zero-filled


def test_dim_customers(built):
    wh, _ = built
    rows = {r[0]: r for r in q(wh, "SELECT customer_key, orders, lifetime_revenue_cad, segment, source_record_count, customer_id "
                                   "FROM marts.dim_customers")}
    assert set(rows) == {"alice@example.com", "bob@example.com", "cara@example.com", "dave@example.com"}
    assert rows["alice@example.com"][1:6] == (3, D("65.00"), "repeat", 2, 1)       # orders 1001, 1003, 1008; two source records
    assert rows["bob@example.com"][1:4] == (3, D("55.00"), "repeat")                # 20 + 25 + 10
    assert rows["cara@example.com"][1] == 0 and rows["cara@example.com"][3] == "prospect"
    assert rows["dave@example.com"][3] == "one_time"


def test_cohort_retention(built):
    wh, _ = built
    rows = q(wh, "SELECT cohort_month, month_number, cohort_size, active_customers, retention_rate FROM marts.monthly_cohort_retention "
                 "ORDER BY cohort_month, month_number")
    # March cohort: alice, bob, dave. In April only bob came back.
    assert rows[0] == (date(2025, 3, 1), 0, 3, 3, D("1.0000"))
    assert rows[1] == (date(2025, 3, 1), 1, 3, 1, D("0.3333"))
    assert len(rows) == 2


def test_product_performance(built):
    wh, _ = built
    p = {r[0]: r for r in q(wh, "SELECT product_id, orders, units_sold, revenue_cad, refunds_cad, net_revenue_cad, cogs_cad, gross_margin_cad "
                                "FROM marts.product_performance")}
    gadget = p[102]    # lines: 20.00 (after discount), 25.00, 25.00; the 25.00 refund on order 1010 lands entirely on it
    assert gadget[1:] == (3, 3, D("70.00"), D("25.00"), D("45.00"), D("30.00"), D("15.00"))
    widget = p[101]    # 2 + 1 + 1 + 1 + 1 units; 20 + 10 + 7 USD + 10 + 10; order 1003's refund (ex tax 7.52) on it
    assert widget[1:3] == (5, 6)
    near(widget[3], 50 + 7 * usd_rate(date(2025, 3, 8)))
    near(widget[4], 8.5 * 15 / 16.95)
    near(widget[6], 24)


def test_reconciliation_detects_every_planted_mismatch(built):
    wh, _ = built
    got = {(r[0] if r[0] is not None else r[1]): r[2] for r in q(wh, "SELECT order_id, order_id AS o2, issue_type FROM marts.fct_payment_reconciliation")}
    assert got[1001] == got[1002] == got[1003] == got[1004] == got[1011] == "none"
    assert got[1008] == "amount_mismatch"        # charged 25.00 for a 28.25 order
    assert got[1009] == "missing_charge"
    assert got[1010] == "refund_mismatch"        # refunded in the store, never in Stripe
    assert got[9999] == "orphan_charge"
    assert len(got) == 9


def test_reconciliation_ignores_orders_inside_the_grace_window(built):
    wh, _ = built
    n = q(wh, "SELECT COUNT(*) FROM marts.fct_payment_reconciliation WHERE issue_type = 'pending_charge'")[0][0]
    assert n == 0


# ------------------------------------------------------------------ data tests

def test_data_tests_pass_and_the_quality_gate_fires(built):
    _, tests = built
    failed = {p["node"] for p in tests["problems"] if p["status"] in ("fail", "error")}
    # 4 of 9 fixture rows are reconciliation issues, far above the 2% limit: that guard must trip, nothing else may
    assert failed == {"assert_reconciliation_issue_rate_acceptable"}
    assert tests["counts"]["pass"] >= 80
    assert any(p["node"] == "assert_reconciliation_issues_found" and p["status"] == "warn" for p in tests["problems"])
