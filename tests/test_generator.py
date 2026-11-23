from datetime import date

from mock_sources.generator import GenConfig, black_friday, generate, season
from tests.conftest import SMALL


def test_same_seed_gives_same_data():
    a, b = generate(SMALL), generate(SMALL)
    assert a.truth == b.truth
    assert [e.id for e in a.entities["stripe.charges"]] == [e.id for e in b.entities["stripe.charges"]]


def test_different_seed_changes_data():
    other = generate(GenConfig(seed=8, start=SMALL.start, end=SMALL.end, n_customers=SMALL.n_customers))
    assert other.truth != generate(SMALL).truth


def test_black_friday_is_the_busiest_day():
    bf = black_friday(2025)
    assert bf == date(2025, 11, 28)
    normal = [season(date(2025, 11, d)) for d in (4, 5, 11, 12, 18, 19)]
    assert season(bf) > 2.5 * max(normal)
    assert season(date(2025, 11, 1) .replace(day=1)) > 0


def test_injected_problems_are_present_and_recorded(small_ds):
    t = small_ds.truth
    for key in ("missing_charge", "orphan_charge", "amount_mismatch", "currency_mismatch", "refund_mismatch"):
        assert len(t[key]) >= 2
    orders = {e.id: e.record for e in small_ds.entities["shopify.orders"]}
    numbers = [r["order_number"] for r in orders.values()]
    assert len(numbers) - len(set(numbers)) == t["duplicate_orders"]
    assert sum(1 for r in orders.values() if r["test"]) == t["test_orders"]


def test_data_is_messy_on_purpose(small_ds):
    emails = [e.record["email"] for e in small_ds.entities["shopify.customers"] if e.record["email"]]
    assert any(m != m.strip().lower() for m in emails)
    currencies = {e.record["currency"] for e in small_ds.entities["shopify.orders"]}
    assert {"CAD", "USD"} <= {c.strip().upper() for c in currencies} and len(currencies) > 2
    assert any(e.record["customer"] is None for e in small_ds.entities["shopify.orders"])


def test_records_have_multiple_versions_with_increasing_updated_at(small_ds):
    versions = small_ds.by_id["shopify.orders"]
    multi = [v for v in versions.values() if len(v) > 1]
    assert len(multi) > len(versions) * 0.5
    for v in multi:
        assert [e.ts for e in v] == sorted(e.ts for e in v)
