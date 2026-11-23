"""What to pull, where it lands, and how a raw API record becomes a typed row."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from . import sources


def row_hash(record: dict) -> str:
    return hashlib.md5(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def epoch(value: int | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)


def dec(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def order_row(r: dict) -> dict:
    addr = r.get("shipping_address") or {}
    codes = r.get("discount_codes") or []
    return {
        "id": r["id"], "order_number": r.get("order_number"), "created_at": ts(r["created_at"]), "updated_at": ts(r["updated_at"]),
        "customer_id": (r.get("customer") or {}).get("id"), "email": r.get("email"), "currency": r.get("currency"),
        "financial_status": r.get("financial_status"), "fulfillment_status": r.get("fulfillment_status"),
        "cancelled_at": ts(r.get("cancelled_at")), "test": r.get("test"), "source_name": r.get("source_name"),
        "subtotal_price": dec(r.get("subtotal_price")), "total_discounts": dec(r.get("total_discounts")),
        "total_shipping_price": dec(r.get("total_shipping_price")), "total_tax": dec(r.get("total_tax")),
        "total_price": dec(r.get("total_price")), "discount_code": codes[0]["code"] if codes else None,
        "shipping_country": addr.get("country_code"), "shipping_province": addr.get("province_code"), "note": r.get("note"),
    }


def order_lines(r: dict) -> list[dict]:
    return [{"id": li["id"], "order_id": r["id"], "product_id": li.get("product_id"), "variant_id": li.get("variant_id"),
             "title": li.get("title"), "sku": li.get("sku"), "quantity": li.get("quantity"),
             "price": dec(li.get("price")), "total_discount": dec(li.get("total_discount"))} for li in r.get("line_items", [])]


def customer_row(r: dict) -> dict:
    return {"id": r["id"], "email": r.get("email"), "first_name": r.get("first_name"), "last_name": r.get("last_name"),
            "phone": r.get("phone"), "country": r.get("country"), "state": r.get("state"),
            "accepts_marketing": r.get("accepts_marketing"), "created_at": ts(r["created_at"]), "updated_at": ts(r["updated_at"])}


def product_row(r: dict) -> dict:
    v = (r.get("variants") or [{}])[0]
    return {"id": r["id"], "title": r.get("title"), "product_type": r.get("product_type"), "vendor": r.get("vendor"),
            "status": r.get("status"), "sku": v.get("sku"), "price": dec(v.get("price")), "cost": dec(v.get("cost")),
            "created_at": ts(r["created_at"]), "updated_at": ts(r["updated_at"])}


def shopify_refund_row(r: dict) -> dict:
    amount = sum((dec(t["amount"]) for t in r.get("transactions", []) if t.get("kind") == "refund"), Decimal("0"))
    return {"id": r["id"], "order_id": r.get("order_id"), "currency": r.get("currency"), "amount": amount,
            "note": r.get("note"), "created_at": ts(r["created_at"]), "updated_at": ts(r["updated_at"])}


def charge_row(r: dict) -> dict:
    meta, bt = r.get("metadata") or {}, r.get("balance_transaction") or {}
    return {"id": r["id"], "created_at": epoch(r["created"]), "updated_at": epoch(r["updated"]), "amount": r.get("amount"),
            "amount_refunded": r.get("amount_refunded"), "currency": r.get("currency"), "status": r.get("status"),
            "paid": r.get("paid"), "order_id": meta.get("order_id"), "order_number": meta.get("order_number"),
            "receipt_email": r.get("receipt_email"),
            "card_brand": ((r.get("payment_method_details") or {}).get("card") or {}).get("brand"),
            "fee": bt.get("fee"), "net": bt.get("net"), "balance_transaction_id": bt.get("id")}


def stripe_refund_row(r: dict) -> dict:
    return {"id": r["id"], "charge_id": r.get("charge"), "amount": r.get("amount"), "currency": r.get("currency"),
            "reason": r.get("reason"), "status": r.get("status"), "created_at": epoch(r["created"]), "updated_at": epoch(r["updated"])}


def payout_row(r: dict) -> dict:
    return {"id": r["id"], "created_at": epoch(r["created"]), "updated_at": epoch(r["updated"]),
            "arrival_date": epoch(r.get("arrival_date")), "amount": r.get("amount"), "currency": r.get("currency"), "status": r.get("status")}


@dataclass(frozen=True)
class Entity:
    source: str
    name: str
    table: str
    flatten: Callable[[dict], dict]
    pages: Callable
    child_table: str | None = None
    child_flatten: Callable[[dict], list[dict]] | None = None
    child_fk: str | None = None


ENTITIES: list[Entity] = [
    Entity("shopify", "products", "shopify_products", product_row, sources.shopify_pages),
    Entity("shopify", "customers", "shopify_customers", customer_row, sources.shopify_pages),
    Entity("shopify", "orders", "shopify_orders", order_row, sources.shopify_pages,
           "shopify_order_lines", order_lines, "order_id"),
    Entity("shopify", "refunds", "shopify_refunds", shopify_refund_row, sources.shopify_pages),
    Entity("stripe", "charges", "stripe_charges", charge_row, sources.stripe_pages),
    Entity("stripe", "refunds", "stripe_refunds", stripe_refund_row, sources.stripe_pages),
    Entity("stripe", "payouts", "stripe_payouts", payout_row, sources.stripe_pages),
]
