from datetime import datetime

from mock_sources.generator import visible_slice
from pipeline import sources
from pipeline.client import ApiClient


def client_for(settings):
    return ApiClient({"X-Shopify-Access-Token": settings.shopify_token, "Authorization": f"Bearer {settings.stripe_key}"},
                     max_retries=8, backoff_base=0.01)


def visible_ids(ds, name, as_of):
    return [e.id for e in visible_slice(ds, name, 0, as_of)]


def test_shopify_cursor_pagination_returns_every_record_once(settings, server, small_ds):
    pages = list(sources.shopify_pages(client_for(settings), settings.shopify_base_url, "orders", None, 100))
    ids = [r["id"] for page in pages for r in page]
    assert len(pages) > 3
    assert len(ids) == len(set(ids))
    assert sorted(ids) == sorted(visible_ids(small_ds, "shopify.orders", small_ds.end_ts()))


def test_stripe_pagination_returns_every_record_once(settings, server, small_ds):
    pages = list(sources.stripe_pages(client_for(settings), settings.stripe_base_url, "charges", None, 40))
    ids = [r["id"] for page in pages for r in page]
    assert len(pages) > 3
    assert len(ids) == len(set(ids))
    assert sorted(ids) == sorted(visible_ids(small_ds, "stripe.charges", small_ds.end_ts()))


def test_updated_filter_only_returns_newer_versions(settings, server, small_ds):
    since = datetime(2025, 3, 20)
    pages = list(sources.shopify_pages(client_for(settings), settings.shopify_base_url, "orders", since, 100))
    rows = [r for p in pages for r in p]
    assert rows and all(r["updated_at"] >= "2025-03-20T00:00:00Z" for r in rows)


def test_pagination_survives_rate_limits_and_server_errors(settings, server, small_ds):
    server.faults.rate_limit_per_sec = 4
    server.faults.fail_next = 3
    client = client_for(settings)
    pages = list(sources.shopify_pages(client, settings.shopify_base_url, "orders", None, 25))
    ids = [r["id"] for p in pages for r in p]
    assert sorted(ids) == sorted(visible_ids(small_ds, "shopify.orders", small_ds.end_ts()))
    assert client.stats["rate_limited"] > 0
    assert client.stats["server_errors"] >= 3
