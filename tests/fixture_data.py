"""A tiny hand-built warehouse state. Expected KPIs in test_models.py are worked out from these rows.

Orders (CAD unless noted, tax is 13% unless noted):
  1001 alice      2025-03-03  2 x Widget @10           subtotal 20.00 ship 5.00 tax 3.25 total 28.25
  1002 bob        2025-03-03  1 x Gadget @25 less 5    subtotal 20.00 ship 0    tax 2.60 total 22.60
  1003 alice(dup) 2025-03-05  1 x Widget @10           subtotal 10.00 ship 5.00 tax 1.95 total 16.95  refunded 8.50 on 03-06
  1004 dave       2025-03-08  1 x Widget @7.00 USD     total 7.00, no tax (a Saturday: needs the Friday rate)
  1005 test order, 1006 duplicate of #1001, 1007 cancelled
  1008 alice      2025-03-10  1 x Gadget @25           total 28.25   (charge is only 25.00)
  1009 no email   2025-03-10  1 x Widget @10           total 16.95   (no charge)
  1010 bob        2025-03-11  1 x Gadget @25           total 28.25   refunded in full 03-12, Stripe never refunded
  1011 bob        2025-04-02  1 x Widget @10           subtotal 10.00 tax 1.30 total 11.30
"""
from datetime import datetime as dt

import pandas as pd

from pipeline.warehouse import frame_for

NOW = dt(2025, 4, 3)


def order(oid, number, created, cust, email, status="paid", currency="CAD", test=False, cancelled=None,
          subtotal="0", discounts="0", ship="0", tax="0", total="0", lines=()):
    return {"id": oid, "order_number": number, "created_at": created, "updated_at": created, "customer_id": cust, "email": email,
            "currency": currency, "financial_status": status, "fulfillment_status": None, "cancelled_at": cancelled, "test": test,
            "source_name": "web", "subtotal_price": subtotal, "total_discounts": discounts, "total_shipping_price": ship,
            "total_tax": tax, "total_price": total, "discount_code": None, "shipping_country": "CA", "shipping_province": "ON",
            "note": None}, [{"id": oid * 10 + i, "order_id": oid, "product_id": pid, "variant_id": None, "title": "x", "sku": "s",
                             "quantity": q, "price": price, "total_discount": disc} for i, (pid, q, price, disc) in enumerate(lines)]


ORDERS = [
    order(1001, 1001, dt(2025, 3, 3, 10), 1, " Alice@Example.com ", subtotal="20.00", ship="5.00", tax="3.25", total="28.25", lines=[(101, 2, "10.00", "0.00")]),
    order(1002, 1002, dt(2025, 3, 3, 15), 3, "bob@example.com", subtotal="20.00", discounts="5.00", tax="2.60", total="22.60", lines=[(102, 1, "25.00", "5.00")]),
    order(1003, 1003, dt(2025, 3, 5, 9), 2, "ALICE@example.com", status="PAID", subtotal="10.00", ship="5.00", tax="1.95", total="16.95", lines=[(101, 1, "10.00", "0.00")]),
    order(1004, 1004, dt(2025, 3, 8, 12), None, "dave@example.com", currency="usd", subtotal="7.00", total="7.00", lines=[(101, 1, "7.00", "0.00")]),
    order(1005, 1005, dt(2025, 3, 9, 8), None, "test+1@example.com", test=True, subtotal="10.00", tax="1.30", total="11.30", lines=[(101, 1, "10.00", "0.00")]),
    order(1006, 1001, dt(2025, 3, 3, 10, 0, 2), 1, " Alice@Example.com ", status="pending", subtotal="20.00", ship="5.00", tax="3.25", total="28.25", lines=[(101, 2, "10.00", "0.00")]),
    order(1007, 1007, dt(2025, 3, 9, 9), 3, "bob@example.com", status="VOIDED ", cancelled=dt(2025, 3, 9, 10), subtotal="10.00", tax="1.30", total="11.30", lines=[(101, 1, "10.00", "0.00")]),
    order(1008, 1008, dt(2025, 3, 10, 11), 1, "alice@example.com", subtotal="25.00", tax="3.25", total="28.25", lines=[(102, 1, "25.00", "0.00")]),
    order(1009, 1009, dt(2025, 3, 10, 13), None, None, subtotal="10.00", ship="5.00", tax="1.95", total="16.95", lines=[(101, 1, "10.00", "0.00")]),
    order(1010, 1010, dt(2025, 3, 11, 10), 3, "bob@example.com", subtotal="25.00", tax="3.25", total="28.25", lines=[(102, 1, "25.00", "0.00")]),
    order(1011, 1011, dt(2025, 4, 2, 9), 3, "bob@example.com", subtotal="10.00", tax="1.30", total="11.30", lines=[(101, 1, "10.00", "0.00")]),
]


def customer(cid, email, first, country, created):
    return {"id": cid, "email": email, "first_name": first, "last_name": "Test", "phone": None, "country": country, "state": "enabled",
            "accepts_marketing": True, "created_at": created, "updated_at": created}


CUSTOMERS = [
    customer(1, " Alice@Example.com ", "alice", "Canada", dt(2025, 3, 3, 9)),
    customer(2, "alice@example.com", "ALICE", "CA", dt(2025, 3, 4, 9)),
    customer(3, "bob@example.com", "Bob", "us", dt(2025, 3, 3, 14)),
    customer(4, "cara@example.com", "Cara", "CA", dt(2025, 3, 1, 9)),
]

PRODUCTS = [
    {"id": 101, "title": "  Widget ", "product_type": "coffee", "vendor": None, "status": "Active", "sku": "w-1", "price": "10.00", "cost": "4.00",
     "created_at": dt(2025, 1, 1), "updated_at": dt(2025, 1, 1)},
    {"id": 102, "title": "Gadget", "product_type": "Gear", "vendor": "Maple & Pine", "status": "active", "sku": "g-1", "price": "25.00", "cost": "10.00",
     "created_at": dt(2025, 1, 1), "updated_at": dt(2025, 1, 1)},
]

SHOP_REFUNDS = [
    {"id": 5001, "order_id": 1003, "currency": "CAD", "amount": "8.50", "note": "damaged", "created_at": dt(2025, 3, 6, 9), "updated_at": dt(2025, 3, 6, 9)},
    {"id": 5002, "order_id": 1010, "currency": "CAD", "amount": "28.25", "note": "changed mind", "created_at": dt(2025, 3, 12, 9), "updated_at": dt(2025, 3, 12, 9)},
]


def charge(cid, created, amount, fee, order_id, currency="cad"):
    return {"id": cid, "created_at": created, "updated_at": created, "amount": amount, "amount_refunded": 0, "currency": currency,
            "status": "succeeded", "paid": True, "order_id": order_id, "order_number": None, "receipt_email": None, "card_brand": "visa",
            "fee": fee, "net": amount - fee, "balance_transaction_id": "txn_" + cid}


CHARGES = [
    charge("ch_1", dt(2025, 3, 3, 10, 0, 5), 2825, 112, "1001"),
    charge("ch_2", dt(2025, 3, 3, 15, 0, 5), 2260, 96, "1002"),
    charge("ch_3", dt(2025, 3, 5, 9, 0, 5), 1695, 79, "1003"),
    charge("ch_4", dt(2025, 3, 8, 12, 0, 5), 700, 50, "1004", "usd"),
    charge("ch_5", dt(2025, 3, 10, 11, 0, 5), 2500, 100, "1008"),
    charge("ch_6", dt(2025, 3, 12, 8, 0, 0), 4000, 150, "9999"),
    charge("ch_7", dt(2025, 3, 11, 10, 0, 5), 2825, 112, "1010"),
    charge("ch_8", dt(2025, 4, 2, 9, 0, 5), 1130, 62, "1011"),
]

STRIPE_REFUNDS = [
    {"id": "re_1", "charge_id": "ch_3", "amount": 850, "currency": "cad", "reason": "requested_by_customer", "status": "succeeded",
     "created_at": dt(2025, 3, 6, 9), "updated_at": dt(2025, 3, 6, 9)},
]

PAYOUTS = [
    {"id": "po_1", "created_at": dt(2025, 3, 4, 0, 30), "updated_at": dt(2025, 3, 4, 0, 30), "arrival_date": dt(2025, 3, 5), "amount": 4877,
     "currency": "cad", "status": "paid"},
    {"id": "po_2", "created_at": dt(2025, 3, 7, 0, 30), "updated_at": dt(2025, 3, 7, 0, 30), "arrival_date": dt(2025, 3, 8), "amount": -850,
     "currency": "cad", "status": "paid"},
]


def load(wh):
    wh.init_schema()
    for table, rows in (("shopify_customers", CUSTOMERS), ("shopify_products", PRODUCTS), ("shopify_refunds", SHOP_REFUNDS),
                        ("stripe_charges", CHARGES), ("stripe_refunds", STRIPE_REFUNDS), ("stripe_payouts", PAYOUTS),
                        ("shopify_orders", [o for o, _ in ORDERS]), ("shopify_order_lines", [l for _, ls in ORDERS for l in ls])):
        wh.insert_frame(f"raw.{table}", frame_for(table, _dec(rows), "fixture", NOW))


def _dec(rows):
    from decimal import Decimal
    out = []
    for r in rows:
        out.append({k: (Decimal(v) if isinstance(v, str) and _is_num(v) and k in NUMERIC else v) for k, v in r.items()})
    return out


NUMERIC = {"subtotal_price", "total_discounts", "total_shipping_price", "total_tax", "total_price", "price", "cost", "amount", "total_discount"}


def _is_num(v):
    try:
        float(v)
        return True
    except ValueError:
        return False
