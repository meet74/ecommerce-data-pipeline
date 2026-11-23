"""Incremental loading: watermark, late-arriving updates, idempotent re-runs."""
from datetime import datetime, timedelta, timezone

from mock_sources.generator import iso, visible_slice
from pipeline import ingest
from pipeline.config import Settings
from pipeline.warehouse import DuckDBWarehouse

T0 = "2025-03-15T23:59:59Z"
T1 = "2025-03-16T23:59:59Z"


def epoch(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def visible(ds, name, as_of_iso, since_ts=0):
    return list(visible_slice(ds, name, since_ts, epoch(as_of_iso)))


def by_name(results):
    return {r["entity"]: r for r in results}


def test_second_run_reads_only_changed_rows(settings, server, small_ds):
    ds = small_ds
    server.set_as_of(T0)
    with DuckDBWarehouse(":memory:") as wh:
        first = by_name(ingest.extract_load(wh, settings, "run1"))
        assert all(r["status"] == "success" for r in first.values())
        assert first["shopify.orders"]["rows_read"] == len({e.id for e in visible(ds, "shopify.orders", T0)})

        # the watermark is the newest updated_at that was loaded
        wm = wh.scalar("SELECT high_watermark FROM meta.watermarks WHERE source='shopify' AND entity='orders'")
        newest = max(e.ts for e in visible(ds, "shopify.orders", T0))
        assert wm == datetime.fromtimestamp(newest, timezone.utc).replace(tzinfo=None)

        server.set_as_of(T1)
        second = by_name(ingest.extract_load(wh, settings, "run2"))
        o = second["shopify.orders"]
        since = newest - settings.lookback_seconds
        window = visible(ds, "shopify.orders", T1, since)
        seen_before = {e.id for e in visible(ds, "shopify.orders", T0)}
        assert o["rows_read"] == len({e.id for e in window})
        assert o["rows_read"] < 0.1 * first["shopify.orders"]["rows_read"]
        assert o["inserted"] == len({e.id for e in window} - seen_before)
        assert o["updated"] == len({e.id for e in window} & seen_before) - o["unchanged"]
        assert o["updated"] > 0, "fixture should contain updates to orders that were already loaded"

        # nothing changed at the source: a third run rewrites nothing
        third = by_name(ingest.extract_load(wh, settings, "run3"))
        assert all(r["rows_written"] == 0 for r in third.values())
        assert third["shopify.orders"]["rows_read"] == third["shopify.orders"]["unchanged"]

        incremental = snapshot(wh)

    # the incrementally built warehouse equals a one-shot load at the same point in time
    with DuckDBWarehouse(":memory:") as fresh:
        ingest.extract_load(fresh, settings, "full")
        assert snapshot(fresh) == incremental


def snapshot(wh):
    out = {}
    for t in ("shopify_orders", "shopify_order_lines", "shopify_customers", "shopify_products", "shopify_refunds",
              "stripe_charges", "stripe_refunds", "stripe_payouts"):
        col = "_row_hash" if t != "shopify_order_lines" else "id"
        out[t] = wh.query(f"SELECT id, {col} FROM raw.{t} ORDER BY id")
    return out


def test_late_update_to_an_old_order_is_picked_up(settings, server, small_ds):
    """An order edited weeks after it was placed: created_at filtering would miss it, updated_at does not."""
    ds = small_ds
    late = None
    for e in ds.entities["shopify.orders"]:
        age_days = (e.ts - epoch(e.record["created_at"])) / 86400
        if age_days > 20 and e.next_ts is None and e.record["note"]:
            late = e
            break
    assert late is not None
    before = iso(late.ts - 3600)
    server.set_as_of(before)
    with DuckDBWarehouse(":memory:") as wh:
        ingest.extract_load(wh, settings, "r1", entities=["orders"])
        assert wh.scalar("SELECT note FROM raw.shopify_orders WHERE id = ?", [late.id]) is None
        server.set_as_of(iso(late.ts + 60))
        res = by_name(ingest.extract_load(wh, settings, "r2", entities=["orders"]))["shopify.orders"]
        assert wh.scalar("SELECT note FROM raw.shopify_orders WHERE id = ?", [late.id]) == late.record["note"]
        assert res["updated"] >= 1


def test_failed_extract_does_not_move_the_watermark(settings, server):
    server.set_as_of(T0)
    with DuckDBWarehouse(":memory:") as wh:
        wh.init_schema()
        server.faults.error_rate = 1.0          # every request fails
        settings.max_retries = 2
        res = by_name(ingest.extract_load(wh, settings, "bad", entities=["orders"]))["shopify.orders"]
        assert res["status"] == "failed"
        assert wh.scalar("SELECT COUNT(*) FROM meta.watermarks") == 0
        assert wh.scalar("SELECT status FROM meta.run_log WHERE run_id = 'bad'") == "failed"
        server.faults.error_rate = 0.0
        ok = by_name(ingest.extract_load(wh, settings, "good", entities=["orders"]))["shopify.orders"]
        assert ok["status"] == "success" and ok["inserted"] > 0
