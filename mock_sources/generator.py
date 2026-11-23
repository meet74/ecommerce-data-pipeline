"""Seeded synthetic store + payments data for a fictional shop ("Maple & Pine Supply Co.").

The generator produces *versions* of each record. A record that changes over time
(fulfilled, refunded, edited months later) has several versions, each with its own
updated_at. The mock APIs serve whichever version was current at their "as of"
clock, which is what makes incremental loads and late-arriving updates testable.

Everything is derived from one seed, including the ground truth of the data
quality problems that were injected (written to Dataset.truth).
"""
from __future__ import annotations

import bisect
import copy
import functools
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

UTC = timezone.utc
# bump when generator output changes, so cached datasets are rebuilt
GENERATOR_VERSION = 2


@dataclass
class GenConfig:
    seed: int = 42
    start: date = date(2025, 1, 1)
    end: date = date(2026, 6, 30)
    n_customers: int = 4200
    n_products: int = 60
    signup_only_rate: float = 0.08
    test_order_rate: float = 0.012
    duplicate_order_rate: float = 0.008
    duplicate_customer_rate: float = 0.025
    refund_rate: float = 0.055
    late_edit_rate: float = 0.03
    cancel_rate: float = 0.02
    # injected payment mismatches, as a share of orders (min 2 each)
    missing_charge_rate: float = 0.0012
    orphan_charge_rate: float = 0.0006
    amount_mismatch_rate: float = 0.0012
    currency_mismatch_rate: float = 0.0003
    refund_mismatch_rate: float = 0.0004


@dataclass
class Entry:
    ts: int            # updated_at as epoch seconds (sort key)
    id: Any
    record: dict
    next_ts: int | None = None   # when the next version of this id appears


@dataclass
class Dataset:
    config: GenConfig
    entities: dict[str, list[Entry]]
    truth: dict
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        self.index()

    def index(self):
        self.keys: dict[str, list[tuple]] = {}
        self.by_id: dict[str, dict[Any, list[Entry]]] = {}
        for name, entries in self.entities.items():
            entries.sort(key=lambda e: (e.ts, str(e.id)))
            by_id: dict[Any, list[Entry]] = {}
            for e in entries:
                by_id.setdefault(e.id, []).append(e)
            for versions in by_id.values():
                for a, b in zip(versions, versions[1:]):
                    a.next_ts = b.ts
            self.by_id[name] = by_id
            self.keys[name] = [(e.ts, str(e.id)) for e in entries]

    def end_ts(self) -> int:
        return ts_of(datetime(self.config.end.year, self.config.end.month, self.config.end.day, 23, 59, 59, tzinfo=UTC))


def ts_of(dt: datetime) -> int:
    return int(dt.timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(cents: int) -> str:
    return f"{cents / 100:.2f}"


# ---------------------------------------------------------------- calendar

@functools.lru_cache(maxsize=None)
def black_friday(year: int) -> date:
    d = date(year, 11, 1)
    thursdays = [d + timedelta(days=i) for i in range(30) if (d + timedelta(days=i)).weekday() == 3]
    return thursdays[3] + timedelta(days=1)


MONTH_FACTOR = {1: 0.85, 2: 0.85, 3: 0.95, 4: 0.95, 5: 1.0, 6: 0.95, 7: 0.85, 8: 0.85, 9: 1.0, 10: 1.1, 11: 1.3, 12: 1.3}
WEEKDAY_FACTOR = [1.05, 1.0, 0.95, 0.95, 1.0, 0.9, 0.95]
HOUR_WEIGHTS = [4, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 6, 6, 6, 5, 5, 5, 5, 5]  # UTC, North American evenings


@functools.lru_cache(maxsize=None)
def season(d: date) -> float:
    f = MONTH_FACTOR[d.month] * WEEKDAY_FACTOR[d.weekday()]
    bf = black_friday(d.year)
    delta = (d - bf).days
    if delta == 0:
        f *= 3.6
    elif delta == 3:        # cyber monday
        f *= 2.4
    elif delta == -1:
        f *= 1.4
    elif delta in (1, 2):
        f *= 1.6
    elif d.month == 12 and d.day == 26:
        f *= 1.7
    elif d.month == 12 and 18 <= d.day <= 23:
        f *= 1.25
    return f


# ---------------------------------------------------------------- reference data

FIRST = ["Aiden", "Priya", "Liam", "Sofia", "Noah", "Mei", "Lucas", "Amara", "Ethan", "Chloe", "Omar", "Hannah",
         "Mateo", "Isla", "Arjun", "Zoe", "Ravi", "Nora", "Felix", "Leah", "Daniel", "Maya", "Owen", "Tara",
         "Jonas", "Elena", "Kai", "Sara", "Theo", "Anika", "Cole", "Ines", "Rohan", "Wren", "Marco", "Yuki"]
LAST = ["Tremblay", "Patel", "Nguyen", "Okafor", "Fraser", "Singh", "Larsen", "Moreau", "Haddad", "Kowalski",
        "Bennett", "Sato", "Costa", "Dubois", "Rahman", "Murphy", "Ivanov", "Campbell", "Reyes", "Walsh",
        "Chen", "Hughes", "Gagnon", "Silva", "Ali", "Park", "Novak", "Fisher", "Lam", "Roy"]
CA_PROV = [("ON", 0.13, 38), ("QC", 0.14975, 20), ("BC", 0.12, 15), ("AB", 0.05, 12), ("NS", 0.15, 8), ("MB", 0.12, 7)]
US_STATE = [("NY", 0.08875, 25), ("CA", 0.0725, 25), ("TX", 0.0625, 15), ("WA", 0.065, 15), ("IL", 0.0625, 12), ("MA", 0.0, 8)]
CATEGORIES = {
    "Coffee": (["Single-Origin Beans", "House Blend", "Dark Roast", "Decaf Blend", "Cold Brew Grounds", "Espresso Roast"], (1400, 2800)),
    "Tea": (["Earl Grey", "Sencha Green", "Chamomile", "Masala Chai", "Oolong", "Peppermint Leaf"], (1100, 2200)),
    "Brewing Gear": (["Pour-over Kettle", "Burr Grinder", "Glass French Press", "Ceramic Dripper", "Scale", "Milk Frother"], (2400, 9500)),
    "Drinkware": (["Enamel Camp Mug", "Stoneware Mug", "Insulated Tumbler", "Glass Cup Set"], (1800, 4200)),
    "Pantry": (["Maple Syrup", "Wildflower Honey", "Oat Granola", "Cocoa Nibs", "Shortbread Tin"], (900, 2600)),
    "Gift Sets": (["Starter Box", "Holiday Box", "Tea Lover Box"], (4800, 8800)),
}
ADJ = ["Harbour", "Cedar", "Northern", "Prairie", "Juniper", "Birch", "Lakeside", "Alder", "Summit", "Willow"]
CODES = [("WELCOME10", 0.10), ("SPRING15", 0.15), ("FREESHIP", 0.0), ("LOYAL20", 0.20), ("BF25", 0.25)]


def pick_weighted(rng: random.Random, pairs):
    return rng.choices([p for p in pairs], weights=[p[-1] for p in pairs])[0]


def messy_case(rng: random.Random, s: str, rate: float, shout: bool = True) -> str:
    r = rng.random()
    if r < rate / 2:
        return s.upper() if shout else f" {s}"
    if r < rate:
        return f" {s} " if rng.random() < 0.5 else s + " "
    return s


# ---------------------------------------------------------------- builder

class Builder:
    def __init__(self, cfg: GenConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.days = [cfg.start + timedelta(days=i) for i in range((cfg.end - cfg.start).days + 1)]
        self.end_ts = ts_of(datetime(cfg.end.year, cfg.end.month, cfg.end.day, 23, 59, 59, tzinfo=UTC))
        self.start_ts = ts_of(datetime(cfg.start.year, cfg.start.month, cfg.start.day, tzinfo=UTC))
        self.ent: dict[str, list[Entry]] = {k: [] for k in (
            "shopify.orders", "shopify.customers", "shopify.products", "shopify.refunds",
            "stripe.charges", "stripe.refunds", "stripe.payouts")}
        self.truth: dict[str, Any] = {}
        self._rand_ids: set[str] = set()

    def put(self, name: str, ts: int, id_, record: dict):
        if ts <= self.end_ts:
            self.ent[name].append(Entry(ts, id_, record))

    def stripe_id(self, prefix: str) -> str:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        while True:
            s = prefix + "_3" + "".join(self.rng.choice(alphabet) for _ in range(22))
            if s not in self._rand_ids:
                self._rand_ids.add(s)
                return s

    # -- products
    def build_products(self):
        rng, cfg = self.rng, self.cfg
        products = []
        pid = 7_100_000_000_000
        names = set()
        while len(products) < cfg.n_products:
            cat = rng.choice(list(CATEGORIES))
            base_names, (lo, hi) = CATEGORIES[cat]
            title = f"{rng.choice(ADJ)} {rng.choice(base_names)}"
            if title in names:
                continue
            names.add(title)
            price = int(rng.randint(lo, hi) // 50 * 50 + 49)
            cost = int(price * rng.uniform(0.33, 0.55))
            created = self.start_ts - rng.randint(20, 120) * 86400
            if rng.random() < 0.15:
                created = self.start_ts + rng.randint(30, (cfg.end - cfg.start).days - 30) * 86400
            pid += 1
            sku = f"{cat[:3].upper()}-{len(products) + 1:03d}"
            products.append({"id": pid, "title": title, "type": cat, "price": price, "cost": cost, "sku": sku,
                             "variant_id": pid * 10 + 1, "created": created})
        weights = [1 / (i + 3) ** 0.9 for i in range(len(products))]
        rng.shuffle(weights)
        for p, w in zip(products, weights):
            p["weight"] = w
        self.products = products
        for p in products:
            rec = {"id": p["id"], "title": messy_case(rng, p["title"], 0.10, shout=False), "product_type": p["type"] if rng.random() > 0.04 else p["type"].lower(),
                   "vendor": "Maple & Pine Supply Co." if rng.random() > 0.1 else None, "status": "active",
                   "created_at": iso(p["created"]), "updated_at": iso(p["created"]),
                   "variants": [{"id": p["variant_id"], "sku": p["sku"], "price": money(p["price"]), "cost": money(p["cost"])}]}
            self.put("shopify.products", p["created"], p["id"], rec)
        for p in rng.sample(products, 8):
            ts = self.start_ts + rng.randint(10, (cfg.end - cfg.start).days - 5) * 86400 + rng.randint(0, 80000)
            rec = copy.deepcopy(self.ent["shopify.products"][products.index(p)].record)
            rec["updated_at"] = iso(ts)
            rec["title"] = p["title"]
            rec["status"] = "archived" if rng.random() < 0.4 else "active"
            self.put("shopify.products", ts, p["id"], rec)

    # -- customers
    def build_customers(self):
        rng, cfg = self.rng, self.cfg
        weights = []
        n_days = len(self.days)
        for i, d in enumerate(self.days):
            growth = 0.6 + 0.8 * i / n_days
            weights.append(growth * season(d) ** 1.2)
        acq_days = rng.choices(range(n_days), weights=weights, k=cfg.n_customers)
        acq_days.sort()
        customers = []
        for n, di in enumerate(acq_days):
            country = "CA" if rng.random() < 0.7 else "US"
            region = pick_weighted(rng, CA_PROV if country == "CA" else US_STATE)
            first, last = rng.choice(FIRST), rng.choice(LAST)
            email = f"{first}.{last}{rng.randint(1, 9999)}@example.{rng.choice(['com', 'com', 'com', 'net', 'org'])}".lower()
            c = {"idx": n, "id": 6_200_000_000_000 + n, "first": first, "last": last, "email": email, "country": country,
                 "region": region, "day": di, "rate": rng.lognormvariate(math.log(0.95), 0.75),
                 "life": rng.expovariate(1 / 250), "twin_id": None}
            customers.append(c)
        self.customers = customers
        return customers

    def customer_record(self, c, ts, twin=False):
        rng = self.rng
        email = c["email"]
        email = messy_case(rng, email, 0.06)
        if twin:
            email = rng.choice([c["email"].upper(), " " + c["email"], c["email"].title().lower().replace("@", "@")])
        cv = {"CA": ["CA", "CA", "CA", "CA", "ca", "Canada", " CA "], "US": ["US", "US", "US", "us", "United States", "USA"]}[c["country"]]
        return {"id": c["twin_id"] if twin else c["id"], "email": email,
                "first_name": None if rng.random() < 0.02 else (c["first"].lower() if rng.random() < 0.03 else c["first"]),
                "last_name": c["last"], "phone": None if rng.random() < 0.4 else f"+1-{rng.choice(['416', '604', '514', '212', '206'])}-555-{rng.randint(100, 199):04d}",
                "country": rng.choice(cv), "state": "enabled", "accepts_marketing": rng.random() < 0.55,
                "created_at": iso(ts), "updated_at": iso(ts)}

    # -- orders
    def build_orders(self):
        rng, cfg = self.rng, self.cfg
        plist = self.products
        pw = [p["weight"] for p in plist]
        raw_orders = []   # (ts, customer)
        total_season = sum(season(d) for d in self.days) / len(self.days)
        for c in self.customers:
            d0 = c["day"]
            ts0 = self.day_ts(d0)
            raw_orders.append((ts0, c, True))
            last_day = min(len(self.days) - 1, d0 + int(c["life"]))
            base = c["rate"] / 30.4 / total_season
            for di in range(d0 + 1, last_day + 1):
                p = base * season(self.days[di])
                if rng.random() < p:
                    raw_orders.append((self.day_ts(di), c, False))
        raw_orders.sort(key=lambda x: x[0])
        # test orders: not tied to customers
        n_test = int(len(raw_orders) * cfg.test_order_rate)
        for i in range(n_test):
            raw_orders.append((self.day_ts(rng.randrange(len(self.days))), {"test": i}, False))
        raw_orders.sort(key=lambda x: x[0])

        orders = []
        order_number = 1000
        oid = 4_900_000_000_000
        seen_first = set()
        for ts, c, is_first in raw_orders:
            order_number += 1
            oid += rng.randint(1, 3)
            o = self.make_order(oid, order_number, ts, c, is_first, plist, pw)
            orders.append(o)
        self.orders = orders
        return orders

    def day_ts(self, day_index: int) -> int:
        hour = self.rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
        return self.start_ts + day_index * 86400 + hour * 3600 + self.rng.randint(0, 3599)

    def make_order(self, oid, number, ts, c, is_first, plist, pw):
        rng = self.rng
        is_test = "test" in c
        d = datetime.fromtimestamp(ts, UTC).date()
        if is_test:
            country, region, currency = "CA", ("ON", 0.13, 1), "CAD"
        else:
            country, region = c["country"], c["region"]
            currency = "CAD" if country == "CA" else "USD"
        n_lines = rng.choices([1, 2, 3, 4], weights=[50, 28, 15, 7])[0]
        chosen = []
        while len(chosen) < n_lines:
            p = rng.choices(plist, weights=pw)[0]
            if p not in chosen and p["created"] <= ts:
                chosen.append(p)
        bf_week = abs((d - black_friday(d.year)).days) <= 3
        pct, code = 0.0, None
        if bf_week and rng.random() < 0.6:
            pct, code = 0.25, "BF25"
        elif is_first and rng.random() < 0.3:
            pct, code = 0.10, "WELCOME10"
        elif rng.random() < 0.15:
            code, pct = rng.choice([x for x in CODES if x[0] in ("SPRING15", "LOYAL20", "FREESHIP")])
        lines = []
        for k, p in enumerate(chosen):
            qty = rng.choices([1, 2, 3], weights=[75, 20, 5])[0]
            unit = p["price"] if currency == "CAD" else int(p["price"] * 0.73)
            gross = unit * qty
            disc = int(round(gross * pct))
            lines.append({"id": oid * 10 + k, "product_id": p["id"], "variant_id": p["variant_id"], "title": p["title"], "sku": p["sku"],
                          "quantity": qty, "price": money(unit), "total_discount": money(disc), "_net": gross - disc, "_disc": disc})
        subtotal = sum(l["_net"] for l in lines)
        free_ship = 7500 if currency == "CAD" else 5500
        shipping = 0 if (subtotal >= free_ship or code == "FREESHIP") else (999 if currency == "CAD" else 799)
        tax = int(round((subtotal + shipping) * region[1]))
        total = subtotal + shipping + tax
        discount_total = sum(l["_disc"] for l in lines)
        if is_test:
            email, cust_id = f"test+{c['test']}@example.com", None
        else:
            email = messy_case(rng, c["email"], 0.04)
            cust_id = c["id"]
            if c.get("twin_id") and rng.random() < 0.4:
                cust_id = c["twin_id"]
                email = rng.choice([c["email"].upper(), " " + c["email"]])
            r = rng.random()
            if r < 0.035:
                cust_id = None
            elif r < 0.039:
                cust_id, email = None, None
        status = rng.choice(["paid"] * 97 + ["PAID", "Paid "])
        rec = {"id": oid, "order_number": number, "name": f"#{number}", "created_at": iso(ts), "updated_at": iso(ts),
               "email": email, "customer": {"id": cust_id} if cust_id else None,
               "currency": rng.choice([currency] * 197 + [currency.lower(), f" {currency}"]),
               "financial_status": status, "fulfillment_status": None, "cancelled_at": None, "test": is_test,
               "source_name": rng.choice(["web", "web", "web", "pos", "draft_order"]) if not is_test else "web",
               "subtotal_price": money(subtotal), "total_discounts": money(discount_total),
               "total_shipping_price": money(shipping), "total_tax": money(tax), "total_price": money(total),
               "discount_codes": [{"code": code}] if code else [],
               "shipping_address": None if rng.random() < 0.01 else {"country_code": country, "province_code": region[0]},
               "note": None, "line_items": [{k: v for k, v in l.items() if not k.startswith("_")} for l in lines]}
        return {"id": oid, "ts": ts, "rec": rec, "currency": currency, "total": total, "tax": tax, "test": is_test,
                "customer": None if is_test else c, "country": country}

    # -- lifecycle: fulfilment, cancellation, refunds, late edits, charges
    def build_lifecycle(self):
        rng, cfg = self.rng, self.cfg
        refunds_s, charges = [], []
        valid = []
        for o in self.orders:
            events: list[tuple[int, str, dict]] = []
            rec = o["rec"]
            ts = o["ts"]
            if not o["test"] and rng.random() < cfg.cancel_rate:
                rec["financial_status"] = "pending"
                cts = ts + rng.randint(1800, 6 * 3600)
                events.append((cts, "cancel", {}))
                o["cancelled"] = True
            else:
                o["cancelled"] = False
                events.append((ts + rng.randint(2 * 3600, 72 * 3600), "fulfil", {}))
                if not o["test"] and rng.random() < cfg.refund_rate:
                    full = rng.random() < 0.45
                    amt = o["total"] if full else max(100, int(o["total"] * rng.uniform(0.2, 0.6)))
                    rts = ts + int((2 + rng.expovariate(1 / 6)) * 86400) + rng.randint(0, 80000)
                    o["refund"] = {"ts": rts, "amount": amt, "full": full}
                    events.append((rts, "refund", o["refund"]))
                if not o["test"] and rng.random() < cfg.late_edit_rate:
                    events.append((ts + rng.randint(15, 120) * 86400 + rng.randint(0, 80000), "edit", {}))
            events.sort(key=lambda e: e[0])
            state = copy.deepcopy(rec)
            self.put("shopify.orders", ts, o["id"], copy.deepcopy(state))
            for ets, kind, data in events:
                state = copy.deepcopy(state)
                state["updated_at"] = iso(ets)
                if kind == "fulfil":
                    state["fulfillment_status"] = "fulfilled"
                elif kind == "cancel":
                    state["cancelled_at"] = iso(ets)
                    state["financial_status"] = "voided"
                elif kind == "refund":
                    state["financial_status"] = "refunded" if data["full"] else "partially_refunded"
                elif kind == "edit":
                    state["note"] = "Address corrected after support contact"
                    if state.get("shipping_address"):
                        state["shipping_address"] = dict(state["shipping_address"], province_code=state["shipping_address"]["province_code"])
                self.put("shopify.orders", ets, o["id"], state)
            if not o["test"] and not o["cancelled"]:
                valid.append(o)
        self.valid = valid
        # refunds (shopify side)
        n_orders = len(valid)
        for o in valid:
            r = o.get("refund")
            if not r:
                continue
            rid = 8_300_000_000_000 + o["id"] % 100_000_000_000
            r["id"] = rid
            rec = {"id": rid, "order_id": o["id"], "created_at": iso(r["ts"]), "updated_at": iso(r["ts"]),
                   "note": rng.choice(["Damaged in transit", "Wrong item sent", "Changed mind", "Arrived late", "Quality issue"]),
                   "currency": o["currency"], "transactions": [{"kind": "refund", "amount": money(r["amount"]), "status": "success"}]}
            self.put("shopify.refunds", r["ts"], rid, rec)

    def inject_duplicates(self):
        rng, cfg = self.rng, self.cfg
        dup_ids = []
        eligible = [o for o in self.valid]
        k = int(len(eligible) * cfg.duplicate_order_rate)
        for n, o in enumerate(rng.sample(eligible, k)):
            rec = copy.deepcopy(self.ent_first("shopify.orders", o["id"]))
            did = 9_100_000_000_000 + n
            rec["id"] = did
            ts = o["ts"] + rng.randint(1, 3)
            rec["created_at"] = rec["updated_at"] = iso(ts)
            rec["financial_status"] = "pending"
            for i, li in enumerate(rec["line_items"]):
                li["id"] = did * 10 + i
            self.put("shopify.orders", ts, did, rec)
            dup_ids.append(did)
        self.truth["duplicate_orders"] = len(dup_ids)
        # duplicate customers (same person, second record with messy email)
        twins = 0
        for c in rng.sample(self.customers, int(len(self.customers) * cfg.duplicate_customer_rate)):
            c["twin_id"] = 6_900_000_000_000 + c["idx"]
            twins += 1
        self.truth["duplicate_customers"] = twins

    def ent_first(self, name, id_):
        if not hasattr(self, "_first_idx"):
            self._first_idx = {}
            for e in self.ent[name]:
                self._first_idx.setdefault(e.id, e.record)
        return self._first_idx[id_]

    def emit_customers(self):
        rng, cfg = self.rng, self.cfg
        first_order = {}
        last_ts = {}
        for o in self.orders:
            if o["customer"] is not None:
                first_order.setdefault(o["customer"]["idx"], o["ts"])
        for c in self.customers:
            ts = first_order.get(c["idx"], self.day_ts(c["day"]))
            rec = self.customer_record(c, ts)
            self.put("shopify.customers", ts, c["id"], rec)
            if c["twin_id"]:
                tts = ts + rng.randint(-5 * 86400, 5 * 86400)
                self.put("shopify.customers", max(tts, self.start_ts), c["twin_id"], self.customer_record(c, max(tts, self.start_ts), twin=True))
            if rng.random() < 0.10:
                uts = ts + rng.randint(10, 300) * 86400
                upd = copy.deepcopy(rec)
                upd["accepts_marketing"] = not rec["accepts_marketing"]
                upd["updated_at"] = iso(uts)
                self.put("shopify.customers", uts, c["id"], upd)
        # sign-ups that never bought
        n = int(len(self.customers) * cfg.signup_only_rate)
        for i in range(n):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            ts = self.day_ts(rng.randrange(len(self.days)))
            cid = 6_500_000_000_000 + i
            ctry = rng.choice(["CA", "US"])
            rec = {"id": cid, "email": f"{first}.{last}{rng.randint(1, 9999)}@example.com".lower(), "first_name": first, "last_name": last,
                   "phone": None, "country": ctry, "state": rng.choice(["enabled", "disabled"]), "accepts_marketing": True,
                   "created_at": iso(ts), "updated_at": iso(ts)}
            self.put("shopify.customers", ts, cid, rec)

    # -- payments
    def build_payments(self):
        rng, cfg = self.rng, self.cfg
        valid = self.valid
        n = len(valid)
        k = lambda rate: max(2, int(n * rate))
        pool = [o for o in valid if o["ts"] < self.end_ts - 3 * 86400]
        rng.shuffle(pool)
        take = lambda cnt: [pool.pop() for _ in range(cnt)]
        missing = take(k(cfg.missing_charge_rate))
        amount_bad = take(k(cfg.amount_mismatch_rate))
        currency_bad = take(k(cfg.currency_mismatch_rate))
        refunded_pool = [o for o in pool if o.get("refund")]
        n_ref = min(k(cfg.refund_mismatch_rate), len(refunded_pool))
        refund_bad = rng.sample(refunded_pool, n_ref)
        missing_ids = {o["id"] for o in missing}
        amount_ids = {o["id"] for o in amount_bad}
        cur_ids = {o["id"] for o in currency_bad}
        refund_ids = {o["id"] for o in refund_bad}
        truth = {"missing_charge": sorted(missing_ids), "amount_mismatch": sorted(amount_ids),
                 "currency_mismatch": sorted(cur_ids), "refund_mismatch": sorted(refund_ids), "orphan_charge": []}
        ledger: dict[tuple[date, str], int] = {}
        for o in valid:
            if o["id"] in missing_ids:
                continue
            ts = o["ts"] + rng.randint(2, 9)
            amount, cur = o["total"], o["currency"].lower()
            if o["id"] in amount_ids:
                amount -= rng.choice([150, 300, 500, 1000, 2500]) if amount > 3000 else 100
            if o["id"] in cur_ids:
                cur = "usd" if cur == "cad" else "cad"
            self.add_charge(o, ts, amount, cur, o["id"] in refund_ids, ledger)
        # orphan charges: payment taken, no matching order
        for i in range(k(cfg.orphan_charge_rate)):
            ts = self.start_ts + rng.randrange(0, (self.end_ts - self.start_ts) - 4 * 86400)
            fake_oid = 4_800_000_000_000 + i
            fake = {"id": fake_oid, "ts": ts, "currency": rng.choice(["CAD", "USD"]), "total": rng.randint(2500, 18000), "refund": None,
                    "rec": {"order_number": 0, "email": f"orphan{i}@example.com"}}
            cid = self.add_charge(fake, ts, fake["total"], fake["currency"].lower(), False, ledger, order_exists=False)
            truth["orphan_charge"].append(cid)
        self.truth.update(truth)
        # daily payouts per currency
        for (day, cur), amount in sorted(ledger.items()):
            created = ts_of(datetime(day.year, day.month, day.day, tzinfo=UTC)) + 86400 + 1800
            pid = self.stripe_id("po")
            rec = {"id": pid, "object": "payout", "created": created, "updated": created,
                   "arrival_date": created + 86400, "amount": amount, "currency": cur, "status": "paid"}
            self.put("stripe.payouts", created, pid, rec)

    def add_charge(self, o, ts, amount, cur, refund_bad, ledger, order_exists=True):
        rng = self.rng
        rate = 0.029 if cur == "cad" else 0.039
        fee = int(round(amount * rate)) + 30
        cid = self.stripe_id("ch")
        rec = {"id": cid, "object": "charge", "created": ts, "updated": ts, "amount": amount, "amount_refunded": 0,
               "currency": cur, "status": "succeeded", "paid": True, "refunded": False,
               "description": f"Order #{o['rec']['order_number']}" if order_exists else "Online payment",
               "receipt_email": o["rec"]["email"] if o["rec"].get("email") else None,
               "payment_method_details": {"type": "card", "card": {"brand": rng.choice(["visa", "mastercard", "amex"])}},
               "metadata": {"order_id": str(o["id"]), "order_number": str(o["rec"]["order_number"])},
               "balance_transaction": {"id": self.stripe_id("txn"), "fee": fee, "net": amount - fee, "currency": cur}}
        self.put("stripe.charges", ts, cid, rec)
        day = datetime.fromtimestamp(ts, UTC).date()
        key = (day, cur)
        ledger[key] = ledger.get(key, 0) + amount - fee
        r = o.get("refund")
        if r and ts <= r["ts"]:
            r_amount = r["amount"]
            skip = False
            if refund_bad:
                if rng.random() < 0.5:
                    skip = True
                else:
                    r_amount = max(50, int(r_amount * rng.uniform(0.5, 0.9)))
            if not skip and r["ts"] <= self.end_ts:
                rid = self.stripe_id("re")
                self.put("stripe.refunds", r["ts"], rid, {"id": rid, "object": "refund", "charge": cid, "created": r["ts"], "updated": r["ts"],
                                                          "amount": r_amount, "currency": cur, "reason": "requested_by_customer", "status": "succeeded"})
                upd = dict(rec, updated=r["ts"], amount_refunded=r_amount, refunded=r_amount >= amount)
                self.put("stripe.charges", r["ts"], cid, upd)
                rday = datetime.fromtimestamp(r["ts"], UTC).date()
                ledger[(rday, cur)] = ledger.get((rday, cur), 0) - r_amount
        return cid


def generate(cfg: GenConfig | None = None) -> Dataset:
    cfg = cfg or GenConfig()
    b = Builder(cfg)
    b.build_products()
    b.build_customers()
    b.build_orders()
    b.build_lifecycle()
    b.inject_duplicates()
    b.emit_customers()
    b.build_payments()
    b.truth["test_orders"] = sum(1 for o in b.orders if o["test"])
    b.truth["cancelled_orders"] = sum(1 for o in b.orders if o.get("cancelled"))
    b.truth["valid_orders"] = len(b.valid)
    ds = Dataset(cfg, b.ent, b.truth)
    ds.stats = {k: len(v) for k, v in ds.entities.items()}
    ds.stats["distinct_ids"] = {k: len(v) for k, v in ds.by_id.items()}
    return ds


def visible_slice(ds: Dataset, name: str, since_ts: int, as_of: int, after: tuple | None = None):
    """Yield entries visible at `as_of` with updated_at >= since_ts, in (ts, id) order after `after`."""
    entries, keys = ds.entities[name], ds.keys[name]
    lo = bisect.bisect_left(keys, (since_ts, ""))
    if after is not None:
        lo = max(lo, bisect.bisect_right(keys, after))
    for i in range(lo, len(entries)):
        e = entries[i]
        if e.ts > as_of:
            return
        if e.next_ts is not None and e.next_ts <= as_of:
            continue
        yield e
