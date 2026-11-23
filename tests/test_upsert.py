import copy

import pytest

from pipeline.entities import ENTITIES
from pipeline.ingest import merge
from pipeline.warehouse import DuckDBWarehouse

ORDERS = next(e for e in ENTITIES if e.name == "orders")


def order(oid=1, updated="2025-03-01T10:00:00Z", status="paid", lines=2):
    return {"id": oid, "order_number": 1000 + oid, "created_at": "2025-03-01T09:00:00Z", "updated_at": updated, "email": "a@example.com",
            "customer": {"id": 7}, "currency": "CAD", "financial_status": status, "fulfillment_status": None, "cancelled_at": None,
            "test": False, "source_name": "web", "subtotal_price": "10.00", "total_discounts": "0.00", "total_shipping_price": "0.00",
            "total_tax": "1.30", "total_price": "11.30", "discount_codes": [], "shipping_address": None, "note": None,
            "line_items": [{"id": oid * 10 + i, "product_id": 5, "variant_id": 6, "title": "x", "sku": "S", "quantity": 1,
                            "price": "5.00", "total_discount": "0.00"} for i in range(lines)]}


@pytest.fixture
def wh():
    w = DuckDBWarehouse(":memory:")
    w.init_schema()
    yield w
    w.close()


def run(wh, records):
    with wh.transaction():
        return merge(wh, ORDERS, records, "t")


def test_second_identical_merge_writes_nothing(wh):
    first = run(wh, [order(1), order(2)])
    assert first["inserted"] == 2 and first["rows_written"] == 2 + 4
    again = run(wh, [order(1), order(2)])
    assert again["unchanged"] == 2 and again["rows_written"] == 0
    assert wh.scalar("SELECT COUNT(*) FROM raw.shopify_orders") == 2
    assert wh.scalar("SELECT COUNT(*) FROM raw.shopify_order_lines") == 4


def test_newer_version_updates_row_and_replaces_children(wh):
    run(wh, [order(1, lines=3)])
    res = run(wh, [order(1, updated="2025-03-02T10:00:00Z", status="refunded", lines=1)])
    assert res["updated"] == 1 and res["inserted"] == 0
    assert wh.scalar("SELECT financial_status FROM raw.shopify_orders WHERE id = 1") == "refunded"
    assert wh.scalar("SELECT COUNT(*) FROM raw.shopify_order_lines WHERE order_id = 1") == 1


def test_stale_version_does_not_overwrite_newer_data(wh):
    run(wh, [order(1, updated="2025-03-05T10:00:00Z", status="refunded")])
    res = run(wh, [order(1, updated="2025-03-02T10:00:00Z", status="paid")])
    assert res["stale"] == 1 and res["rows_written"] == 0
    assert wh.scalar("SELECT financial_status FROM raw.shopify_orders WHERE id = 1") == "refunded"


def test_duplicates_inside_one_batch_keep_the_newest(wh):
    old, new = order(1, updated="2025-03-01T10:00:00Z"), order(1, updated="2025-03-03T10:00:00Z", status="refunded")
    res = run(wh, [new, copy.deepcopy(old)])
    assert res["inserted"] == 1
    assert wh.scalar("SELECT financial_status FROM raw.shopify_orders WHERE id = 1") == "refunded"


def test_failed_transaction_leaves_nothing_behind(wh):
    bad = order(1)
    bad["total_price"] = "not a number"
    with pytest.raises(Exception):
        run(wh, [bad])
    assert wh.scalar("SELECT COUNT(*) FROM raw.shopify_orders") == 0
