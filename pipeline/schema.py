"""Table definitions for the raw and meta schemas. Types are the common subset of DuckDB and Postgres."""
from __future__ import annotations

META_COLS = [("_row_hash", "VARCHAR"), ("_run_id", "VARCHAR"), ("_loaded_at", "TIMESTAMP")]

TABLES: dict[str, list[tuple[str, str]]] = {
    "shopify_orders": [
        ("id", "BIGINT"), ("order_number", "BIGINT"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
        ("customer_id", "BIGINT"), ("email", "VARCHAR"), ("currency", "VARCHAR"), ("financial_status", "VARCHAR"),
        ("fulfillment_status", "VARCHAR"), ("cancelled_at", "TIMESTAMP"), ("test", "BOOLEAN"), ("source_name", "VARCHAR"),
        ("subtotal_price", "NUMERIC(14,2)"), ("total_discounts", "NUMERIC(14,2)"), ("total_shipping_price", "NUMERIC(14,2)"),
        ("total_tax", "NUMERIC(14,2)"), ("total_price", "NUMERIC(14,2)"), ("discount_code", "VARCHAR"),
        ("shipping_country", "VARCHAR"), ("shipping_province", "VARCHAR"), ("note", "VARCHAR"),
    ],
    "shopify_order_lines": [
        ("id", "BIGINT"), ("order_id", "BIGINT"), ("product_id", "BIGINT"), ("variant_id", "BIGINT"), ("title", "VARCHAR"),
        ("sku", "VARCHAR"), ("quantity", "INTEGER"), ("price", "NUMERIC(14,2)"), ("total_discount", "NUMERIC(14,2)"),
    ],
    "shopify_customers": [
        ("id", "BIGINT"), ("email", "VARCHAR"), ("first_name", "VARCHAR"), ("last_name", "VARCHAR"), ("phone", "VARCHAR"),
        ("country", "VARCHAR"), ("state", "VARCHAR"), ("accepts_marketing", "BOOLEAN"),
        ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
    ],
    "shopify_products": [
        ("id", "BIGINT"), ("title", "VARCHAR"), ("product_type", "VARCHAR"), ("vendor", "VARCHAR"), ("status", "VARCHAR"),
        ("sku", "VARCHAR"), ("price", "NUMERIC(14,2)"), ("cost", "NUMERIC(14,2)"),
        ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
    ],
    "shopify_refunds": [
        ("id", "BIGINT"), ("order_id", "BIGINT"), ("currency", "VARCHAR"), ("amount", "NUMERIC(14,2)"), ("note", "VARCHAR"),
        ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
    ],
    "stripe_charges": [
        ("id", "VARCHAR"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"), ("amount", "BIGINT"),
        ("amount_refunded", "BIGINT"), ("currency", "VARCHAR"), ("status", "VARCHAR"), ("paid", "BOOLEAN"),
        ("order_id", "VARCHAR"), ("order_number", "VARCHAR"), ("receipt_email", "VARCHAR"), ("card_brand", "VARCHAR"),
        ("fee", "BIGINT"), ("net", "BIGINT"), ("balance_transaction_id", "VARCHAR"),
    ],
    "stripe_refunds": [
        ("id", "VARCHAR"), ("charge_id", "VARCHAR"), ("amount", "BIGINT"), ("currency", "VARCHAR"), ("reason", "VARCHAR"),
        ("status", "VARCHAR"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
    ],
    "stripe_payouts": [
        ("id", "VARCHAR"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"), ("arrival_date", "TIMESTAMP"),
        ("amount", "BIGINT"), ("currency", "VARCHAR"), ("status", "VARCHAR"),
    ],
}

META_TABLES: dict[str, str] = {
    "watermarks": """
        source VARCHAR NOT NULL, entity VARCHAR NOT NULL, high_watermark TIMESTAMP,
        last_run_id VARCHAR, updated_at TIMESTAMP, PRIMARY KEY (source, entity)""",
    "run_log": """
        run_id VARCHAR NOT NULL, source VARCHAR NOT NULL, entity VARCHAR NOT NULL,
        started_at TIMESTAMP, finished_at TIMESTAMP, duration_s DOUBLE PRECISION, status VARCHAR,
        rows_read BIGINT, rows_inserted BIGINT, rows_updated BIGINT, rows_unchanged BIGINT, rows_stale BIGINT,
        rows_written BIGINT, http_requests BIGINT, http_retries BIGINT, rate_limited BIGINT,
        watermark_before TIMESTAMP, watermark_after TIMESTAMP, error VARCHAR, detail VARCHAR""",
}


def ddl() -> list[str]:
    out = ["CREATE SCHEMA IF NOT EXISTS raw", "CREATE SCHEMA IF NOT EXISTS meta"]
    for name, cols in TABLES.items():
        defs = [f"{c} {t}" + (" PRIMARY KEY" if c == "id" else "") for c, t in cols + META_COLS]
        out.append(f"CREATE TABLE IF NOT EXISTS raw.{name} ({', '.join(defs)})")
    out.append("CREATE INDEX IF NOT EXISTS ix_order_lines_order ON raw.shopify_order_lines (order_id)")
    for name, body in META_TABLES.items():
        out.append(f"CREATE TABLE IF NOT EXISTS meta.{name} ({body})")
    return out
